from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from common.multipole.runtime_profile import resolve_runtime_profile
from common.multipole.stationary_field_sampling import (
    generate_stationary_field_sample_rows,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT / "projects" / "rf_hexapole_ion_optics"
PREREGISTRATION_PATH = (
    PROJECT_ROOT
    / "config"
    / "qualification"
    / "comsol_hybrid_c1_cg_amg_field_screen_preregistration.json"
)
MUMPS_PREREGISTRATION_PATH = (
    PROJECT_ROOT
    / "config"
    / "qualification"
    / "comsol_hybrid_c1_mumps_field_screen_preregistration.json"
)
CG_RUNTIME_ID = (
    "exit_aperture_plate_acceleration_n100_hybrid_c1_cg_amg_field_screen"
)
MUMPS_RUNTIME_ID = (
    "exit_aperture_plate_acceleration_n100_hybrid_c1_mumps_field_screen"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class C1SampledFieldPreregistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preregistration = load(PREREGISTRATION_PATH)
        self.mumps_preregistration = load(MUMPS_PREREGISTRATION_PATH)

    def test_two_arms_use_the_same_mesh_and_quadratic_order(self) -> None:
        cg = resolve_runtime_profile(
            REPO_ROOT, "rf_hexapole_ion_optics", CG_RUNTIME_ID
        )
        mumps = resolve_runtime_profile(
            REPO_ROOT, "rf_hexapole_ion_optics", MUMPS_RUNTIME_ID
        )
        self.assertEqual(cg["stop_stage"], "field_solve")
        self.assertEqual(mumps["stop_stage"], "field_solve")
        cg_numerics = cg["solver_numerics"]["comsol"]["values"]
        mumps_numerics = mumps["solver_numerics"]["comsol"]["values"]
        self.assertEqual(cg_numerics["mesh"], mumps_numerics["mesh"])
        self.assertEqual(
            cg_numerics["electric_potential_element_order"], "quadratic"
        )
        self.assertEqual(
            mumps_numerics["electric_potential_element_order"], "quadratic"
        )
        self.assertEqual(cg_numerics["stationary_linear_solver_backend"], "cg_amg")
        self.assertEqual(mumps_numerics["stationary_linear_solver_backend"], "mumps")

    def test_live_budget_closes_three_level_field_sequence(self) -> None:
        budget = load(
            PROJECT_ROOT / "config" / "qualification" / "engineering_budget.json"
        )
        pilot = budget["pilot_authorization"]
        self.assertFalse(pilot["authorized"])
        self.assertFalse(budget["full_matrix_authorization"]["authorized"])
        self.assertNotIn(
            pilot["scope"]["runtime_profile_id"],
            {CG_RUNTIME_ID, MUMPS_RUNTIME_ID},
        )
        self.assertEqual(
            pilot["scope"]["runtime_profile_id"],
            "exit_aperture_plate_acceleration_n100_hybrid_c1_background_sensitive_032_field_screen",
        )
        self.assertEqual(pilot["scope"]["stop_stage"], "field_solve")
        self.assertEqual(pilot["scope"]["allowed_solvers"], ["comsol"])
        self.assertEqual(pilot["limits"]["wall_clock_seconds_by_solver"]["comsol"], 600)
        self.assertEqual(pilot["limits"]["process_tree_working_set_bytes"], 12 * 1024**3)
        self.assertEqual(pilot["limits"]["maximum_mesh_cells"], 1_000_000)
        self.assertEqual(pilot["limits"]["automatic_retry_count"], 0)
        trend = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_c1_background_sensitive_field_trend.json"
        )
        self.assertEqual(
            trend["status"], "INCONCLUSIVE_MESH_STRATEGY_CHANGE_REQUIRED"
        )

    def test_completed_c1_arm_preserves_frozen_authority_and_implementation_hashes(
        self,
    ) -> None:
        frozen = self.preregistration["frozen_identity"]
        for field in (
            "runtime_profiles_sha256",
            "comsol_solver_numerics_sha256",
            "engineering_budget_sha256",
            "particle_source_profiles_sha256",
            "design_profiles_sha256",
        ):
            self.assertRegex(frozen[field], r"^[0-9A-F]{64}$")
        implementation = self.preregistration["frozen_implementation"]["files"]
        self.assertEqual(
            {entry["path"] for entry in implementation},
            {
                "common/multipole/run_finite_3d_transport.ps1",
                "common/multipole/solve_finite_3d_transport.m",
                "common/multipole/export_comsol_stationary_field_samples.m",
                "common/multipole/stationary_field_sampling.py",
            },
        )
        for entry in implementation:
            self.assertRegex(entry["sha256"], r"^[0-9A-F]{64}$")
            self.assertTrue((REPO_ROOT / entry["path"]).is_file())

    def test_sampling_plan_is_frozen_and_has_the_preregistered_count(self) -> None:
        sampling = self.preregistration["field_sampling"]
        plan_path = REPO_ROOT / sampling["plan_path"]
        self.assertEqual(sampling["plan_sha256"], sha256(plan_path))
        rows = generate_stationary_field_sample_rows(
            load(PROJECT_ROOT / "config" / "resolved_design.json"),
            load(plan_path),
        )
        self.assertEqual(len(rows), sampling["expected_point_count"])
        self.assertEqual(
            2 * len(rows),
            sampling["expected_row_count"],
        )

    def test_preregistration_is_one_run_zero_retry_and_no_particle_claim(self) -> None:
        self.assertEqual(self.preregistration["schema_version"], 2)
        self.assertEqual(self.preregistration["status"], "completed_success")
        authorization = self.preregistration["authorization"]
        self.assertEqual(authorization["maximum_commercial_run_count"], 1)
        self.assertEqual(authorization["automatic_retry_count"], 0)
        self.assertEqual(authorization["runtime_profile_id"], CG_RUNTIME_ID)
        self.assertEqual(authorization["stop_stage"], "field_solve")
        self.assertFalse(
            self.preregistration["decision_policy"][
                "particle_followup_authorized"
            ]
        )
        execution = self.preregistration["execution_result"]
        self.assertEqual(execution["manifest_status"], "success")
        self.assertEqual(execution["observed"]["mesh_global_elements"], 371_447)
        self.assertEqual(execution["observed"]["differential_field_dof"], 733_422)
        self.assertEqual(execution["observed"]["static_field_dof"], 733_422)
        self.assertEqual(execution["observed"]["field_sample_row_count"], 6_660)
        for token in (
            "FIELD_SAMPLE_POINT_COUNT=3330",
            "FIELD_SAMPLE_ROW_COUNT=6660",
            "CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE",
            "FIELD_PHYSICS_CREATED=1",
            "FIELD_STUDIES_CREATED=2",
            "FIELD_SOLUTIONS_CREATED=2",
        ):
            self.assertIn(token, self.preregistration["required_report"]["tokens"])

    def test_mumps_followup_preserves_frozen_authorities_and_cg_evidence(
        self,
    ) -> None:
        self.assertEqual(self.mumps_preregistration["status"], "completed_success")
        self.assertEqual(
            self.mumps_preregistration["authorization"]["runtime_profile_id"],
            MUMPS_RUNTIME_ID,
        )
        frozen = self.mumps_preregistration["frozen_identity"]
        for field in (
            "runtime_profiles_sha256",
            "comsol_solver_numerics_sha256",
            "engineering_budget_sha256",
            "particle_source_profiles_sha256",
            "design_profiles_sha256",
        ):
            self.assertRegex(frozen[field], r"^[0-9A-F]{64}$")
        parent = self.mumps_preregistration["parent_cg_amg_arm"]
        self.assertEqual(parent["manifest_status"], "success")
        self.assertEqual(
            parent["run_manifest_sha256"],
            self.preregistration["execution_result"]["evidence_sha256"][
                "run_manifest"
            ],
        )
        identity = self.mumps_preregistration["frozen_mesh_and_dof_identity"]
        self.assertEqual(identity["mesh_global_elements"], 371_447)
        self.assertEqual(identity["differential_field_dof"], 733_422)
        self.assertEqual(identity["static_field_dof"], 733_422)
        execution = self.mumps_preregistration["execution_result"]
        self.assertEqual(execution["manifest_status"], "success")
        self.assertEqual(execution["observed"]["mesh_global_elements"], 371_447)
        self.assertEqual(execution["observed"]["field_sample_row_count"], 6_660)

    def test_comparison_record_remains_diagnostic_only(self) -> None:
        comparison = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_hybrid_c1_solver_comparison.json"
        )
        self.assertEqual(comparison["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")
        self.assertFalse(comparison["acceptance_thresholds_applied"])
        self.assertEqual(
            comparison["decision"]["solver_pair_functional_closure"], "PASS"
        )
        self.assertEqual(
            comparison["decision"]["numerical_equivalence_qualification"],
            "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET",
        )
        self.assertFalse(comparison["decision"]["particle_followup_authorized"])
        self.assertFalse(
            comparison["decision"]["commercial_run_authorization_open"]
        )
        self.assertEqual(
            comparison["metrics"]["differential"][
                "field_vector_reference_normalized_rms"
            ],
            2.29979687036153e-6,
        )
        self.assertEqual(
            comparison["metrics"]["static"][
                "field_vector_reference_normalized_rms"
            ],
            3.0298904548747926e-5,
        )

    def test_d2_sampled_spatial_arm_is_completed_and_single_axis(self) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_hybrid_d2_cg_amg_sampled_field_preregistration.json"
        )
        self.assertEqual(preregistration["status"], "completed_success")
        mesh = preregistration["frozen_mesh"]
        self.assertEqual(mesh["single_refinement_axis"], "nonaxial_local_size_limits")
        self.assertEqual(mesh["unchanged_axial_layers_per_swept_segment"], 10)
        self.assertEqual(mesh["expected_mesh_global_elements"], 884_643)
        self.assertEqual(mesh["expected_differential_field_dof"], 1_657_156)
        self.assertFalse(
            preregistration["decision_policy"]["particle_followup_authorized"]
        )
        execution = preregistration["execution_result"]
        self.assertEqual(execution["manifest_status"], "success")
        self.assertEqual(execution["observed"]["mesh_global_elements"], 884_643)
        self.assertEqual(execution["observed"]["field_sample_row_count"], 6_660)

    def test_d3_axial_arm_is_completed_and_single_axis(self) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_hybrid_d3_axial14_cg_amg_sampled_field_preregistration.json"
        )
        self.assertEqual(preregistration["status"], "completed_success")
        self.assertTrue(
            preregistration["authorization"]["planned_run_id"].endswith("__r02")
        )
        frozen = preregistration["frozen_identity"]
        for field in (
            "runtime_profiles_sha256",
            "comsol_solver_numerics_sha256",
            "engineering_budget_sha256",
            "particle_source_profiles_sha256",
            "design_profiles_sha256",
        ):
            self.assertRegex(frozen[field], r"^[0-9A-F]{64}$")
        mesh = preregistration["frozen_mesh"]
        self.assertEqual(
            mesh["single_refinement_axis"], "axial_layers_per_swept_segment"
        )
        self.assertEqual(mesh["parent_axial_layers_per_swept_segment"], 10)
        self.assertEqual(mesh["axial_layers_per_swept_segment"], 14)
        self.assertFalse(
            preregistration["decision_policy"]["particle_followup_authorized"]
        )
        pre_solver = preregistration["pre_solver_attempt"]
        self.assertFalse(pre_solver["commercial_solver_launched"])
        self.assertEqual(pre_solver["commercial_run_count_consumed"], 0)
        execution = preregistration["execution_result"]
        self.assertEqual(execution["manifest_status"], "success")
        self.assertEqual(execution["observed"]["mesh_global_elements"], 979_785)
        self.assertEqual(execution["observed"]["field_sample_row_count"], 6_660)
        self.assertFalse(execution["particle_followup_authorized"])

    def test_d2_to_d3_comparison_closes_without_particle_authorization(self) -> None:
        comparison = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_hybrid_d2_vs_d3_axial_comparison.json"
        )
        self.assertEqual(comparison["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")
        self.assertFalse(comparison["acceptance_thresholds_applied"])
        self.assertEqual(
            comparison["decision"]["axial_discretization_engineering_stability"],
            "SUPPORTED_BY_SMALL_ADJACENT_DIFFERENCE",
        )
        self.assertEqual(
            comparison["decision"]["overall_spatial_convergence"],
            "NOT_ESTABLISHED",
        )
        self.assertFalse(comparison["decision"]["further_mesh_refinement_authorized"])
        self.assertFalse(comparison["decision"]["particle_followup_authorized"])
        self.assertEqual(
            comparison["metrics"]["differential"][
                "field_vector_reference_normalized_rms"
            ],
            0.001574401382595984,
        )
        self.assertEqual(
            comparison["metrics"]["static"][
                "field_vector_reference_normalized_rms"
            ],
            0.008096903185390733,
        )


if __name__ == "__main__":
    unittest.main()
