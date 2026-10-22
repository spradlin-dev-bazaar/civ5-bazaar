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
		CivHookCtx header;
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
	{
		const int index = (int)s_plugins.size();
		CivPluginRecord blank;
		blank.path = paths[i];
		blank.builtApiMajor = 0;
		blank.builtApiMinor = 0;
		blank.status = CIV_PLUGIN_FILE_NOT_LOADED;
		blank.quarantined = false;
		s_plugins.push_back(blank);
		CivPluginRecord& rec = s_plugins.back();

		HMODULE module = LoadLibraryA(paths[i].c_str());
		if (!module)
		{
			char problem[256];
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Windows could not load the file (error %lu).", GetLastError());
			rec.problems.push_back(problem);
			Log("Plugin %s: %s", rec.path.c_str(), problem);
			continue;
		}
		CivPluginEntryFn entry = (CivPluginEntryFn)GetProcAddress(module, CIV_PLUGIN_ENTRY_NAME);
		if (!entry)
		{
			rec.status = CIV_PLUGIN_NO_ENTRY;
			rec.problems.push_back("The file has no " CIV_PLUGIN_ENTRY_NAME " function, so it is not a plugin.");
			Log("Plugin %s: %s", rec.path.c_str(), rec.problems.back().c_str());
			FreeLibrary(module);
			continue;
		}

		CivHostInfo host = { CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR, index, &RegisterHook, &PluginLog };
		CivPluginInfo info = { 0, 0, 0, 0 };
		EntryCall call = { { 0, false }, entry, &host, &info, false };
		s_pending.clear();
		s_loadingPlugin = index;
		unsigned int code = 0;
		const bool ran = GuardedCall(&EntryThunk, &call, &code);
		s_loadingPlugin = -1;
		if (!ran && code == EXCEPTION_STACK_OVERFLOW)
			_resetstkoflw();

		CivPluginRecord& r = s_plugins[index];
		if (ran)
		{
			r.name = Copy(info.name);
			r.version = Copy(info.version);
			r.builtApiMajor = info.builtApiMajor;
			r.builtApiMinor = info.builtApiMinor;
		}
		if (r.name.empty())
			r.name = r.path;

		char problem[512];
		problem[0] = 0;
		if (!ran)
		{
			r.status = CIV_PLUGIN_FAULTED_AT_LOAD;
			r.quarantined = true;
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Faulted while loading (code 0x%08X) and was disabled for this session.", code);
		}
		else if (!call.accepted)
		{
			r.status = CIV_PLUGIN_ENTRY_DECLINED;
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Declined to load.");
		}
		else if (info.builtApiMajor != CIV_HOST_API_MAJOR)
		{
			r.status = CIV_PLUGIN_OTHER_MAJOR;
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Built for host API %d.%d, which this host (API %d.%d) cannot run.",
				info.builtApiMajor, info.builtApiMinor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
		}
		else if (info.builtApiMinor > CIV_HOST_API_MINOR)
		{
			r.status = CIV_PLUGIN_NEWER_API;
			_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Built for a newer host (API %d.%d); this host is API %d.%d.",
				info.builtApiMajor, info.builtApiMinor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
		}

		if (problem[0])
		{
			s_pending.clear();
			r.problems.push_back(problem);
			Log("Plugin %s: %s", r.name.c_str(), problem);
			if (r.status != CIV_PLUGIN_FAULTED_AT_LOAD)
				FreeLibrary(module);
			continue;
		}
		CommitPending(index);
		r.status = CIV_PLUGIN_LOADED;
		Log("Plugin %s %s loaded (built for API %d.%d).", r.name.c_str(), r.version.c_str(), r.builtApiMajor, r.builtApiMinor);
	}
}
