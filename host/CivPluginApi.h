#pragma once

// The contract between the host and plugin DLLs. From 1.0 on, structures here only grow at the end, except CivApiVersion, which never changes.

#ifdef _UNICODE
#error Set your project's Character Set to Use Multi-Byte Character Set, as Bazaar's is.
#endif

#define CIV_HOST_API_MAJOR 0
#define CIV_HOST_API_MINOR 4

class CvUnit;

enum CivHookKind
{
	// Returning true vetoes the call: the caller gets what the before-hooks left in the result, and the after-hooks
	// still run.
	CIV_HOOK_BEFORE = 0,
	// Runs after the function, or after a veto, and may change the result.
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
// What the values mean depends on the popup; hand-placed-hooks.md lists them.
typedef void (*CivPopupRaisedFn)(int player, int popupType, int data1, int data2, int data3, bool option1, bool option2, const char* text);
typedef void (*CivNotificationAddedFn)(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2);
typedef void (*CivDealResolvedFn)(int fromPlayer, int toPlayer, int actingPlayer, bool accepted, bool finalized);
typedef void (*CivUnitOrdersCancelledFn)(CvUnit* unit, int reason);

struct lua_State;
typedef int (*CivLuaFunction)(lua_State* L);

struct CivHostInfo
{
	int pluginIndex;
	// Only from CivPluginEntry. fn must have the exact type CivHooks.h gives the hook point for that kind; the typed
	// CivRegisterBefore, CivRegisterAfter and CivRegisterReplace below make the compiler check it.
	int (*RegisterHook)(int pluginIndex, int hookId, int kind, void* fn);
	void (*Log)(int pluginIndex, const char* message);
	int (*RegisterHandHook)(int pluginIndex, int handHook, void* fn);
	// Pushes exactly one value onto L's stack: fn as a Lua function that runs inside Bazaar's crash guard. Once the
	// plugin is off, or unloaded, calling it raises a Lua error instead.
	void (*PushLuaFunction)(int pluginIndex, lua_State* L, CivLuaFunction fn);
};

// The result parameter of a before-hook or after-hook on a function returning R: a reference to the value the caller
// gets, or, for a function returning a reference, to a pointer to it.
template<class R> struct CivHookSlot { typedef R& Type; };
template<class T> struct CivHookSlot<const T> { typedef T& Type; };
template<class T> struct CivHookSlot<T&> { typedef T*& Type; };

// Hook is a hook point from CivHooks.h, such as CivHooks::CvPlayer_GetScore. A hook whose type does not match fails to
// compile.
template<class Hook> int CivRegisterBefore(const CivHostInfo* host, typename Hook::Before hook)
{
	return host->RegisterHook(host->pluginIndex, Hook::ID, CIV_HOOK_BEFORE, (void*)hook);
}

template<class Hook> int CivRegisterAfter(const CivHostInfo* host, typename Hook::After hook)
{
	return host->RegisterHook(host->pluginIndex, Hook::ID, CIV_HOOK_AFTER, (void*)hook);
}

template<class Hook> int CivRegisterReplace(const CivHostInfo* host, typename Hook::Replace hook)
{
	return host->RegisterHook(host->pluginIndex, Hook::ID, CIV_HOOK_REPLACE, (void*)hook);
}

struct CivPluginInfo
{
	const char* name;
	const char* version;
};

// Never changes, nor does its export name, and holds no pointers: every Bazaar reads it from plugin files of every
// version without loading them.
struct CivApiVersion
{
	int major;
	int minor;
};

// Write CIV_PLUGIN_EXPORT_API_VERSION; once, outside any function, in one of your plugin's .cpp files. Bazaar reads it
// from the plugin's file before running any of its code, and refuses a plugin built for a newer Bazaar or another major.
#define CIV_PLUGIN_API_VERSION_NAME "CivPluginApiVersion"
#define CIV_PLUGIN_EXPORT_API_VERSION \
	extern "C" __declspec(dllexport) const CivApiVersion CivPluginApiVersion = {CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR}

typedef bool (*CivPluginEntryFn)(const CivHostInfo* host, CivPluginInfo* plugin);
typedef void (*CivPluginShutdownFn)();

#define CIV_PLUGIN_ENTRY_NAME "CivPluginEntry"
// Optional, for anything your plugin holds outside the host (threads, sockets, files); the host removes your hooks itself.
// If your plugin crashes or is refused after its entry function ran, it still needs to be shut down, so it needs to be able to shut down from a partially-loaded state.
// If one of your threads is still running inside your DLL after it returns, your DLL stays in memory until Civilization V restarts.
// Threads in other DLLs your plugin loaded are not checked, so stop them too.
#define CIV_PLUGIN_SHUTDOWN_NAME "CivPluginShutdown"
