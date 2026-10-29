"""The checker as the plugin template and the Lua mod template ship it: the same files as tools/bazaar_check, the same
check.cmd, and a checks.toml that checks what its template builds and writes."""

import filecmp
import glob
import os
import re
import shutil
import subprocess
import tempfile
import sys
import unittest
from xml.etree import ElementTree

from fakes import HERE

from bazaar_check import runner

REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
SOURCE = os.path.join(REPO, "tools", "bazaar_check")
TEMPLATES = [
    os.path.join(REPO, "sdk", "plugin-template"),
    os.path.join(REPO, "claude-plugin", "skills", "new-lua-mod", "template"),
]


def project_name(template):
    """The mod's name, which build.cmd gives its folder in Build."""
    (project,) = glob.glob(os.path.join(template, "mod", "*.civ5proj"))
    return next(e.text for e in ElementTree.parse(project).iter() if e.tag.rsplit("}", 1)[-1] == "Name")


def source(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def files_in(folder):
    found = []
    for path, folders, names in os.walk(folder):
        folders[:] = [name for name in folders if name != "__pycache__"]
        found += [os.path.relpath(os.path.join(path, name), folder) for name in names]
    return sorted(found)


class TemplatesTest(unittest.TestCase):
    def test_each_template_s_checker_is_tools_bazaar_check(self):
        for template in TEMPLATES:
            copy = os.path.join(template, "bazaar_check")
            with self.subTest(template=template):
                self.assertEqual(files_in(copy), files_in(SOURCE), "copy tools/bazaar_check into %s again" % copy)
                different = [
                    name
                    for name in files_in(SOURCE)
                    if not filecmp.cmp(os.path.join(SOURCE, name), os.path.join(copy, name), shallow=False)
                ]
                self.assertEqual(different, [], "copy tools/bazaar_check into %s again" % copy)

    def test_both_templates_have_the_same_check_cmd(self):
        first, second = (os.path.join(template, "check.cmd") for template in TEMPLATES)
        self.assertTrue(filecmp.cmp(first, second, shallow=False))

    def check_cmd(self, build="echo built", python=True):
        """check.cmd run from a folder with brackets in its name, with a stub build.cmd and a checks.toml the checker
        refuses at once, finding Python only as a .bat, as pyenv-win's python is."""
        with tempfile.TemporaryDirectory() as folder:
            template = os.path.join(folder, "My Mod (x86)")
            shutil.copytree(TEMPLATES[0], template, ignore=shutil.ignore_patterns("__pycache__"))
            with open(os.path.join(template, "build.cmd"), "w") as f:
                f.write("@echo off\n%s\n" % build)
            with open(os.path.join(template, "checks.toml"), "w") as f:
                f.write("mods = []\n")
            shims = os.path.join(folder, "shims")
            os.makedirs(shims)
            with open(os.path.join(shims, "python.bat"), "w") as f:
                f.write('@"%s" %%*\n' % sys.executable)
            path = [shims] if python else []
            env = dict(os.environ, PATH=os.pathsep.join(path + [os.path.join(os.environ["SystemRoot"], "System32")]))
            done = subprocess.run(
                ["cmd", "/c", os.path.join(template, "check.cmd")], capture_output=True, text=True, env=env
            )
            left = os.listdir(os.path.join(template, "bazaar_check"))
        return done.returncode, [line.rstrip() for line in done.stdout.splitlines()], left

    def test_check_cmd_builds_then_runs_the_checker_beside_it_and_passes_on_its_result(self):
        code, printed, left = self.check_cmd()
        self.assertEqual((code, printed), (1, ["built", "checks.toml: the checks name no mods"]))
        self.assertNotIn("__pycache__", left)

    def test_check_cmd_stops_before_building_without_python(self):
        code, printed, _ = self.check_cmd(python=False)
        self.assertEqual((code, printed), (1, ["The checks need Python 3.11 or newer: install it from python.org."]))

    def test_check_cmd_stops_when_the_build_fails(self):
        code, printed, _ = self.check_cmd(build="exit /b 3")
        self.assertEqual((code, printed), (1, []))

    def test_each_template_s_checks_file_checks_the_folder_its_build_makes(self):
        for template in TEMPLATES:
            with self.subTest(template=template):
                checks = runner.read_checks(os.path.join(template, "checks.toml"))
                self.assertEqual(checks.mods, [os.path.join(template, "Build", project_name(template))])

    def test_the_plugin_template_s_checks_find_what_the_template_writes(self):
        template = TEMPLATES[0]
        cpp = source(template, "src", "TemplatePlugin.cpp")
        (turn_format,) = re.findall(r'Log\("(%s starts turn %d [^"]*)"', cpp)
        steps = runner.read_checks(os.path.join(template, "checks.toml")).steps
        (turn,) = [step["has"] for step in steps if "log" in step]
        self.assertRegex("[Template Plugin] " + turn_format % ("America", 1, 0, 1, 0), turn)
        self.assertNotRegex("[Template Plugin] " + turn_format % ("America", 11, 0, 11, 0), turn)
        (plugin,) = [step["plugin"] for step in steps if "plugin" in step]
        self.assertIn("('%s')" % plugin, source(template, "mod", "TemplatePlugin.sql"))
        (lua,) = [step["lua"] for step in steps if "lua" in step]
        (function,) = re.findall(r'lua_setfield\(L, -2, "(\w+)"\)', cpp)
        self.assertEqual(lua, "Game.%s()" % function)

    def test_the_lua_template_s_check_finds_the_line_the_template_prints(self):
        template = TEMPLATES[1]
        lua = source(template, "mod", "TemplateLuaMod.lua")
        before, after = re.search(r'print\("([^"]*)" \.\. iPlayer \.\. "([^"]*)"\)', lua).groups()
        (log,) = [step for step in runner.read_checks(os.path.join(template, "checks.toml")).steps if "log" in step]
        self.assertEqual(log["log"], "Lua.log")
        self.assertRegex("[1234.5] TemplateLuaMod: " + before + "0" + after, log["has"])


if __name__ == "__main__":
    unittest.main()
