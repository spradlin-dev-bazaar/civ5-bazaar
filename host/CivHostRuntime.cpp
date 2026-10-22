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

	std::vector<CivPluginRecord> s_plugins;
	std::vector<PendingHook> s_pending;
	int s_loadingPlugin = -1;
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
		__try
		{
			thunk(ctx);
			return true;
		}
		__except (FaultFilter(*code = GetExceptionCode()))
		{
			return false;
		}
	}

	void Quarantine(int plugin, int hookId, unsigned int code)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		rec.quarantined = true;
		char problem[512];
		_snprintf_s(problem, sizeof(problem), _TRUNCATE,
			"Faulted (code 0x%08X) in %s and was disabled for this session.", code, HookName(hookId));
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
		if (code == EXCEPTION_STACK_OVERFLOW)
			_resetstkoflw();
		Quarantine(e->plugin, hookId, code);
		return false;
	}

	int RegisterHook(int plugin, int hookId, int kind, void* fn)
	{
		if (plugin != s_loadingPlugin)
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
				Log("Plugin %s: %s", s_plugins[plugin].name.empty() ? s_plugins[plugin].path.c_str() : s_plugins[plugin].name.c_str(), problem);
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
		const char* name = (plugin >= 0 && plugin < (int)s_plugins.size()) ? s_plugins[plugin].name.c_str() : "?";
		Log("[%s] %s", name, message ? message : "");
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

	std::string Copy(const char* s)
	{
		return s ? std::string(s) : std::string();
	}

	void Refuse(CivPluginRecord& rec, CivPluginStatus status, const std::string& problem)
	{
		if (rec.name.empty())
			rec.name = rec.path.substr(rec.path.find_last_of("\\/") + 1);
		rec.status = status;
		rec.problems.push_back(problem);
		Log("Plugin %s: %s", rec.name.c_str(), problem.c_str());
	}

	bool AlreadyListed(const std::string& path)
	{
		for (size_t i = 0; i < s_plugins.size(); ++i)
			if (_stricmp(s_plugins[i].path.c_str(), path.c_str()) == 0)
				return true;
		return false;
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
		char full[MAX_PATH];
		const DWORD length = GetFullPathNameA(requested.c_str(), MAX_PATH, full, 0);
		const std::string path = (length > 0 && length < MAX_PATH) ? std::string(full) : requested;
		const int index = (int)s_plugins.size();
		CivPluginRecord blank;
		blank.path = path;
		blank.builtApiMajor = 0;
		blank.builtApiMinor = 0;
		blank.status = CIV_PLUGIN_FILE_NOT_LOADED;
		blank.quarantined = false;
		const bool duplicate = AlreadyListed(path);
		s_plugins.push_back(blank);
		if (duplicate)
		{
			Refuse(s_plugins[index], CIV_PLUGIN_DUPLICATE, "It is listed more than once; only the first listing was loaded.");
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

		// A loaded plugin may keep this pointer for the whole session.
		CivHostInfo* host = new CivHostInfo;
		host->apiMajor = CIV_HOST_API_MAJOR;
		host->apiMinor = CIV_HOST_API_MINOR;
		host->pluginIndex = index;
		host->RegisterHook = &RegisterHook;
		host->Log = &PluginLog;
		CivPluginInfo info = { 0, 0, 0, 0 };
		EntryCall call = { entry, host, &info, false };
		s_pending.clear();
		s_loadingPlugin = index;
		unsigned int code = 0;
		const bool ran = GuardedCall(&EntryThunk, &call, &code);
		s_loadingPlugin = -1;
		if (!ran && code == EXCEPTION_STACK_OVERFLOW)
			_resetstkoflw();

		CivPluginRecord& rec = s_plugins[index];
		rec.name = info.name ? Copy(info.name) : path;
		rec.version = Copy(info.version);
		rec.builtApiMajor = info.builtApiMajor;
		rec.builtApiMinor = info.builtApiMinor;

		if (!ran)
		{
			// The module stays loaded: the fault may have left its code referenced elsewhere.
			char problem[256];
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Faulted while loading (code 0x%08X) and was disabled for this session.", code);
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
			FreeLibrary(module);
			delete host;
			return;
		}
		CommitPending(index);
		rec.status = CIV_PLUGIN_LOADED;
		Log("Plugin %s %s loaded (built for API %d.%d).", rec.name.c_str(), rec.version.c_str(), rec.builtApiMajor, rec.builtApiMinor);
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

int CivHookRunReplace(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	const CivHookEntry* e = hp.replace;
	if (!e || !Alive(e->plugin))
		return 0;
	return CallPlugin(e, id, thunk, ctx) ? 1 : -1;
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
