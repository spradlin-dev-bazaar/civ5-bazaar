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


class StoppingErrorsTest(unittest.TestCase):
    def test_a_new_error_outside_a_body_in_the_project_or_a_fatal_one_anywhere_stops_the_build(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        header, utility = os.path.join(root, "CvUnit.h"), os.path.join(root, "CvDatabaseUtility.h")
        with open(header, "w") as f:
            f.write("int a\n")
        with open(utility, "w") as f:
            f.write("int x = ;\nint y = ;\n")
        support = os.path.join(tempfile.gettempdir(), "support", "Headers.h")
        errors = [
            (os.path.join(root, "CvUnit.cpp"), 3, "use of undeclared identifier", True, False),
            (header, 1, "expected ';'", False, False),
            (utility, 1, "expected expression", False, False),
            (utility, 2, "expected expression", False, False),
            (os.path.join(tempfile.gettempdir(), "sdk", "windows.h"), 1, "unknown type name", False, False),
            (support, 53, "'Windows.h' file not found", False, True),
        ]
        project = types.SimpleNamespace(contains=lambda path: path.startswith(root + os.sep))
        known = {("CvDatabaseUtility.h", "expected expression", "int x = ;")}
        with mock.patch.object(common, "known_errors", lambda: known):
            self.assertEqual(
                analyze.stopping_errors(project, [{"errors": errors}]),
                {
                    (header, 1, "expected ';'"),
                    (utility, 2, "expected expression"),
                    (support, 53, "'Windows.h' file not found"),
                },
            )

    def test_a_header_that_cannot_be_found_is_a_fatal_error(self):
        source = '#include "Missing.h"\nint f();\nint g = ;\n'
        tu = analyze.ci.Index.create().parse("f.cpp", args=["-x", "c++"], unsaved_files=[("f.cpp", source)])
        fatal = [(e[2], e[4]) for e in analyze.parse_errors(tu, "f.cpp", [])]
        self.assertEqual(fatal, [("'Missing.h' file not found", True)])


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
        known = {("Engine.h", "expected expression", "int broken = ;")}
        with mock.patch.object(common, "known_errors", lambda: known):
            self.assertEqual(analyze.check_plugin_header(self.project, header), (set(), {}))
            self.write(self.engine, "Engine.h", "int broken = ;\nint other = ;\n")
            with self.assertRaises(RuntimeError):
                analyze.check_plugin_header(self.project, header)

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
