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
    return common.Project(root, sources, [root, common.HOST_DIR], BUILD, os.path.join(BUILD, "hook-ids.txt"))


def generate_hooks(sources):
    project = fixture_project(sources)
    if analyze.project_errors(project, analyze.run(project)):
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


def export_marker_problems():
    """A global variable and a static member variable are marked for export in the generated header."""
    with open(os.path.join(BUILD, "src", "fixture", "fake_engine.h")) as f:
        header = f.read()
    expected = ["CIV_HOST_API extern int g_levelCalls;", "CIV_HOST_API static int s_created;"]
    return ["%r is not marked for export" % line for line in expected if line not in header]


if __name__ == "__main__":
    registry = os.path.join(BUILD, "hook-ids.txt")
    if os.path.exists(registry):
        os.remove(registry)
    first = generate_hooks(["fake_engine.cpp"])
    second = generate_hooks(["aaa_extra.cpp", "fake_engine.cpp"])
    third = generate_hooks(["fake_engine.cpp"])
    problems = registry_problems(first, second, third) + key_format_problems(first) + export_marker_problems()
    if problems:
        print("FAIL: " + "; ".join(problems))
        sys.exit(1)
    sys.exit(0)
