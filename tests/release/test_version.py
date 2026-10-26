"""Checks of tools/version.py: reading VERSION and the numbers that must follow it.

python -m unittest discover -s tests/release
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))

import version  # noqa: E402


def write(folder, text, newline="\n", encoding="utf-8"):
    path = os.path.join(folder, "VERSION")
    with open(path, "w", encoding=encoding, newline=newline) as f:
        f.write(text)
    return path


class ReadTest(unittest.TestCase):
    def test_a_release_and_a_mod_version_are_read(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(version.read(write(folder, "release 1.12.0\nmod 7\n")), ("1.12.0", 7))

    def test_windows_line_ends_are_read(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(version.read(write(folder, "release 0.3.0\nmod 1\n", "\r\n")), ("0.3.0", 1))

    def test_a_byte_order_mark_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(folder, "release 0.3.0\nmod 1\n", encoding="utf-8-sig")
            self.assertEqual(version.read(path), ("0.3.0", 1))

    def test_a_malformed_file_stops(self):
        for text in [
            "release 0.3\nmod 1\n",
            "release 0.03.0\nmod 1\n",
            "release 0.3.0\nmod 0\n",
            "mod 1\nrelease 0.3.0\n",
            "release 0.3.0\n",
            "release 0.3.0\nmod 1\nextra\n",
            "release 0.3.0 \nmod 1\n",
        ]:
            with tempfile.TemporaryDirectory() as folder, self.subTest(text=text):
                with self.assertRaises(SystemExit) as stop:
                    version.read(write(folder, text))
                self.assertIn("is not 'release <major.minor.patch>'", str(stop.exception))
                self.assertIn("it reads %r" % text, str(stop.exception))


class OldestBazaarTest(unittest.TestCase):
    def test_a_plugin_needs_the_first_release_with_its_api_version(self):
        self.assertEqual(version.oldest_bazaar("0.4.2"), "0.4.0")
        self.assertEqual(version.oldest_bazaar("1.12.3"), "1.12.0")


class DisagreementTest(unittest.TestCase):
    def test_matching_numbers_agree(self):
        self.assertEqual(version.disagreements(version.Version("0.3.2", 1), (0, 3), "0.3.2"), [])

    def test_an_api_version_that_differs_is_named(self):
        found = version.disagreements(version.Version("0.4.0", 1), (0, 3), "0.4.0")
        self.assertEqual(len(found), 1)
        self.assertIn("plugin API version", found[0])
        self.assertIn("is 0.3, not 0.4", found[0])

    def test_a_claude_plugin_version_that_differs_is_named(self):
        found = version.disagreements(version.Version("0.3.1", 1), (0, 3), "0.3.0")
        self.assertEqual(len(found), 1)
        self.assertIn("Claude plugin's version", found[0])
        self.assertIn("is 0.3.0, not 0.3.1", found[0])

    def test_a_missing_claude_plugin_version_is_named(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "plugin.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"name": "civ5-bazaar"}')
            found = version.disagreements(version.Version("0.3.1", 1), (0, 3), version.plugin_version(path))
        self.assertEqual(
            found,
            ["the Claude plugin's version in %s is missing, not 0.3.1" % version.common.shown(version.PLUGIN_JSON)],
        )

    def test_a_plugin_template_that_names_another_bazaar_is_named(self):
        found = version.template_disagreements("0.5.0", ("0.4.0", ["0.5.0"]))
        self.assertEqual(len(found), 1)
        self.assertIn("plugin template needs", found[0])
        self.assertIn("is 0.4.0, not 0.5.0", found[0])

    def test_a_workshop_description_that_requires_another_bazaar_is_named(self):
        for required, words in (
            (["0.4.0"], "says 'Requires Bazaar 0.4.0 or newer.', not 0.5.0"),
            ([], "does not say 'Requires Bazaar 0.5.0 or newer.'"),
        ):
            with self.subTest(required=required):
                found = version.template_disagreements("0.5.0", ("0.5.0", required))
                self.assertEqual(len(found), 1)
                self.assertIn(words, found[0])

    def test_the_check_covers_the_plugin_template(self):
        with mock.patch.object(version, "template_bazaar", return_value=("0.1.0", ["0.1.0"])):
            found = version.check()[1]
        self.assertTrue(any("plugin template needs" in problem for problem in found), found)

    def test_this_repository_agrees_with_itself(self):
        self.assertEqual(version.check()[1], [], "run python tools/version.py and fix what it names")


class EditTest(unittest.TestCase):
    def test_written_numbers_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "VERSION")
            version.write(version.Version("1.2.3", 4), path)
            self.assertEqual(version.read(path), ("1.2.3", 4))

    def test_the_claude_plugin_version_is_set_and_its_line_ends_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            text = '{\n  "name": "civ5-bazaar",\n  "version": "0.3.0",\n  "author": { "name": "x" }\n}\n'
            path = write(folder, text, "\r\n")
            version.set_plugin_version("0.4.0", path)
            with open(path, newline="") as f:
                self.assertEqual(f.read(), text.replace("0.3.0", "0.4.0").replace("\n", "\r\n"))

    def test_the_plugin_templates_bazaar_is_set_in_both_files_and_nothing_else_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            version_text = "release 1\nbazaar 0.4.0\n"
            workshop_text = (
                "[h1]Template Plugin[/h1]\r\nA plugin.\r\n\r\nRequires Bazaar 0.4.0 or newer. Subscribe too.\r\n"
            )
            version_path = write(folder, version_text)
            workshop_path = os.path.join(folder, "workshop-description.txt")
            with open(workshop_path, "w", encoding="utf-8", newline="") as f:
                f.write(workshop_text)
            version.set_template_bazaar("0.5.0", version_path, workshop_path)
            with open(version_path, newline="") as f:
                self.assertEqual(f.read(), version_text.replace("0.4.0", "0.5.0"))
            with open(workshop_path, newline="") as f:
                self.assertEqual(f.read(), workshop_text.replace("0.4.0", "0.5.0"))
            self.assertEqual(version.template_bazaar(version_path, workshop_path), ("0.5.0", ["0.5.0"]))

    def test_a_template_file_with_nothing_to_set_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            version_path = write(folder, "release 1\nbazaar 0.4.0\n")
            workshop_path = os.path.join(folder, "workshop-description.txt")
            with open(workshop_path, "w", encoding="utf-8") as f:
                f.write("A plugin.\n")
            with self.assertRaises(SystemExit) as stop:
                version.set_template_bazaar("0.5.0", version_path, workshop_path)
            self.assertIn("does not name a Bazaar release to set", str(stop.exception))
            with open(version_path, newline="") as f:
                self.assertEqual(f.read(), "release 1\nbazaar 0.4.0\n", "VERSION changed before the stop")

    def test_a_bazaar_line_with_more_spaces_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            version_path = write(folder, "release 1\nbazaar  0.4.0\n")
            workshop_path = os.path.join(folder, "workshop-description.txt")
            with open(workshop_path, "w", encoding="utf-8") as f:
                f.write("Requires Bazaar 0.4.0 or newer.\n")
            self.assertEqual(version.template_bazaar(version_path, workshop_path), ("0.4.0", ["0.4.0"]))


if __name__ == "__main__":
    unittest.main()
