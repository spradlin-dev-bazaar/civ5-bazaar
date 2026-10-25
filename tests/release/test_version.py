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


if __name__ == "__main__":
    unittest.main()
