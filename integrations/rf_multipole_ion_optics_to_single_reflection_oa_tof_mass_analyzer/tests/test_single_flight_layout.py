from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    select_profile,
)


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


class SingleFlightLayoutTests(unittest.TestCase):
    def test_10ev_profile_derives_linked_layout_from_one_energy_parameter(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        profile = select_profile(registry, "symmetric_10ev_injection_diagnostic")
        resolved, derived_port, values = compile_geometry_and_port(geometry, port, profile)
        expected_axis = -48.8 * math.sqrt(2.0)
        self.assertAlmostEqual(values["accelerator_axis_x_mm"], expected_axis)
        self.assertAlmostEqual(values["detector_x_mm"], -expected_axis)
        self.assertAlmostEqual(values["entry_port_x_mm"], expected_axis - 19.0)
        self.assertEqual(resolved["particle_source"]["center_x_mm"], expected_axis)
        self.assertEqual(derived_port["mating_surface"]["center_mm"][0], expected_axis - 19.0)

    def test_source_z22_profile_compiles_coupled_reflectron_candidate(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        profile = select_profile(registry, "symmetric_10ev_source_z22_diagnostic")
        resolved, _, _ = compile_geometry_and_port(geometry, port, profile)
        derivation = resolved["geometry_derivation"]["reflectron"]
        self.assertEqual(resolved["particle_source"]["size_z_mm"], 2.2)
        self.assertEqual(
            resolved["geometry_derivation"]["accelerator"]["d1_mm"], 3.0
        )
        self.assertAlmostEqual(derivation["energy_min_V"], 1824.0)
        self.assertAlmostEqual(derivation["energy_max_V"], 2176.0)
        self.assertGreater(
            resolved["geometry_mm"]["L_stage2"], geometry["geometry_mm"]["L_stage2"]
        )
        self.assertNotEqual(
            resolved["electrodes_V"]["backplate"],
            geometry["electrodes_V"]["backplate"],
        )
        compilation = resolved["single_flight_layout_derivation"][
            "design_compilation"
        ]
        self.assertEqual(
            compilation["method"],
            "catalog_design_overrides_with_theory_closure_v1",
        )
        self.assertEqual(
            compilation["simion_rebuild_plan"],
            {
                "frontend_pa": False,
                "flight_tube_pa": False,
                "reflectron_pa": True,
            },
        )

    def test_generic_overrides_rebuild_linked_accelerator_and_flight_region(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        profile = select_profile(registry, "symmetric_10ev_injection_diagnostic")
        profile["design_overrides"] = [
            {"variable": "accelerator_stage1_length", "value": 3.5, "unit": "mm"},
            {"variable": "flight_length", "value": 550.0, "unit": "mm"},
        ]
        resolved, _, _ = compile_geometry_and_port(geometry, port, profile)
        compilation = resolved["single_flight_layout_derivation"][
            "design_compilation"
        ]
        self.assertEqual(
            compilation["simion_rebuild_plan"],
            {
                "frontend_pa": True,
                "flight_tube_pa": True,
                "reflectron_pa": True,
            },
        )
        self.assertEqual(
            resolved["geometry_derivation"]["accelerator"]["d1_mm"], 3.5
        )
        self.assertEqual(resolved["geometry_mm"]["L_flight"], 550.0)


if __name__ == "__main__":
    unittest.main()
