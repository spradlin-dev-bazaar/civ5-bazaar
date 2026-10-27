"""Find every function defined in a project's source files, and whether it can be hooked.

Writes analysis.json in the project's build folder, which generate.py turns into hook wrappers.
"""

import json
import multiprocessing
import os
import sys
import time

import clang.cindex as ci

import common

CK = ci.CursorKind
FUNCTION_KINDS = (
    CK.CXX_METHOD,
    CK.FUNCTION_DECL,
    CK.CONSTRUCTOR,
    CK.DESTRUCTOR,
    CK.CONVERSION_FUNCTION,
    CK.FUNCTION_TEMPLATE,
)
CLASS_KINDS = (CK.CLASS_DECL, CK.STRUCT_DECL)
TEMPLATE_KINDS = (CK.CLASS_TEMPLATE, CK.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION, CK.FUNCTION_TEMPLATE)
# Windows calls these under its loader lock, or before any plugin can have loaded.
LOADER_ENTRY_POINTS = {"DllMain", "DllGetGameContext"}
# Bazaar starts, unloads its plugins, answers the Plugins screen and saves plugins' data from inside these, so a
# plugin's hook on one could keep it from doing so.
HOST_ENTRY_POINTS = {
    ("CvDllGameContext", "Init"),
    ("CvDllGameContext", "Uninit"),
    ("CvDllWorldBuilderMapLoader", "GetMapPreview"),
    ("CvDllGame", "ReadSupportingClassData"),
    ("CvDllGame", "WriteSupportingClassData"),
    ("CvGame", "ReadSupportingClassData"),
    ("CvGame", "WriteSupportingClassData"),
}
VARIABLE_SCOPES = (CK.TRANSLATION_UNIT, CK.NAMESPACE, CK.CLASS_DECL, CK.STRUCT_DECL)
SCALAR_KINDS = {
    ci.TypeKind.BOOL,
    ci.TypeKind.CHAR_U,
    ci.TypeKind.UCHAR,
    ci.TypeKind.CHAR16,
    ci.TypeKind.CHAR32,
    ci.TypeKind.USHORT,
    ci.TypeKind.UINT,
    ci.TypeKind.ULONG,
    ci.TypeKind.ULONGLONG,
    ci.TypeKind.CHAR_S,
    ci.TypeKind.SCHAR,
    ci.TypeKind.WCHAR,
    ci.TypeKind.SHORT,
    ci.TypeKind.INT,
    ci.TypeKind.LONG,
    ci.TypeKind.LONGLONG,
    ci.TypeKind.FLOAT,
    ci.TypeKind.DOUBLE,
    ci.TypeKind.LONGDOUBLE,
    ci.TypeKind.POINTER,
    ci.TypeKind.ENUM,
    ci.TypeKind.MEMBERPOINTER,
}


def enclosing_scopes(cursor):
    """Namespaces (outermost first) and whether any scope is a function or template."""
    namespaces = []
    local = False
    templated = False
    p = cursor.semantic_parent
    while p is not None and p.kind != CK.TRANSLATION_UNIT:
        if p.kind == CK.NAMESPACE:
            namespaces.insert(0, p.spelling)
        elif p.kind in FUNCTION_KINDS:
            local = True
        elif p.kind in TEMPLATE_KINDS:
            templated = True
        p = p.semantic_parent
    return namespaces, local, templated


def lexical_namespaces(cursor):
    names = []
    p = cursor.lexical_parent
    while p is not None and p.kind != CK.TRANSLATION_UNIT:
        if p.kind == CK.NAMESPACE:
            names.insert(0, p.spelling)
        p = p.lexical_parent
    return names


def qualified_class(cursor):
    parts = []
    p = cursor.semantic_parent
    while p is not None and p.kind in CLASS_KINDS + (CK.CLASS_TEMPLATE,):
        parts.insert(0, p.spelling)
        p = p.semantic_parent
    return "::".join(parts) if parts else None


def default_constructible(record_type):
    decl = record_type.get_declaration()
    ctors = [c for c in decl.get_children() if c.kind == CK.CONSTRUCTOR]
    if not ctors:
        return True
    for c in ctors:
        if c.access_specifier != ci.AccessSpecifier.PUBLIC:
            continue
        if all(any(t.spelling == "=" for t in p.get_tokens()) for p in c.get_arguments()):
            return True
    return False


def canonical_parameters(function_type):
    """A function type's parameters, each named from outside its class and namespace, without the top-level const or
    volatile that a function pointer type ignores."""
    return [t.spelling for t in function_type.get_canonical().argument_types()]


def classify_result(t):
    if t.kind == ci.TypeKind.VOID:
        return {"kind": "void"}
    canon = t.get_canonical()
    if canon.kind == ci.TypeKind.LVALUEREFERENCE:
        return {"kind": "ref"}
    if canon.kind in SCALAR_KINDS:
        return {"kind": "scalar"}
    if canon.kind == ci.TypeKind.RECORD:
        return {"kind": "record", "default_ctor": default_constructible(canon)}
    return {"kind": "other", "canonical": canon.spelling}


def name_span(cursor, data):
    """Byte offsets of the function's name as written at its definition, or None if not literal."""
    off = cursor.location.offset
    name = cursor.spelling
    if cursor.kind == CK.CONVERSION_FUNCTION:
        return None
    if name.startswith("operator"):
        toks = list(cursor.get_tokens())
        for i, t in enumerate(toks):
            if t.spelling == "operator" and t.location.offset == off and i + 1 < len(toks):
                end_tok = toks[i + 1]
                end = end_tok.extent.end.offset
                if end_tok.spelling in ("(", "[") and i + 2 < len(toks) and toks[i + 2].spelling in (")", "]"):
                    end = toks[i + 2].extent.end.offset
                if end_tok.spelling in ("new", "delete") and i + 2 < len(toks) and toks[i + 2].spelling == "[":
                    return None
                written = data[off:end].decode("cp1252")
                if "\n" in written:
                    return None
                return off, end, written
        return None
    if data[off : off + len(name)].decode("cp1252", "replace") != name:
        return None
    return off, off + len(name), name


def body_start(cursor):
    for ch in cursor.get_children():
        if ch.kind == CK.COMPOUND_STMT:
            return ch.extent.start.offset
    return None


def declaration_info(defn):
    """The separate declaration of a function (usually in its class), if there is one."""
    canon = defn.canonical
    if canon is None or canon == defn or not canon.location.file:
        return None
    if canon.location.file.name == defn.location.file.name and canon.location.offset == defn.location.offset:
        return None
    toks = list(canon.get_tokens())
    if not toks:
        return None
    params = list(canon.get_arguments())
    drop = []
    for p in params:
        ptoks = list(p.get_tokens())
        depth = 0
        for i, t in enumerate(ptoks):
            if t.spelling in ("(", "<", "["):
                depth += 1
            elif t.spelling in (")", ">", "]"):
                depth -= 1
            elif t.spelling == "=" and depth == 0:
                drop.append((t.extent.start.offset, p.extent.end.offset))
                break
    name_off = canon.location.offset
    kept = []
    for t in toks:
        o = t.extent.start.offset
        if any(a <= o < b for a, b in drop):
            continue
        if t.spelling == "virtual":
            continue
        kept.append(t)
    return {
        "file": os.path.abspath(canon.location.file.name),
        "extent_end": canon.extent.end.offset,
        "name_offset": name_off,
        "tokens": [(t.spelling, t.extent.start.offset) for t in kept],
    }


def analyze_tu(job):
    project, rel = job
    src = os.path.join(project.root, rel)
    idx = ci.Index.create()
    tu = idx.parse(src, args=project.clang_args(), options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    with open(src, "rb") as f:
        data = f.read()
    functions, variables = [], []

    def in_this_file(c):
        return c.location.file and os.path.normcase(os.path.abspath(c.location.file.name)) == os.path.normcase(src)

    for c in tu.cursor.walk_preorder():
        if c.kind in FUNCTION_KINDS and c.is_definition() and in_this_file(c):
            functions.append(function_record(c, data, rel, project))
        elif c.kind == CK.VAR_DECL and c.is_definition() and in_this_file(c):
            record = variable_record(c, project)
            if record:
                variables.append(record)
    bodies = [(fn["body_start"], fn["def_end"]) for fn in functions if fn["body_start"] is not None]
    return {"rel": rel, "errors": parse_errors(tu, src, bodies), "functions": functions, "variables": variables}


def parse_errors(tu, src, bodies):
    """(file, line, message, inside one of src's function bodies) for each error clang reported."""
    errors = []
    for d in tu.diagnostics:
        if d.severity < ci.Diagnostic.Error:
            continue
        path = os.path.abspath(d.location.file.name) if d.location.file else ""
        in_src = os.path.normcase(path) == os.path.normcase(src)
        in_body = in_src and any(s is not None and s <= d.location.offset < e for s, e in bodies)
        errors.append((path, d.location.line, d.spelling, in_body))
    return errors


def function_record(c, data, rel, project):
    namespaces, local, templated = enclosing_scopes(c)
    rec = {
        "usr": c.get_usr(),
        "kind": c.kind.name,
        "name": c.spelling,
        "displayname": c.displayname,
        "class": qualified_class(c),
        "namespaces": namespaces,
        "lex_namespaces": lexical_namespaces(c),
        "file": rel,
        "line": c.location.line,
        "static_method": c.is_static_method(),
        "const": c.is_const_method(),
        "virtual": c.is_virtual_method(),
        "storage": c.storage_class.name if c.storage_class else None,
        "linkage": c.linkage.name if c.linkage else None,
        "access": c.access_specifier.name if c.access_specifier else None,
    }
    reasons = []
    if c.kind in (CK.CONSTRUCTOR, CK.DESTRUCTOR):
        reasons.append("constructor or destructor")
    if c.kind == CK.CONVERSION_FUNCTION:
        reasons.append("conversion operator")
    if c.spelling in LOADER_ENTRY_POINTS:
        reasons.append("DLL entry point")
    if (rec["class"], c.spelling) in HOST_ENTRY_POINTS:
        reasons.append("calls into Bazaar")
    if c.spelling.startswith(("operator new", "operator delete")):
        reasons.append("allocation operator")
    if c.kind == CK.FUNCTION_TEMPLATE or templated:
        reasons.append("template")
    if local:
        reasons.append("defined inside another function")
    if c.type.kind == ci.TypeKind.FUNCTIONPROTO and c.type.is_function_variadic():
        reasons.append("variadic")
    span = name_span(c, data)
    if span is None and not reasons:
        reasons.append("name not written literally (macro or unusual form)")
    body = body_start(c)
    if body is None and not reasons:
        reasons.append("no body found")
    params = []
    for p in c.get_arguments():
        params.append(
            {
                "name": p.spelling,
                "type": p.type.spelling,
                "start": p.extent.start.offset,
                "end": p.extent.end.offset,
                "loc": p.location.offset,
                "canonical": p.type.get_canonical().kind.name,
            }
        )
    if not reasons:
        for p in params:
            if not p["name"] and p["canonical"] in ("POINTER",) and "(" in p["type"]:
                reasons.append("unnamed function-pointer parameter")
                break
            if p["canonical"] in ("CONSTANTARRAY", "INCOMPLETEARRAY"):
                reasons.append("array parameter")
                break
    rec["result"] = (
        classify_result(c.result_type) if c.kind not in (CK.CONSTRUCTOR, CK.DESTRUCTOR) else {"kind": "void"}
    )
    rec["result_type"] = c.result_type.spelling
    rec["canonical_result"] = c.result_type.get_canonical().spelling
    rec["canonical_params"] = canonical_parameters(c.type)
    parent = c.semantic_parent
    rec["canonical_class"] = parent.type.get_canonical().spelling if rec["class"] and parent else None
    if not reasons and rec["result"]["kind"] == "record" and not rec["result"].get("default_ctor"):
        reasons.append("returns a class without a default constructor")
    if not reasons and rec["result"]["kind"] == "other":
        reasons.append("unusual return type: " + rec["result"].get("canonical", ""))
    rec["params"] = params
    rec["def_start"] = c.extent.start.offset
    rec["def_end"] = c.extent.end.offset
    rec["body_start"] = body
    if span:
        rec["name_start"], rec["name_end"], rec["name_written"] = span
    rec["decl"] = declaration_info(c) if not reasons else None
    if not reasons and rec["class"] and rec["decl"] is None:
        reasons.append("member without a separate declaration")
    if rec["decl"] and not project.contains(rec["decl"]["file"]):
        reasons.append("declared outside the project")
    rec["skip"] = reasons
    exportable = not (templated or local or c.kind == CK.FUNCTION_TEMPLATE)
    rec["export_decl"] = export_declaration(c, project) if exportable else None
    return rec


def variable_record(c, project):
    """A variable defined here and first declared elsewhere in the project, normally a header, which plugins reach
    through the export marker. Not one whose first declaration gives its value: users compile that value in, and it
    cannot be imported."""
    if c.semantic_parent is None or c.semantic_parent.kind not in VARIABLE_SCOPES:
        return None
    ex = export_declaration(c, project)
    if ex is None or ex["is_definition"] or any(t.spelling == "=" for t in c.canonical.get_tokens()):
        return None
    return {"usr": c.get_usr(), "name": c.spelling, "export_decl": ex}


def export_declaration(defn, project):
    """Where to put the export marker: the start of the first declaration."""
    if defn.linkage != ci.LinkageKind.EXTERNAL:
        return None
    canon = defn.canonical
    if canon is None or not canon.location.file or not project.contains(canon.location.file.name):
        return None
    toks = list(canon.get_tokens())
    if not toks or toks[0].extent.start.offset != canon.extent.start.offset:
        return None
    return {
        "file": os.path.abspath(canon.location.file.name),
        "start": canon.extent.start.offset,
        "first_token": toks[0].spelling,
        "is_definition": canon == defn,
    }


def run(project):
    os.makedirs(project.build_dir, exist_ok=True)
    t = time.time()
    jobs = [(project, rel) for rel in project.sources]
    with multiprocessing.Pool(max(1, min(len(jobs), os.cpu_count() or 4))) as pool:
        results = pool.map(analyze_tu, jobs)
    with open(os.path.join(project.build_dir, "analysis.json"), "w") as f:
        json.dump(results, f)
    funcs = [fn for r in results for fn in r["functions"]]
    hookable = [fn for fn in funcs if not fn["skip"]]
    variables = sum(len(r["variables"]) for r in results)
    print(
        "translation units %d, functions %d, hookable %d, shared variables %d, seconds %.0f"
        % (len(results), len(funcs), len(hookable), variables, time.time() - t)
    )
    reasons = {}
    for fn in funcs:
        for r in fn["skip"]:
            reasons[r] = reasons.get(r, 0) + 1
    for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("  skipped, %s: %d" % (r, n))
    in_bodies = {(e[0], e[1], e[2]) for r in results for e in r["errors"] if project.contains(e[0]) and e[3]}
    errors = project_errors(project, results)
    print("parse errors in project files: %d inside function bodies, %d new elsewhere" % (len(in_bodies), len(errors)))
    for e in sorted(errors)[:20]:
        print("  %s:%d %s" % (os.path.basename(e[0]), e[1], e[2]))
    return results


def parse_as_plugin(project, header, code=""):
    """A plugin source that includes header, followed by code."""
    probe = os.path.join(os.path.dirname(header), "civ_plugin_probe.cpp")
    source = '#include "%s"\n%s' % (os.path.basename(header), code)
    args = project.clang_args() + ["-I" + os.path.dirname(header), "-I" + common.HOST_DIR]
    return ci.Index.create().parse(probe, args=args, unsaved_files=[(probe, source)])


def check_plugin_header(project, header):
    """Parses CivHooks.h as a plugin includes it. Returns the lines of header with an error, and each Original
    typedef's canonical types by line: (result, parameters)."""
    header = os.path.normcase(os.path.abspath(header))
    tu = parse_as_plugin(project, header)
    known = common.known_errors()
    lines = set()
    for d in tu.diagnostics:
        path = os.path.abspath(d.location.file.name) if d.location.file else ""
        if d.severity == ci.Diagnostic.Fatal or (
            d.severity >= ci.Diagnostic.Error
            and project.contains(path)
            and not common.known_error(known, path, d.location.line, d.spelling)
        ):
            # Types the game's headers no longer declare would leave hook points untyped without a word.
            where = "%s:%d " % (common.shown(path), d.location.line) if path else ""
            raise RuntimeError("generator: could not read the game's headers as a plugin does: " + where + d.spelling)
        if d.severity >= ci.Diagnostic.Error and os.path.normcase(path) == header:
            lines.add(d.location.line)
    originals = {}
    for space in tu.cursor.get_children():
        if space.spelling != "CivHooks" or not space.location.file:
            continue
        if os.path.normcase(os.path.abspath(space.location.file.name)) != header:
            continue
        for c in (c for struct in space.get_children() for c in struct.get_children()):
            original = c.kind == CK.TYPEDEF_DECL and c.spelling == "Original"
            fn = c.underlying_typedef_type.get_canonical().get_pointee() if original else None
            if fn is not None and fn.kind == ci.TypeKind.FUNCTIONPROTO:
                originals[c.location.line] = (fn.get_result().get_canonical().spelling, canonical_parameters(fn))
    return lines, originals


def project_errors(project, results):
    """New parse errors in the project outside function bodies: they can hide functions, so the build must stop.
    Errors inside a body cannot, since the generator never needs a body's contents."""
    known = common.known_errors()
    return {
        (e[0], e[1], e[2])
        for r in results
        for e in r["errors"]
        if project.contains(e[0]) and not e[3] and not common.known_error(known, e[0], e[1], e[2])
    }


if __name__ == "__main__":
    project = common.engine_project()
    sys.exit(1 if project_errors(project, run(project)) else 0)
