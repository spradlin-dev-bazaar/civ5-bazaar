"""Gather the docs site for GitHub Pages from the docs zips of Bazaar's GitHub releases.

    python tools/docs/gather_site.py --repo OWNER/NAME FOLDER

The newest version of Bazaar on the Steam Workshop goes at the site's main address, each other version on the
Workshop at <version>/, and the newest version at <version>/ when it is newer than every version on the Workshop.
Each version's docs come from the newest of its releases that has a docs zip. A version is on the Workshop when one
of its releases is not a pre-release. Every file in a docs zip goes on the site except the Markdown copies of the pages.
The script runs with Python's standard library and gh, GitHub's command-line tool, so the docs Action depends on
nothing else.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
DOCS_ZIP = "Bazaar-docs-%s.zip"
MARKDOWN = ".md"


def stop(message):
    raise SystemExit("gather_site: " + message)


def say(message):
    print("gather_site: " + message, flush=True)


def gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        stop("gh %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout


def releases(repo):
    """Every published release, as dicts with tag, prerelease and assets."""
    query = ".[] | select(.draft | not) | {tag: .tag_name, prerelease, assets: [.assets[].name]}"
    out = gh("api", "--paginate", "repos/%s/releases" % repo, "--jq", query)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def versions_of(found):
    versions = {}
    for release in found:
        match = TAG.fullmatch(release["tag"])
        if match:
            numbers = tuple(int(n) for n in match.groups())
            versions.setdefault(numbers[:2], []).append((numbers, release))
    return versions


def choose(found):
    """Where each version's docs go and which release's docs zip they come from: (folder, tag, zip name) for each
    version the site keeps, the main address first, its folder empty."""
    versions = versions_of(found)
    on_workshop = sorted(
        (v for v, listed in versions.items() if any(not release["prerelease"] for _, release in listed)), reverse=True
    )
    if not on_workshop:
        stop("no release is a full release, so no version of Bazaar is on the Workshop to put at the main address")
    at_main = on_workshop[0]
    newest = max(versions)
    kept = [at_main] + ([newest] if newest > at_main else []) + on_workshop[1:]
    chosen = []
    for v in kept:
        shown = "%d.%d" % v
        with_docs = [(n, release) for n, release in versions[v] if docs_zip(release["tag"]) in release["assets"]]
        if not with_docs:
            if v == at_main:
                stop("no release of Bazaar %s has a docs zip, so the main address would have no docs" % shown)
            say("no release of Bazaar %s has a docs zip, so the site leaves it out" % shown)
            continue
        _, release = max(with_docs, key=lambda pair: pair[0])
        chosen.append(("" if v == at_main else shown, release["tag"], docs_zip(release["tag"])))
    return chosen


def docs_zip(tag):
    return DOCS_ZIP % tag[1:]


def unpack(zip_path, folder):
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(folder, [name for name in z.namelist() if not name.endswith(MARKDOWN)])


def gather(repo, site):
    if os.path.exists(site) and os.listdir(site):
        stop("%s is not empty" % site)
    with tempfile.TemporaryDirectory() as downloads:
        for folder, tag, name in choose(releases(repo)):
            target = os.path.join(site, folder)
            if folder and os.path.exists(target):
                stop("the docs at the main address already have a folder named %s" % folder)
            gh("release", "download", tag, "--repo", repo, "--pattern", name, "--dir", downloads)
            unpack(os.path.join(downloads, name), target)
            say("%s from %s" % ("%s/" % folder if folder else "the main address", name))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, help="the GitHub repository, such as owner/name")
    parser.add_argument("site", help="the folder to write the site into. It must be empty or not exist yet")
    args = parser.parse_args()
    gather(args.repo, args.site)
    return 0


if __name__ == "__main__":
    sys.exit(main())
