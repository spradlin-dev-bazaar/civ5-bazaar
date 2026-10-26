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

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Crash");
	LogRegistered(CivRegisterAfter<CivHooks::CvPlayer_doTurn>(s_host, &AfterDoTurn), "after CvPlayer::doTurn");
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

// The Game table is on top of the stack while its methods are registered.
static void AfterRegisterGame(lua_State* L)
{
	lua_pushcclosure(L, &Ping, 0);
	lua_setfield(L, -2, "ToyHandPing");
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

#else
#error Define one TOY_* variant.
#endif
