"""Observe one externally launched SIMION process without project policy."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import time
import warnings
from pathlib import Path
from typing import Literal, Mapping, Sequence


HardDeadlineAction = Literal["terminate_process_tree"]


def process_working_set_bytes(process_id: int) -> int | None:
    """Return the current Windows working set for ``process_id`` when observable."""
    if os.name != "nt":
        return None
    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
    if not process:
        return None
    try:
        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb
        ):
            return None
        return int(counters.working_set_size)
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Stop an explicitly abandoned observed process and every child it owns."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/pid", str(process.pid), "/t", "/f"],
            cwd=Path(__file__).resolve().parent,
            timeout=None,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    os.killpg(process.pid, signal.SIGKILL)


def _wait_after_observation_failure(process: subprocess.Popen[bytes], failure: BaseException) -> None:
    """Keep the original failure while the owned root finishes naturally."""
    failure.observed_process_exit_confirmed = False
    failure.observed_process_returncode = None
    interrupted = False
    while True:
        try:
            returncode = process.wait()
        except KeyboardInterrupt:
            if not interrupted:
                failure.add_note(f"OBSERVED_PROCESS_WAIT_INTERRUPTED pid={process.pid}; waiting for natural exit")
                interrupted = True
        except BaseException as wait_error:
            failure.add_note(
                f"OBSERVED_PROCESS_EXIT_UNCONFIRMED pid={process.pid}; "
                f"wait failed: {type(wait_error).__name__}: {wait_error}; do not seal outputs"
            )
            return
        else:
            failure.observed_process_exit_confirmed = True
            failure.observed_process_returncode = returncode
            failure.add_note(f"OBSERVED_PROCESS_ROOT_EXITED pid={process.pid} returncode={returncode}")
            return


def run_observed_process(
    command: Sequence[str], *, cwd: Path, stdout: Path, stderr: Path,
    environment: Mapping[str, str] | None = None,
    warning_seconds: float | None = None,
    hard_deadline_seconds: float | None = None,
    hard_deadline_action: HardDeadlineAction | None = None,
    sample_interval_seconds: float = 0.1,
) -> tuple[subprocess.CompletedProcess[None], int | None]:
    """Run a command and return its exit result plus observed root-process peak.

    Observation is warning-only by default: exceeding ``warning_seconds`` records
    one warning and lets a healthy process complete naturally.  Termination is
    available only when a caller deliberately supplies both an explicit hard
    deadline and ``hard_deadline_action='terminate_process_tree'``.  That action
    stops the observed process tree, rather than leaving SIMION child processes
    behind.  This helper does not diagnose solver health or enforce budgets.

    A ``None`` peak means that the host cannot expose Windows working-set
    information; callers must then use the scheduler's conservative
    unknown-profile route.

    Observation failures wait for this root process without a deadline, then
    re-raise the same exception. Its ``observed_process_exit_confirmed`` and
    ``observed_process_returncode`` attributes describe that wait; an OS wait
    failure leaves confirmation false. This is not proof that descendants have
    exited: callers still need their existing process-owner completion checks.
    """
    if not command:
        raise ValueError("observed process command cannot be empty")
    if sample_interval_seconds <= 0:
        raise ValueError("sampling interval must be positive")
    if warning_seconds is not None and warning_seconds <= 0:
        raise ValueError("warning_seconds must be positive when specified")
    if (hard_deadline_seconds is None) != (hard_deadline_action is None):
        raise ValueError(
            "hard_deadline_seconds and hard_deadline_action must be specified together"
        )
    if hard_deadline_seconds is not None and hard_deadline_seconds <= 0:
        raise ValueError("hard_deadline_seconds must be positive when specified")
    if hard_deadline_action not in (None, "terminate_process_tree"):
        raise ValueError("unsupported hard_deadline_action")

    stdout.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    peak: int | None = None
    warned = False
    popen_options: dict[str, object] = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True
    process = None
    observation_failure = None
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            try:
                process = subprocess.Popen(
                    list(command), cwd=cwd, stdout=out, stderr=err, env=environment,
                    **popen_options,
                )
                while process.poll() is None:
                    observed = process_working_set_bytes(process.pid)
                    if observed is not None:
                        peak = observed if peak is None else max(peak, observed)
                    elapsed = time.monotonic() - started
                    if not warned and warning_seconds is not None and elapsed > warning_seconds:
                        warnings.warn(
                            f"OBSERVED_PROCESS_WARNING elapsed_seconds={elapsed:.3f} "
                            f"warning_seconds={warning_seconds:.3f} pid={process.pid}",
                            RuntimeWarning,
                            stacklevel=2,
                        )
                        warned = True
                    if hard_deadline_seconds is not None and elapsed > hard_deadline_seconds:
                        _terminate_process_tree(process)
                        process.wait()
                        raise subprocess.TimeoutExpired(command, hard_deadline_seconds)
                    time.sleep(sample_interval_seconds)
                observed = process_working_set_bytes(process.pid)
                if observed is not None:
                    peak = observed if peak is None else max(peak, observed)
            except BaseException as error:
                observation_failure = error
                if process is not None:
                    _wait_after_observation_failure(process, error)
                raise
    except BaseException as error:
        if observation_failure is not None and error is not observation_failure:
            observation_failure.add_note(f"Observed process log close failed: {type(error).__name__}: {error}")
            raise observation_failure
        if observation_failure is None and process is not None:
            _wait_after_observation_failure(process, error)
        raise
    return subprocess.CompletedProcess(list(command), process.returncode), peak
