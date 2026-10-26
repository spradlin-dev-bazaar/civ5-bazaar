"""Stands in for a template's build.cmd in the release script's tests: packs what build.cmd would, from the project's
.civ5proj and .sql files, with a stand-in DLL for each DllPlugins row.

usage: fake_build.py PROJECT_FOLDER

Environment variables make it go wrong on purpose: FAKE_BUILD_FAIL, FAKE_NO_PACKAGE, FAKE_API ("major.minor", or
"none" for no API version), FAKE_64BIT, FAKE_SKIP_DLL (a DLL name to leave out), FAKE_AFFECTS_SAVES ("0"),
FAKE_NO_ROW, FAKE_MODINFO_VERSION, FAKE_TWO_MODINFO and FAKE_PACKAGE_NAME.
"""

import glob
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

TAR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")


def fake_dll(exports, magic=0x10B):
    """A DLL holding an empty section and then an export table with exports, a {name: bytes} dict; magic 0x20B marks
    it 64-bit. Each name's ordinal is the reverse of its place in the sorted name table, so a reader that confuses the
    two reads the wrong export, and the export table is in the second section, so a reader must walk the sections."""
    base = 0x3000
    names = sorted(exports)
    count = len(names)
    functions_at, names_at, ordinals_at = 40, 40 + 4 * count, 40 + 8 * count
    body = bytearray(ordinals_at + 2 * count)
    struct.pack_into("<IIIII", body, 20, count, count, base + functions_at, base + names_at, base + ordinals_at)
    for i, name in enumerate(names):
        ordinal = count - 1 - i
        struct.pack_into("<I", body, names_at + 4 * i, base + len(body))
        body += name.encode() + bytes(1)
        struct.pack_into("<H", body, ordinals_at + 2 * i, ordinal)
        struct.pack_into("<I", body, functions_at + 4 * ordinal, base + len(body))
        body += exports[name]
    headers = bytearray(0x200)
    struct.pack_into("<I", headers, 0x3C, 0x40)
    headers[0x40:0x44] = b"PE" + bytes(2)
    struct.pack_into("<HH", headers, 0x44, 0x14C, 2)
    struct.pack_into("<H", headers, 0x54, 224)
    struct.pack_into("<H", headers, 0x58, magic)
    struct.pack_into("<II", headers, 0x58 + 96, base, len(body))
    sections = 0x58 + 224
    struct.pack_into("<IIII", headers, sections + 8, 0x2000, 0x1000, 0x200, 0x200)
    struct.pack_into("<IIII", headers, sections + 40 + 8, len(body) + 0x100, base, len(body), 0x400)
    return bytes(headers + bytes(0x200) + body)


def read(path):
    with open(path, encoding="latin-1") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="latin-1", newline="") as f:
        f.write(text)


def sdk_api():
    header = read(os.path.join(os.environ["BAZAAR_SDK"], "include", "CivPluginApi.h"))
    return "%s.%s" % tuple(re.search(r"#define CIV_HOST_API_%s (\d+)" % p, header).group(1) for p in ("MAJOR", "MINOR"))


def dll_plugin_rows(sql):
    code = re.sub(r"'[^']*'|--[^\r\n]*|/\*.*?\*/", lambda m: m[0] if m[0][0] == "'" else "", sql, flags=re.S)
    for insert in re.findall(r"(?i)(?:INSERT\s+(?:OR\s+\w+\s+)?|REPLACE\s+)INTO\s+[\"`\[]?DllPlugins\b[^;]*", code):
        yield from re.findall(r"'([^']+)'", insert)


def write_dll(path):
    api = os.environ.get("FAKE_API") or sdk_api()
    exports = {"CivPluginEntry": b"code"}
    if api != "none":
        exports["CivPluginApiVersion"] = struct.pack("<ii", *(int(n) for n in api.split(".")))
    with open(path, "wb") as f:
        f.write(fake_dll(exports, 0x20B if os.environ.get("FAKE_64BIT") else 0x10B))


def stage_mod(project, stage, mod):
    updates = []
    for sql in glob.glob(os.path.join(project, "mod", "*.sql")):
        text = read(sql)
        if os.environ.get("FAKE_NO_ROW"):
            text = re.sub(r"(?i)INSERT\s+INTO\s+DllPlugins[^;]*;", "", text)
        write(os.path.join(stage, os.path.basename(sql)), text)
        updates.append(os.path.basename(sql))
        for dll in dll_plugin_rows(text):
            if dll != os.environ.get("FAKE_SKIP_DLL"):
                write_dll(os.path.join(stage, dll))
    modinfo = (
        '<Mod id="x" version="%s"><Properties><AffectsSavedGames>%s</AffectsSavedGames></Properties>'
        "<Actions><OnModActivated>%s</OnModActivated></Actions></Mod>"
        % (
            os.environ.get("FAKE_MODINFO_VERSION", mod),
            os.environ.get("FAKE_AFFECTS_SAVES", "1"),
            "".join("<UpdateDatabase>%s</UpdateDatabase>" % u for u in updates),
        )
    )
    write(os.path.join(stage, "mod.modinfo"), modinfo)
    if os.environ.get("FAKE_TWO_MODINFO"):
        write(os.path.join(stage, "another.modinfo"), modinfo)


def main(project):
    if os.environ.get("FAKE_BUILD_FAIL"):
        print("fake build: failing on purpose")
        return 1
    if os.environ.get("FAKE_NO_PACKAGE"):
        return 0
    (civ5proj,) = glob.glob(os.path.join(project, "mod", "*.civ5proj"))
    text = read(civ5proj)
    name = os.environ.get("FAKE_PACKAGE_NAME") or re.search(r"<Name>([^<]*)</Name>", text).group(1)
    mod = re.search(r"<ModVersion>([^<]*)</ModVersion>", text).group(1).strip()
    packages = os.path.join(project, "Packages")
    os.makedirs(packages, exist_ok=True)
    package = os.path.join(packages, "%s (v %s).civ5mod" % (name, mod))
    stage = tempfile.mkdtemp()
    try:
        stage_mod(project, stage, mod)
        subprocess.run([TAR, "-c", "--format", "7zip", "-f", package, "-C", stage] + os.listdir(stage), check=True)
    finally:
        shutil.rmtree(stage)
    print("fake build: made " + os.path.basename(package))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
