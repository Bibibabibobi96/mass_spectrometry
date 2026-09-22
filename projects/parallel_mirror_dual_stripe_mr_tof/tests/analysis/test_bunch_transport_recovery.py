from __future__ import annotations

import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_transport_recovery import plan, rank


class BunchTransportRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workpoint = {"selected_workpoint": {"voltages_v": [-24.0, 52.0, 196.0, -195.0]}}
        self.theory = {"selected_seed": {"stripe_biases_v": [-50.0, 100.0]}}

    def test_plan_is_s_only_and_bounded(self) -> None:
        result = plan(self.workpoint, self.theory)
        self.assertEqual(result["probe_particle_count"], 100)
        self.assertEqual(len(result["candidates"]), 2)
        for candidate in result["candidates"]:
            self.assertEqual(candidate["voltages_v"][2:], [196.0, -195.0])

    def test_rank_requires_integrity_and_hard_minimum(self) -> None:
        document = plan(self.workpoint, self.theory)
        selected = rank(document, [
            {"purpose": "theory_stripe_seed", "cohort_analysis": {"event_integrity_passed": True, "detection_rate": 0.39, "target_k_fraction": 0.8}},
            {"purpose": "stripe_midpoint_to_theory", "cohort_analysis": {"event_integrity_passed": True, "detection_rate": 0.42, "target_k_fraction": 0.2}},
        ])
        self.assertEqual(selected["status"], "selected")
        self.assertEqual(selected["selected"]["purpose"], "stripe_midpoint_to_theory")

    def test_failed_theory_direction_refreshes_independent_reverse_s_axes(self) -> None:
        result = plan(self.workpoint, self.theory, stage="reverse_axis")
        self.assertEqual(result["stage"], "reverse_axis")
        self.assertEqual([item["purpose"] for item in result["candidates"]], [
            "reverse_s1_half_theory", "reverse_s2_half_theory",
        ])
        self.assertEqual(result["candidates"][0]["voltages_v"], [-11.0, 52.0, 196.0, -195.0])
        self.assertEqual(result["candidates"][1]["voltages_v"], [-24.0, 28.0, 196.0, -195.0])


if __name__ == "__main__":
    unittest.main()
