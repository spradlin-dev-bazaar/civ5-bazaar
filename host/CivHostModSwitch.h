#pragma once

#include <string>
#include <vector>

// The game's own bug in switching to the mods of a save or a replay, and the fix Bazaar puts into the game's code. When a
// save loads with other mods switched on, or with some of its mods off, the game looks up the version of each of the save's
// mods with one database query. It never resets the query between mods, so most mods after the first get no version, or
// the first mod's version, and stay off. When Bazaar is one of them, the game reads the save without Bazaar and crashes.
// Viewing a replay switches mods through two more copies of the same loops. The fix resets the query at the start of each
// of the four loops, which are the same code in the DirectX 9, DirectX 11 and Tablet executables apart from addresses and,
// in the replay loops, where the query sits on the stack.

const unsigned int CIV_MOD_SWITCH_JUMP_SIZE = 6;
const unsigned int CIV_MOD_SWITCH_STUB_SIZE = 22;

struct CivModSwitchLoop
{
	CivModSwitchLoop(unsigned int address_, unsigned int stepSlot_, unsigned char queryOffset_)
		: address(address_), stepSlot(stepSlot_), queryOffset(queryOffset_)
	{
	}
	unsigned int address;
	// The import slot through which the loop calls Database::Results::Step.
	unsigned int stepSlot;
	// Where the loop's query is at the loop's start, above the stack pointer.
	unsigned char queryOffset;
};

// Adds each loop found in code, which sits at address start in the game.
void CivFindModSwitchLoops(const unsigned char* code, unsigned int size, unsigned int start, std::vector<CivModSwitchLoop>* found);

// Why the loops found cannot be fixed, or empty when they can: there must be four, all calling the same Step, two with
// their query at one place on the stack and two at another.
std::string CivModSwitchProblem(const std::vector<CivModSwitchLoop>& found);

// Why the loops' Step slot cannot be trusted, or empty when it can: it must lie in the executable's image and hold the
// Step that the game's database DLL exports. Then *reset is that DLL's Database::Results::Reset.
std::string CivModSwitchReset(unsigned int stepSlot, unsigned int imageStart, unsigned int imageSize, unsigned int* reset);

// Finds the loops in the executable loaded at exe and checks them with CivModSwitchProblem and CivModSwitchReset.
std::string CivFindModSwitch(const void* exe, std::vector<CivModSwitchLoop>* loops, unsigned int* reset);

// The code a loop jumps to, written for address stub: it calls reset, Database::Results::Reset, on the loop's query, does
// what the jump replaced, and goes back into the loop.
void CivModSwitchStub(const CivModSwitchLoop& loop, unsigned int stub, unsigned int reset, unsigned char* out);

void CivModSwitchJump(unsigned int loop, unsigned int stub, unsigned char* out);

// Puts the fix into the code: each loop's stub goes into memory that is never freed, since the fixed loops run again after
// this DLL unloads, and each loop gets its jump. Returns why it could not, and then no loop is changed; empty when every
// loop is fixed.
std::string CivPatchModSwitch(const std::vector<CivModSwitchLoop>& loops, unsigned int reset);
