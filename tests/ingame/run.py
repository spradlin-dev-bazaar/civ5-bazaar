"""Bazaar's in-game checks: build the test plugins, then play each checks file in checks/ in Civilization V with nobody
at the keyboard, and print what passed. Needs a build-hooked.cmd build. Each run puts back everything it changed in the
player's folder, MODS included. A checks file with test DLC packs in dlc/NAME/ has them in the game's own DLC folder
for its run only. With --play, build them and start the game with one checks file's mods switched on, to play by hand;
closing the game puts everything back.

    python tests/ingame/run.py [NAME ...]     NAME is a checks file in checks/, such as crash_turn; all by default
    python tests/ingame/run.py --play NAME
"""

import contextlib
import glob
import os
import re
import shutil
import sys
import winreg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import package  # noqa: E402
from bazaar_check import CheckError, files, game, runner  # noqa: E402

CHECKS = os.path.join(HERE, "checks")
PACKS = os.path.join(HERE, "dlc")
CIV5_APP = 8930
LEFT_IN_GAME = "could not take %s out of the game's DLC folder: delete it by hand"


def checks_path(name):
    return os.path.join(CHECKS, name + ".toml")


def steam_folder():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
        return winreg.QueryValueEx(key, "SteamPath")[0]


def dlc_folder(steam=None):
    """Civilization V's DLC folder, from Steam's list of its library folders."""
    try:
        with open(os.path.join(steam or steam_folder(), "steamapps", "libraryfolders.vdf"), encoding="utf-8") as f:
            libraries = [path.replace("\\\\", "\\") for path in re.findall(r'"path"\s+"([^"]*)"', f.read())]
        for library in libraries:
            manifest = os.path.join(library, "steamapps", "appmanifest_%d.acf" % CIV5_APP)
            if os.path.isfile(manifest):
                with open(manifest, encoding="utf-8") as f:
                    found = re.search(r'"installdir"\s+"([^"]*)"', f.read())
                if found:
                    return os.path.join(library, "steamapps", "common", found.group(1), "Assets", "DLC")
    except OSError as e:
        raise CheckError("could not find Civilization V's folder through Steam: %s" % e)
    raise CheckError("Steam lists no Civilization V install")


def packs_for(name):
    return sorted(
        pack for pack in glob.glob(os.path.join(glob.escape(PACKS), glob.escape(name), "*")) if os.path.isdir(pack)
    )


def remove_packs(dlc):
    """Returns the test packs still in the game's DLC folder. Only a folder holding a test pack's own package file
    counts as one, so the game's own pack of the same name stays."""
    left = []
    for package_file in glob.glob(os.path.join(glob.escape(PACKS), "*", "*", "*.Civ5Pkg")):
        target = os.path.join(dlc, os.path.basename(os.path.dirname(package_file)))
        if not os.path.isfile(os.path.join(target, os.path.basename(package_file))):
            continue
        with contextlib.suppress(OSError):
            files.remove_tree(target)
        if os.path.exists(target):
            left.append(target)
    return left


@contextlib.contextmanager
def packs_in_game(name):
    """The game reads its DLC folder as it starts, and every later game would read a pack left there."""
    packs = packs_for(name)
    if not packs:
        yield
        return
    dlc = dlc_folder()
    try:
        remove_packs(dlc)
        for pack in packs:
            try:
                shutil.copytree(pack, os.path.join(dlc, os.path.basename(pack)))
            except OSError as e:
                raise CheckError(
                    "could not put the test pack %s in the game's DLC folder: %s" % (os.path.basename(pack), e)
                )
        yield
    finally:
        left = remove_packs(dlc)
    if left:
        raise CheckError(LEFT_IN_GAME % " and ".join(left))


def main(argv):
    playing = argv[:1] == ["--play"]
    names = argv[1:] if playing else argv
    if playing and len(names) != 1:
        print(__doc__.strip())
        return 2
    names = names or sorted(name[: -len(".toml")] for name in os.listdir(CHECKS) if name.endswith(".toml"))
    try:
        all_checks = {name: runner.read_checks(checks_path(name)) for name in names}
        game.Game().preflight()
    except CheckError as e:
        print(e)
        return 1
    # What a run stopped by force left in the game.
    with contextlib.suppress(CheckError):
        for target in remove_packs(dlc_folder()):
            print(LEFT_IN_GAME % target)
    if package.main([]) != 0:
        return 1
    if playing:
        try:
            with packs_in_game(names[0]):
                stopped = runner.play_by_hand(all_checks[names[0]], game.Game())
        except CheckError as e:
            stopped = "stopped: %s" % e
        if stopped:
            print("Playing " + stopped)
        return 1 if stopped else 0
    failed = []
    for name in names:
        print("\n== %s" % name, flush=True)
        try:
            with packs_in_game(name):
                why = runner.run(all_checks[name], game.Game())
        except CheckError as e:
            why = str(e)
        print("%s %s" % (name, why or "passed."), flush=True)
        if why:
            failed.append(name)
    print(
        "\n%d of %d checks files passed%s"
        % (len(names) - len(failed), len(names), "" if not failed else ": failed " + ", ".join(failed))
    )
    return 1 if failed else 0


if __name__ == "__main__":
    game.make_output_safe()
    sys.exit(main(sys.argv[1:]))
