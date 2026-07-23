from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from projects.oa_tof.analysis.compare_field_profiles import region_metrics
from projects.oa_tof.analysis.field_comparison_contract import (
    convergence_decision,
    merge_complete_samples,
    normalized_rms_difference_pct,
)


class FieldComparisonContractTest(unittest.TestCase):
    def test_merge_rejects_missing_sample_on_either_side(self) -> None:
        left = pd.DataFrame({"sample_id": [1, 2], "value": [10.0, 20.0]})
        right = pd.DataFrame({"sample_id": [1], "value": [10.0]})

        with self.assertRaisesRegex(ValueError, "sample coverage differs"):
            merge_complete_samples(
                left,
                right,
                keys=["sample_id"],
                left_label="COMSOL",
                right_label="SIMION",
            )

    def test_merge_rejects_duplicate_keys(self) -> None:
        left = pd.DataFrame({"sample_id": [1, 1], "value": [10.0, 20.0]})
        right = pd.DataFrame({"sample_id": [1], "value": [10.0]})

        with self.assertRaisesRegex(ValueError, "duplicate sample keys"):
            merge_complete_samples(
                left,
                right,
                keys=["sample_id"],
                left_label="COMSOL",
                right_label="SIMION",
            )

    def test_near_zero_reference_does_not_create_infinite_ratio(self) -> None:
        ratio = normalized_rms_difference_pct(
            np.zeros(3),
            np.asarray([0.0, 1.0e-12, -1.0e-12]),
        )
        self.assertIsNone(ratio["relative_to_reference_rms_pct"])
        self.assertTrue(np.isfinite(ratio["symmetric_scale_pct"]))

    def test_region_metrics_reports_near_zero_samples_without_inf(self) -> None:
        frame = pd.DataFrame(
            {
                "COMSOL_Ez_V_per_m": [0.0, 1.0, 1000.0],
                "SIMION_Ez_V_per_m": [1.0, 2.0, 1001.0],
            }
        )

        metrics = region_metrics(frame)

        self.assertGreater(metrics["near_zero_reference_points"], 0)
        self.assertTrue(np.isfinite(metrics["symmetric_normalized_rms_difference_pct"]))

    def test_convergence_without_acceptance_criteria_is_not_pass(self) -> None:
        decision = convergence_decision()

        self.assertEqual(decision["status"], "NOT_EVALUATED")
        self.assertEqual(decision["reason"], "NO_ACCEPTANCE_CRITERIA")


if __name__ == "__main__":
    unittest.main()
