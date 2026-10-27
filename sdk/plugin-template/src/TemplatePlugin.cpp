#include "CvGameCoreDLLPCH.h"

#include "CivHooks.h"
#include "CivPluginApi.h"
#include "PluginVersion.h"

#include <stdarg.h>
#include <stdio.h>

#define PLUGIN_EXPORT extern "C" __declspec(dllexport)

CIV_PLUGIN_EXPORT_API_VERSION;

static const CivHostInfo* s_host = 0;
// Both are kept in saved games: a value on every player, and data of the plugin's own.
static CivValue<CvPlayer, int> s_turnsStarted;
static int s_notifications = 0;

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
	s_turnsStarted.Set(player, s_turnsStarted.Get(player) + 1);
	if (player->isHuman())
		Log("%s starts turn %d with %d gold (turns started: %d, notifications seen: %d)", player->getCivilizationShortDescription(),
			GC.getGame().getGameTurn(), player->GetTreasury()->GetGold(), s_turnsStarted.Get(player), s_notifications);
	return false;
}

static void NotificationAdded(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2,
	int lookupIndex)
{
	++s_notifications;
	Log("notification %d for %s: %s", notificationType, GET_PLAYER((PlayerTypes)player).getCivilizationShortDescription(), message);
}

static int Hello(lua_State* L)
{
	lua_pushstring(L, "Hello from the template plugin");
	return 1;
}

// Runs at every save, one of them on another thread, so it must not use Lua.
static void SaveData(void* saving)
{
	CivSaveWriter writer(s_host, saving);
	writer.WriteInt(s_notifications);
}

// Runs when a game starts or a save loads; data is null when there is none.
static void LoadData(const void* data, int size)
{
	CivSaveReader reader(data, size);
	s_notifications = reader.ReadInt(0);
}

// The Game table is on top of the Lua stack while its methods are registered.
static void AfterRegisterGame(lua_State* L)
{
	s_host->PushLuaFunction(s_host->pluginIndex, L, &Hello);
	lua_setfield(L, -2, "TemplateHello");
}

PLUGIN_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* plugin)
{
	s_host = host;
	plugin->name = "Template Plugin";
	plugin->version = PLUGIN_VERSION;
	Check(CivRegisterBefore<CivHooks::CvPlayer_doTurn>(host, &BeforeDoTurn), "before CvPlayer::doTurn");
	Check(host->RegisterHandHook(host->pluginIndex, CIV_HAND_NOTIFICATION_ADDED, (void*)&NotificationAdded), "NotificationAdded");
	Check(CivRegisterAfter<CivHooks::CvLuaGame_RegisterMembers>(host, &AfterRegisterGame), "after CvLuaGame::RegisterMembers");
	Check(host->RegisterSaveData(host->pluginIndex, &SaveData, &LoadData), "save data");
	if (!s_turnsStarted.Declare(host, "TurnsStarted", 0, CIV_VALUE_PUBLISHED))
		Log("could not declare the value TurnsStarted");
	return true;
}

PLUGIN_EXPORT void CivPluginShutdown()
{
	Log("shutting down");
}
