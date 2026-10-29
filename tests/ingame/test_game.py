"""Tests for the game driver's own logic: the player's files, MODS, putting things back after a run, and the waits that
must not be fooled. The game itself is replaced by a Game whose game-facing calls are scripted."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "ingame"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import game  # noqa: E402
import mods  # noqa: E402
import tuner  # noqa: E402

TASKLIST_NONE = "INFO: No tasks are running which match the specified criteria.\n"
TASKLIST_DX11 = '"CivilizationV_DX11.exe","46564","Console","1","945,180 K"\n'


class FakeClock:
    """Stands in for the time module: sleeping moves the clock on, so waits run out without real waiting."""

    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def write_mod(folder, mod_id, version=1, name="A Mod"):
    os.makedirs(folder)
    mods.write_modinfo(folder, name, mod_id, "A test mod.", [], [], version=version)
    return folder


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


class ModKeyTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def test_a_mod_folder_gives_its_id_and_version_even_with_brackets_in_its_path(self):
        folder = write_mod(os.path.join(self.root, "A [test] mod"), "abc", version=3)
        self.assertEqual(game.mod_key(folder), ("abc", 3))

    def test_no_or_several_descriptions_give_none(self):
        empty = os.path.join(self.root, "empty")
        os.makedirs(empty)
        self.assertIsNone(game.mod_key(empty))
        twice = write_mod(os.path.join(self.root, "twice"), "abc")
        mods.write_modinfo(twice, "Other", "def", "x", [], [])
        self.assertIsNone(game.mod_key(twice))

    def test_a_broken_description_is_a_game_error(self):
        folder = os.path.join(self.root, "broken")
        os.makedirs(folder)
        with open(os.path.join(folder, "Broken.modinfo"), "w") as f:
            f.write("<Mod id='x' version='one'>")
        with self.assertRaises(game.GameError):
            game.mod_key(folder)

    def test_mod_folders_finds_every_copy_and_skips_broken_ones(self):
        first = write_mod(os.path.join(self.root, "Bazaar (v 6)"), "bazaar", version=6)
        second = write_mod(os.path.join(self.root, "Bazaar test"), "bazaar", version=6)
        write_mod(os.path.join(self.root, "Bazaar (v 5)"), "bazaar", version=5)
        broken = os.path.join(self.root, "broken")
        os.makedirs(broken)
        with open(os.path.join(broken, "Broken.modinfo"), "w") as f:
            f.write("not xml")
        self.assertEqual(game.mod_folders(self.root, ("bazaar", 6)), [first, second])


class InstallTest(UserFolderTest):
    def test_a_package_is_copied_for_the_game_to_unpack(self):
        package = os.path.join(self.user, "Bazaar-0.6.0.civ5mod")
        with open(package, "wb") as f:
            f.write(b"7z")
        self.game.install([package])
        self.assertTrue(os.path.isfile(self.path("MODS", "Bazaar-0.6.0.civ5mod")))

    def test_a_folder_replaces_one_of_the_same_mod(self):
        old = write_mod(self.path("MODS", "Template Plugin"), "template")
        with open(os.path.join(old, "stale.txt"), "w") as f:
            f.write("old")
        new = write_mod(os.path.join(self.user, "build", "Template Plugin"), "template")
        self.game.install([new])
        self.assertFalse(os.path.exists(self.path("MODS", "Template Plugin", "stale.txt")))
        self.assertEqual(game.mod_key(self.path("MODS", "Template Plugin")), ("template", 1))

    def test_a_folder_never_replaces_another_mod(self):
        write_mod(self.path("MODS", "Template Plugin"), "someone-elses")
        new = write_mod(os.path.join(self.user, "build", "Template Plugin"), "template")
        with self.assertRaisesRegex(game.GameError, "different mod"):
            self.game.install([new])
        self.assertEqual(game.mod_key(self.path("MODS", "Template Plugin")), ("someone-elses", 1))


PLAYER_AUTOSAVES = {
    "AutoSave_0003 BC-3880.Civ5Save": b"the player's turn 3",
    os.path.join("prev", "0ldAutoSave_0002 BC-3940.Civ5Save"): b"the player's turn 2",
}


def write_files(folder, files):
    for rel, content in files.items():
        os.makedirs(os.path.dirname(os.path.join(folder, rel)), exist_ok=True)
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(content)


def read_files(folder):
    found = {}
    for dirpath, _, filenames in os.walk(folder):
        for name in filenames:
            with open(os.path.join(dirpath, name), "rb") as f:
                found[os.path.relpath(os.path.join(dirpath, name), folder)] = f.read()
    return found


def rotate_autosaves(user):
    """What the game does to the autosaves when a new game starts."""
    auto = os.path.join(user, game.AUTOSAVES)
    shutil.rmtree(os.path.join(auto, "prev"), ignore_errors=True)
    os.makedirs(os.path.join(auto, "prev"))
    for name in os.listdir(auto):
        if name != "prev":
            os.rename(os.path.join(auto, name), os.path.join(auto, "prev", "0ld" + name))
    write_files(auto, {"AutoSave_Initial_0000 BC-4000.Civ5Save": b"the check's game"})


class UserFilesTest(UserFolderTest):
    def write(self, name, content):
        os.makedirs(os.path.dirname(self.path(name)) or self.user, exist_ok=True)
        with open(self.path(name), "wb") as f:
            f.write(content)

    def read(self, name):
        with open(self.path(name), "rb") as f:
            return f.read()

    def test_autosaves_rotated_by_the_checks_game_come_back_as_they_were(self):
        write_files(self.path(game.AUTOSAVES), PLAYER_AUTOSAVES)
        saved = self.game.save_user_files()
        rotate_autosaves(self.user)
        self.assertEqual(self.game.restore_user_files(saved), [])
        self.assertEqual(read_files(self.path(game.AUTOSAVES)), PLAYER_AUTOSAVES)
        self.assertFalse(os.path.exists(saved.folder))

    def test_the_plugin_order_is_copied_to_disk_before_the_check_changes_it(self):
        self.write(game.ORDER_FILE, b"load\tMCPServer.dll\t\t\r\n")
        saved = self.game.save_user_files()
        self.addCleanup(shutil.rmtree, saved.folder, True)
        self.game.use_default_plugin_order()
        self.assertEqual(read_files(saved.folder), {"Bazaar plugin order.txt": b"load\tMCPServer.dll\t\t\r\n"})

    def test_with_no_autosaves_before_the_checks_own_are_removed(self):
        saved = self.game.save_user_files()
        write_files(self.path(game.AUTOSAVES), {"AutoSave_Initial_0000 BC-4000.Civ5Save": b"the check's game"})
        self.assertEqual(self.game.restore_user_files(saved), [])
        self.assertFalse(os.path.exists(self.path(game.AUTOSAVES)))

    def test_autosaves_are_left_alone_while_the_game_still_runs_and_their_copy_is_named(self):
        write_files(self.path(game.AUTOSAVES), PLAYER_AUTOSAVES)
        saved = self.game.save_user_files()
        rotate_autosaves(self.user)
        with mock.patch.object(game, "game_processes", return_value=["civilizationv_dx11.exe"]):
            running, kept = self.game.restore_user_files(saved)
        self.assertIn("still running", running)
        self.assertIn(saved.folder, kept)
        self.assertEqual(read_files(saved.autosaves), PLAYER_AUTOSAVES)
        shutil.rmtree(saved.folder)

    def test_a_plugin_order_the_check_made_is_removed_and_the_players_comes_back(self):
        saved = self.game.save_user_files()
        self.game.use_default_plugin_order()
        self.assertEqual(self.read(game.ORDER_FILE), b"")
        self.game.restore_user_files(saved)
        self.assertFalse(os.path.exists(self.path(game.ORDER_FILE)))
        self.write(game.ORDER_FILE, b"skip\tTemplatePlugin.dll\t\t\r\n")
        saved = self.game.save_user_files()
        self.game.use_default_plugin_order()
        self.game.restore_user_files(saved)
        self.assertEqual(self.read(game.ORDER_FILE), b"skip\tTemplatePlugin.dll\t\t\r\n")

    def test_only_a_log_written_during_this_run_counts(self):
        self.write(os.path.join("Logs", "Bazaar.log"), b"Plugin Template Plugin 1 loaded\r\n")
        self.game.started = os.path.getmtime(self.path("Logs", "Bazaar.log")) + 60
        self.assertEqual(self.game.log(), [])
        self.game.started -= 120
        self.assertEqual(self.game.log(), ["Plugin Template Plugin 1 loaded"])


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
        rotate_autosaves(self.user)
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
        write_files(self.path(game.AUTOSAVES), PLAYER_AUTOSAVES)
        return g

    def autosaves(self):
        return read_files(self.path(game.AUTOSAVES))

    def test_a_good_run_puts_the_mods_back_then_quits(self):
        g = self.scripted()
        with game.session(g):
            g.step("check")
        self.assertEqual(g.calls, ["start", "mods", "check", "to_main_menu", "set_mods [('player-mod', 2)]", "quit"])
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_a_failing_check_still_puts_everything_back_and_keeps_its_error(self):
        g = self.scripted()
        with self.assertRaisesRegex(game.GameError, "turn 1 cannot end"):
            with game.session(g):
                raise game.GameError("turn 1 cannot end")
        self.assertEqual(g.calls[-3:], ["to_main_menu", "set_mods [('player-mod', 2)]", "quit"])
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_when_the_menus_never_come_back_the_player_is_told_which_mods_to_switch_on(self):
        g = self.scripted(to_main_menu=tuner.TunerError("the game closed the tuner connection"))
        with self.assertRaisesRegex(game.GameError, "the plugin crashed"):
            with game.session(g):
                raise game.GameError("the plugin crashed")
        self.assertIn("quit", g.calls)
        self.assertTrue(any("Player Mod (v 2)" in line for line in g.said))
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_a_problem_putting_things_back_after_a_good_run_is_an_error(self):
        g = self.scripted(quit=game.GameError("Civilization V closing did not happen"))
        with self.assertRaisesRegex(game.GameError, "close Civilization V by hand"):
            with game.session(g):
                pass

    def test_a_failed_start_leaves_the_autosaves_it_never_touched_and_says_nothing_of_them(self):
        g = self.scripted(start=game.GameError("Steam started civilizationv.exe"))
        g.start = lambda timeout=300: g.step("start")
        with mock.patch.object(game, "game_processes", return_value=["civilizationv.exe"]):
            with self.assertRaisesRegex(game.GameError, "Steam started"):
                with game.session(g):
                    pass
        self.assertEqual(g.calls, ["start"])
        self.assertEqual(g.said, [])
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)

    def test_a_second_ctrl_c_while_putting_things_back_still_puts_the_autosaves_back(self):
        g = self.scripted(to_main_menu=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            with game.session(g):
                raise game.GameError("turn 1 cannot end")
        self.assertEqual(self.autosaves(), PLAYER_AUTOSAVES)


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
        with self.assertRaisesRegex(game.GameError, "closed as it started"):
            self.started(["civilizationv_dx11.exe"], [])

    def test_the_directx_9_version_is_refused(self):
        with self.assertRaisesRegex(game.GameError, "civilizationv.exe, not the DirectX 11 version"):
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
            with self.assertRaisesRegex(game.GameError, "does not list the save"):
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
        with self.assertRaisesRegex(game.GameError, "waiting for ENDTURN_BLOCKING_UNITS"):
            self.end_turn_failing((3, "ENDTURN_BLOCKING_UNITS"))

    def test_a_turn_that_ends_but_never_comes_back_says_nothing_blocked_it(self):
        with self.assertRaisesRegex(game.GameError, "nothing blocks the turn"):
            self.end_turn_failing((game.NOT_BLOCKED, "NO_ENDTURN_BLOCKING_TYPE"))


class WaitTest(UserFolderTest):
    def test_a_missing_state_is_not_yet_and_the_last_error_is_named(self):
        g = game.Game(say=lambda text: None, user=self.user)

        def ready():
            raise tuner.NoSuchState("the game has no Lua state named InGame")

        with mock.patch.object(g.tuner, "connect") as connect, mock.patch.object(game, "time", FakeClock()):
            with self.assertRaisesRegex(game.GameError, "no Lua state named InGame"):
                g.wait("the game starting", ready, 60)
        connect.assert_not_called()

    def test_a_game_that_closed_ends_the_wait_at_once(self):
        g = game.Game(say=lambda text: None, user=self.user)

        def ready():
            raise tuner.TunerError("the game closed the tuner connection")

        with self.assertRaisesRegex(game.GameError, "closed while waiting"):
            g.wait("the game starting", ready, 60)


if __name__ == "__main__":
    unittest.main()
