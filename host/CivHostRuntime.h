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
};

struct CivPluginRecord
{
	std::string path;
	std::string name;
	std::string version;
	int builtApiMajor;
	int builtApiMinor;
	CivPluginStatus status;
	bool quarantined;
	std::vector<std::string> problems;
};

typedef void (*CivHostLogSink)(const char* line);
typedef void (*CivHostFaultSink)(int pluginIndex, const char* pluginName, int hookId, unsigned int code);

void CivHostSetLogSink(CivHostLogSink sink);
void CivHostSetFaultSink(CivHostFaultSink sink);

void CivHostLoadPlugins(const std::vector<std::string>& paths);
const std::vector<CivPluginRecord>& CivHostPlugins();
