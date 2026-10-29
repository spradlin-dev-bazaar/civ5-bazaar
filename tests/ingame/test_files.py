"""Tests for the player's folder as the checks use it: mod descriptions, installing into MODS, and the copies that put
the plugin order and the autosaves back."""

import os
import shutil
import tempfile
import unittest
from unittest import mock
from xml.etree import ElementTree

from fakes import PLAYER_AUTOSAVES, files, mods, read_files, rotate_autosaves, write_files, write_mod


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
        self.assertEqual(info.dependencies, [("bazaar", "Bazaar", 0, 999), ("vmc", "VMC", 97, 97)])

    def test_test_builds_are_above_every_release_and_inside_any_version(self):
        any_version = ElementTree.fromstring(mods.mod_line("bazaar", "Bazaar"))
        self.assertEqual(files.TEST_VERSION, int(any_version.get("maxversion")))
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
        self.assertEqual(files.order_line("MCPServer.dll"), "load\tMCPServer.dll\t\t\r\n")
        entry = {"file": "A.dll", "skip": True, "use_both_with": ["B.dll", "C.dll"]}
        self.assertEqual(files.order_line(entry), "skip\tA.dll\t\t\tB.dll\tC.dll\r\n")

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
        staging = os.path.join(self.user, "staging")
        os.makedirs(staging, exist_ok=True)
        return self.files.install(list(sources), staging)

    @unittest.skipUnless(os.path.isfile(files.TAR), "needs Windows' tar.exe")
    def test_a_package_is_unpacked_and_installed_under_the_name_the_game_gives_it(self):
        built = write_mod(self.path("build"), "bazaar", 999, "Bazaar", [("Bazaar.dll", "new")])
        package = self.path("Bazaar-0.6.0.civ5mod")
        self.assertIsNone(mods.pack(built, package))
        (expected,) = self.install(package)
        self.assertEqual(files.mod_key(expected), ("bazaar", 999))
        self.assertEqual(self.files.installed_problems([expected]), [])
        self.assertTrue(os.path.isfile(self.path("MODS", "Bazaar (v 999)", "Bazaar.dll")))

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
        self.assertIn("2 copies of bazaar v6", problem)
        self.assertIn(test_build, problem)

    def test_a_copy_that_changed_since_it_was_installed_is_named(self):
        self.put("Bazaar (v 6)", content="a different build")
        (problem,) = self.files.installed_problems([self.expected])
        self.assertIn("is not the build in package", problem)
        self.assertIn("Bazaar.dll", problem)
        self.assertIn("something changed it after the check put it there", problem)

    def test_no_copy_is_named(self):
        (problem,) = self.files.installed_problems([self.expected])
        self.assertEqual(problem, "MODS holds no copy of bazaar v6")


class CopiesTest(PlayerFolderTest):
    def write(self, name, content):
        write_files(self.user, {name: content})

    def read(self, name):
        with open(self.path(name), "rb") as f:
            return f.read()

    def copy_aside(self):
        copies = self.files.copy_aside()
        self.addCleanup(shutil.rmtree, copies.folder, True)
        return copies

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
            self.said, ["copies of your plugin order and autosaves are kept in %s until the check ends" % copies.folder]
        )

    def test_the_plugin_order_is_copied_to_disk_before_the_check_changes_it(self):
        self.write(files.ORDER_FILE, b"load\tMCPServer.dll\t\t\r\n")
        copies = self.copy_aside()
        self.files.use_plugin_order(["TemplatePlugin.dll"])
        self.assertEqual(self.read(files.ORDER_FILE), b"load\tTemplatePlugin.dll\t\t\r\n")
        self.assertEqual(read_files(copies.folder), {"Bazaar plugin order.txt": b"load\tMCPServer.dll\t\t\r\n"})

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

    def test_autosaves_are_left_alone_while_the_game_still_runs_and_their_copy_is_named(self):
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        copies = self.copy_aside()
        rotate_autosaves(self.user)
        running, kept = self.files.put_back(copies, game_running=True)
        self.assertIn("still running", running)
        self.assertEqual(kept, "the copies stay in %s" % copies.folder)
        self.assertEqual(read_files(copies.autosaves), PLAYER_AUTOSAVES)

    def test_with_nothing_copied_no_copies_are_named_or_left(self):
        copies = self.copy_aside()
        self.assertEqual(self.said, [])
        self.assertEqual(
            self.files.put_back(copies, game_running=True),
            ["Civilization V is still running, so the autosaves its game made stay"],
        )
        self.assertFalse(os.path.exists(copies.folder))

    def test_a_plugin_order_that_cannot_be_put_back_keeps_its_copy_and_names_it(self):
        self.write(files.ORDER_FILE, b"skip\tTemplatePlugin.dll\t\t\r\n")
        copies = self.copy_aside()
        os.remove(self.path(files.ORDER_FILE))
        os.makedirs(self.path(files.ORDER_FILE))
        problem, kept = self.files.put_back(copies)
        self.assertIn("your plugin order could not be put back", problem)
        self.assertEqual(kept, "the copies stay in %s" % copies.folder)
        self.assertTrue(os.path.isfile(os.path.join(copies.folder, "Bazaar plugin order.txt")))

    def test_autosaves_that_cannot_be_put_back_keep_their_copy_and_name_it(self):
        write_files(self.path(files.AUTOSAVES), PLAYER_AUTOSAVES)
        copies = self.copy_aside()
        with mock.patch.object(files.shutil, "copytree", side_effect=PermissionError("in use")):
            problem, kept = self.files.put_back(copies)
        self.assertIn("your autosaves could not be put back (in use)", problem)
        self.assertIn(copies.folder, kept)
        self.assertEqual(read_files(copies.autosaves), PLAYER_AUTOSAVES)

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

    def test_only_a_log_written_since_then_counts(self):
        self.write(os.path.join("Logs", "Bazaar.log"), b"Plugin Template Plugin 1 loaded\r\n")
        written = os.path.getmtime(self.path("Logs", "Bazaar.log"))
        self.assertEqual(self.files.log("Bazaar.log", written + 60), [])
        self.assertEqual(self.files.log("Bazaar.log", None), [])
        self.assertEqual(self.files.log("Bazaar.log", written - 60), ["Plugin Template Plugin 1 loaded"])


if __name__ == "__main__":
    unittest.main()
