from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    OPPOSITE_MIRROR_TURN,
    resolve_drift_phase_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class DriftPhaseContractTest(unittest.TestCase):
    def test_opposite_turn_derives_half_period_without_duplicate_baseline_value(self) -> None:
        resolved = resolve_drift_phase_contract({
            "nominal": {
                "target_drift_period_ratio": 25.5,
                "fast_path_symmetry": OPPOSITE_MIRROR_TURN,
            }
        })
        self.assertEqual(resolved.complete_oscillation_count, 25)
        self.assertEqual(resolved.target_period_ratio, 25.5)
        self.assertEqual(resolved.target_half_oscillation_count, 51)
        self.assertEqual(resolved.origin_mirror_side, 1)
        self.assertEqual(resolved.return_mirror_side, -1)

    def test_missing_or_same_turn_phase_fails_closed(self) -> None:
        for phase in (None, "same_positive_mirror_turn"):
            with self.subTest(phase=phase), self.assertRaises(CandidateContractError):
                resolve_drift_phase_contract({
                    "nominal": {
                        "target_drift_period_ratio": 25.5,
                        "fast_path_symmetry": phase,
                    }
                })

    def test_any_positive_half_integer_is_parameterized(self) -> None:
        resolved = resolve_drift_phase_contract({
            "nominal": {
                "target_drift_period_ratio": 31.5,
                "fast_path_symmetry": OPPOSITE_MIRROR_TURN,
            }
        })
        self.assertEqual(resolved.target_period_ratio, 31.5)
        self.assertEqual(resolved.target_half_oscillation_count, 63)

    def test_integer_ratio_conflicts_with_opposite_turn_symmetry(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "half-integer"):
            resolve_drift_phase_contract({
                "nominal": {
                    "target_drift_period_ratio": 25,
                    "fast_path_symmetry": OPPOSITE_MIRROR_TURN,
                }
            })


if __name__ == "__main__":
    unittest.main()
