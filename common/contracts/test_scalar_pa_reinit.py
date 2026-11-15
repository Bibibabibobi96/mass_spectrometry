"""Portable SIMION PA API double for repeated sampled-program initialization."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from msplatform.backends.simion.resources import native_resource_path


class ScalarPaReinitializationTests(unittest.TestCase):
    def test_repeated_loads_preserve_support_and_container_bound(self):
        lua = os.environ.get('SIMION_LUA_EXE') or shutil.which('lua5.1') or shutil.which('lua')
        if not lua:
            self.skipTest('Lua 5.1 provider unavailable')
        script = Path(__file__).with_suffix('.lua')
        result = subprocess.run([str(lua), str(script), str(native_resource_path('scalar_field_adapter.lua')),
                                 str(native_resource_path('ip_mr_scalar_field.lua'))],
                                cwd=str(script.parent), capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SCALAR_REINIT_PASS arrays=107 passes=4', result.stdout)
