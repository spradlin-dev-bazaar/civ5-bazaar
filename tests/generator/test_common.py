"""Checks of tools/generator/common.py.

python -m unittest discover -s tests/generator
"""

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "generator"))

import common  # noqa: E402


class EnvTest(unittest.TestCase):
    def test_the_visual_c_path_replaces_the_one_before_it_whatever_its_case(self):
        printed = types.SimpleNamespace(stdout="Path=C:\\VC\\BIN\nINCLUDE=C:\\VC\\INCLUDE\n")
        with (
            mock.patch.object(common.subprocess, "run", return_value=printed),
            mock.patch.dict(os.environ, {"PATH": "C:\\Windows"}),
        ):
            env = common.vs_env()
        self.assertEqual(env["PATH"], "C:\\VC\\BIN")
        self.assertNotIn("Path", env)


if __name__ == "__main__":
    unittest.main()
