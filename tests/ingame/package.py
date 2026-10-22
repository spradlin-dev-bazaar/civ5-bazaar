"""Build the in-game toy plugins and lay out mod folders for the host and each toy.

Output goes to tests/ingame/out/MODS. Nothing is installed: copy the folders into the game's MODS
folder by hand.
"""

import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SOURCE_ROOT = os.path.join(REPO, "CvGameCoreSource")
CIVGEN = os.path.join(SOURCE_ROOT, "BuildTemp", "civgen")
MIRROR_ENGINE = os.path.join(CIVGEN, "src", "CvGameCoreDLL_Expansion2")
HOST_OUT = os.path.join(CIVGEN, "src", "BuildOutput", "VS2008_ModWin32")
OUT = os.path.join(HERE, "out")
VSVARS = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\Common7\Tools\vsvars32.bat"
CL = r"C:\Program Files (x86)\Microsoft Visual Studio 9.0\VC\bin\cl.exe"

HOST_ID = "b829cadb-b570-46c5-a0ba-419434eb6398"
BNW_DLC = "6DA07636-4123-4018-B643-6575B4EC336B"
TOYS = [
    ("GOLD", "ToyGold", "Toy Gold Plugin", "c411a905-2f0d-471c-848b-357ccf98ab4b"),
    ("RIVAL", "ToyRival", "Toy Rival Plugin", "bd4f6967-e129-4de5-9ac5-58627909ed43"),
    ("CRASH", "ToyCrash", "Toy Crash Plugin", "6172647d-3bcb-41fa-9cde-870a7723518f"),
    ("NEWER", "ToyNewer", "Toy Newer Plugin", "1e11469a-724f-42b1-9d52-2ca0ca704665"),
]
SUPPORT_INCLUDE = [
    r"CvWorldBuilderMap\include",
    r"CvGameCoreDLLUtil\include",
    r"CvLocalization\include",
    r"CvGameDatabase\include",
    r"FirePlace\include",
    r"FirePlace\include\FireWorks",
    r"ThirdPartyLibs\Lua51\include",
]
SUPPORT_LIBS = [
    (r"CvWorldBuilderMap\lib", "CvWorldBuilderMapWin32.lib"),
    (r"CvGameCoreDLLUtil\lib", "CvGameCoreDLLUtilWin32.lib"),
    (r"CvLocalization\lib", "CvLocalizationWin32.lib"),
    (r"CvGameDatabase\lib", "CvGameDatabaseWin32.lib"),
    (r"FirePlace\lib", "FireWorksWin32.lib"),
    (r"FirePlace\lib", "FLuaWin32.lib"),
    (r"ThirdPartyLibs\Lua51\lib", "lua51_Win32.lib"),
]


def vs_env():
    out = subprocess.run('"%s" >nul && set' % VSVARS, shell=True, capture_output=True, text=True).stdout
    env = dict(os.environ)
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return env


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


def write_host_mod():
    folder = os.path.join(OUT, "MODS", "Civ Plugin Host (v 1)")
    os.makedirs(folder)
    shutil.copyfile(
        os.path.join(HOST_OUT, "CvGameCore_Expansion2.dll"), os.path.join(folder, "CvGameCore_Expansion2.dll")
    )
    with open(os.path.join(folder, "Civ Plugin Host (v 1).modinfo"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<Mod id="%s" version="1">\n' % HOST_ID)
        f.write(PROPERTIES.format(name="Civ Plugin Host", teaser="P0 test build of the plugin host.", affects=1))
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
        f.write(PROPERTIES.format(name=mod_name, teaser="Test plugin for the Civ Plugin Host.", affects=0))
        f.write("  <Dependencies>\n")
        f.write('    <Dlc id="%s" minversion="0" maxversion="999" />\n' % BNW_DLC)
        f.write('    <Mod id="%s" minversion="0" maxversion="999" title="Civ Plugin Host" />\n' % HOST_ID)
        f.write("  </Dependencies>\n  <References />\n  <Blocks />\n  <Files>\n")
        f.write('    <File md5="%s" import="0">%s</File>\n' % (md5(os.path.join(folder, dll)), dll))
        f.write('    <File md5="%s" import="0">%s</File>\n' % (md5(os.path.join(folder, sql)), sql))
        f.write("  </Files>\n  <Actions>\n    <OnModActivated>\n      <UpdateDatabase>%s</UpdateDatabase>\n" % sql)
        f.write("    </OnModActivated>\n  </Actions>\n</Mod>\n")


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
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
        "/D_SECURE_SCL=0",
        "/D_HAS_ITERATOR_DEBUGGING=0",
        "/DFXS_IS_DLL",
        "/DWIN32",
        "/DNDEBUG",
        "/D_WINDOWS",
        "/D_USRDLL",
        "/DFINAL_RELEASE",
        "/D_CRT_SECURE_NO_WARNINGS",
        "/wd4251",
        "/wd4275",
        "/I" + MIRROR_ENGINE,
        "/I" + os.path.join(REPO, "host"),
        "/I" + os.path.join(CIVGEN, "sdk"),
    ]
    flags += ["/I" + os.path.join(SOURCE_ROOT, inc) for inc in SUPPORT_INCLUDE]
    libs = [os.path.join(HOST_OUT, "CvGameCore_Expansion2.lib")]
    libs += [os.path.join(SOURCE_ROOT, d, name) for d, name in SUPPORT_LIBS]
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
    write_host_mod()
    for _, dll_name, mod_name, mod_id in TOYS:
        write_toy_mod(dll_name, mod_name, mod_id)
    print("mod folders in", os.path.join(OUT, "MODS"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
