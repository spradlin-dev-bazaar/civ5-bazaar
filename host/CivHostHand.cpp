#include "CivHostHand.h"
#include "CivHostHooks.h"
#include "CivHostValues.h"
#include "CivPluginApi.h"

const int g_CivHandHookCount = CIV_HAND_HOOK_COUNT;
CivHookPoint g_CivHandHookPoints[CIV_HAND_HOOK_COUNT];

// A hook added to CivHandHook without a case here fails the build.
#pragma warning(push)
#pragma warning(error : 4062)
const char* CivHandHookName(int handHook)
{
	switch (static_cast<CivHandHook>(handHook))
	{
	case CIV_HAND_IS_PLUGIN_CONTROLLED_PLAYER:
		return "IsPluginControlledPlayer";
	case CIV_HAND_KEEP_DEAD_SLOT_OPEN:
		return "KeepDeadSlotOpen";
	case CIV_HAND_POPUP_RAISED:
		return "PopupRaised";
	case CIV_HAND_NOTIFICATION_ADDED:
		return "NotificationAdded";
	case CIV_HAND_DEAL_RESOLVED:
		return "DealResolved";
	case CIV_HAND_UNIT_ORDERS_CANCELLED:
		return "UnitOrdersCancelled";
	case CIV_HAND_UNIT_REPLACED:
		return "UnitReplaced";
	case CIV_HAND_CITY_REPLACED:
		return "CityReplaced";
	case CIV_HAND_HOOK_COUNT:
		break;
	}
	return "?";
}
#pragma warning(pop)

namespace
{
	// The same shape as a generated hook's context: CivHookRunBefore reaches civ_h through a void*.
	struct PlayerQuery
	{
		CivHookCtx civ_h;
		int player;

		static void Ask(void* p)
		{
			PlayerQuery& c = *static_cast<PlayerQuery*>(p);
			c.civ_h.veto = reinterpret_cast<CivPlayerQueryFn>(c.civ_h.fn)(c.player);
		}
	};

	// A before list stops at the first veto, so a yes ends the question.
	bool AnyYes(int handHook, int player)
	{
		const CivHookPoint& hp = g_CivHandHookPoints[handHook];
		if (!hp.before)
			return false;
		PlayerQuery c = { { 0, false }, player };
		return CivHookRunBefore(hp, CivHandHookId(handHook), &PlayerQuery::Ask, &c);
	}

	// Announcement thunks never set veto, so every plugin hears it.
	void Announce(int handHook, CivHookThunk thunk, void* ctx)
	{
		const CivHookPoint& hp = g_CivHandHookPoints[handHook];
		if (hp.before)
			CivHookRunBefore(hp, CivHandHookId(handHook), thunk, ctx);
	}

	struct Popup
	{
		CivHookCtx civ_h;
		int player;
		int popupType;
		int data1;
		int data2;
		int data3;
		bool option1;
		bool option2;
		const char* text;

		static void Tell(void* p)
		{
			Popup& c = *static_cast<Popup*>(p);
			reinterpret_cast<CivPopupRaisedFn>(c.civ_h.fn)(c.player, c.popupType, c.data1, c.data2, c.data3, c.option1, c.option2, c.text);
		}
	};

	struct Notification
	{
		CivHookCtx civ_h;
		int player;
		int notificationType;
		const char* message;
		const char* summary;
		int x;
		int y;
		int data1;
		int data2;

		static void Tell(void* p)
		{
			Notification& c = *static_cast<Notification*>(p);
			reinterpret_cast<CivNotificationAddedFn>(c.civ_h.fn)(c.player, c.notificationType, c.message, c.summary, c.x, c.y, c.data1, c.data2);
		}
	};

	struct Deal
	{
		CivHookCtx civ_h;
		int fromPlayer;
		int toPlayer;
		int actingPlayer;
		bool accepted;
		bool finalized;

		static void Tell(void* p)
		{
			Deal& c = *static_cast<Deal*>(p);
			reinterpret_cast<CivDealResolvedFn>(c.civ_h.fn)(c.fromPlayer, c.toPlayer, c.actingPlayer, c.accepted, c.finalized);
		}
	};

	struct OrdersCancelled
	{
		CivHookCtx civ_h;
		CvUnit* unit;
		int reason;

		static void Tell(void* p)
		{
			OrdersCancelled& c = *static_cast<OrdersCancelled*>(p);
			reinterpret_cast<CivUnitOrdersCancelledFn>(c.civ_h.fn)(c.unit, c.reason);
		}
	};

	struct UnitReplaced
	{
		CivHookCtx civ_h;
		int oldOwner;
		int oldUnit;
		CvUnit* newUnit;

		static void Tell(void* p)
		{
			UnitReplaced& c = *static_cast<UnitReplaced*>(p);
			reinterpret_cast<CivUnitReplacedFn>(c.civ_h.fn)(c.oldOwner, c.oldUnit, c.newUnit);
		}
	};

	struct CityReplaced
	{
		CivHookCtx civ_h;
		int oldOwner;
		int oldCity;
		CvCity* newCity;

		static void Tell(void* p)
		{
			CityReplaced& c = *static_cast<CityReplaced*>(p);
			reinterpret_cast<CivCityReplacedFn>(c.civ_h.fn)(c.oldOwner, c.oldCity, c.newCity);
		}
	};

	struct CapturedFrom
	{
		int owner;
		int unit;
		bool taken;
	};

	std::vector<CapturedFrom> s_capturedFrom;

	const char* Text(const char* text)
	{
		return text ? text : "";
	}
}

bool CivHandIsPluginControlledPlayer(int player)
{
	return AnyYes(CIV_HAND_IS_PLUGIN_CONTROLLED_PLAYER, player);
}

bool CivHandKeepDeadSlotOpen(int player)
{
	return AnyYes(CIV_HAND_KEEP_DEAD_SLOT_OPEN, player);
}

void CivHandPopupRaised(int player, int popupType, int data1, int data2, int data3, bool option1, bool option2, const char* text)
{
	Popup c = { { 0, false }, player, popupType, data1, data2, data3, option1, option2, Text(text) };
	Announce(CIV_HAND_POPUP_RAISED, &Popup::Tell, &c);
}

void CivHandPopupRaised(const std::vector<int>& players, int popupType, int data1, int data2, int data3, bool option1, bool option2,
	const char* text)
{
	for (size_t i = 0; i < players.size(); ++i)
		CivHandPopupRaised(players[i], popupType, data1, data2, data3, option1, option2, text);
}

void CivHandNotificationAdded(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2)
{
	Notification c = { { 0, false }, player, notificationType, Text(message), Text(summary), x, y, data1, data2 };
	Announce(CIV_HAND_NOTIFICATION_ADDED, &Notification::Tell, &c);
}

void CivHandDealResolved(int fromPlayer, int toPlayer, int actingPlayer, bool accepted, bool finalized)
{
	Deal c = { { 0, false }, fromPlayer, toPlayer, actingPlayer, accepted, finalized };
	Announce(CIV_HAND_DEAL_RESOLVED, &Deal::Tell, &c);
}

void CivHandUnitOrdersCancelled(CvUnit* unit, int reason)
{
	OrdersCancelled c = { { 0, false }, unit, reason };
	Announce(CIV_HAND_UNIT_ORDERS_CANCELLED, &OrdersCancelled::Tell, &c);
}

void CivHandUnitReplaced(int oldOwner, int oldUnit, CvUnit* newUnit)
{
	CivValuesReplaced(CIV_ON_UNIT, CivObjectKey(oldOwner, oldUnit), newUnit);
	UnitReplaced c = { { 0, false }, oldOwner, oldUnit, newUnit };
	Announce(CIV_HAND_UNIT_REPLACED, &UnitReplaced::Tell, &c);
}

void CivHandCityReplaced(int oldOwner, int oldCity, CvCity* newCity)
{
	CivValuesReplaced(CIV_ON_CITY, CivObjectKey(oldOwner, oldCity), newCity);
	CityReplaced c = { { 0, false }, oldOwner, oldCity, newCity };
	Announce(CIV_HAND_CITY_REPLACED, &CityReplaced::Tell, &c);
}

void CivHostCaptureFrom(int owner, int unit)
{
	CapturedFrom from = { owner, unit, false };
	s_capturedFrom.push_back(from);
}

bool CivHostTakeCapturedFrom(int* owner, int* unit)
{
	if (s_capturedFrom.empty() || s_capturedFrom.back().taken)
		return false;
	CapturedFrom& from = s_capturedFrom.back();
	*owner = from.owner;
	*unit = from.unit;
	from.taken = true;
	return true;
}

void CivHostCaptureDone()
{
	if (!s_capturedFrom.empty())
		s_capturedFrom.pop_back();
}
