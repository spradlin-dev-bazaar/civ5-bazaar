#include "CivHostCalls.h"
#include "CivHostHookList.h"
#include "CivHostHooks.h"
#include "CivHostRuntime.h"

#include <windows.h>
#include <string.h>

namespace
{
	// The game can run hooked functions on two threads at the same time, so each thread keeps its own pointer.
	class ThreadFlagSlot
	{
	public:
		ThreadFlagSlot() : m_slot(TlsAlloc()) {}
		~ThreadFlagSlot()
		{
			if (m_slot != TLS_OUT_OF_INDEXES)
				TlsFree(m_slot);
		}
		bool* Get() const { return m_slot == TLS_OUT_OF_INDEXES ? 0 : static_cast<bool*>(TlsGetValue(m_slot)); }
		bool Set(bool* flag) const { return m_slot != TLS_OUT_OF_INDEXES && TlsSetValue(m_slot, flag) != FALSE; }

	private:
		ThreadFlagSlot(const ThreadFlagSlot&);
		ThreadFlagSlot& operator=(const ThreadFlagSlot&);

		DWORD m_slot;
	};

	ThreadFlagSlot s_originalCalled;

	CivHookPoint& Point(int id)
	{
		return id < g_CivHookPointCount ? g_CivHookPoints[id] : g_CivHandHookPoints[id - g_CivHookPointCount];
	}

	void DeleteEntries(CivHookEntry* e)
	{
		while (e)
		{
			CivHookEntry* next = e->next;
			delete e;
			e = next;
		}
	}

	void RemoveHooks(CivHookPoint& hp)
	{
		DeleteEntries(hp.before);
		DeleteEntries(hp.after);
		delete hp.replace;
		hp.before = hp.after = hp.replace = 0;
	}

	void LogSkippedOriginal(int plugin, int hookId)
	{
		CivHostLog("Plugin %s: its replacement of %s returned without running the original, so no hook inside the original ran. This is logged only once.",
			CivHostRecord(plugin).name.c_str(), CivHookName(hookId));
	}
}

const char* CivHookName(int id)
{
	if (id >= 0 && id < g_CivHookPointCount)
		return g_CivHookPointNames[id];
	return id >= g_CivHookPointCount ? CivHandHookName(id - g_CivHookPointCount) : "?";
}

// Players see the name alone, unless an overload shares it and only the parameters tell them apart.
std::string CivHookShortName(int id)
{
	const std::string full = CivHookName(id);
	const size_t open = full.find('(');
	const std::string name = full.substr(0, open);
	if (open == std::string::npos || name.empty())
		return full;
	for (int i = 0; i < g_CivHookPointCount; ++i)
		if (i != id && strncmp(g_CivHookPointNames[i], name.c_str(), name.size()) == 0 && g_CivHookPointNames[i][name.size()] == '(')
			return full;
	return name + "(...)";
}

void CivHookAdd(int plugin, int id, int kind, void* fn)
{
	CivHookPoint& hp = Point(id);
	CivHookEntry* e = new CivHookEntry;
	e->fn = fn;
	e->plugin = plugin;
	e->next = 0;
	e->loggedSkippedOriginal = false;
	if (kind == CIV_HOOK_BEFORE)
	{
		CivHookEntry** tail = &hp.before;
		while (*tail)
			tail = &(*tail)->next;
		*tail = e;
	}
	else if (kind == CIV_HOOK_AFTER)
	{
		// After-hooks run in reverse load order, so each plugin's goes in front.
		e->next = hp.after;
		hp.after = e;
	}
	else
	{
		hp.replace = e;
	}
	if (id < g_CivHookPointCount)
		g_CivHookActive[id] = 1;
}

void CivHookRemoveAll()
{
	for (int i = 0; i < g_CivHookPointCount; ++i)
	{
		if (!g_CivHookActive[i])
			continue;
		RemoveHooks(g_CivHookPoints[i]);
		g_CivHookActive[i] = 0;
	}
	for (int i = 0; i < g_CivHandHookCount; ++i)
		RemoveHooks(g_CivHandHookPoints[i]);
}

bool CivHookRunBefore(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	CivHookCtx* c = static_cast<CivHookCtx*>(ctx);
	for (const CivHookEntry* e = hp.before; e; e = e->next)
	{
		if (!CivHostAlive(e->plugin))
			continue;
		c->veto = false;
		if (CivCallsHook(e, id, thunk, ctx) && c->veto)
			return true;
	}
	return false;
}

// No C++ objects may live in this frame, or __try is not allowed.
bool CivHookRunReplace(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	CivHookEntry* e = hp.replace;
	if (!e || !CivHostAlive(e->plugin))
		return false;
	// The original may run other replacements before this one returns, and an exception nobody here handles may pass
	// through, so the outer replacement's flag is always put back.
	bool* const outer = s_originalCalled.Get();
	bool called = false;
	bool ran = false;
	const bool tracked = s_originalCalled.Set(&called);
	__try
	{
		ran = CivCallsHook(e, id, thunk, ctx);
	}
	__finally
	{
		s_originalCalled.Set(outer);
	}
	if (ran && tracked && !called && !e->loggedSkippedOriginal)
	{
		e->loggedSkippedOriginal = true;
		LogSkippedOriginal(e->plugin, id);
	}
	return ran;
}

void CivHookOriginalCalled()
{
	if (bool* const called = s_originalCalled.Get())
		*called = true;
}

void CivHookRunAfter(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	for (const CivHookEntry* e = hp.after; e; e = e->next)
		if (CivHostAlive(e->plugin))
			CivCallsHook(e, id, thunk, ctx);
}
