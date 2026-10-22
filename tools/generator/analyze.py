"""Find every function defined in the engine's source files and every class in its headers.

Writes BuildTemp/civgen/analysis.json, which generate.py turns into hook wrappers.
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


def analyze_tu(rel):
    src = os.path.join(common.ENGINE_DIR, rel)
    idx = ci.Index.create()
    tu = idx.parse(src, args=common.clang_args(), options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    data = open(src, "rb").read()
    errors = [
        (os.path.abspath(d.location.file.name) if d.location.file else "", d.location.line, d.spelling)
        for d in tu.diagnostics
        if d.severity >= ci.Diagnostic.Error
    ]
    functions = []
    classes = []
    for c in tu.cursor.walk_preorder():
        if c.kind in FUNCTION_KINDS and c.is_definition() and c.location.file:
            path = os.path.abspath(c.location.file.name)
            if os.path.normcase(path) != os.path.normcase(src):
                continue
            functions.append(function_record(c, data, rel))
        elif c.kind in CLASS_KINDS + TEMPLATE_KINDS and c.is_definition() and c.location.file:
            path = os.path.abspath(c.location.file.name)
            if not common.is_engine_file(path) or c.kind == CK.FUNCTION_TEMPLATE:
                continue
            namespaces, local, templated = enclosing_scopes(c)
            classes.append(
                {
                    "usr": c.get_usr(),
                    "name": c.spelling,
                    "kind": c.kind.name,
                    "file": path,
                    "line": c.location.line,
                    "name_offset": c.location.offset,
                    "template": c.kind != CK.CLASS_DECL and c.kind != CK.STRUCT_DECL or templated,
                    "local": local,
                    "in_source_file": path.lower().endswith(".cpp"),
                    "outer_class": qualified_class(c),
                }
            )
    return {"rel": rel, "errors": errors, "functions": functions, "classes": classes}


def function_record(c, data, rel):
    namespaces, local, templated = enclosing_scopes(c)
    rec = {
        "usr": c.get_usr(),
        "kind": c.kind.name,
        "name": c.spelling,
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
    rec["skip"] = reasons
    rec["export_decl"] = export_declaration(c) if not (templated or local or c.kind == CK.FUNCTION_TEMPLATE) else None
    return rec


def export_declaration(defn):
    """Where to put the export marker: the start of the function's first declaration."""
    if defn.linkage != ci.LinkageKind.EXTERNAL:
        return None
    canon = defn.canonical
    if canon is None or not canon.location.file or not common.is_engine_file(canon.location.file.name):
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


def main():
    os.makedirs(common.BUILD_DIR, exist_ok=True)
    sources = common.engine_sources()
    t = time.time()
    with multiprocessing.Pool(min(len(sources), os.cpu_count() or 4)) as pool:
        results = pool.map(analyze_tu, sources)
    out = os.path.join(common.BUILD_DIR, "analysis.json")
    with open(out, "w") as f:
        json.dump(results, f)
    funcs = [fn for r in results for fn in r["functions"]]
    hookable = [fn for fn in funcs if not fn["skip"]]
    print(
        "translation units %d, functions %d, hookable %d, seconds %.0f"
        % (len(results), len(funcs), len(hookable), time.time() - t)
    )
    reasons = {}
    for fn in funcs:
        for r in fn["skip"]:
            reasons[r] = reasons.get(r, 0) + 1
    for r, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print("  skipped, %s: %d" % (r, n))
    engine_errors = {(e[0], e[1], e[2]) for r in results for e in r["errors"] if common.is_engine_file(e[0])}
    print("parse errors in engine files: %d" % len(engine_errors))
    for e in sorted(engine_errors)[:20]:
        print("  %s:%d %s" % (os.path.basename(e[0]), e[1], e[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
