"""Turn a project's analysis.json into a hooked copy of its sources.

The committed source is never changed. Every file is mirrored into the project's build folder with
#line directives pointing back at the original, so compiler errors, crash stacks and the debugger
all name the real files. Inserted text always stays on its line, so line numbers never shift.

Hook ids live in a registry file: an id, once given, always means the same function, so plugins
built against an older host keep working.
"""

import json
import os
import re
import shutil
import sys

import common

ID_PLACEHOLDER = "\0HOOK_ID\0"
INCLUDE_LINE = re.compile(rb"^[ \t]*#[ \t]*(?:include\b|pragma[ \t]+once\b)[^\n]*", re.MULTILINE)
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
        return os.path.normcase(os.path.abspath(path))

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
    return sig.decode("cp1252").rstrip()


def collapse(code):
    code = re.sub(r"//[^\n]*", "", code)
    return " ".join(code.split())


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
        orig_decl = collapse(sig[:rel_q] + orig_name(fn) + sig[rel_end:]) + ";"
        semantic, lexical = fn["namespaces"], fn["lex_namespaces"]
        if semantic[: len(lexical)] != lexical:
            raise Skip("qualified definition outside its namespace")
        inner = semantic[len(lexical) :]
        if not inner:
            raise Skip("qualified free function in its own namespace")
        return namespace_open(inner) + orig_decl + " " + namespace_close(inner) + " "
    if fn["decl"] is None:
        marker = "CIV_HOST_API " if exported else ""
        return marker + collapse(wrapper_signature(fn, data, keep_defaults=True)) + "; "
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
    return "\t\tstatic %s Original(%s) { %s; }" % (result, ", ".join(params), body)


def wrapper_code(fn, data, src_path, exported):
    """The wrapper that takes the function's name, with ID_PLACEHOLDER standing for its hook id."""
    params = [param_parts(fn, data, i) for i in range(len(fn["params"]))]
    types = [t for t, _ in params]
    names = [n for _, n in params]
    is_void = fn["result"]["kind"] == "void"
    call = "%s(%s)" % (orig_name(fn), ", ".join(names))
    self_type = None
    if fn["class"] is not None and not fn["static_method"]:
        self_type = ("const %s*" % fn["class"]) if fn["const"] else ("%s*" % fn["class"])
    plugin_params = ([self_type] if self_type else []) + types
    plugin_args = (["c.self"] if self_type else []) + ["*c.a%d" % i for i in range(len(types))]
    run_hooks = (
        "\tif (!CivHookRunBefore(civ_hp, %(id)s, &civ_C::Before, &civ_c)"
        " && !CivHookRunReplace(civ_hp, %(id)s, &civ_C::Replace, &civ_c))" % {"id": ID_PLACEHOLDER}
    )

    lines = ["#line %d %s" % (fn["line"], c_string(src_path))]
    lines.append(("CIV_HOST_API " if exported else "") + wrapper_signature(fn, data))
    lines += ["{", "\tCivHookPoint& civ_hp = g_CivHookPoints[%s];" % ID_PLACEHOLDER]
    if is_void:
        lines.append("\tif (!civ_hp.active) { %s; return; }" % call)
        slot = []
    else:
        lines.append("\tif (!civ_hp.active) return %s;" % call)
        lines.append("\ttypedef %s civ_R;" % return_text(fn, data))
        lines.append("\ttypedef CivHookResult< civ_R > civ_Res;")
        slot = ["civ_Res::Slot&"]
    result = "void" if is_void else "civ_R"
    lines += ["\tstruct civ_C", "\t{"]
    lines.append("\t\ttypedef bool (*BeforeFn)(%s);" % ", ".join(plugin_params + slot))
    lines.append("\t\ttypedef %s (*OriginalFn)(%s);" % (result, ", ".join(plugin_params)))
    lines.append("\t\ttypedef %s (*ReplaceFn)(%s);" % (result, ", ".join(["OriginalFn"] + plugin_params)))
    lines.append("\t\ttypedef void (*AfterFn)(%s);" % ", ".join(plugin_params + slot))
    lines.append("\t\tCivHookCtx civ_h;")
    if self_type:
        lines.append("\t\t%s self;" % self_type)
    lines += ["\t\tCivHookArg< %s >::Ptr a%d;" % (t, i) for i, t in enumerate(types)]
    if not is_void:
        lines.append("\t\tciv_Res* res;")
    lines.append(original_line(fn, self_type, types, result))
    lines += thunk_lines(is_void, plugin_args)
    lines.append("\t};")

    init = ["{ 0, false }"] + (["this"] if self_type else []) + ["&" + n for n in names]
    if is_void:
        lines.append("\tciv_C civ_c = { %s };" % ", ".join(init))
        lines += [run_hooks, "\t\t%s;" % call]
    else:
        lines.append("\tciv_Res civ_res;")
        lines.append("\tciv_C civ_c = { %s };" % ", ".join(init + ["&civ_res"]))
        lines += [run_hooks, "\t\tciv_res.Set(%s);" % call, "\tif (civ_res.Empty())", "\t\tciv_res.Set(%s);" % call]
    lines.append("\tCivHookRunAfter(civ_hp, %s, &civ_C::After, &civ_c);" % ID_PLACEHOLDER)
    if not is_void:
        lines.append("\treturn civ_res.Get();")
    lines.append("}")
    return "\n".join(lines) + "\n"


def orig_declaration(fn, files):
    """Text declaring the renamed original inside its class, and where to insert it."""
    decl = fn["decl"]
    path = decl["file"]
    data = files.setdefault(path, read(path))
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
    return path, pos + 1, " " + " ".join(out) + ";"


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


def hook_name(fn, taken):
    """A C++ identifier for the plugin header, unique among the names already taken."""
    words = [re.sub(r"\W+", "_", part).strip("_") for part in named_scopes(fn)]
    leaf = "op_" + operator_leaf(fn["name"]) if fn["name"].startswith("operator") else fn["name"]
    name = "_".join([w for w in words if w] + [leaf])
    if name in taken:
        params = "_".join(re.sub(r"\W+", "_", p["type"]).strip("_") for p in fn["params"]) or "void"
        name = "%s_with_%s%s" % (name, params, "_const" if fn["const"] else "")
    base, n = name, 2
    while name in taken:
        name, n = "%s_%d" % (base, n), n + 1
    return name


class Registry:
    """The committed id-to-function list. Ids are only ever added."""

    def __init__(self, path):
        self.path = path
        self.entries = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for number, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    fields = line.rstrip("\n").split("\t", 2)
                    if len(fields) != 3 or not fields[0].isdigit():
                        raise RuntimeError("%s line %d is not 'id<TAB>name<TAB>function'" % (path, number))
                    self.entries[fields[2]] = (int(fields[0]), fields[1])
        self.names = set(name for _, name in self.entries.values())
        self.next_id = max([i for i, _ in self.entries.values()] or [-1]) + 1
        self.added = 0

    def claim(self, fn):
        key = hook_key(fn)
        if key not in self.entries:
            name = hook_name(fn, self.names)
            self.entries[key] = (self.next_id, name)
            self.next_id += 1
            self.names.add(name)
            self.added += 1
        return key, self.entries[key][0], self.entries[key][1]

    def save(self):
        rows = sorted((hook_id, name, key) for key, (hook_id, name) in self.entries.items())
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines("%d\t%s\t%s\n" % row for row in rows)

    def count(self):
        return self.next_id


def load_functions(project):
    with open(os.path.join(project.build_dir, "analysis.json")) as f:
        results = json.load(f)
    functions = {}
    for r in results:
        for fn in r["functions"]:
            functions.setdefault(fn["usr"] + "@" + fn["file"], fn)
    return list(functions.values())


def prepare_hook(fn, project, files):
    """Everything a hook needs, or Skip: (wrapper code, edits to apply)."""
    if fn["name"].startswith("operator") and operator_leaf(fn["name"]) is None:
        raise Skip("operator without a hook name")
    ex = fn.get("export_decl")
    if (ex and ex["first_token"] == "friend") or (fn["decl"] and fn["decl"]["tokens"][0][0] == "friend"):
        raise Skip("friend function")
    src = os.path.join(project.root, fn["file"])
    data = files.setdefault(src, read(src))
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
            continue
        fn["hook_key"], fn["hook_id"], fn["hook_name"] = registry.claim(fn)
        for path, start, end, insert in fn_edits:
            edits.setdefault(path, []).append((start, end, insert))
        src = os.path.join(project.root, fn["file"])
        wrappers.setdefault(src, []).append((fn, code.replace(ID_PLACEHOLDER, str(fn["hook_id"]))))
        hooks.append(fn)
    return hooks, skipped, wrappers


def mark_exports(functions, files, edits):
    """Put the export marker on each function's first declaration. Returns (marked, missed)."""
    marked, missed, sites = 0, 0, set()
    for fn in functions:
        ex = fn.get("export_decl")
        if not ex or ex["first_token"] == "friend":
            continue
        if ex["is_definition"]:
            marked += "hook_id" in fn
            continue
        site = (os.path.normcase(ex["file"]), ex["start"])
        if site in sites:
            continue
        data = files.setdefault(ex["file"], read(ex["file"]))
        if text(data, ex["start"], ex["start"] + len(ex["first_token"])) != ex["first_token"]:
            missed += 1
            continue
        sites.add(site)
        edits.setdefault(ex["file"], []).append((ex["start"], ex["start"], "CIV_HOST_API "))
        marked += 1
    return marked, missed


def apply_edits(data, edits):
    out = bytearray(data)
    for start, end, repl in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        out[start:end] = repl.encode("cp1252")
    return bytes(out)


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
            out = add_line_directive(src, apply_edits(files.get(src) or read(src), edits.get(src, [])))
            if src in wrappers:
                tail = ["", '#include "CivHostHooks.h"', ""]
                for fn, code in wrappers[src]:
                    tail += [namespace_open(fn["lex_namespaces"]), code, namespace_close(fn["lex_namespaces"])]
                out = out.rstrip() + b"\r\n" + "\n".join(tail).replace("\n", "\r\n").encode("cp1252")
            with open(dst, "wb") as f:
                f.write(out)


def write_table(project, registry):
    by_id = dict((hook_id, key) for key, (hook_id, _) in registry.entries.items())
    lines = [
        '#include "CivHostHooks.h"',
        "",
        "CivHookPoint g_CivHookPoints[%d];" % max(1, registry.count()),
        "const int g_CivHookPointCount = %d;" % registry.count(),
        "",
        "extern const char* const g_CivHookPointNames[] =",
        "{",
    ]
    lines += ['\t"%s",' % by_id.get(i, "(unused)").replace("\\", "\\\\") for i in range(registry.count())]
    if not registry.count():
        lines.append('\t"",')
    lines.append("};")
    with open(os.path.join(project.mirror_dir, "CivHookTable.cpp"), "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def write_plugin_header(project, registry):
    lines = [
        "#pragma once",
        "",
        "// Generated: one namespace per hook point, with its id.",
        "",
        "namespace CivHooks",
        "{",
    ]
    for hook_id, name in sorted(registry.entries.values()):
        lines.append("\tnamespace %s { enum { ID = %d }; }" % (name, hook_id))
    lines.append("}")
    out_dir = os.path.join(project.build_dir, "sdk")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "CivHooks.h"), "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


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
    for path in [
        os.path.join(common.HOST_DIR, "CivHostRuntime.cpp"),
        os.path.join(common.HOST_DIR, "CivHostEngine.cpp"),
        os.path.join(project.mirror_dir, "CivHookTable.cpp"),
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


def write_hook_list(project, hooks):
    rows = [
        {"id": fn["hook_id"], "name": fn["hook_name"], "key": fn["hook_key"], "file": fn["file"], "line": fn["line"]}
        for fn in hooks
    ]
    with open(os.path.join(project.build_dir, "hooks.json"), "w") as f:
        json.dump(sorted(rows, key=lambda r: r["id"]), f, indent=0)


def run(project):
    functions = load_functions(project)
    files, edits = PathDict(), PathDict()
    registry = Registry(project.registry)
    hooks, skipped, wrappers = plan_hooks(functions, project, files, edits, registry)
    marked, missed = mark_exports(functions, files, edits)
    write_mirror(project, files, edits, wrappers)
    registry.save()
    write_table(project, registry)
    write_plugin_header(project, registry)
    write_hook_list(project, hooks)
    if project.vcproj:
        write_engine_build_files(project)

    vanished = len(registry.entries) - len(hooks)
    print(
        "hook points %d (new %d, no longer present %d), functions marked for export %d"
        % (len(hooks), registry.added, vanished, marked)
    )
    if missed:
        print("  export marker not placed (declaration not written literally): %d" % missed)
    for reason, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print("  skipped while generating, %s: %d" % (reason, n))
    return hooks


if __name__ == "__main__":
    run(common.engine_project())
    sys.exit(0)
