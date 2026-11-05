"""Bounded, evidence-preserving ownership for ACK-gated synthetic fixtures only.

This is test support, never a production solver timeout policy. The copied
fixture must wait for stdin ACK before creating children. Windows Job children
cannot break away; POSIX fixtures get their own session.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from uuid import uuid4


ACK = b"fixture-owned-start\n"


def _creation_filetime(handle: int) -> int:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    values = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime


def _job_processes(job) -> list[dict]:
    import win32api
    import win32job

    rows = []
    for pid in win32job.QueryInformationJobObject(job, win32job.JobObjectBasicProcessIdList):
        handle = win32api.OpenProcess(0x1000, False, pid)
        try:
            if not win32job.IsProcessInJob(handle, job):
                raise RuntimeError("Fixture job membership changed during observation")
            rows.append(dict(pid=pid, creation_filetime_100ns=_creation_filetime(int(handle))))
        finally:
            handle.Close()
    return rows


def _exclude_exited_root(rows: list[dict], *, root_pid: int,
                         root_creation: int, root_exited: bool) -> list[dict]:
    """Only the exact retained, confirmed-exited root is not a descendant."""
    return [row for row in rows if not (
        root_exited
        and row.get("pid") == root_pid
        and row.get("creation_filetime_100ns") == root_creation
    )]


@contextmanager
def _job_completion_handles(job, rows: list[dict], metadata: dict):
    """Pin observed members before termination; PID alone never authorizes a wait."""
    handles = []
    try:
        if job is not None:
            import win32api
            import win32job

            for row in rows:
                handle = None
                try:
                    # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION.
                    handle = win32api.OpenProcess(0x00101000, False, row["pid"])
                    if (_creation_filetime(int(handle)) != row["creation_filetime_100ns"]
                            or not win32job.IsProcessInJob(handle, job)):
                        raise RuntimeError("Fixture member identity changed before cleanup")
                    handles.append((row, handle))
                    handle = None
                except BaseException as error:
                    metadata["secondary_errors"].append(f"member_handle: {error!r}")
                finally:
                    if handle is not None:
                        try:
                            handle.Close()
                        except BaseException as error:
                            metadata["secondary_errors"].append(f"member_handle_close: {error!r}")
        yield handles
    finally:
        for _, handle in handles:
            try:
                handle.Close()
            except BaseException as error:
                metadata["secondary_errors"].append(f"member_handle_close: {error!r}")


def _wait_job_members(handles: list, deadline: float, metadata: dict) -> set[tuple[int, int]]:
    """Wait on retained identities within the existing shared cleanup budget."""
    import win32event

    confirmed = set()
    witnesses = metadata["member_completion_waits"] = []
    for row, handle in handles:
        witness = dict(row, exit_confirmed=False)
        witnesses.append(witness)
        result = win32event.WaitForSingleObject(handle, math.ceil(max(0, deadline - time.monotonic()) * 1000))
        witness["wait_result"] = result
        witness["exit_confirmed"] = result == win32event.WAIT_OBJECT_0
        if not witness["exit_confirmed"]:
            raise TimeoutError("Owned fixture member did not finish within cleanup budget")
        confirmed.add((row["pid"], row["creation_filetime_100ns"]))
    return confirmed


def _save_evidence(destination: Path, root: Path, metadata: dict, stdout: bytes, stderr: bytes,
                   drained_stdout: bytes | None, drained_stderr: bytes | None) -> None:
    """Save small named fixture records before their TemporaryDirectory exits."""
    payloads = {"stdout.bin": stdout, "stderr.bin": stderr}
    if drained_stdout is not None:
        payloads.update({"drained_stdout.bin": drained_stdout, "drained_stderr.bin": drained_stderr or b""})
    for name in ("events", "timeline.jsonl", "completion.json", "result.json", "child.json"):
        source = root / name
        if source.is_file():
            payloads[name] = source.read_bytes()
    records = {}
    for name, payload in payloads.items():
        (destination / name).write_bytes(payload)
        records[name] = dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    for name, payload in (("stdout", stdout), ("stderr", stderr)):
        (destination / f"{name}.utf8.txt").write_text(payload.decode("utf-8", errors="replace"), encoding="utf-8")
    metadata["files"] = records
    (destination / "diagnostics.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def run_fixture_process(command: list[str], *, root: Path, environment: dict[str, str],
                        mode: str, timeout: float = 30, diagnostics_root: Path | None = None,
                        cwd: Path | None = None
                        ) -> subprocess.CompletedProcess[str]:
    """Keep raw timeout bytes, then stop only this gated fixture's owned tree."""
    evidence_root = diagnostics_root or Path(tempfile.gettempdir()) / "oatof_fixture_diagnostics"
    evidence_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=f"compensation-{mode}-", dir=evidence_root))
    started = time.monotonic()
    metadata = dict(schema_version=1, mode=mode, argv=command, cwd=str(cwd or root), timeout_seconds=timeout,
                    selected_python=environment.get("FIXTURE_PYTHON"), monotonic_begin=started,
                    secondary_errors=[])
    sources = [Path(__file__)]
    sources += [Path(environment[key]) for key in ("FIXTURE_TEST_SOURCE", "FIXTURE_ADAPTER_SOURCE") if key in environment]
    if "-File" in command:
        sources.append(Path(command[command.index("-File") + 1]))
    metadata["source_identity"] = [dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                                   for path in sources]
    metadata["test_id"] = environment.get("FIXTURE_TEST_METHOD")
    process = None
    job = None
    assigned = False
    failure = None
    stdout = stderr = b""
    drained_out = drained_err = None
    try:
        if os.name == "nt":
            import win32job

            job = win32job.CreateJobObject(None, "oatof-fixture-" + uuid4().hex)
            limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
            limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        process = subprocess.Popen(command, cwd=cwd or root, env=environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=os.name != "nt")
        metadata["root_pid"] = process.pid
        if job is not None:
            # The copied pwsh fixture cannot launch children until ACK is sent.
            win32job.AssignProcessToJobObject(job, int(process._handle))
            assigned = True
            metadata["root_creation_filetime_100ns"] = _creation_filetime(int(process._handle))
        metadata["ownership_setup_seconds"] = time.monotonic() - started
        # As in subprocess.run, the original communicate timeout starts after
        # Popen; ownership setup is separately reported, never hidden in wall.
        stdout, stderr = process.communicate(ACK, timeout=timeout)
        metadata["returncode"] = process.returncode
        if job is not None:
            import win32event

            observed = _job_processes(job)
            metadata["observed_job_processes_after_return"] = observed
            # Popen retains this original process handle; never reopen by PID.
            root_exited = (process.returncode is not None and
                           win32event.WaitForSingleObject(process._handle, 0) == win32event.WAIT_OBJECT_0)
            metadata["root_exit_confirmed"] = root_exited
            metadata["remaining_job_processes"] = _exclude_exited_root(
                observed, root_pid=process.pid,
                root_creation=metadata["root_creation_filetime_100ns"], root_exited=root_exited)
            if metadata["remaining_job_processes"]:
                raise RuntimeError("Synthetic fixture returned with a live descendant")
    except BaseException as error:
        failure = error
        if isinstance(error, subprocess.TimeoutExpired):
            # Preserve the exact original exception payload; draining later is separate.
            stdout, stderr = error.output or b"", error.stderr or b""
            metadata["timeout_output_types"] = [type(error.output).__name__, type(error.stderr).__name__]
        metadata["primary_error"] = dict(type=type(error).__name__, message=str(error))
        if process is not None:
            try:
                if job is not None and assigned:
                    metadata["job_processes_at_failure"] = _job_processes(job)
            except BaseException as diagnostic_error:
                metadata["secondary_errors"].append(f"process_snapshot: {diagnostic_error!r}")
            try:
                deadline = time.monotonic() + 5
                owned_job = job if assigned else None
                with _job_completion_handles(owned_job, metadata.get("job_processes_at_failure", []), metadata) as handles:
                    if owned_job is not None:
                        win32job.TerminateJobObject(job, 124)
                    elif os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    elif process.poll() is None:
                        # Assignment failed before ACK: this root cannot have children.
                        process.kill()
                    drained_out, drained_err = process.communicate(timeout=max(0, deadline - time.monotonic()))
                    metadata["drained_stdout_bytes"] = len(drained_out or b"")
                    metadata["drained_stderr_bytes"] = len(drained_err or b"")
                    metadata["cleanup_returncode"] = process.returncode
                    if owned_job is not None:
                        confirmed = _wait_job_members(handles, deadline, metadata)
                        observed = _job_processes(job)
                        metadata["observed_job_processes_after_cleanup"] = observed
                        # Retained handles can keep exited members in the Job census.
                        metadata["remaining_job_processes"] = [row for row in observed if (
                            row["pid"], row["creation_filetime_100ns"]) not in confirmed]
            except BaseException as cleanup_error:
                metadata["secondary_errors"].append(f"owned_tree_cleanup: {cleanup_error!r}")
        raise
    finally:
        metadata["elapsed_seconds"] = time.monotonic() - started
        metadata["monotonic_end"] = time.monotonic()
        try:
            _save_evidence(destination, root, metadata, stdout, stderr, drained_out, drained_err)
        except BaseException as diagnostic_error:
            metadata["secondary_errors"].append(f"save_evidence: {diagnostic_error!r}")
            if failure is None:
                raise
        finally:
            if job is not None:
                try:
                    job.Close()
                except BaseException as close_error:
                    metadata["secondary_errors"].append(f"job_close: {close_error!r}")
                    if failure is None:
                        raise
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except BaseException as close_error:
                            metadata["secondary_errors"].append(f"pipe_close: {close_error!r}")
                            if failure is None:
                                raise
            if failure is not None:
                failure.fixture_diagnostics = str(destination)
                failure.fixture_metadata = metadata
                failure.fixture_secondary = list(metadata["secondary_errors"])
                failure.add_note(f"FIXTURE_DIAGNOSTICS={destination}")
                for secondary in metadata["secondary_errors"]:
                    failure.add_note(secondary)
    result = subprocess.CompletedProcess(command, process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8"))
    result.fixture_diagnostics = str(destination)
    return result
