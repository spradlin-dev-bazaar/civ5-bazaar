"""Lay out and pack the mods Bazaar ships: Bazaar's own mod, which holds the host and the Plugins screen, and the VMC
Bootstrap, VMC's database files as a mod of their own. tests/ingame/package.py lays out its test mods with these too.

A package holds one mod, with its files at the top and no folder around them; the game makes the folder when it
installs it. ModBuddy's upload refuses a package with more than one mod description in it, even in a subfolder.
"""

import glob
import hashlib
import os
import shutil
import subprocess
import sys
from collections import namedtuple
from xml.etree import ElementTree
from xml.sax.saxutils import escape, quoteattr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "generator"))

import common  # noqa: E402

VMC_DIR = os.path.join(common.REPO, "mod", "vmc")
FRONTEND_DIR = os.path.join(common.REPO, "frontend")
INGAME_DIR = os.path.join(common.REPO, "ingame")
STOPPED_POPUP = (
    "InGameUIAddin",
    "ingame/BazaarStopped.xml",
    "Plugin stopped working",
    "Returns the player to the main menu after a plugin crashes in a game.",
)
LICENSE_FILE = ("LICENSE.txt", common.LICENSE)
NOTICE_FILE = ("NOTICE.txt", common.NOTICE)

HOST_ID = common.HOST_MOD_ID
HOST_NAME = common.HOST_MOD_NAME
HOST_TEASER = (
    "Run more than one DLL mod at a time, as plugins you choose and order on a Plugins screen. Bazaar also includes"
    " whoward69's Various Mod Components (VMC), so mods that need VMC work with it."
)
BNW_DLC = "6DA07636-4123-4018-B643-6575B4EC336B"
VMC_DATA_NAME = "Bazaar - VMC Bootstrap (required)"
# The id whoward69's VMC and the Community Patch share; mods made for either reference it.
VMC_MOD_ID = "d1b6328c-ff44-4b0d-aad7-c657f83610cd"
# Bazaar's mod creates the plugin list before any plugin mod is switched on, so the list's shape is Bazaar's. Plugins
# create it too, so that without Bazaar they leave no error in the database log.
DLL_PLUGINS_TABLE = "CREATE TABLE IF NOT EXISTS DllPlugins (File TEXT NOT NULL);\n"
# Windows' own tar is libarchive, which writes 7z; LZMA is what ModBuddy's packages use.
TAR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest().upper()


PROPERTIES = """  <Properties>
    <Name>{name}</Name>
    <Stability>Experimental</Stability>
    <Teaser>{teaser}</Teaser>
    <Description>{description}</Description>
    <Authors>{authors}</Authors>
{credits}    <HideSetupGame>0</HideSetupGame>
    <AffectsSavedGames>{affects}</AffectsSavedGames>
    <MinCompatibleSaveVersion>0</MinCompatibleSaveVersion>
    <SupportsSinglePlayer>1</SupportsSinglePlayer>
    <SupportsMultiplayer>0</SupportsMultiplayer>
    <SupportsHotSeat>0</SupportsHotSeat>
    <SupportsMac>0</SupportsMac>
    <ReloadAudioSystem>0</ReloadAudioSystem>
    <ReloadLandmarkSystem>0</ReloadLandmarkSystem>
    <ReloadStrategicViewSystem>0</ReloadStrategicViewSystem>
    <ReloadUnitSystem>0</ReloadUnitSystem>
  </Properties>
"""


VmcParts = namedtuple("VmcParts", "files updates entries version authors credits affects_saves")


def vmc_mod_parts():
    """From VMC's modinfo: its files without its DLL, its database updates in its order, its entry points, its version,
    and the properties that credit him and his translators."""
    (modinfo,) = glob.glob(os.path.join(VMC_DIR, "*.modinfo"))
    root = ElementTree.parse(modinfo).getroot()
    files = [(f.text, f.get("import")) for f in root.find("Files") if not f.text.lower().endswith(".dll")]
    updates = [u.text for u in root.find("Actions/OnModActivated")]
    entries = [
        (e.get("type"), e.get("file"), e.findtext("Name"), e.findtext("Description")) for e in root.find("EntryPoints")
    ]
    properties = root.find("Properties")
    credits = [(tag, properties.findtext(tag)) for tag in ("SpecialThanks", "Homepage") if properties.findtext(tag)]
    return VmcParts(
        files,
        updates,
        entries,
        int(root.get("version")),
        properties.findtext("Authors"),
        credits,
        properties.findtext("AffectsSavedGames") == "1",
    )


def host_description(release):
    return HOST_TEASER + " This is Bazaar %s." % release


def new_mod_folder(mods_folder, name, version=1):
    folder = os.path.join(mods_folder, "%s (v %d)" % (name, version))
    os.makedirs(folder)
    return folder


def mod_line(mod_id, title, version=None):
    """A reference or dependency on any version of a mod, or on that version only."""
    low, high = (version, version) if version is not None else (0, 999)
    return '    <Mod id=%s minversion="%d" maxversion="%d" title=%s />\n' % (
        quoteattr(mod_id),
        low,
        high,
        quoteattr(title),
    )


def write_modinfo(
    folder,
    name,
    mod_id,
    teaser,
    files,
    updates,
    entries=(),
    dll=None,
    references=(),
    dependencies=(),
    version=1,
    authors="spradlin-dev",
    credits=(),
    affects_saves=None,
    description=None,
):
    """Write a mod's description file; files are (path, import flag) pairs inside folder, references and dependencies
    (id, title) or (id, title, version), credits extra (property, text) pairs. A mod affects saved games if it has a
    DLL or changes the database, unless affects_saves says otherwise: a loaded save switches on only the database
    changes of the mods it lists. The description the Mods menu shows is the teaser unless one is given."""
    dependencies = ['    <Dlc id=%s minversion="0" maxversion="999" />\n' % quoteattr(BNW_DLC)] + [
        mod_line(*d) for d in dependencies
    ]
    if affects_saves is None:
        affects_saves = bool(dll or updates)
    with open(os.path.join(folder, "%s (v %d).modinfo" % (name, version)), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<Mod id=%s version="%d">\n' % (quoteattr(mod_id), version))
        credit_lines = "".join("    <%s>%s</%s>\n" % (tag, escape(text), tag) for tag, text in credits)
        f.write(
            PROPERTIES.format(
                name=escape(name),
                teaser=escape(teaser),
                description=escape(description or teaser),
                authors=escape(authors),
                credits=credit_lines,
                affects=int(affects_saves),
            )
        )
        f.write("  <Dependencies>\n" + "".join(dependencies) + "  </Dependencies>\n")
        f.write("  <References>\n" + "".join(mod_line(*r) for r in references) + "  </References>\n")
        f.write("  <Blocks />\n  <Files>\n")
        for path, vfs in files:
            digest = md5(os.path.join(folder, path))
            f.write("    <File md5=%s import=%s>%s</File>\n" % (quoteattr(digest), quoteattr(str(vfs)), escape(path)))
        f.write("  </Files>\n  <Actions>\n")
        if dll:
            f.write("    <OnGetDLLPath>\n      <SetDllPath>%s</SetDllPath>\n    </OnGetDLLPath>\n" % escape(dll))
        f.write("    <OnModActivated>\n")
        f.writelines("      <UpdateDatabase>%s</UpdateDatabase>\n" % escape(u) for u in updates)
        f.write("    </OnModActivated>\n  </Actions>\n")
        if entries:
            f.write("  <EntryPoints>\n")
            for kind, path, entry_name, description in entries:
                f.write("    <EntryPoint type=%s file=%s>\n" % (quoteattr(kind), quoteattr(path)))
                f.write("      <Name>%s</Name>\n" % escape(entry_name))
                f.write("      <Description>%s</Description>\n    </EntryPoint>\n" % escape(description))
            f.write("  </EntryPoints>\n")
        f.write("</Mod>\n")


def copy_host_screens(folder):
    """The Plugins screen's files, which replace Advanced Setup, and the pop-up for a plugin that crashes in a game."""
    files = []
    for source, target in ((FRONTEND_DIR, "frontend"), (INGAME_DIR, "ingame")):
        os.makedirs(os.path.join(folder, target))
        for path in sorted(glob.glob(os.path.join(source, "*.lua")) + glob.glob(os.path.join(source, "*.xml"))):
            files.append((target + "/" + os.path.basename(path), 1))
            shutil.copyfile(path, os.path.join(folder, files[-1][0]))
    return files


def copy_license_files(folder):
    for name, source in (LICENSE_FILE, NOTICE_FILE):
        shutil.copyfile(source, os.path.join(folder, name))
    return [(name, 0) for name, _ in (LICENSE_FILE, NOTICE_FILE)]


def write_vmc_data_mod(mods_folder):
    """whoward69's VMC files without his DLL, under his mod id, so mods made for VMC are switched on after them. A
    Workshop item may hold only one mod, so it is a mod of its own rather than a subfolder of the host. Returns its
    folder and VMC's version."""
    vmc = vmc_mod_parts()
    folder = new_mod_folder(mods_folder, VMC_DATA_NAME, version=vmc.version)
    for path, _ in vmc.files:
        os.makedirs(os.path.dirname(os.path.join(folder, path)), exist_ok=True)
        shutil.copyfile(os.path.join(VMC_DIR, path), os.path.join(folder, path))
    license_files = copy_license_files(folder)
    teaser = "whoward69's Various Mod Components database files, for the %s, so mods made for VMC load after them." % (
        HOST_NAME
    )
    write_modinfo(
        folder,
        VMC_DATA_NAME,
        VMC_MOD_ID,
        teaser,
        vmc.files + license_files,
        vmc.updates,
        vmc.entries,
        version=vmc.version,
        authors=vmc.authors,
        credits=vmc.credits,
        affects_saves=vmc.affects_saves,
    )
    return folder, vmc.version


def write_dll_mod(mods_folder, name, mod_id, teaser, dll, host_screens=False, version=1, description=None):
    """A build of the game core, with VMC's data mod beside it. The DLL reads tables and columns VMC's files add, so it
    depends on that mod, which makes the game switch it on first. Returns its folder, then the VMC data mod's folder."""
    folder = new_mod_folder(mods_folder, name, version)
    shutil.copyfile(dll, os.path.join(folder, "CvGameCore_Expansion2.dll"))
    with open(os.path.join(folder, "DllPlugins.sql"), "w") as f:
        f.write(DLL_PLUGINS_TABLE)
    license_files = copy_license_files(folder)
    vmc_folder, vmc_version = write_vmc_data_mod(mods_folder)
    files = [("CvGameCore_Expansion2.dll", 1), ("DllPlugins.sql", 0)] + license_files
    entries = []
    if host_screens:
        files += copy_host_screens(folder)
        entries.append(STOPPED_POPUP)
    write_modinfo(
        folder,
        name,
        mod_id,
        teaser,
        files,
        ["DllPlugins.sql"],
        entries,
        dll="CvGameCore_Expansion2.dll",
        dependencies=[(VMC_MOD_ID, VMC_DATA_NAME, vmc_version)],
        version=version,
        description=description,
    )
    return folder, vmc_folder


def pack(folder, package):
    """Returns None, or why packing failed."""
    if not os.path.isfile(TAR):
        return "Windows' tar.exe was not found at %s." % TAR
    if os.path.exists(package):
        os.remove(package)
    entries = sorted(os.listdir(folder))
    cmd = [TAR, "-c", "--format", "7zip", "--options", "7zip:compression=lzma1", "-f", package, "-C", folder] + entries
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        if os.path.exists(package):
            os.remove(package)
        output = (p.stdout + p.stderr).strip()
        return "tar.exe could not pack %s into %s (exit code %d)%s" % (
            folder,
            package,
            p.returncode,
            ": " + output if output else "",
        )
    return None
