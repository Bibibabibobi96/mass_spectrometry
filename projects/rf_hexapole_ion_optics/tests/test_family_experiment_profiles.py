from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema
from common.multipole.design_profile import resolve_design_profile
from common.multipole.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
    "exit_aperture_plate_acceleration",
)


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class FamilyExperimentProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolved = {
            mode_id: resolve_design_profile(
                REPO_ROOT, "rf_hexapole_ion_optics", mode_id
            )["resolved_design"]
            for mode_id in MODE_IDS
        }

    def assert_contract_values(
        self, contract: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        for dotted_path, expected_value in expected.items():
            actual: Any = contract
            for key in dotted_path.split("."):
                actual = actual[key]
            self.assertEqual(actual, expected_value, dotted_path)

    def test_profiles_share_one_governed_base_catalog_and_envelope(self) -> None:
        registry = load("config/design_profiles.json")
        validate_schema(registry, "design_profiles.schema.json")
        current = [
            profile
            for profile in registry["profiles"]
            if profile["design_profile_id"] in MODE_IDS
        ]
        self.assertEqual({profile["mode_id"] for profile in current}, set(MODE_IDS))
        for key in ("design_request", "design_variables", "optimization_envelope"):
            self.assertEqual({profile[key] for profile in current}, {
                {
                    "design_request": "config/requests/mechanical_base.json",
                    "design_variables": "config/design_variables.json",
                    "optimization_envelope": "config/optimization_envelope.json",
                }[key]
            })
            self.assertEqual(len({profile["sha256"][key] for profile in current}), 1)
        aliases = {
            profile["design_profile_id"]: profile["mode_id"]
            for profile in registry["profiles"]
            if profile["design_profile_id"] not in MODE_IDS
        }
        self.assertEqual(
            aliases,
            {
                "baseline_finite_3d": "segmented_rod_axial_acceleration",
                "exit_aperture_plate_acceleration_reference": (
                    "exit_aperture_plate_acceleration"
                ),
            },
        )

    def test_profile_source_hashes_use_repository_lf_bytes(self) -> None:
        registry = load("config/design_profiles.json")
        current = [
            profile
            for profile in registry["profiles"]
            if profile["design_profile_id"] in MODE_IDS
        ]
        for field in ("design_request", "design_variables", "optimization_envelope"):
            for profile in current:
                path = PROJECT_ROOT / profile[field]
                content = path.read_bytes()
                self.assertNotIn(b"\r", content, profile[field])
                self.assertEqual(
                    hashlib.sha256(content).hexdigest().upper(),
                    profile["sha256"][field],
                )

    def test_three_modes_have_exactly_one_mechanical_geometry(self) -> None:
        baseline = self.resolved[MODE_IDS[0]]
        for resolved in self.resolved.values():
            self.assertEqual(resolved["geometry_mm"], baseline["geometry_mm"])
            self.assertEqual(resolved["interfaces_mm"], baseline["interfaces_mm"])
            physical_segments = [
                {
                    key: value
                    for key, value in electrode.items()
                    if key != "common_mode_V"
                }
                for electrode in resolved["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            baseline_segments = [
                {
                    key: value
                    for key, value in electrode.items()
                    if key != "common_mode_V"
                }
                for electrode in baseline["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            self.assertEqual(physical_segments, baseline_segments)
        self.assertEqual(
            (baseline["geometry_mm"]["rod_z_min"], baseline["geometry_mm"]["rod_z_max"]),
            (0.0, 79.6),
        )
        segments = baseline["segmentation"]["axial_acceleration"]["derived"]["segments"]
        self.assertEqual(len(segments), 4)
        for segment in segments:
            self.assertAlmostEqual(segment["z_max_mm"] - segment["z_min_mm"], 19.6)
        self.assertEqual(
            baseline["interfaces_mm"],
            {
                "entrance": {
                    "aperture_radius_mm": 3.6,
                    "aperture_plate_upstream_face_z_mm": -1.0,
                    "aperture_plate_downstream_face_z_mm": -0.5,
                    "connector_length_mm": 0.0,
                    "connector_upstream_face_z_mm": -1.0,
                    "connector_downstream_face_z_mm": -1.0,
                    "release_plane_z_mm": -1.5,
                    "connector_shape": "cylindrical_bore",
                },
                "exit": {
                    "aperture_radius_mm": 3.6,
                    "aperture_plate_upstream_face_z_mm": 80.1,
                    "aperture_plate_downstream_face_z_mm": 80.6,
                    "aperture_crossing_plane_z_mm": 80.6,
                    "connector_length_mm": 0.0,
                    "connector_upstream_face_z_mm": 80.6,
                    "connector_downstream_face_z_mm": 80.6,
                    "handoff_plane_z_mm": 80.6,
                    "census_plane_z_mm": 81.1,
                    "connector_shape": "cylindrical_bore",
                },
            },
        )

    def test_modes_differ_only_by_registered_electrical_assignments(self) -> None:
        expected = {
            "no_acceleration_full_length": ([0.0, 0.0, 0.0, 0.0], 0.0),
            "segmented_rod_axial_acceleration": ([0.0, -1.0, -2.0, -3.0], -3.0),
            "exit_aperture_plate_acceleration": ([0.0, 0.0, 0.0, 0.0], -3.0),
        }
        for mode_id, resolved in self.resolved.items():
            segment_voltages = [
                segment["common_mode_V"]
                for segment in resolved["segmentation"]["axial_acceleration"][
                    "derived"
                ]["segments"]
            ]
            exit_voltage = resolved["static_electrodes_V"][
                "exit_outer_endcap_aperture_plate_connector_V"
            ]
            self.assertEqual((segment_voltages, exit_voltage), expected[mode_id])

    def test_runtime_tiers_change_only_the_registered_numerical_axis(self) -> None:
        for mode_id in MODE_IDS:
            baseline = resolve_runtime_profile(
                REPO_ROOT, "rf_hexapole_ion_optics", mode_id
            )
            spatial = resolve_runtime_profile(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                f"{mode_id}_n100_spatial_refined",
            )
            temporal = resolve_runtime_profile(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                f"{mode_id}_n100_temporal_refined",
            )
            statistical = resolve_runtime_profile(
                REPO_ROOT, "rf_hexapole_ion_optics", f"{mode_id}_n1000"
            )
            self.assertEqual(
                {
                    baseline["design_profile_id"],
                    spatial["design_profile_id"],
                    temporal["design_profile_id"],
                    statistical["design_profile_id"],
                },
                {mode_id},
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                spatial["particle_source"]["sha256"],
            )
            self.assertEqual(
                baseline["particle_source"]["profile_id"],
                "family_mother_sample_v1_n100",
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                temporal["particle_source"]["sha256"],
            )
            self.assertEqual(
                temporal["solver_numerics"]["comsol"]["values"]["mesh"][
                    "working_region_maximum_element_size_mm"
                ],
                0.35,
            )
            self.assertEqual(
                temporal["solver_numerics"]["comsol"]["values"]["trajectory"][
                    "rf_steps_per_period"
                ],
                160,
            )
            self.assertEqual(
                temporal["solver_numerics"]["simion"]["values"]["cell_mm"],
                0.3,
            )
            self.assertEqual(
                temporal["solver_numerics"]["simion"]["values"]["trajectory"][
                    "rf_steps_per_period"
                ],
                80,
            )
            self.assertEqual(
                statistical["particle_source"]["sha256"],
                "CE68A6B47DC5726D9C45CBE28E4397A2321D782FAED265067824891AAF4D0FBF",
            )
            self.assertEqual(
                statistical["particle_source"]["profile_id"],
                "family_mother_sample_v1_n1000",
            )
        for alias in (
            "baseline_finite_3d",
            "exit_aperture_plate_acceleration_reference",
        ):
            resolved_alias = resolve_runtime_profile(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                alias,
            )
            self.assertEqual(
                resolved_alias["particle_source"]["profile_id"],
                "family_mother_sample_v1_n100",
            )

    def test_preregistration_refuses_unsourced_numerical_thresholds(self) -> None:
        convergence = load("config/qualification/n100_convergence_preregistration.json")
        for solver_id, spatial_key in (
            ("comsol", "working_region_maximum_element_size_mm"),
            ("simion", "cell_mm"),
        ):
            plan = convergence["solver_plans"][solver_id]
            self.assertEqual(
                plan["active_registry_sha256"],
                sha256(REPO_ROOT / plan["registry"]),
            )
            self.assertRegex(plan["registry_sha256_at_preregistration"], r"^[A-F0-9]{64}$")
            self.assertEqual(
                plan["tiers"]["temporal_refined"][spatial_key],
                plan["tiers"]["spatial_refined"][spatial_key],
            )
        self.assertFalse(convergence["decision_policy"]["qualification_pass_allowed"])
        self.assertEqual(
            convergence["decision_policy"]["continuous_result"], "INCONCLUSIVE"
        )
        for name, role, content in (
            (
                "dispersion_acceptance.json",
                "multipole_dispersion_acceptance_contract",
                "acceptance_criteria",
            ),
            (
                "dispersion_effect_resolution.json",
                "multipole_dispersion_effect_resolution_contract",
                "effect_resolution",
            ),
            (
                "engineering_budget.json",
                "multipole_engineering_budget_contract",
                "pilot_authorization",
            ),
        ):
            contract = load(f"config/qualification/{name}")
            self.assertEqual(contract["role"], role)
            self.assertTrue(contract["preregistered_before_run"])
            self.assertTrue(contract[content])
        engineering = load("config/qualification/engineering_budget.json")
        self.assertFalse(engineering["pilot_authorization"]["authorized"])
        self.assertEqual(
            engineering["pilot_authorization"]["scope"]["runtime_profile_id"],
            "exit_aperture_plate_acceleration_n100_hybrid_d3_axial14_cg_amg_field_screen",
        )
        self.assertEqual(
            engineering["pilot_authorization"]["scope"]["allowed_solvers"],
            ["comsol"],
        )
        self.assertEqual(
            engineering["pilot_authorization"]["limits"]["maximum_mesh_cells"],
            1000000,
        )
        self.assertFalse(engineering["full_matrix_authorization"]["authorized"])
        self.assertEqual(
            engineering["full_matrix_authorization"]["reason"],
            "d3_axial14_arm_completed_and_no_further_mesh_or_particle_matrix_is_authorized",
        )

        result = load(
            "config/qualification/n100_no_acceleration_qualification.json"
        )
        self.assertEqual(result["functional_transport"]["status"], "PASS")
        self.assertEqual(
            result["continuous_diagnostics"]["status"],
            "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET",
        )
        self.assertEqual(
            result["decision"]["further_brute_force_refinement"],
            "NOT_AUTHORIZED",
        )
        acceleration = load(
            "config/qualification/n100_segmented_rod_axial_acceleration_qualification.json"
        )
        self.assertEqual(
            acceleration["baseline_functional_transport"]["status"],
            "PASS",
        )
        self.assertEqual(
            acceleration["same_solver_spatial"]["comsol"]["status"],
            "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED",
        )
        exit_plate = load(
            "config/qualification/n100_exit_aperture_plate_acceleration_qualification.json"
        )
        self.assertEqual(
            exit_plate["baseline_functional_transport"]["status"],
            "PASS",
        )
        self.assertEqual(
            exit_plate["same_solver_spatial"]["simion"]["functional_status"],
            "PASS",
        )
        self.assertEqual(
            exit_plate["same_solver_spatial"]["comsol"]["status"],
            "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED",
        )

    def test_hybrid_mesh_campaign_freezes_four_sequential_mumps_axes(self) -> None:
        campaign = load(
            "docs/history/20260729__closed-hybrid-mesh-campaigns/"
            "comsol_hybrid_mesh_pilot_preregistration.json"
        )
        self.assert_contract_values(
            campaign,
            {
                "preregistered_before_run": True, "maximum_commercial_run_count": 4,
                "commercial_run_count_currently_authorized": 0, "implementation_blockers.commercial_authorization": False,
                "status": "closed_after_p1_topology_failure", "execution_result.terminal": True,
                "execution_result.status": "FAILED_TOPOLOGY_GATE_BEFORE_FIELD_SOLUTION",
                "execution_result.resource_limit_triggered": False, "execution_result.later_pilots_executed": False,
                "scope.stationary_linear_solver_backend": "mumps",
            },
        )
        runtime_profiles = load("config/runtime_profiles.json")["profiles"]
        for pilot in campaign["ordered_pilots"]:
            self.assertNotIn(pilot["runtime_profile_id"], runtime_profiles)

        for name, authority in campaign["frozen_authorities"].items():
            if name == "engineering_budget":
                self.assertEqual(
                    authority["sha256"],
                    campaign["execution_result"]["frozen_engineering_budget_sha256"],
                )
                continue
            path = REPO_ROOT / authority["path"]
            self.assertTrue(path.is_file(), authority["path"])
            self.assertRegex(authority["sha256"], r"^[A-F0-9]{64}$")

        expected = (
            ("hybrid_p1_coarse", "mesh_strategy_feasibility_against_existing_full_tetra_baseline", 0.5, 10, 0.5),
            ("hybrid_p2_radial_refined", "radial_core_and_rod_hmax_only", 0.35, 10, 0.5),
            ("hybrid_p3_axial_refined", "axial_layers_per_swept_segment_only", 0.35, 20, 0.5),
            ("hybrid_p4_transition_end_refined", "transition_and_end_tetra_hmax_only", 0.35, 20, 0.35),
        )
        pilots = campaign["ordered_pilots"]
        self.assertEqual(len(pilots), 4)
        numerics_registry = load("config/comsol_solver_numerics.json")["profiles"]
        for index, (pilot, frozen) in enumerate(zip(pilots, expected), start=1):
            profile_id, changed_axis, radial, layers, tetra = frozen
            self.assert_contract_values(pilot, {
                "sequence": index, "comsol_solver_numerics_profile_id": profile_id,
                "changed_axis_from_previous": changed_axis, "radial_core_and_rod_hmax_mm": radial,
                "axial_layers_per_swept_segment": layers, "transition_and_end_tetra_hmax_mm": tetra,
            })
            self.assertNotIn(profile_id, numerics_registry)

        topology = campaign["hybrid_topology"]
        self.assert_contract_values(
            topology,
            {
                "physical_segment_count": 4, "physical_segment_length_mm": 19.6,
                "segment_end_buffer_mm_each_end": 1.0, "central_swept_length_per_segment_mm": 17.6,
                "core_radius_mm": 8.0, "outer_vacuum_hmax_mm": 1.0, "minimum_element_size_mm": 0.02,
            },
        )
        self.assert_contract_values(campaign["sequential_stop_policy"], {
            "branching_or_reordering_allowed": False,
            "additional_commercial_run_after_P4_allowed": False,
        })
        future_solvers = set(campaign["implementation_blockers"]["future_solver_campaigns"])
        self.assertTrue({"pardiso", "cg_amg"} <= future_solvers)

    def test_d1_mesh_build_is_bounded_and_d2_is_only_conditional(self) -> None:
        diagnostic = load(
            "docs/history/20260729__closed-hybrid-mesh-campaigns/"
            "comsol_hybrid_mesh_build_diagnostic_preregistration.json"
        )
        self.assert_contract_values(
            diagnostic,
            {
                "preregistered_before_run": True, "status": "closed_after_d1_diagnostic_implementation_failure",
                "d1.authorized": False, "d2.authorized": False, "scope.stop_stage": "mesh_build",
                "d1.hybrid_mesh.core_radius_mm": 8.5, "d1.hybrid_mesh.radial_core_and_rod_hmax_mm": 0.5,
                "execution_result.terminal": True,
                "execution_result.status": "INCONCLUSIVE_DIAGNOSTIC_IMPLEMENTATION_FAILURE",
                "execution_result.run_id": "20260729_155030__build__comsol__hex-hybrid-d1-mesh-build__r01",
                "execution_result.commercial_run_count": 1, "execution_result.automatic_retry_count": 0,
                "execution_result.retry_budget_exhausted": True, "execution_result.retry_authorized": False,
                "execution_result.mesh_run_reached": False, "execution_result.mesh_evidence_available": False,
                "execution_result.topology_evidence_available": False, "execution_result.resource_limit_triggered": False,
                "execution_result.observed_prebuild_diagnostics.vacuum_selection_entity_count": 31,
                "execution_result.observed_prebuild_diagnostics.vacuum_volume_evidence_status": "UNKNOWN",
                "legacy_p1_campaign.p1_retry_authorized": False, "legacy_p1_campaign.p2_p3_p4_authorized": False,
            },
        )
        self.assertEqual(
            diagnostic["d1"]["resource_limits"],
            {
                "wall_clock_seconds": 300,
                "transient_run_directory_bytes": 128 * 1024**2,
                "process_tree_working_set_bytes": 6 * 1024**3,
                "minimum_system_available_memory_bytes": 8 * 1024**3,
                "compact_final_retained_bytes": 10 * 1024**2,
                "automatic_retry_count": 0,
            },
        )
        resolved = self.resolved["exit_aperture_plate_acceleration"]
        rod_tangent_radius = resolved["geometry_mm"]["rod_center_radius"] + resolved["geometry_mm"]["rod_radius"]
        self.assertGreater(diagnostic["d1"]["hybrid_mesh"]["core_radius_mm"], rod_tangent_radius)
        wrapper = (PROJECT_ROOT / "analysis/run_finite_3d_transport.ps1").read_text(encoding="utf-8-sig")
        launcher_support = (REPO_ROOT / "common/multipole/project_transport_launcher_support.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn(diagnostic["scope"]["runtime_profile_id"], wrapper)
        self.assertIn("Invoke-MultipoleProjectFinite3dTransport", wrapper)
        for token in ("$arguments.StopStage = $stopStage", "profile_id"):
            self.assertIn(token, launcher_support)

        solver = (REPO_ROOT / "common/multipole/solve_finite_3d_transport.m").read_text(encoding="utf-8")
        mesh_helper = (REPO_ROOT / "common/multipole/configure_comsol_segment_hybrid_mesh.m").read_text(encoding="utf-8")
        runner = (REPO_ROOT / "common/multipole/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        for before, after in (
            ("emit_mesh_prebuild_diagnostics", "mesh.run;"),
            ("if meshBuildOnly", "model.material.create('mat_vac'"),
            ("return\n    end\n    material =", "comp.physics.create('es'"),
        ):
            self.assertLess(solver.index(before), solver.index(after))
        for token in (
            "FIELD_PHYSICS_CREATED=%d", "FIELD_STUDIES_CREATED=%d", "FIELD_SOLUTIONS_CREATED=%d",
            "PARTICLE_PHYSICS_CREATED=%d", "PARTICLE_STUDIES_CREATED=%d",
            "physicsTags = cell(comp.physics.tags())", "studyTags = cell(model.study.tags())",
            "solutionTags = cell(model.sol.tags())", "a tangent core partition is forbidden",
            "diagnostics.swept = cell(", "diagnostics.swept{index}",
            "'domain', 'selection', entities", "%s_VOLUME_MM3=UNKNOWN",
        ):
            self.assertIn(token, solver)
        self.assertNotIn("diagnostics.swept(index) =", solver)
        self.assertNotIn("'volume', 'selection', entities", solver)
        self.assertIn("add_size(sweep, sprintf('szRod%d'", mesh_helper)
        self.assertIn("add_size(tetrahedra, 'szTetRod'", mesh_helper)
        self.assertNotIn("add_size(mesh, 'szRodBnd'", mesh_helper)
        self.assertIn("Assert-MultipoleMeshBuildReport -Path $report", runner)
        for token in diagnostic["d1"]["required_report_tokens"]:
            self.assertIn(token.split("=", 1)[0], runner)


if __name__ == "__main__":
    unittest.main()
