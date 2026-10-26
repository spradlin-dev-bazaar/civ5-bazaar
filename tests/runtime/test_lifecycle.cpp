// Unloading plugins, changing the plugin list, and plugins that cannot be unloaded safely.
#include "harness.h"
#include "fake_engine.h"

namespace
{
	int s_addDuringShutdown = -1;

	void AddDuringShutdown()
	{
		FakeUnit unit;
		s_addDuringShutdown = unit.add(2, 3);
	}

	bool ChangePluginsNow()
	{
		return CivHostSetPlugins(std::vector<std::string>()) != CIV_PLUGINS_BUSY;
	}

	void CallTwice()
	{
		FakeUnit::Twice(2);
	}

	void LoadEntryBreak()
	{
		Load("toy_entry_break.dll");
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	bool BreaksOut(void (*fn)())
	{
		__try
		{
			fn();
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
			return true;
		}
		return false;
	}
}

void TestUnloading()
{
	const char* const names[] = {"toy_basic.dll", "toy_second.dll", "toy_shapes.dll", "toy_fault.dll", "toy_entry_fault.dll",
		"toy_fault_kept.dll"};
	StartWith(names);
	s_addDuringShutdown = -1;
	FakeUnit unit;
	unit.add(2, 3);
	Check(IsQuarantined("toy_fault.dll") && IsQuarantined("toy_fault_kept.dll"), "the faulting plugins are quarantined before the plugins unload");
	ToySetShutdownProbeFn* setProbe = TOY_FUNCTION("toy_basic.dll", ToySetShutdownProbe);
	ToyFaultOnShutdownFn* faultAgain = TOY_FUNCTION("toy_fault_kept.dll", ToyFaultOnShutdown);
	Check(setProbe && faultAgain, "the test plugins can be told what to do while shutting down");
	if (!setProbe || !faultAgain)
		return;
	setProbe(&AddDuringShutdown);
	faultAgain();
	const int faults = FaultCount();
	ClearLog();

	Check(CivHostUnloadPlugins(), "plugins unload when none is running");
	Check(CivHostPlugins().empty(), "no plugin is listed after unloading");
	Check(s_addDuringShutdown == 5, "hooks are already removed while plugins shut down");
	const int second = LogIndex("[Toy Second] shutting down");
	Check(second >= 0 && second < LogIndex("[Toy Basic] shutting down"), "plugins shut down in reverse load order");
	Check(unit.add(2, 3) == 5, "no hooks remain on a member function after unloading");
	Check(FakeUnit::Twice(2) == 4, "no hooks remain on a static member function after unloading");
	Check(!IsInMemory("toy_basic.dll"), "an unloaded plugin's DLL is released");
	Check(LogHas("[Toy Fault] shutting down"), "a plugin that faulted in a hook is still shut down");
	Check(!IsInMemory("toy_fault.dll"), "a plugin that faulted in a hook is released after its shutdown");
	Check(LogHas("[Toy Entry Fault] shutting down"), "a plugin that faulted while loading is still shut down");
	Check(!IsInMemory("toy_entry_fault.dll"), "a plugin that faulted while loading is released after its shutdown");
	Check(IsInMemory("toy_fault_kept.dll"), "a faulted plugin that faults again while shutting down stays in memory");
	Check(FaultCount() == faults, "a second fault while shutting down is not reported again");
}

void TestReload()
{
	const char* const names[] = {"toy_basic.dll", "toy_reentrant.dll", "toy_entry_fault.dll"};
	const char* const respelled[] = {".\\toy_basic.dll", ".\\toy_reentrant.dll", ".\\toy_entry_fault.dll"};
	const char* const reversed[] = {"toy_entry_fault.dll", "toy_reentrant.dll", "toy_basic.dll"};
	// Loaded and released once first, so the list below loads each plugin again; toy_entry_fault faults both times.
	StartWith(names);
	StartWithNone();
	FakeUnit unit;

	Check(CivHostSetPlugins(OutFiles(names)) == CIV_PLUGINS_CHANGED, "a new plugin list is loaded");
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED), "a plugin loads again after being unloaded");
	Check(unit.add(2, 3) == 105, "a reloaded plugin's hooks run again");
	unit.notify(5);
	Check(unit.m_notified == 10, "a reloaded plugin's replacement works again");
	const CivPluginReportRow basic = ReportRow("toy_basic.dll");
	Check(basic.status == "Loaded" && basic.problems.empty(), "a reloaded plugin does not clash with the replacement it had before");
	Check(HasStatus("toy_entry_fault.dll", CIV_PLUGIN_FAULTED_AT_LOAD), "a plugin that faulted and was released is loaded again, not refused");
	ClearLog();
	Check(CivHostSetPlugins(OutFiles(respelled)) == CIV_PLUGINS_UNCHANGED, "the same list, spelled differently, changes nothing");
	Check(!LogHas("shutting down"), "the same list spelled differently shuts no plugin down");
	Check(CivHostSetPlugins(OutFiles(reversed)) == CIV_PLUGINS_CHANGED, "the same plugins in another order count as a change");
}

void TestListWhileRunning()
{
	const char* const names[] = {"toy_basic.dll", "toy_reentrant.dll"};
	StartWith(names);
	ToySetHostCallFn* setHostCall = TOY_FUNCTION("toy_reentrant.dll", ToySetHostCall);
	ToyBreakOnNextCallFn* breakOnNextCall = TOY_FUNCTION("toy_reentrant.dll", ToyBreakOnNextCall);
	Check(setHostCall && breakOnNextCall, "the re-entry test plugin can be given a host call and told to break");
	if (!setHostCall || !breakOnNextCall)
		return;
	setHostCall(&ChangePluginsNow);
	ClearLog();
	FakeUnit::Twice(2);
	setHostCall(0);
	Check(Call(TOY_FUNCTION("toy_reentrant.dll", ToyHostCallResult), -1) == 0, "the list cannot change while a plugin is running");
	Check(CivHostPlugins().size() == 2, "a refused change while a plugin runs leaves every plugin listed");
	Check(!LogHas("shutting down"), "a refused change while a plugin runs shuts no plugin down");

	breakOnNextCall();
	Check(BreaksOut(&CallTwice), "an exception the host does not handle passes through to the caller");
	Check(CivHostSetPlugins(std::vector<std::string>()) == CIV_PLUGINS_CHANGED, "the list can still change after that exception");
}

void TestReplaceSwap()
{
	const char* const basicFirst[] = {"toy_basic.dll", "toy_conflict.dll"};
	const char* const conflictFirst[] = {"toy_conflict.dll", "toy_basic.dll"};
	StartWith(basicFirst);
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED), "of two plugins replacing one function, the higher one loads");
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_REPLACE_CONFLICT), "of two plugins replacing one function, the lower one is turned off");
	Check(CivHostSetPlugins(OutFiles(conflictFirst)) == CIV_PLUGINS_CHANGED, "swapping the two counts as a change");
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_LOADED), "moving the turned-off plugin above the other loads it");
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_REPLACE_CONFLICT), "moving it up turns the other plugin off");
	FakeUnit unit;
	unit.notify(5);
	Check(unit.m_notified == -5, "the plugin moved up has its replacement run");
}

void TestKeptInMemory()
{
	const char* const names[] = {"toy_kept.dll", "toy_reentrant.dll"};
	const char* const withoutKept[] = {"toy_reentrant.dll"};
	const char* const withKept[] = {"toy_kept.dll", "toy_conflict.dll", "toy_reentrant.dll"};
	StartWith(names);
	ToyFaultOnShutdownFn* faultOnShutdown = TOY_FUNCTION("toy_kept.dll", ToyFaultOnShutdown);
	Check(faultOnShutdown != 0, "the kept test plugin can be told to fault while shutting down");
	if (!faultOnShutdown)
		return;
	faultOnShutdown();
	const int faults = FaultCount();

	Check(CivHostSetPlugins(OutFiles(withoutKept)) == CIV_PLUGINS_CHANGED, "the list changes even when a plugin cannot be unloaded");
	Check(FaultCount() == faults + 1 && LastFaultWhileShuttingDown(), "a plugin whose shutdown faults is reported as such");
	Check(IsInMemory("toy_kept.dll"), "a plugin whose shutdown faults stays in memory");
	Check(CivHostSetPlugins(OutFiles(withKept)) == CIV_PLUGINS_CHANGED, "a plugin left in memory can be listed again");
	Check(HasStatus("toy_kept.dll", CIV_PLUGIN_STILL_IN_MEMORY), "a plugin left in memory is refused when listed again");
	Check(ReportRow("toy_kept.dll").name == "Toy Kept", "a plugin left in memory is refused by its own name");
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_LOADED), "a plugin listed below one left in memory can replace the function it had replaced");
	FakeUnit unit;
	unit.notify(5);
	Check(unit.m_notified == -5, "that replacement runs, not the one left in memory");
	Check(Call(TOY_FUNCTION("toy_kept.dll", ToyRegisterLate), -1) == CIV_HOOK_NOT_ALLOWED,
		"a plugin left in memory cannot register hooks, even while another plugin replaces the same function");
}

void TestEntryBreak()
{
	StartWithNone();
	Check(BreaksOut(&LoadEntryBreak), "an exception the host does not handle passes out of a plugin's entry point");
	Check(Call(TOY_FUNCTION("toy_entry_break.dll", ToyRegisterLate), -1) == CIV_HOOK_NOT_ALLOWED, "after that, the plugin no longer counts as loading");
	Check(CivHostSetPlugins(std::vector<std::string>()) == CIV_PLUGINS_CHANGED, "the list still changes after that exception");
	Check(!IsInMemory("toy_entry_break.dll"), "the half-loaded plugin is unloaded at the next list change");
}

void TestThreads()
{
	const char* const threads[] = {"toy_threads.dll"};
	const std::vector<std::string> none;
	StartWith(threads);
	ToyStartThreadFn* start = TOY_FUNCTION("toy_threads.dll", ToyStartThread);
	Check(start != 0, "the thread test plugin can start a thread");
	if (!start)
		return;
	start(0);
	Check(CivHostSetPlugins(none) == CIV_PLUGINS_CHANGED, "the list changes while the plugin's thread runs");
	Check(!IsInMemory("toy_threads.dll"), "a plugin whose shutdown stops its thread is unloaded");

	Check(CivHostSetPlugins(OutFiles(threads)) == CIV_PLUGINS_CHANGED, "the thread test plugin loads again");
	start = TOY_FUNCTION("toy_threads.dll", ToyStartThread);
	ToyLeaveThreadRunningFn* leaveRunning = TOY_FUNCTION("toy_threads.dll", ToyLeaveThreadRunning);
	Check(start && leaveRunning, "the thread test plugin can be told to leave its thread running");
	if (!start || !leaveRunning)
		return;
	start(1);
	leaveRunning();
	ClearLog();
	CivHostSetPlugins(none);
	Check(IsInMemory("toy_threads.dll"), "a plugin that leaves a thread running, even one started through the C runtime, stays in memory");
	Check(LogHas("one of its threads is still running"), "the log says a thread is still running");
	CivHostSetPlugins(OutFiles(threads));
	Check(HasStatus("toy_threads.dll", CIV_PLUGIN_STILL_IN_MEMORY), "a plugin left in memory by its thread is refused when listed again");
}

void TestNoShutdown()
{
	const char* const names[] = {"toy_no_shutdown.dll"};
	StartWith(names);
	Check(HasStatus("toy_no_shutdown.dll", CIV_PLUGIN_LOADED), "a plugin without a shutdown function loads");
	const int faults = FaultCount();
	Check(CivHostSetPlugins(std::vector<std::string>()) == CIV_PLUGINS_CHANGED, "dropping a plugin that has no shutdown function from the list is accepted");
	Check(!IsInMemory("toy_no_shutdown.dll"), "a plugin without a shutdown function is unloaded and released");
	Check(FaultCount() == faults, "unloading a plugin without a shutdown function reports no fault");
}
