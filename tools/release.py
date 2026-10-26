"""Make a Bazaar release, as docs/plugin-host.md describes under Making a release.

    python tools/release.py number [--major]       after build-hooked.cmd: the next release's number, and what changed
    python tools/release.py prepare [--major]      on main: a release branch with the new numbers and saved lists
    python tools/release.py build [--trial]        on main, once the release branch has merged: the release's files
    python tools/release.py publish --notes FILE   tag the commit the files were built from and draft its GitHub release

--major starts a new major version, such as 1.0.0. build --trial runs on any branch, leaves the release marks out of the
docs, and writes to dist/trial, which publish never uses.
"""

import argparse
import collections
import difflib
import os
import posixpath
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "generator"))
sys.path.insert(0, os.path.join(HERE, "docs"))
sys.path.insert(0, os.path.join(HERE, "..", "sdk"))

import build_docs  # noqa: E402
import build_sdk  # noqa: E402
import common  # noqa: E402
import layouts  # noqa: E402
import mods  # noqa: E402
import version  # noqa: E402

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

HOOK_LINE = re.compile(r"^\tnamespace (\w+) \{ enum \{ ID = (\d+) \}; \}", re.M)
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
    done = subprocess.run(["git", "show", "%s:%s" % (tag, rel)], cwd=common.REPO, capture_output=True)
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
    found = sorted(HOOK_LINE.findall(text), key=lambda hook: int(hook[1]))
    return ["%s\t%s" % (hook_id, name) for name, hook_id in found]


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
    return Difference("class layouts", sorted(set(key for key, _ in new)), sorted(set(key for key, _, _ in lost)))


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


def next_version(base, diffs, major=False):
    """The release after base, or None when only a new major version may follow it."""
    numbers = version.numbers(base.release)
    if major:
        release = "%d.0.0" % (numbers[0] + 1)
    elif numbers[0] >= 1 and any(d.removed for d in diffs):
        return None
    elif any(d.added or d.removed for d in diffs):
        release = "%d.%d.0" % (numbers[0], numbers[1] + 1)
    else:
        release = "%d.%d.%d" % (numbers[0], numbers[1], numbers[2] + 1)
    return version.Version(release, base.mod + 1)


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
    if not any(d.added or d.removed for d in diffs):
        print("  nothing added, removed or changed")
    sys.stdout.flush()


def require_major_allowed(tag, major):
    if major and tag is None:
        stop("the first release keeps VERSION's numbers, so --major does not apply: set them in VERSION")


def plan(lists, major):
    """The next release's numbers, after saying what they come from."""
    tag, base, diffs = choose(lists)
    require_major_allowed(tag, major)
    if diffs is None:
        say("no release has been made yet, so the first one keeps VERSION's numbers: %s, mod version %d" % base)
        return base
    report(tag, diffs)
    new = next_version(base, diffs, major)
    if new is None:
        stop("from 1.0 on, removing or changing what plugins use needs a new major version: run it with --major")
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


def write_release_files(current, out, release_marks):
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    docs = os.path.join(STAGE, "docs")
    build_docs.build(common.engine_project(), docs, release=current.release if release_marks else None)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    names = release_files(current.release)
    host_folder, bootstrap_folder = mods.write_dll_mod(
        os.path.join(STAGE, "MODS"),
        mods.HOST_NAME,
        mods.HOST_ID,
        mods.HOST_TEASER,
        common.HOST_DLL,
        plugins_screen=True,
        version=current.mod,
    )
    for folder, name in ((host_folder, names.host), (bootstrap_folder, names.bootstrap)):
        problem = mods.pack(folder, os.path.join(out, name))
        if problem:
            stop(problem)
    write_zip(os.path.join(out, names.sdk), build_sdk.SDK, top=os.path.basename(build_sdk.SDK))
    write_zip(os.path.join(out, names.docs), docs)
    return names


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
        expected = next_version(base, diffs, major)
        if expected is None:
            stop(
                "this build removes or changes what plugins use, which from 1.0 on needs a new major version: prepare"
                " the release again with --major"
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


def number(major):
    plan(None, major)
    return 0


def prepare(major):
    require_main()
    require_no_release_branch()
    tag = last_release()
    require_major_allowed(tag, major)
    run("building the host", ["cmd", "/c", BUILD_HOOKED])
    lists = current_lists()
    new = plan(lists, major)
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
    if not trial:
        require_build_as_prepared(current)
    say("laying out the SDK")
    if build_sdk.main([]) != 0:
        stop("the SDK did not build")
    out = TRIAL_FOLDER if trial else release_folder(current.release)
    names = write_release_files(current, out, release_marks=not trial)
    if trial:
        say("the trial files of %s are in %s:" % (current.release, out))
    else:
        require_unchanged_by_build()
        head = git("rev-parse", "HEAD")
        with open(os.path.join(out, BUILT_FROM), "w") as f:
            f.write(head + "\n")
        say("the files of %s, built from %s, are in %s:" % (current.release, head, out))
    print("".join("  %s\n" % name for name in names), end="", flush=True)
    return 0


def publish(notes):
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
    paths = [os.path.join(out, name) for name in release_files(current.release)]
    missing = [path for path in paths if not os.path.isfile(path)]
    if missing:
        stop("these release files are missing: " + ", ".join(missing))
    if not os.path.isfile(notes) or not read_text(notes).strip():
        stop("the release notes file %s is missing or empty" % notes)
    gh = shutil.which("gh")
    if gh is None:
        stop("gh, GitHub's command-line tool, was not found: install it, then log in with gh auth login")
    if subprocess.run([gh, "auth", "status"], capture_output=True).returncode != 0:
        stop("gh is not logged in to GitHub: run gh auth login")
    title = "Bazaar " + current.release
    tagged = tagged_commit(tag)
    if tagged is None:
        git("tag", "-a", tag, "-m", title)
    elif tagged != head:
        stop("%s already tags another commit: if it was never pushed, delete it with git tag -d %s" % (tag, tag))
    git("push", "origin", "refs/tags/" + tag)
    cmd = [gh, "release", "create", tag, "--verify-tag", "--draft", "--title", title, "--notes-file", notes]
    if version.numbers(current.release)[0] == 0:
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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("number").add_argument("--major", action="store_true")
    commands.add_parser("prepare").add_argument("--major", action="store_true")
    commands.add_parser("build").add_argument("--trial", action="store_true")
    commands.add_parser("publish").add_argument("--notes", required=True)
    args = parser.parse_args()
    if args.command == "number":
        return number(args.major)
    if args.command == "prepare":
        return prepare(args.major)
    if args.command == "build":
        return build(args.trial)
    return publish(os.path.abspath(args.notes))


if __name__ == "__main__":
    sys.exit(main())
