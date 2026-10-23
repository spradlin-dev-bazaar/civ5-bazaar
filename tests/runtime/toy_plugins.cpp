// One source, built once per toy plugin with a TOY_* define.
#include "CivHooks.h"
#include "CivPluginApi.h"
#include "fake_engine.h"

#include <string>
#include <vector>

#define TOY_EXPORT extern "C" __declspec(dllexport)

static const CivHostInfo* s_host = 0;
static int s_beforeCalls = 0;
static int s_lastRegisterResult = -1;

static void Describe(CivPluginInfo* info, const char* name, int major, int minor)
{
	info->name = name;
	info->version = "1.0";
	info->builtApiMajor = major;
	info->builtApiMinor = minor;
}

static int Register(int hookId, int kind, void* fn)
{
	s_lastRegisterResult = s_host->RegisterHook(s_host->pluginIndex, hookId, kind, fn);
	return s_lastRegisterResult;
}

TOY_EXPORT int ToyBeforeCalls()
{
	return s_beforeCalls;
}

TOY_EXPORT int ToyLastRegisterResult()
{
	return s_lastRegisterResult;
}

typedef void (*NotifyFn)(FakeUnit*, int);

static void ReplaceNothing(NotifyFn, FakeUnit*, int)
{
}

TOY_EXPORT int ToyRegisterLate()
{
	return s_host->RegisterHook(s_host->pluginIndex, CivHooks::FakeUnit_notify::ID, CIV_HOOK_REPLACE, (void*)&ReplaceNothing);
}

typedef void (*ActionFn)();
static ActionFn s_ownShutdown = 0;
static ActionFn s_shutdownProbe = 0;
static bool s_faultOnShutdown = false;

TOY_EXPORT void ToySetShutdownProbe(ActionFn probe)
{
	s_shutdownProbe = probe;
}

TOY_EXPORT void ToyFaultOnShutdown()
{
	s_faultOnShutdown = true;
}

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
	Describe(info, "Toy Basic", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
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

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Second", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_BEFORE, (void*)&BeforeAdd);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	Register(CivHooks::FakeUnit_Subtract::ID, CIV_HOOK_REPLACE, (void*)&ReplaceSubtract);
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
	Describe(info, "Toy Shapes", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
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

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Conflict", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::FakeUnit_notify::ID, CIV_HOOK_REPLACE, (void*)&ReplaceNotify);
	return true;
}

#elif defined(TOY_NEWER) || defined(TOY_MAJOR)

static void AfterAdd(const FakeUnit*, int, int, int& result)
{
	result = 999999;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
#if defined(TOY_NEWER)
	Describe(info, "Toy Newer", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR + 1);
#else
	Describe(info, "Toy Major", CIV_HOST_API_MAJOR + 1, 0);
#endif
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
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
	Describe(info, "Toy Fault", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
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
	Describe(info, "Toy Fault Replace", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::FakeUnit_Level::ID, CIV_HOOK_REPLACE, (void*)&ReplaceLevel);
	return true;
}

#elif defined(TOY_FAULT_BEFORE)

static bool BeforeAdd(const FakeUnit*, int, int, int&)
{
	int* volatile nowhere = 0;
	return *nowhere == 1;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Fault Before", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_BEFORE, (void*)&BeforeAdd);
	return true;
}

#elif defined(TOY_ENTRY_FAULT)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Entry Fault", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	volatile int zero = 0;
	return 10 / zero == 1;
}

#elif defined(TOY_ENTRY_BREAK)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Entry Break", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
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
	Describe(info, "Toy Bench", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::Square::ID, CIV_HOOK_AFTER, (void*)&AfterSquare);
	return true;
}

#elif defined(TOY_REENTRANT)

typedef bool (*HostCallFn)();
static HostCallFn s_hostCall = 0;
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

TOY_EXPORT void ToySetHostCall(HostCallFn call)
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
	Describe(info, "Toy Reentrant", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
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
	Describe(info, "Toy Threads", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	s_ownShutdown = &StopThread;
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
