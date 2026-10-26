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
    def test_each_line_is_a_file_name_and_a_message_and_comments_are_skipped(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, "known.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# why each is harmless\n\nCvDatabaseUtility.h\texpected expression\nA.h\tinvalid\tname\n")
        self.assertEqual(
            common.known_errors(path), {("CvDatabaseUtility.h", "expected expression"), ("A.h", "invalid\tname")}
        )


class UnderTest(unittest.TestCase):
    def test_a_path_is_under_a_folder_only_inside_it_in_any_case(self):
        folder = os.path.join(tempfile.gettempdir(), "Engine")
        self.assertTrue(common.under(os.path.join(folder.upper(), "CvUnit.h"), [folder]))
        self.assertFalse(common.under(folder + "2" + os.sep + "CvUnit.h", [folder]))
        self.assertFalse(common.under("", [folder]))


if __name__ == "__main__":
    unittest.main()
