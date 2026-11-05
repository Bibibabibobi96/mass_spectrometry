"""Command invariants and standalone Lua stubs; never execute SIMION or open PA."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import unittest

from msplatform.backends.simion.native_io import apply_native_io_mode


LUA = shutil.which("lua") or str(Path(os.environ.get(
    "SIMION_EXE", r"C:\Program Files\SIMION-2020\simion.exe")).with_name("lua.exe"))


class NativeIoTests(unittest.TestCase):
    def setUp(self):
        self.original = ["simion.exe", "--nogui", "--noprompt", "lua", "owned.lua", "same input", "--unchanged"]

    def run_lua(self, stub, enabled):
        if not Path(LUA).is_file():
            self.skipTest("standalone Lua executable unavailable; no native SIMION fallback")
        argv = apply_native_io_mode(self.original, allow_asynchronous_io=enabled)
        return subprocess.run([LUA, "-e", stub + "; " + argv[4]],
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=False,
            cwd=Path(__file__).resolve().parents[2])

    def test_none_preserves_all_original_arguments_and_input(self):
        for original in (self.original, ["python", "-c", "pass"], ["simion.exe", "--lua", "original()"]):
            result = apply_native_io_mode(original, allow_asynchronous_io=None)
            self.assertEqual(result, original)
            self.assertIsNot(result, original)
        with self.assertRaises(TypeError):
            apply_native_io_mode("simion.exe", allow_asynchronous_io=None)

    def test_explicit_modes_change_only_prelude_and_never_mutate_argv(self):
        before = self.original.copy()
        for enabled in (False, True):
            actual = apply_native_io_mode(self.original, allow_asynchronous_io=enabled)
            self.assertEqual(actual[:3]+actual[5:], before)
            self.assertEqual(actual[3], "--lua")
            self.assertIn("type(before)=='boolean'", actual[4])
            self.assertIn(f"d.allow_asynchronous_io={str(enabled).lower()}", actual[4])
            self.assertIn(f"d.allow_asynchronous_io=={str(enabled).lower()}", actual[4])
            self.assertEqual(actual[4].count("io.stdout:flush()"), 2)
        self.assertEqual(self.original, before)

    def test_explicit_fly_mode_is_before_command_and_keeps_iob_spelling(self):
        original=['simion.exe','--nogui','--noprompt','fly','C:/alias/unit/instrument.iob']
        self.assertEqual(apply_native_io_mode(original,allow_asynchronous_io=None),original)
        for enabled in (False,True):
            with self.subTest(enabled=enabled):
                actual=apply_native_io_mode(original,allow_asynchronous_io=enabled)
                self.assertEqual(actual[:3]+actual[5:],original)
                self.assertEqual(actual[3],'--lua')
                self.assertEqual(actual[-2:],original[-2:])
                self.original=original
                result=self.run_lua('simion={debug={allow_asynchronous_io=true}}',enabled)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('ASYNC_IO_CONTROL applied='+str(enabled).lower(),result.stdout)
        self.assertEqual(original[-1],'C:/alias/unit/instrument.iob')
        for wrong in (['simion.exe','--noprompt','fly','file.iob'],
                      ['simion.exe','--nogui','--noprompt','refine','file.pa#'],
                      ['simion.exe','--nogui=0','--noprompt','fly','file.iob']):
            with self.subTest(wrong=wrong),self.assertRaisesRegex(ValueError,'headless'):
                apply_native_io_mode(wrong,allow_asynchronous_io=False)

    def test_conflicting_preludes_and_nonheadless_shapes_reject(self):
        for token in ("--lua", "--lua=custom()"):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, "conflicts"):
                apply_native_io_mode(self.original+[token], allow_asynchronous_io=False)
        for arguments in (["python", "--nogui", "--noprompt", "lua", "owned.lua"],
                          ["simion.exe", "lua", "owned.lua"], self.original[:4],
                          ["simion.exe", "--nogui", "--noprompt", "refine", "field.pa#"]):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, "headless"):
                apply_native_io_mode(arguments, allow_asynchronous_io=False)
        for value in (0, 1, "false"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                apply_native_io_mode(self.original, allow_asynchronous_io=value)

    def test_plain_lua_boolean_getter_setter_readback_and_flushed_facts(self):
        for before in (False, True):
            for enabled in (False, True):
                with self.subTest(before=before, enabled=enabled):
                    result = self.run_lua(
                        "simion={debug={allow_asynchronous_io="+str(before).lower()+"}}", enabled)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertEqual(result.stdout.splitlines(), [
                        f"ASYNC_IO_CONTROL before={str(before).lower()}",
                        f"ASYNC_IO_CONTROL applied={str(enabled).lower()}"])

    def test_plain_lua_unknown_getter_and_failed_readback_are_not_success(self):
        cases = [("simion={}", "interface unavailable"),
                 ("simion={debug={}}", "getter unverified"),
                 ("simion={debug={allow_asynchronous_io='false'}}", "getter unverified"),
                 ("simion={debug=setmetatable({}, {__index=function() return true end, "
                  "__newindex=function() end})}", "readback failed")]
        for stub, message in cases:
            with self.subTest(message=message):
                result = self.run_lua(stub, False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn("ASYNC_IO_CONTROL applied=", result.stdout)

    def test_existing_tiny_fixture_uses_same_installed_implementation(self):
        from common.simion import test_dirichlet_patch_basis as fixture
        original = [str(fixture.SIMION), *self.original[1:]]
        self.assertEqual(fixture._fixture_execution_command(original, disable_async_io=False), original)
        self.assertEqual(fixture._fixture_execution_command(original, disable_async_io=True),
            apply_native_io_mode(original, allow_asynchronous_io=False))
        self.assertEqual(fixture._ASYNC_IO_PRELUDE,
            apply_native_io_mode(original, allow_asynchronous_io=False)[4])


if __name__ == "__main__":
    unittest.main()
