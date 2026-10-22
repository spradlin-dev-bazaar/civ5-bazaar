#include "CivHostHooks.h"
#include "CivHostRuntime.h"

#include <windows.h>
#include <malloc.h>
#include <stdarg.h>
#include <stdio.h>

extern const char* const g_CivHookPointNames[];

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

	std::vector<CivPluginRecord> s_plugins;
	std::vector<PendingHook> s_pending;
	std::vector<KeptPlugin> s_kept;
	int s_loadingPlugin = -1;
	const CivPluginInfo* s_loadingInfo = 0;
	int s_pluginCallDepth = 0;
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

	const char* HookName(int id)
	{
		return (id >= 0 && id < g_CivHookPointCount) ? g_CivHookPointNames[id] : "?";
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

	void Quarantine(int plugin, int hookId, const char* where, unsigned int code)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		rec.quarantined = true;
		char problem[512];
		_snprintf_s(problem, sizeof(problem), _TRUNCATE,
			"Faulted (code 0x%08X) in %s.", code, where);
		rec.problems.push_back(problem);
		Log("Plugin %s: %s", rec.name.c_str(), problem);
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
			const char* owner = 0;
			if (g_CivHookPoints[hookId].replace)
				owner = s_plugins[g_CivHookPoints[hookId].replace->plugin].name.c_str();
			for (size_t i = 0; i < s_pending.size() && !owner; ++i)
				if (s_pending[i].id == hookId && s_pending[i].kind == CIV_HOOK_REPLACE)
					owner = "this plugin";
			if (owner)
			{
				char problem[512];
				_snprintf_s(problem, sizeof(problem), _TRUNCATE,
					"Its replacement of %s was refused: %s already replaces it.", HookName(hookId), owner);
				s_plugins[plugin].problems.push_back(problem);
				Log("Plugin %s: %s", DisplayName(plugin), problem);
				return CIV_HOOK_REPLACE_TAKEN;
			}
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
			CivHookPoint& hp = g_CivHookPoints[p.id];
			CivHookEntry* e = new CivHookEntry;
			e->fn = p.fn;
			e->plugin = plugin;
			e->next = 0;
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
			hp.active = 1;
		}
		s_pending.clear();
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
		if (rec.quarantined)
			Log("Plugin %s: Faulted (code 0x%08X) in its shutdown function.", rec.name.c_str(), code);
		else
			Quarantine(plugin, -1, "its shutdown function", code);
		return false;
	}

	// A plugin whose shutdown faulted may still have threads or callbacks pointing into its DLL, so the DLL
	// stays loaded and the plugin stays refused until Civilization V restarts.
	void Unload(int plugin)
	{
		const bool clean = ShutDownCleanly(plugin);
		CivPluginRecord& rec = s_plugins[plugin];
		if (clean)
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
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Built for host API %d.%d, which this host (API %d.%d) cannot run.",
				info.builtApiMajor, info.builtApiMinor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
			return problem;
		}
		if (info.builtApiMinor > CIV_HOST_API_MINOR)
		{
			*status = CIV_PLUGIN_NEWER_API;
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Built for a newer host (API %d.%d); this host is API %d.%d.",
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
			Refuse(s_plugins[index], CIV_PLUGIN_STILL_IN_MEMORY, "It stopped working earlier and could not be shut down safely, so it stays off until you restart Civilization V.");
			return;
		}

		HMODULE module = LoadLibraryA(path.c_str());
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
		s_plugins[index].module = module;
		s_plugins[index].host = host;
		CivPluginInfo info = { 0, 0, 0, 0 };
		EntryCall call = { entry, host, &info, false };
		s_pending.clear();
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
			s_pending.clear();
			rec.quarantined = true;
			Refuse(rec, CIV_PLUGIN_FAULTED_AT_LOAD, problem);
			return;
		}
		CivPluginStatus status = CIV_PLUGIN_LOADED;
		const std::string problem = RefusalReason(call.accepted, info, &status);
		if (!problem.empty())
		{
			s_pending.clear();
			Refuse(rec, status, problem);
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

	void RemoveAllHooks()
	{
		for (int i = 0; i < g_CivHookPointCount; ++i)
		{
			CivHookPoint& hp = g_CivHookPoints[i];
			if (!hp.active)
				continue;
			DeleteEntries(hp.before);
			DeleteEntries(hp.after);
			delete hp.replace;
			hp.before = hp.after = hp.replace = 0;
			hp.active = 0;
		}
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

bool CivHookRunReplace(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	const CivHookEntry* e = hp.replace;
	return e && Alive(e->plugin) && CallPlugin(e, id, thunk, ctx);
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

void CivHostLoadPlugins(const std::vector<std::string>& paths)
{
	for (size_t i = 0; i < paths.size(); ++i)
		LoadOne(paths[i]);
}

CivPluginListResult CivHostSetPlugins(const std::vector<std::string>& paths)
{
	if (SameAsListed(paths))
		return CIV_PLUGINS_UNCHANGED;
	if (!CivHostUnloadPlugins())
		return CIV_PLUGINS_BUSY;
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
	return true;
}
