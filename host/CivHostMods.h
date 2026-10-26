#pragma once

#include <string>
#include <vector>

struct CivActiveMod
{
	std::string id;
	int version;
};

struct CivModFile
{
	// Inside the mod's folder, as the description writes it.
	std::string path;
	// The game loads the file into its own file system, where screens and scripts are found by name.
	bool imported;
};

struct CivModInfo
{
	CivModInfo() : version(0), affectsSavedGames(false) {}

	std::string id;
	int version;
	bool affectsSavedGames;
	std::vector<CivModFile> files;
};

// False, with mod left empty, when the text is not a mod description with an ID and a version. Text with a UTF-16 byte
// order mark is read as UTF-16, and any other text as CivWide decodes it, whatever encoding the description declares.
bool CivReadModInfo(const std::string& text, CivModInfo* mod);

// The path, inside the mod's folder and with Windows slashes, of the last file the mod lists with this name, in any
// case; empty when there is none.
std::string CivModFilePath(const CivModInfo& mod, const std::string& fileName);
// The same, among only the files the game loads into its file system.
std::string CivModImportedFilePath(const CivModInfo& mod, const std::string& fileName);

struct CivInstalledMod
{
	std::string folder;
	CivModInfo info;
};

// Every mod description directly inside a folder of the MODS folder. The game also finds descriptions in subfolders,
// which this does not look in. The paths of descriptions that cannot be read are added to unreadable.
std::vector<CivInstalledMod> CivInstalledMods(const std::string& modsFolder, std::vector<std::string>* unreadable);
