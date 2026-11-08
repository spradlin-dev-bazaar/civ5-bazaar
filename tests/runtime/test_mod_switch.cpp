// Finding the game's loops that switch to the mods of a save or a replay, and the code that fixes them.
#include "harness.h"
#include "CivHostModSwitch.h"

#include <string.h>
#include <windows.h>

namespace
{
	// The DirectX 11 executable's four loops: for saves at 0x670460 and 0x670606, for replays at 0x702c57 and 0x702df5.
	const unsigned char kSaveLoop[] = {
		0x6A, 0x00, 0x6A, 0xFF, 0x8B, 0xCF, 0xE8, 0xE5, 0x91, 0x03, 0x00, 0x50, 0x6A, 0x01, 0x8D, 0x4C, 0x24, 0x60, 0xFF, 0x15,
		0x04, 0x61, 0x9D, 0x00, 0x8B, 0xCF, 0xE8, 0x81, 0xAB, 0xDE, 0xFF, 0x50, 0x6A, 0x02, 0x8D, 0x4C, 0x24, 0x58, 0xFF, 0x15,
		0xF0, 0x60, 0x9D, 0x00, 0x8D, 0x4C, 0x24, 0x50, 0xFF, 0x15, 0x20, 0x61, 0x9D, 0x00, 0x6A, 0x00, 0x8D, 0x4C, 0x24, 0x54,
		0xFF, 0x15, 0x08, 0x61, 0x9D, 0x00};
	const unsigned char kSecondSaveLoop[] = {
		0x6A, 0x00, 0x6A, 0xFF, 0x8B, 0xCF, 0xE8, 0x3F, 0x90, 0x03, 0x00, 0x50, 0x6A, 0x01, 0x8D, 0x4C, 0x24, 0x60, 0xFF, 0x15,
		0x04, 0x61, 0x9D, 0x00, 0x8B, 0xCF, 0xE8, 0xDB, 0xA9, 0xDE, 0xFF, 0x50, 0x6A, 0x02, 0x8D, 0x4C, 0x24, 0x58, 0xFF, 0x15,
		0xF0, 0x60, 0x9D, 0x00, 0x8D, 0x4C, 0x24, 0x50, 0xFF, 0x15, 0x20, 0x61, 0x9D, 0x00, 0x6A, 0x00, 0x8D, 0x4C, 0x24, 0x54,
		0xFF, 0x15, 0x08, 0x61, 0x9D, 0x00};
	const unsigned char kReplayLoop[] = {
		0x6A, 0x00, 0x6A, 0xFF, 0x8B, 0xCF, 0xE8, 0xEE, 0x69, 0xFA, 0xFF, 0x50, 0x6A, 0x01, 0x8D, 0x4C, 0x24, 0x5C, 0xFF, 0x15,
		0x04, 0x61, 0x9D, 0x00, 0x8B, 0xCF, 0xE8, 0x8A, 0x83, 0xD5, 0xFF, 0x50, 0x6A, 0x02, 0x8D, 0x4C, 0x24, 0x54, 0xFF, 0x15,
		0xF0, 0x60, 0x9D, 0x00, 0x8D, 0x4C, 0x24, 0x4C, 0xFF, 0x15, 0x20, 0x61, 0x9D, 0x00, 0x6A, 0x00, 0x8D, 0x4C, 0x24, 0x50,
		0xFF, 0x15, 0x08, 0x61, 0x9D, 0x00};
	const unsigned char kSecondReplayLoop[] = {
		0x6A, 0x00, 0x6A, 0xFF, 0x8B, 0xCF, 0xE8, 0x50, 0x68, 0xFA, 0xFF, 0x50, 0x6A, 0x01, 0x8D, 0x4C, 0x24, 0x5C, 0xFF, 0x15,
		0x04, 0x61, 0x9D, 0x00, 0x8B, 0xCF, 0xE8, 0xEC, 0x81, 0xD5, 0xFF, 0x50, 0x6A, 0x02, 0x8D, 0x4C, 0x24, 0x54, 0xFF, 0x15,
		0xF0, 0x60, 0x9D, 0x00, 0x8D, 0x4C, 0x24, 0x4C, 0xFF, 0x15, 0x20, 0x61, 0x9D, 0x00, 0x6A, 0x00, 0x8D, 0x4C, 0x24, 0x50,
		0xFF, 0x15, 0x08, 0x61, 0x9D, 0x00};
	// The DirectX 9 executable's first loop for saves, at 0x6afca0: its import slots differ from DirectX 11's.
	const unsigned char kDx9SaveLoop[] = {
		0x6A, 0x00, 0x6A, 0xFF, 0x8B, 0xCF, 0xE8, 0x95, 0x83, 0xE3, 0xFF, 0x50, 0x6A, 0x01, 0x8D, 0x4C, 0x24, 0x60, 0xFF, 0x15,
		0x50, 0x90, 0x9C, 0x00, 0x8B, 0xCF, 0xE8, 0x01, 0x73, 0xDE, 0xFF, 0x50, 0x6A, 0x02, 0x8D, 0x4C, 0x24, 0x58, 0xFF, 0x15,
		0x3C, 0x90, 0x9C, 0x00, 0x8D, 0x4C, 0x24, 0x50, 0xFF, 0x15, 0x6C, 0x90, 0x9C, 0x00, 0x6A, 0x00, 0x8D, 0x4C, 0x24, 0x54,
		0xFF, 0x15, 0x54, 0x90, 0x9C, 0x00};
	const unsigned int kLoopSize = sizeof(kSaveLoop);
	const unsigned int kStepSlot = 0x009D6120, kDx9StepSlot = 0x009C906C;
	const unsigned int kStart = 0x00401000;
	// How far apart the DirectX 11 executable's two loops for saves are, on one page.
	const unsigned int kLoopGap = 0x670606 - 0x670460;

	std::vector<CivModSwitchLoop> Find(const std::vector<unsigned char>& code)
	{
		std::vector<CivModSwitchLoop> found;
		CivFindModSwitchLoops(&code[0], static_cast<unsigned int>(code.size()), kStart, &found);
		return found;
	}

	std::vector<unsigned char> Code(unsigned int size)
	{
		return std::vector<unsigned char>(size, 0xCC);
	}

	void Put(std::vector<unsigned char>* code, unsigned int at, const unsigned char* bytes)
	{
		memcpy(&(*code)[at], bytes, kLoopSize);
	}

	// The game's four loops, 100 bytes apart.
	std::vector<unsigned char> FourLoops()
	{
		std::vector<unsigned char> code = Code(500);
		Put(&code, 0, kSaveLoop);
		Put(&code, 100, kSecondSaveLoop);
		Put(&code, 200, kReplayLoop);
		Put(&code, 300, kSecondReplayLoop);
		return code;
	}

	unsigned int ReadAddress(const unsigned char* p)
	{
		unsigned int value;
		memcpy(&value, p, sizeof(value));
		return value;
	}

	unsigned int s_resetOn = 0;

	struct FakeQuery
	{
		bool Reset()
		{
			s_resetOn = reinterpret_cast<unsigned int>(this);
			return true;
		}
	};

	unsigned int FakeReset()
	{
		bool (FakeQuery::*method)() = &FakeQuery::Reset;
		unsigned int address;
		memcpy(&address, &method, sizeof(address));
		return address;
	}

	// Calls code with nothing on the stack but the return address; returns where the stack pointer was on entry.
	unsigned int Run(const void* code)
	{
		unsigned int entry = 0;
		__asm
		{
			mov eax, code
			lea ecx, [esp - 4]
			mov entry, ecx
			xor edx, edx
			call eax
		}
		return entry;
	}

	// A stand-in for a loop's start: the six bytes the jump replaces, then dropping their two pushes and returning.
	const unsigned char kFakeLoop[] = {0x6A, 0x00, 0x6A, 0xFF, 0x8B, 0xCF, 0x83, 0xC4, 0x08, 0xC3};

	unsigned char* FakeLoopPage()
	{
		unsigned char* page = static_cast<unsigned char*>(VirtualAlloc(NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
		memcpy(page, kFakeLoop, sizeof(kFakeLoop));
		memcpy(page + kLoopGap, kFakeLoop, sizeof(kFakeLoop));
		DWORD was = 0;
		VirtualProtect(page, 4096, PAGE_EXECUTE_READ, &was);
		return page;
	}

	bool ReadOnly(const void* address)
	{
		MEMORY_BASIC_INFORMATION memory;
		return VirtualQuery(address, &memory, sizeof(memory)) && memory.Protect == PAGE_EXECUTE_READ;
	}

	void TestFinding()
	{
		std::vector<CivModSwitchLoop> found = Find(FourLoops());
		Check(found.size() == 4 && found[0].address == kStart && found[1].address == kStart + 100 && found[2].address == kStart + 200
				&& found[3].address == kStart + 300,
			"all four of the game's loops are found where they are");
		Check(found.size() == 4 && found[0].queryOffset == 0x50 && found[1].queryOffset == 0x50 && found[2].queryOffset == 0x4C
				&& found[3].queryOffset == 0x4C,
			"each loop's query is found where its own code has it");
		Check(found.size() == 4 && found[0].stepSlot == kStepSlot && found[3].stepSlot == kStepSlot, "each loop's Step slot is read from its code");
		Check(CivModSwitchProblem(found).empty(), "two loops for saves and two for replays that call the same Step can be fixed");

		std::vector<unsigned char> dx9 = Code(100);
		Put(&dx9, 0, kDx9SaveLoop);
		found = Find(dx9);
		Check(found.size() == 1 && found[0].stepSlot == kDx9StepSlot && found[0].queryOffset == 0x50, "the DirectX 9 executable's loop is found too, with its own Step slot");
		std::vector<unsigned char> atEnd = Code(kLoopSize + 20);
		Put(&atEnd, 20, kSaveLoop);
		Check(Find(atEnd).size() == 1, "a loop that ends where the code ends is found");

		std::vector<unsigned char> changed = FourLoops();
		changed[300 + 17] = 0x5C + 4;
		Check(Find(changed).size() == 3, "a loop whose Bind names another place on the stack than its Step is not found");
		Check(CivModSwitchProblem(Find(changed)) == "its code was found 3 times instead of four times", "three loops are not fixed");
		Check(CivModSwitchProblem(Find(Code(100))) == "its code was found 0 times instead of four times", "a game without the loops is not changed");
		std::vector<unsigned char> five = FourLoops();
		five.resize(600, 0xCC);
		Put(&five, 500, kSaveLoop);
		Check(CivModSwitchProblem(Find(five)) == "its code was found 5 times instead of four times", "a fifth place like the loops leaves them unfixed");
		std::vector<unsigned char> unpaired = FourLoops();
		Put(&unpaired, 300, kSecondSaveLoop);
		Check(CivModSwitchProblem(Find(unpaired)) == "the places that look like its code do not come in two pairs", "three loops of one kind and one of the other are not fixed");
		std::vector<unsigned char> otherStep = FourLoops();
		otherStep[300 + 50] = 0x24;
		Check(Find(otherStep).size() == 4, "a loop calling another Step still looks like the loops");
		Check(CivModSwitchProblem(Find(otherStep)) == "the places that look like its code read the game's database through different functions", "loops that read the database through different functions are not fixed");
	}

	void TestCheckingStep()
	{
		unsigned int reset = 0;
		Check(CivModSwitchReset(0x1000, 0x2000, 0x1000, &reset) == "the place its code reads the database's Step function from is outside the game", "a Step slot before the game's image is not trusted");
		Check(CivModSwitchReset(0x2FFE, 0x2000, 0x1000, &reset) == "the place its code reads the database's Step function from is outside the game", "a Step slot running past the image's end is not trusted");
		Check(CivModSwitchReset(0xFFFFFFFE, 0xFFFF0000, 0xFFFF, &reset) == "the place its code reads the database's Step function from is outside the game", "a Step slot at the top of memory is not trusted, though its end wraps around");
		void* const notStep = reinterpret_cast<void*>(GetProcAddress(GetModuleHandleA("kernel32.dll"), "Sleep"));
		void* const slot[1] = {notStep};
		Check(CivModSwitchReset(reinterpret_cast<unsigned int>(slot), reinterpret_cast<unsigned int>(slot), sizeof(slot), &reset) == "the function its code calls to read the game's database is not the database's Step", "a slot holding another function than the database's Step is not trusted");
		std::vector<CivModSwitchLoop> loops;
		Check(CivFindModSwitch(GetModuleHandleA(NULL), &loops, &reset) == "its code was found 0 times instead of four times", "a program without the loops is searched and not changed");
	}

	void TestEncoding()
	{
		const CivModSwitchLoop loop(0x00702C57, kStepSlot, 0x4C);
		const unsigned int stub = 0x10000000, reset = 0x6A001234;
		unsigned char stubCode[CIV_MOD_SWITCH_STUB_SIZE], jump[CIV_MOD_SWITCH_JUMP_SIZE];
		CivModSwitchStub(loop, stub, reset, stubCode);
		CivModSwitchJump(loop.address, stub, jump);
		Check(jump[0] == 0xE9 && loop.address + 5 + ReadAddress(jump + 1) == stub, "the loop's first bytes become a jump to the stub");
		Check(stubCode[0] == 0x8D && stubCode[3] == 0x4C, "the stub points at the loop's own query");
		Check(stubCode[4] == 0xB8 && ReadAddress(stubCode + 5) == reset, "the stub calls Reset");
		Check(memcmp(stubCode + 11, kReplayLoop, CIV_MOD_SWITCH_JUMP_SIZE) == 0, "the stub then does what the jump replaced");
		Check(stubCode[17] == 0xE9 && stub + CIV_MOD_SWITCH_STUB_SIZE + ReadAddress(stubCode + 18) == loop.address + CIV_MOD_SWITCH_JUMP_SIZE, "the stub goes back into the loop after the jump");
	}

	void TestPatching()
	{
		unsigned char* const page = FakeLoopPage();
		std::vector<CivModSwitchLoop> fakes;
		fakes.push_back(CivModSwitchLoop(reinterpret_cast<unsigned int>(page), kStepSlot, 0x50));
		fakes.push_back(CivModSwitchLoop(reinterpret_cast<unsigned int>(page + kLoopGap), kStepSlot, 0x4C));
		Check(CivPatchModSwitch(fakes, FakeReset()).empty(), "two loops on one read-only page are both fixed");
		s_resetOn = 0;
		unsigned int entry = Run(page);
		Check(s_resetOn == entry + 0x50, "a fixed loop for saves resets the query at [esp+50h] and runs on");
		s_resetOn = 0;
		entry = Run(page + kLoopGap);
		Check(s_resetOn == entry + 0x4C, "a fixed loop for replays resets the query at [esp+4Ch] and runs on");
		Check(ReadOnly(page), "the page is read-only again afterwards");
		VirtualFree(page, 0, MEM_RELEASE);

		unsigned char* const kept = FakeLoopPage();
		void* const reserved = VirtualAlloc(NULL, 4096, MEM_RESERVE, PAGE_NOACCESS);
		std::vector<CivModSwitchLoop> halfWritable;
		halfWritable.push_back(CivModSwitchLoop(reinterpret_cast<unsigned int>(kept), kStepSlot, 0x50));
		halfWritable.push_back(CivModSwitchLoop(reinterpret_cast<unsigned int>(reserved), kStepSlot, 0x50));
		Check(CivPatchModSwitch(halfWritable, FakeReset()) == "Windows did not let Bazaar change the game's code", "a loop that cannot be changed stops the fix");
		Check(memcmp(kept, kFakeLoop, sizeof(kFakeLoop)) == 0, "then the loop that could be changed is left as it was");
		Check(ReadOnly(kept), "and its page is read-only again");
		VirtualFree(reserved, 0, MEM_RELEASE);
		VirtualFree(kept, 0, MEM_RELEASE);
	}
}

void TestModSwitch()
{
	TestFinding();
	TestCheckingStep();
	TestEncoding();
	TestPatching();
}
