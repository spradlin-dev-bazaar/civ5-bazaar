"""Stands in for the building part of a template's build.cmd in the build script's tests: packs what build.cmd would,
from the project's .civ5proj and its .sql and .xml database updates, with a stand-in for each DLL it is told of."""

import dataclasses
import glob
import os
import shutil
import struct
import subprocess
import tempfile
from xml.etree import ElementTree

TAR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
SAVES = "<AffectsSavedGames>1</AffectsSavedGames>"


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


def write_dll(path, api, bits):
    exports = {"CivPluginEntry": b"code"}
    if api:
        exports["CivPluginApiVersion"] = struct.pack("<ii", *(int(n) for n in api.split(".")))
    with open(path, "wb") as f:
        f.write(fake_dll(exports, 0x20B if bits == 64 else 0x10B))


def project_property(civ5proj, name):
    for group in ElementTree.parse(civ5proj).getroot():
        if group.tag.endswith("PropertyGroup"):
            for element in group:
                if element.tag.endswith("}" + name):
                    return element.text or ""
    return None


@dataclasses.dataclass
class Build:
    """What to pack: each DLL declares api, "major.minor", or no version when api is None, and sits in dll_folder, with
    a second listed copy in copy_in when that is given. skip_dll is left out of the package and unlisted_dll out of the
    mod's file list; saves is what the mod description's <Properties> holds."""

    dlls: tuple = ()
    dll_folder: str = ""
    copy_in: str = ""
    api: str | None = None
    bits: int = 32
    skip_dll: str | None = None
    unlisted_dll: str | None = None
    saves: str = SAVES
    broken_modinfo: bool = False
    two_modinfo: bool = False
    package_name: str | None = None

    def stage(self, project, stage, mod):
        updates = []
        for pattern in ("*.sql", "*.xml"):
            for path in glob.glob(os.path.join(project, "mod", pattern)):
                shutil.copy(path, stage)
                updates.append(os.path.basename(path))
        os.makedirs(os.path.join(stage, self.dll_folder), exist_ok=True)
        for dll in self.dlls:
            if dll != self.skip_dll:
                write_dll(os.path.join(stage, self.dll_folder, dll), self.api, self.bits)
        listed = [dll for dll in self.dlls if dll != self.unlisted_dll]
        files = updates + [self.dll_folder + "\\" + dll if self.dll_folder else dll for dll in listed]
        if self.copy_in:
            os.makedirs(os.path.join(stage, self.copy_in))
            for dll in self.dlls:
                write_dll(os.path.join(stage, self.copy_in, dll), self.api, self.bits)
            files += [self.copy_in + "\\" + dll for dll in self.dlls]
        modinfo = (
            '<Mod id="x" version="%s"><Properties>%s</Properties><Files>%s</Files>'
            "<Actions><OnModActivated>%s</OnModActivated></Actions></Mod>"
            % (
                mod,
                self.saves,
                "".join('<File md5="0" import="0">%s</File>' % name for name in files),
                "".join("<UpdateDatabase>%s</UpdateDatabase>" % u for u in updates),
            )
        )
        if self.broken_modinfo:
            modinfo = modinfo.replace("</Properties>", "", 1)
        with open(os.path.join(stage, "mod.modinfo"), "w") as f:
            f.write(modinfo)
        if self.two_modinfo:
            shutil.copy(os.path.join(stage, "mod.modinfo"), os.path.join(stage, "another.modinfo"))

    def pack(self, project):
        (civ5proj,) = glob.glob(os.path.join(project, "mod", "*.civ5proj"))
        name = self.package_name or project_property(civ5proj, "Name")
        mod = project_property(civ5proj, "ModVersion").strip()
        packages = os.path.join(project, "Packages")
        os.makedirs(packages, exist_ok=True)
        package = os.path.join(packages, "%s (v %s).civ5mod" % (name, mod))
        stage = tempfile.mkdtemp()
        try:
            self.stage(project, stage, mod)
            subprocess.run([TAR, "-c", "--format", "7zip", "-f", package, "-C", stage] + os.listdir(stage), check=True)
        finally:
            shutil.rmtree(stage)
        return package
