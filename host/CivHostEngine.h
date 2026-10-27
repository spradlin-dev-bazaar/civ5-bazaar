#pragma once

#include "CivHostHand.h"

#include <vector>

struct lua_State;
class FDataStream;

// The places the engine calls into the host.
void CivHostOnDatabaseReady();
void CivHostOnGameUpdate();
void CivHostOnEngineShutdown();
void CivHostOnNewGame();
// The version of CvGame's supporting data from which Bazaar's part follows it, last in a save, so every player, city,
// unit and plot exists when it is read.
#define CIV_HOST_SAVE_VERSION 2
void CivHostOnWriteSave(FDataStream& stream);
void CivHostOnReadSave(FDataStream& stream, unsigned int version);
void CivHostOnPlayerReset(int player);
// Front-end Lua has no other way into the DLL, so the Plugins screen calls UI.GetMapPreview("bazaar:<request>", ...),
// which the engine passes here first. True, with the number of results pushed, when the call was for the host.
bool CivHostOnFrontEndCall(lua_State* L, int* results);
// The living players on a team, for the hand-placed hooks the engine calls for a team.
std::vector<int> CivHostTeamPlayers(int team);
