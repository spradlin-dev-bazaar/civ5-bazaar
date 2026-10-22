#pragma once

#include <string>

// A stand-in engine, hooked by the real generator at test time. Each function is a shape the
// generator must handle.
class FakeUnit
{
public:
	FakeUnit() : m_notified(0), m_name("Warrior") {}

	int add(int a, int b) const;
	void notify(int amount);
	const std::string& name() const;
	static int Twice(int x);
	int Scale(int v, int factor = 2) const;
	void Ignore(int);
	const int Level() const;
	std::string Greet(std::string who) const;
	bool operator==(const FakeUnit& other) const;

	int m_notified;
	std::string m_name;
};

namespace FakeRules
{
	int Bonus(int x);
}

int Square(int x);
int UsesHelper(int x);
int CallsUnannounced(int x);
