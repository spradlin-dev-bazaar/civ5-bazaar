"""Bazaar's in-game checks: build the test plugins, then play each checks file in checks/ in Civilization V with nobody
at the keyboard, and print what passed. Needs a build-hooked.cmd build. The test plugins and the VMC check mod it puts
into MODS are removed when it ends; the test build of Bazaar and the VMC Bootstrap stay.

    python tests/ingame/run.py [NAME ...]     NAME is a checks file in checks/, such as crash_turn; all by default
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import package  # noqa: E402
from bazaar_check import CheckError, files, game, runner  # noqa: E402

CHECKS = os.path.join(HERE, "checks")


def checks_path(name):
    return os.path.join(CHECKS, name + ".toml")


def remove_test_mods(player):
    if game.game_processes():
        print("Civilization V is still running, so the test mods stay in MODS")
        return
    removed = []
    try:
        names = sorted(os.listdir(player.path("MODS")))
    except OSError as e:
        print("the test mods could not be removed: %s" % e)
        return
    for name in names:
        folder = player.path("MODS", name)
        try:
            info = files.read_modinfo(folder) if os.path.isdir(folder) else None
        except (CheckError, OSError):
            continue
        if info and info.id in package.TEST_MOD_IDS:
            try:
                shutil.rmtree(folder)
                removed.append(name)
            except OSError as e:
                print("%s could not be removed: %s" % (folder, e))
    if removed:
        print("removed the test mods from MODS: " + ", ".join(removed))


def main(argv):
    names = argv or sorted(name[: -len(".toml")] for name in os.listdir(CHECKS) if name.endswith(".toml"))
    try:
        all_checks = {name: runner.read_checks(checks_path(name)) for name in names}
        player = files.PlayerFiles(files.user_folder())
        game.Game().preflight()
    except CheckError as e:
        print(e)
        return 1
    if package.main([]) != 0:
        return 1
    failed = []
    try:
        for name in names:
            print("\n== %s" % name, flush=True)
            why = runner.run(all_checks[name], game.Game())
            print("%s %s" % (name, why or "passed."), flush=True)
            if why:
                failed.append(name)
    finally:
        remove_test_mods(player)
    print(
        "\n%d of %d checks files passed%s"
        % (len(names) - len(failed), len(names), "" if not failed else ": failed " + ", ".join(failed))
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
