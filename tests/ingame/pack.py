"""Pack a mod folder laid out by package.py into a .civ5mod package for uploading to the Steam Workshop.

usage: pack.py "<mod folder name in tests/ingame/out/MODS>"
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import mods  # noqa: E402

MODS = os.path.join(HERE, "out", "MODS")
PACKAGES = os.path.join(HERE, "out", "Packages")


def main(args):
    if len(args) != 1 or not os.path.isdir(os.path.join(MODS, args[0])):
        print(__doc__)
        return 1
    os.makedirs(PACKAGES, exist_ok=True)
    package = os.path.join(PACKAGES, args[0] + ".civ5mod")
    problem = mods.pack(os.path.join(MODS, args[0]), package)
    if problem:
        print(problem)
        return 1
    print(package)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
