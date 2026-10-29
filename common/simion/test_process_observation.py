from __future__ import annotations

from contextlib import contextmanager
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
    def test_observation_failures_wait_for_native_output_and_preserve_the_error(self) -> None:
        for callback in ("sample", "warning", "sleep"):
            for error_type in (RuntimeError, KeyboardInterrupt):
                with self.subTest(callback=callback, error_type=error_type), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    processes = []
                    popen = subprocess.Popen
                    failure = error_type("observation callback failed")

                    def start(*args, **kwargs):
                        process = popen(*args, **kwargs)
                        processes.append(process)
                        return process

                    target, name = {
                        "sample": (process_observation, "process_working_set_bytes"),
                        "warning": (warnings, "showwarning"),
                        "sleep": (process_observation.time, "sleep"),
                    }[callback]
                    try:
                        with patch.object(process_observation.subprocess, "Popen", side_effect=start), \
                                patch.object(target, name, side_effect=failure), warnings.catch_warnings():
                            warnings.simplefilter("always")
                            with self.assertRaises(error_type) as caught:
                                run_observed_process(
                                    [sys.executable, "-u", "-c",
                                     "import sys,time\nfor i in range(6):\n print(i,flush=True); time.sleep(.03)\n"
                                     "print('native done',flush=True); print('native stderr',file=sys.stderr); sys.exit(7)"],
                                    cwd=root, stdout=root / "stdout.log", stderr=root / "stderr.log",
                                    warning_seconds=0.001, sample_interval_seconds=0.005,
                                )
                        self.assertIs(caught.exception, failure)
                        self.assertEqual(processes[0].poll(), 7, "observer returned while its native writer was alive")
                        self.assertIs(failure.observed_process_exit_confirmed, True)
                        self.assertEqual(failure.observed_process_returncode, 7)
                        self.assertEqual((root / "stdout.log").read_text().splitlines(),
                                         [*map(str, range(6)), "native done"])
                        self.assertEqual((root / "stderr.log").read_text().splitlines(), ["native stderr"])
                    finally:
                        # The baseline deliberately returns early; let this short
                        # real fixture finish naturally before removing its logs.
                        for process in processes:
                            process.wait(timeout=5)

    def test_a_second_interrupt_during_cleanup_keeps_waiting_for_the_same_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            popen = subprocess.Popen
            waits = []
            failure = RuntimeError("sampling failed first")

            def start(*args, **kwargs):
                process = popen(*args, **kwargs)
                wait = process.wait

                def interrupted_wait(*args, **kwargs):
                    waits.append(process.pid)
                    if len(waits) == 1:
                        raise KeyboardInterrupt("second interrupt")
                    return wait(*args, **kwargs)

                process.wait = interrupted_wait
                return process

            with patch.object(process_observation.subprocess, "Popen", side_effect=start), \
                    patch.object(process_observation, "process_working_set_bytes", side_effect=failure):
                with self.assertRaises(RuntimeError) as caught:
                    run_observed_process(
                        [sys.executable, "-c", "import time; time.sleep(.1); print('finished')"],
                        cwd=root, stdout=root / "stdout.log", stderr=root / "stderr.log",
                    )
            self.assertIs(caught.exception, failure)
            self.assertEqual(len(waits), 2)
            self.assertEqual(len(set(waits)), 1)
            self.assertIs(failure.observed_process_exit_confirmed, True)
            self.assertEqual(failure.observed_process_returncode, 0)
            self.assertIn("OBSERVED_PROCESS_WAIT_INTERRUPTED", "\n".join(failure.__notes__))
            self.assertEqual((root / "stdout.log").read_text().strip(), "finished")

    def test_wait_failure_keeps_original_error_and_explicitly_withholds_exit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            popen = subprocess.Popen
            waits = []
            failure = RuntimeError("sampling failed first")

            def start(*args, **kwargs):
                process = popen(*args, **kwargs)
                waits.append(process.wait)

                def failed_wait():
                    raise OSError("wait handle unavailable")

                process.wait = failed_wait
                return process

            try:
                with patch.object(process_observation.subprocess, "Popen", side_effect=start), \
                        patch.object(process_observation, "process_working_set_bytes", side_effect=failure):
                    with self.assertRaises(RuntimeError) as caught:
                        run_observed_process(
                            [sys.executable, "-c", "import time; time.sleep(.1); print('finished')"],
                            cwd=root, stdout=root / "stdout.log", stderr=root / "stderr.log",
                        )
                self.assertIs(caught.exception, failure)
                self.assertIs(failure.observed_process_exit_confirmed, False)
                self.assertIsNone(failure.observed_process_returncode)
                self.assertIn("OBSERVED_PROCESS_EXIT_UNCONFIRMED", "\n".join(failure.__notes__))
                self.assertIn("wait handle unavailable", "\n".join(failure.__notes__))
            finally:
                for wait in waits:
                    wait(timeout=5)

    def test_log_close_failure_does_not_replace_the_original_observation_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_open = Path.open
            failure = RuntimeError("sampling failed first")

            @contextmanager
            def open_with_close_failure(path, *args, **kwargs):
                with real_open(path, *args, **kwargs) as stream:
                    try:
                        yield stream
                    finally:
                        if path.name == "stdout.log":
                            raise OSError("log close failed second")

            with patch.object(Path, "open", open_with_close_failure), \
                    patch.object(process_observation, "process_working_set_bytes", side_effect=failure):
                with self.assertRaises(RuntimeError) as caught:
                    run_observed_process(
                        [sys.executable, "-c", "import time; time.sleep(.1); print('finished')"],
                        cwd=root, stdout=root / "stdout.log", stderr=root / "stderr.log",
                    )
            self.assertIs(caught.exception, failure)
            self.assertIs(failure.observed_process_exit_confirmed, True)
            self.assertEqual(failure.observed_process_returncode, 0)
            self.assertIn("log close failed second", "\n".join(failure.__notes__))
            self.assertEqual((root / "stdout.log").read_text().strip(), "finished")

    def test_native_nonzero_exit_is_returned_without_becoming_an_observer_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed, _ = run_observed_process(
                [sys.executable, "-c", "import sys; print('native failure',file=sys.stderr); sys.exit(9)"],
                cwd=root, stdout=root / "stdout.log", stderr=root / "stderr.log",
                sample_interval_seconds=0.01,
            )
            self.assertEqual(completed.returncode, 9)
            self.assertEqual((root / "stderr.log").read_text().strip(), "native failure")

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
