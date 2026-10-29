"""Checks of the Steam Workshop upload that need neither Steam nor a build: choosing the item and the change note, the
checks before and after an upload, and the checks release.py workshop makes first.

python -m unittest discover -s tests/release
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "workshop"))

import release  # noqa: E402
import upload  # noqa: E402
import version  # noqa: E402

CHANGES = """[b]0.5.1[/b]
Fixes one problem.

For players:
[list]
[*]A fix.
[/list]

[b]0.5.0[/b]
The first public release. It names [b]bold[/b] text.

[b]0.4.0[/b]
Older.
"""
NOTE_0_5_1 = "[b]0.5.1[/b]\nFixes one problem.\n\nFor players:\n[list]\n[*]A fix.\n[/list]"


class ChangeNoteTest(unittest.TestCase):
    def test_the_newest_release_gets_only_its_own_section(self):
        self.assertEqual(upload.change_note(CHANGES, "0.5.1"), NOTE_0_5_1)

    def test_an_older_release_ends_at_the_next_heading_not_at_bold_text(self):
        note = upload.change_note(CHANGES, "0.5.0")
        self.assertEqual(note, "[b]0.5.0[/b]\nThe first public release. It names [b]bold[/b] text.")

    def test_the_last_section_runs_to_the_end(self):
        self.assertEqual(upload.change_note(CHANGES, "0.4.0"), "[b]0.4.0[/b]\nOlder.")

    def test_a_release_without_a_section_stops(self):
        with self.assertRaises(SystemExit) as stopped:
            upload.change_note(CHANGES, "0.5.2")
        self.assertIn("no [b]0.5.2[/b] section", str(stopped.exception))


class TextLimitTest(unittest.TestCase):
    def test_a_text_at_steam_s_limit_fits(self):
        upload.require_fits("bazaar.txt", "x" * 7999)

    def test_the_limit_counts_bytes_not_characters(self):
        with self.assertRaises(SystemExit) as stopped:
            upload.require_fits("bazaar.txt", "é" * 4000)
        self.assertIn("bazaar.txt is 8000 bytes, more than the 7999 Steam allows", str(stopped.exception))


class UploadTest(unittest.TestCase):
    BEFORE = {"result": 1, "consumer_app_id": upload.GAME_APP, "file_size": "10", "time_updated": 100}
    AFTER = {"result": 1, "consumer_app_id": upload.GAME_APP, "file_size": "3", "time_updated": 200}

    def upload(
        self,
        answers=(BEFORE, AFTER),
        release="0.5.1",
        changes=CHANGES,
        description="The description.",
        build_code=0,
        uploader_code=0,
    ):
        """What upload stops with, or None. Steam's Web API gives the answers in turn, then the last one again, and
        raises an answer that is an exception. self.builds counts the builds, self.uploads holds the uploader's command
        lines, self.folders the folders it ran in and self.texts what its change note and description files held."""
        answers = list(answers)
        self.checks = 0
        self.builds = 0
        self.uploads = []
        self.folders = []
        self.texts = []

        def details(item):
            self.checks += 1
            answer = answers.pop(0) if len(answers) > 1 else answers[0]
            if isinstance(answer, Exception):
                raise answer
            return answer

        def run(cmd, **kwargs):
            if cmd[0] == "cl":
                self.builds += 1
                return types.SimpleNamespace(returncode=build_code, stdout="upload.cpp(1) : error C2143")
            self.uploads.append(cmd)
            self.folders.append(kwargs.get("cwd"))
            for path in cmd[4:]:
                with open(path, encoding="utf-8") as f:
                    self.texts.append(f.read())
            return types.SimpleNamespace(returncode=uploader_code)

        with tempfile.TemporaryDirectory() as folder:
            self.out = folder
            package = os.path.join(folder, "Bazaar-%s.civ5mod" % release)
            with open(package, "wb") as f:
                f.write(b"abc")
            changes_file = os.path.join(folder, "changes.txt")
            with open(changes_file, "w", encoding="utf-8") as f:
                f.write(changes)
            description_file = os.path.join(folder, "bazaar.txt")
            with open(description_file, "w", encoding="utf-8") as f:
                f.write(description)
            with (
                mock.patch.object(upload, "OUT", folder),
                mock.patch.object(upload, "CHANGES", changes_file),
                mock.patch.object(upload, "DESCRIPTION", description_file),
                mock.patch.object(upload, "steam_api", return_value="steam_api.dll"),
                mock.patch.object(upload, "details", details),
                mock.patch.object(upload.common, "vs_env", return_value={}),
                mock.patch.object(upload.shutil, "which", return_value="cl"),
                mock.patch.object(upload.subprocess, "run", run),
                mock.patch.object(upload.time, "sleep"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                try:
                    upload.upload(release, package)
                    return None
                except SystemExit as stop:
                    return str(stop)

    def test_the_uploader_gets_the_item_the_package_the_note_and_the_description(self):
        self.assertIsNone(self.upload())
        self.assertEqual(len(self.uploads), 1)
        self.assertEqual(self.uploads[0][1:3], ["steam_api.dll", "3825428828"])
        self.assertTrue(self.uploads[0][3].endswith("Bazaar-0.5.1.civ5mod"))
        self.assertEqual(self.texts, [NOTE_0_5_1, "The description."])
        self.assertEqual(self.folders, [self.out])

    def test_a_major_version_without_an_item_stops_before_building(self):
        self.assertIn("Bazaar 1.x has no Workshop item yet", self.upload(release="1.0.0", changes="[b]1.0.0[/b]\n"))
        self.assertEqual((self.checks, self.builds), (0, 0))

    def test_a_description_over_steam_s_limit_stops_before_building(self):
        message = self.upload(description="x" * 8000)
        self.assertIn("bazaar.txt is 8000 bytes", message)
        self.assertEqual((self.checks, self.builds), (0, 0))

    def test_a_change_note_over_steam_s_limit_stops_before_building(self):
        message = self.upload(changes="[b]0.5.1[/b]\n" + "x" * 8000)
        self.assertIn("the 0.5.1 section of", message)
        self.assertEqual((self.checks, self.builds), (0, 0))

    def test_an_item_that_is_hidden_or_gone_stops_before_building(self):
        message = self.upload(answers=(dict(self.BEFORE, result=9),))
        self.assertIn("is not a public Civilization V item", message)
        self.assertEqual(self.builds, 0)

    def test_an_item_of_another_game_stops_before_building(self):
        message = self.upload(answers=(dict(self.BEFORE, consumer_app_id=289070),))
        self.assertIn("is not a public Civilization V item", message)
        self.assertEqual(self.builds, 0)

    def test_no_answer_from_steam_before_the_upload_stops(self):
        message = self.upload(answers=(OSError("timed out"),))
        self.assertIn("did not answer about item 3825428828: timed out", message)
        self.assertEqual(self.builds, 0)

    def test_a_failed_build_stops_with_the_compiler_s_errors(self):
        message = self.upload(build_code=2)
        self.assertIn("upload.cpp did not build:\nupload.cpp(1) : error C2143", message)
        self.assertEqual(self.uploads, [])

    def test_a_failed_upload_stops(self):
        self.assertIn("the uploader stopped", self.upload(uploader_code=1))

    def test_a_new_file_that_shows_late_is_waited_for(self):
        self.assertIsNone(self.upload(answers=(self.BEFORE, self.BEFORE, self.BEFORE, self.AFTER)))
        self.assertEqual(self.checks, 4)

    def test_no_answer_after_the_upload_counts_as_not_yet(self):
        self.assertIsNone(self.upload(answers=(self.BEFORE, OSError("timed out"), ValueError("not JSON"), self.AFTER)))

    def test_an_item_still_showing_the_old_file_stops(self):
        self.assertIn("does not show the new file", self.upload(answers=(self.BEFORE,)))

    def test_an_item_updated_with_a_file_of_another_size_stops(self):
        message = self.upload(answers=(self.BEFORE, dict(self.BEFORE, time_updated=200)))
        self.assertIn("does not show the new file", message)

    def test_an_item_with_the_same_size_but_not_updated_stops(self):
        message = self.upload(answers=(self.BEFORE, dict(self.BEFORE, file_size="3")))
        self.assertIn("does not show the new file", message)


class WorkshopTest(unittest.TestCase):
    TAGGED = "abc123"
    CURRENT = version.Version("0.5.1", 5)

    def workshop(self, built_from=TAGGED, tagged=TAGGED, on_github=True, package=True, gh="gh", draft=False, view=0):
        """What release.py workshop stops with, or None; self.sent holds what it handed to upload.upload and self.views
        the folders gh release view ran in."""
        self.sent = []
        self.views = []

        def run(cmd, **kwargs):
            if cmd[1:3] == ["release", "view"]:
                self.views.append(kwargs.get("cwd"))
                stdout = json.dumps({"isDraft": draft})
                return types.SimpleNamespace(returncode=view, stdout=stdout, stderr="HTTP 502: Bad Gateway")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, release.tag_of(self.CURRENT.release))
            os.makedirs(out)
            if built_from:
                with open(os.path.join(out, release.BUILT_FROM), "w") as f:
                    f.write(built_from + "\n")
            if package:
                open(os.path.join(out, "Bazaar-0.5.1.civ5mod"), "wb").close()
            with (
                mock.patch.object(release, "DIST", folder),
                mock.patch.object(release.version, "read", return_value=self.CURRENT),
                mock.patch.object(release, "require_main") as self.require_main,
                mock.patch.object(release, "tagged_commit", return_value=tagged),
                mock.patch.object(release, "on_github", return_value=on_github),
                mock.patch.object(release.shutil, "which", return_value=gh),
                mock.patch.object(release.subprocess, "run", run),
                mock.patch.object(release.upload, "upload", lambda *args: self.sent.append(args)),
            ):
                try:
                    release.workshop()
                    return None
                except SystemExit as stop:
                    return str(stop)

    def test_a_published_release_sends_its_package(self):
        self.assertIsNone(self.workshop())
        self.require_main.assert_called_once_with()
        ((sent_release, package),) = self.sent
        self.assertEqual(sent_release, "0.5.1")
        self.assertEqual(os.path.basename(package), "Bazaar-0.5.1.civ5mod")
        self.assertEqual(self.views, [release.common.REPO])

    def test_a_release_not_tagged_on_github_stops(self):
        for tagged, on_github in ((None, False), (self.TAGGED, False)):
            self.assertIn("publish the release first", self.workshop(tagged=tagged, on_github=on_github))
        self.assertEqual(self.sent, [])

    def test_files_built_from_another_commit_stop(self):
        for built_from in (None, "def456"):
            self.assertIn("does not hold the files tagged v0.5.1", self.workshop(built_from=built_from))
        self.assertEqual(self.sent, [])

    def test_a_missing_package_stops(self):
        self.assertIn("Bazaar-0.5.1.civ5mod is missing", self.workshop(package=False))
        self.assertEqual(self.sent, [])

    def test_without_gh_it_stops(self):
        self.assertIn("gh, GitHub's command-line tool, was not found", self.workshop(gh=None))
        self.assertEqual(self.sent, [])

    def test_a_release_still_a_draft_stops(self):
        self.assertIn("v0.5.1 is still a draft: publish it there first", self.workshop(draft=True))
        self.assertEqual(self.sent, [])

    def test_a_release_that_keeps_bazaar_has_nothing_to_upload(self):
        with mock.patch.object(release, "kept_release", return_value="0.5.0"):
            self.assertIn("keeps the Bazaar of 0.5.0, so it has nothing new for the Workshop", self.workshop())
        self.assertEqual(self.sent, [])

    def test_gh_failing_stops_with_its_error(self):
        self.assertIn("could not show the GitHub release v0.5.1: HTTP 502: Bad Gateway", self.workshop(view=1))
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
