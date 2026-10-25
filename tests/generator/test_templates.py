"""Values the templates copy by hand from the host's build.

python -m unittest discover -s tests/generator
"""

import os
import sys
import unittest
from xml.etree import ElementTree

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(REPO, "tools", "generator"))

import common  # noqa: E402

TEMPLATES = [
    os.path.join(REPO, "sdk", "plugin-template", "mod", "TemplatePlugin.civ5proj"),
    os.path.join(REPO, "claude-plugin", "skills", "new-lua-mod", "template", "mod", "TemplateLuaMod.civ5proj"),
]


class TemplateTest(unittest.TestCase):
    def test_each_template_depends_on_the_host_mod_by_its_id_and_name(self):
        for path in TEMPLATES:
            root = ElementTree.parse(path).getroot()
            ns = {"m": root.tag.split("}")[0][1:]} if root.tag.startswith("{") else {}
            prefix = "m:" if ns else ""
            dependencies = root.findall(".//%sModDependencies/%sAssociation" % (prefix, prefix), ns)
            found = [
                (d.findtext(prefix + "Id", namespaces=ns), d.findtext(prefix + "Name", namespaces=ns))
                for d in dependencies
            ]
            self.assertIn((common.HOST_MOD_ID, common.HOST_MOD_NAME), found, path)


if __name__ == "__main__":
    unittest.main()
