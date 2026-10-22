#include "fake_engine.h"

#include "CivHostHooks.h"

CivHookPoint g_CivHookPoints[FAKE_HOOK_COUNT];
const int g_CivHookPointCount = FAKE_HOOK_COUNT;
extern const char* const g_CivHookPointNames[] = {"FakeUnit::add", "FakeUnit::notify", "FakeUnit::name", "Square"};

int FakeUnit::CivOrig_add(int a, int b) const
{
	return a + b;
}

void FakeUnit::CivOrig_notify(int amount)
{
	m_notified += amount;
}

const std::string& FakeUnit::CivOrig_name() const
{
	return m_name;
}

__declspec(noinline) int CivOrig_Square(int x)
{
	return x * x;
}

// The four wrappers below follow generate.py's output line for line.

int FakeUnit::add(int a, int b) const
{
	CivHookPoint& civ_hp = g_CivHookPoints[0];
	if (!civ_hp.active)
		return CivOrig_add(a, b);
	typedef int civ_R;
	typedef CivHookResult<civ_R> civ_Res;
	struct civ_C
	{
		typedef bool (*BeforeFn)(const FakeUnit*, int, int, civ_Res::Slot&);
		typedef civ_R (*ReplaceFn)(const FakeUnit*, int, int);
		typedef void (*AfterFn)(const FakeUnit*, int, int, civ_Res::Slot&);
		void* fn;
		bool veto;
		const FakeUnit* self;
		CivHookArg<int>::Ptr a0;
		CivHookArg<int>::Ptr a1;
		civ_Res* res;
		static void Before(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.veto = reinterpret_cast<BeforeFn>(c.fn)(c.self, *c.a0, *c.a1, c.res->value); }
		static void Replace(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.res->Set(reinterpret_cast<ReplaceFn>(c.fn)(c.self, *c.a0, *c.a1)); }
		static void After(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<AfterFn>(c.fn)(c.self, *c.a0, *c.a1, c.res->value); }
	};
	civ_Res civ_res;
	civ_C civ_c = {0, false, this, &a, &b, &civ_res};
	if (!CivHookRunBefore(civ_hp, 0, &civ_C::Before, &civ_c) && CivHookRunReplace(civ_hp, 0, &civ_C::Replace, &civ_c) == 0)
		civ_res.Set(CivOrig_add(a, b));
	if (civ_res.Empty())
		civ_res.Set(CivOrig_add(a, b));
	CivHookRunAfter(civ_hp, 0, &civ_C::After, &civ_c);
	return civ_res.Get();
}

void FakeUnit::notify(int amount)
{
	CivHookPoint& civ_hp = g_CivHookPoints[1];
	if (!civ_hp.active) { CivOrig_notify(amount); return; }
	struct civ_C
	{
		typedef bool (*BeforeFn)(FakeUnit*, int);
		typedef void (*ReplaceFn)(FakeUnit*, int);
		typedef void (*AfterFn)(FakeUnit*, int);
		void* fn;
		bool veto;
		FakeUnit* self;
		CivHookArg<int>::Ptr a0;
		static void Before(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.veto = reinterpret_cast<BeforeFn>(c.fn)(c.self, *c.a0); }
		static void Replace(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<ReplaceFn>(c.fn)(c.self, *c.a0); }
		static void After(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<AfterFn>(c.fn)(c.self, *c.a0); }
	};
	civ_C civ_c = {0, false, this, &amount};
	if (!CivHookRunBefore(civ_hp, 1, &civ_C::Before, &civ_c) && CivHookRunReplace(civ_hp, 1, &civ_C::Replace, &civ_c) == 0)
		CivOrig_notify(amount);
	CivHookRunAfter(civ_hp, 1, &civ_C::After, &civ_c);
}

const std::string& FakeUnit::name() const
{
	CivHookPoint& civ_hp = g_CivHookPoints[2];
	if (!civ_hp.active)
		return CivOrig_name();
	typedef const std::string& civ_R;
	typedef CivHookResult<civ_R> civ_Res;
	struct civ_C
	{
		typedef bool (*BeforeFn)(const FakeUnit*, civ_Res::Slot&);
		typedef civ_R (*ReplaceFn)(const FakeUnit*);
		typedef void (*AfterFn)(const FakeUnit*, civ_Res::Slot&);
		void* fn;
		bool veto;
		const FakeUnit* self;
		civ_Res* res;
		static void Before(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.veto = reinterpret_cast<BeforeFn>(c.fn)(c.self, c.res->value); }
		static void Replace(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.res->Set(reinterpret_cast<ReplaceFn>(c.fn)(c.self)); }
		static void After(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<AfterFn>(c.fn)(c.self, c.res->value); }
	};
	civ_Res civ_res;
	civ_C civ_c = {0, false, this, &civ_res};
	if (!CivHookRunBefore(civ_hp, 2, &civ_C::Before, &civ_c) && CivHookRunReplace(civ_hp, 2, &civ_C::Replace, &civ_c) == 0)
		civ_res.Set(CivOrig_name());
	if (civ_res.Empty())
		civ_res.Set(CivOrig_name());
	CivHookRunAfter(civ_hp, 2, &civ_C::After, &civ_c);
	return civ_res.Get();
}

__declspec(noinline) int Square(int x)
{
	CivHookPoint& civ_hp = g_CivHookPoints[3];
	if (!civ_hp.active)
		return CivOrig_Square(x);
	typedef int civ_R;
	typedef CivHookResult<civ_R> civ_Res;
	struct civ_C
	{
		typedef bool (*BeforeFn)(int, civ_Res::Slot&);
		typedef civ_R (*ReplaceFn)(int);
		typedef void (*AfterFn)(int, civ_Res::Slot&);
		void* fn;
		bool veto;
		CivHookArg<int>::Ptr a0;
		civ_Res* res;
		static void Before(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.veto = reinterpret_cast<BeforeFn>(c.fn)(*c.a0, c.res->value); }
		static void Replace(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.res->Set(reinterpret_cast<ReplaceFn>(c.fn)(*c.a0)); }
		static void After(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<AfterFn>(c.fn)(*c.a0, c.res->value); }
	};
	civ_Res civ_res;
	civ_C civ_c = {0, false, &x, &civ_res};
	if (!CivHookRunBefore(civ_hp, 3, &civ_C::Before, &civ_c) && CivHookRunReplace(civ_hp, 3, &civ_C::Replace, &civ_c) == 0)
		civ_res.Set(CivOrig_Square(x));
	if (civ_res.Empty())
		civ_res.Set(CivOrig_Square(x));
	CivHookRunAfter(civ_hp, 3, &civ_C::After, &civ_c);
	return civ_res.Get();
}
