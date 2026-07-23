from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]


class MassFilterSimionContractTests(unittest.TestCase):
    def test_lua_applies_dc_and_rf_as_one_differential_voltage(self) -> None:
        wrapper = (PROJECT_ROOT / "simion" / "programs" / "quad_transport.lua").read_text(encoding="utf-8")
        self.assertIn("MULTIPOLE_SIMION_SHARED_PROGRAM_LUA", wrapper)
        lua = (REPO_ROOT / "common" / "multipole" / "simion_transport.lua").read_text(encoding="utf-8")
        self.assertIn("local differential = transport_dc_amplitude_v + rf", lua)
        self.assertIn("adj_elect01 = transport_axis_voltage_v + differential", lua)
        self.assertIn("adj_elect02 = transport_axis_voltage_v - differential", lua)

    def test_runner_uses_paired_mass_generator_and_functional_analyzer(self) -> None:
        runner = (PROJECT_ROOT / "tests" / "simion" / "run_transport_candidate.ps1").read_text(encoding="utf-8")
        self.assertIn("'mass_filter_reference'", runner)
        self.assertIn("analysis.generate_mass_scan_particle_table", runner)
        self.assertIn("analysis.analyze_simion_mass_scan", runner)
        self.assertLess(runner.index("$expectedParticles = if"), runner.index("minimum_diagnostic_particles"))
        self.assertIn("$baseTransportMode.numerics.simion_rf_steps_per_period", runner)
        self.assertIn("$baseTransportMode.static_electrodes_V", runner)
        self.assertIn("resolved_mass_filter.json", runner)

    def test_mass_filter_voltage_contract_is_unambiguous(self) -> None:
        mode = json.loads(
            (PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json").read_text(encoding="utf-8")
        )
        self.assertAlmostEqual(mode["rf"]["dc_amplitude_V_per_group"], 22.763014939677756)
        self.assertAlmostEqual(mode["rf"]["axis_common_mode_offset_V"], -8.0)
        self.assertEqual(mode["solver_screen"]["particles_per_mass"], 100)


if __name__ == "__main__":
    unittest.main()
