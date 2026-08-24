"""Observe one externally launched SIMION process without project policy."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from pathlib import Path
from typing import Mapping, Sequence


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


def run_observed_process(
    command: Sequence[str], *, cwd: Path, stdout: Path, stderr: Path,
    environment: Mapping[str, str] | None = None, timeout_seconds: float,
    sample_interval_seconds: float = 0.1,
) -> tuple[subprocess.CompletedProcess[None], int | None]:
    """Run a command and return its exit result plus observed root-process peak.

    This is deliberately a process observation primitive, not a scheduler or
    resource-budget enforcer.  A ``None`` peak means that the host cannot expose
    Windows working-set information; callers must then use the scheduler's
    conservative unknown-profile route.
    """
    if not command:
        raise ValueError("observed process command cannot be empty")
    if timeout_seconds <= 0 or sample_interval_seconds <= 0:
        raise ValueError("observation timeout and sampling interval must be positive")
    stdout.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    peak: int | None = None
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(
            list(command), cwd=cwd, stdout=out, stderr=err, env=environment
        )
        while process.poll() is None:
            observed = process_working_set_bytes(process.pid)
            if observed is not None:
                peak = observed if peak is None else max(peak, observed)
            if time.monotonic() - started > timeout_seconds:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            time.sleep(sample_interval_seconds)
        observed = process_working_set_bytes(process.pid)
        if observed is not None:
            peak = observed if peak is None else max(peak, observed)
    return subprocess.CompletedProcess(list(command), process.returncode), peak
