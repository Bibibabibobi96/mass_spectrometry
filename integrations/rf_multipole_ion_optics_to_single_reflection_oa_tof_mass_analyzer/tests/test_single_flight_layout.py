from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    select_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import (
    bind_oatof_adjustables,
)


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


class SingleFlightLayoutTests(unittest.TestCase):
    def test_formal_pa_assets_cross_runtime_boundary_by_value(self) -> None:
        support = (
            INTEGRATION / "runtime" / "single_flight_assets.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("Copy-Item -LiteralPath $source -Destination $target", support)
        self.assertNotIn("ItemType HardLink", support)

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
        self.assertEqual(
            resolved["single_flight_layout_derivation"]["design_compilation"][
                "changed_variables"
            ],
            [],
        )

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
        resolved, derived_port, _ = compile_geometry_and_port(geometry, port, profile)
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

    def test_finite_interval_profile_derives_focus_at_global_zero(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        profile = select_profile(
            registry, "symmetric_10ev_source_z22_finite_interval_theory"
        )
        resolved, derived_port, _ = compile_geometry_and_port(geometry, port, profile)
        accelerator = resolved["geometry_derivation"]["accelerator"]
        theory = accelerator["finite_interval_theory"]
        self.assertEqual(resolved["particle_source"]["size_z_mm"], 2.2)
        self.assertAlmostEqual(
            accelerator["canonical_grid2_z_mm"]
            + accelerator["focus_drift_after_grid2_mm"],
            0.0,
            places=12,
        )
        self.assertAlmostEqual(resolved["electrodes_V"]["repeller"], 2157.37, places=1)
        self.assertAlmostEqual(resolved["electrodes_V"]["grid1"], 1842.29, places=1)
        self.assertEqual(resolved["rings"]["accelerator_count"], 5)
        self.assertLess(theory["theoretical_rms_time_ns"], 0.082)
        self.assertAlmostEqual(resolved["electrodes_V"]["midgrid"], 1603.68, places=1)
        self.assertGreater(
            resolved["electrodes_V"]["backplate"],
            resolved["electrodes_V"]["midgrid"],
        )
        self.assertLess(
            theory["coupled_reflectron"]["required_stage2_depth_mm"],
            resolved["geometry_mm"]["L_stage2"],
        )
        expected_near_outer = (
            accelerator["outer_envelope_min_z_mm"]
            - resolved["geometry_mm"]["shield_near_endcap_gap"]
            - resolved["geometry_mm"]["shield_endcap_thickness"]
        )
        self.assertAlmostEqual(
            resolved["geometry_mm"]["shield_outer_z_min"], expected_near_outer
        )
        self.assertEqual(
            derived_port["mating_surface"]["center_mm"][2],
            resolved["particle_source"]["center_z_mm"],
        )
        self.assertEqual(
            resolved["particle_source"]["center_z_rule"],
            "geometry_derivation.accelerator.finite_interval_theory."
            "canonical_repeller_z_mm + source_center_mm",
        )
        self.assertEqual(
            resolved["single_flight_layout_derivation"]["design_compilation"][
                "simion_rebuild_plan"
            ],
            {"frontend_pa": True, "flight_tube_pa": True, "reflectron_pa": False},
        )

    def test_zero_match_reflectron_voltage_is_consistent_through_generated_lua(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        formal = (
            REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/"
            "workbench/formal/oatof_ideal_grounded.lua"
        ).read_text()
        for profile_id in ("zero_match_short_1mm", "zero_match_long_2p2mm"):
            with self.subTest(profile_id=profile_id):
                profile = select_profile(registry, profile_id)
                resolved, _, _ = compile_geometry_and_port(geometry, port, profile)
                accelerator = resolved["geometry_derivation"]["accelerator"]
                coupled = accelerator["finite_interval_theory"]["coupled_reflectron"]
                reflectron = resolved["geometry_derivation"]["reflectron"]
                compilation = resolved["single_flight_layout_derivation"]["design_compilation"]
                midgrid = resolved["electrodes_V"]["midgrid"]
                backplate = resolved["electrodes_V"]["backplate"]
                self.assertAlmostEqual(midgrid, coupled["stage1_voltage_drop_v"])
                self.assertAlmostEqual(
                    backplate,
                    midgrid
                    + coupled["stage2_field_v_per_mm"]
                    * resolved["geometry_mm"]["L_stage2"],
                )
                self.assertAlmostEqual(
                    reflectron["source_release_full_width_mm"],
                    resolved["particle_source"]["size_z_mm"],
                )
                self.assertAlmostEqual(
                    reflectron["energy_min_V"], coupled["energy_min_v"]
                )
                self.assertAlmostEqual(
                    reflectron["energy_max_V"], coupled["energy_max_v"]
                )
                self.assertFalse(compilation["simion_rebuild_plan"]["reflectron_pa"])
                self.assertEqual(
                    compilation["reflectron_voltage_application"],
                    {
                        "pa0_basis_reused": True,
                        "method": "official_simion_runtime_fast_adjust_v1",
                        "voltage_authority": "electrodes_V",
                        "runtime_call": "r:fast_adjust(reflectron_voltages)",
                    },
                )
                bound = bind_oatof_adjustables(formal, resolved)
                self.assertIn("r:fast_adjust(reflectron_voltages)", bound)
                for name, expected in {"V_mid": midgrid, "V_backplate": backplate}.items():
                    match = re.search(rf"(?m)^adjustable {name}=([^\r\n]+)$", bound)
                    self.assertIsNotNone(match)
                    self.assertAlmostEqual(float(match.group(1)), expected)

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
        resolved, derived_port, _ = compile_geometry_and_port(geometry, port, profile)
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
        self.assertEqual(
            derived_port["mating_surface"]["center_mm"][2],
            resolved["particle_source"]["center_z_mm"],
        )


if __name__ == "__main__":
    unittest.main()
