#include "harness.h"

namespace
{
	const char* const kValues = "toy_values.dll";
	const char* const kReader = "toy_values_reader.dll";
	const char* const kDecline = "toy_decline.dll";
	const char* const kTwin = "toy_function_twin.dll";
	const char* const kSave = "toy_save.dll";
	const char* const kValuesMod = "{VALUES}";
	const char* const kReaderMod = "{READER}";

	void LoadList(const std::vector<CivPluginFile>& files)
	{
		StartWithNone();
		CivHostLoadPlugins(files);
	}

	// False, after a failed check, when a toy did not load and so its functions cannot be called.
	bool StartBoth(bool readerFirst)
	{
		const CivPluginFile values(OutFile(kValues), kValuesMod);
		const CivPluginFile reader(OutFile(kReader), kReaderMod);
		std::vector<CivPluginFile> files;
		files.push_back(readerFirst ? reader : values);
		files.push_back(readerFirst ? values : reader);
		LoadList(files);
		const bool loaded = HasStatus(kValues, CIV_PLUGIN_LOADED) && HasStatus(kReader, CIV_PLUGIN_LOADED);
		Check(loaded, "the plugins that publish and call functions load");
		return loaded;
	}
}

void TestPublishedFunctions()
{
	if (!StartBoth(false))
		return StartWithNone();
	ToyReaderFunctionFoundFn* found = TOY_FUNCTION(kReader, ToyReaderFunctionFound);
	ToyReaderFindsFn* finds = TOY_FUNCTION(kReader, ToyReaderFinds);
	Check(found(0) == 1, "a plugin finds another plugin's published functions");
	Check(found(1) == 0 && found(2) == 0, "a function cannot be found as another type, or under a name nobody published");
	Check(!finds("{OTHER}", "", "Doubled") && !finds(kValuesMod, "OTHER", "Doubled"),
		"a function cannot be found under another mod's ID or another plugin ID");
	bool called = false;
	Check(TOY_FUNCTION(kReader, ToyReaderDoubled)(21, &called) == 42 && called, "a call runs the other plugin's function and returns its result");
	ToyReaderDigitsFn* digits = TOY_FUNCTION(kReader, ToyReaderDigits);
	Check(digits(0) == 7 && digits(2) == 12 && digits(3) == 123 && digits(4) == 1234,
		"functions with no parameters, or up to four, get them all in order");
	TOY_FUNCTION(kReader, ToyReaderGreet)("Bob");
	Check(LogHas("[Toy Values] hello Bob"), "a function that returns nothing runs");
	ToyValuesPublishedFn* published = TOY_FUNCTION(kValues, ToyValuesPublished);
	Check(published(0) == CIV_HOOK_BAD_ID && LogHas("its function Doubled was refused because the plugin already publishes a function of that name"),
		"a second function of the same name is refused, and the log says why");
	Check(published(1) == CIV_HOOK_BAD_ID && published(2) == CIV_HOOK_BAD_ID, "a function needs a name and a function");
	Check(TOY_FUNCTION(kValues, ToyValuesPublishLate)() == CIV_HOOK_NOT_ALLOWED
			&& LogHas("its function Late was refused because it was published outside the plugin's entry function"),
		"functions are published only from the entry function, and the log says why");
	StartWithNone();
}

void TestFunctionCrashes()
{
	if (!StartBoth(false))
		return StartWithNone();
	const int faults = FaultCount();
	bool called = true;
	Check(TOY_FUNCTION(kReader, ToyReaderCrash)(&called) == 0 && !called && FaultCount() == faults + 1,
		"a crash in a published function is caught, and the call says it did not run");
	Check(IsQuarantined(kValues) && !IsQuarantined(kReader), "the crash turns off the plugin whose function it was, not the caller");
	Check(LogHas("its function Crash, which Toy Reader called"), "the log says whose function crashed and who called it");
	called = true;
	Check(TOY_FUNCTION(kReader, ToyReaderDoubled)(21, &called) == 0 && !called, "the functions of a plugin that is off do not run");
	StartWithNone();
}

void TestFunctionLoadOrder()
{
	if (!StartBoth(true))
		return StartWithNone();
	Check(TOY_FUNCTION(kReader, ToyReaderFunctionFound)(0) == 0, "while plugins load, a plugin cannot find the functions of one below it");
	bool called = true;
	const bool unfoundRan = TOY_FUNCTION(kReader, ToyReaderDoubled)(5, &called) != 0 || called;
	called = true;
	Check(!unfoundRan && TOY_FUNCTION(kReader, ToyReaderCallUnfound)(&called) == 0 && !called,
		"a function that was not found, or never looked for, does not run");
	called = false;
	Check(TOY_FUNCTION(kReader, ToyReaderFindDoubledNow)() && TOY_FUNCTION(kReader, ToyReaderDoubled)(5, &called) == 10 && called,
		"once they have all loaded, it can");
	StartWithNone();
}

void TestFunctionsOfRefusedPlugins()
{
	std::vector<CivPluginFile> files;
	files.push_back(CivPluginFile(OutFile(kDecline), "{DECLINE}"));
	files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kTwin), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kReader), kReaderMod));
	LoadList(files);
	if (!HasStatus(kValues, CIV_PLUGIN_LOADED) || !HasStatus(kReader, CIV_PLUGIN_LOADED))
	{
		Check(false, "the plugins that publish and call functions load after one that declines");
		return StartWithNone();
	}
	ToyReaderFindsFn* finds = TOY_FUNCTION(kReader, ToyReaderFinds);
	bool called = false;
	Check(!finds("{DECLINE}", "", "Doubled") && TOY_FUNCTION(kReader, ToyReaderDoubled)(21, &called) == 42 && called,
		"the functions of a plugin that declines are dropped, and the next plugin's function of the same name is kept");
	Check(HasStatus(kTwin, CIV_PLUGIN_ID_TAKEN) && !finds(kValuesMod, "", "Tripled")
			&& LogHas("Toy Values, higher in the list, comes from the same mod and publishes functions with no plugin ID too"),
		"a plugin that publishes functions is refused when one higher in the list, from the same mod with the same plugin ID, "
		"publishes functions too, and its functions are dropped");

	files.clear();
	files.push_back(CivPluginFile(OutFile(kTwin), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kSave), kValuesMod));
	LoadList(files);
	Check(HasStatus(kTwin, CIV_PLUGIN_LOADED) && HasStatus(kSave, CIV_PLUGIN_LOADED),
		"a plugin that keeps data loads below one from the same mod that only publishes functions");
	StartWithNone();
}

void TestFunctionsWhenUnloading()
{
	if (!StartBoth(true))
		return StartWithNone();
	TOY_FUNCTION(kReader, ToyReaderFindDoubledNow)();
	const int faults = FaultCount();
	CivHostUnloadPlugins();
	Check(FaultCount() == faults && LogHas("[Toy Reader] Doubled did not run while shutting down"),
		"a plugin shutting down cannot call the functions of a plugin already unloaded below it");

	std::vector<CivPluginFile> files;
	files.push_back(CivPluginFile(OutFile(kReader), kReaderMod));
	LoadList(files);
	Check(HasStatus(kReader, CIV_PLUGIN_LOADED) && !TOY_FUNCTION(kReader, ToyReaderFinds)(kValuesMod, "", "Doubled"),
		"once plugins are loaded again, the functions of a plugin no longer loaded are gone");
	StartWithNone();
}

// Toy Kept Caller stays in memory for the rest of the run, so no other section may load it.
void TestFunctionsOfKeptPlugins()
{
	const char* const kKeptCaller = "toy_kept_caller.dll";
	std::vector<CivPluginFile> files;
	files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kKeptCaller), "{KEPT}"));
	LoadList(files);
	if (!HasStatus(kKeptCaller, CIV_PLUGIN_LOADED))
	{
		Check(false, "a plugin that calls a function loads below the one that publishes it");
		return StartWithNone();
	}
	ToyKeptCallerDoubledFn* doubled = TOY_FUNCTION(kKeptCaller, ToyKeptCallerDoubled);
	bool called = false;
	Check(doubled(&called) == 42 && called, "a plugin calls a function it found while loading");
	TOY_FUNCTION(kKeptCaller, ToyFaultOnShutdown)();
	files.pop_back();
	LoadList(files);
	called = true;
	Check(IsInMemory(kKeptCaller) && doubled(&called) == 0 && !called,
		"a plugin kept in memory after its shutdown crashed cannot call a function it found before the plugins loaded again");
	StartWithNone();
}
