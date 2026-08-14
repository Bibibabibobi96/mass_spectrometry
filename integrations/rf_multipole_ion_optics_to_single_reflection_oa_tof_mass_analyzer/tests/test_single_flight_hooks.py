from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pure_boundary_validator import (
    BoundaryContractError,
    validate_pure_lua_component_source,
)


ROOT = Path(__file__).resolve().parents[1]
PULSE_HOOK = ROOT / "runtime/single_flight_pulse_hook.lua"
FRONTEND_HOOK = ROOT / "runtime/single_flight_frontend_hook.lua"
LUA_TEST = ROOT / "tests/test_single_flight_hooks.lua"
SIMION_EXE = Path(r"C:\Program Files\SIMION-2020\simion.exe")


class SingleFlightHookTests(unittest.TestCase):
    def test_components_are_callback_neutral(self) -> None:
        for path in (PULSE_HOOK, FRONTEND_HOOK):
            source = path.read_text(encoding="utf-8")
            self.assertEqual(
                validate_pure_lua_component_source(source, path.name), source
            )

    def test_validator_rejects_every_owned_boundary_with_token_spacing(self) -> None:
        forbidden = (
            "simion.workbench_program()",
            "segment . fast_adjust=function() end",
            "adj_elect[1]=0",
            "return ion_time_of_birth",
            "return ion_time_of_flight",
            "return simion . wb.instances",
            "return os . clock()",
        )
        for index, source in enumerate(forbidden):
            with self.subTest(source=source):
                with self.assertRaises(BoundaryContractError):
                    validate_pure_lua_component_source(source, f"invalid_{index}")

    def test_validator_uses_word_boundaries(self) -> None:
        source = "local segment_state, my_adj_electrode, ion_time_of_flightless = 1, 2, 3"
        self.assertEqual(validate_pure_lua_component_source(source, "valid"), source)

    @unittest.skipUnless(SIMION_EXE.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_lua_cli_executes_pure_hook_contract(self) -> None:
        result = subprocess.run(
            [
                str(SIMION_EXE),
                "--nogui",
                "--noprompt",
                "lua",
                str(LUA_TEST),
                str(PULSE_HOOK),
                str(FRONTEND_HOOK),
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
        self.assertIn("SINGLE_FLIGHT_PURE_HOOKS=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
