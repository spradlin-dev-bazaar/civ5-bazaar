"""Turn analysis.json into a hooked copy of the engine and a project file that builds it.

The committed source is never changed. Every engine file is mirrored into BuildTemp/civgen/src with
#line directives pointing back at the original, so compiler errors, crash stacks and the debugger
all name the real files.
"""

import json
import os
import re
import shutil
import sys

import common

MIRROR_ROOT = os.path.join(common.BUILD_DIR, "src")
MIRROR_ENGINE = os.path.join(MIRROR_ROOT, "CvGameCoreDLL_Expansion2")
HOST_DIR = os.path.join(common.REPO, "host")

INCLUDE_LINE = re.compile(rb"^[ \t]*#[ \t]*(?:include\b|pragma[ \t]+once\b)[^\n]*", re.M)
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
    "operator new": "new",
    "operator delete": "delete",
}


def c_string(path):
    return '"' + path.replace("\\", "\\\\") + '"'


def orig_name(fn):
    name = fn["name"]
    if name.startswith("operator"):
        key = (
            re.sub(r"\s+", "", name)
            if not name.startswith("operator new") and not name.startswith("operator delete")
            else name
        )
        return "CivOrigOp_" + OPERATOR_NAMES[key]
    return "CivOrig_" + name


def operator_known(fn):
    name = fn["name"]
    if not name.startswith("operator"):
        return True
    key = (
        re.sub(r"\s+", "", name)
        if not name.startswith("operator new") and not name.startswith("operator delete")
        else name
    )
    return key in OPERATOR_NAMES


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


def read(path):
    with open(path, "rb") as f:
        return f.read()


def text(data, start, end):
    return data[start:end].decode("cp1252")


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


def return_text(fn, data):
    before = text(data, fn["def_start"], fn["name_start"])
    before = re.sub(r"(\s*\b\w+\s*(<[^<>]*>)?\s*::\s*)+$", "", before)
    words = before.split()
    words = [w for w in words if w not in LEADING_SPECIFIERS and w not in CALLING_CONVENTIONS]
    result = " ".join(words)
    result = re.sub(r"__declspec\s*\([^)]*\)", "", result).strip()
    if not result:
        raise Skip("could not read return type")
    return result


def wrapper_signature(fn, data, keep_defaults=False):
    """The definition's own text up to its body, with names added for unnamed parameters."""
    start = fn["def_start"]
    sig = bytearray(data[start : fn["body_start"]])
    for i in reversed(range(len(fn["params"]))):
        p = fn["params"][i]
        raw = text(data, p["start"], p["end"])
        eq = top_level_equals(raw)
        if eq and not keep_defaults:
            del sig[p["start"] - start + eq : p["end"] - start]
        if not p["name"]:
            if eq:
                raise Skip("unnamed parameter with a default value")
            at = p["end"] - start
            sig[at:at] = (" civ_p%d" % i).encode("cp1252")
    return sig.decode("cp1252").rstrip()


def collapse(code):
    """One line, so text inserted into a source file never shifts its line numbers."""
    code = re.sub(r"//[^\n]*", "", code)
    return " ".join(code.split())


def qualifier_start(fn, data):
    """Offset where a written qualifier such as `CvTypes::` begins, or the name's own start."""
    before = text(data, fn["def_start"], fn["name_start"])
    m = re.search(r"(\b\w+\s*::\s*)+$", before)
    return fn["def_start"] + m.start() if m else fn["name_start"]


def free_function_declarations(fn, data):
    """Declarations a renamed free function needs ahead of its definition, on the same line."""
    q = qualifier_start(fn, data)
    if q != fn["name_start"]:
        sig = wrapper_signature(fn, data)
        rel_q = q - fn["def_start"]
        rel_end = fn["name_end"] - fn["def_start"]
        orig_decl = collapse(sig[:rel_q] + orig_name(fn) + sig[rel_end:]) + ";"
        semantic = fn["namespaces"]
        lexical = fn["lex_namespaces"]
        if semantic[: len(lexical)] != lexical:
            raise Skip("qualified definition outside its namespace")
        inner = semantic[len(lexical) :]
        if not inner:
            raise Skip("qualified free function in its own namespace")
        return namespace_open(inner) + orig_decl + " " + namespace_close(inner) + " "
    if fn["decl"] is None:
        return collapse(wrapper_signature(fn, data, keep_defaults=True)) + "; "
    return ""


def wrapper_code(fn, hook_id, data, src_path):
    params = [param_parts(fn, data, i) for i in range(len(fn["params"]))]
    types = [t for t, _ in params]
    names = [n for _, n in params]
    is_void = fn["result"]["kind"] == "void"
    member = fn["class"] is not None and not fn["static_method"]
    orig = orig_name(fn)
    args = ", ".join(names)
    call = "%s(%s)" % (orig, args)

    self_type = None
    if member:
        cls = fn["class"]
        self_type = ("const %s*" % cls) if fn["const"] else ("%s*" % cls)
    plugin_params = ([self_type] if self_type else []) + types
    plugin_args = (["c.self"] if self_type else []) + ["*c.a%d" % i for i in range(len(types))]

    lines = []
    lines.append("#line %d %s" % (fn["line"], c_string(src_path)))
    lines.append(wrapper_signature(fn, data))
    lines.append("{")
    lines.append("\tCivHookPoint& civ_hp = g_CivHookPoints[%d];" % hook_id)
    if is_void:
        lines.append("\tif (!civ_hp.active) { %s; return; }" % call)
    else:
        lines.append("\tif (!civ_hp.active) return %s;" % call)
        lines.append("\ttypedef %s civ_R;" % return_text(fn, data))
        lines.append("\ttypedef CivHookResult< civ_R > civ_Res;")

    lines.append("\tstruct civ_C")
    lines.append("\t{")
    if is_void:
        lines.append("\t\ttypedef bool (*BeforeFn)(%s);" % ", ".join(plugin_params))
        lines.append("\t\ttypedef void (*ReplaceFn)(%s);" % ", ".join(plugin_params))
        lines.append("\t\ttypedef void (*AfterFn)(%s);" % ", ".join(plugin_params))
    else:
        with_slot = ", ".join(plugin_params + ["civ_Res::Slot&"])
        lines.append("\t\ttypedef bool (*BeforeFn)(%s);" % with_slot)
        lines.append("\t\ttypedef civ_R (*ReplaceFn)(%s);" % ", ".join(plugin_params))
        lines.append("\t\ttypedef void (*AfterFn)(%s);" % with_slot)
    lines.append("\t\tvoid* fn;")
    lines.append("\t\tbool veto;")
    if self_type:
        lines.append("\t\t%s self;" % self_type)
    for i, t in enumerate(types):
        lines.append("\t\tCivHookArg< %s >::Ptr a%d;" % (t, i))
    if not is_void:
        lines.append("\t\tciv_Res* res;")
    pa = ", ".join(plugin_args)
    pa_slot = ", ".join(plugin_args + ["c.res->value"])
    if is_void:
        lines.append(
            "\t\tstatic void Before(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.veto = reinterpret_cast<BeforeFn>(c.fn)(%s); }"
            % pa
        )
        lines.append(
            "\t\tstatic void Replace(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<ReplaceFn>(c.fn)(%s); }"
            % pa
        )
        lines.append(
            "\t\tstatic void After(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<AfterFn>(c.fn)(%s); }"
            % pa
        )
    else:
        lines.append(
            "\t\tstatic void Before(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.veto = reinterpret_cast<BeforeFn>(c.fn)(%s); }"
            % pa_slot
        )
        lines.append(
            "\t\tstatic void Replace(void* p) { civ_C& c = *static_cast<civ_C*>(p); c.res->Set(reinterpret_cast<ReplaceFn>(c.fn)(%s)); }"
            % pa
        )
        lines.append(
            "\t\tstatic void After(void* p) { civ_C& c = *static_cast<civ_C*>(p); reinterpret_cast<AfterFn>(c.fn)(%s); }"
            % pa_slot
        )
    lines.append("\t};")

    init = ["0", "false"] + (["this"] if self_type else []) + ["&" + n for n in names]
    if is_void:
        lines.append("\tciv_C civ_c = { %s };" % ", ".join(init))
        lines.append(
            "\tif (!CivHookRunBefore(civ_hp, %d, &civ_C::Before, &civ_c) && CivHookRunReplace(civ_hp, %d, &civ_C::Replace, &civ_c) == 0)"
            % (hook_id, hook_id)
        )
        lines.append("\t\t%s;" % call)
        lines.append("\tCivHookRunAfter(civ_hp, %d, &civ_C::After, &civ_c);" % hook_id)
    else:
        lines.append("\tciv_Res civ_res;")
        lines.append("\tciv_C civ_c = { %s };" % ", ".join(init + ["&civ_res"]))
        lines.append(
            "\tif (!CivHookRunBefore(civ_hp, %d, &civ_C::Before, &civ_c) && CivHookRunReplace(civ_hp, %d, &civ_C::Replace, &civ_c) == 0)"
            % (hook_id, hook_id)
        )
        lines.append("\t\tciv_res.Set(%s);" % call)
        lines.append("\tif (civ_res.Empty())")
        lines.append("\t\tciv_res.Set(%s);" % call)
        lines.append("\tCivHookRunAfter(civ_hp, %d, &civ_C::After, &civ_c);" % hook_id)
        lines.append("\treturn civ_res.Get();")
    lines.append("}")
    return "\n".join(lines) + "\n"


def orig_declaration(fn, files):
    """Text declaring the renamed original inside its class, and where to insert it."""
    decl = fn["decl"]
    path = decl["file"]
    data = files.setdefault(path, read(path))
    toks = decl["tokens"]
    name = fn["name"]
    out = []
    i = 0
    found = False
    while i < len(toks):
        spelling, off = toks[i]
        if off == decl["name_offset"] and not found:
            if name.startswith("operator"):
                target = re.sub(r"\s+", "", name)
                j = i + 1
                written = "operator"
                while j < len(toks) and len(written) < len(target):
                    written += toks[j][0]
                    j += 1
                if written != target:
                    raise Skip("operator declaration not understood")
                out.append(orig_name(fn))
                i = j
                found = True
                continue
            if spelling != name:
                raise Skip("declaration not written literally")
            out.append(orig_name(fn))
            found = True
        else:
            out.append(spelling)
        i += 1
    if not found:
        raise Skip("declaration name not found")
    while len(out) >= 2 and out[-2] == "=" and out[-1] == "0":
        out = out[:-2]
    pos = decl["extent_end"]
    while pos < len(data) and data[pos : pos + 1] in (b" ", b"\t"):
        pos += 1
    if data[pos : pos + 1] != b";":
        raise Skip("declaration does not end where expected")
    return path, pos + 1, " " + " ".join(out) + ";"


def hook_names(hooks):
    seen = {}
    for fn in hooks:
        base = "_".join(fn["namespaces"] + ([fn["class"].replace("::", "_")] if fn["class"] else []))
        if fn["storage"] == "STATIC" and not fn["class"]:
            base = os.path.splitext(os.path.basename(fn["file"]))[0] + ("_" + base if base else "")
        leaf = ("op_" + orig_name(fn)[len("CivOrigOp_") :]) if fn["name"].startswith("operator") else fn["name"]
        name = (base + "_" + leaf) if base else leaf
        n = seen.get(name, 0) + 1
        seen[name] = n
        fn["hook_name"] = name if n == 1 else "%s_%d" % (name, n)
        fn["display_name"] = "::".join(fn["namespaces"] + ([fn["class"]] if fn["class"] else []) + [fn["name"]])


def namespace_open(names):
    return "".join("namespace %s{ " % (n + " " if n else "") for n in names)


def namespace_close(names):
    return "}" * len(names)


def apply_edits(data, edits):
    out = bytearray(data)
    for start, end, repl in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        out[start:end] = repl.encode("cp1252")
    return bytes(out)


def add_line_directive(path, data):
    """Point the rest of the file back at the original, after the last #include or #pragma once.

    VS2008 resolves quoted #includes and #pragma once against the file name a #line directive
    sets, so a directive above either would pick up the unhooked originals or include twice.
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


def generate_project(hooked_sources):
    with open(common.VCPROJ, encoding="cp1252") as f:
        proj = f.read()
    root = common.SOURCE_ROOT + "\\"

    def absolutize(m):
        return m.group(1) + m.group(2).replace("$(SolutionDir)\\", root).replace("$(SolutionDir)", root) + '"'

    proj = re.sub(r'(AdditionalIncludeDirectories=")([^"]*)"', absolutize, proj)
    proj = re.sub(r'(AdditionalLibraryDirectories=")([^"]*)"', absolutize, proj)
    proj = proj.replace(
        'AdditionalIncludeDirectories="',
        'AdditionalIncludeDirectories="&quot;%s&quot;;&quot;%s&quot;;' % (HOST_DIR, MIRROR_ENGINE),
        1,
    )
    # Plugins import from the host by its installed name, so the import library must carry it.
    proj = proj.replace(
        'OutputFile="$(OutDir)\\$(ProjectName)$(PlatformName)$(ConfigurationName).dll"',
        'OutputFile="$(OutDir)\\CvGameCore_Expansion2.dll"',
        1,
    )
    # The engine's PCH sets the two library-layout switches; files outside it must match or
    # std::string and std::vector differ in size across the call.
    proj = proj.replace(
        'PreprocessorDefinitions="FXS_IS_DLL;',
        'PreprocessorDefinitions="CIV_HOST_API=__declspec(dllexport);_SECURE_SCL=0;_HAS_ITERATOR_DEBUGGING=0;FXS_IS_DLL;',
        1,
    )
    proj = proj.replace('AdditionalOptions="/EHsc"', 'AdditionalOptions="/EHsc /MP /bigobj /wd4251 /wd4275"', 1)
    extra = []
    for path in [
        os.path.join(HOST_DIR, "CivHostRuntime.cpp"),
        os.path.join(HOST_DIR, "CivHostEngine.cpp"),
        os.path.join(MIRROR_ENGINE, "CivHookTable.cpp"),
    ]:
        extra.append(
            '\t\t<File RelativePath="%s">\n'
            '\t\t\t<FileConfiguration Name="Mod|Win32">\n'
            '\t\t\t\t<Tool Name="VCCLCompilerTool" UsePrecompiledHeader="0"/>\n'
            "\t\t\t</FileConfiguration>\n"
            "\t\t</File>\n" % path
        )
    proj = proj.replace("\t</Files>", "".join(extra) + "\t</Files>", 1)
    with open(
        os.path.join(MIRROR_ENGINE, "CvGameCoreDLL_Expansion2.vcproj"), "w", encoding="cp1252", newline="\r\n"
    ) as f:
        f.write(proj)
    sln = (
        "Microsoft Visual Studio Solution File, Format Version 10.00\n"
        "# Visual Studio 2008\n"
        'Project("{8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942}") = "CvGameCoreDLL_Expansion2", '
        '"CvGameCoreDLL_Expansion2\\CvGameCoreDLL_Expansion2.vcproj", "{F58F230D-EE4A-40E0-91D5-93626E790055}"\n'
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
    )
    with open(os.path.join(MIRROR_ROOT, "Expansion2.civgen.sln"), "w", newline="\r\n") as f:
        f.write(sln)


def generate_table(hooks):
    lines = [
        '#include "CivHostHooks.h"',
        "",
        "CivHookPoint g_CivHookPoints[%d];" % max(1, len(hooks)),
        "const int g_CivHookPointCount = %d;" % len(hooks),
        "",
        "extern const char* const g_CivHookPointNames[] =",
        "{",
    ]
    for fn in hooks:
        lines.append('\t"%s",' % fn["display_name"])
    if not hooks:
        lines.append('\t"",')
    lines.append("};")
    with open(os.path.join(MIRROR_ENGINE, "CivHookTable.cpp"), "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def generate_plugin_header(hooks):
    lines = [
        "#pragma once",
        "",
        "// Generated: one namespace per hook point, with its id.",
        "",
        "namespace CivHooks",
        "{",
    ]
    for fn in hooks:
        lines.append("\tnamespace %s { enum { ID = %d }; }" % (fn["hook_name"], fn["hook_id"]))
    lines.append("}")
    out_dir = os.path.join(common.BUILD_DIR, "sdk")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "CivHooks.h"), "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def main():
    with open(os.path.join(common.BUILD_DIR, "analysis.json")) as f:
        results = json.load(f)

    functions = {}
    for r in results:
        for fn in r["functions"]:
            functions.setdefault(fn["usr"] + "@" + fn["file"], fn)

    files = PathDict()
    edits = PathDict()
    skipped = {}
    hooks = []
    candidates = sorted(
        (fn for fn in functions.values() if not fn["skip"]), key=lambda fn: (fn["file"], fn["def_start"])
    )
    wrappers_by_file = PathDict()
    for fn in candidates:
        src = os.path.join(common.ENGINE_DIR, fn["file"])
        data = files.setdefault(src, read(src))
        try:
            if not operator_known(fn):
                raise Skip("operator without a hook name")
            ex = fn.get("export_decl")
            if (ex and ex["first_token"] == "friend") or (fn["decl"] and fn["decl"]["tokens"][0][0] == "friend"):
                raise Skip("friend function")
            decl_edit = orig_declaration(fn, files) if fn["class"] else None
            ahead = "" if fn["class"] else free_function_declarations(fn, data)
            if ahead and fn["decl"] is None and ex and ex["is_definition"]:
                ahead = "CIV_HOST_API " + ahead
            hooks.append(fn)
            fn["hook_id"] = len(hooks) - 1
            code = wrapper_code(fn, fn["hook_id"], data, src)
        except Skip as e:
            if hooks and hooks[-1] is fn:
                hooks.pop()
            skipped[str(e)] = skipped.get(str(e), 0) + 1
            fn["skip"] = [str(e)]
            continue
        edits.setdefault(src, []).append((fn["name_start"], fn["name_end"], orig_name(fn)))
        if ahead:
            edits[src].append((fn["def_start"], fn["def_start"], ahead))
        if decl_edit:
            path, pos, insert = decl_edit
            edits.setdefault(path, []).append((pos, pos, insert))
        wrappers_by_file.setdefault(src, []).append((fn, code))

    exported = 0
    export_sites = set()
    hooked = set(id(fn) for fn in hooks)
    for fn in functions.values():
        ex = fn.get("export_decl")
        if not ex or ex["first_token"] == "friend":
            continue
        if ex["is_definition"] and id(fn) in hooked:
            fn["export_wrapper"] = True
            exported += 1
            continue
        site = (os.path.normcase(ex["file"]), ex["start"])
        if site in export_sites:
            continue
        data = files.setdefault(ex["file"], read(ex["file"]))
        if text(data, ex["start"], ex["start"] + len(ex["first_token"])) != ex["first_token"]:
            continue
        export_sites.add(site)
        edits.setdefault(ex["file"], []).append((ex["start"], ex["start"], "CIV_HOST_API "))
        exported += 1

    hook_names(hooks)

    if os.path.isdir(MIRROR_ROOT):
        shutil.rmtree(MIRROR_ROOT)
    for dirpath, _, filenames in os.walk(common.ENGINE_DIR):
        for name in filenames:
            src = os.path.join(dirpath, name)
            dst = os.path.join(MIRROR_ENGINE, os.path.relpath(src, common.ENGINE_DIR))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not name.lower().endswith((".cpp", ".h", ".inl")):
                shutil.copyfile(src, dst)
                continue
            data = files.get(src) or read(src)
            out = apply_edits(data, edits.get(src, []))
            out = add_line_directive(src, out)
            if src in wrappers_by_file:
                tail = ["", '#include "CivHostHooks.h"', ""]
                for fn, code in wrappers_by_file[src]:
                    tail.append(namespace_open(fn["lex_namespaces"]))
                    if fn.get("export_wrapper"):
                        first_line_end = code.index("\n") + 1
                        code = code[:first_line_end] + "CIV_HOST_API " + code[first_line_end:]
                    tail.append(code)
                    tail.append(namespace_close(fn["lex_namespaces"]))
                out = (
                    out.rstrip()
                    + b"\r\n"
                    + "\r\n".join(tail).replace("\r\n", "\n").replace("\n", "\r\n").encode("cp1252")
                )
            with open(dst, "wb") as f:
                f.write(out)

    generate_table(hooks)
    generate_plugin_header(hooks)
    generate_project(sorted(wrappers_by_file))
    with open(os.path.join(common.BUILD_DIR, "hooks.json"), "w") as f:
        json.dump(
            [
                {
                    "id": fn["hook_id"],
                    "name": fn["hook_name"],
                    "display": fn["display_name"],
                    "file": fn["file"],
                    "line": fn["line"],
                }
                for fn in hooks
            ],
            f,
            indent=0,
        )

    print("hook points %d, functions marked for export %d" % (len(hooks), exported))
    for reason, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print("  skipped while generating, %s: %d" % (reason, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
