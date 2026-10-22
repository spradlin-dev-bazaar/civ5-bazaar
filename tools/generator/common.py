import os
import re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOURCE_ROOT = os.path.join(REPO, "CvGameCoreSource")
ENGINE_DIR = os.path.join(SOURCE_ROOT, "CvGameCoreDLL_Expansion2")
VCPROJ = os.path.join(ENGINE_DIR, "CvGameCoreDLL_Expansion2.vcproj")
BUILD_DIR = os.path.join(SOURCE_ROOT, "BuildTemp", "civgen")

VS2008_INCLUDE = [
    r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\INCLUDE",
    r"C:\Program Files\Microsoft SDKs\Windows\v6.0A\include",
]

SUPPORT_INCLUDE = [
    r"CvWorldBuilderMap\include",
    r"CvGameCoreDLLUtil\include",
    r"CvLocalization\include",
    r"CvGameDatabase\include",
    r"FirePlace\include",
    r"FirePlace\include\FireWorks",
    r"ThirdPartyLibs\Lua51\include",
]

DEFINES = [
    "FXS_IS_DLL",
    "WIN32",
    "NDEBUG",
    "_WINDOWS",
    "_USRDLL",
    "CVGAMECOREDLL_EXPORTS",
    "FINAL_RELEASE",
    "_CRT_SECURE_NO_WARNINGS",
    "_MT",
    "_DLL",
    "_CPPUNWIND",
]


def engine_sources():
    """The .cpp files the vcproj compiles, as paths relative to ENGINE_DIR."""
    with open(VCPROJ, encoding="cp1252") as f:
        text = f.read()
    rels = re.findall(r'RelativePath="\.\\([^"]+\.cpp)"', text)
    return [r.replace("\\", os.sep) for r in rels]


def clang_args():
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
        os.path.join(os.path.dirname(__file__), "parse-shims", "msvc-leniency.h"),
    ]
    for d in DEFINES:
        args.append("-D" + d)
    for inc in VS2008_INCLUDE:
        args += ["-isystem", inc]
    args.append("-I" + ENGINE_DIR)
    for inc in SUPPORT_INCLUDE:
        args.append("-I" + os.path.join(SOURCE_ROOT, inc))
    return args


def is_engine_file(path):
    if not path:
        return False
    p = os.path.normcase(os.path.abspath(path))
    return p.startswith(os.path.normcase(ENGINE_DIR) + os.sep)


def rel_engine(path):
    return os.path.relpath(os.path.abspath(path), ENGINE_DIR)
