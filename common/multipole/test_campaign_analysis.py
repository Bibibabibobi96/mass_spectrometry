from __future__ import annotations

import unittest

from common.multipole.campaign_analysis import compare_modes, compare_pair


def arm(project: str, run_id: str, *, offset: float = 0.0) -> dict:
    return {
        "project_id": project,
        "run_id": run_id,
        "particle_source_sha256": "A" * 64,
        "centroid_x_mm": offset,
        "centroid_y_mm": 0.0,
        "transmission": 1.0,
        "centered_spatial_rms_spread_mm": 0.4 + offset,
        "mean_direction_tilt_deg": 0.1 + offset,
        "centered_angular_rms_spread_deg": 3.0 + offset,
        "mean_energy_eV": 2.0 + offset,
        "centered_rms_energy_spread_eV": 0.1 + offset,
        "mean_elapsed_time_us": 40.0 + offset,
        "centered_rms_elapsed_time_spread_us": 0.2 + offset,
        "p95_radius_mm": 0.8 + offset,
        "p99_radius_mm": 0.9 + offset,
        "p95_divergence_deg": 5.0 + offset,
        "p99_divergence_deg": 6.0 + offset,
    }


class CampaignAnalysisTests(unittest.TestCase):
    def test_pair_reports_segmented_minus_no_acceleration(self) -> None:
        result = compare_pair(arm("p", "left"), arm("p", "right", offset=0.25))
        self.assertAlmostEqual(result["centroid_shift_mm"], 0.25)
        self.assertAlmostEqual(
            result["segmented_minus_no_acceleration"]["mean_energy_eV"], 0.25
        )

    def test_pair_rejects_different_project_or_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "project or particle source"):
            compare_pair(arm("left", "a"), arm("right", "b"))
        changed = arm("left", "b")
        changed["particle_source_sha256"] = "B" * 64
        with self.assertRaisesRegex(ValueError, "project or particle source"):
            compare_pair(arm("left", "a"), changed)

    def test_named_pair_freezes_right_minus_left_direction(self) -> None:
        result = compare_modes(
            arm("p", "segmented"),
            arm("p", "endface", offset=-0.2),
            left_mode="segmented_acceleration",
            right_mode="exit_aperture_plate_acceleration",
        )
        self.assertEqual(result["left_mode"], "segmented_acceleration")
        self.assertEqual(result["right_mode"], "exit_aperture_plate_acceleration")
        self.assertAlmostEqual(
            result["right_minus_left"]["centered_angular_rms_spread_deg"],
            -0.2,
        )


if __name__ == "__main__":
    unittest.main()
