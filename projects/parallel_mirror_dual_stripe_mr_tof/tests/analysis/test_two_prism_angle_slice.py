from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_angle_slice import (
    AngleSliceControls,
    solve_p2_angle_slice_from_legal_anchor,
)


SIGNATURE = "branch-a"


def controls(**changes):
    values = dict(
        p2_bounds_v=(-10.0, 10.0),
        angle_ratio_root_tolerance=1e-9,
        p2_root_tolerance_v=1e-8,
        topology_boundary_tolerance_v=1e-6,
        maximum_evaluations=64,
    )
    values.update(changes)
    return AngleSliceControls(**values)


def legal(pair, residual):
    return {
        "status": "legal_topology",
        "topology_signature_sha256": SIGNATURE,
        "prism_voltages_v": list(pair),
        "residual_vector": [3.0, residual],
    }


class TwoPrismAngleSliceTests(unittest.TestCase):
    def test_analytic_prediction_can_be_the_root(self):
        def evaluate(pair):
            return legal(pair, pair[1] - 2.0)

        result = solve_p2_angle_slice_from_legal_anchor(
            evaluate,
            lambda _anchor: 2.0,
            legal_anchor_pair_v=(1.0, 0.0),
            expected_signature_sha256=SIGNATURE,
            controls=controls(),
        )
        self.assertEqual(result["status"], "angle_root_reached_at_analytic_prediction")
        self.assertEqual(result["selected_p2_voltage_v"], 2.0)
        self.assertEqual(result["selected_positive_mirror_turn_y_residual_mm"], 3.0)

    def test_legal_prediction_with_sign_change_is_bisected(self):
        def evaluate(pair):
            return legal(pair, pair[1] - 1.25)

        result = solve_p2_angle_slice_from_legal_anchor(
            evaluate,
            lambda _anchor: 2.0,
            legal_anchor_pair_v=(1.0, 0.0),
            expected_signature_sha256=SIGNATURE,
            controls=controls(),
        )
        self.assertEqual(result["status"], "angle_root_reached_by_bisection")
        self.assertAlmostEqual(result["selected_p2_voltage_v"], 1.25, places=8)
        self.assertEqual(result["selected_positive_mirror_turn_y_residual_mm"], 3.0)

    def test_invalid_prediction_localizes_topology_boundary_without_penalty(self):
        def evaluate(pair):
            if pair[1] > 1.0:
                return {"status": "invalid_topology", "failure": "wrong face"}
            return legal(pair, pair[1] - 2.0)

        result = solve_p2_angle_slice_from_legal_anchor(
            evaluate,
            lambda _anchor: 3.0,
            legal_anchor_pair_v=(1.0, 0.0),
            expected_signature_sha256=SIGNATURE,
            controls=controls(),
        )
        self.assertEqual(result["status"], "topology_boundary_before_angle_root")
        self.assertLessEqual(result["last_legal_p2_voltage_v"], 1.0)
        self.assertGreater(result["remote_p2_voltage_v"], 1.0)
        self.assertLess(result["last_legal_angle_ratio_residual"], 0.0)
        self.assertEqual(result["last_legal_positive_mirror_turn_y_residual_mm"], 3.0)
        self.assertTrue(any(item["status"] == "invalid_topology" for item in result["evaluations"]))

    def test_changed_signature_is_a_boundary(self):
        def evaluate(pair):
            record = legal(pair, pair[1] - 2.0)
            if pair[1] > 1.0:
                record["topology_signature_sha256"] = "branch-b"
            return record

        result = solve_p2_angle_slice_from_legal_anchor(
            evaluate,
            lambda _anchor: 3.0,
            legal_anchor_pair_v=(1.0, 0.0),
            expected_signature_sha256=SIGNATURE,
            controls=controls(),
        )
        self.assertEqual(result["status"], "topology_boundary_before_angle_root")

    def test_prediction_outside_domain_is_reported_without_clipping(self):
        result = solve_p2_angle_slice_from_legal_anchor(
            lambda pair: legal(pair, -1.0),
            lambda _anchor: 20.0,
            legal_anchor_pair_v=(1.0, 0.0),
            expected_signature_sha256=SIGNATURE,
            controls=controls(),
        )
        self.assertEqual(result["status"], "analytic_prediction_outside_p2_domain")
        self.assertEqual(result["analytic_predicted_p2_voltage_v"], 20.0)
        self.assertEqual(result["evaluation_count"], 1)


if __name__ == "__main__":
    unittest.main()
