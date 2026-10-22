#pragma once

// The contract between the host and plugin DLLs. Structures here only ever grow at the end.

#define CIV_HOST_API_MAJOR 0
#define CIV_HOST_API_MINOR 1

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
	CIV_HOOK_BAD_ID = 1,
	CIV_HOOK_BAD_KIND = 2,
	CIV_HOOK_REPLACE_TAKEN = 3,
	CIV_HOOK_NOT_ALLOWED = 4,
};

struct CivHostInfo
{
	int apiMajor;
	int apiMinor;
	int pluginIndex;
	int (*RegisterHook)(int pluginIndex, int hookId, int kind, void* fn);
	void (*Log)(int pluginIndex, const char* message);
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
#define CIV_PLUGIN_SHUTDOWN_NAME "CivPluginShutdown"
