from __future__ import annotations

import copy
import hashlib
import json
import math
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    select_profile,
)


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


class SingleFlightLayoutTests(unittest.TestCase):
    @staticmethod
    def _three_zone_candidate() -> dict[str, object]:
        return {
            "role": "oatof_three_zone_simion_candidate_resolved",
            "qualification": "CANDIDATE_ONLY",
            "compiler_mode": "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
            "campaign": {"campaign_id": "three_zone_solver_free_funnel_v1"},
            "t5_evidence": {"plan_sha256": "A" * 64},
            "source_identity": {
                "frozen_source": {
                    "center_x_mm": 1.5,
                    "nominal_energy_per_charge_v": 2000.0,
                }
            },
            "identities": {
                "topology_id": "three_zone_accelerator_ideal_v1",
                "geometry_id": "three_zone_focus_origin_planes_v1",
                "field_id": "three_zone_piecewise_uniform_ideal_field_v1",
            },
            "accelerator_topology": {
                "topology_id": "three_zone_accelerator_ideal_v1",
                "planes_global_z_mm": {
                    "repeller": -25.0,
                    "intermediate1": -20.0,
                    "intermediate2": -10.0,
                    "exit": -5.0,
                },
                "potentials_v": {
                    "repeller": 2000.0,
                    "intermediate1": 1500.0,
                    "intermediate2": 500.0,
                    "exit": 0.0,
                },
            },
            "accelerator_physics": {
                "lengths_mm": {"d1": 5.0, "d2": 10.0, "d3": 5.0},
                "focus_drift_after_exit_mm": 5.0,
            },
            "reflectron": {
                "u_r1_v": 1600.0,
                "f_r2_v_per_mm": 10.0,
            },
        }

    def test_t5_three_zone_profile_maps_exact_topology_and_legacy_surface(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (
                REPO
                / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
            ).read_text()
        )
        port = json.loads(
            (
                REPO
                / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json"
            ).read_text()
        )
        profile = select_profile(registry, "three_zone_t5_primary_v1")
        candidate = self._three_zone_candidate()
        binding = {"path": "candidate.json", "sha256": "B" * 64}
        resolved, _, _ = compile_geometry_and_port(
            geometry,
            port,
            profile,
            three_zone_candidate=candidate,
            three_zone_candidate_binding=binding,
        )
        self.assertEqual(
            resolved["accelerator_topology"],
            candidate["accelerator_topology"],
        )
        self.assertEqual(resolved["geometry_mm"]["accelerator_grid1_z"], -20.0)
        self.assertEqual(resolved["geometry_mm"]["accelerator_grid2_z"], -5.0)
        accelerator = resolved["geometry_derivation"]["accelerator"]
        self.assertEqual(accelerator["d1_mm"], 5.0)
        self.assertEqual(accelerator["d2_mm"], 15.0)
        self.assertEqual(accelerator["canonical_intermediate2_z_mm"], -10.0)
        self.assertEqual(resolved["particle_source"]["center_z_mm"], -23.5)
        self.assertEqual(resolved["particle_source"]["size_z_mm"], 2.2)
        self.assertEqual(resolved["geometry_mm"]["L_flight"], 600.0)
        self.assertEqual(resolved["electrodes_V"]["midgrid"], 1600.0)
        self.assertAlmostEqual(
            resolved["electrodes_V"]["backplate"],
            1600.0 + 10.0 * resolved["geometry_mm"]["L_stage2"],
        )
        compilation = resolved["single_flight_layout_derivation"][
            "design_compilation"
        ]
        self.assertEqual(compilation["candidate"], binding)
        self.assertEqual(
            compilation["simion_rebuild_plan"],
            {
                "frontend_pa": True,
                "flight_tube_pa": True,
                "reflectron_pa": False,
            },
        )

    def test_t5_three_zone_profile_requires_bound_candidate(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        geometry = json.loads(
            (
                REPO
                / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
            ).read_text()
        )
        port = json.loads(
            (
                REPO
                / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json"
            ).read_text()
        )
        with self.assertRaisesRegex(
            ContractError, "requires a hash-bound Candidate"
        ):
            compile_geometry_and_port(
                geometry,
                port,
                select_profile(registry, "three_zone_t5_primary_v1"),
            )

    def test_three_zone_shaping_ring_successor_derives_exact_one_plus_four_centers(self) -> None:
        registry = json.loads(
            (INTEGRATION / "config/single_flight_layout_profiles.json").read_text()
        )
        old_profile = select_profile(registry, "three_zone_t5_primary_v1")
        old_bytes = json.dumps(
            old_profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(
            hashlib.sha256(old_bytes).hexdigest().upper(),
            "06D1BFAF5A89DEC4D44CDB72E6DF27A793444B6C0A236FF85ABA9813BD9FEDE7",
        )
        geometry = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        port = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json").read_text()
        )
        candidate = self._three_zone_candidate()
        candidate["accelerator_topology"]["planes_global_z_mm"].update(
            {"repeller": -23.25, "intermediate1": -20.0,
             "intermediate2": -14.9, "exit": -3.0}
        )
        candidate["accelerator_physics"] = {
            "lengths_mm": {"d1": 3.25, "d2": 5.1, "d3": 11.9},
            "focus_drift_after_exit_mm": 3.0,
        }
        profile = select_profile(
            registry, "three_zone_t5_primary_shaping_rings_1p4_v1"
        )
        resolved, _, _ = compile_geometry_and_port(
            geometry, port, profile, three_zone_candidate=candidate,
            three_zone_candidate_binding={"path": "candidate.json", "sha256": "B" * 64},
        )
        placement = resolved["rings"]["accelerator_placement"]
        self.assertEqual(placement["zone_ring_counts"], {"zone2": 1, "zone3": 4})
        self.assertEqual(
            placement["ring_z_mm"],
            [-20.0 + 2.55, *[-14.9 + index * 2.38 for index in range(1, 5)]],
        )
        self.assertAlmostEqual(
            placement["minimum_observed_grid_to_ring_edge_clearance_mm"], 1.88
        )

        invalid = copy.deepcopy(profile)
        invalid["accelerator_ring_placement_policy"]["zone2_ring_count"] = 2
        with self.assertRaisesRegex(ContractError, "placement policy is invalid"):
            select_profile({**registry, "profiles": [invalid]}, invalid["layout_profile_id"])
        invalid = copy.deepcopy(profile)
        invalid["accelerator_ring_placement_policy"][
            "minimum_grid_to_ring_edge_clearance_mm"
        ] = 2.1
        with self.assertRaisesRegex(ContractError, "clearance is below policy"):
            compile_geometry_and_port(
                geometry, port, invalid, three_zone_candidate=candidate,
                three_zone_candidate_binding={"path": "candidate.json", "sha256": "B" * 64},
            )

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
        profiles = [
            select_profile(registry, item["layout_profile_id"])
            for item in registry["profiles"]
            if item.get("finite_interval_accelerator_profile")
        ]
        self.assertGreaterEqual(len(profiles), 1)
        for profile in profiles:
            with self.subTest(profile_id=profile["layout_profile_id"]):
                resolved, derived_port, values = compile_geometry_and_port(
                    geometry, port, profile
                )
                repeated = compile_geometry_and_port(geometry, port, profile)
                self.assertEqual((resolved, derived_port, values), repeated)

                provenance = resolved["single_flight_layout_derivation"][
                    "finite_interval_input_provenance"
                ]
                authority = json.loads(
                    (INTEGRATION / provenance["profile_path"]).read_text()
                )
                expected_phase_space = profile.get(
                    "finite_interval_phase_space_input",
                    authority["frozen_phase_space_input"],
                )
                self.assertEqual(provenance["phase_space_input"], expected_phase_space)

                accelerator = resolved["geometry_derivation"]["accelerator"]
                theory = accelerator["finite_interval_theory"]
                expected_width = float(
                    profile.get(
                        "finite_interval_source_full_width_mm",
                        authority["finite_interval_design"]["source_full_width_mm"],
                    )
                )
                expected_d1 = float(
                    profile.get(
                        "accelerator_stage1_length_mm",
                        accelerator["reference_d1_mm"],
                    )
                )
                self.assertEqual(resolved["particle_source"]["size_z_mm"], expected_width)
                self.assertEqual(accelerator["d1_mm"], expected_d1)
                self.assertEqual(theory["source_full_width_mm"], expected_width)
                self.assertEqual(theory["solver_phase_space_input"], {
                    key: expected_phase_space[key]
                    for key in (
                        "mass_to_charge_Th", "release_position_mm",
                        "mean_initial_velocity_m_per_s",
                        "velocity_slope_m_per_s_per_mm",
                    )
                })
                self.assertAlmostEqual(
                    resolved["particle_source"]["center_z_mm"],
                    theory["canonical_repeller_z_mm"] + theory["source_center_mm"],
                )
                self.assertAlmostEqual(
                    resolved["electrodes_V"]["repeller"], theory["repeller_v"]
                )
                self.assertAlmostEqual(
                    resolved["electrodes_V"]["grid1"], theory["intermediate_v"]
                )
                coupled = theory["coupled_reflectron"]
                self.assertGreater(coupled["stage1_voltage_drop_v"], 0.0)
                self.assertGreater(coupled["stage2_field_v_per_mm"], 0.0)
                self.assertLess(abs(coupled["total_first_derivative_residual"]), 1e-12)
                self.assertLess(abs(coupled["total_second_derivative_residual"]), 1e-12)
                self.assertEqual(
                    values["accelerator_axis_x_mm"],
                    resolved["coordinate_convention"]["accelerator_axis_x"],
                )
                self.assertEqual(
                    derived_port["mating_surface"]["center_mm"][0],
                    values["entry_port_x_mm"],
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
