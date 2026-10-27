"""Build the in-game toy plugins and lay out mod folders for the host, VMC's database files, each toy and a check of
VMC's events.

With "bench plain" or "bench host", lay out the benchmark mod instead, holding the build made by
build-dll.cmd bench or build-hooked.cmd bench. Both share one mod id, so a save made with either
loads with either. Output goes to tests/ingame/out/MODS. Nothing is installed: copy the folders into
the game's MODS folder by hand.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "generator"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

import common  # noqa: E402
import mods  # noqa: E402
import version as bazaar_version  # noqa: E402

PROJECT = common.engine_project()
HOST_OUT = common.HOST_OUTPUT
OUT = os.path.join(HERE, "out")
MODS = os.path.join(OUT, "MODS")
CL = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\bin\cl.exe"

PLAIN_OUT = os.path.join(common.SOURCE_ROOT, "BuildOutput", "VS2008_ModWin32")

BENCH_ID = "d9b32c9d-2f72-42f0-b53e-50b86d1ed3c7"
BENCH_DLLS = {
    "plain": os.path.join(PLAIN_OUT, "CvGameCoreDLL_Expansion2Win32Mod.dll"),
    "host": common.HOST_DLL,
}
TOYS = [
    ("GOLD", "ToyGold", "Toy Gold Plugin", "c411a905-2f0d-471c-848b-357ccf98ab4b"),
    ("RIVAL", "ToyRival", "Toy Rival Plugin", "bd4f6967-e129-4de5-9ac5-58627909ed43"),
    ("CRASH", "ToyCrash", "Toy Crash Plugin", "6172647d-3bcb-41fa-9cde-870a7723518f"),
    ("NEWER", "ToyNewer", "Toy Newer Plugin", "1e11469a-724f-42b1-9d52-2ca0ca704665"),
    ("HAND", "ToyHand", "Toy Hand Plugin", "d6d32c6a-5f13-49b5-ab37-505f39e88adc"),
    ("HAND_REPLACE", "ToyHandReplace", "Toy Hand Replace Plugin", "2df335dd-943f-40dd-86a9-241903d92043"),
    ("SAVES", "ToySaves", "Toy Saves Plugin", "b012c631-4178-4d68-99af-7c2fcf5d3701"),
]
VMC_CHECK_ID = "a78808bb-cf9a-4543-9953-bc7b1ea3bed0"
# Runs after VMC's CustomModOptions.xml has added the row only if the game orders it after VMC's files, because like
# mods made for VMC it only references VMC's mod id.
VMC_CHECK_SQL = "UPDATE CustomModOptions SET Value = 1 WHERE Name = 'EVENTS_PLAYER_TURN';\n"
VMC_CHECK_LUA = """print("DLL id " .. Game.GetDllGuid())
print("EVENTS_PLAYER_TURN on: " .. tostring(Game.IsCustomModOption("EVENTS_PLAYER_TURN")))
GameEvents.PlayerDoneTurn.Add(function(iPlayer) print("PlayerDoneTurn for player " .. iPlayer) end)
print("Game.ToyHandPing: " .. (Game.ToyHandPing and Game.ToyHandPing() or "missing"))
print("Game.ToyHandRaise: " .. (Game.ToyHandRaise and tostring(select(2, pcall(Game.ToyHandRaise))) or "missing"))
"""
VMC_CHECK_XML = '<?xml version="1.0" encoding="utf-8"?>\n<Context>\n</Context>\n'


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


def write_toy_mod(dll_name, mod_name, mod_id):
    folder = mods.new_mod_folder(MODS, mod_name)
    dll = dll_name + ".dll"
    sql = dll_name + ".sql"
    shutil.copyfile(os.path.join(OUT, "build", dll), os.path.join(folder, dll))
    with open(os.path.join(folder, sql), "w") as f:
        f.write(mods.DLL_PLUGINS_TABLE)
        f.write("INSERT INTO DllPlugins (File) VALUES ('%s');\n" % dll)
    mods.write_modinfo(
        folder,
        mod_name,
        mod_id,
        "Test plugin for the %s." % mods.HOST_NAME,
        [(dll, 0), (sql, 0)],
        [sql],
        dependencies=[(mods.HOST_ID, mods.HOST_NAME)],
    )


def write_vmc_check_mod():
    name = "Toy VMC Check"
    folder = mods.new_mod_folder(MODS, name)
    files = [("VmcCheck.sql", VMC_CHECK_SQL, 0), ("VmcCheck.lua", VMC_CHECK_LUA, 1), ("VmcCheck.xml", VMC_CHECK_XML, 1)]
    for file_name, content, _ in files:
        with open(os.path.join(folder, file_name), "w") as f:
            f.write(content)
    teaser = "Test mod for the %s: switches on one VMC event and writes it to Lua.log." % mods.HOST_NAME
    mods.write_modinfo(
        folder,
        name,
        VMC_CHECK_ID,
        teaser,
        [(file_name, vfs) for file_name, _, vfs in files],
        ["VmcCheck.sql"],
        [("InGameUIAddin", "VmcCheck.xml", "VMC check", teaser)],
        references=[(mods.VMC_MOD_ID, "DLL - Various Mod Components")],
    )


def write_bench_mod(build):
    teaser = "Benchmark build (%s): the computer plays by itself and logs how long each turn takes." % build
    mods.write_dll_mod(MODS, "Civ Bench", BENCH_ID, teaser, BENCH_DLLS[build])
    print("mod folder in", MODS)
    return 0


def main(args):
    if args not in ([], ["bench", "plain"], ["bench", "host"]):
        print("usage: package.py [bench plain|bench host]")
        return 1
    bench = bool(args)
    dll = BENCH_DLLS[args[1]] if bench else common.HOST_DLL
    problem = build_problem(dll, bench)
    if problem:
        print(problem)
        return 1
    host_version = bazaar_version.read().mod
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    if bench:
        return write_bench_mod(args[1])
    build = os.path.join(OUT, "build")
    os.makedirs(build)
    env = common.vs_env()
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
    mods.write_dll_mod(
        MODS,
        mods.HOST_NAME,
        mods.HOST_ID,
        "Test build of the %s." % mods.HOST_NAME,
        common.HOST_DLL,
        host_screens=True,
        version=host_version,
    )
    for _, dll_name, mod_name, mod_id in TOYS:
        write_toy_mod(dll_name, mod_name, mod_id)
    write_vmc_check_mod()
    print("mod folders in", MODS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
