#include "CivHostCrash.h"
#include "CivHostHooks.h"
#include "CivHostPath.h"
#include "CivHostRuntime.h"
#include "CivHostValues.h"

#include <windows.h>
#include <tlhelp32.h>
#include <intrin.h>
#include <malloc.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

namespace
{
	struct PendingHook
	{
		int id;
		int kind;
		void* fn;
	};

	struct KeptPlugin
	{
		std::string path;
		std::string name;
	};

	struct PossibleConflict
	{
		int other;
		int hookPoint;
		int handHook;
		bool pluginReplaces;
	};

	std::vector<CivPluginRecord> s_plugins;
	std::vector<PendingHook> s_pending;
	std::vector<PossibleConflict> s_possibleConflicts;
	std::vector<KeptPlugin> s_kept;
	CivFilePairs s_useBoth;
	int s_loadingPlugin = -1;
	const CivPluginInfo* s_loadingInfo = 0;
	bool s_loadingConflict = false;
	CivSaveDataFn s_pendingSave = 0;
	CivLoadDataFn s_pendingLoad = 0;
	std::string* s_saving = 0;
	// A new one for every call of a save function, so a saving kept from an earlier call writes nowhere.
	unsigned int s_saveToken = 0;
	bool s_strayWriteLogged = false;
	volatile LONG s_pluginCallDepth = 0;
	bool* s_originalCalled = 0;
	CivHostLogSink s_logSink = 0;
	CivHostFaultSink s_faultSink = 0;
	CivHostLuaPusher s_luaPusher = 0;
	unsigned int s_lastSerial = 0;

	void Log(const char* format, ...)
	{
		char line[1024];
		va_list args;
		va_start(args, format);
		_vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
		va_end(args);
		if (s_logSink)
			s_logSink(line);
		OutputDebugStringA(line);
		OutputDebugStringA("\n");
	}

	std::string Format(const char* format, ...)
	{
		char text[1024];
		va_list args;
		va_start(args, format);
		_vsnprintf_s(text, sizeof(text), _TRUNCATE, format, args);
		va_end(args);
		return text;
	}

	const char* HookName(int id)
	{
		if (id >= 0 && id < g_CivHookPointCount)
			return g_CivHookPointNames[id];
		return id >= g_CivHookPointCount ? CivHandHookName(id - g_CivHookPointCount) : "?";
	}

	CivHookPoint& Point(int id)
	{
		return id < g_CivHookPointCount ? g_CivHookPoints[id] : g_CivHandHookPoints[id - g_CivHookPointCount];
	}

	// Players see the name alone, unless an overload shares it and only the parameters tell them apart.
	std::string ShortHookName(int id)
	{
		const std::string full = HookName(id);
		const size_t open = full.find('(');
		const std::string name = full.substr(0, open);
		if (open == std::string::npos || name.empty())
			return full;
		for (int i = 0; i < g_CivHookPointCount; ++i)
			if (i != id && strncmp(g_CivHookPointNames[i], name.c_str(), name.size()) == 0 && g_CivHookPointNames[i][name.size()] == '(')
				return full;
		return name + "(...)";
	}

	bool Alive(int plugin)
	{
		return plugin >= 0 && plugin < (int)s_plugins.size() && !s_plugins[plugin].quarantined;
	}

	// A plugin registers and logs from its entry point, before the host has copied its name.
	const char* DisplayName(int plugin)
	{
		if (plugin < 0 || plugin >= (int)s_plugins.size())
			return "?";
		if (plugin == s_loadingPlugin && s_loadingInfo->name && *s_loadingInfo->name)
			return s_loadingInfo->name;
		return s_plugins[plugin].name.c_str();
	}

	int FaultFilter(unsigned int code, const EXCEPTION_POINTERS* info, const void* owner)
	{
		switch (code)
		{
		case EXCEPTION_ACCESS_VIOLATION:
		case EXCEPTION_ARRAY_BOUNDS_EXCEEDED:
		case EXCEPTION_FLT_DIVIDE_BY_ZERO:
		case EXCEPTION_FLT_INVALID_OPERATION:
		case EXCEPTION_ILLEGAL_INSTRUCTION:
		case EXCEPTION_IN_PAGE_ERROR:
		case EXCEPTION_INT_DIVIDE_BY_ZERO:
		case EXCEPTION_INT_OVERFLOW:
		case EXCEPTION_PRIV_INSTRUCTION:
		case EXCEPTION_STACK_OVERFLOW:
		case 0xE06D7363: // a C++ exception escaping the plugin
			CivCrashRecord(code, info, owner);
			return EXCEPTION_EXECUTE_HANDLER;
		}
		return EXCEPTION_CONTINUE_SEARCH;
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	bool GuardedCall(CivHookThunk thunk, void* ctx, unsigned int* code)
	{
		bool ran = true;
		InterlockedIncrement(&s_pluginCallDepth);
		__try
		{
			__try
			{
				thunk(ctx);
			}
			__except (FaultFilter(*code = GetExceptionCode(), GetExceptionInformation(), code))
			{
				ran = false;
			}
		}
		__finally
		{
			InterlockedDecrement(&s_pluginCallDepth);
		}
		if (!ran && *code == EXCEPTION_STACK_OVERFLOW)
			_resetstkoflw();
		return ran;
	}

	void LogCrash(const void* owner)
	{
		const std::vector<std::string> lines = CivCrashReport(owner);
		for (size_t i = 0; i < lines.size(); ++i)
			Log("%s", lines[i].c_str());
	}

	// The player hears about a plugin's first fault only; later ones are logged.
	void Quarantine(int plugin, bool shuttingDown, const char* where, const unsigned int* code)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		char problem[512];
		_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Faulted (code 0x%08X) in %s.", *code, where);
		Log("Plugin %s: %s", rec.name.c_str(), problem);
		LogCrash(code);
		if (rec.quarantined)
			return;
		rec.quarantined = true;
		rec.problems.push_back(problem);
		if (s_faultSink)
			s_faultSink(plugin, rec.name.c_str(), shuttingDown, *code);
	}

	bool CallPlugin(const CivHookEntry* e, int hookId, CivHookThunk thunk, void* ctx)
	{
		static_cast<CivHookCtx*>(ctx)->fn = e->fn;
		unsigned int code = 0;
		if (GuardedCall(thunk, ctx, &code))
			return true;
		Quarantine(e->plugin, false, HookName(hookId), &code);
		return false;
	}

	bool PendingReplace(int hookId)
	{
		for (size_t i = 0; i < s_pending.size(); ++i)
			if (s_pending[i].id == hookId && s_pending[i].kind == CIV_HOOK_REPLACE)
				return true;
		return false;
	}

	bool HasText(const std::vector<std::string>& texts, const std::string& text)
	{
		for (size_t i = 0; i < texts.size(); ++i)
			if (texts[i] == text)
				return true;
		return false;
	}

	bool UseBoth(const std::string& a, const std::string& b)
	{
		for (size_t i = 0; i < s_useBoth.size(); ++i)
		{
			const CivFilePair& pair = s_useBoth[i];
			if ((CivSameText(pair.first, a) && CivSameText(pair.second, b)) || (CivSameText(pair.first, b) && CivSameText(pair.second, a)))
				return true;
		}
		return false;
	}

	void NotePossibleConflict(int other, int hookPoint, int handHook, bool pluginReplaces)
	{
		PossibleConflict conflict = { other, hookPoint, handHook, pluginReplaces };
		s_possibleConflicts.push_back(conflict);
	}

	void AddOnce(std::vector<std::string>& texts, const std::string& text)
	{
		if (!HasText(texts, text))
			texts.push_back(text);
	}

	void AddAndLog(int plugin, std::vector<std::string>& texts, const std::string& text)
	{
		if (HasText(texts, text))
			return;
		texts.push_back(text);
		Log("Plugin %s: %s", s_plugins[plugin].name.c_str(), text.c_str());
	}

	// A replacement that never calls the original skips the hand-placed hooks inside it, so the plugin lower in the list
	// is held back unless the player chose to use both. True when it is held back.
	bool ReportPossibleConflicts(int plugin)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		bool heldBack = false;
		for (size_t i = 0; i < s_possibleConflicts.size(); ++i)
		{
			const PossibleConflict& c = s_possibleConflicts[i];
			const std::string otherFile = CivFileName(s_plugins[c.other].path);
			const char* otherName = s_plugins[c.other].name.c_str();
			const std::string function = ShortHookName(c.hookPoint);
			const char* hook = CivHandHookName(c.handHook);
			AddOnce(rec.conflictsWith, otherFile);
			if (UseBoth(CivFileName(rec.path), otherFile))
			{
				AddAndLog(plugin, rec.notes, Format("You chose to use this plugin with %s anyway, although one of them replaces %s, which runs the %s hook the other uses.",
					otherName, function.c_str(), hook));
				continue;
			}
			heldBack = true;
			if (c.pluginReplaces)
				AddAndLog(plugin, rec.problems, Format("This plugin replaces %s, which runs the %s hook that %s, higher in the list, uses. If the version in this plugin does not run the game's own, %s never gets that hook, so this plugin was held back. If you know the two work together, check Use both anyway.",
					function.c_str(), hook, otherName, otherName));
			else
				AddAndLog(plugin, rec.problems, Format("%s, higher in the list, replaces %s, which runs the %s hook this plugin uses. If the version in %s does not run the game's own, this plugin never gets that hook, so it was held back. If you know the two work together, check Use both anyway.",
					otherName, function.c_str(), hook, otherName));
		}
		s_possibleConflicts.clear();
		return heldBack;
	}

	void NoteHandHookUsers(int hookId)
	{
		for (int i = 0; i < g_CivHandHookSiteCount; ++i)
		{
			const CivHandHookSite& site = g_CivHandHookSites[i];
			if (site.hookPoint != hookId)
				continue;
			for (const CivHookEntry* e = g_CivHandHookPoints[site.handHook].before; e; e = e->next)
				NotePossibleConflict(e->plugin, hookId, site.handHook, true);
		}
	}

	void NoteReplacements(int handHook)
	{
		for (int i = 0; i < g_CivHandHookSiteCount; ++i)
		{
			const CivHandHookSite& site = g_CivHandHookSites[i];
			const CivHookEntry* replacement = g_CivHookPoints[site.hookPoint].replace;
			if (site.handHook == handHook && replacement)
				NotePossibleConflict(replacement->plugin, site.hookPoint, handHook, false);
		}
	}

	// A plugin kept in memory after a crash has the index -1 too.
	bool InEntryOf(int plugin)
	{
		return s_loadingPlugin >= 0 && plugin == s_loadingPlugin;
	}

	int RegisterHandHook(int plugin, int handHook, void* fn)
	{
		if (!InEntryOf(plugin))
			return CIV_HOOK_NOT_ALLOWED;
		if (handHook < 0 || handHook >= g_CivHandHookCount || !fn)
			return CIV_HOOK_BAD_ID;
		NoteReplacements(handHook);
		PendingHook p = { CivHandHookId(handHook), CIV_HOOK_BEFORE, fn };
		s_pending.push_back(p);
		return CIV_HOOK_OK;
	}

	int RegisterHook(int plugin, int hookId, int kind, void* fn)
	{
		if (!InEntryOf(plugin))
			return CIV_HOOK_NOT_ALLOWED;
		if (hookId < 0 || hookId >= g_CivHookPointCount || !fn)
			return CIV_HOOK_BAD_ID;
		if (!g_CivHookLive[hookId])
		{
			Log("Plugin %s asked for hook %d (%s), which this Bazaar no longer has: the function changed or is gone. Rebuild the plugin with the current SDK.",
				DisplayName(plugin), hookId, g_CivHookPointNames[hookId]);
			return CIV_HOOK_BAD_ID;
		}
		if (kind < CIV_HOOK_BEFORE || kind > CIV_HOOK_REPLACE)
			return CIV_HOOK_BAD_KIND;
		if (kind == CIV_HOOK_REPLACE)
		{
			std::string problem;
			if (const CivHookEntry* taken = g_CivHookPoints[hookId].replace)
			{
				// Its other hooks may rely on the replacement it lost, so the whole plugin stays off.
				s_loadingConflict = true;
				const char* owner = s_plugins[taken->plugin].name.c_str();
				problem = Format("%s, higher in the list, already replaces %s, and only one plugin can replace a function. To use this one instead, move it above %s.",
					owner, ShortHookName(hookId).c_str(), owner);
			}
			else if (PendingReplace(hookId))
				problem = Format("Its replacement of %s was refused: this plugin already replaces it.", ShortHookName(hookId).c_str());
			if (!problem.empty())
			{
				s_plugins[plugin].problems.push_back(problem);
				Log("Plugin %s: %s", DisplayName(plugin), problem.c_str());
				return CIV_HOOK_REPLACE_TAKEN;
			}
			NoteHandHookUsers(hookId);
		}
		PendingHook p = { hookId, kind, fn };
		s_pending.push_back(p);
		return CIV_HOOK_OK;
	}

	int RegisterSaveData(int plugin, CivSaveDataFn save, CivLoadDataFn load)
	{
		if (!InEntryOf(plugin) || s_pendingSave)
			return CIV_HOOK_NOT_ALLOWED;
		if (!save || !load)
			return CIV_HOOK_BAD_ID;
		s_pendingSave = save;
		s_pendingLoad = load;
		return CIV_HOOK_OK;
	}

	void* CurrentSaveToken()
	{
		return s_saving ? reinterpret_cast<void*>(static_cast<UINT_PTR>(s_saveToken)) : 0;
	}

	int DeclareValue(int plugin, int kind, int type, const char* name, int flags, const void* start)
	{
		std::string problem;
		int value = -1;
		if (InEntryOf(plugin))
			value = CivValuesDeclare(plugin, kind, type, name, flags, start, &problem);
		else
			problem = "it was declared outside the plugin's entry function";
		if (value < 0)
			Log("Plugin %s: its value %s was refused because %s.", DisplayName(plugin), name ? name : "", problem.c_str());
		return value;
	}

	void CommitPending(int plugin)
	{
		CivValuesCommitPending(s_plugins[plugin].modId, s_plugins[plugin].pluginId);
		s_plugins[plugin].saveFn = s_pendingSave;
		s_plugins[plugin].loadFn = s_pendingLoad;
		s_pendingSave = 0;
		s_pendingLoad = 0;
		for (size_t i = 0; i < s_pending.size(); ++i)
		{
			const PendingHook& p = s_pending[i];
			CivHookPoint& hp = Point(p.id);
			CivHookEntry* e = new CivHookEntry;
			e->fn = p.fn;
			e->plugin = plugin;
			e->next = 0;
			e->loggedSkippedOriginal = false;
			if (p.kind == CIV_HOOK_BEFORE)
			{
				CivHookEntry** tail = &hp.before;
				while (*tail)
					tail = &(*tail)->next;
				*tail = e;
			}
			else if (p.kind == CIV_HOOK_AFTER)
			{
				// After-hooks run in reverse load order, so each plugin's goes in front.
				e->next = hp.after;
				hp.after = e;
			}
			else
			{
				hp.replace = e;
			}
			if (p.id < g_CivHookPointCount)
				g_CivHookActive[p.id] = 1;
		}
		s_pending.clear();
	}

	void DiscardPending()
	{
		s_pending.clear();
		s_possibleConflicts.clear();
		s_pendingSave = 0;
		s_pendingLoad = 0;
		CivValuesDiscardPending();
	}

	void PluginLog(int plugin, const char* message)
	{
		Log("[%s] %s", DisplayName(plugin), message ? message : "");
	}

	int PluginWithCode(const void* address)
	{
		HMODULE module = 0;
		GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)address, &module);
		for (size_t i = 0; i < s_plugins.size(); ++i)
			if (module && s_plugins[i].module == module)
				return (int)i;
		return -1;
	}

	void WriteSaveData(void* saving, const void* data, int size)
	{
		if (saving && saving == CurrentSaveToken())
		{
			if (data && size > 0)
				s_saving->append(static_cast<const char*>(data), size);
			return;
		}
		if (s_strayWriteLogged)
			return;
		s_strayWriteLogged = true;
		const int plugin = PluginWithCode(_ReturnAddress());
		Log("Plugin %s wrote save data outside its save function, or with the saving of an earlier save, so it was not saved. This is logged only once.",
			plugin < 0 ? "?" : DisplayName(plugin));
	}

	// Serial 0 belongs to no plugin, so a function pushed with a wrong index refuses to run rather than unbalancing the
	// plugin's Lua stack, or getting another plugin turned off when it crashes.
	void PushLuaFunction(int plugin, lua_State* L, CivLuaFunction fn)
	{
		const int owner = PluginWithCode((const void*)fn);
		const bool own = plugin >= 0 && plugin < (int)s_plugins.size() && (owner < 0 || owner == plugin);
		if (!own)
			Log("Plugin %s pushed a Lua function with plugin index %d, which is not its own, so calling it raises a Lua error.",
				owner < 0 ? "?" : DisplayName(owner), plugin);
		if (s_luaPusher)
			s_luaPusher(L, own ? s_plugins[plugin].serial : 0, fn);
	}

	struct EntryCall
	{
		CivPluginEntryFn entry;
		const CivHostInfo* host;
		CivPluginInfo* info;
		bool accepted;
	};

	void EntryThunk(void* p)
	{
		EntryCall& c = *static_cast<EntryCall*>(p);
		c.accepted = c.entry(c.host, c.info);
	}

	// A plugin's name and version may point anywhere, even after its entry function crashed partway.
	// No C++ objects may live in this frame, or __try is not allowed.
	bool CopyPluginText(const char* text, char* out, size_t size)
	{
		out[0] = 0;
		__try
		{
			if (text)
				strncpy_s(out, size, text, _TRUNCATE);
			return true;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
			out[0] = 0;
			return false;
		}
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	bool GuardedEntry(EntryCall* call, unsigned int* code)
	{
		bool ran = false;
		s_loadingPlugin = call->host->pluginIndex;
		s_loadingInfo = call->info;
		__try
		{
			ran = GuardedCall(&EntryThunk, call, code);
		}
		__finally
		{
			s_loadingPlugin = -1;
			s_loadingInfo = 0;
		}
		return ran;
	}

	void ShutdownThunk(void* p)
	{
		(*static_cast<CivPluginShutdownFn*>(p))();
	}

	bool ShutDownCleanly(int plugin)
	{
		const CivPluginRecord& rec = s_plugins[plugin];
		CivPluginShutdownFn shutdown = (CivPluginShutdownFn)GetProcAddress((HMODULE)rec.module, CIV_PLUGIN_SHUTDOWN_NAME);
		unsigned int code = 0;
		if (!shutdown || GuardedCall(&ShutdownThunk, &shutdown, &code))
			return true;
		Quarantine(plugin, true, "its shutdown function", &code);
		return false;
	}

	typedef LONG(WINAPI* QueryThreadFn)(HANDLE thread, int infoClass, void* info, ULONG size, ULONG* written);

	const int kThreadBasicInformation = 0;
	const int kThreadStartAddress = 9;

	struct ThreadBasicInfo
	{
		LONG exitStatus;
		NT_TIB* tib;
		void* clientProcess;
		void* clientThread;
		ULONG_PTR affinity;
		LONG priority;
		LONG basePriority;
	};

	// A stack value counts only if it could be a return address into the DLL: the bytes before it are one of
	// the x86 CALL forms. Ordinary numbers that merely fall inside the DLL's address range then rarely match.
	bool IsReturnInto(DWORD value, const BYTE* start, const BYTE* end)
	{
		const BYTE* p = reinterpret_cast<const BYTE*>(value);
		if (p < start + 7 || p >= end)
			return false;
		if (p[-5] == 0xE8)
			return true;
		for (int length = 2; length <= 7; ++length)
			if (p[-length] == 0xFF && (p[1 - length] & 0x38) == 0x10)
				return true;
		return false;
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	bool StackPointsInto(const NT_TIB* tib, DWORD esp, const BYTE* start, const BYTE* end)
	{
		__try
		{
			const DWORD* top = static_cast<const DWORD*>(tib->StackBase);
			for (const DWORD* p = reinterpret_cast<const DWORD*>(esp); p < top; ++p)
				if (IsReturnInto(*p, start, end))
					return true;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
		}
		return false;
	}

	// The thread is suspended only while its registers and stack are read, which takes no locks, so it
	// cannot be holding anything this thread then waits for. Anything that cannot be checked counts as
	// inside: keeping a DLL loaded is the safe mistake.
	bool ThreadIsInside(DWORD id, const BYTE* start, const BYTE* end, QueryThreadFn query)
	{
		HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, id);
		if (!thread)
			return GetLastError() != ERROR_INVALID_PARAMETER; // that error means the thread has already ended
		bool inside = true;
		DWORD exitCode = 0;
		const BYTE* entry = 0;
		ThreadBasicInfo info = {};
		if (GetExitCodeThread(thread, &exitCode) && exitCode != STILL_ACTIVE)
			inside = false;
		else if (query(thread, kThreadStartAddress, &entry, sizeof(entry), 0) == 0 && entry >= start && entry < end)
			inside = true;
		else if (query(thread, kThreadBasicInformation, &info, sizeof(info), 0) == 0 && SuspendThread(thread) != (DWORD)-1)
		{
			CONTEXT context;
			context.ContextFlags = CONTEXT_CONTROL;
			if (GetThreadContext(thread, &context))
			{
				const BYTE* eip = reinterpret_cast<const BYTE*>(context.Eip);
				inside = (eip >= start && eip < end) || StackPointsInto(info.tib, context.Esp, start, end);
			}
			ResumeThread(thread);
		}
		CloseHandle(thread);
		return inside;
	}

	// A thread the plugin left running, even one only waiting, would crash once the DLL is gone. A thread
	// started through the C runtime begins outside the DLL, so its stack is searched as well. A thread
	// started after the snapshot is not seen; by then the plugin's own shutdown has already run.
	bool ThreadStillInside(HMODULE module)
	{
		QueryThreadFn query = (QueryThreadFn)GetProcAddress(GetModuleHandleA("ntdll.dll"), "NtQueryInformationThread");
		if (!query)
			return true;
		HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
		if (snapshot == INVALID_HANDLE_VALUE)
			return true;
		const BYTE* start = reinterpret_cast<const BYTE*>(module);
		const IMAGE_NT_HEADERS* headers = reinterpret_cast<const IMAGE_NT_HEADERS*>(
			start + reinterpret_cast<const IMAGE_DOS_HEADER*>(start)->e_lfanew);
		const BYTE* end = start + headers->OptionalHeader.SizeOfImage;
		THREADENTRY32 entry;
		entry.dwSize = sizeof(entry);
		bool inside = false;
		for (BOOL more = Thread32First(snapshot, &entry); more && !inside; more = Thread32Next(snapshot, &entry))
			if (entry.th32OwnerProcessID == GetCurrentProcessId() && entry.th32ThreadID != GetCurrentThreadId())
				inside = ThreadIsInside(entry.th32ThreadID, start, end, query);
		CloseHandle(snapshot);
		return inside;
	}

	// A plugin whose shutdown faulted, or that still has a thread inside its DLL, may still have code
	// referenced elsewhere, so the DLL stays loaded and the plugin stays refused until Civilization V restarts.
	void Unload(int plugin)
	{
		const bool clean = ShutDownCleanly(plugin);
		CivPluginRecord& rec = s_plugins[plugin];
		const bool threadLeft = clean && ThreadStillInside((HMODULE)rec.module);
		if (clean && !threadLeft)
		{
			CivCrashForgetModule((HMODULE)rec.module);
			FreeLibrary((HMODULE)rec.module);
			delete rec.host;
			Log("Plugin %s unloaded.", rec.name.c_str());
		}
		else
		{
			rec.host->pluginIndex = -1;
			KeptPlugin kept = { rec.path, rec.name };
			s_kept.push_back(kept);
			if (threadLeft)
				Log("Plugin %s stays in memory because one of its threads is still running.", rec.name.c_str());
			else
				Log("Plugin %s stays in memory because its shutdown function faulted.", rec.name.c_str());
		}
		rec.module = 0;
		rec.host = 0;
	}

	void Refuse(CivPluginRecord& rec, CivPluginStatus status, const std::string& problem)
	{
		rec.status = status;
		rec.problems.push_back(problem);
		Log("Plugin %s: %s", rec.name.c_str(), problem.c_str());
	}

	bool RefusedForSaveKey(int plugin)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		if (!s_pendingSave && !CivValuesPending())
			return false;
		for (int i = 0; i < plugin; ++i)
		{
			const CivPluginRecord& other = s_plugins[i];
			if ((!other.saveFn && !CivValuesDeclaredBy(i)) || !CivSameSaveKey(other, rec.modId, rec.pluginId))
				continue;
			const std::string id = rec.pluginId.empty() ? "no plugin ID" : "the plugin ID \"" + rec.pluginId + "\"";
			Refuse(rec, CIV_PLUGIN_SAVE_ID_TAKEN, Format("%s, higher in the list, comes from the same mod and keeps its data in saves with %s too, so this plugin was not loaded, or their data would mix. Each plugin of a mod that keeps data in saves needs a plugin ID of its own; ask the plugin's author to fix this.",
				other.name.c_str(), id.c_str()));
			return true;
		}
		return false;
	}

	bool ListedAbove(int plugin)
	{
		for (int i = 0; i < plugin; ++i)
			if (CivSameText(s_plugins[i].path, s_plugins[plugin].path))
				return true;
		return false;
	}

	const KeptPlugin* KeptInMemory(const std::string& path)
	{
		for (size_t i = 0; i < s_kept.size(); ++i)
			if (CivSameText(s_kept[i].path, path))
				return &s_kept[i];
		return 0;
	}

	bool Fits(DWORD offset, unsigned __int64 bytes, DWORD imageSize)
	{
		return offset <= imageSize && bytes <= imageSize - offset;
	}

	enum ExportRead
	{
		EXPORT_FOUND,
		EXPORT_MISSING,
		EXPORT_64_BIT,
	};

	// Copies a named data export out of a file mapped with LOAD_LIBRARY_AS_IMAGE_RESOURCE, where GetProcAddress does not
	// work. A file that cannot be read counts as missing. No C++ objects may live in this frame, or __try is not allowed.
	ExportRead CopyExportedData(HMODULE image, const char* name, void* out, DWORD size)
	{
		__try
		{
			// Windows marks such a handle in its low bits.
			const BYTE* base = (const BYTE*)((ULONG_PTR)image & ~(ULONG_PTR)3);
			const IMAGE_NT_HEADERS32* nt = (const IMAGE_NT_HEADERS32*)(base + ((const IMAGE_DOS_HEADER*)base)->e_lfanew);
			if (nt->OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC)
				return EXPORT_64_BIT;
			if (nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR32_MAGIC || nt->OptionalHeader.NumberOfRvaAndSizes <= IMAGE_DIRECTORY_ENTRY_EXPORT)
				return EXPORT_MISSING;
			const DWORD imageSize = nt->OptionalHeader.SizeOfImage;
			const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT];
			if (!dir.VirtualAddress || !Fits(dir.VirtualAddress, sizeof(IMAGE_EXPORT_DIRECTORY), imageSize))
				return EXPORT_MISSING;
			const IMAGE_EXPORT_DIRECTORY* exports = (const IMAGE_EXPORT_DIRECTORY*)(base + dir.VirtualAddress);
			const unsigned __int64 count = exports->NumberOfNames;
			if (!Fits(exports->AddressOfNames, count * sizeof(DWORD), imageSize)
				|| !Fits(exports->AddressOfNameOrdinals, count * sizeof(WORD), imageSize)
				|| !Fits(exports->AddressOfFunctions, (unsigned __int64)exports->NumberOfFunctions * sizeof(DWORD), imageSize))
				return EXPORT_MISSING;
			const DWORD* names = (const DWORD*)(base + exports->AddressOfNames);
			const WORD* ordinals = (const WORD*)(base + exports->AddressOfNameOrdinals);
			const DWORD* functions = (const DWORD*)(base + exports->AddressOfFunctions);
			const size_t nameBytes = strlen(name) + 1;
			for (DWORD i = 0; i < exports->NumberOfNames; ++i)
			{
				if (!Fits(names[i], nameBytes, imageSize) || memcmp(base + names[i], name, nameBytes) != 0)
					continue;
				if (ordinals[i] >= exports->NumberOfFunctions)
					return EXPORT_MISSING;
				const DWORD rva = functions[ordinals[i]];
				// A forwarded export's address points at the forwarding text, inside the export directory.
				const bool forwarded = rva >= dir.VirtualAddress && rva - dir.VirtualAddress < dir.Size;
				if (!rva || forwarded || !Fits(rva, size, imageSize))
					return EXPORT_MISSING;
				memcpy(out, base + rva, size);
				return EXPORT_FOUND;
			}
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
		}
		return EXPORT_MISSING;
	}

	// Windows maps the file without running any of it or loading the DLLs it imports, so a refused plugin never runs.
	bool RefusedForApiVersion(CivPluginRecord& rec)
	{
		HMODULE image = LoadLibraryExW(CivWide(rec.path).c_str(), 0, LOAD_LIBRARY_AS_IMAGE_RESOURCE);
		if (!image)
		{
			Refuse(rec, CIV_PLUGIN_FILE_NOT_LOADED, Format("Windows could not open the file (error %lu).", GetLastError()));
			return true;
		}
		CivApiVersion built = {0, 0};
		const ExportRead read = CopyExportedData(image, CIV_PLUGIN_API_VERSION_NAME, &built, sizeof(built));
		FreeLibrary(image);
		if (read == EXPORT_64_BIT)
		{
			Refuse(rec, CIV_PLUGIN_FILE_NOT_LOADED, "It is a 64-bit DLL, and Civilization V can only load 32-bit ones.");
			return true;
		}
		if (read == EXPORT_MISSING)
		{
			Refuse(rec, CIV_PLUGIN_NO_API_VERSION, "The file does not say which Bazaar it was built for (it has no "
				CIV_PLUGIN_API_VERSION_NAME "), so it was built for an older Bazaar or is not a plugin.");
			return true;
		}
		rec.builtApiMajor = built.major;
		rec.builtApiMinor = built.minor;
		if (built.major != CIV_HOST_API_MAJOR)
		{
			Refuse(rec, CIV_PLUGIN_OTHER_MAJOR, Format("Built for Bazaar API %d.%d, which this Bazaar (API %d.%d) cannot run.",
				built.major, built.minor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR));
			return true;
		}
		if (built.minor > CIV_HOST_API_MINOR)
		{
			Refuse(rec, CIV_PLUGIN_NEWER_API, Format("Built for a newer Bazaar (API %d.%d); this Bazaar is API %d.%d.",
				built.major, built.minor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR));
			return true;
		}
		return false;
	}

	int AddRecord(const CivPluginFile& file)
	{
		CivPluginRecord rec;
		rec.path = CivFullPath(file.path);
		rec.modId = file.modId;
		rec.name = CivFileName(rec.path);
		rec.serial = ++s_lastSerial;
		s_plugins.push_back(rec);
		return (int)s_plugins.size() - 1;
	}

	// Nothing here may run the plugin's code: a refused plugin must never run.
	bool RefusedBeforeLoading(int plugin)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		if (ListedAbove(plugin))
		{
			Refuse(rec, CIV_PLUGIN_DUPLICATE, "It is listed more than once, so this listing was skipped.");
			return true;
		}
		if (const KeptPlugin* kept = KeptInMemory(rec.path))
		{
			rec.name = kept->name;
			Refuse(rec, CIV_PLUGIN_STILL_IN_MEMORY, "It could not be shut down safely earlier, so it stays off until you restart Civilization V.");
			return true;
		}
		return RefusedForApiVersion(rec);
	}

	// A plugin may keep this pointer for as long as its DLL is loaded.
	CivHostInfo* NewHostInfo(int plugin)
	{
		CivHostInfo* host = new CivHostInfo;
		host->pluginIndex = plugin;
		host->RegisterHook = &RegisterHook;
		host->Log = &PluginLog;
		host->RegisterHandHook = &RegisterHandHook;
		host->PushLuaFunction = &PushLuaFunction;
		host->RegisterSaveData = &RegisterSaveData;
		host->WriteSaveData = &WriteSaveData;
		host->DeclareValue = &DeclareValue;
		host->FindValue = &CivFindValue;
		host->GetIntValue = &CivGetIntValue;
		host->SetIntValue = &CivSetIntValue;
		host->GetInt64Value = &CivGetInt64Value;
		host->SetInt64Value = &CivSetInt64Value;
		host->GetDoubleValue = &CivGetDoubleValue;
		host->SetDoubleValue = &CivSetDoubleValue;
		host->GetTextValue = &CivGetTextValue;
		host->SetTextValue = &CivSetTextValue;
		return host;
	}

	void CopyDescription(CivPluginRecord& rec, const CivPluginInfo& info)
	{
		char text[256];
		if (CopyPluginText(info.name, text, sizeof(text)) && *text)
			rec.name = text;
		CopyPluginText(info.version, text, sizeof(text));
		rec.version = text;
		CopyPluginText(info.id, text, sizeof(text));
		rec.pluginId = text;
	}

	// When this is false, the plugin was refused and what it registered was discarded.
	bool EntryAccepted(int plugin)
	{
		// Held across the entry function: nothing a plugin can call while it loads adds or removes a record.
		CivPluginRecord& rec = s_plugins[plugin];
		// Lets a plugin's own helper DLLs load from its folder rather than the game's.
		HMODULE module = LoadLibraryExW(CivWide(rec.path).c_str(), 0, LOAD_WITH_ALTERED_SEARCH_PATH);
		if (!module)
		{
			Refuse(rec, CIV_PLUGIN_FILE_NOT_LOADED, Format("Windows could not load the file (error %lu).", GetLastError()));
			return false;
		}
		CivPluginEntryFn entry = (CivPluginEntryFn)GetProcAddress(module, CIV_PLUGIN_ENTRY_NAME);
		if (!entry)
		{
			Refuse(rec, CIV_PLUGIN_NO_ENTRY, "The file has no " CIV_PLUGIN_ENTRY_NAME " function, so it is not a plugin.");
			CivCrashForgetModule(module);
			FreeLibrary(module);
			return false;
		}

		rec.module = module;
		rec.host = NewHostInfo(plugin);
		CivPluginInfo info = { 0, 0, 0 };
		EntryCall call = { entry, rec.host, &info, false };
		DiscardPending();
		s_loadingConflict = false;
		unsigned int code = 0;
		const bool ran = GuardedEntry(&call, &code);
		CopyDescription(rec, info);
		if (!ran)
		{
			DiscardPending();
			rec.quarantined = true;
			Refuse(rec, CIV_PLUGIN_FAULTED_AT_LOAD, Format("It stopped working while loading (code 0x%08X) and was turned off until you return to the main menu.", code));
			LogCrash(&code);
			return false;
		}
		if (!call.accepted)
		{
			DiscardPending();
			Refuse(rec, CIV_PLUGIN_ENTRY_DECLINED, "Declined to load.");
			Unload(plugin);
			return false;
		}
		return true;
	}

	void KeepOrTurnAway(int plugin)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		if (RefusedForSaveKey(plugin))
		{
			DiscardPending();
			Unload(plugin);
			return;
		}
		const bool heldBack = !s_loadingConflict && ReportPossibleConflicts(plugin);
		if (s_loadingConflict || heldBack)
		{
			DiscardPending();
			rec.status = heldBack ? CIV_PLUGIN_POSSIBLE_CONFLICT : CIV_PLUGIN_REPLACE_CONFLICT;
			Unload(plugin);
			return;
		}
		CommitPending(plugin);
		rec.status = CIV_PLUGIN_LOADED;
		Log("Plugin %s %s loaded (built for API %d.%d).", rec.name.c_str(), rec.version.c_str(), rec.builtApiMajor, rec.builtApiMinor);
	}

	void LoadOne(const CivPluginFile& file)
	{
		const int plugin = AddRecord(file);
		if (!RefusedBeforeLoading(plugin) && EntryAccepted(plugin))
			KeepOrTurnAway(plugin);
	}

	void DeleteEntries(CivHookEntry* e)
	{
		while (e)
		{
			CivHookEntry* next = e->next;
			delete e;
			e = next;
		}
	}

	void RemoveHooks(CivHookPoint& hp)
	{
		DeleteEntries(hp.before);
		DeleteEntries(hp.after);
		delete hp.replace;
		hp.before = hp.after = hp.replace = 0;
	}

	void RemoveAllHooks()
	{
		for (int i = 0; i < g_CivHookPointCount; ++i)
		{
			if (!g_CivHookActive[i])
				continue;
			RemoveHooks(g_CivHookPoints[i]);
			g_CivHookActive[i] = 0;
		}
		for (int i = 0; i < g_CivHandHookCount; ++i)
			RemoveHooks(g_CivHandHookPoints[i]);
	}

	void LogSkippedOriginal(int plugin, int hookId)
	{
		Log("Plugin %s: its replacement of %s returned without running the original, so no hook inside the original ran. This is logged only once.",
			s_plugins[plugin].name.c_str(), HookName(hookId));
	}

	bool SameAsListed(const std::vector<CivPluginFile>& files)
	{
		if (files.size() != s_plugins.size())
			return false;
		for (size_t i = 0; i < files.size(); ++i)
			if (!CivSameText(CivFullPath(files[i].path), s_plugins[i].path) || !CivSameText(files[i].modId, s_plugins[i].modId))
				return false;
		return true;
	}
}

bool CivHookRunBefore(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	CivHookCtx* c = static_cast<CivHookCtx*>(ctx);
	for (const CivHookEntry* e = hp.before; e; e = e->next)
	{
		if (!Alive(e->plugin))
			continue;
		c->veto = false;
		if (CallPlugin(e, id, thunk, ctx) && c->veto)
			return true;
	}
	return false;
}

// No C++ objects may live in this frame, or __try is not allowed.
bool CivHookRunReplace(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	CivHookEntry* e = hp.replace;
	if (!e || !Alive(e->plugin))
		return false;
	// The original may run other replacements before this one returns, and an exception nobody here handles may pass
	// through, so the outer replacement's flag is always put back.
	bool* const outer = s_originalCalled;
	bool called = false;
	bool ran = false;
	s_originalCalled = &called;
	__try
	{
		ran = CallPlugin(e, id, thunk, ctx);
	}
	__finally
	{
		s_originalCalled = outer;
	}
	if (ran && !called && !e->loggedSkippedOriginal)
	{
		e->loggedSkippedOriginal = true;
		LogSkippedOriginal(e->plugin, id);
	}
	return ran;
}

void CivHookOriginalCalled()
{
	if (s_originalCalled)
		*s_originalCalled = true;
}

void CivHookRunAfter(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	for (const CivHookEntry* e = hp.after; e; e = e->next)
		if (Alive(e->plugin))
			CallPlugin(e, id, thunk, ctx);
}

void CivHostSetLogSink(CivHostLogSink sink)
{
	s_logSink = sink;
}

void CivHostSetFaultSink(CivHostFaultSink sink)
{
	s_faultSink = sink;
}

void CivHostSetLuaPusher(CivHostLuaPusher pusher)
{
	s_luaPusher = pusher;
}

namespace
{
	struct LuaCall
	{
		CivLuaFunction fn;
		lua_State* L;
		int results;
	};

	void LuaThunk(void* p)
	{
		LuaCall& c = *static_cast<LuaCall*>(p);
		c.results = c.fn(c.L);
	}

	int PluginWithSerial(unsigned int serial)
	{
		for (size_t i = 0; i < s_plugins.size(); ++i)
			if (s_plugins[i].serial == serial && s_plugins[i].module)
				return (int)i;
		return -1;
	}

	struct SaveCall
	{
		CivSaveDataFn fn;
		void* saving;
	};

	void SaveThunk(void* p)
	{
		SaveCall& c = *static_cast<SaveCall*>(p);
		c.fn(c.saving);
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	bool GuardedSave(SaveCall* call, std::string* data, unsigned int* code)
	{
		bool ran = false;
		if (++s_saveToken == 0)
			++s_saveToken;
		s_saving = data;
		call->saving = CurrentSaveToken();
		__try
		{
			ran = GuardedCall(&SaveThunk, call, code);
		}
		__finally
		{
			s_saving = 0;
		}
		return ran;
	}

	struct LoadCall
	{
		CivLoadDataFn fn;
		const void* data;
		int size;
	};

	void LoadThunk(void* p)
	{
		LoadCall& c = *static_cast<LoadCall*>(p);
		c.fn(c.data, c.size);
	}
}

// No C++ objects may live in this frame: a Lua error the plugin raises jumps out of it.
bool CivHostCallLuaFunction(unsigned int serial, CivLuaFunction fn, lua_State* L, int* results, char* why, size_t whySize)
{
	if (!serial)
	{
		_snprintf_s(why, whySize, _TRUNCATE, "This Lua function was pushed with a wrong plugin index, so it cannot run.");
		return false;
	}
	const int plugin = PluginWithSerial(serial);
	if (plugin < 0)
	{
		_snprintf_s(why, whySize, _TRUNCATE, "The plugin that added this Lua function is no longer loaded.");
		return false;
	}
	if (!Alive(plugin))
	{
		_snprintf_s(why, whySize, _TRUNCATE, "%s was turned off after a crash, so its Lua functions no longer run.",
			s_plugins[plugin].name.c_str());
		return false;
	}
	LuaCall call = { fn, L, 0 };
	unsigned int code = 0;
	if (GuardedCall(&LuaThunk, &call, &code))
	{
		*results = call.results;
		return true;
	}
	Quarantine(plugin, false, "a Lua function", &code);
	_snprintf_s(why, whySize, _TRUNCATE, "%s stopped working in a Lua function and was turned off.", s_plugins[plugin].name.c_str());
	return false;
}

const std::vector<CivPluginRecord>& CivHostPlugins()
{
	return s_plugins;
}

void CivHostLogLine(const char* line)
{
	Log("%s", line);
}

const char* CivHostPluginName(int plugin)
{
	return DisplayName(plugin);
}

bool CivSameSaveKey(const std::string& modIdA, const std::string& pluginIdA, const std::string& modIdB, const std::string& pluginIdB)
{
	return CivSameText(modIdA, modIdB) && CivSameText(pluginIdA, pluginIdB);
}

bool CivSameSaveKey(const CivPluginRecord& plugin, const std::string& modId, const std::string& pluginId)
{
	return CivSameSaveKey(plugin.modId, plugin.pluginId, modId, pluginId);
}

bool CivHostCallSaveFunction(int plugin, std::string* data)
{
	data->clear();
	if (!Alive(plugin) || !s_plugins[plugin].saveFn)
		return false;
	SaveCall call = { s_plugins[plugin].saveFn, 0 };
	unsigned int code = 0;
	if (GuardedSave(&call, data, &code))
		return true;
	data->clear();
	Quarantine(plugin, false, "its save function", &code);
	return false;
}

void CivHostCallLoadFunction(int plugin, const std::string* data)
{
	if (!Alive(plugin) || !s_plugins[plugin].loadFn)
		return;
	const bool none = !data || data->empty();
	LoadCall call = { s_plugins[plugin].loadFn, none ? 0 : data->data(), none ? 0 : (int)data->size() };
	unsigned int code = 0;
	if (!GuardedCall(&LoadThunk, &call, &code))
		Quarantine(plugin, false, "its load function", &code);
}

std::vector<CivPluginReportRow> CivHostReportRows()
{
	std::vector<CivPluginReportRow> rows;
	for (size_t i = 0; i < s_plugins.size(); ++i)
	{
		const CivPluginRecord& p = s_plugins[i];
		CivPluginReportRow row;
		row.file = CivFileName(p.path);
		row.name = p.name;
		row.version = p.version;
		row.failed = p.status != CIV_PLUGIN_LOADED || p.quarantined;
		if (p.quarantined)
			row.status = "Turned off after a crash";
		else if (row.failed)
			row.status = CIV_REPORT_NOT_LOADED;
		else
			row.status = "Loaded";
		for (size_t j = 0; j < p.problems.size(); ++j)
			row.problems += (j ? "\n" : "") + p.problems[j];
		for (size_t j = 0; j < p.notes.size(); ++j)
			row.problems += (row.problems.empty() ? "" : "\n") + p.notes[j];
		row.conflictsWith = p.conflictsWith;
		rows.push_back(row);
	}
	return rows;
}

void CivHostLoadPlugins(const std::vector<CivPluginFile>& files)
{
	for (size_t i = 0; i < files.size(); ++i)
		LoadOne(files[i]);
}

CivPluginListResult CivHostSetPlugins(const std::vector<CivPluginFile>& files, const CivFilePairs& useBoth)
{
	if (SameAsListed(files) && useBoth == s_useBoth)
		return CIV_PLUGINS_UNCHANGED;
	if (!CivHostUnloadPlugins())
		return CIV_PLUGINS_BUSY;
	s_useBoth = useBoth;
	if (!files.empty())
		Log("---- Loading plugins");
	CivHostLoadPlugins(files);
	return CIV_PLUGINS_CHANGED;
}

bool CivHostUnloadPlugins()
{
	// A plugin call on the stack means its code, and the hook list that called it, are still in use.
	if (s_pluginCallDepth > 0)
		return false;
	RemoveAllHooks();
	for (size_t i = s_plugins.size(); i-- > 0;)
		if (s_plugins[i].module)
			Unload((int)i);
	s_plugins.clear();
	s_useBoth.clear();
	s_strayWriteLogged = false;
	CivValuesForgetAll();
	return true;
}
