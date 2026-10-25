"""What the docs pages say about the engine, from the clang pass and the generator's own planning."""

import bisect
import collections
import multiprocessing
import os
import re

import analyze
import build_vmc_reference as vmc
import collect
import common
import generate
import history
from paths import posix

HEADER_REASON = "written in a header"
PURE_REASON = "it has no code of its own: it is pure virtual, so the classes that override it have the code"


def is_hook(fn):
    return "hook_id" in fn


class Engine:
    def __init__(self, project):
        self.project = project
        self.texts, self.line_starts = {}, {}
        results = read_all(project)
        errors = analyze.project_errors(project, results)
        if errors:
            for path, line, message in sorted(errors)[:20]:
                print("  %s:%d %s" % (os.path.basename(path), line, message))
            raise SystemExit("docs: %d new parse errors outside function bodies, nothing written" % len(errors))
        self.body_errors = sum(1 for r in results for e in r["errors"] if e[3])
        self.functions, self.classes = merge(results, project)
        self.plan_hooks()
        self.by_usr = {}
        for fn in self.functions:
            self.by_usr.setdefault(fn["usr"], fn)
        self.callers, self.overridden_by = self.cross_references()
        self.hand_sites = self.scan_bodies()
        self.prepare_history()

    def text(self, rel):
        if rel not in self.texts:
            with open(os.path.join(self.project.root, rel), "rb") as f:
                self.texts[rel] = f.read()
        return self.texts[rel]

    def line_of(self, rel, offset):
        if rel not in self.line_starts:
            self.line_starts[rel] = [0] + [m.end() for m in re.finditer(b"\n", self.text(rel))]
        return bisect.bisect_right(self.line_starts[rel], offset)

    def plan_hooks(self):
        """The generator's own planning, so pages match the build's hooks; the hook list is never saved from here."""
        files, edits = generate.PathDict(), generate.PathDict()
        self.registry = generate.Registry(self.project.registry)
        cpp = [fn for fn in self.functions if fn["compiled"]]
        hooks, _, _ = generate.plan_hooks(cpp, self.project, files, edits, self.registry)
        for fn in hooks:
            fn["declarations"] = hook_declarations(fn, self.text(fn["file"]))
        self.unregistered_hooks = self.registry.added
        self.stale_registry_entries = len(self.registry.entries) - len(hooks)

    def cross_references(self):
        callers = collections.defaultdict(dict)
        overridden_by = collections.defaultdict(list)
        for fn in self.functions:
            for usr, _, _ in fn["refs"]:
                target = self.by_usr.get(usr)
                if target is not None and target is not fn:
                    callers[id(target)][id(fn)] = fn
            for usr in fn["overrides"]:
                if usr in self.by_usr:
                    overridden_by[id(self.by_usr[usr])].append(fn)
        return callers, overridden_by

    def prepare_history(self):
        """A function outside any class always carries its file, so its name never depends on whether another file
        holds a twin."""
        seen = set()
        for fn in self.functions:
            fn["history_key"] = generate.hook_key(fn)
            if not fn["owner"]:
                fn["history_key"] += " @" + posix(fn["file"])
            if fn["history_key"] in seen:
                raise SystemExit("docs: two functions share the history name %s" % fn["history_key"])
            seen.add(fn["history_key"])
            fn["source"] = posix(os.path.relpath(os.path.join(self.project.root, fn["file"]), common.REPO))
            fn["lines"] = (self.line_of(fn["file"], fn["def_start"]), self.line_of(fn["file"], fn["def_end"]))
            fn["added_in"], fn["changed_in"] = "", []

    def history_now(self):
        return {
            fn["history_key"]: history.Current(
                fn["fingerprint"], tuple(sorted({hook for hook, _ in fn["hand_hooks"]})), fn["source"], *fn["lines"]
            )
            for fn in self.functions
        }

    def apply_history(self, entries):
        for fn in self.functions:
            entry = entries.get(fn["history_key"])
            if entry:
                fn["added_in"], fn["changed_in"] = entry.added, entry.changes

    def callers_of(self, fn):
        return list(self.callers[id(fn)].values())

    def overriders_of(self, fn):
        return self.overridden_by[id(fn)]

    def scan_bodies(self):
        macros = event_macros(self.project.root)
        hand_sites = collections.defaultdict(list)
        for fn in self.functions:
            fn["hand_hooks"], fn["events"] = [], []
            if fn["body_start"] is None:
                continue
            data = self.text(fn["file"])
            body = data[fn["body_start"] : fn["def_end"]].decode("cp1252", "replace")
            code = vmc.code_only(body)
            fn["hand_hooks"] = self.hand_hooks_in(fn, data, code)
            fn["events"] = events_in(fn, body, code, macros)
            for hook, line in fn["hand_hooks"]:
                hand_sites[hook].append((fn, line))
        return hand_sites

    def hand_hooks_in(self, fn, data, code):
        found = []
        for m in generate.HAND_HOOK_CALL.finditer(data, fn["body_start"], fn["def_end"]):
            if live(fn, code, m.start() - fn["body_start"]):
                found.append((m.group(1).decode("ascii"), self.line_of(fn["file"], m.start())))
        return found


def read_all(project):
    jobs = [(project, rel) for rel in project.sources]
    with multiprocessing.Pool(max(1, min(len(jobs), os.cpu_count() or 4))) as pool:
        return pool.map(collect.collect_tu, jobs)


def merge(results, project):
    """An #include can spell a file name in another case, so names are taken from the disk."""
    disk = {}
    for dirpath, _, filenames in os.walk(project.root):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), project.root)
            disk[os.path.normcase(rel)] = rel
    sources = {os.path.normcase(rel) for rel in project.sources}
    functions, classes = {}, {}
    for r in results:
        for fn in r["functions"]:
            fn["file"] = disk.get(os.path.normcase(fn["file"]), fn["file"])
            fn["compiled"] = os.path.normcase(fn["file"]) in sources
            functions.setdefault(fn["usr"] + "@" + os.path.normcase(fn["file"]), fn)
        for c in r["classes"]:
            c["file"] = disk.get(os.path.normcase(c["file"]), c["file"])
            classes.setdefault(c["name"], c)
    functions = sorted(functions.values(), key=lambda f: (f["file"].lower(), f["def_start"]))
    for fn in functions:
        if fn["pure"]:
            fn["skip"] = [PURE_REASON]
        elif not fn["compiled"]:
            fn["skip"] = [HEADER_REASON]
    return functions, classes


def event_macros(root):
    macros = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".h"):
                with open(os.path.join(dirpath, name), encoding="latin-1") as f:
                    for macro, lua_name, _ in vmc.DEFINE.findall(f.read()):
                        macros[macro] = lua_name
    return macros


def events_in(fn, body, code, macros):
    names = [macros.get(m.group(2), m.group(2)) for m in vmc.VMC_CALL.finditer(body) if live(fn, code, m.start())]
    names += [m.group(2) for m in vmc.BASE_CALL.finditer(body) if live(fn, code, m.start())]
    return list(dict.fromkeys(names))


def live(fn, code, at):
    """at is an offset into the body, and code is the body with its comments and strings blanked out."""
    return code[at] != " " and not in_ranges(fn["body_start"] + at, fn["excluded"])


def in_ranges(offset, ranges):
    return any(s <= offset <= e for s, e in ranges)


def result_slot(result):
    # Mirrors the Slot of CivHookResult in host/CivHostHooks.h, which a plugin's result parameter must match.
    if result.endswith("&"):
        return result[:-1].rstrip() + "*&"
    value = re.sub(r"\s+const$", "", result)
    return re.sub(r"^const\s+(?=[^*&]*$)", "", value) + "&"


def hook_declarations(fn, data):
    params = [generate.param_parts(fn, data, i) for i in range(len(fn["params"]))]
    types = [t for t, _ in params]
    args = ["%s %s" % (t, "arg" + n[len("civ_p") :] if n.startswith("civ_p") else n) for t, n in params]
    self_type = []
    if fn["owner"] and not fn["static_method"]:
        self_type = ["%s%s*" % ("const " if fn["const"] else "", fn["owner"])]
    self_param = ["%s self" % t for t in self_type]
    void = fn["result"]["kind"] == "void"
    result = "void" if void else generate.return_text(fn, data)
    slot = [] if void else [result_slot(result) + " result"]
    original = "%s (*original)(%s)" % (result, ", ".join(self_type + types))
    name = fn["hook_name"]
    lines = [
        "static bool Before%s(%s);" % (name, ", ".join(self_param + args + slot)),
        "static void After%s(%s);" % (name, ", ".join(self_param + args + slot)),
        "static %s Replace%s(%s);" % (result, name, ", ".join([original] + self_param + args)),
        "",
    ]
    for kind, prefix in (("BEFORE", "Before"), ("AFTER", "After"), ("REPLACE", "Replace")):
        lines.append(
            "host->RegisterHook(host->pluginIndex, CivHooks::%s::ID, CIV_HOOK_%s, (void*)&%s%s);"
            % (name, kind, prefix, name)
        )
    return "\n".join(lines) + "\n"
