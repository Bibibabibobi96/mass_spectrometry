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
SIMION_ARMS = {
    "A": ("r030_z030_t080", {"x": 0.3, "y": 0.3, "z": 0.3}, 80, "010201"),
    "R": ("r020_z030_t080", {"x": 0.2, "y": 0.2, "z": 0.3}, 80, "010202"),
    "Z": ("r030_z020_t080", {"x": 0.3, "y": 0.3, "z": 0.2}, 80, "010203"),
    "I": ("r020_z020_t080", {"x": 0.2, "y": 0.2, "z": 0.2}, 80, "010204"),
    "T": ("r020_z020_t160", {"x": 0.2, "y": 0.2, "z": 0.2}, 160, "010205"),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_budget(path: Path, solver: str, runtime_id: str, run_id: str) -> dict:
    runtime = resolve_runtime_profile(REPO_ROOT, "rf_octupole_ion_optics", runtime_id)
    return validate_pilot_budget(
        repo_root=REPO_ROOT,
        budget_path=path,
        project_id="rf_octupole_ion_optics",
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
            self.assertIn(f"20260731_{run_serial}__sim__simion__oct-", scope["authorized_run_id"])
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
        numerics = load(PROJECT_ROOT / "config/comsol_solver_numerics.json")["profiles"]
        runtime = load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"]
        anchor_id = "hybrid_c1_corridor040_exit020_nosweep_cg_amg_spatial_temporal_refined"
        refined_id = "hybrid_c1_corridor040_exit020_nosweep_cg_amg_temporal_refined_320"
        refined_as_anchor = copy.deepcopy(numerics[refined_id])
        refined_as_anchor["trajectory"]["rf_steps_per_period"] = 160
        self.assertEqual(refined_as_anchor, numerics[anchor_id])
        for steps, serial in ((160, "020201"), (320, "020202")):
            runtime_id = f"no_acceleration_full_length_n100_comsol_followup_exit020_t{steps}"
            profile_id = anchor_id if steps == 160 else refined_id
            self.assertEqual(runtime[runtime_id]["comsol_solver_numerics_profile_id"], profile_id)
            budget = load(CAMPAIGN / f"comsol_exit020_t{steps}_budget.json")
            scope = budget["pilot_authorization"]["scope"]
            self.assertEqual(scope["allowed_solvers"], ["comsol"])
            self.assertEqual(scope["runtime_profile_id"], runtime_id)
            self.assertIn(f"20260731_{serial}__sim__comsol__oct-", scope["authorized_run_id"])
            self.assertEqual(budget["pilot_authorization"]["limits"]["automatic_retry_count"], 0)
            validate_budget(
                CAMPAIGN / f"comsol_exit020_t{steps}_budget.json",
                "comsol",
                runtime_id,
                scope["authorized_run_id"],
            )

    def test_preregistrations_are_frozen_before_run(self) -> None:
        simion = load(CAMPAIGN / "simion_preregistration.json")
        comsol = load(CAMPAIGN / "comsol_preregistration.json")
        self.assertEqual(comsol["resolution_contract"], simion["resolution_contract"])
        for prereg in (simion, comsol):
            self.assertTrue(all(not arm["executed"] for arm in prereg["ordered_arms"]))
            references = [prereg["resolution_contract"]]
            for value in prereg["frozen_authorities"].values():
                references.extend(value if isinstance(value, list) else [value])
            for reference in references:
                self.assertEqual(
                    reference["sha256"],
                    file_sha256(REPO_ROOT / reference["path"]),
                )
        self.assertFalse(list(CAMPAIGN.glob("*qualification*.json")))


if __name__ == "__main__":
    unittest.main()
