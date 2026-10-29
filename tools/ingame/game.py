"""Drive Civilization V for the in-game checks through its tuner port (tuner.py): start it through Steam, choose the
mods, start a game, end turns, save, load and quit, with nobody at the keyboard. The player's own mod choices, plugin
order and autosaves are put back afterwards.

The game must be set up for it once: EnableTuner = 1 and LoggingEnabled = 1 in its config.ini, and DirectX 11 chosen
the last time it was started from Steam, since starting it through steam://rungameid starts the version chosen last.
"""

import collections
import contextlib
import csv
import ctypes
import glob
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
from xml.etree import ElementTree

import tuner

GAME_URL = "steam://rungameid/8930"
DX11_EXE = "civilizationv_dx11.exe"
ORDER_FILE = os.path.join("ModUserData", "Bazaar plugin order.txt")
SAVES = os.path.join("ModdedSaves", "single")
AUTOSAVES = os.path.join(SAVES, "auto")
FRONT_END = "MainMenu"
MODS_BROWSER = "ModsBrowser"
IN_GAME = "InGame"
LOAD_SCREEN = "LoadScreen"
LEGAL_SCREEN = "LegalScreen"
CSIDL_PERSONAL = 5
NOT_BLOCKED = -1
REFUSED = "refused: "

UserFiles = collections.namedtuple("UserFiles", "folder order autosaves")


class GameError(Exception):
    pass


ERRORS = (GameError, tuner.TunerError, tuner.LuaError)


def user_folder():
    """The game's folder in Documents, wherever Windows keeps Documents."""
    path = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, path) != 0:
        raise GameError("Windows did not report your Documents folder")
    return os.path.join(path.value, "My Games", "Sid Meier's Civilization 5")


def config_problems(text):
    return [
        "%s = 1" % name
        for name in ("EnableTuner", "LoggingEnabled")
        if not re.search(r"^\s*%s\s*=\s*1\s*$" % name, text, re.M)
    ]


def parse_tasklist(out):
    return [
        row[0].lower() for row in csv.reader(io.StringIO(out)) if row and row[0].lower().startswith("civilizationv")
    ]


def game_processes():
    command = ["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq CivilizationV*"]
    return parse_tasklist(subprocess.run(command, capture_output=True, text=True).stdout)


def mod_key(folder):
    modinfos = glob.glob(os.path.join(glob.escape(folder), "*.modinfo"))
    if len(modinfos) != 1:
        return None
    try:
        root = ElementTree.parse(modinfos[0]).getroot()
        return root.get("id"), int(root.get("version"))
    except (ElementTree.ParseError, TypeError, ValueError):
        raise GameError("%s is not a mod description the game can read" % modinfos[0])


def mod_folders(mods_folder, key):
    """A broken mod of someone else's must not stop the check."""
    found = []
    for name in sorted(os.listdir(mods_folder)):
        folder = os.path.join(mods_folder, name)
        with contextlib.suppress(GameError):
            if os.path.isdir(folder) and mod_key(folder) == key:
                found.append(folder)
    return found


def mod_problems(wanted, enabled):
    on = {(m, v): name for m, v, name in enabled}
    problems = []
    missing = ["%s v%d" % key for key in wanted if key not in on]
    if missing:
        problems.append("not switched on: " + ", ".join(missing))
    extra = ["%s (v %d)" % (name, key[1]) for key, name in on.items() if key not in wanted]
    if extra:
        problems.append("still on: " + ", ".join(extra))
    return problems


def mod_table(mods):
    return "{%s}" % ", ".join("{%s, %d}" % (tuner.lua_text(i), v) for i, v in mods)


LIST_MODS = r"""
for _, v in pairs(Modding.GetModBrowserInstalledListings()) do
    local name = tostring(v.Title or v.Name):gsub("[\t\r\n]", " ")
    print(v.ModId .. "\t" .. v.Version .. "\t" .. tostring(v.Enabled) .. "\t" .. name)
end
"""

SET_MODS = r"""
local wanted, keep = %(mods)s, {}
for _, m in ipairs(wanted) do keep[m[1] .. "/" .. m[2]] = true end
for _, v in pairs(Modding.GetModBrowserInstalledListings()) do
    if v.Enabled and not keep[v.ModId .. "/" .. v.Version] then Modding.DisableMod(v.ModId, v.Version) end
end
for _, m in ipairs(wanted) do Modding.EnableMod(m[1], m[2]) end
"""

MOD_DESCRIPTION = r"""
local details = Modding.GetInstalledModDetails(%(id)s, %(version)d)
if details and details.Description then print(details.Description) end
"""

# What the game's own setup screen does from the Mods menu, which leaves the player's Play Now settings alone.
START_GAME = r"""
PreGame.SetPrivateGame(false)
PreGame.SetGameType(GameTypes.GAME_SINGLE_PLAYER)
PreGame.ResetSlots()
PreGame.ResetGameOptions()
PreGame.ResetMapOptions()
PreGame.LoadPreGameSettings()
PreGame.SetPersistSettings(false)
PreGame.SetLoadWBScenario(false)
for row in GameInfo.MapScripts() do
    if row.FileName and string.find(row.FileName, "\\Continents.lua", 1, true) then
        PreGame.SetRandomMapScript(false)
        PreGame.SetMapScript(row.FileName)
        break
    end
end
local world = GameInfo.Worlds.WORLDSIZE_DUEL
PreGame.SetRandomWorldSize(false)
PreGame.SetWorldSize(world.ID)
PreGame.SetNumMinorCivs(world.DefaultMinorCivs)
Events.SerialEventStartGame()
UIManager:SetUICursor(1)
"""

LOAD_GAME = r"""
local ending = %(ending)s
local files = {}
UI.SaveFileList(files, GameTypes.GAME_SINGLE_PLAYER, false, true)
for _, path in ipairs(files) do
    if string.sub(path, -#ending) == ending then
        UIManager:SetUICursor(1)
        Events.PlayerChoseToLoadGame(path)
        return
    end
end
print("%(refused)sthe game does not list the save " .. ending)
"""

# Ending a turn waits for every unit to have orders, so the checks spend their units' moves.
FINISH_MOVES = "for u in Players[Game.GetActivePlayer()]:Units() do u:FinishMoves() end"

BLOCKER = r"""
local t = Players[Game.GetActivePlayer()]:GetEndTurnBlockingType()
local name = tostring(t)
for n, v in pairs(EndTurnBlockingTypes) do if v == t then name = n end end
print(t .. "\t" .. name)
"""

# The game ignores End Turn until it has finished its own work, and a repeat is ignored once the turn has ended.
END_TURN = r"""
local turn = Game.GetGameTurn()
if turn == %(turn)d then Game.DoControl(GameInfoTypes.CONTROL_ENDTURN) end
print(tostring(turn > %(turn)d and Players[Game.GetActivePlayer()]:IsTurnActive()))
"""


class Game:
    def __init__(self, say=print, port=tuner.PORT, user=None):
        self.say = say
        self.tuner = tuner.Tuner(port=port)
        self.user = user or user_folder()
        self.started = None

    def path(self, *parts):
        return os.path.join(self.user, *parts)

    def lua(self, state, code, timeout=30):
        return self.tuner.run(state, code, timeout)

    def text(self, state, expression, timeout=30):
        return "\n".join(self.lua(state, "print(tostring(%s))" % expression, timeout))

    def flag(self, state, expression, timeout=30):
        return self.text(state, "(%s) and true or false" % expression, timeout) == "true"

    def state_ids(self, name):
        return self.tuner.state_ids(name)

    def wait(self, what, ready, timeout):
        """While the game loads it answers slowly or not at all, so a failed ready() only means not yet. The last
        failure is named if the wait runs out."""
        deadline = time.time() + timeout
        last = None
        while True:
            try:
                if ready():
                    return
            except (tuner.NoSuchState, tuner.LuaError) as e:
                last = e
            except tuner.TunerError as e:
                last = e
                if not game_processes():
                    raise GameError("Civilization V closed while waiting for %s" % what)
                with contextlib.suppress(tuner.TunerError):
                    self.tuner.connect(min(20, max(deadline - time.time(), 1)))
            if time.time() > deadline:
                because = " (last error: %s)" % last if last else ""
                raise GameError("%s did not happen within %d seconds%s" % (what, timeout, because))
            time.sleep(2)

    def preflight(self):
        """What must hold before a check changes anything."""
        if game_processes():
            raise GameError("Civilization V is already running: close it, then run this again")
        config = self.path("config.ini")
        if not os.path.isfile(config) or not os.path.isdir(self.path("MODS")):
            raise GameError("%s has no config.ini or MODS folder: start Civilization V once first" % self.user)
        with open(config, encoding="utf-8", errors="replace") as f:
            problems = config_problems(f.read())
        if problems:
            raise GameError("%s needs %s; set that with the game closed" % (config, " and ".join(problems)))

    def install(self, paths):
        """Copy mod folders and packages into MODS; the game unpacks a package when it starts. A folder replaces one of
        the same name only when both hold the same mod."""
        mods = self.path("MODS")
        for source in paths:
            target = os.path.join(mods, os.path.basename(source))
            if os.path.isfile(source):
                shutil.copyfile(source, target)
                continue
            key = mod_key(source)
            if key is None:
                raise GameError("%s holds no mod description" % source)
            if os.path.exists(target):
                if (mod_key(target) or (None,))[0] != key[0]:
                    raise GameError("%s already holds a different mod: move it out of MODS first" % target)
                shutil.rmtree(target)
            shutil.copytree(source, target)

    def save_user_files(self):
        """Copies, on disk so they survive the script being killed, of what a check changes outside MODS: the plugin
        order, and the autosaves, which the game rotates whenever a new game starts, whatever its settings."""
        folder = tempfile.mkdtemp(prefix="Bazaar check ")
        order = None
        if os.path.isfile(self.path(ORDER_FILE)):
            shutil.copyfile(self.path(ORDER_FILE), os.path.join(folder, os.path.basename(ORDER_FILE)))
            with open(self.path(ORDER_FILE), "rb") as f:
                order = f.read()
        autosaves = None
        if os.path.isdir(self.path(AUTOSAVES)):
            autosaves = os.path.join(folder, "auto")
            shutil.copytree(self.path(AUTOSAVES), autosaves)
        return UserFiles(folder, order, autosaves)

    def restore_user_files(self, saved, autosaves_touched=True):
        """Puts the copies back and returns what could not be; then the copies go, unless something was not put back.
        Without autosaves_touched, as when no game was started, the autosaves are left as they are."""
        problems = []
        order = self.path(ORDER_FILE)
        try:
            if saved.order is not None:
                with open(order, "wb") as f:
                    f.write(saved.order)
            elif os.path.exists(order):
                os.remove(order)
        except OSError as e:
            problems.append("your plugin order could not be put back (%s)" % e)
        if autosaves_touched and game_processes():
            problems.append("Civilization V is still running, so your autosaves were not put back")
        elif autosaves_touched:
            autosaves = self.path(AUTOSAVES)
            try:
                if os.path.isdir(autosaves):
                    shutil.rmtree(autosaves)
                if saved.autosaves:
                    shutil.copytree(saved.autosaves, autosaves)
            except OSError as e:
                problems.append("your autosaves could not be put back (%s)" % e)
        if problems:
            return problems + ["copies of your plugin order and autosaves are kept in %s" % saved.folder]
        shutil.rmtree(saved.folder, ignore_errors=True)
        return problems

    def use_default_plugin_order(self):
        """Bazaar loads every listed plugin when the order file is empty, whatever the player unticked."""
        path = self.path(ORDER_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()

    def start(self, timeout=300):
        self.preflight()
        self.say("starting Civilization V through Steam")
        self.started = time.time()
        os.startfile(GAME_URL)
        self.wait("Civilization V starting", game_processes, 120)
        running = game_processes()
        if not running:
            raise GameError("Civilization V closed as it started")
        if DX11_EXE not in running:
            raise GameError(
                "Steam started %s, not the DirectX 11 version. Close it, start the game once from Steam choosing"
                " DirectX 11, then run this again" % ", ".join(running)
            )
        try:
            self.tuner.connect(timeout)
            self.wait("the main menu showing", self.menu_ready, timeout)
        except ERRORS:
            with contextlib.suppress(ERRORS):
                self.quit(60)
            raise

    def menu_ready(self):
        """At the main menu, after closing the legal screen that waits for a click at startup, as its button does."""
        if self.state_ids(LEGAL_SCREEN) and not self.flag(LEGAL_SCREEN, "ContextPtr:IsHidden()"):
            self.lua(LEGAL_SCREEN, "UIManager:DequeuePopup(ContextPtr)")
        return self.at_main_menu()

    def at_main_menu(self):
        return bool(self.state_ids(FRONT_END)) and not self.flag(FRONT_END, "ContextPtr:IsHidden()")

    def mods(self, enabled_only=True):
        rows = []
        for line in self.lua(FRONT_END, LIST_MODS):
            fields = line.split("\t", 3)
            if len(fields) != 4 or not fields[1].isdigit():
                raise GameError("the game listed a mod as %r" % line)
            if fields[2] == "true" or not enabled_only:
                rows.append((fields[0], int(fields[1]), fields[3]))
        return rows

    def set_mods(self, wanted):
        self.lua(FRONT_END, SET_MODS % {"mods": mod_table(wanted)})
        problems = mod_problems(wanted, self.mods())
        if problems:
            raise GameError("the Mods menu could not be set; " + "; ".join(problems))

    def mod_description(self, mod_id, version):
        lines = self.lua(FRONT_END, MOD_DESCRIPTION % {"id": tuner.lua_text(mod_id), "version": version})
        return "\n".join(lines) if lines else None

    def activate(self):
        """Switch the chosen mods on as the Mods menu's Next button does, which loads Bazaar and its plugins."""
        self.say("switching the mods on")
        self.lua(MODS_BROWSER, "OnNextButtonClicked()", timeout=180)

    def _through_load_screen(self, state, code, timeout):
        """Run code that starts or loads a game, then press the loading screen's button. Only states newer than those
        listed before code ran count, since the last game's stay listed for a moment."""
        screens = max(self.state_ids(LOAD_SCREEN) or [-1])
        games = max(self.state_ids(IN_GAME) or [-1])
        for line in self.lua(state, code):
            if line.startswith(REFUSED):
                raise GameError(line[len(REFUSED) :])

        def loaded():
            ids = self.state_ids(LOAD_SCREEN)
            return bool(ids) and max(ids) > screens and not self.flag(LOAD_SCREEN, "Controls.ActivateButton:IsHidden()")

        self.wait("the game loading", loaded, timeout)
        self.lua(LOAD_SCREEN, "OnActivateButtonClicked()")
        self.wait("the game starting", lambda: max(self.state_ids(IN_GAME) or [-1]) > games, 60)

    def start_game(self, timeout=300):
        self.say("starting a game")
        self._through_load_screen(FRONT_END, START_GAME, timeout)

    def load(self, name, timeout=300):
        self.say("loading %s" % name)
        state = IN_GAME if self.state_ids(IN_GAME) else FRONT_END
        code = LOAD_GAME % {"ending": tuner.lua_text("\\" + name + ".Civ5Save"), "refused": REFUSED}
        self._through_load_screen(state, code, timeout)

    def turn(self):
        return int(self.text(IN_GAME, "Game.GetGameTurn()"))

    def blocker(self):
        lines = self.lua(IN_GAME, BLOCKER)
        fields = lines[0].split("\t") if lines else []
        if len(fields) != 2:
            raise GameError("the game reported what it waits for as %r" % lines)
        return int(fields[0]), fields[1]

    def end_turn(self, timeout=180):
        """End the human player's turn; returns the new turn's number."""
        turn = self.turn()
        self.lua(IN_GAME, FINISH_MOVES)
        try:
            self.wait("turn %d ready to end" % turn, lambda: self.blocker()[0] == NOT_BLOCKED, 20)
            self.wait(
                "turn %d starting" % (turn + 1),
                lambda: self.lua(IN_GAME, END_TURN % {"turn": turn}) == ["true"],
                timeout,
            )
        except GameError as e:
            waiting = "the check could not read what the game is waiting for"
            with contextlib.suppress(ERRORS):
                number, name = self.blocker()
                waiting = "the game is waiting for %s" % name
                if number == NOT_BLOCKED:
                    waiting = "nothing blocks the turn, so the other players may still be moving"
            raise GameError("%s; %s" % (e, waiting))
        self.say("turn %d" % (turn + 1))
        return turn + 1

    def save(self, name, timeout=60):
        path = self.path(SAVES, name + ".Civ5Save")
        before = os.path.getmtime(path) if os.path.exists(path) else 0
        self.lua(IN_GAME, "UI.SaveGame(%s)" % tuner.lua_text(name))

        def written():
            if not os.path.exists(path) or os.path.getmtime(path) <= before:
                return False
            size = os.path.getsize(path)
            time.sleep(1)
            return os.path.getsize(path) == size

        self.wait("the save %s" % name, written, timeout)
        return path

    def to_main_menu(self, timeout=180):
        """Leave the game for the menus. Which menu shows depends on how the game was started, so only the menus'
        Lua answering again counts."""
        if not self.state_ids(IN_GAME):
            return
        self.lua(IN_GAME, "Events.ExitToMainMenu()")
        self.wait("the menus answering", lambda: not self.state_ids(IN_GAME) and self.state_ids(FRONT_END), timeout)

    def quit(self, timeout=120):
        with contextlib.suppress(tuner.TunerError, tuner.LuaError):
            state = IN_GAME if self.state_ids(IN_GAME) else FRONT_END
            self.lua(state, "UI.ExitGame()", timeout=10)
        self.tuner.close()
        self.wait("Civilization V closing", lambda: not game_processes(), timeout)

    def clean_up(self, mods, saved):
        """Put the player's game back as it was; returns what could not be. Interrupted, as by a second Ctrl+C, it
        still puts the files back, or says where their copies are, before stopping."""
        problems = []
        try:
            try:
                self.to_main_menu()
                if mods is not None:
                    self.set_mods([(m, v) for m, v, _ in mods])
            except ERRORS as e:
                if mods is not None:
                    names = ", ".join("%s (v %d)" % (name, v) for _, v, name in mods)
                    problems.append(
                        "your Mods menu could not be put back (%s); switch these on there again: %s" % (e, names)
                    )
            try:
                self.quit()
            except ERRORS as e:
                problems.append("%s; close Civilization V by hand" % e)
        except BaseException:
            for problem in self.restore_user_files(saved):
                self.say(problem)
            raise
        problems += self.restore_user_files(saved)
        if not problems:
            self.say("your Mods menu choices, plugin order and autosaves are as they were")
        return problems

    def log(self, name="Bazaar.log"):
        """The log's lines if the game wrote it during this run. Bazaar empties its log only when it first writes, so
        an older file holds a past run's lines."""
        path = self.path("Logs", name)
        if self.started is None or not os.path.exists(path) or os.path.getmtime(path) < self.started:
            return []
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()


@contextlib.contextmanager
def session(game):
    """Start the game, and close it afterwards with the player's mods, plugin order and autosaves as they were. A
    problem putting things back is reported without hiding the error that ended the run."""
    saved = game.save_user_files()
    try:
        game.start()
    except BaseException:
        for problem in game.restore_user_files(saved, autosaves_touched=False):
            game.say(problem)
        raise
    mods = None
    try:
        mods = game.mods()
        yield game
    except BaseException:
        for problem in game.clean_up(mods, saved):
            game.say(problem)
        raise
    problems = game.clean_up(mods, saved)
    if problems:
        raise GameError("; ".join(problems))
