"""Upload a release's mod to its Steam Workshop item without ModBuddy, for tools/release.py workshop.

Civ 5's Workshop items are Steam's old kind, which SteamCMD cannot update. upload.cpp makes the calls ModBuddy makes,
through ModBuddy's own steam_api.dll, so the Civilization V SDK must be installed and Steam running and signed in to the
account that owns the item.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import winreg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "generator"))

import common  # noqa: E402

# By major version: a new major goes up as a new item, since games saved with the old one still need its mod.
BAZAAR_ITEMS = {0: 3825428828}
GAME_APP = 8930
SDK_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 16830"
STEAM_API = os.path.join("ModBuddy", "Extensions", "Application", "steam_api.dll")
CHANGES = os.path.join(common.REPO, "workshop", "changes.txt")
DESCRIPTION = os.path.join(common.REPO, "workshop", "bazaar.txt")
UPLOADER = os.path.join(HERE, "upload.cpp")
OUT = os.path.join(common.SOURCE_ROOT, "BuildTemp", "workshop")
DETAILS_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
WEB_API_ERRORS = (OSError, ValueError, KeyError, IndexError, TypeError)
WEB_API_TRIES = 12
WEB_API_WAIT_SECONDS = 5
RESULT_OK = 1
# Steam's limit for a description or a change note is 8000 bytes, which may count C's closing zero.
MAX_TEXT_BYTES = 7999
HEADING = re.compile(r"^\[b\](\d+\.\d+\.\d+)\[/b\]$", re.M)


def stop(message):
    raise SystemExit("workshop: " + message)


def say(message):
    print("workshop: " + message, flush=True)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def bazaar_item(release):
    major = int(release.split(".")[0])
    if major not in BAZAAR_ITEMS:
        stop(
            "Bazaar %d.x has no Workshop item yet: publish its mod as a new item with ModBuddy, then add the item's"
            " number to BAZAAR_ITEMS in %s" % (major, common.shown(os.path.join(HERE, "upload.py")))
        )
    return BAZAAR_ITEMS[major]


def change_note(changes, release):
    """The section of the Workshop change log for release, from its [b]release[/b] heading to the next one."""
    headings = list(HEADING.finditer(changes))
    for i, heading in enumerate(headings):
        if heading.group(1) == release:
            end = headings[i + 1].start() if i + 1 < len(headings) else len(changes)
            return changes[heading.start() : end].strip()
    stop(
        "%s has no [b]%s[/b] section: add the release's change note at its top through a pull request first"
        % (common.shown(CHANGES), release)
    )


def require_fits(what, text):
    size = len(text.encode("utf-8"))
    if size > MAX_TEXT_BYTES:
        stop("%s is %d bytes, more than the %d Steam allows: shorten it" % (what, size, MAX_TEXT_BYTES))


def steam_api():
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SDK_KEY, 0, winreg.KEY_READ | view) as key:
                path = os.path.join(winreg.QueryValueEx(key, "InstallLocation")[0], STEAM_API)
        except OSError:
            continue
        if os.path.isfile(path):
            return path
    stop("ModBuddy's steam_api.dll was not found: install the Sid Meier's Civilization V SDK from Steam's library")


def details(item):
    data = urllib.parse.urlencode({"itemcount": 1, "publishedfileids[0]": item}).encode()
    with urllib.request.urlopen(DETAILS_URL, data, timeout=30) as response:
        return json.load(response)["response"]["publishedfiledetails"][0]


def require_game_item(item):
    try:
        found = details(item)
    except WEB_API_ERRORS as e:
        stop("Steam's Web API did not answer about item %d: %s" % (item, e))
    if found.get("result") != RESULT_OK or found.get("consumer_app_id") != GAME_APP:
        stop("item %d is not a public Civilization V item on the Steam Workshop" % item)
    return found


def build_uploader():
    env = common.vs_env()
    cl = shutil.which("cl", path=env.get("PATH"))
    if not cl:
        stop("cl was not found: is Visual C++ 2008 installed?")
    os.makedirs(OUT, exist_ok=True)
    args = [cl, "/nologo", "/EHsc", "/W3", "/O2", "/MT", UPLOADER]
    done = subprocess.run(args, cwd=OUT, env=env, capture_output=True, text=True, errors="replace")
    if done.returncode != 0:
        stop("upload.cpp did not build:\n" + done.stdout.strip())
    return os.path.join(OUT, "upload.exe")


def write_text(name, text):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def wait_for_file(item, package, before):
    """A check Steam's Web API does not answer counts as not yet, since the upload has already gone through."""
    size = os.path.getsize(package)
    for _ in range(WEB_API_TRIES):
        try:
            now = details(item)
            if int(now["file_size"]) == size and now["time_updated"] > before["time_updated"]:
                return True
        except WEB_API_ERRORS:
            pass
        time.sleep(WEB_API_WAIT_SECONDS)
    return False


def upload(release, package):
    item = bazaar_item(release)
    note = change_note(read_text(CHANGES), release)
    description = read_text(DESCRIPTION)
    require_fits("the %s section of %s" % (release, common.shown(CHANGES)), note)
    require_fits(common.shown(DESCRIPTION), description)
    api = steam_api()
    before = require_game_item(item)
    uploader = build_uploader()
    note_file = write_text("change-note.txt", note)
    description_file = write_text("description.txt", description)
    say("uploading %s to item %d" % (os.path.basename(package), item))
    command = [uploader, api, str(item), package, note_file, description_file]
    if subprocess.run(command, cwd=OUT).returncode != 0:
        stop("the uploader stopped, as its message above says")
    if not wait_for_file(item, package, before):
        stop(
            "Steam took the upload, but its Web API does not show the new file on item %d yet: check the item's page"
            % item
        )
    say("item %d now holds %s" % (item, os.path.basename(package)))
