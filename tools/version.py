"""The version of a Bazaar release, kept in VERSION at the top of the repository, and the numbers that must follow it:
the plugin API version in CivPluginApi.h, the Claude plugin's version and the newest row of VERSIONS.md's list of
mod versions.

    python tools/version.py
"""

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "generator"))

import common  # noqa: E402
import layouts  # noqa: E402

VERSION_FILE = os.path.join(common.REPO, "VERSION")
PLUGIN_JSON = os.path.join(common.REPO, "claude-plugin", ".claude-plugin", "plugin.json")
VERSIONS_LIST = os.path.join(common.REPO, "VERSIONS.md")
NUMBER = "(?:0|[1-9][0-9]*)"
FORMAT = re.compile(r"release (%s\.%s\.%s)\nmod ([1-9][0-9]*)\n?" % (NUMBER, NUMBER, NUMBER))
VERSIONS_ROW = re.compile(r"^\| ([1-9][0-9]*) \| (%s\.%s\.%s) \|(\r?)$" % (NUMBER, NUMBER, NUMBER), re.M)

Version = collections.namedtuple("Version", "release mod")


def parse(text, name):
    found = FORMAT.fullmatch(text)
    if not found:
        raise SystemExit(
            "version: %s is not 'release <major.minor.patch>' and 'mod <whole number>' on two lines; it reads %r"
            % (name, text)
        )
    return Version(found.group(1), int(found.group(2)))


def read(path=VERSION_FILE):
    with open(path, encoding="utf-8-sig") as f:
        return parse(f.read(), common.shown(path))


def numbers(release):
    return tuple(int(n) for n in release.split("."))


def write(version, path=VERSION_FILE):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("release %s\nmod %d\n" % version)


def plugin_version(path=PLUGIN_JSON):
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("version", "missing")


def set_plugin_version(release, path=PLUGIN_JSON):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    text, count = re.subn(r'("version"\s*:\s*")[^"]*"', r'\g<1>%s"' % release, text)
    if count != 1:
        raise SystemExit('version: %s does not have exactly one "version"' % common.shown(path))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def listed_versions(path=VERSIONS_LIST):
    """VERSIONS.md's rows, newest first, as Versions."""
    with open(path, encoding="utf-8") as f:
        return [Version(release, int(mod)) for mod, release, _ in VERSIONS_ROW.findall(f.read())]


def add_listed_version(version, path=VERSIONS_LIST):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    newest = VERSIONS_ROW.search(text)
    if not newest:
        raise SystemExit("version: %s has no mod versions to add to" % common.shown(path))
    row = "| %d | %s |%s\n" % (version.mod, version.release, newest.group(3))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text[: newest.start()] + row + text[newest.start() :])


def disagreements(version, api, plugin):
    """api is CivPluginApi.h's (major, minor), plugin the Claude plugin's version."""
    major, minor, _ = numbers(version.release)
    found = []
    if api != (major, minor):
        found.append(
            "the plugin API version in %s is %d.%d, not %d.%d"
            % (common.shown(layouts.API_HEADER), api[0], api[1], major, minor)
        )
    if plugin != version.release:
        found.append(
            "the Claude plugin's version in %s is %s, not %s" % (common.shown(PLUGIN_JSON), plugin, version.release)
        )
    return found


def bazaar_version(release):
    """The version of Bazaar that a release belongs to: its first two numbers, such as 0.5."""
    return "%d.%d" % numbers(release)[:2]


def bazaar_made_in(version, listed):
    """The release that made the Bazaar that version has: the listed release with version's mod version, or version
    itself. listed may already hold rows for releases after version."""
    return next((row.release for row in listed if row.mod == version.mod), version.release)


def kept_bazaar(version, listed):
    """The earlier release whose Bazaar version keeps, or None. A release that keeps one keeps its mod version and adds
    no row to VERSIONS.md, so the newest row names an earlier release with the same mod version. listed is what
    listed_versions returns."""
    if listed and listed[0].mod == version.mod and numbers(listed[0].release) < numbers(version.release):
        return listed[0].release
    return None


def listed_disagreements(version, listed):
    """listed is what listed_versions returns."""
    if not listed:
        return ["%s lists no mod versions" % common.shown(VERSIONS_LIST)]
    if listed[0] != version and kept_bazaar(version, listed) is None:
        return [
            "the newest row of %s is mod version %d, Bazaar %s, not mod version %d, Bazaar %s"
            % (common.shown(VERSIONS_LIST), listed[0].mod, listed[0].release, version.mod, version.release)
        ]
    return []


def check():
    version = read()
    found = disagreements(version, layouts.api_version(), plugin_version())
    return version, found + listed_disagreements(version, listed_versions())


def main():
    version, found = check()
    for problem in found:
        print("version: " + problem)
    if found:
        return 1
    print("Bazaar %s, mod version %d" % version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
