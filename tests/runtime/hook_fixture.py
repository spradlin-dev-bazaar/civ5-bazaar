"""Run the real generator over the test fixture, so the runtime tests exercise its actual output.

It generates twice: the second run must reload the id registry and change nothing.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "generator"))

import analyze  # noqa: E402
import common  # noqa: E402
import generate  # noqa: E402


def fixture_project():
    root = os.path.join(HERE, "fixture")
    build = os.path.join(HERE, "out", "civgen")
    return common.Project(
        root, ["fake_engine.cpp"], [root, common.HOST_DIR], build, os.path.join(build, "hook-ids.txt")
    )


def ids(hooks):
    return sorted((fn["hook_key"], fn["hook_id"], fn["hook_name"]) for fn in hooks)


if __name__ == "__main__":
    project = fixture_project()
    if os.path.exists(project.registry):
        os.remove(project.registry)
    analyze.run(project)
    first = generate.run(project)
    second = generate.run(project)
    if not first or ids(first) != ids(second):
        print("FAIL: a second generator run changed hook ids or names")
        sys.exit(1)
    sys.exit(0)
