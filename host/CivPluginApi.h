#pragma once

// The contract between the host and plugin DLLs. From 0.5 on, structures here only grow at the end, except CivApiVersion, which never changes.

#ifdef _UNICODE
#error Set your project's Character Set to Use Multi-Byte Character Set, as Bazaar's is.
#endif

#define CIV_HOST_API_MAJOR 0
#define CIV_HOST_API_MINOR 4

#include <string.h>

#include <string>

class CvCity;
class CvPlayer;
class CvPlot;
class CvUnit;

enum CivHookKind
{
	// Returning true vetoes the call: the caller gets what the before-hooks left in the result, and the after-hooks
	// still run. A veto on a function that returns a reference still runs the function if no before-hook set the result.
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
// beside it, and plugins are called in load order. Ids only ever grow at the end. Later releases may also run a hook
// in more places, and pass popup types and reasons a plugin does not know yet, which it ignores.
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
	// CivUnitReplacedFn: the game made a new unit in place of an old one, which may already be gone, such as for an
	// upgrade, a gift, a capture, a civilian handed back or a barbarian that changed sides. Values that carry over are
	// already copied.
	CIV_HAND_UNIT_REPLACED = 6,
	// CivCityReplacedFn: the game made a new city in place of an old one, which is already gone, such as for a capture,
	// a gift or a liberation. Values that carry over are already copied.
	CIV_HAND_CITY_REPLACED = 7,
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
typedef void (*CivUnitReplacedFn)(int oldOwner, int oldUnit, CvUnit* newUnit);
typedef void (*CivCityReplacedFn)(int oldOwner, int oldCity, CvCity* newCity);

enum CivObjectKind
{
	CIV_ON_PLAYER = 0,
	CIV_ON_CITY = 1,
	CIV_ON_UNIT = 2,
	CIV_ON_PLOT = 3,
};

enum CivValueType
{
	CIV_VALUE_INT = 0,
	CIV_VALUE_INT64 = 1,
	CIV_VALUE_DOUBLE = 2,
	CIV_VALUE_TEXT = 3,
};

enum CivValueFlags
{
	// Other plugins, and Lua, can read it; only its own plugin can change it.
	CIV_VALUE_PUBLISHED = 1,
	// Copied to the new object when the game replaces one; see CIV_HAND_UNIT_REPLACED and CIV_HAND_CITY_REPLACED.
	CIV_VALUE_CARRIES_OVER = 2,
};

struct lua_State;
typedef int (*CivLuaFunction)(lua_State* L);

typedef void (*CivSaveDataFn)(void* saving);
typedef void (*CivLoadDataFn)(const void* data, int size);

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
	// Only from CivPluginEntry, once. save runs at every save, one of them on another thread, so it must not use Lua. load
	// runs whenever a game starts or a save loads, with data null when there is none, and replaces what the plugin held.
	int (*RegisterSaveData)(int pluginIndex, CivSaveDataFn save, CivLoadDataFn load);
	// Only inside the plugin's save function, with the saving it was given; each call adds to the data.
	void (*WriteSaveData)(void* saving, const void* data, int size);
	// Only from CivPluginEntry, with a name no other value of this plugin has. The value's number, which works once the
	// entry function has returned, or -1 when it was refused; Bazaar.log says why. start points at the starting value in
	// the value's type, or is the text itself; null starts it at zero or empty. The CivValue class below does this for you.
	int (*DeclareValue)(int pluginIndex, int objectKind, int valueType, const char* name, int flags, const void* start);
	// Another plugin's published value, or -1 when it has none of that name, or it is on another kind of object or of
	// another type. While plugins load, only the values of the plugins loaded before this one can be found.
	int (*FindValue)(int pluginIndex, const char* modId, const char* pluginId, const char* name, int objectKind, int valueType);
	// A value never set, or read on a null object, reads as its starting value. A value of the wrong type, or another
	// plugin's private one, reads as zero or empty. Only the plugin that declared a value can set it, and not on a null
	// object; Set gives back false when it did not.
	int (*GetIntValue)(int pluginIndex, int value, const void* object);
	bool (*SetIntValue)(int pluginIndex, int value, const void* object, int n);
	__int64 (*GetInt64Value)(int pluginIndex, int value, const void* object);
	bool (*SetInt64Value)(int pluginIndex, int value, const void* object, __int64 n);
	double (*GetDoubleValue)(int pluginIndex, int value, const void* object);
	bool (*SetDoubleValue)(int pluginIndex, int value, const void* object, double n);
	// Copies the text, cut short to fit, and gives back its full length, so a second call with a bigger buffer gets it all.
	int (*GetTextValue)(int pluginIndex, int value, const void* object, char* buffer, int size);
	bool (*SetTextValue)(int pluginIndex, int value, const void* object, const char* text);
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
	// Optional. Bazaar keeps a plugin's data in saves under its mod's ID and this id, so a mod with more than one plugin
	// gives each its own. Changing it, or the mod's ID, loses the data in existing saves.
	const char* id;
};

// Saves hold what these write, so how they lay out a number or a text never changes, not even in a new major version.
class CivSaveWriter
{
public:
	CivSaveWriter(const CivHostInfo* host, void* saving) : m_host(host), m_saving(saving) {}

	void Write(const void* data, int size) { m_host->WriteSaveData(m_saving, data, size); }
	void WriteInt(int value) { Write(&value, sizeof(value)); }
	void WriteText(const std::string& text)
	{
		WriteInt((int)text.size());
		Write(text.data(), (int)text.size());
	}

private:
	const CivHostInfo* m_host;
	void* m_saving;
};

// Once the data runs out or a read fails, every later read gives back its fallback, so a newer plugin can read what an
// older one saved.
class CivSaveReader
{
public:
	CivSaveReader(const void* data, int size) : m_data(static_cast<const char*>(data)), m_left(data && size > 0 ? size : 0) {}

	bool Read(void* out, int size)
	{
		if (size < 0 || size > m_left)
		{
			m_left = 0;
			return false;
		}
		memcpy(out, m_data, size);
		m_data += size;
		m_left -= size;
		return true;
	}
	int ReadInt(int fallback)
	{
		int value;
		return Read(&value, sizeof(value)) ? value : fallback;
	}
	std::string ReadText(const std::string& fallback)
	{
		const int size = ReadInt(-1);
		if (size < 0 || size > m_left)
		{
			m_left = 0;
			return fallback;
		}
		const std::string text(m_data, size);
		m_data += size;
		m_left -= size;
		return text;
	}

private:
	const char* m_data;
	int m_left;
};

template<class Object> struct CivObjectKindOf;
template<> struct CivObjectKindOf<CvPlayer> { enum { Kind = CIV_ON_PLAYER }; };
template<> struct CivObjectKindOf<CvCity> { enum { Kind = CIV_ON_CITY }; };
template<> struct CivObjectKindOf<CvUnit> { enum { Kind = CIV_ON_UNIT }; };
template<> struct CivObjectKindOf<CvPlot> { enum { Kind = CIV_ON_PLOT }; };

// Each simple type is kept in one wide enough to hold all its values, so a value reads back exactly as it was set.
// The rest, enums included, are kept in an int.
template<class T> struct CivValueStorage { typedef int Stored; };
template<> struct CivValueStorage<unsigned int> { typedef __int64 Stored; };
template<> struct CivValueStorage<unsigned long> { typedef __int64 Stored; };
template<> struct CivValueStorage<__int64> { typedef __int64 Stored; };
template<> struct CivValueStorage<unsigned __int64> { typedef __int64 Stored; };
template<> struct CivValueStorage<float> { typedef double Stored; };
template<> struct CivValueStorage<double> { typedef double Stored; };
template<> struct CivValueStorage<long double> { typedef double Stored; };
template<> struct CivValueStorage<std::string> { typedef std::string Stored; };

template<class Stored> struct CivStoredValue;
template<> struct CivStoredValue<int>
{
	enum { Type = CIV_VALUE_INT };
	static const void* Start(const int& n) { return &n; }
	static int Get(const CivHostInfo* host, int value, const void* object) { return host->GetIntValue(host->pluginIndex, value, object); }
	static bool Set(const CivHostInfo* host, int value, const void* object, int n) { return host->SetIntValue(host->pluginIndex, value, object, n); }
};
template<> struct CivStoredValue<__int64>
{
	enum { Type = CIV_VALUE_INT64 };
	static const void* Start(const __int64& n) { return &n; }
	static __int64 Get(const CivHostInfo* host, int value, const void* object) { return host->GetInt64Value(host->pluginIndex, value, object); }
	static bool Set(const CivHostInfo* host, int value, const void* object, __int64 n) { return host->SetInt64Value(host->pluginIndex, value, object, n); }
};
template<> struct CivStoredValue<double>
{
	enum { Type = CIV_VALUE_DOUBLE };
	static const void* Start(const double& n) { return &n; }
	static double Get(const CivHostInfo* host, int value, const void* object) { return host->GetDoubleValue(host->pluginIndex, value, object); }
	static bool Set(const CivHostInfo* host, int value, const void* object, double n) { return host->SetDoubleValue(host->pluginIndex, value, object, n); }
};
template<> struct CivStoredValue<std::string>
{
	enum { Type = CIV_VALUE_TEXT };
	static const void* Start(const std::string& text) { return text.c_str(); }
	static std::string Get(const CivHostInfo* host, int value, const void* object)
	{
		char first[256];
		const int size = host->GetTextValue(host->pluginIndex, value, object, first, sizeof(first));
		if (size < (int)sizeof(first))
			return std::string(first, size);
		std::string text(size + 1, '\0');
		host->GetTextValue(host->pluginIndex, value, object, &text[0], size + 1);
		text.resize(size);
		return text;
	}
	static bool Set(const CivHostInfo* host, int value, const void* object, const std::string& text)
	{
		return host->SetTextValue(host->pluginIndex, value, object, text.c_str());
	}
};

template<class T, class Stored> T CivFromStored(const Stored& stored) { return static_cast<T>(stored); }
template<> inline bool CivFromStored<bool, int>(const int& stored) { return stored != 0; }

// A value on every object of a kind, such as CivValue<CvUnit, int> or CivValue<CvCity, std::string>: Declare it from
// CivPluginEntry, or Find another plugin's published one.
template<class Object, class T> class CivValue
{
	typedef typename CivValueStorage<T>::Stored Stored;
	typedef CivStoredValue<Stored> Calls;

public:
	CivValue() : m_host(0), m_value(-1) {}

	bool Declare(const CivHostInfo* host, const char* name, const T& start, int flags = 0)
	{
		m_host = host;
		const Stored stored = static_cast<Stored>(start);
		m_value = host->DeclareValue(host->pluginIndex, CivObjectKindOf<Object>::Kind, Calls::Type, name, flags, Calls::Start(stored));
		return m_value >= 0;
	}
	bool Find(const CivHostInfo* host, const char* modId, const char* pluginId, const char* name)
	{
		m_host = host;
		m_value = host->FindValue(host->pluginIndex, modId, pluginId, name, CivObjectKindOf<Object>::Kind, Calls::Type);
		return m_value >= 0;
	}
	T Get(const Object* object) const { return m_host ? CivFromStored<T, Stored>(Calls::Get(m_host, m_value, object)) : T(); }
	bool Set(const Object* object, const T& value) const { return m_host && Calls::Set(m_host, m_value, object, static_cast<Stored>(value)); }

private:
	const CivHostInfo* m_host;
	int m_value;
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
