"""Turn a project's analysis.json into a hooked copy of its sources.

The committed source is never changed. Every file is mirrored into the project's build folder with
#line directives pointing back at the original, so compiler errors, crash stacks and the debugger
all name the real files. Inserted text always stays on its line, so line numbers never shift.

Hook ids live in a registry file: an id, once given, always means the same function, so plugins
built against an older host keep working.
"""

import glob
import json
import os
import re
import shutil
import sys
import tempfile

import analyze
import common

ID_PLACEHOLDER = "\0HOOK_ID\0"
INCLUDE_LINE = re.compile(rb"^[ \t]*#[ \t]*(?:include\b|pragma[ \t]+once\b)[^\n]*", re.MULTILINE)
QUOTED_INCLUDE = re.compile(rb'^([ \t]*#[ \t]*include[ \t]*")([^"\r\n]+)"', re.MULTILINE)
DIRECTIVE = re.compile(r"^[ \t]*#[ \t]*(\w+)")
HAND_HOOK_CALL = re.compile(rb"\bCivHand([A-Z][A-Za-z0-9]*)\s*\(")
CALLING_CONVENTIONS = {"__stdcall", "__cdecl", "__thiscall", "__fastcall", "DLLCALL", "WINAPI", "CALLBACK", "APIENTRY"}
LEADING_SPECIFIERS = {"static", "inline", "__inline", "__forceinline", "extern", "virtual", "explicit"}
OPERATOR_NAMES = {
    "operator==": "eq",
    "operator!=": "ne",
    "operator<": "lt",
    "operator>": "gt",
    "operator<=": "le",
    "operator>=": "ge",
    "operator=": "assign",
    "operator+": "add",
    "operator-": "sub",
    "operator*": "mul",
    "operator/": "div",
    "operator%": "mod",
    "operator+=": "add_assign",
    "operator-=": "sub_assign",
    "operator*=": "mul_assign",
    "operator/=": "div_assign",
    "operator[]": "index",
    "operator()": "call",
    "operator<<": "shl",
    "operator>>": "shr",
    "operator!": "not",
    "operator&": "bitand",
    "operator|": "bitor",
    "operator^": "xor",
    "operator&=": "and_assign",
    "operator|=": "or_assign",
    "operator^=": "xor_assign",
    "operator<<=": "shl_assign",
    "operator>>=": "shr_assign",
    "operator&&": "and",
    "operator||": "or",
    "operator++": "inc",
    "operator--": "dec",
    "operator->": "arrow",
    "operator~": "compl",
}


class Skip(Exception):
    pass


class PathDict(dict):
    """Keys are file paths compared the way Windows does: case-insensitively."""

    @staticmethod
    def _key(path):
        return common.path_key(path)

    def __getitem__(self, path):
        return dict.__getitem__(self, self._key(path))

    def __setitem__(self, path, value):
        dict.__setitem__(self, self._key(path), value)

    def __contains__(self, path):
        return dict.__contains__(self, self._key(path))

    def get(self, path, default=None):
        return dict.get(self, self._key(path), default)

    def setdefault(self, path, default=None):
        return dict.setdefault(self, self._key(path), default)


def c_string(path):
    return '"' + path.replace("\\", "\\\\") + '"'


def operator_leaf(name):
    """The identifier-safe word for an operator (`eq` for `operator==`), or None if unknown."""
    return OPERATOR_NAMES.get(re.sub(r"\s+", "", name))


def orig_name(fn):
    if fn["name"].startswith("operator"):
        return "CivOrigOp_" + operator_leaf(fn["name"])
    return "CivOrig_" + fn["name"]


def read(path):
    with open(path, "rb") as f:
        return f.read()


def cached_read(files, path):
    if path not in files:
        files[path] = read(path)
    return files[path]


def text(data, start, end):
    return data[start:end].decode("cp1252")


def top_level_equals(s):
    depth = 0
    for i, ch in enumerate(s):
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        elif ch == "=" and depth == 0:
            return i
    return 0


def param_parts(fn, data, index):
    """(type text, name) for one parameter as written in the definition."""
    p = fn["params"][index]
    raw = text(data, p["start"], p["end"])
    if p["name"]:
        rel = p["loc"] - p["start"]
        if raw[rel : rel + len(p["name"])] != p["name"]:
            raise Skip("parameter name not where expected")
        type_text = raw[:rel] + raw[rel + len(p["name"]) :]
    else:
        type_text = raw
    if top_level_equals(type_text):
        type_text = type_text[: top_level_equals(type_text)]
    type_text = " ".join(type_text.split())
    if not type_text:
        raise Skip("empty parameter type")
    return type_text, p["name"] or ("civ_p%d" % index)


def return_text(fn, data):
    before = text(data, fn["def_start"], fn["name_start"])
    before = re.sub(r"(\s*\b\w+\s*(<[^<>]*>)?\s*::\s*)+$", "", before)
    words = [w for w in before.split() if w not in LEADING_SPECIFIERS and w not in CALLING_CONVENTIONS]
    result = re.sub(r"__declspec\s*\([^)]*\)", "", " ".join(words)).strip()
    if not result:
        raise Skip("could not read return type")
    return result


def wrapper_signature(fn, data, keep_defaults=False):
    """The definition's own text up to its body, with names added for unnamed parameters."""
    start = fn["def_start"]
    sig = bytearray(data[start : fn["body_start"]])
    for i in reversed(range(len(fn["params"]))):
        p = fn["params"][i]
        eq = top_level_equals(text(data, p["start"], p["end"]))
        if eq and not keep_defaults:
            del sig[p["start"] - start + eq : p["end"] - start]
        if not p["name"]:
            if eq:
                raise Skip("unnamed parameter with a default value")
            at = p["end"] - start
            sig[at:at] = (" civ_p%d" % i).encode("cp1252")
    return active_version(sig.decode("cp1252")).rstrip()


def active_version(sig):
    """The signature without other versions written around it with #if. The body is always active, so an #if the
    signature leaves open is the branch it is in, and an unmatched #else, #elif or #endif starts another version."""
    kept, open_ifs = [], []
    for line in sig.split("\n"):
        m = DIRECTIVE.match(line)
        word = m.group(1) if m else None
        if word in ("if", "ifdef", "ifndef"):
            open_ifs.append([len(kept), False])
        elif word in ("else", "elif", "endif") and not open_ifs:
            break
        elif word in ("else", "elif"):
            open_ifs[-1][1] = True
        elif word == "endif":
            open_ifs.pop()
        kept.append(line)
    for at, has_other_branch in reversed(open_ifs):
        if has_other_branch:
            raise Skip("signature split across #if branches")
        del kept[at]
    return "\n".join(kept)


def collapse(code):
    code = re.sub(r"//[^\n]*", "", code)
    return " ".join(code.split())


def one_line(sig):
    """The signature collapsed onto one line, which an #if inside it cannot be."""
    if any(DIRECTIVE.match(line) for line in sig.split("\n")):
        raise Skip("#if inside a free function's signature")
    return collapse(sig)


def qualifier_start(fn, data):
    """Offset where a written qualifier such as `CvTypes::` begins, or the name's own start."""
    before = text(data, fn["def_start"], fn["name_start"])
    m = re.search(r"(\b\w+\s*::\s*)+$", before)
    return fn["def_start"] + m.start() if m else fn["name_start"]


def namespace_open(names):
    return "".join("namespace %s{ " % (n + " " if n else "") for n in names)


def namespace_close(names):
    return "}" * len(names)


def free_function_declarations(fn, data, exported):
    """Declarations a renamed free function needs ahead of its definition, on the same line."""
    q = qualifier_start(fn, data)
    if q != fn["name_start"]:
        sig = wrapper_signature(fn, data)
        rel_q = q - fn["def_start"]
        rel_end = fn["name_end"] - fn["def_start"]
        orig_decl = one_line(sig[:rel_q] + orig_name(fn) + sig[rel_end:]) + ";"
        semantic, lexical = fn["namespaces"], fn["lex_namespaces"]
        if semantic[: len(lexical)] != lexical:
            raise Skip("qualified definition outside its namespace")
        inner = semantic[len(lexical) :]
        if not inner:
            raise Skip("qualified free function in its own namespace")
        return namespace_open(inner) + orig_decl + " " + namespace_close(inner) + " "
    if fn["decl"] is None:
        marker = "CIV_HOST_API " if exported else ""
        return marker + one_line(wrapper_signature(fn, data, keep_defaults=True)) + "; "
    return ""


def thunk_lines(is_void, plugin_args):
    pa = ", ".join(plugin_args)
    pa_slot = ", ".join(plugin_args + ["c.res->value"])
    pa_orig = ", ".join(["&civ_C::Original"] + plugin_args)
    head = "\t\tstatic void %s(void* p) { civ_C& c = *static_cast<civ_C*>(p); "
    if is_void:
        return [
            head % "Before" + "c.civ_h.veto = reinterpret_cast<BeforeFn>(c.civ_h.fn)(%s); }" % pa,
            head % "Replace" + "reinterpret_cast<ReplaceFn>(c.civ_h.fn)(%s); }" % pa_orig,
            head % "After" + "reinterpret_cast<AfterFn>(c.civ_h.fn)(%s); }" % pa,
        ]
    return [
        head % "Before" + "c.civ_h.veto = reinterpret_cast<BeforeFn>(c.civ_h.fn)(%s); }" % pa_slot,
        head % "Replace" + "c.res->Set(reinterpret_cast<ReplaceFn>(c.civ_h.fn)(%s)); }" % pa_orig,
        head % "After" + "reinterpret_cast<AfterFn>(c.civ_h.fn)(%s); }" % pa_slot,
    ]


def original_line(fn, self_type, types, result):
    """The helper a replacement receives first, so it can run the unhooked original."""
    params = (["%s s" % self_type] if self_type else []) + [
        "CivHookArg< %s >::Type o%d" % (t, i) for i, t in enumerate(types)
    ]
    call = "%s%s(%s)" % ("s->" if self_type else "", orig_name(fn), ", ".join("o%d" % i for i in range(len(types))))
    body = call if result == "void" else "return " + call
    return "\t\tstatic %s Original(%s) { CivHookOriginalCalled(); %s; }" % (result, ", ".join(params), body)


def hooked_lines(is_void, self_type, types, names, call):
    """The slow path: run every hook around the original. Kept out of the wrapper so the wrapper stays
    small enough for the compiler to inline when no plugin hooks the function."""
    params = (["%s civ_self" % self_type] if self_type else []) + [
        "CivHookArg< %s >::Type %s" % (t, n) for t, n in zip(types, names)
    ]
    init = ["{ 0, false }"] + (["civ_self"] if self_type else []) + ["&" + n for n in names]
    lines = ["\t\tstatic __declspec(noinline) %s Hooked(%s)" % ("void" if is_void else "civ_R", ", ".join(params))]
    lines += ["\t\t{", "\t\t\tCivHookPoint& civ_hp = g_CivHookPoints[%s];" % ID_PLACEHOLDER]
    if not is_void:
        lines.append("\t\t\tciv_Res civ_res;")
        init.append("&civ_res")
    lines.append("\t\t\tciv_C civ_c = { %s };" % ", ".join(init))
    lines.append(
        "\t\t\tif (!CivHookRunBefore(civ_hp, %(id)s, &civ_C::Before, &civ_c)"
        " && !CivHookRunReplace(civ_hp, %(id)s, &civ_C::Replace, &civ_c))" % {"id": ID_PLACEHOLDER}
    )
    if is_void:
        lines.append("\t\t\t\t%s;" % call)
    else:
        # Only a reference result can be empty: one a veto left unset runs the original after all (CivHookResult).
        lines += ["\t\t\t\tciv_res.Set(%s);" % call, "\t\t\tif (civ_res.Empty())", "\t\t\t\tciv_res.Set(%s);" % call]
    lines.append("\t\t\tCivHookRunAfter(civ_hp, %s, &civ_C::After, &civ_c);" % ID_PLACEHOLDER)
    if not is_void:
        lines.append("\t\t\treturn civ_res.Get();")
    lines.append("\t\t}")
    return lines


def wrapper_code(fn, data, src_path, exported):
    """The wrapper that takes the function's name, with ID_PLACEHOLDER standing for its hook id."""
    params = [param_parts(fn, data, i) for i in range(len(fn["params"]))]
    types = [t for t, _ in params]
    names = [n for _, n in params]
    is_void = fn["result"]["kind"] == "void"
    self_type = None
    if fn["class"] is not None and not fn["static_method"]:
        self_type = ("const %s*" % fn["class"]) if fn["const"] else ("%s*" % fn["class"])
    plugin_params = ([self_type] if self_type else []) + types
    plugin_args = (["c.self"] if self_type else []) + ["*c.a%d" % i for i in range(len(types))]
    inner_call = "%s%s(%s)" % ("civ_self->" if self_type else "", orig_name(fn), ", ".join(names))

    lines = ["#line %d %s" % (fn["line"], c_string(src_path))]
    lines.append(("CIV_HOST_API " if exported else "") + wrapper_signature(fn, data))
    lines.append("{")
    if not is_void:
        lines.append("\ttypedef %s civ_R;" % return_text(fn, data))
        lines.append("\ttypedef CivHookResult< civ_R > civ_Res;")
    result = "void" if is_void else "civ_R"
    lines += ["\tstruct civ_C", "\t{"]
    lines += ["\t\t" + typedef for typedef in hook_type_lines(result, plugin_params, "Fn")]
    lines.append("\t\tCivHookCtx civ_h;")
    if self_type:
        lines.append("\t\t%s self;" % self_type)
    lines += ["\t\tCivHookArg< %s >::Ptr a%d;" % (t, i) for i, t in enumerate(types)]
    if not is_void:
        lines.append("\t\tciv_Res* res;")
    lines.append(original_line(fn, self_type, types, result))
    lines += thunk_lines(is_void, plugin_args)
    lines += hooked_lines(is_void, self_type, types, names, inner_call)
    lines.append("\t};")
    lines.append("\tif (!g_CivHookActive[%s])" % ID_PLACEHOLDER)
    lines.append("\t\treturn %s(%s);" % (orig_name(fn), ", ".join(names)))
    lines.append("\treturn civ_C::Hooked(%s);" % ", ".join((["this"] if self_type else []) + names))
    lines.append("}")
    return "\n".join(lines) + "\n"


def orig_declaration(fn, files):
    """Text declaring the renamed original inside its class, and where to insert it."""
    decl = fn["decl"]
    path = decl["file"]
    data = cached_read(files, path)
    toks = decl["tokens"]
    out = []
    i = 0
    found = False
    while i < len(toks):
        spelling, off = toks[i]
        if off != decl["name_offset"] or found:
            out.append(spelling)
            i += 1
            continue
        if fn["name"].startswith("operator"):
            target = re.sub(r"\s+", "", fn["name"])
            written = "operator"
            i += 1
            while i < len(toks) and len(written) < len(target):
                written += toks[i][0]
                i += 1
            if written != target:
                raise Skip("operator declaration not understood")
        else:
            if spelling != fn["name"]:
                raise Skip("declaration not written literally")
            i += 1
        out.append(orig_name(fn))
        found = True
    if not found:
        raise Skip("declaration name not found")
    if len(out) >= 2 and out[-2:] == ["=", "0"]:
        out = out[:-2]
    pos = decl["extent_end"]
    while pos < len(data) and data[pos : pos + 1] in (b" ", b"\t"):
        pos += 1
    if data[pos : pos + 1] != b";":
        raise Skip("declaration does not end where expected")
    # Inserted before the `;`, so it can never share an offset with an export marker on the next declaration.
    return path, pos, "; " + " ".join(out)


def named_scopes(fn):
    """Namespaces and class, without anonymous namespaces; file-local functions lead with their file."""
    parts = [n for n in fn["namespaces"] if n] + ([fn["class"]] if fn["class"] else [])
    if fn["linkage"] in ("INTERNAL", "UNIQUE_EXTERNAL"):
        parts = [fn["file"].replace("\\", "/") + ":"] + parts
    return parts


def hook_key(fn):
    """What a hook id stands for: its scope, name, parameter types and constness."""
    key = "::".join(named_scopes(fn) + [fn["displayname"]]).replace(":::", ":")
    return key + (" const" if fn["const"] else "")


def cpp_name(text):
    """Text as a C++ name that is never reserved: no repeated underscores, no leading digit."""
    name = re.sub(r"_+", "_", re.sub(r"\W+", "_", text)).strip("_")
    return "File_" + name if name[:1].isdigit() else name


def hook_name(fn, taken):
    """A C++ identifier for the plugin header, unique among the names already taken."""
    leaf = "op_" + operator_leaf(fn["name"]) if fn["name"].startswith("operator") else fn["name"]
    name = cpp_name("_".join(named_scopes(fn) + [leaf]))
    if name in taken:
        params = "_".join(p["type"] for p in fn["params"]) or "void"
        name = cpp_name("%s_with_%s%s" % (name, params, "_const" if fn["const"] else ""))
    base, n = name, 2
    while name in taken:
        name, n = "%s_%d" % (base, n), n + 1
    return name


def hook_shape(fn):
    """What a plugin's hook depends on besides the key: whether the function is static, and what it returns, as libclang
    spells it so that reformatting the source changes nothing."""
    return ("static " if fn["static_method"] else "") + fn["result_type"]


class Registry:
    """The committed id-to-function list. Ids are only ever added; a function whose shape changes gets a new one."""

    def __init__(self, path):
        self.path = path
        self.entries = {}
        ids = set()
        self.names = set()
        self.claimed = set()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    fields = line.rstrip("\n").split("\t", 3)
                    if len(fields) not in (3, 4) or not re.fullmatch(r"[0-9]+", fields[0]):
                        raise RuntimeError("%s line %d is not 'id<TAB>name<TAB>function<TAB>shape'" % (path, number))
                    hook_id, name, key = int(fields[0]), fields[1], fields[2]
                    shape = fields[3] if len(fields) == 4 else ""
                    # A merge of two branches that both added hooks can repeat an id, which would make one
                    # function's hooks run on another.
                    if hook_id in ids or name in self.names or (key, shape) in self.entries:
                        raise RuntimeError("%s line %d repeats an id, name or function seen earlier" % (path, number))
                    ids.add(hook_id)
                    self.names.add(name)
                    self.entries[(key, shape)] = (hook_id, name)
        self.next_id = max([i for i, _ in self.entries.values()] or [-1]) + 1
        self.added = 0
        self.reshaped = 0

    def claim(self, fn):
        key, shape = hook_key(fn), hook_shape(fn)
        if (key, shape) not in self.entries and (key, "") in self.entries:
            # A row written before shapes were recorded.
            self.entries[(key, shape)] = self.entries.pop((key, ""))
        if (key, shape) not in self.entries:
            if any(k == key for k, _ in self.entries):
                self.reshaped += 1
            name = hook_name(fn, self.names)
            self.entries[(key, shape)] = (self.next_id, name)
            self.next_id += 1
            self.names.add(name)
            self.added += 1
        hook_id, name = self.entries[(key, shape)]
        self.claimed.add(hook_id)
        return key, hook_id, name

    def save(self):
        rows = sorted((hook_id, name, key, shape) for (key, shape), (hook_id, name) in self.entries.items())
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            for hook_id, name, key, shape in rows:
                f.write("%d\t%s\t%s%s\n" % (hook_id, name, key, "\t" + shape if shape else ""))

    def count(self):
        return self.next_id


def load_analysis(project):
    """The analyzed functions and shared variables, each once."""
    with open(os.path.join(project.build_dir, "analysis.json")) as f:
        results = json.load(f)
    functions, variables = {}, {}
    for r in results:
        for fn in r["functions"]:
            functions.setdefault(fn["usr"] + "@" + fn["file"], fn)
        for v in r["variables"]:
            variables.setdefault(v["usr"], v)
    return list(functions.values()), list(variables.values())


def prepare_hook(fn, project, files):
    """Everything a hook needs, or Skip: (wrapper code, edits to apply)."""
    if fn["name"].startswith("operator") and operator_leaf(fn["name"]) is None:
        raise Skip("operator without a hook name")
    ex = fn.get("export_decl")
    if (ex and ex["first_token"] == "friend") or (fn["decl"] and fn["decl"]["tokens"][0][0] == "friend"):
        raise Skip("friend function")
    src = os.path.join(project.root, fn["file"])
    data = cached_read(files, src)
    exported = bool(ex and ex["is_definition"])
    edits = [(src, fn["name_start"], fn["name_end"], orig_name(fn))]
    if fn["class"]:
        path, pos, insert = orig_declaration(fn, files)
        edits.append((path, pos, pos, insert))
    else:
        ahead = free_function_declarations(fn, data, exported)
        if ahead:
            edits.append((src, fn["def_start"], fn["def_start"], ahead))
    return wrapper_code(fn, data, src, exported), edits


def plan_hooks(functions, project, files, edits, registry):
    hooks, skipped, wrappers = [], {}, PathDict()
    for fn in sorted((f for f in functions if not f["skip"]), key=lambda f: (f["file"], f["def_start"])):
        try:
            code, fn_edits = prepare_hook(fn, project, files)
        except Skip as e:
            skipped[str(e)] = skipped.get(str(e), 0) + 1
            fn["skip"] = [str(e)]
            continue
        fn["hook_key"], fn["hook_id"], fn["hook_name"] = registry.claim(fn)
        for path, start, end, insert in fn_edits:
            edits.setdefault(path, []).append((start, end, insert))
        src = os.path.join(project.root, fn["file"])
        fn["signature"] = hooked_signature(fn, files[src])
        wrappers.setdefault(src, []).append((fn, code.replace(ID_PLACEHOLDER, str(fn["hook_id"]))))
        hooks.append(fn)
    return hooks, skipped, wrappers


def mark_exports(functions, files, edits):
    """Put the export marker on the first declaration of each function or shared variable. Returns (marked, missed)."""
    marked, missed, sites = 0, 0, set()
    for fn in functions:
        ex = fn.get("export_decl")
        if not ex or ex["first_token"] == "friend":
            continue
        if ex["is_definition"]:
            marked += "hook_id" in fn
            continue
        site = (common.path_key(ex["file"]), ex["start"])
        if site in sites:
            continue
        data = cached_read(files, ex["file"])
        if text(data, ex["start"], ex["start"] + len(ex["first_token"])) != ex["first_token"]:
            missed += 1
            continue
        sites.add(site)
        edits.setdefault(ex["file"], []).append((ex["start"], ex["start"], "CIV_HOST_API "))
        marked += 1
    return marked, missed


def apply_edits(data, edits):
    """Each edit is (start, end, text) against the original data; texts inserted at one offset keep their order."""
    out = bytearray(data)
    limit = len(data)
    for start, end, repl in reversed(sorted(edits, key=lambda e: (e[0], e[1]))):
        if end > limit:
            raise RuntimeError("generator: edits overlap at offset %d" % start)
        out[start:end] = repl.encode("cp1252")
        limit = start
    return bytes(out)


def pin_outside_includes(project, path, data):
    """Point quoted #includes that climb out of the project at the originals, which the mirror does not copy."""

    def pin(m):
        target = os.path.normpath(os.path.join(os.path.dirname(path), m.group(2).decode("cp1252")))
        if project.contains(target) or not os.path.isfile(target):
            return m.group(0)
        return m.group(1) + target.encode("cp1252") + b'"'

    return QUOTED_INCLUDE.sub(pin, data)


def add_line_directive(path, data):
    """Point the rest of the file back at the original, after the last #include or #pragma once.

    VS2008 resolves quoted #includes and #pragma once against the file name a #line directive
    sets, so a directive above either would pick up the unhooked originals or include twice.
    Lines above the directive keep the mirror's name, with correct line numbers.
    """
    orig = c_string(path)
    last = None
    for m in INCLUDE_LINE.finditer(data):
        last = m
    if last is None:
        return ("#line 1 %s\r\n" % orig).encode("cp1252") + data
    line_no = data.count(b"\n", 0, last.start()) + 1
    eol = data.find(b"\n", last.end())
    if eol < 0:
        return data + ("\r\n#line %d %s\r\n" % (line_no + 1, orig)).encode("cp1252")
    return data[: eol + 1] + ("#line %d %s\r\n" % (line_no + 1, orig)).encode("cp1252") + data[eol + 1 :]


def write_mirror(project, files, edits, wrappers):
    if os.path.isdir(project.mirror_root):
        shutil.rmtree(project.mirror_root)
    for dirpath, _, filenames in os.walk(project.root):
        for name in filenames:
            src = os.path.join(dirpath, name)
            dst = os.path.join(project.mirror_dir, os.path.relpath(src, project.root))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not name.lower().endswith((".cpp", ".h", ".inl")):
                shutil.copyfile(src, dst)
                continue
            data = apply_edits(files.get(src) or read(src), edits.get(src, []))
            out = add_line_directive(src, pin_outside_includes(project, src, data))
            if src in wrappers:
                tail = ["", '#include "CivHostHooks.h"', ""]
                for fn, code in wrappers[src]:
                    tail += [namespace_open(fn["lex_namespaces"]), code, namespace_close(fn["lex_namespaces"])]
                out = out.rstrip() + b"\r\n" + "\n".join(tail).replace("\n", "\r\n").encode("cp1252")
            with open(dst, "wb") as f:
                f.write(out)


def hand_hook_enum(name):
    """A call to CivHand<Name> runs the hand-placed hook CIV_HAND_<NAME> of CivPluginApi.h."""
    return "CIV_HAND_" + re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()


def hand_hook_sites(hooks, files, root):
    """(hand-placed hook, hook id) once for each hooked function whose body calls that hand-placed hook."""
    sites = set()
    for fn in hooks:
        data = files[os.path.join(root, fn["file"])]
        for m in HAND_HOOK_CALL.finditer(data, fn["body_start"], fn["def_end"]):
            sites.add((hand_hook_enum(m.group(1).decode("ascii")), fn["hook_id"]))
    return sorted(sites, key=lambda site: (site[1], site[0]))


def write_table(project, registry, sites):
    by_id = dict((hook_id, key) for (key, _), (hook_id, _) in registry.entries.items())
    lines = [
        '#include "CivHostHooks.h"',
        '#include "CivPluginApi.h"',
        "",
        "CivHookPoint g_CivHookPoints[%d];" % max(1, registry.count()),
        "unsigned char g_CivHookActive[%d];" % max(1, registry.count()),
        "const int g_CivHookPointCount = %d;" % registry.count(),
        "",
        "extern const char* const g_CivHookPointNames[] =",
        "{",
    ]
    lines += ['\t"%s",' % by_id.get(i, "(unused)").replace("\\", "\\\\") for i in range(registry.count())]
    if not registry.count():
        lines.append('\t"",')
    lines += ["};", "", "extern const unsigned char g_CivHookLive[] =", "{"]
    live = ["1" if i in registry.claimed else "0" for i in range(registry.count())] or ["0"]
    lines += ["\t" + ", ".join(live[i : i + 40]) + "," for i in range(0, len(live), 40)]
    lines += ["};", "", "extern const CivHandHookSite g_CivHandHookSites[] =", "{"]
    lines += ["\t{ %s, %d }," % site for site in sites] or ["\t{ -1, -1 },"]
    lines += ["};", "const int g_CivHandHookSiteCount = %d;" % len(sites)]
    with open(os.path.join(project.mirror_dir, "CivHookTable.cpp"), "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def hooked_signature(fn, data):
    result = "void" if fn["result"]["kind"] == "void" else return_text(fn, data)
    return ("static " if fn["static_method"] else "") + result + " " + fn["hook_key"]


def plugin_spelling(type_text):
    # Visual C++ 2008 reads >> as the shift operator, so nested template arguments need a space between them.
    while ">>" in type_text:
        type_text = type_text.replace(">>", "> >")
    return type_text


def hook_type_lines(result, params, suffix=""):
    """The typedefs of a hook point's original function, and of a before-hook, after-hook and replacement on it."""
    slot = [] if result == "void" else ["CivHookSlot< %s >::Type" % result]
    original = "Original" + suffix
    return [
        "typedef %s (*%s)(%s);" % (result, original, ", ".join(params)),
        "typedef bool (*Before%s)(%s);" % (suffix, ", ".join(params + slot)),
        "typedef void (*After%s)(%s);" % (suffix, ", ".join(params + slot)),
        "typedef %s (*Replace%s)(%s);" % (result, suffix, ", ".join([original] + params)),
    ]


def hook_types(fn, qualified=False):
    """A hook point's result type and parameter types, self first: as the game's code writes them, which a plugin
    cannot always name (a nested type written inside its own class), or qualified, which reads worse but always names
    it."""
    if qualified:
        owner = fn["canonical_class"]
        params, result = fn["canonical_params"], fn["canonical_result"]
    else:
        owner = "::".join([n for n in fn["namespaces"] if n] + [fn["class"] or ""])
        params, result = [p["type"] for p in fn["params"]], fn["result_type"]
    self_type = ["%s%s *" % ("const " if fn["const"] else "", owner)] if fn["class"] and not fn["static_method"] else []
    result = "void" if fn["result"]["kind"] == "void" else result
    return plugin_spelling(result), [plugin_spelling(t) for t in self_type + params]


def plugin_typedefs(fn, qualified=False):
    """The hook point's typedefs for CivHooks.h."""
    return hook_type_lines(*hook_types(fn, qualified))


def function_types(fn):
    """The hooked function's own types, canonically spelled: (result, parameters), self first."""
    self_type = []
    if fn["class"] and not fn["static_method"]:
        self_type = ["%s%s *" % ("const " if fn["const"] else "", fn["canonical_class"])]
    return fn["canonical_result"], self_type + fn["canonical_params"]


PLUGIN_HEADER_INTRO = """#pragma once

// Generated: one struct per hook point, with its id, the function it hooks, and the exact types of the hooks a plugin
// can register on it, which CivRegisterBefore, CivRegisterAfter and CivRegisterReplace check. A hook point with no
// types takes a type %(first)s does not declare, or one private to its class: register its hooks
// with RegisterHook, and match the function by hand.

#include "%(first)s"
#include "CivPluginApi.h"

namespace CivHooks
{"""

# A hook point's first line in CivHooks.h, which ends with the struct's closing brace only when it has no types.
HEADER_HOOK = re.compile(r"^\tstruct (\w+) \{ enum \{ ID = (\d+) \};( \};)?", re.M)


def header_hooks(text):
    """(name, id, has types) for each hook point in CivHooks.h's text."""
    return [(m.group(1), int(m.group(2)), not m.group(3)) for m in HEADER_HOOK.finditer(text)]


def plugin_header(registry, hooks, untyped, plugin_include, qualified=()):
    """CivHooks.h's text, and the hook id of each line that declares a hook's types, by line number."""
    by_id = dict((fn["hook_id"], fn) for fn in hooks)
    lines = (PLUGIN_HEADER_INTRO % {"first": plugin_include}).split("\n")
    type_lines = {}
    live_names = dict((key, name) for (key, _), (hook_id, name) in registry.entries.items() if hook_id in by_id)
    for (key, _), (hook_id, name) in sorted(registry.entries.items(), key=lambda item: item[1]):
        fn = by_id.get(hook_id)
        if fn is None:
            # Left out, so a plugin rebuilt against this SDK stops at its old name rather than being refused in the
            # game.
            replacement = live_names.get(key)
            changed = ": its function changed, and its hook is now %s" % replacement if replacement else ""
            lines.append("\t// %s (id %d) is no longer a hook point%s." % (name, hook_id, changed))
            continue
        if hook_id in untyped:
            lines.append("\tstruct %s { enum { ID = %d }; }; // %s" % (name, hook_id, fn["signature"]))
            continue
        lines.append("\tstruct %s { enum { ID = %d }; // %s" % (name, hook_id, fn["signature"]))
        for typedef in plugin_typedefs(fn, hook_id in qualified):
            lines.append("\t\t" + typedef)
            type_lines[len(lines)] = hook_id
        lines.append("\t};")
    lines.append("}")
    return "\n".join(lines) + "\n", type_lines


def failing_hooks(check, type_lines, expected):
    """The hook points whose typedefs have an error, or name other types than the hooked function's own."""
    errors, originals = check
    stray = sorted(line for line in errors if line not in type_lines)
    if stray:
        raise RuntimeError("generator: CivHooks.h has errors outside hook types, at lines %s" % stray)
    failed = set(type_lines[line] for line in errors)
    for line, types in originals.items():
        hook_id = type_lines.get(line)
        if hook_id is not None and types != expected[hook_id]:
            failed.add(hook_id)
    return failed


def checked_plugin_header(project, registry, hooks):
    """CivHooks.h's text, the hook points it gives no types, and those whose types it qualifies. Each hook point's
    types are spelled as the game's code writes them, else qualified, else left out, whichever first compiles in a
    plugin as the function's own."""
    expected = dict((fn["hook_id"], function_types(fn)) for fn in hooks)
    qualified, untyped = set(), set()
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "CivHooks.h")
        for retry_in in (qualified, untyped, None):
            text, type_lines = plugin_header(registry, hooks, untyped, project.plugin_include, qualified)
            with open(path, "w", newline="\r\n") as f:
                f.write(text)
            failed = failing_hooks(analyze.check_plugin_header(project, path), type_lines, expected)
            if not failed:
                return text, untyped, qualified - untyped
            if retry_in is None:
                raise RuntimeError("generator: CivHooks.h still fails for hook points %s" % sorted(failed)[:20])
            retry_in |= failed


def write_plugin_header(project, registry, hooks):
    """Writes CivHooks.h. Returns the hook points it gives no types."""
    text, untyped, _ = checked_plugin_header(project, registry, hooks)
    out_dir = os.path.join(project.build_dir, "sdk")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "CivHooks.h"), "w", newline="\r\n") as f:
        f.write(text)
    return untyped


def replace_once(text, old, new):
    if old not in text:
        raise RuntimeError("generator: project file no longer contains %r" % old)
    return text.replace(old, new, 1)


def write_engine_build_files(project):
    with open(project.vcproj, encoding="cp1252") as f:
        proj = f.read()
    root = common.SOURCE_ROOT + "\\"

    def absolutize(m):
        return m.group(1) + m.group(2).replace("$(SolutionDir)\\", root).replace("$(SolutionDir)", root) + '"'

    proj = re.sub(r'(AdditionalIncludeDirectories=")([^"]*)"', absolutize, proj)
    proj = re.sub(r'(AdditionalLibraryDirectories=")([^"]*)"', absolutize, proj)
    proj = replace_once(
        proj,
        'AdditionalIncludeDirectories="',
        'AdditionalIncludeDirectories="&quot;%s&quot;;&quot;%s&quot;;' % (common.HOST_DIR, project.mirror_dir),
    )
    # Plugins import from the host by its installed name, so the import library must carry it.
    proj = replace_once(
        proj,
        'OutputFile="$(OutDir)\\$(ProjectName)$(PlatformName)$(ConfigurationName).dll"',
        'OutputFile="$(OutDir)\\CvGameCore_Expansion2.dll"',
    )
    defines = ";".join(["CIV_HOST_API=__declspec(dllexport)"] + common.LAYOUT_DEFINES)
    proj = replace_once(
        proj, 'PreprocessorDefinitions="FXS_IS_DLL;', 'PreprocessorDefinitions="%s;FXS_IS_DLL;' % defines
    )
    proj = replace_once(proj, 'AdditionalOptions="/EHsc"', 'AdditionalOptions="/EHsc /MP /bigobj /wd4251 /wd4275"')
    extra = []
    for path in sorted(glob.glob(os.path.join(common.HOST_DIR, "*.cpp"))) + [
        os.path.join(project.mirror_dir, "CivHookTable.cpp")
    ]:
        extra.append(
            '\t\t<File RelativePath="%s">\n'
            '\t\t\t<FileConfiguration Name="Mod|Win32">\n'
            '\t\t\t\t<Tool Name="VCCLCompilerTool" UsePrecompiledHeader="0"/>\n'
            "\t\t\t</FileConfiguration>\n"
            "\t\t</File>\n" % path
        )
    proj = replace_once(proj, "\t</Files>", "".join(extra) + "\t</Files>")
    vcproj_name = os.path.basename(project.vcproj)
    with open(os.path.join(project.mirror_dir, vcproj_name), "w", encoding="cp1252", newline="\r\n") as f:
        f.write(proj)
    sln = (
        "Microsoft Visual Studio Solution File, Format Version 10.00\n"
        "# Visual Studio 2008\n"
        'Project("{8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942}") = "CvGameCoreDLL_Expansion2", '
        '"CvGameCoreDLL_Expansion2\\%s", "{F58F230D-EE4A-40E0-91D5-93626E790055}"\n'
        "EndProject\n"
        "Global\n"
        "\tGlobalSection(SolutionConfigurationPlatforms) = preSolution\n"
        "\t\tMod|Win32 = Mod|Win32\n"
        "\tEndGlobalSection\n"
        "\tGlobalSection(ProjectConfigurationPlatforms) = postSolution\n"
        "\t\t{F58F230D-EE4A-40E0-91D5-93626E790055}.Mod|Win32.ActiveCfg = Mod|Win32\n"
        "\t\t{F58F230D-EE4A-40E0-91D5-93626E790055}.Mod|Win32.Build.0 = Mod|Win32\n"
        "\tEndGlobalSection\n"
        "EndGlobal\n"
    ) % vcproj_name
    with open(os.path.join(project.mirror_root, "Expansion2.civgen.sln"), "w", newline="\r\n") as f:
        f.write(sln)


def run(project):
    functions, variables = load_analysis(project)
    files, edits = PathDict(), PathDict()
    registry = Registry(project.registry)
    hooks, skipped, wrappers = plan_hooks(functions, project, files, edits, registry)
    marked, missed = mark_exports(functions, files, edits)
    shared, missed_shared = mark_exports(variables, files, edits)
    write_mirror(project, files, edits, wrappers)
    registry.save()
    write_table(project, registry, hand_hook_sites(hooks, files, project.root))
    untyped = write_plugin_header(project, registry, hooks)
    if project.vcproj:
        write_engine_build_files(project)

    vanished = len(registry.entries) - len(hooks)
    print(
        "hook points %d (new %d, no longer present %d), marked for export: functions %d, shared variables %d"
        % (len(hooks), registry.added, vanished, marked, shared)
    )
    if registry.reshaped:
        print("  new numbers for functions whose return type or static changed: %d" % registry.reshaped)
    if untyped:
        print("  hook points whose types plugins cannot name, so CivHooks.h gives them no types: %d" % len(untyped))
    if missed or missed_shared:
        print("  export marker not placed (declaration not written literally): %d" % (missed + missed_shared))
    for reason, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print("  skipped while generating, %s: %d" % (reason, n))
    return hooks


if __name__ == "__main__":
    run(common.engine_project())
    sys.exit(0)
