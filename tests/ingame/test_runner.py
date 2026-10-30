"""Tests for the checks runner: reading a checks file, choosing the mods a check needs, and playing its steps against a
game whose answers a test sets up."""

import contextlib
import inspect
import io
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from fakes import HERE, use_own_temp, write_mod

from bazaar_check import CheckError, files, game, runner, tuner

REPO = os.path.join(HERE, "..", "..")

ONE_OF_EACH = {
    "start_game": {"start_game": "duel"},
    "end_turns": {"end_turns": 1},
    "save": {"save": "a"},
    "load": {"load": "a"},
    "main_menu": {"main_menu": True},
    "lua": {"lua": "true"},
    "run": {"run": "x = 1"},
    "log": {"log": "Bazaar.log", "has": "x"},
    "plugin": {"plugin": "A.dll"},
    "description_of": {"description_of": "id", "version": 1, "is": "x"},
    "mark": {"mark": "a"},
    "hand_over": {"hand_over": "Look around."},
}


class FakeGame:
    """Stands in for game.py's Game as the runner uses it, over a real player's folder. Each of its methods is one Game
    has, which a test checks."""

    def __init__(
        self,
        user,
        installed,
        enabled=(),
        logs=None,
        answers=None,
        plugins=(),
        description=None,
        closed_at_hand_over=False,
    ):
        self.files = files.PlayerFiles(user)
        self.installed = list(installed)
        self.enabled = set(enabled)
        self.logs = logs or {}
        self.answers = answers or {}
        self.plugin_rows = list(plugins)
        self.description = description
        self.closed_at_hand_over = closed_at_hand_over
        self.said = []
        self.say = self.said.append
        self.steps = []

    def wait(self, what, ready, timeout):
        """Asks up to timeout times, with no real waiting."""
        for _ in range(timeout):
            if ready():
                return
        raise CheckError("%s did not happen" % what)

    def mods(self, enabled_only=True):
        return [(m, v, name) for m, v, name in self.installed if not enabled_only or (m, v) in self.enabled]

    def set_mods(self, wanted):
        self.steps.append(("set_mods", wanted))
        self.enabled = set(wanted)

    def activate(self):
        """Keeps the plugin order as it stood when Bazaar loaded the plugins."""
        self.steps.append(("activate",))
        path = self.files.path(files.ORDER_FILE)
        if os.path.exists(path):
            with open(path, "rb") as f:
                self.order_at_activate = f.read()

    def start_game(self, timeout=300):
        self.steps.append(("start_game",))

    def end_turn(self, timeout=180):
        self.steps.append(("end_turn",))

    def save(self, name, timeout=60):
        self.steps.append(("save", name))

    def load(self, name, timeout=300):
        self.steps.append(("load", name))

    def to_main_menu(self, timeout=180):
        self.steps.append(("to_main_menu",))

    def hand_over(self, message):
        self.steps.append(("hand_over", message))
        if self.closed_at_hand_over:
            raise game.GameClosed(game.CLOSED_DURING_HAND_OVER)

    def lua(self, state, code, timeout=30):
        """Code "--log NAME: LINE" writes LINE to the log NAME, as a plugin would."""
        self.steps.append(("lua", state, code))
        if code.startswith("--log "):
            name, line = code[len("--log ") :].split(": ", 1)
            self.logs.setdefault(name, []).append(line)
        return []

    def text(self, state, expression, timeout=30):
        """A list of answers gives one per question, then repeats the last."""
        answer = self.answers.get(expression, "true")
        if isinstance(answer, str):
            return answer
        return answer.pop(0) if len(answer) > 1 else answer[0]

    def plugins(self):
        return self.plugin_rows

    def mod_description(self, mod_id, version):
        return self.description

    def log(self, name="Bazaar.log"):
        return list(self.logs.get(name, []))


class FolderTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        use_own_temp(self)
        os.makedirs(self.path("MODS"))

    def path(self, *parts):
        return os.path.join(self.root, *parts)


class ReadChecksTest(FolderTest):
    def read(self, text):
        path = self.path("checks.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return runner.read_checks(path)

    def refused(self, text, why):
        with self.assertRaisesRegex(CheckError, why):
            self.read(text)

    def test_a_checks_file_gives_its_mods_from_its_own_folder_and_its_steps(self):
        checks = self.read(
            'mods = ["Build/My Plugin (v 1)", "../Bazaar.civ5mod"]\n'
            'plugin_order = ["MyPlugin.dll", {file = "Other.dll", skip = true}]\n'
            '[[steps]]\nstart_game = "duel"\n'
            "[[steps]]\nend_turns = 2\n"
            '[[steps]]\nlog = "Bazaar.log"\nhas = "^Plugin My Plugin .+ loaded"\nwhat = "My Plugin loaded"\n'
        )
        self.assertEqual(
            checks.mods, [self.path("Build", "My Plugin (v 1)"), os.path.normpath(self.path("..", "Bazaar.civ5mod"))]
        )
        self.assertEqual(checks.plugin_order, ["MyPlugin.dll", {"file": "Other.dll", "skip": True}])
        self.assertEqual([runner.kind_of(step) for step in checks.steps], ["start_game", "end_turns", "log"])
        self.assertEqual((checks.crash_expected, checks.lua_errors_expected), (False, False))

    def test_settings_it_does_not_know_or_of_the_wrong_kind_are_named(self):
        self.refused('mods = ["a"]\nplugin_ordre = []\n', "a setting the checks do not know: plugin_ordre")
        self.refused('mods = "a"\n', "mods needs a list")
        self.refused('mods = ["a"]\ncrash_expected = "yes"\n', "crash_expected needs true or false or a list")
        self.refused('mods = ["a"]\ncrash_expected = [1]\n', "crash_expected needs true, false, or a list of plugin")
        self.assertEqual(self.read('mods = ["a"]\ncrash_expected = ["Toy Crash"]\n').crash_expected, ["Toy Crash"])
        self.refused('mods = ["a"]\nseed = -1\n', "seed needs a whole number from 0 to 2147483647")
        self.refused('mods = ["a"]\nseed = 2147483648\n', "seed needs a whole number from 0 to 2147483647")
        self.refused('mods = ["a"]\nseed = "random"\n', "seed needs a whole number")
        self.assertEqual(self.read('mods = ["a"]\nseed = 0\n').seed, 0)
        self.assertEqual(self.read('mods = ["a"]\n').seed, runner.DEFAULT_SEED)
        self.refused("mods = [1]\n", "mods needs a list of folders and packages")
        self.refused("mods = []\n", "checks.toml: the checks name no mods")
        self.refused('[[steps]]\nstart_game = "duel"\n', "checks.toml: the checks name no mods")
        self.refused("mods = [\n", "could not be read")
        self.refused(
            'mods = ["a"]\nplugin_order = ["A.dll", {file = "B.dll", use_both_with = "C.dll"}]\n',
            "plugin_order entry 2: use_both_with is not a list of DLL names",
        )

    def test_steps_that_cannot_run_are_named_by_number(self):
        cases = [
            ('[[steps]]\nstart_game = "duel"\n[[steps]]\nsave = 1\n', "step 2 \\(save\\): save needs text"),
            ("[[steps]]\nend_turns = true\n", "end_turns needs a whole number"),
            ('[[steps]]\nsave = "a"\nload = "a"\n', "step 1 must do one of"),
            ('[[steps]]\nwait = "a"\n', "step 1 must do one of"),
            ('[[steps]]\nlog = "Bazaar.log"\n', "needs has or lacks, not both"),
            ('[[steps]]\nlog = "Bazaar.log"\nhas = "a"\nlacks = "b"\n', "needs has or lacks, not both"),
            ('[[steps]]\nlog = "Bazaar.log"\nhas = "("\n', "has pattern Python cannot read"),
            ('[[steps]]\nlua = "true"\nstat = "InGame"\n', "does not take stat"),
            ('[[steps]]\nrun = "x = 1"\nwhat = "x"\n', "does not take what"),
            ('[[steps]]\ndescription_of = "id"\nversion = 1\n', "description_of\\) needs is"),
            ('[[steps]]\nstart_game = "huge"\n', 'can only start a "duel" game'),
            ("[[steps]]\nend_turns = 0\n", "needs 1 or more"),
            ("[[steps]]\nmain_menu = false\n", "main_menu\\) needs true"),
            ('[[steps]]\nlog = "Bazaar.log"\nlacks = "a"\ncount = 1\n', "takes count only with has"),
            ('[[steps]]\nlog = "Bazaar.log"\nhas = "a"\ncount = 0\n', "and needs 1 or more"),
            (
                '[[steps]]\nlog = "Bazaar.log"\nhas = "a"\nsince = "load"\n',
                'step 1 \\(log\\): no step before it marks "load"',
            ),
            ('[[steps]]\nlua = "x"\nhas = "("\n', "has pattern Python cannot read"),
            ('[[steps]]\nlua = "x"\nwithin = 0\n', "within needs 1 or more seconds"),
            ('[[steps]]\nplugin = "A.dll"\nstatus = "Not Loaded"\n', 'step 1 \\(plugin\\): status is one of "Loaded"'),
            ('[[steps]]\nlog = "Bazaar.log"\nlacks = "x"\nwithin = 5\n', "within waits for a line to appear"),
            ('[[steps]]\nsave = "a/b"\n', "step 1 \\(save\\) needs a name that can be a file name"),
            ('[[steps]]\nload = " . "\n', "step 1 \\(load\\) needs a name that can be a file name"),
            ('[[steps]]\nhand_over = " "\n', "step 1 \\(hand_over\\) needs text saying what to do with the game"),
        ]
        for steps, why in cases:
            with self.subTest(steps=steps):
                self.refused('mods = ["a"]\n' + steps, why)


class DependenciesTest(FolderTest):
    def test_the_newest_installed_version_in_range_is_chosen_and_its_own_needs_followed(self):
        plugin = write_mod(self.path("build", "Plugin"), "plugin", dependencies=[("bazaar", "Bazaar")])
        write_mod(self.path("MODS", "Bazaar (v 7)"), "bazaar", 7, dependencies=[("vmc", "VMC", 97)])
        installed = [
            ("plugin", 1, "Plugin"),
            ("bazaar", 6, "B"),
            ("bazaar", 7, "B"),
            ("vmc", 97, "V"),
            ("vmc", 98, "V"),
        ]
        wanted = runner.dependencies([plugin], installed, self.path("MODS"))
        self.assertEqual(wanted, [("plugin", 1), ("bazaar", 7), ("vmc", 97)])

    def test_a_checked_mod_meets_another_s_need_itself_if_its_version_is_in_range(self):
        bazaar = write_mod(self.path("build", "Bazaar"), "bazaar", files.TEST_VERSION)
        plugin = write_mod(self.path("build", "Plugin"), "plugin", dependencies=[("bazaar", "Bazaar")])
        installed = [("bazaar", 7, "B"), ("bazaar", files.TEST_VERSION, "B"), ("plugin", 1, "P")]
        wanted = runner.dependencies([bazaar, plugin], installed, self.path("MODS"))
        self.assertEqual(wanted, [("bazaar", files.TEST_VERSION), ("plugin", 1)])
        pinned = write_mod(
            self.path("build", "Pinned"), "pinned", name="Pinned", dependencies=[("bazaar", "Bazaar", 7)]
        )
        with self.assertRaisesRegex(
            CheckError, "^Pinned needs Bazaar, version 7, but the checks file lists version 900$"
        ):
            runner.dependencies([bazaar, pinned], installed, self.path("MODS"))

    def test_a_test_build_is_chosen_only_when_the_checks_file_lists_it(self):
        plugin = write_mod(
            self.path("build", "Plugin"), "plugin", name="My Plugin", dependencies=[("bazaar", "Bazaar")]
        )
        installed = [("bazaar", 5, "B"), ("bazaar", files.TEST_VERSION, "B"), ("bazaar", 999, "B"), ("plugin", 1, "P")]
        self.assertEqual(runner.dependencies([plugin], installed, self.path("MODS")), [("plugin", 1), ("bazaar", 5)])
        with self.assertRaisesRegex(
            CheckError,
            "which is not installed \\(only a version of 900 or above is, which counts as a test build: list",
        ):
            runner.dependencies([plugin], installed[1:3], self.path("MODS"))

    def test_a_need_nothing_installed_meets_is_named(self):
        plugin = write_mod(self.path("build", "Plugin"), "plugin", name="My Plugin", dependencies=[("vmc", "VMC", 97)])
        with self.assertRaisesRegex(CheckError, "^My Plugin needs VMC, version 97, which is not installed$"):
            runner.dependencies([plugin], [("vmc", 96, "V")], self.path("MODS"))
        any_version = write_mod(self.path("build", "Any"), "any", name="Any", dependencies=[("vmc", "VMC")])
        with self.assertRaisesRegex(CheckError, "^Any needs VMC, any version, which is not installed$"):
            runner.dependencies([any_version], [], self.path("MODS"))

    def test_the_newest_version_every_need_allows_is_chosen(self):
        first = write_mod(self.path("build", "First"), "first", dependencies=[("c", "C")])
        second = write_mod(self.path("build", "Second"), "second", name="Second", dependencies=[("c", "C", 3)])
        installed = [("c", 3, "C"), ("c", 5, "C")]
        wanted = runner.dependencies([second, first], installed, self.path("MODS"))
        self.assertEqual(wanted, [("second", 1), ("first", 1), ("c", 3)])
        with self.assertRaisesRegex(CheckError, "Second needs C, version 3, and another mod needs any version; no"):
            runner.dependencies([second, first], installed[1:], self.path("MODS"))

    def test_two_versions_of_one_mod_are_refused(self):
        old = write_mod(self.path("build", "Old"), "bazaar", 6, name="Bazaar")
        new = write_mod(self.path("build", "New"), "bazaar", files.TEST_VERSION, name="Bazaar")
        with self.assertRaisesRegex(CheckError, "mods lists two versions of Bazaar \\(6 and 900\\): keep one"):
            runner.dependencies([old, new], [], self.path("MODS"))


class PlayTest(FolderTest):
    def setUp(self):
        super().setUp()
        self.plugin = write_mod(self.path("build", "Plugin"), "plugin", name="Plugin", dependencies=[("bazaar", "B")])
        shutil.copytree(self.plugin, self.path("MODS", "Plugin"))
        write_mod(self.path("MODS", "Bazaar (v 7)"), "bazaar", 7)
        self.installed = [("plugin", 1, "Plugin"), ("bazaar", 7, "Bazaar"), ("player-mod", 2, "Player Mod")]

    def play(self, steps=(), crash_expected=False, lua_errors_expected=False, **fake):
        g = FakeGame(self.root, self.installed, **fake)
        checks = runner.Checks([self.plugin], [], list(steps), crash_expected, lua_errors_expected)
        results = []
        runner.play_steps(checks, g, [self.plugin], results)
        results.extend(runner.final_checks(checks, g))
        return g, results

    def test_the_plugin_order_is_written_before_bazaar_loads_the_plugins(self):
        g = FakeGame(self.root, self.installed)
        runner.play_steps(runner.Checks([self.plugin], ["A.dll"]), g, [self.plugin], [])
        self.assertEqual(g.order_at_activate, b"load\tA.dll\t\t\r\n")

    def test_every_method_of_the_fake_is_one_the_game_has_called_the_same_way(self):
        methods = [name for name, value in vars(FakeGame).items() if callable(value) and not name.startswith("_")]
        self.assertIn("end_turn", methods)
        for name in methods:
            fake = list(inspect.signature(getattr(FakeGame, name)).parameters.values())
            real = list(inspect.signature(getattr(game.Game, name)).parameters.values())
            self.assertEqual([p.name for p in real[: len(fake)]], [p.name for p in fake], name)
            self.assertTrue(all(p.default is not p.empty for p in real[len(fake) :]), name)

    def test_every_kind_of_step_is_one_the_runner_does(self):
        self.assertEqual(set(ONE_OF_EACH), set(runner.STEPS))
        for kind, step in ONE_OF_EACH.items():
            with self.subTest(kind=kind):
                runner.validate(runner.Checks(["a"], steps=[step]))
                runner.do_step(FakeGame(self.root, self.installed), step, [], runner.Marks([step]))

    def test_the_mods_and_what_they_need_are_chosen_then_the_steps_run_in_order(self):
        steps = [{"start_game": "duel"}, {"end_turns": 2}, {"save": "a"}, {"main_menu": True}, {"load": "a"}]
        steps.append({"run": "Game.SetGold(1)"})
        g, results = self.play(steps)
        self.assertEqual(g.steps[0], ("set_mods", [("plugin", 1), ("bazaar", 7)]))
        self.assertEqual(
            [s[0] for s in g.steps[1:]],
            ["activate", "start_game", "end_turn", "end_turn", "save", "to_main_menu", "load", "lua"],
        )
        self.assertEqual(g.steps[-1], ("lua", game.IN_GAME, "Game.SetGold(1)"))
        self.assertEqual(g.said, ["choosing Plugin (v 1), Bazaar (v 7)"])
        self.assertEqual([r.what for r in results], ["no plugin stopped working", "Lua.log has no Lua errors"])
        self.assertTrue(all(r.passed for r in results))
        with open(self.path(files.ORDER_FILE), "rb") as f:
            self.assertEqual(f.read(), b"")

    def test_the_steps_after_a_hand_over_run_once_the_game_is_back(self):
        g, results = self.play([{"start_game": "duel"}, {"hand_over": "Look around."}, {"run": "x = 1"}])
        self.assertEqual(
            [s[:2] for s in g.steps[2:]], [("start_game",), ("hand_over", "Look around."), ("lua", game.IN_GAME)]
        )
        self.assertTrue(all(r.passed for r in results))

    def test_closing_the_game_during_the_last_hand_over_ends_the_run_as_closing_play_cmd_does(self):
        _, results = self.play([{"start_game": "duel"}, {"hand_over": "Play."}], closed_at_hand_over=True)
        self.assertEqual([r.what for r in results], ["no plugin stopped working", "Lua.log has no Lua errors"])

    def test_closing_the_game_during_a_hand_over_with_steps_after_it_says_they_did_not_run(self):
        steps = [{"hand_over": "Play."}, {"lua": "true"}]
        with self.assertRaisesRegex(game.GameClosed, "during the hand-over, so the steps after it did not run"):
            self.play(steps, closed_at_hand_over=True)

    def test_closing_the_game_during_any_other_last_step_still_ends_the_run(self):
        g = FakeGame(self.root, self.installed)
        g.end_turn = mock.Mock(side_effect=game.GameClosed("Civilization V closed while waiting for the turn"))
        checks = runner.Checks([self.plugin], [], [{"start_game": "duel"}, {"end_turns": 1}])
        with self.assertRaisesRegex(game.GameClosed, "while waiting for the turn"):
            runner.play_steps(checks, g, [self.plugin], [])

    def test_a_mod_the_game_never_lists_stops(self):
        self.installed = self.installed[1:]
        with self.assertRaisesRegex(CheckError, "the game listing the mods did not happen"):
            self.play()

    def test_another_copy_in_mods_stops_before_anything_is_switched_on(self):
        shutil.copytree(self.plugin, self.path("MODS", "Plugin copy"))
        with self.assertRaisesRegex(CheckError, "MODS holds 2 copies of Plugin \\(v 1\\)"):
            self.play()

    def test_lua_checks_pass_on_anything_but_false_or_nil(self):
        steps = [{"lua": "a"}, {"lua": "b", "state": "MainMenu"}, {"lua": "c"}]
        _, results = self.play(steps, answers={"a": "3", "b": "false", "c": "nil"})
        self.assertEqual([r.passed for r in results[:3]], [True, False, False])
        self.assertEqual((results[1].what, results[1].found), ("MainMenu: b", "it gave false"))

    def test_a_lua_error_or_a_missing_state_fails_its_check_and_the_run_goes_on(self):
        g = FakeGame(self.root, self.installed)
        errors = {
            "bad": tuner.LuaError("[string]:1: attempt to call a nil value"),
            "gone": tuner.NoSuchState("the game has no Lua state named BazaarStopped"),
        }

        def text(state, expression, timeout=30):
            if expression in errors:
                raise errors[expression]
            return "true"

        g.text = text
        results = []
        for step in ({"lua": "bad"}, {"lua": "gone", "state": "BazaarStopped"}, {"lua": "fine"}):
            runner.do_step(g, step, results, runner.Marks([]))
        self.assertEqual(
            [(r.passed, r.found) for r in results],
            [(False, str(errors["bad"])), (False, str(errors["gone"])), (True, "it gave true")],
        )

    def test_a_check_s_name_is_what_its_result_says(self):
        steps = [
            {"lua": "a", "what": "the gold is right"},
            {"log": "Bazaar.log", "has": "x", "what": "the plugin said x"},
            {"plugin": "A.dll", "what": "A is on the Plugins screen"},
            {"description_of": "bazaar", "version": 7, "is": "x", "what": "Bazaar describes itself"},
        ]
        _, results = self.play(steps)
        self.assertEqual(
            [r.what for r in results[:4]],
            ["the gold is right", "the plugin said x", "A is on the Plugins screen", "Bazaar describes itself"],
        )

    def test_log_checks_find_or_miss_a_line(self):
        log = ["Plugin Plugin 1 loaded (built for API 0.6).", "[Plugin] turn 1"]
        steps = [
            {"log": "Bazaar.log", "has": r"loaded \(built for API 0\.6\)"},
            {"log": "Bazaar.log", "has": "turn 2"},
            {"log": "Bazaar.log", "lacks": "turn 1"},
        ]
        _, results = self.play(steps, logs={"Bazaar.log": log})
        self.assertEqual([r.passed for r in results[:3]], [True, False, False])
        self.assertEqual(results[1].found, "Bazaar.log has no such line")
        self.assertEqual(results[2].found, "it has: [Plugin] turn 1")

    def test_a_log_check_since_a_mark_sees_only_the_lines_after_it(self):
        steps = [
            {"run": "--log Bazaar.log: loaded: 3 turns"},
            {"mark": "before load"},
            {"log": "Bazaar.log", "has": "loaded: 3 turns", "since": "before load"},
            {"run": "--log Bazaar.log: loaded: 3 turns"},
            {"log": "Bazaar.log", "has": "loaded: 3 turns", "since": "before load"},
            {"log": "Bazaar.log", "has": "loaded: 3 turns", "count": 2},
            {"log": "Bazaar.log", "has": "loaded", "count": 1},
        ]
        _, results = self.play(steps)
        self.assertEqual([r.passed for r in results[:4]], [False, True, True, False])
        self.assertEqual(results[3].found, "it has it 2 times")

    def test_a_lua_check_can_look_for_text_in_its_value(self):
        steps = [{"lua": "a", "has": "stopped working"}, {"lua": "b", "has": "stopped working"}]
        answers = {"a": "false\tToy Crash stopped working in a Lua function", "b": "true"}
        _, results = self.play(steps, answers=answers)
        self.assertEqual([r.passed for r in results[:2]], [True, False])
        self.assertEqual(results[1].found, "it gave true")

    def test_a_log_check_within_some_seconds_reads_the_log_until_it_passes(self):
        g = FakeGame(self.root, self.installed)
        reads = []

        def log(name="Bazaar.log"):
            reads.append(name)
            return ["Plugin Plugin unloaded."] if len(reads) >= 3 else []

        g.log = log
        step = {"log": "Bazaar.log", "has": "unloaded", "within": 30}
        self.assertTrue(runner.log_step(g, step, runner.Marks([step])).passed)
        reads.clear()
        late = runner.log_step(g, dict(step, within=2), runner.Marks([step]))
        self.assertEqual((late.passed, late.found), (False, "Bazaar.log has no such line"))

    def test_a_game_that_closes_during_a_wait_ends_the_run(self):
        g = FakeGame(self.root, self.installed)
        g.wait = mock.Mock(side_effect=game.GameClosed("Civilization V closed while waiting"))
        for step in ({"lua": "shown", "within": 30}, {"log": "Bazaar.log", "has": "x", "within": 30}):
            with self.subTest(step=step), self.assertRaises(game.GameClosed):
                runner.do_step(g, step, [], runner.Marks([step]))

    def test_a_game_that_never_answers_within_the_time_names_the_wait(self):
        g = FakeGame(self.root, self.installed)
        g.wait = mock.Mock(side_effect=CheckError("Bazaar's pop-up did not happen within 30 seconds"))
        result = runner.lua_check(g, {"lua": "shown", "within": 30, "what": "Bazaar's pop-up"})
        self.assertEqual(
            result, runner.Result("Bazaar's pop-up", False, "Bazaar's pop-up did not happen within 30 seconds")
        )

    def test_a_lua_check_within_some_seconds_asks_until_it_passes(self):
        steps = [
            {"lua": "shown", "within": 30},
            {"lua": "late", "within": 2},
            {"lua": "now"},
        ]
        answers = {"shown": ["false", "false", "true"], "late": ["false", "false", "true"], "now": ["false", "true"]}
        _, results = self.play(steps, answers=answers)
        self.assertEqual([r.passed for r in results[:3]], [True, False, False])
        self.assertEqual(results[1].found, "it gave false")

    def test_plugin_checks_compare_the_status_and_the_problems(self):
        rows = [("Plugin.dll", "Loaded", ""), ("Other.dll", "Not loaded", "It needs API 0.7.")]
        steps = [
            {"plugin": "plugin.dll", "status": "Loaded"},
            {"plugin": "Other.dll", "status": "Not loaded", "problems": "needs API"},
            {"plugin": "Other.dll", "status": "Loaded"},
            {"plugin": "Missing.dll"},
        ]
        _, results = self.play(steps, plugins=rows)
        self.assertEqual([r.passed for r in results[:4]], [True, True, False, False])
        self.assertEqual(results[2].found, "it shows Not loaded: It needs API 0.7.")
        self.assertEqual(
            results[1].what, "the Plugins screen shows Other.dll as Not loaded with a problem matching needs API"
        )
        self.assertEqual(results[3].found, "it does not list Missing.dll")
        self.assertEqual(results[3].what, "the Plugins screen lists Missing.dll")

    def test_a_description_must_match_whole(self):
        step = {"description_of": "bazaar", "version": 7, "is": "Bazaar 0.6.0."}
        for description, passed in (("Bazaar 0.6.0.\n", True), ("Bazaar 0.5.0.", False), (None, False)):
            with self.subTest(description=description):
                _, results = self.play([step], description=description)
                self.assertEqual(results[0].passed, passed)

    def test_a_crash_or_a_lua_error_fails_unless_the_file_expects_one(self):
        logs = {
            "Bazaar.log": ["Plugin Toy Fault: Faulted (code 0xC0000005) in CvPlayer::doTurn."],
            "Lua.log": ["[1234.5] Runtime Error: Assets\\UI\\InGame\\TopPanel.lua:12: attempt to index a nil value"],
        }
        _, results = self.play(logs=logs)
        self.assertEqual([r.passed for r in results], [False, False])
        self.assertIn("Faulted", results[0].found)
        _, results = self.play(logs=logs, crash_expected=True, lua_errors_expected=True)
        self.assertEqual(results, [])

    def test_only_the_plugins_a_file_expects_to_crash_may(self):
        crashes = ["Plugin Toy Crash: Faulted (code 0xC0000005) in CvPlayer::doTurn."]
        logs = {"Bazaar.log": crashes + ["Plugin Toy Gold: It stopped working while loading (code 0xC0000005)."]}
        _, results = self.play(logs={"Bazaar.log": crashes}, crash_expected=["Toy Crash"])
        self.assertEqual((results[0].what, results[0].passed), ("no plugin other than Toy Crash stopped working", True))
        _, results = self.play(logs=logs, crash_expected=["Toy Crash"])
        self.assertFalse(results[0].passed)
        self.assertIn("Toy Gold", results[0].found)

    def test_a_plugin_s_own_words_are_not_a_crash(self):
        _, results = self.play(logs={"Bazaar.log": ["[Timer Plugin] the watchdog stopped working, so it restarted"]})
        self.assertTrue(results[0].passed)


class RunChecksTest(FolderTest):
    def run_checks(self, play):
        """The order run_checks did things in, and the staging folder it used."""
        g = mock.create_autospec(game.Game, instance=True)
        g.files = mock.create_autospec(files.PlayerFiles, instance=True)
        done, staging = [], []
        g.preflight.side_effect = lambda: done.append("preflight")

        def stage_all(sources, folder):
            done.append("stage")
            staging.append(folder)
            return [("staged", "target")]

        @contextlib.contextmanager
        def session(game, seed, staged, saves, windowed):
            done.append("session with seed %d and saves %s%s" % (seed, saves, ", windowed" if windowed else ""))
            yield ["expected"]
            done.append("game closed")

        g.files.stage_all.side_effect = stage_all

        def put_back_leftovers():
            with self.assertRaisesRegex(CheckError, "another check is running"):
                with files.one_run_at_a_time():
                    pass
            done.append("leftovers put back")

        g.files.put_back_leftovers.side_effect = put_back_leftovers
        g.log.side_effect = lambda name="Bazaar.log": done.append("read " + name) or []
        with mock.patch.object(game, "session", session), mock.patch.object(runner, "play_steps", side_effect=play):
            try:
                runner.run_checks(runner.Checks(["a"], steps=[{"save": "Kept"}]), g, [])
            finally:
                self.done, self.staging = done, staging[0] if staging else None

    def test_an_earlier_check_s_copies_go_back_before_the_mods_are_staged_with_the_game_closed(self):
        self.run_checks(lambda checks, g, expected, results: None)
        self.assertEqual(
            self.done[:4],
            [
                "preflight",
                "leftovers put back",
                "stage",
                "session with seed %d and saves ['Kept'], windowed" % runner.DEFAULT_SEED,
            ],
        )
        self.assertFalse(os.path.exists(self.staging))

    def test_crashes_and_lua_errors_are_read_once_the_game_has_closed(self):
        self.run_checks(lambda checks, g, expected, results: None)
        self.assertEqual(self.done[4:], ["game closed", "read Bazaar.log", "read Lua.log"])

    def test_the_staging_folder_goes_even_when_a_check_fails(self):
        with self.assertRaises(CheckError):
            self.run_checks(mock.Mock(side_effect=CheckError("turn 1 cannot end")))
        self.assertFalse(os.path.exists(self.staging))


class PlayByHandTest(FolderTest):
    def play_by_hand(self, until_closed):
        """What play_by_hand returned, with wait_until_closed doing until_closed; self.done is the order it went in."""
        g = mock.create_autospec(game.Game, instance=True)
        g.files = mock.create_autospec(files.PlayerFiles, instance=True)
        done = self.done = []
        g.preflight.side_effect = lambda: done.append("preflight")
        g.files.put_back_leftovers.side_effect = lambda: done.append("leftovers put back")
        g.files.stage_all.return_value = [("staged", "target")]
        g.handed_over = False
        g.wait_until_closed.side_effect = lambda: until_closed(g)
        g.say = lambda text: None

        @contextlib.contextmanager
        def session(game, seed=None, staged=(), saves=(), windowed=False):
            done.append("session with seed %s, %s, windowed %s" % (seed, staged, windowed))
            try:
                yield ["expected"]
            finally:
                done.append("everything put back")

        def switch_on(checks, g, expected):
            done.append("switched on %s" % expected)

        with mock.patch.object(game, "session", session), mock.patch.object(runner, "switch_on", side_effect=switch_on):
            return runner.play_by_hand(runner.Checks(["a"]), g)

    def test_the_mods_are_switched_on_then_the_game_is_left_to_the_player_until_it_closes(self):
        self.assertIsNone(self.play_by_hand(lambda g: self.done.append("played until closed")))
        self.assertEqual(
            self.done,
            [
                "preflight",
                "leftovers put back",
                "session with seed None, [('staged', 'target')], windowed False",
                "switched on ['expected']",
                "played until closed",
                "everything put back",
            ],
        )

    def test_stopping_with_the_game_open_says_the_next_run_puts_the_files_back(self):
        def handed_over_then_stopped(g):
            g.handed_over = True
            raise KeyboardInterrupt

        stopped = self.play_by_hand(handed_over_then_stopped)
        self.assertEqual(
            stopped, "stopped with the game still open: the next run of check.cmd or play.cmd puts your files back"
        )
        self.assertEqual(self.done[-1], "everything put back")

    def test_stopping_before_the_game_is_handed_over_says_only_that(self):
        self.assertEqual(self.play_by_hand(mock.Mock(side_effect=KeyboardInterrupt)), "stopped")

    def test_a_problem_says_why_playing_stopped(self):
        stopped = self.play_by_hand(mock.Mock(side_effect=CheckError("Civilization V closed while starting")))
        self.assertEqual(stopped, "stopped: Civilization V closed while starting")

    def test_main_plays_by_hand_and_says_why_playing_stopped(self):
        path = os.path.join(self.root, "checks.toml")
        with open(path, "w") as f:
            f.write('mods = ["a"]\n')
        for stopped, code, printed_line in ((None, 0, ""), ("stopped", 1, "Playing stopped\n")):
            with self.subTest(stopped=stopped):
                printed = io.StringIO()
                with (
                    mock.patch.object(game, "Game"),
                    mock.patch.object(runner, "play_by_hand", return_value=stopped) as play,
                    contextlib.redirect_stdout(printed),
                ):
                    self.assertEqual(runner.main(["--play", path]), code)
                self.assertEqual(play.call_args[0][0].mods, [os.path.join(self.root, "a")])
                self.assertEqual(printed.getvalue(), printed_line)

    def test_main_says_a_check_run_stopped_by_ctrl_c_as_play_cmd_does(self):
        path = os.path.join(self.root, "checks.toml")
        with open(path, "w") as f:
            f.write('mods = ["a"]\n')
        open_game = "stopped with the game still open: the next run of check.cmd or play.cmd puts your files back"
        for handed_over, stopped in ((True, open_game), (False, "stopped")):
            with self.subTest(handed_over=handed_over):
                printed = io.StringIO()
                with (
                    mock.patch.object(game, "Game") as Game,
                    mock.patch.object(runner, "run", side_effect=KeyboardInterrupt),
                    contextlib.redirect_stdout(printed),
                ):
                    Game.return_value.handed_over = handed_over
                    self.assertEqual(runner.main([path]), 1)
                self.assertEqual(printed.getvalue(), "The checks %s\n" % stopped)


class RunTest(unittest.TestCase):
    def run_checks(
        self,
        side_effect,
        checks=None,
        started=1000.0,
        log=("Plugin Template Plugin 1 loaded (built for API 0.6).",),
        mods_on=None,
    ):
        g = mock.create_autospec(game.Game, instance=True)
        g.started = started
        g.mods_on = started is not None if mods_on is None else mods_on
        g.log.return_value = list(log)
        printed = io.StringIO()
        with (
            mock.patch.object(runner, "run_checks", side_effect=side_effect) as run_checks,
            contextlib.redirect_stdout(printed),
        ):
            failed = runner.run(checks or runner.Checks(["a"]), g)
        self.ran = run_checks.called
        return failed, printed.getvalue()

    def test_all_passed_gives_none(self):
        failed, printed = self.run_checks(lambda checks, g, results: results.append(runner.Result("it", True, "")))
        self.assertIsNone(failed)
        self.assertEqual(printed, "  PASS  it\n")

    def test_a_failed_check_shows_why_and_the_end_of_the_log(self):
        def run(checks, g, results):
            results.append(runner.Result("the turn line", False, "Bazaar.log has no such line"))

        failed, printed = self.run_checks(run)
        self.assertTrue(failed.startswith("failed.\nThe end of Bazaar.log:\nPlugin Template Plugin 1 loaded"))
        self.assertEqual(printed, "  FAIL  the turn line\n        Bazaar.log has no such line\n")

    def test_an_error_part_way_still_shows_what_passed(self):
        for error in (CheckError("turn 1 cannot end"), PermissionError("Bazaar.log is locked")):

            def run(checks, g, results):
                results.append(runner.Result("the first check", True, ""))
                raise error

            with self.subTest(error=error):
                failed, printed = self.run_checks(run)
                self.assertTrue(failed.startswith("could not finish: %s\n" % error))
                self.assertEqual(
                    printed,
                    "  PASS  the first check\n  PASS  no plugin stopped working\n  PASS  Lua.log has no Lua errors\n",
                )

    def test_a_crash_that_ended_the_run_is_named_above_its_call_stack(self):
        crash = "Plugin Toy Crash: Faulted (code 0xC0000005) in CvPlayer::doTurn."
        stack = ["  #%02d ToyCrash.dll+0x00001A2B" % frame for frame in range(30)]
        timeout = CheckError("turn 2 starting did not happen within 180 seconds")
        failed, printed = self.run_checks(mock.Mock(side_effect=timeout), log=[crash] + stack)
        self.assertIn("  FAIL  no plugin stopped working\n        Bazaar.log has: " + crash, printed)
        self.assertNotIn(crash, failed)

    def test_a_run_that_never_switched_the_mods_on_shows_no_crash_or_lua_checks(self):
        refused = CheckError("Steam started civilizationv.exe, not the DirectX 11 version")
        _, printed = self.run_checks(mock.Mock(side_effect=refused), mods_on=False)
        self.assertEqual(printed, "")

    def test_an_error_before_the_game_started_shows_no_log(self):
        failed, _ = self.run_checks(mock.Mock(side_effect=CheckError("MODS holds no copy")), started=None)
        self.assertEqual(failed, "could not finish: MODS holds no copy")

    def test_checks_built_in_code_are_refused_before_anything_is_touched(self):
        for bad, why in (
            (runner.Checks(["a"], steps=[{"log": "Bazaar.log", "hass": "x"}]), "step 1 (log) does not take hass"),
            (runner.Checks([]), "the checks name no mods"),
            (runner.Checks("a"), "mods needs a list"),
            (runner.Checks(["a"], seed="1"), "seed needs a whole number"),
            (runner.Checks(["a"], lua_errors_expected=None), "lua_errors_expected needs true or false"),
        ):
            with self.subTest(why=why):
                failed, _ = self.run_checks(mock.Mock(), checks=bad)
                self.assertEqual(failed, "could not start: " + why)
                self.assertFalse(self.ran)

    def test_every_setting_is_one_the_checks_have(self):
        self.assertEqual(set(runner.SETTINGS), set(runner.Checks._fields))
        runner.validate(runner.Checks(("a",), steps=({"start_game": "duel"},), crash_expected=("Toy Crash",)))

    def test_main_hands_the_game_back_to_a_waiting_run_or_says_none_is_waiting(self):
        for waiting, code, said in (
            (True, 0, "handed the game back to the check\n"),
            (False, 1, "no check is waiting for its game back\n"),
        ):
            with self.subTest(waiting=waiting):
                printed = io.StringIO()
                with (
                    mock.patch.object(files, "hand_back", return_value=waiting),
                    mock.patch.object(game, "Game") as Game,
                    contextlib.redirect_stdout(printed),
                ):
                    self.assertEqual(runner.main(["--hand-back"]), code)
                self.assertEqual(printed.getvalue(), said)
                Game.assert_not_called()

    def test_main_names_a_file_it_cannot_use_without_starting_the_game(self):
        printed = io.StringIO()
        with mock.patch.object(game, "Game") as Game, contextlib.redirect_stdout(printed):
            self.assertEqual(runner.main([os.path.join(HERE, "no such checks.toml")]), 1)
            self.assertEqual(runner.main([]), 2)
            self.assertEqual(runner.main(["--play"]), 2)
        Game.assert_not_called()
        self.assertIn("no such checks.toml could not be read", printed.getvalue())


class SourceContractTest(unittest.TestCase):
    """The default crash check reads lines Bazaar writes: this ties it to them."""

    def test_a_fault_and_a_refusal_for_stopping_are_the_lines_the_crash_check_finds(self):
        with open(os.path.join(REPO, "host", "CivHostRuntime.cpp"), encoding="latin-1") as f:
            source = f.read()
        self.assertEqual(source.count('Log("Plugin %s: %s", rec.name.c_str(), problem'), 2)
        (fault,) = re.findall(r'"(Faulted \(code 0x%08X\) in %s\.)"', source)
        (refusal,) = re.findall(r'Format\("(It stopped working while loading [^"]*)"', source)
        self.assertRegex("Plugin %s: %s" % ("Toy Fault", fault % (5, "doTurn")), runner.CRASH)
        self.assertRegex("Plugin %s: %s" % ("Toy Fault", refusal.replace("%08X", "%d") % 5), runner.CRASH)
        self.assertNotRegex("Plugin Template Plugin 1 loaded (built for API 0.6).", runner.CRASH)

    def test_the_status_words_a_checks_file_compares_are_the_ones_the_plugins_screen_shows(self):
        source = ""
        for name in ("CivHostRuntime.cpp", "CivHostRuntime.h", "CivHostOrder.cpp"):
            with open(os.path.join(REPO, "host", name), encoding="latin-1") as f:
                source += f.read()
        for status in runner.STATUSES:
            self.assertIn('"%s"' % status, source)

    def test_the_plugins_screen_s_table_has_the_columns_the_checker_reads(self):
        with open(os.path.join(REPO, "host", "CivHostEngine.cpp"), encoding="latin-1") as f:
            (columns,) = re.findall(r"CREATE TABLE BazaarPlugins \(([^)]*)\)", f.read())
        made = {column.split()[0] for column in columns.split(",")}
        read, order = re.search(r"SELECT (.+?) FROM BazaarPlugins ORDER BY (\w+)", game.PLUGINS).groups()
        self.assertLessEqual({column.strip() for column in read.split(",")} | {order}, made)


if __name__ == "__main__":
    unittest.main()
