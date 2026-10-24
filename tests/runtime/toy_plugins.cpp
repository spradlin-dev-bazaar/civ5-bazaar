// One source, built once per toy plugin with a TOY_* define.
#include "CivHooks.h"
#include "CivPluginApi.h"
#include "fake_engine.h"
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
	return s_host->RegisterHook(s_host->pluginIndex, CivHooks::FakeUnit_notify::ID, CIV_HOOK_REPLACE, (void*)&ReplaceNothing);
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
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_BEFORE, (void*)&BeforeAdd);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	Register(CivHooks::FakeUnit_notify::ID, CIV_HOOK_REPLACE, (void*)&ReplaceNotify);
	Register(CivHooks::FakeUnit_name::ID, CIV_HOOK_AFTER, (void*)&AfterName);
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
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_BEFORE, (void*)&BeforeAdd);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	Register(CivHooks::FakeUnit_Subtract::ID, CIV_HOOK_REPLACE, (void*)&ReplaceSubtract);
	Register(CivHooks::FakeUnit_Grow::ID, CIV_HOOK_REPLACE, (void*)&ReplaceGrow);
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
	Register(CivHooks::FakeUnit_Twice::ID, CIV_HOOK_AFTER, (void*)&AfterTwice);
	Register(CivHooks::FakeUnit_Scale::ID, CIV_HOOK_AFTER, (void*)&AfterScale);
	Register(CivHooks::FakeUnit_Level::ID, CIV_HOOK_AFTER, (void*)&AfterLevel);
	Register(CivHooks::FakeUnit_Greet::ID, CIV_HOOK_AFTER, (void*)&AfterGreet);
	Register(CivHooks::FakeUnit_op_eq::ID, CIV_HOOK_AFTER, (void*)&AfterEquals);
	Register(CivHooks::FakeUnit_Ignore::ID, CIV_HOOK_BEFORE, (void*)&BeforeIgnore);
	Register(CivHooks::FakeUnit_Heal::ID, CIV_HOOK_AFTER, (void*)&AfterHeal);
	Register(CivHooks::FakeUnit_Range::ID, CIV_HOOK_AFTER, (void*)&AfterRange);
	Register(CivHooks::FakeRules_Bonus::ID, CIV_HOOK_AFTER, (void*)&AfterPlusThousand);
	Register(CivHooks::FakeRules_Penalty::ID, CIV_HOOK_AFTER, (void*)&AfterPlusThousand);
	Register(CivHooks::fake_engine_cpp_Helper::ID, CIV_HOOK_AFTER, (void*)&AfterPlusThousand);
	Register(CivHooks::Unannounced::ID, CIV_HOOK_AFTER, (void*)&AfterUnannounced);
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
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	Register(CivHooks::FakeUnit_Grow::ID, CIV_HOOK_REPLACE, (void*)&ReplaceGrow);
	LogResult("replace result", Register(CivHooks::FakeUnit_notify::ID, CIV_HOOK_REPLACE, (void*)&ReplaceNotify));
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
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes);
	return true;
}

#elif defined(TOY_FAULT)

static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	int* volatile nowhere = 0;
	result += *nowhere;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Fault");
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	return true;
}

#elif defined(TOY_FAULT_REPLACE)

static int ReplaceLevel(int (*)(const FakeUnit*), const FakeUnit*)
{
	int* volatile nowhere = 0;
	return *nowhere;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Fault Replace");
	Register(CivHooks::FakeUnit_Level::ID, CIV_HOOK_REPLACE, (void*)&ReplaceLevel);
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
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_BEFORE, (void*)&BeforeAdd);
	return true;
}

#elif defined(TOY_KEPT)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Kept");
	Register(CivHooks::FakeUnit_notify::ID, CIV_HOOK_REPLACE, (void*)&ReplaceNothing);
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
	Register(CivHooks::Square::ID, CIV_HOOK_AFTER, (void*)&AfterSquare);
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
	Register(CivHooks::FakeUnit_Twice::ID, CIV_HOOK_AFTER, (void*)&AfterTwice);
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
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes);
	return false;
#else
	Describe(info, "Toy Late Fault");
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, (void*)&SayYes);
	volatile int zero = 0;
	return 10 / zero == 1;
#endif
}

#elif defined(TOY_BAD_HOOKS)

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
	Register(CivHooks::FakeUnit_Range::ID, CIV_HOOK_REPLACE, (void*)&ReplaceRangeFirst);
	LogResult("second replace", Register(CivHooks::FakeUnit_Range::ID, CIV_HOOK_REPLACE, (void*)&ReplaceRangeSecond));
	LogResult("hand-placed hook past the last", RegisterHand(CIV_HAND_HOOK_COUNT, (void*)&SayYes));
	LogResult("negative hand-placed hook", RegisterHand(-1, (void*)&SayYes));
	LogResult("hand-placed hook with no function", RegisterHand(CIV_HAND_KEEP_DEAD_SLOT_OPEN, 0));
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
	Register(CivHooks::FakeUnit_Range::ID, CIV_HOOK_AFTER, (void*)&AfterRange);
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

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Veto");
	Register(CivHooks::FakeUnit_Subtract::ID, CIV_HOOK_BEFORE, (void*)&BeforeSubtract);
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

static void HeardNotification(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2)
{
	char line[256];
	_snprintf_s(line, sizeof(line), _TRUNCATE, "notification %d %d [%s] [%s] %d %d %d %d", player, notificationType, message, summary, x, y, data1, data2);
	s_host->Log(s_host->pluginIndex, line);
}

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

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Hand Replace");
	Register(CivHooks::FakeUnit_CancelOrders::ID, CIV_HOOK_REPLACE, (void*)&ReplaceCancelOrders);
	Register(CivHooks::FakeUnit_Range::ID, CIV_HOOK_REPLACE, (void*)&ReplaceRange);
	Register(CivHooks::FakeUnit_Reach::ID, CIV_HOOK_REPLACE, (void*)&ReplaceReach);
	RegisterHand(CIV_HAND_UNIT_ORDERS_CANCELLED, (void*)&HeardOrdersCancelled);
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

#elif defined(TOY_NEWER_IMPORTS)

// Provided by no DLL, as a function an older Bazaar lacks would be: Windows cannot load this toy at all.
extern "C" __declspec(dllimport) int ToyAbsentFunction();

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Newer Imports");
	return ToyAbsentFunction() == 0;
}

#elif defined(TOY_NO_ENTRY)

TOY_EXPORT int NotAPlugin()
{
	return 0;
}

#else
#error Define one TOY_* variant.
#endif
