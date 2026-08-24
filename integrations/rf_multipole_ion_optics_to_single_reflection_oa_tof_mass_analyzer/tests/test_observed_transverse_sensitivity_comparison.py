from __future__ import annotations

import copy
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.compare_observed_transverse_sensitivity import (
    ARM_AFFINE_FIXED,
    ARM_C,
    ARM_D,
    ARM_OBSERVED_FIXED,
    SEQUENTIAL_ARMS,
    _comparable_versioned_input,
    _sequential_authority_gate,
    _sequential_mode_requested,
    compare_frames,
    compare_sequential_frames,
    main,
)


def _frame(offset: float = 0.0, count: int = 100) -> pd.DataFrame:
    rows = []
    for particle_id in range(1, count + 1):
        for event in (
            "source_release",
            "pre_pulse_state",
            "accelerator_grid1_forward",
            "accelerator_intermediate2_forward",
            "local_accelerator_exit",
            "accelerator_focus_forward",
            "reflectron_entrance_forward",
            "reflectron_midgrid_forward",
            "reflectron_turning_point",
            "reflectron_exit_return",
            "detector_crossing",
        ):
            rows.append(
                {
                    "particle_id": particle_id,
                    "event": event,
                    "instrument_time_us": 10.0 + particle_id * 1e-3 + offset,
                    "x_mm": float(particle_id) + offset,
                    "y_mm": offset,
                    "z_mm": 0.0,
                    "vx_mm_per_us": 1.0 + offset,
                    "vy_mm_per_us": 2.0,
                    "vz_mm_per_us": 3.0,
                }
            )
    return pd.DataFrame(rows)


def _authority_arm(arm_name: str) -> dict[str, object]:
    arm_sha256s = {name: str(index) * 64 for index, name in enumerate(SEQUENTIAL_ARMS, 1)}
    base_invariants = {
        "full_observed_velocity_preserved": True,
        "full_observed_position_common_translation": True,
        "collapsed_z_vz_energy_clock_equal_full": True,
        "collapsed_x_y_equal_current_center": True,
        "collapsed_vy_zero": True,
        "collapsed_positive_vx_preserves_transverse_speed": True,
        "energy_recomputed_from_velocity": True,
        "all_arms_observed_z_id_clock_equal": True,
        "affine_arm_vz_from_frozen_authority": True,
        "observed_fixed_arm_observed_vz_preserved": True,
        "fixed_10eV_arms_energy_equal": True,
        "fixed_10eV_arms_centered_xy_vy_zero_positive_vx": True,
    }
    projection = {
        "method": "observed_z_four_arm_energy_decomposition_v2",
        "fixed_kinetic_energy_eV": 15.5,
        "affine_authority": {
            "mean_velocity_z_m_per_s": 1.0,
            "velocity_z_slope_m_per_s_per_mm": 2.0,
            "center_z_mm": 3.0,
        },
        "old_center_mm": [0.0, 0.0, 0.0],
        "current_center_mm": [0.0, 0.0, 1.0],
        "translation_mm": [0.0, 0.0, 1.0],
        "old_instrument_time_us": 1.0,
        "current_instrument_time_us": 2.0,
        "simulation_to_source_particle_id": [
            {"simulation_particle_id": value, "source_particle_id": value} for value in range(1, 101)
        ],
    }
    return {
        "source_identity": {
            "run_id": "source",
            "observed_pre_pulse_projection": {
                "authority_manifest": {"path": "manifest", "sha256": "A" * 64},
                "arm_id": arm_name,
            },
        },
        "child_parameters": {"layout_profile_id": "three-zone", "rf_steps_per_period": 160},
        "child_input_sha256s": {"oatof_resolved_geometry": "B" * 64},
        "versioned_child_inputs": {
            "pulse_schedule": {"pulse_effective_time_us": 9.0},
            "runtime_binding": {"connection_profile_id": "three-zone"},
            "resolved_connection": {"potential_alignment": {"mode": "exact"}},
        },
        "projection_receipt_document": {
            "authorities": {
                name: {"sha256": value * 64}
                for name, value in (
                    ("manifest", "C"),
                    ("prepared_arms", "D"),
                    ("observed_state", "E"),
                    ("old_geometry", "F"),
                )
            },
            "projection": projection,
            "arms": {name: {"sha256": sha} for name, sha in arm_sha256s.items()},
            "invariants": base_invariants,
        },
    }


class ObservedTransverseSensitivityComparisonTests(unittest.TestCase):
    def test_cli_help_describes_pairwise_and_sequential_responsibilities(self) -> None:
        output = io.StringIO()
        with patch("sys.argv", ["compare-observed-source", "--help"]), redirect_stdout(output):
            with self.assertRaisesRegex(SystemExit, "0"):
                main()
        help_text = output.getvalue()
        self.assertIn("observed-source transverse sensitivity", help_text)
        self.assertIn("sequential source", help_text)
        self.assertIn("attribution.", help_text)
        self.assertIn("Observed-energy transverse-collapsed parent", help_text)
        self.assertIn("Full-observed-6D parent", help_text)

    def test_four_arm_sequential_decomposition_closes_at_every_event(self) -> None:
        frames = {
            ARM_AFFINE_FIXED: _frame(0.0, count=37),
            ARM_OBSERVED_FIXED: _frame(1e-3, count=37),
            ARM_C: _frame(3e-3, count=37),
            ARM_D: _frame(6e-3, count=37),
        }
        result, rows = compare_sequential_frames(frames, {name: 9.0 for name in SEQUENTIAL_ARMS})
        self.assertEqual(result["status"], "FUNCTIONAL_ONLY")
        self.assertFalse(result["formal_gate_passed"])
        self.assertTrue(result["decomposition"]["order_dependent"])
        self.assertFalse(result["decomposition"]["factorial_effects"])
        self.assertEqual(result["decomposition"]["arm_order"], list(SEQUENTIAL_ARMS))
        self.assertEqual(result["paired_particle_count"], 37)
        self.assertEqual(len(rows), 11 * 37)
        detector = result["events"]["detector_crossing"]
        closure = detector["telescoping_closure_residual"]["time_ns"]
        self.assertLess(closure["max_abs"], 1e-10)
        self.assertAlmostEqual(
            detector["adjacent_transitions"]["affine_to_observed_zvz"]["time_ns"]["mean"],
            1.0,
        )
        self.assertIn("accelerator_focus_forward", result["peak_metrics"])
        self.assertIsNone(result["thresholds"])
        self.assertFalse(result["qualification_decision_made"])

    def test_four_arm_authority_gate_rejects_pa_and_source_mismatch(self) -> None:
        arms = {name: _authority_arm(name) for name in SEQUENTIAL_ARMS}
        _sequential_authority_gate(arms)
        pa_mismatch = copy.deepcopy(arms)
        pa_mismatch[ARM_D]["child_input_sha256s"]["oatof_resolved_geometry"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "PA, geometry, numerics"):
            _sequential_authority_gate(pa_mismatch)
        source_mismatch = copy.deepcopy(arms)
        source_mismatch[ARM_C]["source_identity"]["run_id"] = "different"
        with self.assertRaisesRegex(ContractError, "source, PA"):
            _sequential_authority_gate(source_mismatch)
        receipt_mismatch = copy.deepcopy(arms)
        receipt_mismatch[ARM_D]["projection_receipt_document"]["authorities"]["manifest"]["sha256"] = "9" * 64
        with self.assertRaisesRegex(ContractError, "source, PA"):
            _sequential_authority_gate(receipt_mismatch)
        versioned_physics_mismatch = copy.deepcopy(arms)
        versioned_physics_mismatch[ARM_D]["versioned_child_inputs"]["pulse_schedule"]["pulse_effective_time_us"] = 9.1
        with self.assertRaisesRegex(ContractError, "source, PA"):
            _sequential_authority_gate(versioned_physics_mismatch)

    def test_versioned_input_normalization_excludes_only_preregistered_identity(self) -> None:
        pulse = {
            "campaign_id": "campaign-a",
            "experiment_id": "arm-a",
            "experiment_row_sha256": "A" * 64,
            "pulse_effective_time_us": 9.0,
        }
        pulse_other_arm = copy.deepcopy(pulse)
        pulse_other_arm.update(campaign_id="campaign-b", experiment_id="arm-b", experiment_row_sha256="B" * 64)
        self.assertEqual(
            _comparable_versioned_input("pulse_schedule", pulse),
            _comparable_versioned_input("pulse_schedule", pulse_other_arm),
        )
        pulse_other_arm["pulse_effective_time_us"] = 9.1
        self.assertNotEqual(
            _comparable_versioned_input("pulse_schedule", pulse),
            _comparable_versioned_input("pulse_schedule", pulse_other_arm),
        )

        runtime = {
            "connection_profile_id": "three-zone",
            "implementation_binding": {"path": "runner.ps1", "sha256": "A" * 64},
        }
        runtime_other_version = copy.deepcopy(runtime)
        runtime_other_version["implementation_binding"]["sha256"] = "B" * 64
        self.assertEqual(
            _comparable_versioned_input("runtime_binding", runtime),
            _comparable_versioned_input("runtime_binding", runtime_other_version),
        )
        runtime_other_version["connection_profile_id"] = "two-zone"
        self.assertNotEqual(
            _comparable_versioned_input("runtime_binding", runtime),
            _comparable_versioned_input("runtime_binding", runtime_other_version),
        )

        connection = {
            "sources": {
                "profile_sha256": "A" * 64,
                **{
                    name: {"path": f"run-a/{name}.json", "sha256": "A" * 64}
                    for name in (
                        "upstream_port",
                        "downstream_port",
                        "upstream_authority",
                        "downstream_authority",
                        "profile_registry",
                    )
                },
            },
            "potential_alignment": {"mode": "exact"},
        }
        connection_other_run = copy.deepcopy(connection)
        connection_other_run["sources"]["profile_registry"] = {
            "path": "run-b/registry.json",
            "sha256": "B" * 64,
        }
        self.assertEqual(
            _comparable_versioned_input("resolved_connection", connection),
            _comparable_versioned_input("resolved_connection", connection_other_run),
        )
        connection_other_run["potential_alignment"]["mode"] = "offset"
        self.assertNotEqual(
            _comparable_versioned_input("resolved_connection", connection),
            _comparable_versioned_input("resolved_connection", connection_other_run),
        )

    def test_four_arm_parent_arguments_are_all_or_none(self) -> None:
        self.assertFalse(_sequential_mode_requested(None, None))
        self.assertTrue(_sequential_mode_requested("affine", "observed"))
        with self.assertRaisesRegex(ContractError, "all-or-none"):
            _sequential_mode_requested("affine", None)

    def test_four_arm_missing_arm_or_clock_mismatch_fails_closed(self) -> None:
        frames = {
            ARM_AFFINE_FIXED: _frame(0.0),
            ARM_OBSERVED_FIXED: _frame(1e-3),
            ARM_C: _frame(2e-3),
        }
        with self.assertRaisesRegex(ContractError, "exactly four named frames"):
            compare_sequential_frames(frames, {name: 9.0 for name in frames})
        frames[ARM_D] = _frame(3e-3)
        clocks = {name: 9.0 for name in frames}
        clocks[ARM_D] = 9.1
        with self.assertRaisesRegex(ContractError, "different pulse-effective clocks"):
            compare_sequential_frames(frames, clocks)

    def test_nonempty_exactly_paired_detector_cohort(self) -> None:
        peak = {"mean_tof_us": 1.0, "std_tof_ns": 2.0, "direct_fwhm_tof_ns": 3.0, "mass_resolution": 4.0}
        result, rows = compare_frames(_frame(count=37), _frame(1e-3, count=37), peak, peak)
        self.assertEqual(result["status"], "FUNCTIONAL_ONLY")
        self.assertFalse(result["formal_gate_passed"])
        self.assertEqual(len(rows), 37)
        self.assertAlmostEqual(rows[0]["delta_time_full_minus_collapsed_ns"], 1.0)
        self.assertEqual(result["detector_identity"]["transverse_collapsed_particles"], 37)
        self.assertAlmostEqual(result["peak_metrics"]["full_minus_collapsed"]["std_tof_pct"], 0.0)

    def test_missing_detector_velocity_is_published_as_null(self) -> None:
        peak = {"mean_tof_us": 1.0, "std_tof_ns": 2.0, "direct_fwhm_tof_ns": 3.0, "mass_resolution": 4.0}
        c_frame = _frame()
        d_frame = _frame(1e-3)
        for frame in (c_frame, d_frame):
            frame[["vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us"]] = float("nan")
        result, rows = compare_frames(c_frame, d_frame, peak, peak)
        self.assertIsNone(rows[0]["delta_vx_full_minus_collapsed_m_s"])
        velocity = result["paired_detector_deltas_full_minus_collapsed"]["velocity_delta_norm_m_s"]
        self.assertEqual(velocity["available_count"], 0)
        self.assertIsNone(velocity["rms"])

    def test_missing_detector_id_fails_closed(self) -> None:
        peak = {"mean_tof_us": 1.0, "std_tof_ns": 2.0, "direct_fwhm_tof_ns": 3.0, "mass_resolution": 4.0}
        with self.assertRaisesRegex(ContractError, "nonempty and exactly paired"):
            compare_frames(_frame(), _frame(count=99), peak, peak)


if __name__ == "__main__":
    unittest.main()
