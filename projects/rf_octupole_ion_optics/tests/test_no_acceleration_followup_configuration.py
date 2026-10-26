from __future__ import annotations

import copy
import csv
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.design_profile import resolve_design_profile
from common.multipole.particle_source_preflight import load_validated_source, materialize_source_release
from common.ion_release import mt19937_disk_cone_rf_phase as release_sampler
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


# Complete selected COMSOL field/mesh baseline from the preregistered registry,
# whose original SHA was verified when this test fixture was recorded. It is test data,
# not a second production authority or a requirement on unrelated registry rows.
COMSOL_FOLLOWUP_FIELD_NUMERICS = {
    "stationary_linear_solver_backend": "cg_amg",
    "electric_potential_element_order": "quadratic",
    "stationary_iterative_solver": {"relative_tolerance": 0.001, "maximum_iterations": 500, "error_check_mode": "on"},
    "mesh": {
        "strategy": "physical_segment_hybrid_swept_tetra_v1",
        "global_auto_level": 6,
        "working_region_maximum_element_size_mm": None,
        "hybrid": {
            "physical_segment_count": 4,
            "segment_end_buffer_mm": 1.0,
            "swept_length_per_segment_mm": 17.6,
            "core_radius_mm": 8.5,
            "radial_core_and_rod_hmax_mm": 0.7,
            "axial_layers_per_swept_segment": 10,
            "transition_and_end_tetra_hmax_mm": 0.7,
            "outer_vacuum_hmax_mm": 1.4,
            "minimum_element_size_mm": 0.028,
            "sensitive_region": {
                "particle_corridor_radius_mm": 3.6,
                "maximum_element_size_mm": 0.4,
                "exit_interface_refinement": {
                    "upstream_extent_from_rod_exit_mm": 1.0,
                    "downstream_extent_from_handoff_mm": 0.5,
                    "maximum_element_size_mm": 0.2,
                },
            },
        },
    },
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
    def test_524da_through_exit_runtime_and_budget_validate_without_sampling(self) -> None:
        with patch.object(
            release_sampler,
            "generate_mt19937_disk_cone_rf_phase_states",
            side_effect=AssertionError("preflight must not sample"),
        ):
            runtime = resolve_runtime_profile(
                REPO_ROOT, "rf_octupole_ion_optics", "through_exit_no_acceleration_524da_n100"
            )
            budget = validate_pilot_budget(
                repo_root=REPO_ROOT,
                budget_path=Path(runtime["engineering_budget"]["path"]),
                project_id="rf_octupole_ion_optics",
                solver="simion",
                runtime_profile_id=runtime["runtime_profile_id"],
                design_profile_id=runtime["design_profile_id"],
                retention_class="compact",
            )
        old_runtime = resolve_runtime_profile(REPO_ROOT, "rf_octupole_ion_optics", "through_exit_no_acceleration_n100")
        self.assertEqual(runtime["design_profile_resolution"], old_runtime["design_profile_resolution"])
        self.assertEqual(runtime["particle_source"]["particle_count"], 100)
        self.assertNotIn("path", runtime["particle_source"])
        numerics = copy.deepcopy(runtime["solver_numerics"]["simion"]["values"])
        self.assertEqual(numerics["trajectory"]["maximum_global_time_us"], 80.0 * math.sqrt(524.0 / 100.0))
        numerics["trajectory"]["maximum_global_time_us"] = 80.0
        self.assertEqual(numerics, old_runtime["solver_numerics"]["simion"]["values"])
        old_budget = load(PROJECT_ROOT / "config/qualification/through_exit_functional_budget.json")
        new_budget = load(Path(runtime["engineering_budget"]["path"]))
        self.assertEqual(new_budget["pilot_authorization"]["limits"], old_budget["pilot_authorization"]["limits"])
        self.assertEqual(new_budget["pilot_authorization"]["scope"]["allowed_solvers"], ["simion"])
        self.assertFalse(new_budget["full_matrix_authorization"]["authorized"])
        self.assertEqual(budget["limits"]["wall_clock_seconds"], 720)
        resolved = resolve_design_profile(REPO_ROOT, "rf_octupole_ion_optics", runtime["design_profile_id"])[
            "resolved_design"
        ]
        self.assertEqual(resolved["drive"]["rf_amplitude_V_zero_to_peak_per_group"], 139.81792)
        self.assertEqual(resolved["drive"]["frequency_Hz"], 1100000.0)

    def test_524da_release_changes_speed_without_replacing_the_original_mother(self) -> None:
        runtime = resolve_runtime_profile(
            REPO_ROOT, "rf_octupole_ion_optics", "through_exit_no_acceleration_524da_n100"
        )
        resolved = resolve_design_profile(REPO_ROOT, "rf_octupole_ion_optics", runtime["design_profile_id"])[
            "resolved_design"
        ]
        old_runtime = resolve_runtime_profile(REPO_ROOT, "rf_octupole_ion_optics", "through_exit_no_acceleration_n100")
        with Path(old_runtime["particle_source"]["path"]).open(encoding="utf-8", newline="") as stream:
            original = list(csv.DictReader(stream))
        with tempfile.TemporaryDirectory(prefix="octupole-524da-release-") as directory:
            root = Path(directory)
            frozen = root / "release_spec.json"
            shutil.copyfile(runtime["particle_source"]["release_spec"]["path"], frozen)
            source, receipt = root / "source.csv", root / "receipt.json"
            with patch.object(
                release_sampler,
                "generate_mt19937_disk_cone_rf_phase_states",
                wraps=release_sampler.generate_mt19937_disk_cone_rf_phase_states,
            ) as sample:
                materialize_source_release(frozen, source, receipt, resolved)
                metadata, states = load_validated_source(
                    source, resolved, release_spec_path=frozen, release_receipt_path=receipt
                )
                self.assertEqual(sample.call_count, 1)
            self.assertEqual(
                (metadata["particle_count"], metadata["mass_amu"], metadata["charge_state"]), (100, 524.0, 1)
            )
            self.assertEqual(len(states), len(original))
            speed_scale = math.sqrt(100.0 / 524.0)
            # Binary64 roundoff from speed, unit-vector and CSV repr operations.
            roundoff = 8 * sys.float_info.epsilon
            for before, after in zip(original, states, strict=True):
                for field in ("particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "charge_state"):
                    self.assertEqual(float(after[field]), float(before[field]), field)
                old_velocity = [float(before[axis]) for axis in ("vx_m_s", "vy_m_s", "vz_m_s")]
                new_velocity = [float(after[axis]) for axis in ("vx_m_s", "vy_m_s", "vz_m_s")]
                for old, new in zip(old_velocity, new_velocity, strict=True):
                    self.assertTrue(math.isclose(new, old * speed_scale, rel_tol=roundoff))
                    self.assertTrue(
                        math.isclose(new / math.hypot(*new_velocity), old / math.hypot(*old_velocity), rel_tol=roundoff)
                    )
                self.assertEqual(float(after["mass_amu"]), 524.0)
            self.assertEqual(metadata["energy_model"]["kinetic_energy_eV"], 2.0)

    def test_simion_factorial_profiles_and_independent_budgets_are_bound(self) -> None:
        numerics = load(PROJECT_ROOT / "config/simion_solver_numerics.json")["profiles"]
        runtime = load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"]
        prereg = load(CAMPAIGN / "simion_preregistration.json")
        self.assertEqual([arm["arm"] for arm in prereg["ordered_arms"]], list(SIMION_ARMS))
        for arm, (suffix, cell, steps, run_serial) in SIMION_ARMS.items():
            numerics_id = f"simion_followup_{arm}_{suffix}"
            runtime_id = f"no_acceleration_full_length_n100_simion_followup_{arm}_{suffix}"
            self.assertEqual(numerics[numerics_id]["cell_mm_xyz"], cell)
            self.assertEqual(numerics[numerics_id]["trajectory"]["rf_steps_per_period"], steps)
            self.assertEqual(runtime[runtime_id]["simion_solver_numerics_profile_id"], numerics_id)
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

    def _assert_selected_arms(self, prereg: dict, runtime: dict, numerics: dict) -> None:
        """Bind only the consumed arm profiles; registries may gain unrelated rows."""
        solver = prereg["scope"]["solver"]
        for arm in prereg["ordered_arms"]:
            budget = load(PROJECT_ROOT / arm["engineering_budget_path"])
            scope = budget["pilot_authorization"]["scope"]
            self.assertEqual(scope["design_profile_id"], prereg["scope"]["design_profile_id"])
            self.assertEqual(scope["particle_source_profile_id"], prereg["scope"]["particle_source_profile_id"])
            self.assertEqual(scope["particle_count"], prereg["scope"]["particle_count"])
            self.assertEqual(scope["authorized_run_id"], arm["authorized_run_id"])
            self.assertEqual(scope["runtime_profile_id"], arm["runtime_profile_id"])
            expected_runtime = {
                "engineering_budget_path": arm["engineering_budget_path"],
                "design_profile_id": scope["design_profile_id"],
                "particle_source_profile_id": scope["particle_source_profile_id"],
                **{
                    f"{name}_solver_numerics_profile_id": profile
                    for name, profile in scope["solver_numerics_profile_ids"].items()
                },
            }
            selected_runtime = copy.deepcopy(runtime[arm["runtime_profile_id"]])
            self.assertEqual(selected_runtime.pop("stop_stage", "transport"), scope["stop_stage"])
            self.assertEqual(selected_runtime, expected_runtime)
            numerical_id = arm[f"{solver}_solver_numerics_profile_id"]
            self.assertEqual(scope["solver_numerics_profile_ids"][solver], numerical_id)
            if solver == "simion":
                expected_numerics = {"cell_mm_xyz": arm["cell_mm_xyz"], "trajectory_quality": 10}
            else:
                expected_numerics = copy.deepcopy(COMSOL_FOLLOWUP_FIELD_NUMERICS)
                self.assertEqual(
                    expected_numerics["mesh"]["hybrid"]["sensitive_region"]["exit_interface_refinement"][
                        "maximum_element_size_mm"
                    ],
                    arm["exit_radius_mm"],
                )
            expected_numerics["trajectory"] = {
                "rf_steps_per_period": arm["rf_steps_per_period"],
                "maximum_global_time_us": 80.0,
            }
            self.assertEqual(numerics[numerical_id], expected_numerics)

    def test_preregistered_selected_arms_reject_semantic_drift_and_allow_unrelated_profiles(self) -> None:
        prereg = load(CAMPAIGN / "simion_preregistration.json")
        runtime = load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"]
        numerics = load(PROJECT_ROOT / "config/simion_solver_numerics.json")["profiles"]
        # Extra rows must not change the identity or meaning of an existing arm.
        runtime["unrelated_experiment"] = {"unrelated": True}
        numerics["unrelated_experiment"] = {"unrelated": True}
        self._assert_selected_arms(prereg, runtime, numerics)
        arm = prereg["ordered_arms"][0]
        changed_runtime = copy.deepcopy(runtime)
        changed_runtime[arm["runtime_profile_id"]]["particle_source_profile_id"] = "planar_524da_2ev_n100"
        with self.assertRaises(AssertionError):
            self._assert_selected_arms(prereg, changed_runtime, numerics)
        changed_numerics = copy.deepcopy(numerics)
        changed_numerics[arm["simion_solver_numerics_profile_id"]]["trajectory"]["rf_steps_per_period"] *= 2
        with self.assertRaises(AssertionError):
            self._assert_selected_arms(prereg, runtime, changed_numerics)

    def test_preregistrations_are_frozen_before_run(self) -> None:
        simion = load(CAMPAIGN / "simion_preregistration.json")
        comsol = load(CAMPAIGN / "comsol_preregistration.json")
        self.assertEqual(comsol["resolution_contract"], simion["resolution_contract"])
        for prereg in (simion, comsol):
            self.assertTrue(all(not arm["executed"] for arm in prereg["ordered_arms"]))
            # These are actual immutable inputs. Whole-registry hashes remain
            # historical provenance; no complete old registry copy was retained.
            references = [prereg["resolution_contract"], *prereg["frozen_authorities"]["budgets"]]
            solver = prereg["scope"]["solver"]
            self._assert_selected_arms(
                prereg,
                load(PROJECT_ROOT / "config/runtime_profiles.json")["profiles"],
                load(PROJECT_ROOT / f"config/{solver}_solver_numerics.json")["profiles"],
            )
            for reference in references:
                self.assertEqual(
                    reference["sha256"],
                    file_sha256(REPO_ROOT / reference["path"]),
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


if __name__ == "__main__":
    unittest.main()
