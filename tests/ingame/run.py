"""Bazaar's in-game checks: build the test plugins, then play each checks file in checks/ in Civilization V with nobody
at the keyboard, and print what passed. Needs a build-hooked.cmd build. Each run puts back everything it changed in the
player's folder, MODS included. With --play, build them and start the game with one checks file's mods switched on, to
play by hand; closing the game puts everything back.

    python tests/ingame/run.py [NAME ...]     NAME is a checks file in checks/, such as crash_turn; all by default
    python tests/ingame/run.py --play NAME
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import package  # noqa: E402
from bazaar_check import CheckError, game, runner  # noqa: E402

CHECKS = os.path.join(HERE, "checks")


def checks_path(name):
    return os.path.join(CHECKS, name + ".toml")


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
    if package.main([]) != 0:
        return 1
    if playing:
        stopped = runner.play_by_hand(all_checks[names[0]], game.Game())
        if stopped:
            print("Playing " + stopped)
        return 1 if stopped else 0
    failed = []
    for name in names:
        print("\n== %s" % name, flush=True)
        why = runner.run(all_checks[name], game.Game())
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
