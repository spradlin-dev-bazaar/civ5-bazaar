#include "CvGameCoreDLLPCH.h"

#include "CivHooks.h"
#include "CivPluginApi.h"
#include "PluginVersion.h"

#include <stdarg.h>
#include <stdio.h>

#define PLUGIN_EXPORT extern "C" __declspec(dllexport)

CIV_PLUGIN_EXPORT_API_VERSION;

static const CivHostInfo* s_host = 0;

// Writes a line to Logs\Bazaar.log, headed with this plugin's name.
static void Log(const char* format, ...)
{
	char line[512];
	va_list args;
	va_start(args, format);
	_vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
	va_end(args);
	s_host->Log(s_host->pluginIndex, line);
}

static void Check(int result, const char* hook)
{
	if (result != CIV_HOOK_OK)
		Log("could not register %s (result %d)", hook, result);
}

// Runs before CvPlayer::doTurn. Returning true would skip the function.
static bool BeforeDoTurn(CvPlayer* player)
{
	if (player->isHuman())
		Log("%s starts turn %d with %d gold", player->getCivilizationShortDescription(), GC.getGame().getGameTurn(), player->GetTreasury()->GetGold());
	return false;
}

static void NotificationAdded(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2)
{
	Log("notification %d for %s: %s", notificationType, GET_PLAYER((PlayerTypes)player).getCivilizationShortDescription(), message);
}

static int Hello(lua_State* L)
{
	lua_pushstring(L, "Hello from the template plugin");
	return 1;
}

// The Game table is on top of the Lua stack while its methods are registered.
static void AfterRegisterGame(lua_State* L)
{
	lua_pushcclosure(L, &Hello, 0);
	lua_setfield(L, -2, "TemplateHello");
}

PLUGIN_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* plugin)
{
	s_host = host;
	plugin->name = "Template Plugin";
	plugin->version = PLUGIN_VERSION;
	Check(host->RegisterHook(host->pluginIndex, CivHooks::CvPlayer_doTurn::ID, CIV_HOOK_BEFORE, (void*)&BeforeDoTurn), "before CvPlayer::doTurn");
	Check(host->RegisterHandHook(host->pluginIndex, CIV_HAND_NOTIFICATION_ADDED, (void*)&NotificationAdded), "NotificationAdded");
	Check(host->RegisterHook(host->pluginIndex, CivHooks::CvLuaGame_RegisterMembers::ID, CIV_HOOK_AFTER, (void*)&AfterRegisterGame),
		"after CvLuaGame::RegisterMembers");
	return true;
}

PLUGIN_EXPORT void CivPluginShutdown()
{
	Log("shutting down");
}
