from __future__ import annotations

import copy
import hashlib
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
            "symmetric_10ev_source_z22_finite_interval_theory": "0825D932E7A638C02A959DC6B49A0498ED16377A22D3561F2B1E0DDC5673A0AB",
            "theory_source_z10_d1_3": "7978E3EE42BB2FA41E12708EF572CF2BA8E94410DBF4D8D57CF1C98E165BA31E",
            "zero_match_short_1mm": "98FC3BBADAEF841CFAFE91151169BFBA32A099F2099B3238329472CE3E6DADCD",
            "theory_source_z10_d1_4": "9BAFEE370330033809FAC3B997AC7C077545DF633E5D2B38C4744EC95FCDAE42",
            "theory_source_z10_d1_5": "93F85D1606E164D39346829B069FE2704CD375CE8451D95D403677041A0CEF43",
            "theory_source_z22_d1_3": "428728EB8B27376396E2C600E18D47B810CFADAFAEB06C293C52AA47DE7F8A7E",
            "zero_match_long_2p2mm": "AE1E74FC6662BD0BA6F74A153EEF12D84F1437EAC57B092E55AA5D81F698C6A0",
            "theory_source_z22_d1_4": "92B7FB6783927050983EFBF7E09BA2354AFB46796802BAABF668285000195F5C",
            "theory_source_z22_d1_5": "68245FB7295F078466B4EE24856F08DF5466EFB0B47088C92469BAF505D0BE07",
        }
        expected = {
            "symmetric_10ev_source_z22_finite_interval_theory": "DB29B9ED6761C43201FA0421A09FA155300C187D7E331418368889B62C5D52FB",
            "theory_source_z10_d1_3": "8C0677E1514D47CF0D5FACED59AAC1359172975CF0B1C1B8A486DE3A3D705FE3",
            "zero_match_short_1mm": "9681025140FF5626D845974095A1E119A917F92016CB77307C270CAD7154023F",
            "theory_source_z10_d1_4": "D2E81D81F03E98AA3F144A5D7C4C89F7C4F88E98168E5B145F5DEB0CD78A2326",
            "theory_source_z10_d1_5": "7C51489461ACE3B54F84E8536390A3B968C8B4157C6ED82F6FFB29D7A35F58EB",
            "theory_source_z22_d1_3": "17547A56CA37C29643DEE14E5A9FC24A1B9CA0ED2C42BC2A6A527A04100E337F",
            "zero_match_long_2p2mm": "C826AA4DA9A4C0A18374B96CC9CFF622004904B98263A0F9F0ACA954158CF31F",
            "theory_source_z22_d1_4": "B86135CB7A471D2443AE1F663E2192D02F82324B44B61626DBE71460B9B55528",
            "theory_source_z22_d1_5": "064C32DA6566051F0A4C7475447D1050A47636108B0DEFC305E444DBFA5910D8",
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
