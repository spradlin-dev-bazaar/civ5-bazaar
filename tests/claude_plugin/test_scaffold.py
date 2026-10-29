"""The new-dll-plugin and new-lua-mod skills' scaffold scripts, run on the real templates and on altered copies; and the
skills' eval graders, which name the templates' mod IDs.

python -m unittest discover -s tests/claude_plugin
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from xml.etree import ElementTree
from xml.parsers import expat

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "sdk"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import build_sdk  # noqa: E402
from bazaar_check import runner  # noqa: E402

SKILLS = os.path.join(REPO, "claude-plugin", "skills")
NEW_LUA_MOD = os.path.join(SKILLS, "new-lua-mod", "scripts", "new-lua-mod.ps1")
NEW_DLL_PLUGIN = os.path.join(SKILLS, "new-dll-plugin", "scripts", "new-dll-plugin.ps1")
LUA_TEMPLATE = os.path.join(SKILLS, "new-lua-mod", "template")
PLUGIN_TEMPLATE = os.path.join(REPO, "sdk", "plugin-template")
REPOSITORY_SDK = os.path.relpath(build_sdk.SDK, build_sdk.HERE)
BOM = b"\xef\xbb\xbf"
PLUGIN_NAMES = [("Template Plugin", "Score Doubler"), ("TemplatePlugin", "ScoreDoubler")]
# What a template folder holds after a build, which the scripts must leave out.
BUILD_OUTPUT = [
    os.path.join("Build", "Template Plugin", "x.txt"),
    os.path.join("Packages", "Template Plugin.civ5mod"),
    os.path.join("src", "out", "TemplatePlugin.obj"),
    os.path.join("mod", "TemplatePlugin.dll"),
    os.path.join("src", "TemplatePlugin.vcproj.PC.user"),
    "TemplatePlugin.ncb",
    os.path.join("bazaar_check", "__pycache__", "runner.cpython-312.pyc"),
]


def tracked(template):
    """The template's files as git has them, so a developer's leftovers in the folder do not count."""
    listed = subprocess.run(
        ["git", "-C", REPO, "ls-files", "-z", "--", os.path.relpath(template, REPO)], capture_output=True, check=True
    ).stdout.decode("utf-8")
    files = {}
    for path in filter(None, listed.split("\0")):
        with open(os.path.join(REPO, path), "rb") as f:
            files[os.path.relpath(os.path.join(REPO, path), template)] = f.read()
    return files


def files_of(folder):
    found = {}
    for path, _, names in os.walk(folder):
        for name in names:
            with open(os.path.join(path, name), "rb") as f:
                found[os.path.relpath(os.path.join(path, name), folder)] = f.read()
    return found


def project_of(files):
    return next(data for relative, data in files.items() if relative.endswith(".civ5proj"))


def setting_texts(data, names):
    """Where each setting's text starts and ends in data, the element chosen as scaffold.ps1's Find-ElementTexts
    chooses the one it edits."""
    parser = expat.ParserCreate()
    path, spans = [], {}
    setting = text_start = None

    def start(name, attributes):
        nonlocal setting, text_start
        path.append(name)
        if len(path) == 3 and path[:2] == ["Project", "PropertyGroup"] and name in names and name not in spans:
            setting, text_start = name, None

    def text(content):
        nonlocal text_start
        if setting and len(path) == 3 and text_start is None:
            text_start = parser.CurrentByteIndex

    def end(name):
        nonlocal setting
        if setting and len(path) == 3:
            spans[setting] = (parser.CurrentByteIndex if text_start is None else text_start, parser.CurrentByteIndex)
            setting = None
        path.pop()

    parser.StartElementHandler, parser.CharacterDataHandler, parser.EndElementHandler = start, text, end
    parser.Parse(data, True)
    return spans


def without_settings(data, names):
    for start, end in sorted(setting_texts(data, names).values(), reverse=True):
        data = data[:start] + data[end:]
    return data


def replace_once(data, old, new):
    if old not in data:
        raise AssertionError("The template no longer holds %r." % old)
    return data.replace(old, new, 1)


def project_values(data):
    root = ElementTree.fromstring(data[len(BOM) :] if data.startswith(BOM) else data)
    settings = next(child for child in root if child.tag.endswith("PropertyGroup"))
    values = {}
    for child in settings:
        values.setdefault(child.tag.split("}")[1], child.text)
    return values


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        self.out = os.path.join(self.folder, "out")
        os.makedirs(self.out)
        self.env = {k: v for k, v in os.environ.items() if k.upper() != "BAZAAR_SDK"}

    def run_script(self, script, *args, cwd=None, env=None):
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script] + list(args),
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env or self.env,
        )

    def make_sdk(self, where, change_project=None, extra=None):
        """A stand-in for an unzipped SDK: the plugin template, altered if asked, and the property sheet the script
        looks for."""
        for relative, data in tracked(PLUGIN_TEMPLATE).items():
            if relative.endswith(".civ5proj") and change_project:
                data = change_project(data)
            path = os.path.join(where, "plugin-template", relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        for relative, data in (extra or {}).items():
            path = os.path.join(where, "plugin-template", relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        open(os.path.join(where, "CivPlugin.vsprops"), "w").close()
        return where

    def make_plugin(self, sdk, name="Score Doubler", *extra):
        return self.run_script(NEW_DLL_PLUGIN, "-DisplayName", name, "-Sdk", sdk, "-Destination", self.out, *extra)

    def assert_made_like(self, template, done, made, names, values, rewritten=()):
        """The made folder holds every template file, renamed, with the same bytes; in the .civ5proj only a new mod ID
        and the values given differ, and workshop-description.txt has the new teaser in place of the template's."""
        self.assertEqual(done.returncode, 0, done.stderr)
        before_values = project_values(project_of(template))
        expected = {}
        for relative, data in template.items():
            for old, new in names:
                relative = relative.replace(old, new)
                data = data.replace(old.encode(), new.encode())
            if relative == "workshop-description.txt" and "Teaser" in values:
                data = data.replace(before_values["Teaser"].encode(), values["Teaser"].encode())
            expected[relative] = data
        actual = files_of(made)
        self.assertEqual(sorted(actual), sorted(expected))
        for relative, data in actual.items():
            if relative.endswith(".civ5proj"):
                self.assert_project(expected[relative], data, done, values)
            elif relative not in rewritten:
                self.assertEqual(data, expected[relative], relative)

    def assert_project(self, template, made, done, values):
        before, after = project_values(template), project_values(made)
        self.assertNotEqual(after["Guid"], before["Guid"])
        self.assertEqual(str(uuid.UUID(after["Guid"])), after["Guid"])
        self.assertIn("Mod ID:", done.stdout)
        self.assertEqual(re.search(r"Mod ID:\s+(\S+)", done.stdout).group(1), after["Guid"])
        changed = dict(values, Guid=after["Guid"])
        for name in after:
            self.assertEqual(after[name], changed.get(name, before[name]), name)
        self.assertEqual(without_settings(made, changed), without_settings(template, changed))

    def test_a_lua_mod_is_the_template_with_its_names_a_new_id_and_the_values_given(self):
        done = self.run_script(
            NEW_LUA_MOD,
            "-DisplayName",
            "Tom's Turn Logger (x)",
            "-Options",
            "EVENTS_PLAYER_TURN, EVENTS_PLAYER_TURN",
            "-Destination",
            self.out,
            "-Description",
            "Logs <each> turn & more.",
            "-Author",
            "A & B",
        )
        made = os.path.join(self.out, "TomSTurnLoggerX")
        names = [("Template Lua Mod", "Tom's Turn Logger (x)"), ("TemplateLuaMod", "TomSTurnLoggerX")]
        sql = os.path.join("mod", "TomSTurnLoggerX.sql")
        values = {"Teaser": "Logs <each> turn & more.", "Description": "Logs <each> turn & more.", "Authors": "A & B"}
        self.assert_made_like(tracked(LUA_TEMPLATE), done, made, names, values, rewritten={sql})
        with open(os.path.join(LUA_TEMPLATE, "mod", "TemplateLuaMod.sql"), "rb") as f:
            header = f.read().split(b"\n")[0] + b"\n"
        for old, new in names:
            header = header.replace(old.encode(), new.encode())
        with open(os.path.join(made, sql), "rb") as f:
            self.assertEqual(
                f.read(), header + b"UPDATE CustomModOptions SET Value = 1 WHERE Name = 'EVENTS_PLAYER_TURN';\n"
            )
        checks = runner.read_checks(os.path.join(made, "checks.toml"))
        self.assertEqual(checks.mods, [os.path.join(made, "Build", "Tom's Turn Logger (x)")])
        with open(os.path.join(made, "mod", "TomSTurnLoggerX.lua"), encoding="utf-8") as f:
            before, after = re.search(r'print\("([^"]*)" \.\. iPlayer \.\. "([^"]*)"\)', f.read()).groups()
        (log,) = [step for step in checks.steps if "log" in step]
        self.assertRegex(before + "0" + after, log["has"])

    def test_a_lua_mod_with_no_options_description_or_author_keeps_the_template_s_defaults(self):
        done = self.run_script(NEW_LUA_MOD, "-DisplayName", "Turn Logger", "-Options", "none", "-Destination", self.out)
        made = os.path.join(self.out, "TurnLogger")
        teaser = "Turn Logger, a Lua mod for the Bazaar Multi-DLL Mod Loader."
        sql = os.path.join("mod", "TurnLogger.sql")
        names = [("Template Lua Mod", "Turn Logger"), ("TemplateLuaMod", "TurnLogger")]
        self.assert_made_like(
            tracked(LUA_TEMPLATE), done, made, names, {"Teaser": teaser, "Description": teaser}, {sql}
        )
        with open(os.path.join(made, sql), "rb") as f:
            self.assertEqual(len(f.read().split(b"\n")), 2)

    def test_a_plugin_is_the_template_without_its_build_output_with_a_new_id_and_the_values_given(self):
        icon = bytes(range(256))
        extra = dict(
            {relative: b"build output" for relative in BUILD_OUTPUT}, **{os.path.join("art", "Icon.png"): icon}
        )
        sdk = self.make_sdk(os.path.join(self.folder, "Bazaar SDK"), extra=extra)
        done = self.make_plugin(sdk, "Score Doubler", "-Author", "Jane Doe")
        teaser = "Score Doubler, a plugin for the Bazaar Multi-DLL Mod Loader."
        template = dict(tracked(PLUGIN_TEMPLATE), **{os.path.join("art", "Icon.png"): icon})
        values = {"Teaser": teaser, "Description": teaser, "Authors": "Jane Doe"}
        made = os.path.join(self.out, "ScoreDoubler")
        self.assert_made_like(template, done, made, PLUGIN_NAMES, values)
        checks = runner.read_checks(os.path.join(made, "checks.toml"))
        self.assertEqual(checks.mods, [os.path.join(made, "Build", "Score Doubler")])
        self.assertEqual([step["plugin"] for step in checks.steps if "plugin" in step], ["ScoreDoubler.dll"])

    def test_a_plugin_made_without_an_author_keeps_the_template_s_placeholder(self):
        sdk = self.make_sdk(os.path.join(self.folder, "Bazaar SDK"))
        done = self.make_plugin(sdk)
        teaser = "Score Doubler, a plugin for the Bazaar Multi-DLL Mod Loader."
        made = os.path.join(self.out, "ScoreDoubler")
        self.assert_made_like(
            tracked(PLUGIN_TEMPLATE), done, made, PLUGIN_NAMES, {"Teaser": teaser, "Description": teaser}
        )

    def altered_plugin(self, change):
        """Makes a plugin, with Jane as its author, from a stand-in SDK whose .civ5proj change has altered, checks it
        against that altered template, and returns the made .civ5proj."""
        sdk = self.make_sdk(os.path.join(self.folder, "Bazaar SDK"), change)
        done = self.make_plugin(sdk, "Score Doubler", "-Author", "Jane")
        template = files_of(os.path.join(sdk, "plugin-template"))
        teaser = "Score Doubler, a plugin for the Bazaar Multi-DLL Mod Loader."
        values = {"Teaser": teaser, "Description": teaser, "Authors": "Jane"}
        self.assert_made_like(template, done, os.path.join(self.out, "ScoreDoubler"), PLUGIN_NAMES, values)
        with open(os.path.join(self.out, "ScoreDoubler", "mod", "ScoreDoubler.civ5proj"), "rb") as f:
            return f.read()

    def test_a_project_saved_with_a_byte_order_mark_crlf_a_lone_cr_and_other_spellings_keeps_every_other_byte(self):
        def odd(data):
            data = replace_once(BOM + data.replace(b"\n", b"\r\n"), b"\r\n    <Teaser>", b"\r    <Teaser>")
            return replace_once(data, b"</Authors>", b"</Authors>\r\n    <Spare a='it&apos;s'/>")

        data = self.altered_plugin(odd)
        self.assertTrue(data.startswith(BOM))

    def test_an_empty_setting_is_filled_in_place_and_any_other_element_of_the_same_name_is_left(self):
        def emptied(data):
            start, end = setting_texts(data, ["Description"])["Description"]
            data = data[:start] + b"\n    " + data[end:]
            data = replace_once(data, b"</Description>", b"</Description>\n    <Description>Second</Description>")
            data = replace_once(data, b"<Authors>Your name</Authors>", b"<Authors></Authors>")
            early = b"<ItemGroup><Content><Description>Early</Description></Content></ItemGroup>\n  <PropertyGroup>"
            later = b"  <PropertyGroup><Authors>Later</Authors></PropertyGroup>\n"
            content = b"  <ItemGroup><Content><Description>Kept</Description></Content></ItemGroup>\n"
            data = replace_once(data, b"<PropertyGroup>", early)
            return replace_once(data, b"</Project>", later + content + b"</Project>")

        data = self.altered_plugin(emptied)
        for kept in (
            b"<Description>Early</Description>",
            b"<Description>Second</Description>",
            b"<Authors>Later</Authors>",
            b"<Description>Kept</Description>",
        ):
            self.assertIn(kept, data)

    def test_a_self_closed_setting_stops_only_when_it_is_to_be_set(self):
        sdk = self.make_sdk(
            os.path.join(self.folder, "Bazaar SDK"),
            lambda data: data.replace(b"<Authors>Your name</Authors>", b"<Authors />"),
        )
        done = self.make_plugin(sdk, "Score Doubler", "-Author", "Jane")
        self.assertEqual(done.returncode, 1)
        self.assertIn("<Authors />", done.stderr)
        self.assertEqual(os.listdir(self.out), [])
        self.assertEqual(self.make_plugin(sdk).returncode, 0)

    def test_a_project_the_script_cannot_edit_stops_and_leaves_nothing_behind(self):
        cases = [
            (lambda data: data.replace(b"</Guid>", b"</Guid><Guid>x</Guid>"), "Expected one <Guid>"),
            (lambda data: data.replace(b"Teaser>", b"Tagline>"), "No <Teaser>"),
            (lambda data: data.replace(b"</Teaser>", b""), "not valid XML"),
        ]
        for number, (change, message) in enumerate(cases):
            sdk = self.make_sdk(os.path.join(self.folder, "SDK %d" % number), change)
            done = self.make_plugin(sdk)
            self.assertEqual(done.returncode, 1, message)
            self.assertIn(message, done.stderr)
            self.assertEqual(os.listdir(self.out), [], message)

    def test_a_folder_that_already_exists_is_refused_and_left_as_it_was(self):
        sdk = self.make_sdk(os.path.join(self.folder, "Bazaar SDK"))
        for script, args, folder in [
            (NEW_DLL_PLUGIN, ["-Sdk", sdk], "ScoreDoubler"),
            (NEW_LUA_MOD, ["-Options", "none"], "ScoreDoubler"),
        ]:
            keep = os.path.join(self.out, folder, "keep.txt")
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            open(keep, "w").close()
            done = self.run_script(script, "-DisplayName", "Score Doubler", "-Destination", self.out, *args)
            self.assertEqual(done.returncode, 1, script)
            self.assertIn("already exists", done.stderr)
            self.assertEqual(os.listdir(os.path.join(self.out, folder)), ["keep.txt"])

    def test_names_and_texts_that_would_break_the_build_windows_or_the_xml_are_refused(self):
        sdk = self.make_sdk(os.path.join(self.folder, "Bazaar SDK"))
        cases = [
            (NEW_DLL_PLUGIN, ["-DisplayName", "Score, Doubler"], "may use only"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "Score Doubler."], "must not end with a dot"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "Bad & Name"], "may use only"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "CON"], "keeps the name"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "LPT3"], "keeps the name"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "con.x"], "keeps the name"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "Com 1"], "keeps the name 'Com1'"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "My Template Plugin"], "template's own name"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "3D Maps"], "must start with a letter"),
            (NEW_DLL_PLUGIN, ["-DisplayName", "Maps", "-Description", "Café"], "plain ASCII"),
            (NEW_LUA_MOD, ["-DisplayName", "My Template Lua Mod", "-Options", "none"], "template's own name"),
        ]
        for script, args, message in cases:
            extra = ["-Sdk", sdk] if script == NEW_DLL_PLUGIN else []
            done = self.run_script(script, *args, "-Destination", self.out, *extra)
            self.assertEqual(done.returncode, 1, args)
            self.assertIn(message, done.stderr, args)
        self.assertEqual(os.listdir(self.out), [])
        named = self.run_script(
            NEW_DLL_PLUGIN, "-DisplayName", "3D Maps", "-FileName", "ThreeDMaps", "-Sdk", sdk, "-Destination", self.out
        )
        self.assertEqual(named.returncode, 0, named.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.out, "ThreeDMaps")))

    def test_the_sdk_comes_from_sdk_or_bazaar_sdk_and_must_be_one(self):
        sdk = self.make_sdk(os.path.join(self.folder, "Bazaar SDK"))
        done = self.run_script(NEW_DLL_PLUGIN, "-DisplayName", "Score Doubler", "-Destination", self.out)
        self.assertIn("Set BAZAAR_SDK", done.stderr)
        empty, half = os.path.join(self.folder, "Empty"), os.path.join(self.folder, "Half SDK")
        os.makedirs(empty)
        os.makedirs(half)
        open(os.path.join(half, "CivPlugin.vsprops"), "w").close()
        for folder in (empty, half):
            done = self.make_plugin(folder)
            self.assertIn("is not a Bazaar SDK folder", done.stderr, folder)
        self.assertEqual(os.listdir(self.out), [])
        env = dict(self.env, BAZAAR_SDK=sdk)
        done = self.run_script(
            NEW_DLL_PLUGIN, "-DisplayName", "Score Doubler", "-Destination", "out", cwd=self.folder, env=env
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.out, "ScoreDoubler")))

    def test_only_the_repository_s_own_sdk_build_is_refused_as_a_destination(self):
        repository = os.path.join(self.folder, "repo", "sdk")
        built = self.make_sdk(os.path.join(repository, REPOSITORY_SDK))
        open(os.path.join(repository, "build_sdk.py"), "w").close()
        done = self.run_script(NEW_DLL_PLUGIN, "-DisplayName", "Inside", "-Sdk", built + "\\", "-Destination", built)
        self.assertEqual(done.returncode, 1)
        self.assertIn("deletes and rebuilds", done.stderr)
        self.assertFalse(os.path.exists(os.path.join(built, "Inside")))
        beside = built + " Plugins"
        done = self.run_script(NEW_DLL_PLUGIN, "-DisplayName", "Beside", "-Sdk", built, "-Destination", beside)
        self.assertEqual(done.returncode, 0, done.stderr)
        unzipped = self.make_sdk(os.path.join(self.folder, "Unzipped SDK"))
        done = self.run_script(NEW_DLL_PLUGIN, "-DisplayName", "Inside", "-Sdk", unzipped, "-Destination", unzipped)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_an_unknown_or_number_option_is_refused(self):
        with open(os.path.join(SKILLS, "new-lua-mod", "references", "vmc-options.txt"), encoding="utf-8") as f:
            number = next(line.split("\t")[0] for line in f if line.rstrip().endswith("\tnumber"))
        for option, message in [
            ("EVENTS_NO_SUCH_THING", "is not one of VMC's options"),
            ("events_player_turn", "is not one of VMC's options"),
            (number, "holds a number"),
        ]:
            done = self.run_script(
                NEW_LUA_MOD, "-DisplayName", "Turn Logger", "-Options", option, "-Destination", self.out
            )
            self.assertEqual(done.returncode, 1, option)
            self.assertIn(message, done.stderr)


class SharedCodeTest(unittest.TestCase):
    def test_the_scaffold_script_finds_positions_in_a_project_as_the_templates_release_script_does(self):
        def function(path, name):
            with open(path, encoding="ascii") as f:
                text = f.read()
            start = text.index("function %s(" % name)
            return text[start : text.index("\n}\n", start)]

        scaffold = os.path.join(REPO, "claude-plugin", "scripts", "scaffold.ps1")
        release = os.path.join(PLUGIN_TEMPLATE, "release.ps1")
        self.assertEqual(function(scaffold, "Get-TextOffset"), function(release, "Get-TextOffset"))


class GraderTest(unittest.TestCase):
    def test_the_new_mod_id_graders_name_their_template_s_ids(self):
        for skill, template in [("new-dll-plugin", PLUGIN_TEMPLATE), ("new-lua-mod", LUA_TEMPLATE)]:
            values = project_values(project_of(tracked(template)))
            graders = [
                os.path.join(path, name)
                for path, _, names in os.walk(os.path.join(SKILLS, skill, "evals"))
                for name in names
                if name.endswith("new-mod-id.md")
            ]
            self.assertTrue(graders, skill)
            for grader in graders:
                with open(grader, encoding="utf-8") as f:
                    text = f.read()
                self.assertIn(values["Guid"], text, grader)
                self.assertIn(values["ProjectGuid"], text, grader)


if __name__ == "__main__":
    unittest.main()
