"""bazaar-build.ps1, the part of both templates' build.cmd that finds the project's files and the SDK and checks the
package, run on copies of the templates with fake_build.py standing in for the building in between; the plugin
template's build.cmd, run up to Visual C++; and the texts that name the Bazaar version the templates are for.

python -m unittest discover -s tests/sdk
"""

import contextlib
import filecmp
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from xml.etree import ElementTree

import fake_build

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "generator"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "sdk"))

import build_sdk  # noqa: E402
import common  # noqa: E402
import version  # noqa: E402

PLUGIN_TEMPLATE = os.path.join(REPO, "sdk", "plugin-template")
LUA_TEMPLATE = os.path.join(REPO, "claude-plugin", "skills", "new-lua-mod", "template")
SKILLS = os.path.join(REPO, "claude-plugin", "skills")
NEW_DLL_PLUGIN = os.path.join(SKILLS, "new-dll-plugin", "scripts", "new-dll-plugin.ps1")
NEW_LUA_MOD = os.path.join(SKILLS, "new-lua-mod", "scripts", "new-lua-mod.ps1")
GUIDE = os.path.join(REPO, "sdk", "README.md")
SCRIPT = "bazaar-build.ps1"
# The files the guide's steps for a new Bazaar version copy from that version's SDK over the project's own.
COPIED_FILES = ("build.cmd", "check.cmd", "play.cmd", SCRIPT)
TEMPLATE_NAMES = ("TemplatePlugin", "Template Plugin", "TemplateLuaMod", "Template Lua Mod")
NAME = "Score Doubler"
DLL = "ScoreDoubler.dll"
PACKAGE = NAME + " (v 1).civ5mod"
MSBUILD = "{http://schemas.microsoft.com/developer/msbuild/2003}"
LIST_ENTRY = re.compile(r"^\s+'(\d+\.\d+)' = '([0-9a-f-]+)'$", re.M)
SAVES_OFF = "<AffectsSavedGames>0</AffectsSavedGames>"

ElementTree.register_namespace("", MSBUILD[1:-1])


def read(path):
    with open(path, encoding="latin-1", newline="") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="latin-1", newline="") as f:
        f.write(text)


def branch_version():
    return "%d.%d" % version.numbers(version.read().release)[:2]


def other_version(of):
    major, minor = of.split(".")
    return "%s.%d" % (major, int(minor) + 1)


def sdk_variable(of):
    return "BAZAAR_SDK_" + of.replace(".", "_")


def known_versions(script):
    return dict(LIST_ENTRY.findall(read(script)))


def civ5proj(folder):
    (name,) = [n for n in os.listdir(os.path.join(folder, "mod")) if n.endswith(".civ5proj")]
    return os.path.join(folder, "mod", name)


def edit_project(folder, change):
    path = civ5proj(folder)
    tree = ElementTree.parse(path)
    change(tree.getroot().find(MSBUILD + "PropertyGroup"))
    tree.write(path, encoding="utf-8", xml_declaration=True)


def setting_values(**values):
    def change(group):
        for name, value in values.items():
            group.find(MSBUILD + name).text = value

    return change


def dependency_on(group, mod_id):
    (found,) = [a for a in group.iter(MSBUILD + "Association") if a.find(MSBUILD + "Id").text.lower() == mod_id]
    return found


def mod_file(folder, extension):
    (name,) = [n for n in os.listdir(os.path.join(folder, "mod")) if n.endswith(extension)]
    return os.path.join(folder, "mod", name)


class BuildScriptTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.version = branch_version()
        self.variable = sdk_variable(self.version)
        self.sdk = self.make_sdk(os.path.join(self.root, "Bazaar SDK"), self.version)
        self.temp = os.path.join(self.root, "temp")
        os.makedirs(self.temp)
        self.env = dict((k, v) for k, v in os.environ.items() if not k.upper().startswith("BAZAAR_SDK"))
        self.env.update(TEMP=self.temp, TMP=self.temp)

    def make_sdk(self, folder, api):
        os.makedirs(os.path.join(folder, "include"), exist_ok=True)
        write(os.path.join(folder, "CivPlugin.vsprops"), "")
        major, minor = api.split(".")
        write(
            os.path.join(folder, "include", "CivPluginApi.h"),
            "#define CIV_HOST_API_MAJOR %s\n#define CIV_HOST_API_MINOR %s\n" % (major, minor),
        )
        return folder

    def project(self, template=PLUGIN_TEMPLATE, inside=None):
        """With the template's settings and DLL name changed, in a folder with a space in its name, so the script's
        quoting is tested."""
        folder = os.path.join(inside or self.root, NAME)
        shutil.copytree(template, folder, ignore=shutil.ignore_patterns("out", "Build", "Packages", "__pycache__"))
        teaser = "Doubles every player's score."
        edit_project(
            folder,
            setting_values(Guid=str(uuid.uuid4()), Name=NAME, Authors="Jane Doe", Teaser=teaser, Description=teaser),
        )
        for path in (mod_file(folder, ".sql"), os.path.join(folder, "src", "TemplatePlugin.vcproj")):
            if os.path.exists(path):
                write(path, read(path).replace("TemplatePlugin.dll", DLL))
        return folder

    def run_script(self, folder, step, plugin=True, **env):
        done = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(folder, SCRIPT), step]
            + (["-Plugin"] if plugin else []),
            env=dict(self.env, **env),
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            [n for n in os.listdir(self.temp) if n.startswith("bazaar-build-")], [], "unpacked package left"
        )
        return done

    def start(self, folder, plugin=True, **env):
        done = self.run_script(folder, "start", plugin, **env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return dict(line.split("=", 1) for line in done.stdout.splitlines())

    def check(self, folder, found, plugin=True):
        return self.run_script(folder, "check", plugin, **({"BAZAAR_SDK": found["SDK"]} if plugin else {}))

    def build(self, folder, plugin=True, **fake):
        """start, the fake build and check, as build.cmd runs them, with the SDK given to a plugin's build.cmd. The
        fake build packs the DLL start named, declaring the SDK's API version, unless fake says otherwise."""
        found = self.start(folder, plugin, **({"BAZAAR_SDK_GIVEN": self.sdk} if plugin else {}))
        fake.setdefault("dlls", [found["DLL"]] if plugin else [])
        fake.setdefault("api", self.version)
        fake_build.Build(**fake).pack(folder)
        return self.check(folder, found, plugin)

    def assert_checked(self, done, package=PACKAGE):
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("build: checked Packages\\" + package, done.stdout)

    def assert_problems(self, folder, done, *words):
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("build: Packages\\%s has these problems:" % PACKAGE, done.stderr)
        for word in words:
            self.assertIn(word, done.stderr)
        self.assertIn(
            "build.cmd deleted the package, so that nobody can upload a broken package by mistake.", done.stderr
        )
        self.assertEqual(os.listdir(os.path.join(folder, "Packages")), [])

    def assert_start_stops(self, folder, words, plugin=True, **env):
        done = self.run_script(folder, "start", plugin, **env)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(done.stdout, "")
        for word in words:
            self.assertIn(word, done.stderr)
        return done

    def assert_sdk(self, found, sdk=None):
        self.assertEqual(os.path.normcase(found["SDK"]), os.path.normcase(sdk or self.sdk))

    def test_the_sdk_given_to_build_cmd_is_used(self):
        other = self.make_sdk(os.path.join(self.root, "Other SDK"), self.version)
        self.assert_sdk(self.start(self.project(), BAZAAR_SDK_GIVEN=self.sdk, **{self.variable: other}))

    def test_without_one_the_variable_for_the_version_the_mod_depends_on_is_used(self):
        self.assert_sdk(self.start(self.project(), **{self.variable: self.sdk}))

    def test_without_either_the_folder_above_the_project_is_used(self):
        self.assert_sdk(self.start(self.project(inside=self.sdk)))

    def test_a_folder_given_with_a_separator_at_its_end_is_printed_without_it(self):
        folder = self.project()
        for end in ("\\", "/"):
            self.assert_sdk(self.start(folder, BAZAAR_SDK_GIVEN=self.sdk + end))
            self.assert_sdk(self.start(folder, **{self.variable: self.sdk + end}))

    def test_without_any_sdk_it_names_the_variable_and_the_one_visual_cpp_reads(self):
        folder = self.project()
        done = self.assert_start_stops(folder, ["No Bazaar SDK was found for Bazaar " + self.version, self.variable])
        self.assertNotIn("Visual C++ reads", done.stderr)
        self.assert_start_stops(
            folder, ["is the variable that Visual C++ reads. build.cmd reads " + self.variable], BAZAAR_SDK=self.sdk
        )

    def test_an_sdk_whose_header_names_no_api_version_is_refused(self):
        folder = self.project()
        sdk = self.make_sdk(os.path.join(self.root, "Odd SDK"), self.version)
        write(os.path.join(sdk, "include", "CivPluginApi.h"), "// no version here\n")
        self.assert_start_stops(folder, ["include\\CivPluginApi.h", "names no API version"], BAZAAR_SDK_GIVEN=sdk)

    def test_a_folder_that_is_not_an_sdk_is_refused(self):
        folder = self.project()
        half = os.path.join(self.root, "Half SDK")
        os.makedirs(half)
        write(os.path.join(half, "CivPlugin.vsprops"), "")
        self.assert_start_stops(folder, ["given to build.cmd", "is not a Bazaar SDK"], BAZAAR_SDK_GIVEN=half)
        self.assert_start_stops(
            folder, ["The folder in " + self.variable, "is not a Bazaar SDK"], **{self.variable: half}
        )

    def test_an_sdk_for_another_bazaar_version_is_refused(self):
        other = other_version(self.version)
        newer = self.make_sdk(os.path.join(self.root, "Newer SDK"), other)
        self.assert_start_stops(
            self.project(), ["is for Bazaar " + other, "depends on Bazaar " + self.version], BAZAAR_SDK_GIVEN=newer
        )

    def test_a_mod_that_depends_on_no_bazaar_the_script_knows_is_refused(self):
        folder = self.project()
        bazaar = known_versions(os.path.join(folder, SCRIPT))[self.version]

        def depend_on_another_mod(group):
            dependency_on(group, bazaar).find(MSBUILD + "Id").text = str(uuid.uuid4())

        edit_project(folder, depend_on_another_mod)
        words = ["does not depend on a Bazaar version that this build script can build for"]
        self.assert_start_stops(folder, words, BAZAAR_SDK_GIVEN=self.sdk)

    def test_a_mod_that_depends_on_two_bazaar_versions_is_refused(self):
        folder = self.project()
        script = os.path.join(folder, SCRIPT)
        bazaar = known_versions(script)[self.version]
        second = str(uuid.uuid4())
        entry = "    '%s' = '%s'\n" % (self.version, bazaar)
        write(script, read(script).replace(entry, entry + "    '9.9' = '%s'\n" % second))

        def depend_on_both(group):
            dependency = dependency_on(group, bazaar)
            copy = ElementTree.fromstring(ElementTree.tostring(dependency))
            copy.find(MSBUILD + "Id").text = second
            group.find(MSBUILD + "ModDependencies").append(copy)

        edit_project(folder, depend_on_both)
        words = ["depends on Bazaar", "9.9", "built for a single Bazaar version"]
        self.assert_start_stops(folder, words, BAZAAR_SDK_GIVEN=self.sdk)

    def test_start_prints_the_files_build_cmd_builds_from_and_a_lua_mod_needs_no_sdk(self):
        found = self.start(self.project(), BAZAAR_SDK_GIVEN=self.sdk)
        self.assert_sdk(found)
        expected = {
            "VCPROJ": "src\\TemplatePlugin.vcproj",
            "DLL": DLL,
            "NAME": NAME,
            "PROJECT": "mod\\TemplatePlugin.civ5proj",
        }
        self.assertEqual(list(found), ["SDK"] + list(expected), "PROJECT last, as build.cmd expects")
        self.assertEqual(dict(found, SDK=None), dict(expected, SDK=None))
        shutil.rmtree(os.path.join(self.root, NAME))
        lua = self.run_script(self.project(LUA_TEMPLATE), "start", False)
        self.assertEqual((lua.returncode, lua.stderr), (0, ""))
        self.assertEqual(lua.stdout.splitlines(), ["NAME=" + NAME, "PROJECT=mod\\TemplateLuaMod.civ5proj"])

    def test_a_plugin_needs_one_vcproj_that_names_its_dll(self):
        folder = self.project()
        vcproj = os.path.join(folder, "src", "TemplatePlugin.vcproj")
        text = read(vcproj)
        for output in ("$(OutDir)\\$(ProjectName).dll", "..\\bin\\" + DLL):
            write(vcproj, text.replace("$(OutDir)\\" + DLL, output))
            self.assert_start_stops(folder, ["does not give the file name of the DLL"], BAZAAR_SDK_GIVEN=self.sdk)
        write(vcproj, text.replace('OutputDirectory="$(ProjectDir)out"', 'OutputDirectory="$(SolutionDir)Release"'))
        words = ["does not set the Output Directory", "to $(ProjectDir)out"]
        self.assert_start_stops(folder, words, BAZAAR_SDK_GIVEN=self.sdk)
        write(vcproj, text.replace("</Files>", ""))
        self.assert_start_stops(
            folder,
            ["src\\", "is not valid XML", "Open the file in a text editor and fix the XML."],
            BAZAAR_SDK_GIVEN=self.sdk,
        )
        os.remove(vcproj)
        words = ["Expected exactly one .vcproj file in the src folder, but found 0."]
        self.assert_start_stops(folder, words, BAZAAR_SDK_GIVEN=self.sdk)

    def test_start_removes_a_package_an_earlier_build_left(self):
        for template, plugin in ((PLUGIN_TEMPLATE, True), (LUA_TEMPLATE, False)):
            folder = self.project(template)
            os.makedirs(os.path.join(folder, "Packages"))
            left = os.path.join(folder, "Packages", "Old Name (v 1).civ5mod")
            kept = os.path.join(folder, "Packages", NAME + " (v 2).civ5mod")
            for path in (left, kept):
                write(path, "")
            self.start(folder, plugin, BAZAAR_SDK_GIVEN=self.sdk)
            self.assertEqual(os.listdir(os.path.join(folder, "Packages")), [os.path.basename(kept)])
            shutil.rmtree(folder)

    def test_a_project_the_script_cannot_read_stops_it(self):
        folder = self.project(LUA_TEMPLATE)
        path = civ5proj(folder)
        text = read(path)
        edit_project(folder, setting_values(ModVersion="first"))
        self.assert_start_stops(folder, ["has no <ModVersion> line with a whole number"], False)
        write(path, text)
        edit_project(folder, setting_values(Name=" "))
        self.assert_start_stops(folder, ["No mod name was found in mod\\TemplateLuaMod.civ5proj."], False)
        write(path, text.replace("</Name>", "", 1))
        self.assert_start_stops(
            folder, ["mod\\", "is not valid XML", "Open the file in a text editor and fix the XML."], False
        )
        write(path, text)
        shutil.copy(path, path.replace(".civ5proj", " copy.civ5proj"))
        self.assert_start_stops(folder, ["Expected exactly one .civ5proj file in the mod folder, but found 2."], False)

    def test_a_project_saved_with_a_byte_order_mark_is_read(self):
        folder = self.project()
        write(civ5proj(folder), "\xef\xbb\xbf" + read(civ5proj(folder)))
        self.assert_checked(self.build(folder))

    def test_a_plugin_and_a_lua_mod_that_are_right_pass_without_warnings(self):
        for template, plugin in ((PLUGIN_TEMPLATE, True), (LUA_TEMPLATE, False)):
            folder = self.project(template)
            done = self.build(folder, plugin)
            self.assert_checked(done)
            self.assertNotIn("warning", done.stdout)
            shutil.rmtree(folder)

    def test_mods_made_with_the_scaffold_scripts_build_without_warnings(self):
        shutil.copytree(
            PLUGIN_TEMPLATE,
            os.path.join(self.sdk, "plugin-template"),
            ignore=shutil.ignore_patterns("out", "Build", "Packages", "__pycache__"),
        )
        made = os.path.join(self.root, "made")
        os.makedirs(made)
        for script, options, plugin in (
            (NEW_DLL_PLUGIN, ["-Sdk", self.sdk], True),
            (NEW_LUA_MOD, ["-Options", "none"], False),
        ):
            scaffold = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script]
            scaffold += ["-DisplayName", NAME, "-Author", "Jane Doe", "-Destination", made] + options
            done = subprocess.run(scaffold, env=self.env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            folder = os.path.join(made, "ScoreDoubler")
            built = self.build(folder, plugin)
            self.assert_checked(built)
            self.assertNotIn("warning", built.stdout)
            shutil.rmtree(folder)

    def test_what_is_left_of_either_template_is_a_warning_and_the_build_still_passes(self):
        for template, plugin in ((PLUGIN_TEMPLATE, True), (LUA_TEMPLATE, False)):
            folder = os.path.join(self.root, "Unchanged")
            shutil.copytree(template, folder, ignore=shutil.ignore_patterns("out", "Build", "Packages", "__pycache__"))
            done = self.build(folder, plugin)
            self.assertEqual(done.returncode, 0, done.stderr)
            warnings = [line for line in done.stdout.splitlines() if line.startswith("build: warning: ")]
            expected = ["template's mod ID", "the template's name", "'Your name'", "the template's text"]
            if plugin:
                expected.append("still adds the template's DLL")
            self.assertEqual(len(warnings), len(expected), done.stdout)
            for words in expected:
                self.assertTrue(any(words in line for line in warnings), words)
            shutil.rmtree(folder)

    def test_the_template_s_dll_in_an_xml_row_is_a_warning_too_and_the_build_still_passes(self):
        folder = self.project()
        template_dll = "Template" + "Plugin.dll"
        rows = "<GameData><DllPlugins><Row File='%s'/></DllPlugins></GameData>" % template_dll
        write(os.path.join(folder, "mod", "Rows.xml"), rows)
        done = self.build(folder, dlls=[DLL, template_dll])
        self.assert_checked(done)
        self.assertIn("build: warning: mod\\Rows.xml still adds the template's DLL", done.stdout)

    def test_a_mod_that_changes_the_database_must_affect_saved_games(self):
        folder = self.project()
        for saves in (SAVES_OFF, "<!-- %s -->" % fake_build.SAVES):
            self.assert_problems(folder, self.build(folder, saves=saves), "not set to affect saved games")

    def test_a_plugin_without_a_dll_plugins_row_is_refused(self):
        folder = self.project()
        sql = mod_file(folder, ".sql")
        write(sql, "".join(line for line in read(sql).splitlines(True) if not line.startswith("INSERT")))
        self.assert_problems(folder, self.build(folder), "DllPlugins table")

    def test_dll_plugins_rows_in_an_xml_database_update_are_read(self):
        folder = self.project()
        sql = mod_file(folder, ".sql")
        write(sql, "".join(line for line in read(sql).splitlines(True) if not line.startswith("INSERT")))
        rows = os.path.join(folder, "mod", "Rows.xml")
        write(
            rows,
            "<GameData><DllPlugins><Row><File>Child.dll</File></Row><!-- <Row File='Commented.dll'/> -->"
            "<Replace File='Second.dll'/></DllPlugins></GameData>",
        )
        done = self.build(folder)
        self.assert_problems(folder, done, "it has no Child.dll", "it has no Second.dll")
        self.assertNotIn("DllPlugins table", done.stderr)
        self.assertNotIn("Commented.dll", done.stderr)
        write(rows, "<GameData>")
        self.assert_problems(folder, self.build(folder), "Rows.xml is not valid XML", "DllPlugins table")

    def test_a_missing_or_unlisted_dll_is_refused(self):
        folder = self.project()
        self.assert_problems(folder, self.build(folder, skip_dll=DLL), "it has no " + DLL)
        self.assert_problems(folder, self.build(folder, unlisted_dll=DLL), "does not list " + DLL)

    def test_a_dll_in_a_subfolder_of_the_mod_is_found_by_its_file_name_as_bazaar_finds_it(self):
        folder = self.project()
        self.assert_checked(self.build(folder, dll_folder="Bin"))
        self.assert_problems(folder, self.build(folder, dll_folder="Bin", bits=64), "32-bit Windows DLL")

    def test_two_files_with_the_dll_s_name_are_refused_since_their_order_decides_which_bazaar_loads(self):
        folder = self.project()
        words = "more than one file named %s: Old\\%s and %s." % (DLL, DLL, DLL)
        self.assert_problems(folder, self.build(folder, copy_in="Old"), words)

    def test_a_plugin_dll_must_declare_its_sdk_s_api_version_as_a_32_bit_dll(self):
        folder = self.project()
        other = other_version(self.version)
        self.assert_problems(folder, self.build(folder, api=other), "declares API " + other)
        self.assert_problems(folder, self.build(folder, api=None), "CIV_PLUGIN_EXPORT_API_VERSION")
        self.assert_problems(folder, self.build(folder, bits=64), "32-bit Windows DLL")

    def test_a_lua_mod_with_a_dll_gets_every_check_but_the_api_version(self):
        folder = self.project(LUA_TEMPLATE)
        sql = mod_file(folder, ".sql")
        write(sql, read(sql) + "INSERT INTO DllPlugins (File) VALUES ('%s');\n" % DLL)
        self.assert_checked(self.build(folder, False, dlls=[DLL], api=None))
        self.assert_problems(folder, self.build(folder, False, dlls=[DLL], unlisted_dll=DLL), "does not list " + DLL)
        self.assert_problems(folder, self.build(folder, False, dlls=[DLL], bits=64), "32-bit Windows DLL")

    def test_every_dll_a_row_names_is_checked_however_the_row_is_written(self):
        folder = self.project()
        second = "Second--Half.dll"
        sql = mod_file(folder, ".sql")
        write(
            sql,
            read(sql) + "-- INSERT INTO DllPlugins (File) VALUES ('Commented.dll');\n"
            "INSERT OR REPLACE INTO DllPlugins (File) VALUES ('%s');\n" % second,
        )
        done = self.build(folder)
        self.assert_problems(folder, done, "it has no " + second)
        self.assertNotIn("Commented.dll", done.stderr)

    def test_a_broken_package_is_listed(self):
        folder = self.project()
        self.assert_problems(folder, self.build(folder, broken_modinfo=True), "not valid XML")
        self.assert_problems(folder, self.build(folder, two_modinfo=True), "2 mod descriptions")

    def test_a_package_that_tar_cannot_unpack_is_refused(self):
        folder = self.project()
        found = self.start(folder, BAZAAR_SDK_GIVEN=self.sdk)
        os.makedirs(os.path.join(folder, "Packages"))
        write(os.path.join(folder, "Packages", PACKAGE), "not a package")
        self.assert_problems(folder, self.check(folder, found), "Windows' tar could not unpack the package")

    def test_the_package_must_be_the_one_the_build_made_for_the_mod_version(self):
        folder = self.project()
        found = self.start(folder, BAZAAR_SDK_GIVEN=self.sdk)
        self.assertIn("made 0 packages ending in '(v 1).civ5mod'", self.check(folder, found).stderr)
        for name in (NAME, "Another Name"):
            fake_build.Build(dlls=[DLL], api=self.version, package_name=name).pack(folder)
        self.assertIn("made 2 packages", self.check(folder, found).stderr)
        self.assert_checked(self.build(folder, package_name="Another Name"), "Another Name (v 1).civ5mod")

    # build.cmd run without Visual C++: reaching its "not found" message shows it found the SDK.

    def run_build_cmd(self, folder, *args, **env):
        missing = os.path.join(self.root, "No Visual C++") + "\\"
        return subprocess.run(
            build_sdk.build_command(os.path.join(folder, "build.cmd"), *args),
            env=dict(self.env, VS90COMNTOOLS=missing, **env),
            capture_output=True,
            text=True,
        )

    def assert_found_sdk(self, done):
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout.strip(), "Visual C++ 2008 was not found.", done.stderr)

    def test_build_cmd_finds_the_sdk_with_and_without_a_folder_given(self):
        self.assert_found_sdk(self.run_build_cmd(self.project(inside=self.sdk)))
        folder = self.project()
        self.assert_found_sdk(self.run_build_cmd(folder, **{self.variable: self.sdk + "\\"}))
        self.assert_found_sdk(self.run_build_cmd(folder, self.sdk + "\\"))

    def test_build_cmd_passes_on_folders_with_brackets_a_caret_and_an_ampersand(self):
        sdk = self.make_sdk(os.path.join(self.root, "Bazaar ^SDK & (x86)"), self.version)
        self.assert_found_sdk(self.run_build_cmd(self.project(inside=os.path.join(self.root, "Mods & (x86)")), sdk))

    def test_build_cmd_stops_with_the_script_s_message_when_no_sdk_is_found(self):
        done = self.run_build_cmd(self.project(), BAZAAR_SDK=self.sdk)
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertIn("No Bazaar SDK was found", done.stderr)
        self.assertIn("is the variable that Visual C++ reads.", done.stderr)


class SdkBuildTest(unittest.TestCase):
    def test_the_sdk_s_build_of_the_template_fails_without_the_package_check_s_line(self):
        with tempfile.TemporaryDirectory() as folder:
            build_cmd = os.path.join(folder, "build.cmd")
            for lines, passes in (
                ("@echo build: checked Packages\\x\n", True),
                ("@echo built\n", False),
                ("@echo build: checked Packages\\x\n@exit /b 1\n", False),
            ):
                write(build_cmd, lines.replace("\n", "\r\n"))
                with self.subTest(lines=lines), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(build_sdk.builds_and_passes_its_check(build_cmd, folder), passes)


class OnePlaceTest(unittest.TestCase):
    def test_both_templates_build_scripts_are_the_same(self):
        self.assertTrue(filecmp.cmp(os.path.join(PLUGIN_TEMPLATE, SCRIPT), os.path.join(LUA_TEMPLATE, SCRIPT), False))

    def test_the_build_script_lists_this_version_with_bazaar_s_mod_id_as_its_newest(self):
        versions = known_versions(os.path.join(PLUGIN_TEMPLATE, SCRIPT))
        self.assertEqual(versions.get(branch_version()), common.HOST_MOD_ID)
        self.assertEqual(list(versions)[-1], branch_version())

    def test_the_guide_s_table_of_mod_ids_has_every_version_the_build_script_lists(self):
        guide = read(GUIDE)
        for listed, mod_id in known_versions(os.path.join(PLUGIN_TEMPLATE, SCRIPT)).items():
            self.assertIn("| %s | `%s` |" % (listed, mod_id), guide)

    def test_both_templates_depend_on_this_version_s_bazaar(self):
        for template in (PLUGIN_TEMPLATE, LUA_TEMPLATE):
            ids = [e.text for e in ElementTree.parse(civ5proj(template)).iter(MSBUILD + "Id")]
            self.assertIn(common.HOST_MOD_ID, ids, template)

    def test_texts_that_name_a_bazaar_version_name_this_branch_s(self):
        names = {
            r"Runs on Bazaar (\d+\.\d+)\.x\.": [
                GUIDE,
                os.path.join(PLUGIN_TEMPLATE, "workshop-description.txt"),
                os.path.join(LUA_TEMPLATE, "workshop-description.txt"),
                os.path.join(SKILLS, "new-lua-mod", "SKILL.md"),
                os.path.join(SKILLS, "new-dll-plugin", "SKILL.md"),
            ],
            r"BAZAAR_SDK_(\d+_\d+)": [
                GUIDE,
                NEW_DLL_PLUGIN,
                os.path.join(SKILLS, "new-dll-plugin", "SKILL.md"),
                os.path.join(
                    SKILLS, "new-dll-plugin", "evals", "score-doubler-builds", "graders", "05-left-machine-alone.md"
                ),
            ],
        }
        for pattern, paths in names.items():
            for path in paths:
                found = {v.replace("_", ".") for v in re.findall(pattern, read(path))}
                self.assertEqual(found, {branch_version()}, (pattern, path))

    def test_the_files_a_newer_sdk_replaces_name_no_template_so_they_can_be_copied_over_a_renamed_project(self):
        for template in (PLUGIN_TEMPLATE, LUA_TEMPLATE):
            for name in COPIED_FILES:
                text = read(os.path.join(template, name))
                self.assertEqual([n for n in TEMPLATE_NAMES if n in text], [], os.path.join(template, name))

    def test_the_build_script_is_plain_ascii_which_windows_powershell_reads_without_a_byte_order_mark(self):
        with open(os.path.join(PLUGIN_TEMPLATE, SCRIPT), "rb") as f:
            f.read().decode("ascii")


if __name__ == "__main__":
    unittest.main()
