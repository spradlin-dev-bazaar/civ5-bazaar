"""Build the in-game toy plugins and lay out mod folders for the host, VMC's database files, each toy and a check of
VMC's events.

With "bench plain" or "bench host", lay out the benchmark mod instead, holding the build made by
build-dll.cmd bench or build-hooked.cmd bench. Both share one mod id, so a save made with either
loads with either. Output goes to tests/ingame/out/MODS. Nothing is installed: copy the folders into
the game's MODS folder by hand.
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
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "generator"))

import common  # noqa: E402

PROJECT = common.engine_project()
HOST_OUT = common.HOST_OUTPUT
OUT = os.path.join(HERE, "out")
VSVARS = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat"
CL = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\bin\cl.exe"

PLAIN_OUT = os.path.join(common.SOURCE_ROOT, "BuildOutput", "VS2008_ModWin32")
VMC_DIR = os.path.join(common.REPO, "mod", "vmc")
FRONTEND_DIR = os.path.join(common.REPO, "frontend")

HOST_ID = common.HOST_MOD_ID
HOST_NAME = common.HOST_MOD_NAME
BENCH_ID = "d9b32c9d-2f72-42f0-b53e-50b86d1ed3c7"
BENCH_DLLS = {
    "plain": os.path.join(PLAIN_OUT, "CvGameCoreDLL_Expansion2Win32Mod.dll"),
    "host": os.path.join(HOST_OUT, "CvGameCore_Expansion2.dll"),
}
BNW_DLC = "6DA07636-4123-4018-B643-6575B4EC336B"
# Also replaces Advanced Setup; referencing it makes the game switch the host on after it, so the host's screen wins.
RAS_ID = "34feb829-33fb-4241-956f-462e6877e070"
RAS_NAME = "Really Advanced Setup"
VMC_DATA_NAME = "Bazaar - VMC Bootstrap (required)"
TOYS = [
    ("GOLD", "ToyGold", "Toy Gold Plugin", "c411a905-2f0d-471c-848b-357ccf98ab4b"),
    ("RIVAL", "ToyRival", "Toy Rival Plugin", "bd4f6967-e129-4de5-9ac5-58627909ed43"),
    ("CRASH", "ToyCrash", "Toy Crash Plugin", "6172647d-3bcb-41fa-9cde-870a7723518f"),
    ("NEWER", "ToyNewer", "Toy Newer Plugin", "1e11469a-724f-42b1-9d52-2ca0ca704665"),
    ("HAND", "ToyHand", "Toy Hand Plugin", "d6d32c6a-5f13-49b5-ab37-505f39e88adc"),
    ("HAND_REPLACE", "ToyHandReplace", "Toy Hand Replace Plugin", "2df335dd-943f-40dd-86a9-241903d92043"),
]
VMC_CHECK_ID = "a78808bb-cf9a-4543-9953-bc7b1ea3bed0"
# Runs after VMC's CustomModOptions.xml has added the row only if the game orders it after VMC's files, because like
# mods made for VMC it only references VMC's mod id.
VMC_CHECK_SQL = "UPDATE CustomModOptions SET Value = 1 WHERE Name = 'EVENTS_PLAYER_TURN';\n"
VMC_CHECK_LUA = """print("DLL id " .. Game.GetDllGuid())
print("EVENTS_PLAYER_TURN on: " .. tostring(Game.IsCustomModOption("EVENTS_PLAYER_TURN")))
GameEvents.PlayerDoneTurn.Add(function(iPlayer) print("PlayerDoneTurn for player " .. iPlayer) end)
print("Game.ToyHandPing: " .. (Game.ToyHandPing and Game.ToyHandPing() or "missing"))
"""
VMC_CHECK_XML = '<?xml version="1.0" encoding="utf-8"?>\n<Context>\n</Context>\n'
# The id whoward69's VMC and the Community Patch share; mods made for either reference it.
VMC_MOD_ID = "d1b6328c-ff44-4b0d-aad7-c657f83610cd"
# Bazaar's mod creates the plugin list before any plugin mod is switched on, so the list's shape is Bazaar's. Plugins
# create it too, so that without Bazaar they leave no error in the database log.
DLL_PLUGINS_TABLE = "CREATE TABLE IF NOT EXISTS DllPlugins (File TEXT NOT NULL);\n"


def vs_env():
    out = subprocess.run('"%s" >nul && set' % VSVARS, shell=True, capture_output=True, text=True).stdout
    env = dict(os.environ)
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


def build_problem(dll, want_bench):
    """Why this DLL is the wrong build to package, or None. Benchmark builds start autoplay by themselves."""
    if not os.path.exists(dll):
        return "%s does not exist; build it first." % dll
    with open(dll, "rb") as f:
        bench = b"CivTurnBench.csv" in f.read()
    if bench and not want_bench:
        return "%s is a benchmark build; rebuild it without the bench option." % dll
    if want_bench and not bench:
        return "%s is not a benchmark build; rebuild it with the bench option." % dll
    return None


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest().upper()


PROPERTIES = """  <Properties>
    <Name>{name}</Name>
    <Stability>Experimental</Stability>
    <Teaser>{teaser}</Teaser>
    <Description>{teaser}</Description>
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


def new_mod_folder(name, version=1):
    folder = os.path.join(OUT, "MODS", "%s (v %d)" % (name, version))
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
    dependencies=None,
    version=1,
    authors="spradlin-dev",
    credits=(),
    affects_saves=None,
):
    """Write a mod's description file; files are (path, import flag) pairs inside folder, references and dependencies
    (id, title) or (id, title, version), credits extra (property, text) pairs. A mod affects saved games if it has a
    DLL or changes the database, unless affects_saves says otherwise: a loaded save switches on only the database
    changes of the mods it lists.

    A test mod depends on the host unless it names its own dependencies."""
    if dependencies is None:
        dependencies = [(HOST_ID, HOST_NAME)]
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


def copy_plugins_screen(folder):
    """The Plugins screen's files, which replace Advanced Setup."""
    os.makedirs(os.path.join(folder, "frontend"))
    files = []
    for path in sorted(glob.glob(os.path.join(FRONTEND_DIR, "*.lua")) + glob.glob(os.path.join(FRONTEND_DIR, "*.xml"))):
        files.append(("frontend/" + os.path.basename(path), 1))
        shutil.copyfile(path, os.path.join(folder, files[-1][0]))
    return files


def write_vmc_data_mod():
    """whoward69's VMC files without his DLL, under his mod id, so mods made for VMC are switched on after them. A
    Workshop item may hold only one mod, so it is a mod of its own rather than a subfolder of the host. Returns VMC's
    version."""
    vmc = vmc_mod_parts()
    folder = new_mod_folder(VMC_DATA_NAME, version=vmc.version)
    for path, _ in vmc.files:
        os.makedirs(os.path.dirname(os.path.join(folder, path)), exist_ok=True)
        shutil.copyfile(os.path.join(VMC_DIR, path), os.path.join(folder, path))
    teaser = "whoward69's Various Mod Components database files, for the %s, so mods made for VMC load after them." % (
        HOST_NAME
    )
    write_modinfo(
        folder,
        VMC_DATA_NAME,
        VMC_MOD_ID,
        teaser,
        vmc.files,
        vmc.updates,
        vmc.entries,
        dependencies=[],
        version=vmc.version,
        authors=vmc.authors,
        credits=vmc.credits,
        affects_saves=vmc.affects_saves,
    )
    return vmc.version


def write_dll_mod(name, mod_id, teaser, dll, plugins_screen=False):
    """A build of the game core, with VMC's data mod beside it. The DLL reads tables and columns VMC's files add, so it
    depends on that mod, which makes the game switch it on first."""
    folder = new_mod_folder(name)
    shutil.copyfile(dll, os.path.join(folder, "CvGameCore_Expansion2.dll"))
    with open(os.path.join(folder, "DllPlugins.sql"), "w") as f:
        f.write(DLL_PLUGINS_TABLE)
    vmc_version = write_vmc_data_mod()
    files = [("CvGameCore_Expansion2.dll", 1), ("DllPlugins.sql", 0)]
    references = []
    if plugins_screen:
        files += copy_plugins_screen(folder)
        references.append((RAS_ID, RAS_NAME))
    write_modinfo(
        folder,
        name,
        mod_id,
        teaser,
        files,
        ["DllPlugins.sql"],
        dll="CvGameCore_Expansion2.dll",
        references=references,
        dependencies=[(VMC_MOD_ID, VMC_DATA_NAME, vmc_version)],
    )


def write_toy_mod(dll_name, mod_name, mod_id):
    folder = new_mod_folder(mod_name)
    dll = dll_name + ".dll"
    sql = dll_name + ".sql"
    shutil.copyfile(os.path.join(OUT, "build", dll), os.path.join(folder, dll))
    with open(os.path.join(folder, sql), "w") as f:
        f.write(DLL_PLUGINS_TABLE)
        f.write("INSERT INTO DllPlugins (File) VALUES ('%s');\n" % dll)
    write_modinfo(folder, mod_name, mod_id, "Test plugin for the %s." % HOST_NAME, [(dll, 0), (sql, 0)], [sql])


def write_vmc_check_mod():
    name = "Toy VMC Check"
    folder = new_mod_folder(name)
    files = [("VmcCheck.sql", VMC_CHECK_SQL, 0), ("VmcCheck.lua", VMC_CHECK_LUA, 1), ("VmcCheck.xml", VMC_CHECK_XML, 1)]
    for file_name, content, _ in files:
        with open(os.path.join(folder, file_name), "w") as f:
            f.write(content)
    teaser = "Test mod for the %s: switches on one VMC event and writes it to Lua.log." % HOST_NAME
    write_modinfo(
        folder,
        name,
        VMC_CHECK_ID,
        teaser,
        [(file_name, vfs) for file_name, _, vfs in files],
        ["VmcCheck.sql"],
        [("InGameUIAddin", "VmcCheck.xml", "VMC check", teaser)],
        references=[(VMC_MOD_ID, "DLL - Various Mod Components")],
        dependencies=[],
    )


def write_bench_mod(build):
    teaser = "Benchmark build (%s): the computer plays by itself and logs how long each turn takes." % build
    write_dll_mod("Civ Bench", BENCH_ID, teaser, BENCH_DLLS[build])
    print("mod folder in", os.path.join(OUT, "MODS"))
    return 0


def main(args):
    if args not in ([], ["bench", "plain"], ["bench", "host"]):
        print("usage: package.py [bench plain|bench host]")
        return 1
    bench = bool(args)
    dll = BENCH_DLLS[args[1]] if bench else os.path.join(HOST_OUT, "CvGameCore_Expansion2.dll")
    problem = build_problem(dll, bench)
    if problem:
        print(problem)
        return 1
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    if bench:
        return write_bench_mod(args[1])
    build = os.path.join(OUT, "build")
    os.makedirs(build)
    env = vs_env()
    flags = [
        CL,
        "/nologo",
        "/O2",
        "/Oy",
        "/Ob2",
        "/GS-",
        "/MD",
        "/EHsc",
        "/W3",
        "/fp:strict",
        "/LD",
        "/wd4251",
        "/wd4275",
        "/I" + PROJECT.mirror_dir,
        "/I" + common.HOST_DIR,
        "/I" + os.path.join(PROJECT.build_dir, "sdk"),
    ]
    flags += ["/D" + d for d in common.PLUGIN_DEFINES]
    flags += ["/I" + os.path.join(common.SOURCE_ROOT, inc) for inc in common.SUPPORT_INCLUDE]
    libs = [os.path.join(HOST_OUT, "CvGameCore_Expansion2.lib")]
    libs += [os.path.join(common.SOURCE_ROOT, lib) for lib in common.SUPPORT_LIBS]
    for define, dll_name, _, _ in TOYS:
        cmd = flags + [
            "/DTOY_" + define,
            "/Fo" + os.path.join(build, dll_name + ".obj"),
            "/Fe" + os.path.join(build, dll_name + ".dll"),
            os.path.join(HERE, "toy_ingame.cpp"),
        ]
        cmd += libs + ["/link", "/NODEFAULTLIB:libcmt"]
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, errors="replace")
        if p.returncode != 0:
            print(p.stdout[-4000:], p.stderr[-2000:])
            return 1
        print("built", dll_name + ".dll")
    write_dll_mod(
        HOST_NAME,
        HOST_ID,
        "Test build of the %s." % HOST_NAME,
        os.path.join(HOST_OUT, "CvGameCore_Expansion2.dll"),
        plugins_screen=True,
    )
    for _, dll_name, mod_name, mod_id in TOYS:
        write_toy_mod(dll_name, mod_name, mod_id)
    write_vmc_check_mod()
    print("mod folders in", os.path.join(OUT, "MODS"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
