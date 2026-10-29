"""The player's Civilization V folder in Documents: reading mod descriptions, installing mods into MODS, writing
Bazaar's plugin order, and copying aside and putting back what a check changes there. Nothing here needs the game, so
all of it works with the game closed."""

import collections
import contextlib
import ctypes
import filecmp
import glob
import os
import re
import shutil
import subprocess
import tempfile
from xml.etree import ElementTree

from . import CheckError

ORDER_FILE = os.path.join("ModUserData", "Bazaar plugin order.txt")
SAVES = os.path.join("ModdedSaves", "single")
AUTOSAVES = os.path.join(SAVES, "auto")
CONFIG = "config.ini"
# Where the game keeps which mods are switched on, in its Mods table.
MODS_DATABASE = os.path.join("cache", "Civ5ModsDatabase.db")
SEED_KEYS = ("SyncRandSeed", "MapRandSeed")
CSIDL_PERSONAL = 5
TAR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
# The top of the range a mod's dependency on any version of another allows.
ANY_VERSION = 999
# Bazaar's test builds, and any mod at this version or above: above every release, and below ANY_VERSION.
TEST_VERSION = 900
COPIES_PREFIX = "Bazaar check copies "
WHERE_THEY_GO = "where these go.txt"
ORDER_KEYS = {"file", "skip", "use_both_with"}

ModInfo = collections.namedtuple("ModInfo", "id version name dependencies")
Dependency = collections.namedtuple("Dependency", "id title low high")
Copies = collections.namedtuple("Copies", "folder mods_database order config autosaves")
Kept = collections.namedtuple("Kept", "label rel field held_by_game")
KEPT = (
    Kept("Mods menu choices", MODS_DATABASE, "mods_database", True),
    Kept("plugin order", ORDER_FILE, "order", False),
    Kept("config.ini", CONFIG, "config", True),
)


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
                m.get("id"),
                m.get("title") or m.get("id"),
                int(m.get("minversion", 0)),
                int(m.get("maxversion", ANY_VERSION)),
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


def and_list(names):
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else "".join(names)


def copied_text(copies):
    names = [kept.label for kept in KEPT if getattr(copies, kept.field) is not None]
    return and_list(names + (["autosaves"] if copies.autosaves is not None else []))


def leftover_copies():
    """Copies folders an earlier check did not put back and delete. A folder without its note was left by a check
    stopped while copying, before it changed anything."""
    pattern = os.path.join(glob.escape(tempfile.gettempdir()), glob.escape(COPIES_PREFIX) + "*")
    return [folder for folder in sorted(glob.glob(pattern)) if os.path.isfile(os.path.join(folder, WHERE_THEY_GO))]


def refuse_leftover_copies():
    """Copying the files an earlier check's copies replaced would keep that check's changes for good."""
    leftover = leftover_copies()
    if leftover:
        raise CheckError(
            "copies an earlier check made are still in %s: if that check did not put your files back, put them back as"
            ' "%s" there says; then delete the folder' % (leftover[0], WHERE_THEY_GO)
        )


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
            info = read_modinfo(expected)
            folders = mod_folders(self.path("MODS"), (info.id, info.version))
            if not folders:
                problems.append("MODS holds no copy of %s (v %d)" % (info.name, info.version))
                continue
            if len(folders) > 1:
                problems.append(
                    "MODS holds %d copies of %s (v %d): %s; move the others out of MODS"
                    % (len(folders), info.name, info.version, ", ".join(folders))
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

    def copy_file(self, rel, folder):
        """The file's bytes, after copying it into folder; None when there is no such file."""
        if not os.path.isfile(self.path(rel)):
            return None
        shutil.copyfile(self.path(rel), os.path.join(folder, os.path.basename(rel)))
        with open(self.path(rel), "rb") as f:
            return f.read()

    def put_file(self, rel, content):
        """The file as it was: None removes it. Written beside it first, so a failed write leaves the file whole."""
        path = self.path(rel)
        if content is None:
            if os.path.exists(path):
                os.remove(path)
            return
        try:
            with open(path + ".bazaar-check", "wb") as f:
                f.write(content)
            os.replace(path + ".bazaar-check", path)
        except OSError:
            with contextlib.suppress(OSError):
                os.remove(path + ".bazaar-check")
            raise

    def put_back_file(self, what, rel, content):
        """Why the file could not be put back, or None."""
        try:
            if rel == MODS_DATABASE:
                # A journal left by a game that died mid-write would be replayed into the restored database.
                for journal in (rel + "-journal", rel + "-wal", rel + "-shm"):
                    self.put_file(journal, None)
            self.put_file(rel, content)
        except OSError as e:
            return "your %s could not be put back (%s)" % (what, e)
        return None

    def put_back_autosaves(self, copy):
        autosaves = self.path(AUTOSAVES)
        try:
            if os.path.isdir(autosaves):
                shutil.rmtree(autosaves)
            if copy:
                shutil.copytree(copy, autosaves)
        except OSError as e:
            return "your autosaves could not be put back (%s)" % e
        return None

    def where_they_go(self, copies):
        lines = [
            "These are copies a Bazaar check made before it changed your files. If it could not put them back, close",
            "Civilization V, then:",
        ]
        none = "if it is there, since you had none before the check"
        for kept in KEPT:
            path = self.path(kept.rel)
            if getattr(copies, kept.field) is None:
                lines.append("- your %s: delete %s %s" % (kept.label, path, none))
            else:
                lines.append("- your %s: copy %s into %s" % (kept.label, os.path.basename(path), os.path.dirname(path)))
        if copies.autosaves is None:
            lines.append("- your autosaves: delete the folder %s %s" % (self.path(AUTOSAVES), none))
        else:
            lines.append("- your autosaves: put the auto folder in place of %s" % self.path(AUTOSAVES))
        lines.append("Then delete this folder.")
        return "\r\n".join(lines) + "\r\n"

    def copy_aside(self):
        """Copies, on disk so they survive the script being killed, of what a check changes outside MODS: the Mods
        menu's choices, the plugin order, config.ini, and the autosaves, which the game rotates whenever a new game
        starts, whatever its settings."""
        refuse_leftover_copies()
        folder = tempfile.mkdtemp(prefix=COPIES_PREFIX)
        try:
            autosaves = None
            if os.path.isdir(self.path(AUTOSAVES)):
                autosaves = os.path.join(folder, "auto")
                shutil.copytree(self.path(AUTOSAVES), autosaves)
            copies = Copies(
                folder=folder, autosaves=autosaves, **{kept.field: self.copy_file(kept.rel, folder) for kept in KEPT}
            )
            with open(os.path.join(folder, WHERE_THEY_GO), "w", encoding="utf-8", newline="") as f:
                f.write(self.where_they_go(copies))
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        if copied_text(copies):
            self.say("copies of your %s are kept in %s until the check ends" % (copied_text(copies), folder))
        return copies

    def put_back(self, copies, autosaves_touched=True, game_running=False):
        """Returns what could not be put back; the copies are deleted unless something was not. The game holds its
        mods database, config.ini and autosaves while it runs, so those go back only once it has closed."""
        problems, left = [], []
        for kept in KEPT:
            content = getattr(copies, kept.field)
            if game_running and kept.held_by_game:
                left += [kept.label] if content is not None else []
            else:
                problems.append(self.put_back_file(kept.label, kept.rel, content))
        if game_running:
            left += ["autosaves"] if autosaves_touched and copies.autosaves else []
            if left:
                problems.append("Civilization V is still running, so your %s were not put back" % and_list(left))
            if autosaves_touched and not copies.autosaves:
                problems.append("Civilization V is still running, so the autosaves its game made stay")
        elif autosaves_touched:
            problems.append(self.put_back_autosaves(copies.autosaves))
        problems = [problem for problem in problems if problem]
        if problems and copied_text(copies):
            return problems + [
                'the copies stay in %s, and "%s" there says where each goes' % (copies.folder, WHERE_THEY_GO)
            ]
        shutil.rmtree(copies.folder, ignore_errors=True)
        if os.path.exists(copies.folder):
            back = "" if problems else "your files are back, but "
            problems.append("%s%s could not be deleted: delete it yourself" % (back, copies.folder))
        return problems

    def use_seed(self, seed):
        """The game reads both its seeds from config.ini as it starts; 0 has it take them from the clock."""
        path = self.path(CONFIG)
        with open(path, "rb") as f:
            text = f.read().decode("latin-1")
        for key in SEED_KEYS:
            text, found = re.subn(r"(?im)^[ \t]*%s[ \t]*=[^\r\n]*" % key, "%s = %d" % (key, seed), text)
            if not found:
                raise CheckError(
                    "%s has no %s line: start Civilization V once, so it writes the file in full" % (path, key)
                )
        with open(path, "wb") as f:
            f.write(text.encode("latin-1"))

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
