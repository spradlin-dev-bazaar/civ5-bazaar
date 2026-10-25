"""The hand-written Markdown on the docs site: the task guide, the class summaries, the function notes and the
hand-placed hooks."""

import collections
import re

from paths import HOME_PAGE, rel_link

Inputs = collections.namedtuple("Inputs", "hand_hooks task_guide class_summaries function_notes")
LINK = re.compile(r"\[\[([^\[\]]+)\]\]")


def read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def read_sections(path):
    parts = re.split(r"^## (.+?)\s*$", read(path), flags=re.M)
    names = parts[1::2]
    twice = [name for name in names if names.count(name) > 1]
    if twice:
        raise SystemExit("docs: %s has two sections named %s" % (path, twice[0]))
    return re.sub(r"\A\s*# .*\n", "", parts[0]), dict(zip(names, parts[2::2]))


def named_links(text, source, page, targets):
    def link(m):
        name, _, label = m.group(1).partition("|")
        found = targets.get(name, [])
        if len(found) != 1:
            raise SystemExit("docs: %s names %s, which is not one function, class or hand-placed hook" % (source, name))
        return "[`%s`](%s)" % (label or re.sub(r"\s+const$", "", name), rel_link(page, found[0]))

    linked = LINK.sub(link, text)
    unclosed = re.search(r"\[\[.*", linked)
    if unclosed:
        raise SystemExit("docs: %s has a [[ link with no closing ]]: %s" % (source, unclosed.group(0).strip()))
    return linked


def task_guide(path, targets):
    return named_links(read(path), path, HOME_PAGE, targets)


def class_summaries(path, targets, class_pages):
    summaries = read_sections(path)[1]
    unknown = [owner for owner in summaries if owner not in class_pages]
    if unknown:
        raise SystemExit("docs: classes summarized in %s that have no page: %s" % (path, ", ".join(unknown)))
    return {owner: named_links(md, path, class_pages[owner], targets) for owner, md in summaries.items()}


def function_notes(path, targets, pages_by_name):
    notes = read_sections(path)[1]
    unclear = [name for name in notes if len(pages_by_name.get(name, [])) != 1]
    if unclear:
        raise SystemExit("docs: functions noted in %s that are not one function: %s" % (path, ", ".join(unclear)))
    pages = [pages_by_name[name][0] for name in notes]
    twice = [name for name, page in zip(notes, pages) if pages.count(page) > 1]
    if twice:
        raise SystemExit("docs: %s has two notes for one function: %s" % (path, ", ".join(twice)))
    return {page: named_links(md, path, page, targets) for page, md in zip(pages, notes.values())}


def hook_descriptions(path, called):
    intro, sections = read_sections(path)
    unknown = sorted(set(called) - set(sections))
    if unknown:
        raise SystemExit(
            "docs: hand-placed hooks the engine calls that have no section in %s: %s" % (path, ", ".join(unknown))
        )
    unused = sorted(set(sections) - set(called))
    if unused:
        raise SystemExit("docs: hand-placed hooks in %s that no engine function calls: %s" % (path, ", ".join(unused)))
    return intro, sections
