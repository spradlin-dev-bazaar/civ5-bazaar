#pragma once

#include <windows.h>

// The game writes one save from a thread of its own.
class CivLock
{
public:
	CivLock() { InitializeCriticalSection(&m_section); }
	~CivLock() { DeleteCriticalSection(&m_section); }
	void Enter() { EnterCriticalSection(&m_section); }
	void Leave() { LeaveCriticalSection(&m_section); }

private:
	CivLock(const CivLock&);
	CivLock& operator=(const CivLock&);

	CRITICAL_SECTION m_section;
};

class CivLockHold
{
public:
	explicit CivLockHold(CivLock& lock) : m_lock(lock) { m_lock.Enter(); }
	~CivLockHold() { m_lock.Leave(); }

private:
	CivLockHold(const CivLockHold&);
	CivLockHold& operator=(const CivLockHold&);

	CivLock& m_lock;
};
