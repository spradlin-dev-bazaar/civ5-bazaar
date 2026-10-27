#pragma once

#include <string>

std::string CivHostSavePart();
// part is null for a new game or a save from before Bazaar kept plugin data. Gives back what was wrong with a part it
// could not read, or nothing, and whether the game was saved after a plugin crashed in it.
std::string CivHostLoadPart(const std::string* part, bool* savedAfterCrash = 0);
