// Loading plugins, running their hooks, catching their crashes, and sharing memory with them.
#include "harness.h"
#include "fake_engine.h"

#include <malloc.h>
#include <stdio.h>

void TestLoading()
{
	const char* const names[] = {"toy_basic.dll", "toy_second.dll", "toy_shapes.dll", "toy_conflict.dll", "toy_newer.dll",
		"toy_major.dll", "toy_no_entry.dll", "toy_missing.dll", "toy_entry_fault.dll"};
	StartWith(names);

	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED), "a current plugin loads");
	Check(HasStatus("toy_second.dll", CIV_PLUGIN_LOADED), "a second plugin loads beside it");
	Check(HasStatus("toy_newer.dll", CIV_PLUGIN_NEWER_API), "a plugin built for a newer host is refused");
	Check(ReportRow("toy_newer.dll").problems.find("newer Bazaar") != std::string::npos, "the Plugins screen says why a plugin built for a newer host was refused");
	Check(LogHas("[Toy Newer] shutting down"), "a refused plugin is shut down before it is unloaded");
	Check(HasStatus("toy_major.dll", CIV_PLUGIN_OTHER_MAJOR), "a plugin built for another major version is refused");
	Check(HasStatus("toy_no_entry.dll", CIV_PLUGIN_NO_ENTRY), "a DLL without the entry point is refused");
	Check(HasStatus("toy_missing.dll", CIV_PLUGIN_FILE_NOT_LOADED), "a missing file is reported, not ignored");
	Check(HasStatus("toy_entry_fault.dll", CIV_PLUGIN_FAULTED_AT_LOAD), "a plugin that faults while loading is refused");
	Check(IsQuarantined("toy_entry_fault.dll"), "a plugin that faults while loading is quarantined");
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_REPLACE_CONFLICT), "a plugin replacing a function another plugin already replaces is turned off");
	Check(!IsInMemory("toy_conflict.dll"), "a plugin turned off for replacing a taken function is unloaded");
	char toldWhy[64];
	_snprintf_s(toldWhy, sizeof(toldWhy), _TRUNCATE, "[Toy Conflict] replace result %d", CIV_HOOK_REPLACE_TAKEN);
	Check(LogHas(toldWhy), "the refused plugin is told why");
	Check(LogHas("Toy Basic, higher in the list, already replaces"), "the refusal names the plugin that holds the replacement");
	Check(LogHas("Plugin Toy Conflict: Toy Basic"), "the refusal names the refused plugin, though it is still loading");
	Check(LogHas("[Toy Basic] starting"), "a plugin logging from its entry point is named in the log");
	Check(Call(TOY_FUNCTION("toy_basic.dll", ToyRegisterLate), -1) == CIV_HOOK_NOT_ALLOWED, "registering after loading is refused");

	const CivPluginReportRow basic = ReportRow("toy_basic.dll");
	Check(!basic.failed && basic.status == "Loaded", "the Plugins screen lists a loaded plugin as Loaded");
	Check(basic.name == "Toy Basic", "the Plugins screen names a loaded plugin by the name it gives");
	Check(basic.problems.empty(), "the Plugins screen shows no problems for a plugin that loaded cleanly");
	const CivPluginReportRow newer = ReportRow("toy_newer.dll");
	Check(newer.failed && newer.status == "Not loaded", "the Plugins screen lists a refused plugin as Not loaded");
	const CivPluginReportRow conflict = ReportRow("toy_conflict.dll");
	Check(conflict.failed && conflict.status == "Not loaded", "the Plugins screen lists a turned-off plugin as Not loaded");
	Check(conflict.problems.find("move it above Toy Basic") != std::string::npos, "a turned-off plugin's row says how to use it instead");
	Check(conflict.problems.find("already replaces FakeUnit::notify(...),") != std::string::npos,
		"a function no other shares its name with is named without its parameters");
	Check(conflict.problems.find("already replaces FakeUnit::Grow(int) const,") != std::string::npos,
		"an overloaded function is named with its parameters, which tell it apart");
	const CivPluginReportRow entryFault = ReportRow("toy_entry_fault.dll");
	Check(entryFault.failed && entryFault.status == "Turned off after a crash", "the Plugins screen lists a plugin that crashed while loading as turned off");
	Check(ReportRow("toy_missing.dll").name == "toy_missing.dll", "the Plugins screen names a plugin by its file until the plugin gives its own name");
}

void TestHooks()
{
	const char* const names[] = {"toy_basic.dll", "toy_second.dll", "toy_conflict.dll", "toy_newer.dll", "toy_major.dll"};
	StartWith(names);
	FakeUnit unit;
	ClearLog();
	Check(unit.add(2, 3) == 110, "after-hooks run in reverse load order (5 * 2 + 100 = 110)");
	const int basicBefore = LogIndex("[Toy Basic] before add");
	Check(basicBefore >= 0 && basicBefore < LogIndex("[Toy Second] before add"), "before-hooks run in load order");
	const int secondBefore = Call(TOY_FUNCTION("toy_second.dll", ToyBeforeCalls), -1);
	Check(unit.add(13, 1) == 98, "a veto skips the function; its result still passes through the after-hooks");
	Check(Call(TOY_FUNCTION("toy_second.dll", ToyBeforeCalls), -2) == secondBefore, "a veto skips the remaining before-hooks");
	unit.notify(5);
	Check(unit.m_notified == 10, "a replacement runs instead of the original, and can call the original itself");
	Check(unit.Subtract(7, 2) == 50, "the original gets the replacement's arguments in order and returns its result");
	Check(unit.name() == "Hooked Warrior", "an after-hook can change a function's returned reference");
	Check(unit.add(1, 1) == 104, "hooks from refused plugins never run, including the other hooks of a turned-off plugin");
	Check(unit.Grow(1) == 102, "a replacement runs on the overload it was registered for");
	Check(unit.Grow(1, 2) == 3, "a replacement leaves the other overload of the function alone");

	Load("toy_basic.dll");
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_DUPLICATE), "a plugin listed twice is loaded once");
	Check(unit.add(2, 3) == 110, "the hooks of a plugin listed twice still run once per call");
}

void TestShapes()
{
	const char* const names[] = {"toy_shapes.dll"};
	StartWith(names);
	FakeUnit unit;
	Check(FakeUnit::Twice(2) == 1004, "a static member function");
	Check(unit.Scale(5) == 1010, "a declared default argument still applies");
	Check(unit.Level() == 1007, "a const return value");
	Check(unit.Greet("Bob") == "Hello Bob!", "a class passed and returned by value");
	Check(!(unit == unit), "an operator");
	unit.Ignore(1);
	Check(Call(TOY_FUNCTION("toy_shapes.dll", ToyBeforeCalls), 0) == 1, "an unnamed parameter");
	Check(unit.Heal(5) == 1005, "a signature written in two versions, the first one active");
	Check(unit.Range() == 1004, "a signature whose #if closes after another function's signature");
	Check(FakeRules::Bonus(1) == 1002, "a namespace function defined with a qualified name");
	Check(FakeRules::Penalty(1) == 1000, "a qualified signature written in two versions, the second one active");
	Check(UsesHelper(1) == 1011, "a file-local static function");
	Check(CallsUnannounced(1) == 1004, "a function with no earlier declaration and a default argument");
}

void TestQuarantine()
{
	const char* const names[] = {"toy_basic.dll", "toy_second.dll", "toy_fault.dll", "toy_fault_before.dll", "toy_fault_replace.dll"};
	StartWith(names);
	FakeUnit unit;
	const int before = FaultCount();
	const int result = unit.add(2, 3);
	Check(FaultCount() == before + 2, "faulting before- and after-hooks are both caught and reported");
	Check(result == 110, "the other plugins' hooks still run on the same call");
	Check(IsQuarantined("toy_fault.dll"), "a faulting plugin is quarantined");
	Check(ReportRow("toy_fault.dll").problems.find("Faulted") != std::string::npos, "a quarantined plugin's row gives the fault");
	Check(unit.add(2, 3) == 110 && FaultCount() == before + 2, "a quarantined plugin's hooks never run again");
	const CivPluginReportRow faulted = ReportRow("toy_fault.dll");
	Check(faulted.failed && faulted.status == "Turned off after a crash", "the Plugins screen lists a quarantined plugin as turned off");

	const int calls = g_levelCalls;
	const int level = unit.Level();
	Check(FaultCount() == before + 3, "a faulting replacement is caught");
	Check(level == 7 && g_levelCalls == calls + 1, "when a replacement faults, the original runs instead, once");
	Check(unit.Level() == 7 && g_levelCalls == calls + 2, "the original keeps running once the replacement is quarantined");
	Check(FaultCount() == before + 3, "a quarantined replacement does not fault again");
}

void TestStrings()
{
	const char* const names[] = {"toy_basic.dll"};
	StartWith(names);
	ToyFillStringsFn* fill = TOY_FUNCTION("toy_basic.dll", ToyFillStrings);
	ToyReleaseStringsFn* release = TOY_FUNCTION("toy_basic.dll", ToyReleaseStrings);
	Check(fill && release, "the test plugin's string helpers are present");
	if (!fill || !release)
		return;
	std::string s;
	std::vector<std::string> v;
	fill(s, v);
	Check(s.size() > 40 && v.size() == 2 && v[1].size() == 300, "a plugin fills a string and vector the host owns");
	s += " The host grows it afterwards.";
	v.push_back(std::string(500, 'y'));
	std::string s2(400, 'z');
	std::vector<std::string> v2(3, std::string(100, 'w'));
	release(s2, v2);
	Check(s2.empty() && v2.empty(), "a plugin frees memory the host allocated");
	Check(_heapchk() == _HEAPOK, "the shared heap is intact afterwards");
}
