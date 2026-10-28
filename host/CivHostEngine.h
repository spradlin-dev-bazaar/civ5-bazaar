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
// False from a plugin's crash until the player is back at the main menu, so the game saves nothing it may have damaged.
bool CivHostSavingAllowed();
void CivHostOnPlayerReset(int player);
// Front-end Lua has no other way into the DLL, so the Plugins screen, and the handler Bazaar sets up to run after Next, call
// UI.GetMapPreview("bazaar:<request>", ...), which the engine passes here first. True, with the number of results pushed, when the
// call was for the host.
bool CivHostOnFrontEndCall(lua_State* L, int* results);
// Game.GetPluginValue(modId, pluginId, name, first, second): a value a plugin published, or nil when no loaded plugin
// publishes one of that name or the object does not exist. first and second name the object: a player's ID and 0, a
// city's or unit's owner and ID, or a plot's x and y. Whole numbers and true or false come back as Lua numbers, exact
// up to 2 to the power 53.
int CivHostLuaGetPluginValue(lua_State* L);
// The living players on a team, for the hand-placed hooks the engine calls for a team.
std::vector<int> CivHostTeamPlayers(int team);
