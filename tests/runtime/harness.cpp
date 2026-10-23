// Runs the host runtime outside the game, against the fixture hooked by the real generator.
#include "CivHostOrder.h"
#include "CivHostRuntime.h"
#include "CivHostSetup.h"
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

static CivPluginReportRow ReportRow(const char* fileName)
{
	const std::vector<CivPluginReportRow> rows = CivHostReportRows();
	for (size_t i = 0; i < rows.size(); ++i)
		if (_stricmp(rows[i].file.c_str(), fileName) == 0)
			return rows[i];
	return CivPluginReportRow();
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
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_REPLACE_CONFLICT) && !GetModuleHandleA(Dll("toy_conflict.dll").c_str()),
		"a plugin replacing a function another plugin already replaces is turned off and unloaded");
	char toldWhy[64];
	_snprintf_s(toldWhy, sizeof(toldWhy), _TRUNCATE, "[Toy Conflict] replace result %d", CIV_HOOK_REPLACE_TAKEN);
	Check(LogHas(toldWhy), "the refused plugin is told why");
	Check(LogHas("Toy Basic, higher in the list, already replaces"), "the refusal names the plugin that holds the replacement");
	Check(LogHas("Plugin Toy Conflict: Toy Basic"), "the refusal names the refused plugin, though it is still loading");
	Check(LogHas("[Toy Basic] starting"), "a plugin logging from its entry point is named in the log");
	Check(CallInt("toy_basic.dll", "ToyRegisterLate", -1) == CIV_HOOK_NOT_ALLOWED, "registering after loading is refused");

	const CivPluginReportRow basic = ReportRow("toy_basic.dll");
	Check(!basic.failed && basic.status == "Loaded" && basic.name == "Toy Basic" && basic.problems.empty(), "the Plugins screen lists a loaded plugin by name as Loaded");
	const CivPluginReportRow newer = ReportRow("toy_newer.dll");
	Check(newer.failed && newer.status == "Not loaded" && newer.problems.find("newer Bazaar") != std::string::npos, "it lists a refused plugin as Not loaded, with the reason");
	const CivPluginReportRow conflict = ReportRow("toy_conflict.dll");
	Check(conflict.failed && conflict.status == "Not loaded" && conflict.problems.find("move it above Toy Basic") != std::string::npos,
		"it lists the turned-off plugin as Not loaded, saying how to use it instead");
	Check(conflict.problems.find("already replaces FakeUnit::notify(...),") != std::string::npos,
		"a function no other shares its name with is named without its parameters");
	Check(conflict.problems.find("already replaces FakeUnit::Grow(int) const,") != std::string::npos,
		"an overloaded function is named with its parameters, which tell it apart");
	const CivPluginReportRow entryFault = ReportRow("toy_entry_fault.dll");
	Check(entryFault.failed && entryFault.status == "Turned off after a crash", "it lists a plugin that crashed while loading as turned off");
	Check(ReportRow("toy_missing.dll").name == "toy_missing.dll", "it names a plugin by its file until the plugin gives its own name");
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
	Check(unit.add(1, 1) == 104, "hooks from refused plugins never run, including the other hooks of a turned-off plugin");
	Check(unit.Grow(1) == 102 && unit.Grow(1, 2) == 3, "each overload has its own hooks: replacing one leaves the other alone");

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
	const CivPluginReportRow faulted = ReportRow("toy_fault.dll");
	Check(faulted.failed && faulted.status == "Turned off after a crash", "the Plugins screen lists a quarantined plugin as turned off");

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

	std::vector<std::string> basicFirst, conflictFirst;
	basicFirst.push_back(Dll("toy_basic.dll"));
	basicFirst.push_back(Dll("toy_conflict.dll"));
	conflictFirst.push_back(Dll("toy_conflict.dll"));
	conflictFirst.push_back(Dll("toy_basic.dll"));
	CivHostSetPlugins(basicFirst);
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED) && HasStatus("toy_conflict.dll", CIV_PLUGIN_REPLACE_CONFLICT),
		"of two plugins replacing one function, the lower one is turned off");
	CivHostSetPlugins(conflictFirst);
	FakeUnit swapped;
	swapped.notify(5);
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_LOADED) && HasStatus("toy_basic.dll", CIV_PLUGIN_REPLACE_CONFLICT) && swapped.m_notified == -5,
		"moving it above the other turns the other one off, and its replacement runs");
	CivHostSetPlugins(reversed);

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

static CivOrderEntry Entry(const char* file, bool skip, const char* name)
{
	CivOrderEntry entry;
	entry.file = file;
	entry.skip = skip;
	entry.name = name;
	return entry;
}

static void TestOrder()
{
	printf("\n-- the player's plugin order\n");
	std::vector<std::string> listed;
	listed.push_back("A.dll");
	listed.push_back("b.dll");
	listed.push_back("c.dll");
	listed.push_back("A.dll");
	std::vector<CivOrderEntry> saved;
	saved.push_back(Entry("c.dll", true, "Toy C"));
	saved.push_back(Entry("gone.dll", false, ""));
	saved.push_back(Entry("a.DLL", false, ""));
	const std::vector<CivOrderEntry> order = CivApplyOrder(listed, saved);
	Check(order.size() == 4 && order[0].file == "c.dll" && order[1].file == "A.dll" && order[2].file == "b.dll",
		"saved plugins come first in the saved order, matched in any case, then the rest in listed order");
	Check(order.size() == 4 && order[0].skip && !order[1].skip && !order[2].skip, "a saved skip is kept, and a plugin new to the order is not skipped");
	Check(order.size() == 4 && order[3].file == "A.dll", "a plugin listed twice stays listed twice, so loading can refuse the second");

	std::vector<CivOrderEntry> named = order;
	named[1].name = "Toy\tA";
	named[1].version = "1.0";
	const std::vector<CivOrderEntry> parsed = CivParseOrder(CivFormatOrder(named));
	Check(parsed.size() == 4 && parsed[0].skip && parsed[0].name == "Toy C" && parsed[1].name == "Toy A" && parsed[1].version == "1.0"
			&& parsed[3].file == "A.dll",
		"a saved order reads back the same, with a tab in a name turned into a space");
	const std::vector<CivOrderEntry> messy = CivParseOrder("junk\nskip\tx.dll\nload\t\nload\ty.dll\r\n");
	Check(messy.size() == 2 && messy[0].skip && messy[0].file == "x.dll" && messy[1].file == "y.dll",
		"lines it does not recognise are ignored, and Windows line ends are read");
	const std::vector<CivOrderEntry> marked = CivParseOrder("\xEF\xBB\xBFskip\tx.dll\n");
	Check(marked.size() == 1 && marked[0].skip, "a byte-order mark an editor added does not hide the first line");

	std::vector<CivOrderEntry> applied;
	applied.push_back(Entry("a.dll", false, ""));
	applied.push_back(Entry("b.dll", false, ""));
	std::vector<CivOrderEntry> before;
	before.push_back(Entry("off.dll", true, "Toy Off"));
	before.push_back(Entry("A.DLL", true, ""));
	const std::vector<CivOrderEntry> kept = CivKeepUnlisted(applied, before);
	Check(kept.size() == 3 && kept[0].file == "a.dll" && !kept[0].skip && kept[2].file == "off.dll" && kept[2].skip,
		"saving keeps a plugin whose mod is off, with its skip, after the plugins listed now");

	std::vector<CivOrderEntry> entries;
	entries.push_back(Entry("first.dll", false, ""));
	entries.push_back(Entry("skipped.dll", true, "Toy Skipped"));
	entries.push_back(Entry("missing.dll", false, ""));
	entries.push_back(Entry("last.dll", false, ""));
	entries.push_back(Entry("ghost.dll", false, ""));
	const std::vector<std::string> missing(1, "MISSING.dll");
	std::vector<CivPluginReportRow> loaded(2);
	loaded[0].name = "Toy Last";
	loaded[0].file = "last.dll";
	loaded[1].name = "Toy First";
	loaded[1].file = "FIRST.DLL";
	const std::vector<CivPluginReportRow> rows = CivOrderReportRows(entries, missing, loaded);
	Check(rows.size() == 5 && rows[0].name == "Toy First" && rows[3].name == "Toy Last",
		"each loaded plugin's row is matched by its file name and keeps its place among skipped and missing ones");
	Check(rows.size() == 5 && rows[1].skipped && !rows[1].failed && rows[1].status == "Skipped" && rows[1].name == "Toy Skipped",
		"a skipped plugin is listed by its saved name as Skipped");
	Check(rows.size() == 5 && rows[2].failed && rows[2].status == "Not loaded" && rows[2].problems == CIV_REPORT_FILE_NOT_FOUND
			&& rows[2].name == "missing.dll",
		"a missing file is listed in its place as Not loaded");
	Check(rows.size() == 5 && rows[4].failed && rows[4].status == "Not loaded", "a plugin with no loaded row is listed as Not loaded, not as blank");
	Check(rows.size() == 5 && rows[0].file == "first.dll", "each row carries the file name as listed, which the screen sends back");
}

static void WriteText(const std::string& path, const std::string& text)
{
	for (size_t slash = path.find('\\', 3); slash != std::string::npos; slash = path.find('\\', slash + 1))
		CreateDirectoryA(path.substr(0, slash).c_str(), 0);
	SetFileAttributesA(path.c_str(), FILE_ATTRIBUTE_NORMAL);
	FILE* f = 0;
	if (fopen_s(&f, path.c_str(), "wb") == 0 && f)
	{
		fwrite(text.data(), 1, text.size(), f);
		fclose(f);
	}
}

static std::string ReadText(const std::string& path)
{
	std::string text;
	FILE* f = 0;
	if (fopen_s(&f, path.c_str(), "rb") == 0 && f)
	{
		char buffer[256];
		for (size_t n; (n = fread(buffer, 1, sizeof(buffer), f)) > 0;)
			text.append(buffer, n);
		fclose(f);
	}
	return text;
}

static std::string ModInfo(const char* id, int version, const char* files)
{
	char head[256];
	_snprintf_s(head, sizeof(head), _TRUNCATE, "\xEF\xBB\xBF<?xml version=\"1.0\"?>\r\n<Mod id=\"%s\" version=\"%d\">\r\n", id, version);
	return std::string(head) + "  <Dependencies>\r\n    <Mod id=\"dependency\" minversion=\"0\" maxversion=\"999\" title=\"Other\" />\r\n"
		"  </Dependencies>\r\n  <Files>\r\n" + files + "  </Files>\r\n</Mod>\r\n";
}

static CivActiveMod Active(const char* id, int version)
{
	CivActiveMod mod;
	mod.id = id;
	mod.version = version;
	return mod;
}

static void TestReplacedSetup()
{
	printf("\n-- the Advanced Setup screen the Plugins screen replaced\n");
	const std::string ras = ModInfo("ras-id", 15,
		"    <File md5=\"1\" import=\"0\">Unused/AdvancedSetup.xml</File>\r\n"
		"    <File md5=\"2\" import=\"1\">UI Overrides/AdvancedSetup.xml</File>\r\n"
		"    <File import=\"1\" md5=\"3\">UI Overrides/AdvancedSetup.lua</File>\r\n");
	std::string id;
	int version = 0;
	Check(CivModIdentity(ras, &id, &version) && id == "ras-id" && version == 15, "a mod description gives its ID and version, not a dependency's");
	Check(CivImportedFile(ras, "advancedsetup.XML") == "UI Overrides/AdvancedSetup.xml", "it finds a file the mod imports into the game, by name in any case");
	Check(CivImportedFile(ModInfo("x", 1, "    <File import=\"0\">AdvancedSetup.xml</File>\r\n"), "AdvancedSetup.xml").empty(),
		"a file the mod does not import is not counted");
	Check(CivImportedFile(ModInfo("x", 1, "    <File import=\"1\">Fish &amp; Chips/AdvancedSetup.lua</File>\r\n"), "AdvancedSetup.lua")
			== "Fish & Chips/AdvancedSetup.lua",
		"an escaped character in a path is read back");

	const std::string root = s_dir + "setup_test";
	const std::string mods = root + "\\MODS";
	const std::string own = mods + "\\Bazaar (v 1)";
	const std::string game = root + "\\Game";
	const std::string rasXml = mods + "\\RAS (v 15)\\UI Overrides\\AdvancedSetup.xml";
	WriteText(mods + "\\RAS (v 15)\\RAS (v 15).modinfo", ras);
	WriteText(rasXml, "ras xml");
	WriteText(mods + "\\RAS (v 15)\\UI Overrides\\AdvancedSetup.lua", "ras lua");
	WriteText(mods + "\\Other (v 1)\\Other (v 1).modinfo", ModInfo("other-id", 1, "    <File import=\"1\">Other.lua</File>\r\n"));
	WriteText(own + "\\Bazaar (v 1).modinfo", ModInfo("bazaar-id", 1, "    <File import=\"1\">frontend/AdvancedSetup.xml</File>\r\n"));
	WriteText(own + "\\frontend\\AdvancedSetup.xml", "bazaar xml");
	WriteText(game + "\\Assets\\UI\\FrontEnd\\GameSetup\\AdvancedSetup.xml", "game xml");
	WriteText(game + "\\Assets\\UI\\FrontEnd\\GameSetup\\AdvancedSetup.lua", "game lua");
	WriteText(game + "\\Assets\\DLC\\Expansion\\UI\\FrontEnd\\GameSetup\\AdvancedSetup.xml", "expansion xml");

	std::vector<CivActiveMod> withRas;
	withRas.push_back(Active("ras-id", 15));
	withRas.push_back(Active("other-id", 1));
	withRas.push_back(Active("bazaar-id", 1));
	const CivReplacedSetup first = CivCopyReplacedSetup(mods, game, own, withRas, true);
	const std::string copy = own + "\\BazaarNextSetup";
	Check(first.copy == copy && ReadText(copy + ".xml") == "ras xml" && ReadText(copy + ".lua") == "ras lua",
		"another active mod's screen is copied beside Bazaar under a name of its own, and Bazaar's own is passed over");
	Check(first.xmlSource == rasXml, "it says which file it copied");

	SetFileAttributesA(rasXml.c_str(), FILE_ATTRIBUTE_READONLY);
	CivCopyReplacedSetup(mods, game, own, withRas, true);
	Check(!CivCopyReplacedSetup(mods, game, own, withRas, true).copy.empty(), "a read-only source does not stop the next copy");
	SetFileAttributesA(rasXml.c_str(), FILE_ATTRIBUTE_NORMAL);

	std::vector<CivActiveMod> withoutRas(withRas.begin() + 1, withRas.end());
	CivCopyReplacedSetup(mods, game, own, withoutRas, true);
	Check(ReadText(copy + ".xml") == "expansion xml" && ReadText(copy + ".lua") == "game lua", "with no such mod active, the game's own screen is copied");
	CivCopyReplacedSetup(mods, game, own, withoutRas, false);
	Check(ReadText(copy + ".xml") == "game xml", "the game's base layout is used when Gods and Kings is off");
	withoutRas.push_back(Active("ras-id", 14));
	CivCopyReplacedSetup(mods, game, own, withoutRas, false);
	Check(ReadText(copy + ".xml") == "game xml", "an installed mod counts only in the version that is active");

	const CivReplacedSetup failed = CivCopyReplacedSetup(mods, root + "\\NoGame", own, withoutRas, false);
	Check(failed.copy.empty() && failed.problem.find("Could not copy") == 0, "a screen that cannot be copied gives a reason instead of a path");
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
	TestOrder();
	TestReplacedSetup();
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
