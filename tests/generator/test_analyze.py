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
import common  # noqa: E402


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


class CanonicalParametersTest(unittest.TestCase):
    def test_a_parameters_top_level_const_and_volatile_are_dropped_and_any_other_kept(self):
        source = (
            "struct S { enum E { A }; }; namespace N { struct T {}; }\n"
            "void f(const int a, const char* const c, char* volatile d, const S e, const N::T& g, S::E h,\n"
            "       void (*const p)(int), int (*const q)[3]);\n"
        )
        tu = analyze.ci.Index.create().parse("f.cpp", args=["-x", "c++"], unsaved_files=[("f.cpp", source)])
        f = [c for c in tu.cursor.get_children() if c.spelling == "f"][0]
        self.assertEqual(
            analyze.canonical_parameters(f.type),
            ["int", "const char *", "char *", "S", "const N::T &", "S::E", "void (*)(int)", "int (*)[3]"],
        )


class CheckPluginHeaderTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.engine = os.path.join(self.root, "engine")
        self.sdk = os.path.join(self.root, "sdk")
        os.makedirs(self.engine)
        os.makedirs(self.sdk)
        self.project = common.Project(self.engine, [], [self.engine], self.sdk, "", "Engine.h")

    def write(self, folder, name, text):
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_an_error_in_the_games_headers_stops_unless_it_is_known(self):
        self.write(self.engine, "Engine.h", "int broken = ;\n")
        header = self.write(self.sdk, "CivHooks.h", '#include "Engine.h"\n')
        with self.assertRaises(RuntimeError):
            analyze.check_plugin_header(self.project, header)
        known = {("Engine.h", "expected expression")}
        with mock.patch.object(analyze, "known_errors", lambda: known):
            self.assertEqual(analyze.check_plugin_header(self.project, header), (set(), {}))

    def test_each_original_typedef_gives_its_types_and_an_error_gives_its_line(self):
        self.write(self.engine, "Engine.h", "struct Unit { enum Mood { CALM }; };\n")
        header = self.write(
            self.sdk,
            "CivHooks.h",
            '#include "Engine.h"\nnamespace CivHooks\n{\n'
            "\tstruct A { typedef int (*Original)(const Unit *, Unit::Mood, const int); };\n"
            "\tstruct B { typedef Missing (*Original)(); };\n}\n",
        )
        lines, originals = analyze.check_plugin_header(self.project, header)
        self.assertEqual(lines, {5})
        self.assertEqual(originals[4], ("int", ["const Unit *", "Unit::Mood", "int"]))


if __name__ == "__main__":
    unittest.main()
