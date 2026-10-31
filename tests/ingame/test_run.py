"""Tests for run.py and the checks files it plays, without the game: each file reads and names only the mods and
plugins package.py builds, and --play hands one file's game over."""

import contextlib
import io
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from fakes import files, mods

import run
from bazaar_check import runner

LAID_OUT = {
    "%s (v %d)" % (mods.HOST_NAME, files.TEST_VERSION),
    "%s (v %d)" % (mods.VMC_DATA_NAME, mods.vmc_mod_parts().version),
    "Toy VMC Check (v 1)",
} | {"%s (v 1)" % toy.mod_name for toy in run.package.TOYS}
PLUGINS = {toy.dll_name + ".dll" for toy in run.package.TOYS}
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def checks_names():
    return sorted(name[: -len(".toml")] for name in os.listdir(run.CHECKS) if name.endswith(".toml"))


class ChecksFilesTest(unittest.TestCase):
    def test_every_checks_file_reads_and_names_only_what_package_py_builds(self):
        out = os.path.normpath(os.path.join(run.HERE, "out", "MODS"))
        self.assertTrue(checks_names())
        for name in checks_names():
            with self.subTest(name=name):
                checks = runner.read_checks(run.checks_path(name))
                self.assertEqual({os.path.dirname(mod) for mod in checks.mods}, {out})
                self.assertLessEqual({os.path.basename(mod) for mod in checks.mods}, LAID_OUT)
                named = [entry if isinstance(entry, str) else entry["file"] for entry in checks.plugin_order]
                named += [step["plugin"] for step in checks.steps if "plugin" in step]
                self.assertLessEqual(set(named), PLUGINS)

    def test_the_mod_ids_in_checks_files_are_the_test_plugins(self):
        toy_ids = {toy.mod_id for toy in run.package.TOYS}
        for name in checks_names():
            with open(run.checks_path(name), encoding="utf-8") as f:
                self.assertLessEqual(set(re.findall(UUID, f.read())), toy_ids, name)

    def test_no_state_a_check_reads_is_one_the_checks_close(self):
        for name in checks_names():
            for step in runner.read_checks(run.checks_path(name)).steps:
                self.assertFalse(step.get("state", "").endswith("Popup"), name)


class DlcFolderTest(unittest.TestCase):
    def setUp(self):
        self.steam = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.steam)
        self.library = os.path.join(self.steam, "Other Library")
        for folder in (self.steam, self.library):
            os.makedirs(os.path.join(folder, "steamapps"))

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def list_libraries(self, *libraries):
        rows = "".join(
            '\t"%d"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n' % (i, path.replace("\\", "\\\\"))
            for i, path in enumerate(libraries)
        )
        self.write(os.path.join(self.steam, "steamapps", "libraryfolders.vdf"), '"libraryfolders"\n{\n%s}\n' % rows)

    def test_the_game_is_found_in_the_steam_library_that_has_it(self):
        self.list_libraries(self.steam, self.library)
        manifest = os.path.join(self.library, "steamapps", "appmanifest_8930.acf")
        self.write(manifest, '"AppState"\n{\n\t"appid"\t\t"8930"\n\t"installdir"\t\t"Sid Meier\'s Civilization V"\n}\n')
        found = run.dlc_folder(self.steam)
        self.assertEqual(
            found, os.path.join(self.library, "steamapps", "common", "Sid Meier's Civilization V", "Assets", "DLC")
        )

    def test_a_steam_without_the_game_says_so(self):
        self.list_libraries(self.steam)
        with self.assertRaisesRegex(run.CheckError, "Steam lists no Civilization V install"):
            run.dlc_folder(self.steam)
        with self.assertRaisesRegex(run.CheckError, "could not find Civilization V's folder through Steam"):
            run.dlc_folder(os.path.join(self.steam, "missing"))


def put_in_game(dlc, *names):
    """A folder named like the test pack in the game's DLC folder, holding these files."""
    folder = os.path.join(dlc, "Bazaar Test Skin")
    os.makedirs(folder)
    for name in names:
        with open(os.path.join(folder, name), "w") as f:
            f.write("left")
    return folder


class PacksTest(unittest.TestCase):
    def setUp(self):
        self.dlc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dlc)
        patcher = mock.patch.object(run, "dlc_folder", return_value=self.dlc)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_checks_file_s_packs_are_in_the_game_for_its_run_only_even_when_it_stops(self):
        pack = put_in_game(self.dlc, "BazaarTestSkin.Civ5Pkg", "left by a stopped run.txt")
        with self.assertRaises(RuntimeError):
            with run.packs_in_game("dlc_setup"):
                self.assertEqual(os.listdir(self.dlc), ["Bazaar Test Skin"])
                self.assertTrue(os.path.isfile(os.path.join(pack, "Lua", "UI", "Deep", "AdvancedSetup.lua")))
                self.assertFalse(os.path.exists(os.path.join(pack, "left by a stopped run.txt")))
                raise RuntimeError("the run stopped")
        self.assertEqual(os.listdir(self.dlc), [])

    def test_a_folder_of_that_name_without_the_test_pack_s_package_file_is_not_touched(self):
        folder = put_in_game(self.dlc, "SomePack.Civ5Pkg")
        with self.assertRaisesRegex(
            run.CheckError, "could not put the test pack Bazaar Test Skin in the game's DLC folder"
        ):
            with run.packs_in_game("dlc_setup"):
                self.fail("the run started")
        self.assertEqual(os.listdir(folder), ["SomePack.Civ5Pkg"])

    def test_a_pack_that_cannot_be_taken_out_fails_the_run(self):
        with mock.patch.object(run.files, "remove_tree"):
            with self.assertRaisesRegex(
                run.CheckError, "could not take .*Bazaar Test Skin out of the game's DLC folder"
            ):
                with run.packs_in_game("dlc_setup"):
                    pass

    def test_a_checks_file_without_packs_leaves_the_game_alone(self):
        with mock.patch.object(run, "dlc_folder", side_effect=AssertionError("looked for the game")):
            with run.packs_in_game("plugins"):
                pass
        self.assertEqual(os.listdir(self.dlc), [])


class MainTest(unittest.TestCase):
    stopped = None

    def setUp(self):
        self.dlc = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dlc)
        self.find_game = mock.Mock(return_value=self.dlc)

    def play(self, *args):
        self.in_game_while_played = os.listdir(self.dlc)
        return self.stopped

    def main(self, argv, outcomes=None, built=0):
        printed = io.StringIO()
        with (
            mock.patch.object(run, "dlc_folder", self.find_game),
            mock.patch.object(run.package, "main", return_value=built) as build,
            mock.patch.object(run.runner, "run", side_effect=outcomes or []) as play,
            mock.patch.object(run.runner, "play_by_hand", side_effect=self.play) as self.play_by_hand,
            mock.patch.object(run.game, "Game"),
            contextlib.redirect_stdout(printed),
        ):
            code = run.main(argv)
        return code, printed.getvalue(), build.called, play.call_count

    def test_a_checks_file_that_does_not_read_stops_before_anything_is_built(self):
        code, printed, built, _ = self.main(["no_such_check"])
        self.assertEqual(code, 1)
        self.assertIn("no_such_check.toml could not be read", printed)
        self.assertFalse(built)

    def test_every_file_is_played_even_after_a_failure(self):
        code, printed, built, played = self.main(["crash_lua", "use_both"], ["failed.", None])
        self.assertEqual((code, built, played), (1, True, 2))
        self.assertIn("1 of 2 checks files passed: failed crash_lua", printed)

    def test_play_builds_then_hands_the_named_file_s_game_over(self):
        code, _, built, played = self.main(["--play", "crash_turn"])
        self.assertEqual((code, built, played), (0, True, 0))
        self.assertEqual(self.play_by_hand.call_args[0][0], runner.read_checks(run.checks_path("crash_turn")))

    def test_play_that_stopped_says_why(self):
        self.stopped = "stopped: Civilization V closed while starting"
        code, printed, _, _ = self.main(["--play", "crash_turn"])
        self.assertEqual(code, 1)
        self.assertIn("Playing stopped: Civilization V closed while starting", printed)

    def test_play_takes_one_checks_file(self):
        for argv in (["--play"], ["--play", "crash_lua", "use_both"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.main(argv)[0], 2)

    def test_a_game_that_cannot_be_checked_stops_before_anything_is_built(self):
        with mock.patch.object(run.game, "Game") as Game:
            Game.return_value.preflight.side_effect = run.CheckError("Civilization V is already running")
            printed = io.StringIO()
            with mock.patch.object(run.package, "main") as build, contextlib.redirect_stdout(printed):
                self.assertEqual(run.main(["use_both"]), 1)
        build.assert_not_called()
        self.assertIn("Civilization V is already running", printed.getvalue())

    def test_a_test_pack_a_run_stopped_by_force_left_in_the_game_is_taken_out_first(self):
        put_in_game(self.dlc, "BazaarTestSkin.Civ5Pkg")
        os.makedirs(os.path.join(self.dlc, "Expansion2"))
        self.main(["use_both"], [None])
        self.assertEqual(os.listdir(self.dlc), ["Expansion2"])

    def test_a_file_whose_packs_cannot_go_in_the_game_fails_and_the_rest_still_play(self):
        self.find_game.side_effect = run.CheckError("Steam lists no Civilization V install")
        code, printed, _, played = self.main(["dlc_setup", "use_both"], [None])
        self.assertEqual((code, played), (1, 1))
        self.assertIn("dlc_setup Steam lists no Civilization V install", printed)

    def test_play_has_the_file_s_packs_in_the_game_while_it_is_played(self):
        code, _, _, _ = self.main(["--play", "dlc_setup"])
        self.assertEqual((code, self.in_game_while_played, os.listdir(self.dlc)), (0, ["Bazaar Test Skin"], []))
        self.find_game.side_effect = run.CheckError("Steam lists no Civilization V install")
        code, printed, _, _ = self.main(["--play", "dlc_setup"])
        self.assertEqual(code, 1)
        self.assertIn("Playing stopped: Steam lists no Civilization V install", printed)

    def test_a_failed_build_plays_nothing(self):
        code, _, _, played = self.main(["use_both"], built=1)
        self.assertEqual((code, played), (1, 0))


if __name__ == "__main__":
    unittest.main()
