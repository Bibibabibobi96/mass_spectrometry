from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    compile_design_request,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUEST_PATH = PROJECT_ROOT / "config" / "requests" / "mechanical_base.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pointer_value(document: dict, pointer: str):
    value = document
    for token in pointer.lstrip("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


class Phase2DesignConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.request = load(REQUEST_PATH)
        cls.catalog = load(PROJECT_ROOT / "config" / "design_variables.json")
        cls.envelope = load(PROJECT_ROOT / "config" / "optimization_envelope.json")
        cls.baseline = load(PROJECT_ROOT / "config" / "baseline.json")
        cls.finite = load(PROJECT_ROOT / "config" / "finite_3d_transport.json")
        cls.screen = load(PROJECT_ROOT / "config" / "round_rod_field_screen.json")
        cls.comsol_numerics = load(
            PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
        )
        cls.runtime_profiles = load(
            PROJECT_ROOT / "config" / "runtime_profiles.json"
        )
        cls.identity = {
            "project_id": "rf_hexapole_ion_optics",
            "family_id": "rf_multipole_ion_optics",
            "radial_order_n": 3,
            "electrode_count": 6,
        }

    def test_contracts_are_schema_valid_and_identity_is_locked(self) -> None:
        validate_schema(self.request, "multipole_design_request.schema.json")
        validate_schema(self.catalog, "design_variable_catalog.schema.json")
        validate_schema(self.envelope, "optimization_envelope.schema.json")
        self.assertEqual(self.request["identity"], self.identity)
        changed = copy.deepcopy(self.request)
        changed["identity"]["electrode_count"] = 8
        with self.assertRaisesRegex(MultipoleDesignCompileError, "identity"):
            compile_design_request(changed, expected_identity=self.identity)

    def test_request_compiles_to_current_rods_interfaces_drive_and_segmentation(self) -> None:
        compiled = compile_design_request(self.request, expected_identity=self.identity)
        geometry = self.request["geometry_mm"]
        self.assertEqual(len(compiled["geometry_mm"]["rod_array"]["rods"]), 6)
        self.assertEqual(geometry["inscribed_radius_r0"], self.baseline["geometry_mm"]["inscribed_radius_r0"])
        self.assertEqual(geometry["rod_radius_ratio"], 0.5)
        self.assertIn(geometry["rod_radius_ratio"], self.screen["geometry_mm"]["rod_radius_ratio_sweep"])
        self.assertEqual(geometry["rod_z_min"], self.finite["geometry_mm"]["rod_z_min"])
        self.assertEqual(geometry["rod_z_max"], self.baseline["geometry_mm"]["effective_length"])
        self.assertEqual(compiled["geometry_mm"]["enclosure"], geometry["enclosure"])
        self.assertEqual(
            geometry["enclosure"],
            {
                "model": "cylindrical_grounded_shield_v1",
                "role": "full_length_grounded_shield",
                "working_region_radius_mm": self.finite["geometry_mm"]["working_region_radius"],
                "vacuum_z_min_mm": -2.5,
                "vacuum_z_max_mm": 82.1,
                "shield_inner_radius_mm": self.finite["geometry_mm"]["grounded_shield_inner_radius"],
                "shield_outer_radius_mm": 21.0,
                "entrance_outer_endcap_upstream_face_z_mm": -2.5,
                "entrance_outer_endcap_downstream_face_z_mm": -2.0,
                "exit_outer_endcap_upstream_face_z_mm": 81.6,
                "exit_outer_endcap_downstream_face_z_mm": 82.1,
            },
        )
        for side in ("entrance_interface", "exit_interface"):
            self.assertEqual(
                geometry[side],
                {
                    key: value
                    for key, value in self.finite["geometry_mm"][side].items()
                    if key != "outer_ground_clearance_mm"
                },
            )
        rf = self.baseline["rf"]
        self.assertEqual(
            self.request["drive"],
            {
                "waveform": rf["waveform"],
                "rf_amplitude_V_zero_to_peak_per_group": rf["amplitude_V_peak"],
                "dc_amplitude_V_per_group": 0.0,
                "common_mode_offset_V": rf["common_mode_offset_V"],
                "frequency_Hz": rf["frequency_Hz"],
                "phase_rad": rf["phase_rad"],
            },
        )
        self.assertEqual(
            self.request["segmentation"],
            {
                "strategy": "uniform",
                "segment_count": 4,
                "intersegment_gap_mm": 0.4,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": 0.0,
                "output_reference_V": 0.0,
            },
        )
        self.assertEqual(
            compiled["segmentation"]["axial_acceleration"]["segmentation"]["segment_count"],
            4,
        )

    def test_envelope_has_complete_bounded_unit_coverage(self) -> None:
        variables = self.catalog["variables"]
        pointers = {item["json_pointer"] for item in variables}
        self.assertEqual(len(pointers), len(variables))
        for variable in variables:
            current = pointer_value(self.request, variable["json_pointer"])
            self.assertLess(variable["minimum"], variable["maximum"])
            self.assertLessEqual(variable["minimum"], current)
            self.assertLessEqual(current, variable["maximum"])
            self.assertIn(variable["unit"], {"mm", "ratio", "V", "Hz", "rad", "count"})
        bounded = next(item for item in self.envelope["constraints"] if item["kind"] == "bounded_variable")
        self.assertEqual(set(bounded["request_json_pointers"]), pointers)
        self.assertEqual(
            self.envelope["reference"]["design_request_sha256"],
            hashlib.sha256(REQUEST_PATH.read_bytes()).hexdigest().upper(),
        )
        self.assertIn("connector_shape_supported", self.catalog["invariants"])

    def test_comsol_baseline_freezes_verified_working_region_mesh_limit(self) -> None:
        profiles = self.comsol_numerics["profiles"]
        self.assertEqual(
            profiles["baseline_finite_3d"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.5,
        )
        self.assertEqual(
            profiles["n100_spatial_refined"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.35,
        )
        self.assertEqual(
            profiles["n100_temporal_refined"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.35,
        )
        self.assertEqual(
            profiles["n100_temporal_refined"]["trajectory"]["rf_steps_per_period"],
            160,
        )

    def test_local_sensitive_mesh_sequence_changes_only_registered_size(
        self,
    ) -> None:
        profile_ids = (
            "hybrid_local_sensitive_050_cg_amg_field_screen",
            "hybrid_local_sensitive_040_cg_amg_field_screen",
            "hybrid_local_sensitive_032_cg_amg_field_screen",
        )
        profiles = [
            self.comsol_numerics["profiles"][profile_id]
            for profile_id in profile_ids
        ]
        sizes = [
            profile["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            for profile in profiles
        ]
        self.assertEqual(sizes, [0.5, 0.4, 0.32])
        self.assertEqual([sizes[0] / sizes[1], sizes[1] / sizes[2]], [1.25, 1.25])
        for profile in profiles:
            hybrid = profile["mesh"]["hybrid"]
            self.assertEqual(
                hybrid["sensitive_region"]["particle_corridor_radius_mm"], 3.6
            )
            self.assertEqual(hybrid["axial_layers_per_swept_segment"], 10)
            self.assertEqual(profile["electric_potential_element_order"], "quadratic")
            self.assertEqual(profile["stationary_linear_solver_backend"], "cg_amg")
        normalized = copy.deepcopy(profiles[0])
        del normalized["mesh"]["hybrid"]["sensitive_region"][
            "maximum_element_size_mm"
        ]
        for profile in profiles[1:]:
            peer = copy.deepcopy(profile)
            del peer["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            self.assertEqual(peer, normalized)

    def test_both_static_topologies_bind_all_local_field_levels(self) -> None:
        runtime = self.runtime_profiles["profiles"]
        for mode in (
            "exit_aperture_plate_acceleration",
            "segmented_rod_axial_acceleration",
        ):
            for size in ("050", "040", "032"):
                profile = runtime[
                    f"{mode}_n100_hybrid_local_sensitive_{size}_field_screen"
                ]
                self.assertEqual(profile["stop_stage"], "field_solve")
                self.assertEqual(profile["design_profile_id"], mode)
                self.assertEqual(
                    profile["comsol_solver_numerics_profile_id"],
                    f"hybrid_local_sensitive_{size}_cg_amg_field_screen",
                )

    def test_c1_background_sequence_changes_only_sensitive_size(self) -> None:
        profile_ids = (
            "hybrid_c1_background_sensitive_050_cg_amg_field_screen",
            "hybrid_c1_background_sensitive_040_cg_amg_field_screen",
            "hybrid_c1_background_sensitive_032_cg_amg_field_screen",
        )
        profiles = [
            self.comsol_numerics["profiles"][profile_id]
            for profile_id in profile_ids
        ]
        sizes = [
            profile["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            for profile in profiles
        ]
        self.assertEqual(sizes, [0.5, 0.4, 0.32])
        for profile in profiles:
            hybrid = profile["mesh"]["hybrid"]
            self.assertEqual(hybrid["radial_core_and_rod_hmax_mm"], 0.7)
            self.assertEqual(hybrid["transition_and_end_tetra_hmax_mm"], 0.7)
            self.assertEqual(hybrid["outer_vacuum_hmax_mm"], 1.4)
            self.assertEqual(hybrid["axial_layers_per_swept_segment"], 10)
        normalized = copy.deepcopy(profiles[0])
        del normalized["mesh"]["hybrid"]["sensitive_region"][
            "maximum_element_size_mm"
        ]
        for profile in profiles[1:]:
            peer = copy.deepcopy(profile)
            del peer["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            self.assertEqual(peer, normalized)

    def test_both_static_topologies_bind_c1_background_levels(self) -> None:
        runtime = self.runtime_profiles["profiles"]
        for mode in (
            "exit_aperture_plate_acceleration",
            "segmented_rod_axial_acceleration",
        ):
            for size in ("050", "040", "032"):
                profile = runtime[
                    f"{mode}_n100_hybrid_c1_background_sensitive_{size}_field_screen"
                ]
                self.assertEqual(profile["stop_stage"], "field_solve")
                self.assertEqual(profile["design_profile_id"], mode)
                self.assertEqual(
                    profile["comsol_solver_numerics_profile_id"],
                    f"hybrid_c1_background_sensitive_{size}_cg_amg_field_screen",
                )

    def test_local_sensitive_050_preregistration_freezes_complete_runner(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_local_sensitive_050_field_preregistration.json"
        )
        self.assertEqual(
            preregistration["status"], "completed_resource_budget_exceeded"
        )
        self.assertEqual(
            preregistration["frozen_mesh"]["planned_sequence_mm"],
            [0.5, 0.4, 0.32],
        )
        self.assertEqual(preregistration["frozen_mesh"]["refinement_ratio"], 1.25)
        frozen_paths = {
            entry["path"] for entry in preregistration["frozen_implementation"]["files"]
        }
        self.assertIn(
            "common/multipole/configure_comsol_segment_hybrid_mesh.m",
            frozen_paths,
        )
        frozen_files = preregistration["frozen_implementation"]["files"]
        self.assertEqual(len(frozen_paths), len(frozen_files))
        for entry in frozen_files:
            self.assertRegex(entry["sha256"], r"^[0-9A-F]{64}$")
        execution = preregistration["execution_result"]
        self.assertEqual(
            execution["result"], "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED"
        )
        self.assertEqual(execution["observed"]["mesh_global_elements"], 1_019_364)
        self.assertFalse(execution["later_field_levels_authorized"])

    def test_c1_background_050_preregistration_is_single_run(self) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_c1_background_sensitive_050_field_preregistration.json"
        )
        self.assertEqual(preregistration["status"], "completed_success")
        self.assertEqual(
            preregistration["authorization"]["maximum_commercial_run_count"], 1
        )
        self.assertEqual(
            preregistration["authorization"]["automatic_retry_count"], 0
        )
        mesh = preregistration["frozen_mesh"]
        self.assertEqual(mesh["radial_core_and_rod_hmax_mm"], 0.7)
        self.assertEqual(mesh["transition_and_end_tetra_hmax_mm"], 0.7)
        self.assertEqual(mesh["outer_vacuum_hmax_mm"], 1.4)
        self.assertEqual(
            mesh["sensitive_region"]["maximum_element_size_mm"], 0.5
        )
        self.assertEqual(
            mesh["predecessor_failed_strategy"]["mesh_global_elements"],
            1_019_364,
        )
        self.assertEqual(
            preregistration["execution_result"]["observed"]["mesh_global_elements"],
            685_215,
        )

    def test_v2_corridor_only_050_preregistration_tracks_current_implementation(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_v2_corridor_only_050_field_preregistration.json"
        )
        self.assertEqual(
            preregistration["status"], "completed_mesh_problem_gate_failed"
        )
        self.assertEqual(
            preregistration["frozen_mesh"]["refinement_semantics"],
            "orthogonal_corridor_only_v2",
        )
        self.assertEqual(
            preregistration["frozen_mesh"]["fixed_boundary_axes"],
            {
                "rod_boundary_hmax_source": "radial_core_and_rod_hmax_mm",
                "interface_boundary_hmax_source": "transition_and_end_tetra_hmax_mm",
            },
        )
        frozen_files = preregistration["frozen_implementation"]["files"]
        self.assertEqual(
            len({entry["path"] for entry in frozen_files}), len(frozen_files)
        )
        for entry in frozen_files:
            self.assertRegex(entry["sha256"], r"^[0-9A-F]{64}$")
        budget_path = (
            PROJECT_ROOT / "config" / "qualification" / "engineering_budget.json"
        )
        budget = load(budget_path)
        self.assertFalse(budget["full_matrix_authorization"]["authorized"])
        self.assertEqual(
            preregistration["execution_result"]["observed"]["mesh_global_elements"],
            494_663,
        )
        self.assertEqual(
            preregistration["execution_result"]["observed"][
                "mesh_swept_segments_with_problems"
            ],
            4,
        )
        self.assertFalse(
            preregistration["execution_result"]["particle_followup_authorized"]
        )

    def test_v3_inherited_boundary_050_preregistration_tracks_current_code(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_v3_inherited_boundary_050_field_preregistration.json"
        )
        self.assertEqual(
            preregistration["status"], "completed_diagnostic_api_incompatible"
        )
        self.assertEqual(
            preregistration["mesh_contract"]["refinement_semantics"],
            "domain_inherited_boundary_v3",
        )
        self.assertEqual(
            preregistration["mesh_contract"][
                "localized_boundary_size_features_expected"
            ],
            0,
        )
        for entry in preregistration["frozen_implementation"]["files"]:
            self.assertRegex(entry["sha256"], r"^[0-9A-F]{64}$")
        self.assertEqual(
            preregistration["execution_result"]["result"],
            "INCONCLUSIVE_DIAGNOSTIC_API_INCOMPATIBLE",
        )
        self.assertFalse(
            preregistration["execution_result"]["mesh_statistics_available"]
        )

    def test_inherited_boundary_nonblocking_050_run_closes_postrun_failure(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_inherited_boundary_nonblocking_050_field_preregistration.json"
        )
        self.assertEqual(
            preregistration["status"], "completed_postrun_contract_failure"
        )
        self.assertEqual(
            preregistration["diagnostic_contract"]["mesh_validity_authority"],
            "mphmeshstats.hasproblems",
        )
        self.assertEqual(
            preregistration["diagnostic_contract"]["per_feature_problem_messages"],
            "best_effort_nonblocking",
        )
        self.assertEqual(
            preregistration["mesh_contract"][
                "localized_boundary_size_features_expected"
            ],
            0,
        )
        for entry in preregistration["frozen_implementation"]["files"]:
            self.assertRegex(entry["sha256"], r"^[0-9A-F]{64}$")
        execution = preregistration["execution_result"]
        self.assertEqual(
            execution["result"], "POSTHOC_ENGINEERING_OBSERVATION_ONLY"
        )
        self.assertEqual(execution["observed"]["mesh_global_elements"], 434_876)
        self.assertFalse(execution["observed"]["mesh_global_has_problems"])
        self.assertEqual(execution["observed"]["field_sample_row_count"], 6_660)
        self.assertFalse(execution["authoritative_level_pass"])

    def test_inherited_boundary_050_requalification_freezes_complete_report(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_inherited_boundary_050_field_requalification.json"
        )
        self.assertEqual(preregistration["status"], "completed_success")
        required_report = preregistration["required_report"]
        for token in (
            "MESH_GLOBAL_HAS_PROBLEMS=0",
            "MESH_VACUUM_HAS_PROBLEMS=0",
            "CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE",
            "FIELD_SOLVE_DIAGNOSTIC=PASS",
            "STATUS=PASS",
        ):
            self.assertIn(token, required_report["tokens"])
        self.assertEqual(
            set(required_report["forbidden_checkpoints"]),
            {
                "PRIMARY_PARTICLE_CASE_COMPLETE",
                "CONTROL_PARTICLE_CASE_COMPLETE",
            },
        )
        for entry in preregistration["frozen_implementation"]["files"]:
            path = PROJECT_ROOT.parents[1] / entry["path"]
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                entry["sha256"],
            )
        self.assertEqual(
            preregistration["execution_result"]["observed"]["mesh_global_elements"],
            434_876,
        )
        self.assertTrue(preregistration["execution_result"]["authoritative_level_pass"])

    def test_inherited_boundary_040_preregistration_binds_valid_parent(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_inherited_boundary_040_field_preregistration.json"
        )
        self.assertEqual(preregistration["status"], "completed_success")
        self.assertEqual(
            preregistration["mesh_contract"]["corridor_maximum_element_size_mm"],
            0.4,
        )
        self.assertEqual(
            preregistration["mesh_contract"]["parent"]["mesh_global_elements"],
            434_876,
        )
        for entry in preregistration["frozen_implementation"]["files"]:
            self.assertRegex(entry["sha256"], r"^[0-9A-F]{64}$")
        self.assertEqual(
            preregistration["execution_result"]["observed"]["mesh_global_elements"],
            537_566,
        )

    def test_inherited_boundary_032_preregistration_binds_trend_and_budget(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_inherited_boundary_032_field_preregistration.json"
        )
        trend = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_inherited_boundary_field_trend.json"
        )
        self.assertEqual(
            preregistration["status"],
            "completed_success_sequence_stopped_at_budget_boundary",
        )
        self.assertFalse(trend["decision"]["field_convergence_established"])
        self.assertFalse(trend["decision"]["particle_followup_authorized"])
        self.assertEqual(
            preregistration["mesh_contract"]["corridor_maximum_element_size_mm"],
            0.32,
        )
        self.assertEqual(
            preregistration["execution_result"]["observed"]["mesh_global_elements"],
            713_396,
        )
        self.assertEqual(
            trend["resource_boundary"]["next_level_0256_extrapolated_cells"],
            1_014_459,
        )
        budget = load(
            PROJECT_ROOT / "config" / "qualification" / "engineering_budget.json"
        )
        self.assertFalse(budget["pilot_authorization"]["authorized"])

    def test_c1_background_040_preregistration_binds_successful_parent(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_c1_background_sensitive_040_field_preregistration.json"
        )
        self.assertEqual(
            preregistration["status"],
            "completed_success_sequence_stopped_at_budget_boundary",
        )
        self.assertEqual(
            preregistration["authorization"]["automatic_retry_count"], 0
        )
        mesh = preregistration["frozen_mesh"]
        self.assertEqual(mesh["sensitive_region"]["maximum_element_size_mm"], 0.4)
        self.assertEqual(mesh["parent"]["mesh_global_elements"], 685_215)
        self.assertEqual(
            mesh["parent"]["field_samples_sha256"],
            "924A83C94D39AB20564D86BDCAFC253661AB7B7526EFEDCA6BBE658D68E15C13",
        )
        execution = preregistration["execution_result"]
        self.assertEqual(execution["observed"]["mesh_global_elements"], 990_929)
        self.assertEqual(execution["observed"]["remaining_mesh_cell_budget"], 9_071)

    def test_local_field_trend_stops_before_unaffordable_third_level(
        self,
    ) -> None:
        trend = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_c1_background_sensitive_field_trend.json"
        )
        self.assertEqual(
            trend["status"], "INCONCLUSIVE_MESH_STRATEGY_CHANGE_REQUIRED"
        )
        regular = trend["regular_region_field_vector_reference_normalized_rms"][
            "rod_span_uniform"
        ]
        self.assertLess(
            regular["differential_050_to_040"],
            regular["differential_c1_to_050"],
        )
        self.assertLess(
            regular["static_050_to_040"],
            regular["static_c1_to_050"],
        )
        self.assertFalse(trend["resource_boundary"]["sensitive_032_authorized"])
        self.assertFalse(trend["decision"]["field_convergence_established"])
        self.assertFalse(trend["decision"]["particle_followup_authorized"])


if __name__ == "__main__":
    unittest.main()
