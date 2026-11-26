#include "CivHostCalls.h"
#include "CivHostCrash.h"
#include "CivHostFunctions.h"
#include "CivHostHookList.h"
#include "CivHostLock.h"
#include "CivHostRuntime.h"

#include <windows.h>
#include <malloc.h>
#include <stdio.h>

namespace
{
	int s_loadingPlugin = -1;
	const CivPluginInfo* s_loadingInfo = 0;
	std::string* s_saving = 0;
	// A new one for every call of a save function, so a saving kept from an earlier call writes nowhere.
	unsigned int s_saveToken = 0;
	volatile LONG s_pluginCallDepth = 0;
	CivHostFaultSink s_faultSink = 0;
	volatile bool s_gameMayBeDamaged = false;
	// Lets one thread at a time log a plugin's crash and turn the plugin off, so each crash's lines stay together in Bazaar.log.
	CivLock s_quarantineLock;

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

	// The player hears about a plugin's first fault only; later ones are logged.
	void Quarantine(int plugin, bool shuttingDown, const char* where, const unsigned int* code)
	{
		CivPluginRecord& rec = CivHostRecord(plugin);
		char problem[512];
		// The in-game checker that mod authors keep a copy of finds crashes by this line and the load fault's in
		// CivHostRuntime.cpp, and a Bazaar update cannot change their copies, so changed words would let a crash pass their
		// checks unseen.
		_snprintf_s(problem, sizeof(problem), _TRUNCATE, "Faulted (code 0x%08X) in %s.", *code, where);
		if (!shuttingDown)
			s_gameMayBeDamaged = true;
		{
			const CivLockHold hold(s_quarantineLock);
			CivHostLog("Plugin %s: %s", rec.name.c_str(), problem);
			CivCallsLogCrash(code);
			if (rec.quarantined)
				return;
			rec.quarantined = true;
			rec.problems.push_back(problem);
		}
		if (s_faultSink)
			s_faultSink(plugin, rec.name.c_str(), shuttingDown, *code);
	}

	void* CurrentSaveToken()
	{
		return s_saving ? reinterpret_cast<void*>(static_cast<UINT_PTR>(s_saveToken)) : 0;
	}

	struct FunctionCall
	{
		CivFunctionRunner run;
		void* fn;
		void* args;
	};

	void FunctionCallThunk(void* p)
	{
		FunctionCall& c = *static_cast<FunctionCall*>(p);
		c.run(c.fn, c.args);
	}

	void EntryThunk(void* p)
	{
		CivEntryCall& c = *static_cast<CivEntryCall*>(p);
		c.accepted = c.entry(c.host, c.info);
	}

	void ShutdownThunk(void* p)
	{
		(*static_cast<CivPluginShutdownFn*>(p))();
	}

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
		for (size_t i = 0; i < CivHostPlugins().size(); ++i)
			if (CivHostPlugins()[i].serial == serial && CivHostPlugins()[i].module)
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

void CivCallsLogCrash(const void* owner)
{
	const std::vector<std::string> lines = CivCrashReport(owner);
	for (size_t i = 0; i < lines.size(); ++i)
		CivHostLog("%s", lines[i].c_str());
}

bool CivCallsHook(const CivHookEntry* e, int hookId, CivHookThunk thunk, void* ctx)
{
	static_cast<CivHookCtx*>(ctx)->fn = e->fn;
	unsigned int code = 0;
	if (GuardedCall(thunk, ctx, &code))
		return true;
	Quarantine(e->plugin, false, CivHookName(hookId), &code);
	return false;
}

// No C++ objects may live in this frame, or __try is not allowed.
bool CivCallsEntry(CivEntryCall* call, unsigned int* code)
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

int CivCallsEntryPlugin()
{
	return s_loadingPlugin;
}

const CivPluginInfo* CivCallsEntryInfo()
{
	return s_loadingInfo;
}

bool CivCallsShutDown(int plugin)
{
	const CivPluginRecord& rec = CivHostRecord(plugin);
	CivPluginShutdownFn shutdown = (CivPluginShutdownFn)GetProcAddress((HMODULE)rec.module, CIV_PLUGIN_SHUTDOWN_NAME);
	unsigned int code = 0;
	if (!shutdown || GuardedCall(&ShutdownThunk, &shutdown, &code))
		return true;
	Quarantine(plugin, true, "its shutdown function", &code);
	return false;
}

// Plugins unload bottom-up without being turned off, so a shutdown function could reach one already freed but for
// the module check; a plugin kept in memory calls with index -1 and numbers from before a reload.
bool CivCallsFunction(int plugin, int function, CivFunctionRunner run, void* args)
{
	int owner = -1;
	void* fn = 0;
	if (!run || !CivHostAlive(plugin) || !CivFunctionsGet(function, &owner, &fn) || !CivHostAlive(owner) || !CivHostRecord(owner).module)
		return false;
	FunctionCall c = { run, fn, args };
	unsigned int code = 0;
	if (GuardedCall(&FunctionCallThunk, &c, &code))
		return true;
	Quarantine(owner, false, CivHostFormat("its function %s, which %s called", CivFunctionsName(function), CivHostPluginName(plugin)).c_str(),
		&code);
	return false;
}

bool CivCallsWriteSave(void* saving, const void* data, int size)
{
	if (!saving || saving != CurrentSaveToken())
		return false;
	if (data && size > 0)
		s_saving->append(static_cast<const char*>(data), size);
	return true;
}

bool CivCallsRunning()
{
	return s_pluginCallDepth > 0;
}

void CivHostSetFaultSink(CivHostFaultSink sink)
{
	s_faultSink = sink;
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
	if (!CivHostAlive(plugin))
	{
		_snprintf_s(why, whySize, _TRUNCATE, "%s was turned off after a crash, so its Lua functions no longer run.",
			CivHostRecord(plugin).name.c_str());
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
	_snprintf_s(why, whySize, _TRUNCATE, "%s stopped working in a Lua function and was turned off.", CivHostRecord(plugin).name.c_str());
	return false;
}

bool CivHostGameMayBeDamaged()
{
	return s_gameMayBeDamaged;
}

void CivHostForgetGameDamage()
{
	s_gameMayBeDamaged = false;
}

bool CivHostCallSaveFunction(int plugin, std::string* data)
{
	data->clear();
	if (!CivHostAlive(plugin) || !CivHostRecord(plugin).saveFn)
		return false;
	SaveCall call = { CivHostRecord(plugin).saveFn, 0 };
	unsigned int code = 0;
	if (GuardedSave(&call, data, &code))
		return true;
	data->clear();
	Quarantine(plugin, false, "its save function", &code);
	return false;
}

void CivHostCallLoadFunction(int plugin, const std::string* data)
{
	if (!CivHostAlive(plugin) || !CivHostRecord(plugin).loadFn)
		return;
	const bool none = !data || data->empty();
	LoadCall call = { CivHostRecord(plugin).loadFn, none ? 0 : data->data(), none ? 0 : (int)data->size() };
	unsigned int code = 0;
	if (!GuardedCall(&LoadThunk, &call, &code))
		Quarantine(plugin, false, "its load function", &code);
}
