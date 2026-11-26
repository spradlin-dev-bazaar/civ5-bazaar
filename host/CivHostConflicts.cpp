#include "CivHostConflicts.h"
#include "CivHostHookList.h"
#include "CivHostHooks.h"
#include "CivHostPath.h"
#include "CivHostRuntime.h"
#include "CivHostValues.h"

#include <algorithm>

namespace
{
	struct PossibleConflict
	{
		int other;
		int hookPoint;
		int handHook;
		bool pluginReplaces;
		// The other side only has values that Bazaar carries over at the hook, rather than a hook of its own there.
		bool carriedValues;
	};

	std::vector<PossibleConflict> s_possibleConflicts;
	std::vector<int> s_loadingHandHooks;
	CivFilePairs s_useBoth;
	bool s_replaceTaken = false;

	bool HasText(const std::vector<std::string>& texts, const std::string& text)
	{
		for (size_t i = 0; i < texts.size(); ++i)
			if (texts[i] == text)
				return true;
		return false;
	}

	bool UseBoth(const std::string& a, const std::string& b)
	{
		for (size_t i = 0; i < s_useBoth.size(); ++i)
		{
			const CivFilePair& pair = s_useBoth[i];
			if ((CivSameText(pair.first, a) && CivSameText(pair.second, b)) || (CivSameText(pair.first, b) && CivSameText(pair.second, a)))
				return true;
		}
		return false;
	}

	void NotePossibleConflict(int other, int hookPoint, int handHook, bool pluginReplaces, bool carriedValues)
	{
		PossibleConflict conflict = { other, hookPoint, handHook, pluginReplaces, carriedValues };
		s_possibleConflicts.push_back(conflict);
	}

	void AddOnce(std::vector<std::string>& texts, const std::string& text)
	{
		if (!HasText(texts, text))
			texts.push_back(text);
	}

	void AddAndLog(int plugin, std::vector<std::string>& texts, const std::string& text)
	{
		if (HasText(texts, text))
			return;
		texts.push_back(text);
		CivHostLog("Plugin %s: %s", CivHostRecord(plugin).name.c_str(), text.c_str());
	}

	// A replacement that never calls the original skips the hand-placed hooks inside it, so the plugin lower in the list
	// is held back unless the player chose to use both. True when it is held back.
	bool ReportPossibleConflicts(int plugin)
	{
		CivPluginRecord& rec = CivHostRecord(plugin);
		bool heldBack = false;
		for (size_t i = 0; i < s_possibleConflicts.size(); ++i)
		{
			const PossibleConflict& c = s_possibleConflicts[i];
			const std::string otherFile = CivFileName(CivHostRecord(c.other).path);
			const char* otherName = CivHostRecord(c.other).name.c_str();
			const std::string function = CivHookShortName(c.hookPoint);
			const char* hook = CivHandHookName(c.handHook);
			AddOnce(rec.conflictsWith, otherFile);
			if (UseBoth(CivFileName(rec.path), otherFile))
			{
				if (c.carriedValues)
					AddAndLog(plugin, rec.notes, CivHostFormat("You chose to use this plugin with %s anyway, although one of them replaces %s, where Bazaar carries the other's values over to a new unit or city.",
						otherName, function.c_str()));
				else
					AddAndLog(plugin, rec.notes, CivHostFormat("You chose to use this plugin with %s anyway, although one of them replaces %s, which runs the %s hook the other uses.",
						otherName, function.c_str(), hook));
				continue;
			}
			heldBack = true;
			if (c.carriedValues && c.pluginReplaces)
				AddAndLog(plugin, rec.problems, CivHostFormat("This plugin replaces %s, where Bazaar carries the values of %s, higher in the list, over to a new unit or city. If the version in this plugin does not run the game's own, those values are not carried over, so this plugin was held back. If you know the two work together, check Use both anyway.",
					function.c_str(), otherName));
			else if (c.carriedValues)
				AddAndLog(plugin, rec.problems, CivHostFormat("%s, higher in the list, replaces %s, where Bazaar carries this plugin's values over to a new unit or city. If the version in %s does not run the game's own, those values are not carried over, so this plugin was held back. If you know the two work together, check Use both anyway.",
					otherName, function.c_str(), otherName));
			else if (c.pluginReplaces)
				AddAndLog(plugin, rec.problems, CivHostFormat("This plugin replaces %s, which runs the %s hook that %s, higher in the list, uses. If the version in this plugin does not run the game's own, %s never gets that hook, so this plugin was held back. If you know the two work together, check Use both anyway.",
					function.c_str(), hook, otherName, otherName));
			else
				AddAndLog(plugin, rec.problems, CivHostFormat("%s, higher in the list, replaces %s, which runs the %s hook this plugin uses. If the version in %s does not run the game's own, this plugin never gets that hook, so it was held back. If you know the two work together, check Use both anyway.",
					otherName, function.c_str(), hook, otherName));
		}
		s_possibleConflicts.clear();
		return heldBack;
	}

	// The kind of object whose values Bazaar carries over where this hand-placed hook runs, or -1.
	int CarriedKind(int handHook)
	{
		if (handHook == CIV_HAND_UNIT_REPLACED)
			return CIV_ON_UNIT;
		if (handHook == CIV_HAND_CITY_REPLACED)
			return CIV_ON_CITY;
		return -1;
	}

	bool RegisteredHandHook(int plugin, int handHook)
	{
		const std::vector<int> plugins = CivHandHookPlugins(handHook);
		return std::find(plugins.begin(), plugins.end(), plugin) != plugins.end();
	}

	bool LoadingPluginUses(int handHook)
	{
		for (size_t i = 0; i < s_loadingHandHooks.size(); ++i)
			if (s_loadingHandHooks[i] == handHook)
				return true;
		return false;
	}

	void NoteReplacements(int handHook, bool carriedValues)
	{
		for (int i = 0; i < g_CivHandHookSiteCount; ++i)
		{
			const CivHandHookSite& site = g_CivHandHookSites[i];
			const int replacer = CivHookReplacer(site.hookPoint);
			if (site.handHook == handHook && replacer >= 0)
				NotePossibleConflict(replacer, site.hookPoint, handHook, false, carriedValues);
		}
	}

	// Run once the entry function has returned, when the plugin's values and hand-placed hooks are all known.
	void NoteCarriedValues(int plugin)
	{
		for (int handHook = 0; handHook < g_CivHandHookCount; ++handHook)
		{
			const int kind = CarriedKind(handHook);
			if (kind >= 0 && CivValuesCarryOver(plugin, kind) && !LoadingPluginUses(handHook))
				NoteReplacements(handHook, true);
		}
	}
}

std::string CivConflictsTurnAwayIfReplaced(int hookId)
{
	const int taken = CivHookReplacer(hookId);
	if (taken < 0)
		return std::string();
	// Its other hooks may rely on the replacement it lost, so the whole plugin stays off.
	s_replaceTaken = true;
	const char* owner = CivHostRecord(taken).name.c_str();
	return CivHostFormat("%s, higher in the list, already replaces %s, and only one plugin can replace a function. To use this one instead, move it above %s.",
		owner, CivHookShortName(hookId).c_str(), owner);
}

void CivConflictsOnReplace(int plugin, int hookId)
{
	for (int i = 0; i < g_CivHandHookSiteCount; ++i)
	{
		const CivHandHookSite& site = g_CivHandHookSites[i];
		if (site.hookPoint != hookId)
			continue;
		const std::vector<int> users = CivHandHookPlugins(site.handHook);
		for (size_t u = 0; u < users.size(); ++u)
			NotePossibleConflict(users[u], hookId, site.handHook, true, false);
		const int kind = CarriedKind(site.handHook);
		for (int other = 0; kind >= 0 && other < plugin; ++other)
			if (CivValuesCarryOver(other, kind) && !RegisteredHandHook(other, site.handHook))
				NotePossibleConflict(other, hookId, site.handHook, true, true);
	}
}

void CivConflictsOnHandHook(int handHook)
{
	NoteReplacements(handHook, false);
	s_loadingHandHooks.push_back(handHook);
}

CivPluginStatus CivConflictsVerdict(int plugin)
{
	NoteCarriedValues(plugin);
	CivPluginStatus verdict = CIV_PLUGIN_REPLACE_CONFLICT;
	if (!s_replaceTaken)
		verdict = ReportPossibleConflicts(plugin) ? CIV_PLUGIN_POSSIBLE_CONFLICT : CIV_PLUGIN_LOADED;
	CivConflictsForget();
	return verdict;
}

void CivConflictsForget()
{
	s_possibleConflicts.clear();
	s_loadingHandHooks.clear();
	s_replaceTaken = false;
}

const CivFilePairs& CivConflictsUseBoth()
{
	return s_useBoth;
}

void CivConflictsSetUseBoth(const CivFilePairs& useBoth)
{
	s_useBoth = useBoth;
}
