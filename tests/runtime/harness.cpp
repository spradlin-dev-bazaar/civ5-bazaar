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

static bool LogHas(const char* text)
{
	for (size_t i = 0; i < s_log.size(); ++i)
		if (s_log[i].find(text) != std::string::npos)
			return true;
	return false;
}

static int CallInt(const char* dll, const char* function, int fallback)
{
	typedef int (*Fn)();
	Fn fn = (Fn)GetProcAddress(GetModuleHandleA(Dll(dll).c_str()), function);
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
	Check(HasStatus("toy_major.dll", CIV_PLUGIN_OTHER_MAJOR), "a plugin built for another major version is refused");
	Check(HasStatus("toy_no_entry.dll", CIV_PLUGIN_NO_ENTRY), "a DLL without the entry point is refused");
	Check(HasStatus("toy_missing.dll", CIV_PLUGIN_FILE_NOT_LOADED), "a missing file is reported, not ignored");
	Check(HasStatus("toy_entry_fault.dll", CIV_PLUGIN_FAULTED_AT_LOAD) && Find("toy_entry_fault.dll")->quarantined, "a plugin that faults while loading is quarantined");
	Check(HasStatus("toy_conflict.dll", CIV_PLUGIN_LOADED) && !Find("toy_conflict.dll")->problems.empty(), "a second replace of the same function is refused and recorded");
	Check(CallInt("toy_conflict.dll", "ToyLastRegisterResult", -1) == CIV_HOOK_REPLACE_TAKEN, "the refused plugin is told why");
	Check(LogHas("Toy Basic already replaces"), "the refusal names the plugin that holds the replacement");
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
	Check(unit.m_notified == 10, "a replacement runs instead of the original");
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
	Check(FakeRules::Bonus(1) == 1002, "a namespace function defined with a qualified name");
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
}

static void TestStrings()
{
	printf("\n-- strings and vectors across the boundary\n");
	typedef void (*FillFn)(std::string&, std::vector<std::string>&);
	HMODULE basic = GetModuleHandleA(Dll("toy_basic.dll").c_str());
	FillFn fill = (FillFn)GetProcAddress(basic, "ToyFillStrings");
	FillFn release = (FillFn)GetProcAddress(basic, "ToyReleaseStrings");
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

	printf("\n-- cost per call (Square, %d calls each)\n", calls);
	Load("toy_bench.dll");
	const double nsHooked = TimeCalls(&Square, calls / 10);
	printf("      plain function:        %.2f ns\n", nsPlain);
	printf("      wrapped, no hooks:     %.2f ns (+%.2f)\n", nsWrapped, nsWrapped - nsPlain);
	printf("      wrapped, one after:    %.2f ns (+%.2f)\n", nsHooked, nsHooked - nsPlain);

	printf("\n%d failure(s)\n", s_failures);
	return s_failures;
}
