"""What the compiler's layout report leaves out, read with libclang: the type of each field, the parameters of each
virtual function and the value of each enum constant. Plugins compile all three in, so changing one breaks them even
when no size or position changes. The blocks join the report's in the layout record. Class templates are left out:
the compiler's report has the sizes and positions of the ones the headers use."""

import os
import re
from importlib import metadata

import clang.cindex as ci

import common

CK = ci.CursorKind
RECORD_KINDS = {CK.CLASS_DECL: "class", CK.STRUCT_DECL: "struct", CK.UNION_DECL: "union"}
# clang names an unnamed type by its place in the file, which moves whenever a line above it does.
UNNAMED_AT = re.compile(r"((?:\w+::)*)\((unnamed|anonymous) (\w+) at .*?:\d+:\d+\)")
FOLDERS = [common.SOURCE_ROOT, common.HOST_DIR]
REQUIREMENTS = os.path.join(common.HERE, "requirements.txt")


def read(unit, includes, folders=FOLDERS):
    """The blocks for the types the headers under folders declare, as sorted (key, text) pairs."""
    check_libclang()
    args = common.clang_arguments(common.PLUGIN_DEFINES + common.CL_DEFINES, includes)
    tu = ci.Index.create().parse(unit, args=args, options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES)
    check_errors(tu, folders)
    blocks = []
    walk(tu.cursor, folders, blocks)
    return sorted(blocks)


def check_libclang():
    with open(REQUIREMENTS, encoding="utf-8") as f:
        pin = re.search(r"^libclang==(\S+)", f.read(), re.M)
    if not pin:
        raise RuntimeError("tools\\generator\\requirements.txt must name one libclang version, as libclang==<version>.")
    try:
        installed = metadata.version("libclang")
    except metadata.PackageNotFoundError:
        installed = None
    if installed != pin.group(1):
        found = "libclang %s is installed" % installed if installed else "libclang's pip package is not installed"
        raise RuntimeError(
            "The layout record holds the types as libclang %s spells them, but %s: run .venv\\Scripts\\python.exe "
            "-m pip install -r tools\\generator\\requirements.txt" % (pin.group(1), found)
        )


def check_errors(tu, folders):
    known = common.known_errors()
    for d in tu.diagnostics:
        path = d.location.file.name if d.location.file else ""
        if d.severity == ci.Diagnostic.Fatal or (
            d.severity >= ci.Diagnostic.Error
            and common.under(path, folders)
            and not common.known_error(known, path, d.location.line, d.spelling)
        ):
            where = "%s line %d: " % (common.shown(path), d.location.line) if path else ""
            raise RuntimeError("libclang could not read the headers as a plugin does: " + where + d.spelling)


def walk(scope, folders, blocks):
    for c in scope.get_children():
        if c.kind in (CK.NAMESPACE, CK.LINKAGE_SPEC):
            walk(c, folders, blocks)
        elif not (c.is_definition() and c.location.file and common.under(c.location.file.name, folders)):
            continue
        elif c.kind in RECORD_KINDS:
            # An unnamed one's fields are in the block of the class around it.
            if not c.is_anonymous():
                blocks += class_block(c)
            walk(c, folders, blocks)
        elif c.kind == CK.ENUM_DECL:
            blocks += enum_blocks(c)


def class_block(record):
    lines = [" field " + f for f in fields(record)]
    lines += [
        " virtual %s %s" % (m.spelling, spelled(m.type))
        for m in record.get_children()
        if m.kind == CK.CXX_METHOD and m.is_virtual_method()
    ]
    key = "types " + spelled(record.type)
    return [(key, "\n".join([key + ":"] + lines))] if lines else []


def enum_blocks(enum):
    """One block per constant, named as C++ names it, without the enum's own name."""
    values = [c for c in enum.get_children() if c.kind == CK.ENUM_CONSTANT_DECL]
    # CivPluginApi.h ends its enum of hook ids with a count, which grows whenever an id is added, as plugins allow.
    if values and values[-1].spelling.endswith("_COUNT") and common.under(enum.location.file.name, [common.HOST_DIR]):
        values.pop()
    blocks = []
    for value in values:
        key = "enum " + scope_prefix(enum) + value.spelling
        blocks.append((key, "%s = %d" % (key, value.enum_value)))
    return blocks


def scope_prefix(cursor):
    names = []
    parent = cursor.semantic_parent
    while parent is not None and parent.kind != CK.TRANSLATION_UNIT:
        if parent.kind in RECORD_KINDS and not parent.is_anonymous():
            names.insert(0, spelled(parent.type))
            break
        if parent.kind == CK.NAMESPACE:
            names.insert(0, parent.spelling)
        parent = parent.semantic_parent
    return "".join(name + "::" for name in names)


def fields(record):
    """Each field as "name: type", with an anonymous union's or struct's own fields in braces where it stands."""
    children = list(record.get_children())
    typed = [declared(c.type) for c in children if c.kind == CK.FIELD_DECL]
    out = []
    for c in children:
        if c.kind == CK.FIELD_DECL:
            width = " : %d" % c.get_bitfield_width() if c.is_bitfield() else ""
            out.append("%s: %s%s" % (c.spelling, spelled(c.type), width))
        elif c.kind in RECORD_KINDS and c.is_anonymous() and c not in typed:
            out.append(unnamed(c))
    return out


def declared(t):
    t = t.get_canonical()
    while t.kind in (ci.TypeKind.POINTER, ci.TypeKind.CONSTANTARRAY, ci.TypeKind.INCOMPLETEARRAY):
        t = t.get_pointee() if t.kind == ci.TypeKind.POINTER else t.element_type
    return t.get_declaration()


def unnamed(record):
    return "%s { %s }" % (RECORD_KINDS[record.kind], "; ".join(fields(record)))


def spelled(t):
    canon = t.get_canonical()
    decl = declared(canon)
    if decl.kind in RECORD_KINDS and decl.is_anonymous():
        spelling = UNNAMED_AT.sub(lambda m: unnamed(decl), canon.spelling, count=1)
    else:
        spelling = canon.spelling
    return UNNAMED_AT.sub(r"\1(\2 \3)", spelling)
