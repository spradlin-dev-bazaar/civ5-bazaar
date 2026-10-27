// One source, built once per toy plugin with a TOY_* define.
#include "fake_engine.h"
#include "CivHooks.h"
#include "toy_api.h"

#include <stdio.h>

#include <stdexcept>

// toy_ordinals exports only what its .def file lists, with ordinals out of name order.
#if defined(TOY_ORDINALS)
#define TOY_EXPORT extern "C"
#else
#define TOY_EXPORT extern "C" __declspec(dllexport)
#endif

TOY_EXPORT ToyBeforeCallsFn ToyBeforeCalls;
TOY_EXPORT ToyRegisterLateFn ToyRegisterLate;
TOY_EXPORT ToyRegisterHandLateFn ToyRegisterHandLate;
TOY_EXPORT ToyFaultOnShutdownFn ToyFaultOnShutdown;
TOY_EXPORT ToySetShutdownProbeFn ToySetShutdownProbe;
TOY_EXPORT ToyFillStringsFn ToyFillStrings;
TOY_EXPORT ToyReleaseStringsFn ToyReleaseStrings;
TOY_EXPORT ToySetHostCallFn ToySetHostCall;
TOY_EXPORT ToyHostCallResultFn ToyHostCallResult;
TOY_EXPORT ToyBreakOnNextCallFn ToyBreakOnNextCall;
TOY_EXPORT ToyStartThreadFn ToyStartThread;
TOY_EXPORT ToyLeaveThreadRunningFn ToyLeaveThreadRunning;
TOY_EXPORT ToyExplodeLineFn ToyExplodeLine;
TOY_EXPORT ToySaveSetFn ToySaveSet;
TOY_EXPORT ToySaveValueFn ToySaveValue;
TOY_EXPORT ToySaveLoadsFn ToySaveLoads;
TOY_EXPORT ToySaveHadDataFn ToySaveHadData;
TOY_EXPORT ToySaveCrashNextFn ToySaveCrashNext;
TOY_EXPORT ToySaveRegisteredFn ToySaveRegistered;
TOY_EXPORT ToySaveWriteKeptFn ToySaveWriteKept;
TOY_EXPORT ToyValuesDeclaredFn ToyValuesDeclared;
TOY_EXPORT ToyValuesSetKillsFn ToyValuesSetKills;
TOY_EXPORT ToyValuesKillsFn ToyValuesKills;
TOY_EXPORT ToyValuesSetVeteranFn ToyValuesSetVeteran;
TOY_EXPORT ToyValuesVeteranFn ToyValuesVeteran;
TOY_EXPORT ToyValuesSetMoraleFn ToyValuesSetMorale;
TOY_EXPORT ToyValuesMoraleFn ToyValuesMorale;
TOY_EXPORT ToyValuesSetMottoFn ToyValuesSetMotto;
TOY_EXPORT ToyValuesMottoFn ToyValuesMotto;
TOY_EXPORT ToyValuesSetBigFn ToyValuesSetBig;
TOY_EXPORT ToyValuesBigFn ToyValuesBig;
TOY_EXPORT ToyValuesSetSpeedFn ToyValuesSetSpeed;
TOY_EXPORT ToyValuesSpeedFn ToyValuesSpeed;
TOY_EXPORT ToyValuesSetShortFn ToyValuesSetShort;
TOY_EXPORT ToyValuesShortFn ToyValuesShort;
TOY_EXPORT ToyValuesKillsWhenReplacedFn ToyValuesKillsWhenReplaced;
TOY_EXPORT ToyValuesSetWideFn ToyValuesSetWide;
TOY_EXPORT ToyValuesWideFn ToyValuesWide;
TOY_EXPORT ToyReaderFoundFn ToyReaderFound;
TOY_EXPORT ToyReaderKillsFn ToyReaderKills;
TOY_EXPORT ToyReaderSetKillsFn ToyReaderSetKills;
TOY_EXPORT ToyReaderMottoFn ToyReaderMotto;
TOY_EXPORT ToyReaderReadIntFn ToyReaderReadInt;

#if defined(TOY_NEWER) || defined(TOY_NEWER_IMPORTS)
TOY_EXPORT const CivApiVersion CivPluginApiVersion = {CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR + 1};
#elif defined(TOY_MAJOR)
TOY_EXPORT const CivApiVersion CivPluginApiVersion = {CIV_HOST_API_MAJOR + 1, 0};
#elif defined(TOY_OLDER)
TOY_EXPORT const CivApiVersion CivPluginApiVersion = {CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR - 1};
#elif defined(TOY_ORDINALS)
TOY_EXPORT const CivApiVersion CivPluginApiVersion = {CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR};
#elif !defined(TOY_NO_VERSION)
CIV_PLUGIN_EXPORT_API_VERSION;
#endif

static const CivHostInfo* s_host = 0;
static int s_beforeCalls = 0;

static void Describe(CivPluginInfo* info, const char* name)
{
	info->name = name;
	info->version = "1.0";
}

static int Register(int hookId, int kind, void* fn)
{
	return s_host->RegisterHook(s_host->pluginIndex, hookId, kind, fn);
}

static int RegisterHand(int handHook, void* fn)
{
	return s_host->RegisterHandHook(s_host->pluginIndex, handHook, fn);
}

static bool SayYes(int)
{
	return true;
}

TOY_EXPORT int ToyBeforeCalls()
{
	return s_beforeCalls;
}

typedef void (*NotifyFn)(FakeUnit*, int);

static void ReplaceNothing(NotifyFn, FakeUnit*, int)
{
}

TOY_EXPORT int ToyRegisterLate()
{
	return CivRegisterReplace<CivHooks::FakeUnit_notify>(s_host, &ReplaceNothing);
}

TOY_EXPORT int ToyRegisterHandLate()
{
	return RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes);
}

static ToyActionFn* s_ownShutdown = 0;
static ToyActionFn* s_shutdownProbe = 0;
static bool s_faultOnShutdown = false;

TOY_EXPORT void ToySetShutdownProbe(ToyActionFn* probe)
{
	s_shutdownProbe = probe;
}

TOY_EXPORT void ToyFaultOnShutdown()
{
	s_faultOnShutdown = true;
}

#if !defined(TOY_NO_SHUTDOWN)
TOY_EXPORT void CivPluginShutdown()
{
	s_host->Log(s_host->pluginIndex, "shutting down");
	if (s_ownShutdown)
		s_ownShutdown();
	if (s_shutdownProbe)
		s_shutdownProbe();
	if (s_faultOnShutdown)
	{
		int* volatile nowhere = 0;
		*nowhere = 1;
	}
}
#endif

static void LogResult(const char* what, int result)
{
	char line[128];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "%s %d", what, result);
	s_host->Log(s_host->pluginIndex, line);
}

#if defined(TOY_BASIC)

static bool BeforeAdd(const FakeUnit*, int a, int, int& result)
{
	++s_beforeCalls;
	s_host->Log(s_host->pluginIndex, "before add");
	if (a == 13)
	{
		result = -1;
		return true;
	}
	return false;
}

static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	result += 100;
}

static void ReplaceNotify(NotifyFn original, FakeUnit* self, int amount)
{
	original(self, amount);
	original(self, amount);
}

static void AfterName(const FakeUnit*, const std::string*& result)
{
	static const std::string hooked("Hooked Warrior");
	result = &hooked;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Basic");
	s_host->Log(s_host->pluginIndex, "starting");
	CivRegisterBefore<CivHooks::FakeUnit_add>(s_host, &BeforeAdd);
	CivRegisterAfter<CivHooks::FakeUnit_add>(s_host, &AfterAdd);
	CivRegisterReplace<CivHooks::FakeUnit_notify>(s_host, &ReplaceNotify);
	CivRegisterAfter<CivHooks::FakeUnit_name>(s_host, &AfterName);
	return true;
}

TOY_EXPORT void ToyFillStrings(std::string& s, std::vector<std::string>& v)
{
	s = "Allocated inside the plugin, and long enough that it cannot use the small-string buffer.";
	v.push_back("one");
	v.push_back(std::string(300, 'x'));
}

TOY_EXPORT void ToyReleaseStrings(std::string& s, std::vector<std::string>& v)
{
	std::string().swap(s);
	std::vector<std::string>().swap(v);
}

#elif defined(TOY_SECOND)

static bool BeforeAdd(const FakeUnit*, int, int, int&)
{
	++s_beforeCalls;
	s_host->Log(s_host->pluginIndex, "before add");
	return false;
}

static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	result *= 2;
}

static int ReplaceSubtract(int (*original)(const FakeUnit*, int, int), const FakeUnit* self, int a, int b)
{
	return original(self, a, b) * 10;
}

static int ReplaceGrow(int (*original)(const FakeUnit*, int), const FakeUnit* self, int x)
{
	return original(self, x) + 100;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Second");
	CivRegisterBefore<CivHooks::FakeUnit_add>(s_host, &BeforeAdd);
	CivRegisterAfter<CivHooks::FakeUnit_add>(s_host, &AfterAdd);
	CivRegisterReplace<CivHooks::FakeUnit_Subtract>(s_host, &ReplaceSubtract);
	CivRegisterReplace<CivHooks::FakeUnit_Grow>(s_host, &ReplaceGrow);
	return true;
}

#elif defined(TOY_SHAPES)

static void AfterTwice(int, int& result)
{
	result += 1000;
}

static void AfterScale(const FakeUnit*, int, int, int& result)
{
	result += 1000;
}

static void AfterLevel(const FakeUnit*, int& result)
{
	result += 1000;
}

static void AfterGreet(const FakeUnit*, std::string, std::string& result)
{
	result += "!";
}

static void AfterEquals(const FakeUnit*, const FakeUnit&, bool& result)
{
	result = !result;
}

static void AfterHeal(const FakeUnit*, int, int& result)
{
	result += 1000;
}

static void AfterRange(const FakeUnit*, int& result)
{
	result += 1000;
}

static bool BeforeIgnore(FakeUnit*, int)
{
	++s_beforeCalls;
	return false;
}

static void AfterPlusThousand(int, int& result)
{
	result += 1000;
}

static void AfterUnannounced(int, int, int& result)
{
	result += 1000;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Shapes");
	CivRegisterAfter<CivHooks::FakeUnit_Twice>(s_host, &AfterTwice);
	CivRegisterAfter<CivHooks::FakeUnit_Scale>(s_host, &AfterScale);
	CivRegisterAfter<CivHooks::FakeUnit_Level>(s_host, &AfterLevel);
	CivRegisterAfter<CivHooks::FakeUnit_Greet>(s_host, &AfterGreet);
	CivRegisterAfter<CivHooks::FakeUnit_op_eq>(s_host, &AfterEquals);
	CivRegisterBefore<CivHooks::FakeUnit_Ignore>(s_host, &BeforeIgnore);
	CivRegisterAfter<CivHooks::FakeUnit_Heal>(s_host, &AfterHeal);
	CivRegisterAfter<CivHooks::FakeUnit_Range>(s_host, &AfterRange);
	CivRegisterAfter<CivHooks::FakeRules_Bonus>(s_host, &AfterPlusThousand);
	CivRegisterAfter<CivHooks::FakeRules_Penalty>(s_host, &AfterPlusThousand);
	CivRegisterAfter<CivHooks::fake_engine_cpp_Helper>(s_host, &AfterPlusThousand);
	CivRegisterAfter<CivHooks::Unannounced>(s_host, &AfterUnannounced);
	return true;
}

#elif defined(TOY_CONFLICT)

static void ReplaceNotify(NotifyFn, FakeUnit* self, int amount)
{
	self->m_notified -= amount;
}

static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	result += 1000000;
}

static int ReplaceGrow(int (*)(const FakeUnit*, int), const FakeUnit*, int)
{
	return -1;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Conflict");
	CivRegisterAfter<CivHooks::FakeUnit_add>(s_host, &AfterAdd);
	CivRegisterReplace<CivHooks::FakeUnit_Grow>(s_host, &ReplaceGrow);
	LogResult("replace result", CivRegisterReplace<CivHooks::FakeUnit_notify>(s_host, &ReplaceNotify));
	return true;
}

#elif defined(TOY_NEWER) || defined(TOY_MAJOR) || defined(TOY_NO_VERSION)

// Bazaar must refuse these toys before running them; the log line and hooks show it if it does not.
static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	result = 999999;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_NEWER)
	Describe(info, "Toy Newer");
#elif defined(TOY_MAJOR)
	Describe(info, "Toy Major");
#else
	Describe(info, "Toy No Version");
#endif
	host->Log(host->pluginIndex, "starting");
	CivRegisterAfter<CivHooks::FakeUnit_add>(s_host, &AfterAdd);
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes);
	return true;
}

#elif defined(TOY_FAULT)

static int s_explodeLine = 0;

static __declspec(noinline) int Explode()
{
	int* volatile nowhere = 0;
	return *nowhere;
}

TOY_EXPORT int ToyExplodeLine()
{
	return s_explodeLine;
}

// The statement after the call starts a new line, so the return address names that line rather than the call's.
static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	s_explodeLine = __LINE__ + 1;
	Explode();
	result = 7;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Fault");
	CivRegisterAfter<CivHooks::FakeUnit_add>(s_host, &AfterAdd);
	return true;
}

#elif defined(TOY_FAULT_REPLACE)

static const int ReplaceLevel(const int (*)(const FakeUnit*), const FakeUnit*)
{
	int (*volatile nothing)() = 0;
	return nothing() + 1;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Fault Replace");
	CivRegisterReplace<CivHooks::FakeUnit_Level>(s_host, &ReplaceLevel);
	return true;
}

#elif defined(TOY_FAULT_BEFORE) || defined(TOY_FAULT_KEPT)

static bool BeforeAdd(const FakeUnit*, int, int, int&)
{
	int* volatile nowhere = 0;
	return *nowhere == 1;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_FAULT_BEFORE)
	Describe(info, "Toy Fault Before");
#else
	Describe(info, "Toy Fault Kept");
#endif
	CivRegisterBefore<CivHooks::FakeUnit_add>(s_host, &BeforeAdd);
	return true;
}

#elif defined(TOY_KEPT)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Kept");
	CivRegisterReplace<CivHooks::FakeUnit_notify>(s_host, &ReplaceNothing);
	return true;
}

#elif defined(TOY_ENTRY_FAULT)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Entry Fault");
	volatile int zero = 0;
	return 10 / zero == 1;
}

#elif defined(TOY_ENTRY_BREAK)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Entry Break");
	__debugbreak();
	return true;
}

#elif defined(TOY_BENCH)

static void AfterSquare(int, int&)
{
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Bench");
	CivRegisterAfter<CivHooks::Square>(s_host, &AfterSquare);
	return true;
}

#elif defined(TOY_REENTRANT)

static ToyHostCallFn* s_hostCall = 0;
static int s_hostCallResult = -1;
static bool s_breakNextCall = false;

static void AfterTwice(int, int&)
{
	if (s_breakNextCall)
	{
		s_breakNextCall = false;
		__debugbreak();
	}
	if (s_hostCall)
		s_hostCallResult = s_hostCall() ? 1 : 0;
}

TOY_EXPORT void ToySetHostCall(ToyHostCallFn* call)
{
	s_hostCall = call;
}

TOY_EXPORT int ToyHostCallResult()
{
	return s_hostCallResult;
}

TOY_EXPORT void ToyBreakOnNextCall()
{
	s_breakNextCall = true;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Reentrant");
	CivRegisterAfter<CivHooks::FakeUnit_Twice>(s_host, &AfterTwice);
	return true;
}

#elif defined(TOY_THREADS)

// Without this, windows.h brings in winsock.h, whose s_host macro would rename the toys' s_host.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <process.h>

static volatile LONG s_stop = 0;
static HANDLE s_thread = 0;
static bool s_leaveRunning = false;

static DWORD WINAPI WindowsLoop(void*)
{
	while (!s_stop)
		Sleep(5);
	return 0;
}

static unsigned __stdcall RuntimeLoop(void*)
{
	while (!s_stop)
		Sleep(5);
	return 0;
}

static void StopThread()
{
	if (!s_thread || s_leaveRunning)
		return;
	InterlockedExchange(&s_stop, 1);
	WaitForSingleObject(s_thread, INFINITE);
	CloseHandle(s_thread);
	s_thread = 0;
}

TOY_EXPORT void ToyStartThread(int throughRuntime)
{
	s_stop = 0;
	s_thread = throughRuntime ? (HANDLE)_beginthreadex(0, 0, &RuntimeLoop, 0, 0, 0) : CreateThread(0, 0, &WindowsLoop, 0, 0, 0);
}

TOY_EXPORT void ToyLeaveThreadRunning()
{
	s_leaveRunning = true;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Threads");
	s_ownShutdown = &StopThread;
	return true;
}

#elif defined(TOY_DECLINE) || defined(TOY_LATE_FAULT)

static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	result += 500000;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_DECLINE)
	Describe(info, "Toy Decline");
	CivRegisterAfter<CivHooks::FakeUnit_add>(s_host, &AfterAdd);
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes);
	host->DeclareValue(host->pluginIndex, CIV_ON_UNIT, CIV_VALUE_INT, "Kills", CIV_VALUE_PUBLISHED, 0);
	return false;
#else
	Describe(info, "Toy Late Fault");
	CivRegisterAfter<CivHooks::FakeUnit_add>(s_host, &AfterAdd);
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes);
	volatile int zero = 0;
	return 10 / zero == 1;
#endif
}

#elif defined(TOY_BAD_HOOKS)

#include "ToyGoneHook.h"

static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	result += 700000;
}

static int ReplaceRangeFirst(int (*)(const FakeUnit*), const FakeUnit*)
{
	return 500;
}

static int ReplaceRangeSecond(int (*)(const FakeUnit*), const FakeUnit*)
{
	return 600;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Bad Hooks");
	LogResult("unknown id", Register(1000000, CIV_HOOK_AFTER, (void*)&AfterAdd));
	LogResult("negative id", Register(-1, CIV_HOOK_AFTER, (void*)&AfterAdd));
	LogResult("kind past the last", Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_REPLACE + 1, (void*)&AfterAdd));
	LogResult("negative kind", Register(CivHooks::FakeUnit_add::ID, -1, (void*)&AfterAdd));
	LogResult("no function", Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, 0));
	LogResult("hook point that is gone", Register(TOY_GONE_HOOK_ID, CIV_HOOK_AFTER, (void*)&AfterAdd));
	LogResult("an index not its own",
		host->RegisterHook(host->pluginIndex + 1, CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd));
	LogResult("hand-placed hook for an index not its own",
		host->RegisterHandHook(host->pluginIndex + 1, CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes));
	CivRegisterReplace<CivHooks::FakeUnit_Range>(s_host, &ReplaceRangeFirst);
	LogResult("second replace", CivRegisterReplace<CivHooks::FakeUnit_Range>(s_host, &ReplaceRangeSecond));
	LogResult("hand-placed hook past the last", RegisterHand(CIV_HAND_HOOK_COUNT, (void*)&SayYes));
	LogResult("negative hand-placed hook", RegisterHand(-1, (void*)&SayYes));
	LogResult("hand-placed hook with no function", RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, 0));
	return true;
}

#elif defined(TOY_OVERFLOW)

static int Deeper(int depth)
{
	volatile char room[512];
	room[depth % 512] = 1;
	return depth < 0 ? 0 : Deeper(depth + 1) + room[0];
}

static void AfterRange(const FakeUnit*, int& result)
{
	result += Deeper(0);
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Overflow");
	CivRegisterAfter<CivHooks::FakeUnit_Range>(s_host, &AfterRange);
	return true;
}

#elif defined(TOY_THROW)

static void AfterRange(const FakeUnit*, int&)
{
	throw std::runtime_error("thrown from a plugin hook");
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Throw");
	CivRegisterAfter<CivHooks::FakeUnit_Range>(s_host, &AfterRange);
	return true;
}

#elif defined(TOY_VETO)

static bool BeforeSubtract(const FakeUnit*, int a, int, int& result)
{
	if (a != 99)
		return false;
	result = 77;
	return true;
}

static bool BeforeScale(const FakeUnit*, int v, int, int&)
{
	return v == 99;
}

static bool BeforeName(const FakeUnit*, const std::string*&)
{
	return true;
}

static bool BeforeGreet(const FakeUnit*, std::string who, std::string& result)
{
	if (who == "veto")
		result = "Vetoed";
	return who == "veto" || who == "quiet";
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Veto");
	CivRegisterBefore<CivHooks::FakeUnit_Subtract>(s_host, &BeforeSubtract);
	CivRegisterBefore<CivHooks::FakeUnit_Scale>(s_host, &BeforeScale);
	CivRegisterBefore<CivHooks::FakeUnit_name>(s_host, &BeforeName);
	CivRegisterBefore<CivHooks::FakeUnit_Greet>(s_host, &BeforeGreet);
	return true;
}

#elif defined(TOY_NO_SHUTDOWN)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy No Shutdown");
	return true;
}

#elif defined(TOY_HAND) || defined(TOY_HAND_SECOND)

#if defined(TOY_HAND)
static const int kPlayedPlayer = 3;
#else
static const int kPlayedPlayer = 5;
#endif

static bool PlaysPlayer(int player)
{
	LogResult("asked about player", player);
	return player == kPlayedPlayer;
}

#if defined(TOY_HAND)
static void HeardNotification(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2,
	int lookupIndex)
{
	char line[256];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "notification %d %d [%s] [%s] %d %d %d %d %d", player, notificationType, message, summary, x, y,
		data1, data2, lookupIndex);
	s_host->Log(s_host->pluginIndex, line);
}
#else
// Written as a plugin built before the lookup index was added.
static void HeardNotification(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2)
{
	char line[256];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "notification %d %d [%s] [%s] %d %d %d %d", player, notificationType, message, summary, x, y, data1, data2);
	s_host->Log(s_host->pluginIndex, line);
}
#endif

#if defined(TOY_HAND)
static bool KeepsSlot(int player)
{
	return player == 4;
}

static void HeardPopup(int player, int popupType, int data1, int data2, int data3, bool option1, bool option2, const char* text)
{
	char line[256];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "popup %d %d %d %d %d %d %d [%s]", player, popupType, data1, data2, data3, option1, option2, text);
	s_host->Log(s_host->pluginIndex, line);
}

static void HeardDeal(int fromPlayer, int toPlayer, int actingPlayer, bool accepted, bool finalized)
{
	char line[128];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "deal %d %d %d %d %d", fromPlayer, toPlayer, actingPlayer, accepted, finalized);
	s_host->Log(s_host->pluginIndex, line);
}

// The fake engine hands its own unit through the hook's CvUnit pointer.
static void HeardOrdersCancelled(CvUnit* unit, int reason)
{
	char line[128];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "orders cancelled %s %d", reinterpret_cast<FakeUnit*>(unit)->m_name.c_str(), reason);
	s_host->Log(s_host->pluginIndex, line);
}

static void HeardUnitReplaced(int oldOwner, int oldUnit, CvUnit* newUnit)
{
	char line[128];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "unit replaced %d %d %s", oldOwner, oldUnit, reinterpret_cast<FakeUnit*>(newUnit)->m_name.c_str());
	s_host->Log(s_host->pluginIndex, line);
}

static void HeardCityReplaced(int oldOwner, int oldCity, CvCity* newCity)
{
	char line[128];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "city replaced %d %d %s", oldOwner, oldCity, newCity ? "by a new city" : "by nothing");
	s_host->Log(s_host->pluginIndex, line);
}
#endif

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_HAND)
	Describe(info, "Toy Hand");
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&KeepsSlot);
	RegisterHand(CIV_HAND_POPUP_RAISED, (void*)&HeardPopup);
	RegisterHand(CIV_HAND_DEAL_RESOLVED, (void*)&HeardDeal);
	RegisterHand(CIV_HAND_UNIT_ORDERS_CANCELLED, (void*)&HeardOrdersCancelled);
	RegisterHand(CIV_HAND_UNIT_REPLACED, (void*)&HeardUnitReplaced);
	RegisterHand(CIV_HAND_CITY_REPLACED, (void*)&HeardCityReplaced);
#else
	Describe(info, "Toy Hand Second");
#endif
	RegisterHand(CIV_HAND_IS_PLUGIN_CONTROLLED_PLAYER, (void*)&PlaysPlayer);
	RegisterHand(CIV_HAND_NOTIFICATION_ADDED, (void*)&HeardNotification);
	return true;
}

#elif defined(TOY_HAND_FAULT)

static bool FaultWhenAsked(int)
{
	int* volatile nowhere = 0;
	*nowhere = 1;
	return true;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Hand Fault");
	RegisterHand(CIV_HAND_IS_PLUGIN_CONTROLLED_PLAYER, (void*)&FaultWhenAsked);
	return true;
}

#elif defined(TOY_HAND_REPLACE)

static void ReplaceCancelOrders(void (*)(FakeUnit*, int), FakeUnit* self, int)
{
	self->m_notified = -1;
}

static int ReplaceRange(int (*original)(const FakeUnit*), const FakeUnit* self)
{
	return original(self) + 100;
}

static int ReplaceReach(int (*)(const FakeUnit*), const FakeUnit*)
{
	return 30;
}

static void HeardOrdersCancelled(CvUnit*, int reason)
{
	LogResult("heard its own cancelled orders", reason);
}

// A second function running a hand-placed hook Toy Hand uses, so the two plugins conflict at two places.
static bool ReplacePlayedByPlugin(bool (*original)(const FakeUnit*, int), const FakeUnit* self, int player)
{
	return original(self, player);
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Hand Replace");
	CivRegisterReplace<CivHooks::FakeUnit_CancelOrders>(s_host, &ReplaceCancelOrders);
	CivRegisterReplace<CivHooks::FakeUnit_PlayedByPlugin>(s_host, &ReplacePlayedByPlugin);
	CivRegisterReplace<CivHooks::FakeUnit_Range>(s_host, &ReplaceRange);
	CivRegisterReplace<CivHooks::FakeUnit_Reach>(s_host, &ReplaceReach);
	RegisterHand(CIV_HAND_UNIT_ORDERS_CANCELLED, (void*)&HeardOrdersCancelled);
	return true;
}

#elif defined(TOY_TAKE_REPLACE)

static void ReplaceTake(void (*)(FakeUnit*, int, int), FakeUnit*, int, int)
{
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Take Replace");
	CivRegisterReplace<CivHooks::FakeUnit_TakeCity>(s_host, &ReplaceTake);
	CivRegisterReplace<CivHooks::FakeUnit_TakeUnit>(s_host, &ReplaceTake);
	return true;
}

#elif defined(TOY_OLDER) || defined(TOY_ORDINALS)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_OLDER)
	Describe(info, "Toy Older");
#else
	Describe(info, "Toy Ordinals");
#endif
	return true;
}

#elif defined(TOY_NEWER_IMPORTS) || defined(TOY_LOAD_FAILS)

// Provided by no DLL, as a function an older Bazaar lacks would be: Windows cannot load this toy at all.
extern "C" __declspec(dllimport) int ToyAbsentFunction();

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_NEWER_IMPORTS)
	Describe(info, "Toy Newer Imports");
#else
	Describe(info, "Toy Load Fails");
#endif
	return ToyAbsentFunction() == 0;
}

#elif defined(TOY_EMPTY_NAME)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	info->name = "";
	info->version = reinterpret_cast<const char*>(1);
	return true;
}

#elif defined(TOY_LUA)

#include <setjmp.h>

static int LuaTwo(lua_State*)
{
	return 2;
}

static int LuaMinusOne(lua_State*)
{
	return -1;
}

static int LuaCrash(lua_State*)
{
	int* volatile nowhere = 0;
	return *nowhere;
}

// The tests pass a jmp_buf as the lua_State, so this leaves as a Lua error does: by longjmp, past the crash guard.
static int LuaError(lua_State* L)
{
	longjmp(*reinterpret_cast<jmp_buf*>(L), 1);
	return 0;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Lua");
	// In the order test_lua.cpp names them.
	host->PushLuaFunction(host->pluginIndex, 0, &LuaTwo);
	host->PushLuaFunction(host->pluginIndex, 0, &LuaMinusOne);
	host->PushLuaFunction(host->pluginIndex, 0, &LuaCrash);
	host->PushLuaFunction(host->pluginIndex, 0, &LuaError);
	host->PushLuaFunction(host->pluginIndex + 100, 0, &LuaTwo);
	host->PushLuaFunction(-1, 0, &LuaTwo);
	host->PushLuaFunction(host->pluginIndex - 1, 0, &LuaTwo);
	return true;
}

#elif defined(TOY_SAVE) || defined(TOY_SAVE_SECOND) || defined(TOY_SAVE_TWIN)

static int s_saveValue = 0;
static int s_loads = 0;
static bool s_hadData = false;
static int s_crashNext = 0;
static int s_registered[4] = {-1, -1, -1, -1};
static void* s_keptSaving = 0;
static bool s_writeKept = false;

static void SaveData(void* saving)
{
	if (s_writeKept && s_keptSaving)
		s_host->WriteSaveData(s_keptSaving, "z", 1);
	s_writeKept = false;
	s_keptSaving = saving;
	CivSaveWriter out(s_host, saving);
	if (s_crashNext == 1)
	{
		s_crashNext = 0;
		out.WriteInt(12345);
		int* volatile nowhere = 0;
		*nowhere = 1;
	}
	out.WriteInt(s_saveValue);
	out.WriteText("toy");
}

static void LoadData(const void* data, int size)
{
	++s_loads;
	if (s_crashNext == 2)
	{
		s_crashNext = 0;
		int* volatile nowhere = 0;
		*nowhere = 1;
	}
	CivSaveReader in(data, size);
	s_hadData = data != 0;
	s_saveValue = in.ReadInt(0);
	if (data && (in.ReadText("") != "toy" || in.ReadInt(77) != 77))
		s_saveValue = -1;
}

TOY_EXPORT void ToySaveSet(int value)
{
	s_saveValue = value;
}

TOY_EXPORT int ToySaveValue()
{
	return s_saveValue;
}

TOY_EXPORT int ToySaveLoads()
{
	return s_loads;
}

TOY_EXPORT bool ToySaveHadData()
{
	return s_hadData;
}

TOY_EXPORT void ToySaveCrashNext(int where)
{
	s_crashNext = where;
}

TOY_EXPORT int ToySaveRegistered(int attempt)
{
	if (attempt < 4)
		return s_registered[attempt];
	return s_host->RegisterSaveData(s_host->pluginIndex, &SaveData, &LoadData);
}

TOY_EXPORT void ToySaveWriteKept()
{
	s_writeKept = true;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_SAVE)
	Describe(info, "Toy Save");
#elif defined(TOY_SAVE_SECOND)
	Describe(info, "Toy Save Second");
	info->id = "second";
#else
	Describe(info, "Toy Save Twin");
#endif
	s_registered[0] = host->RegisterSaveData(host->pluginIndex, 0, &LoadData);
	s_registered[1] = host->RegisterSaveData(host->pluginIndex, &SaveData, 0);
	s_registered[2] = host->RegisterSaveData(host->pluginIndex, &SaveData, &LoadData);
	s_registered[3] = host->RegisterSaveData(host->pluginIndex, &SaveData, &LoadData);
	return true;
}

#elif defined(TOY_VALUES)

static CivValue<CvUnit, int> s_kills;
static CivValue<CvUnit, bool> s_veteran;
static CivValue<CvCity, double> s_morale;
static CivValue<CvPlayer, std::string> s_motto;
static CivValue<CvPlot, __int64> s_big;
static CivValue<CvUnit, float> s_speed;
static CivValue<CvUnit, unsigned short> s_short;
static CivValue<CvUnit, unsigned int> s_wide;
static int s_declared[5] = {-2, -2, -2, -2, -2};
static int s_killsWhenReplaced = -1;

TOY_EXPORT int ToyValuesDeclared(int attempt)
{
	if (attempt < 5)
		return s_declared[attempt];
	CivValue<CvUnit, int> late;
	return late.Declare(s_host, "Late", 0) ? 1 : 0;
}

TOY_EXPORT bool ToyValuesSetKills(const void* unit, int kills)
{
	return s_kills.Set(static_cast<const CvUnit*>(unit), kills);
}

TOY_EXPORT int ToyValuesKillsWhenReplaced()
{
	return s_killsWhenReplaced;
}

TOY_EXPORT void ToyValuesSetWide(const void* unit, unsigned int n)
{
	s_wide.Set(static_cast<const CvUnit*>(unit), n);
}

TOY_EXPORT unsigned int ToyValuesWide(const void* unit)
{
	return s_wide.Get(static_cast<const CvUnit*>(unit));
}

static void HeardUnitReplaced(int, int, CvUnit* newUnit)
{
	s_killsWhenReplaced = s_kills.Get(newUnit);
}

TOY_EXPORT int ToyValuesKills(const void* unit)
{
	return s_kills.Get(static_cast<const CvUnit*>(unit));
}

TOY_EXPORT void ToyValuesSetVeteran(const void* unit, bool veteran)
{
	s_veteran.Set(static_cast<const CvUnit*>(unit), veteran);
}

TOY_EXPORT bool ToyValuesVeteran(const void* unit)
{
	return s_veteran.Get(static_cast<const CvUnit*>(unit));
}

TOY_EXPORT void ToyValuesSetMorale(const void* city, double morale)
{
	s_morale.Set(static_cast<const CvCity*>(city), morale);
}

TOY_EXPORT double ToyValuesMorale(const void* city)
{
	return s_morale.Get(static_cast<const CvCity*>(city));
}

TOY_EXPORT void ToyValuesSetMotto(const void* player, const char* motto)
{
	s_motto.Set(static_cast<const CvPlayer*>(player), motto);
}

TOY_EXPORT std::string ToyValuesMotto(const void* player)
{
	return s_motto.Get(static_cast<const CvPlayer*>(player));
}

TOY_EXPORT void ToyValuesSetBig(const void* plot, __int64 big)
{
	s_big.Set(static_cast<const CvPlot*>(plot), big);
}

TOY_EXPORT __int64 ToyValuesBig(const void* plot)
{
	return s_big.Get(static_cast<const CvPlot*>(plot));
}

TOY_EXPORT void ToyValuesSetSpeed(const void* unit, float speed)
{
	s_speed.Set(static_cast<const CvUnit*>(unit), speed);
}

TOY_EXPORT float ToyValuesSpeed(const void* unit)
{
	return s_speed.Get(static_cast<const CvUnit*>(unit));
}

TOY_EXPORT void ToyValuesSetShort(const void* unit, unsigned short n)
{
	s_short.Set(static_cast<const CvUnit*>(unit), n);
}

TOY_EXPORT unsigned short ToyValuesShort(const void* unit)
{
	return s_short.Get(static_cast<const CvUnit*>(unit));
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Values");
	s_kills.Declare(host, "Kills", 0, CIV_VALUE_PUBLISHED | CIV_VALUE_CARRIES_OVER);
	s_veteran.Declare(host, "Veteran", false);
	s_morale.Declare(host, "Morale", 100.0, CIV_VALUE_CARRIES_OVER);
	s_motto.Declare(host, "Motto", "none yet", CIV_VALUE_PUBLISHED);
	s_big.Declare(host, "Big", 5000000000LL);
	s_speed.Declare(host, "Speed", 1.5f);
	s_short.Declare(host, "Short", 7);
	s_wide.Declare(host, "Wide", 0);
	CivValue<CvUnit, int> again;
	s_declared[0] = again.Declare(host, "Kills", 0) ? 1 : 0;
	s_declared[1] = again.Declare(host, "", 0) ? 1 : 0;
	s_declared[2] = host->DeclareValue(host->pluginIndex, 9, CIV_VALUE_INT, "Odd kind", 0, 0);
	s_declared[3] = host->DeclareValue(host->pluginIndex, CIV_ON_UNIT, 9, "Odd type", 0, 0);
	s_declared[4] = host->DeclareValue(host->pluginIndex, CIV_ON_UNIT, CIV_VALUE_INT, "Odd flags", 64, 0);
	RegisterHand(CIV_HAND_UNIT_REPLACED, (void*)&HeardUnitReplaced);
	return true;
}

#elif defined(TOY_VALUES_READER)

// Toy Values comes from this mod, with no plugin ID, in the tests.
static const char* const kValuesMod = "{VALUES}";
static CivValue<CvUnit, int> s_kills;
static CivValue<CvPlayer, std::string> s_motto;
static int s_found[8] = {-2, -2, -2, -2, -2, -2, -2, -2};

TOY_EXPORT int ToyReaderFound(int attempt)
{
	return attempt < 8 ? s_found[attempt] : -2;
}

TOY_EXPORT int ToyReaderKills(const void* unit)
{
	return s_kills.Get(static_cast<const CvUnit*>(unit));
}

TOY_EXPORT bool ToyReaderSetKills(const void* unit, int kills)
{
	return s_kills.Set(static_cast<const CvUnit*>(unit), kills);
}

TOY_EXPORT std::string ToyReaderMotto(const void* player)
{
	return s_motto.Get(static_cast<const CvPlayer*>(player));
}

TOY_EXPORT int ToyReaderReadInt(int value, const void* unit)
{
	return s_host->GetIntValue(s_host->pluginIndex, value, unit);
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Reader");
	s_found[0] = s_kills.Find(host, kValuesMod, "", "Kills") ? 1 : 0;
	s_found[1] = s_motto.Find(host, kValuesMod, "", "Motto") ? 1 : 0;
	CivValue<CvCity, double> morale;
	s_found[2] = morale.Find(host, kValuesMod, "", "Morale") ? 1 : 0;
	CivValue<CvUnit, double> wrongType;
	s_found[3] = wrongType.Find(host, kValuesMod, "", "Kills") ? 1 : 0;
	CivValue<CvCity, int> wrongKind;
	s_found[4] = wrongKind.Find(host, kValuesMod, "", "Kills") ? 1 : 0;
	CivValue<CvUnit, long> sameStorage;
	s_found[5] = sameStorage.Find(host, kValuesMod, "", "Kills") ? 1 : 0;
	CivValue<CvUnit, int> otherPlugin;
	s_found[6] = otherPlugin.Find(host, kValuesMod, "OTHER", "Kills") ? 1 : 0;
	s_found[7] = otherPlugin.Find(host, "{OTHER}", "", "Kills") ? 1 : 0;
	return true;
}

#elif defined(TOY_NO_ENTRY)

TOY_EXPORT int NotAPlugin()
{
	return 0;
}

#else
#error Define one TOY_* variant.
#endif
