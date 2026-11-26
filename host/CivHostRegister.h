#pragma once

#include "CivPluginApi.h"

// Pushes a Lua function that hands serial, fn and its own lua_State to CivHostCallLuaFunction.
typedef void (*CivHostLuaPusher)(lua_State* L, unsigned int serial, CivLuaFunction fn);

// Set before plugins load: without a pusher, PushLuaFunction pushes nothing.
void CivHostSetLuaPusher(CivHostLuaPusher pusher);

CivHostInfo* CivRegisterNewHostInfo(int plugin);
void CivRegisterFreeHostInfo(CivHostInfo* host);
void CivRegisterCommit(int plugin);
void CivRegisterDiscard();
bool CivRegisterPendingSave();
// Called once every plugin has unloaded.
void CivRegisterForgetStrayWrites();
