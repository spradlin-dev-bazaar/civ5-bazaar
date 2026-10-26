#pragma once

#include "CivPluginApi.h"

#include <string>
#include <utility>
#include <vector>

enum CivPluginStatus
{
	CIV_PLUGIN_LOADED,
	CIV_PLUGIN_FILE_NOT_LOADED,
	CIV_PLUGIN_NO_ENTRY,
	CIV_PLUGIN_NO_API_VERSION,
	CIV_PLUGIN_ENTRY_DECLINED,
	CIV_PLUGIN_NEWER_API,
	CIV_PLUGIN_OTHER_MAJOR,
	CIV_PLUGIN_FAULTED_AT_LOAD,
	CIV_PLUGIN_DUPLICATE,
	CIV_PLUGIN_STILL_IN_MEMORY,
	CIV_PLUGIN_REPLACE_CONFLICT,
	CIV_PLUGIN_POSSIBLE_CONFLICT,
};

struct CivPluginRecord
{
	CivPluginRecord()
		: builtApiMajor(0), builtApiMinor(0), status(CIV_PLUGIN_FILE_NOT_LOADED), quarantined(false), module(0), host(0),
		  serial(0)
	{
	}

	std::string path;
	std::string name;
	std::string version;
	int builtApiMajor;
	int builtApiMinor;
	CivPluginStatus status;
	bool quarantined;
	std::vector<std::string> problems;
	// Shown on the Plugins screen after the problems, but never announced in the game.
	std::vector<std::string> notes;
	// Files of plugins higher in the list where one of the two replaces a function that runs a hand-placed hook the
	// other uses.
	std::vector<std::string> conflictsWith;
	void* module;
	CivHostInfo* host;
	// Never reused, so a Lua function a plugin pushed before an unload or reload can tell its plugin is gone.
	unsigned int serial;
};

#define CIV_REPORT_NOT_LOADED "Not loaded"

struct CivPluginReportRow
{
	CivPluginReportRow() : failed(false), skipped(false) {}

	std::string file;
	std::string name;
	std::string version;
	std::string status;
	std::string problems;
	// The Plugins screen shows a failed row in red; other rows' problems are warnings.
	bool failed;
	bool skipped;
	std::vector<std::string> conflictsWith;
	// The plugins the player chose to use this one with despite a possible conflict.
	std::vector<std::string> useBothWith;
};

enum CivPluginListResult
{
	CIV_PLUGINS_UNCHANGED,
	CIV_PLUGINS_CHANGED,
	CIV_PLUGINS_BUSY,
};

// Two plugin file names, in either order.
typedef std::pair<std::string, std::string> CivFilePair;
typedef std::vector<CivFilePair> CivFilePairs;

typedef void (*CivHostLogSink)(const char* line);
typedef void (*CivHostFaultSink)(int pluginIndex, const char* pluginName, bool shuttingDown, unsigned int code);
// Pushes a Lua function that hands serial, fn and its own lua_State to CivHostCallLuaFunction.
typedef void (*CivHostLuaPusher)(lua_State* L, unsigned int serial, CivLuaFunction fn);

void CivHostSetLogSink(CivHostLogSink sink);
void CivHostSetFaultSink(CivHostFaultSink sink);
// Set before plugins load: without a pusher, PushLuaFunction pushes nothing.
void CivHostSetLuaPusher(CivHostLuaPusher pusher);
// Runs a plugin's Lua function through the crash guard and gives back what it returned, a negative yield included.
// False, with why, when its plugin is off or unloaded, it was pushed with a wrong index, or it crashed. A Lua error the
// function raises passes straight through.
bool CivHostCallLuaFunction(unsigned int serial, CivLuaFunction fn, lua_State* L, int* results, char* why, size_t whySize);

// Adds plugins without unloading any; CivHostSetPlugins is the way to change the list.
void CivHostLoadPlugins(const std::vector<std::string>& paths);
// Replaces the loaded plugins with these, unless they are the ones already listed with the same useBoth. BUSY changes
// nothing. A pair in useBoth loads despite a possible conflict between the two.
CivPluginListResult CivHostSetPlugins(const std::vector<std::string>& paths, const CivFilePairs& useBoth = CivFilePairs());
// False, with nothing changed, when called while a plugin is running.
bool CivHostUnloadPlugins();
const std::vector<CivPluginRecord>& CivHostPlugins();
// What the Plugins screen shows for each plugin record, in load order; problems are separated by "\n".
std::vector<CivPluginReportRow> CivHostReportRows();
