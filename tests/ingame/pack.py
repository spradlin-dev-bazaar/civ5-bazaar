"""Pack a mod folder laid out by package.py into a .civ5mod package for uploading to the Steam Workshop.

usage: pack.py "<mod folder name in tests/ingame/out/MODS>"

A package holds one mod, with its files at the top and no folder around them; the game makes the folder when it
installs it. ModBuddy's upload refuses a package with more than one mod description in it, even in a subfolder.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODS = os.path.join(HERE, "out", "MODS")
PACKAGES = os.path.join(HERE, "out", "Packages")
# Windows' own tar is libarchive, which writes 7z; LZMA is what ModBuddy's packages use.
TAR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")


def main(args):
    if len(args) != 1 or not os.path.isdir(os.path.join(MODS, args[0])):
        print(__doc__)
        return 1
    folder = os.path.join(MODS, args[0])
    os.makedirs(PACKAGES, exist_ok=True)
    package = os.path.join(PACKAGES, args[0] + ".civ5mod")
    if os.path.exists(package):
        os.remove(package)
    entries = sorted(os.listdir(folder))
    if not os.path.isfile(TAR):
        print("Windows' tar.exe was not found at %s." % TAR)
        return 1
    cmd = [TAR, "-c", "--format", "7zip", "--options", "7zip:compression=lzma1", "-f", package, "-C", folder] + entries
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout + p.stderr)
        if os.path.exists(package):
            os.remove(package)
        return 1
    print(package)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
