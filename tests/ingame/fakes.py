"""What the in-game check tests share: a clock that never waits, mod folders, and the player's autosaves."""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import mods  # noqa: E402
from bazaar_check import files  # noqa: E402

TASKLIST_NONE = "INFO: No tasks are running which match the specified criteria.\n"
TASKLIST_DX11 = '"CivilizationV_DX11.exe","46564","Console","1","945,180 K"\n'

PLAYER_AUTOSAVES = {
    "AutoSave_0003 BC-3880.Civ5Save": b"the player's turn 3",
    os.path.join("prev", "0ldAutoSave_0002 BC-3940.Civ5Save"): b"the player's turn 2",
}


class FakeClock:
    """Stands in for the time module: sleeping moves the clock on, so waits run out without real waiting."""

    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def write_mod(folder, mod_id, version=1, name="A Mod", content=(), dependencies=()):
    """content is (file name, text) pairs; dependencies are (id, title), on any version, or (id, title, version)."""
    os.makedirs(folder)
    for file_name, text in content:
        with open(os.path.join(folder, file_name), "w") as f:
            f.write(text)
    mods.write_modinfo(folder, name, mod_id, "A test mod.", [], [], dependencies=dependencies, version=version)
    return folder


def write_files(folder, found):
    for rel, content in found.items():
        os.makedirs(os.path.dirname(os.path.join(folder, rel)), exist_ok=True)
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(content)


def read_files(folder):
    found = {}
    for dirpath, _, filenames in os.walk(folder):
        for name in filenames:
            with open(os.path.join(dirpath, name), "rb") as f:
                found[os.path.relpath(os.path.join(dirpath, name), folder)] = f.read()
    return found


def rotate_autosaves(user):
    """What the game does to the autosaves when a new game starts."""
    auto = os.path.join(user, files.AUTOSAVES)
    shutil.rmtree(os.path.join(auto, "prev"), ignore_errors=True)
    os.makedirs(os.path.join(auto, "prev"))
    for name in os.listdir(auto):
        if name != "prev":
            os.rename(os.path.join(auto, name), os.path.join(auto, "prev", "0ld" + name))
    write_files(auto, {"AutoSave_Initial_0000 BC-4000.Civ5Save": b"the check's game"})
