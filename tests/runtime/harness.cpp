// Runs the host runtime outside the game, against the fixture hooked by the real generator.
#include "CivHostRuntime.h"
#include "fake_engine.h"

#include <windows.h>
#include <malloc.h>
#include <stdio.h>

#include <string>
#include <vector>

static int s_failures = 0;
static std::vector<std::string> s_log;
static int s_faults = 0;
static std::string s_dir;

static void Check(bool ok, const char* what)
{
	printf("%s  %s\n", ok ? "PASS" : "FAIL", what);
	if (!ok)
		++s_failures;
}

static void LogSink(const char* line)
{
	s_log.push_back(line);
	printf("      log: %s\n", line);
}

static void FaultSink(int, const char* name, int hookId, unsigned int code)
{
	++s_faults;
	printf("      fault sink: %s, hook %d, code 0x%08X\n", name, hookId, code);
}

static std::string Dll(const char* name)
{
	return s_dir + name;
}

static void Load(const char* name)
{
	std::vector<std::string> one(1, Dll(name));
	CivHostLoadPlugins(one);
}

// Records are looked up afresh each time: loading more plugins can move them.
static const CivPluginRecord* Find(const char* fileName)
{
	const std::vector<CivPluginRecord>& all = CivHostPlugins();
	const CivPluginRecord* found = 0;
	for (size_t i = 0; i < all.size(); ++i)
	{
		const std::string& path = all[i].path;
		const size_t n = strlen(fileName);
		if (path.size() >= n && _stricmp(path.c_str() + path.size() - n, fileName) == 0)
			found = &all[i];
	}
	return found;
}

static bool HasStatus(const char* fileName, CivPluginStatus status)
{
	const CivPluginRecord* rec = Find(fileName);
	return rec && rec->status == status;
}

static int LogIndex(const char* text)
{
	for (size_t i = 0; i < s_log.size(); ++i)
		if (s_log[i].find(text) != std::string::npos)
			return (int)i;
	return -1;
}

static bool LogHas(const char* text)
{
	return LogIndex(text) >= 0;
}

static FARPROC ToyExport(const char* dll, const char* function)
{
	return GetProcAddress(GetModuleHandleA(Dll(dll).c_str()), function);
}

static int CallInt(const char* dll, const char* function, int fallback)
{
	typedef int (*Fn)();
	Fn fn = (Fn)ToyExport(dll, function);
	return fn ? fn() : fallback;
}

__declspec(noinline) static int PlainSquare(int x)
{
	return x * x;
}

static double TimeCalls(int (*fn)(int), int n)
{
	LARGE_INTEGER a, b, f;
	volatile int sink = 0;
	QueryPerformanceCounter(&a);
	for (int i = 0; i < n; ++i)
		sink += fn(i);
	QueryPerformanceCounter(&b);
	QueryPerformanceFrequency(&f);
	return double(b.QuadPart - a.QuadPart) / double(f.QuadPart) * 1e9 / n;
}

static void TestLoading()
{
	printf("\n-- loading\n");
	const char* first[] = {"toy_basic.dll", "toy_second.dll", "toy_shapes.dll", "toy_conflict.dll", "toy_newer.dll",
		"toy_major.dll", "toy_no_entry.dll", "toy_missing.dll", "toy_entry_fault.dll"};
	std::vector<std::string> paths;
	for (size_t i = 0; i < sizeof(first) / sizeof(first[0]); ++i)
		paths.push_back(Dll(first[i]));
	CivHostLoadPlugins(paths);

	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED), "a current plugin loads");
	Check(HasStatus("toy_second.dll", CIV_PLUGIN_LOADED), "a second plugin loads beside it");
	Check(HasStatus("toy_newer.dll", CIV_PLUGIN_NEWER_API) && !Find("toy_newer.dll")->problems.empty(), "a plugin built for a newer host is refused, with a reason");
	Check(LogHas("[Toy Newer] shutting down"), "a refused plugin is shut down before it is unloaded");
	Check(HasStatus("toy_major.dll", CIV_PLUGIN_OTHER_MAJOR), "a plugin built for another major version is refused");
	Check(HasStatus("toy_no_entry.dll", CIV_PLUGIN_NO_ENTRY), "a DLL without the entry point is refused");
	Check(HasStatus("toy_missing.dll", CIV_PLUGIN_FILE_NOT_LOADED), "a missing file is reported, not ignored");
	Check(HasStatus("toy_entry_fault.dll", CIV_PLUGIN_FAULTED_AT_LOAD) && Find("toy_entry_fault.dll")->quarantined, "a plugin that faults while loading is quarantined");
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_LOADED) && !Find("toy_conflict.dll")->problems.empty(), "a second replace of the same function is refused and recorded");
	Check(CallInt("toy_conflict.dll", "ToyLastRegisterResult", -1) == CIV_HOOK_REPLACE_TAKEN, "the refused plugin is told why");
	Check(LogHas("Toy Basic already replaces"), "the refusal names the plugin that holds the replacement");
	Check(LogHas("Plugin Toy Conflict: Its replacement"), "the refusal names the refused plugin, though it is still loading");
	Check(LogHas("[Toy Basic] starting"), "a plugin logging from its entry point is named in the log");
	Check(CallInt("toy_basic.dll", "ToyRegisterLate", -1) == CIV_HOOK_NOT_ALLOWED, "registering after loading is refused");
}

static void TestHooks()
{
	printf("\n-- hooks\n");
	FakeUnit unit;
	s_log.clear();
	Check(unit.add(2, 3) == 110, "after-hooks run in reverse load order (5 * 2 + 100 = 110)");
	Check(s_log.size() >= 2 && s_log[0].find("Toy Basic") != std::string::npos && s_log[1].find("Toy Second") != std::string::npos, "before-hooks run in load order");
	const int secondBefore = CallInt("toy_second.dll", "ToyBeforeCalls", -1);
	Check(unit.add(13, 1) == 98, "a veto skips the function; its result still passes through the after-hooks");
	Check(CallInt("toy_second.dll", "ToyBeforeCalls", -2) == secondBefore, "a veto skips the remaining before-hooks");
	unit.notify(5);
	Check(unit.m_notified == 10, "a replacement runs instead of the original, and can call the original itself");
	Check(unit.Subtract(7, 2) == 50, "the original gets the replacement's arguments in order and returns its result");
	Check(unit.name() == "Hooked Warrior", "an after-hook can change a function's returned reference");
	Check(unit.add(1, 1) == 104, "hooks from refused plugins never run");

	Load("toy_basic.dll");
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_DUPLICATE), "a plugin listed twice is loaded once");
	Check(unit.add(2, 3) == 110, "its hooks still run once per call");
}

static void TestShapes()
{
	printf("\n-- generated wrappers for each function shape\n");
	FakeUnit unit;
	Check(FakeUnit::Twice(2) == 1004, "a static member function");
	Check(unit.Scale(5) == 1010, "a declared default argument still applies");
	Check(unit.Level() == 1007, "a const return value");
	Check(unit.Greet("Bob") == "Hello Bob!", "a class passed and returned by value");
	Check(!(unit == unit), "an operator");
	unit.Ignore(1);
	Check(CallInt("toy_shapes.dll", "ToyBeforeCalls", 0) == 1, "an unnamed parameter");
	Check(unit.Heal(5) == 1005, "a signature written in two versions, the first one active");
	Check(unit.Range() == 1004, "a signature whose #if closes after another function's signature");
	Check(FakeRules::Bonus(1) == 1002, "a namespace function defined with a qualified name");
	Check(FakeRules::Penalty(1) == 1000, "a qualified signature written in two versions, the second one active");
	Check(UsesHelper(1) == 1011, "a file-local static function");
	Check(CallsUnannounced(1) == 1004, "a function with no earlier declaration and a default argument");
}

static void TestQuarantine()
{
	printf("\n-- quarantine\n");
	FakeUnit unit;
	Load("toy_fault.dll");
	Load("toy_fault_before.dll");
	const int before = s_faults;
	const int r1 = unit.add(2, 3);
	Check(s_faults == before + 2, "faulting before- and after-hooks are both caught and reported");
	Check(r1 == 110, "the other plugins' hooks still run on the same call");
	Check(Find("toy_fault.dll") && Find("toy_fault.dll")->quarantined && !Find("toy_fault.dll")->problems.empty(), "a faulting plugin is quarantined with a reason");
	Check(unit.add(2, 3) == 110 && s_faults == before + 2, "a quarantined plugin's hooks never run again");

	Load("toy_fault_replace.dll");
	const int calls = g_levelCalls;
	Check(unit.Level() == 1007 && s_faults == before + 3 && g_levelCalls == calls + 1, "when a replacement faults, the original runs instead, once");
	Check(unit.Level() == 1007 && s_faults == before + 3 && g_levelCalls == calls + 2, "and keeps running once the replacement is quarantined");
}

static void TestStrings()
{
	printf("\n-- strings and vectors across the boundary\n");
	typedef void (*FillFn)(std::string&, std::vector<std::string>&);
	FillFn fill = (FillFn)ToyExport("toy_basic.dll", "ToyFillStrings");
	FillFn release = (FillFn)ToyExport("toy_basic.dll", "ToyReleaseStrings");
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

static int s_addDuringShutdown = -1;

static void AddDuringShutdown()
{
	FakeUnit unit;
	s_addDuringShutdown = unit.add(2, 3);
}

static bool ChangePluginsNow()
{
	return CivHostSetPlugins(std::vector<std::string>()) != CIV_PLUGINS_BUSY;
}

typedef void (*VoidFn)();

static void CallTwice()
{
	FakeUnit::Twice(2);
}

static void LoadEntryBreak()
{
	Load("toy_entry_break.dll");
}

// No C++ objects may live in this frame, or __try is not allowed.
static bool BreaksOut(VoidFn fn)
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

static void TestUnload()
{
	printf("\n-- unloading\n");
	FakeUnit unit;
	typedef void (*SetProbeFn)(VoidFn);
	SetProbeFn setProbe = (SetProbeFn)ToyExport("toy_basic.dll", "ToySetShutdownProbe");
	if (setProbe)
		setProbe(&AddDuringShutdown);
	VoidFn faultAgain = (VoidFn)ToyExport("toy_fault_before.dll", "ToyFaultOnShutdown");
	if (faultAgain)
		faultAgain();
	const int faults = s_faults;
	s_log.clear();
	Check(CivHostUnloadPlugins() && CivHostPlugins().empty(), "plugins unload when none is running");
	Check(s_addDuringShutdown == 5, "hooks are already removed while plugins shut down");
	const int second = LogIndex("[Toy Second] shutting down");
	Check(second >= 0 && second < LogIndex("[Toy Basic] shutting down"), "plugins shut down in reverse load order");
	Check(unit.add(2, 3) == 5 && FakeUnit::Twice(2) == 4, "no hooks remain after unloading");
	Check(!GetModuleHandleA(Dll("toy_basic.dll").c_str()), "an unloaded plugin's DLL is released");
	Check(LogHas("[Toy Fault] shutting down") && !GetModuleHandleA(Dll("toy_fault.dll").c_str()),
		"a plugin that faulted in a hook is still shut down, then released");
	Check(LogHas("[Toy Entry Fault] shutting down") && !GetModuleHandleA(Dll("toy_entry_fault.dll").c_str()),
		"so is a plugin that faulted while loading");
	Check(s_faults == faults && GetModuleHandleA(Dll("toy_fault_before.dll").c_str()) != 0,
		"a faulted plugin that faults again while shutting down stays in memory, without a second report");
}

static void TestPluginList()
{
	printf("\n-- changing the plugin list\n");
	FakeUnit unit;
	const char* names[] = {"toy_basic.dll", "toy_reentrant.dll", "toy_entry_fault.dll"};
	std::vector<std::string> list, respelled, reversed;
	for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i)
	{
		list.push_back(Dll(names[i]));
		respelled.push_back(s_dir + ".\\" + names[i]);
		reversed.insert(reversed.begin(), Dll(names[i]));
	}

	Check(CivHostSetPlugins(list) == CIV_PLUGINS_CHANGED, "a new plugin list is loaded");
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED) && unit.add(2, 3) == 105, "a plugin loads again after being unloaded");
	unit.notify(5);
	Check(unit.m_notified == 10 && Find("toy_basic.dll")->problems.empty(), "its replacement works again after the reload");
	Check(HasStatus("toy_entry_fault.dll", CIV_PLUGIN_FAULTED_AT_LOAD), "a plugin that faulted and was released is loaded again, not refused");
	s_log.clear();
	Check(CivHostSetPlugins(respelled) == CIV_PLUGINS_UNCHANGED && !LogHas("shutting down"), "the same list, spelled differently, changes nothing");

	typedef void (*SetHostCallFn)(bool (*)());
	SetHostCallFn setHostCall = (SetHostCallFn)ToyExport("toy_reentrant.dll", "ToySetHostCall");
	Check(setHostCall != 0, "the re-entry test plugin can be given a host call");
	if (setHostCall)
		setHostCall(&ChangePluginsNow);
	FakeUnit::Twice(2);
	Check(CallInt("toy_reentrant.dll", "ToyHostCallResult", -1) == 0 && CivHostPlugins().size() == 3 && !LogHas("shutting down"),
		"the list cannot change while a plugin is running");

	VoidFn breakOnNextCall = (VoidFn)ToyExport("toy_reentrant.dll", "ToyBreakOnNextCall");
	if (breakOnNextCall)
		breakOnNextCall();
	Check(BreaksOut(&CallTwice), "an exception the host does not handle passes through to the caller");
	const CivPluginListResult afterBreak = CivHostSetPlugins(reversed);
	Check(afterBreak != CIV_PLUGINS_BUSY, "the list can still change after that exception");
	Check(afterBreak == CIV_PLUGINS_CHANGED, "the same plugins in another order count as a change");

	VoidFn faultOnShutdown = (VoidFn)ToyExport("toy_basic.dll", "ToyFaultOnShutdown");
	if (faultOnShutdown)
		faultOnShutdown();
	const int faults = s_faults;
	const std::vector<std::string> withoutBasic(1, Dll("toy_reentrant.dll"));
	Check(CivHostSetPlugins(withoutBasic) == CIV_PLUGINS_CHANGED && s_faults == faults + 1 && GetModuleHandleA(Dll("toy_basic.dll").c_str()) != 0,
		"a plugin whose shutdown faults is reported and stays in memory");
	std::vector<std::string> withBasic;
	withBasic.push_back(Dll("toy_conflict.dll"));
	withBasic.push_back(Dll("toy_basic.dll"));
	withBasic.push_back(Dll("toy_reentrant.dll"));
	Check(CivHostSetPlugins(withBasic) == CIV_PLUGINS_CHANGED && HasStatus("toy_basic.dll", CIV_PLUGIN_STILL_IN_MEMORY)
			&& Find("toy_basic.dll")->name == "Toy Basic" && HasStatus("toy_conflict.dll", CIV_PLUGIN_LOADED),
		"it is refused by name when listed again, and the others load");
	Check(CallInt("toy_basic.dll", "ToyRegisterLate", -1) == CIV_HOOK_NOT_ALLOWED,
		"a plugin left in memory cannot register hooks, even while another plugin replaces the same function");

	Check(BreaksOut(&LoadEntryBreak), "an exception the host does not handle passes out of a plugin's entry point");
	Check(CallInt("toy_entry_break.dll", "ToyRegisterLate", -1) == CIV_HOOK_NOT_ALLOWED, "after that, the plugin no longer counts as loading");
	Check(CivHostSetPlugins(withBasic) == CIV_PLUGINS_CHANGED && !GetModuleHandleA(Dll("toy_entry_break.dll").c_str()),
		"the half-loaded plugin is unloaded at the next list change");
}

static void TestThreads()
{
	printf("\n-- plugins with threads of their own\n");
	const std::vector<std::string> threads(1, Dll("toy_threads.dll"));
	const std::vector<std::string> none;
	typedef void (*StartFn)(int);

	CivHostSetPlugins(threads);
	StartFn start = (StartFn)ToyExport("toy_threads.dll", "ToyStartThread");
	Check(start != 0, "the thread test plugin can start a thread");
	if (start)
		start(0);
	Check(CivHostSetPlugins(none) == CIV_PLUGINS_CHANGED && !GetModuleHandleA(Dll("toy_threads.dll").c_str()),
		"a plugin whose shutdown stops its thread is unloaded");

	CivHostSetPlugins(threads);
	start = (StartFn)ToyExport("toy_threads.dll", "ToyStartThread");
	VoidFn leaveRunning = (VoidFn)ToyExport("toy_threads.dll", "ToyLeaveThreadRunning");
	if (start && leaveRunning)
	{
		start(1);
		leaveRunning();
	}
	s_log.clear();
	CivHostSetPlugins(none);
	Check(GetModuleHandleA(Dll("toy_threads.dll").c_str()) != 0 && LogHas("one of its threads is still running"),
		"a plugin that leaves a thread running, even one started through the C runtime, stays in memory");
	CivHostSetPlugins(threads);
	Check(HasStatus("toy_threads.dll", CIV_PLUGIN_STILL_IN_MEMORY), "it is refused when listed again");
}

int main(int argc, char** argv)
{
	s_dir = argc > 1 ? std::string(argv[1]) + "\\" : std::string();
	CivHostSetLogSink(&LogSink);
	CivHostSetFaultSink(&FaultSink);

	const int calls = 50000000;
	const double nsPlain = TimeCalls(&PlainSquare, calls);
	const double nsWrapped = TimeCalls(&Square, calls);

	TestLoading();
	TestHooks();
	TestShapes();
	TestQuarantine();
	TestStrings();
	TestUnload();
	TestPluginList();
	TestThreads();

	printf("\n-- cost per call (Square, %d calls each)\n", calls);
	Load("toy_bench.dll");
	const double nsHooked = TimeCalls(&Square, calls / 10);
	printf("      plain function:        %.2f ns\n", nsPlain);
	printf("      wrapped, no hooks:     %.2f ns (+%.2f)\n", nsWrapped, nsWrapped - nsPlain);
	printf("      wrapped, one after:    %.2f ns (+%.2f)\n", nsHooked, nsHooked - nsPlain);

	printf("\n%d failure(s)\n", s_failures);
	return s_failures;
}
