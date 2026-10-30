#pragma once

#include <string>
#include <vector>

// The UI skins of the DLC packs in the game's Assets\DLC folder, whose files the game shows in place of its own. Only
// skins for Brave New World on a PC count: the game uses no other while Bazaar runs.

struct CivDlcSkin
{
	CivDlcSkin() : priority(0) {}
	int priority;
	// Full paths. The game finds a skin's files anywhere inside them, by name.
	std::vector<std::string> folders;
	// Full paths of the files the skin lists one by one. The name may hold wildcards, as in GameMenu.*.
	std::vector<std::string> files;
};

// Each package file that cannot be read to its end is added to unreadable, and its pack counts for nothing.
std::vector<CivDlcSkin> CivReadDlcSkins(const std::string& gameFolder, std::vector<std::string>* unreadable);

// The file of that name from the skin with the highest priority that has it; empty when none has. Of two skins with the
// same priority, the one read first wins.
std::string CivFileInDlcSkins(const std::vector<CivDlcSkin>& skins, const std::string& fileName);
