"""Build settings shared by the generator and the scripts that build against its output."""

import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SOURCE_ROOT = os.path.join(REPO, "CvGameCoreSource")
ENGINE_DIR = os.path.join(SOURCE_ROOT, "CvGameCoreDLL_Expansion2")
VCPROJ = os.path.join(ENGINE_DIR, "CvGameCoreDLL_Expansion2.vcproj")
BUILD_DIR = os.path.join(SOURCE_ROOT, "BuildTemp", "civgen")
HOST_DIR = os.path.join(REPO, "host")
HOST_OUTPUT = os.path.join(BUILD_DIR, "src", "BuildOutput", "VS2008_ModWin32")
HOST_DLL = os.path.join(HOST_OUTPUT, "CvGameCore_Expansion2.dll")
LICENSE = os.path.join(REPO, "LICENSE")
# From this release on, what plugins use is frozen: removing or changing any of it needs a new major version. Bazaar's
# loader has its own copy in host/CivHostRuntime.h, which a test keeps equal.
FREEZE = (0, 5)
FREEZE_SHOWN = "%d.%d" % FREEZE
NOTICE = os.path.join(REPO, "NOTICE")

VS2008_INCLUDE = [
    r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\INCLUDE",
    r"C:\Program Files\Microsoft SDKs\Windows\v6.0A\include",
]
VSVARS = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat"

SUPPORT_INCLUDE = [
    r"CvWorldBuilderMap\include",
    r"CvGameCoreDLLUtil\include",
    r"CvLocalization\include",
    r"CvGameDatabase\include",
    r"FirePlace\include",
    r"FirePlace\include\FireWorks",
    r"ThirdPartyLibs\Lua51\include",
]

SUPPORT_LIBS = [
    r"CvWorldBuilderMap\lib\CvWorldBuilderMapWin32.lib",
    r"CvGameCoreDLLUtil\lib\CvGameCoreDLLUtilWin32.lib",
    r"CvLocalization\lib\CvLocalizationWin32.lib",
    r"CvGameDatabase\lib\CvGameDatabaseWin32.lib",
    r"FirePlace\lib\FireWorksWin32.lib",
    r"FirePlace\lib\FLuaWin32.lib",
    r"ThirdPartyLibs\Lua51\lib\lua51_Win32.lib",
]

# The engine's precompiled header sets these; every file and DLL that shares std types with it must match.
LAYOUT_DEFINES = ["_SECURE_SCL=0", "_HAS_ITERATOR_DEBUGGING=0"]

ENGINE_DEFINES = ["FXS_IS_DLL", "WIN32", "NDEBUG", "_WINDOWS", "_USRDLL", "FINAL_RELEASE", "_CRT_SECURE_NO_WARNINGS"]

# What cl defines by itself for /MD and /EHsc.
CL_DEFINES = ["_MT", "_DLL", "_CPPUNWIND"]

# Clang reads the engine as the host build compiles it, with its export define. The layout defines are set here too,
# since parse-shims\msvc-leniency.h reads standard headers before CvGameCoreDLLPCH.h can set them.
CLANG_DEFINES = ENGINE_DEFINES + ["CVGAMECOREDLL_EXPORTS"] + LAYOUT_DEFINES + CL_DEFINES

PLUGIN_DEFINES = ["CIV_HOST_API=__declspec(dllimport)"] + LAYOUT_DEFINES + ENGINE_DEFINES

# The host's mod, which the plugin and Lua mod templates depend on.
HOST_MOD_ID = "b829cadb-b570-46c5-a0ba-419434eb6398"
HOST_MOD_NAME = "Bazaar Multi-DLL Mod Loader"


class Project:
    """A tree of C++ sources to hook: the engine, or a small test fixture."""

    def __init__(self, root, sources, include_dirs, build_dir, registry, plugin_include, vcproj=None):
        self.root = os.path.abspath(root)
        self.sources = sources
        self.include_dirs = include_dirs
        self.build_dir = build_dir
        self.registry = registry
        self.vcproj = vcproj
        # The header CivHooks.h includes for the types its hook points take.
        self.plugin_include = plugin_include

    @property
    def mirror_root(self):
        return os.path.join(self.build_dir, "src")

    @property
    def mirror_dir(self):
        return os.path.join(self.mirror_root, os.path.basename(self.root))

    def contains(self, path):
        return under(path, [self.root])

    def clang_args(self):
        return clang_arguments(CLANG_DEFINES, self.include_dirs)


def under(path, folders):
    if not path:
        return False
    path = os.path.normcase(os.path.abspath(path))
    return any(path.startswith(os.path.normcase(os.path.abspath(folder)) + os.sep) for folder in folders)


def clang_arguments(defines, include_dirs):
    args = [
        "-x",
        "c++",
        "--target=i686-pc-windows-msvc",
        "-fms-extensions",
        "-fms-compatibility",
        "-fms-compatibility-version=15.00",
        "-fdelayed-template-parsing",
        "-nostdlibinc",
        "-Wno-everything",
        "-ferror-limit=0",
        "-include",
        os.path.join(HERE, "parse-shims", "msvc-leniency.h"),
    ]
    args += ["-D" + d for d in defines]
    for inc in VS2008_INCLUDE:
        args += ["-isystem", inc]
    args += ["-I" + inc for inc in include_dirs]
    return args


def known_errors(path=os.path.join(HERE, "known-parse-errors.txt")):
    """(file name, message, line text) of each parse error known to be harmless."""
    entries = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t", 2)
            if len(fields) != 3:
                raise RuntimeError("%s: %r needs a file name, a message and a line's text between tabs" % (path, line))
            entries.add((fields[0], fields[1], even_spaces(fields[2])))
    return entries


def even_spaces(text):
    return re.sub(r"[ \t]+", " ", text).strip(" ")


def source_line(path, number):
    """A line of a file, numbered as clang numbers it, with its spaces evened out; empty past the end."""
    with open(path, "rb") as f:
        # Not str.splitlines, which also breaks at form feeds and other characters clang does not count as line ends.
        lines = re.split(rb"\r\n|\r|\n", f.read())
    if not 0 < number <= len(lines):
        return ""
    return even_spaces(lines[number - 1].decode("cp1252", errors="replace"))


def known_error(known, path, number, message):
    """Whether known lists this error: its file's name, its message and the text of its line."""
    return (os.path.basename(path), message, source_line(path, number)) in known


def shown(path):
    try:
        return os.path.relpath(path, REPO)
    except ValueError:
        return path


def vs_env():
    out = subprocess.run('"%s" >nul && set' % VSVARS, shell=True, capture_output=True, text=True).stdout
    env = dict(os.environ)
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            # os.environ's keys are upper case, while cmd started from PowerShell prints "Path=": two keys would keep
            # the PATH without Visual C++.
            env[k.upper()] = v
    return env


def engine_sources():
    """The .cpp files the vcproj compiles, as paths relative to ENGINE_DIR."""
    with open(VCPROJ, encoding="cp1252") as f:
        text = f.read()
    rels = re.findall(r'RelativePath="\.\\([^"]+\.cpp)"', text)
    return [r.replace("\\", os.sep) for r in rels]


def engine_project():
    includes = [ENGINE_DIR] + [os.path.join(SOURCE_ROOT, inc) for inc in SUPPORT_INCLUDE]
    return Project(
        ENGINE_DIR,
        engine_sources(),
        includes,
        BUILD_DIR,
        os.path.join(HERE, "hook-ids.txt"),
        "CvGameCoreDLLPCH.h",
        VCPROJ,
    )


def frozen(numbers):
    """Whether a version, as (major, minor) or longer, is at or past the freeze."""
    return tuple(numbers[:2]) >= FREEZE
