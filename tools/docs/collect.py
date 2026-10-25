"""Read one source file with clang for the docs."""

import ctypes
import os

import clang.cindex as ci

import analyze
import common
import history

CK = ci.CursorKind
# Bazaar's build defines CIV_HOST_API; without it the engine's calls into Bazaar read as left out of the build, and no
# page shows a hand-placed hook.
BUILD_ARGS = ["-DCIV_HOST_API=", "-I" + common.HOST_DIR] + ["-D" + d for d in common.LAYOUT_DEFINES]
CALLABLE = (
    CK.CXX_METHOD,
    CK.FUNCTION_DECL,
    CK.CONSTRUCTOR,
    CK.DESTRUCTOR,
    CK.CONVERSION_FUNCTION,
    CK.FUNCTION_TEMPLATE,
)
CLASS_SCOPES = analyze.CLASS_KINDS + (CK.CLASS_TEMPLATE,)
SCOPE_KINDS = (CK.NAMESPACE, CK.LINKAGE_SPEC, CK.UNEXPOSED_DECL) + CLASS_SCOPES


class SourceRangeList(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint), ("ranges", ctypes.POINTER(ci.SourceRange))]


lib = ci.conf.lib
lib.clang_getSkippedRanges.argtypes = [ci.TranslationUnit, ci.File]
lib.clang_getSkippedRanges.restype = ctypes.POINTER(SourceRangeList)
lib.clang_disposeSourceRangeList.argtypes = [ctypes.POINTER(SourceRangeList)]
lib.clang_disposeSourceRangeList.restype = None
lib.clang_getOverriddenCursors.argtypes = [
    ci.Cursor,
    ctypes.POINTER(ctypes.POINTER(ci.Cursor)),
    ctypes.POINTER(ctypes.c_uint),
]
lib.clang_getOverriddenCursors.restype = None
lib.clang_disposeOverriddenCursors.argtypes = [ctypes.POINTER(ci.Cursor)]
lib.clang_disposeOverriddenCursors.restype = None


def excluded_ranges(tu, path):
    found = lib.clang_getSkippedRanges(tu, ci.File.from_name(tu, path))
    try:
        return [(r.start.offset, r.end.offset) for r in found.contents.ranges[: found.contents.count]]
    finally:
        lib.clang_disposeSourceRangeList(found)


def overridden(method):
    found = ctypes.POINTER(ci.Cursor)()
    count = ctypes.c_uint()
    lib.clang_getOverriddenCursors(method, ctypes.byref(found), ctypes.byref(count))
    usrs = []
    for i in range(count.value):
        base = found[i]
        base._tu = method._tu
        usrs.append(base.get_usr())
    if count.value:
        lib.clang_disposeOverriddenCursors(found)
    return usrs


def scope_of(cursor):
    parts = []
    p = cursor.semantic_parent
    while p is not None and p.kind != CK.TRANSLATION_UNIT:
        if p.kind in CLASS_SCOPES or (p.kind == CK.NAMESPACE and p.spelling):
            parts.insert(0, p.spelling)
        p = p.semantic_parent
    return "::".join(parts)


def scoped(cursor):
    scope = scope_of(cursor)
    return scope + "::" + cursor.spelling if scope else cursor.spelling


def same_file(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def references(fn, path):
    """A construction has no name of its own to link from, so it gets no offset: a link would land on the variable."""
    refs = []
    stack = list(fn.get_children())
    while stack:
        c = stack.pop()
        stack.extend(c.get_children())
        if c.kind not in (CK.DECL_REF_EXPR, CK.MEMBER_REF_EXPR, CK.CALL_EXPR):
            continue
        target = c.referenced
        if target is None or target.kind not in CALLABLE:
            continue
        if c.kind == CK.CALL_EXPR and target.kind != CK.CONSTRUCTOR:
            continue
        loc = c.location
        linkable = c.kind != CK.CALL_EXPR and loc.file is not None and same_file(loc.file.name, path)
        refs.append((target.get_usr(), loc.offset if linkable else None, scoped(target)))
    return refs


def in_project(cursor, project):
    return cursor.location.file is not None and project.contains(cursor.location.file.name)


def function_entry(c, project, texts, ranges, tu):
    path = os.path.abspath(c.location.file.name)
    if path not in texts:
        with open(path, "rb") as f:
            texts[path] = f.read()
        ranges[path] = excluded_ranges(tu, path)
    rec = analyze.function_record(c, texts[path], os.path.relpath(path, project.root), project)
    scope = scope_of(c)
    owner = c.semantic_parent is not None and c.semantic_parent.kind in CLASS_SCOPES
    rec["owner"] = scope if owner else None
    rec["title"] = (scope + "::" if scope else "") + c.displayname + (" const" if rec["const"] else "")
    rec["refs"] = references(c, path) if c.is_definition() else []
    rec["overrides"] = overridden(c) if c.kind == CK.CXX_METHOD and c.is_virtual_method() else []
    rec["pure"] = c.kind == CK.CXX_METHOD and c.is_pure_virtual_method() and not c.is_definition()
    rec["excluded"] = ranges[path]
    rec["fingerprint"] = history.fingerprint(t.spelling for t in c.get_tokens() if t.kind != ci.TokenKind.COMMENT)
    return rec


def collect_tu(job):
    project, rel = job
    src = os.path.join(project.root, rel)
    tu = ci.Index.create().parse(
        src, args=project.clang_args() + BUILD_ARGS, options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
    )
    texts, ranges, functions, classes = {}, {}, [], []
    stack = [c for c in tu.cursor.get_children() if in_project(c, project)]
    while stack:
        c = stack.pop()
        if c.kind in analyze.FUNCTION_KINDS and (c.is_definition() or c.is_pure_virtual_method()):
            functions.append(function_entry(c, project, texts, ranges, tu))
            continue
        if c.kind in CLASS_SCOPES and c.is_definition():
            bases = [b.referenced for b in c.get_children() if b.kind == CK.CXX_BASE_SPECIFIER and b.referenced]
            classes.append(
                {
                    "name": scoped(c),
                    "file": os.path.relpath(os.path.abspath(c.location.file.name), project.root),
                    "line": c.location.line,
                    "bases": [scoped(b) for b in bases],
                }
            )
        if c.kind in SCOPE_KINDS:
            stack.extend(c.get_children())
    own = [f for f in functions if same_file(os.path.join(project.root, f["file"]), src)]
    bodies = [(f["body_start"], f["def_end"]) for f in own]
    return {"rel": rel, "functions": functions, "classes": classes, "errors": analyze.parse_errors(tu, src, bodies)}
