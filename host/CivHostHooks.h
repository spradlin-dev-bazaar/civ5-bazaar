#pragma once

#include "CivPluginApi.h"

#include <malloc.h>
#include <new>

struct CivHookEntry
{
	void* fn;
	int plugin;
	CivHookEntry* next;
	bool loggedSkippedOriginal;
	bool loggedIgnoredVeto;
	// An index into a call's records, the same for every before-hook and after-hook of this plugin on this hook point;
	// -1 for a replacement and for a hand-placed hook.
	int record;
};

struct CivHookPoint
{
	CivHookEntry* before;
	CivHookEntry* after;
	CivHookEntry* replace;
	// One for each plugin with a before-hook or after-hook here; a hand-placed hook point keeps 0.
	int recordCount;
};

// The first member of every generated thunk context; the runtime reaches it through a void*, so a context struct
// never gets a base class or a virtual function.
struct CivHookCtx
{
	CivHookCtx() : fn(0), veto(false), call(0), records(0), recordCount(0), resultUnset(false) {}
	// Blanks the records here, where the wrapper hands them over, since _alloca leaves whatever the stack held.
	CivHookCtx(CivHookCall* first, int count) : fn(0), veto(false), call(0), records(first), recordCount(count), resultUnset(false)
	{
		const CivHookCall blank = {false, 0};
		for (int i = 0; i < count; ++i)
			records[i] = blank;
	}

	void* fn;
	bool veto;
	// The record of the plugin whose hook runs now.
	CivHookCall* call;
	CivHookCall* records;
	int recordCount;
	// Set by a before-hook's thunk on a function that returns a reference, where a veto needs a result.
	bool resultUnset;
};

// _alloca makes the records in the frame of the wrapper that calls this, so they last until its after-hooks have run.
#define CIV_HOOK_RECORDS(count) static_cast<CivHookCall*>(_alloca((count) * sizeof(CivHookCall)))

typedef void (*CivHookThunk)(void*);

extern CivHookPoint g_CivHookPoints[];
// One byte per hook point, apart from the hook lists, so the check every wrapper makes stays in cache.
extern unsigned char g_CivHookActive[];
extern const int g_CivHookPointCount;
extern const char* const g_CivHookPointNames[];
// Zero for a number whose function is gone or changed shape, which a plugin built against an older SDK may still ask for.
extern const unsigned char g_CivHookLive[];

// A hand-placed hook keeps its plugins in the before list, in load order.
extern CivHookPoint g_CivHandHookPoints[];
extern const int g_CivHandHookCount;
const char* CivHandHookName(int handHook);

// The runtime numbers hand-placed hooks after the generated hook points.
inline int CivHandHookId(int handHook)
{
	return g_CivHookPointCount + handHook;
}

// Generated from the engine source: the hook points whose functions call a hand-placed hook.
struct CivHandHookSite
{
	int handHook;
	int hookPoint;
};
extern const CivHandHookSite g_CivHandHookSites[];
extern const int g_CivHandHookSiteCount;

bool CivHookRunBefore(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);
// False when there is no replacement or it faulted; the wrapper then runs the original.
bool CivHookRunReplace(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);
void CivHookRunAfter(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);
// The original a replacement receives calls this first.
void CivHookOriginalCalled();

template<class T> struct CivHookArg { typedef T* Ptr; typedef T Type; };
template<class T> struct CivHookArg<T&> { typedef T* Ptr; typedef T& Type; };

// A vetoed call returns what the hooks left in value: the type's default unless a hook set it.
// A reference result has no default, so CivHookRunBefore ignores a veto that leaves it empty.
template<class R> struct CivHookResult
{
	R value;
	CivHookResult() : value() {}
	// Copy-construct rather than assign: some engine handles copy state their operator= drops.
	void Set(R v) { value.~R(); new (&value) R(v); }
	R Get() { return value; }
};

template<class T> struct CivHookResult<const T> : CivHookResult<T>
{
};

template<class T> struct CivHookResult<T&>
{
	T* value;
	CivHookResult() : value(0) {}
	void Set(T& v) { value = &v; }
	bool Empty() const { return value == 0; }
	T& Get() { return *value; }
};
