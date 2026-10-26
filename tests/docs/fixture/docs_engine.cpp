#include "docs_engine.h"
#include "docs_shapes.h"

static Thing s_things[2];

Thing& Thing::Get(int i)
{
	return s_things[i];
}

//	--------------------------------------------------------------------------------
/// The thing's score.
int Thing::Score(bool bFinal) const
{
#if defined(DOCS_NEVER)
#define DOCS_UNUSED 1
#ifdef DOCS_INNER
	CivHandPopupRaised(0);
#endif // DOCS_INNER
	return 0;
#else
	return Inline() + (bFinal ? 1 : 0);
#endif
}

int Thing::Score(int iBase, int iBonus)
{
#if defined(CIV_HOST_API)
	CivHandPopupRaised(iBase);
#endif
	GAMEEVENTINVOKE_HOOK(GAMEEVENT_CityBuilt, iBase, iBonus);
	return Score(true) + iBonus;
}

int Thing::Total()
{
	return 1;
}

int Thing::total()
{
	// CivHandNotAHook(1);
	return GET_THING(0).Total();
}

bool Thing::operator==(const Thing& other) const
{
	return m_i == other.m_i;
}

int Thing::operator[](int i) const
{
	return m_i + i;
}

void Thing::index()
{
}

const int Thing::Level() const
{
	return m_i;
}

const char* const Thing::Name() const
{
	return "thing";
}

const Thing& Thing::Self() const
{
	return *this;
}

// - - - - - - - - - - - - - - - -
// Resets.
void Thing::Reset()
{
	m_i = 0;
}

int Thing::Weight(int) const
{
#if defined(CIV_HOST_API)
	return 20;
#else // not CIV_HOST_API
#ifdef DOCS_OTHER
	return 30;
#endif // DOCS_OTHER
	return 40;
#endif // CIV_HOST_API
}

int BetterThing::Score(bool bFinal) const
{
	return Thing::Score(bFinal) * 2;
}

int Square::Area() const
{
	return 4;
}

int Measure(const Shape& shape)
{
	return shape.Area();
}

Counter::Counter(int n) : m_n(n)
{
#if defined(CIV_HOST_API)
	CivHandPopupRaised(n);
#endif
}

//	------------------------------------------------------------------
//
// Counts.
//
int Count()
{
	Counter counter(3);
	return counter.m_n;
}

////////////////////////////////////////
// Setup
////////////////////////////////////////
int Setup::Option::GetValue() const
{
	return 1;
}

int FreeHelper(int x)
{
	return Thing::Get(x).Score(x, 1);
}

int Thing::Feel(Mood mood) const
{
	return mood;
}
