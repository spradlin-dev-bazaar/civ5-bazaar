"""Build the in-game toy plugins and lay out mod folders for the host and each toy.

With "bench plain" or "bench host", lay out the benchmark mod instead, holding the build made by
build-dll.cmd bench or build-hooked.cmd bench. Both share one mod id, so a save made with either
loads with either. Output goes to tests/ingame/out/MODS. Nothing is installed: copy the folders into
the game's MODS folder by hand.
"""

import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "generator"))

import common  # noqa: E402

PROJECT = common.engine_project()
HOST_OUT = os.path.join(PROJECT.mirror_root, "BuildOutput", "VS2008_ModWin32")
OUT = os.path.join(HERE, "out")
VSVARS = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat"
CL = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\bin\cl.exe"

PLAIN_OUT = os.path.join(common.SOURCE_ROOT, "BuildOutput", "VS2008_ModWin32")

HOST_ID = "b829cadb-b570-46c5-a0ba-419434eb6398"
HOST_NAME = "Bazaar Multi-DLL Mod Loader"
BENCH_ID = "d9b32c9d-2f72-42f0-b53e-50b86d1ed3c7"
BENCH_DLLS = {
    "plain": os.path.join(PLAIN_OUT, "CvGameCoreDLL_Expansion2Win32Mod.dll"),
    "host": os.path.join(HOST_OUT, "CvGameCore_Expansion2.dll"),
}
BNW_DLC = "6DA07636-4123-4018-B643-6575B4EC336B"
TOYS = [
    ("GOLD", "ToyGold", "Toy Gold Plugin", "c411a905-2f0d-471c-848b-357ccf98ab4b"),
    ("RIVAL", "ToyRival", "Toy Rival Plugin", "bd4f6967-e129-4de5-9ac5-58627909ed43"),
    ("CRASH", "ToyCrash", "Toy Crash Plugin", "6172647d-3bcb-41fa-9cde-870a7723518f"),
    ("NEWER", "ToyNewer", "Toy Newer Plugin", "1e11469a-724f-42b1-9d52-2ca0ca704665"),
]


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
    <Authors>spradlin-dev</Authors>
    <HideSetupGame>0</HideSetupGame>
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


def write_dll_mod(name, mod_id, teaser, dll):
    folder = os.path.join(OUT, "MODS", "%s (v 1)" % name)
    os.makedirs(folder)
    shutil.copyfile(dll, os.path.join(folder, "CvGameCore_Expansion2.dll"))
    with open(os.path.join(folder, "%s (v 1).modinfo" % name), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<Mod id="%s" version="1">\n' % mod_id)
        f.write(PROPERTIES.format(name=name, teaser=teaser, affects=1))
        f.write('  <Dependencies>\n    <Dlc id="%s" minversion="0" maxversion="999" />\n  </Dependencies>\n' % BNW_DLC)
        f.write("  <References />\n  <Blocks />\n  <Files>\n")
        f.write(
            '    <File md5="%s" import="1">CvGameCore_Expansion2.dll</File>\n'
            % md5(os.path.join(folder, "CvGameCore_Expansion2.dll"))
        )
        f.write(
            "  </Files>\n  <Actions>\n    <OnGetDLLPath>\n      <SetDllPath>CvGameCore_Expansion2.dll</SetDllPath>\n"
        )
        f.write("    </OnGetDLLPath>\n  </Actions>\n</Mod>\n")


def write_toy_mod(dll_name, mod_name, mod_id):
    folder = os.path.join(OUT, "MODS", "%s (v 1)" % mod_name)
    os.makedirs(folder)
    dll = dll_name + ".dll"
    sql = dll_name + ".sql"
    shutil.copyfile(os.path.join(OUT, "build", dll), os.path.join(folder, dll))
    with open(os.path.join(folder, sql), "w") as f:
        f.write("CREATE TABLE IF NOT EXISTS DllPlugins (File TEXT NOT NULL, ApiMajor INTEGER, ApiMinor INTEGER);\n")
        f.write("INSERT INTO DllPlugins (File, ApiMajor, ApiMinor) VALUES ('%s', 0, 1);\n" % dll)
    with open(os.path.join(folder, "%s (v 1).modinfo" % mod_name), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<Mod id="%s" version="1">\n' % mod_id)
        f.write(PROPERTIES.format(name=mod_name, teaser="Test plugin for the %s." % HOST_NAME, affects=0))
        f.write("  <Dependencies>\n")
        f.write('    <Dlc id="%s" minversion="0" maxversion="999" />\n' % BNW_DLC)
        f.write('    <Mod id="%s" minversion="0" maxversion="999" title="%s" />\n' % (HOST_ID, HOST_NAME))
        f.write("  </Dependencies>\n  <References />\n  <Blocks />\n  <Files>\n")
        f.write('    <File md5="%s" import="0">%s</File>\n' % (md5(os.path.join(folder, dll)), dll))
        f.write('    <File md5="%s" import="0">%s</File>\n' % (md5(os.path.join(folder, sql)), sql))
        f.write("  </Files>\n  <Actions>\n    <OnModActivated>\n      <UpdateDatabase>%s</UpdateDatabase>\n" % sql)
        f.write("    </OnModActivated>\n  </Actions>\n</Mod>\n")


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
        "/DCIV_HOST_API=__declspec(dllimport)",
        "/DFXS_IS_DLL",
        "/DWIN32",
        "/DNDEBUG",
        "/D_WINDOWS",
        "/D_USRDLL",
        "/DFINAL_RELEASE",
        "/D_CRT_SECURE_NO_WARNINGS",
        "/wd4251",
        "/wd4275",
        "/I" + PROJECT.mirror_dir,
        "/I" + common.HOST_DIR,
        "/I" + os.path.join(PROJECT.build_dir, "sdk"),
    ]
    flags += ["/D" + d for d in common.LAYOUT_DEFINES]
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
    )
    for _, dll_name, mod_name, mod_id in TOYS:
        write_toy_mod(dll_name, mod_name, mod_id)
    print("mod folders in", os.path.join(OUT, "MODS"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
