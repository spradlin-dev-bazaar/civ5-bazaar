#pragma once

#include <string>

#include "..\fixture_options.h"

// A stand-in engine, hooked by the real generator at test time. Each function is a shape the
// generator must handle.

// Shares its name with FakeUnit's private Hidden, which Peek takes.
struct Hidden
{
	long other;
};

class FakeUnit
{
public:
	FakeUnit() : m_notified(0), m_name("Warrior") {}

	int add(int a, int b) const;
	int Subtract(int a, int b) const;
	int Grow(int x) const;
	int Grow(int x, int y) const;
	void notify(int amount);
	const std::string& name() const;
	static int Twice(int x);
	int Scale(int v, int factor = 2) const;
	void Ignore(int);
	const int Level() const;
	std::string Greet(std::string who) const;
	bool operator==(const FakeUnit& other) const;
#if defined(FAKE_MOD_OPTION)
	int Heal(int amount) const;
#else
	int Heal(int amount, bool full) const;
#endif
	int Range() const;
#if defined(FAKE_MOD_OPTION)
	int Reach() const;
#endif
	void CancelOrders(int reason);
	bool PlayedByPlugin(int player) const;

private:
	struct Hidden
	{
		int value;
	};

public:
	int Peek(const Hidden& hidden) const;

	enum Mood
	{
		CALM,
		ANGRY,
	};
	int Feel(Mood mood) const;

	int m_notified;
	std::string m_name;
	static int s_created;
};

extern int g_levelCalls;

namespace FakeRules
{
	int Bonus(int x);
#if !defined(FAKE_MOD_OPTION)
	int Penalty(int x, int y);
#else
	int Penalty(int x);
#endif
}

int Square(int x);
int UsesHelper(int x);
int CallsUnannounced(int x);
