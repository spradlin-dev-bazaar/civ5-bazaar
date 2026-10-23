#pragma once

#include <string>
#include <vector>

// The Plugins screen takes the Advanced Setup slot so it comes first on the way to a game; this finds the screen it took
// the slot from, so the Plugins screen can open it next.

struct CivActiveMod
{
	std::string id;
	int version;
};

struct CivReplacedSetup
{
	// The copy's path without its extension; empty, with problem set, when it could not be copied.
	std::string copy;
	std::string xmlSource;
	std::string luaSource;
	std::string problem;
};

bool CivModIdentity(const std::string& modinfo, std::string* id, int* version);
// The path, inside the mod's folder, of the last file it imports into the game with this name; empty when there is none.
std::string CivImportedFile(const std::string& modinfo, const std::string& fileName);

// Copies each of the screen's two files, from the last active mod importing it (other than the mod in ownFolder) or else
// the game, into ownFolder under a name of its own: the game finds screens by name, and that name is taken by Bazaar's.
CivReplacedSetup CivCopyReplacedSetup(const std::string& modsFolder, const std::string& gameFolder, const std::string& ownFolder,
	const std::vector<CivActiveMod>& active, bool expansion1);
