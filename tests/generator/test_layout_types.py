"""What libclang adds to the layout record, read from small headers as a plugin reads the engine's.

python -m unittest discover -s tests/generator
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "generator"))

import common  # noqa: E402
import layout_types  # noqa: E402
import layouts  # noqa: E402

SUPPORT = [os.path.join(common.SOURCE_ROOT, folder) for folder in common.SUPPORT_INCLUDE]
FIREWORKS = os.path.join(common.SOURCE_ROOT, "FirePlace", "include", "FireWorks")


class ReadTest(unittest.TestCase):
    def setUp(self):
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top)
        # clang names an unnamed type by its path, and a bracket in it must not survive into the record.
        self.folder = os.path.join(top, "work (1)")
        os.makedirs(self.folder)

    def read(self, header, folders=None, unit_text='#include "shapes.h"\n'):
        with open(os.path.join(self.folder, "shapes.h"), "w") as f:
            f.write(header)
        unit = os.path.join(self.folder, "unit.cpp")
        with open(unit, "w") as f:
            f.write(unit_text)
        return dict(layout_types.read(unit, [self.folder] + SUPPORT, folders or [self.folder]))

    def changed(self, before, after):
        then, now = sorted(self.read(before).items()), sorted(self.read(after).items())
        return [key for key, _, _ in layouts.compare(then, now)[0]]

    def test_each_field_s_type_and_each_virtual_function_s_parameters_are_recorded(self):
        found = self.read(
            "typedef int Count;\nstruct Unit { virtual void Move(int x, const Unit* to) const; Count m_n; };\n"
        )
        self.assertEqual(
            found["types Unit"],
            "types Unit:\n field m_n: int\n virtual Move void (int, const Unit *) __attribute__((thiscall)) const",
        )

    def test_a_field_that_changes_type_but_not_size_is_a_change(self):
        self.assertEqual(self.changed("struct Unit { int m_x; };", "struct Unit { float m_x; };"), ["types Unit"])

    def test_a_virtual_function_whose_parameters_change_is_a_change(self):
        before = "struct Unit { virtual void Move(int); };"
        self.assertEqual(self.changed(before, before.replace("int", "short")), ["types Unit"])

    def test_a_bit_field_s_width_is_recorded(self):
        before = "struct Flags { unsigned a : 3; unsigned b : 5; };"
        self.assertIn(" field a: unsigned int : 3", self.read(before)["types Flags"])
        self.assertEqual(self.changed(before, before.replace(": 3", ": 4")), ["types Flags"])

    def test_a_value_inserted_in_an_enum_changes_the_ones_after_it_and_one_added_at_the_end_is_new(self):
        before = "enum UnitAI { NONE = -1, SETTLE, WORKER };"
        self.assertEqual(self.changed(before, before.replace("SETTLE,", "SETTLE, ATTACK,")), ["enum WORKER"])
        self.assertEqual(self.changed(before, before.replace("WORKER", "WORKER, ATTACK")), [])
        self.assertEqual(self.read(before)["enum NONE"], "enum NONE = -1")

    def test_an_enum_value_is_named_as_c_plus_plus_names_it_so_renaming_its_enum_changes_nothing(self):
        before = "namespace N { struct Unit { enum Moves { WALK, SWIM }; }; }"
        self.assertEqual(self.read(before)["enum N::Unit::SWIM"], "enum N::Unit::SWIM = 1")
        self.assertEqual(self.changed(before, before.replace("Moves", "Movement")), [])

    def test_namespaces_and_extern_c_blocks_are_read(self):
        found = self.read(
            'namespace N { struct In { int a; }; enum { K = 2 }; }\nextern "C" { struct C { int c; }; }\n'
        )
        self.assertEqual(sorted(found), ["enum N::K", "types C", "types N::In"])

    def test_an_unnamed_type_is_spelled_by_its_fields_and_stays_put_when_lines_above_move(self):
        header = (
            "struct Arg { union { int i; float f; enum { J = 2 } e; }; struct { short s; } m_named;\n"
            "  enum { K = 3 } m_kind; struct { int a; } *m_points; };\n"
        )
        found = self.read(header)
        self.assertEqual(sorted(found), ["enum Arg::J", "enum Arg::K", "types Arg"])
        self.assertEqual(
            found["types Arg"],
            "types Arg:\n field union { i: int; f: float; e: Arg::(unnamed enum) }\n"
            " field m_named: struct { s: short }\n field m_kind: Arg::(unnamed enum)\n"
            " field m_points: struct { a: int } *",
        )
        self.assertEqual(self.read("\n\n// moved\n" + header), found)

    def test_a_struct_named_by_a_typedef_gets_its_own_block(self):
        self.assertIn("types Plain", self.read("typedef struct { int a; } Plain;"))

    def test_a_class_template_is_left_out_and_a_class_using_one_names_it_with_its_arguments(self):
        found = self.read("template <class T> struct Box { T m_v; };\nstruct Use { Box<int> m_b; };\n")
        self.assertEqual(sorted(found), ["types Use"])
        self.assertIn(" field m_b: Box<int>", found["types Use"])

    def test_a_class_with_no_fields_or_virtual_functions_adds_nothing(self):
        self.assertEqual(self.read("struct Empty { void Act(); static int s_count; };"), {})

    def test_the_count_that_ends_a_host_enum_is_left_out_since_it_grows_by_design(self):
        header = "enum CivHandHook { CIV_HAND_FIRST_COUNT = 0, CIV_HAND_HOOK_COUNT };\nstruct Info { int size; };"
        with mock.patch.object(layout_types.common, "HOST_DIR", self.folder):
            self.assertEqual(sorted(self.read(header)), ["enum CIV_HAND_FIRST_COUNT", "types Info"])
        self.assertIn("enum CIV_HAND_HOOK_COUNT", self.read(header))

    def test_the_memory_pool_values_are_the_header_s_own_not_the_parse_shim_s(self):
        found = self.read("", folders=[FIREWORKS], unit_text="")
        self.assertEqual(found["enum c_eMPoolTypeContainer"], "enum c_eMPoolTypeContainer = 0")
        self.assertEqual(found["enum c_eMPoolTypeSBA"], "enum c_eMPoolTypeSBA = 1")

    def test_the_blocks_read_back_from_the_record_as_libclang_wrote_them(self):
        blocks = sorted(self.read("struct Arg { union { int i; }; enum { K = 3 } m_kind; virtual int Go(); };").items())
        self.assertEqual(layouts.parse_record(layouts.format_record((0, 1), blocks)), ((0, 1), blocks))

    def test_headers_outside_the_folders_are_left_out(self):
        self.assertEqual(self.read("struct Unit { int m_x; };", folders=[os.path.join(self.folder, "other")]), {})

    def test_an_error_in_the_headers_stops_and_says_where(self):
        with self.assertRaises(RuntimeError) as stop:
            self.read("struct Unit { Missing m_x; };")
        self.assertIn("shapes.h line 1", str(stop.exception))

    def test_a_known_error_or_one_outside_the_folders_does_not_stop_but_the_same_error_on_another_line_does(self):
        known = {("shapes.h", "unknown type name 'Missing'", "struct Unit { Missing m_x; };")}
        with mock.patch.object(layout_types.common, "known_errors", lambda: known):
            self.read("struct Unit { Missing m_x; };")
            with self.assertRaises(RuntimeError):
                self.read("struct Unit { Missing m_x; };\nstruct Other { Missing m_y; };")
        self.read("struct Unit { Missing m_x; };", folders=[os.path.join(self.folder, "other")])

    def test_a_header_that_is_not_found_stops_wherever_it_is(self):
        with self.assertRaises(RuntimeError):
            self.read("", folders=[os.path.join(self.folder, "other")], unit_text='#include "missing.h"\n')

    def test_another_libclang_than_the_one_named_in_requirements_stops(self):
        with mock.patch.object(layout_types.metadata, "version", lambda name: "17.0.6"):
            with self.assertRaises(RuntimeError) as stop:
                self.read("struct Unit { int m_x; };")
        self.assertIn("libclang 17.0.6 is installed", str(stop.exception))

    def test_a_libclang_from_elsewhere_or_a_loose_pin_stops_with_a_message(self):
        def missing(name):
            raise layout_types.metadata.PackageNotFoundError(name)

        with mock.patch.object(layout_types.metadata, "version", missing):
            with self.assertRaises(RuntimeError) as stop:
                layout_types.check_libclang()
        self.assertIn("pip package is not installed", str(stop.exception))
        requirements = os.path.join(self.folder, "requirements.txt")
        with open(requirements, "w") as f:
            f.write("libclang>=18\n")
        with mock.patch.object(layout_types, "REQUIREMENTS", requirements):
            with self.assertRaises(RuntimeError) as stop:
                layout_types.check_libclang()
        self.assertIn("libclang==<version>", str(stop.exception))


if __name__ == "__main__":
    unittest.main()
