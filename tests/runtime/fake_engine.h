#pragma once

#include <string>

// Stand-ins for engine functions, wrapped exactly the way generate.py wraps real ones.
enum FakeHook
{
	FAKE_HOOK_ADD = 0,
	FAKE_HOOK_NOTIFY = 1,
	FAKE_HOOK_NAME = 2,
	FAKE_HOOK_SQUARE = 3,
	FAKE_HOOK_COUNT = 4,
};

class FakeUnit
{
public:
	FakeUnit() : m_notified(0), m_name("Warrior") {}

	int add(int a, int b) const;
	int CivOrig_add(int a, int b) const;

	void notify(int amount);
	void CivOrig_notify(int amount);

	const std::string& name() const;
	const std::string& CivOrig_name() const;

	int m_notified;
	std::string m_name;
};

int Square(int x);
int CivOrig_Square(int x);
