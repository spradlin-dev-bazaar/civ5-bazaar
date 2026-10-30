"""The hand-built records follow analyze.py's function_record; tests/runtime/hook_fixture.py runs the whole generator
over a fixture.

    python -m unittest discover -s tests/generator
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "generator"))

import generate  # noqa: E402


def function(
    name,
    displayname=None,
    cls=None,
    namespaces=(),
    linkage="EXTERNAL",
    file="CvUnit.cpp",
    const=False,
    params=(),
    result_type="void",
    static=False,
):
    return {
        "name": name,
        "displayname": displayname or name + "()",
        "class": cls,
        "namespaces": list(namespaces),
        "linkage": linkage,
        "file": file,
        "const": const,
        "params": [{"type": t} for t in params],
        "result_type": result_type,
        "static_method": static,
    }


def written_params(data, *written):
    """Each parameter's offsets as analyze.py records them; libclang locates an unnamed one at its start."""
    out, at = [], 0
    for param, name in written:
        start = data.index(param.encode(), at)
        loc = data.index(name.encode(), start) if name else start
        out.append({"start": start, "end": start + len(param), "name": name, "loc": loc})
        at = start + len(param)
    return out


def write_file(folder, name, data):
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


class HookKeyTest(unittest.TestCase):
    def test_member_function_names_its_class_parameters_and_constness(self):
        fn = function("getX", "getX(int)", cls="CvUnit", const=True)
        self.assertEqual(generate.hook_key(fn), "CvUnit::getX(int) const")

    def test_overloads_and_constness_tell_functions_apart(self):
        keys = {
            generate.hook_key(function("getX", "getX(int)", cls="CvUnit")),
            generate.hook_key(function("getX", "getX(bool)", cls="CvUnit")),
            generate.hook_key(function("getX", "getX(int)", cls="CvUnit", const=True)),
        }
        self.assertEqual(len(keys), 3)

    def test_namespaces_come_before_the_class_and_anonymous_ones_are_left_out(self):
        self.assertEqual(generate.hook_key(function("draw", namespaces=["Gfx", ""])), "Gfx::draw()")
        self.assertEqual(generate.hook_key(function("f", cls="C", namespaces=["N"])), "N::C::f()")
        self.assertEqual(generate.hook_key(function("f", cls="A::B", namespaces=["N"])), "N::A::B::f()")

    def test_a_file_local_function_leads_with_its_file(self):
        local = function("Help", linkage="INTERNAL", file="Sub\\Helpers.cpp")
        self.assertEqual(generate.hook_key(local), "Sub/Helpers.cpp:Help()")
        unique = function("Help", cls="Local", linkage="UNIQUE_EXTERNAL", file="Other.cpp")
        self.assertEqual(generate.hook_key(unique), "Other.cpp:Local::Help()")


class HookNameTest(unittest.TestCase):
    def test_a_file_name_with_a_leading_digit_still_makes_a_valid_name(self):
        local = function("Helper", linkage="INTERNAL", file="2DGrid.cpp")
        self.assertEqual(generate.hook_name(local, set()), "File_2DGrid_cpp_Helper")

    def test_a_taken_name_adds_the_parameter_types_then_a_number(self):
        overload = function("Pack", cls="CvUnit", params=["unsigned __int64"])
        self.assertEqual(generate.hook_name(overload, {"CvUnit_Pack"}), "CvUnit_Pack_with_unsigned_int64")
        taken = {"CvUnit_Pack", "CvUnit_Pack_with_unsigned_int64"}
        self.assertEqual(generate.hook_name(overload, taken), "CvUnit_Pack_with_unsigned_int64_2")

    def test_a_taken_name_for_a_const_overload_says_so(self):
        overload = function("Pack", cls="CvUnit", const=True, params=["int"])
        self.assertEqual(generate.hook_name(overload, {"CvUnit_Pack"}), "CvUnit_Pack_with_int_const")

    def test_an_operator_is_named_by_its_word(self):
        self.assertEqual(generate.hook_name(function("operator=="), set()), "op_eq")


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "hook-ids.txt")

    def tearDown(self):
        shutil.rmtree(self.folder)

    def write(self, text):
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def test_the_first_id_is_zero(self):
        self.assertEqual(generate.Registry(self.path).claim(function("A"))[1], 0)

    def test_a_listed_function_keeps_its_id_and_a_new_one_takes_the_next(self):
        self.write("0\tA\tA()\n\n1\tB\tB()\n")
        registry = generate.Registry(self.path)
        self.assertEqual(registry.claim(function("B")), ("B()", 1, "B"))
        self.assertEqual(registry.claim(function("C")), ("C()", 2, "C"))
        self.assertEqual(registry.added, 1)

    def test_new_overloads_never_take_a_name_already_given(self):
        self.write("0\tCvUnit_Pack\tCvUnit::Pack(int)\n")
        registry = generate.Registry(self.path)
        first = function("Pack", "Pack(bool)", cls="CvUnit", params=["bool"])
        second = function("Pack", "Pack(char)", cls="CvUnit", params=["char"])
        names = [registry.claim(fn)[2] for fn in (first, second)]
        self.assertEqual(names, ["CvUnit_Pack_with_bool", "CvUnit_Pack_with_char"])

    def test_two_new_overloads_in_one_run_get_different_names(self):
        registry = generate.Registry(self.path)
        first = function("Pack", "Pack(bool)", cls="CvUnit", params=["bool"])
        second = function("Pack", "Pack(char)", cls="CvUnit", params=["char"])
        self.assertEqual([registry.claim(fn)[2] for fn in (first, second)], ["CvUnit_Pack", "CvUnit_Pack_with_char"])

    def run_claiming(self, header_problem=None, build_files_problem=None):
        """A generator run that claims one new function; its plugin-header check fails with header_problem, and writing
        the engine's build files with build_files_problem."""

        def plan(functions, project, files, edits, registry):
            registry.claim(function("B"))
            return [], {}, {}

        def fail_with(problem, result=None):
            def step(*args):
                if problem:
                    raise problem
                return result

            return step

        project = types.SimpleNamespace(registry=self.path, root=self.folder, vcproj="Engine.vcproj")
        with contextlib.ExitStack() as stack:
            for name, replacement in (
                ("load_analysis", lambda project: ([], [])),
                ("plan_hooks", plan),
                ("mark_exports", lambda functions, files, edits: (0, 0)),
                ("write_mirror", lambda *args: None),
                ("hand_hook_sites", lambda *args: []),
                ("write_table", lambda *args: None),
                ("write_plugin_header", fail_with(header_problem, [])),
                ("write_engine_build_files", fail_with(build_files_problem)),
            ):
                stack.enter_context(mock.patch.object(generate, name, replacement))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            generate.run(project)

    def test_a_run_saves_its_new_ids_only_once_its_checks_have_passed(self):
        self.write("0\tA\tA()\n")
        for failing in (
            {"header_problem": RuntimeError("generator: could not read the game's headers as a plugin does")},
            {"build_files_problem": SystemExit("generator: the project file no longer contains its source list")},
        ):
            with self.subTest(failing=failing), self.assertRaises(BaseException):
                self.run_claiming(**failing)
            with open(self.path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "0\tA\tA()\n")
        self.run_claiming()
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "0\tA\tA()\n1\tB\tB()\tvoid\n")

    def test_an_id_is_never_reused(self):
        self.write("0\tA\tA()\n5\tB\tB()\n")
        registry = generate.Registry(self.path)
        self.assertEqual(registry.claim(function("C"))[1], 6)
        registry.save()
        reread = generate.Registry(self.path)
        self.assertEqual(reread.entries[("B()", "")], (5, "B"), "a function no longer claimed keeps its row")
        self.assertEqual(reread.claim(function("D"))[1], 7)

    def test_the_saved_list_is_in_id_order_and_reads_back_the_same(self):
        self.write("10\tA\tA()\n9\tB\tB()\n")
        registry = generate.Registry(self.path)
        registry.claim(function("C", result_type="int"))
        registry.save()
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), b"9\tB\tB()\n10\tA\tA()\n11\tC\tC()\tint\n")
        self.assertEqual(generate.Registry(self.path).entries, registry.entries)

    def test_a_row_written_before_shapes_were_recorded_keeps_its_id_and_takes_the_shape(self):
        self.write("0\tA\tA()\n")
        registry = generate.Registry(self.path)
        self.assertEqual(registry.claim(function("A", result_type="int"))[1], 0)
        registry.save()
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), b"0\tA\tA()\tint\n")

    def test_a_function_whose_return_type_or_staticness_changes_gets_a_new_id(self):
        self.write("0\tA\tA()\tint\n")
        registry = generate.Registry(self.path)
        for fn in (function("A", result_type="bool"), function("A", result_type="int", static=True)):
            key, hook_id, name = registry.claim(fn)
            self.assertEqual(key, "A()")
            self.assertNotEqual((hook_id, name), (0, "A"))
        self.assertEqual(registry.entries[("A()", "int")], (0, "A"), "the old shape keeps its row")
        self.assertEqual(registry.claimed, {1, 2})
        self.assertEqual(registry.reshaped, 2)

    def test_the_plugin_header_leaves_out_a_gone_hook_and_names_the_one_that_replaced_it(self):
        self.write("0\tA\tA()\tint\n1\tB\tB()\tint\n")
        registry = generate.Registry(self.path)
        _, new_id, new_name = registry.claim(function("A", result_type="bool"))
        hooks = [{"hook_id": new_id, "signature": "bool A()"}]
        header, _ = generate.plugin_header(registry, hooks, {new_id}, "Engine.h")
        self.assertIn("\tstruct %s { enum { ID = %d }; }; // bool A()\n" % (new_name, new_id), header)
        self.assertIn(
            "\t// A (id 0) is no longer a hook point: its function changed, and its hook is now %s.\n" % new_name,
            header,
        )
        self.assertIn("\t// B (id 1) is no longer a hook point.\n", header)
        self.assertNotIn("struct A ", header)
        self.assertNotIn("struct B ", header)
        self.assertEqual(generate.header_hooks(header), [(new_name, new_id, False)])

    def test_the_plugin_header_gives_each_hook_point_its_types_and_marks_the_lines_that_declare_them(self):
        self.write("")
        registry = generate.Registry(self.path)
        fn = function("Score", cls="CvPlayer", const=True, params=["bool"], result_type="int")
        fn["result"] = {"kind": "scalar"}
        fn["signature"] = "int CvPlayer::Score(bool) const"
        _, fn["hook_id"], name = registry.claim(fn)
        header, type_lines = generate.plugin_header(registry, [fn], set(), "Engine.h")
        lines = header.split("\n")
        first = "\tstruct %s { enum { ID = %d }; // int CvPlayer::Score(bool) const" % (name, fn["hook_id"])
        start = lines.index(first)
        self.assertEqual(lines[start + 1 : start + 6], ["\t\t" + t for t in generate.plugin_typedefs(fn)] + ["\t};"])
        self.assertEqual(type_lines, dict((start + 2 + i, fn["hook_id"]) for i in range(4)))
        self.assertIn('#include "Engine.h"', header)
        self.assertEqual(generate.header_hooks(header), [(name, fn["hook_id"], True)])

    def test_a_hook_points_types_are_spelled_as_a_plugin_names_them(self):
        method = function("Score", "Score(bool)", "CvPlayer", ["Game", ""], const=True, params=["bool"])
        method["result_type"] = "int"
        method["result"] = {"kind": "scalar"}
        self.assertEqual(
            generate.plugin_typedefs(method),
            [
                "typedef int (*Original)(const Game::CvPlayer *, bool);",
                "typedef bool (*Before)(const Game::CvPlayer *, bool, CivHookSlot< int >::Type);",
                "typedef void (*After)(const Game::CvPlayer *, bool, CivHookSlot< int >::Type);",
                "typedef int (*Replace)(Original, const Game::CvPlayer *, bool);",
            ],
        )
        static = function("Make", cls="CvUnit", static=True, params=["std::vector<std::vector<int>>"])
        static["result"] = {"kind": "void"}
        self.assertEqual(
            generate.plugin_typedefs(static),
            [
                "typedef void (*Original)(std::vector<std::vector<int> >);",
                "typedef bool (*Before)(std::vector<std::vector<int> >);",
                "typedef void (*After)(std::vector<std::vector<int> >);",
                "typedef void (*Replace)(Original, std::vector<std::vector<int> >);",
            ],
        )

    def test_a_hook_points_qualified_types_and_the_functions_own_types_name_types_from_outside_their_class(self):
        method = function("Feel", "Feel(Mood)", "Unit", ["Game"], const=True, params=["Mood"], result_type="int")
        method["result"] = {"kind": "scalar"}
        method.update(canonical_class="Game::Unit", canonical_params=["Game::Unit::Mood"], canonical_result="int")
        self.assertEqual(
            generate.plugin_typedefs(method, qualified=True)[0],
            "typedef int (*Original)(const Game::Unit *, Game::Unit::Mood);",
        )
        self.assertEqual(generate.function_types(method), ("int", ["const Game::Unit *", "Game::Unit::Mood"]))

    def test_a_hook_point_fails_on_an_error_in_its_types_or_on_types_other_than_its_functions(self):
        type_lines = {12: 7, 13: 7, 20: 8, 21: 8}
        expected = {7: ("int", ["int"]), 8: ("void", [])}
        self.assertEqual(generate.failing_hooks(({21}, {12: ("int", ["int"])}), type_lines, expected), {8})
        self.assertEqual(generate.failing_hooks((set(), {12: ("int", ["long"])}), type_lines, expected), {7})
        with self.assertRaises(RuntimeError):
            generate.failing_hooks(({3}, {}), type_lines, expected)

    def test_a_hook_point_is_spelled_as_written_then_qualified_then_left_without_types_and_a_late_failure_stops(self):
        self.write("")
        registry = generate.Registry(self.path)
        hooks = []
        for name in ("Feel", "Rest"):
            fn = function(name, name + "(Mood)", "Unit", ["Game"], params=["Mood"], result_type="int")
            fn.update(result={"kind": "scalar"}, signature="int Game::Unit::%s(Mood)" % name)
            fn.update(canonical_class="Game::Unit", canonical_params=["Game::Unit::Mood"], canonical_result="int")
            _, fn["hook_id"], fn["hook_name"] = registry.claim(fn)
            hooks.append(fn)
        feel, rest = hooks[0]["hook_name"], hooks[1]["hook_name"]
        project = types.SimpleNamespace(plugin_include="Engine.h")
        rounds = []

        def failing(names):
            def check(project, path):
                with open(path) as f:
                    lines = f.read().split("\n")
                rounds.append(lines)
                struct = None
                errors = set()
                for number, line in enumerate(lines, 1):
                    struct = line.split()[1] if line.startswith("\tstruct ") else struct
                    if "(*Original)" in line and struct in names(len(rounds)):
                        errors.add(number)
                return errors, {}

            return check

        with mock.patch.object(generate.analyze, "check_plugin_header", failing(lambda n: [feel])):
            text, untyped, qualified = generate.checked_plugin_header(project, registry, hooks)
        self.assertEqual((untyped, qualified), ({hooks[0]["hook_id"]}, set()))
        self.assertIn("\t\ttypedef int (*Original)(Game::Unit *, Mood);", rounds[0])
        self.assertIn("\t\ttypedef int (*Original)(Game::Unit *, Game::Unit::Mood);", rounds[1])
        self.assertEqual([has_types for _, _, has_types in generate.header_hooks(text)], [False, True])
        del rounds[:]
        with mock.patch.object(generate.analyze, "check_plugin_header", failing(lambda n: [feel] if n == 1 else [])):
            _, untyped, qualified = generate.checked_plugin_header(project, registry, hooks)
        self.assertEqual((untyped, qualified), (set(), {hooks[0]["hook_id"]}))
        del rounds[:]
        late = failing(lambda n: [feel] if n < 3 else [rest])
        with mock.patch.object(generate.analyze, "check_plugin_header", late):
            with self.assertRaises(RuntimeError):
                generate.checked_plugin_header(project, registry, hooks)

    def test_a_repeated_id_name_or_function_is_refused(self):
        for text in (
            "0\tA\tA()\n0\tB\tB()\n",
            "0\tA\tA()\n1\tA\tB()\n",
            "0\tA\tA()\n1\tB\tA()\n",
            "0\tA\tA()\tint\n1\tB\tA()\tint\n",
        ):
            self.write(text)
            with self.assertRaises(RuntimeError, msg=repr(text)):
                generate.Registry(self.path)
        self.write("0\tA\tA()\tint\n1\tA_bool\tA()\tbool\n")
        self.assertEqual(len(generate.Registry(self.path).entries), 2, "one function in two shapes is two rows")

    def test_a_line_that_is_not_id_name_function_is_refused(self):
        for text in ("x\tA\tA()\n", "0\tA\n", "\u00b2\tA\tA()\n"):
            self.write(text)
            with self.assertRaises(RuntimeError, msg=repr(text)):
                generate.Registry(self.path)


class ApplyEditsTest(unittest.TestCase):
    def test_every_edit_uses_the_original_offsets(self):
        data = b"int f(int a);"
        edits = [(4, 5, "CivOrig_f"), (0, 0, "CIV_HOST_API ")]
        self.assertEqual(generate.apply_edits(data, edits), b"CIV_HOST_API int CivOrig_f(int a);")
        self.assertEqual(generate.apply_edits(data, edits[::-1]), b"CIV_HOST_API int CivOrig_f(int a);")

    def test_texts_inserted_at_one_offset_keep_their_listed_order(self):
        edits = [(1, 1, "A"), (1, 1, "B")]
        self.assertEqual(generate.apply_edits(b"xy", edits), b"xABy")
        self.assertEqual(generate.apply_edits(b"xy", edits[::-1]), b"xBAy")

    def test_an_insert_at_either_end_of_a_replaced_range_stays_outside_it(self):
        edits = [(4, 7, "CivOrig_foo"), (4, 4, "X "), (7, 7, " Y")]
        for listing in (edits, edits[::-1]):
            self.assertEqual(generate.apply_edits(b"int foo(int a);", listing), b"int X CivOrig_foo Y(int a);")

    def test_overlapping_edits_are_refused(self):
        for edits in ([(4, 7, "R"), (5, 5, "X")], [(4, 7, "R"), (6, 9, "S")], [(4, 7, "R"), (4, 7, "S")]):
            with self.assertRaises(RuntimeError, msg=repr(edits)):
                generate.apply_edits(b"int foo(int a);", edits)


class EditProducerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder)

    def member(self, data, name, tokens):
        """A member function whose in-class declaration is the token list, ending just before its `;`."""
        path = write_file(self.folder, "unit.h", data)
        offsets, at = [], data.index(tokens[0].encode())
        for spelling in tokens:
            at = data.index(spelling.encode(), at)
            offsets.append((spelling, at))
            at += len(spelling)
        name_offset = next(offset for spelling, offset in offsets if spelling in (name, "operator"))
        decl = {"file": path, "tokens": offsets, "name_offset": name_offset, "extent_end": at}
        return dict(function(name, cls="CvUnit"), decl=decl), path

    def test_the_original_is_declared_before_the_semicolon_of_its_declaration(self):
        data = b"class CvUnit {\n\tint Grow(int x) const;\n};"
        fn, path = self.member(data, "Grow", ["int", "Grow", "(", "int", "x", ")", "const"])
        files = generate.PathDict()
        at, insert = generate.orig_declaration(fn, files)[1:]
        self.assertEqual(at, data.index(b";"))
        out = generate.apply_edits(data, [(at, at, insert)])
        self.assertEqual(out, b"class CvUnit {\n\tint Grow(int x) const; int CivOrig_Grow ( int x ) const;\n};")

    def test_a_pure_virtual_original_is_not_pure_and_an_operator_takes_its_word(self):
        data = b"class CvUnit {\n\tvirtual void f() = 0;\n\tbool operator==(int x);\n};"
        fn, _ = self.member(data, "f", ["void", "f", "(", ")", "=", "0"])
        self.assertEqual(generate.orig_declaration(fn, generate.PathDict())[2], "; void CivOrig_f ( )")
        op, _ = self.member(data, "operator==", ["bool", "operator", "==", "(", "int", "x", ")"])
        self.assertEqual(generate.orig_declaration(op, generate.PathDict())[2], "; bool CivOrigOp_eq ( int x )")

    def test_a_declaration_that_does_not_end_at_a_semicolon_is_skipped(self):
        data = b"class CvUnit {\n\tint Grow(int x) const {}\n};"
        fn, _ = self.member(data, "Grow", ["int", "Grow", "(", "int", "x", ")", "const"])
        with self.assertRaises(generate.Skip):
            generate.orig_declaration(fn, generate.PathDict())

    def test_the_original_declaration_and_the_next_declarations_export_marker_never_meet(self):
        data = b"class CvUnit {\n\tint Grow(int x);int Shrink(int x);\n};"
        fn, path = self.member(data, "Grow", ["int", "Grow", "(", "int", "x", ")"])
        _, at, insert = generate.orig_declaration(fn, generate.PathDict())
        marker = data.index(b"int Shrink")
        edits = [(at, at, insert), (marker, marker, "CIV_HOST_API ")]
        expected = b"class CvUnit {\n\tint Grow(int x); int CivOrig_Grow ( int x );CIV_HOST_API int Shrink(int x);\n};"
        for listing in (edits, edits[::-1]):
            self.assertEqual(generate.apply_edits(data, listing), expected)

    def free(self, data, name, namespaces=(), lex_namespaces=(), params=()):
        fn = function(name, namespaces=namespaces)
        fn.update(
            def_start=0,
            name_start=data.index(name.encode()),
            name_end=data.index(name.encode()) + len(name),
            body_start=data.index(b"{"),
            lex_namespaces=list(lex_namespaces),
            decl=None,
            params=written_params(data, *params),
        )
        return fn

    def test_a_free_function_with_no_declaration_gets_one_ahead_of_its_definition(self):
        data = b"int Helper(int a = 2)\n{"
        fn = self.free(data, "Helper", params=[("int a = 2", "a")])
        self.assertEqual(generate.free_function_declarations(fn, data, True), "CIV_HOST_API int Helper(int a = 2); ")
        self.assertEqual(generate.free_function_declarations(fn, data, False), "int Helper(int a = 2); ")
        fn["decl"] = {"file": "unit.h"}
        self.assertEqual(generate.free_function_declarations(fn, data, True), "")

    def test_a_declaration_that_would_put_an_if_mid_line_is_refused(self):
        data = b"int Helper(int a\n#if X\n, int b\n#endif\n)\n{"
        fn = self.free(data, "Helper", params=[("int a", "a"), ("int b", "b")])
        with self.assertRaises(generate.Skip):
            generate.free_function_declarations(fn, data, True)

    def test_a_qualified_free_function_declares_its_original_inside_its_namespace(self):
        data = b"void Gfx::draw(int n)\n{"
        fn = self.free(data, "draw", namespaces=["Gfx"], params=[("int n", "n")])
        expected = "namespace Gfx { void CivOrig_draw(int n); } "
        self.assertEqual(generate.free_function_declarations(fn, data, False), expected)
        for lexical in (["Gfx"], ["Other"]):
            fn["lex_namespaces"] = lexical
            with self.assertRaises(generate.Skip, msg=repr(lexical)):
                generate.free_function_declarations(fn, data, False)

    def test_each_declaration_is_marked_for_export_once_and_a_mismatch_is_counted(self):
        data = b"int a();\nstatic int b();\n"
        path = write_file(self.folder, "unit.h", data)
        site_a = {"first_token": "int", "is_definition": False, "file": path, "start": 0}
        site_b = {"first_token": "int", "is_definition": False, "file": path, "start": data.index(b"static")}
        functions = [
            {"export_decl": site_a},
            {"export_decl": dict(site_a)},
            {"export_decl": site_b},
            {"export_decl": dict(site_a, first_token="friend")},
            {"export_decl": {"first_token": "int", "is_definition": True}, "hook_id": 3},
            {"export_decl": {"first_token": "int", "is_definition": True}},
            {"export_decl": None},
        ]
        edits = generate.PathDict()
        self.assertEqual(generate.mark_exports(functions, generate.PathDict(), edits), (2, 1))
        self.assertEqual(edits[path], [(0, 0, "CIV_HOST_API ")])

    def test_a_declaration_reached_under_two_spellings_is_marked_once_where_capitals_count(self):
        path = write_file(self.folder, "Unit.h", b"int a();\n")
        site = {"first_token": "int", "is_definition": False, "file": path, "start": 0}
        functions = [{"export_decl": site}, {"export_decl": dict(site, file=path.upper())}]
        edits = generate.PathDict()
        with mock.patch.object(os.path, "normcase", lambda path: path):
            self.assertEqual(generate.mark_exports(functions, generate.PathDict(), edits), (1, 0))
            self.assertEqual(edits[path.lower()], [(0, 0, "CIV_HOST_API ")])


class PathDictTest(unittest.TestCase):
    def test_a_path_is_found_in_any_case_and_with_either_slash(self):
        files = generate.PathDict()
        files[os.path.join(tempfile.gettempdir(), "Engine", "CvUnit.h")] = 1
        self.assertEqual(files[os.path.join(tempfile.gettempdir(), "engine", "CVUNIT.H").replace("\\", "/")], 1)

    def test_a_path_is_found_in_any_case_where_capitals_count(self):
        files = generate.PathDict()
        with mock.patch.object(os.path, "normcase", lambda path: path):
            files[os.path.join(tempfile.gettempdir(), "Engine", "CvUnit.h")] = 1
            self.assertEqual(files[os.path.join(tempfile.gettempdir(), "engine", "CVUNIT.H")], 1)


class SignatureTest(unittest.TestCase):
    def test_a_signature_with_no_other_versions_is_kept(self):
        self.assertEqual(generate.active_version("int f(int a) const"), "int f(int a) const")

    def test_the_other_version_after_the_active_one_is_cut(self):
        sig = "void f(int a, bool b)\n#else\nvoid f(int a)\n#endif\n"
        self.assertEqual(generate.active_version(sig), "void f(int a, bool b)")
        self.assertEqual(generate.active_version("void f(int a, bool b)\n#endif\n"), "void f(int a, bool b)")

    def test_an_if_closed_inside_the_signature_is_kept(self):
        sig = "void f(int a\n#if X\n, bool b\n#endif\n)"
        self.assertEqual(generate.active_version(sig), sig)

    def test_an_if_the_signature_leaves_open_is_dropped_unless_it_has_another_branch(self):
        self.assertEqual(generate.active_version("void f(int a\n#if X\n, bool b)"), "void f(int a\n, bool b)")
        with self.assertRaises(generate.Skip):
            generate.active_version("void f(int a\n#if X\n, bool b\n#else\n, int c)")

    def test_only_an_equals_sign_outside_brackets_starts_a_default(self):
        self.assertEqual(generate.top_level_equals("Foo<(a==b)> x = 0"), len("Foo<(a==b)> x "))
        self.assertEqual(generate.top_level_equals("std::map<int, int> m"), 0)

    def test_a_parameter_loses_its_name_and_default_and_an_unnamed_one_gets_a_name(self):
        data = b"void f(const CvPlot* pPlot, int iRange = MAX(1, 2), bool)"
        params = [("const CvPlot* pPlot", "pPlot"), ("int iRange = MAX(1, 2)", "iRange"), ("bool", "")]
        fn = {"params": written_params(data, *params)}
        parts = [generate.param_parts(fn, data, i) for i in range(3)]
        self.assertEqual(parts, [("const CvPlot*", "pPlot"), ("int", "iRange"), ("bool", "civ_p2")])

    def test_the_wrapper_signature_drops_defaults_and_names_unnamed_parameters(self):
        data = b"int CvUnit::f(int a = 3, bool)"
        fn = {"def_start": 0, "body_start": len(data), "params": written_params(data, ("int a = 3", "a"), ("bool", ""))}
        self.assertEqual(generate.wrapper_signature(fn, data), "int CvUnit::f(int a , bool civ_p1)")
        self.assertEqual(
            generate.wrapper_signature(fn, data, keep_defaults=True), "int CvUnit::f(int a = 3, bool civ_p1)"
        )

    def test_an_unnamed_parameter_with_a_default_is_skipped(self):
        data = b"void f(int = 3)"
        fn = {"def_start": 0, "body_start": len(data), "params": written_params(data, ("int = 3", ""))}
        with self.assertRaises(generate.Skip):
            generate.wrapper_signature(fn, data)

    def test_the_return_type_loses_specifiers_and_the_written_qualifier(self):
        cases = [
            (b"static inline const CvPlot* CvMap::plot(int x) const", "plot", "const CvPlot*"),
            (b"__declspec(noinline) int __cdecl g()", "g", "int"),
            (b"std::vector<int> Grid<T>::get()", "get", "std::vector<int>"),
        ]
        for data, name, expected in cases:
            fn = {"def_start": 0, "name_start": data.index(name.encode())}
            self.assertEqual(generate.return_text(fn, data), expected)
        with self.assertRaises(generate.Skip):
            generate.return_text({"def_start": 0, "name_start": 7}, b"inline f()")


class SkipTest(unittest.TestCase):
    def test_a_function_the_generator_cannot_hook_gets_no_id_and_no_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = generate.Registry(os.path.join(folder, "hook-ids.txt"))
            friend = {"first_token": "friend", "is_definition": False}
            functions = [
                dict(function("Pack"), skip=[], def_start=0, decl=None, export_decl=friend),
                dict(function("Unpack"), skip=[], def_start=1, decl=None, export_decl=friend),
                dict(function("operator,"), skip=[], def_start=2, decl=None),
                dict(function("Broken"), skip=["template"], def_start=3, decl=None),
            ]
            edits = generate.PathDict()
            project = types.SimpleNamespace(root=folder)
            hooks, skipped, wrappers = generate.plan_hooks(functions, project, generate.PathDict(), edits, registry)
            self.assertEqual(hooks, [])
            self.assertEqual(skipped, {"friend function": 2, "operator without a hook name": 1})
            reasons = [["friend function"], ["friend function"], ["operator without a hook name"], ["template"]]
            self.assertEqual([fn["skip"] for fn in functions], reasons)
            self.assertEqual((dict(edits), dict(wrappers), registry.added), ({}, {}, 0))


class LineDirectiveTest(unittest.TestCase):
    def test_a_file_without_includes_starts_with_the_directive(self):
        self.assertEqual(generate.add_line_directive("p.cpp", b"int x;\r\n"), b'#line 1 "p.cpp"\r\nint x;\r\n')

    def test_the_directive_follows_the_last_include_and_names_the_next_line(self):
        data = b'#include "a.h"\r\n#pragma once\r\nint x;\r\n'
        expected = b'#include "a.h"\r\n#pragma once\r\n#line 3 "p.cpp"\r\nint x;\r\n'
        self.assertEqual(generate.add_line_directive("p.cpp", data), expected)

    def test_a_last_include_with_no_line_end_gets_one(self):
        self.assertEqual(
            generate.add_line_directive("p.cpp", b'#include "a.h"'), b'#include "a.h"\r\n#line 2 "p.cpp"\r\n'
        )

    def test_backslashes_in_a_windows_path_are_escaped(self):
        self.assertEqual(
            generate.add_line_directive("C:\\src\\p.cpp", b"int x;"), b'#line 1 "C:\\\\src\\\\p.cpp"\r\nint x;'
        )


class HandHookSiteTest(unittest.TestCase):
    def test_calls_in_a_hooked_body_count_once_per_hook_and_function(self):
        data = (
            b"void A() { CivHandPopupRaised(1); CivHandPopupRaised (2); }\n"
            b"int x = CivHandDealResolved(4);\n"
            b"void B() { CivHandIsPluginControlledPlayer(3); }\n"
        )
        a_start, a_end = data.index(b"{"), data.index(b"}") + 1
        b_start = data.index(b"{", a_end)
        hooks = [
            {"file": "f.cpp", "body_start": a_start, "def_end": a_end, "hook_id": 9},
            {"file": "f.cpp", "body_start": b_start, "def_end": len(data), "hook_id": 7},
        ]
        sites = generate.hand_hook_sites(hooks, {os.path.join("root", "f.cpp"): data}, "root")
        self.assertEqual(sites, [("CIV_HAND_IS_PLUGIN_CONTROLLED_PLAYER", 7), ("CIV_HAND_POPUP_RAISED", 9)])


if __name__ == "__main__":
    unittest.main()
