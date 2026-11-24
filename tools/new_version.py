"""The edits that release.py start makes to the files that name Bazaar's versions and mod IDs, other than VERSION,
VERSIONS.md, CivPluginApi.h and the Claude Code plugin's version."""

import os
import re
import sys
from xml.etree import ElementTree
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "generator"))

import common  # noqa: E402

COMMON_PY = common.COMMON_PY
TEMPLATES = (
    os.path.join(common.REPO, "sdk", "plugin-template"),
    os.path.join(common.REPO, "claude-plugin", "skills", "new-lua-mod", "template"),
)
TEMPLATE_PROJECTS = (
    os.path.join(TEMPLATES[0], "mod", "TemplatePlugin.civ5proj"),
    os.path.join(TEMPLATES[1], "mod", "TemplateLuaMod.civ5proj"),
)
BUILD_SCRIPTS = tuple(os.path.join(template, "bazaar-build.ps1") for template in TEMPLATES)
GUIDE = os.path.join(common.REPO, "sdk", "README.md")
MSBUILD = "{http://schemas.microsoft.com/developer/msbuild/2003}"

# Each pattern ends where the new line goes, and its first group is the file's line ending.
VERSIONS_DICT = re.compile(r"^BAZAAR_VERSIONS = \{(\r?\n)(?:    .*\r?\n)*(?=\}\r?$)", re.M)
SCRIPT_LIST = re.compile(r"^\$bazaarVersions = \[ordered\]@\{(\r?\n)(?:    '.*\r?\n)*(?=\}\r?$)", re.M)
GUIDE_TABLE = re.compile(
    r"^\| Bazaar version \| Mod ID \|(\r?\n)\|---\|---\|\r?\n(?:\| \d+\.\d+ \| `[0-9a-f-]+` \|\r?\n)*", re.M
)


def read_text(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def insert_line(path, pattern, line, what):
    """line is the new line without its line ending."""
    text = read_text(path)
    found = pattern.search(text)
    if not found:
        raise SystemExit("new_version: %s has no %s to add to" % (common.shown(path), what))
    write_text(path, text[: found.end()] + line + found.group(1) + text[found.end() :])


def add_to_bazaar_versions(bazaar_version, mod_id, on_workshop, path=None):
    line = '    "%s": BazaarVersion("%s", %s, None),' % (bazaar_version, mod_id, on_workshop)
    insert_line(path or COMMON_PY, VERSIONS_DICT, line, "BAZAAR_VERSIONS")


def add_to_build_script(bazaar_version, mod_id, path):
    insert_line(path, SCRIPT_LIST, "    '%s' = '%s'" % (bazaar_version, mod_id), "$bazaarVersions list")


def add_to_guide_table(bazaar_version, mod_id, path=None):
    insert_line(path or GUIDE, GUIDE_TABLE, "| %s | `%s` |" % (bazaar_version, mod_id), "table of mod IDs")


def set_template_dependency(mod_id, name, path):
    known = set(entry.mod_id.lower() for entry in common.BAZAAR_VERSIONS.values())
    found = [
        a
        for a in ElementTree.parse(path).getroot().iter(MSBUILD + "Association")
        if a.findtext(MSBUILD + "Type") == "Mod" and (a.findtext(MSBUILD + "Id") or "").lower() in known
    ]
    if len(found) != 1:
        raise SystemExit("new_version: %s does not depend on exactly one version of Bazaar" % common.shown(path))
    text = read_text(path)
    for tag, new in (("Id", mod_id), ("Name", name)):
        old_element = "<%s>%s</%s>" % (tag, escape(found[0].findtext(MSBUILD + tag) or ""), tag)
        if text.count(old_element) != 1:
            raise SystemExit("new_version: %s does not hold %s exactly once" % (common.shown(path), old_element))
        text = text.replace(old_element, "<%s>%s</%s>" % (tag, escape(new), tag))
    write_text(path, text)
