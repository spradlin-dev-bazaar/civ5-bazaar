#pragma once

#include <new>

struct CivHookEntry
{
	void* fn;
	int plugin;
	CivHookEntry* next;
};

struct CivHookPoint
{
	CivHookEntry* before;
	CivHookEntry* after;
	CivHookEntry* replace;
};

// The first member of every generated thunk context; the runtime reaches it through a void*.
struct CivHookCtx
{
	void* fn;
	bool veto;
};

typedef void (*CivHookThunk)(void*);

extern CivHookPoint g_CivHookPoints[];
// One byte per hook point, apart from the hook lists, so the check every wrapper makes stays in cache.
extern unsigned char g_CivHookActive[];
extern const int g_CivHookPointCount;

bool CivHookRunBefore(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);
// False when there is no replacement or it faulted; the wrapper then runs the original.
bool CivHookRunReplace(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);
void CivHookRunAfter(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);

template<class T> struct CivHookArg { typedef T* Ptr; typedef T Type; };
template<class T> struct CivHookArg<T&> { typedef T* Ptr; typedef T& Type; };

// A vetoed call returns what the hooks left in the slot: the type's default unless a hook set it.
// A reference result can't be empty, so its wrapper runs the original instead.
template<class R> struct CivHookResult
{
	typedef R Slot;
	R value;
	CivHookResult() : value() {}
	// Copy-construct rather than assign: some engine handles copy state their operator= drops.
	void Set(R v) { value.~R(); new (&value) R(v); }
	bool Empty() const { return false; }
	R Get() { return value; }
};

template<class T> struct CivHookResult<const T> : CivHookResult<T>
{
};

template<class T> struct CivHookResult<T&>
{
	typedef T* Slot;
	T* value;
	CivHookResult() : value(0) {}
	void Set(T& v) { value = &v; }
	bool Empty() const { return value == 0; }
	T& Get() { return *value; }
};
