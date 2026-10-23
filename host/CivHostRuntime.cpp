#include "CivHostHooks.h"
#include "CivHostRuntime.h"

#include <windows.h>
#include <tlhelp32.h>
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
	int s_pluginCallDepth = 0;
	bool* s_originalCalled = 0;
	CivHostLogSink s_logSink = 0;
	CivHostFaultSink s_faultSink = 0;

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

	const char* FileName(const std::string& path)
	{
		return path.c_str() + (path.find_last_of("\\/") + 1);
	}

	bool SamePath(const std::string& a, const std::string& b)
	{
		return _stricmp(a.c_str(), b.c_str()) == 0;
	}

	std::string FullPath(const std::string& requested)
	{
		char full[MAX_PATH];
		const DWORD length = GetFullPathNameA(requested.c_str(), MAX_PATH, full, 0);
		return (length > 0 && length < MAX_PATH) ? std::string(full) : requested;
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

	int FaultFilter(unsigned int code)
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
			return EXCEPTION_EXECUTE_HANDLER;
		}
		return EXCEPTION_CONTINUE_SEARCH;
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	bool GuardedCall(CivHookThunk thunk, void* ctx, unsigned int* code)
	{
		bool ran = true;
		++s_pluginCallDepth;
		__try
		{
			__try
			{
				thunk(ctx);
			}
			__except (FaultFilter(*code = GetExceptionCode()))
			{
				ran = false;
			}
		}
		__finally
		{
			--s_pluginCallDepth;
		}
		if (!ran && *code == EXCEPTION_STACK_OVERFLOW)
			_resetstkoflw();
		return ran;
	}

	// The player hears about a plugin's first fault only; later ones are logged.
	void Quarantine(int plugin, int hookId, const char* where, unsigned int code)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		char problem[512];
		_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Faulted (code 0x%08X) in %s.", code, where);
		Log("Plugin %s: %s", rec.name.c_str(), problem);
		if (rec.quarantined)
			return;
		rec.quarantined = true;
		rec.problems.push_back(problem);
		if (s_faultSink)
			s_faultSink(plugin, rec.name.c_str(), hookId, code);
	}

	bool CallPlugin(const CivHookEntry* e, int hookId, CivHookThunk thunk, void* ctx)
	{
		static_cast<CivHookCtx*>(ctx)->fn = e->fn;
		unsigned int code = 0;
		if (GuardedCall(thunk, ctx, &code))
			return true;
		Quarantine(e->plugin, hookId, HookName(hookId), code);
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
			if ((SamePath(pair.first, a) && SamePath(pair.second, b)) || (SamePath(pair.first, b) && SamePath(pair.second, a)))
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
			const std::string otherFile = FileName(s_plugins[c.other].path);
			const char* otherName = s_plugins[c.other].name.c_str();
			const std::string function = ShortHookName(c.hookPoint);
			const char* hook = CivHandHookName(c.handHook);
			AddOnce(rec.conflictsWith, otherFile);
			if (UseBoth(FileName(rec.path), otherFile))
			{
				AddAndLog(plugin, rec.notes, Format("You chose to use this plugin with %s anyway, although one of them replaces %s, which runs the %s hook the other uses.",
					otherName, function.c_str(), hook));
				continue;
			}
			heldBack = true;
			if (c.pluginReplaces)
				AddAndLog(plugin, rec.problems, Format("This plugin replaces %s, which runs the %s hook that %s, higher in the list, uses. If the version in this plugin does not run the game's own, %s never gets that hook, so this plugin was held back. If you know the two work together, tick Use both anyway.",
					function.c_str(), hook, otherName, otherName));
			else
				AddAndLog(plugin, rec.problems, Format("%s, higher in the list, replaces %s, which runs the %s hook this plugin uses. If the version in %s does not run the game's own, this plugin never gets that hook, so it was held back. If you know the two work together, tick Use both anyway.",
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

	int RegisterHandHook(int plugin, int handHook, void* fn)
	{
		if (s_loadingPlugin < 0 || plugin != s_loadingPlugin)
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
		if (s_loadingPlugin < 0 || plugin != s_loadingPlugin)
			return CIV_HOOK_NOT_ALLOWED;
		if (hookId < 0 || hookId >= g_CivHookPointCount || !fn)
			return CIV_HOOK_BAD_ID;
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

	void CommitPending(int plugin)
	{
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
	}

	void PluginLog(int plugin, const char* message)
	{
		Log("[%s] %s", DisplayName(plugin), message ? message : "");
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
		Quarantine(plugin, -1, "its shutdown function", code);
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

	// No C++ objects may live in this frame, or __try is not allowed.
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
		HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
		if (!query || snapshot == INVALID_HANDLE_VALUE)
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

	bool AlreadyListed(const std::string& path)
	{
		for (size_t i = 0; i < s_plugins.size(); ++i)
			if (SamePath(s_plugins[i].path, path))
				return true;
		return false;
	}

	const KeptPlugin* KeptInMemory(const std::string& path)
	{
		for (size_t i = 0; i < s_kept.size(); ++i)
			if (SamePath(s_kept[i].path, path))
				return &s_kept[i];
		return 0;
	}

	std::string RefusalReason(bool accepted, const CivPluginInfo& info, CivPluginStatus* status)
	{
		char problem[256];
		if (!accepted)
		{
			*status = CIV_PLUGIN_ENTRY_DECLINED;
			return "Declined to load.";
		}
		if (info.builtApiMajor != CIV_HOST_API_MAJOR)
		{
			*status = CIV_PLUGIN_OTHER_MAJOR;
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Built for Bazaar API %d.%d, which this Bazaar (API %d.%d) cannot run.",
				info.builtApiMajor, info.builtApiMinor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
			return problem;
		}
		if (info.builtApiMinor > CIV_HOST_API_MINOR)
		{
			*status = CIV_PLUGIN_NEWER_API;
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Built for a newer Bazaar (API %d.%d); this Bazaar is API %d.%d.",
				info.builtApiMajor, info.builtApiMinor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
			return problem;
		}
		return std::string();
	}

	void LoadOne(const std::string& requested)
	{
		const std::string path = FullPath(requested);
		const int index = (int)s_plugins.size();
		CivPluginRecord blank;
		blank.path = path;
		blank.name = FileName(path);
		const bool duplicate = AlreadyListed(path);
		s_plugins.push_back(blank);
		if (duplicate)
		{
			Refuse(s_plugins[index], CIV_PLUGIN_DUPLICATE, "It is listed more than once, so this listing was skipped.");
			return;
		}
		if (const KeptPlugin* kept = KeptInMemory(path))
		{
			s_plugins[index].name = kept->name;
			Refuse(s_plugins[index], CIV_PLUGIN_STILL_IN_MEMORY, "It could not be shut down safely earlier, so it stays off until you restart Civilization V.");
			return;
		}

		// Lets a plugin's own helper DLLs load from its folder rather than the game's.
		HMODULE module = LoadLibraryExA(path.c_str(), 0, LOAD_WITH_ALTERED_SEARCH_PATH);
		if (!module)
		{
			char problem[256];
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Windows could not load the file (error %lu).", GetLastError());
			Refuse(s_plugins[index], CIV_PLUGIN_FILE_NOT_LOADED, problem);
			return;
		}
		CivPluginEntryFn entry = (CivPluginEntryFn)GetProcAddress(module, CIV_PLUGIN_ENTRY_NAME);
		if (!entry)
		{
			Refuse(s_plugins[index], CIV_PLUGIN_NO_ENTRY, "The file has no " CIV_PLUGIN_ENTRY_NAME " function, so it is not a plugin.");
			FreeLibrary(module);
			return;
		}

		// A plugin may keep this pointer for as long as its DLL is loaded.
		CivHostInfo* host = new CivHostInfo;
		host->apiMajor = CIV_HOST_API_MAJOR;
		host->apiMinor = CIV_HOST_API_MINOR;
		host->pluginIndex = index;
		host->RegisterHook = &RegisterHook;
		host->Log = &PluginLog;
		host->RegisterHandHook = &RegisterHandHook;
		s_plugins[index].module = module;
		s_plugins[index].host = host;
		CivPluginInfo info = { 0, 0, 0, 0 };
		EntryCall call = { entry, host, &info, false };
		DiscardPending();
		s_loadingConflict = false;
		unsigned int code = 0;
		const bool ran = GuardedEntry(&call, &code);

		CivPluginRecord& rec = s_plugins[index];
		if (info.name && *info.name)
			rec.name = info.name;
		rec.version = info.version ? info.version : "";
		rec.builtApiMajor = info.builtApiMajor;
		rec.builtApiMinor = info.builtApiMinor;

		if (!ran)
		{
			char problem[256];
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "It stopped working while loading (code 0x%08X) and was turned off until you return to the main menu.", code);
			DiscardPending();
			rec.quarantined = true;
			Refuse(rec, CIV_PLUGIN_FAULTED_AT_LOAD, problem);
			return;
		}
		CivPluginStatus status = CIV_PLUGIN_LOADED;
		const std::string problem = RefusalReason(call.accepted, info, &status);
		if (!problem.empty())
		{
			DiscardPending();
			Refuse(rec, status, problem);
			Unload(index);
			return;
		}
		const bool heldBack = !s_loadingConflict && ReportPossibleConflicts(index);
		if (s_loadingConflict || heldBack)
		{
			DiscardPending();
			rec.status = heldBack ? CIV_PLUGIN_POSSIBLE_CONFLICT : CIV_PLUGIN_REPLACE_CONFLICT;
			Unload(index);
			return;
		}
		CommitPending(index);
		rec.status = CIV_PLUGIN_LOADED;
		Log("Plugin %s %s loaded (built for API %d.%d).", rec.name.c_str(), rec.version.c_str(), rec.builtApiMajor, rec.builtApiMinor);
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

	bool SameAsListed(const std::vector<std::string>& paths)
	{
		if (paths.size() != s_plugins.size())
			return false;
		for (size_t i = 0; i < paths.size(); ++i)
			if (!SamePath(FullPath(paths[i]), s_plugins[i].path))
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

const std::vector<CivPluginRecord>& CivHostPlugins()
{
	return s_plugins;
}

std::vector<CivPluginReportRow> CivHostReportRows()
{
	std::vector<CivPluginReportRow> rows;
	for (size_t i = 0; i < s_plugins.size(); ++i)
	{
		const CivPluginRecord& p = s_plugins[i];
		CivPluginReportRow row;
		row.file = FileName(p.path);
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

void CivHostLoadPlugins(const std::vector<std::string>& paths)
{
	for (size_t i = 0; i < paths.size(); ++i)
		LoadOne(paths[i]);
}

CivPluginListResult CivHostSetPlugins(const std::vector<std::string>& paths, const CivFilePairs& useBoth)
{
	if (SameAsListed(paths) && useBoth == s_useBoth)
		return CIV_PLUGINS_UNCHANGED;
	if (!CivHostUnloadPlugins())
		return CIV_PLUGINS_BUSY;
	s_useBoth = useBoth;
	if (!paths.empty())
		Log("---- Loading plugins");
	CivHostLoadPlugins(paths);
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
	return true;
}
