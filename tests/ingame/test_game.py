"""Tests for the game driver's own logic: putting things back after a run, and the waits that must not be fooled. The
game itself is replaced by a Game whose game-facing calls are scripted."""

import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from fakes import PLAYER_AUTOSAVES, TASKLIST_DX11, TASKLIST_NONE, FakeClock, read_files, rotate_autosaves, write_files

from bazaar_check import CheckError, files, game, tuner


class UserFolderTest(unittest.TestCase):
    def setUp(self):
        self.user = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.user)
        os.makedirs(os.path.join(self.user, "MODS"))
        self.game = game.Game(say=lambda text: None, user=self.user)
        patcher = mock.patch.object(game, "game_processes", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def path(self, *parts):
        return os.path.join(self.user, *parts)


class HelpersTest(unittest.TestCase):
    def test_config_needs_the_tuner_and_logging(self):
        self.assertEqual(game.config_problems("EnableTuner = 1\r\nLoggingEnabled = 1\r\n"), [])
        self.assertEqual(game.config_problems("EnableTuner = 10\n LoggingEnabled=1\n"), ["EnableTuner = 1"])
        self.assertEqual(game.config_problems(""), ["EnableTuner = 1", "LoggingEnabled = 1"])

    def test_tasklist_names_only_the_game(self):
        self.assertEqual(game.parse_tasklist(TASKLIST_NONE), [])
        self.assertEqual(game.parse_tasklist(TASKLIST_DX11 + '"steam.exe","4632"\n'), ["civilizationv_dx11.exe"])

    def test_mod_problems_name_what_is_missing_and_what_is_still_on(self):
        wanted = [("bazaar", 6), ("template", 1)]
        enabled = [("bazaar", 6, "Bazaar"), ("other", 2, "Other Mod")]
        self.assertEqual(
            game.mod_problems(wanted, enabled), ["not switched on: template v1", "still on: Other Mod (v 2)"]
        )
        self.assertEqual(game.mod_problems(wanted, [("bazaar", 6, "B"), ("template", 1, "T")]), [])

    def test_mod_table_quotes_ids(self):
        self.assertEqual(game.mod_table([("a-b", 5), ('q"', 1)]), '{{"a-b", 5}, {"q\\"", 1}}')


class ScriptedGame(game.Game):
    """A Game whose calls to the game are recorded, and answered or failed as a test sets up."""

    def __init__(self, user):
        self.said = []
        super().__init__(say=self.said.append, user=user)
        self.calls = []
        self.failing = {}

    def step(self, name, result=None):
        self.calls.append(name)
        if name in self.failing:
            raise self.failing[name]
        return result

    def start(self, timeout=300):
        rotate_autosaves(self.files.user)
        self.step("start")

    def mods(self, enabled_only=True):
        return self.step("mods", [("player-mod", 2, "Player Mod")])

    def to_main_menu(self, timeout=180):
        self.step("to_main_menu")

    def set_mods(self, wanted):
        self.step("set_mods %s" % wanted)

    def quit(self, timeout=120):
        self.step("quit")


class SessionTest(UserFolderTest):
    def scripted(self, **failing):
        g = ScriptedGame(self.user)
        g.failing = failing
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        return g

    def autosaves(self):
        return read_files(self.path(files.AUTOSAVES))

    def copies_folder(self, g):
        """Where the session said it kept the copies; removed when the test ends."""
        (folder,) = [m.group(1) for m in map(re.compile(r"^copies of .+ are kept in (.+) until").match, g.said) if m]
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_a_good_run_puts_the_mods_back_then_quits(self):
        g = self.scripted()
        with game.session(g):
            g.step("check")
        self.assertEqual(g.calls, ["start", "mods", "check", "to_main_menu", "set_mods [('player-mod', 2)]", "quit"])
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)
        self.assertFalse(os.path.exists(self.copies_folder(g)))
        self.assertEqual(g.said[-1], "your Mods menu choices, plugin order and autosaves are as they were")

    def test_a_failing_check_still_puts_everything_back_and_keeps_its_error(self):
        g = self.scripted()
        with self.assertRaisesRegex(CheckError, "turn 1 cannot end"):
            with game.session(g):
                raise CheckError("turn 1 cannot end")
        self.assertEqual(g.calls[-3:], ["to_main_menu", "set_mods [('player-mod', 2)]", "quit"])
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_when_the_menus_never_come_back_the_player_is_told_which_mods_to_switch_on(self):
        g = self.scripted(to_main_menu=tuner.TunerError("the game closed the tuner connection"))
        with self.assertRaisesRegex(CheckError, "the plugin crashed"):
            with game.session(g):
                raise CheckError("the plugin crashed")
        self.assertIn("quit", g.calls)
        self.assertTrue(any("Player Mod (v 2)" in line for line in g.said))
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_a_mod_list_never_read_asks_for_no_mods_and_keeps_the_real_error(self):
        closed = tuner.TunerError("the game closed the tuner connection")
        g = self.scripted(mods=closed, to_main_menu=closed)
        with self.assertRaisesRegex(tuner.TunerError, "closed the tuner connection"):
            with game.session(g):
                pass
        self.assertEqual(g.calls, ["start", "mods", "to_main_menu", "quit"])
        self.assertFalse(any("switch these on" in line for line in g.said))
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_a_problem_putting_things_back_after_a_good_run_is_an_error(self):
        g = self.scripted(quit=CheckError("Civilization V closing did not happen"))
        with self.assertRaisesRegex(CheckError, "close Civilization V by hand"):
            with game.session(g):
                pass

    def test_a_game_that_will_not_close_after_a_good_run_keeps_the_autosaves_copy(self):
        g = self.scripted(quit=CheckError("Civilization V closing did not happen"))
        with mock.patch.object(game, "game_processes", return_value=["civilizationv_dx11.exe"]):
            with self.assertRaisesRegex(CheckError, "still running.+the copies stay in"):
                with game.session(g):
                    pass
        self.assertNotEqual(self.autosaves(), PLAYER_AUTOSAVES)
        self.assertEqual(read_files(os.path.join(self.copies_folder(g), "auto")), PLAYER_AUTOSAVES)

    def test_a_failed_start_leaves_the_autosaves_it_never_touched(self):
        g = self.scripted(start=CheckError("Steam started civilizationv.exe"))
        since = {"AutoSave_0004 BC-3820.Civ5Save": b"saved while the check started"}

        def start(timeout=300):
            write_files(self.path(files.AUTOSAVES), since)
            g.step("start")

        g.start = start
        with self.assertRaisesRegex(CheckError, "Steam started"):
            with game.session(g):
                pass
        self.assertEqual(g.calls, ["start"])
        self.assertEqual(self.autosaves(), dict(PLAYER_AUTOSAVES, **since))
        self.assertFalse(os.path.exists(self.copies_folder(g)))
        self.assertEqual(len(g.said), 1)

    def test_ctrl_c_while_the_game_starts_says_to_close_it(self):
        g = self.scripted()

        def start(timeout=300):
            g.started = 1000.0
            raise KeyboardInterrupt

        g.start = start
        with mock.patch.object(game, "game_processes", return_value=["civilizationv_dx11.exe"]):
            with self.assertRaises(KeyboardInterrupt):
                with game.session(g):
                    pass
        self.assertEqual(g.said[-1], "close Civilization V by hand")
        self.copies_folder(g)

    def test_a_second_ctrl_c_while_putting_things_back_still_puts_the_autosaves_back(self):
        g = self.scripted(to_main_menu=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            with game.session(g):
                raise CheckError("turn 1 cannot end")
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)
        self.assertTrue(any("(the check was stopped)" in line and "Player Mod (v 2)" in line for line in g.said))
        self.assertNotIn("quit", g.calls)

    def test_an_unexpected_error_putting_things_back_still_closes_the_game_and_names_the_error(self):
        g = self.scripted(to_main_menu=ValueError("a mistake in the check"))
        with self.assertRaisesRegex(ValueError, "a mistake in the check"):
            with game.session(g):
                pass
        self.assertEqual(g.calls[-1], "quit")
        self.assertTrue(any("(a mistake in the check)" in line and "Player Mod (v 2)" in line for line in g.said))
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_a_game_left_running_is_named_and_its_autosaves_left_alone(self):
        g = self.scripted(to_main_menu=KeyboardInterrupt())
        with mock.patch.object(game, "game_processes", return_value=["civilizationv_dx11.exe"]):
            with self.assertRaises(KeyboardInterrupt):
                with game.session(g):
                    pass
        self.assertEqual(g.said[-1], "close Civilization V by hand")
        self.assertNotEqual(self.autosaves(), PLAYER_AUTOSAVES)
        self.assertIn("the copies stay in %s" % self.copies_folder(g), g.said)


class StartTest(UserFolderTest):
    def started(self, *processes):
        with open(self.path("config.ini"), "w") as f:
            f.write("EnableTuner = 1\nLoggingEnabled = 1\n")
        with (
            mock.patch.object(game, "game_processes", side_effect=[[]] + list(processes)),
            mock.patch.object(game.os, "startfile", create=True),
            mock.patch.object(game, "time", FakeClock()),
        ):
            self.game.start()

    def test_a_game_that_closes_as_it_starts_is_named(self):
        with self.assertRaisesRegex(CheckError, "closed as it started"):
            self.started(["civilizationv_dx11.exe"], [])

    def test_the_directx_9_version_is_refused(self):
        with self.assertRaisesRegex(CheckError, "civilizationv.exe, not the DirectX 11 version"):
            self.started(["civilizationv.exe"], ["civilizationv.exe"])


class LoadScreenTest(UserFolderTest):
    def test_only_a_loading_screen_newer_than_the_last_games_is_pressed(self):
        g = game.Game(say=lambda text: None, user=self.user)
        polls = iter([[50], [50], [50], [50, 180], [50, 180]])
        listed = {game.LOAD_SCREEN: lambda: next(polls), game.IN_GAME: lambda: [174]}
        pressed = []

        def lua(state, code, timeout=30):
            if code == "OnActivateButtonClicked()":
                pressed.append(listed[game.LOAD_SCREEN]())
                listed[game.IN_GAME] = lambda: [174, 304]
            return []

        with (
            mock.patch.object(g, "state_ids", side_effect=lambda name: listed[name]()),
            mock.patch.object(g, "flag", return_value=False),
            mock.patch.object(g, "lua", side_effect=lua),
            mock.patch.object(game, "time", FakeClock()),
        ):
            g._through_load_screen(game.IN_GAME, "load", 60)
        self.assertEqual(pressed, [[50, 180]])

    def test_a_save_the_game_does_not_list_stops_at_once(self):
        g = game.Game(say=lambda text: None, user=self.user)
        with (
            mock.patch.object(g, "state_ids", return_value=[]),
            mock.patch.object(g, "lua", return_value=[game.REFUSED + "the game does not list the save x"]),
        ):
            with self.assertRaisesRegex(CheckError, "does not list the save"):
                g._through_load_screen(game.FRONT_END, "load", 60)


class EndTurnTest(UserFolderTest):
    def test_end_turn_is_sent_until_the_next_turn_starts(self):
        g = game.Game(say=lambda text: None, user=self.user)
        answers = iter([["false"], ["false"], ["true"]])
        sent = []

        def lua(state, code, timeout=30):
            if "CONTROL_ENDTURN" in code:
                sent.append(code)
                return next(answers)
            return []

        with (
            mock.patch.object(g, "turn", return_value=4),
            mock.patch.object(g, "blocker", return_value=(game.NOT_BLOCKED, "NO_ENDTURN_BLOCKING_TYPE")),
            mock.patch.object(g, "lua", side_effect=lua),
            mock.patch.object(game, "time", FakeClock()),
        ):
            self.assertEqual(g.end_turn(), 5)
        self.assertEqual(len(sent), 3)

    def end_turn_failing(self, blocker):
        g = game.Game(say=lambda text: None, user=self.user)
        with (
            mock.patch.object(g, "turn", return_value=4),
            mock.patch.object(g, "blocker", return_value=blocker),
            mock.patch.object(g, "lua", return_value=["false"]),
            mock.patch.object(game, "time", FakeClock()),
        ):
            g.end_turn()

    def test_a_turn_that_cannot_end_names_what_the_game_waits_for(self):
        with self.assertRaisesRegex(CheckError, "waiting for ENDTURN_BLOCKING_UNITS"):
            self.end_turn_failing((3, "ENDTURN_BLOCKING_UNITS"))

    def test_a_turn_that_ends_but_never_comes_back_says_nothing_blocked_it(self):
        with self.assertRaisesRegex(CheckError, "nothing blocks the turn"):
            self.end_turn_failing((game.NOT_BLOCKED, "NO_ENDTURN_BLOCKING_TYPE"))


class WaitTest(UserFolderTest):
    def test_a_missing_state_is_not_yet_and_the_last_error_is_named(self):
        g = game.Game(say=lambda text: None, user=self.user)

        def ready():
            raise tuner.NoSuchState("the game has no Lua state named InGame")

        with mock.patch.object(g.tuner, "connect") as connect, mock.patch.object(game, "time", FakeClock()):
            with self.assertRaisesRegex(CheckError, "no Lua state named InGame"):
                g.wait("the game starting", ready, 60)
        connect.assert_not_called()

    def test_a_game_that_closed_ends_the_wait_at_once(self):
        g = game.Game(say=lambda text: None, user=self.user)

        def ready():
            raise tuner.TunerError("the game closed the tuner connection")

        with self.assertRaisesRegex(CheckError, "closed while waiting"):
            g.wait("the game starting", ready, 60)


if __name__ == "__main__":
    unittest.main()
