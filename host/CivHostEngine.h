#pragma once

#include "CivHostHand.h"

#include <vector>

struct lua_State;

// The places the engine calls into the host.
void CivHostOnDatabaseReady();
void CivHostOnGameUpdate();
void CivHostOnEngineShutdown();
// Front-end Lua has no other way into the DLL, so the Plugins screen calls UI.GetMapPreview("bazaar:<request>", ...),
// which the engine passes here first. True, with the number of results pushed, when the call was for the host.
bool CivHostOnFrontEndCall(lua_State* L, int* results);
// The living players on a team, for the hand-placed hooks the engine calls for a team.
std::vector<int> CivHostTeamPlayers(int team);
