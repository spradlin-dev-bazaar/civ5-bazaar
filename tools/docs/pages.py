"""Where each docs page goes, and the HTML of every page and of the search index."""

import bisect
import collections
import hashlib
import json
import os
import posixpath
import re

import markdown

import generate
import render
from model import is_hook

SEPARATOR = re.compile(r"^[\s/*=-]*$")
IF_LINE = re.compile(r"^#\s*if")
BRANCH_LINE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b")
FOLD_AFTER = 30
HOME_PAGE = "index.html"
HOOKS_PAGE = "hooks/index.html"
GITHUB = "https://github.com/spradlin-dev/civ5-bazaar"


def file_dir(rel):
    return "reference/" + rel.replace(os.sep, "/")


def file_page(rel):
    return file_dir(rel) + "/index.html"


def folder_page(folder):
    return "reference/%sindex.html" % (folder + "/" if folder else "")


def hook_page(hook):
    return "hooks/%s.html" % hook


def rel_link(page, target):
    return posixpath.relpath(target, posixpath.dirname(page) or ".")


class Site:
    def __init__(self, engine, hand_hooks_md):
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
        self.pages = {}
        for fn in engine.functions:
            self.function_page(fn)
        self.class_and_file_pages()
        self.folder_pages()
        self.hook_pages(hand_hooks_md)
        self.home_page()

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
        folder = posixpath.dirname(rel.replace(os.sep, "/"))
        return self.folder_trail(folder) + [(os.path.basename(rel), file_page(rel))]

    def scope_trail(self, fn):
        if fn["owner"]:
            return self.file_trail(self.homes[fn["owner"]]) + [(fn["owner"], self.class_page(fn["owner"]))]
        return self.file_trail(fn["file"])

    def function_link(self, path, fn):
        return render.link(rel_link(path, fn["page"]), fn["title"])

    # Function pages.

    def code_view(self, fn):
        engine = self.engine
        data = engine.text(fn["file"])
        start = snippet_start(data, fn["def_start"])
        raw = data[start : fn["def_end"]].decode("cp1252", "replace")
        crlf = [m.start() for m in re.finditer("\r\n", raw)]
        text = raw.replace("\r\n", "\n")
        lines = text.split("\n")
        first = engine.line_of(fn["file"], start)
        targets = collections.defaultdict(dict)
        for usr, offset, _ in fn["refs"]:
            target = engine.by_usr.get(usr)
            if offset is not None and target is not None and start <= offset < fn["def_end"]:
                targets[offset][id(target)] = target
        links = {}
        for offset, found in targets.items():
            if len(found) == 1:
                target = next(iter(found.values()))
                at = offset - start - bisect.bisect_left(crlf, offset - start)
                links[at] = (rel_link(fn["page"], target["page"]), target["title"])
        greyed = set()
        for s, e in fn["excluded"]:
            for n in range(engine.line_of(fn["file"], s), engine.line_of(fn["file"], e) + 1):
                i = n - first
                if 0 <= i < len(lines) and not BRANCH_LINE.match(lines[i]):
                    greyed.add(i)
        marks = {line - first: "hand-placed hook: %s" % hook for hook, line in fn["hand_hooks"]}
        return text, first, links, greyed, marks

    def fact_rows(self, fn):
        path = fn["page"]
        shown = render.esc(fn["file"].replace(os.sep, "/"))
        if fn["file"] in self.listed_files:
            shown = render.link(rel_link(path, file_page(fn["file"])), fn["file"].replace(os.sep, "/"))
        rows = [("Defined in", "%s, line %d" % (shown, fn["line"]))]
        if fn["owner"]:
            rows.append(("Class", render.link(rel_link(path, self.class_page(fn["owner"])), fn["owner"])))
        if is_hook(fn):
            rows.append(("Hook name", "<code>CivHooks::%s</code>" % render.esc(fn["hook_name"])))
        else:
            rows.append(("Not a hook point", render.esc("; ".join(fn["skip"]))))
        rows.append(("Added in", render.esc(fn["added_in"])))
        rows.append(("Changed in", ", ".join(change_mark(c) for c in fn["changed_in"])))
        overrides = [self.engine.by_usr[u] for u in fn["overrides"] if u in self.engine.by_usr]
        overriders = sorted(self.engine.overriders_of(fn), key=lambda f: f["title"])
        rows.append(("Overrides", ", ".join(self.function_link(path, f) for f in overrides)))
        rows.append(("Overridden by", ", ".join(self.function_link(path, f) for f in overriders)))
        if fn["events"]:
            rows.append(("Lua events", ", ".join("<code>GameEvents.%s</code>" % render.esc(e) for e in fn["events"])))
        return rows

    def hand_hook_section(self, fn):
        path = fn["page"]
        items = []
        for hook, line in fn["hand_hooks"]:
            hook_link = render.link(rel_link(path, hook_page(hook)), hook)
            items.append("%s, %s" % (hook_link, render.link("#L%d" % line, "line %d" % line)))
        warning = ""
        if is_hook(fn):
            warning = (
                '<p class="warn">A replacement for this function that does not call <code>original</code> stops these '
                "hooks from running.</p>"
            )
        return render.section("Hand-placed hooks inside", warning + render.entry_list(items) if items else "")

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
        body = "<h1>%s</h1>" % render.esc(fn["title"]) + render.facts(self.fact_rows(fn))
        body += self.hand_hook_section(fn)
        if is_hook(fn):
            body += render.section("Hooks", render.code_block(fn["declarations"], None), "hooks")
        text, first, links, greyed, marks = self.code_view(fn)
        body += render.section("Code", render.code_block(text, first, links=links, greyed=greyed, marks=marks), "code")
        body += render.section("Calls", self.calls_list(fn))
        callers = sorted(self.engine.callers_of(fn), key=lambda f: (f["file"].lower(), f["title"]))
        summary = "%d functions in %d files" % (len(callers), len({f["file"] for f in callers}))
        links = [self.function_link(path, f) for f in callers]
        body += render.section("Called by", render.entry_list(links, FOLD_AFTER, summary))
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

    def class_and_file_pages(self):
        by_owner = collections.defaultdict(list)
        free = collections.defaultdict(list)
        for fn in self.engine.functions:
            (by_owner[fn["owner"]] if fn["owner"] else free[fn["file"]]).append(fn)
        homed = collections.defaultdict(list)
        for owner, fns in by_owner.items():
            homed[self.homes[owner]].append(owner)
            path = self.class_page(owner)
            info = self.engine.classes.get(owner)
            rows = []
            if info:
                declared = "%s, line %d" % (render.esc(info["file"].replace(os.sep, "/")), info["line"])
                rows.append(("Declared in", declared))
                rows.append(("Based on", ", ".join(self.class_link(path, b) for b in info["bases"])))
            derived = sorted(name for name, c in self.engine.classes.items() if owner in c["bases"])
            rows.append(("Classes based on it", ", ".join(self.class_link(path, d) for d in derived)))
            body = "<h1>%s</h1>" % render.esc(owner) + render.facts(rows)
            body += render.section("Functions", self.scope_listing(path, fns))
            self.add(path, owner, self.file_trail(self.homes[owner]) + [(owner, path)], body)
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
            parts = rel.replace(os.sep, "/").split("/")
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

    def hook_pages(self, hand_hooks_md):
        with open(hand_hooks_md, encoding="utf-8-sig") as f:
            parts = re.split(r"^## (.+?)\s*$", f.read(), flags=re.M)
        intro, sections = re.sub(r"\A\s*# .*\n", "", parts[0]), dict(zip(parts[1::2], parts[2::2]))
        sites = self.engine.hand_sites
        unknown = sorted(set(sites) - set(sections))
        if unknown:
            raise SystemExit(
                "docs: hand-placed hooks the engine calls that have no section in %s: %s"
                % (hand_hooks_md, ", ".join(unknown))
            )
        unused = sorted(set(sections) - set(sites))
        if unused:
            raise SystemExit(
                "docs: hand-placed hooks in %s that no engine function calls: %s" % (hand_hooks_md, ", ".join(unused))
            )
        items = []
        for hook in sorted(sections):
            path = hook_page(hook)
            fires = []
            for fn, line in sorted(sites[hook], key=lambda s: (s[0]["file"].lower(), s[1])):
                line_link = render.link(rel_link(path, fn["page"]) + "#L%d" % line, "line %d" % line)
                fires.append("%s, %s" % (self.function_link(path, fn), line_link))
            body = "<h1>%s</h1>" % render.esc(hook) + to_html(sections[hook])
            body += render.section("Where it fires", render.entry_list(fires))
            self.add(path, hook, [("Hand-placed hooks", HOOKS_PAGE), (hook, path)], body)
            items.append(render.link(rel_link(HOOKS_PAGE, path), hook))
        body = "<h1>Hand-placed hooks</h1>" + to_html(intro) + render.entry_list(items)
        self.add(HOOKS_PAGE, "Hand-placed hooks", [("Hand-placed hooks", HOOKS_PAGE)], body)

    def home_page(self):
        functions = self.engine.functions
        counts = " (%d functions, %d of them hook points)" % (len(functions), sum(1 for fn in functions if is_hook(fn)))
        links = [
            render.link(folder_page(""), "The game's code") + counts,
            render.link(HOOKS_PAGE, "Hand-placed hooks"),
        ]
        intro = (
            "<p>Every function in the game's code, with its code, the functions it calls and the functions that call "
            "it, and how to hook it from a plugin.</p>"
        )
        body = "<h1>%s</h1>%s%s" % (render.esc(render.SITE_NAME), intro, render.entry_list(links))
        self.add(HOME_PAGE, render.SITE_NAME, [], body)

    # The search index.

    def search_rows(self):
        rows = [[fn["title"], fn["page"]] for fn in self.engine.functions]
        rows += [[owner + " (class)", self.class_page(owner)] for owner in sorted(self.homes)]
        rows += [[os.path.basename(f) + " (file)", file_page(f)] for f in sorted(self.listed_files)]
        return rows

    def search_index(self):
        return "window.BAZAAR_INDEX = %s;\n" % json.dumps(self.search_rows(), separators=(",", ":"))


def change_mark(change):
    blame = "%s/blame/v%s/%s#L%d-L%d" % (GITHUB, change.release, change.source, change.first, change.last)
    mark = render.link(blame, change.release)
    if change.added_hooks:
        plural = "s" if len(change.added_hooks) > 1 else ""
        mark += " (added hand-placed hook%s %s)" % (plural, render.esc(", ".join(change.added_hooks)))
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


def to_html(md):
    return markdown.markdown(md, extensions=["tables", "fenced_code"])
