#pragma once

// The contract between the host and plugin DLLs. Structures here only ever grow at the end.

#define CIV_HOST_API_MAJOR 0
#define CIV_HOST_API_MINOR 2

class CvUnit;

enum CivHookKind
{
	CIV_HOOK_BEFORE = 0,
	CIV_HOOK_AFTER = 1,
	// A replacement gets the original function as its first argument; calling it runs the engine's own version.
	CIV_HOOK_REPLACE = 2,
};

enum CivHookRegisterResult
{
	CIV_HOOK_OK = 0,
	CIV_HOOK_BAD_ID = 1, // an unknown hook id, or no function given
	CIV_HOOK_BAD_KIND = 2,
	CIV_HOOK_REPLACE_TAKEN = 3,
	CIV_HOOK_NOT_ALLOWED = 4,
};

// Hand-placed hooks: spots inside engine functions, registered with RegisterHandHook. Each takes the function type named
// beside it, and plugins are called in load order. Ids only ever grow at the end.
enum CivHandHook
{
	// CivPlayerQueryFn: does a plugin play this player, rather than the person at the keyboard? Any yes wins.
	CIV_HAND_IS_PLUGIN_CONTROLLED_PLAYER = 0,
	// CivPlayerQueryFn: should this player's slot stay open now that they have been eliminated? Any yes wins.
	CIV_HAND_KEEP_DEAD_SLOT_OPEN = 1,
	// CivPopupRaisedFn: the game raised a popup for this player, or would have if they were at the keyboard.
	CIV_HAND_POPUP_RAISED = 2,
	// CivNotificationAddedFn: a notification was added to this player's list.
	CIV_HAND_NOTIFICATION_ADDED = 3,
	// CivDealResolvedFn: a proposed deal was accepted or turned down.
	CIV_HAND_DEAL_RESOLVED = 4,
	// CivUnitOrdersCancelledFn: the game cancelled a unit's orders, for one of the CivOrdersCancelledReason reasons.
	CIV_HAND_UNIT_ORDERS_CANCELLED = 5,
	// Not a hook: one more than the last id this header knows.
	CIV_HAND_HOOK_COUNT,
};

enum CivOrdersCancelledReason
{
	CIV_ORDERS_PROMOTION_READY = 0,
	CIV_ORDERS_CANNOT_LAND = 1,
	CIV_ORDERS_NO_ROUTE_TO_BUILD = 2,
	CIV_ORDERS_ROUTE_BLOCKED = 3,
	CIV_ORDERS_NO_PATH = 4,
	// The way there now takes more than two turns longer than when the move began.
	CIV_ORDERS_PATH_LONGER = 5,
	CIV_ORDERS_DESTINATION_BLOCKED = 6,
};

typedef bool (*CivPlayerQueryFn)(int player);
// What the values mean depends on the popup; docs/hand-placed-hooks.md lists them.
typedef void (*CivPopupRaisedFn)(int player, int popupType, int data1, int data2, int data3, bool option1, bool option2, const char* text);
typedef void (*CivNotificationAddedFn)(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2);
typedef void (*CivDealResolvedFn)(int fromPlayer, int toPlayer, int actingPlayer, bool accepted, bool finalized);
typedef void (*CivUnitOrdersCancelledFn)(CvUnit* unit, int reason);

struct CivHostInfo
{
	int apiMajor;
	int apiMinor;
	int pluginIndex;
	int (*RegisterHook)(int pluginIndex, int hookId, int kind, void* fn);
	void (*Log)(int pluginIndex, const char* message);
	// API 0.2: an older host's structure ends before this field, so check apiMinor first.
	int (*RegisterHandHook)(int pluginIndex, int handHook, void* fn);
};

struct CivPluginInfo
{
	const char* name;
	const char* version;
	int builtApiMajor;
	int builtApiMinor;
};

typedef bool (*CivPluginEntryFn)(const CivHostInfo* host, CivPluginInfo* plugin);
typedef void (*CivPluginShutdownFn)();

#define CIV_PLUGIN_ENTRY_NAME "CivPluginEntry"
// Optional, for anything your plugin holds outside the host (threads, sockets, files); the host removes your hooks itself.
// If your plugin crashes or is refused for any reason, it still needs to be shut down, so it needs to be able to shut down from a partially-loaded state.
// If one of your threads is still running after it returns, your DLL stays in memory until Civilization V restarts.
#define CIV_PLUGIN_SHUTDOWN_NAME "CivPluginShutdown"
