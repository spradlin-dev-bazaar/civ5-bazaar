// Loading plugins, running their hooks, catching their crashes, and sharing memory with them.
#include "harness.h"
#include "fake_engine.h"
#include "CivHooks.h"
#include "CivHostCrash.h"
#include "CivHostHand.h"
#include "CivHostHooks.h"
#include "CivHostPath.h"

#include <dbghelp.h>
#include <malloc.h>
#include <stdio.h>

#include <exception>

namespace
{
	// Mirrors the host's "[plugin name] message" log lines and the toys' LogResult message.
	std::string ResultLine(const char* pluginName, const char* what, int result)
	{
		char line[128];
		_snprintf_s(line, sizeof(line), _TRUNCATE, "[%s] %s %d", pluginName, what, result);
		return line;
	}

	// Mirrors the host's line for a plugin that loaded.
	std::string LoadedLine(const char* pluginName, int major, int minor)
	{
		char line[128];
		_snprintf_s(line, sizeof(line), _TRUNCATE, "Plugin %s 1.0 loaded (built for API %d.%d).", pluginName, major, minor);
		return line;
	}

	int AfterHookCount(int hookId)
	{
		int count = 0;
		for (const CivHookEntry* e = g_CivHookPoints[hookId].after; e; e = e->next)
			++count;
		return count;
	}

	// The toy registers a hook and is then declined or refused; toy_second loads after it and doubles add's result.
	void CheckTurnedAwayAfterRegistering(const char* toy, CivPluginStatus status, const char* what)
	{
		const char* const names[] = {toy, "toy_second.dll"};
		StartWith(names);
		FakeUnit unit;
		Check(HasStatus(toy, status), what);
		const std::string name = toy;
		Check(unit.add(2, 3) == 10, (name + ": its hook never runs, and the next plugin's hooks do").c_str());
		Check(AfterHookCount(CivHooks::FakeUnit_add::ID) == 1, (name + ": only the next plugin's hook is registered").c_str());
		Check(!CivHandKeepDeadSlotOpen(1), (name + ": its hand-placed hook never runs").c_str());
	}

	int s_waiting = 0;
	int s_later = 0;

	int RecordTwice(const EXCEPTION_POINTERS* info)
	{
		CivCrashRecord(EXCEPTION_ACCESS_VIOLATION, info, &s_waiting);
		CivCrashRecord(EXCEPTION_ACCESS_VIOLATION, info, &s_later);
		return EXCEPTION_EXECUTE_HANDLER;
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	void CrashRecordedTwice()
	{
		__try
		{
			int* volatile nowhere = 0;
			*nowhere = 1;
		}
		__except (RecordTwice(GetExceptionInformation()))
		{
		}
	}
}

void TestLoading()
{
	const char* const names[] = {"toy_basic.dll", "toy_second.dll", "toy_shapes.dll", "toy_conflict.dll", "toy_newer.dll",
		"toy_major.dll", "toy_no_version.dll", "toy_newer_imports.dll", "toy_older.dll", "toy_ordinals.dll", "toy_no_entry.dll",
		"toy_missing.dll", "toy_entry_fault.dll", "toy_load_fails.dll", "toy_64bit.dll", "toy_empty_name.dll"};
	StartWith(names);

	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED), "a current plugin loads");
	Check(HasStatus("toy_second.dll", CIV_PLUGIN_LOADED), "a second plugin loads beside it");
	Check(HasStatus("toy_newer.dll", CIV_PLUGIN_NEWER_API), "a plugin built for a newer host is refused");
	Check(ReportRow("toy_newer.dll").problems.find("newer Bazaar") != std::string::npos, "the Plugins screen says why a plugin built for a newer host was refused");
	Check(!LogHas("[Toy Newer]"), "a plugin built for a newer host never runs: its version is read from its file");
	Check(HasStatus("toy_major.dll", CIV_PLUGIN_OTHER_MAJOR), "a plugin built for another major version is refused");
	Check(!LogHas("[Toy Major]"), "a plugin built for another major version never runs");
	Check(CivApiRefusedAsBeforeFreeze(0, 5, 0, 4) && CivApiRefusedAsBeforeFreeze(0, 9, 0, 3) && !CivApiRefusedAsBeforeFreeze(0, 5, 0, 5)
		&& !CivApiRefusedAsBeforeFreeze(1, 2, 1, 0), "from the freeze on, a plugin built before it is refused");
	Check(!CivApiRefusedAsBeforeFreeze(0, 4, 0, 3), "before the freeze, a plugin built for an older minor version still loads");
	Check(HasStatus("toy_no_version.dll", CIV_PLUGIN_NO_API_VERSION), "a plugin that does not export its API version is refused");
	Check(ReportRow("toy_no_version.dll").problems.find("which Bazaar") != std::string::npos, "the Plugins screen says the plugin does not say which Bazaar it was built for");
	Check(!LogHas("[Toy No Version]"), "a plugin that does not export its API version never runs");
	Check(HasStatus("toy_newer_imports.dll", CIV_PLUGIN_NEWER_API), "a plugin built for a newer host that uses a function this host lacks is refused by its version, not by a Windows load error");
	const HMODULE unloadable = LoadLibraryExW(CivWide(OutFile("toy_newer_imports.dll")).c_str(), 0, LOAD_WITH_ALTERED_SEARCH_PATH);
	Check(!unloadable, "Windows itself cannot load toy_newer_imports.dll, so only its version could have refused it");
	if (unloadable)
		FreeLibrary(unloadable);
	Check(LogHas(LoadedLine("Toy Basic", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR).c_str()), "the host reads the version a plugin exports");
	Check(HasStatus("toy_older.dll", CIV_PLUGIN_LOADED), "a plugin built for an older minor version loads");
	Check(LogHas(LoadedLine("Toy Older", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR - 1).c_str()), "the host reads an older plugin's own version");
	Check(HasStatus("toy_ordinals.dll", CIV_PLUGIN_LOADED), "a plugin whose exports are numbered out of name order loads: its version is found by name");
	Check(HasStatus("toy_no_entry.dll", CIV_PLUGIN_NO_ENTRY), "a DLL without the entry point is refused");
	Check(HasStatus("toy_missing.dll", CIV_PLUGIN_FILE_NOT_LOADED), "a missing file is reported, not ignored");
	Check(HasStatus("toy_load_fails.dll", CIV_PLUGIN_FILE_NOT_LOADED)
			&& ReportRow("toy_load_fails.dll").problems.find("Windows could not load the file (error 126).") != std::string::npos,
		"a current plugin Windows cannot load, here for a DLL it imports from that is missing, is refused with Windows' error");
	Check(HasStatus("toy_64bit.dll", CIV_PLUGIN_FILE_NOT_LOADED)
			&& ReportRow("toy_64bit.dll").problems.find("It is a 64-bit DLL") != std::string::npos,
		"a 64-bit DLL is refused as one, not as a DLL built for another Bazaar");
	Check(HasStatus("toy_empty_name.dll", CIV_PLUGIN_LOADED) && ReportRow("toy_empty_name.dll").name == "toy_empty_name.dll",
		"a plugin that gives an empty name is named by its file");
	Check(Find("toy_empty_name.dll") && Find("toy_empty_name.dll")->version.empty(),
		"a version that points nowhere is read as none, and the plugin still loads");
	Check(HasStatus("toy_entry_fault.dll", CIV_PLUGIN_FAULTED_AT_LOAD), "a plugin that faults while loading is refused");
	Check(IsQuarantined("toy_entry_fault.dll"), "a plugin that faults while loading is quarantined");
	Check(LogHas("    #00 toy_entry_fault.dll+0x"), "a plugin that faults while loading has its call stack logged");
	Check(LogHas("  It stopped at toy_entry_fault.dll+0x"), "a fault that touched no memory says only where it stopped");
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_REPLACE_CONFLICT), "a plugin replacing a function another plugin already replaces is turned off");
	Check(!IsInMemory("toy_conflict.dll"), "a plugin turned off for replacing a taken function is unloaded");
	Check(LogHas(ResultLine("Toy Conflict", "replace result", CIV_HOOK_REPLACE_TAKEN).c_str()), "the refused plugin is told why");
	Check(LogHas("Toy Basic, higher in the list, already replaces"), "the refusal names the plugin that holds the replacement");
	Check(LogHas("Plugin Toy Conflict: Toy Basic"), "the refusal names the refused plugin, though it is still loading");
	Check(LogHas("[Toy Basic] starting"), "a plugin logging from its entry point is named in the log");
	Check(Call(TOY_FUNCTION("toy_basic.dll", ToyRegisterLate), -1) == CIV_HOOK_NOT_ALLOWED, "registering after loading is refused");
	Check(Call(TOY_FUNCTION("toy_basic.dll", ToyRegisterHandLate), -1) == CIV_HOOK_NOT_ALLOWED, "registering a hand-placed hook after loading is refused");

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
	// Without the flags a report adds, so a report that leaves them set is caught whatever ran before.
	const DWORD options = SymGetOptions() & ~(SYMOPT_DEFERRED_LOADS | SYMOPT_LOAD_LINES | SYMOPT_FAIL_CRITICAL_ERRORS | SYMOPT_NO_PROMPTS);
	SymSetOptions(options);
	const int result = unit.add(2, 3);
	Check(FaultCount() == before + 2 && !LastFaultWhileShuttingDown(),
		"faulting before- and after-hooks are both caught and reported as crashes, not as ones while shutting down");
	Check(SymGetOptions() == options, "a crash report puts back dbghelp's settings, which the game's own crash handling shares");
	Check(result == 110, "the other plugins' hooks still run on the same call");
	Check(IsQuarantined("toy_fault.dll"), "a faulting plugin is quarantined");
	Check(ReportRow("toy_fault.dll").problems.find("Faulted") != std::string::npos, "a quarantined plugin's row gives the fault");
	Check(LogHas("  It read address 0x00000000, at toy_fault.dll+0x"), "the log says what memory the crash touched, and where in the plugin");
	const int top = LogIndex("    #00 toy_fault.dll+0x");
	Check(top >= 0 && LogLine(top).find(" (Explode, toy_plugins.cpp line ") != std::string::npos, "a frame in a plugin built with its .pdb names the function and the source line");
	char caller[64];
	_snprintf_s(caller, sizeof(caller), _TRUNCATE, " (AfterAdd, toy_plugins.cpp line %d)", Call(TOY_FUNCTION("toy_fault.dll", ToyExplodeLine), -1));
	Check(LogLine(top + 1).find("    #01 toy_fault.dll+0x") == 0 && LogLine(top + 1).find(caller) != std::string::npos, "a caller's frame names the line of its call, not the line after it");
	Check(LogLine(top + 2).find("    #02 harness.exe+0x") == 0, "the call stack goes on from the plugin into the code that called it");
	const int unnamed = LogIndex("    #00 toy_fault_before.dll+0x");
	Check(unnamed >= 0 && LogLine(unnamed).find('(') == std::string::npos, "a frame in a plugin without its .pdb names no function, rather than a wrong exported one");
	ClearLog();
	Check(unit.add(2, 3) == 110, "the other plugins' hooks still run once the faulting ones are quarantined");
	Check(!LogHas("Plugin Toy Fault: Faulted") && !LogHas("Plugin Toy Fault Before: Faulted"), "a quarantined plugin's hooks never run again");
	const CivPluginReportRow faulted = ReportRow("toy_fault.dll");
	Check(faulted.failed && faulted.status == "Turned off after a crash", "the Plugins screen lists a quarantined plugin as turned off");

	const int calls = g_levelCalls;
	const int level = unit.Level();
	Check(FaultCount() == before + 3 && !LastFaultWhileShuttingDown(), "a faulting replacement is caught and reported as a crash");
	Check(level == 7 && g_levelCalls == calls + 1, "when a replacement faults, the original runs instead, once");
	Check(unit.Level() == 7 && g_levelCalls == calls + 2, "the original keeps running once the replacement is quarantined");
	Check(FaultCount() == before + 3, "a quarantined replacement does not fault again");
	Check(LogHas("  It ran code at address 0x00000000."), "a call through a null function pointer is logged as running code there");
	const int nowhere = LogIndex("    #00 0x00000000");
	Check(nowhere >= 0 && LogLine(nowhere + 1).find("    #01 toy_fault_replace.dll+0x") == 0, "the call stack of a call through a null pointer starts again at its caller");

	const char* const first[] = {"toy_fault.dll"};
	StartWith(first);
	const HMODULE freed = (HMODULE)Find("toy_fault.dll")->module;
	unit.add(2, 3);
	const char* const second[] = {"toy_overflow.dll"};
	StartWith(second);
	Check(Find("toy_overflow.dll")->module == freed, "the second toy loads where the first one was, so the next check means something");
	unit.Range();
	const int reused = LogIndex("    #00 toy_overflow.dll+0x");
	Check(reused >= 0 && LogLine(reused).find(" (Deeper, toy_plugins.cpp line ") != std::string::npos,
		"a plugin loaded where another was freed is named from its own .pdb, not the freed plugin's");

	// toy_fault_before's crash makes the crash log record the DLL loaded behind Bazaar's back, before it is freed.
	StartWithNone();
	const HMODULE behind = LoadLibraryExW(CivWide(OutFile("toy_fault.dll")).c_str(), 0, LOAD_WITH_ALTERED_SEARCH_PATH);
	const char* const recorder[] = {"toy_fault_before.dll"};
	StartWith(recorder);
	unit.add(2, 3);
	StartWithNone();
	FreeLibrary(behind);
	StartWith(second);
	Check(behind && Find("toy_overflow.dll")->module == behind, "the plugin loads where the DLL freed behind Bazaar's back was");
	unit.Range();
	const int unrecorded = LogIndex("    #00 toy_overflow.dll+0x");
	Check(unrecorded >= 0 && LogLine(unrecorded).find('(') == std::string::npos,
		"a plugin loaded where a DLL was freed behind Bazaar's back names no function, rather than that DLL's");
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

void TestRegistration()
{
	const char* const names[] = {"toy_bad_hooks.dll"};
	StartWith(names);
	Check(LogHas(ResultLine("Toy Bad Hooks", "unknown id", CIV_HOOK_BAD_ID).c_str()), "registering a hook with an unknown id is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "negative id", CIV_HOOK_BAD_ID).c_str()), "registering a hook with a negative id is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "kind past the last", CIV_HOOK_BAD_KIND).c_str()), "registering a hook of a kind past the last is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "negative kind", CIV_HOOK_BAD_KIND).c_str()), "registering a hook of a negative kind is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "no function", CIV_HOOK_BAD_ID).c_str()), "registering a hook with no function is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "hook point that is gone", CIV_HOOK_BAD_ID).c_str()),
		"registering a hook point whose function is gone is refused");
	Check(LogHas("Plugin Toy Bad Hooks asked for hook ") && LogHas("which this Bazaar no longer has"),
		"the log says a plugin asked for a hook point that is gone and needs rebuilding");
	Check(LogHas(ResultLine("Toy Bad Hooks", "an index not its own", CIV_HOOK_NOT_ALLOWED).c_str()),
		"registering a hook under an index not the plugin's own is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "hand-placed hook for an index not its own", CIV_HOOK_NOT_ALLOWED).c_str()),
		"registering a hand-placed hook under an index not the plugin's own is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "second replace", CIV_HOOK_REPLACE_TAKEN).c_str()),
		"a plugin replacing the same function twice has the second replacement refused");
	Check(HasStatus("toy_bad_hooks.dll", CIV_PLUGIN_LOADED), "a plugin whose bad registrations were refused still loads");
	Check(ReportRow("toy_bad_hooks.dll").problems.find("this plugin already replaces it") != std::string::npos,
		"the Plugins screen shows that a plugin's second replacement of one function was refused");
	FakeUnit unit;
	Check(unit.Range() == 500, "a plugin's first replacement of a function still runs after its second was refused");
	Check(unit.add(2, 3) == 5, "refused registrations add no hooks");
	Check(LogHas(ResultLine("Toy Bad Hooks", "hand-placed hook past the last", CIV_HOOK_BAD_ID).c_str()), "registering a hand-placed hook past the last is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "negative hand-placed hook", CIV_HOOK_BAD_ID).c_str()), "registering a negative hand-placed hook is refused");
	Check(LogHas(ResultLine("Toy Bad Hooks", "hand-placed hook with no function", CIV_HOOK_BAD_ID).c_str()), "registering a hand-placed hook with no function is refused");
	Check(!CivHandKeepDeadSlotOpen(1), "refused hand-placed hook registrations add nothing");
}

void TestTurnedAwayAfterRegistering()
{
	CheckTurnedAwayAfterRegistering("toy_decline.dll", CIV_PLUGIN_ENTRY_DECLINED, "a plugin whose entry function declines is not loaded");
	Check(ReportRow("toy_decline.dll").problems.find("Declined") != std::string::npos, "the Plugins screen says the plugin declined");
	Check(LogHas("[Toy Decline] shutting down"), "a plugin that declined is shut down");
	Check(!IsInMemory("toy_decline.dll"), "a plugin that declined is released");
	CheckTurnedAwayAfterRegistering("toy_late_fault.dll", CIV_PLUGIN_FAULTED_AT_LOAD, "a plugin that faults after registering a hook is refused");
}

void TestVetoAndReplace()
{
	const char* const names[] = {"toy_second.dll", "toy_veto.dll"};
	StartWith(names);
	FakeUnit unit;
	Check(unit.Subtract(7, 2) == 50, "a replacement runs when no before-hook vetoes");
	Check(unit.Subtract(99, 1) == 77, "a veto skips the replacement as well as the original, and the call returns the veto's result");
	Check(unit.Scale(99, 3) == 0 && unit.Scale(4, 3) == 12, "a veto that sets no result returns the type's default");
	Check(unit.name() == "Warrior", "a veto that sets no reference result runs the original after all, since a reference can't be empty");
	Check(unit.Greet("veto") == "Vetoed" && unit.Greet("quiet").empty() && unit.Greet("Bob") == "Hello Bob",
		"a function returning a class returns the veto's result, or an empty one when the veto sets none");
}

void TestExceptions()
{
	StartWithNone();
	FakeUnit unit;
	const int original = unit.Range();
	// toy_throw loads last, so its after-hook runs first and toy_shapes' runs after it.
	const char* const names[] = {"toy_shapes.dll", "toy_throw.dll"};
	StartWith(names);
	const int before = FaultCount();
	const int range = unit.Range();
	Check(FaultCount() == before + 1, "a C++ exception thrown out of a plugin hook is caught and reported");
	Check(!std::uncaught_exception(), "no C++ exception is left in flight after the host catches one");
	Check(range == original + 1000, "the hooks after the one that threw still run, on the original's result");
	Check(IsQuarantined("toy_throw.dll"), "the plugin that threw is quarantined");
	Check(ReportRow("toy_throw.dll").problems.find("0xE06D7363") != std::string::npos, "the Plugins screen gives the C++ exception's code");
	const int threw = LogIndex("Plugin Toy Throw: Faulted");
	const int thrower = LogIndex("toy_throw.dll+0x", threw);
	Check(threw >= 0 && thrower > threw && LogLine(thrower).find("    #") == 0, "the call stack of a C++ exception reaches the plugin function that threw it");
	ClearLog();
	Check(unit.Range() == original + 1000, "the other plugin's hook keeps running after the quarantine");
	Check(!LogHas("Plugin Toy Throw: Faulted"), "the hook that threw never runs again");

	const char* const overflowing[] = {"toy_overflow.dll"};
	StartWith(overflowing);
	const int beforeOverflow = FaultCount();
	unit.Range();
	Check(FaultCount() == beforeOverflow + 1 && IsQuarantined("toy_overflow.dll"), "a plugin that runs out of stack is caught and quarantined");
	Check(LogHas("Plugin Toy Overflow: Faulted (code 0xC00000FD)"), "the log gives the stack overflow's code");
	Check(LogHas("    #00 toy_overflow.dll+0x") && LogHas("    #63 toy_overflow.dll+0x"), "a stack overflow's call stack is walked, as far as the frames shown go");
	Check(LogHas("    (more frames not shown)"), "a call stack cut short says so");
	Check(unit.Range() == original, "the game's function keeps working after a plugin's stack overflow");

	CrashRecordedTwice();
	const std::vector<std::string> laterLines = CivCrashReport(&s_later);
	const std::vector<std::string> waitingLines = CivCrashReport(&s_waiting);
	Check(laterLines.size() == 1 && laterLines[0] == "  The call stack was not recorded, because another plugin's crash was still being reported.", "a crash during another crash's report says its stack was not recorded");
	Check(waitingLines.size() > 2 && waitingLines[1] == "  Call stack, innermost first, as file+offset:", "the first crash keeps its own record and call stack");
}
