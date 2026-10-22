#pragma once

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

// Every generated thunk context starts with these two fields.
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

template<class R> struct CivHookResult
{
	typedef R Slot;
	R value;
	CivHookResult() : value() {}
	void Set(R v) { value = v; }
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
