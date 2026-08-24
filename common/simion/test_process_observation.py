from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.simion.process_observation import run_observed_process


class ProcessObservationTests(unittest.TestCase):
    def test_observes_a_successful_process_without_changing_its_output_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed, peak = run_observed_process(
                [sys.executable, "-c", "print('observed')"],
                cwd=root,
                stdout=root / "stdout.log",
                stderr=root / "stderr.log",
                timeout_seconds=10,
                sample_interval_seconds=0.01,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual((root / "stdout.log").read_text(encoding="utf-8"), "observed\n")
            self.assertEqual((root / "stderr.log").read_text(encoding="utf-8"), "")
            if os.name == "nt":
                self.assertIsInstance(peak, int)
                self.assertGreater(peak, 0)
            else:
                self.assertIsNone(peak)

    def test_timeout_terminates_only_the_observed_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(subprocess.TimeoutExpired):
                run_observed_process(
                    [sys.executable, "-c", "import time; time.sleep(5)"],
                    cwd=root,
                    stdout=root / "stdout.log",
                    stderr=root / "stderr.log",
                    timeout_seconds=0.05,
                    sample_interval_seconds=0.01,
                )
