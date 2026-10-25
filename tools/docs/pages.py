"""What every docs page says, written out as HTML and as Markdown, and the search index."""

import bisect
import collections
import hashlib
import json
import os
import posixpath
import re

import generate
import handwritten
import render
import render_md
from model import is_hook
from outline import Badge, Code, Entries, Facts, Link, Mono, Page, Paragraph, Prose, Section, joined
from paths import HOME_PAGE, HOOKS_PAGE, file_dir, file_page, folder_page, hook_page, markdown_page, posix

SEPARATOR = re.compile(r"^\s*([/*=-]\s*){4,}$")
IF_LINE = re.compile(r"^#\s*if")
BRANCH_LINE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b")
FOLD_AFTER = 30
GITHUB = "https://github.com/spradlin-dev-bazaar/civ5-bazaar"
REPLACEMENT_WARNING = [
    "A replacement for this function that does not call ",
    Mono("original"),
    " stops these hooks from running.",
]
INTRO = (
    "Every function in the game's code, with its code, the functions it calls and the functions that call it, and how "
    "to hook it from a plugin."
)


class Site:
    def __init__(self, engine, inputs):
        self.engine = engine
        self.homes = class_homes(engine.functions, engine.classes)
        self.listed_files = {fn["file"] for fn in engine.functions if not fn["owner"]} | set(self.homes.values())
        folders = collections.defaultdict(list)
        for fn in engine.functions:
            folders[self.class_dir(fn["owner"]) if fn["owner"] else file_dir(fn["file"])].append(fn)
        for folder, fns in folders.items():
            assign_slugs(fns)
            for fn in fns:
                fn["page"] = "%s/%s.html" % (folder, fn["slug"])
        self.targets = self.link_targets()
        page_of_class = {owner: self.class_page(owner) for owner in self.homes}
        self.summaries = handwritten.class_summaries(inputs.class_summaries, self.targets, page_of_class)
        self.notes = handwritten.function_notes(inputs.function_notes, self.targets, self.function_names())
        self.outlines = []
        for fn in engine.functions:
            self.function_page(fn)
        self.class_pages()
        self.file_pages()
        self.folder_pages()
        self.hook_pages(*handwritten.hook_descriptions(inputs.hand_hooks, engine.hand_sites))
        self.home_page(handwritten.task_guide(inputs.task_guide, self.targets))
        self.html = {o.path: render.page(o) for o in self.outlines}
        self.markdown = {markdown_page(o.path): render_md.page(o) for o in self.outlines}

    def class_dir(self, owner):
        return "%s/%s" % (file_dir(self.homes[owner]), owner.replace("::", "."))

    def class_page(self, owner):
        return self.class_dir(owner) + "/index.html"

    def add(self, path, title, trail, blocks, heading=None):
        self.outlines.append(Page(path, title, heading or title, trail, blocks))

    def folder_trail(self, folder):
        parts = folder.split("/") if folder else []
        return [("Game code", folder_page(""))] + [
            (parts[i], folder_page("/".join(parts[: i + 1]))) for i in range(len(parts))
        ]

    def file_trail(self, rel):
        folder = posixpath.dirname(posix(rel))
        return self.folder_trail(folder) + [(os.path.basename(rel), file_page(rel))]

    def scope_trail(self, fn):
        if fn["owner"]:
            return self.file_trail(self.homes[fn["owner"]]) + [(fn["owner"], self.class_page(fn["owner"]))]
        return self.file_trail(fn["file"])

    # Function pages.

    def code(self, fn):
        data = self.engine.text(fn["file"])
        start = snippet_start(data, fn["def_start"])
        raw = data[start : fn["def_end"]].decode("cp1252", "replace")
        text = raw.replace("\r\n", "\n")
        first = self.engine.line_of(fn["file"], start)
        links = self.code_links(fn, start, raw)
        greyed = self.greyed_lines(fn, first, text.split("\n"))
        marks = {line - first: hook for hook, line in fn["hand_hooks"]}
        return Code(text, first, links, greyed, marks, posix(fn["file"]))

    def code_links(self, fn, start, raw):
        """A spot that names two functions, as a macro can, gets no link."""
        crlf = [m.start() for m in re.finditer("\r\n", raw)]
        targets = collections.defaultdict(dict)
        for usr, offset, _ in fn["refs"]:
            target = self.engine.by_usr.get(usr)
            if offset is not None and target is not None and start <= offset < fn["def_end"]:
                targets[offset][id(target)] = target
        links = {}
        for offset, found in targets.items():
            if len(found) == 1:
                target = next(iter(found.values()))
                at = offset - start - bisect.bisect_left(crlf, offset - start)
                links[at] = (target["page"], target["title"])
        return links

    def greyed_lines(self, fn, first, lines):
        greyed = set()
        for s, e in fn["excluded"]:
            top, bottom = self.engine.line_of(fn["file"], s), self.engine.line_of(fn["file"], e)
            for n in range(top, bottom + 1):
                i = n - first
                if 0 <= i < len(lines) and not (n in (top, bottom) and BRANCH_LINE.match(lines[i])):
                    greyed.add(i)
        return greyed

    def fact_rows(self, fn):
        shown = Link(file_page(fn["file"]), posix(fn["file"])) if fn["file"] in self.listed_files else posix(fn["file"])
        rows = [("Defined in", [shown, ", line %d" % fn["line"]])]
        if fn["owner"]:
            rows.append(("Class", [Link(self.class_page(fn["owner"]), fn["owner"])]))
        if is_hook(fn):
            rows.append(("Hook name", [Mono("CivHooks::" + fn["hook_name"])]))
        else:
            rows.append(("Not a hook point", ["; ".join(fn["skip"])]))
        rows.append(("Added in", [fn["added_in"]]))
        rows.append(("Changed in", joined(change_mark(c, self.engine.hand_sites) for c in fn["changed_in"])))
        overrides = [self.engine.by_usr[u] for u in fn["overrides"] if u in self.engine.by_usr]
        overriders = sorted(self.engine.overriders_of(fn), key=lambda f: f["title"])
        rows.append(("Overrides", joined([function_link(f)] for f in overrides)))
        rows.append(("Overridden by", joined([function_link(f)] for f in overriders)))
        rows.append(("Lua events", joined([Mono("GameEvents." + e)] for e in fn["events"])))
        return rows

    def hand_hook_section(self, fn):
        if not fn["hand_hooks"]:
            return []
        items = [
            [Link(hook_page(hook), hook), ", ", Link(fn["page"], "line %d" % line, line=line)]
            for hook, line in fn["hand_hooks"]
        ]
        warning = [Paragraph(REPLACEMENT_WARNING, warning=True)] if is_hook(fn) else []
        return [Section("Hand-placed hooks inside", warning + [Entries(items)])]

    def calls_list(self, fn):
        seen, items = set(), []
        for usr, _, qualified in fn["refs"]:
            if usr in seen:
                continue
            seen.add(usr)
            target = self.engine.by_usr.get(usr)
            if target is fn:
                continue
            if target is not None:
                items.append(((target["title"].lower(), target["title"]), [function_link(target)]))
            else:
                items.append(((qualified.lower(), qualified), [Mono(qualified)]))
        return Entries([parts for _, parts in sorted(items, key=lambda item: item[0])])

    def function_page(self, fn):
        path = fn["page"]
        blocks = [Facts(self.fact_rows(fn))]
        if path in self.notes:
            blocks.append(Prose(self.notes[path]))
        blocks += self.hand_hook_section(fn)
        if is_hook(fn):
            blocks.append(Section("Hooks", [Code(fn["declarations"], None)], "hooks"))
        blocks.append(Section("Code", [self.code(fn)], "code"))
        blocks.append(Section("Calls", [self.calls_list(fn)]))
        callers = sorted(self.engine.callers_of(fn), key=lambda f: (f["file"].lower(), f["title"]))
        summary = "%d functions in %d files" % (len(callers), len({f["file"] for f in callers}))
        blocks.append(Section("Called by", [Entries([[function_link(f)] for f in callers], FOLD_AFTER, summary)]))
        self.add(path, fn["title"], self.scope_trail(fn) + [(fn["name"], path)], blocks)

    # Class, file and folder pages.

    def scope_listing(self, fns):
        items = []
        for fn in sorted(fns, key=lambda f: (f["name"].lower(), f["title"])):
            label = fn["displayname"] + (" const" if fn["const"] else "")
            badge = [] if is_hook(fn) else [" ", Badge("not a hook point")]
            items.append([Link(fn["page"], label, fn["title"])] + badge)
        return Entries(items)

    def class_link(self, owner):
        return Link(self.class_page(owner), owner) if owner in self.homes else Mono(owner)

    def class_pages(self):
        by_owner = collections.defaultdict(list)
        for fn in self.engine.functions:
            if fn["owner"]:
                by_owner[fn["owner"]].append(fn)
        derived = collections.defaultdict(list)
        for name, c in self.engine.classes.items():
            for base in c["bases"]:
                derived[base].append(name)
        for owner, fns in by_owner.items():
            path = self.class_page(owner)
            info = self.engine.classes.get(owner)
            rows = []
            if info:
                rows.append(("Declared in", ["%s, line %d" % (posix(info["file"]), info["line"])]))
                rows.append(("Based on", joined([self.class_link(b)] for b in info["bases"])))
            rows.append(("Classes based on it", joined([self.class_link(d)] for d in sorted(derived[owner]))))
            blocks = [Facts(rows)]
            if owner in self.summaries:
                blocks.append(Prose(self.summaries[owner]))
            blocks.append(Section("Functions", [self.scope_listing(fns)]))
            self.add(path, owner, self.file_trail(self.homes[owner]) + [(owner, path)], blocks)

    def file_pages(self):
        free = collections.defaultdict(list)
        for fn in self.engine.functions:
            if not fn["owner"]:
                free[fn["file"]].append(fn)
        homed = collections.defaultdict(list)
        for owner, rel in self.homes.items():
            homed[rel].append(owner)
        for rel in self.listed_files:
            classes = Entries([[Link(self.class_page(c), c)] for c in sorted(homed[rel], key=str.lower)])
            blocks = [Section("Classes", [classes]), Section("Functions", [self.scope_listing(free[rel])])]
            name = os.path.basename(rel)
            self.add(file_page(rel), name, self.file_trail(rel), blocks)

    def folder_pages(self):
        folders = collections.defaultdict(lambda: (set(), set()))
        for rel in self.listed_files:
            parts = posix(rel).split("/")
            folders["/".join(parts[:-1])][1].add(rel)
            for i in range(len(parts) - 1):
                folders["/".join(parts[:i])][0].add("/".join(parts[: i + 1]))
        for folder, (subfolders, files) in folders.items():
            items = [[Link(folder_page(s), s.split("/")[-1] + "/")] for s in sorted(subfolders, key=str.lower)]
            items += [[Link(file_page(f), os.path.basename(f))] for f in sorted(files, key=str.lower)]
            name = folder.split("/")[-1] if folder else os.path.basename(self.engine.project.root)
            self.add(folder_page(folder), folder or "Game code", self.folder_trail(folder), [Entries(items)], name)

    # Hand-placed hook pages and the home page.

    def hook_pages(self, intro, descriptions):
        items = []
        for hook in sorted(descriptions):
            path = hook_page(hook)
            fires = []
            for fn, line in sorted(self.engine.hand_sites[hook], key=lambda s: (s[0]["file"].lower(), s[1])):
                fires.append([function_link(fn), ", ", Link(fn["page"], "line %d" % line, line=line)])
            blocks = [Prose(descriptions[hook]), Section("Where it fires", [Entries(fires)])]
            self.add(path, hook, [("Hand-placed hooks", HOOKS_PAGE), (hook, path)], blocks)
            items.append([Link(path, hook)])
        trail = [("Hand-placed hooks", HOOKS_PAGE)]
        self.add(HOOKS_PAGE, "Hand-placed hooks", trail, [Prose(intro), Entries(items)])

    def home_page(self, guide):
        functions = self.engine.functions
        counts = " (%d functions, %d of them hook points)" % (len(functions), sum(1 for fn in functions if is_hook(fn)))
        links = [[Link(folder_page(""), "The game's code"), counts], [Link(HOOKS_PAGE, "Hand-placed hooks")]]
        if self.summaries:
            links.append(["Main classes: "] + joined([Link(self.class_page(c), c)] for c in self.summaries))
        blocks = [Paragraph([INTRO]), Entries(links), Prose(guide, first_heading=2)]
        self.add(HOME_PAGE, render.SITE_NAME, [], blocks)

    def function_names(self):
        names = collections.defaultdict(list)
        for fn in self.engine.functions:
            names[fn["title"]].append(fn["page"])
            names[fn["title"].split("(")[0]].append(fn["page"])
        return names

    def link_targets(self):
        targets = self.function_names()
        for owner in self.homes:
            targets[owner].append(self.class_page(owner))
        for hook in self.engine.hand_sites:
            targets[hook].append(hook_page(hook))
        return targets

    # The search index.

    def search_rows(self):
        rows = [[fn["title"], fn["page"]] for fn in self.engine.functions]
        rows += [[owner + " (class)", self.class_page(owner)] for owner in sorted(self.homes)]
        rows += [[hook + " (hand-placed hook)", hook_page(hook)] for hook in sorted(self.engine.hand_sites)]
        rows += [[os.path.basename(f) + " (file)", file_page(f)] for f in sorted(self.listed_files)]
        return rows

    def search_index(self):
        return "%s%s;\n" % (render.INDEX_START, json.dumps(self.search_rows(), separators=(",", ":")))


def function_link(fn):
    return Link(fn["page"], fn["title"])


def change_mark(change, hooks):
    """hooks: the hand-placed hooks the engine calls today, the ones that still have a page to link to."""
    blame = "%s/blame/v%s/%s#L%d-L%d" % (GITHUB, change.release, change.source, change.first, change.last)
    mark = [Link(blame, change.release)]
    if change.added_hooks:
        plural = "s" if len(change.added_hooks) > 1 else ""
        names = joined([Link(hook_page(h), h)] if h in hooks else [h] for h in change.added_hooks)
        mark += [" (added hand-placed hook%s " % plural] + names + [")"]
    return mark


def class_homes(functions, classes):
    homes = {}
    for fn in functions:
        if fn["owner"] and fn["compiled"]:
            homes.setdefault(fn["owner"], fn["file"])
    for fn in functions:
        if fn["owner"] and fn["owner"] not in homes:
            info = classes.get(fn["owner"])
            homes[fn["owner"]] = info["file"] if info else fn["file"]
    return homes


def leaf_slug(fn):
    name = fn["name"]
    if name.startswith("operator"):
        return "operator_" + (generate.operator_leaf(name) or generate.cpp_name(name[len("operator") :]))
    return name


def assign_slugs(fns):
    """Unique even where Windows ignores case, which makes Total.html and total.html one file."""
    by_leaf = collections.defaultdict(list)
    for fn in fns:
        by_leaf[leaf_slug(fn)].append(fn)
    for leaf, group in by_leaf.items():
        if len(group) == 1:
            group[0]["slug"] = leaf
            continue
        taken = set()
        for fn in group:
            params = generate.cpp_name("_".join(p["type"] for p in fn["params"]) or "void")[:60]
            slug = "%s-%s%s" % (leaf, params, "-const" if fn["const"] else "")
            base, n = slug, 2
            while slug in taken:
                slug, n = "%s-%d" % (base, n), n + 1
            taken.add(slug)
            fn["slug"] = slug
    folded = collections.Counter(fn["slug"].lower() for fn in fns)
    for fn in fns:
        if folded[fn["slug"].lower()] > 1 or fn["slug"].lower() == "index":
            fn["slug"] += "-" + hashlib.sha1(fn["slug"].encode("utf-8")).hexdigest()[:6]


def snippet_start(data, def_start):
    """Takes in an #if just above, which may open a block whose #else holds another version of the signature."""
    start = data.rfind(b"\n", 0, def_start) + 1
    while start > 0:
        prev = data.rfind(b"\n", 0, start - 1) + 1
        line = data[prev:start].decode("cp1252", "replace").strip()
        if not (line.startswith("//") or IF_LINE.match(line)) or SEPARATOR.match(line):
            break
        start = prev
    return start
