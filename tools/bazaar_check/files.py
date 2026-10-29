"""The player's Civilization V folder in Documents. Nothing here needs the game, so all of it works with the game
closed."""

import collections
import ctypes
import filecmp
import glob
import os
import shutil
import subprocess
import tempfile
from xml.etree import ElementTree

from . import CheckError

ORDER_FILE = os.path.join("ModUserData", "Bazaar plugin order.txt")
SAVES = os.path.join("ModdedSaves", "single")
AUTOSAVES = os.path.join(SAVES, "auto")
CSIDL_PERSONAL = 5
TAR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
# Bazaar's test builds: above any release's mod version, and still inside the 0 to 999 a dependency on any version
# allows.
TEST_VERSION = 999
ORDER_KEYS = {"file", "skip", "use_both_with"}

ModInfo = collections.namedtuple("ModInfo", "id version name dependencies")
Dependency = collections.namedtuple("Dependency", "id title low high")
Copies = collections.namedtuple("Copies", "folder order autosaves")


def user_folder():
    """The game's folder in Documents, wherever Windows keeps Documents."""
    path = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, path) != 0:
        raise CheckError("Windows did not report your Documents folder")
    return os.path.join(path.value, "My Games", "Sid Meier's Civilization 5")


def read_modinfo(folder):
    """The folder's one mod description, or None when it has none or several."""
    modinfos = glob.glob(os.path.join(glob.escape(folder), "*.modinfo"))
    if len(modinfos) != 1:
        return None
    try:
        root = ElementTree.parse(modinfos[0]).getroot()
        dependencies = [
            Dependency(
                m.get("id"), m.get("title") or m.get("id"), int(m.get("minversion", 0)), int(m.get("maxversion", 999))
            )
            for m in root.findall("Dependencies/Mod")
        ]
        return ModInfo(root.get("id"), int(root.get("version")), root.findtext("Properties/Name") or "", dependencies)
    except (ElementTree.ParseError, TypeError, ValueError):
        raise CheckError("%s is not a mod description the game can read" % modinfos[0])


def mod_key(folder):
    info = read_modinfo(folder)
    return (info.id, info.version) if info else None


def mod_folders(mods_folder, key):
    """A broken mod of someone else's must not stop the check."""
    found = []
    for name in sorted(os.listdir(mods_folder)):
        folder = os.path.join(mods_folder, name)
        try:
            if os.path.isdir(folder) and mod_key(folder) == key:
                found.append(folder)
        except CheckError:
            pass
    return found


def different_files(expected, folder):
    """The files under expected that folder lacks or holds with other bytes."""
    different = []
    for dirpath, _, filenames in os.walk(expected):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), expected)
            there = os.path.join(folder, rel)
            if not os.path.isfile(there) or not filecmp.cmp(os.path.join(expected, rel), there, shallow=False):
                different.append(rel)
    return sorted(different)


def unpack(package, folder):
    os.makedirs(folder)
    if subprocess.run([TAR, "-x", "-f", package, "-C", folder], capture_output=True).returncode != 0:
        raise CheckError("%s could not be unpacked" % package)
    return folder


def order_entry_problem(entry):
    """An entry is a DLL's name, or a {file, skip, use_both_with} table; returns what is wrong with it, or None."""
    if isinstance(entry, str):
        return None
    if not isinstance(entry, dict) or type(entry.get("file")) is not str:
        return "it is neither a DLL's name nor a table with a file"
    unknown = set(entry) - ORDER_KEYS
    if unknown:
        return "it does not take %s" % ", ".join(sorted(unknown))
    if type(entry.get("skip", False)) is not bool:
        return "skip is not true or false"
    partners = entry.get("use_both_with", [])
    if type(partners) is not list or not all(isinstance(f, str) for f in partners):
        return "use_both_with is not a list of DLL names"
    return None


def order_line(entry):
    if isinstance(entry, str):
        entry = {"file": entry}
    fields = ["skip" if entry.get("skip") else "load", entry["file"], "", ""] + entry.get("use_both_with", [])
    return "\t".join(fields) + "\r\n"


def copied(copies):
    what = [
        name for name, kept in (("plugin order", copies.order), ("autosaves", copies.autosaves)) if kept is not None
    ]
    return " and ".join(what)


class PlayerFiles:
    def __init__(self, user, say=print):
        self.user = user
        self.say = say

    def path(self, *parts):
        return os.path.join(self.user, *parts)

    def stage(self, source, staging):
        """The folder holding the mod, unpacked into staging if it is a package, and its folder in MODS. A package
        goes into MODS under the name the game would unpack it to."""
        if not os.path.exists(source):
            raise CheckError("%s does not exist" % source)
        packaged = os.path.isfile(source)
        folder = unpack(source, os.path.join(staging, os.path.basename(source))) if packaged else source
        info = read_modinfo(folder)
        if info is None:
            raise CheckError("%s holds no mod description, or more than one" % source)
        target = self.path("MODS", "%s (v %d)" % (info.name, info.version) if packaged else os.path.basename(folder))
        if os.path.exists(target):
            there = read_modinfo(target)
            if there is None or there.id != info.id:
                raise CheckError("%s already holds a different mod: move it out of MODS first" % target)
        return folder, target

    def install(self, sources, staging):
        """Returns the folders holding what the game should load. Every source is read before anything is copied, and
        a folder in MODS is replaced only by the same mod."""
        staged = [self.stage(source, staging) for source in sources]
        for folder, target in staged:
            if os.path.exists(target):
                if os.path.samefile(folder, target):
                    continue
                shutil.rmtree(target)
            shutil.copytree(folder, target)
        return [folder for folder, _ in staged]

    def installed_problems(self, expected_folders):
        """Why the game might not load exactly these mods: another copy of the same mod and version in MODS, such as
        a test build or a Workshop download, or a copy that differs from what was installed."""
        problems = []
        for expected in expected_folders:
            key = mod_key(expected)
            folders = mod_folders(self.path("MODS"), key)
            if not folders:
                problems.append("MODS holds no copy of %s v%d" % key)
                continue
            if len(folders) > 1:
                problems.append(
                    "MODS holds %d copies of %s v%d (%s): move the others out of MODS"
                    % (len(folders), key[0], key[1], ", ".join(folders))
                )
                continue
            changed = different_files(expected, folders[0])
            if changed:
                problems.append(
                    "%s is not the build in %s (%s differ): something changed it after the check put it there, such as"
                    " a Workshop download or a .civ5mod package of the same mod in MODS; move that out of MODS"
                    % (folders[0], os.path.basename(expected), ", ".join(changed[:5]))
                )
        return problems

    def copy_aside(self):
        """Copies, on disk so they survive the script being killed, of what a check changes outside MODS: the plugin
        order, and the autosaves, which the game rotates whenever a new game starts, whatever its settings."""
        folder = tempfile.mkdtemp(prefix="Bazaar check ")
        try:
            order = None
            if os.path.isfile(self.path(ORDER_FILE)):
                shutil.copyfile(self.path(ORDER_FILE), os.path.join(folder, os.path.basename(ORDER_FILE)))
                with open(self.path(ORDER_FILE), "rb") as f:
                    order = f.read()
            autosaves = None
            if os.path.isdir(self.path(AUTOSAVES)):
                autosaves = os.path.join(folder, "auto")
                shutil.copytree(self.path(AUTOSAVES), autosaves)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        copies = Copies(folder, order, autosaves)
        if copied(copies):
            self.say("copies of your %s are kept in %s until the check ends" % (copied(copies), folder))
        return copies

    def put_back(self, copies, autosaves_touched=True, game_running=False):
        """Returns what could not be put back. The copies are deleted unless something was not."""
        problems = []
        order = self.path(ORDER_FILE)
        try:
            if copies.order is not None:
                with open(order, "wb") as f:
                    f.write(copies.order)
            elif os.path.exists(order):
                os.remove(order)
        except OSError as e:
            problems.append("your plugin order could not be put back (%s)" % e)
        if autosaves_touched and game_running:
            left = "your autosaves were not put back" if copies.autosaves else "the autosaves its game made stay"
            problems.append("Civilization V is still running, so %s" % left)
        elif autosaves_touched:
            autosaves = self.path(AUTOSAVES)
            try:
                if os.path.isdir(autosaves):
                    shutil.rmtree(autosaves)
                if copies.autosaves:
                    shutil.copytree(copies.autosaves, autosaves)
            except OSError as e:
                problems.append("your autosaves could not be put back (%s)" % e)
        if problems and copied(copies):
            return problems + ["the copies stay in %s" % copies.folder]
        shutil.rmtree(copies.folder, ignore_errors=True)
        return problems

    def use_plugin_order(self, entries):
        """Bazaar loads every listed plugin, in its own order, when the order file is empty."""
        path = self.path(ORDER_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("".join(order_line(entry) for entry in entries))

    def log(self, name, since):
        """The log's lines if the game wrote it since then. Bazaar empties its log only when it first writes, so an
        older file holds a past run's lines."""
        path = self.path("Logs", name)
        if since is None or not os.path.exists(path) or os.path.getmtime(path) < since:
            return []
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
