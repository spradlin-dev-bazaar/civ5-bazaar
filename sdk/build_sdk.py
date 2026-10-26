"""Lay out the plugin SDK from the hooked host build, then check it: make a plugin from its template with the DLL
skill's scaffold script, and release that plugin with the template's release script, against the SDK alone.

usage: build_sdk.py   (after build-hooked.cmd; the SDK goes to sdk/out/Bazaar SDK)
"""

import os
import re
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools", "generator"))

import common  # noqa: E402

PROJECT = common.engine_project()
HOST_LIB = os.path.join(common.HOST_OUTPUT, "CvGameCore_Expansion2.lib")
HOOKS_HEADER = os.path.join(PROJECT.build_dir, "sdk", "CivHooks.h")
OUT = os.path.join(HERE, "out")
# new-dll-plugin.ps1 refuses to make a plugin folder in here because this script is two folders up.
SDK = os.path.join(OUT, "Bazaar SDK")
CHECK_NAME = "TemplateCheck"
TEMPLATE_CHECK = os.path.join(OUT, CHECK_NAME)
NEW_DLL_PLUGIN = os.path.join(common.REPO, "claude-plugin", "skills", "new-dll-plugin", "scripts", "new-dll-plugin.ps1")

# The generator points includes that leave the engine folder at the originals on this machine, and marks where each
# header's own text starts with a #line naming the original. Neither may reach another machine.
PINNED_INCLUDE = re.compile(r'^(\s*#\s*include\s*")%s\\([^"]+)"' % re.escape(common.SOURCE_ROOT), re.M)
LINE_DIRECTIVE = re.compile(r"^#line \d+ .*\r?\n", re.M)

VSPROPS = """<?xml version="1.0" encoding="Windows-1252"?>
<VisualStudioPropertySheet
	ProjectType="Visual C++"
	Version="8.00"
	Name="CivPlugin"
	>
	<Tool
		Name="VCCLCompilerTool"
		AdditionalOptions="/MP /wd4251 /wd4275"
		Optimization="3"
		InlineFunctionExpansion="2"
		EnableIntrinsicFunctions="true"
		OmitFramePointers="true"
		AdditionalIncludeDirectories="{includes}"
		PreprocessorDefinitions="{defines}"
		ExceptionHandling="1"
		RuntimeLibrary="2"
		BufferSecurityCheck="false"
		EnableFunctionLevelLinking="true"
		FloatingPointModel="1"
		WarningLevel="3"
		DebugInformationFormat="3"
	/>
	<Tool
		Name="VCLinkerTool"
		AdditionalDependencies="{libs}"
		AdditionalLibraryDirectories="&quot;$(BAZAAR_SDK)\\lib&quot;"
		IgnoreDefaultLibraryNames="libcmt"
		GenerateDebugInformation="true"
		SubSystem="2"
		OptimizeReferences="2"
		EnableCOMDATFolding="2"
		TargetMachine="1"
	/>
</VisualStudioPropertySheet>
"""


def copy_engine_headers(target):
    for dirpath, _, filenames in os.walk(PROJECT.mirror_dir):
        for name in filenames:
            if not name.lower().endswith((".h", ".inl")):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), PROJECT.mirror_dir)
            original_dir = os.path.dirname(os.path.join(PROJECT.root, rel))
            with open(os.path.join(dirpath, name), "rb") as f:
                text = f.read().decode("cp1252")

            def unpin(m):
                return m.group(1) + os.path.relpath(os.path.join(common.SOURCE_ROOT, m.group(2)), original_dir) + '"'

            text = LINE_DIRECTIVE.sub("", PINNED_INCLUDE.sub(unpin, text))
            os.makedirs(os.path.dirname(os.path.join(target, rel)), exist_ok=True)
            with open(os.path.join(target, rel), "wb") as f:
                f.write(text.encode("cp1252"))


def write_vsprops(include_dirs):
    """The host build's compiler and linker settings, with paths inside the SDK."""
    includes = ";".join('"$(BAZAAR_SDK)\\%s"' % d for d in include_dirs)
    libs = " ".join([os.path.basename(lib) for lib in [HOST_LIB] + common.SUPPORT_LIBS] + ["winmm.lib"])
    values = dict(includes=includes, defines=";".join(common.PLUGIN_DEFINES), libs=libs)
    with open(os.path.join(SDK, "CivPlugin.vsprops"), "w", encoding="cp1252", newline="\r\n") as f:
        f.write(VSPROPS.format(**dict((k, escape(v, {'"': "&quot;"})) for k, v in values.items())))


def lay_out():
    include = os.path.join(SDK, "include")
    engine = os.path.basename(PROJECT.root)
    copy_engine_headers(os.path.join(include, engine))
    for inc in common.SUPPORT_INCLUDE:
        shutil.copytree(os.path.join(common.SOURCE_ROOT, inc), os.path.join(include, inc), dirs_exist_ok=True)
    shutil.copy(os.path.join(common.HOST_DIR, "CivPluginApi.h"), include)
    shutil.copy(HOOKS_HEADER, include)
    lib = os.path.join(SDK, "lib")
    os.makedirs(lib)
    for path in [HOST_LIB] + [os.path.join(common.SOURCE_ROOT, p) for p in common.SUPPORT_LIBS]:
        shutil.copy(path, lib)
    write_vsprops(["include", "include\\" + engine] + ["include\\" + inc for inc in common.SUPPORT_INCLUDE])
    shutil.copytree(os.path.join(HERE, "plugin-template"), os.path.join(SDK, "plugin-template"))
    for name in ("README.md", "hand-placed-hooks.md"):
        shutil.copy(os.path.join(HERE, name), SDK)
    for path in (common.LICENSE, common.NOTICE):
        shutil.copy(path, SDK)


def files_naming_this_machine(folder):
    needles = [common.REPO, common.REPO.replace("\\", "/"), common.REPO.replace("\\", "\\\\")]
    needles = [n.lower().encode("cp1252") for n in needles]
    found = []
    for dirpath, _, filenames in os.walk(folder):
        for name in filenames:
            with open(os.path.join(dirpath, name), "rb") as f:
                data = f.read().lower()
            if any(n in data for n in needles):
                found.append(os.path.relpath(os.path.join(dirpath, name), folder))
    return found


def main(args):
    if args:
        print(__doc__)
        return 1
    for path in (HOST_LIB, HOOKS_HEADER):
        if not os.path.exists(path):
            print("%s does not exist; run build-hooked.cmd first." % path)
            return 1
    for folder in (SDK, TEMPLATE_CHECK):
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    lay_out()
    leaks = files_naming_this_machine(SDK)
    if leaks:
        print("These SDK files name folders on this machine: %s" % ", ".join(leaks))
        return 1
    scaffold = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", NEW_DLL_PLUGIN]
    scaffold += ["-DisplayName", "Template Check", "-FileName", CHECK_NAME, "-Sdk", SDK, "-Destination", OUT]
    scaffold += ["-Author", "Bazaar"]
    env = dict(os.environ, BAZAAR_SDK=SDK)
    if (
        subprocess.run(scaffold).returncode != 0
        or subprocess.run(["cmd", "/c", os.path.join(TEMPLATE_CHECK, "release.cmd")], env=env).returncode != 0
    ):
        print("The template plugin, made with the DLL skill's scaffold script, did not release against the SDK.")
        return 1
    print(SDK)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
