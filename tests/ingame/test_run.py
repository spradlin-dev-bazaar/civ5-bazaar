"""Tests for run.py and the checks files it plays, without the game: each file reads and names only the mods and
plugins package.py builds, and --play hands one file's game over."""

import contextlib
import io
import os
import re
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


class MainTest(unittest.TestCase):
    stopped = None

    def main(self, argv, outcomes=None, built=0):
        printed = io.StringIO()
        with (
            mock.patch.object(run.package, "main", return_value=built) as build,
            mock.patch.object(run.runner, "run", side_effect=outcomes or []) as play,
            mock.patch.object(run.runner, "play_by_hand", return_value=self.stopped) as self.play_by_hand,
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

    def test_a_failed_build_plays_nothing(self):
        code, _, _, played = self.main(["use_both"], built=1)
        self.assertEqual((code, played), (1, 0))


if __name__ == "__main__":
    unittest.main()
