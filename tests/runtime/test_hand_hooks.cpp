// Hand-placed hooks: the engine's calls into plugins from inside its functions, and the conflicts replacements bring.
#include "harness.h"
#include "CivHostHand.h"
#include "fake_engine.h"

namespace
{
	bool LoggedInOrder(const char* first, const char* second)
	{
		const int a = LogIndex(first);
		return a >= 0 && LogIndex(second) > a;
	}

	bool Contains(const std::string& text, const char* part)
	{
		return text.find(part) != std::string::npos;
	}
}

void TestHandHooks()
{
	StartWithNone();
	Check(!CivHandIsPluginControlledPlayer(3), "with no plugins, a question is answered no");

	const char* const names[] = {"toy_hand.dll", "toy_hand_second.dll"};
	StartWith(names);
	Check(CivHandIsPluginControlledPlayer(3), "a question is answered yes when a plugin says yes");
	Check(LogHas("[Toy Hand] asked about player 3") && !LogHas("[Toy Hand Second] asked about player 3"),
		"the first yes ends the question, so the plugins below it are not asked");
	ClearLog();
	Check(CivHandIsPluginControlledPlayer(5), "a yes from a plugin lower in the list counts too");
	Check(LoggedInOrder("[Toy Hand] asked about player 5", "[Toy Hand Second] asked about player 5"), "plugins are asked in load order");
	ClearLog();
	Check(!CivHandIsPluginControlledPlayer(7), "a question is answered no when every plugin says no");
	Check(LogHas("[Toy Hand Second] asked about player 7"), "every plugin is asked when none says yes");
	FakeUnit unit;
	Check(unit.PlayedByPlugin(3) && !unit.PlayedByPlugin(7), "an engine function asks the plugins through its hand-placed hook");
	Check(CivHandKeepDeadSlotOpen(4) && !CivHandKeepDeadSlotOpen(3), "the dead-slot question gets the answer of the plugin that registered for it");

	ClearLog();
	CivHandPopupRaised(2, 10, 1, -1, 3, true, false, "Found gold");
	Check(LogHas("[Toy Hand] popup 2 10 1 -1 3 1 0 [Found gold]"), "a popup reaches the plugin with all its values");
	std::vector<int> team;
	team.push_back(1);
	team.push_back(6);
	CivHandPopupRaised(team, 11, 0, 0, 0, false, true, 0);
	Check(LogHas("[Toy Hand] popup 1 11 0 0 0 0 1 []") && LogHas("[Toy Hand] popup 6 11 0 0 0 0 1 []"),
		"a popup for a team reaches the plugin once for each of the team's players, and missing text arrives empty");
	CivHandNotificationAdded(1, 7, "A message", "A summary", 4, 5, 6, 8);
	Check(LoggedInOrder("[Toy Hand] notification 1 7 [A message] [A summary] 4 5 6 8", "[Toy Hand Second] notification 1 7 [A message] [A summary] 4 5 6 8"),
		"an announcement reaches every plugin that listens, in load order, with all its values");
	CivHandDealResolved(1, 2, 2, true, false);
	Check(LogHas("[Toy Hand] deal 1 2 2 1 0"), "a resolved deal reaches the plugin with all its values");
	unit.CancelOrders(CIV_ORDERS_NO_PATH);
	Check(LogHas("[Toy Hand] orders cancelled Warrior 4"), "cancelled orders reach the plugin with the unit and the reason");
}

void TestHandHookFaults()
{
	const char* const names[] = {"toy_hand_fault.dll", "toy_hand.dll"};
	StartWith(names);
	const int before = FaultCount();
	Check(CivHandIsPluginControlledPlayer(3), "a plugin that faults while answering counts as a no, and the plugins below it are still asked");
	Check(FaultCount() == before + 1 && IsQuarantined("toy_hand_fault.dll"), "a plugin that faults in a hand-placed hook is quarantined");
	Check(LogHas("Plugin Toy Hand Fault: Faulted (code 0xC0000005) in IsPluginControlledPlayer."), "the log names the hand-placed hook that faulted");
	Check(LogHas("    #00 toy_hand_fault.dll+0x"), "a fault in a hand-placed hook has its call stack logged");
	Check(LogHas("  It wrote to address 0x00000000, at toy_hand_fault.dll+0x"), "a crash that wrote memory says so");
	ClearLog();
	CivHandIsPluginControlledPlayer(3);
	Check(!LogHas("Plugin Toy Hand Fault: Faulted"), "a quarantined plugin is not asked again");
}

void TestPossibleConflicts()
{
	FakeUnit unit;
	const char* const usesFirst[] = {"toy_hand.dll", "toy_hand_replace.dll"};
	StartWith(usesFirst);
	Check(HasStatus("toy_hand_replace.dll", CIV_PLUGIN_POSSIBLE_CONFLICT),
		"a plugin replacing a function that runs a hand-placed hook a plugin higher in the list uses is held back");
	const CivPluginReportRow replacer = ReportRow("toy_hand_replace.dll");
	Check(replacer.failed && Contains(replacer.problems, "This plugin replaces FakeUnit::CancelOrders(...), which runs the UnitOrdersCancelled hook that Toy Hand, higher in the list, uses."),
		"the Plugins screen names the function, the hook and the other plugin");
	Check(replacer.conflictsWith.size() == 1 && replacer.conflictsWith[0] == "toy_hand.dll", "the Plugins screen knows which plugin it conflicts with");
	const CivPluginReportRow user = ReportRow("toy_hand.dll");
	Check(!user.failed && user.problems.empty() && user.conflictsWith.empty(), "the plugin higher in the list loads with no warning");
	ClearLog();
	unit.CancelOrders(CIV_ORDERS_NO_PATH);
	Check(unit.m_notified == CIV_ORDERS_NO_PATH && LogHas("[Toy Hand] orders cancelled"), "the held-back replacement does not run, so the hook inside the original does");

	const char* const replacesFirst[] = {"toy_hand_replace.dll", "toy_hand.dll"};
	StartWith(replacesFirst);
	Check(HasStatus("toy_hand.dll", CIV_PLUGIN_POSSIBLE_CONFLICT),
		"a plugin using a hand-placed hook inside a function a plugin higher in the list replaces is held back");
	Check(Contains(ReportRow("toy_hand.dll").problems, "Toy Hand Replace, higher in the list, replaces FakeUnit::CancelOrders(...), which runs the UnitOrdersCancelled hook this plugin uses."),
		"the Plugins screen names the plugin higher in the list that replaces the function");
	Check(HasStatus("toy_hand_replace.dll", CIV_PLUGIN_LOADED), "the replacing plugin higher in the list loads");

	const char* const alone[] = {"toy_hand_replace.dll"};
	StartWith(alone);
	Check(HasStatus("toy_hand_replace.dll", CIV_PLUGIN_LOADED) && ReportRow("toy_hand_replace.dll").conflictsWith.empty(),
		"a plugin that replaces a function and uses the hook inside it itself is not held back");

	const char* const unrelated[] = {"toy_hand.dll", "toy_second.dll"};
	StartWith(unrelated);
	Check(HasStatus("toy_second.dll", CIV_PLUGIN_LOADED) && ReportRow("toy_second.dll").conflictsWith.empty(),
		"replacing functions with no hand-placed hook inside is no conflict");

	// toy_hand_replace also replaces Range, which toy_bad_hooks already replaces.
	const char* const refused[] = {"toy_bad_hooks.dll", "toy_hand.dll", "toy_hand_replace.dll"};
	StartWith(refused);
	const CivPluginReportRow clash = ReportRow("toy_hand_replace.dll");
	Check(HasStatus("toy_hand_replace.dll", CIV_PLUGIN_REPLACE_CONFLICT) && clash.conflictsWith.empty() && !Contains(clash.problems, "Use both anyway"),
		"a plugin turned off for another reason is not offered Use both anyway");

	StartWithNone();
	const std::vector<std::string> paths = OutFiles(usesFirst);
	CivHostSetPlugins(paths, CivFilePairs(1, CivFilePair("TOY_HAND_REPLACE.DLL", "toy_hand.dll")));
	Check(HasStatus("toy_hand_replace.dll", CIV_PLUGIN_LOADED) && HasStatus("toy_hand.dll", CIV_PLUGIN_LOADED),
		"a pair the player chose to use anyway loads together, matched in any case");
	const CivPluginReportRow chosen = ReportRow("toy_hand_replace.dll");
	Check(!chosen.failed && Contains(chosen.problems, "You chose to use this plugin with Toy Hand anyway"), "the Plugins screen says the pair was loaded together by choice");
	Check(chosen.conflictsWith.size() == 1, "the Plugins screen can still offer to take the choice back");
	const CivPluginRecord* record = Find("toy_hand_replace.dll");
	Check(record && record->problems.empty() && record->notes.size() == 1, "the choice is a note for the Plugins screen, not a problem announced in the game");
	ClearLog();
	unit.CancelOrders(CIV_ORDERS_NO_PATH);
	Check(unit.m_notified == -1 && !LogHas("[Toy Hand] orders cancelled"), "with both loaded, the replacement runs and the hook inside the original does not");
	CivHostSetPlugins(paths, CivFilePairs(1, CivFilePair("toy_hand.dll", "toy_hand_replace.dll")));
	Check(HasStatus("toy_hand_replace.dll", CIV_PLUGIN_LOADED), "a pair also loads together when the choice names the held-back plugin second");
	Check(CivHostSetPlugins(paths) == CIV_PLUGINS_CHANGED && HasStatus("toy_hand_replace.dll", CIV_PLUGIN_POSSIBLE_CONFLICT),
		"taking the choice back reloads the plugins although the list is the same, and the pair is held back again");
	Check(CivHostSetPlugins(paths) == CIV_PLUGINS_UNCHANGED, "the same list with the same choices changes nothing");
}

void TestSkippedOriginal()
{
	const char* const names[] = {"toy_hand_replace.dll", "toy_second.dll"};
	StartWith(names);
	FakeUnit unit;
	unit.CancelOrders(1);
	Check(LogHas("Plugin Toy Hand Replace: its replacement of FakeUnit::CancelOrders(int) returned without running the original"),
		"a replacement that returns without running the original is logged, with the plugin and the function");
	ClearLog();
	unit.CancelOrders(1);
	Check(!LogHas("returned without running the original"), "it is logged only the first time");
	Check(unit.Subtract(7, 2) == 50 && !LogHas("returned without running the original"), "a replacement that runs the original is not logged");
	Check(unit.Range() == 131, "a replacement's original runs the replacement of a function it calls");
	Check(LogHas("its replacement of FakeUnit::Reach() const returned without") && !LogHas("its replacement of FakeUnit::Range() const returned without"),
		"a replacement inside the original that skips its own original does not make the outer replacement look like it skipped");
}
