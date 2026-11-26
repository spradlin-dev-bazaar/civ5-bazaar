#include "CivHostCalls.h"
#include "CivHostConflicts.h"
#include "CivHostFunctions.h"
#include "CivHostHookList.h"
#include "CivHostHooks.h"
#include "CivHostRegister.h"
#include "CivHostRuntime.h"
#include "CivHostValues.h"

#include <windows.h>
#include <intrin.h>

namespace
{
	struct PendingHook
	{
		int id;
		int kind;
		void* fn;
	};

	std::vector<PendingHook> s_pending;
	CivSaveDataFn s_pendingSave = 0;
	CivLoadDataFn s_pendingLoad = 0;
	bool s_strayWriteLogged = false;
	CivHostLuaPusher s_luaPusher = 0;

	bool PendingReplace(int hookId)
	{
		for (size_t i = 0; i < s_pending.size(); ++i)
			if (s_pending[i].id == hookId && s_pending[i].kind == CIV_HOOK_REPLACE)
				return true;
		return false;
	}

	// A plugin kept in memory after a crash has the index -1 too.
	bool InEntryOf(int plugin)
	{
		return CivCallsEntryPlugin() >= 0 && plugin == CivCallsEntryPlugin();
	}

	int RegisterHandHook(int plugin, int handHook, void* fn)
	{
		if (!InEntryOf(plugin))
			return CIV_HOOK_NOT_ALLOWED;
		if (handHook < 0 || handHook >= g_CivHandHookCount || !fn)
			return CIV_HOOK_BAD_ID;
		CivConflictsOnHandHook(handHook);
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
			CivHostLog("Plugin %s asked for hook %d (%s), which this Bazaar no longer has: the function changed or is gone. Rebuild the plugin with the current SDK.",
				CivHostPluginName(plugin), hookId, g_CivHookPointNames[hookId]);
			return CIV_HOOK_BAD_ID;
		}
		if (kind < CIV_HOOK_BEFORE || kind > CIV_HOOK_REPLACE)
			return CIV_HOOK_BAD_KIND;
		if (kind == CIV_HOOK_REPLACE)
		{
			std::string problem = CivConflictsTurnAwayIfReplaced(hookId);
			if (problem.empty() && PendingReplace(hookId))
				problem = CivHostFormat("Its replacement of %s was refused: this plugin already replaces it.", CivHookShortName(hookId).c_str());
			if (!problem.empty())
			{
				CivHostRecord(plugin).problems.push_back(problem);
				CivHostLog("Plugin %s: %s", CivHostPluginName(plugin), problem.c_str());
				return CIV_HOOK_REPLACE_TAKEN;
			}
			CivConflictsOnReplace(plugin, hookId);
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

	int PublishFunction(int plugin, const char* name, const char* signature, void* fn)
	{
		std::string problem;
		int result = CIV_HOOK_BAD_ID;
		if (!InEntryOf(plugin))
		{
			problem = "it was published outside the plugin's entry function";
			result = CIV_HOOK_NOT_ALLOWED;
		}
		else if (CivFunctionsPublish(plugin, name, signature, fn, &problem))
		{
			return CIV_HOOK_OK;
		}
		CivHostLog("Plugin %s: its function %s was refused because %s.", CivHostPluginName(plugin), name ? name : "", problem.c_str());
		return result;
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
			CivHostLog("Plugin %s: its value %s was refused because %s.", CivHostPluginName(plugin), name ? name : "", problem.c_str());
		return value;
	}

	void PluginLog(int plugin, const char* message)
	{
		CivHostLog("[%s] %s", CivHostPluginName(plugin), message ? message : "");
	}

	int PluginWithCode(const void* address)
	{
		HMODULE module = 0;
		GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)address, &module);
		for (size_t i = 0; i < CivHostPlugins().size(); ++i)
			if (module && CivHostPlugins()[i].module == module)
				return (int)i;
		return -1;
	}

	void WriteSaveData(void* saving, const void* data, int size)
	{
		if (CivCallsWriteSave(saving, data, size))
			return;
		if (s_strayWriteLogged)
			return;
		s_strayWriteLogged = true;
		const int plugin = PluginWithCode(_ReturnAddress());
		CivHostLog("Plugin %s wrote save data outside its save function, or with the saving of an earlier save, so it was not saved. This is logged only once.",
			plugin < 0 ? "?" : CivHostPluginName(plugin));
	}

	// Serial 0 belongs to no plugin, so a function pushed with a wrong index refuses to run rather than unbalancing the
	// plugin's Lua stack, or getting another plugin turned off when it crashes.
	void PushLuaFunction(int plugin, lua_State* L, CivLuaFunction fn)
	{
		const int owner = PluginWithCode((const void*)fn);
		const bool own = plugin >= 0 && plugin < (int)CivHostPlugins().size() && (owner < 0 || owner == plugin);
		if (!own)
			CivHostLog("Plugin %s pushed a Lua function with plugin index %d, which is not its own, so calling it raises a Lua error.",
				owner < 0 ? "?" : CivHostPluginName(owner), plugin);
		if (s_luaPusher)
			s_luaPusher(L, own ? CivHostRecord(plugin).serial : 0, fn);
	}
}

// A plugin may keep this pointer for as long as its DLL is loaded.
CivHostInfo* CivRegisterNewHostInfo(int plugin)
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
	host->PublishFunction = &PublishFunction;
	host->FindFunction = &CivFunctionsFind;
	host->CallFunction = &CivCallsFunction;
	return host;
}

void CivRegisterFreeHostInfo(CivHostInfo* host)
{
	delete host;
}

void CivRegisterCommit(int plugin)
{
	CivValuesCommitPending(CivHostRecord(plugin).modId, CivHostRecord(plugin).pluginId);
	CivFunctionsCommitPending(CivHostRecord(plugin).modId, CivHostRecord(plugin).pluginId);
	CivHostRecord(plugin).saveFn = s_pendingSave;
	CivHostRecord(plugin).loadFn = s_pendingLoad;
	s_pendingSave = 0;
	s_pendingLoad = 0;
	for (size_t i = 0; i < s_pending.size(); ++i)
		CivHookAdd(plugin, s_pending[i].id, s_pending[i].kind, s_pending[i].fn);
	s_pending.clear();
}

void CivRegisterDiscard()
{
	s_pending.clear();
	CivConflictsForget();
	s_pendingSave = 0;
	s_pendingLoad = 0;
	CivValuesDiscardPending();
	CivFunctionsDiscardPending();
}

bool CivRegisterPendingSave()
{
	return s_pendingSave != 0;
}

void CivRegisterForgetStrayWrites()
{
	s_strayWriteLogged = false;
}

void CivHostSetLuaPusher(CivHostLuaPusher pusher)
{
	s_luaPusher = pusher;
}
