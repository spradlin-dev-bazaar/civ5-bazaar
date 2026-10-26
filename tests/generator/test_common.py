"""Checks of tools/generator/common.py.

python -m unittest discover -s tests/generator
"""

import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "generator"))

import common  # noqa: E402


class EnvTest(unittest.TestCase):
    def test_the_visual_c_path_replaces_the_one_before_it_whatever_its_case(self):
        printed = types.SimpleNamespace(stdout="Path=C:\\VC\\BIN\nINCLUDE=C:\\VC\\INCLUDE\n")
        with (
            mock.patch.object(common.subprocess, "run", return_value=printed),
            mock.patch.dict(os.environ, {"PATH": "C:\\Windows"}),
        ):
            env = common.vs_env()
        self.assertEqual(env["PATH"], "C:\\VC\\BIN")
        self.assertNotIn("Path", env)


class KnownErrorsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)

    def write(self, name, data):
        path = os.path.join(self.folder, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_each_line_is_a_file_name_a_message_and_a_source_line_with_its_spaces_evened_out(self):
        path = self.write("known.txt", b"# why\n\nA.h\texpected expression\tint x = ;\nB.h\tm\t\tf(a,\t b); \n")
        entries = {("A.h", "expected expression", "int x = ;"), ("B.h", "m", "f(a, b);")}
        self.assertEqual(common.known_errors(path), entries)
        with self.assertRaises(RuntimeError):
            common.known_errors(self.write("short.txt", b"A.h\texpected expression\n"))

    def test_a_source_line_is_numbered_as_clang_numbers_lines_and_read_in_the_games_code_page(self):
        path = self.write("A.h", b"one\r\ntwo\rthree\n\t four \x85  five  \nsix\x0cseven\nend")
        lines = [common.source_line(path, number) for number in range(1, 8)]
        self.assertEqual(lines, ["one", "two", "three", "four … five", "six\x0cseven", "end", ""])

    def test_an_error_is_known_only_on_the_line_its_entry_names(self):
        path = self.write("A.h", b"int x = ;\nint y = ;\n")
        known = {("A.h", "expected expression", "int x = ;")}
        self.assertTrue(common.known_error(known, path, 1, "expected expression"))
        self.assertFalse(common.known_error(known, path, 2, "expected expression"))
        self.assertFalse(common.known_error(known, path, 1, "another message"))
        self.assertFalse(common.known_error(known, self.write("B.h", b"int x = ;\n"), 1, "expected expression"))


class UnderTest(unittest.TestCase):
    def test_a_path_is_under_a_folder_only_inside_it_in_any_case(self):
        folder = os.path.join(tempfile.gettempdir(), "Engine")
        self.assertTrue(common.under(os.path.join(folder.upper(), "CvUnit.h"), [folder]))
        self.assertFalse(common.under(folder + "2" + os.sep + "CvUnit.h", [folder]))
        self.assertFalse(common.under("", [folder]))


if __name__ == "__main__":
    unittest.main()
