// Runs the host runtime outside the game: loading, refusals, hook order, quarantine, and cost.
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

static const CivPluginRecord* Find(const char* name)
{
	const std::vector<CivPluginRecord>& all = CivHostPlugins();
	for (size_t i = 0; i < all.size(); ++i)
		if (all[i].name == name)
			return &all[i];
	return 0;
}

static bool LogHas(const char* text)
{
	for (size_t i = 0; i < s_log.size(); ++i)
		if (s_log[i].find(text) != std::string::npos)
			return true;
	return false;
}

template <class F> static F Export(const std::string& dll, const char* name)
{
	return (F)GetProcAddress(GetModuleHandleA(dll.c_str()), name);
}

static double Seconds(LARGE_INTEGER a, LARGE_INTEGER b)
{
	LARGE_INTEGER f;
	QueryPerformanceFrequency(&f);
	return double(b.QuadPart - a.QuadPart) / double(f.QuadPart);
}

static double TimeCalls(int (*fn)(int), int n)
{
	LARGE_INTEGER a, b;
	volatile int sink = 0;
	QueryPerformanceCounter(&a);
	for (int i = 0; i < n; ++i)
		sink += fn(i);
	QueryPerformanceCounter(&b);
	return Seconds(a, b) * 1e9 / n;
}

int main(int argc, char** argv)
{
	const std::string dir = argc > 1 ? std::string(argv[1]) + "\\" : std::string();
	CivHostSetLogSink(&LogSink);
	CivHostSetFaultSink(&FaultSink);

	const int calls = 50000000;
	const double nsPlain = TimeCalls(&CivOrig_Square, calls);
	const double nsWrapped = TimeCalls(&Square, calls);

	std::vector<std::string> first;
	first.push_back(dir + "toy_basic.dll");
	first.push_back(dir + "toy_second.dll");
	first.push_back(dir + "toy_conflict.dll");
	first.push_back(dir + "toy_newer.dll");
	first.push_back(dir + "toy_major.dll");
	first.push_back(dir + "toy_no_entry.dll");
	first.push_back(dir + "toy_missing.dll");
	first.push_back(dir + "toy_entry_fault.dll");
	CivHostLoadPlugins(first);

	printf("\n-- loading\n");
	const CivPluginRecord* basic = Find("Toy Basic");
	const CivPluginRecord* second = Find("Toy Second");
	const CivPluginRecord* conflict = Find("Toy Conflict");
	const CivPluginRecord* newer = Find("Toy Newer");
	const CivPluginRecord* major = Find("Toy Major");
	const CivPluginRecord* entryFault = Find("Toy Entry Fault");
	Check(basic && basic->status == CIV_PLUGIN_LOADED, "a current plugin loads");
	Check(second && second->status == CIV_PLUGIN_LOADED, "a second plugin loads beside it");
	Check(newer && newer->status == CIV_PLUGIN_NEWER_API && !newer->problems.empty(), "a plugin built for a newer host is refused, with a reason");
	Check(major && major->status == CIV_PLUGIN_OTHER_MAJOR, "a plugin built for another major version is refused");
	Check(CivHostPlugins()[5].status == CIV_PLUGIN_NO_ENTRY, "a DLL without the entry point is refused");
	Check(CivHostPlugins()[6].status == CIV_PLUGIN_FILE_NOT_LOADED, "a missing file is reported, not ignored");
	Check(entryFault && entryFault->status == CIV_PLUGIN_FAULTED_AT_LOAD && entryFault->quarantined, "a plugin that faults while loading is quarantined");
	Check(conflict && conflict->status == CIV_PLUGIN_LOADED && !conflict->problems.empty(), "a second replace of the same function is refused and recorded");
	Check(Export<int (*)()>(dir + "toy_conflict.dll", "ToyLastRegisterResult")() == CIV_HOOK_REPLACE_TAKEN, "the refused plugin is told why");
	Check(LogHas("Toy Basic already replaces"), "the refusal names the plugin that holds the replacement");

	printf("\n-- hooks\n");
	FakeUnit unit;
	s_log.clear();
	Check(unit.add(2, 3) == 110, "after-hooks run in reverse load order (5 * 2 + 100 = 110)");
	Check(s_log.size() >= 2 && s_log[0].find("Toy Basic") != std::string::npos && s_log[1].find("Toy Second") != std::string::npos, "before-hooks run in load order");
	const int secondBefore = Export<int (*)()>(dir + "toy_second.dll", "ToyBeforeCalls")();
	Check(unit.add(13, 1) == 98, "a veto skips the function; its result still passes through the after-hooks");
	Check(Export<int (*)()>(dir + "toy_second.dll", "ToyBeforeCalls")() == secondBefore, "a veto skips the remaining before-hooks");
	unit.notify(5);
	Check(unit.m_notified == 10, "a replacement runs instead of the original");
	Check(unit.name() == "Hooked Warrior", "an after-hook can change a function's returned reference");
	Check(newer->status != CIV_PLUGIN_LOADED && unit.add(1, 1) != 999999, "hooks from refused plugins never run");

	printf("\n-- quarantine\n");
	std::vector<std::string> later;
	later.push_back(dir + "toy_fault.dll");
	CivHostLoadPlugins(later);
	const int before = s_faults;
	const int r1 = unit.add(2, 3);
	Check(s_faults == before + 1, "a faulting after-hook is caught and reported");
	Check(r1 == 110, "the other plugins' hooks still run on the same call");
	const CivPluginRecord* fault = Find("Toy Fault");
	Check(fault && fault->quarantined && !fault->problems.empty(), "the faulting plugin is quarantined with a reason");
	Check(unit.add(2, 3) == 110 && s_faults == before + 1, "a quarantined plugin's hooks never run again");

	printf("\n-- strings and vectors across the boundary\n");
	{
		typedef void (*FillFn)(std::string&, std::vector<std::string>&);
		FillFn fill = Export<FillFn>(dir + "toy_basic.dll", "ToyFillStrings");
		FillFn release = Export<FillFn>(dir + "toy_basic.dll", "ToyReleaseStrings");
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
	}
	Check(_heapchk() == _HEAPOK, "the shared heap is intact afterwards");

	printf("\n-- cost per call (Square, %d calls each)\n", calls);
	std::vector<std::string> bench;
	bench.push_back(dir + "toy_bench.dll");
	CivHostLoadPlugins(bench);
	const double nsHooked = TimeCalls(&Square, calls / 10);
	printf("      plain function:        %.2f ns\n", nsPlain);
	printf("      wrapped, no hooks:     %.2f ns (+%.2f)\n", nsWrapped, nsWrapped - nsPlain);
	printf("      wrapped, one after:    %.2f ns (+%.2f)\n", nsHooked, nsHooked - nsPlain);

	printf("\n%d failure(s)\n", s_failures);
	return s_failures;
}
