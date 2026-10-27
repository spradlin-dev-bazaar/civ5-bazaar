// Toy plugins for the in-game checks, built once per TOY_* define against the hooked host.
#include "CvGameCoreDLLPCH.h"

#include "CivHooks.h"
#include "CivPluginApi.h"

#include <stdarg.h>
#include <stdio.h>

#define TOY_EXPORT extern "C" __declspec(dllexport)

#if defined(TOY_NEWER)
TOY_EXPORT const CivApiVersion CivPluginApiVersion = {CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR + 1};
#else
CIV_PLUGIN_EXPORT_API_VERSION;
#endif

static const CivHostInfo* s_host = 0;

static void Log(const char* format, ...)
{
	char line[512];
	va_list args;
	va_start(args, format);
	_vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
	va_end(args);
	s_host->Log(s_host->pluginIndex, line);
}

static void Describe(CivPluginInfo* info, const char* name)
{
	info->name = name;
	info->version = "1.0";
}

typedef int (*ScoreFn)(const CvPlayer*, bool, bool);

static void LogRegistered(int result, const char* what)
{
	Log("registered %s: %s", what, result == CIV_HOOK_OK ? "ok" : "refused");
}

#if defined(TOY_GOLD)

static bool BeforeDoTurn(CvPlayer* self)
{
	if (self->isHuman())
		Log("turn starting for %s with %d gold", self->getCivilizationShortDescription(), self->GetTreasury()->GetGold());
	return false;
}

static void AfterDoTurn(CvPlayer* self)
{
	if (self->isHuman())
		Log("turn finished for %s with %d gold", self->getCivilizationShortDescription(), self->GetTreasury()->GetGold());
}

static int ReplaceScore(ScoreFn original, const CvPlayer* self, bool bFinal, bool bVictory)
{
	return self->isHuman() ? 4242 : original(self, bFinal, bVictory);
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Gold");
	LogRegistered(CivRegisterBefore<CivHooks::CvPlayer_doTurn>(s_host, &BeforeDoTurn), "before CvPlayer::doTurn");
	LogRegistered(CivRegisterAfter<CivHooks::CvPlayer_doTurn>(s_host, &AfterDoTurn), "after CvPlayer::doTurn");
	LogRegistered(CivRegisterReplace<CivHooks::CvPlayer_GetScore>(s_host, &ReplaceScore), "replace CvPlayer::GetScore");
	return true;
}

TOY_EXPORT void CivPluginShutdown()
{
	Log("shutting down");
}

#elif defined(TOY_RIVAL)

static int ReplaceScore(ScoreFn, const CvPlayer*, bool, bool)
{
	return 1;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Rival");
	LogRegistered(CivRegisterReplace<CivHooks::CvPlayer_GetScore>(s_host, &ReplaceScore), "replace CvPlayer::GetScore");
	return true;
}

#elif defined(TOY_CRASH)

static void AfterDoTurn(CvPlayer* self)
{
	if (self->isHuman())
	{
		int* volatile nowhere = 0;
		*nowhere = self->GetTreasury()->GetGold();
	}
}

// For the tester to call from FireTuner, so the crash comes from Lua rather than from a turn.
static int CrashFromLua(lua_State* L)
{
	int* volatile nowhere = 0;
	return *nowhere;
}

static void AfterRegisterGame(lua_State* L)
{
	s_host->PushLuaFunction(s_host->pluginIndex, L, &CrashFromLua);
	lua_setfield(L, -2, "ToyCrashLua");
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Crash");
	LogRegistered(CivRegisterAfter<CivHooks::CvPlayer_doTurn>(s_host, &AfterDoTurn), "after CvPlayer::doTurn");
	LogRegistered(CivRegisterAfter<CivHooks::CvLuaGame_RegisterMembers>(s_host, &AfterRegisterGame), "after CvLuaGame::RegisterMembers");
	return true;
}

#elif defined(TOY_NEWER)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Newer");
	Log("this ran, so Bazaar did not refuse it by its version first");
	return true;
}

#elif defined(TOY_HAND)

static void RegisterHand(int handHook, void* fn, const char* what)
{
	const int result = s_host->RegisterHandHook(s_host->pluginIndex, handHook, fn);
	Log("registered %s: %s", what, result == CIV_HOOK_OK ? "ok" : "refused");
}

static bool s_askedAboutPlayer = false;

// Asked for every unit with moves left when a turn ends, so logged once.
static bool PlaysPlayer(int player)
{
	if (!s_askedAboutPlayer)
		Log("asked whether a plugin plays player %d", player);
	s_askedAboutPlayer = true;
	return false;
}

static bool KeepsSlot(int player)
{
	Log("asked whether to keep the slot of eliminated player %d open", player);
	return false;
}

static void HeardPopup(int player, int popupType, int data1, int data2, int data3, bool option1, bool option2, const char* text)
{
	Log("popup %d for player %d: %d %d %d %d %d [%s]", popupType, player, data1, data2, data3, option1, option2, text);
}

static void HeardNotification(int player, int, const char* message, const char*, int, int, int, int)
{
	Log("notification for player %d: %s", player, message);
}

static void HeardDeal(int fromPlayer, int toPlayer, int actingPlayer, bool accepted, bool finalized)
{
	Log("deal from player %d to player %d, answered by player %d: accepted %d, finalized %d", fromPlayer, toPlayer, actingPlayer, accepted, finalized);
}

static void HeardOrdersCancelled(CvUnit* unit, int reason)
{
	Log("orders cancelled for %s of player %d, reason %d", unit->getName().c_str(), unit->getOwner(), reason);
}

static int Ping(lua_State* L)
{
	lua_pushstring(L, "Toy Hand added this to the Game table");
	return 1;
}

static int Raise(lua_State* L)
{
	return luaL_error(L, "Toy Hand raised this Lua error on purpose");
}

// The Game table is on top of the stack while its methods are registered.
static void AfterRegisterGame(lua_State* L)
{
	s_host->PushLuaFunction(s_host->pluginIndex, L, &Ping);
	lua_setfield(L, -2, "ToyHandPing");
	s_host->PushLuaFunction(s_host->pluginIndex, L, &Raise);
	lua_setfield(L, -2, "ToyHandRaise");
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Hand");
	RegisterHand(CIV_HAND_IS_PLUGIN_CONTROLLED_PLAYER, (void*)&PlaysPlayer, "IsPluginControlledPlayer");
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&KeepsSlot, "KeepDeadSlotOpen");
	RegisterHand(CIV_HAND_POPUP_RAISED, (void*)&HeardPopup, "PopupRaised");
	RegisterHand(CIV_HAND_NOTIFICATION_ADDED, (void*)&HeardNotification, "NotificationAdded");
	RegisterHand(CIV_HAND_DEAL_RESOLVED, (void*)&HeardDeal, "DealResolved");
	RegisterHand(CIV_HAND_UNIT_ORDERS_CANCELLED, (void*)&HeardOrdersCancelled, "UnitOrdersCancelled");
	LogRegistered(CivRegisterAfter<CivHooks::CvLuaGame_RegisterMembers>(s_host, &AfterRegisterGame), "after CvLuaGame::RegisterMembers");
	return true;
}

#elif defined(TOY_HAND_REPLACE)

typedef int (*AddNotificationFn)(CvNotifications*, NotificationTypes, const char*, const char*, int, int, int, int);

static bool s_loggedAdd = false;

// Runs the game's own version, so Toy Hand still hears every notification when the two are used together.
static int ReplaceAddNotification(AddNotificationFn original, CvNotifications* self, NotificationTypes type, const char* message,
	const char* summary, int x, int y, int data1, int data2)
{
	if (!s_loggedAdd)
		Log("replaced CvNotifications::Add and ran the original");
	s_loggedAdd = true;
	return original(self, type, message, summary, x, y, data1, data2);
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Hand Replace");
	LogRegistered(CivRegisterReplace<CivHooks::CvNotifications_Add>(s_host, &ReplaceAddNotification), "replace CvNotifications::Add");
	return true;
}

#elif defined(TOY_SAVES)

// The human player's turns in this game are the plugin's own data; the rest are values. All are kept in saved games.
static int s_turns = 0;
static CivValue<CvUnit, int> s_turnsAlive;
static CivValue<CvCity, std::string> s_founder;
static CivValue<CvPlayer, __int64> s_big;
static CivValue<CvPlot, double> s_mark;

static void SaveData(void* saving)
{
	CivSaveWriter writer(s_host, saving);
	writer.WriteInt(s_turns);
	Log("saved: %d turns", s_turns);
}

static void LoadData(const void* data, int size)
{
	CivSaveReader reader(data, size);
	s_turns = reader.ReadInt(0);
	Log(data ? "loaded: %d turns" : "no saved data: %d turns", s_turns);
}

// Every player's units and cities get values, so a captured one shows what carried over; only the human's are logged.
static bool BeforeDoTurn(CvPlayer* self)
{
	const bool human = self->isHuman();
	int loop = 0;
	for (CvUnit* unit = self->firstUnit(&loop); unit; unit = self->nextUnit(&loop))
	{
		s_turnsAlive.Set(unit, s_turnsAlive.Get(unit) + 1);
		if (human)
			Log("unit %s (ID %d): %d turns alive", unit->getName().c_str(), unit->GetID(), s_turnsAlive.Get(unit));
	}
	for (CvCity* city = self->firstCity(&loop); city; city = self->nextCity(&loop))
	{
		if (s_founder.Get(city).empty())
			s_founder.Set(city, self->getCivilizationShortDescription());
		if (human)
			Log("city %s (ID %d): founded by %s", city->getName().c_str(), city->GetID(), s_founder.Get(city).c_str());
	}
	if (!human)
		return false;
	++s_turns;
	// 2 to the power 53, plus 1: exact in C++, the smallest whole number a Lua number cannot hold.
	s_big.Set(self, 9007199254740993LL);
	CvCity* capital = self->getCapitalCity();
	if (capital)
		s_mark.Set(capital->plot(), s_mark.Get(capital->plot()) + 1.5);
	Log("turn %d of this game for %s; capital tile mark %.1f, big %I64d", s_turns, self->getCivilizationShortDescription(),
		capital ? s_mark.Get(capital->plot()) : 0.0, s_big.Get(self));
	return false;
}

static void UnitReplaced(int oldOwner, int oldUnit, CvUnit* newUnit)
{
	Log("unit replaced: player %d's unit %d is now %s (ID %d) of player %d, %d turns alive", oldOwner, oldUnit,
		newUnit->getName().c_str(), newUnit->GetID(), newUnit->getOwner(), s_turnsAlive.Get(newUnit));
}

static void CityReplaced(int oldOwner, int oldCity, CvCity* newCity)
{
	Log("city replaced: player %d's city %d is now %s (ID %d) of player %d, founded by %s", oldOwner, oldCity,
		newCity->getName().c_str(), newCity->GetID(), newCity->getOwner(), s_founder.Get(newCity).c_str());
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Saves");
	LogRegistered(host->RegisterSaveData(host->pluginIndex, &SaveData, &LoadData), "save data");
	LogRegistered(CivRegisterBefore<CivHooks::CvPlayer_doTurn>(s_host, &BeforeDoTurn), "before CvPlayer::doTurn");
	LogRegistered(host->RegisterHandHook(host->pluginIndex, CIV_HAND_UNIT_REPLACED, (void*)&UnitReplaced), "UnitReplaced");
	LogRegistered(host->RegisterHandHook(host->pluginIndex, CIV_HAND_CITY_REPLACED, (void*)&CityReplaced), "CityReplaced");
	const bool declared = s_turnsAlive.Declare(host, "TurnsAlive", 0, CIV_VALUE_PUBLISHED | CIV_VALUE_CARRIES_OVER)
		&& s_founder.Declare(host, "Founder", "", CIV_VALUE_PUBLISHED | CIV_VALUE_CARRIES_OVER)
		&& s_big.Declare(host, "Big", 0, CIV_VALUE_PUBLISHED) && s_mark.Declare(host, "Mark", 0.0, CIV_VALUE_PUBLISHED);
	Log("declared values: %s", declared ? "ok" : "refused");
	return true;
}

#else
#error Define one TOY_* variant.
#endif
