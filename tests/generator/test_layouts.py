"""The layout check's own logic, on reports written like the compiler's; one test reads a real report when cl.exe is on
the path, as it is under tests/runtime/run.cmd.

    python -m unittest discover -s tests/generator
"""

import io
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "generator"))

import common  # noqa: E402
import layouts  # noqa: E402

UNIT = "class CvUnit\tsize(12):\n\t+---\n 0\t| {vfptr}\n 4\t| m_iX\n 8\t| m_iY\n\t+---\n"
GROWN = UNIT.replace(" 8\t| m_iY\n", " 8\t| m_iY\n12\t| m_iZ\n").replace("size(12)", "size(16)")
UNIT_TABLE = (
    "CvUnit::$vftable@:\n"
    "\t| &CvUnit_meta\n"
    "\t|  0\n"
    " 0\t| &CvUnit::{dtor}\n"
    " 1\t| &CvUnit::Range\n"
    "\n"
    "CvUnit::Range this adjustor: 0\n"
)
CITY = "class CvCity\tsize(4):\n\t+---\n 0\t| m_iID\n\t+---\n"
FIRST = "class iterator\tsize(4):\n\t+---\n 0\t| _Ptr\n\t+---\n"
SECOND = "class iterator\tsize(8):\n\t+---\n 0\t| _Ptr\n 4\t| _Mycont\n\t+---\n"
THIRD = "class iterator\tsize(12):\n\t+---\n 0\t| _Ptr\n 4\t| _Mycont\n 8\t| _Index\n\t+---\n"
UNIT_TYPES = (
    "types CvUnit:\n field m_iX: int\n field m_iY: int\n virtual Range int () __attribute__((thiscall)) const\n"
)
VALUES = "enum UnitAITypes::NO_UNITAI = -1\nenum UnitAITypes::UNITAI_SETTLE = 0\n"


def report(*blocks):
    return "all-headers.cpp\n" + "\n\n".join(blocks) + "\n\n"


def block(text):
    return layouts.parse_report(text)[0]


def temp_folder(test):
    folder = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, folder)
    return folder


class ParseReportTest(unittest.TestCase):
    def test_each_class_and_virtual_table_is_a_block_named_without_its_size(self):
        keys = [key for key, _ in layouts.parse_report(report(UNIT, UNIT_TABLE, CITY))]
        self.assertEqual(keys, ["CvUnit::$vftable@", "class CvCity", "class CvUnit"])

    def test_the_lines_after_a_table_stay_with_it_and_the_file_name_line_is_dropped(self):
        blocks = dict(layouts.parse_report(report(UNIT, UNIT_TABLE)))
        self.assertTrue(blocks["CvUnit::$vftable@"].endswith("CvUnit::Range this adjustor: 0"))
        self.assertNotIn("all-headers.cpp", "".join(blocks.values()))

    def test_a_class_s_types_are_a_block_and_each_enum_value_is_one_even_on_the_next_line(self):
        blocks = dict(layouts.parse_report(report(UNIT, UNIT_TYPES, VALUES)))
        self.assertEqual(
            sorted(blocks),
            ["class CvUnit", "enum UnitAITypes::NO_UNITAI", "enum UnitAITypes::UNITAI_SETTLE", "types CvUnit"],
        )
        self.assertEqual(blocks["types CvUnit"], UNIT_TYPES.rstrip("\n"))
        self.assertEqual(layouts.label("types CvUnit"), "field types and virtual functions of CvUnit")
        self.assertEqual(layouts.label("enum NO_UNITAI"), "enum value NO_UNITAI")
        self.assertEqual(blocks["enum UnitAITypes::UNITAI_SETTLE"], "enum UnitAITypes::UNITAI_SETTLE = 0")

    def test_line_endings_and_trailing_spaces_do_not_change_a_block(self):
        plain = layouts.parse_report(report(UNIT))
        self.assertEqual(layouts.parse_report(report(UNIT).replace("\n", " \r\n")), plain)


class CompareTest(unittest.TestCase):
    def test_the_same_layouts_lose_and_add_nothing(self):
        blocks = layouts.parse_report(report(UNIT, CITY))
        self.assertEqual(layouts.compare(blocks, blocks), ([], []))

    def test_a_changed_class_is_lost_and_comes_with_its_new_layout(self):
        lost, new = layouts.compare(layouts.parse_report(report(UNIT)), layouts.parse_report(report(GROWN)))
        self.assertEqual([(key, now) for key, _, now in lost], [("class CvUnit", [block(GROWN)[1]])])
        self.assertEqual(new, [])

    def test_a_vanished_class_is_lost_with_nothing_in_its_place(self):
        lost, _ = layouts.compare(layouts.parse_report(report(UNIT, CITY)), layouts.parse_report(report(UNIT)))
        self.assertEqual([(key, now) for key, _, now in lost], [("class CvCity", None)])

    def test_a_new_class_is_added(self):
        lost, new = layouts.compare(layouts.parse_report(report(UNIT)), layouts.parse_report(report(UNIT, CITY)))
        self.assertEqual((lost, new), ([], [block(CITY)]))

    def test_nested_classes_that_share_a_name_are_matched_as_a_group(self):
        recorded = layouts.parse_report(report(SECOND, FIRST))
        lost, new = layouts.compare(recorded, layouts.parse_report(report(FIRST, THIRD, SECOND)))
        self.assertEqual((lost, new), ([], [block(THIRD)]))
        lost, new = layouts.compare(recorded, layouts.parse_report(report(FIRST, THIRD)))
        self.assertEqual([(text, now) for _, text, now in lost], [(block(SECOND)[1], [block(THIRD)[1]])])
        self.assertEqual(new, [])


class DescribeTest(unittest.TestCase):
    def describe(self, recorded, current):
        recorded, current = layouts.parse_report(recorded), layouts.parse_report(current)
        lost, _ = layouts.compare(recorded, current)
        return layouts.describe(lost, layouts.shared_names(recorded, current))

    def test_a_changed_class_shows_the_lines_that_changed(self):
        out = self.describe(report(UNIT), report(GROWN))
        self.assertEqual(out[0], "  changed: class CvUnit")
        self.assertIn("    +12\t| m_iZ", out)

    def test_a_gone_class_says_so(self):
        self.assertEqual(self.describe(report(UNIT, CITY), report(UNIT)), ["  gone: class CvCity"])

    def test_a_changed_nested_class_is_compared_with_the_most_like_it_and_said_to_be_nested(self):
        renamed = FIRST.replace("_Ptr", "_Pointer")
        out = self.describe(report(FIRST, SECOND), report(SECOND, THIRD, renamed))
        self.assertTrue(out[0].startswith("  changed: class iterator (one of several classes of this name"))
        self.assertIn("    + 0\t| _Pointer", out)
        self.assertFalse(any("_Index" in line for line in out))

    def test_a_long_diff_and_a_long_list_are_cut_and_say_so(self):
        wide = (
            "class CvWide\tsize(80):\n\t+---\n" + "".join(" %d\t| m_%d\n" % (i * 4, i) for i in range(20)) + "\t+---\n"
        )
        out = self.describe(report(wide), report(wide.replace("| m_", "| m_new")))
        self.assertEqual(out[-1], "    ...")
        many = ["class CvGone%d\tsize(4):\n\t+---\n 0\t| m_i\n\t+---\n" % i for i in range(16)]
        out = self.describe(report(*many), report(CITY))
        self.assertEqual(out[-1], "  and 1 more")
        self.assertEqual(len(out), 16)


class RecordTest(unittest.TestCase):
    def test_a_record_reads_back_as_written(self):
        blocks = layouts.parse_report(report(UNIT, UNIT_TABLE, CITY, UNIT_TYPES, VALUES))
        self.assertEqual(layouts.parse_record(layouts.format_record((0, 3), blocks)), ((0, 3), blocks))

    def test_a_record_without_its_api_line_is_refused(self):
        with self.assertRaises(RuntimeError):
            layouts.parse_record(report(UNIT))


class AcceptAllowedTest(unittest.TestCase):
    def test_the_host_refuses_plugins_from_before_the_same_freeze(self):
        with open(os.path.join(common.HOST_DIR, "CivHostRuntime.h"), encoding="utf-8") as f:
            text = f.read()
        found = [re.search(r"#define CIV_HOST_FREEZE_%s (\d+)" % part, text) for part in ("MAJOR", "MINOR")]
        self.assertTrue(all(found))
        self.assertEqual(tuple(int(m.group(1)) for m in found), common.FREEZE)

    def test_before_the_freeze_a_change_may_always_be_accepted(self):
        for tag in (None, "v0.3.0", "v0.4.1"):
            self.assertTrue(layouts.accept_allowed((0, 3), (0, 4), tag), tag)
        self.assertTrue(layouts.accept_allowed((0, 4), (0, 5), "v0.4.1"), "the release that freezes, while prepared")

    def test_the_freeze_fixes_the_layouts_of_the_releases_before_it(self):
        for tag in ("v0.5.0", "v0.9.0"):
            self.assertFalse(layouts.accept_allowed((0, 5), (0, 5), tag), tag)
            self.assertFalse(layouts.accept_allowed((0, 5), (0, 9), tag), tag)
        for tag in (None, "v1.0.0"):
            self.assertFalse(layouts.accept_allowed((0, 9), (1, 0), tag), tag)

    def test_within_a_released_major_version_a_change_is_refused(self):
        self.assertFalse(layouts.accept_allowed((0, 9), (1, 4), "v1.3.0"))
        self.assertFalse(layouts.accept_allowed((2, 0), (2, 1), "v2.0.0"))

    def test_the_major_version_after_the_last_release_s_may_change_them_again_until_released(self):
        self.assertTrue(layouts.accept_allowed((0, 5), (1, 0), "v0.5.0"))
        self.assertTrue(layouts.accept_allowed((1, 4), (2, 0), "v1.4.0"))
        self.assertTrue(layouts.accept_allowed((2, 0), (2, 0), "v1.4.0"))

    def test_a_number_raised_past_it_or_put_back_to_0_after_the_freeze_is_refused(self):
        self.assertFalse(layouts.accept_allowed((1, 4), (3, 0), "v1.4.0"))
        self.assertFalse(layouts.accept_allowed((1, 4), (0, 4), "v1.4.0"))

    def test_without_a_release_tag_only_a_record_and_number_before_the_freeze_may_change(self):
        self.assertFalse(layouts.accept_allowed((1, 4), (2, 0), None))
        self.assertFalse(layouts.accept_allowed((0, 4), (2, 0), None))
        self.assertFalse(layouts.accept_allowed((1, 4), (0, 4), None))
        self.assertFalse(layouts.accept_allowed((0, 4), (0, 5), None))


class ShippedHeadersTest(unittest.TestCase):
    def test_the_headers_that_do_not_compile_are_left_out_and_the_rest_sorted_ignoring_case(self):
        mirror = temp_folder(self)
        os.makedirs(os.path.join(mirror, "Lua"))
        for rel in [
            "B.h",
            "a.h",
            "CvDLLFAStarIFaceBase.h",
            os.path.join("Lua", "CvLuaScopedIndirectInstance.h"),
            "a.cpp",
        ]:
            open(os.path.join(mirror, rel), "w").close()
        self.assertEqual(layouts.shipped_headers(types.SimpleNamespace(mirror_dir=mirror)), ["a.h", "B.h"])


class ApiVersionTest(unittest.TestCase):
    def version_of(self, text):
        path = os.path.join(temp_folder(self), "CivPluginApi.h")
        with open(path, "w") as f:
            f.write(text)
        with mock.patch.object(layouts, "API_HEADER", path):
            return layouts.api_version()

    def test_the_version_is_read_from_its_two_defines(self):
        self.assertEqual(
            self.version_of("#pragma once\n#define CIV_HOST_API_MAJOR 1\n#define CIV_HOST_API_MINOR 12\n"), (1, 12)
        )

    def test_a_header_without_them_is_refused_with_a_message(self):
        with self.assertRaises(RuntimeError):
            self.version_of("#define CIV_HOST_API_MAJOR (1)\n")

    def test_the_version_is_set_and_nothing_else_changes(self):
        text = "#pragma once\r\n#define CIV_HOST_API_MAJOR 0\r\n#define CIV_HOST_API_MINOR 3\r\nstruct CivHostInfo;\r\n"
        path = os.path.join(temp_folder(self), "CivPluginApi.h")
        with open(path, "w", newline="") as f:
            f.write(text)
        layouts.set_api_version(1, 0, path)
        with open(path, newline="") as f:
            self.assertEqual(f.read(), text.replace("MAJOR 0", "MAJOR 1").replace("MINOR 3", "MINOR 0"))

    def test_setting_a_header_without_one_of_the_numbers_stops(self):
        for name in ("MAJOR", "MINOR"):
            with self.subTest(name=name):
                path = os.path.join(temp_folder(self), "CivPluginApi.h")
                with open(path, "w") as f:
                    header = "#define CIV_HOST_API_MAJOR 0\n#define CIV_HOST_API_MINOR 3\n"
                    f.write(header.replace("API_" + name, "API_" + name + "_NUMBER"))
                with self.assertRaises(SystemExit) as stop:
                    layouts.set_api_version(1, 0, path)
                self.assertIn("CIV_HOST_API_" + name, str(stop.exception))


class HostDefinesTest(unittest.TestCase):
    PROJECT = (
        '<Configuration Name="Debug|Win32">\n'
        '<Tool Name="VCCLCompilerTool" PreprocessorDefinitions="_DEBUG;WIN32"/>\n'
        "</Configuration>\n"
        '<Configuration Name="Mod|Win32">\n'
        '<Tool Name="VCLinkerTool" OutputFile="x.dll"/>\n'
        '<Tool Name="VCCLCompilerTool" Optimization="3"\n'
        '\tPreprocessorDefinitions="CIV_HOST_API=__declspec(dllexport);NDEBUG;CVGAMECOREDLL_EXPORTS"/>\n'
        "</Configuration>\n"
    )

    def defines_of(self, text):
        mirror = temp_folder(self)
        if text is not None:
            with open(os.path.join(mirror, "engine.vcproj"), "w") as f:
                f.write(text)
        return layouts.host_defines(types.SimpleNamespace(mirror_dir=mirror, vcproj=r"C:\source\engine.vcproj"))

    def test_the_defines_come_from_the_mod_configurations_compiler(self):
        self.assertEqual(
            self.defines_of(self.PROJECT), ["CIV_HOST_API=__declspec(dllexport)", "NDEBUG", "CVGAMECOREDLL_EXPORTS"]
        )

    def test_a_missing_project_or_configuration_is_refused_with_a_message(self):
        for text in [None, self.PROJECT.replace("Mod|Win32", "Release|Win32")]:
            with self.assertRaises(RuntimeError):
                self.defines_of(text)


class RunTest(unittest.TestCase):
    def setUp(self):
        folder = temp_folder(self)
        self.project = types.SimpleNamespace(build_dir=folder, mirror_dir=folder)
        self.version = (0, 3)
        self.host_defines = list(layouts.common.PLUGIN_DEFINES)
        self.types = []
        self.tag = "v0.3.0"
        for target, name, value in [
            (layouts, "RECORD", os.path.join(folder, "class-layouts.txt")),
            (layouts, "api_version", lambda: self.version),
            (layouts, "host_defines", lambda project: self.host_defines),
            (layouts, "last_release_tag", lambda: self.tag),
            (layouts.common, "engine_project", lambda: self.project),
        ]:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_step(self, step, plugin, host=None):
        """The step's exit code and output, with plugin and host as the compiler's two reports."""
        texts = iter([plugin, host if host is not None else plugin])
        out = io.StringIO()
        with mock.patch.object(layouts, "compile_report", lambda *args: next(texts)):
            with mock.patch.object(layouts.layout_types, "read", self.read_types):
                with mock.patch.object(layouts, "check_hooks_header", self.check_header), redirect_stdout(out):
                    code = layouts.main(["--accept"] if step == "accept" else [])
        return code, out.getvalue()

    def read_types(self, unit, includes):
        self.read_with = (unit, includes)
        return self.types

    def check_header(self, folder, includes):
        self.header_checked_with = (folder, includes)

    def check(self, plugin, host=None):
        return self.run_step("check", plugin, host)

    def accept(self, plugin):
        return self.run_step("accept", plugin)

    def saved(self):
        return layouts.read_record((0, 0))

    def freeze(self, *blocks):
        """A record saved before the freeze, and the version moved to 1.4, the last release's."""
        self.check(report(*blocks))
        self.version = (1, 4)
        self.tag = "v1.4.0"

    def test_the_first_check_saves_the_record_with_the_current_version(self):
        self.assertEqual(self.check(report(UNIT))[0], 0)
        self.assertEqual(self.saved(), ((0, 3), layouts.parse_report(report(UNIT))))

    def test_new_classes_are_added_and_keep_the_version_the_record_was_saved_for(self):
        self.check(report(UNIT))
        self.version = (0, 4)
        self.assertEqual(self.check(report(UNIT, CITY))[0], 0)
        self.assertEqual(self.saved(), ((0, 3), layouts.parse_report(report(UNIT, CITY))))

    def test_a_changed_class_fails_says_how_to_accept_and_leaves_the_record_alone(self):
        self.check(report(UNIT, CITY))
        code, out = self.check(report(GROWN, CITY))
        self.assertEqual(code, 1)
        self.assertIn("changed: class CvUnit", out)
        self.assertIn("run build-hooked.cmd accept-layouts, then rebuild every plugin", out)
        self.assertEqual(self.saved()[1], layouts.parse_report(report(UNIT, CITY)))

    def test_a_changed_class_once_frozen_says_to_raise_the_number_past_the_last_release_and_put_it_back(self):
        self.freeze(UNIT)
        out = self.check(report(GROWN))[1]
        self.assertIn("CIV_HOST_API_MAJOR in host\\CivPluginApi.h to 2, one more than the", out)
        self.assertIn("Then set it back to the major number in VERSION", out)

    def test_two_changes_for_the_next_major_version_are_both_accepted_with_the_number_put_back_between(self):
        self.freeze(UNIT, CITY)
        moved = CITY.replace("m_iID", "m_iOwner")
        for current in (report(GROWN, CITY), report(GROWN, moved)):
            self.assertEqual(self.check(current)[0], 1)
            self.version = (2, 0)
            self.assertIn("To change them on purpose", self.check(current)[1])
            code, out = self.accept(current)
            self.assertEqual(code, 0)
            self.assertIn("If you changed CIV_HOST_API_MAJOR for this, set it back to the major number in VERSION", out)
            self.version = (1, 4)
            self.assertEqual(self.check(current)[0], 0)
        self.assertEqual(self.saved(), ((2, 0), layouts.parse_report(report(GROWN, moved))))

    def test_the_check_compiles_civhooks_h_with_the_include_folders_plugins_use(self):
        self.check(report(UNIT))
        folder = os.path.dirname(self.read_with[0])
        self.assertEqual(self.header_checked_with, (folder, layouts.include_dirs(self.project)))

    def test_the_types_libclang_reads_join_the_record_and_a_change_to_them_fails(self):
        self.types = layouts.parse_report(UNIT_TYPES + VALUES)
        self.check(report(UNIT))
        self.assertEqual(self.saved()[1], layouts.parse_report(report(UNIT, UNIT_TYPES, VALUES)))
        unit, includes = self.read_with
        self.assertEqual(os.path.basename(unit), "all-headers.cpp")
        self.assertEqual(includes, layouts.include_dirs(self.project))
        self.types = layouts.parse_report(UNIT_TYPES.replace("m_iY: int", "m_iY: float") + VALUES)
        code, out = self.check(report(UNIT))
        self.assertEqual(code, 1)
        self.assertIn("changed: field types and virtual functions of CvUnit", out)

    def test_a_gone_class_fails_and_says_the_release_without_it_is_a_new_major_version(self):
        self.freeze(UNIT, CITY)
        code, out = self.check(report(UNIT))
        self.assertEqual(code, 1)
        self.assertIn("gone: class CvCity", out)
        self.assertIn("From 0.5 on, the release\nwithout it must be a new major version", out)

    def test_a_layout_the_host_sees_differently_fails_and_names_the_defines_that_differ(self):
        self.host_defines = self.host_defines + ["CVGAMECOREDLL_EXPORTS"]
        code, out = self.check(report(UNIT), host=report(UNIT, CITY))
        self.assertEqual(code, 1)
        self.assertIn("  class CvCity", out)
        self.assertIn("Defines only the host sets, in the generated engine project: CVGAMECOREDLL_EXPORTS", out)
        self.assertNotIn("Defines only plugins set", out)
        self.assertFalse(os.path.exists(layouts.RECORD))

    def test_a_report_without_layouts_fails(self):
        code, out = self.check("all-headers.cpp\n")
        self.assertEqual(code, 1)
        self.assertIn("reported no class layouts", out)

    def test_from_the_freeze_on_a_missing_record_is_not_made_again(self):
        self.version = (0, 5)
        self.assertEqual(self.check(report(UNIT))[0], 1)
        self.assertEqual(self.accept(report(UNIT))[0], 1)
        self.assertFalse(os.path.exists(layouts.RECORD))

    def test_accept_saves_the_current_layouts_and_version(self):
        self.check(report(UNIT))
        self.version = (0, 4)
        code, out = self.accept(report(GROWN))
        self.assertEqual(code, 0)
        self.assertIn("Rebuild every plugin. If you changed CIV_HOST_API_MAJOR for this, set it back", out)
        self.assertEqual(self.saved(), ((0, 4), layouts.parse_report(report(GROWN))))

    def test_accept_with_no_record_saves_one(self):
        self.assertEqual(self.accept(report(UNIT))[0], 0)
        self.assertEqual(self.saved(), ((0, 3), layouts.parse_report(report(UNIT))))

    def test_accept_with_nothing_changed_keeps_the_version(self):
        self.check(report(UNIT))
        self.version = (1, 0)
        self.assertEqual(self.accept(report(UNIT, CITY))[0], 0)
        self.assertEqual(self.saved(), ((0, 3), layouts.parse_report(report(UNIT, CITY))))

    def test_accept_is_refused_for_a_changed_class_once_frozen_and_names_it(self):
        self.freeze(UNIT)
        code, out = self.accept(report(GROWN))
        self.assertEqual(code, 1)
        self.assertIn("changed: class CvUnit", out)
        self.assertIn("set CIV_HOST_API_MAJOR", out)
        self.assertEqual(self.saved(), ((0, 3), layouts.parse_report(report(UNIT))))

    def test_without_a_release_tag_the_advice_says_to_fetch_the_tags(self):
        self.assertIn("git fetch --tags", "\n".join(layouts.frozen_advice(None)))

    def test_until_the_freeze_is_tagged_a_change_is_made_under_0(self):
        self.assertIn("CivPluginApi.h to 0 and run", "\n".join(layouts.frozen_advice("v0.4.1")))
        for tag, major in (("v0.5.0", 1), ("v0.9.0", 1), ("v1.0.0", 2), ("v1-beta", 2)):
            advice = "\n".join(layouts.frozen_advice(tag))
            self.assertNotIn("to 0 and run", advice, tag)
            self.assertIn("CivPluginApi.h to %d," % major, advice, tag)

    def test_accept_of_a_gone_class_is_allowed_once_frozen_and_keeps_the_version(self):
        self.freeze(UNIT, CITY)
        code, out = self.accept(report(UNIT))
        self.assertEqual(code, 0)
        self.assertNotIn("Rebuild every plugin.", out)
        self.assertEqual(self.saved(), ((0, 3), layouts.parse_report(report(UNIT))))


@unittest.skipUnless(shutil.which("cl"), "needs cl.exe on the path, as tests/runtime/run.cmd sets up")
class RealReportTest(unittest.TestCase):
    def compiled(self, unit_body, before=""):
        unit = os.path.join(temp_folder(self), "shapes.cpp")
        with open(unit, "w") as f:
            f.write(
                before + "struct Base { virtual ~Base() {} virtual int Range() const { return 1; } int m_owner; };\n"
                "struct Unit : public Base { %s };\n"
                "struct Outer { struct iterator { int* p; }; iterator m_it; };\n" % unit_body
            )
        return layouts.compile_report(unit, [], [], "plugins'")

    def report_of(self, unit_body):
        return layouts.parse_report(self.compiled(unit_body))

    def lost_keys(self, before, after):
        return [key for key, _, _ in layouts.compare(before, after)[0]]

    def test_the_compiler_report_parses_and_an_added_field_is_caught(self):
        before = self.report_of("char m_flag; double m_health;")
        keys = set(key for key, _ in before)
        self.assertTrue({"class Base", "class Unit", "class Outer", "class iterator"} <= keys)
        self.assertIn(
            "class Unit", self.lost_keys(before, self.report_of("char m_flag; int m_added; double m_health;"))
        )

    def test_reordered_virtual_functions_are_caught(self):
        before = self.report_of("virtual void Move() {} virtual void Stop() {}")
        after = self.report_of("virtual void Stop() {} virtual void Move() {}")
        self.assertEqual(self.lost_keys(before, after), ["Unit::$vftable@"])

    def test_a_warning_does_not_reach_the_report(self):
        self.assertNotIn("warning", self.compiled("int m_x;", before="#define TWICE 1\n#define TWICE 2\n"))


if __name__ == "__main__":
    unittest.main()
