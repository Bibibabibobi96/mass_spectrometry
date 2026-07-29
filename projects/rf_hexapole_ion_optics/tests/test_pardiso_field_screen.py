from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from common.multipole.runtime_profile import resolve_runtime_profile


REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT / "projects" / "rf_hexapole_ion_optics"
RUNTIME_ID = "exit_aperture_plate_acceleration_n100_hybrid_d2_pardiso_field_screen"


def load(relative_path: str) -> dict:
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig"))


def sha256(relative_path: str) -> str:
    return hashlib.sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest().upper()


class PardisoFieldScreenContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preregistration = load(
            "config/qualification/"
            "comsol_hybrid_d2_pardiso_field_screen_preregistration.json"
        )

    def test_runtime_changes_only_stationary_backend_from_rejected_mesh(self) -> None:
        runtime = resolve_runtime_profile(
            REPO_ROOT, "rf_hexapole_ion_optics", RUNTIME_ID
        )
        self.assertEqual(runtime["stop_stage"], "field_solve")
        candidate = runtime["solver_numerics"]["comsol"]["values"]
        rejected = load("config/comsol_solver_numerics.json")["profiles"][
            "hybrid_d2_transport_screen"
        ]
        self.assertEqual(candidate["stationary_linear_solver_backend"], "pardiso")
        self.assertEqual(rejected["stationary_linear_solver_backend"], "mumps")
        self.assertEqual(candidate["mesh"], rejected["mesh"])
        self.assertEqual(candidate["trajectory"], rejected["trajectory"])

    def test_authority_hashes_and_single_run_budget_are_frozen(self) -> None:
        frozen = self.preregistration["frozen_identity"]
        for field, path in {
            "runtime_profiles_sha256": "config/runtime_profiles.json",
            "comsol_solver_numerics_sha256": "config/comsol_solver_numerics.json",
            "particle_source_profiles_sha256": "config/particle_source_profiles.json",
            "design_profiles_sha256": "config/design_profiles.json",
        }.items():
            self.assertEqual(frozen[field], sha256(path))
        self.assertEqual(
            self.preregistration["execution_result"][
                "completed_engineering_budget_sha256"
            ],
            sha256("config/qualification/engineering_budget.json"),
        )
        authorization = self.preregistration["authorization"]
        self.assertEqual(authorization["maximum_commercial_run_count"], 1)
        self.assertEqual(authorization["automatic_retry_count"], 0)
        self.assertEqual(authorization["stop_stage"], "field_solve")
        limits = self.preregistration["resource_limits"]
        self.assertEqual(limits["wall_clock_seconds"], 300)
        self.assertEqual(limits["process_tree_working_set_bytes"], 12 * 1024**3)
        self.assertEqual(limits["maximum_mesh_cells"], 1_000_000)

    def test_live_engineering_budget_closes_field_screen(self) -> None:
        budget = load("config/qualification/engineering_budget.json")
        pilot = budget["pilot_authorization"]
        self.assertFalse(pilot["authorized"])
        self.assertEqual(pilot["scope"]["runtime_profile_id"], RUNTIME_ID)
        self.assertEqual(
            pilot["scope"]["solver_numerics_profile_ids"]["comsol"],
            "hybrid_d2_pardiso_field_screen",
        )
        self.assertEqual(pilot["scope"]["allowed_solvers"], ["comsol"])
        self.assertFalse(budget["full_matrix_authorization"]["authorized"])
        result = self.preregistration["execution_result"]
        self.assertTrue(result["terminal"])
        self.assertEqual(
            result["result"], "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED"
        )
        self.assertFalse(result["differential_field_complete"])
        self.assertFalse(result["particle_followup_authorized"])

    def test_field_stop_is_before_particle_construction(self) -> None:
        solver = (
            REPO_ROOT / "common" / "multipole" / "solve_finite_3d_transport.m"
        ).read_text(encoding="utf-8")
        field_stop = solver.index("if fieldSolveOnly")
        particle_create = solver.index(
            "comp.physics.create('cpt', 'ChargedParticleTracing', 'geom1')"
        )
        self.assertLess(field_stop, particle_create)
        for token in (
            "STATIONARY_LINEAR_SOLVER_BACKEND=%s",
            "DIFFERENTIAL_FIELD_DOF=%d",
            "STATIC_FIELD_DOF=%d",
            "FIELD_SOLVE_DIAGNOSTIC=PASS",
            "PARTICLE_PHYSICS_CREATED=%d",
        ):
            self.assertIn(token, solver)


if __name__ == "__main__":
    unittest.main()
