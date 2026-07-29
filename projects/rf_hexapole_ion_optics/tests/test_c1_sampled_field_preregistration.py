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

    def test_active_budget_authorizes_only_the_second_arm(self) -> None:
        budget = load(
            PROJECT_ROOT / "config" / "qualification" / "engineering_budget.json"
        )
        pilot = budget["pilot_authorization"]
        self.assertTrue(pilot["authorized"])
        self.assertEqual(pilot["scope"]["runtime_profile_id"], MUMPS_RUNTIME_ID)
        self.assertEqual(pilot["scope"]["stop_stage"], "field_solve")
        self.assertEqual(pilot["scope"]["allowed_solvers"], ["comsol"])
        self.assertEqual(pilot["limits"]["wall_clock_seconds_by_solver"]["comsol"], 600)
        self.assertEqual(pilot["limits"]["process_tree_working_set_bytes"], 12 * 1024**3)
        self.assertEqual(pilot["limits"]["maximum_mesh_cells"], 600_000)
        self.assertEqual(pilot["limits"]["automatic_retry_count"], 0)

    def test_authority_and_implementation_hashes_are_current(self) -> None:
        frozen = self.preregistration["frozen_identity"]
        authorities = {
            "runtime_profiles_sha256": PROJECT_ROOT
            / "config"
            / "runtime_profiles.json",
            "comsol_solver_numerics_sha256": PROJECT_ROOT
            / "config"
            / "comsol_solver_numerics.json",
            "particle_source_profiles_sha256": PROJECT_ROOT
            / "config"
            / "particle_source_profiles.json",
            "design_profiles_sha256": PROJECT_ROOT
            / "config"
            / "design_profiles.json",
        }
        for field, path in authorities.items():
            self.assertEqual(frozen[field], sha256(path), field)
        self.assertRegex(frozen["engineering_budget_sha256"], r"^[0-9A-F]{64}$")
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
            self.assertEqual(entry["sha256"], sha256(REPO_ROOT / entry["path"]))

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

    def test_mumps_followup_freezes_current_authorities_and_cg_evidence(self) -> None:
        self.assertEqual(self.mumps_preregistration["status"], "authorized_not_run")
        self.assertEqual(
            self.mumps_preregistration["authorization"]["runtime_profile_id"],
            MUMPS_RUNTIME_ID,
        )
        frozen = self.mumps_preregistration["frozen_identity"]
        authorities = {
            "runtime_profiles_sha256": PROJECT_ROOT
            / "config"
            / "runtime_profiles.json",
            "comsol_solver_numerics_sha256": PROJECT_ROOT
            / "config"
            / "comsol_solver_numerics.json",
            "engineering_budget_sha256": PROJECT_ROOT
            / "config"
            / "qualification"
            / "engineering_budget.json",
            "particle_source_profiles_sha256": PROJECT_ROOT
            / "config"
            / "particle_source_profiles.json",
            "design_profiles_sha256": PROJECT_ROOT
            / "config"
            / "design_profiles.json",
        }
        for field, path in authorities.items():
            self.assertEqual(frozen[field], sha256(path), field)
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


if __name__ == "__main__":
    unittest.main()
