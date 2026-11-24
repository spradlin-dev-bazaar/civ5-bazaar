"""Checks of tools/new_version.py: the edits release.py start makes to the files that name a branch's version of Bazaar,
made on copies of the real files.

python -m unittest discover -s tests/release
"""

import os
import re
import shutil
import sys
import tempfile
import unittest
from xml.etree import ElementTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))

import new_version  # noqa: E402

MOD_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
# A name no branch's templates have, so that each test changes the template's name.
NAME = "Bazaar 9.9 - Multi-DLL Mod Loader"


def lines_of(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read().splitlines(keepends=True)


class NewVersionTest(unittest.TestCase):
    def copy(self, path):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        copied = os.path.join(folder, os.path.basename(path))
        shutil.copyfile(path, copied)
        return copied

    def added_lines(self, before, after):
        """after's lines that before lacks, when after is before with lines added."""
        remaining = list(before)
        added = []
        for line in after:
            if remaining and line == remaining[0]:
                remaining.pop(0)
            else:
                added.append(line)
        self.assertEqual(remaining, [], "lines were changed or removed, not only added")
        return added

    def test_the_version_is_added_at_the_end_of_bazaar_versions(self):
        path = self.copy(new_version.COMMON_PY)
        before = lines_of(path)
        new_version.add_to_bazaar_versions("0.6", MOD_ID, False, path)
        after = lines_of(path)
        added = self.added_lines(before, after)
        self.assertEqual(added, ['    "0.6": BazaarVersion("%s", False, None),\n' % MOD_ID])
        self.assertEqual(after[after.index(added[0]) + 1], "}\n")
        new_version.add_to_bazaar_versions("1.0", MOD_ID, True, path)
        self.assertIn('    "1.0": BazaarVersion("%s", True, None),\n' % MOD_ID, lines_of(path))

    def test_both_build_scripts_list_the_version_last_with_its_mod_id(self):
        for script in new_version.BUILD_SCRIPTS:
            with self.subTest(script=script):
                path = self.copy(script)
                before = lines_of(path)
                new_version.add_to_build_script("0.6", MOD_ID, path)
                self.assertEqual(self.added_lines(before, lines_of(path)), ["    '0.6' = '%s'\n" % MOD_ID])
                listed = re.findall(r"^    '(\d+\.\d+)' = '([0-9a-f-]+)'$", "".join(lines_of(path)), re.M)
                self.assertEqual(listed[-1], ("0.6", MOD_ID))

    def test_the_guide_s_table_of_mod_ids_gets_the_version_last(self):
        path = self.copy(new_version.GUIDE)
        before = lines_of(path)
        new_version.add_to_guide_table("0.6", MOD_ID, path)
        added = self.added_lines(before, lines_of(path))
        self.assertEqual(added, ["| 0.6 | `%s` |\n" % MOD_ID])
        after = lines_of(path)
        self.assertTrue(re.match(r"\| \d+\.\d+ \| `", after[after.index(added[0]) - 1]))

    def test_both_templates_depend_on_the_new_version_and_nothing_else_changes(self):
        msbuild = new_version.MSBUILD
        for project in new_version.TEMPLATE_PROJECTS:
            with self.subTest(project=project):
                path = self.copy(project)
                before = lines_of(path)
                new_version.set_template_dependency(MOD_ID, NAME, path)
                after = lines_of(path)
                self.assertEqual(len(after), len(before))
                self.assertEqual(sum(1 for old, new in zip(before, after) if old != new), 2)
                mods = [
                    (a.findtext(msbuild + "Id"), a.findtext(msbuild + "Name"))
                    for a in ElementTree.parse(path).getroot().iter(msbuild + "Association")
                    if a.findtext(msbuild + "Type") == "Mod"
                ]
                self.assertEqual(mods, [(MOD_ID, NAME)])

    def test_a_template_that_depends_on_no_known_bazaar_stops(self):
        path = self.copy(new_version.TEMPLATE_PROJECTS[0])
        new_version.set_template_dependency(MOD_ID, NAME, path)
        with self.assertRaises(SystemExit) as stop:
            new_version.set_template_dependency(MOD_ID, NAME, path)
        self.assertIn("does not depend on exactly one version of Bazaar", str(stop.exception))

    def test_a_file_without_its_list_stops(self):
        path = self.copy(new_version.BUILD_SCRIPTS[0])
        with open(path, "w") as f:
            f.write("$other = @{\n}\n")
        with self.assertRaises(SystemExit) as stop:
            new_version.add_to_build_script("0.6", MOD_ID, path)
        self.assertIn("has no $bazaarVersions list to add to", str(stop.exception))

    def test_a_file_with_windows_line_ends_keeps_them(self):
        path = self.copy(new_version.COMMON_PY)
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read().replace("\n", "\r\n")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        new_version.add_to_bazaar_versions("0.6", MOD_ID, False, path)
        with open(path, encoding="utf-8", newline="") as f:
            after = f.read()
        self.assertIn('    "0.6": BazaarVersion("%s", False, None),\r\n}\r\n' % MOD_ID, after)
        self.assertNotIn("\n", after.replace("\r\n", ""))


if __name__ == "__main__":
    unittest.main()
