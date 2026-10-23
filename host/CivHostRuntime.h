#pragma once

#include "CivPluginApi.h"

#include <string>
#include <vector>

enum CivPluginStatus
{
	CIV_PLUGIN_LOADED,
	CIV_PLUGIN_FILE_NOT_LOADED,
	CIV_PLUGIN_NO_ENTRY,
	CIV_PLUGIN_ENTRY_DECLINED,
	CIV_PLUGIN_NEWER_API,
	CIV_PLUGIN_OTHER_MAJOR,
	CIV_PLUGIN_FAULTED_AT_LOAD,
	CIV_PLUGIN_DUPLICATE,
	CIV_PLUGIN_STILL_IN_MEMORY,
};

struct CivPluginRecord
{
	CivPluginRecord()
		: builtApiMajor(0), builtApiMinor(0), status(CIV_PLUGIN_FILE_NOT_LOADED), quarantined(false), module(0), host(0)
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
	void* module;
	CivHostInfo* host;
};

#define CIV_REPORT_NOT_LOADED "Not loaded"

struct CivPluginReportRow
{
	CivPluginReportRow() : failed(false) {}

	std::string file;
	std::string name;
	std::string version;
	std::string status;
	std::string problems;
	// The Plugins screen shows a failed row in red; other rows' problems are warnings.
	bool failed;
};

enum CivPluginListResult
{
	CIV_PLUGINS_UNCHANGED,
	CIV_PLUGINS_CHANGED,
	CIV_PLUGINS_BUSY,
};

typedef void (*CivHostLogSink)(const char* line);
// hookId is -1 when the fault was outside any hook, such as in the plugin's shutdown function.
typedef void (*CivHostFaultSink)(int pluginIndex, const char* pluginName, int hookId, unsigned int code);

void CivHostSetLogSink(CivHostLogSink sink);
void CivHostSetFaultSink(CivHostFaultSink sink);

// Adds plugins without unloading any; CivHostSetPlugins is the way to change the list.
void CivHostLoadPlugins(const std::vector<std::string>& paths);
// Replaces the loaded plugins with these, unless they are the ones already listed. BUSY changes nothing.
CivPluginListResult CivHostSetPlugins(const std::vector<std::string>& paths);
// False, with nothing changed, when called while a plugin is running.
bool CivHostUnloadPlugins();
const std::vector<CivPluginRecord>& CivHostPlugins();
// What the Plugins screen shows for each plugin record, in load order; problems are separated by "\n".
std::vector<CivPluginReportRow> CivHostReportRows();
