"""Run the real generator over the test fixture, so the runtime tests exercise its actual output.

It generates three times. The second run adds a function that the generator reaches first, which must
take a new id while every existing function keeps its own; the third run removes it again.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "generator"))

import analyze  # noqa: E402
import common  # noqa: E402
import generate  # noqa: E402


BUILD = os.path.join(HERE, "out", "civgen")


def fixture_project(sources):
    root = os.path.join(HERE, "fixture")
    registry = os.path.join(BUILD, "hook-ids.txt")
    return common.Project(root, sources, [root, common.HOST_DIR], BUILD, registry, plugin_include="fake_engine.h")


def generate_hooks(sources):
    project = fixture_project(sources)
    if analyze.stopping_errors(project, analyze.run(project)):
        raise SystemExit("FAIL: the fixture does not parse")
    return dict((fn["hook_key"], (fn["hook_id"], fn["hook_name"])) for fn in generate.run(project))


def registry_problems(first, second, third):
    problems = ["%s changed from %s to %s" % (k, first[k], second[k]) for k in first if second.get(k) != first[k]]
    newest = max(i for i, _ in first.values())
    problems += [
        "%s took id %d, not a new one" % (k, v[0]) for k, v in second.items() if k not in first and v[0] <= newest
    ]
    if len(second) != len(first) + 1:
        problems.append("the added function did not get a hook")
    if third != first:
        problems.append("removing the added function changed the others")
    return problems


def key_format_problems(hooks):
    """A libclang change to this format would give every function a new hook number."""
    expected = ["FakeUnit::Grow(int) const", "FakeUnit::Grow(int, int) const"]
    problems = ["no hook has the key %r" % key for key in expected if key not in hooks]
    return problems + ["%r says const twice" % key for key in hooks if "const const" in key]


def shape_format_problems():
    """A libclang change to how it spells a type would give every function with such a type a new hook number."""
    shapes = dict(generate.Registry(os.path.join(BUILD, "hook-ids.txt")).entries.keys())
    expected = {
        "FakeUnit::name() const": "const std::string &",
        "FakeUnit::Twice(int)": "static int",
        "FakeUnit::Level() const": "const int",
    }
    return ["%r has the shape %r, not %r" % (k, shapes.get(k), v) for k, v in expected.items() if shapes.get(k) != v]


def gone_hook_problems():
    """The third run leaves Extra gone: CivHooks.h says so instead of naming it, and the toys get its number."""
    entries = generate.Registry(os.path.join(BUILD, "hook-ids.txt")).entries
    gone = [hook_id for (key, _), (hook_id, _) in entries.items() if key == "Extra(int)"]
    with open(os.path.join(BUILD, "sdk", "CivHooks.h")) as f:
        header = f.read()
    problems = ["Extra is still a hook point in CivHooks.h"] if "struct Extra " in header else []
    problems += [] if "// Extra (id " in header else ["CivHooks.h does not say Extra is gone"]
    with open(os.path.join(BUILD, "sdk", "ToyGoneHook.h"), "w") as f:
        f.write("#define TOY_GONE_HOOK_ID %d\n" % (gone[0] if gone else -1))
    return problems + ([] if len(gone) == 1 else ["Extra has %d rows" % len(gone)])


def export_marker_problems():
    """A global variable and a static member variable are marked for export in the generated header."""
    with open(os.path.join(BUILD, "src", "fixture", "fake_engine.h")) as f:
        header = f.read()
    expected = ["CIV_HOST_API extern int g_levelCalls;", "CIV_HOST_API static int s_created;"]
    return ["%r is not marked for export" % line for line in expected if line not in header]


def typed_header_problems():
    """CivHooks.h types each hook point a plugin can name, as the function's own types, and a hook of the wrong type
    fails to compile."""
    header = os.path.join(BUILD, "sdk", "CivHooks.h")
    with open(header) as f:
        text = f.read()
    typed = dict((name, has_types) for name, _, has_types in generate.header_hooks(text))
    problems = [] if typed.get("FakeUnit_add") else ["FakeUnit_add has no types in CivHooks.h"]
    if typed.get("FakeUnit_Peek", True):
        problems.append("FakeUnit_Peek, which takes a private type that a global type shares a name with, has types")
    if "typedef int (*Original)(const FakeUnit *, FakeUnit::Mood);" not in text:
        problems.append("FakeUnit_Feel, which takes a nested type written without its class, is not typed qualified")
    project = fixture_project(["fake_engine.cpp"])
    for result, should_compile in (("int& result", True), ("long& result", False), ("", False)):
        code = (
            "static void AfterAdd(const FakeUnit*, int, int%s) {}\n"
            "int Register(const CivHostInfo* host)\n"
            "{ return CivRegisterAfter<CivHooks::FakeUnit_add>(host, &AfterAdd); }\n"
        ) % (", " + result if result else "")
        tu = analyze.parse_as_plugin(project, header, code)
        compiled = not any(d.severity >= analyze.ci.Diagnostic.Error for d in tu.diagnostics)
        if compiled != should_compile:
            outcome = "compiles" if compiled else "fails to compile"
            problems.append("an after-hook on FakeUnit::add taking %r %s" % (result, outcome))
    return problems


if __name__ == "__main__":
    registry = os.path.join(BUILD, "hook-ids.txt")
    if os.path.exists(registry):
        os.remove(registry)
    first = generate_hooks(["fake_engine.cpp"])
    second = generate_hooks(["aaa_extra.cpp", "fake_engine.cpp"])
    third = generate_hooks(["fake_engine.cpp"])
    problems = registry_problems(first, second, third) + key_format_problems(first) + export_marker_problems()
    problems += shape_format_problems() + gone_hook_problems() + typed_header_problems()
    if problems:
        print("FAIL: " + "; ".join(problems))
        sys.exit(1)
    sys.exit(0)
