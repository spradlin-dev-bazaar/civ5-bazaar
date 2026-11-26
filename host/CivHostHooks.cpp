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
		hp.records = 0;
	}

	int RecordOf(CivHookPoint& hp, int plugin)
	{
		const CivHookEntry* const lists[] = {hp.before, hp.after};
		for (int i = 0; i < 2; ++i)
			for (const CivHookEntry* e = lists[i]; e; e = e->next)
				if (e->plugin == plugin)
					return e->record;
		return hp.records++;
	}

	// Null for a hand-placed hook, whose context has no records.
	CivHookCall* RecordFor(const CivHookCtx& c, const CivHookEntry& e)
	{
		return e.record < c.recordCount ? &c.records[e.record] : 0;
	}

	void LogSkippedOriginal(int plugin, int hookId)
	{
		CivHostLog("Plugin %s: its replacement of %s returned without running the original, so no hook inside the original ran. This is logged only once.",
			CivHostRecord(plugin).name.c_str(), CivHookName(hookId));
	}

	void LogIgnoredVeto(int plugin, int hookId)
	{
		CivHostLog("Plugin %s: its before-hook on %s returned true to veto the call but left result null. That function returns a reference, so a veto needs an object to give the caller. Bazaar ignored the veto and ran the before-hooks after this one, then the replacement or the game's function, then the after-hooks. A veto of this function counts only when a before-hook sets result, its last parameter, to the object that the caller gets back. This is logged only once.",
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
	e->loggedIgnoredVeto = false;
	e->record = -1;
	if (kind == CIV_HOOK_REPLACE)
	{
		hp.replace = e;
	}
	else
	{
		e->record = RecordOf(hp, plugin);
		CivHookEntry** tail = kind == CIV_HOOK_BEFORE ? &hp.before : &hp.after;
		while (*tail)
			tail = &(*tail)->next;
		*tail = e;
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

int CivHookReplacer(int hookId)
{
	const CivHookEntry* e = g_CivHookPoints[hookId].replace;
	return e ? e->plugin : -1;
}

std::vector<int> CivHandHookPlugins(int handHook)
{
	std::vector<int> plugins;
	for (const CivHookEntry* e = g_CivHandHookPoints[handHook].before; e; e = e->next)
		plugins.push_back(e->plugin);
	return plugins;
}

bool CivHookRunBefore(const CivHookPoint& hp, int id, CivHookThunk thunk, void* ctx)
{
	CivHookCtx* c = static_cast<CivHookCtx*>(ctx);
	const CivHookCall blank = {false, 0};
	for (int i = 0; i < c->recordCount; ++i)
		c->records[i] = blank;
	bool vetoed = false;
	for (CivHookEntry* e = hp.before; e && !vetoed; e = e->next)
	{
		if (!CivHostAlive(e->plugin))
			continue;
		c->veto = false;
		c->call = RecordFor(*c, *e);
		if (!CivCallsHook(e, id, thunk, ctx) || !c->veto)
			continue;
		if (!c->resultUnset)
			vetoed = true;
		else if (!e->loggedIgnoredVeto)
		{
			e->loggedIgnoredVeto = true;
			LogIgnoredVeto(e->plugin, id);
		}
	}
	for (int i = 0; i < c->recordCount; ++i)
		c->records[i].vetoed = vetoed;
	return vetoed;
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
	CivHookCtx* c = static_cast<CivHookCtx*>(ctx);
	for (const CivHookEntry* e = hp.after; e; e = e->next)
	{
		if (!CivHostAlive(e->plugin))
			continue;
		c->call = RecordFor(*c, *e);
		CivCallsHook(e, id, thunk, ctx);
	}
}
