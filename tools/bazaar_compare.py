"""Whether a release can keep an earlier release's Bazaar: Bazaar's code changed in nothing but comments since then, and
today's files would package that Bazaar the same way. release.py's --same-bazaar asks it."""

import glob
import io
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from xml.etree import ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "generator"))

import common  # noqa: E402
import mods  # noqa: E402
from bazaar_check import files  # noqa: E402

# What build-hooked.cmd builds Bazaar's DLL from. The other files in its package are compared as packaged.
CODE = ("CvGameCoreSource", "host", "tools/generator", "tools/shims", "build-hooked.cmd")
C_SOURCES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl")
C_PIECES = re.compile(
    r"""(//(?:\\\n|[^\n])*|/\*.*?\*/)|("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\s+)|([^"'/\s]+|.)""", re.S
)


def c_text(text):
    """C or C++ with each run of comments and spaces made one space, or one line break if it held one, since a
    preprocessor line ends at its line break. String and character literals stay exactly as they are."""
    out, gap = [], ""
    for comment, literal, space, other in C_PIECES.findall(text):
        if comment or space:
            gap = "\n" if "\n" in space or gap == "\n" else " "
            continue
        if gap and out:
            out.append(gap)
        gap = ""
        out.append(literal or other)
    return "".join(out)


def comparable(path, data):
    """A code file's bytes, made comparable so that a change only to its comments, blank lines or the width of its
    spacing is no change. A Python file that does not tokenize is compared as text, and any other file as text too,
    since a cmd comment can swallow the line after it."""
    text = data.decode("latin-1").replace("\r\n", "\n")
    if path.lower().endswith(C_SOURCES):
        return c_text(text)
    if path.lower().endswith(".py"):
        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            return [(t.type, t.string) for t in tokens if t.type not in (tokenize.COMMENT, tokenize.NL)]
        except (tokenize.TokenError, SyntaxError):
            return text
    return text


def git_show(tag, rel):
    return subprocess.run(["git", "show", "%s:%s" % (tag, rel)], cwd=common.REPO, capture_output=True)


def file_at(tag, rel):
    """A file's bytes as tag left it, or None if it was not there."""
    done = git_show(tag, rel)
    return done.stdout if done.returncode == 0 else None


def changed_code(tag, names):
    """Of these files, named as git names them, those that differ from tag in more than comments and spacing."""
    changed = []
    for rel in names:
        then, path = file_at(tag, rel), os.path.join(common.REPO, rel)
        now = None
        if os.path.isfile(path):
            with open(path, "rb") as f:
                now = f.read()
        if then is None or now is None or comparable(rel, then) != comparable(rel, now):
            changed.append(rel)
    return changed


def folder_differences(then, now):
    return sorted(set(files.different_files(then, now)) | set(files.different_files(now, then)))


def package_changes(host_package, bootstrap_package):
    """What today's files would package differently from these Bazaar and VMC Bootstrap packages, given their own DLL,
    mod version and description. Raises files.CheckError for a package that cannot be read."""
    with tempfile.TemporaryDirectory() as folder:
        then_host = files.unpack(host_package, os.path.join(folder, "then", "host"))
        then_bootstrap = files.unpack(bootstrap_package, os.path.join(folder, "then", "bootstrap"))
        modinfos = glob.glob(os.path.join(glob.escape(then_host), "*.modinfo"))
        try:
            (root,) = [ElementTree.parse(modinfo).getroot() for modinfo in modinfos]
            mod_version = int(root.get("version"))
        except (ValueError, TypeError, ElementTree.ParseError):
            raise files.CheckError("%s holds no mod description that can be read" % host_package)
        if root.get("id") != mods.HOST_ID:
            raise files.CheckError("%s does not hold Bazaar's mod" % host_package)
        now_host, now_bootstrap = mods.write_dll_mod(
            os.path.join(folder, "now"),
            mods.HOST_NAME,
            mods.HOST_ID,
            mods.HOST_TEASER,
            os.path.join(then_host, "CvGameCore_Expansion2.dll"),
            host_screens=True,
            version=mod_version,
            description=root.findtext("Properties/Description"),
        )
        return ["Bazaar's mod: " + rel for rel in folder_differences(then_host, now_host)] + [
            "the VMC Bootstrap: " + rel for rel in folder_differences(then_bootstrap, now_bootstrap)
        ]
