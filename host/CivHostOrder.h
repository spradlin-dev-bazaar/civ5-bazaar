#pragma once

#include "CivHostMods.h"
#include "CivHostRuntime.h"

#include <string>
#include <vector>

// One plugin in the order the player set on the Plugins screen.
struct CivOrderEntry
{
	CivOrderEntry() : skip(false) {}

	std::string file;
	bool skip;
	// A skipped plugin is never loaded to ask, so the name it had when last listed is kept.
	std::string name;
	std::string version;
	std::vector<std::string> useBothWith;
};

// The listed plugin files in the wanted order; files the wanted order lacks follow, in listed order.
std::vector<CivOrderEntry> CivOrderListedFiles(const std::vector<std::string>& listedFiles, const std::vector<CivOrderEntry>& wanted);
// What to save: the order, then the saved entries it leaves out, so a plugin whose mod is off keeps its place and skip.
std::vector<CivOrderEntry> CivKeepUnlisted(const std::vector<CivOrderEntry>& order, const std::vector<CivOrderEntry>& saved);
std::string CivFormatOrder(const std::vector<CivOrderEntry>& order);
// Lines it does not recognise are ignored.
std::vector<CivOrderEntry> CivParseOrder(const std::string& text);
// Each plugin with each one in its useBothWith.
CivFilePairs CivUseBothPairs(const std::vector<CivOrderEntry>& order);
// One row per entry. Each entry neither skipped nor in notLoaded takes the loaded plugin row with its file name. A row's
// useBothWith lists every plugin paired with it, whichever of the two lines holds the choice.
std::vector<CivPluginReportRow> CivOrderReportRows(const std::vector<CivOrderEntry>& order, const std::vector<CivNotLoaded>& notLoaded,
	const std::vector<CivPluginReportRow>& loaded);
// A row with no file is Bazaar's own note, which the Plugins screen keeps at the top.
std::vector<CivPluginReportRow> CivWithNote(const char* warning, const std::vector<CivPluginReportRow>& rows);
