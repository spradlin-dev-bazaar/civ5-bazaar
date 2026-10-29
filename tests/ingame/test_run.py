"""Tests for run.py and the checks files it plays, without the game: each file reads, and names only the mods and
plugins package.py builds, and the test mods are removed afterwards."""

import contextlib
import io
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from fakes import files, mods, write_files, write_mod

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


class RemoveTestModsTest(unittest.TestCase):
    def setUp(self):
        self.user = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.user)
        self.test_build = "Bazaar (v %d)" % files.TEST_VERSION

    def remove(self, running=()):
        printed = io.StringIO()
        with (
            mock.patch.object(run.game, "game_processes", return_value=list(running)),
            contextlib.redirect_stdout(printed),
        ):
            run.remove_test_mods(files.PlayerFiles(self.user))
        return printed.getvalue()

    def write_mods(self):
        toy = run.package.TOYS[0]
        write_mod(os.path.join(self.user, "MODS", toy.mod_name + " (v 1)"), toy.mod_id)
        write_mod(os.path.join(self.user, "MODS", "Toy VMC Check (v 1)"), run.package.VMC_CHECK_ID)
        write_mod(os.path.join(self.user, "MODS", self.test_build), mods.HOST_ID, files.TEST_VERSION)
        write_mod(os.path.join(self.user, "MODS", "Player Mod (v 2)"), "player-mod", 2)
        write_files(os.path.join(self.user, "MODS", "Broken Mod"), {"Broken.modinfo": b"not xml"})

    def test_only_the_test_mods_are_removed(self):
        self.write_mods()
        self.assertEqual(self.remove(), "removed the test mods from MODS: Toy Gold Plugin (v 1), Toy VMC Check (v 1)\n")
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.user, "MODS"))), [self.test_build, "Broken Mod", "Player Mod (v 2)"]
        )

    def test_nothing_is_removed_while_the_game_still_runs(self):
        self.write_mods()
        printed = self.remove(running=["civilizationv_dx11.exe"])
        self.assertEqual(printed, "Civilization V is still running, so the test mods stay in MODS\n")
        self.assertEqual(len(os.listdir(os.path.join(self.user, "MODS"))), 5)

    def test_no_mods_folder_is_named_not_raised(self):
        self.assertIn("the test mods could not be removed", self.remove())


class MainTest(unittest.TestCase):
    def main(self, argv, outcomes=None, built=0):
        printed = io.StringIO()
        with (
            mock.patch.object(run.package, "main", return_value=built) as build,
            mock.patch.object(run.runner, "run", side_effect=outcomes or []) as play,
            mock.patch.object(run.game, "Game"),
            mock.patch.object(run, "remove_test_mods") as remove,
            mock.patch.object(run.files, "user_folder", return_value="user"),
            contextlib.redirect_stdout(printed),
        ):
            code = run.main(argv)
        return code, printed.getvalue(), build.called, play.call_count, remove.called

    def test_a_checks_file_that_does_not_read_stops_before_anything_is_built(self):
        code, printed, built, _, _ = self.main(["no_such_check"])
        self.assertEqual(code, 1)
        self.assertIn("no_such_check.toml could not be read", printed)
        self.assertFalse(built)

    def test_every_file_is_played_and_the_test_mods_removed_even_after_a_failure(self):
        code, printed, built, played, removed = self.main(["crash_lua", "use_both"], ["failed.", None])
        self.assertEqual((code, built, played, removed), (1, True, 2, True))
        self.assertIn("1 of 2 checks files passed: failed crash_lua", printed)

    def test_a_failed_build_plays_nothing(self):
        code, _, _, played, _ = self.main(["use_both"], built=1)
        self.assertEqual((code, played), (1, 0))


if __name__ == "__main__":
    unittest.main()
