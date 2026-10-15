from __future__ import annotations

import json
from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
    measured_prism_jacobian,
)


class TwoPrismOperatingPointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = Path(__file__).resolve().parents[2] / "config" / "simion_candidate_two_zone.json"

    def test_shared_measured_model_accepts_signed_columns_and_rejects_mixed_problem(self):
        def record(voltage, residual):
            return {
                "prism_voltages_v": voltage, "residual_vector": residual,
                "source_identity": {"source": "same"},
                "target_positive_mirror_turn_y_mm": 0.,
                "target_low_field_tangent_ratio_vy_over_vz": .5,
                "p2_low_field_reference_section": {"plane": 20.},
                "frozen_problem": {"mesh": "same"},
            }
        contract = json.loads(self.contract.read_text(encoding="utf-8"))
        seed = record([100., -100.], [-4., .05])
        p1 = record([99., -100.], [-4.2, -.02])
        p2 = record([100., -98.], [-3.86, .18])
        jacobian, steps, classification = measured_prism_jacobian(seed, p1, p2, contract)
        self.assertEqual(steps, [-1., 2.])
        self.assertAlmostEqual(jacobian[0, 0], .2)
        self.assertEqual(classification["status"], "square_exact")
        with self.assertRaises(CandidateContractError):
            measured_prism_jacobian(seed, p1, p2, contract, positive_steps=True)
        p2["frozen_problem"]["mesh"] = "changed"
        with self.assertRaises(CandidateContractError):
            measured_prism_jacobian(seed, p1, p2, contract)

    def test_shared_measured_model_rejects_rank_deficiency(self):
        def record(voltage, residual):
            return {
                "prism_voltages_v": voltage, "residual_vector": residual,
                "source_identity": {}, "target_positive_mirror_turn_y_mm": 0.,
                "target_low_field_tangent_ratio_vy_over_vz": .5,
                "p2_low_field_reference_section": {"plane": 20.},
            }
        contract = json.loads(self.contract.read_text(encoding="utf-8"))
        with self.assertRaises(CandidateContractError):
            measured_prism_jacobian(
                record([100., -100.], [1., 1.]),
                record([101., -100.], [2., 2.]),
                record([100., -99.], [2., 2.]), contract)


if __name__ == "__main__":
    unittest.main()
