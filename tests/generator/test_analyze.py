"""The analyzer's rule for which parse errors stop the build.

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

import analyze  # noqa: E402


class ProjectErrorsTest(unittest.TestCase):
    def test_only_a_new_error_outside_a_body_in_the_project_stops_the_build(self):
        root = os.path.join(tempfile.gettempdir(), "engine")
        header = os.path.join(root, "CvUnit.h")
        errors = [
            (os.path.join(root, "CvUnit.cpp"), 3, "use of undeclared identifier", True),
            (header, 5, "expected ';'", False),
            (os.path.join(root, "CvDatabaseUtility.h"), 7, "expected expression", False),
            (os.path.join(tempfile.gettempdir(), "sdk", "windows.h"), 1, "unknown type name", False),
        ]
        project = types.SimpleNamespace(contains=lambda path: path.startswith(root + os.sep))
        with mock.patch.object(analyze, "known_errors", lambda: {("CvDatabaseUtility.h", "expected expression")}):
            self.assertEqual(analyze.project_errors(project, [{"errors": errors}]), {(header, 5, "expected ';'")})


class KnownErrorsTest(unittest.TestCase):
    def test_each_line_is_a_file_name_and_a_message_and_comments_are_skipped(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, "known.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# why each is harmless\n\nCvDatabaseUtility.h\texpected expression\nA.h\tinvalid\tname\n")
        self.assertEqual(
            analyze.known_errors(path), {("CvDatabaseUtility.h", "expected expression"), ("A.h", "invalid\tname")}
        )


if __name__ == "__main__":
    unittest.main()
