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
	int active;
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
extern const int g_CivHookPointCount;

bool CivHookRunBefore(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);
// 1 when a replacement ran, 0 when there is none, -1 when it faulted.
int CivHookRunReplace(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);
void CivHookRunAfter(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx);

template<class T> struct CivHookArg { typedef T* Ptr; };
template<class T> struct CivHookArg<T&> { typedef T* Ptr; };

// A vetoed call, or one whose replacement faulted, returns what the hooks left in the slot: the
// type's default unless a hook set it. A reference result can't be empty, so its wrapper runs the
// original instead.
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
