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

// The game gives a screen two switched-on mods import to the one with the newest row in its mod list, whatever their switch-on order.
struct CivInstalledMod
{
	CivInstalledMod() : row(0), activated(false), replacesSetup(false) {}

	int row;
	std::string id;
	std::string name;
	bool activated;
	bool replacesSetup;
};

// The rows must keep each installed version's rows together.
void CivAddInstalledModRow(std::vector<CivInstalledMod>* mods, int row, const std::string& id, const std::string& name, bool activated,
	const std::string& importedPath);

std::string CivOwnModId(const std::vector<CivActiveMod>& mods, const std::string& ownFolder);

struct CivSetupOrder
{
	CivSetupOrder() : newer(false), newerOn(false) {}

	bool newer;
	bool newerOn;
	std::string newerName;
};

CivSetupOrder CivCheckSetupOrder(const std::vector<CivInstalledMod>& mods, const std::string& ownId);

struct CivSetupMove
{
	CivSetupMove() : reload(false) {}

	bool reload;
	std::string logLine;
};

CivSetupMove CivSetupMoveOutcome(const CivSetupOrder& order, bool moved);

struct CivSetupWinner
{
	std::string logLine;
	std::string popup;
};

CivSetupWinner CivSetupWinnerOutcome(const CivSetupOrder& order, bool reloaded);

// The game's front-end pop-up garbles its text past 256 characters; 255 is the longest checked in the game.
#define CIV_SETUP_POPUP_MOST 255
std::string CivSetupPopupText(const std::string& newerName);
