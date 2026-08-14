from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "simion/workbench/candidates/oatof_analyzer_component.lua"
LUA_TEST = Path(__file__).with_suffix(".lua")
SIMION_EXE = Path(r"C:\Program Files\SIMION-2020\simion.exe")


class OatofAnalyzerComponentTests(unittest.TestCase):
    def test_component_has_no_callback_electrode_or_clock_authority(self) -> None:
        source = COMPONENT.read_text(encoding="utf-8")
        for forbidden in (
            "simion.workbench_program",
            "segment.",
            "adj_elect",
            "ion_time_of_birth",
            "ion_time_of_flight",
            "os.clock",
            "handoff_pulse_time",
            "pulse_width",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("function component.new(config)", source)
        self.assertIn("accelerator_electrode_write_plan=accelerator_plan", source)
        self.assertIn("initialize_workbench=initialize_workbench", source)
        self.assertNotIn("reference_ground", source)
        self.assertNotIn("state.time_us", source)
        self.assertIn("state.elapsed_us", source)

    @unittest.skipUnless(SIMION_EXE.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_lua_cli_executes_component_contract(self) -> None:
        result = subprocess.run(
            [
                str(SIMION_EXE),
                "--nogui",
                "--noprompt",
                "lua",
                str(LUA_TEST),
                str(COMPONENT),
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
        self.assertIn("OATOF_ANALYZER_COMPONENT_TEST=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
