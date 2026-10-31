"""Lua native transport reads the same ephemeral mapping as Python."""
from pathlib import Path
import subprocess
import tempfile
import unittest


LUA = Path("C:/Program Files/SIMION-2020/lua.exe")
MODULE = Path(__file__).with_name("native_run_path.lua")


@unittest.skipUnless(LUA.is_file(), "plain Lua unavailable")
class NativeRunPathTests(unittest.TestCase):
    def test_dynamic_mapping_is_contained_and_does_not_become_persistent_content(self):
        harness = r'''
local env={}
os.getenv=function(name) return env[name] end
local project=assert(loadfile(arg[1]))()
local source='C:/deep/canonical/run/simion/control.lua'
assert(project(source)==source)
env.MASS_SPECTROMETRY_RUN_DIRECTORY='C:/deep/canonical/run'
assert(not pcall(project,source))
env.MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY='C:/short/run_x'
assert(project(source)=='C:/short/run_x/simion/control.lua')
assert(project('c:\\deep\\canonical\\run\\simion\\control.lua')=='C:/short/run_x/simion/control.lua')
assert(project('C:/deep/canonical/run_other/control.lua')=='C:/deep/canonical/run_other/control.lua')
assert(project('C:/external/cache/a.pa')=='C:/external/cache/a.pa')
assert(not pcall(project,'C:/deep/canonical/run/../outside.pa'))
env.MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY='D:/new_execution/run_y'
assert(project(source)=='D:/new_execution/run_y/simion/control.lua')
env.MASS_SPECTROMETRY_RUN_DIRECTORY=nil;env.MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=nil
assert(project(source)==source)
print('NATIVE_RUN_PATH=PASS')
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"test.lua"
            path.write_text(harness, encoding="utf-8", newline="\n")
            result = subprocess.run([str(LUA), str(path), str(MODULE)], cwd=temporary,
                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("NATIVE_RUN_PATH=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
