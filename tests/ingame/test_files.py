"""Tests for the player's folder as the checks use it: mod descriptions, installing into MODS, and the copies that put
the plugin order and the autosaves back."""

import os
import shutil
import stat
import tempfile
import time
import unittest
from unittest import mock
from xml.etree import ElementTree

from fakes import (
    HERE,
    FakeClock,
    PLAYER_AUTOSAVES,
    files,
    mods,
    read_files,
    rotate_autosaves,
    use_own_temp,
    write_files,
    write_mod,
)

import version


def host_source(name):
    with open(os.path.join(HERE, "..", "..", "host", name), encoding="latin-1") as f:
        return f.read()


class ModInfoTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)

    def test_a_mod_folder_gives_its_id_and_version_even_with_brackets_in_its_path(self):
        folder = write_mod(os.path.join(self.root, "A [test] mod"), "abc", version=3)
        self.assertEqual(files.mod_key(folder), ("abc", 3))

    def test_dependencies_on_any_version_or_one_come_with_their_title_and_range(self):
        folder = write_mod(
            os.path.join(self.root, "Plugin"), "plugin", dependencies=[("bazaar", "Bazaar"), ("vmc", "VMC", 97)]
        )
        info = files.read_modinfo(folder)
        self.assertEqual(info.name, "A Mod")
        self.assertEqual(info.dependencies, [("bazaar", "Bazaar", 0, files.ANY_VERSION), ("vmc", "VMC", 97, 97)])

    def test_test_builds_are_above_every_release_and_inside_any_version(self):
        any_version = ElementTree.fromstring(mods.mod_line("bazaar", "Bazaar"))
        self.assertLess(version.read().mod, files.TEST_VERSION)
        self.assertEqual(files.ANY_VERSION, int(any_version.get("maxversion")))
        self.assertLess(files.TEST_VERSION, files.ANY_VERSION)
        self.assertEqual(files.TAR, mods.TAR)

    def test_no_or_several_descriptions_give_none(self):
        empty = os.path.join(self.root, "empty")
        os.makedirs(empty)
        self.assertIsNone(files.mod_key(empty))
        twice = write_mod(os.path.join(self.root, "twice"), "abc")
        mods.write_modinfo(twice, "Other", "def", "x", [], [])
        self.assertIsNone(files.mod_key(twice))

    def test_a_broken_description_is_a_check_error(self):
        folder = os.path.join(self.root, "broken")
        os.makedirs(folder)
        with open(os.path.join(folder, "Broken.modinfo"), "w") as f:
            f.write("<Mod id='x' version='one'>")
        with self.assertRaises(files.CheckError):
            files.mod_key(folder)

    def test_mod_folders_finds_every_copy_and_skips_broken_ones(self):
        first = write_mod(os.path.join(self.root, "Bazaar (v 6)"), "bazaar", version=6)
        second = write_mod(os.path.join(self.root, "Bazaar test"), "bazaar", version=6)
        write_mod(os.path.join(self.root, "Bazaar (v 5)"), "bazaar", version=5)
        broken = os.path.join(self.root, "broken")
        os.makedirs(broken)
        with open(os.path.join(broken, "Broken.modinfo"), "w") as f:
            f.write("not xml")
        self.assertEqual(files.mod_folders(self.root, ("bazaar", 6)), [first, second])


class PluginOrderTest(unittest.TestCase):
    def test_order_lines_are_the_ones_bazaar_reads(self):
        """Bazaar reads load or skip, the DLL, its name and version, then the plugins to use both with. The lines
        looked for are where CivHostOrder.cpp reads them: if it was rewritten, check the format by hand."""
        parser = host_source("CivHostOrder.cpp")
        for line in ('kLoad = "load"', 'kSkip = "skip"', "entry.file = fields[1];", "for (size_t j = 4;"):
            self.assertIn(line, parser)
        self.assertEqual(files.order_line("MCPServer.dll"), "load\tMCPServer.dll\t\t\r\n")
        entry = {"file": "A.dll", "skip": True, "use_both_with": ["B.dll", "C.dll"]}
        self.assertEqual(files.order_line(entry), "skip\tA.dll\t\t\tB.dll\tC.dll\r\n")

    def test_the_plugin_order_file_is_the_one_bazaar_reads(self):
        self.assertIn('"\\\\%s"' % files.ORDER_FILE.replace("\\", "\\\\"), host_source("CivHostEngine.cpp"))

    def test_entries_are_dll_names_or_tables_with_a_file(self):
        self.assertIsNone(files.order_entry_problem("A.dll"))
        self.assertIsNone(files.order_entry_problem({"file": "A.dll", "skip": True, "use_both_with": ["B.dll"]}))
        for entry, why in (
            (1, "neither a DLL's name nor a table"),
            ({"file": "A.dll", "first": True}, "does not take first"),
            ({"file": "A.dll", "skip": "no"}, "skip is not true or false"),
            ({"file": "A.dll", "use_both_with": "B.dll"}, "use_both_with is not a list"),
            ({"file": "A.dll", "use_both_with": 5}, "use_both_with is not a list"),
            ({"file": "A.dll", "use_both_with": [5]}, "use_both_with is not a list"),
        ):
            with self.subTest(entry=entry):
                self.assertIn(why, files.order_entry_problem(entry))


class PlayerFolderTest(unittest.TestCase):
    def setUp(self):
        self.user = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.user)
        os.makedirs(os.path.join(self.user, "MODS"))
        self.said = []
        self.files = files.PlayerFiles(self.user, self.said.append)

    def path(self, *parts):
        return os.path.join(self.user, *parts)


class InstallTest(PlayerFolderTest):
    def install(self, *sources):
        return self.files.install(self.stage(*sources))

    def stage(self, *sources):
        staging = os.path.join(self.user, "staging")
        os.makedirs(staging, exist_ok=True)
        return self.files.stage_all(list(sources), staging)

    def test_only_the_folders_installing_replaces_or_adds_are_changed(self):
        mine = write_mod(self.path("MODS", "My Mod (v 1)"), "mine")
        built = write_mod(self.path("build", "Template Plugin"), "template")
        self.assertEqual(self.files.changed_by(self.stage(mine, built)), ["Template Plugin"])

    @unittest.skipUnless(os.path.isfile(files.TAR), "needs Windows' tar.exe")
    def test_a_package_is_unpacked_and_installed_under_the_name_the_game_gives_it(self):
        built = write_mod(self.path("build"), "bazaar", files.TEST_VERSION, "Bazaar", [("Bazaar.dll", "new")])
        package = self.path("Bazaar-0.6.0.civ5mod")
        self.assertIsNone(mods.pack(built, package))
        (expected,) = self.install(package)
        self.assertEqual(files.mod_key(expected), ("bazaar", files.TEST_VERSION))
        self.assertEqual(self.files.installed_problems([expected]), [])
        self.assertTrue(os.path.isfile(self.path("MODS", "Bazaar (v %d)" % files.TEST_VERSION, "Bazaar.dll")))

    @unittest.skipUnless(os.path.isfile(files.TAR), "needs Windows' tar.exe")
    def test_a_package_that_will_not_unpack_is_named(self):
        package = self.path("Broken.civ5mod")
        with open(package, "wb") as f:
            f.write(b"not a package")
        with self.assertRaisesRegex(files.CheckError, "Broken.civ5mod could not be unpacked"):
            self.install(package)

    def test_a_missing_path_is_named_as_missing(self):
        with self.assertRaisesRegex(files.CheckError, "Template Plugin does not exist"):
            self.install(self.path("build", "Template Plugin"))

    def test_nothing_is_installed_when_any_source_has_no_mod_description(self):
        good = write_mod(self.path("build", "Good"), "good")
        empty = self.path("build", "Template Plugin")
        os.makedirs(empty)
        with self.assertRaisesRegex(files.CheckError, "Template Plugin holds no mod description, or more than one"):
            self.install(good, empty)
        self.assertEqual(os.listdir(self.path("MODS")), [])

    def test_a_mod_already_in_mods_is_checked_where_it_is(self):
        mine = write_mod(self.path("MODS", "My Mod (v 1)"), "mine", content=[("My.lua", "print(1)")])
        self.assertEqual(self.install(mine), [mine])
        self.assertEqual(read_files(mine), {"My.lua": b"print(1)", "A Mod (v 1).modinfo": mock.ANY})

    def test_a_folder_replaces_one_of_the_same_mod(self):
        old = write_mod(self.path("MODS", "Template Plugin"), "template")
        with open(os.path.join(old, "stale.txt"), "w") as f:
            f.write("old")
        new = write_mod(self.path("build", "Template Plugin"), "template")
        self.assertEqual(self.install(new), [new])
        self.assertFalse(os.path.exists(self.path("MODS", "Template Plugin", "stale.txt")))
        self.assertEqual(files.mod_key(self.path("MODS", "Template Plugin")), ("template", 1))

    def test_two_mods_that_go_into_one_folder_in_mods_are_refused(self):
        first = write_mod(self.path("build", "Template Plugin"), "template")
        second = write_mod(self.path("other", "Template Plugin"), "template")
        with self.assertRaisesRegex(files.CheckError, "mods lists two that go into the same folder in MODS"):
            self.stage(first, second)

    def test_a_package_whose_mod_name_cannot_be_a_folder_name_is_refused(self):
        package = self.path("Odd.civ5mod")
        write_files(self.user, {"Odd.civ5mod": b"a package"})
        with (
            mock.patch.object(files, "unpack", return_value=self.path("staging", "Odd.civ5mod")),
            mock.patch.object(files, "read_modinfo", return_value=files.ModInfo("odd", 1, "Odd/Mod", [])),
        ):
            with self.assertRaisesRegex(files.CheckError, "names its mod Odd/Mod, which cannot be a folder name"):
                self.stage(package)

    def test_a_folder_never_replaces_another_mod(self):
        write_mod(self.path("MODS", "Template Plugin"), "someone-elses")
        new = write_mod(self.path("build", "Template Plugin"), "template")
        with self.assertRaisesRegex(files.CheckError, "different mod"):
            self.install(new)
        self.assertEqual(files.mod_key(self.path("MODS", "Template Plugin")), ("someone-elses", 1))


class InstalledProblemsTest(PlayerFolderTest):
    def setUp(self):
        super().setUp()
        self.expected = write_mod(self.path("package"), "bazaar", 6, content=[("Bazaar.dll", "new")])

    def put(self, name, content="new", version=6):
        return write_mod(self.path("MODS", name), "bazaar", version, content=[("Bazaar.dll", content)])

    def test_one_copy_as_packaged_is_fine(self):
        self.put("Bazaar (v 6)")
        self.put("Bazaar (v 5)", content="old", version=5)
        self.assertEqual(self.files.installed_problems([self.expected]), [])

    def test_a_second_copy_of_the_same_version_is_named(self):
        self.put("Bazaar (v 6)")
        test_build = self.put("Bazaar test build")
        (problem,) = self.files.installed_problems([self.expected])
        self.assertIn("2 copies of A Mod (v 6)", problem)
        self.assertIn(test_build, problem)

    def test_a_copy_that_changed_since_it_was_installed_is_named(self):
        self.put("Bazaar (v 6)", content="a different build")
        (problem,) = self.files.installed_problems([self.expected])
        self.assertIn("is not the build in package", problem)
        self.assertIn("Bazaar.dll", problem)
        self.assertIn("something changed it after the check put it there", problem)

    def test_no_copy_is_named(self):
        (problem,) = self.files.installed_problems([self.expected])
        self.assertEqual(problem, "MODS holds no copy of A Mod (v 6)")


class CopiesTest(PlayerFolderTest):
    def setUp(self):
        super().setUp()
        self.temp = use_own_temp(self)

    def write(self, name, content):
        write_files(self.user, {name: content})

    def read(self, name):
        with open(self.path(name), "rb") as f:
            return f.read()

    def copy_aside(self, player_files=None, **lists):
        copies = (player_files or self.files).copy_aside(**lists)
        self.addCleanup(shutil.rmtree, copies.folder, True)
        return copies

    def stopped_run(self, **lists):
        return self.copy_aside(files.PlayerFiles(self.user, say=lambda text: None), **lists)

    def stopped_long_ago(self, copies, *changed):
        """As if the run stopped, after changing these, long enough ago that later changes are the player's."""
        then = time.time() - files.SINCE_MARGIN - 60
        for path in (os.path.join(copies.folder, files.HEARTBEAT),) + changed:
            os.utime(path, (then, then))

    def copy_of(self, copies, rel):
        (item,) = [item for item in copies.items if item.rel == rel]
        return os.path.join(copies.folder, item.copy)

    def note(self, copies):
        with open(os.path.join(copies.folder, files.WHERE_THEY_GO), encoding="utf-8", newline="") as f:
            return f.read().split("\r\n")

    def test_autosaves_rotated_by_the_checks_game_come_back_as_they_were(self):
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        copies = self.copy_aside()
        rotate_autosaves(self.user)
        self.assertEqual(self.files.put_back(copies), [])
        self.assertEqual(read_files(self.path(files.AUTOSAVES)), PLAYER_AUTOSAVES)
        self.assertFalse(os.path.exists(copies.folder))

    def test_where_the_copies_are_is_said_before_anything_changes(self):
        self.write(files.ORDER_FILE, b"load\tMCPServer.dll\t\t\r\n")
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        copies = self.copy_aside()
        self.assertEqual(
            self.said, ["copies of your plugin order and autosaves are kept in %s until this run ends" % copies.folder]
        )

    def test_config_ini_gets_the_seeds_and_comes_back_as_it_was(self):
        config = b"[CONFIG]\r\nSyncRandSeed = 0\r\n; maps\r\nMapRandSeed=0\r\nEnableTuner = 1\r\n"
        self.write(files.CONFIG, config)
        self.write(files.ORDER_FILE, b"")
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        copies = self.copy_aside()
        self.assertIn("copies of your plugin order, config.ini and autosaves are kept in", self.said[0])
        self.files.use_seed(42)
        seeded = b"[CONFIG]\r\nSyncRandSeed = 42\r\n; maps\r\nMapRandSeed = 42\r\nEnableTuner = 1\r\n"
        self.assertEqual(self.read(files.CONFIG), seeded)
        self.assertEqual(self.files.put_back(copies), [])
        self.assertEqual(self.read(files.CONFIG), config)

    def test_a_windowed_run_s_display_settings_come_back_as_they_were(self):
        graphics = b"[Video]\r\nFullScreen = 1\r\nWindowResX = 1280\r\n"
        self.write(files.GRAPHICS, graphics)
        copies = self.copy_aside(graphics=True)
        self.files.use_windowed()
        self.assertEqual(self.read(files.GRAPHICS), b"[Video]\r\nFullScreen = 0\r\nWindowResX = 1280\r\n")
        self.assertEqual(self.files.put_back(copies, autosaves_touched=False), [])
        self.assertEqual(self.read(files.GRAPHICS), graphics)

    def test_display_settings_are_left_out_of_a_run_that_does_not_change_them(self):
        self.write(files.GRAPHICS, b"FullScreen = 1\r\n")
        copies = self.copy_aside()
        self.assertNotIn(files.GRAPHICS, [item.rel for item in copies.items])

    def test_display_settings_without_a_full_screen_line_are_named(self):
        with self.assertRaisesRegex(files.CheckError, "GraphicsSettingsDX11.ini has no FullScreen line"):
            self.files.use_windowed()

    def test_a_config_ini_without_a_seed_line_is_named(self):
        self.write(files.CONFIG, b"[CONFIG]\r\nSyncRandSeed = 0\r\n")
        with self.assertRaisesRegex(files.CheckError, "config.ini has no MapRandSeed line"):
            self.files.use_seed(1)

    def test_the_plugin_order_is_copied_to_disk_before_the_check_changes_it(self):
        self.write(files.ORDER_FILE, b"load\tMCPServer.dll\t\t\r\n")
        copies = self.copy_aside()
        self.files.use_plugin_order(["TemplatePlugin.dll"])
        self.assertEqual(self.read(files.ORDER_FILE), b"load\tTemplatePlugin.dll\t\t\r\n")
        with open(self.copy_of(copies, files.ORDER_FILE), "rb") as f:
            self.assertEqual(f.read(), b"load\tMCPServer.dll\t\t\r\n")

    def test_with_no_autosaves_before_the_checks_own_are_removed(self):
        copies = self.copy_aside()
        write_files(self.path(files.AUTOSAVES), {"AutoSave_Initial_0000 BC-4000.Civ5Save": b"the check's game"})
        self.assertEqual(self.files.put_back(copies), [])
        self.assertFalse(os.path.exists(self.path(files.AUTOSAVES)))

    def test_autosaves_no_game_touched_are_left_as_they_are(self):
        copies = self.copy_aside()
        write_files(self.path(files.AUTOSAVES), {"AutoSave_0004 BC-3820.Civ5Save": b"saved since"})
        self.assertEqual(self.files.put_back(copies, autosaves_touched=False), [])
        self.assertEqual(read_files(self.path(files.AUTOSAVES)), {"AutoSave_0004 BC-3820.Civ5Save": b"saved since"})
        self.assertFalse(os.path.exists(copies.folder))

    def test_what_the_game_holds_waits_for_it_to_close_but_the_plugin_order_goes_back(self):
        self.write(files.MODS_DATABASE, b"the player's mods")
        self.write(files.CONFIG, b"SyncRandSeed = 0\r\nMapRandSeed = 0\r\n")
        self.write(files.ORDER_FILE, b"skip\tA.dll\t\t\r\n")
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        copies = self.copy_aside(mods=["Added Mod"])
        self.write(files.MODS_DATABASE, b"the check's mods")
        self.files.use_seed(1)
        self.files.use_plugin_order([])
        rotate_autosaves(self.user)
        write_mod(self.path("MODS", "Added Mod"), "added")
        running, kept = self.files.put_back(copies, game_running=True)
        self.assertEqual(
            running,
            "Civilization V is still running, so these wait to be put back: Mods menu choices, config.ini, autosaves"
            " and mod folder Added Mod",
        )
        self.assertTrue(kept.startswith("the copies stay in %s, " % copies.folder))
        self.assertEqual(self.read(files.ORDER_FILE), b"skip\tA.dll\t\t\r\n")
        self.assertEqual(self.read(files.MODS_DATABASE), b"the check's mods")
        self.assertEqual(self.read(files.CONFIG), b"SyncRandSeed = 1\r\nMapRandSeed = 1\r\n")
        self.assertTrue(os.path.isdir(self.path("MODS", "Added Mod")))
        self.assertEqual(read_files(self.copy_of(copies, files.AUTOSAVES)), PLAYER_AUTOSAVES)

    def test_saves_and_mod_folders_a_check_changes_come_back(self):
        write_files(self.user, {files.save_rel("Kept"): b"the player's"})
        write_mod(self.path("MODS", "Kept Mod"), "kept", content=[("Kept.lua", "the player's")])
        copies = self.copy_aside(saves=["Kept", "New"], mods=["Kept Mod", "Added Mod"])
        write_files(self.user, {files.save_rel("Kept"): b"the check's", files.save_rel("New"): b"the check's"})
        shutil.rmtree(self.path("MODS", "Kept Mod"))
        write_mod(self.path("MODS", "Kept Mod"), "kept", content=[("Kept.lua", "the check's")])
        write_mod(self.path("MODS", "Added Mod"), "added")
        self.assertEqual(self.files.put_back(copies, autosaves_touched=False), [])
        self.assertEqual(self.read(files.save_rel("Kept")), b"the player's")
        self.assertFalse(os.path.exists(self.path(files.save_rel("New"))))
        self.assertEqual(os.listdir(self.path("MODS")), ["Kept Mod"])
        self.assertEqual(self.read(os.path.join("MODS", "Kept Mod", "Kept.lua")), b"the player's")

    def test_a_running_check_marks_itself_as_going(self):
        copies = self.copy_aside()
        heartbeat = os.path.join(copies.folder, files.HEARTBEAT)
        os.utime(heartbeat, (1000, 1000))
        self.files.beat()
        self.assertGreater(os.path.getmtime(heartbeat), 1000)

    def test_hand_back_reaches_only_a_run_waiting_for_its_game_and_waits_for_it_to_take_it(self):
        self.assertFalse(files.hand_back())
        copies = self.copy_aside()
        before = sorted(os.listdir(copies.folder))
        self.assertFalse(files.hand_back())
        self.assertFalse(self.files.handed_back())
        self.files.begin_hand_over()
        clock, taken = FakeClock(), []

        def the_run_takes_it_back(seconds):
            taken.append(self.files.handed_back())
            self.files.end_hand_over()

        clock.sleep = the_run_takes_it_back
        with mock.patch.object(files, "time", clock):
            self.assertTrue(files.hand_back())
        self.assertEqual(taken, [True])
        self.assertFalse(files.hand_back())
        self.assertEqual(sorted(os.listdir(copies.folder)), before)

    def test_hand_back_to_a_run_killed_during_its_hand_over_says_no_run_took_it(self):
        self.copy_aside()
        self.files.begin_hand_over()
        with mock.patch.object(files, "time", FakeClock()):
            self.assertFalse(files.hand_back())
        self.assertFalse(self.files.handed_back())

    def test_a_hand_back_left_from_an_earlier_hand_over_does_not_end_the_next(self):
        self.copy_aside()
        open(os.path.join(self.files.running, files.HAND_BACK), "wb").close()
        self.files.begin_hand_over()
        self.assertFalse(self.files.handed_back())

    def test_a_second_run_cannot_start_until_the_first_ends_and_leaves_no_lock_behind(self):
        with files.one_run_at_a_time():
            with self.assertRaisesRegex(files.CheckError, "another check is running: wait for it to end"):
                with files.one_run_at_a_time():
                    pass
        with files.one_run_at_a_time():
            pass
        self.assertEqual(os.listdir(self.temp), [])

    def test_copies_a_stopped_check_left_are_put_back_by_the_next(self):
        self.write(files.CONFIG, b"the player's settings")
        write_files(self.user, {files.save_rel("Check"): b"the player's"})
        stopped = self.stopped_run(saves=["Check"], mods=["Added Mod"])
        self.write(files.CONFIG, b"SyncRandSeed = 1")
        write_files(self.user, {files.save_rel("Check"): b"the check's"})
        write_mod(self.path("MODS", "Added Mod"), "added")
        self.files.put_back_leftovers()
        self.assertEqual(self.read(files.CONFIG), b"the player's settings")
        self.assertEqual(self.read(files.save_rel("Check")), b"the player's")
        self.assertEqual(os.listdir(self.path("MODS")), [])
        self.assertFalse(os.path.exists(stopped.folder))
        self.assertRegex(self.said[-1], "^a check started on .+ had not put your files back: they are back now$")

    def test_what_changed_after_a_check_stopped_stays_but_the_lines_it_set_go_back(self):
        self.write(files.MODS_DATABASE, b"the player's mods")
        self.write(files.CONFIG, b"SyncRandSeed = 0\r\nMapRandSeed = 0\r\nEnableTuner = 1\r\n")
        self.write(files.GRAPHICS, b"FullScreen = 1\r\nWindowResX = 1280\r\n")
        write_files(self.user, {files.save_rel("Check"): b"the player's"})
        stopped = self.stopped_run(saves=["Check"], mods=["Added Mod"], graphics=True)
        self.files.use_seed(7)
        self.files.use_windowed()
        write_files(self.user, {files.save_rel("Check"): b"the check's"})
        added = write_mod(self.path("MODS", "Added Mod"), "added")
        changed = [self.path(files.CONFIG), self.path(files.GRAPHICS), self.path(files.save_rel("Check")), added]
        self.stopped_long_ago(stopped, *changed, *[os.path.join(added, name) for name in os.listdir(added)])
        self.write(files.MODS_DATABASE, b"the check's mods, as the game rewrote them on closing")
        self.write(files.CONFIG, b"SyncRandSeed = 7\r\nMapRandSeed = 7\r\nEnableTuner = 0\r\n")
        self.write(files.GRAPHICS, b"FullScreen = 0\r\nWindowResX = 800\r\n")
        write_files(self.user, {files.save_rel("Check"): b"the player's since"})
        self.files.put_back_leftovers()
        self.assertEqual(self.read(files.MODS_DATABASE), b"the player's mods")
        self.assertEqual(self.read(files.CONFIG), b"SyncRandSeed = 0\r\nMapRandSeed = 0\r\nEnableTuner = 0\r\n")
        self.assertEqual(self.read(files.GRAPHICS), b"FullScreen = 1\r\nWindowResX = 800\r\n")
        self.assertEqual(self.read(files.save_rel("Check")), b"the player's since")
        self.assertEqual(os.listdir(self.path("MODS")), [])
        self.assertFalse(os.path.exists(stopped.folder))
        self.assertTrue(
            self.said[-1].endswith(
                "they are back now, except what changed after it stopped, which stays as it is: config.ini except its"
                ' seed lines, GraphicsSettingsDX11.ini except its FullScreen line and save "Check"; your Mods menu'
                " choices went back to how they were before it: switch on again any mods you switched on since"
            )
        )

    def test_copies_a_check_stopped_while_copying_are_deleted(self):
        stopped_while_copying = os.path.join(self.temp, files.COPIES_PREFIX + "copying")
        write_files(stopped_while_copying, {"config.ini": b"the player's"})
        self.files.put_back_leftovers()
        self.assertEqual(os.listdir(self.temp), [])

    def test_copies_of_another_civilization_v_folder_are_not_put_back_here(self):
        other = os.path.join(self.user, "another")
        os.makedirs(other)
        self.copy_aside(files.PlayerFiles(other, say=lambda text: None))
        with self.assertRaisesRegex(files.CheckError, "copies an earlier check made of .+another are still in"):
            self.files.put_back_leftovers()

    def test_copies_without_their_list_are_left_for_a_person(self):
        left = os.path.join(self.temp, files.COPIES_PREFIX + "old")
        write_files(left, {files.WHERE_THEY_GO: b"copy config.ini back"})
        with self.assertRaisesRegex(files.CheckError, 'put them back as "where these go.txt" there says'):
            self.files.put_back_leftovers()

    def test_copies_of_another_version_or_with_one_missing_are_left_for_a_person(self):
        self.write(files.CONFIG, b"the player's settings")
        stopped = self.stopped_run()
        manifest = os.path.join(stopped.folder, files.MANIFEST)
        with open(manifest, encoding="utf-8") as f:
            made = f.read()
        with open(manifest, "w", encoding="utf-8") as f:
            f.write(made.replace('"version": %d' % files.MANIFEST_VERSION, '"version": 99'))
        with self.assertRaisesRegex(files.CheckError, "cannot put them back itself"):
            self.files.put_back_leftovers()
        with open(manifest, "w", encoding="utf-8") as f:
            f.write(made)
        os.remove(self.copy_of(stopped, files.CONFIG))
        with self.assertRaisesRegex(files.CheckError, "cannot put them back itself"):
            self.files.put_back_leftovers()
        self.assertEqual(self.read(files.CONFIG), b"the player's settings")

    def test_copies_without_their_last_seen_mark_are_left_for_a_person(self):
        self.write(files.CONFIG, b"the player's settings")
        stopped = self.stopped_run()
        os.remove(os.path.join(stopped.folder, files.HEARTBEAT))
        self.write(files.CONFIG, b"SyncRandSeed = 1")
        with self.assertRaisesRegex(files.CheckError, "cannot put them back itself"):
            self.files.put_back_leftovers()
        self.assertEqual(self.read(files.CONFIG), b"SyncRandSeed = 1")

    def test_copies_that_cannot_all_be_put_back_stop_the_next_check(self):
        self.write(files.ORDER_FILE, b"skip\tA.dll\t\t\r\n")
        self.stopped_run()
        os.remove(self.path(files.ORDER_FILE))
        os.makedirs(self.path(files.ORDER_FILE))
        with self.assertRaisesRegex(files.CheckError, "putting them back failed: your plugin order could not be put"):
            self.files.put_back_leftovers()

    def test_a_plugin_order_that_cannot_be_put_back_keeps_its_copy_and_names_it(self):
        self.write(files.ORDER_FILE, b"skip\tTemplatePlugin.dll\t\t\r\n")
        copies = self.copy_aside()
        os.remove(self.path(files.ORDER_FILE))
        os.makedirs(self.path(files.ORDER_FILE))
        problem, kept = self.files.put_back(copies)
        self.assertIn("your plugin order could not be put back", problem)
        self.assertTrue(kept.startswith("the copies stay in %s, " % copies.folder))
        self.assertTrue(os.path.isfile(self.copy_of(copies, files.ORDER_FILE)))

    def test_autosaves_that_cannot_be_put_back_keep_their_copy_and_name_it(self):
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        copies = self.copy_aside()
        with mock.patch.object(files.shutil, "copytree", side_effect=PermissionError("in use")):
            problem, kept = self.files.put_back(copies)
        self.assertIn("your autosaves could not be put back (in use)", problem)
        self.assertIn(copies.folder, kept)
        self.assertEqual(read_files(self.copy_of(copies, files.AUTOSAVES)), PLAYER_AUTOSAVES)

    def test_a_copy_that_fails_part_way_leaves_no_folder_behind(self):
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        folder = self.path("copies")
        os.makedirs(folder)
        with (
            mock.patch.object(files.tempfile, "mkdtemp", return_value=folder),
            mock.patch.object(files.shutil, "copytree", side_effect=OSError("disk full")),
        ):
            with self.assertRaises(OSError):
                self.files.copy_aside()
        self.assertFalse(os.path.exists(folder))

    def test_a_plugin_order_the_check_made_is_removed_and_the_players_comes_back(self):
        copies = self.copy_aside()
        self.files.use_plugin_order([])
        self.assertEqual(self.read(files.ORDER_FILE), b"")
        self.assertEqual(self.files.put_back(copies), [])
        self.assertFalse(os.path.exists(self.path(files.ORDER_FILE)))
        self.write(files.ORDER_FILE, b"skip\tTemplatePlugin.dll\t\t\r\n")
        copies = self.copy_aside()
        self.files.use_plugin_order([])
        self.assertEqual(self.files.put_back(copies), [])
        self.assertEqual(self.read(files.ORDER_FILE), b"skip\tTemplatePlugin.dll\t\t\r\n")

    def test_copies_an_earlier_check_left_behind_stop_the_next_one(self):
        stopped_while_copying = os.path.join(self.temp, files.COPIES_PREFIX + "copying")
        write_files(stopped_while_copying, {"config.ini": b"the player's"})
        self.assertEqual(self.files.put_back(self.copy_aside()), [])
        left = os.path.join(self.temp, files.COPIES_PREFIX + "abc")
        write_files(left, {"config.ini": b"the player's", files.WHERE_THEY_GO: b"copy config.ini"})
        with self.assertRaisesRegex(files.CheckError, "copies an earlier check made are still in .+abc, and it cannot"):
            self.files.copy_aside()
        self.assertEqual(
            sorted(os.listdir(self.temp)), [os.path.basename(left), os.path.basename(stopped_while_copying)]
        )

    def test_a_copies_folder_that_cannot_be_deleted_is_named(self):
        copies = self.copy_aside()
        with mock.patch.object(files, "remove_tree", side_effect=PermissionError("in use")):
            (problem,) = self.files.put_back(copies, autosaves_touched=False)
        self.assertEqual(
            problem, "your files are back, but %s could not be deleted (in use): delete it yourself" % copies.folder
        )

    def test_the_copies_folder_says_where_each_copy_goes(self):
        self.write(files.MODS_DATABASE, b"the player's mods")
        self.write(files.ORDER_FILE, b"")
        self.write(files.CONFIG, b"")
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        lines = self.note(self.copy_aside())
        self.assertEqual(
            lines[2:],
            [
                "- your Mods menu choices: copy Civ5ModsDatabase.db into %s" % self.path("cache"),
                "- your plugin order: copy Bazaar plugin order.txt into %s" % self.path("ModUserData"),
                "- your config.ini: copy config.ini into %s" % self.user,
                "- your autosaves: put the folder auto in place of %s" % self.path(files.AUTOSAVES),
                "Then delete this folder.",
                "",
            ],
        )

    def test_the_note_says_to_delete_what_the_player_did_not_have(self):
        lines = self.note(self.copy_aside())
        none = "if it is there: it was not there before the check"
        self.assertIn("- your plugin order: delete %s %s" % (self.path(files.ORDER_FILE), none), lines)
        self.assertIn("- your autosaves: delete %s %s" % (self.path(files.AUTOSAVES), none), lines)

    def test_the_note_says_what_to_do_with_saves_and_mod_folders(self):
        write_files(self.user, {files.save_rel("Kept"): b"the player's"})
        write_mod(self.path("MODS", "Kept Mod"), "kept")
        lines = self.note(self.copy_aside(saves=["Kept", "New"], mods=["Kept Mod", "Added Mod"]))
        none = "if it is there: it was not there before the check"
        self.assertIn('- your save "Kept": copy saves\\Kept.Civ5Save into %s' % self.path(files.SAVES), lines)
        self.assertIn('- your save "New": delete %s %s' % (self.path(files.save_rel("New")), none), lines)
        kept_mod = self.path("MODS", "Kept Mod")
        self.assertIn("- your mod folder Kept Mod: put the folder mods\\Kept Mod in place of %s" % kept_mod, lines)
        self.assertIn("- your mod folder Added Mod: delete %s %s" % (self.path("MODS", "Added Mod"), none), lines)

    def test_the_mods_database_comes_back_without_the_game_s_journal(self):
        self.write(files.MODS_DATABASE, b"the player's mods")
        copies = self.copy_aside()
        self.write(files.MODS_DATABASE, b"the check's mods")
        self.write(files.MODS_DATABASE + "-journal", b"half a write")
        self.write(files.MODS_DATABASE + "-wal", b"half a write")
        self.assertEqual(self.files.put_back(copies, autosaves_touched=False), [])
        self.assertEqual(os.listdir(self.path("cache")), ["Civ5ModsDatabase.db"])
        self.assertEqual(self.read(files.MODS_DATABASE), b"the player's mods")

    def test_a_mods_database_the_game_made_is_removed(self):
        copies = self.copy_aside()
        self.write(files.MODS_DATABASE, b"the check's mods")
        self.assertEqual(self.files.put_back(copies, autosaves_touched=False), [])
        self.assertFalse(os.path.exists(self.path(files.MODS_DATABASE)))

    def test_a_mods_database_that_cannot_be_put_back_keeps_its_copy(self):
        self.write(files.MODS_DATABASE, b"the player's mods")
        copies = self.copy_aside()
        self.write(files.MODS_DATABASE, b"the check's mods")
        with mock.patch.object(files.os, "replace", side_effect=PermissionError("in use")):
            problem, kept = self.files.put_back(copies, autosaves_touched=False)
        self.assertEqual(problem, "your Mods menu choices could not be put back (in use)")
        self.assertIn(copies.folder, kept)
        with open(self.copy_of(copies, files.MODS_DATABASE), "rb") as f:
            self.assertEqual(f.read(), b"the player's mods")
        self.assertEqual(os.listdir(self.path("cache")), ["Civ5ModsDatabase.db"])

    def test_a_journal_that_cannot_be_removed_leaves_the_game_s_database_with_it(self):
        self.write(files.MODS_DATABASE, b"the player's mods")
        copies = self.copy_aside()
        self.write(files.MODS_DATABASE, b"the check's mods")
        self.write(files.MODS_DATABASE + "-journal", b"half a write")
        with mock.patch.object(files.os, "remove", side_effect=PermissionError("in use")):
            problem, _ = self.files.put_back(copies, autosaves_touched=False)
        self.assertIn("your Mods menu choices could not be put back", problem)
        self.assertEqual(self.read(files.MODS_DATABASE), b"the check's mods")

    def test_only_a_log_written_since_then_counts(self):
        self.write(os.path.join("Logs", "Bazaar.log"), b"Plugin Template Plugin 1 loaded\r\n")
        written = os.path.getmtime(self.path("Logs", "Bazaar.log"))
        self.assertEqual(self.files.log("Bazaar.log", written + 60), [])
        self.assertEqual(self.files.log("Bazaar.log", None), [])
        self.assertEqual(self.files.log("Bazaar.log", written - 60), ["Plugin Template Plugin 1 loaded"])


class RemoveTreeTest(unittest.TestCase):
    def test_read_only_files_go_too(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        write_files(folder, {os.path.join("sub", "read only.txt"): b"a mod's file"})
        os.chmod(os.path.join(folder, "sub", "read only.txt"), stat.S_IREAD)
        files.remove_tree(folder)
        self.assertFalse(os.path.exists(folder))


if __name__ == "__main__":
    unittest.main()
