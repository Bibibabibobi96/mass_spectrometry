import unittest

from msplatform.workflows.oa_mr.collection_gate import accepted_receipt, evaluate


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


class BunchCollectionGateRegressionTest(unittest.TestCase):
    def test_invalid_rates_and_receipt_policy(self) -> None:
        for value in (None, "0.8", float("nan"), float("inf"), -0.01, 1.01):
            with self.subTest(value=value):
                gate = evaluate({"event_integrity_passed": True, "detection_rate": value})
                self.assertEqual(gate["status"], "invalid_detection_rate")
                self.assertTrue(gate["hard_stop"])
        for rate in (0.4, 0.41, 0.8, 1.0):
            gate = evaluate({"event_integrity_passed": True, "detection_rate": rate})
            self.assertEqual(accepted_receipt(gate), rate >= 0.8)

    def test_module_cli_reads_whole_cohort_and_writes_receipt(self) -> None:
        import json
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observation = root / "observation.json"
            output = root / "nested" / "gate.json"
            for cohort in ({"event_integrity_passed": True, "detection_rate": 0.8}, None):
                with self.subTest(cohort=cohort):
                    observation.write_text(json.dumps({"cohort_analysis": cohort}), encoding="utf-8")
                    completed = subprocess.run(
                        [sys.executable, "-m", "msplatform.workflows.oa_mr.collection_gate",
                         "--observation", str(observation), "--output", str(output)],
                        capture_output=True, text=True, check=True,
                        cwd=Path(__file__).resolve().parents[4], timeout=30)
                    expected = evaluate(cohort if isinstance(cohort, dict) else {"event_integrity_passed": False})
                    self.assertEqual(json.loads(output.read_text(encoding="utf-8")), expected)
                    self.assertEqual(completed.stdout.strip(),
                                     f"MRTOF_BUNCH_COLLECTION_GATE={expected['status']} CONTINUE={expected['continue_downstream']}")
