// Toy plugins for the in-game checks, built once per TOY_* define against the hooked host.
#include "CvGameCoreDLLPCH.h"

#include "CivHooks.h"
#include "CivPluginApi.h"

#include <stdarg.h>
#include <stdio.h>

#define TOY_EXPORT extern "C" __declspec(dllexport)

static const CivHostInfo* s_host = 0;

static void Log(const char* format, ...)
{
	char line[512];
	va_list args;
	va_start(args, format);
	_vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
	va_end(args);
	s_host->Log(s_host->pluginIndex, line);
}

static void Describe(CivPluginInfo* info, const char* name, int major, int minor)
{
	info->name = name;
	info->version = "1.0";
	info->builtApiMajor = major;
	info->builtApiMinor = minor;
}

typedef int (*ScoreFn)(const CvPlayer*, bool, bool);

static void Register(int hookId, int kind, void* fn, const char* what)
{
	const int result = s_host->RegisterHook(s_host->pluginIndex, hookId, kind, fn);
	Log("registered %s: %s", what, result == CIV_HOOK_OK ? "ok" : "refused");
}

#if defined(TOY_GOLD)

static bool BeforeDoTurn(CvPlayer* self)
{
	if (self->isHuman())
		Log("turn starting for %s with %d gold", self->getCivilizationShortDescription(), self->GetTreasury()->GetGold());
	return false;
}

static void AfterDoTurn(CvPlayer* self)
{
	if (self->isHuman())
		Log("turn finished for %s with %d gold", self->getCivilizationShortDescription(), self->GetTreasury()->GetGold());
}

static int ReplaceScore(ScoreFn original, const CvPlayer* self, bool bFinal, bool bVictory)
{
	return self->isHuman() ? 4242 : original(self, bFinal, bVictory);
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Gold", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::CvPlayer_doTurn::ID, CIV_HOOK_BEFORE, (void*)&BeforeDoTurn, "before CvPlayer::doTurn");
	Register(CivHooks::CvPlayer_doTurn::ID, CIV_HOOK_AFTER, (void*)&AfterDoTurn, "after CvPlayer::doTurn");
	Register(CivHooks::CvPlayer_GetScore::ID, CIV_HOOK_REPLACE, (void*)&ReplaceScore, "replace CvPlayer::GetScore");
	return true;
}

TOY_EXPORT void CivPluginShutdown()
{
	Log("shutting down");
}

#elif defined(TOY_RIVAL)

static int ReplaceScore(ScoreFn, const CvPlayer*, bool, bool)
{
	return 1;
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Rival", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::CvPlayer_GetScore::ID, CIV_HOOK_REPLACE, (void*)&ReplaceScore, "replace CvPlayer::GetScore");
	return true;
}

#elif defined(TOY_CRASH)

static void AfterDoTurn(CvPlayer* self)
{
	if (self->isHuman())
	{
		int* volatile nowhere = 0;
		*nowhere = self->GetTreasury()->GetGold();
	}
}

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Crash", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR);
	Register(CivHooks::CvPlayer_doTurn::ID, CIV_HOOK_AFTER, (void*)&AfterDoTurn, "after CvPlayer::doTurn");
	return true;
}

#elif defined(TOY_NEWER)

TOY_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* info)
{
	s_host = host;
	Describe(info, "Toy Newer", CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR + 1);
	return true;
}

#else
#error Define one TOY_* variant.
#endif
