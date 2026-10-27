#include "harness.h"
#include "CivHostSaves.h"

#include <string.h>

namespace
{
	const char* const kSave = "toy_save.dll";
	const char* const kSecond = "toy_save_second.dll";
	const char* const kTwin = "toy_save_twin.dll";

	struct Listed
	{
		const char* toy;
		const char* modId;
	};

	// Leaves no saved data from an earlier section.
	template<size_t N> void StartWithMods(const Listed (&listed)[N])
	{
		std::vector<CivPluginFile> files;
		for (size_t i = 0; i < N; ++i)
			files.push_back(CivPluginFile(OutFile(listed[i].toy), listed[i].modId));
		StartWithNone();
		CivHostLoadPart(0);
		CivHostLoadPlugins(files);
	}

	const Listed kOne[] = {{kSave, "{MOD-A}"}};
	const Listed kThree[] = {{kSave, "{MOD-A}"}, {kSecond, "{mod-a}"}, {kTwin, "{MOD-B}"}};

	void Set(const char* toy, int value)
	{
		if (ToySaveSetFn* set = TOY_FUNCTION(toy, ToySaveSet))
			set(value);
	}

	void SetAll(int save, int second, int twin)
	{
		Set(kSave, save);
		Set(kSecond, second);
		Set(kTwin, twin);
	}

	int Value(const char* toy)
	{
		return Call(TOY_FUNCTION(toy, ToySaveValue), -100);
	}

	bool Values(int save, int second, int twin)
	{
		return Value(kSave) == save && Value(kSecond) == second && Value(kTwin) == twin;
	}

	int Loads(const char* toy)
	{
		return Call(TOY_FUNCTION(toy, ToySaveLoads), -1);
	}

	bool HadData(const char* toy)
	{
		ToySaveHadDataFn* had = TOY_FUNCTION(toy, ToySaveHadData);
		return had && had();
	}

	void CrashNext(const char* toy, int where)
	{
		if (ToySaveCrashNextFn* crash = TOY_FUNCTION(toy, ToySaveCrashNext))
			crash(where);
	}

	// Saved with kThree and the values 1, 2 and 3.
	std::string SavedThree()
	{
		StartWithMods(kThree);
		SetAll(1, 2, 3);
		return CivHostSavePart();
	}

	DWORD WINAPI SaveOnThread(void* out)
	{
		*static_cast<std::string*>(out) = CivHostSavePart();
		return 0;
	}

	std::string SaveFromAnotherThread()
	{
		std::string part;
		HANDLE thread = CreateThread(0, 0, &SaveOnThread, &part, 0, 0);
		WaitForSingleObject(thread, INFINITE);
		CloseHandle(thread);
		return part;
	}

	// Written by hand rather than by Bazaar, so the tests check the format itself.
	void PutNumber(std::string* part, unsigned int n)
	{
		part->append(reinterpret_cast<const char*>(&n), sizeof(n));
	}

	void PutText(std::string* part, const std::string& text)
	{
		PutNumber(part, (unsigned int)text.size());
		part->append(text);
	}

	// An entry is three texts, each with its length in front.
	size_t EntryEnd(const std::string& part, size_t at)
	{
		for (int text = 0; text < 3; ++text)
		{
			unsigned int size = 0;
			memcpy(&size, part.data() + at, sizeof(size));
			at += sizeof(size) + size;
		}
		return at;
	}

	std::string OneEntry(const char* modId, const std::string& data)
	{
		std::string part;
		PutNumber(&part, 1);
		PutNumber(&part, 1);
		PutText(&part, modId);
		PutText(&part, "");
		PutText(&part, data);
		return part;
	}
}

void TestSaveRegistration()
{
	StartWithMods(kOne);
	ToySaveRegisteredFn* registered = TOY_FUNCTION(kSave, ToySaveRegistered);
	Check(registered && registered(0) == CIV_HOOK_BAD_ID && registered(1) == CIV_HOOK_BAD_ID,
		"a plugin must give both a save function and a load function");
	Check(registered && registered(2) == CIV_HOOK_OK && registered(3) == CIV_HOOK_NOT_ALLOWED,
		"a plugin registers its save and load functions once");
	Check(registered && registered(4) == CIV_HOOK_NOT_ALLOWED, "a plugin registers them only from its entry function");

	const Listed noData[] = {{"toy_basic.dll", "{MOD-A}"}, {kSave, "{MOD-A}"}};
	StartWithMods(noData);
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED) && HasStatus(kSave, CIV_PLUGIN_LOADED),
		"a plugin of the same mod and plugin ID loads when the other keeps no data in saves");
	const Listed twins[] = {{kSave, "{MOD-A}"}, {kTwin, "{mod-a}"}};
	StartWithMods(twins);
	Check(HasStatus(kSave, CIV_PLUGIN_LOADED) && HasStatus(kTwin, CIV_PLUGIN_SAVE_ID_TAKEN)
		&& ReportRow(kTwin).problems.find("Toy Save, higher in the list, comes from the same mod") != std::string::npos,
		"a second plugin of the same mod with the same plugin ID is not loaded, and the Plugins screen says why");
	CivHostLoadPart(0);
}

void TestSaveRoundTrip()
{
	StartWithMods(kOne);
	Set(kSave, 5);
	CivHostLoadPart(0);
	Check(Loads(kSave) == 1 && !HadData(kSave) && Value(kSave) == 0,
		"a new game, or a save from before Bazaar kept plugin data, tells a plugin there is none");
	Set(kSave, 7);
	const std::string part = CivHostSavePart();
	Set(kSave, 0);
	Check(CivHostLoadPart(&part).empty() && HadData(kSave) && Value(kSave) == 7,
		"a plugin gets back the data it saved, written and read with the SDK's helpers");

	if (ToySaveWriteKeptFn* writeKept = TOY_FUNCTION(kSave, ToySaveWriteKept))
		writeKept();
	const std::string afterKept = CivHostSavePart();
	Set(kSave, 0);
	CivHostLoadPart(&afterKept);
	Check(Value(kSave) == 7, "a write with the saving of an earlier save adds nothing to the data");
	Check(LogHas("Plugin Toy Save wrote save data outside its save function"), "that write is logged, naming the plugin");
	CivHostLoadPart(0);
}

void TestSaveKeys()
{
	const std::string all = SavedThree();
	const Listed recased[] = {{kSave, "{mod-a}"}, {kSecond, "{MOD-A}"}, {kTwin, "{mod-b}"}};
	StartWithMods(recased);
	CivHostLoadPart(&all);
	Check(Values(1, 2, 3), "each plugin gets back only its own data, found by its mod's ID, in any case, and its plugin ID");
	CivHostLoadPart(0);
}

void TestSavesOfPluginsThatAreOff()
{
	const std::string all = SavedThree();
	const Listed onlySecond[] = {{kSecond, "{MOD-A}"}};
	StartWithMods(onlySecond);
	CivHostLoadPart(&all);
	Set(kSecond, 20);
	const std::string kept = CivHostSavePart();
	StartWithMods(kThree);
	CivHostLoadPart(&kept);
	Check(Values(1, 20, 3), "the data of plugins that are off goes into the next save unchanged");

	StartWithMods(onlySecond);
	CivHostLoadPart(&all);
	CivHostLoadPart(0);
	const std::string afterNewGame = CivHostSavePart();
	StartWithMods(kThree);
	CivHostLoadPart(&afterNewGame);
	Check(!HadData(kSave) && !HadData(kTwin), "a new game drops the kept data of plugins that are off too");
	CivHostLoadPart(0);
}

void TestSaveCrashes()
{
	const std::string all = SavedThree();
	StartWithMods(kThree);
	CivHostLoadPart(&all);
	SetAll(9, 22, 33);
	CrashNext(kSave, 1);
	int faults = FaultCount();
	const std::string afterSaveCrash = CivHostSavePart();
	Check(IsQuarantined(kSave) && FaultCount() == faults + 1, "a crash in a plugin's save function is caught and turns the plugin off");
	StartWithMods(kThree);
	CivHostLoadPart(&afterSaveCrash);
	Check(Values(1, 22, 33), "that save holds the crashed plugin's data as it was last loaded or saved, and the others' new data");

	Set(kSecond, 0);
	CrashNext(kSave, 2);
	faults = FaultCount();
	CivHostLoadPart(&all);
	Check(IsQuarantined(kSave) && FaultCount() == faults + 1 && !IsQuarantined(kSecond) && Value(kSecond) == 2,
		"a crash in a plugin's load function turns off that plugin alone, and the others still load");

	StartWithMods(kThree);
	SetAll(4, 5, 6);
	const std::string fromThread = SaveFromAnotherThread();
	SetAll(0, 0, 0);
	CivHostLoadPart(&fromThread);
	Check(Values(4, 5, 6), "a save made on another thread, as the game makes one, holds every plugin's data");
	CrashNext(kSave, 1);
	faults = FaultCount();
	SaveFromAnotherThread();
	Check(IsQuarantined(kSave) && FaultCount() == faults + 1, "a crash in a save function on another thread is caught too");
	Check(CivHostUnloadPlugins(), "after that crash, no plugin call still counts as running");
	CivHostLoadPart(0);
}

void TestDamagedSaves()
{
	const std::string all = SavedThree();
	StartWithMods(kThree);
	CivHostLoadPart(&all);
	const int loads = Loads(kTwin);
	Set(kSave, 0);
	// The first entry follows the format number and the count; the cut falls two bytes into the second.
	const std::string cut = all.substr(0, EntryEnd(all, 8) + 2);
	Check(CivHostLoadPart(&cut).find("some plugins") != std::string::npos && Value(kSave) == 1 && !HadData(kSecond)
		&& !HadData(kTwin) && Loads(kTwin) == loads + 1,
		"a damaged part is reported; the entries before the damage are read, and the plugins after it are told there is none");

	CivHostLoadPart(&all);
	std::string newer = all;
	newer[0] = 99;
	Check(CivHostLoadPart(&newer).find("newer Bazaar") != std::string::npos && !HadData(kSave) && !HadData(kSecond),
		"a part from a newer Bazaar is reported, and the plugins are told there is no data");
	const std::string empty;
	Check(CivHostLoadPart(&empty).find("damaged") != std::string::npos, "a part that could not be read at all is reported as damaged");

	CivHostLoadPart(&all);
	const std::string emptyEntry = OneEntry("{MOD-A}", "");
	CivHostLoadPart(&emptyEntry);
	Check(!HadData(kSave) && Value(kSave) == 0, "a plugin whose saved data is empty is told there is none");

	// The format before values, which the in-game probe build wrote: the same entries, without the count of values.
	std::string older = all;
	older[0] = 1;
	older.resize(older.size() - sizeof(unsigned int));
	SetAll(0, 0, 0);
	Check(CivHostLoadPart(&older).empty() && Values(1, 2, 3), "a part in the format before values loads, with every plugin's data");
	CivHostLoadPart(0);
}

void TestSaveReader()
{
	CivSaveReader none(0, 0);
	Check(none.ReadInt(5) == 5 && none.ReadText("fallback") == "fallback", "with no data, every read gives back its fallback");

	std::string data;
	PutNumber(&data, 7);
	PutNumber(&data, 10);
	data += "abc";
	PutNumber(&data, 8);
	CivSaveReader reader(data.data(), (int)data.size());
	Check(reader.ReadInt(0) == 7, "a whole number reads back");
	Check(reader.ReadText("fallback") == "fallback", "a text whose length runs past the data gives back its fallback");
	Check(reader.ReadInt(77) == 77, "after a failed read, every later read gives back its fallback");

	CivSaveReader halfNumber(data.data(), 2);
	char out[4];
	Check(halfNumber.ReadInt(9) == 9 && !halfNumber.Read(out, -1), "a number cut short, or a negative size, is not read");
}
