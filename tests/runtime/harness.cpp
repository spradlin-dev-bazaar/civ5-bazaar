// Runs the host runtime outside the game, against the fixture hooked by the real generator.
// harness.exe <toy folder> [reverse | list | section names, each at most once]
#include "harness.h"
#include "CivHostPath.h"
#include "fake_engine.h"

#include <stdio.h>
#include <string.h>

void TestLoading();
void TestHooks();
void TestShapes();
void TestQuarantine();
void TestStrings();
void TestRegistration();
void TestTurnedAwayAfterRegistering();
void TestVetoAndReplace();
void TestExceptions();
void TestUnloading();
void TestNoShutdown();
void TestReload();
void TestListWhileRunning();
void TestReplaceSwap();
void TestKeptInMemory();
void TestEntryBreak();
void TestThreads();
void TestOrder();
void TestReplacedSetup();
void TestHandHooks();
void TestHandHookFaults();
void TestPossibleConflicts();
void TestSkippedOriginal();
void TestPaths();
void TestActiveMods();
void TestLuaFunctions();

namespace
{
	int s_failures = 0;
	std::vector<std::string> s_log;
	int s_faults = 0;
	bool s_lastFaultShuttingDown = false;
	std::string s_dir;

	void LogSink(const char* line)
	{
		s_log.push_back(line);
		printf("      log: %s\n", line);
	}

	void FaultSink(int, const char* name, bool shuttingDown, unsigned int code)
	{
		++s_faults;
		s_lastFaultShuttingDown = shuttingDown;
		printf("      fault sink: %s%s, code 0x%08X\n", name, shuttingDown ? ", shutting down" : "", code);
	}

	struct Section
	{
		const char* name;
		void (*run)();
	};

	const Section kSections[] = {
		{"loading", &TestLoading},
		{"hooks", &TestHooks},
		{"shapes", &TestShapes},
		{"quarantine", &TestQuarantine},
		{"strings", &TestStrings},
		{"registration", &TestRegistration},
		{"declined or refused after registering", &TestTurnedAwayAfterRegistering},
		{"veto and replace", &TestVetoAndReplace},
		{"exceptions", &TestExceptions},
		{"unloading", &TestUnloading},
		{"no shutdown", &TestNoShutdown},
		{"reload", &TestReload},
		{"list while running", &TestListWhileRunning},
		{"replace swap", &TestReplaceSwap},
		{"kept in memory", &TestKeptInMemory},
		{"entry break", &TestEntryBreak},
		{"threads", &TestThreads},
		{"order", &TestOrder},
		{"replaced setup", &TestReplacedSetup},
		{"hand-placed hooks", &TestHandHooks},
		{"hand-placed hook faults", &TestHandHookFaults},
		{"possible conflicts", &TestPossibleConflicts},
		{"skipped original", &TestSkippedOriginal},
		{"paths", &TestPaths},
		{"active mods", &TestActiveMods},
		{"lua functions", &TestLuaFunctions},
	};
	const int kSectionCount = sizeof(kSections) / sizeof(kSections[0]);

	void Run(const Section& section)
	{
		printf("\n-- %s\n", section.name);
		section.run();
	}

	__declspec(noinline) int PlainSquare(int x)
	{
		return x * x;
	}

	double TimeCalls(int (*fn)(int), int n)
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

	void ReportCallCost()
	{
		StartWithNone();
		const int calls = 50000000;
		const double nsPlain = TimeCalls(&PlainSquare, calls);
		const double nsWrapped = TimeCalls(&Square, calls);
		const char* const bench[] = {"toy_bench.dll"};
		StartWith(bench);
		const double nsHooked = TimeCalls(&Square, calls / 10);
		printf("\n-- cost per call (Square, %d calls each)\n", calls);
		printf("      plain function:        %.2f ns\n", nsPlain);
		printf("      wrapped, no hooks:     %.2f ns (+%.2f)\n", nsWrapped, nsWrapped - nsPlain);
		printf("      wrapped, one after:    %.2f ns (+%.2f)\n", nsHooked, nsHooked - nsPlain);
	}
}

void Check(bool ok, const char* what)
{
	printf("%s  %s\n", ok ? "PASS" : "FAIL", what);
	if (!ok)
		++s_failures;
}

std::string OutFile(const char* name)
{
	return s_dir + name;
}

std::vector<std::string> OutFiles(const char* const* names, size_t count)
{
	std::vector<std::string> paths;
	for (size_t i = 0; i < count; ++i)
		paths.push_back(OutFile(names[i]));
	return paths;
}

void StartWith(const char* const* names, size_t count)
{
	StartWithNone();
	CivHostLoadPlugins(OutFiles(names, count));
}

void StartWithNone()
{
	CivHostUnloadPlugins();
	ClearLog();
}

void Load(const char* name)
{
	CivHostLoadPlugins(std::vector<std::string>(1, OutFile(name)));
}

// Records are looked up afresh each time: loading more plugins can move them. A file listed twice finds the later record.
const CivPluginRecord* Find(const char* fileName)
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

CivPluginReportRow ReportRow(const char* fileName)
{
	const std::vector<CivPluginReportRow> rows = CivHostReportRows();
	for (size_t i = 0; i < rows.size(); ++i)
		if (_stricmp(rows[i].file.c_str(), fileName) == 0)
			return rows[i];
	return CivPluginReportRow();
}

bool HasStatus(const char* fileName, CivPluginStatus status)
{
	const CivPluginRecord* rec = Find(fileName);
	return rec && rec->status == status;
}

bool IsQuarantined(const char* fileName)
{
	const CivPluginRecord* rec = Find(fileName);
	return rec && rec->quarantined;
}

bool IsInMemory(const char* fileName)
{
	return GetModuleHandleW(CivWide(OutFile(fileName)).c_str()) != 0;
}

void ClearLog()
{
	s_log.clear();
}

int LogIndex(const char* text, int from)
{
	for (size_t i = from > 0 ? (size_t)from : 0; i < s_log.size(); ++i)
		if (s_log[i].find(text) != std::string::npos)
			return (int)i;
	return -1;
}

std::string LogLine(int index)
{
	return index >= 0 && index < (int)s_log.size() ? s_log[index] : std::string();
}

bool LogHas(const char* text)
{
	return LogIndex(text) >= 0;
}

int FaultCount()
{
	return s_faults;
}

bool LastFaultWhileShuttingDown()
{
	return s_lastFaultShuttingDown;
}

FARPROC ToyExport(const char* fileName, const char* function)
{
	HMODULE module = GetModuleHandleW(CivWide(OutFile(fileName)).c_str());
	return module ? GetProcAddress(module, function) : 0;
}

int Call(int (*fn)(), int fallback)
{
	return fn ? fn() : fallback;
}

// Wide arguments, because the out folder's path joins the UTF-8 paths Bazaar works with.
int wmain(int argc, wchar_t** wideArgs)
{
	std::vector<std::string> argv;
	for (int a = 0; a < argc; ++a)
		argv.push_back(CivUtf8(wideArgs[a]));
	s_dir = argc > 1 ? argv[1] + "\\" : std::string();
	CivHostSetLogSink(&LogSink);
	CivHostSetFaultSink(&FaultSink);

	if (argc == 3 && argv[2] == "list")
	{
		for (int i = 0; i < kSectionCount; ++i)
			printf("%s\n", kSections[i].name);
		return 0;
	}
	const bool reverse = argc == 3 && argv[2] == "reverse";
	if (argc > 2 && !reverse)
	{
		for (int a = 2; a < argc; ++a)
		{
			bool found = false;
			for (int i = 0; i < kSectionCount; ++i)
				if (argv[a] == kSections[i].name)
				{
					Run(kSections[i]);
					found = true;
				}
			Check(found, ("a section is called " + argv[a]).c_str());
		}
	}
	else
	{
		for (int i = 0; i < kSectionCount; ++i)
			Run(kSections[reverse ? kSectionCount - 1 - i : i]);
		if (!reverse)
			ReportCallCost();
	}

	printf("\n%d failure(s)\n", s_failures);
	return s_failures;
}
