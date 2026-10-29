"""Checks of tools/release.py that need no build: reading the build's lists, choosing the number, the checks before a
release is built or published, and the files it writes.

python -m unittest discover -s tests/release
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import release  # noqa: E402
import version  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "generator"))

import generate  # noqa: E402

DUMPBIN = """
    ordinal hint RVA      name

          1    0 00017B50 ??0CustomMods@@QAE@XZ = ??0CustomMods@@QAE@XZ (public: CustomMods::CustomMods(void))
          2    1 003D8B00 ?yieldX@CvFractal@@IAEHH@Z = ?yieldX@CvFractal@@IAEHH@Z (int CvFractal::yieldX(int))
          3    2 00202550 DllGetGameContext = _DllGetGameContext

  Summary
"""

API_HEADER = """#pragma once
// The handshake.
#define CIV_HOST_API_MAJOR 0
#define CIV_HOST_API_MINOR 3

/* What a plugin
   gets. */
enum CivHandHook
{
	CIV_HAND_FIRST,
	CIV_HAND_SECOND,
	CIV_HAND_HOOK_COUNT,
};
struct CivHostInfo
{
	int  size; // in bytes
};
typedef bool (*CivPluginEntryFn)(const CivHostInfo* host,
	CivPluginInfo* plugin);
"""


def layout_record(*classes):
    blocks = [
        ("class " + name, "class %s\tsize(%d):\n\t+---\n 0\t| x\n\t+---" % (name, size)) for name, size in classes
    ]
    return release.layouts.format_record((0, 3), blocks)


def changes(added=(), removed=()):
    return [release.Difference("hooks", list(added), list(removed))]


def api_change(edited):
    return release.ordered_difference("header", release.api_statements(API_HEADER), release.api_statements(edited))


class ListTest(unittest.TestCase):
    def test_the_generators_hook_header_reads_back_as_its_live_hooks(self):
        with tempfile.TemporaryDirectory() as folder:
            registry_path = os.path.join(folder, "hook-ids.txt")
            with open(registry_path, "w") as f:
                f.write("0\tCvCity_init\tCvCity::init()\tvoid\n")
                f.write("1\tCvUnit_kill\tCvUnit::kill()\tvoid\n")
                f.write("10\tCvPlot_area\tCvPlot::area()\tint\n")
            hooks = [
                {"hook_id": 0, "signature": "void CvCity::init()"},
                {
                    "hook_id": 10,
                    "signature": "int CvPlot::area()",
                    "class": "CvPlot",
                    "namespaces": [],
                    "static_method": False,
                    "const": False,
                    "params": [],
                    "result": {"kind": "scalar"},
                    "result_type": "int",
                },
            ]
            header, _ = generate.plugin_header(generate.Registry(registry_path), hooks, {0}, "Engine.h")
            self.assertEqual(release.hooks_from(header), ["0\tCvCity_init", "10\tCvPlot_area"])

    def test_exported_names_are_read_without_their_undecorated_forms(self):
        text = "       3 number of functions\n       3 number of names\n" + DUMPBIN
        self.assertEqual(
            release.exports_from(text), ["??0CustomMods@@QAE@XZ", "?yieldX@CvFractal@@IAEHH@Z", "DllGetGameContext"]
        )

    def test_exported_names_that_do_not_add_up_stop(self):
        for head in ("       4 number of names\n", ""):
            with self.subTest(head=head), self.assertRaises(SystemExit) as stop:
                release.exports_from(head + DUMPBIN)
            self.assertIn("could not be read", str(stop.exception))

    def test_a_saved_list_is_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "hooks.txt")
            release.write_list(path, "0.3.0", ["9\tCvCity_init", "10\tCvUnit_kill"])
            self.assertEqual(release.read_list(path), ("0.3.0", ["9\tCvCity_init", "10\tCvUnit_kill"]))

    def test_a_list_without_its_release_line_stops(self):
        with self.assertRaises(SystemExit) as stop:
            release.parse_list("9\tCvCity_init\n", "hooks.txt")
        self.assertIn("does not start with 'release <number>'", str(stop.exception))

    def test_saved_lists_that_do_not_belong_together_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            hooks, exports = os.path.join(folder, "hooks.txt"), os.path.join(folder, "exports.txt")
            with mock.patch.object(release, "HOOKS_LIST", hooks), mock.patch.object(release, "EXPORTS_LIST", exports):
                self.assertIsNone(release.saved_release())
                release.write_list(hooks, "0.3.0", [])
                with self.assertRaises(SystemExit) as stop:
                    release.saved_release()
                self.assertIn("is missing", str(stop.exception))
                release.write_list(exports, "0.2.0", [])
                with self.assertRaises(SystemExit) as stop:
                    release.saved_release()
                self.assertIn("saved by different releases", str(stop.exception))
                release.write_list(exports, "0.3.0", [])
                self.assertEqual(release.saved_release(), "0.3.0")


class DifferenceTest(unittest.TestCase):
    def test_api_header_comments_spacing_wrapping_and_version_are_no_change(self):
        edited = (
            API_HEADER.replace("// The handshake.", "// What the host and a plugin agree on.")
            .replace("What a plugin", "What each plugin")
            .replace("MINOR 3", "MINOR 4")
            .replace("int  size;", "int size;")
            .replace("host,\n\tCivPluginInfo* plugin);", "host, CivPluginInfo* plugin);")
        )
        self.assertEqual(api_change(edited), ("header", [], []))

    def test_an_enum_value_added_before_the_count_is_only_added(self):
        found = api_change(API_HEADER.replace("\tCIV_HAND_HOOK_COUNT,", "\tCIV_HAND_THIRD,\n\tCIV_HAND_HOOK_COUNT,"))
        self.assertEqual((found.added, found.removed), (["CIV_HAND_THIRD,"], []))

    def test_enum_values_that_swap_places_are_a_change(self):
        found = api_change(API_HEADER.replace("FIRST,\n\tCIV_HAND_SECOND,", "SECOND,\n\tCIV_HAND_FIRST,"))
        self.assertTrue(found.removed)

    def test_a_changed_declaration_is_added_and_removed(self):
        found = api_change(API_HEADER.replace("int  size", "long size"))
        self.assertEqual((found.added, found.removed), (["long size;"], ["int size;"]))

    def test_a_class_that_changed_is_removed_and_a_new_one_added(self):
        found = release.layout_difference(
            layout_record(("A", 4), ("B", 4)), layout_record(("A", 8), ("B", 4), ("C", 4))
        )
        self.assertEqual((found.added, found.removed), (["class C"], ["class A"]))

    def test_bazaar_s_host_info_grown_at_its_end_is_added_not_removed(self):
        host = "class CivHostInfo\tsize(4):\n\t+---\n 0\t| pluginIndex\n\t+---"
        types = "types CivHostInfo:\n field pluginIndex: int"
        then = release.layouts.format_record((0, 5), [("class CivHostInfo", host), ("types CivHostInfo", types)])
        grown_host = host.replace("size(4)", "size(8)").replace("pluginIndex\n", "pluginIndex\n 4\t| Log\n")
        grown_types = types + "\n field Log: void (*)(int)"
        now = release.layouts.format_record(
            (0, 5), [("class CivHostInfo", grown_host), ("types CivHostInfo", grown_types)]
        )
        found = release.layout_difference(then, now)
        self.assertEqual((found.added, found.removed), (["class CivHostInfo", "types CivHostInfo"], []))

    def test_an_enum_value_that_moved_is_removed_and_one_added_at_the_end_is_added(self):
        then = release.layouts.format_record((0, 3), [("enum E::A", "enum E::A = 0"), ("enum E::B", "enum E::B = 1")])
        now = then.replace("E::B = 1", "E::B = 2") + "enum E::C = 3\n\n"
        found = release.layout_difference(then, now)
        self.assertEqual((found.added, found.removed), (["enum E::C"], ["enum E::B"]))

    def test_identical_layouts_differ_in_nothing(self):
        found = release.layout_difference(layout_record(("A", 4)), layout_record(("A", 4)))
        self.assertEqual((found.added, found.removed), ([], []))

    def test_the_report_lists_a_limited_number_of_items(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            release.report("v0.3.0", changes(added=["hook %d" % n for n in range(release.MAX_LISTED + 1)]))
        self.assertIn("hooks added: %d" % (release.MAX_LISTED + 1), out.getvalue())
        self.assertIn("and 1 more", out.getvalue())
        self.assertNotIn("hook %d\n" % release.MAX_LISTED, out.getvalue())


class NumberTest(unittest.TestCase):
    def test_nothing_changed_raises_the_last_number_and_the_mod_version(self):
        self.assertEqual(release.next_version(version.Version("0.3.0", 1), changes()), ("0.3.1", 2))

    def test_something_added_raises_the_middle_number(self):
        self.assertEqual(release.next_version(version.Version("0.3.2", 4), changes(added=["x"])), ("0.4.0", 5))

    def test_something_removed_before_the_freeze_raises_the_middle_number(self):
        self.assertEqual(release.next_version(version.Version("0.3.2", 4), changes(removed=["x"])), ("0.4.0", 5))
        self.assertEqual(release.next_version(version.Version("0.4.1", 5), changes(removed=["x"])), ("0.5.0", 6))

    def test_something_added_from_the_freeze_on_raises_the_middle_number(self):
        self.assertEqual(release.next_version(version.Version("0.5.0", 6), changes(added=["x"])), ("0.6.0", 7))
        self.assertEqual(release.next_version(version.Version("1.2.3", 9), changes(added=["x"])), ("1.3.0", 10))

    def test_something_removed_from_the_freeze_on_needs_major(self):
        self.assertIsNone(release.next_version(version.Version("0.5.0", 6), changes(removed=["x"])))
        base, diffs = version.Version("1.2.3", 9), changes(removed=["x"])
        self.assertIsNone(release.next_version(base, diffs))
        with (
            mock.patch.object(release, "choose", return_value=("v1.2.3", base, diffs)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as stop:
                release.plan(None, False)
        self.assertIn("run it with --major", str(stop.exception))

    def test_major_starts_the_next_major_version(self):
        self.assertEqual(release.next_version(version.Version("0.3.2", 4), changes(), major=True), ("1.0.0", 5))
        major = release.next_version(version.Version("1.2.3", 9), changes(["x"], ["y"]), major=True)
        self.assertEqual(major, ("2.0.0", 10))


class ChooseTest(unittest.TestCase):
    SAVED = {
        "VERSION": "release 0.3.0\nmod 1\n",
        "hooks.txt": "release 0.3.0\n0\tCvCity_init\n",
        "exports.txt": "release 0.3.0\nDllGetGameContext\n",
    }

    def at_tag(self, tag, path, encoding="utf-8"):
        self.assertEqual(tag, "v0.3.0")
        if os.path.basename(path) in self.SAVED:
            return self.SAVED[os.path.basename(path)]
        return release.read_text(path, encoding)

    def choose(self, tag, lists):
        with (
            mock.patch.object(release, "last_release", return_value=tag),
            mock.patch.object(release, "at_tag", self.at_tag),
        ):
            return release.choose(lists)

    def test_the_first_release_keeps_versions_numbers(self):
        self.assertEqual(self.choose(None, None), (None, version.read(), None))

    def test_a_new_hook_since_the_tag_raises_the_middle_number(self):
        lists = (["0\tCvCity_init", "1\tCvUnit_kill"], ["DllGetGameContext"])
        tag, base, diffs = self.choose("v0.3.0", lists)
        self.assertEqual((tag, base), ("v0.3.0", ("0.3.0", 1)))
        self.assertEqual(
            [(d.what, d.added, d.removed) for d in diffs if d.added or d.removed], [("hooks", ["1\tCvUnit_kill"], [])]
        )
        self.assertEqual(release.next_version(base, diffs), ("0.4.0", 2))

    def test_release_tags_only_on_github_stop(self):
        with (
            mock.patch.object(release.layouts, "last_release_tag", return_value=None),
            mock.patch.object(release, "git", return_value="abc123\trefs/tags/v0.3.0") as git,
        ):
            with self.assertRaises(SystemExit) as stop:
                release.last_release()
        self.assertIn("git fetch --tags", str(stop.exception))
        git.assert_called_once_with("ls-remote", "--tags", "origin", "refs/tags/v[0-9]*")

    def test_a_build_that_no_longer_calls_for_versions_number_stops(self):
        lists = (["0\tCvCity_init", "1\tCvUnit_kill"], ["DllGetGameContext"])
        with tempfile.TemporaryDirectory() as folder:
            hooks, exports = os.path.join(folder, "hooks.txt"), os.path.join(folder, "exports.txt")
            release.write_list(hooks, "0.3.1", lists[0])
            release.write_list(exports, "0.3.1", lists[1])
            with (
                mock.patch.object(release, "HOOKS_LIST", hooks),
                mock.patch.object(release, "EXPORTS_LIST", exports),
                mock.patch.object(release, "current_lists", return_value=lists),
                mock.patch.object(release, "last_release", return_value="v0.3.0"),
                mock.patch.object(release, "at_tag", self.at_tag),
            ):
                release.require_build_as_prepared(version.Version("0.4.0", 2))
                with self.assertRaises(SystemExit) as stop:
                    release.require_build_as_prepared(version.Version("0.3.1", 2))
                self.assertIn("calls for release 0.4.0", str(stop.exception))

    def test_a_build_prepared_with_major_passes(self):
        lists = (["0\tCvCity_init"], ["DllGetGameContext"])
        with tempfile.TemporaryDirectory() as folder:
            hooks, exports = os.path.join(folder, "hooks.txt"), os.path.join(folder, "exports.txt")
            release.write_list(hooks, "1.0.0", lists[0])
            release.write_list(exports, "1.0.0", lists[1])
            with (
                mock.patch.object(release, "HOOKS_LIST", hooks),
                mock.patch.object(release, "EXPORTS_LIST", exports),
                mock.patch.object(release, "current_lists", return_value=lists),
                mock.patch.object(release, "last_release", return_value="v0.3.0"),
                mock.patch.object(release, "at_tag", self.at_tag),
            ):
                release.require_build_as_prepared(version.Version("1.0.0", 2))

    def test_a_build_that_needs_a_major_version_says_so(self):
        lists = (["0\tCvCity_init"], ["DllGetGameContext"])
        with tempfile.TemporaryDirectory() as folder:
            hooks, exports = os.path.join(folder, "hooks.txt"), os.path.join(folder, "exports.txt")
            release.write_list(hooks, "1.3.0", lists[0])
            release.write_list(exports, "1.3.0", lists[1])
            with (
                mock.patch.object(release, "HOOKS_LIST", hooks),
                mock.patch.object(release, "EXPORTS_LIST", exports),
                mock.patch.object(release, "current_lists", return_value=lists),
                mock.patch.object(
                    release, "choose", return_value=("v1.2.3", version.Version("1.2.3", 9), changes(removed=["x"]))
                ),
            ):
                with self.assertRaises(SystemExit) as stop:
                    release.require_build_as_prepared(version.Version("1.3.0", 10))
        self.assertIn("prepare the release again with --major", str(stop.exception))

    def test_a_release_tag_only_on_this_machine_stops(self):
        with (
            mock.patch.object(release.layouts, "last_release_tag", return_value="v0.4.0"),
            mock.patch.object(release, "on_github", return_value=False),
        ):
            with self.assertRaises(SystemExit) as stop:
                release.last_release()
        self.assertIn("only on this machine", str(stop.exception))
        self.assertIn("git tag -d v0.4.0", str(stop.exception))

    def test_a_reordered_api_header_since_the_tag_is_a_change(self):
        swapped = API_HEADER.replace("FIRST,\n\tCIV_HAND_SECOND,", "SECOND,\n\tCIV_HAND_FIRST,")
        self.assertNotEqual(swapped, API_HEADER)
        self.SAVED = dict(self.SAVED, **{"CivPluginApi.h": API_HEADER})
        with tempfile.TemporaryDirectory() as folder:
            header = os.path.join(folder, "CivPluginApi.h")
            with open(header, "w") as f:
                f.write(swapped)
            with mock.patch.object(release.layouts, "API_HEADER", header):
                _, _, diffs = self.choose("v0.3.0", (["0\tCvCity_init"], ["DllGetGameContext"]))
        (api,) = [d for d in diffs if d.what.endswith("CivPluginApi.h")]
        self.assertTrue(api.removed)


class PublishTest(unittest.TestCase):
    HEAD = "abc123"
    CURRENT = version.Version("0.4.0", 2)

    def publish(
        self,
        built_from=HEAD,
        files=None,
        notes="Notes.",
        gh="gh",
        tagged=None,
        gh_exit_codes=(0, 0),
        current=CURRENT,
        checked=HEAD,
        no_check=False,
    ):
        """What publish stops with, or None, and the git commands it ran, with HEAD at self.HEAD and VERSION at current.
        gh_exit_codes are what gh auth status and gh release create return; self.gh_commands holds the gh commands it
        ran. checked is the commit release.py check last passed, or None."""
        names = release.release_files(current.release) if files is None else files
        calls = []
        self.gh_commands = []

        def git(*args, check=True):
            calls.append(args[0])
            return self.HEAD

        def run(cmd, **kwargs):
            self.gh_commands.append(cmd)
            code = gh_exit_codes[len(self.gh_commands) - 1]
            return types.SimpleNamespace(returncode=code, stdout="https://github.com/releases/1", stderr="gh: refused")

        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, release.tag_of(current.release))
            os.makedirs(out)
            if built_from:
                with open(os.path.join(out, release.BUILT_FROM), "w") as f:
                    f.write(built_from + "\n")
            if checked:
                with open(os.path.join(out, release.CHECKED), "w") as f:
                    f.write(checked + "\n")
            for name in names:
                with open(os.path.join(out, name), "w") as f:
                    f.write("x")
            notes_path = os.path.join(folder, "notes.md")
            with open(notes_path, "w") as f:
                f.write(notes)
            with (
                mock.patch.object(release, "DIST", folder),
                mock.patch.object(release.version, "read", return_value=current),
                mock.patch.object(release, "require_main"),
                mock.patch.object(release, "git", git),
                mock.patch.object(release, "tagged_commit", return_value=tagged),
                mock.patch.object(release.shutil, "which", return_value=gh),
                mock.patch.object(release.subprocess, "run", run),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                try:
                    release.publish(notes_path, no_check)
                    return None, calls
                except SystemExit as stop:
                    return str(stop), calls

    def test_no_build_stops(self):
        self.assertIn("holds no release build", self.publish(built_from=None)[0])

    def test_files_that_have_not_passed_the_check_since_they_were_built_stop_before_tagging(self):
        for checked in (None, "def456"):
            message, calls = self.publish(checked=checked)
            self.assertIn("have not passed release.py check", message)
            self.assertNotIn("tag", calls)

    def test_no_check_publishes_a_release_that_only_changes_the_sdk_or_docs(self):
        message, calls = self.publish(checked=None, no_check=True)
        self.assertIsNone(message)
        self.assertIn("push", calls)

    def test_a_build_of_another_commit_stops(self):
        self.assertIn("not built from main as it is now", self.publish(built_from="def456")[0])

    def test_a_missing_release_file_stops(self):
        names = release.release_files(self.CURRENT.release)
        message, calls = self.publish(files=names[:3])
        self.assertIn("missing: ", message)
        self.assertIn(names.docs, message)
        self.assertNotIn("tag", calls)

    def test_empty_notes_stop(self):
        self.assertIn("missing or empty", self.publish(notes=" \n")[0])

    def test_no_gh_stops_before_tagging(self):
        message, calls = self.publish(gh=None)
        self.assertIn("gh, GitHub's command-line tool, was not found", message)
        self.assertNotIn("tag", calls)

    def test_gh_not_logged_in_stops_before_tagging(self):
        message, calls = self.publish(gh_exit_codes=(1,))
        self.assertIn("gh is not logged in", message)
        self.assertNotIn("tag", calls)

    def test_a_new_tag_is_made_and_pushed_and_a_draft_before_the_freeze_is_a_pre_release(self):
        message, calls = self.publish()
        self.assertIsNone(message)
        self.assertLess(calls.index("tag"), calls.index("push"))
        create = self.gh_commands[-1]
        self.assertEqual(create[1:4], ["release", "create", "v0.4.0"])
        self.assertIn("--draft", create)
        self.assertIn("--prerelease", create)

    def test_a_draft_from_the_freeze_on_is_not_a_pre_release(self):
        for current in (version.Version("0.5.0", 5), version.Version("1.0.0", 5)):
            message, _ = self.publish(current=current)
            self.assertIsNone(message)
            self.assertNotIn("--prerelease", self.gh_commands[-1])

    def test_a_failed_draft_says_to_delete_one_already_there(self):
        message, calls = self.publish(gh_exit_codes=(0, 1))
        self.assertIn("gh: refused", message)
        self.assertIn("delete it there first", message)
        self.assertIn("push", calls)

    def test_a_tag_left_on_the_built_commit_is_pushed_again(self):
        message, calls = self.publish(tagged=self.HEAD)
        self.assertIsNone(message)
        self.assertIn("push", calls)
        self.assertNotIn("tag", calls)

    def test_a_tag_on_another_commit_stops(self):
        message, calls = self.publish(tagged="def456")
        self.assertIn("git tag -d", message)
        self.assertNotIn("push", calls)


class HistoryTest(unittest.TestCase):
    def test_the_history_is_put_back_as_the_last_release_left_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "function-history.txt")
            with open(path, "w") as f:
                f.write("release\t0.4.0\nmarked since\n")
            with mock.patch.object(release, "at_tag", return_value="release\t0.3.0\n") as at_tag:
                release.restore_history("v0.3.0", path)
            at_tag.assert_called_once_with("v0.3.0", path)
            self.assertEqual(release.read_text(path), "release\t0.3.0\n")

    def test_before_the_first_release_the_history_starts_afresh(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "function-history.txt")
            with open(path, "w") as f:
                f.write("release\t0.3.0\n")
            release.restore_history(None, path)
            self.assertFalse(os.path.exists(path))
            release.restore_history(None, path)


class StepRecorder:
    """Stands in for the steps of a command: records each call's name and arguments, in order, and raises SystemExit
    from the step named failing."""

    def __init__(self, failing=None):
        self.calls = []
        self.failing = failing

    def step(self, name, result=None):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == self.failing:
                raise SystemExit("docs: broken")
            return result

        return record

    def names(self):
        return [name for name, _, _ in self.calls]

    def arguments(self, name):
        return [(args, kwargs) for called, args, kwargs in self.calls if called == name]

    def run(self, command, replaced):
        with contextlib.ExitStack() as stack:
            for owner, name, replacement in replaced:
                stack.enter_context(mock.patch.object(owner, name, replacement))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            try:
                command()
                return None
            except SystemExit as stop:
                return str(stop)


class PrepareTest(unittest.TestCase):
    LISTS = (["0\tCvCity_init"], ["DllGetGameContext"])

    def prepare(self, failing=None, planned=version.Version("0.4.0", 2)):
        steps = StepRecorder(failing)
        replaced = [
            (release, "require_main", steps.step("require_main")),
            (release, "require_no_release_branch", steps.step("branch check")),
            (release, "last_release", steps.step("last_release", "v0.3.0")),
            (release, "run", steps.step("run")),
            (release, "current_lists", steps.step("lists", self.LISTS)),
            (release, "plan", steps.step("plan", planned)),
            (release.version, "write", steps.step("VERSION")),
            (release.layouts, "set_api_version", steps.step("API version")),
            (release.version, "set_plugin_version", steps.step("plugin version")),
            (release.version, "set_template_bazaar", steps.step("template bazaar")),
            (release.version, "add_listed_version", steps.step("mod versions")),
            (release, "require_numbers_agree", steps.step("numbers agree")),
            (release, "restore_history", steps.step("restore history")),
            (release.build_docs, "build", steps.step("docs")),
            (release, "write_list", steps.step("write list")),
            (release, "git", steps.step("git")),
        ]
        return steps, steps.run(lambda: release.prepare(False), replaced)

    def test_the_checks_come_first_the_history_before_the_docs_and_the_branch_last(self):
        steps, message = self.prepare()
        self.assertIsNone(message)
        names = steps.names()
        self.assertEqual(names[: names.index("VERSION")].count("run"), 5)
        self.assertLess(names.index("plugin version"), names.index("numbers agree"))
        self.assertLess(names.index("template bazaar"), names.index("numbers agree"))
        self.assertLess(names.index("mod versions"), names.index("numbers agree"))
        self.assertLess(names.index("restore history"), names.index("docs"))
        self.assertEqual(steps.arguments("git"), [(("switch", "-c", "release-0.4.0"), {})])
        self.assertEqual(names[-1], "git")

    def test_each_step_gets_the_new_release(self):
        steps, _ = self.prepare()
        self.assertEqual(steps.arguments("VERSION"), [((version.Version("0.4.0", 2),), {})])
        self.assertEqual(steps.arguments("API version"), [((0, 4), {})])
        self.assertEqual(steps.arguments("plugin version"), [(("0.4.0",), {})])
        self.assertEqual(steps.arguments("template bazaar"), [(("0.4.0",), {})])
        self.assertEqual(steps.arguments("mod versions"), [((version.Version("0.4.0", 2),), {})])
        self.assertEqual(steps.arguments("restore history"), [(("v0.3.0",), {})])
        ((_, docs),) = steps.arguments("docs")
        self.assertEqual(docs, {"release": "0.4.0"})
        written = [args for args, _ in steps.arguments("write list")]
        expected = [(release.HOOKS_LIST, "0.4.0", self.LISTS[0]), (release.EXPORTS_LIST, "0.4.0", self.LISTS[1])]
        self.assertEqual(written, expected)

    def test_a_patch_release_leaves_the_plugin_template_at_the_first_release_of_its_api(self):
        steps, _ = self.prepare(planned=version.Version("0.4.1", 3))
        self.assertEqual(steps.arguments("template bazaar"), [(("0.4.0",), {})])

    def test_a_stop_part_way_says_how_to_start_again(self):
        steps, message = self.prepare(failing="docs")
        self.assertIn("docs: broken", message)
        self.assertIn("git restore :/", message)
        self.assertNotIn("git", steps.names())


class BuildTest(unittest.TestCase):
    CURRENT = version.Version("0.4.0", 2)
    HEAD = "abc123"

    def build(self, trial):
        """The steps build took, whether it wrote trial files, and the commit built-from.txt names."""
        steps = StepRecorder()
        names = release.release_files(self.CURRENT.release)

        def write_files(current, out, trial):
            steps.calls.append(("files", (current, out), {"trial": trial}))
            os.makedirs(out)
            return names

        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "out")
            replaced = [
                (release.version, "read", lambda: self.CURRENT),
                (release, "require_releasable", steps.step("releasable")),
                (release, "require_numbers_agree", steps.step("numbers agree")),
                (release, "run", steps.step("run")),
                (release, "require_build_as_prepared", steps.step("as prepared")),
                (release.build_sdk, "main", steps.step("SDK", 0)),
                (release, "write_release_files", write_files),
                (release, "require_unchanged_by_build", steps.step("unchanged")),
                (release, "git", steps.step("git", self.HEAD)),
                (release, "release_folder", lambda r: out),
                (release, "TRIAL_FOLDER", out),
            ]
            message = steps.run(lambda: release.build(trial), replaced)
            built_from = os.path.join(out, release.BUILT_FROM)
            head = release.read_text(built_from).strip() if os.path.exists(built_from) else None
        self.assertIsNone(message)
        ((_, marks),) = steps.arguments("files")
        return steps.names(), marks["trial"], head

    def test_a_release_build_checks_before_and_after_and_records_its_commit(self):
        names, trial, head = self.build(trial=False)
        expected = ["releasable", "numbers agree", "run", "as prepared", "SDK", "files", "unchanged", "git"]
        self.assertEqual(names, expected)
        self.assertFalse(trial)
        self.assertEqual(head, self.HEAD)

    def test_a_trial_build_skips_the_release_checks_and_records_no_commit(self):
        names, trial, head = self.build(trial=True)
        self.assertEqual(names, ["numbers agree", "run", "SDK", "files"])
        self.assertTrue(trial)
        self.assertIsNone(head)

    def test_a_release_not_prepared_or_already_out_stops(self):
        for saved, tagged, expected in (
            ("0.3.0", False, "were not saved at 0.4.0"),
            ("0.4.0", True, "already tagged"),
            ("0.4.0", False, None),
        ):
            with (
                self.subTest(saved=saved, tagged=tagged),
                mock.patch.object(release, "require_main"),
                mock.patch.object(release, "saved_release", return_value=saved),
                mock.patch.object(release, "on_github", return_value=tagged),
            ):
                if expected is None:
                    release.require_releasable(self.CURRENT)
                    continue
                with self.assertRaises(SystemExit) as stop:
                    release.require_releasable(self.CURRENT)
                self.assertIn(expected, str(stop.exception))


class WriteFilesTest(unittest.TestCase):
    def write(self, trial):
        """The four files written for 0.4.0, with the docs, SDK and mods made small; returns what they hold and what the
        docs build and the mods were given."""
        given = {}

        def docs_build(project, out, release=None):
            given["release"] = release
            os.makedirs(out)
            for name in ("index.html", "LICENSE.txt", "NOTICE.txt"):
                with open(os.path.join(out, name), "w") as f:
                    f.write("x")

        def write_dll_mod(mods_folder, name, mod_id, teaser, dll, host_screens=False, version=1, description=None):
            given["mod"] = (name, mod_id, teaser, dll, host_screens, version)
            given["description"] = description
            folders = os.path.join(mods_folder, "host"), os.path.join(mods_folder, "bootstrap")
            for path in folders:
                os.makedirs(path)
            return folders

        def pack(folder, package):
            with open(package, "w") as f:
                f.write(os.path.basename(folder))

        with tempfile.TemporaryDirectory() as folder:
            sdk = os.path.join(folder, "Bazaar SDK")
            os.makedirs(sdk)
            for name in ("LICENSE", "NOTICE", "README.md"):
                with open(os.path.join(sdk, name), "w") as f:
                    f.write("x")
            out = os.path.join(folder, "out")
            with (
                mock.patch.object(release, "STAGE", os.path.join(folder, "stage")),
                mock.patch.object(release.build_docs, "build", docs_build),
                mock.patch.object(release.mods, "write_dll_mod", write_dll_mod),
                mock.patch.object(release.mods, "pack", pack),
                mock.patch.object(release.build_sdk, "SDK", sdk),
            ):
                names = release.write_release_files(version.Version("0.4.0", 2), out, trial)
            held = {"files": sorted(os.listdir(out))}
            for kind in ("host", "bootstrap"):
                held[kind] = release.read_text(os.path.join(out, getattr(names, kind)))
            for kind in ("sdk", "docs"):
                with zipfile.ZipFile(os.path.join(out, getattr(names, kind))) as z:
                    held[kind] = sorted(z.namelist())
        return names, held, given

    def test_the_four_files_hold_what_a_release_ships(self):
        names, held, given = self.write(trial=False)
        self.assertEqual(held["files"], sorted(names))
        self.assertEqual((held["host"], held["bootstrap"]), ("host", "bootstrap"))
        self.assertEqual(held["docs"], ["LICENSE.txt", "NOTICE.txt", "index.html"])
        self.assertEqual(held["sdk"], ["Bazaar SDK/LICENSE", "Bazaar SDK/NOTICE", "Bazaar SDK/README.md"])
        self.assertEqual(given["release"], "0.4.0")
        expected_mod = (release.mods.HOST_NAME, release.mods.HOST_ID, release.mods.HOST_TEASER, release.common.HOST_DLL)
        self.assertEqual(given["mod"], expected_mod + (True, 2))
        self.assertEqual(given["description"], release.mods.host_description("0.4.0"))

    def test_a_trial_leaves_the_release_out_of_the_docs_and_the_mod_and_gives_it_the_test_version(self):
        _, _, given = self.write(trial=True)
        self.assertIsNone(given["release"])
        self.assertIsNone(given["description"])
        self.assertEqual(given["mod"][-1], release.files.TEST_VERSION)


class FileTest(unittest.TestCase):
    def test_the_release_files_are_named_for_the_release(self):
        names = release.release_files("0.4.0")
        self.assertEqual(names.host, "Bazaar-0.4.0.civ5mod")
        self.assertRegex(names.bootstrap, r"^Bazaar-VMC-Bootstrap-\d+\.civ5mod$")
        self.assertEqual((names.sdk, names.docs), ("Bazaar-SDK-0.4.0.zip", "Bazaar-docs-0.4.0.zip"))

    def test_the_docs_action_downloads_the_docs_zip_this_script_writes(self):
        workflow = release.read_text(os.path.join(release.common.REPO, ".github", "workflows", "docs.yml"))
        (pattern,) = re.findall(r'--pattern "([^"]+)"', workflow)
        tag = release.tag_of("0.4.0")
        self.assertTrue(tag.startswith("v"))
        self.assertEqual(pattern.replace("${TAG#v}", tag[1:]), release.release_files("0.4.0").docs)

    def test_a_zip_holds_the_folder_under_its_top(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "Bazaar SDK")
            os.makedirs(os.path.join(source, "include"))
            for rel in ("README.md", "LICENSE", os.path.join("include", "CivPluginApi.h")):
                with open(os.path.join(source, rel), "w") as f:
                    f.write("x")
            path = os.path.join(folder, "sdk.zip")
            release.write_zip(path, source, top="Bazaar SDK")
            with zipfile.ZipFile(path) as z:
                self.assertEqual(
                    z.namelist(),
                    ["Bazaar SDK/LICENSE", "Bazaar SDK/README.md", "Bazaar SDK/include/CivPluginApi.h"],
                )


class ReleaseChecksTest(unittest.TestCase):
    CURRENT = version.Version("0.6.0", 6)
    LOADED = "Plugin Template Plugin 1 loaded (built for API 0.6)."
    TURN = "[Template Plugin] Rome starts turn 1 with 0 gold (turns started: 1, notifications seen: 0)"

    def checks(self, trial):
        return release.release_checks(self.CURRENT, ["host.civ5mod", "vmc.civ5mod"], "Template Plugin", trial)

    def test_a_release_names_itself_loads_the_template_and_logs_its_first_turn(self):
        checks = self.checks(trial=False)
        self.assertEqual(checks.mods, ["host.civ5mod", "vmc.civ5mod", "Template Plugin"])
        self.assertEqual(list(checks.plugin_order), [])
        release.runner.validate(checks)
        kinds = [release.runner.kind_of(step) for step in checks.steps]
        self.assertEqual(kinds, ["description_of", "log", "start_game", "end_turns", "log"])
        description = checks.steps[0]
        self.assertEqual((description["description_of"], description["version"]), (release.mods.HOST_ID, 6))
        self.assertEqual(description["is"], release.mods.host_description("0.6.0"))
        self.assertEqual(checks.steps[3]["end_turns"], 1)
        self.assertEqual(
            [step.get("what") for step in checks.steps if "what" in step],
            [
                "Bazaar's description in the Mods menu names 0.6.0",
                "Bazaar.log says the template plugin loaded, built for API 0.6",
                "the template plugin logged the start of turn 1",
            ],
        )

    def test_the_log_checks_find_the_template_built_for_this_api_and_its_first_turn_only(self):
        loaded, turn = (step["has"] for step in self.checks(trial=False).steps if "log" in step)
        self.assertRegex(self.LOADED, loaded)
        self.assertNotRegex(self.LOADED.replace("0.6", "0.5"), loaded)
        self.assertRegex(self.TURN, turn)
        self.assertNotRegex(self.TURN.replace("turn 1 ", "turn 7 "), turn)

    def test_a_trial_build_is_not_asked_to_name_its_release(self):
        steps = self.checks(trial=True).steps
        self.assertNotIn("description_of", [key for step in steps for key in step])
        self.assertEqual(len(steps), 4)


class CheckTest(unittest.TestCase):
    """check() itself, with the game, the template's build and the runner replaced."""

    CURRENT = version.Version("0.6.0", 6)

    def run_check(self, failed=None, trial=False, built_from=True, files=3, preflight=None):
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "v0.6.0")
            os.makedirs(out)
            for name in release.release_files(self.CURRENT.release)[:files]:
                with open(os.path.join(out, name), "w") as f:
                    f.write("x")
            if built_from:
                with open(os.path.join(out, release.BUILT_FROM), "w") as f:
                    f.write("abc123\n")
            g = mock.create_autospec(release.game.Game, instance=True)
            g.preflight.side_effect = preflight
            template = os.path.join(folder, "Template Plugin")
            with (
                mock.patch.object(release.version, "read", return_value=self.CURRENT),
                mock.patch.object(release, "release_folder", return_value=out),
                mock.patch.object(release, "TRIAL_FOLDER", out),
                mock.patch.object(release.game, "Game", return_value=g) as Game,
                mock.patch.object(release, "build_template", return_value=template) as build,
                mock.patch.object(release.runner, "run", autospec=True, return_value=failed) as run,
            ):
                try:
                    release.check(trial)
                    stopped = None
                except SystemExit as e:
                    stopped = str(e)
            checked = os.path.join(out, release.CHECKED)
            mark = release.read_text(checked) if os.path.exists(checked) else None
            self.reached = [name for name, step in (("game", Game), ("template", build), ("run", run)) if step.called]
            if run.called:
                packages = [os.path.join(out, name) for name in release.release_files(self.CURRENT.release)[:2]]
                expected = release.release_checks(self.CURRENT, packages, template, trial)
                self.assertEqual(run.call_args, mock.call(expected, g))
            return stopped, mark

    def test_missing_release_files_or_build_mark_stop_before_the_game_is_touched(self):
        for kwargs, why in (
            ({"files": 2}, "run release.py build first"),
            ({"built_from": False}, "holds no release build"),
        ):
            with self.subTest(**kwargs):
                stopped, _ = self.run_check(**kwargs)
                self.assertIn(why, stopped)
                self.assertEqual(self.reached, [])

    def test_a_game_that_cannot_be_checked_stops_before_the_template_is_built(self):
        stopped, mark = self.run_check(preflight=release.game.CheckError("Civilization V is already running"))
        self.assertEqual(stopped, "release: the in-game check could not start: Civilization V is already running")
        self.assertEqual(self.reached, ["game"])
        self.assertIsNone(mark)

    def test_a_failed_check_says_why_and_marks_nothing(self):
        stopped, mark = self.run_check(failed="failed.\nThe end of Bazaar.log:\nx")
        self.assertEqual(stopped, "release: the in-game check failed.\nThe end of Bazaar.log:\nx")
        self.assertIsNone(mark)

    def test_a_passed_check_marks_the_build_it_checked_and_a_trial_marks_nothing(self):
        self.assertEqual(self.run_check(), (None, "abc123\n"))
        self.assertEqual(self.run_check(trial=True, built_from=False), (None, None))


class SourceContractTest(unittest.TestCase):
    """The check reads lines Bazaar and the template plugin write, and a file Bazaar keeps: these tie it to them."""

    def source(self, *parts):
        return release.read_text(os.path.join(release.common.REPO, *parts), encoding="latin-1")

    def test_the_loaded_line_is_the_one_bazaar_writes(self):
        (fmt,) = re.findall(
            r'Log\("(Plugin %s %s loaded \(built for API %d\.%d\)\.)"', self.source("host", "CivHostRuntime.cpp")
        )
        self.assertRegex(fmt % ("Template Plugin", "1", 0, 6), release.TEMPLATE_LOADED % (0, 6))

    def test_the_turn_line_is_the_one_the_template_writes_through_bazaar(self):
        plugin_line = re.search(r'Log\("\[%s\] %s"', self.source("host", "CivHostRuntime.cpp"))
        template = self.source("sdk", "plugin-template", "src", "TemplatePlugin.cpp")
        (fmt,) = re.findall(r'Log\("(%s starts turn %d [^"]*)"', template)
        self.assertIsNotNone(plugin_line)
        self.assertIn('plugin->name = "Template Plugin";', template)
        self.assertRegex("[Template Plugin] " + fmt % ("Rome", 4, 0, 1, 0), release.TEMPLATE_TURN % 4)

    def test_the_plugin_order_file_is_the_one_bazaar_reads(self):
        self.assertIn(
            '"\\\\%s"' % release.files.ORDER_FILE.replace("\\", "\\\\"), self.source("host", "CivHostEngine.cpp")
        )


if __name__ == "__main__":
    unittest.main()
