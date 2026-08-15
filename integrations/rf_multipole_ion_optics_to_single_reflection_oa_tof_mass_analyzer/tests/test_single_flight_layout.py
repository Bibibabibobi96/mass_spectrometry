from __future__ import annotations

import copy
import hashlib
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
    def test_finite_interval_design_is_owned_by_the_oatof_project_api(self) -> None:
        source = (
            INTEGRATION / "runtime/single_flight_layout.py"
        ).read_text(encoding="utf-8")
        self.assertIn("compile_finite_interval_oatof_design", source)
        for forbidden in (
            "match_finite_phase_space_interval",
            "linear_phase_space_timing_coefficients",
            "solve_coupled_reflectron_from_accelerator_derivatives",
            'geometry["electrodes_V"]["midgrid"] =',
            'geometry["electrodes_V"]["backplate"] =',
        ):
            self.assertNotIn(forbidden, source)

    def test_finite_interval_profiles_preserve_canonical_resolved_semantics(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        legacy_expected = {
            "symmetric_10ev_source_z22_finite_interval_theory": "80148707BFFE1B95894875C3D451B7986449834447A1917E3682EB96B5FFC60A",
            "theory_source_z10_d1_3": "6298FD5B4416525DE9FEFA4DAD7EE945C9AB92EAE2BA7986C595B08E5BF60950",
            "zero_match_short_1mm": "E60C6123BE4BE357D9A68C0E64AC9B76AFF2D1EE9362D7E1B0CC8189F9D6DBAF",
            "theory_source_z10_d1_4": "9B6A65E37A16B73F2A464420DDB7440A255E2D9E6F12D9DF190553E52C7614A1",
            "theory_source_z10_d1_5": "047A42EBD953797975B8AFCEA7307493F911EC817AD7343F36A9BAE61AA6F0E6",
            "theory_source_z22_d1_3": "C396756DD9E9DC00A8EF1952E2B19472066173C03A503F83D49E3B5F3BC55197",
            "zero_match_long_2p2mm": "1D19DE8B8E15975ACC0CFC8F1BA17B42DAB76234C5E3BEB8B11CA58576DDC2D7",
            "theory_source_z22_d1_4": "75B80C7F5E635DC02995103B9F42681BA075331BBBF7243E74D30840EA96CC0F",
            "theory_source_z22_d1_5": "BCA3C09E03F269F67C91D693893C61FDF4E61AC29B859895C6B22547EAE16A75",
        }
        expected = {
            "symmetric_10ev_source_z22_finite_interval_theory": "A28EE7342A0D697E79D068DFD702996E5717281F9CA0BA7B4683C1DAE297D507",
            "theory_source_z10_d1_3": "7BC4E7A90FF7323E84C32D16E1B17D0B66C1BA5E8D6AAF7D9EB75F0D506FEC3F",
            "zero_match_short_1mm": "A324FD33AA5202F0BFF96326EEC2A999BA0C1ABFE7628F16EAC2B3AC984FE99D",
            "theory_source_z10_d1_4": "7FF2732CFD3FB0DCC7FD6E47D6BDDB9AC57ABDA23919FAA413F0CA5B04FD83DB",
            "theory_source_z10_d1_5": "C9E60784EC922EEBCA2656DBC182BF3842444E98F46F6F2373F2819CD3D36A55",
            "theory_source_z22_d1_3": "00701AC584D9472888F3F2F3D25F53568EDEDDF83509D34BC2136926CB45EB22",
            "zero_match_long_2p2mm": "784A21637414D0B309FB72312E15B1749AFABA979AD03938B7A5A2B151B973AA",
            "theory_source_z22_d1_4": "E1D4DCD98D581B2662F932DD252063F324C4A77BB18B2BC33CA50875A9EAE8EB",
            "theory_source_z22_d1_5": "9A6D743007798431BAA2B8E87C8DB518E12A4E295DEB3B65CC26303B4D641F4E",
        }
        for profile_id, expected_sha in expected.items():
            with self.subTest(profile_id=profile_id):
                compiled = compile_geometry_and_port(
                    geometry, port, select_profile(registry, profile_id)
                )
                canonical = json.dumps(
                    compiled, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
                self.assertEqual(hashlib.sha256(canonical).hexdigest().upper(), expected_sha)
                legacy_equivalent = copy.deepcopy(compiled)
                resolved = legacy_equivalent[0]
                provenance = resolved["single_flight_layout_derivation"].pop(
                    "finite_interval_input_provenance"
                )
                theory = resolved["geometry_derivation"]["accelerator"][
                    "finite_interval_theory"
                ]
                theory["profile_path"] = provenance["profile_path"]
                theory["solver_phase_space_input"] = provenance["phase_space_input"]
                legacy_canonical = json.dumps(
                    legacy_equivalent,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
                self.assertEqual(
                    hashlib.sha256(legacy_canonical).hexdigest().upper(),
                    legacy_expected[profile_id],
                )

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
