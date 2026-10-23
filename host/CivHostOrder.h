#pragma once

#include "CivHostRuntime.h"

#include <string>
#include <vector>

#define CIV_REPORT_FILE_NOT_FOUND "The file was not found in the MODS folder."

// One plugin in the order the player set on the Plugins screen.
struct CivOrderEntry
{
	CivOrderEntry() : skip(false) {}

	std::string file;
	bool skip;
	// A skipped plugin is never loaded to ask, so the name it had when last listed is kept.
	std::string name;
	std::string version;
};

// The listed plugin files in the saved order; files the saved order lacks follow, in listed order.
std::vector<CivOrderEntry> CivApplyOrder(const std::vector<std::string>& listedFiles, const std::vector<CivOrderEntry>& saved);
// What to save: the order, then the saved entries it leaves out, so a plugin whose mod is off keeps its place and skip.
std::vector<CivOrderEntry> CivKeepUnlisted(const std::vector<CivOrderEntry>& order, const std::vector<CivOrderEntry>& saved);
std::string CivFormatOrder(const std::vector<CivOrderEntry>& order);
// Lines it does not recognise are ignored.
std::vector<CivOrderEntry> CivParseOrder(const std::string& text);
// One row per entry. Each entry neither skipped nor missing takes the loaded plugin row with its file name.
std::vector<CivPluginReportRow> CivOrderReportRows(const std::vector<CivOrderEntry>& order, const std::vector<std::string>& missing,
	const std::vector<CivPluginReportRow>& loaded);
