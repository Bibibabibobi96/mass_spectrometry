from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
CAMPAIGN = PROJECT_ROOT / "config/family_experiment/no_acceleration_followup"
N1000_BRIDGE = (
    PROJECT_ROOT
    / "config/family_experiment/no_acceleration_n1000_comsol_bridge"
)
ENGINEERING_ACCEPTANCE = (
    REPO_ROOT / "common/multipole/engineering_progression_acceptance.json"
)
SIMION_ARMS = {
    "A": ("r030_z030_t080", {"x": 0.3, "y": 0.3, "z": 0.3}, 80, "010001"),
    "R": ("r020_z030_t080", {"x": 0.2, "y": 0.2, "z": 0.3}, 80, "010002"),
    "Z": ("r030_z020_t080", {"x": 0.3, "y": 0.3, "z": 0.2}, 80, "010003"),
    "I": ("r020_z020_t080", {"x": 0.2, "y": 0.2, "z": 0.2}, 80, "010004"),
    "T": ("r020_z020_t160", {"x": 0.2, "y": 0.2, "z": 0.2}, 160, "010005"),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_budget(path: Path, solver: str, runtime_id: str, run_id: str) -> dict:
    runtime = resolve_runtime_profile(
        REPO_ROOT, "rf_quadrupole_ion_optics", runtime_id
    )
    return validate_pilot_budget(
        repo_root=REPO_ROOT,
        budget_path=path,
        project_id="rf_quadrupole_ion_optics",
        solver=solver,
        runtime_profile_id=runtime_id,
        design_profile_id=runtime["design_profile_id"],
        particle_source_path=Path(runtime["particle_source"]["path"]),
        retention_class="compact",
        run_id=run_id,
    )


class NoAccelerationFollowupConfigurationTests(unittest.TestCase):
    def test_simion_factorial_profiles_and_independent_budgets_are_bound(self) -> None:
        numerics = load(
            PROJECT_ROOT / "config/multipole_transport_simion_solver_numerics.json"
        )["profiles"]
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
            self.assertEqual(
                runtime[runtime_id]["engineering_budget_path"],
                f"config/family_experiment/no_acceleration_followup/simion_{arm}_budget.json",
            )
            budget = load(CAMPAIGN / f"simion_{arm}_budget.json")
            scope = budget["pilot_authorization"]["scope"]
            limits = budget["pilot_authorization"]["limits"]
            self.assertEqual(scope["runtime_profile_id"], runtime_id)
            self.assertEqual(scope["allowed_solvers"], ["simion"])
            self.assertEqual(scope["particle_count"], 100)
            self.assertEqual(scope["retention_class"], "compact")
            self.assertIn(f"20260731_{run_serial}__sim__simion__quad-", scope["authorized_run_id"])
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

    def test_comsol_temporal_profiles_change_only_steps_and_have_fixed_budgets(self) -> None:
        numerics = load(
            PROJECT_ROOT / "config/multipole_transport_comsol_solver_numerics.json"
        )["profiles"]
        runtime = load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"]
        anchor_id = "hybrid_c1_corridor040_exit020_nosweep_cg_amg_spatial_temporal_refined"
        refined_id = "hybrid_c1_corridor040_exit020_nosweep_cg_amg_temporal_refined_320"
        refined_as_anchor = copy.deepcopy(numerics[refined_id])
        refined_as_anchor["trajectory"]["rf_steps_per_period"] = 160
        self.assertEqual(refined_as_anchor, numerics[anchor_id])
        for steps, serial in ((160, "020001"), (320, "020002")):
            runtime_id = f"no_acceleration_full_length_n100_comsol_followup_exit020_t{steps}"
            profile_id = anchor_id if steps == 160 else refined_id
            self.assertEqual(runtime[runtime_id]["comsol_solver_numerics_profile_id"], profile_id)
            budget = load(CAMPAIGN / f"comsol_exit020_t{steps}_budget.json")
            scope = budget["pilot_authorization"]["scope"]
            self.assertEqual(scope["allowed_solvers"], ["comsol"])
            self.assertEqual(scope["runtime_profile_id"], runtime_id)
            self.assertIn(f"20260731_{serial}__sim__comsol__quad-", scope["authorized_run_id"])
            self.assertEqual(budget["pilot_authorization"]["limits"]["automatic_retry_count"], 0)
            validate_budget(
                CAMPAIGN / f"comsol_exit020_t{steps}_budget.json",
                "comsol",
                runtime_id,
                scope["authorized_run_id"],
            )

    def test_historical_preregistrations_remain_well_formed(self) -> None:
        simion = load(CAMPAIGN / "simion_preregistration.json")
        comsol = load(CAMPAIGN / "comsol_preregistration.json")
        self.assertEqual(comsol["resolution_contract"], simion["resolution_contract"])
        for prereg in (simion, comsol):
            self.assertTrue(all(not arm["executed"] for arm in prereg["ordered_arms"]))
            references = [prereg["resolution_contract"]]
            authorities = prereg["frozen_authorities"]
            for value in authorities.values():
                references.extend(value if isinstance(value, list) else [value])
            for reference in references:
                # These SHA values freeze the pre-run snapshot; later registry
                # additions must not rewrite that historical identity.
                self.assertTrue((REPO_ROOT / reference["path"]).is_file())
                self.assertRegex(reference["sha256"], r"^[A-F0-9]{64}$")
            for arm in prereg["ordered_arms"]:
                resolve_runtime_profile(
                    REPO_ROOT,
                    "rf_quadrupole_ion_optics",
                    arm["runtime_profile_id"],
                )
        self.assertFalse(list(CAMPAIGN.glob("*qualification*.json")))


    def test_followup_result_preserves_inconclusive_claim_boundary(self) -> None:
        result = load(CAMPAIGN / "followup_result.json")
        self.assertEqual(result["role"], "multipole_no_acceleration_followup_result")
        self.assertEqual(
            result["status"],
            "INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED",
        )
        self.assertEqual(result["functional_result"], "PASS_100_OF_100_ALL_SUCCESSFUL_ARMS")
        self.assertEqual(
            result["simion"]["temporal_status"],
            "STABLE_AT_PREREGISTERED_ENGINEERING_RESOLUTION",
        )
        self.assertEqual(
            result["comsol"]["temporal_status"],
            "SENSITIVE_AT_PREREGISTERED_ENGINEERING_RESOLUTION",
        )

    def test_n1000_bridge_is_closed_without_a_particle_result(self) -> None:
        preregistration = load(N1000_BRIDGE / "preregistration.json")
        observed = preregistration["observed_result"]
        self.assertEqual(
            preregistration["status"],
            "EXECUTED_INTERRUPTED_INCONCLUSIVE",
        )
        self.assertTrue(preregistration["authorized_arm"]["executed"])
        self.assertEqual(observed["status"], "interrupted")
        self.assertEqual(
            observed["decision"],
            "CAMPAIGN_CLOSED_INCONCLUSIVE_NO_N1000_RESULT",
        )
        self.assertEqual(observed["requested_particle_count"], 1000)
        self.assertEqual(observed["constructed_particle_release_count"], 746)
        self.assertTrue(observed["stationary_field_completed"])
        self.assertFalse(observed["particle_solve_stage_reached"])
        self.assertFalse(observed["particle_state_result_available"])
        self.assertEqual(observed["automatic_retry_count"], 0)
        self.assertTrue(observed["campaign_closed"])
        for field in (
            "run_manifest_sha256",
            "summary_sha256",
            "resource_usage_sha256",
            "particle_release_log_inventory_sha256",
        ):
            self.assertRegex(observed[field], r"^[A-F0-9]{64}$")

    def test_temporary_engineering_progression_contract_uses_common_authority(
        self,
    ) -> None:
        contract = load(ENGINEERING_ACCEPTANCE)
        self.assertEqual(
            ENGINEERING_ACCEPTANCE,
            REPO_ROOT / "common/multipole/engineering_progression_acceptance.json",
        )
        self.assertEqual(
            contract["role"],
            "multipole_engineering_progression_acceptance_contract",
        )
        self.assertEqual(
            contract["status"],
            "ACTIVE_ENGINEERING_PROGRESSION_POLICY",
        )
        self.assertEqual(
            contract["scope"]["comparison_kinds"],
            ["same_solver_discretization", "cross_solver"],
        )
        energy = contract["continuous_engineering_acceptance"][
            "energy_observables"
        ]
        self.assertEqual(
            energy["mean_energy_difference_eV"],
            {
                "maximum": 0.2,
                "status": "APPROVED",
                "basis": (
                    "Ten percent of the frozen upstream mean source energy "
                    "of 2.0 eV."
                ),
            },
        )
        self.assertEqual(
            energy["centered_energy_spread_difference_eV"],
            {
                "maximum": 0.2,
                "status": "APPROVED",
                "basis": (
                    "Temporary absolute difference limit because the frozen "
                    "upstream centered RMS energy spread is 0 eV."
                ),
            },
        )
        functional = contract["functional_acceptance"]
        self.assertEqual(
            functional["sha256"],
            file_sha256(REPO_ROOT / functional["path"]),
        )
        self.assertEqual(
            contract["decision_policy"]["numerical_convergence"],
            "DEFERRED_NOT_WAIVED",
        )
        self.assertIn(
            "does not establish numerical convergence",
            contract["claim_limit"],
        )


if __name__ == "__main__":
    unittest.main()
