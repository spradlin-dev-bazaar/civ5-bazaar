#pragma once

#include "CivHostMods.h"

#include <string>
#include <vector>

// The Plugins screen takes the Advanced Setup slot so it comes first on the way to a game; this finds the screen it took
// the slot from, so the Plugins screen can open it next.

struct CivReplacedSetup
{
	// The copy's path without its extension; empty, with problem set, when it could not be copied.
	std::string copy;
	std::string xmlSource;
	std::string luaSource;
	std::string problem;
};

// Copies each of the screen's two files, from the last mod importing it (other than the mod in ownFolder) or else the
// game, into ownFolder under a name of its own: the game finds screens by name, and that name is taken by Bazaar's.
CivReplacedSetup CivCopyReplacedSetup(const std::string& gameFolder, const std::string& ownFolder, const std::vector<CivActiveMod>& mods,
	bool expansion1);
