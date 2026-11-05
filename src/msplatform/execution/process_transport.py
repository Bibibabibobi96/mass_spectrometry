"""Existing controlled-worker handshake and healthy owner failure drain."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from typing import Any

def await_managed_process_start() -> None:
    """Identify this Windows worker, then wait for its owner's stdin ACK.

    Call before importing project code or starting native work. This handshake
    grants no resources and creates no files; EOF or a mismatched ACK fails.
    """
    import ctypes
    from ctypes import wintypes
    from datetime import datetime

    nonce = os.environ.pop("MASS_SPECTROMETRY_MANAGED_PROCESS_NONCE", "")
    if os.name != "nt" or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise RuntimeError("Managed worker requires its Windows owner's per-launch nonce")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), *(ctypes.byref(item) for item in
                                                               (created, exited, kernel_time, user_time))):
        raise ctypes.WinError(ctypes.get_last_error())
    # FILETIME is 100 ns since 1601; preserve the host facade's .NET UTC ticks
    # since year 1, without rounding through a floating-point Unix timestamp.
    epoch_ticks = (datetime(1601, 1, 1).toordinal() - 1) * 86400 * 10_000_000
    birth = ((created.dwHighDateTime << 32) | created.dwLowDateTime) + epoch_ticks
    ready = {"schema_version": 1, "role": "repository_managed_process_ready", "nonce": nonce,
             "pid": os.getpid(), "started": f"{birth:019d}"}
    print(json.dumps(ready), flush=True)
    acknowledgement = json.loads(sys.stdin.readline())
    expected = {**ready, "role": "repository_managed_process_ack"}
    if (not isinstance(acknowledgement, dict) or type(acknowledgement.get("schema_version")) is not int
            or type(acknowledgement.get("pid")) is not int or acknowledgement != expected):
        raise RuntimeError("Managed worker ACK does not match this launch and process identity")


def _finish_bridge_after_failure(process: subprocess.Popen, failure: BaseException) -> None:
    """Drain/wait the owned bridge root without killing a healthy owner."""
    failure.observed_process_exit_confirmed = False
    failure.observed_process_returncode = None
    failure.bridge_process_exit_confirmed = False
    failure.bridge_process_returncode = None
    failure.bridge_process_pid = process.pid
    # PowerShell reads the request to EOF. Do not resend a partly sent request
    # or wait forever with its stdin still open after a communication failure.
    if process.stdin is not None:
        try:
            process.stdin.close()
        except BaseException as close_error:
            failure.add_note(f"Bridge stdin close failed: {type(close_error).__name__}: {close_error}")
    try:
        process.communicate()
        returncode = process.wait()
    except BaseException as wait_error:
        failure.add_note(
            f"BRIDGE_ROOT_EXIT_UNCONFIRMED pid={process.pid}; "
            f"{type(wait_error).__name__}: {wait_error}; native writers remain unconfirmed"
        )
    else:
        failure.bridge_process_exit_confirmed = True
        failure.bridge_process_returncode = returncode
        failure.add_note(f"BRIDGE_ROOT_EXITED pid={process.pid} returncode={returncode}; descendants are not attested")


def _host_release(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate transport/binding, without extending the scheduler's proof."""
    release = receipt.get("host_release")
    if (not isinstance(release, dict) or set(release) != {"inherited", "token", "result", "error"}
            or type(release["inherited"]) is not bool or not isinstance(release["token"], str)
            or not release["token"] or (release["error"] is not None and not isinstance(release["error"], str))):
        raise ValueError("missing or invalid host release receipt")
    transaction = release["result"]
    if release["inherited"]:
        if transaction is not None:
            raise ValueError("inherited caller cannot attest owner release")
    elif transaction is not None:
        if (not isinstance(transaction, dict) or transaction.get("token") != release["token"]
                or transaction.get("status") not in {"released", "acquired", "waiting"}
                or (transaction["status"] == "released" and set(transaction) != {"status", "token"})):
            raise ValueError("host release transaction identity differs")
    return release


def _record_host_completion(receipt: dict[str, Any], completion: dict[str, Any]) -> None:
    release = _host_release(receipt)
    completion["host_release"] = release
    completion["host_release_confirmed"] = (not release["inherited"] and release["error"] is None
                                            and (release["result"] or {}).get("status") == "released")
