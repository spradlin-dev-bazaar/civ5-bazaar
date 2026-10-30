"""Make a Bazaar release.

    python tools/release.py number [--major | --same-bazaar]
                                                   after build-hooked.cmd: the next release's number, and what changed
    python tools/release.py prepare [--major | --same-bazaar]
                                                   on main: a release branch with the new numbers and saved lists
    python tools/release.py build [--trial]        on main, once the release branch has merged: the release's files
    python tools/release.py check [--trial]        the release's files in the game, which this starts and plays
    python tools/release.py publish --notes FILE [--no-check]
                                                   tag the commit the files were built from and draft its GitHub release
    python tools/release.py workshop               once the GitHub release is published: Bazaar's mod to the Workshop

--major starts a new major version, such as 1.0.0. --same-bazaar makes a release that keeps the last release's Bazaar
and its mod version, and ships only the SDK and, if they changed, the docs; it stops if Bazaar's code changed in more
than comments since that Bazaar, or if today's files would package it differently, and downloads that Bazaar's
release files from GitHub into dist when they are not there. build --trial runs on any branch,
leaves the release marks out of the docs, gives Bazaar's mod the test version 900, and writes to dist/trial, which
publish never uses; check --trial checks those files. publish needs the files to have passed check since they were
built, unless --no-check, for a release that only changes the docs: the SDK holds the checker, which only release.py
check runs in the game.
"""

import argparse
import collections
import difflib
import glob
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "generator"))
sys.path.insert(0, os.path.join(HERE, "docs"))
sys.path.insert(0, os.path.join(HERE, "..", "sdk"))
sys.path.insert(0, os.path.join(HERE, "workshop"))

import bazaar_compare  # noqa: E402
import build_docs  # noqa: E402
import build_sdk  # noqa: E402
import common  # noqa: E402
import generate  # noqa: E402
import layouts  # noqa: E402
import mods  # noqa: E402
import sync_checker  # noqa: E402
import upload  # noqa: E402
import version  # noqa: E402
from bazaar_check import files, game, runner  # noqa: E402

RELEASED = os.path.join(HERE, "released")
HOOKS_LIST = os.path.join(RELEASED, "hooks.txt")
EXPORTS_LIST = os.path.join(RELEASED, "exports.txt")
BUILD_HOOKED = os.path.join(common.REPO, "build-hooked.cmd")
STAGE = os.path.join(common.SOURCE_ROOT, "BuildTemp", "release")
DIST = os.path.join(common.REPO, "dist")
TRIAL_FOLDER = os.path.join(DIST, "trial")
BUILT_FROM = "built-from.txt"
BRANCH_PREFIX = "release-"
PART_WAY = (
    "prepare stopped part way. Before running it again, put back the files it changed with git restore :/ and delete"
    " any it added, which git status lists"
)

BOOTSTRAP_PATTERN = "Bazaar-VMC-Bootstrap-*.civ5mod"
DOCS_PATTERN = "Bazaar-docs-*.zip"
BUILD_SETTINGS = "CivPlugin.vsprops"
RUN_AGAIN = "run it without --same-bazaar"
PREPARE_AGAIN = "prepare the release again without --same-bazaar"

CHECK_FOLDER = os.path.join(tempfile.gettempdir(), "Bazaar release check")
CHECKED = "checked.txt"
TEMPLATE_LOADED = r"^Plugin Template Plugin \S+ loaded \(built for API %d\.%d\)"

EXPORT_LINE = re.compile(r"^ +\d+ +[0-9A-F]+ +[0-9A-F]{8} (\S+)", re.M)
EXPORT_COUNT = re.compile(r"^ +(\d+) number of names$", re.M)
API_VERSION_LINE = re.compile(layouts.API_NUMBER % "(?:MAJOR|MINOR)")
MAX_LISTED = 20

Difference = collections.namedtuple("Difference", "what added removed")
ReleaseFiles = collections.namedtuple("ReleaseFiles", "host bootstrap sdk docs")


def stop(message):
    raise SystemExit("release: " + message)


def say(message):
    print("release: " + message, flush=True)


def git(*args, check=True):
    done = subprocess.run(["git"] + list(args), cwd=common.REPO, capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        if not check:
            return None
        stop("git %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout.strip()


def run(what, cmd):
    say(what)
    if subprocess.run(cmd, cwd=common.REPO).returncode != 0:
        stop("%s failed" % what)


def read_text(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return f.read()


def at_tag(tag, path, encoding="utf-8"):
    rel = os.path.relpath(path, common.REPO).replace(os.sep, "/")
    done = bazaar_compare.git_show(tag, rel)
    if done.returncode != 0:
        stop("%s could not be read as it was at %s: %s" % (rel, tag, done.stderr.decode(errors="replace").strip()))
    return done.stdout.decode(encoding)


def tag_of(release):
    return "v" + release


def release_folder(release):
    return os.path.join(DIST, tag_of(release))


def tagged_commit(tag):
    return git("rev-parse", "--quiet", "--verify", "refs/tags/%s^{commit}" % tag, check=False)


def on_github(tag):
    return bool(git("ls-remote", "--tags", "origin", "refs/tags/" + tag))


def last_release():
    """The last release's tag, or None before the first release."""
    tag = layouts.last_release_tag()
    if tag is None and git("ls-remote", "--tags", "origin", "refs/tags/" + layouts.RELEASE_TAGS):
        stop("GitHub has release tags that are not here: run git fetch --tags")
    if tag is not None and not on_github(tag):
        stop(
            "the tag %s is only on this machine, left by a publish that did not finish. If main has not changed since,"
            " run publish again; otherwise delete the tag with git tag -d %s" % (tag, tag)
        )
    return tag


def require_main():
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        stop("run this on main")
    changed = git("status", "--porcelain")
    if changed:
        stop("commit or put away these changes first:\n" + changed)
    git("fetch", "--quiet", "origin", "main")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        stop("main here differs from main on GitHub: pull or push first")


def require_no_release_branch():
    branches = git("branch", "--list", BRANCH_PREFIX + "*", "--format=%(refname:short)").split()
    if branches:
        stop("the release branch %s is still here: delete it once its pull request has merged" % branches[0])


def require_numbers_agree():
    problems = version.check()[1]
    if problems:
        stop("these numbers disagree with VERSION:\n  " + "\n  ".join(problems))


def parse_list(text, name):
    lines = text.splitlines()
    head = re.fullmatch(r"release (\S+)", lines[0]) if lines else None
    if not head:
        stop("%s does not start with 'release <number>'" % name)
    return head.group(1), lines[1:]


def read_list(path):
    return parse_list(read_text(path), common.shown(path))


def write_list(path, release, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(line + "\n" for line in ["release " + release] + lines))


def saved_release():
    """The release the lists here were saved at, or None before the first release is prepared."""
    present = [path for path in (HOOKS_LIST, EXPORTS_LIST) if os.path.exists(path)]
    if not present:
        return None
    if len(present) == 1:
        (missing,) = set((HOOKS_LIST, EXPORTS_LIST)) - set(present)
        stop("%s is missing: put it back from git" % common.shown(missing))
    releases = [read_list(path)[0] for path in present]
    if releases[0] != releases[1]:
        stop("%s and %s were saved by different releases" % (common.shown(HOOKS_LIST), common.shown(EXPORTS_LIST)))
    return releases[0]


def hooks_from(text):
    return ["%d\t%s" % (hook_id, name) for name, hook_id, _ in sorted(generate.header_hooks(text), key=lambda h: h[1])]


def current_hooks():
    if not os.path.exists(build_sdk.HOOKS_HEADER):
        stop("%s does not exist: run build-hooked.cmd first" % build_sdk.HOOKS_HEADER)
    hooks = hooks_from(read_text(build_sdk.HOOKS_HEADER, "cp1252"))
    if not hooks:
        stop("%s lists no hooks" % build_sdk.HOOKS_HEADER)
    return hooks


def exports_from(text):
    names = EXPORT_LINE.findall(text)
    count = EXPORT_COUNT.search(text)
    if not names or not count or int(count.group(1)) != len(names):
        stop("dumpbin's list of the names %s exports could not be read" % common.HOST_DLL)
    return sorted(names)


def current_exports():
    if not os.path.exists(common.HOST_DLL):
        stop("%s does not exist: run build-hooked.cmd first" % common.HOST_DLL)
    env = common.vs_env()
    dumpbin = shutil.which("dumpbin", path=env.get("PATH"))
    if not dumpbin:
        stop("dumpbin was not found: is Visual C++ 2008 installed?")
    done = subprocess.run([dumpbin, "/exports", common.HOST_DLL], env=env, capture_output=True, text=True)
    if done.returncode != 0:
        stop("dumpbin failed on %s: %s" % (common.HOST_DLL, done.stdout + done.stderr))
    return exports_from(done.stdout)


def current_lists():
    return current_hooks(), current_exports()


def api_statements(text):
    """CivPluginApi.h one statement at a time, so that wrapping a line differently is no change. The API version is left
    out, since every minor release raises it."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"\\\s*\n", " ", text)
    statements, pending = [], ""
    for line in text.splitlines():
        line = " ".join(line.split())
        if line.startswith("#"):
            if not API_VERSION_LINE.match(line):
                statements.append(line)
            continue
        for piece in re.findall(r"[^;{},]+[;{},]?|[;{},]", line):
            pending = (pending + " " + piece.strip()).strip()
            if pending.endswith((";", "{", "}", ",")):
                statements.append(pending)
                pending = ""
    return statements + ([pending] if pending else [])


def difference(what, then, now):
    then, now = collections.Counter(then), collections.Counter(now)
    return Difference(what, sorted((now - then).elements()), sorted((then - now).elements()))


def ordered_difference(what, then, now):
    """For text whose order means something, such as an enum whose values follow their position."""
    added, removed = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, then, now, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            removed += then[i1:i2]
        if op in ("replace", "insert"):
            added += now[j1:j2]
    return Difference(what, added, removed)


def layout_difference(then_text, now_text):
    lost, new = layouts.compare(layouts.parse_record(then_text)[1], layouts.parse_record(now_text)[1])
    return Difference(
        "class layouts and enum values", sorted(set(key for key, _ in new)), sorted(set(key for key, _, _ in lost))
    )


def differences(tag, hooks, exports):
    def saved(path):
        return parse_list(at_tag(tag, path), "%s at %s" % (common.shown(path), tag))[1]

    api_then = api_statements(at_tag(tag, layouts.API_HEADER, "cp1252"))
    api_now = api_statements(read_text(layouts.API_HEADER, "cp1252"))
    return [
        difference("hooks", saved(HOOKS_LIST), hooks),
        difference("exported names", saved(EXPORTS_LIST), exports),
        ordered_difference(common.shown(layouts.API_HEADER), api_then, api_now),
        layout_difference(at_tag(tag, layouts.RECORD, "cp1252"), read_text(layouts.RECORD, "cp1252")),
    ]


def api_changed(diffs):
    return any(d.added or d.removed for d in diffs)


def next_version(base, diffs, major=False, same_bazaar=False):
    """The release after base, or None when only a new major version may follow it. A release with the same Bazaar keeps
    base's mod version."""
    numbers = version.numbers(base.release)
    if major:
        release = "%d.0.0" % (numbers[0] + 1)
    elif common.frozen(numbers) and any(d.removed for d in diffs):
        return None
    elif api_changed(diffs):
        release = "%d.%d.0" % (numbers[0], numbers[1] + 1)
    else:
        release = "%d.%d.%d" % (numbers[0], numbers[1], numbers[2] + 1)
    return version.Version(release, base.mod if same_bazaar else base.mod + 1)


def choose(lists=None):
    """The last release's tag, its numbers, and what this build changes since it; before the first release, no tag,
    VERSION's numbers and no differences. lists are this build's hooks and exports, read when not given."""
    tag = last_release()
    if tag is None:
        return None, version.read(), None
    hooks, exports = lists or current_lists()
    base = version.parse(at_tag(tag, version.VERSION_FILE), "VERSION at " + tag)
    return tag, base, differences(tag, hooks, exports)


def report(tag, diffs):
    say("since %s:" % tag)
    for d in diffs:
        for label, items in (("added", d.added), ("removed or changed", d.removed)):
            if items:
                print("  %s %s: %d" % (d.what, label, len(items)))
                print("".join("    %s\n" % item.replace("\t", " ") for item in items[:MAX_LISTED]), end="")
                if len(items) > MAX_LISTED:
                    print("    and %d more" % (len(items) - MAX_LISTED))
    if not api_changed(diffs):
        print("  nothing added, removed or changed")
    sys.stdout.flush()


def require_options_allowed(tag, major, same_bazaar=False):
    if major and tag is None:
        stop("the first release keeps VERSION's numbers, so --major does not apply: set them in VERSION")
    if same_bazaar and tag is None:
        stop("the first release makes the first Bazaar, so --same-bazaar does not apply")
    if major and same_bazaar:
        stop("--major and --same-bazaar do not go together: a new major version is a new Bazaar")


def require_api_unchanged(diffs, remedy):
    if api_changed(diffs):
        stop("this build changes what plugins use, so it needs a new Bazaar: " + remedy)


def released_file(release, pattern):
    """The one file matching pattern from a published release: from dist when it is there, else downloaded from the
    release on GitHub into dist. None if the release has no such file."""
    folder = release_folder(release)
    found = glob.glob(os.path.join(glob.escape(folder), pattern))
    if not found:
        gh = require_gh()
        os.makedirs(folder, exist_ok=True)
        cmd = [gh, "release", "download", tag_of(release), "--pattern", pattern, "--dir", folder]
        done = subprocess.run(cmd, cwd=common.REPO, capture_output=True, text=True, errors="replace")
        found = glob.glob(os.path.join(glob.escape(folder), pattern))
        if not os.listdir(folder):
            os.rmdir(folder)
        if done.returncode != 0 and "no assets match" not in done.stderr.lower():
            stop("%s could not be downloaded from the GitHub release %s: %s" % (pattern, release, done.stderr.strip()))
    if len(found) > 1:
        stop("%s holds %d files named like %s: keep only the release's own" % (folder, len(found), pattern))
    return found[0] if found else None


def bazaar_packages(release):
    """The Bazaar and VMC Bootstrap packages a release published."""
    packages = [released_file(release, release_files(release).host), released_file(release, BOOTSTRAP_PATTERN)]
    if None in packages:
        stop("the GitHub release %s has no Bazaar package or no VMC Bootstrap package" % release)
    return packages


def kept_release(current):
    """The earlier release whose Bazaar this one keeps, or None for a release with a Bazaar of its own."""
    return version.kept_bazaar(current, version.listed_versions())


def code_changes(tag):
    """The files Bazaar's DLL is built from that changed since tag in more than comments and spacing."""
    # The docs' function history sits with the generator but is not built into the DLL; prepare rewrites it every time.
    history = os.path.relpath(build_docs.HISTORY, common.REPO).replace(os.sep, "/")
    names = git("diff", "--name-only", tag, "--", *bazaar_compare.CODE).splitlines()
    return bazaar_compare.changed_code(
        tag, [rel for rel in names if not rel.lower().endswith(".md") and rel != history]
    )


def require_same_bazaar(kept, remedy):
    """kept is the release that made the Bazaar a release keeps; remedy says what to do if it has changed."""
    packages = bazaar_packages(kept)
    found = ["code: " + rel for rel in code_changes(tag_of(kept))]
    try:
        found += bazaar_compare.package_changes(*packages)
    except files.CheckError as e:
        stop("%s; if it is in dist, delete it and run this again, which downloads it afresh" % e)
    found += build_settings_changes(kept)
    if found:
        listed = "".join("\n  " + item for item in found[:MAX_LISTED])
        more = "\n  and %d more" % (len(found) - MAX_LISTED) if len(found) > MAX_LISTED else ""
        stop(
            "Bazaar has changed since %s, so this release needs a new Bazaar: %s. What changed:%s%s"
            % (kept, remedy, listed, more)
        )
    say("Bazaar is the same as in %s" % kept)


def build_settings_changes(kept):
    """Plugins are built with the SDK's settings and run with the kept Bazaar, so the settings the SDK builder writes
    must be those in the kept release's SDK."""
    sdk_zip = released_file(kept, release_files(kept).sdk)
    if sdk_zip is None:
        stop("the GitHub release %s has no SDK zip" % kept)
    try:
        with zipfile.ZipFile(sdk_zip) as z:
            then = z.read(posixpath.join(os.path.basename(build_sdk.SDK), BUILD_SETTINGS))
    except KeyError:
        return ["the SDK's build settings: the SDK of %s has no %s" % (kept, BUILD_SETTINGS)]
    except zipfile.BadZipFile:
        stop("%s is damaged: delete it and run this again, which downloads it afresh" % sdk_zip)
    return [] if then == build_sdk.vsprops_bytes() else ["the SDK's build settings, in %s" % BUILD_SETTINGS]


def plan(lists, major, same_bazaar=False):
    """The next release's numbers, after saying what they come from."""
    tag, base, diffs = choose(lists)
    require_options_allowed(tag, major, same_bazaar)
    if diffs is None:
        say("no release has been made yet, so the first one keeps VERSION's numbers: %s, mod version %d" % base)
        return base
    report(tag, diffs)
    if same_bazaar:
        require_api_unchanged(diffs, RUN_AGAIN)
        require_same_bazaar(kept_release(base) or base.release, RUN_AGAIN)
    new = next_version(base, diffs, major, same_bazaar)
    if new is None:
        stop(
            "from %s on, removing or changing what plugins use needs a new major version: run it with --major"
            % common.FREEZE_SHOWN
        )
    say("the next release is %s, mod version %d" % new)
    if any(d.removed for d in diffs):
        say("every plugin must be rebuilt for it, and the release notes must say so")
    return new


def release_files(release):
    return ReleaseFiles(
        "Bazaar-%s.civ5mod" % release,
        "Bazaar-VMC-Bootstrap-%d.civ5mod" % mods.vmc_mod_parts().version,
        "Bazaar-SDK-%s.zip" % release,
        "Bazaar-docs-%s.zip" % release,
    )


def write_zip(path, folder, top=""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, filenames in sorted(os.walk(folder)):
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                z.write(full, posixpath.join(top, os.path.relpath(full, folder).replace(os.sep, "/")))


def last_docs_zip(release):
    """The docs zip of the newest release before this one that has one, or None."""
    tags = [tag for tag in git("tag", "--list", layouts.RELEASE_TAGS).split() if re.fullmatch(r"v\d+\.\d+\.\d+", tag)]
    earlier = [tag for tag in tags if version.numbers(tag[1:]) < version.numbers(release)]
    for tag in sorted(earlier, key=lambda tag: version.numbers(tag[1:]), reverse=True):
        found = released_file(tag[1:], DOCS_PATTERN)
        if found:
            return found
    return None


def docs_changed(docs, release):
    """Whether the docs built in docs differ from the newest docs zip released before release."""
    last = last_docs_zip(release)
    if last is None:
        return True
    with tempfile.TemporaryDirectory() as folder:
        try:
            with zipfile.ZipFile(last) as z:
                z.extractall(folder)
        except zipfile.BadZipFile:
            stop("%s is damaged: delete it and run this again, which downloads it afresh" % last)
        if bazaar_compare.folder_differences(folder, docs):
            return True
    say("the docs are the same as in %s, so this release has no docs zip" % os.path.basename(last))
    return False


def write_release_files(current, out, trial, same_bazaar=False):
    """Returns the names of the files written: all four, or with the same Bazaar only the SDK zip, and the docs zip if
    the docs changed."""
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    docs = os.path.join(STAGE, "docs")
    build_docs.build(common.engine_project(), docs, release=None if trial else current.release)
    with_docs = not same_bazaar or docs_changed(docs, current.release)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    names = release_files(current.release)
    written = []
    if not same_bazaar:
        host_folder, bootstrap_folder = mods.write_dll_mod(
            os.path.join(STAGE, "MODS"),
            mods.HOST_NAME,
            mods.HOST_ID,
            mods.HOST_TEASER,
            common.HOST_DLL,
            host_screens=True,
            version=files.TEST_VERSION if trial else current.mod,
            description=None if trial else mods.host_description(current.release),
        )
        for folder, name in ((host_folder, names.host), (bootstrap_folder, names.bootstrap)):
            problem = mods.pack(folder, os.path.join(out, name))
            if problem:
                stop(problem)
            written.append(name)
    write_zip(os.path.join(out, names.sdk), build_sdk.SDK, top=os.path.basename(build_sdk.SDK))
    written.append(names.sdk)
    if with_docs:
        write_zip(os.path.join(out, names.docs), docs)
        written.append(names.docs)
    return written


def require_build_as_prepared(current):
    hooks, exports = current_lists()
    for what, path, now in (("hooks", HOOKS_LIST, hooks), ("exported names", EXPORTS_LIST, exports)):
        if read_list(path)[1] != now:
            stop(
                "this build's %s differ from %s, saved when the release was prepared: prepare the release again"
                % (what, common.shown(path))
            )
    _, base, diffs = choose((hooks, exports))
    if diffs is not None:
        major = version.numbers(current.release)[0] > version.numbers(base.release)[0]
        same_bazaar = kept_release(current) is not None
        if same_bazaar:
            if major:
                stop("%s is a new major version, which needs a new Bazaar: %s" % (current.release, PREPARE_AGAIN))
            require_api_unchanged(diffs, PREPARE_AGAIN)
        expected = next_version(base, diffs, major, same_bazaar)
        if expected is None:
            stop(
                "this build removes or changes what plugins use, which from %s on needs a new major version: prepare"
                " the release again with --major" % common.FREEZE_SHOWN
            )
        if expected != current:
            stop(
                "this build calls for release %s, mod version %d, but VERSION says %s, mod version %d: prepare the"
                " release again" % (expected + current)
            )


def restore_history(tag, path=build_docs.HISTORY):
    """The docs' function history as the last release left it, so that this release's marks are made afresh."""
    if tag is None:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(at_tag(tag, path))


def number(major, same_bazaar=False):
    plan(None, major, same_bazaar)
    return 0


def prepare(major, same_bazaar=False):
    require_main()
    require_no_release_branch()
    tag = last_release()
    require_options_allowed(tag, major, same_bazaar)
    run("building the host", ["cmd", "/c", BUILD_HOOKED])
    lists = current_lists()
    new = plan(lists, major, same_bazaar)
    run("the tests", ["cmd", "/c", os.path.join(common.REPO, "tests", "runtime", "run.cmd")])
    run("the docs checks", [sys.executable, os.path.join(common.REPO, "tests", "docs", "check_docs.py")])
    run("the lint", [sys.executable, "-m", "ruff", "check", "."])
    run("the format check", [sys.executable, "-m", "ruff", "format", "--check", "."])
    try:
        version.write(new)
        new_major, new_minor, _ = version.numbers(new.release)
        layouts.set_api_version(new_major, new_minor)
        version.set_plugin_version(new.release)
        version.set_template_bazaar(version.oldest_bazaar(new.release))
        if not same_bazaar:
            version.add_listed_version(new)
        require_numbers_agree()
        restore_history(tag)
        build_docs.build(common.engine_project(), build_docs.DEFAULT_OUT, release=new.release)
        write_list(HOOKS_LIST, new.release, lists[0])
        write_list(EXPORTS_LIST, new.release, lists[1])
    except SystemExit as e:
        raise SystemExit("%s\nrelease: %s" % (e, PART_WAY))
    except BaseException:
        say(PART_WAY)
        raise
    branch = BRANCH_PREFIX + new.release
    git("switch", "-c", branch)
    say("%s is ready on branch %s: commit it and open a pull request to main" % (new.release, branch))
    return 0


def require_releasable(current):
    require_main()
    if saved_release() != current.release:
        stop(
            "the lists in %s were not saved at %s: prepare the release and merge it first"
            % (common.shown(RELEASED), current.release)
        )
    if on_github(tag_of(current.release)):
        stop("%s is already tagged, so it is already released: prepare the next release" % current.release)


def require_unchanged_by_build():
    changed = git("status", "--porcelain")
    if changed:
        stop(
            "building changed these files, so main does not hold the release as it was built. Put the changes on"
            " main through a pull request, then run build again:\n" + changed
        )


def build(trial):
    current = version.read()
    if not trial:
        require_releasable(current)
    require_numbers_agree()
    run("building the host", ["cmd", "/c", BUILD_HOOKED])
    kept = None if trial else kept_release(current)
    if not trial:
        require_build_as_prepared(current)
    if kept:
        require_same_bazaar(kept, PREPARE_AGAIN)
    say("laying out the SDK")
    if build_sdk.main([]) != 0:
        stop("the SDK did not build")
    out = TRIAL_FOLDER if trial else release_folder(current.release)
    written = write_release_files(current, out, trial, same_bazaar=kept is not None)
    if trial:
        say("the trial files of %s are in %s:" % (current.release, out))
    else:
        require_unchanged_by_build()
        head = git("rev-parse", "HEAD")
        with open(os.path.join(out, BUILT_FROM), "w") as f:
            f.write(head + "\n")
        say("the files of %s, built from %s, are in %s:" % (current.release, head, out))
    print("".join("  %s\n" % name for name in written), end="", flush=True)
    return 0


def build_template(sdk_zip):
    """Built outside the repository from the SDK zip alone, so the check fails on anything the SDK left out. The
    template's build uses BAZAAR_SDK when it is set, so it is pointed at the unzipped SDK. Returns the template's own
    checks, from its checks.toml."""
    if os.path.isdir(CHECK_FOLDER):
        files.remove_tree(CHECK_FOLDER)
    with zipfile.ZipFile(sdk_zip) as z:
        z.extractall(CHECK_FOLDER)
    sdk = os.path.join(CHECK_FOLDER, os.path.basename(build_sdk.SDK))
    template = os.path.join(sdk, "plugin-template")
    different = sync_checker.differences(os.path.join(template, "bazaar_check"))
    if different:
        stop(
            "the SDK's copy of the checker differs from tools\\bazaar_check in %s. If tools\\bazaar_check changed"
            " after the build, undo that; if not, run tools\\sync_checker.py, put the change on main and build again"
            % ", ".join(different[:5])
        )
    env = dict(os.environ, BAZAAR_SDK=sdk)
    if subprocess.run(["cmd", "/c", os.path.join(template, "build.cmd")], cwd=template, env=env).returncode != 0:
        stop("the template plugin did not build from %s" % sdk_zip)
    out = os.path.join(template, "Build")
    built = [os.path.join(out, name) for name in sorted(os.listdir(out))] if os.path.isdir(out) else []
    built = [folder for folder in built if os.path.isdir(folder) and files.mod_key(folder)]
    if len(built) != 1:
        stop("the template plugin's build made %d mod folders in %s, not one" % (len(built), out))
    return read_template_checks(template, built[0])


def read_template_checks(template, built):
    checks = runner.read_checks(os.path.join(template, "checks.toml"))
    if [os.path.normcase(mod) for mod in checks.mods] != [os.path.normcase(os.path.normpath(built))]:
        stop("the template's checks.toml checks %s, not %s, the mod its build made" % (", ".join(checks.mods), built))
    return checks


def release_checks(current, packages, template_checks, trial, same_bazaar=False):
    """The template's own checks, the ones plugin authors start from, after the release's. A trial build does not name
    its release, and a release that keeps an earlier Bazaar ships no description of its own, so then the description is
    not checked."""
    api = version.numbers(current.release)[:2]
    loaded = {
        "log": "Bazaar.log",
        "has": TEMPLATE_LOADED % api,
        "what": "Bazaar.log says the template plugin loaded, built for API %d.%d" % api,
    }
    steps = [loaded] + list(template_checks.steps)
    if not trial and not same_bazaar:
        description = {
            "description_of": mods.HOST_ID,
            "version": current.mod,
            "is": mods.host_description(current.release),
            "what": "Bazaar's description in the Mods menu names %s" % current.release,
        }
        steps.insert(0, description)
    return template_checks._replace(mods=packages + list(template_checks.mods), steps=steps)


def check(trial):
    current = version.read()
    out = TRIAL_FOLDER if trial else release_folder(current.release)
    names = release_files(current.release)
    sdk_zip = os.path.join(out, names.sdk)
    command = "build --trial" if trial else "build"
    if not os.path.isfile(sdk_zip):
        stop("this release file is missing: %s; run release.py %s first" % (sdk_zip, command))
    built_from = os.path.join(out, BUILT_FROM)
    if not trial and not os.path.exists(built_from):
        stop("%s holds no release build: run release.py build first" % out)
    kept = None if trial else kept_release(current)
    if kept:
        packages = bazaar_packages(kept)
    else:
        packages = [os.path.join(out, names.host), os.path.join(out, names.bootstrap)]
        missing = [path for path in packages if not os.path.isfile(path)]
        if missing:
            stop("these release files are missing: %s; run release.py %s first" % (", ".join(missing), command))
    try:
        try:
            g = game.Game(say)
            g.preflight()
            say("building the template plugin from %s" % names.sdk)
            template_checks = build_template(sdk_zip)
        except game.ERRORS + (OSError, zipfile.BadZipFile) as e:
            stop("the in-game check could not start: %s" % e)
        if os.path.exists(os.path.join(out, CHECKED)):
            os.remove(os.path.join(out, CHECKED))
        failed = runner.run(release_checks(current, packages, template_checks, trial, kept is not None), g)
    finally:
        try:
            if os.path.isdir(CHECK_FOLDER):
                files.remove_tree(CHECK_FOLDER)
        except OSError as e:
            say("the unzipped SDK in %s could not be deleted (%s): delete it yourself" % (CHECK_FOLDER, e))
    if failed:
        stop("the in-game check " + failed)
    if not trial:
        shutil.copyfile(built_from, os.path.join(out, CHECKED))
    say("the in-game check of %s passed" % current.release)
    return 0


def require_gh():
    gh = shutil.which("gh")
    if gh is None:
        stop("gh, GitHub's command-line tool, was not found: install it, then log in with gh auth login")
    if subprocess.run([gh, "auth", "status"], capture_output=True).returncode != 0:
        stop("gh is not logged in to GitHub: run gh auth login")
    return gh


def publish(notes, no_check=False):
    current = version.read()
    tag = tag_of(current.release)
    out = release_folder(current.release)
    require_main()
    built_from = os.path.join(out, BUILT_FROM)
    if not os.path.exists(built_from):
        stop("%s holds no release build: run release.py build first" % out)
    head = git("rev-parse", "HEAD")
    if read_text(built_from).strip() != head:
        stop("the files in %s were not built from main as it is now: run release.py build again" % out)
    checked = os.path.join(out, CHECKED)
    if not no_check and (not os.path.exists(checked) or read_text(checked).strip() != head):
        stop(
            "the files in %s have not passed release.py check since they were built: run it, or publish with"
            " --no-check for a release that only changes the docs" % out
        )
    names = release_files(current.release)
    kept = kept_release(current)
    if kept:
        wanted = [names.sdk] + ([names.docs] if os.path.isfile(os.path.join(out, names.docs)) else [])
    else:
        wanted = list(names)
    paths = [os.path.join(out, name) for name in wanted]
    missing = [path for path in paths if not os.path.isfile(path)]
    if missing:
        stop("these release files are missing: " + ", ".join(missing))
    if not os.path.isfile(notes) or not read_text(notes).strip():
        stop("the release notes file %s is missing or empty" % notes)
    if kept and not re.search(r"(?<![\d.])%s(?!\.?\d)" % re.escape(kept), read_text(notes)):
        stop("this release keeps the Bazaar of %s: the release notes must say so, naming %s" % (kept, kept))
    gh = require_gh()
    title = "Bazaar " + current.release
    tagged = tagged_commit(tag)
    if tagged is None:
        git("tag", "-a", tag, "-m", title)
    elif tagged != head:
        stop("%s already tags another commit: if it was never pushed, delete it with git tag -d %s" % (tag, tag))
    git("push", "origin", "refs/tags/" + tag)
    cmd = [gh, "release", "create", tag, "--verify-tag", "--draft", "--title", title, "--notes-file", notes]
    if not common.frozen(version.numbers(current.release)):
        cmd.append("--prerelease")
    done = subprocess.run(cmd + paths, cwd=common.REPO, capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        stop(
            "%s is tagged on GitHub, but the draft release could not be made: %s\nFix that, then run publish again;"
            " if GitHub already has a draft release for %s, delete it there first" % (tag, done.stderr.strip(), tag)
        )
    say("draft release created: %s" % done.stdout.strip())
    say("check it on GitHub, then publish it there")
    return 0


def workshop():
    current = version.read()
    tag = tag_of(current.release)
    require_main()
    tagged = tagged_commit(tag)
    if tagged is None or not on_github(tag):
        stop("%s is not tagged on GitHub: publish the release first" % current.release)
    kept = kept_release(current)
    if kept:
        stop("%s keeps the Bazaar of %s, so it has nothing new for the Workshop" % (current.release, kept))
    out = release_folder(current.release)
    built_from = os.path.join(out, BUILT_FROM)
    if not os.path.exists(built_from) or read_text(built_from).strip() != tagged:
        stop("%s does not hold the files tagged %s, which were published on GitHub" % (out, tag))
    package = os.path.join(out, release_files(current.release).host)
    if not os.path.isfile(package):
        stop("%s is missing" % package)
    gh = require_gh()
    view = [gh, "release", "view", tag, "--json", "isDraft"]
    done = subprocess.run(view, cwd=common.REPO, capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        stop("gh could not show the GitHub release %s: %s" % (tag, done.stderr.strip()))
    if json.loads(done.stdout).get("isDraft") is not False:
        stop("the GitHub release %s is still a draft: publish it there first" % tag)
    upload.upload(current.release, package)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("number", "prepare"):
        choice = commands.add_parser(name).add_mutually_exclusive_group()
        choice.add_argument("--major", action="store_true")
        choice.add_argument("--same-bazaar", action="store_true")
    commands.add_parser("build").add_argument("--trial", action="store_true")
    commands.add_parser("check").add_argument("--trial", action="store_true")
    publishing = commands.add_parser("publish")
    publishing.add_argument("--notes", required=True)
    publishing.add_argument("--no-check", action="store_true")
    commands.add_parser("workshop")
    args = parser.parse_args()
    if args.command == "number":
        return number(args.major, args.same_bazaar)
    if args.command == "prepare":
        return prepare(args.major, args.same_bazaar)
    if args.command == "build":
        return build(args.trial)
    if args.command == "check":
        return check(args.trial)
    if args.command == "workshop":
        return workshop()
    return publish(os.path.abspath(args.notes), args.no_check)


if __name__ == "__main__":
    game.make_output_safe()
    sys.exit(main())
