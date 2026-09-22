import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_collection_gate import evaluate


class BunchCollectionGateTest(unittest.TestCase):
    def test_thresholds_are_explicit(self) -> None:
        for rate, status, stop in (
            (0.80, "accepted", False),
            (0.79, "warning_below_preferred", False),
            (0.41, "warning_below_preferred", False),
            (0.40, "below_hard_minimum", True),
        ):
            with self.subTest(rate=rate):
                result = evaluate({"event_integrity_passed": True, "detection_rate": rate})
                self.assertEqual(result["status"], status)
                self.assertEqual(result["hard_stop"], stop)

    def test_integrity_failure_stops(self) -> None:
        result = evaluate({"event_integrity_passed": False, "detection_rate": 1.0})
        self.assertTrue(result["hard_stop"])
        self.assertFalse(result["continue_downstream"])
