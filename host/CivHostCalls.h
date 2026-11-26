#pragma once

#include "CivHostHooks.h"
#include "CivPluginApi.h"

#include <string>

struct CivEntryCall
{
	CivPluginEntryFn entry;
	const CivHostInfo* host;
	CivPluginInfo* info;
	bool accepted;
};

typedef void (*CivHostFaultSink)(int pluginIndex, const char* pluginName, bool shuttingDown, unsigned int code);

void CivHostSetFaultSink(CivHostFaultSink sink);
// Runs a plugin's Lua function through the crash guard and gives back what it returned, a negative yield included.
// False, with why, when its plugin is off or unloaded, it was pushed with a wrong index, or it crashed. A Lua error the
// function raises passes straight through.
bool CivHostCallLuaFunction(unsigned int serial, CivLuaFunction fn, lua_State* L, int* results, char* why, size_t whySize);
// From a plugin's crash, other than one while shutting down, until CivHostForgetGameDamage, which the main menu calls.
bool CivHostGameMayBeDamaged();
void CivHostForgetGameDamage();
// False, with data empty, when the plugin has no save function, is off, or crashed in it.
bool CivHostCallSaveFunction(int plugin, std::string* data);
// A null or empty data tells the plugin there is none.
void CivHostCallLoadFunction(int plugin, const std::string* data);

bool CivCallsHook(const CivHookEntry* e, int hookId, CivHookThunk thunk, void* ctx);
bool CivCallsEntry(CivEntryCall* call, unsigned int* code);
// The plugin whose entry function is running, or -1.
int CivCallsEntryPlugin();
const CivPluginInfo* CivCallsEntryInfo();
bool CivCallsShutDown(int plugin);
bool CivCallsFunction(int plugin, int function, CivFunctionRunner run, void* args);
// False, with nothing written, unless saving is the token of the save function running now.
bool CivCallsWriteSave(void* saving, const void* data, int size);
void CivCallsLogCrash(const void* owner);
bool CivCallsRunning();
