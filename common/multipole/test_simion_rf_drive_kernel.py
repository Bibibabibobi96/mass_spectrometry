from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
KERNEL = ROOT / "simion_rf_drive.lua"
LUA_TEST = ROOT / "test_simion_rf_drive.lua"
SIMION_EXE = Path(r"C:\Program Files\SIMION-2020\simion.exe")


class SimionRfDriveKernelTests(unittest.TestCase):
    def test_kernel_is_pure_and_has_no_clock_or_callback_authority(self) -> None:
        source = KERNEL.read_text(encoding="utf-8")
        for forbidden in (
            "simion.workbench_program",
            "segment.",
            "ion_time_of_flight",
            "ion_time_of_birth",
            "adj_elect",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("function kernel.new(config)", source)
        self.assertIn("local function apply_at(instrument_time_us, setter)", source)

    @unittest.skipUnless(SIMION_EXE.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_lua_cli_executes_numerical_contract(self) -> None:
        result = subprocess.run(
            [
                str(SIMION_EXE),
                "--nogui",
                "--noprompt",
                "lua",
                str(LUA_TEST),
                str(KERNEL),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SIMION_RF_DRIVE_KERNEL_TEST=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
