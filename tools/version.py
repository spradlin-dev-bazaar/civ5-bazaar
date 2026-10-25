"""The version of a Bazaar release, kept in VERSION at the top of the repository, and the numbers that must follow it:
the plugin API version in CivPluginApi.h and the Claude plugin's version.

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
NUMBER = "(?:0|[1-9][0-9]*)"
FORMAT = re.compile(r"release (%s\.%s\.%s)\nmod ([1-9][0-9]*)\n?" % (NUMBER, NUMBER, NUMBER))

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


def check():
    version = read()
    return version, disagreements(version, layouts.api_version(), plugin_version())


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
