// A plugin's Lua functions, run through Bazaar's crash guard as the engine's Lua closure runs them.
#include "harness.h"

#include <setjmp.h>

namespace
{
	// toy_lua pushes its functions in this order.
	enum
	{
		kTwo,
		kMinusOne,
		kCrash,
		kError,
		kHighIndex,
		kNegativeIndex,
		kPushed
	};

	struct Pushed
	{
		unsigned int serial;
		CivLuaFunction fn;
	};

	std::vector<Pushed> s_pushed;

	void Record(lua_State*, unsigned int serial, CivLuaFunction fn)
	{
		Pushed p = {serial, fn};
		s_pushed.push_back(p);
	}

	bool Run(const Pushed& p, int* results, std::string* why)
	{
		char text[256] = "";
		const bool ran = CivHostCallLuaFunction(p.serial, p.fn, 0, results, text, sizeof(text));
		*why = text;
		return ran;
	}

	bool Refused(const Pushed& p, const char* reason)
	{
		int results = 0;
		std::string why;
		return !Run(p, &results, &why) && why.find(reason) != std::string::npos;
	}

	// No C++ objects may live in this frame: the plugin's longjmp lands here, as a Lua error lands in Lua.
	bool JumpsBack(const Pushed& p)
	{
		jmp_buf landing;
		if (setjmp(landing))
			return true;
		int results = 0;
		char why[256] = "";
		CivHostCallLuaFunction(p.serial, p.fn, reinterpret_cast<lua_State*>(&landing), &results, why, sizeof(why));
		return false;
	}

	std::vector<Pushed> LoadToyLua()
	{
		s_pushed.clear();
		const char* const names[] = {"toy_lua.dll"};
		StartWith(names);
		return s_pushed;
	}
}

void TestLuaFunctions()
{
	CivHostSetLuaPusher(&Record);
	const std::vector<Pushed> first = LoadToyLua();
	Check(first.size() == kPushed && first[kTwo].serial != 0 && first[kHighIndex].serial == 0 && first[kNegativeIndex].serial == 0,
		"each Lua function a plugin pushes carries its plugin's serial, and one pushed with a wrong index carries none");
	Check(LogHas("Plugin Toy Lua pushed a Lua function with plugin index -1"),
		"a Lua function pushed with a wrong index is logged as it is pushed, with the plugin it came from");
	if (first.size() != kPushed)
	{
		CivHostSetLuaPusher(0);
		return;
	}
	int results = 0;
	std::string why;
	Check(Run(first[kTwo], &results, &why) && results == 2, "a plugin's Lua function runs, and how many results it pushed comes back");
	Check(Run(first[kMinusOne], &results, &why) && results == -1,
		"a negative count, such as a coroutine's yield, comes back as it is and is not taken for a refusal");
	Check(Refused(first[kHighIndex], "wrong plugin index") && Refused(first[kNegativeIndex], "wrong plugin index"),
		"a Lua function pushed with a wrong index raises a Lua error that says so");
	Check(JumpsBack(first[kError]) && !IsQuarantined("toy_lua.dll"),
		"a Lua error the plugin raises leaves through the crash guard without being taken for a crash");

	const int faults = FaultCount();
	Check(Refused(first[kCrash], "stopped working in a Lua function"), "a crash in a plugin's Lua function is caught, and Lua gets an error instead");
	Check(IsQuarantined("toy_lua.dll") && FaultCount() == faults + 1 && !LastFaultWhileShuttingDown(),
		"the crash turns the plugin off and is reported as a crash, not one while shutting down");
	Check(Refused(first[kTwo], "turned off after a crash"), "once its plugin is off, a Lua function raises a Lua error instead of running");

	Check(CivHostUnloadPlugins(), "after a Lua error jumped through it, the guard no longer counts a plugin call as running");
	Check(Refused(first[kTwo], "no longer loaded"), "a Lua function whose plugin was unloaded raises a Lua error instead of running");
	const std::vector<Pushed> second = LoadToyLua();
	Check(second.size() == kPushed && Run(second[kTwo], &results, &why) && Refused(first[kTwo], "no longer loaded"),
		"a plugin loaded again gets a new serial, so its old Lua functions still refuse while the new ones run");
	CivHostSetLuaPusher(0);
}
