"""release.ps1, the release script in the plugin template and the Lua mod template, run on copies of the templates with
fake_build.py standing in for build.cmd."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PLUGIN_TEMPLATE = os.path.join(REPO, "sdk", "plugin-template")
LUA_TEMPLATE = os.path.join(REPO, "claude-plugin", "skills", "new-lua-mod", "template")
NEW_LUA_MOD = os.path.join(REPO, "claude-plugin", "skills", "new-lua-mod", "scripts", "new-lua-mod.ps1")
SCRIPT_FILES = ("release.ps1", "release.cmd")
TEMPLATE_NAMES = ("TemplatePlugin", "Template Plugin", "TemplateLuaMod", "Template Lua Mod")
NAME = "Score Doubler"
PACKAGE = NAME + " (v %d).civ5mod"
VERSION = "release 1\nbazaar 0.4.0\n"
WORKSHOP = "[h1]%s[/h1]\nDoubles every player's score.\n\nRequires Bazaar 0.4.0 or newer.\n" % NAME
BOM = "\xef\xbb\xbf"


def read(path):
    with open(path, encoding="latin-1") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="latin-1", newline="") as f:
        f.write(text)


def civ5proj(folder):
    (name,) = [n for n in os.listdir(os.path.join(folder, "mod")) if n.endswith(".civ5proj")]
    return os.path.join(folder, "mod", name)


def project_value(folder, element):
    return re.search(r"<%s>([^<]*)</%s>" % (element, element), read(civ5proj(folder))).group(1)


def set_project_value(folder, element, value):
    path = civ5proj(folder)
    pattern = r"<%s>[^<]*</%s>" % (element, element)
    write(path, re.sub(pattern, lambda _: "<%s>%s</%s>" % (element, value, element), read(path), 1))


def snapshot(folder, *parts):
    files = {}
    for part in parts:
        path = os.path.join(folder, part)
        paths = [path] if os.path.isfile(path) else [os.path.join(d, n) for d, _, ns in os.walk(path) for n in ns]
        for each in paths:
            with open(each, "rb") as f:
                files[each] = f.read()
    return files


class ReleaseScriptTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.sdk = os.path.join(self.root, "SDK")
        self.set_sdk_api(0, 4)
        write(os.path.join(self.sdk, "CivPlugin.vsprops"), "")
        self.temp = os.path.join(self.root, "temp")
        os.makedirs(self.temp)
        self.env = dict((k, v) for k, v in os.environ.items() if not k.startswith("FAKE_"))
        # release.cmd exists to get past this, so the tests run under it.
        self.env.update(BAZAAR_SDK=self.sdk, TEMP=self.temp, TMP=self.temp, PSExecutionPolicyPreference="Restricted")

    def set_sdk_api(self, major, minor):
        os.makedirs(os.path.join(self.sdk, "include"), exist_ok=True)
        write(
            os.path.join(self.sdk, "include", "CivPluginApi.h"),
            "#define CIV_HOST_API_MAJOR %d\n#define CIV_HOST_API_MINOR %d\n" % (major, minor),
        )

    def project(self, template=PLUGIN_TEMPLATE):
        """In a folder with a space in its name, so the script's quoting is tested."""
        folder = os.path.join(self.root, NAME)
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(template, folder, ignore=shutil.ignore_patterns("out", "Build", "Packages", "Releases"))
        set_project_value(folder, "Guid", str(uuid.uuid4()))
        set_project_value(folder, "Name", NAME)
        set_project_value(folder, "Authors", "Jane Doe")
        write(os.path.join(folder, "VERSION"), VERSION)
        write(os.path.join(folder, "workshop-description.txt"), WORKSHOP)
        self.use_fake_build(folder)
        return folder

    def use_fake_build(self, folder):
        write(
            os.path.join(folder, "build.cmd"),
            '@"%s" "%s" "%%~dp0."\r\n' % (sys.executable, os.path.join(HERE, "fake_build.py")),
        )

    def release(self, folder, **fake):
        done = subprocess.run(
            ["cmd", "/c", os.path.join(folder, "release.cmd")],
            env=dict(self.env, **fake),
            capture_output=True,
            text=True,
        )
        self.assertEqual([n for n in os.listdir(self.temp) if n.startswith("release-")], [], "unpacked package left")
        return done

    def assert_released(self, done, folder, release, mod):
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(os.path.isfile(os.path.join(folder, "Releases", release, PACKAGE % mod)), done.stdout)
        self.assertEqual(project_value(folder, "ModVersion"), str(mod))

    def assert_refused_after_build(self, folder, *words, **fake):
        released = snapshot(folder, "Releases")
        done = self.release(folder, **fake)
        self.assertEqual(done.returncode, 1, done.stdout)
        for word in words:
            self.assertIn(word, done.stderr)
        self.assertEqual(snapshot(folder, "Releases"), released, "a refused release added to Releases")
        return done

    def assert_refused_before_build(self, folder, *words, **fake):
        before = snapshot(folder, "VERSION", "mod", "src", "Packages")
        self.assert_refused_after_build(folder, *words, **fake)
        self.assertEqual(
            snapshot(folder, "VERSION", "mod", "src", "Packages"), before, "a refused release changed files"
        )

    def set_version(self, folder, text):
        write(os.path.join(folder, "VERSION"), text)

    def version(self, folder):
        return read(os.path.join(folder, "VERSION"))

    def plugin_version(self, folder):
        return re.search(r'PLUGIN_VERSION "([^"]*)"', read(os.path.join(folder, "src", "PluginVersion.h"))).group(1)

    def set_sql(self, folder, text):
        write(os.path.join(folder, "mod", "TemplatePlugin.sql"), text)

    def test_a_first_release_keeps_the_package_and_sets_the_version_everywhere(self):
        folder = self.project()
        done = self.release(folder)
        self.assert_released(done, folder, "1", 1)
        self.assertEqual(self.plugin_version(folder), "1")
        self.assertIn("taken as the first, with mod version 1", done.stdout)
        self.assertIn("released %s 1, mod version 1, for Bazaar 0.4.0 or newer" % NAME, done.stdout)
        self.assertNotIn("warning", done.stdout)

    def test_the_next_whole_number_is_the_next_mod_version(self):
        folder = self.project()
        self.release(folder)
        self.set_version(folder, "release 2\nbazaar 0.4.0\n")
        done = self.release(folder)
        self.assert_released(done, folder, "2", 2)
        self.assertEqual(self.plugin_version(folder), "2")
        self.assertNotIn("taken as the first", done.stdout)

    def test_a_release_without_a_section_in_the_change_notes_is_released_with_a_warning(self):
        folder = self.project()
        self.set_version(folder, "release 2\nbazaar 0.4.0\n")
        done = self.release(folder)
        self.assert_released(done, folder, "2", 2)
        self.assertIn("warning: CHANGES.txt has no section for 2", done.stdout)

    def test_the_change_notes_section_must_name_the_release_exactly(self):
        for heading, warned in (("[b]1.0.0[/b]", False), ("[h2]v1.0.0[/h2]", False), ("[b]1x0x0[/b]", True)):
            with self.subTest(heading=heading):
                folder = self.project()
                self.set_version(folder, "release 1.0.0\nbazaar 0.4.0\n")
                write(os.path.join(folder, "CHANGES.txt"), heading + "\nThe first release.\n")
                done = self.release(folder)
                self.assert_released(done, folder, "1.0.0", 1)
                self.assertEqual("CHANGES.txt has no section" in done.stdout, warned)
                shutil.rmtree(folder)

    def test_a_released_number_is_refused(self):
        folder = self.project()
        self.release(folder)
        self.assert_refused_before_build(folder, "1 is already released")

    def test_an_empty_release_folder_is_not_a_release(self):
        folder = self.project()
        os.makedirs(os.path.join(folder, "Releases", "1"))
        self.assert_released(self.release(folder), folder, "1", 1)

    def test_a_whole_number_not_above_every_released_mod_version_is_refused(self):
        for release in ("3", "5"):
            with self.subTest(release=release):
                folder = self.project()
                os.makedirs(os.path.join(folder, "Releases", "1.4.0"))
                write(os.path.join(folder, "Releases", "1.4.0", PACKAGE % 5), "")
                self.set_version(folder, "release %s\nbazaar 0.4.0\n" % release)
                self.assert_refused_before_build(folder, "Raise the release in VERSION above 5")
                shutil.rmtree(folder)

    def test_a_whole_number_below_the_projects_mod_version_is_refused(self):
        folder = self.project()
        set_project_value(folder, "ModVersion", "7")
        self.assert_refused_before_build(folder, "mod version is 7", "release 1 would go below it")

    def test_three_numbers_take_the_mod_version_one_above_the_last_release(self):
        folder = self.project()
        self.set_version(folder, "release 1.0.0\nbazaar 0.4.0\n")
        self.assert_released(self.release(folder), folder, "1.0.0", 1)
        self.assertEqual(self.version(folder), "release 1.0.0\nmod 1\nbazaar 0.4.0\n")
        self.set_version(folder, "release 1.1.0\nmod 1\nbazaar 0.4.0\n")
        self.assert_released(self.release(folder), folder, "1.1.0", 2)
        self.assertEqual(self.version(folder), "release 1.1.0\nmod 2\nbazaar 0.4.0\n")
        self.assertEqual(self.plugin_version(folder), "1.1.0")

    def test_three_numbers_never_take_a_mod_version_below_the_mod_line_or_the_project(self):
        folder = self.project()
        self.set_version(folder, "release 1.0.0\nbazaar 0.4.0\n")
        self.release(folder)
        self.set_version(folder, "release 1.1.0\nmod 9\nbazaar 0.4.0\n")
        self.assert_released(self.release(folder), folder, "1.1.0", 9)
        shutil.rmtree(folder)
        folder = self.project()
        set_project_value(folder, "ModVersion", "3")
        self.set_version(folder, "release 1.0.0\nbazaar 0.4.0\n")
        self.assert_released(self.release(folder), folder, "1.0.0", 3)

    def test_a_first_release_with_three_numbers_keeps_a_mod_line_it_is_given(self):
        folder = self.project()
        self.set_version(folder, "release 2.0.0\nmod 4\nbazaar 0.4.0\n")
        self.assert_released(self.release(folder), folder, "2.0.0", 4)

    def test_a_semantic_version_with_a_label_is_released(self):
        folder = self.project()
        self.set_version(folder, "release 1.0.0-beta.1\nbazaar 0.4.0\n")
        self.assert_released(self.release(folder), folder, "1.0.0-beta.1", 1)
        self.assertEqual(self.plugin_version(folder), "1.0.0-beta.1")

    def test_a_version_file_the_script_cannot_read_is_refused(self):
        for text, words in (
            ("release x\nbazaar 0.4.0\n", ["neither a whole number"]),
            ("release 1.2\nbazaar 0.4.0\n", ["neither a whole number"]),
            ("release 01.2.0\nbazaar 0.4.0\n", ["neither a whole number"]),
            ("release 1\n", ["no 'bazaar' line"]),
            ("bazaar 0.4.0\n", ["no 'release' line"]),
            ("release 1\nrelease 2\nbazaar 0.4.0\n", ["two 'release' lines"]),
            ("release 1\nbazaar 4\n", ["not a Bazaar release number"]),
            ("release 1\nmod 1\nbazaar 0.4.0\n", ["Remove the 'mod' line"]),
            ("release 1.0.0\nmod 0\nbazaar 0.4.0\n", ["not a whole number above 0"]),
            ("version 1\n", ["is not 'release', 'mod' or 'bazaar'"]),
            ("release 1.0.0-beta.\nbazaar 0.4.0\n", ["neither a whole number"]),
        ):
            with self.subTest(text=text):
                folder = self.project()
                self.set_version(folder, text)
                self.assert_refused_before_build(folder, *words)
                shutil.rmtree(folder)

    def test_a_byte_order_mark_is_ignored(self):
        folder = self.project()
        for name in ("VERSION", "CHANGES.txt"):
            path = os.path.join(folder, name)
            write(path, BOM + read(path))
        done = self.release(folder)
        self.assert_released(done, folder, "1", 1)
        self.assertNotIn("warning", done.stdout)
        self.assertEqual(self.version(folder), VERSION)

    def test_a_version_file_saved_as_utf16_is_refused(self):
        folder = self.project()
        with open(os.path.join(folder, "VERSION"), "w", encoding="utf-16") as f:
            f.write(VERSION)
        self.assert_refused_before_build(folder, "VERSION is saved as UTF-16")

    def test_a_mod_version_in_the_project_that_is_not_a_whole_number_is_refused(self):
        for value in ("", "0", "abc"):
            with self.subTest(value=value):
                folder = self.project()
                set_project_value(folder, "ModVersion", value)
                self.assert_refused_before_build(folder, "<ModVersion> is '%s', not a whole number above 0" % value)
                shutil.rmtree(folder)

    def test_what_is_left_of_either_template_is_refused(self):
        for template in (PLUGIN_TEMPLATE, LUA_TEMPLATE):
            for element, words in (
                ("Guid", ["template's mod ID"]),
                ("Name", ["the template's name"]),
                ("Authors", ["'Your name'"]),
            ):
                with self.subTest(template=template, element=element):
                    folder = self.project(template)
                    set_project_value(folder, element, project_value(template, element))
                    self.assert_refused_before_build(folder, *words)
                    shutil.rmtree(folder)

    def test_the_templates_workshop_text_is_refused(self):
        for template in (PLUGIN_TEMPLATE, LUA_TEMPLATE):
            teaser = project_value(template, "Teaser")
            for text in (read(os.path.join(template, "workshop-description.txt")), WORKSHOP + teaser + "\n"):
                with self.subTest(template=template, text=text):
                    folder = self.project(template)
                    write(os.path.join(folder, "workshop-description.txt"), text)
                    self.assert_refused_before_build(folder, "still has the template's text")
                    shutil.rmtree(folder)

    def test_the_workshop_description_must_name_the_bazaar_in_version(self):
        for text, words in (
            (
                "Requires Bazaar 0.3.0 or newer.",
                ["says 'Requires Bazaar 0.3.0 or newer.'", "VERSION names Bazaar 0.4.0"],
            ),
            ("Needs Bazaar.", ["does not say 'Requires Bazaar 0.4.0 or newer.'"]),
            (None, ["There is no workshop-description.txt"]),
        ):
            with self.subTest(text=text):
                folder = self.project()
                if text is None:
                    os.remove(os.path.join(folder, "workshop-description.txt"))
                else:
                    write(os.path.join(folder, "workshop-description.txt"), text)
                self.assert_refused_before_build(folder, *words)
                shutil.rmtree(folder)

    def test_an_sdk_for_a_newer_bazaar_is_refused(self):
        folder = self.project()
        self.set_sdk_api(0, 5)
        self.assert_refused_before_build(folder, "API 0.5, which Bazaar 0.4.0 refuses", "0.5.0")

    def test_an_sdk_for_another_major_version_is_refused(self):
        folder = self.project()
        self.set_sdk_api(1, 0)
        self.assert_refused_before_build(folder, "API 1.0, which Bazaar 0.4.0 refuses")

    def test_an_sdk_for_an_older_bazaar_is_allowed(self):
        folder = self.project()
        self.set_sdk_api(0, 3)
        self.assert_released(self.release(folder), folder, "1", 1)

    def test_a_plugin_without_the_sdk_is_refused(self):
        folder = self.project()
        del self.env["BAZAAR_SDK"]
        self.assert_refused_before_build(folder, "Set BAZAAR_SDK")

    def test_an_sdk_without_the_api_header_is_refused(self):
        folder = self.project()
        os.remove(os.path.join(self.sdk, "include", "CivPluginApi.h"))
        self.assert_refused_before_build(folder, "The SDK has no include\\CivPluginApi.h")

    def test_a_plugin_without_its_version_header_is_refused(self):
        folder = self.project()
        os.remove(os.path.join(folder, "src", "PluginVersion.h"))
        self.assert_refused_before_build(folder, "src\\PluginVersion.h is missing")

    def test_a_plugin_whose_code_ignores_the_version_header_is_refused(self):
        folder = self.project()
        cpp = os.path.join(folder, "src", "TemplatePlugin.cpp")
        write(cpp, read(cpp).replace('#include "PluginVersion.h"\n', "").replace("PLUGIN_VERSION", '"1"'))
        self.assert_refused_before_build(folder, "No file in src uses PLUGIN_VERSION")

    def test_a_failed_build_releases_nothing(self):
        folder = self.project()
        done = self.assert_refused_after_build(
            folder, "build.cmd stopped", "run release.cmd again", FAKE_BUILD_FAIL="1"
        )
        self.assertIn("failing on purpose", done.stdout)

    def test_a_failed_release_can_be_run_again(self):
        folder = self.project()
        self.set_version(folder, "release 1.0.0\nbazaar 0.4.0\n")
        self.assert_refused_after_build(folder, "run release.cmd again", FAKE_API="0.3")
        self.assert_released(self.release(folder), folder, "1.0.0", 1)
        self.assertEqual(self.version(folder), "release 1.0.0\nmod 1\nbazaar 0.4.0\n")

    def test_a_package_left_by_an_earlier_build_is_not_released(self):
        folder = self.project()
        os.makedirs(os.path.join(folder, "Packages"))
        write(os.path.join(folder, "Packages", PACKAGE % 1), "")
        self.assert_refused_after_build(folder, "made 0 packages", FAKE_NO_PACKAGE="1")

    def test_the_package_is_found_by_its_mod_version(self):
        folder = self.project()
        done = self.release(folder, FAKE_PACKAGE_NAME="Another Name")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(os.path.isfile(os.path.join(folder, "Releases", "1", "Another Name (v 1).civ5mod")))

    def test_what_is_wrong_with_the_package_is_listed_and_nothing_released(self):
        for fake, words in (
            ({"FAKE_API": "0.3"}, ["TemplatePlugin.dll declares API 0.3, but this SDK's is 0.4"]),
            ({"FAKE_API": "none"}, ["declares no API version"]),
            ({"FAKE_64BIT": "1"}, ["could not be read as a 32-bit Windows DLL"]),
            ({"FAKE_AFFECTS_SAVES": "0"}, ["does not affect saved games"]),
            ({"FAKE_NO_ROW": "1"}, ["DllPlugins table"]),
            ({"FAKE_SKIP_DLL": "TemplatePlugin.dll"}, ["it has no TemplatePlugin.dll"]),
            ({"FAKE_MODINFO_VERSION": "7"}, ["mod version is 7, not 1"]),
            ({"FAKE_TWO_MODINFO": "1"}, ["2 mod descriptions"]),
            ({"FAKE_API": "0.3", "FAKE_AFFECTS_SAVES": "0"}, ["declares API 0.3", "does not affect saved games"]),
        ):
            with self.subTest(fake=fake):
                folder = self.project()
                self.assert_refused_after_build(folder, "The package was not released", *words, **fake)
                shutil.rmtree(folder)

    def test_every_dll_a_row_names_is_checked(self):
        folder = self.project()
        self.set_sql(
            folder,
            "CREATE TABLE IF NOT EXISTS DllPlugins (File TEXT NOT NULL);\n"
            "INSERT OR IGNORE INTO DllPlugins (File) VALUES ('TemplatePlugin.dll'), ('Second.dll');\n",
        )
        self.assert_refused_after_build(folder, "it has no Second.dll", FAKE_SKIP_DLL="Second.dll")

    def test_a_commented_out_row_is_ignored(self):
        folder = self.project()
        sql = os.path.join(folder, "mod", "TemplatePlugin.sql")
        self.set_sql(folder, read(sql) + "-- INSERT INTO DllPlugins (File) VALUES ('Old.dll');\n")
        self.assert_released(self.release(folder), folder, "1", 1)

    def test_a_plugin_dll_in_a_project_without_a_vcproj_is_refused(self):
        folder = self.project()
        vcproj = os.path.join(folder, "src", "TemplatePlugin.vcproj")
        os.rename(vcproj, vcproj + ".old")
        self.assert_refused_after_build(folder, "checked as a Lua mod, without the plugin checks")

    def test_a_dll_name_with_two_dashes_is_not_taken_for_a_comment(self):
        folder = self.project()
        self.set_sql(folder, "INSERT INTO DllPlugins (File) VALUES ('Template--Plugin.dll');\n")
        self.assert_released(self.release(folder), folder, "1", 1)

    def test_a_lua_mod_is_released_without_an_sdk(self):
        folder = self.project(LUA_TEMPLATE)
        del self.env["BAZAAR_SDK"]
        self.assert_released(self.release(folder), folder, "1", 1)

    def test_a_lua_mod_that_changes_the_database_must_affect_saved_games(self):
        folder = self.project(LUA_TEMPLATE)
        self.assert_refused_after_build(folder, "does not affect saved games", FAKE_AFFECTS_SAVES="0")

    def test_a_lua_mod_made_by_the_scaffold_script_is_released(self):
        made = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", NEW_LUA_MOD]
            + ["-DisplayName", "Turn Logger", "-Options", "none", "-Destination", self.root]
            + ["-Description", "Logs every turn.", "-Author", "Jane Doe"],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(made.returncode, 0, made.stderr)
        folder = os.path.join(self.root, "TurnLogger")
        self.assertIn("Logs every turn.", read(os.path.join(folder, "workshop-description.txt")))
        self.use_fake_build(folder)
        done = self.release(folder)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(os.path.isfile(os.path.join(folder, "Releases", "1", "Turn Logger (v 1).civ5mod")))


class TemplateFilesTest(unittest.TestCase):
    def test_both_templates_carry_the_same_script(self):
        for name in SCRIPT_FILES:
            with (
                open(os.path.join(PLUGIN_TEMPLATE, name), "rb") as a,
                open(os.path.join(LUA_TEMPLATE, name), "rb") as b,
            ):
                self.assertEqual(a.read(), b.read(), name)

    def test_the_script_is_plain_ascii(self):
        # Windows PowerShell reads a file without a byte order mark in the system's code page, not UTF-8.
        with open(os.path.join(PLUGIN_TEMPLATE, "release.ps1"), "rb") as f:
            self.assertTrue(f.read().isascii())

    def test_the_script_never_spells_a_template_name(self):
        # The scaffold scripts would rename it, and the script would then refuse every mod made from the template.
        text = read(os.path.join(PLUGIN_TEMPLATE, "release.ps1"))
        for name in TEMPLATE_NAMES:
            self.assertNotIn(name, text)

    def test_each_templates_files_agree(self):
        script = read(os.path.join(PLUGIN_TEMPLATE, "release.ps1"))
        for template in (PLUGIN_TEMPLATE, LUA_TEMPLATE):
            with self.subTest(template=template):
                version = dict(line.split(" ", 1) for line in read(os.path.join(template, "VERSION")).splitlines())
                workshop = read(os.path.join(template, "workshop-description.txt"))
                self.assertEqual(project_value(template, "ModVersion"), version["release"])
                self.assertIn("[b]%s[/b]" % version["release"], read(os.path.join(template, "CHANGES.txt")))
                self.assertIn("Requires Bazaar %s or newer." % version["bazaar"], workshop)
                self.assertIn(project_value(template, "Teaser"), workshop)
                self.assertEqual(project_value(template, "AffectsSavedGames"), "true")
                self.assertIn("'%s'" % project_value(template, "Teaser"), script)
                self.assertIn("'%s'" % project_value(template, "Guid"), script)
        self.assertIn('PLUGIN_VERSION "1"', read(os.path.join(PLUGIN_TEMPLATE, "src", "PluginVersion.h")))


if __name__ == "__main__":
    unittest.main()
