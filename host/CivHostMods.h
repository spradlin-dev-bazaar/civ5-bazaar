#pragma once

#include "CivHostRuntime.h"

#include <string>
#include <vector>

#define CIV_REPORT_FILE_NOT_FOUND "No mod that is turned on lists this file."
#define CIV_REPORT_NOT_IN_SAVES "This plugin's mod is not marked as affecting saved games, so Bazaar does not load it: it would be missing from games loaded from a save. Ask the plugin's author to fix this."

struct CivModFile
{
	// Full for a mod in MODS, but relative to the game's folder for the game's own scenarios.
	std::string path;
	// The game loads the file into its own file system, where screens and scripts are found by name.
	bool imported;
};

struct CivActiveMod
{
	CivActiveMod() : version(0), affectsSavedGames(false) {}

	std::string id;
	int version;
	bool affectsSavedGames;
	std::vector<CivModFile> files;
};

// The rows must keep each mod's rows together, its files in the order the mod lists them. Only exactly "1" affects
// saved games, as on the game's own Mods screen.
void CivAddModRow(std::vector<CivActiveMod>* mods, const std::string& id, int version, const std::string& affectsSavedGames,
	const std::string& path, bool imported);

// The last file the mod lists with this name, in any case, with Windows slashes; empty when there is none.
std::string CivModFilePath(const CivActiveMod& mod, const std::string& fileName);
// The same, among only the files the game loads into its file system.
std::string CivModImportedFilePath(const CivActiveMod& mod, const std::string& fileName);

struct CivNotLoaded
{
	std::string file;
	std::string reason;
};

// A game loaded from a save keeps the DllPlugins rows of only the mods that affect saved games.
std::vector<CivPluginFile> CivPluginFiles(const std::vector<std::string>& files, const std::vector<CivActiveMod>& mods,
	std::vector<CivNotLoaded>* notLoaded);
