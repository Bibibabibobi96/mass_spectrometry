from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from common.multipole.runtime_profile import resolve_runtime_profile


REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = REPO_ROOT / "projects" / "rf_hexapole_ion_optics"
RUNTIME_ID = (
    "exit_aperture_plate_acceleration_n100_hybrid_d2_cg_amg_field_screen"
)


def load(relative_path: str) -> dict:
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8-sig"))


def sha256(relative_path: str) -> str:
    return hashlib.sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest().upper()


class CgAmgFieldScreenContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preregistration = load(
            "config/qualification/"
            "comsol_hybrid_d2_cg_amg_field_screen_preregistration.json"
        )

    def test_runtime_changes_only_stationary_backend_from_rejected_d2(self) -> None:
        runtime = resolve_runtime_profile(
            REPO_ROOT, "rf_hexapole_ion_optics", RUNTIME_ID
        )
        self.assertEqual(runtime["stop_stage"], "field_solve")
        candidate = runtime["solver_numerics"]["comsol"]["values"]
        rejected = load("config/comsol_solver_numerics.json")["profiles"][
            "hybrid_d2_transport_screen"
        ]
        self.assertEqual(candidate["stationary_linear_solver_backend"], "cg_amg")
        self.assertEqual(rejected["stationary_linear_solver_backend"], "mumps")
        self.assertEqual(candidate["electric_potential_element_order"], "quadratic")
        self.assertEqual(
            rejected["electric_potential_element_order"], "quadratic"
        )
        self.assertEqual(candidate["mesh"], rejected["mesh"])
        self.assertEqual(candidate["trajectory"], rejected["trajectory"])
        self.assertEqual(
            candidate["stationary_iterative_solver"],
            {
                "relative_tolerance": 0.001,
                "maximum_iterations": 500,
                "error_check_mode": "on",
            },
        )

    def test_authority_hashes_and_single_run_budget_are_frozen(self) -> None:
        frozen = self.preregistration["frozen_identity"]
        self.assertEqual(
            frozen,
            {
                "expected_run_parent_resolved_design_sha256": (
                    "C9C3B00A5327825FCB138FB7EEDF2C6F7175497EAEB3CD1EB28A5D995AAC4B6E"
                ),
                "physical_resolved_payload_sha256": (
                    "A868E5C06A6A98BF86C0D662D53118FCFF6EE51BA208214FACD7D39E32F6FD66"
                ),
                "runtime_profiles_sha256": (
                    "D70329FDD81F80AA319321F82B7C4D2DD46137E36F198209C028E3CB66241664"
                ),
                "comsol_solver_numerics_sha256": (
                    "36FD834AFE7128AECEF381058D3A5792C9288C007CE91F28115EB55CDA8F0E95"
                ),
                "engineering_budget_sha256": (
                    "197F9945BB64B3C93F99587F81985D59E3D498E6258F3CBFDCD8479174F5A24D"
                ),
                "particle_source_profiles_sha256": (
                    "8162081232E0ABCA311DA9E9D10B8BDA78ED24E95C919E8E52B6787DDD1C0B30"
                ),
                "design_profiles_sha256": (
                    "157EB846B0F3715A300EF9F3D994DD3B05A919C04FBFD83D6B8611A77FAA74B1"
                ),
            },
        )
        authorization = self.preregistration["authorization"]
        self.assertEqual(authorization["maximum_commercial_run_count"], 1)
        self.assertEqual(authorization["automatic_retry_count"], 0)
        self.assertEqual(authorization["stop_stage"], "field_solve")
        limits = self.preregistration["resource_limits"]
        self.assertEqual(limits["wall_clock_seconds"], 703)
        self.assertEqual(limits["process_tree_working_set_bytes"], 12 * 1024**3)
        self.assertEqual(limits["maximum_mesh_cells"], 1_000_000)
        implementation = self.preregistration["frozen_implementation"]["files"]
        self.assertEqual(
            [entry["path"] for entry in implementation],
            [
                "common/multipole/configure_comsol_stationary_solver.m",
                "common/multipole/solve_finite_3d_transport.m",
                "common/multipole/run_finite_3d_transport.ps1",
                "common/multipole/test_comsol_stationary_solver_smoke.m",
            ],
        )
        self.assertEqual(
            {entry["path"]: entry["sha256"] for entry in implementation},
            {
                "common/multipole/configure_comsol_stationary_solver.m": (
                    "2964CE151C53A3165F45163E48CC2CB3ACF80AC9270CBACB448F02C2FCEDDAB6"
                ),
                "common/multipole/solve_finite_3d_transport.m": (
                    "BABDB5F307F152C85AB13DFADE4CB6D49E218C4AD1CD540C8E44ABBC241F61BE"
                ),
                "common/multipole/run_finite_3d_transport.ps1": (
                    "302EF2516B8DDD7DDE94A03B1870FCCB9CE675E7EF84D12343A7D0EC8BD34957"
                ),
                "common/multipole/test_comsol_stationary_solver_smoke.m": (
                    "0939BE0D804578B8137F60064A205C4196D6307FA41ED5167F56C134147C1DA4"
                ),
            },
        )
        self.assertEqual(
            self.preregistration["single_changed_variable"]["name"],
            "stationary_linear_solver_configuration",
        )
        self.assertEqual(
            self.preregistration["frozen_iterative_solver"][
                "unlisted_amg_properties"
            ],
            "comsol_6_4_generated_defaults_not_individually_qualified_or_reported",
        )

    def test_live_budget_does_not_reauthorize_closed_r0(self) -> None:
        budget = load("config/qualification/engineering_budget.json")
        pilot = budget["pilot_authorization"]
        if pilot["scope"]["runtime_profile_id"] == RUNTIME_ID:
            self.assertFalse(pilot["authorized"])
        else:
            self.assertNotEqual(pilot["scope"]["runtime_profile_id"], RUNTIME_ID)
        self.assertEqual(pilot["scope"]["allowed_solvers"], ["comsol"])
        self.assertFalse(budget["full_matrix_authorization"]["authorized"])

    def test_execution_is_closed_as_protocol_mismatch(self) -> None:
        self.assertEqual(
            self.preregistration["status"],
            "completed_preregistered_report_contract_mismatch",
        )
        result = self.preregistration["execution_result"]
        self.assertTrue(result["terminal"])
        self.assertEqual(result["manifest_status"], "failed")
        self.assertEqual(
            result["result"],
            "INCONCLUSIVE_PREREGISTERED_REPORT_CONTRACT_MISMATCH",
        )
        self.assertFalse(result["preregistered_viability_pass"])
        self.assertFalse(result["preregistered_resource_improvement_pass"])
        self.assertFalse(result["particle_followup_authorized"])
        observation = result["raw_solver_observation"]
        self.assertEqual(observation["field_physics_created"], 1)
        self.assertEqual(observation["field_studies_created"], 2)
        self.assertEqual(observation["field_solutions_created"], 2)
        self.assertEqual(observation["particle_physics_created"], 0)
        self.assertEqual(observation["differential_field_iterations"], 6)
        self.assertEqual(observation["static_field_iterations"], 7)
        self.assertTrue(observation["all_preregistered_resource_limits_observed_satisfied"])
        for value in result["evidence_sha256"].values():
            self.assertRegex(value, r"^[0-9A-F]{64}$")

    def test_report_contract_requires_native_iteration_evidence(self) -> None:
        report = self.preregistration["required_report"]
        for token in (
            "STATIONARY_LINEAR_SOLVER_BACKEND=CG_AMG",
            "ELECTRIC_POTENTIAL_ELEMENT_ORDER=QUADRATIC",
            "STATIONARY_CONTROL=USER",
            "STATIONARY_RELATIVE_TOLERANCE=0.001",
            "STATIONARY_FULLY_COUPLED_LINEAR_SOLVER=I1",
            "STATIONARY_MAX_LINEAR_ITERATIONS=500",
            "STATIONARY_LINEAR_ERROR_CHECK=ON",
            "STATIONARY_CONVERGENCE_LOG=DETAILED",
            "DIFFERENTIAL_FIELD_SOLVER_EVIDENCE_SOURCE=COMSOL_PROGRESS_LINIT_LINRES",
            "STATIC_FIELD_SOLVER_EVIDENCE_SOURCE=COMSOL_PROGRESS_LINIT_LINRES",
            "FIELD_PHYSICS_CREATED=2",
            "FIELD_STUDIES_CREATED=2",
            "FIELD_SOLUTIONS_CREATED=2",
        ):
            self.assertIn(token, report["tokens"])
        self.assertEqual(
            set(report["positive_integer_fields"]),
            {
                "DIFFERENTIAL_FIELD_DOF",
                "STATIC_FIELD_DOF",
                "DIFFERENTIAL_FIELD_ITERATIONS",
                "STATIC_FIELD_ITERATIONS",
            },
        )
        self.assertEqual(
            set(report["finite_nonnegative_fields"]),
            {
                "DIFFERENTIAL_FIELD_FINAL_RESIDUAL",
                "STATIC_FIELD_FINAL_RESIDUAL",
            },
        )
        self.assertFalse(
            self.preregistration["decision_policy"][
                "fallback_backend_or_retry_authorized"
            ]
        )

    def test_runner_requires_exact_preregistered_run_before_package(self) -> None:
        runner = (
            REPO_ROOT / "common" / "multipole" / "run_finite_3d_transport.ps1"
        ).read_text(encoding="utf-8")
        preregistration_gate = runner.index(
            "$fieldPreregistration=Assert-MultipoleFieldPreregistration"
        )
        self.assertLess(preregistration_gate, runner.index("$package=New-RunPackage"))
        for token in (
            "planned_run_id-ne$RunId",
            "maximum_commercial_run_count-ne 1",
            "automatic_retry_count-ne 0",
            "authority hash differs",
            "implementation hash differs",
            "required_report.tokens",
            "required_report.forbidden_checkpoints",
        ):
            self.assertIn(token, runner)


if __name__ == "__main__":
    unittest.main()
