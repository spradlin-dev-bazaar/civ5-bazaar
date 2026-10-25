"""Write the developer documentation site: a page for each function, class, file and folder of the engine and for
each hand-placed hook, all linked to each other. Every link is checked before anything is written.

    python tools/docs/build_docs.py [--out FOLDER] [--release VERSION]
"""

import argparse
import os
import posixpath
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "generator"))
sys.path.insert(0, os.path.join(HERE, ".."))

import common  # noqa: E402
import handwritten  # noqa: E402
import history  # noqa: E402
import model  # noqa: E402
import pages  # noqa: E402
import render  # noqa: E402

DEFAULT_OUT = os.path.join(common.SOURCE_ROOT, "BuildTemp", "docs")
INPUTS = handwritten.Inputs(
    hand_hooks=os.path.join(common.REPO, "sdk", "hand-placed-hooks.md"),
    task_guide=os.path.join(common.REPO, "docs", "task-guide.md"),
    class_summaries=os.path.join(common.REPO, "docs", "class-summaries.md"),
    function_notes=os.path.join(common.REPO, "docs", "function-notes.md"),
)
HISTORY = os.path.join(common.REPO, "tools", "generator", "function-history.txt")
NOTICE = os.path.join(common.REPO, "NOTICE")
HREF = re.compile(r'href="([^"]*)"')


def broken_links(site):
    known = set(site.pages) | set(render.SUPPORT_FILES)
    broken = []
    for path, page in site.pages.items():
        for href in HREF.findall(page):
            target = href.split("#", 1)[0]
            if target and "://" not in target:
                if posixpath.normpath(posixpath.join(posixpath.dirname(path), target)) not in known:
                    broken.append((path, href))
    broken += [(render.INDEX_FILE, target) for _, target in site.search_rows() if target not in known]
    return broken


def is_docs_build(folder):
    index = os.path.join(folder, render.INDEX_FILE)
    if not os.path.isfile(index):
        return False
    with open(index, encoding="utf-8", errors="replace") as f:
        return f.read(len(render.INDEX_START)) == render.INDEX_START


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write(site, out):
    if os.path.isdir(out):
        if os.listdir(out) and not is_docs_build(out):
            raise SystemExit("docs: %s is not an earlier docs build, so it is not emptied" % out)
        shutil.rmtree(out)
    # First, so that a run stopped part way still leaves the file that lets the next run empty the folder.
    write_text(os.path.join(out, render.INDEX_FILE), site.search_index())
    for path, page in site.pages.items():
        write_text(os.path.join(out, *path.split("/")), page)
    with open(os.path.join(HERE, "site", "style.css"), encoding="utf-8") as f:
        write_text(os.path.join(out, render.STYLE_FILE), f.read() + "\n" + render.code_css())
    shutil.copyfile(os.path.join(HERE, "site", "search.js"), os.path.join(out, render.SCRIPT_FILE))
    shutil.copyfile(NOTICE, os.path.join(out, render.NOTICE_FILE))


def build(project, out, inputs=INPUTS, history_path=HISTORY, release=None):
    started = time.time()
    saved_release, entries = history.load(history_path)
    if release is not None:
        history.check(release, saved_release)
    engine = model.Engine(project)
    if release is not None:
        if engine.unregistered_hooks:
            raise SystemExit(
                "docs: %d hook points are not in %s yet: build the host before a release, nothing written"
                % (engine.unregistered_hooks, project.registry)
            )
        entries = history.update(saved_release, entries, engine.history_now(), release)
    engine.apply_history(entries)
    site = pages.Site(engine, inputs)
    broken = broken_links(site)
    if broken:
        for path, href in broken[:20]:
            print("  broken link in %s: %s" % (path, href))
        raise SystemExit("docs: %d broken links, nothing written" % len(broken))
    write(site, out)
    report(engine, site, project, out, started)
    if release is not None:
        history.save(history_path, release, entries)
        report_release(engine, release, saved_release)
    return site


def report(engine, site, project, out, started):
    hooked = sum(1 for fn in engine.functions if model.is_hook(fn))
    print(
        "docs: functions %d (hook points %d), pages %d, seconds %.0f, written to %s"
        % (len(engine.functions), hooked, len(site.pages), time.time() - started, out)
    )
    if engine.body_errors:
        print(
            "  %d parse errors inside function bodies: calls there may be missing from the pages" % engine.body_errors
        )
    if engine.unregistered_hooks:
        print(
            "  %d hook points are not in %s yet: build the host first" % (engine.unregistered_hooks, project.registry)
        )
    if engine.stale_registry_entries:
        print(
            "docs: %d entries in %s are no longer hook points in the engine"
            % (engine.stale_registry_entries, project.registry)
        )


def report_release(engine, release, saved_release):
    if saved_release is None:
        print("docs: release %s starts the function history" % release)
        return
    added = sum(1 for fn in engine.functions if fn["added_in"] == release)
    changed = sum(1 for fn in engine.functions if any(c.release == release for c in fn["changed_in"]))
    print("docs: release %s marks: %d added, %d changed" % (release, added, changed))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=DEFAULT_OUT, help="the folder to write the site into (emptied first)")
    parser.add_argument(
        "--release", help="the release being made: mark what changed since the last one and save the function history"
    )
    args = parser.parse_args()
    build(common.engine_project(), args.out, release=args.release)
    return 0


if __name__ == "__main__":
    sys.exit(main())
