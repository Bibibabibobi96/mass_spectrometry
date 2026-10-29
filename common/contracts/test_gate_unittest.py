"""Behavioral checks for the gate unittest runner."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class GateUnittestTests(unittest.TestCase):
    def test_failure_and_duration_are_reported_before_suite_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_probe.py"
            path.write_text(
                "import unittest\nclass Probe(unittest.TestCase):\n"
                "    def test_a_failure(self): self.fail('FIRST_FAILURE')\n"
                "    def test_b_pass(self): pass\n", encoding="utf-8")
            root = Path(__file__).resolve().parents[2]
            env = dict(os.environ, PYTHONPATH=str(root))
            result = subprocess.run(
                [sys.executable, "-m", "common.gate_unittest", "test_probe"], cwd=directory,
                env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.count("TEST_DURATION_SECONDS="), 2)
            self.assertLess(result.stderr.index("TEST_FAILURE_IMMEDIATE="),
                            result.stderr.index("TEST_DURATION_SECONDS="))
            self.assertLess(result.stderr.index("FIRST_FAILURE"), result.stderr.index("Ran 2 tests"))


    def test_failed_subtest_reports_traceback_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_probe.py"
            path.write_text(
                "import unittest\nclass Probe(unittest.TestCase):\n"
                "    def test_subtests(self):\n"
                "        for value in (1, 2):\n"
                "            with self.subTest(value=value): self.assertEqual(value, 0, 'SUBTEST_FAILURE')\n",
                encoding="utf-8")
            root = Path(__file__).resolve().parents[2]
            result = subprocess.run(
                [sys.executable, "-m", "common.gate_unittest", "test_probe"], cwd=directory,
                env=dict(os.environ, PYTHONPATH=str(root)), capture_output=True, text=True,
                encoding="utf-8", timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.count("TEST_FAILURE_IMMEDIATE="), 2)
            self.assertLess(result.stderr.index("SUBTEST_FAILURE"), result.stderr.index("Ran 1 test"))


if __name__ == "__main__":
    unittest.main()
