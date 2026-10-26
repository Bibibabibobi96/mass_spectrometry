from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from common.simion import process_observation
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
                warning_seconds=10,
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

    def test_elapsed_warning_does_not_interrupt_a_healthy_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                completed, _ = run_observed_process(
                    [sys.executable, "-c", "import time; time.sleep(0.08); print('done')"],
                    cwd=root,
                    stdout=root / "stdout.log",
                    stderr=root / "stderr.log",
                    warning_seconds=0.01,
                    sample_interval_seconds=0.005,
                )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual((root / "stdout.log").read_text(encoding="utf-8"), "done\n")
            self.assertEqual(len(captured), 1)
            self.assertIn("OBSERVED_PROCESS_WARNING", str(captured[0].message))

    def test_hard_deadline_requires_an_explicit_tree_termination_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "must be specified together"):
                run_observed_process(
                    [sys.executable, "-c", "print('not started')"],
                    cwd=root,
                    stdout=root / "stdout.log",
                    stderr=root / "stderr.log",
                    hard_deadline_seconds=1,
                )

    def test_unknown_hard_deadline_action_is_rejected_before_starting_a_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "unsupported hard_deadline_action"):
                run_observed_process(
                    [sys.executable, "-c", "print('not started')"],
                    cwd=root,
                    stdout=root / "stdout.log",
                    stderr=root / "stderr.log",
                    hard_deadline_seconds=1,
                    hard_deadline_action="kill",  # type: ignore[arg-type]
                )

    def test_explicit_hard_deadline_uses_tree_termination_helper(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=os.name == "nt") as directory:
            root = Path(directory)
            with patch.object(
                process_observation,
                "_terminate_process_tree",
                side_effect=lambda process: process.kill(),
            ) as terminate:
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_observed_process(
                        [sys.executable, "-c", "import time; time.sleep(5)"],
                        cwd=root,
                        stdout=root / "stdout.log",
                        stderr=root / "stderr.log",
                        hard_deadline_seconds=0.02,
                        hard_deadline_action="terminate_process_tree",
                        sample_interval_seconds=0.005,
                    )
            terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
