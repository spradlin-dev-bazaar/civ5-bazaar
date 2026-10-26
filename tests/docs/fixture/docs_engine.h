#pragma once

#define GAMEEVENT_CityBuilt "CityBuilt", "ii"
#define GAMEEVENTINVOKE_HOOK(...) 0
#define GET_THING(x) Thing::Get(x)

void CivHandPopupRaised(int player);

class Thing
{
public:
	static Thing& Get(int i);
	virtual int Score(bool bFinal) const;
	int Score(int iBase, int iBonus);
	int Total();
	int total();
	bool operator==(const Thing& other) const;
	int operator[](int i) const;
	int Inline() const { return m_i + 1; }
	void index();
	const int Level() const;
	const char* const Name() const;
	const Thing& Self() const;
	void Reset();
	int Weight(int) const;
	enum Mood
	{
		MOOD_CALM
	};
	int Feel(Mood mood) const;

protected:
	int m_i;
};

class BetterThing : public Thing
{
public:
	virtual int Score(bool bFinal) const;
};

class Counter
{
public:
	Counter(int n);
	int m_n;
};

namespace Setup
{
class Option
{
public:
	int GetValue() const;
};
}
