"""Copy tools/bazaar_check into the plugin template and the Lua mod template, which ship it to mod authors and must
hold the same files.

    .venv\\Scripts\\python.exe tools\\sync_checker.py
"""

import filecmp
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "bazaar_check")
COPIES = [
    os.path.join(HERE, "..", "sdk", "plugin-template", "bazaar_check"),
    os.path.join(HERE, "..", "claude-plugin", "skills", "new-lua-mod", "template", "bazaar_check"),
]


def listing(folder):
    found = set()
    for path, folders, names in os.walk(folder):
        folders[:] = [name for name in folders if name != "__pycache__"]
        found |= {os.path.relpath(os.path.join(path, name), folder) for name in names}
    return found


def differences(copy):
    """The files of tools/bazaar_check that copy lacks, holds with other bytes, or adds."""
    mine, theirs = listing(SOURCE), listing(copy)
    same = {name for name in mine & theirs if filecmp.cmp(os.path.join(SOURCE, name), os.path.join(copy, name), False)}
    return sorted((mine | theirs) - same)


def main():
    for copy in COPIES:
        if os.path.exists(copy):
            shutil.rmtree(copy)
        shutil.copytree(SOURCE, copy, ignore=shutil.ignore_patterns("__pycache__"))
        print("copied tools/bazaar_check into", os.path.normpath(copy))


if __name__ == "__main__":
    main()
