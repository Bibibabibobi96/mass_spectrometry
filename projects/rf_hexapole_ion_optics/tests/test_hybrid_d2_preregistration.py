from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
CONFIG_ROOT = PROJECT_ROOT / "config"
QUALIFICATION_ROOT = CONFIG_ROOT / "qualification"
RUNTIME_PROFILE_ID = (
    "exit_aperture_plate_acceleration_n100_hybrid_d2_mesh_build"
)
NUMERICS_PROFILE_ID = "hybrid_d2_mesh_build"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class HybridD2PreregistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preregistration_path = (
            QUALIFICATION_ROOT
            / "comsol_hybrid_mesh_build_d2_preregistration.json"
        )
        cls.budget_path = QUALIFICATION_ROOT / "engineering_budget.json"
        cls.preregistration = load(cls.preregistration_path)
        cls.budget = load(cls.budget_path)
        cls.runtime_registry = load(CONFIG_ROOT / "runtime_profiles.json")
        cls.comsol_registry = load(CONFIG_ROOT / "comsol_solver_numerics.json")
        cls.execution = cls.preregistration["execution_result"]
        cls.run_root = (
            WORKSPACE_ROOT
            / "artifacts"
            / "projects"
            / "rf_hexapole_ion_optics"
            / "runs"
            / cls.execution["run_id"]
        )
        manifest_path = cls.run_root / "run_manifest.json"
        cls.manifest = load(manifest_path) if manifest_path.is_file() else None

    def assert_retained_identity(self, identity: dict) -> Path:
        self.assertIsInstance(identity["bytes"], int)
        self.assertGreater(identity["bytes"], 0)
        self.assertRegex(identity["sha256"], r"^[A-F0-9]{64}$")
        path = WORKSPACE_ROOT / identity["workspace_relative_path"]
        if path.is_file():
            self.assertEqual(path.stat().st_size, identity["bytes"])
            self.assertEqual(sha256(path), identity["sha256"])
        return path

    def test_d2_is_one_completed_build_only_identity(self) -> None:
        preregistration = self.preregistration
        self.assertEqual(
            preregistration["diagnostic_id"],
            "hexapole_exit_aperture_plate_hybrid_mesh_build_d2_v1",
        )
        self.assertEqual(preregistration["status"], "COMPLETED_PASS")
        self.assertTrue(preregistration["preregistered_before_run"])
        self.assertEqual(preregistration["maximum_commercial_run_count"], 1)
        self.assertEqual(preregistration["commercial_run_count_authorized"], 0)
        self.assertEqual(preregistration["commercial_run_count_executed"], 1)
        self.assertFalse(preregistration["d2"]["authorized"])
        self.assertEqual(preregistration["scope"]["stop_stage"], "mesh_build")
        self.assertEqual(
            preregistration["scope"]["runtime_profile_id"], RUNTIME_PROFILE_ID
        )
        self.assertFalse(preregistration["next_stage"]["authorized"])
        for forbidden in (
            "D1_retry",
            "P1_retry",
            "P2",
            "P3",
            "P4",
            "D3",
            "field_physics",
            "field_study",
            "field_solution",
            "particle_physics",
            "particle_study",
            "automatic_retry",
            "full_matrix",
        ):
            self.assertIn(forbidden, preregistration["prohibited"])

    def test_d2_uses_only_the_existing_hybrid_mesh_fields(self) -> None:
        expected = {
            "strategy": "physical_segment_hybrid_swept_tetra_v1",
            "physical_segment_count": 4,
            "segment_end_buffer_mm": 1.0,
            "swept_length_per_segment_mm": 17.6,
            "core_radius_mm": 8.5,
            "radial_core_and_rod_hmax_mm": 0.5,
            "axial_layers_per_swept_segment": 10,
            "transition_and_end_tetra_hmax_mm": 0.5,
            "outer_vacuum_hmax_mm": 1.0,
            "minimum_element_size_mm": 0.02,
        }
        preregistered = self.preregistration["d2"]["hybrid_mesh"]
        self.assertEqual(preregistered, expected)
        numerics = self.comsol_registry["profiles"][NUMERICS_PROFILE_ID]
        self.assertIsNone(
            numerics["mesh"]["working_region_maximum_element_size_mm"]
        )
        self.assertEqual(numerics["mesh"]["strategy"], expected["strategy"])
        self.assertEqual(
            numerics["mesh"]["hybrid"],
            {key: value for key, value in expected.items() if key != "strategy"},
        )
        self.assertEqual(numerics["trajectory"]["rf_steps_per_period"], 80)
        self.assertEqual(numerics["trajectory"]["maximum_global_time_us"], 80.0)

    def test_d2_runtime_is_retained_but_budget_is_closed(self) -> None:
        profile = self.runtime_registry["profiles"][RUNTIME_PROFILE_ID]
        self.assertEqual(
            profile,
            {
                "design_profile_id": "exit_aperture_plate_acceleration",
                "particle_source_profile_id": "family_mother_sample_v1_n100",
                "comsol_solver_numerics_profile_id": NUMERICS_PROFILE_ID,
                "simion_solver_numerics_profile_id": "baseline_finite_3d",
            },
        )
        authorization = self.budget["pilot_authorization"]
        self.assertFalse(authorization["authorized"])
        self.assertEqual(authorization["scope"]["allowed_solvers"], ["comsol"])
        self.assertEqual(
            authorization["scope"]["runtime_profile_id"], RUNTIME_PROFILE_ID
        )
        self.assertEqual(
            authorization["scope"]["solver_numerics_profile_ids"]["comsol"],
            NUMERICS_PROFILE_ID,
        )
        self.assertEqual(
            authorization["limits"],
            {
                "wall_clock_seconds_by_solver": {
                    "comsol": 300,
                    "simion": 300,
                },
                "transient_run_directory_bytes": 134217728,
                "process_tree_working_set_bytes": 6442450944,
                "minimum_system_available_memory_bytes": 8589934592,
                "compact_final_retained_bytes": 10485760,
                "maximum_mesh_cells": 3000000,
                "automatic_retry_count": 0,
            },
        )
        self.assertFalse(self.budget["full_matrix_authorization"]["authorized"])
        self.assertIn("No commercial solver run", self.budget["claim_limit"])

    def test_d2_solver_size_and_terminal_report_are_frozen(self) -> None:
        d2 = self.preregistration["d2"]
        self.assertEqual(
            d2["solver_size_limit"],
            {
                "engineering_budget_field": (
                    "pilot_authorization.limits.maximum_mesh_cells"
                ),
                "report_metric": "MESH_GLOBAL_ELEMENTS",
                "maximum_mesh_cells": 3000000,
                "evaluation_stage": "mesh_build_runner_gate",
                "runtime_enforcement_status": "RUNNER_ENFORCED",
            },
        )
        for token in (
            "MESH_GLOBAL_ELEMENTS",
            "MESH_VACUUM_MIN_QUALITY",
            "FIELD_PHYSICS_CREATED=0",
            "FIELD_STUDIES_CREATED=0",
            "FIELD_SOLUTIONS_CREATED=0",
            "PARTICLE_PHYSICS_CREATED=0",
            "PARTICLE_STUDIES_CREATED=0",
            "MESH_BUILD_DIAGNOSTIC=PASS",
        ):
            self.assertIn(token, d2["required_report_tokens"])
        self.assertIn(
            "global_mesh_cells_not_greater_than_3000000",
            d2["result_policy"]["pass_requires"],
        )
        self.assertEqual(d2["result_policy"]["automatic_retry_count"], 0)

    def test_frozen_authorities_bind_run_inputs_not_closed_budget(self) -> None:
        authorities = self.preregistration["frozen_authorities"]
        for name, authority in authorities.items():
            if name == "engineering_budget":
                continue
            path = REPO_ROOT / authority["path"]
            self.assertTrue(path.is_file(), authority["path"])
            self.assertEqual(sha256(path), authority["sha256"])
        frozen_inputs = self.execution["frozen_run_inputs"]
        manifest_inputs = self.manifest["inputs"] if self.manifest is not None else {}
        for name in ("evidence_contract", "engineering_budget"):
            identity = frozen_inputs[name]
            self.assertEqual(identity["manifest_input_key"], name)
            self.assert_retained_identity(identity)
            if self.manifest is not None:
                self.assertEqual(manifest_inputs[name]["bytes"], identity["bytes"])
                self.assertEqual(manifest_inputs[name]["sha256"], identity["sha256"])
        frozen_budget = authorities["engineering_budget"]
        self.assertEqual(
            frozen_budget["sha256_at_preregistration"],
            frozen_inputs["engineering_budget"]["sha256"],
        )
        current_budget = self.execution["current_closed_engineering_budget"]
        current_budget_path = REPO_ROOT / current_budget["path"]
        self.assertEqual(current_budget_path.stat().st_size, current_budget["bytes"])
        self.assertEqual(sha256(current_budget_path), current_budget["sha256"])
        self.assertNotEqual(
            current_budget["sha256"],
            frozen_inputs["engineering_budget"]["sha256"],
        )
        self.assertFalse(current_budget["pilot_authorized"])
        frozen_contract_identity = frozen_inputs["evidence_contract"]
        self.assertEqual(
            frozen_contract_identity["snapshot_status"], "AUTHORIZED_NOT_RUN"
        )
        self.assertTrue(frozen_contract_identity["snapshot_d2_authorized"])
        self.assertEqual(
            frozen_contract_identity["snapshot_commercial_run_count_authorized"],
            1,
        )
        frozen_contract_path = (
            WORKSPACE_ROOT / frozen_contract_identity["workspace_relative_path"]
        )
        if frozen_contract_path.is_file():
            frozen_contract = load(frozen_contract_path)
            self.assertEqual(
                frozen_contract["status"],
                frozen_contract_identity["snapshot_status"],
            )
            self.assertEqual(
                frozen_contract["d2"]["authorized"],
                frozen_contract_identity["snapshot_d2_authorized"],
            )
        frozen_budget_identity = frozen_inputs["engineering_budget"]
        self.assertTrue(frozen_budget_identity["snapshot_pilot_authorized"])
        self.assertEqual(
            frozen_budget_identity["snapshot_contract_id"],
            "hexapole_hybrid_mesh_build_d2_diagnostic_authorized_v16",
        )
        for predecessor in (
            "closed_p1_preregistration",
            "closed_d1_preregistration",
        ):
            authority = self.preregistration["predecessor_evidence"][predecessor]
            path = REPO_ROOT / authority["path"]
            self.assertTrue(path.is_file(), authority["path"])
            self.assertEqual(sha256(path), authority["sha256"])
            self.assertFalse(authority["retry_authorized"])

    def test_execution_result_binds_manifest_outputs_and_measured_pass(self) -> None:
        execution = self.execution
        self.assertTrue(execution["terminal"])
        self.assertEqual(execution["status"], "PASS")
        self.assertEqual(
            execution["qualification_status"],
            "UNQUALIFIED_MESH_BUILD_DIAGNOSTIC_ONLY",
        )
        self.assertTrue(execution["authorization_exhausted"])
        self.assertFalse(execution["retry_authorized"])
        manifest_identity = execution["run_manifest"]
        self.assert_retained_identity(manifest_identity)
        self.assertEqual(manifest_identity["manifest_status"], "success")
        self.assertEqual(
            manifest_identity["manifest_project"], "rf_hexapole_ion_optics"
        )
        retained_outputs = execution["retained_outputs"]
        for identity in retained_outputs.values():
            self.assert_retained_identity(identity)
        if self.manifest is not None:
            self.assertEqual(self.manifest["status"], "success")
            self.assertEqual(self.manifest["run_id"], execution["run_id"])
            manifest_outputs = {
                Path(item["path"]).name: item for item in self.manifest["outputs"]
            }
            for name, identity in retained_outputs.items():
                manifest_key = (
                    "comsol_finite_3d_transport.txt"
                    if name == "report"
                    else Path(identity["workspace_relative_path"]).name
                )
                manifest_output = manifest_outputs[manifest_key]
                self.assertEqual(manifest_output["bytes"], identity["bytes"])
                self.assertEqual(manifest_output["sha256"], identity["sha256"])
                self.assertEqual(
                    manifest_output["retention_role"],
                    identity["manifest_retention_role"],
                )
        mesh = execution["mesh_result"]
        self.assertEqual(mesh["global_elements"], 884643)
        self.assertLessEqual(
            mesh["global_elements"], mesh["maximum_global_elements"]
        )
        self.assertEqual(mesh["vacuum_elements"], 746131)
        self.assertEqual(mesh["tetrahedral_elements"], 527571)
        self.assertEqual(mesh["swept_segment_elements"], [54640] * 4)
        self.assertEqual(mesh["global_minimum_quality"], 0.1983)
        self.assertEqual(mesh["swept_minimum_quality"], 0.5311)
        for name in (
            "swept_tetrahedral_overlap_domain_count",
            "vacuum_uncovered_domain_count",
            "nonvacuum_partition_domain_count",
        ):
            self.assertEqual(mesh[name], 0)
        self.assertTrue(execution["resource_result"]["within_all_limits"])
        self.assertTrue(
            all(value == 0 for value in execution["object_creation_result"].values())
        )

    def test_existing_preflight_resolves_d2_but_rejects_every_run(self) -> None:
        runtime = resolve_runtime_profile(
            REPO_ROOT, "rf_hexapole_ion_optics", RUNTIME_PROFILE_ID
        )
        source = Path(runtime["particle_source"]["path"])
        self.assertIsNone(
            runtime["solver_numerics"]["comsol"]["values"]["mesh"][
                "working_region_maximum_element_size_mm"
            ]
        )
        for changed in (
            {},
            {"solver": "simion"},
            {"retention_class": "qualification"},
            {"runtime_profile_id": "exit_aperture_plate_acceleration"},
        ):
            arguments = {
                "repo_root": REPO_ROOT,
                "budget_path": self.budget_path,
                "project_id": "rf_hexapole_ion_optics",
                "solver": "comsol",
                "runtime_profile_id": RUNTIME_PROFILE_ID,
                "design_profile_id": "exit_aperture_plate_acceleration",
                "particle_source_path": source,
                "retention_class": "compact",
            }
            arguments.update(changed)
            with self.assertRaisesRegex(ValueError, "not authorized"):
                validate_pilot_budget(**arguments)
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            resolve_runtime_profile(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                "exit_aperture_plate_acceleration_n100_hybrid_d1_mesh_build",
            )


if __name__ == "__main__":
    unittest.main()
