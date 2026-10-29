"""Tests for the game driver's own logic: putting things back after a run, and the waits that must not be fooled. The
game itself is replaced by a Game whose game-facing calls are scripted."""

import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from fakes import (
    PLAYER_AUTOSAVES,
    TASKLIST_DX11,
    TASKLIST_NONE,
    FakeClock,
    mods,
    read_files,
    rotate_autosaves,
    use_own_temp,
    write_files,
)

from bazaar_check import CheckError, files, game, tuner

CONFIG_INI = b"[CONFIG]\r\nEnableTuner = 1\r\nSyncRandSeed = 0\r\n\r\n; seed for maps\r\nMapRandSeed = 0\r\n"


class UserFolderTest(unittest.TestCase):
    def setUp(self):
        self.user = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.user)
        use_own_temp(self)
        os.makedirs(os.path.join(self.user, "MODS"))
        write_files(self.user, {files.CONFIG: CONFIG_INI})
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
    """A Game whose calls to the game are recorded, and answered or failed as a test sets up. Starting it rotates the
    autosaves and switches mods on, as the real game does."""

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
        write_files(self.files.user, {files.MODS_DATABASE: b"the check's mods"})
        self.step("start")

    def quit(self, timeout=120):
        self.step("quit")


class SessionTest(UserFolderTest):
    def scripted(self, **failing):
        g = ScriptedGame(self.user)
        g.failing = failing
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        write_files(self.user, {files.MODS_DATABASE: b"the player's mods"})
        return g

    def autosaves(self):
        return read_files(self.path(files.AUTOSAVES))

    def mods(self):
        return read_files(self.user)[files.MODS_DATABASE]

    def copies_folder(self, g):
        """Where the session said it kept the copies; removed when the test ends."""
        (folder,) = [m.group(1) for m in map(re.compile(r"^copies of .+ are kept in (.+) until").match, g.said) if m]
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_a_good_run_puts_everything_back_once_the_game_has_closed(self):
        g = self.scripted()
        with game.session(g, 7):
            g.step("check")
            with open(self.path(files.CONFIG), "rb") as f:
                during = f.read()
        self.assertEqual(g.calls, ["start", "check", "quit"])
        self.assertEqual(during, CONFIG_INI.replace(b"Seed = 0", b"Seed = 7"))
        self.assertEqual(read_files(self.user)[files.CONFIG], CONFIG_INI)
        self.assertEqual(self.mods(), b"the player's mods")
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)
        self.assertFalse(os.path.exists(self.copies_folder(g)))
        self.assertEqual(g.said[-1], "your Mods menu choices, config.ini and autosaves are as they were")

    def test_a_failing_check_still_puts_everything_back_and_keeps_its_error(self):
        g = self.scripted()
        with self.assertRaisesRegex(CheckError, "turn 1 cannot end"):
            with game.session(g, 1):
                raise CheckError("turn 1 cannot end")
        self.assertEqual(g.calls[-1], "quit")
        self.assertEqual((self.mods(), self.autosaves()), (b"the player's mods", PLAYER_AUTOSAVES))

    def test_a_problem_putting_things_back_after_a_good_run_is_an_error(self):
        g = self.scripted(quit=CheckError("Civilization V closing did not happen"))
        with self.assertRaisesRegex(CheckError, "close Civilization V by hand"):
            with game.session(g, 1):
                pass

    def test_a_game_that_will_not_close_keeps_the_copies_of_what_it_holds(self):
        g = self.scripted(quit=CheckError("Civilization V closing did not happen"))
        with mock.patch.object(game, "game_processes", return_value=["civilizationv_dx11.exe"]):
            with self.assertRaisesRegex(
                CheckError, "Mods menu choices, config.ini and autosaves were not put back.+the copies"
            ):
                with game.session(g, 1):
                    pass
        seeded = CONFIG_INI.replace(b"Seed = 0", b"Seed = 1")
        self.assertEqual((self.mods(), read_files(self.user)[files.CONFIG]), (b"the check's mods", seeded))
        folder = self.copies_folder(g)
        self.assertEqual(read_files(os.path.join(folder, "auto")), PLAYER_AUTOSAVES)
        self.assertEqual(read_files(folder)["Civ5ModsDatabase.db"], b"the player's mods")
        self.assertEqual(read_files(folder)["config.ini"], CONFIG_INI)

    def test_a_failed_start_leaves_the_autosaves_it_never_touched(self):
        g = self.scripted(start=CheckError("Steam started civilizationv.exe"))
        since = {"AutoSave_0004 BC-3820.Civ5Save": b"saved while the check started"}

        def start(timeout=300):
            write_files(self.path(files.AUTOSAVES), since)
            g.step("start")

        g.start = start
        with self.assertRaisesRegex(CheckError, "Steam started"):
            with game.session(g, 1):
                pass
        self.assertEqual(g.calls, ["start"])
        self.assertEqual(self.autosaves(), dict(PLAYER_AUTOSAVES, **since))
        self.assertEqual(read_files(self.user)[files.CONFIG], CONFIG_INI)
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
                with game.session(g, 1):
                    pass
        self.assertEqual(g.said[-1], "close Civilization V by hand")
        self.copies_folder(g)

    def test_a_second_ctrl_c_while_putting_things_back_still_puts_the_files_back(self):
        g = self.scripted(quit=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            with game.session(g, 1):
                raise CheckError("turn 1 cannot end")
        self.assertEqual((self.mods(), self.autosaves()), (b"the player's mods", PLAYER_AUTOSAVES))
        self.assertEqual(g.calls.count("quit"), 1)

    def test_an_unexpected_error_closing_the_game_tries_once_more(self):
        g = self.scripted(quit=ValueError("a mistake in the check"))
        with self.assertRaisesRegex(ValueError, "a mistake in the check"):
            with game.session(g, 1):
                pass
        self.assertEqual(g.calls.count("quit"), 2)
        self.assertEqual((self.mods(), self.autosaves()), (b"the player's mods", PLAYER_AUTOSAVES))

    def test_a_game_left_running_is_named_and_what_it_holds_left_alone(self):
        g = self.scripted(quit=KeyboardInterrupt())
        with mock.patch.object(game, "game_processes", return_value=["civilizationv_dx11.exe"]):
            with self.assertRaises(KeyboardInterrupt):
                with game.session(g, 1):
                    pass
        self.assertEqual(g.said[-1], "close Civilization V by hand")
        self.assertEqual(self.mods(), b"the check's mods")
        self.assertNotEqual(self.autosaves(), PLAYER_AUTOSAVES)
        folder = self.copies_folder(g)
        self.assertTrue(any(said.startswith("the copies stay in %s, " % folder) for said in g.said))


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


class StartedSessionTest(UserFolderTest):
    def test_a_session_starts_the_game_with_its_own_copies_made(self):
        write_files(self.user, {files.CONFIG: CONFIG_INI + b"LoggingEnabled = 1\r\n"})
        dx11 = ["civilizationv_dx11.exe"]
        with (
            mock.patch.object(game, "game_processes", side_effect=[[], dx11, dx11] + [[]] * 5),
            mock.patch.object(game.os, "startfile", create=True) as startfile,
            mock.patch.object(self.game.tuner, "connect"),
            mock.patch.object(self.game, "menu_ready", return_value=True),
            mock.patch.object(self.game, "quit"),
            mock.patch.object(game, "time", FakeClock()),
        ):
            with game.session(self.game, 1):
                pass
        startfile.assert_called_once_with(game.GAME_URL)
        self.assertEqual(files.leftover_copies(), [])


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
            mock.patch.object(g, "close_popups") as close_popups,
            mock.patch.object(game, "time", FakeClock()),
        ):
            self.assertEqual(g.end_turn(), 5)
        self.assertEqual(len(sent), 3)
        self.assertEqual(close_popups.call_count, 2)

    def test_the_game_s_pop_ups_are_closed_but_bazaar_s_is_left(self):
        said = []
        g = game.Game(say=said.append, user=self.user)
        states = [
            (5, "CityStateGreetingPopup"),
            (6, game.BAZAAR_STOPPED),
            (7, "TechPopup"),
            (8, "CityStateGreetingPopup"),
        ]
        asked = []

        def lua(state, code, timeout=30):
            asked.append(state)
            return ["closed"] if state == "CityStateGreetingPopup" else []

        with mock.patch.object(g.tuner, "states", return_value=states), mock.patch.object(g, "lua", side_effect=lua):
            self.assertEqual(g.close_popups(), ["CityStateGreetingPopup"])
        self.assertEqual(asked, ["CityStateGreetingPopup", "TechPopup"])
        self.assertEqual(said, ["closed CityStateGreetingPopup"])

    def test_bazaar_s_pop_up_is_the_state_its_file_gives_and_is_not_closed(self):
        self.assertEqual(os.path.splitext(os.path.basename(mods.STOPPED_POPUP[1]))[0], game.BAZAAR_STOPPED)
        self.assertFalse(game.BAZAAR_STOPPED.endswith("Popup"))

    def test_a_game_that_closes_while_a_turn_ends_is_not_reported_as_a_stuck_turn(self):
        g = game.Game(say=lambda text: None, user=self.user)
        with (
            mock.patch.object(g, "turn", return_value=4),
            mock.patch.object(g, "lua", return_value=[]),
            mock.patch.object(g, "wait", side_effect=game.GameClosed("Civilization V closed while waiting")),
            mock.patch.object(g, "blocker") as blocker,
        ):
            with self.assertRaisesRegex(game.GameClosed, "^Civilization V closed while waiting$"):
                g.end_turn()
        blocker.assert_not_called()

    def end_turn_failing(self, blocker):
        g = game.Game(say=lambda text: None, user=self.user)
        with (
            mock.patch.object(g, "turn", return_value=4),
            mock.patch.object(g, "blocker", return_value=blocker),
            mock.patch.object(g, "lua", return_value=["false"]),
            mock.patch.object(g.tuner, "states", return_value=[]),
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

        with self.assertRaisesRegex(game.GameClosed, "closed while waiting"):
            g.wait("the game starting", ready, 60)


if __name__ == "__main__":
    unittest.main()
