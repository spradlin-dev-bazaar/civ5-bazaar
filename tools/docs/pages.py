"""The HTML of every docs page and of the search index."""

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
from model import is_hook
from paths import HOME_PAGE, HOOKS_PAGE, file_dir, file_page, folder_page, hook_page, posix, rel_link

SEPARATOR = re.compile(r"^\s*([/*=-]\s*){4,}$")
IF_LINE = re.compile(r"^#\s*if")
BRANCH_LINE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b")
FOLD_AFTER = 30
GITHUB = "https://github.com/spradlin-dev/civ5-bazaar"
REPLACEMENT_WARNING = (
    '<p class="warn">A replacement for this function that does not call <code>original</code> stops these hooks from '
    "running.</p>"
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
        self.pages = {}
        for fn in engine.functions:
            self.function_page(fn)
        self.class_pages()
        self.file_pages()
        self.folder_pages()
        self.hook_pages(*handwritten.hook_descriptions(inputs.hand_hooks, engine.hand_sites))
        self.home_page(handwritten.task_guide(inputs.task_guide, self.targets))

    def class_dir(self, owner):
        return "%s/%s" % (file_dir(self.homes[owner]), owner.replace("::", "."))

    def class_page(self, owner):
        return self.class_dir(owner) + "/index.html"

    def add(self, path, title, trail, body):
        trail = [(label, None if href == path else rel_link(path, href)) for label, href in trail]
        self.pages[path] = render.page(title, "../" * path.count("/"), trail, body)

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

    def function_link(self, path, fn):
        return render.link(rel_link(path, fn["page"]), fn["title"])

    # Function pages.

    def code_html(self, fn):
        data = self.engine.text(fn["file"])
        start = snippet_start(data, fn["def_start"])
        raw = data[start : fn["def_end"]].decode("cp1252", "replace")
        text = raw.replace("\r\n", "\n")
        first = self.engine.line_of(fn["file"], start)
        links = self.code_links(fn, start, raw)
        greyed = self.greyed_lines(fn, first, text.split("\n"))
        marks = {line - first: "hand-placed hook: %s" % hook for hook, line in fn["hand_hooks"]}
        return render.code_block(text, first, links=links, greyed=greyed, marks=marks)

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
                links[at] = (rel_link(fn["page"], target["page"]), target["title"])
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
        path = fn["page"]
        shown = render.esc(posix(fn["file"]))
        if fn["file"] in self.listed_files:
            shown = render.link(rel_link(path, file_page(fn["file"])), posix(fn["file"]))
        rows = [("Defined in", "%s, line %d" % (shown, fn["line"]))]
        if fn["owner"]:
            rows.append(("Class", render.link(rel_link(path, self.class_page(fn["owner"])), fn["owner"])))
        if is_hook(fn):
            rows.append(("Hook name", "<code>CivHooks::%s</code>" % render.esc(fn["hook_name"])))
        else:
            rows.append(("Not a hook point", render.esc("; ".join(fn["skip"]))))
        rows.append(("Added in", render.esc(fn["added_in"])))
        marks = [change_mark(c, path, self.engine.hand_sites) for c in fn["changed_in"]]
        rows.append(("Changed in", ", ".join(marks)))
        overrides = [self.engine.by_usr[u] for u in fn["overrides"] if u in self.engine.by_usr]
        overriders = sorted(self.engine.overriders_of(fn), key=lambda f: f["title"])
        rows.append(("Overrides", ", ".join(self.function_link(path, f) for f in overrides)))
        rows.append(("Overridden by", ", ".join(self.function_link(path, f) for f in overriders)))
        if fn["events"]:
            rows.append(("Lua events", ", ".join("<code>GameEvents.%s</code>" % render.esc(e) for e in fn["events"])))
        return rows

    def hand_hook_section(self, fn):
        if not fn["hand_hooks"]:
            return ""
        path = fn["page"]
        items = []
        for hook, line in fn["hand_hooks"]:
            hook_link = render.link(rel_link(path, hook_page(hook)), hook)
            items.append("%s, %s" % (hook_link, render.link("#L%d" % line, "line %d" % line)))
        warning = REPLACEMENT_WARNING if is_hook(fn) else ""
        return render.section("Hand-placed hooks inside", warning + render.entry_list(items))

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
                items.append((target["title"].lower(), self.function_link(fn["page"], target)))
            else:
                items.append((qualified.lower(), "<code>%s</code>" % render.esc(qualified)))
        return render.entry_list([item for _, item in sorted(items)])

    def function_page(self, fn):
        path = fn["page"]
        body = "<h1>%s</h1>" % render.esc(fn["title"]) + render.facts(self.fact_rows(fn)) + self.notes.get(path, "")
        body += self.hand_hook_section(fn)
        if is_hook(fn):
            body += render.section("Hooks", render.code_block(fn["declarations"], None), "hooks")
        body += render.section("Code", self.code_html(fn), "code")
        body += render.section("Calls", self.calls_list(fn))
        callers = sorted(self.engine.callers_of(fn), key=lambda f: (f["file"].lower(), f["title"]))
        summary = "%d functions in %d files" % (len(callers), len({f["file"] for f in callers}))
        caller_links = [self.function_link(path, f) for f in callers]
        body += render.section("Called by", render.entry_list(caller_links, FOLD_AFTER, summary))
        self.add(path, fn["title"], self.scope_trail(fn) + [(fn["name"], path)], body)

    # Class, file and folder pages.

    def scope_listing(self, path, fns):
        items = []
        for fn in sorted(fns, key=lambda f: (f["name"].lower(), f["title"])):
            badge = "" if is_hook(fn) else ' <span class="badge">not a hook point</span>'
            label = fn["displayname"] + (" const" if fn["const"] else "")
            items.append(render.link(rel_link(path, fn["page"]), label, fn["title"]) + badge)
        return render.entry_list(items)

    def class_link(self, path, owner):
        if owner in self.homes:
            return render.link(rel_link(path, self.class_page(owner)), owner)
        return "<code>%s</code>" % render.esc(owner)

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
                rows.append(("Declared in", "%s, line %d" % (render.esc(posix(info["file"])), info["line"])))
                rows.append(("Based on", ", ".join(self.class_link(path, b) for b in info["bases"])))
            rows.append(("Classes based on it", ", ".join(self.class_link(path, d) for d in sorted(derived[owner]))))
            body = "<h1>%s</h1>" % render.esc(owner) + render.facts(rows) + self.summaries.get(owner, "")
            body += render.section("Functions", self.scope_listing(path, fns))
            self.add(path, owner, self.file_trail(self.homes[owner]) + [(owner, path)], body)

    def file_pages(self):
        free = collections.defaultdict(list)
        for fn in self.engine.functions:
            if not fn["owner"]:
                free[fn["file"]].append(fn)
        homed = collections.defaultdict(list)
        for owner, rel in self.homes.items():
            homed[rel].append(owner)
        for rel in self.listed_files:
            path = file_page(rel)
            classes = [render.link(rel_link(path, self.class_page(c)), c) for c in sorted(homed[rel], key=str.lower)]
            body = "<h1>%s</h1>" % render.esc(os.path.basename(rel))
            body += render.section("Classes", render.entry_list(classes))
            body += render.section("Functions", self.scope_listing(path, free[rel]))
            self.add(path, os.path.basename(rel), self.file_trail(rel), body)

    def folder_pages(self):
        folders = collections.defaultdict(lambda: (set(), set()))
        for rel in self.listed_files:
            parts = posix(rel).split("/")
            folders["/".join(parts[:-1])][1].add(rel)
            for i in range(len(parts) - 1):
                folders["/".join(parts[:i])][0].add("/".join(parts[: i + 1]))
        for folder, (subfolders, files) in folders.items():
            path = folder_page(folder)
            items = [
                render.link(rel_link(path, folder_page(s)), s.split("/")[-1] + "/")
                for s in sorted(subfolders, key=str.lower)
            ]
            items += [
                render.link(rel_link(path, file_page(f)), os.path.basename(f)) for f in sorted(files, key=str.lower)
            ]
            name = folder.split("/")[-1] if folder else os.path.basename(self.engine.project.root)
            body = "<h1>%s</h1>" % render.esc(name) + render.entry_list(items)
            self.add(path, folder or "Game code", self.folder_trail(folder), body)

    # Hand-placed hook pages and the home page.

    def hook_pages(self, intro, descriptions):
        items = []
        for hook in sorted(descriptions):
            path = hook_page(hook)
            fires = []
            for fn, line in sorted(self.engine.hand_sites[hook], key=lambda s: (s[0]["file"].lower(), s[1])):
                line_link = render.link(rel_link(path, fn["page"]) + "#L%d" % line, "line %d" % line)
                fires.append("%s, %s" % (self.function_link(path, fn), line_link))
            body = "<h1>%s</h1>" % render.esc(hook) + descriptions[hook]
            body += render.section("Where it fires", render.entry_list(fires))
            self.add(path, hook, [("Hand-placed hooks", HOOKS_PAGE), (hook, path)], body)
            items.append(render.link(rel_link(HOOKS_PAGE, path), hook))
        body = "<h1>Hand-placed hooks</h1>" + intro + render.entry_list(items)
        self.add(HOOKS_PAGE, "Hand-placed hooks", [("Hand-placed hooks", HOOKS_PAGE)], body)

    def home_page(self, guide):
        functions = self.engine.functions
        counts = " (%d functions, %d of them hook points)" % (len(functions), sum(1 for fn in functions if is_hook(fn)))
        links = [
            render.link(folder_page(""), "The game's code") + counts,
            render.link(HOOKS_PAGE, "Hand-placed hooks"),
        ]
        if self.summaries:
            links.append("Main classes: " + ", ".join(render.link(self.class_page(c), c) for c in self.summaries))
        intro = (
            "<p>Every function in the game's code, with its code, the functions it calls and the functions that call "
            "it, and how to hook it from a plugin.</p>"
        )
        body = "<h1>%s</h1>%s%s" % (render.esc(render.SITE_NAME), intro, render.entry_list(links)) + guide
        self.add(HOME_PAGE, render.SITE_NAME, [], body)

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


def change_mark(change, page, hooks):
    """hooks: the hand-placed hooks the engine calls today, the ones that still have a page to link to."""
    blame = "%s/blame/v%s/%s#L%d-L%d" % (GITHUB, change.release, change.source, change.first, change.last)
    mark = render.link(blame, change.release)
    if change.added_hooks:
        plural = "s" if len(change.added_hooks) > 1 else ""
        names = [
            render.link(rel_link(page, hook_page(h)), h) if h in hooks else render.esc(h) for h in change.added_hooks
        ]
        mark += " (added hand-placed hook%s %s)" % (plural, ", ".join(names))
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
