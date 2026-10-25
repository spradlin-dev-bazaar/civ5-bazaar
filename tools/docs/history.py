"""The function history behind the docs' "added in" and "changed in" marks.

The file: a line `release<TAB>X`, then one line per function: name, fingerprint, hand-placed hooks, release added,
and its changes, each `release|file|first line|last line|hooks it added`, joined with `;`.
"""

import collections
import hashlib
import os
import re

VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

Entry = collections.namedtuple("Entry", "fingerprint hand_hooks added changes")
Change = collections.namedtuple("Change", "release source first last added_hooks")
Current = collections.namedtuple("Current", "fingerprint hand_hooks source first last")


def fingerprint(tokens):
    return hashlib.sha1(" ".join(tokens).encode("utf-8")).hexdigest()[:16]


def version(text):
    if not VERSION.fullmatch(text or ""):
        raise SystemExit("docs: a release is three numbers, such as 0.4.0, not %r" % text)
    return tuple(int(n) for n in text.split("."))


def check(release, saved_release):
    new = version(release)
    if saved_release is not None and new < version(saved_release):
        raise SystemExit("docs: the function history was saved at release %s, later than %s" % (saved_release, release))


def load(path):
    if not os.path.exists(path):
        return None, {}
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    try:
        name, release = (lines[0] if lines else "").split("\t")
        if name != "release" or not VERSION.fullmatch(release):
            raise ValueError
    except ValueError:
        raise SystemExit("docs: line 1 of %s is not a function history line" % path)
    entries = {}
    for number, line in enumerate(lines[1:], 2):
        try:
            key, fp, hooks, added, changes = line.split("\t")
            entries[key] = Entry(fp, split(hooks, ","), added, [read_change(c) for c in split(changes, ";")])
        except ValueError:
            raise SystemExit("docs: line %d of %s is not a function history line" % (number, path))
    return release, entries


def save(path, release, entries):
    lines = ["release\t%s" % release]
    for key in sorted(entries):
        e = entries[key]
        changes = ";".join(write_change(c) for c in e.changes)
        lines.append("\t".join([key, e.fingerprint, ",".join(e.hand_hooks), e.added, changes]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def split(text, sep):
    return tuple(text.split(sep)) if text else ()


def read_change(text):
    release, source, first, last, hooks = text.split("|")
    return Change(release, source, int(first), int(last), split(hooks, "+"))


def write_change(c):
    return "|".join([c.release, c.source, str(c.first), str(c.last), "+".join(c.added_hooks)])


def update(saved_release, saved, current, release):
    """Functions missing from this build keep their entries, so one that comes back keeps its marks."""
    check(release, saved_release)
    if release == saved_release:
        return again(saved, current, release)
    entries = dict(saved)
    for key, now in current.items():
        old = saved.get(key)
        if old is None:
            entries[key] = Entry(now.fingerprint, now.hand_hooks, release if saved_release is not None else "", [])
        elif old.fingerprint != now.fingerprint:
            added_hooks = tuple(h for h in now.hand_hooks if h not in old.hand_hooks)
            change = Change(release, now.source, now.first, now.last, added_hooks)
            entries[key] = Entry(now.fingerprint, now.hand_hooks, old.added, old.changes + [change])
    return entries


def again(saved, current, release):
    """Building a saved release again changes no mark; only where its changes now sit in the files."""
    if any(key not in saved or saved[key].fingerprint != now.fingerprint for key, now in current.items()):
        raise SystemExit(
            "docs: the function history was already saved at release %s, and the code has changed since: prepare the"
            " release again" % release
        )
    entries = dict(saved)
    for key, now in current.items():
        moved = [
            c._replace(source=now.source, first=now.first, last=now.last) if c.release == release else c
            for c in saved[key].changes
        ]
        entries[key] = saved[key]._replace(changes=moved)
    return entries
