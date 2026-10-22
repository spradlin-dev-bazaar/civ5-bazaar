#pragma once

// Benchmark builds only (CIV_TURN_BENCH). The computer plays by itself, and each turn's time goes to
// CivTurnBench.csv beside this DLL: a new game plays long enough to make a test save, a loaded save plays the benchmark.

#include <stdio.h>

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace CivTurnBench
{
	const int kNewGameTurns = 250;
	const int kSavedGameTurns = 50;

	struct State
	{
		bool started;
		bool logging;
		int turn;
		LONGLONG turnStart;
		LONGLONG coreTicks;
	};

	inline State& Get()
	{
		static State s = { false, false, -1, 0, 0 };
		return s;
	}

	inline LONGLONG Now()
	{
		LARGE_INTEGER t;
		QueryPerformanceCounter(&t);
		return t.QuadPart;
	}

	inline double Ms(LONGLONG ticks)
	{
		LARGE_INTEGER f;
		QueryPerformanceFrequency(&f);
		return ticks * 1000.0 / f.QuadPart;
	}

	inline void Write(const char* line)
	{
		char path[MAX_PATH];
		const DWORD length = GetModuleFileNameA(reinterpret_cast<HMODULE>(&__ImageBase), path, MAX_PATH);
		char* slash = strrchr(path, '\\');
		if (length == 0 || length >= MAX_PATH || !slash)
			return;
		strcpy_s(slash + 1, MAX_PATH - (slash + 1 - path), "CivTurnBench.csv");
		FILE* f = 0;
		if (fopen_s(&f, path, "a") == 0 && f)
		{
			fprintf(f, "%s\n", line);
			fclose(f);
		}
	}

	// Autoplay removes the player's own civilization, then hands them the first other civilization when it ends.
	inline void Start(CvGame& game)
	{
		const PlayerTypes active = game.getActivePlayer();
		PlayerTypes back = NO_PLAYER;
		for (int i = 0; i < MAX_MAJOR_CIVS && back == NO_PLAYER; ++i)
			if (i != active && GET_PLAYER((PlayerTypes)i).isAlive())
				back = (PlayerTypes)i;
		const int turns = game.getElapsedGameTurns() == 0 ? kNewGameTurns : kSavedGameTurns;
		char line[128];
		sprintf_s(line, sizeof(line), "# autoplay of %d turns from turn %d", turns, game.getGameTurn());
		Write(line);
		Write("turn,wall_ms,core_ms");
		State& s = Get();
		s.started = true;
		s.logging = true;
		s.turn = game.getGameTurn();
		s.turnStart = Now();
		s.coreTicks = 0;
		game.setAIAutoPlay(turns, back);
	}

	// Adds up the time of every CvGame::update call in a turn; the call that runs doTurn ends the turn.
	class UpdateScope
	{
	public:
		explicit UpdateScope(CvGame& game) : m_start(Now())
		{
			State& s = Get();
			if (!s.started)
			{
				if (game.getActivePlayer() != NO_PLAYER && game.getGameState() == GAMESTATE_ON)
					Start(game);
			}
			else if (s.logging && game.getGameTurn() != s.turn)
			{
				char line[64];
				sprintf_s(line, sizeof(line), "%d,%.1f,%.1f", s.turn, Ms(m_start - s.turnStart), Ms(s.coreTicks));
				Write(line);
				s.logging = game.getAIAutoPlay() > 0;
				s.turn = game.getGameTurn();
				s.turnStart = m_start;
				s.coreTicks = 0;
			}
		}

		~UpdateScope()
		{
			Get().coreTicks += Now() - m_start;
		}

	private:
		LONGLONG m_start;
	};
}
