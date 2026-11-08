#include "CivHostModSwitch.h"

#include <stdio.h>
#include <string.h>
#include <windows.h>

namespace
{
	// The bytes the jump replaces, which the stub then runs instead: push 0; push -1; mov ecx,edi.
	const unsigned char kReplaced[CIV_MOD_SWITCH_JUMP_SIZE] = {0x6A, 0x00, 0x6A, 0xFF, 0x8B, 0xCF};

	// The rest of a loop up to its call to GetInt: it binds the mod's ID and the save's version to the query, steps it and
	// reads the version. ANY marks the bytes that differ between executables and loops: call targets, import slots and
	// the query's place on the stack.
	const int ANY = 0x100;
	const int kRest[] = {
		0xE8, ANY, ANY, ANY, ANY,        // call: the mod's ID
		0x50,                            // push eax
		0x6A, 0x01,                      // push 1
		0x8D, 0x4C, 0x24, ANY,           // lea ecx,[esp+query+10h]
		0xFF, 0x15, ANY, ANY, ANY, ANY,  // call [Bind]
		0x8B, 0xCF,                      // mov ecx,edi
		0xE8, ANY, ANY, ANY, ANY,        // call: the save's version
		0x50,                            // push eax
		0x6A, 0x02,                      // push 2
		0x8D, 0x4C, 0x24, ANY,           // lea ecx,[esp+query+8]
		0xFF, 0x15, ANY, ANY, ANY, ANY,  // call [Bind]
		0x8D, 0x4C, 0x24, ANY,           // lea ecx,[esp+query]
		0xFF, 0x15, ANY, ANY, ANY, ANY,  // call [Step]
		0x6A, 0x00,                      // push 0
		0x8D, 0x4C, 0x24, ANY,           // lea ecx,[esp+query+4]
		0xFF, 0x15, ANY, ANY, ANY, ANY,  // call [GetInt]
	};
	const unsigned int kRestSize = sizeof(kRest) / sizeof(kRest[0]);
	const unsigned int kLoopSize = CIV_MOD_SWITCH_JUMP_SIZE + kRestSize;
	// Offsets in a whole loop. The Binds pop their own arguments, so each lea names the same query.
	const unsigned int kFirstBindQueryAt = 17, kSecondBindQueryAt = 37, kStepQueryAt = 47, kStepSlotAt = 50, kGetIntQueryAt = 59;

	// Offsets in the stub.
	const unsigned int kStubQueryAt = 3, kStubResetAt = 5, kStubReplacedAt = 11, kStubBackAt = 18;

	bool LoopAt(const unsigned char* p)
	{
		if (memcmp(p, kReplaced, sizeof(kReplaced)) != 0)
			return false;
		for (unsigned int i = 0; i < kRestSize; ++i)
			if (kRest[i] != ANY && kRest[i] != p[CIV_MOD_SWITCH_JUMP_SIZE + i])
				return false;
		const int query = p[kStepQueryAt];
		return p[kFirstBindQueryAt] == query + 0x10 && p[kSecondBindQueryAt] == query + 8 && p[kGetIntQueryAt] == query + 4;
	}

	unsigned int ReadAddress(const unsigned char* p)
	{
		return p[0] | (p[1] << 8) | (p[2] << 16) | (static_cast<unsigned int>(p[3]) << 24);
	}

	void WriteAddress(unsigned char* p, unsigned int value)
	{
		for (int i = 0; i < 4; ++i)
			p[i] = static_cast<unsigned char>(value >> (8 * i));
	}

	// Makes each loop's first bytes writable, keeping each one's old protection; returns how many it opened.
	size_t OpenLoops(const std::vector<CivModSwitchLoop>& loops, std::vector<DWORD>* protections)
	{
		size_t opened = 0;
		while (opened < loops.size()
			&& VirtualProtect(reinterpret_cast<void*>(loops[opened].address), CIV_MOD_SWITCH_JUMP_SIZE, PAGE_EXECUTE_READWRITE, &(*protections)[opened]))
			++opened;
		return opened;
	}

	// Loops can share a page, and only the first one opened there saw the page's own protection, so they close in reverse.
	void CloseLoops(const std::vector<CivModSwitchLoop>& loops, const std::vector<DWORD>& protections, size_t opened)
	{
		DWORD was = 0;
		while (opened > 0)
		{
			--opened;
			VirtualProtect(reinterpret_cast<void*>(loops[opened].address), CIV_MOD_SWITCH_JUMP_SIZE, protections[opened], &was);
		}
	}
}

void CivFindModSwitchLoops(const unsigned char* code, unsigned int size, unsigned int start, std::vector<CivModSwitchLoop>* found)
{
	for (unsigned int at = 0; at + kLoopSize <= size; ++at)
		if (LoopAt(code + at))
			found->push_back(CivModSwitchLoop(start + at, ReadAddress(code + at + kStepSlotAt), code[at + kStepQueryAt]));
}

std::string CivModSwitchProblem(const std::vector<CivModSwitchLoop>& found)
{
	if (found.size() != 4)
	{
		char text[100];
		sprintf_s(text, "its code was found %u times instead of four times", static_cast<unsigned int>(found.size()));
		return text;
	}
	std::vector<unsigned char> otherOffsets;
	for (size_t i = 0; i < found.size(); ++i)
	{
		if (found[i].stepSlot != found[0].stepSlot)
			return "the places that look like its code read the game's database through different functions";
		if (found[i].queryOffset != found[0].queryOffset)
			otherOffsets.push_back(found[i].queryOffset);
	}
	if (otherOffsets.size() != 2 || otherOffsets[0] != otherOffsets[1])
		return "the places that look like its code do not come in two pairs";
	return std::string();
}

std::string CivModSwitchReset(unsigned int stepSlot, unsigned int imageStart, unsigned int imageSize, unsigned int* reset)
{
	if (stepSlot < imageStart || imageSize < 4 || stepSlot - imageStart > imageSize - 4)
		return "the place its code reads the database's Step function from is outside the game";
	void* const step = *reinterpret_cast<void* const*>(stepSlot);
	HMODULE database = NULL;
	if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, reinterpret_cast<LPCWSTR>(step), &database)
		|| reinterpret_cast<void*>(GetProcAddress(database, "?Step@Results@Database@@QAE_NXZ")) != step)
		return "the function its code calls to read the game's database is not the database's Step";
	*reset = reinterpret_cast<unsigned int>(GetProcAddress(database, "?Reset@Results@Database@@QAE_NXZ"));
	if (!*reset)
		return "the game's database has no Reset";
	return std::string();
}

std::string CivFindModSwitch(const void* exe, std::vector<CivModSwitchLoop>* loops, unsigned int* reset)
{
	const unsigned char* const base = static_cast<const unsigned char*>(exe);
	const IMAGE_NT_HEADERS* nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + reinterpret_cast<const IMAGE_DOS_HEADER*>(base)->e_lfanew);
	const IMAGE_SECTION_HEADER* section = IMAGE_FIRST_SECTION(nt);
	for (int s = 0; s < nt->FileHeader.NumberOfSections; ++s, ++section)
		if (section->Characteristics & IMAGE_SCN_MEM_EXECUTE)
			CivFindModSwitchLoops(base + section->VirtualAddress, section->Misc.VirtualSize, reinterpret_cast<unsigned int>(base + section->VirtualAddress), loops);
	const std::string problem = CivModSwitchProblem(*loops);
	if (!problem.empty())
		return problem;
	return CivModSwitchReset((*loops)[0].stepSlot, reinterpret_cast<unsigned int>(base), nt->OptionalHeader.SizeOfImage, reset);
}

void CivModSwitchStub(const CivModSwitchLoop& loop, unsigned int stub, unsigned int reset, unsigned char* out)
{
	const unsigned char code[] = {
		0x8D, 0x4C, 0x24, 0,  // lea ecx,[esp+query]
		0xB8, 0, 0, 0, 0,     // mov eax,reset
		0xFF, 0xD0,           // call eax
		0, 0, 0, 0, 0, 0,     // the replaced bytes
		0xE9, 0, 0, 0, 0,     // jmp back into the loop
	};
	// Fails to compile when the bytes above no longer add up to the stub's size.
	typedef char StubSizeMatches[sizeof(code) == CIV_MOD_SWITCH_STUB_SIZE ? 1 : -1];
	memcpy(out, code, sizeof(code));
	out[kStubQueryAt] = loop.queryOffset;
	WriteAddress(out + kStubResetAt, reset);
	memcpy(out + kStubReplacedAt, kReplaced, sizeof(kReplaced));
	WriteAddress(out + kStubBackAt, loop.address + CIV_MOD_SWITCH_JUMP_SIZE - (stub + CIV_MOD_SWITCH_STUB_SIZE));
}

void CivModSwitchJump(unsigned int loop, unsigned int stub, unsigned char* out)
{
	out[0] = 0xE9;
	WriteAddress(out + 1, stub - (loop + 5));
	// Never run: the stub comes back after it.
	out[5] = 0x90;
}

std::string CivPatchModSwitch(const std::vector<CivModSwitchLoop>& loops, unsigned int reset)
{
	const SIZE_T size = loops.size() * CIV_MOD_SWITCH_STUB_SIZE;
	unsigned char* const stubs = static_cast<unsigned char*>(VirtualAlloc(NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
	if (!stubs)
		return "Windows did not give Bazaar memory for the fix";
	for (size_t i = 0; i < loops.size(); ++i)
		CivModSwitchStub(loops[i], reinterpret_cast<unsigned int>(stubs + i * CIV_MOD_SWITCH_STUB_SIZE), reset, stubs + i * CIV_MOD_SWITCH_STUB_SIZE);
	DWORD was = 0;
	if (!VirtualProtect(stubs, size, PAGE_EXECUTE_READ, &was))
	{
		VirtualFree(stubs, 0, MEM_RELEASE);
		return "Windows did not let Bazaar run the fix's own code";
	}
	std::vector<DWORD> protections(loops.size());
	const size_t opened = OpenLoops(loops, &protections);
	const bool allOpen = opened == loops.size();
	if (allOpen)
		for (size_t i = 0; i < loops.size(); ++i)
		{
			unsigned char jump[CIV_MOD_SWITCH_JUMP_SIZE];
			CivModSwitchJump(loops[i].address, reinterpret_cast<unsigned int>(stubs + i * CIV_MOD_SWITCH_STUB_SIZE), jump);
			memcpy(reinterpret_cast<void*>(loops[i].address), jump, sizeof(jump));
		}
	CloseLoops(loops, protections, opened);
	if (!allOpen)
	{
		VirtualFree(stubs, 0, MEM_RELEASE);
		return "Windows did not let Bazaar change the game's code";
	}
	FlushInstructionCache(GetCurrentProcess(), NULL, 0);
	return std::string();
}
