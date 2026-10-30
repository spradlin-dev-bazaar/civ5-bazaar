#include "CivHostSetup.h"
#include "CivHostDlc.h"
#include "CivHostPath.h"

#include <windows.h>
#include <stdio.h>

namespace
{
	const char* const kXml = "AdvancedSetup.xml";
	const char* const kLua = "AdvancedSetup.lua";
	const char* const kCopyName = "BazaarNextSetup";

	bool Inside(const std::string& path, const std::string& folder)
	{
		const std::string prefix = folder + "\\";
		return path.size() > prefix.size() && CivSameText(path.substr(0, prefix.size()), prefix);
	}

	bool IsSetupFile(const std::string& path)
	{
		const std::string name = CivFileName(path);
		return CivSameText(name, kXml) || CivSameText(name, kLua);
	}

	std::string ImportedByActiveMod(const std::vector<CivActiveMod>& mods, const std::string& ownFolder, const std::string& fileName)
	{
		const std::string own = CivFullPath(ownFolder);
		std::string source;
		for (size_t m = 0; m < mods.size(); ++m)
		{
			const std::string file = CivModImportedFilePath(mods[m], fileName);
			if (!file.empty() && !Inside(CivFullPath(file), own))
				source = file;
		}
		return source;
	}

	std::string SetupSource(const std::string& gameFolder, const std::string& ownFolder, const std::vector<CivActiveMod>& mods,
		const std::vector<CivDlcSkin>& skins, const char* fileName)
	{
		std::string source = ImportedByActiveMod(mods, ownFolder, fileName);
		if (source.empty())
			source = CivFileInDlcSkins(skins, fileName);
		if (source.empty())
			source = gameFolder + "\\Assets\\UI\\FrontEnd\\GameSetup\\" + fileName;
		return source;
	}
}

CivReplacedSetup CivCopyReplacedSetup(const std::string& gameFolder, const std::string& ownFolder, const std::vector<CivActiveMod>& mods)
{
	CivReplacedSetup result;
	const std::vector<CivDlcSkin> skins = CivReadDlcSkins(gameFolder, &result.unreadablePacks);
	result.xmlSource = SetupSource(gameFolder, ownFolder, mods, skins, kXml);
	result.luaSource = SetupSource(gameFolder, ownFolder, mods, skins, kLua);

	const std::string copy = ownFolder + "\\" + kCopyName;
	const std::string sources[] = {result.xmlSource, result.luaSource};
	const std::string targets[] = {copy + ".xml", copy + ".lua"};
	for (int i = 0; i < 2; ++i)
	{
		// CopyFile keeps the source's attributes, and it cannot write over a read-only copy left by an earlier visit.
		SetFileAttributesW(CivWide(targets[i]).c_str(), FILE_ATTRIBUTE_NORMAL);
		if (!CopyFileW(CivWide(sources[i]).c_str(), CivWide(targets[i]).c_str(), FALSE))
		{
			char reason[64];
			_snprintf_s(reason, sizeof(reason), _TRUNCATE, " (Windows error %lu)", GetLastError());
			result.problem = "Could not copy " + sources[i] + " to " + targets[i] + reason + ".";
			return result;
		}
	}
	result.copy = copy;
	return result;
}

void CivAddInstalledModRow(std::vector<CivInstalledMod>* mods, int row, const std::string& id, const std::string& name, bool activated,
	const std::string& importedPath)
{
	if (mods->empty() || mods->back().row != row)
	{
		CivInstalledMod mod;
		mod.row = row;
		mod.id = id;
		mod.name = name;
		mod.activated = activated;
		mods->push_back(mod);
	}
	if (!importedPath.empty() && IsSetupFile(importedPath))
		mods->back().replacesSetup = true;
}

std::string CivOwnModId(const std::vector<CivActiveMod>& mods, const std::string& ownFolder)
{
	const std::string own = CivFullPath(ownFolder);
	for (size_t m = 0; m < mods.size(); ++m)
		for (size_t f = 0; f < mods[m].files.size(); ++f)
			if (Inside(CivFullPath(mods[m].files[f].path), own))
				return mods[m].id;
	return std::string();
}

CivSetupOrder CivCheckSetupOrder(const std::vector<CivInstalledMod>& mods, const std::string& ownId)
{
	CivSetupOrder order;
	const CivInstalledMod* own = NULL;
	for (size_t i = 0; i < mods.size(); ++i)
		if (mods[i].activated && mods[i].id == ownId)
			own = &mods[i];
	if (!own)
		return order;
	const CivInstalledMod* newest = NULL;
	for (size_t i = 0; i < mods.size(); ++i)
	{
		const CivInstalledMod& mod = mods[i];
		if (mod.id == ownId || !mod.replacesSetup || mod.row <= own->row)
			continue;
		order.newer = true;
		order.newerOn = order.newerOn || mod.activated;
		if (!newest || (mod.activated != newest->activated ? mod.activated : mod.row > newest->row))
			newest = &mod;
	}
	if (newest)
		order.newerName = newest->name.empty() ? newest->id : newest->name;
	return order;
}

CivSetupMove CivSetupMoveOutcome(const CivSetupOrder& order, bool moved)
{
	CivSetupMove move;
	if (!order.newer)
		return move;
	if (!moved)
	{
		if (order.newerOn)
			move.logLine = "Bazaar could not move itself to the end of the game's mod list, so " + order.newerName
				+ "'s Advanced Setup screen shows instead of the Plugins screen.";
	}
	else if (!order.newerOn)
		move.logLine = "Bazaar moved itself to the end of the game's mod list, after " + order.newerName
			+ ", which also replaces Advanced Setup but is turned off.";
	else
	{
		move.reload = true;
		move.logLine = order.newerName + "'s Advanced Setup screen was newer than Bazaar's Plugins screen, so Bazaar moved itself to the end "
			"of the game's mod list and is switching the mods off and on again.";
	}
	return move;
}

CivSetupWinner CivSetupWinnerOutcome(const CivSetupOrder& order, bool reloaded)
{
	CivSetupWinner winner;
	if (!order.newerOn)
		return winner;
	if (reloaded)
		winner.logLine = "After switching the mods off and on again, " + order.newerName
			+ "'s Advanced Setup screen still comes before Bazaar's Plugins screen.";
	winner.popup = CivSetupPopupText(order.newerName);
	return winner;
}

std::string CivSetupPopupText(const std::string& newerName)
{
	const std::string rest = "'s Advanced Setup screen shows in place of Bazaar's Plugins screen, so your plugins load in the order you last saved. "
		"To change the order, turn that mod off in Mods. Details are in Logs\\Bazaar.log.";
	return CivShortened(newerName, CIV_SETUP_POPUP_MOST - rest.size()) + rest;
}
