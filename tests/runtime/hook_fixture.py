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


def duplicate_problems():
    path = os.path.join(BUILD, "duplicate-ids.txt")
    os.makedirs(BUILD, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("0\tA\tfirst()\n0\tB\tsecond()\n")
    try:
        generate.Registry(path)
    except RuntimeError:
        return []
    return ["a registry that repeats an id was accepted"]


def naming_problems():
    """Names that would not be valid, unreserved C++: a file name with a leading digit, a __ type."""
    local = {"name": "Helper", "namespaces": [], "class": None, "linkage": "INTERNAL", "file": "2DGrid.cpp"}
    local.update(params=[], const=False)
    overload = {"name": "Pack", "namespaces": [], "class": "CvUnit", "linkage": "EXTERNAL", "file": "CvUnit.cpp"}
    overload.update(params=[{"type": "unsigned __int64"}], const=False)
    expected = [
        (generate.hook_name(local, set()), "File_2DGrid_cpp_Helper"),
        (generate.hook_name(overload, {"CvUnit_Pack"}), "CvUnit_Pack_with_unsigned_int64"),
    ]
    return ["%s, expected %s" % pair for pair in expected if pair[0] != pair[1]]


if __name__ == "__main__":
    problems = naming_problems() + duplicate_problems()
    registry = os.path.join(BUILD, "hook-ids.txt")
    if os.path.exists(registry):
        os.remove(registry)
    first = generate_hooks(["fake_engine.cpp"])
    second = generate_hooks(["aaa_extra.cpp", "fake_engine.cpp"])
    third = generate_hooks(["fake_engine.cpp"])
    problems += registry_problems(first, second, third)
    if problems:
        print("FAIL: " + "; ".join(problems))
        sys.exit(1)
    sys.exit(0)
