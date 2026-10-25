"""Checks of tools/version.py: reading VERSION and the numbers that must follow it.

python -m unittest discover -s tests/release
"""

import os
import sys
import tempfile
import unittest

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
            ["the Claude plugin's version in %s is missing, not 0.3.1" % version.layouts.shown(version.PLUGIN_JSON)],
        )

    def test_this_repository_agrees_with_itself(self):
        self.assertEqual(version.check()[1], [], "run python tools/version.py and fix what it names")


API_HEADER = "#pragma once\n#define CIV_HOST_API_MAJOR 0\n#define CIV_HOST_API_MINOR 3\nstruct CivHostInfo;\n"


class EditTest(unittest.TestCase):
    def test_written_numbers_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "VERSION")
            version.write(version.Version("1.2.3", 4), path)
            self.assertEqual(version.read(path), ("1.2.3", 4))

    def test_the_api_version_is_set_and_nothing_else_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write(folder, API_HEADER, "\r\n")
            version.set_api_version(1, 0, path)
            with open(path, newline="") as f:
                expected = API_HEADER.replace("MAJOR 0", "MAJOR 1").replace("MINOR 3", "MINOR 0")
                self.assertEqual(f.read(), expected.replace("\n", "\r\n"))

    def test_a_header_without_one_of_the_api_numbers_stops(self):
        for name in ("MAJOR", "MINOR"):
            with tempfile.TemporaryDirectory() as folder, self.subTest(name=name):
                path = write(folder, API_HEADER.replace("API_" + name, "API_" + name + "_NUMBER"))
                with self.assertRaises(SystemExit) as stop:
                    version.set_api_version(1, 0, path)
                self.assertIn("CIV_HOST_API_" + name, str(stop.exception))

    def test_the_claude_plugin_version_is_set_and_its_line_ends_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            text = '{\n  "name": "civ5-bazaar",\n  "version": "0.3.0",\n  "author": { "name": "x" }\n}\n'
            path = write(folder, text, "\r\n")
            version.set_plugin_version("0.4.0", path)
            with open(path, newline="") as f:
                self.assertEqual(f.read(), text.replace("0.3.0", "0.4.0").replace("\n", "\r\n"))


if __name__ == "__main__":
    unittest.main()
