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
	CIV_PLUGIN_OLDER_API,
	CIV_PLUGIN_FAULTED_AT_LOAD,
	CIV_PLUGIN_DUPLICATE,
	CIV_PLUGIN_STILL_IN_MEMORY,
	CIV_PLUGIN_REPLACE_CONFLICT,
	CIV_PLUGIN_POSSIBLE_CONFLICT,
	CIV_PLUGIN_ID_TAKEN,
};

enum CivApiFit
{
	CIV_API_RUNS,
	CIV_API_NEWER_VERSION,
	CIV_API_LATER_RELEASE,
	CIV_API_OLDER_VERSION,
};

struct CivApiNumbers
{
	int major;
	int minor;
	int release;
};

struct CivPluginFile
{
	CivPluginFile(const std::string& path, const std::string& modId) : path(path), modId(modId) {}

	std::string path;
	std::string modId;
};

struct CivPluginRecord
{
	CivPluginRecord()
		: builtApiMajor(0), builtApiMinor(0), builtApiRelease(0), status(CIV_PLUGIN_FILE_NOT_LOADED), quarantined(false), module(0), host(0),
		  serial(0), saveFn(0), loadFn(0)
	{
	}

	std::string path;
	std::string modId;
	std::string pluginId;
	std::string name;
	std::string version;
	int builtApiMajor;
	int builtApiMinor;
	int builtApiRelease;
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
	CivSaveDataFn saveFn;
	CivLoadDataFn loadFn;
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

void CivHostSetLogSink(CivHostLogSink sink);

// Adds plugins without unloading any; CivHostSetPlugins is the way to change the list.
void CivHostLoadPlugins(const std::vector<CivPluginFile>& files);
// Replaces the loaded plugins with these, unless they are the ones already listed with the same useBoth. BUSY changes
// nothing. A pair in useBoth loads despite a possible conflict between the two.
CivPluginListResult CivHostSetPlugins(const std::vector<CivPluginFile>& files, const CivFilePairs& useBoth = CivFilePairs());
// False, with nothing changed, when called while a plugin is running.
bool CivHostUnloadPlugins();
const std::vector<CivPluginRecord>& CivHostPlugins();
void CivHostLogLine(const char* line);
// Every version may change what plugins use, so a plugin runs only on its own version, from the release it was built
// for on.
CivApiFit CivApiFitOf(const CivApiNumbers& host, const CivApiNumbers& built);
// The refusal of a second plugin with the same key, the lookup of saved data and the finding of published values all
// use this, or data would mix.
bool CivSameSaveKey(const std::string& modIdA, const std::string& pluginIdA, const std::string& modIdB, const std::string& pluginIdB);
bool CivSameSaveKey(const CivPluginRecord& plugin, const std::string& modId, const std::string& pluginId);
// What the Plugins screen shows for each plugin record, in load order; problems are separated by "\n".
std::vector<CivPluginReportRow> CivHostReportRows();

// For the host's other files, which share the plugin list and the log.
CivPluginRecord& CivHostRecord(int plugin);
bool CivHostAlive(int plugin);
const char* CivHostPluginName(int plugin);
void CivHostLog(const char* format, ...);
std::string CivHostFormat(const char* format, ...);
