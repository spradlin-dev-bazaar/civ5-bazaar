#include "fake_engine.h"

int FakeUnit::add(int a, int b) const
{
	return a + b;
}

void FakeUnit::notify(int amount)
{
	m_notified += amount;
}

const std::string& FakeUnit::name() const
{
	return m_name;
}

int FakeUnit::Twice(int x)
{
	return 2 * x;
}

int FakeUnit::Scale(int v, int factor) const
{
	return v * factor;
}

void FakeUnit::Ignore(int)
{
}

int g_levelCalls = 0;

const int FakeUnit::Level() const
{
	++g_levelCalls;
	return 7;
}

std::string FakeUnit::Greet(std::string who) const
{
	return "Hello " + who;
}

bool FakeUnit::operator==(const FakeUnit& other) const
{
	return m_name == other.m_name;
}

int FakeRules::Bonus(int x)
{
	return x + 1;
}

__declspec(noinline) int Square(int x)
{
	return x * x;
}

static int Helper(int x)
{
	return x * 10;
}

int UsesHelper(int x)
{
	return Helper(x) + 1;
}

int Unannounced(int x, int y = 3)
{
	return x + y;
}

int CallsUnannounced(int x)
{
	return Unannounced(x);
}
