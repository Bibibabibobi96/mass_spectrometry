"""Tests for reduction of paired real-field J2 derivatives."""

from __future__ import annotations

import copy
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_j2_real_field_sensitivity import (
    build_j2_real_field_sensitivity_receipt,
)


def _observations() -> dict[str, object]:
    return {
        "role": "oatof_paper1_real_field_central_difference_observations",
        "source_id": "s1_terminal_octupole",
        "candidate_pool_sha256": "A" * 64,
        "state_names": ["x_mm", "y_mm", "z_mm", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s"],
        "state_steps": [0.1, 0.2, 0.5, 10.0, 20.0, 50.0],
        "numeric_identity_sha256": "B" * 64,
        "candidates": [
            {"candidate_id": "baseline", "plus_arrival_time_us": [10.2, 10.4, 11.5, 12.0, 14.0, 16.0], "minus_arrival_time_us": [9.8, 9.6, 10.5, 8.0, 6.0, 4.0]},
            {"candidate_id": "shape_a", "plus_arrival_time_us": [10.1, 10.2, 10.5, 11.0, 12.0, 13.0], "minus_arrival_time_us": [9.9, 9.8, 9.5, 9.0, 8.0, 7.0]},
        ],
    }


class Paper1J2RealFieldSensitivityTests(unittest.TestCase):
    def test_reduces_paired_derivatives_without_detector_metrics(self) -> None:
        receipt = build_j2_real_field_sensitivity_receipt(_observations())
        self.assertEqual(receipt["method"], "paired_central_difference_real_field_v1")
        self.assertEqual(len(receipt["candidates"][0]["time_gradient_us_per_state"]), 6)
        for actual, expected in zip(receipt["candidates"][0]["time_gradient_us_per_state"], [2.0, 2.0, 1.0, 0.2, 0.2, 0.12]):
            self.assertAlmostEqual(actual, expected)
        self.assertNotIn("fwhm", receipt)
        self.assertEqual(len(receipt["finite_difference_observations_sha256"]), 64)

    def test_rejects_mismatched_state_or_duplicate_candidate(self) -> None:
        invalid = copy.deepcopy(_observations())
        invalid["state_names"][0] = "z_mm"
        with self.assertRaisesRegex(ValueError, "state order"):
            build_j2_real_field_sensitivity_receipt(invalid)
        invalid = copy.deepcopy(_observations())
        invalid["candidates"][1]["candidate_id"] = "baseline"
        with self.assertRaisesRegex(ValueError, "unique"):
            build_j2_real_field_sensitivity_receipt(invalid)


if __name__ == "__main__":
    unittest.main()
