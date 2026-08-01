from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
CAMPAIGN = PROJECT_ROOT / "config/qualification/no_acceleration_followup"
RADIAL_EXTENSION = PROJECT_ROOT / "config/qualification/radial_convergence_extension"
SIMION_ARMS = {
    "A": ("r030_z030_t080", {"x": 0.3, "y": 0.3, "z": 0.3}, 80, "010101"),
    "R": ("r020_z030_t080", {"x": 0.2, "y": 0.2, "z": 0.3}, 80, "010102"),
    "Z": ("r030_z020_t080", {"x": 0.3, "y": 0.3, "z": 0.2}, 80, "010103"),
    "I": ("r020_z020_t080", {"x": 0.2, "y": 0.2, "z": 0.2}, 80, "010104"),
    "T": ("r020_z020_t160", {"x": 0.2, "y": 0.2, "z": 0.2}, 160, "010105"),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_budget(path: Path, solver: str, runtime_id: str, run_id: str) -> dict:
    runtime = resolve_runtime_profile(REPO_ROOT, "rf_hexapole_ion_optics", runtime_id)
    return validate_pilot_budget(
        repo_root=REPO_ROOT,
        budget_path=path,
        project_id="rf_hexapole_ion_optics",
        solver=solver,
        runtime_profile_id=runtime_id,
        design_profile_id=runtime["design_profile_id"],
        particle_source_path=Path(runtime["particle_source"]["path"]),
        retention_class="compact",
        run_id=run_id,
    )


class NoAccelerationFollowupConfigurationTests(unittest.TestCase):
    def test_simion_factorial_profiles_and_independent_budgets_are_bound(self) -> None:
        numerics = load(PROJECT_ROOT / "config/simion_solver_numerics.json")["profiles"]
        runtime = load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"]
        prereg = load(CAMPAIGN / "simion_preregistration.json")
        self.assertEqual([arm["arm"] for arm in prereg["ordered_arms"]], list(SIMION_ARMS))
        for arm, (suffix, cell, steps, run_serial) in SIMION_ARMS.items():
            numerics_id = f"simion_followup_{arm}_{suffix}"
            runtime_id = f"no_acceleration_full_length_n100_simion_followup_{arm}_{suffix}"
            self.assertEqual(numerics[numerics_id]["cell_mm_xyz"], cell)
            self.assertEqual(
                numerics[numerics_id]["trajectory"]["rf_steps_per_period"], steps
            )
            self.assertEqual(
                runtime[runtime_id]["simion_solver_numerics_profile_id"], numerics_id
            )
            budget = load(CAMPAIGN / f"simion_{arm}_budget.json")
            scope = budget["pilot_authorization"]["scope"]
            limits = budget["pilot_authorization"]["limits"]
            self.assertEqual(scope["allowed_solvers"], ["simion"])
            self.assertEqual(scope["runtime_profile_id"], runtime_id)
            self.assertIn(f"20260731_{run_serial}__sim__simion__hex-", scope["authorized_run_id"])
            self.assertEqual(limits["automatic_retry_count"], 0)
            self.assertEqual(limits["wall_clock_seconds_by_solver"]["simion"], 1800)
            self.assertEqual(limits["transient_run_directory_bytes"], 6 * 1024**3)
            self.assertEqual(limits["process_tree_working_set_bytes"], 6 * 1024**3)
            self.assertEqual(limits["minimum_system_available_memory_bytes"], 8 * 1024**3)
            self.assertEqual(limits["maximum_pa_grid_points"], 20_000_000)
            validate_budget(
                CAMPAIGN / f"simion_{arm}_budget.json",
                "simion",
                runtime_id,
                scope["authorized_run_id"],
            )

    def test_comsol_new_arm_is_bound_to_existing_pass_anchor(self) -> None:
        numerics = load(PROJECT_ROOT / "config/comsol_solver_numerics.json")["profiles"]
        runtime = load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"]
        anchor_id = "hybrid_c1_corridor040_exit020_nosweep_cg_amg_spatial_temporal_refined"
        refined_id = "hybrid_c1_corridor040_exit020_nosweep_cg_amg_temporal_refined_320"
        refined_as_anchor = copy.deepcopy(numerics[refined_id])
        refined_as_anchor["trajectory"]["rf_steps_per_period"] = 160
        self.assertEqual(refined_as_anchor, numerics[anchor_id])
        runtime_id = "no_acceleration_full_length_n100_comsol_followup_exit020_t320"
        self.assertEqual(runtime[runtime_id]["comsol_solver_numerics_profile_id"], refined_id)
        budget = load(CAMPAIGN / "comsol_exit020_t320_budget.json")
        scope = budget["pilot_authorization"]["scope"]
        self.assertEqual(scope["allowed_solvers"], ["comsol"])
        self.assertEqual(scope["runtime_profile_id"], runtime_id)
        self.assertEqual(
            scope["authorized_run_id"],
            "20260731_020101__sim__comsol__hex-noacc-followup-exit020-t320",
        )
        validate_budget(
            CAMPAIGN / "comsol_exit020_t320_budget.json",
            "comsol",
            runtime_id,
            scope["authorized_run_id"],
        )
        prereg = load(CAMPAIGN / "comsol_preregistration.json")
        anchor, refined = prereg["ordered_arms"]
        self.assertEqual(
            anchor["authorized_run_id"],
            "20260730_152001__sim__comsol__hex-noacc-hybrid-exit020-t160__r01",
        )
        self.assertTrue(anchor["executed"])
        self.assertEqual(anchor["evidence_status"], "EXISTING_PASS_ANCHOR")
        self.assertFalse(refined["executed"])

    def test_preregistrations_are_frozen_without_new_result(self) -> None:
        simion = load(CAMPAIGN / "simion_preregistration.json")
        comsol = load(CAMPAIGN / "comsol_preregistration.json")
        self.assertEqual(comsol["resolution_contract"], simion["resolution_contract"])
        for prereg in (simion, comsol):
            references = [prereg["resolution_contract"]]
            for value in prereg["frozen_authorities"].values():
                references.extend(value if isinstance(value, list) else [value])
            for reference in references:
                # These SHA values freeze the pre-run snapshot; later registry
                # additions must not rewrite that historical identity.
                self.assertTrue((REPO_ROOT / reference["path"]).is_file())
                self.assertRegex(reference["sha256"], r"^[A-F0-9]{64}$")
        self.assertFalse(list(CAMPAIGN.glob("*qualification*.json")))

    def test_h15_radial_extension_is_frozen_and_budget_bound(self) -> None:
        prereg = load(RADIAL_EXTENSION / "preregistration.json")
        arm = prereg["authorized_arm"]
        runtime_id = arm["runtime_profile_id"]
        runtime = load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"]
        numerics = load(PROJECT_ROOT / "config/simion_solver_numerics.json")[
            "profiles"
        ]
        self.assertEqual(
            prereg["status"],
            "EXECUTED_ENGINEERING_PASS_FAMILY_PROGRESSION_AUTHORIZED",
        )
        self.assertEqual(arm["arm"], "H15")
        self.assertTrue(arm["executed"])
        self.assertEqual(arm["evidence_status"], "PASS_ENGINEERING_PROGRESSION")
        self.assertEqual(arm["cell_mm_xyz"], {"x": 0.15, "y": 0.15, "z": 0.2})
        self.assertEqual(arm["rf_steps_per_period"], 160)
        self.assertEqual(
            runtime[runtime_id]["simion_solver_numerics_profile_id"],
            arm["simion_solver_numerics_profile_id"],
        )
        self.assertEqual(
            numerics[arm["simion_solver_numerics_profile_id"]]["cell_mm_xyz"],
            arm["cell_mm_xyz"],
        )
        for reference in prereg["frozen_authorities"].values():
            self.assertEqual(
                reference["sha256"],
                file_sha256(REPO_ROOT / reference["path"]),
            )
        validate_budget(
            RADIAL_EXTENSION / "simion_H15_budget.json",
            "simion",
            runtime_id,
            arm["authorized_run_id"],
        )
        result = load(RADIAL_EXTENSION / "H15_result.json")
        self.assertEqual(
            result["status"],
            "PASS_ENGINEERING_PROGRESSION_CONTINUE_FAMILY_CAMPAIGN",
        )
        self.assertEqual(result["run"]["pa_grid_points"], 33_479_464)
        self.assertEqual(result["run"]["primary_transmission"], 1.0)
        self.assertEqual(result["analysis"]["decision_status"], "PASS")
        self.assertEqual(
            result["analysis"]["identity_status"],
            "ARCHIVED_INCOMPLETE_RUN_NO_MANIFEST",
        )
        self.assertNotIn("run_id", result["analysis"])
        self.assertTrue(result["analysis"]["artifact_path"].startswith("artifacts/"))
        differences = result["adjacent_difference"]
        self.assertLess(
            differences["transverse_centroid_vector_difference_mm"],
            0.2,
        )
        self.assertLess(
            differences["centered_spatial_rms_spread_absolute_difference_mm"],
            0.2,
        )
        self.assertLess(
            differences["mean_beam_direction_separation_deg"],
            1.0,
        )
        self.assertLess(
            differences["centered_angular_rms_spread_absolute_difference_deg"],
            1.0,
        )
        self.assertLess(differences["mean_energy_absolute_difference_eV"], 0.2)
        self.assertLess(
            differences[
                "centered_rms_energy_spread_absolute_difference_eV"
            ],
            0.2,
        )


    def test_followup_result_preserves_inconclusive_claim_boundary(self) -> None:
        result = load(CAMPAIGN / "followup_result.json")
        self.assertEqual(result["role"], "multipole_no_acceleration_followup_result")
        self.assertEqual(
            result["status"],
            "INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED",
        )
        self.assertEqual(result["functional_result"], "PASS_100_OF_100_ALL_SUCCESSFUL_ARMS")
        self.assertEqual(
            result["simion"]["spatial_status"],
            "SENSITIVE_AT_PREREGISTERED_ENGINEERING_RESOLUTION",
        )
        self.assertEqual(
            result["comsol"]["temporal_status"],
            "SENSITIVE_AT_PREREGISTERED_ENGINEERING_RESOLUTION",
        )


if __name__ == "__main__":
    unittest.main()
