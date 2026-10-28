"""Checks of tools/mods.py: the two mods Bazaar ships, laid out and packed.

python -m unittest discover -s tests/release
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))

import mods  # noqa: E402

LICENSE_NAMES = [mods.LICENSE_FILE[0], mods.NOTICE_FILE[0]]
SEVEN_ZIP_SIGNATURE = b"7z\xbc\xaf\x27\x1c"


def modinfo(folder):
    (name,) = [n for n in os.listdir(folder) if n.endswith(".modinfo")]
    return ElementTree.parse(os.path.join(folder, name)).getroot()


def lay_out(mods_folder, **options):
    dll = os.path.join(mods_folder, "fake.dll")
    os.makedirs(mods_folder)
    with open(dll, "wb") as f:
        f.write(b"MZ")
    return mods.write_dll_mod(mods_folder, mods.HOST_NAME, mods.HOST_ID, "Teaser.", dll, **options)


def files_in(folder):
    found = set()
    for dirpath, _, filenames in os.walk(folder):
        found.update(os.path.relpath(os.path.join(dirpath, n), folder).replace(os.sep, "/") for n in filenames)
    return found


class LayoutTest(unittest.TestCase):
    def test_both_mods_carry_the_license_and_list_it(self):
        with tempfile.TemporaryDirectory() as folder:
            for mod in lay_out(os.path.join(folder, "MODS"), host_screens=True, version=3):
                listed = [f.text for f in modinfo(mod).find("Files")]
                for name in LICENSE_NAMES:
                    self.assertTrue(os.path.isfile(os.path.join(mod, name)), "%s lacks %s" % (mod, name))
                    self.assertIn(name, listed)

    def test_every_file_is_listed_with_its_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            for mod in lay_out(os.path.join(folder, "MODS"), host_screens=True):
                with self.subTest(mod=os.path.basename(mod)):
                    listed = dict((f.text, f.get("md5")) for f in modinfo(mod).find("Files"))
                    modinfo_name = [n for n in os.listdir(mod) if n.endswith(".modinfo")]
                    self.assertEqual(set(listed), files_in(mod) - set(modinfo_name))
                    for path, digest in listed.items():
                        self.assertEqual(digest, mods.md5(os.path.join(mod, path)), path)

    def test_the_host_mod_takes_the_version_it_is_given(self):
        with tempfile.TemporaryDirectory() as folder:
            host, bootstrap = lay_out(os.path.join(folder, "MODS"), host_screens=True, version=3)
            self.assertEqual(modinfo(host).get("version"), "3")
            self.assertTrue(host.endswith("(v 3)"))
            self.assertEqual(modinfo(bootstrap).get("version"), str(mods.vmc_mod_parts().version))

    def test_a_mod_given_no_version_is_version_1(self):
        with tempfile.TemporaryDirectory() as folder:
            host, _ = lay_out(os.path.join(folder, "MODS"))
            self.assertEqual(modinfo(host).get("version"), "1")

    def test_the_host_needs_exactly_the_bootstraps_version_and_loads_its_own_dll(self):
        with tempfile.TemporaryDirectory() as folder:
            host, _ = lay_out(os.path.join(folder, "MODS"))
            root = modinfo(host)
            (vmc,) = [m for m in root.find("Dependencies") if m.get("id") == mods.VMC_MOD_ID]
            vmc_version = str(mods.vmc_mod_parts().version)
            self.assertEqual((vmc.get("minversion"), vmc.get("maxversion")), (vmc_version, vmc_version))
            dll = root.findtext("Actions/OnGetDLLPath/SetDllPath")
            imported = dict((f.text, f.get("import")) for f in root.find("Files"))
            self.assertEqual(imported.get(dll), "1")
            self.assertEqual([u.text for u in root.find("Actions/OnModActivated")], ["DllPlugins.sql"])

    def test_the_host_screens_come_with_their_files_and_entry_point(self):
        for host_screens in (True, False):
            with tempfile.TemporaryDirectory() as folder, self.subTest(host_screens=host_screens):
                host, _ = lay_out(os.path.join(folder, "MODS"), host_screens=host_screens)
                root = modinfo(host)
                files = [f.text for f in root.find("Files")]
                entries = root.find("EntryPoints")
                addins = [] if entries is None else [(e.get("type"), e.get("file")) for e in entries]
                self.assertEqual(any(f.startswith("frontend/") for f in files), host_screens)
                self.assertEqual(addins, [mods.STOPPED_POPUP[:2]] if host_screens else [])
                if host_screens:
                    for path in ("ingame/BazaarStopped.xml", "ingame/BazaarStopped.lua"):
                        self.assertIn(path, files)
                        self.assertTrue(os.path.isfile(os.path.join(host, path)))

    def test_the_bootstrap_keeps_vmcs_credits_and_save_setting(self):
        vmc = mods.vmc_mod_parts()
        with tempfile.TemporaryDirectory() as folder:
            _, bootstrap = lay_out(os.path.join(folder, "MODS"))
            properties = modinfo(bootstrap).find("Properties")
            self.assertEqual(properties.findtext("Authors"), vmc.authors)
            for tag, text in vmc.credits:
                self.assertEqual(properties.findtext(tag), text)
            self.assertEqual(properties.findtext("AffectsSavedGames"), str(int(vmc.affects_saves)))


class WorkshopTextTest(unittest.TestCase):
    def test_the_workshop_texts_name_the_vmc_version_the_bootstrap_carries(self):
        workshop = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "workshop")
        for name in ("bazaar.txt", "vmc-bootstrap.txt"):
            with open(os.path.join(workshop, name), encoding="utf-8") as f:
                named = set(re.findall(r"(?:VMC|Mod Components),? version (\d+)", f.read()))
            self.assertEqual(named, {str(mods.vmc_mod_parts().version)}, name)


@unittest.skipUnless(os.path.isfile(mods.TAR), "needs Windows' tar.exe")
class PackTest(unittest.TestCase):
    def test_a_package_is_7z_with_the_mod_files_at_its_top_and_replaces_an_old_one(self):
        with tempfile.TemporaryDirectory() as folder:
            host, _ = lay_out(os.path.join(folder, "MODS"), host_screens=True)
            package = os.path.join(folder, "host.civ5mod")
            with open(package, "wb") as f:
                f.write(b"an old package")
            self.assertIsNone(mods.pack(host, package))
            with open(package, "rb") as f:
                self.assertEqual(f.read(len(SEVEN_ZIP_SIGNATURE)), SEVEN_ZIP_SIGNATURE)
            listed = subprocess.run([mods.TAR, "-tf", package], capture_output=True, text=True).stdout.splitlines()
            self.assertEqual(set(n.split("/")[0] for n in listed), set(os.listdir(host)))

    def test_a_failed_pack_names_the_mod_and_the_package(self):
        with tempfile.TemporaryDirectory() as folder:
            host, _ = lay_out(os.path.join(folder, "MODS"))
            package = os.path.join(folder, "no such folder", "host.civ5mod")
            problem = mods.pack(host, package)
        self.assertIn("could not pack %s into %s" % (host, package), problem)


if __name__ == "__main__":
    unittest.main()
