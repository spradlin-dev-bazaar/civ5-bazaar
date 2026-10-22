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

static void ReplaceNotify(FakeUnit* self, int amount)
{
	self->m_notified += amount * 2;
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
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_BEFORE, (void*)&BeforeAdd);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
	Register(CivHooks::FakeUnit_notify::ID, CIV_HOOK_REPLACE, (void*)&ReplaceNotify);
	Register(CivHooks::FakeUnit_name::ID, CIV_HOOK_AFTER, (void*)&AfterName);
	return true;
}

TOY_EXPORT int ToyRegisterLate()
{
	return s_host->RegisterHook(s_host->pluginIndex, CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
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

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Second", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_BEFORE, (void*)&BeforeAdd);
	Register(CivHooks::FakeUnit_add::ID, CIV_HOOK_AFTER, (void*)&AfterAdd);
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
	Register(CivHooks::FakeRules_Bonus::ID, CIV_HOOK_AFTER, (void*)&AfterPlusThousand);
	Register(CivHooks::fake_engine_cpp_Helper::ID, CIV_HOOK_AFTER, (void*)&AfterPlusThousand);
	Register(CivHooks::Unannounced::ID, CIV_HOOK_AFTER, (void*)&AfterUnannounced);
	return true;
}

#elif defined(TOY_CONFLICT)

static void ReplaceNotify(FakeUnit* self, int amount)
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

#elif defined(TOY_NO_ENTRY)

TOY_EXPORT int NotAPlugin()
{
	return 0;
}

#else
#error Define one TOY_* variant.
#endif
