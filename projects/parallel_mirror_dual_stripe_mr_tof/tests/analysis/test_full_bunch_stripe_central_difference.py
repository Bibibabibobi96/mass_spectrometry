from __future__ import annotations

import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_bunch_stripe_central_difference import (
    analyze_documents,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class FullBunchStripeCentralDifferenceTest(unittest.TestCase):
    def test_runner_passes_each_named_axis_path_explicitly(self) -> None:
        runner = (
            Path(__file__).resolve().parents[2]
            / "analysis"
            / "run_full_bunch_stripe_central_difference.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("$option='--'+$name.Replace('_','-')", runner)
        self.assertIn("$arguments+=@($option,[string]$runs[$name])", runner)

    def _state(self, run_id: str, s1: float, s2: float, shift: float) -> dict:
        inputs = {
            key: f"C:/frozen/{key}/run_manifest.json"
            for key in (
                "geometry_run_manifest", "mirror_run_manifest", "stripe_run_manifest",
                "accelerator_run_manifest", "local_workbench_run_manifest",
                "bunch_source_run_manifest",
            )
        }
        config = {
            "run_id": run_id,
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "finite_3d_two_prism_voltage_trial",
            "inputs": inputs,
            "parameters": {
                "stripe_biases_v": [s1, s2],
                "prism_1_voltage_v": 190.0,
                "prism_2_voltage_v": -190.0,
                "source_particle_count": 100,
                "source_selection": None,
                "source_cohort": {"particle_states_sha256": "same"},
                "trajectory_profile": {"profile_id": "screen", "trajectory_quality": 8.0},
                "accelerator_pulse": {"mode": "static"},
            },
        }
        cohort = {
            "event_integrity_passed": True,
            "integrity_errors": [],
            "expected_particle_count": 100,
            "particle_terminal_count": 100,
            "all_losses_retained": True,
            "detector_hit_count": 90 + shift,
            "electrode_collision_count": 10 - shift,
            "detection_rate": 0.9 + shift / 100.0,
            "target_k_fraction": 1.0,
            "detector_tof_median_us": 800.0 + shift,
            "detector_tof_fwhm_us": 0.02 + shift * 0.001,
            "mass_resolution_t_over_2fwhm": 20000.0 + shift,
            "target_k_handoff_tof_fwhm_us": 0.01 + shift * 0.001,
            "effective_axial_width_W_median_mm": 587.0 + shift,
            "target_k_phase_y_residuals_mm": [shift] * 100,
        }
        return {"config": config, "summary": {"cohort_analysis": cohort}}

    def _states(self) -> dict:
        return {
            "s1_minus": self._state("s1m", -25.025, 50.0, -2.0),
            "s1_plus": self._state("s1p", -24.975, 50.0, 2.0),
            "s2_minus": self._state("s2m", -25.0, 49.975, -1.0),
            "s2_plus": self._state("s2p", -25.0, 50.025, 1.0),
        }

    def test_reports_symmetric_two_axis_derivatives(self) -> None:
        result = analyze_documents(self._states())
        self.assertEqual(result["center_stripe_biases_v"], [-25.0, 50.0])
        self.assertAlmostEqual(result["central_difference_step_v"], 0.025)
        self.assertAlmostEqual(
            result["central_difference_derivatives_per_v"]["detector_hit_count"][0],
            80.0,
        )
        self.assertAlmostEqual(
            result["central_difference_derivatives_per_v"]["detector_hit_count"][1],
            40.0,
        )
        self.assertIsNotNone(result["local_fwhm_descent_unit_direction_dS1_dS2"])

    def test_rejects_changed_frozen_source_or_non_axis_aligned_point(self) -> None:
        states = self._states()
        states["s2_plus"]["config"]["parameters"]["source_cohort"] = {"particle_states_sha256": "other"}
        with self.assertRaises(CandidateContractError):
            analyze_documents(states)
        states = self._states()
        states["s1_plus"]["config"]["parameters"]["stripe_biases_v"][1] += 0.01
        with self.assertRaises(CandidateContractError):
            analyze_documents(states)

    def test_rejects_filtered_or_incomplete_cohort(self) -> None:
        states = self._states()
        states["s1_plus"]["summary"]["cohort_analysis"]["all_losses_retained"] = False
        with self.assertRaises(CandidateContractError):
            analyze_documents(states)


if __name__ == "__main__":
    unittest.main()
