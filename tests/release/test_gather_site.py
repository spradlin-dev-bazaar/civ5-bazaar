import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "docs"))

import gather_site  # noqa: E402
import paths  # noqa: E402


def release(tag, prerelease=False, docs=True):
    return {"tag": tag, "prerelease": prerelease, "assets": ["Bazaar-docs-%s.zip" % tag[1:]] if docs else []}


TODAY = [
    release("v0.5.3"),
    release("v0.5.2", docs=False),
    release("v0.5.1"),
    release("v0.5.0"),
    release("v0.4.1", prerelease=True),
    release("v0.4.0", prerelease=True),
    release("v0.3.0", prerelease=True),
]


class ChooseTest(unittest.TestCase):
    def choose(self, found):
        with mock.patch.object(gather_site, "say") as said:
            chosen = gather_site.choose(found)
        self.said = [call.args[0] for call in said.call_args_list]
        return chosen

    def test_today_the_main_address_has_0_5_s_newest_docs_and_older_pre_releases_are_left_out(self):
        self.assertEqual(self.choose(TODAY), [("", "v0.5.3", "Bazaar-docs-0.5.3.zip")])

    def test_a_newer_version_on_github_only_goes_in_its_own_folder(self):
        found = [release("v0.6.1", prerelease=True), release("v0.6.0", prerelease=True)] + TODAY
        self.assertEqual(
            self.choose(found), [("", "v0.5.3", "Bazaar-docs-0.5.3.zip"), ("0.6", "v0.6.1", "Bazaar-docs-0.6.1.zip")]
        )

    def test_at_1_0_it_takes_the_main_address_and_0_5_moves_to_its_folder(self):
        found = [release("v1.0.0"), release("v0.8.0", prerelease=True), release("v0.6.0", prerelease=True)] + TODAY
        self.assertEqual(
            self.choose(found), [("", "v1.0.0", "Bazaar-docs-1.0.0.zip"), ("0.5", "v0.5.3", "Bazaar-docs-0.5.3.zip")]
        )

    def test_releases_compare_by_number_and_one_without_docs_keeps_the_docs_before_it(self):
        found = [release("v0.5.9"), release("v0.5.10"), release("v0.5.11", docs=False)] + TODAY
        self.assertEqual(self.choose(found), [("", "v0.5.10", "Bazaar-docs-0.5.10.zip")])

    def test_other_tags_are_ignored(self):
        found = [release("v0.7"), release("test"), release("v0.5.4-rc1")] + TODAY
        self.assertEqual(self.choose(found), [("", "v0.5.3", "Bazaar-docs-0.5.3.zip")])

    def test_every_older_version_on_the_workshop_keeps_its_folder_newest_first(self):
        found = [release("v1.0.0"), release("v2.0.0")] + TODAY
        self.assertEqual(
            self.choose(found),
            [
                ("", "v2.0.0", "Bazaar-docs-2.0.0.zip"),
                ("1.0", "v1.0.0", "Bazaar-docs-1.0.0.zip"),
                ("0.5", "v0.5.3", "Bazaar-docs-0.5.3.zip"),
            ],
        )

    def test_a_folder_version_without_docs_is_left_out_with_a_message(self):
        found = [release("v0.6.0", prerelease=True, docs=False)] + TODAY
        self.assertEqual(self.choose(found), [("", "v0.5.3", "Bazaar-docs-0.5.3.zip")])
        self.assertEqual(len(self.said), 1)
        self.assertIn("Bazaar 0.6", self.said[0])

    def test_an_older_version_on_the_workshop_without_docs_is_left_out_with_a_message(self):
        found = [release("v1.0.0"), release("v0.5.0", docs=False)]
        self.assertEqual(self.choose(found), [("", "v1.0.0", "Bazaar-docs-1.0.0.zip")])
        self.assertEqual(len(self.said), 1)
        self.assertIn("Bazaar 0.5", self.said[0])

    def test_the_main_address_without_docs_stops(self):
        with self.assertRaisesRegex(SystemExit, "no release of Bazaar 0.5 has a docs zip"):
            self.choose([release("v0.5.0", docs=False)])

    def test_without_a_full_release_it_stops(self):
        with self.assertRaisesRegex(SystemExit, "no release is a full release"):
            self.choose([release("v0.4.0", prerelease=True)])


class GatherTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.site = os.path.join(temp.name, "site")
        self.zips = {}
        self.found = [release("v0.6.0", prerelease=True), release("v0.5.3")]

    def zip_of(self, name, files):
        self.zips[name] = files

    def gh(self, *args):
        if args[0] == "api":
            return "\n".join(json.dumps(r) for r in self.found)
        name, folder = args[args.index("--pattern") + 1], args[args.index("--dir") + 1]
        with zipfile.ZipFile(os.path.join(folder, name), "w") as z:
            for path, text in self.zips[name].items():
                z.writestr(path, text)
        return ""

    def gather(self):
        with mock.patch.object(gather_site, "gh", self.gh), mock.patch.object(gather_site, "say"):
            gather_site.gather("owner/name", self.site)

    def files(self):
        return sorted(
            os.path.relpath(os.path.join(folder, name), self.site).replace(os.sep, "/")
            for folder, _, names in os.walk(self.site)
            for name in names
        )

    def test_each_version_goes_in_its_place_without_the_markdown_copies(self):
        self.zip_of("Bazaar-docs-0.5.3.zip", {"index.html": "5", "index.md": "5", "reference/a.html": "5"})
        self.zip_of("Bazaar-docs-0.6.0.zip", {"index.html": "6", "reference/a.md": "6", "style.css": "6"})
        self.gather()
        self.assertEqual(self.files(), ["0.6/index.html", "0.6/style.css", "index.html", "reference/a.html"])

    def test_the_site_leaves_out_every_markdown_copy_that_the_docs_build_writes(self):
        self.assertTrue(paths.markdown_page("reference/a.html").endswith(gather_site.MARKDOWN))

    def test_an_empty_folder_takes_the_site(self):
        os.makedirs(self.site)
        self.found = [release("v0.5.3")]
        self.zip_of("Bazaar-docs-0.5.3.zip", {"index.html": "5"})
        self.gather()
        self.assertEqual(self.files(), ["index.html"])

    def test_a_folder_the_main_address_already_has_stops(self):
        self.zip_of("Bazaar-docs-0.5.3.zip", {"index.html": "5", "0.6/x.html": "5"})
        self.zip_of("Bazaar-docs-0.6.0.zip", {"index.html": "6"})
        with self.assertRaisesRegex(SystemExit, "already have a folder named 0.6"):
            self.gather()

    def test_a_folder_that_is_not_empty_stops(self):
        os.makedirs(self.site)
        open(os.path.join(self.site, "old.html"), "w").close()
        with self.assertRaisesRegex(SystemExit, "is not empty"):
            self.gather()


if __name__ == "__main__":
    unittest.main()
