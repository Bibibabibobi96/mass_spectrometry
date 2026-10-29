"""Shared heavy-entry adapter for repository Python 3.11 computations.

MR/OA theory and multipole transport consumers call ``ensure_heavy_entry`` at
their CLI boundary, before computation or pool creation. Mixed campaigns use
``run_heavy_function`` for one complete pool instead of reentering their main.
This module owns no
ledger or worker scheduler. Existing worker counts, numerical algorithms and
checkpoint behavior remain the responsibility of each consumer.
"""

from __future__ import annotations

import json
import importlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

_TOKEN = "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN"
_REENTRY = "MASS_SPECTROMETRY_PYTHON_HEAVY_REENTRY"
_RESULT = "HOST_RESOURCE_PYTHON_RESULT="
_CALL_RESULT_ROLE = "host_resource_python_call_result"


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


def _bridge(operation: str, **payload: Any) -> subprocess.CompletedProcess:
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Repository heavy Python entry requires Python 3.11")
    if os.name != "nt":
        raise RuntimeError("Host resource execution requires Windows PowerShell 7")
    request = {"schema_version": 1, "operation": operation,
               "python": str(Path(sys.executable).resolve()), **payload}
    command = ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
               str(Path(__file__).with_suffix(".ps1"))]
    request_bytes = json.dumps(request, ensure_ascii=False).encode("utf-8")
    capture = operation not in {"enter", "call"}
    # subprocess.run kills its direct child after communication exceptions,
    # including KeyboardInterrupt. Here that child is the process owner, not
    # the native computation, so retain this exact handle and wait naturally.
    process = subprocess.Popen(command, cwd=Path.cwd(), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE if capture else None,
                               stderr=subprocess.PIPE if capture else None)
    failure = None
    try:
        output, errors = process.communicate(request_bytes, timeout=None)
        return subprocess.CompletedProcess(command, process.returncode, output, errors)
    except BaseException as error:
        failure = error
        _finish_bridge_after_failure(process, error)
        raise
    finally:
        close_failure = None
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except BaseException as error:
                primary = failure if failure is not None else close_failure
                if primary is not None:
                    primary.add_note(f"Bridge stream close failed: {type(error).__name__}: {error}")
                else:
                    close_failure = error
        if close_failure is not None:
            _finish_bridge_after_failure(process, close_failure)
            raise close_failure


def _read_result(result: subprocess.CompletedProcess, *, check_exit: bool = True) -> dict[str, Any]:
    if check_exit and result.returncode:
        raise RuntimeError(f"Host resource bridge failed ({result.returncode}): {result.stderr!r}")
    lines = result.stdout.decode("utf-8").splitlines()
    records = [line[len(_RESULT):] for line in lines if line.startswith(_RESULT)]
    if len(records) != 1:
        raise RuntimeError("Host resource bridge returned no unique result")
    value = json.loads(records[0])
    if not isinstance(value, dict):
        raise RuntimeError("Host resource bridge result must be an object")
    return value


def run_managed_python_process(
    arguments: list[str], *, cwd: Path, stdout: Path, stderr: Path,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Wait a controlled actual worker and drain logs, without a resource grant.

    Its first operation must be ``await_managed_process_start``. Scientific
    entry points still own resource admission and native completion evidence.
    A nonzero actual-worker exit is returned intact in the completion receipt.
    """
    if not arguments or any(not isinstance(argument, str) or "\0" in argument for argument in arguments):
        raise ValueError("managed Python arguments must be strings without NUL")
    completion = None
    try:
        result = _bridge("managed_process", argv=list(arguments), working_directory=str(cwd.resolve()),
                         stdout_path=str(stdout.resolve()), stderr_path=str(stderr.resolve()),
                         environment=environment or {})
        envelope = _read_result(result, check_exit=False)
        if set(envelope) != {"completion", "error"}:
            raise ValueError("managed Python transport envelope differs")
        value = envelope["completion"]
        if value is not None:
            flags = ("ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed", "stdout_drained", "stderr_drained")
            if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
                    or value["schema_version"] != 1 or value.get("role") != "repository_managed_python_completion"
                    or any(type(value.get(field)) is not bool for field in flags)
                    or (value.get("exit_code") is not None and type(value["exit_code"]) is not int)):
                raise ValueError("managed Python completion receipt differs")
            completion = value
        error = envelope["error"]
        if error is not None:
            if not isinstance(error, dict) or set(error) != {"type", "message"} or any(not isinstance(item, str) for item in error.values()):
                raise ValueError("managed Python error receipt differs")
            raise RuntimeError(f"Managed Python owner failed: {error['type']}: {error['message']}")
        if (result.returncode or completion is None or not all(completion[field] for field in flags)
                or type(completion["exit_code"]) is not int):
            raise RuntimeError(f"Managed Python owner completion was not confirmed ({result.returncode})")
        if (any(type(completion.get(field)) is not int or completion[field] <= 0 for field in
                ("launcher_process_id", "worker_process_id", "worker_started_at_utc_ticks"))):
            completion = None
            raise ValueError("managed Python completion identity differs")
        return completion
    except BaseException as error:
        error.managed_python_completion = completion
        raise


def ensure_heavy_entry(
    module: str, argv: list[str] | None = None, *, role: str = "GATE", stage: str = "theory_compute",
) -> None:
    """Verify a live heavy grant, or reenter this module once under that grant.

    Call with the importable module name, not ``__main__`` or a shell command.
    The original invocation exits with the managed invocation's exit code.
    Arguments are transported as strings, never interpolated into shell code.
    """
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module) or module == "__main__":
        raise ValueError("heavy entry requires an importable Python module name")
    if role not in {"GATE", "SIMION", "COMSOL"} or not re.fullmatch(r"[A-Za-z_]\w*", stage):
        raise ValueError("heavy entry requires a known role and named stage")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(not isinstance(argument, str) or "\0" in argument for argument in arguments):
        raise ValueError("heavy entry arguments must be strings without NUL")
    if os.environ.get(_TOKEN):
        if _read_result(_bridge("assert")).get("heavy") is not True:
            raise RuntimeError("Host resource bridge did not verify a heavy grant")
        return
    if os.environ.get(_REENTRY):
        raise RuntimeError("Managed Python reentry lost its heavy token; refusing another reentry")
    raise SystemExit(_bridge("enter", module=module, argv=arguments, role=role, stage=stage).returncode)


def _encode_value(value: Any) -> Any:
    """Use tagged containers so user dictionaries cannot impersonate a Path."""
    if isinstance(value, Path):
        return {"kind": "path", "value": str(value)}
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {"kind": "dict", "value": {key: _encode_value(item) for key, item in value.items()}}
    if isinstance(value, (list, tuple)):
        return {"kind": "tuple" if isinstance(value, tuple) else "list", "value": [_encode_value(item) for item in value]}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported stage argument/result type: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    kind, payload = value["kind"], value["value"]
    if kind == "path":
        return Path(payload)
    if kind == "dict":
        return {key: _decode_value(item) for key, item in payload.items()}
    if kind in {"list", "tuple"}:
        items = [_decode_value(item) for item in payload]
        return tuple(items) if kind == "tuple" else items
    raise ValueError(f"Unknown stage value kind: {kind}")


def _write_call_result(path: Path, **payload: Any) -> None:
    """Atomically publish one small result on the existing private IPC path."""
    document = {"schema_version": 1, "role": _CALL_RESULT_ROLE, **payload}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".result-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(document, ensure_ascii=False).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _worker_error(error: BaseException) -> dict[str, Any]:
    value = {"type": type(error).__name__, "module": type(error).__module__,
             "message": str(error), "notes": list(getattr(error, "__notes__", []))}
    for name in ("observed_process_exit_confirmed", "observed_process_returncode"):
        if hasattr(error, name):
            value[name] = getattr(error, name)
    return value


def _attach_host_release() -> None:
    """Append the owner's real release transaction on the existing IPC file."""
    request = json.load(sys.stdin)
    path = Path(request["result_path"])
    document = json.loads(path.read_text(encoding="utf-8"))
    if (document.get("schema_version") != 1 or document.get("role") != _CALL_RESULT_ROLE
            or "host_release" in document):
        raise ValueError("worker result identity differs before owner release publication")
    document.pop("schema_version")
    document.pop("role")
    _write_call_result(path, **document, host_release=request["host_release"])


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


def _read_call_result(path: Path, result: subprocess.CompletedProcess, label: str,
                      completion: dict[str, Any] | None = None) -> Any:
    """A bridge exit alone is not a worker completion or native writer proof."""
    if completion is None:
        completion = {}
    completion.update(bridge_process_exit_confirmed=True, bridge_process_returncode=result.returncode,
                      host_release=None, host_release_confirmed=False)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int
                or receipt["schema_version"] != 1 or receipt.get("role") != _CALL_RESULT_ROLE):
            raise ValueError("result envelope identity differs")
        core_keys = set(receipt) - {"host_release"}
        if receipt.get("status") == "success" and core_keys == {"schema_version", "role", "status", "value"}:
            _record_host_completion(receipt, completion)
            if not completion["host_release_confirmed"]:
                raise ValueError("host owner release was not confirmed")
            if result.returncode:
                raise ValueError("bridge failed after worker result publication")
            return _decode_value(receipt["value"])
        if receipt.get("status") != "failed" or core_keys != {"schema_version", "role", "status", "error"}:
            raise ValueError("result envelope status differs")
        error = receipt["error"]
        required = {"type", "module", "message", "notes"}
        optional = {"observed_process_exit_confirmed", "observed_process_returncode"}
        if (not isinstance(error, dict) or not required <= error.keys() or error.keys() - required - optional
                or any(not isinstance(error[name], str) for name in ("type", "module", "message"))
                or not error["type"] or not error["module"] or not isinstance(error["notes"], list)
                or any(not isinstance(note, str) for note in error["notes"])
                or ("observed_process_exit_confirmed" in error and type(error["observed_process_exit_confirmed"]) is not bool)
                or (error.get("observed_process_returncode") is not None and type(error["observed_process_returncode"]) is not int)
                or (error.get("observed_process_exit_confirmed") is True
                    and type(error.get("observed_process_returncode")) is not int)):
            raise ValueError("worker error fields differ")
    except (OSError, ValueError, KeyError, TypeError) as receipt_error:
        failure = RuntimeError(f"Managed stage {label} failed ({result.returncode}); invalid or missing result: {receipt_error}")
        failure.observed_process_exit_confirmed = False
        failure.observed_process_returncode = None
        failure.host_release = completion["host_release"]
        failure.host_release_confirmed = completion["host_release_confirmed"]
        raise failure from receipt_error
    failure = RuntimeError(f"Managed stage {label} failed ({result.returncode}): {error['type']}: {error['message']}")
    failure.worker_error_type = error["type"]
    failure.worker_error_module = error["module"]
    failure.worker_error_message = error["message"]
    for name in optional:
        if name in error:
            setattr(failure, name, error[name])
    for note in error["notes"]:
        failure.add_note(note)
    try:
        _record_host_completion(receipt, completion)
    except ValueError as release_error:
        failure.add_note(f"Host release unconfirmed: {release_error}")
    failure.host_release = completion["host_release"]
    failure.host_release_confirmed = completion["host_release_confirmed"]
    if failure.host_release is not None and failure.host_release["error"]:
        failure.add_note(f"Host release failed: {failure.host_release['error']}")
    raise failure


def run_heavy_function(module: str, function: str, *args: Any,
                       role: str = "SIMION", stage: str = "flight",
                       completion_receipt: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """Run one complete pool function under a grant; never grant individual workers.

    Inherited heavy callers stay in-process. A light parent is rejected, never
    detached. Standalone calls use a short-lived managed child and temporary
    JSON result; progress/error streams remain attached to the calling console.
    An optional empty ``completion_receipt`` receives owner/bridge facts for
    this call, independently of the unchanged return value and native facts.
    """
    if completion_receipt is not None and (not isinstance(completion_receipt, dict) or completion_receipt):
        raise ValueError("completion_receipt must be an empty per-call dictionary")
    completion = completion_receipt if completion_receipt is not None else {}
    completion.update(bridge_process_exit_confirmed=None, bridge_process_returncode=None,
                      host_release=None, host_release_confirmed=False)
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module) or module == "__main__":
        raise ValueError("stage call requires an importable module")
    if not re.fullmatch(r"[A-Za-z_]\w*", function):
        raise ValueError("stage call requires a simple function name")
    if role not in {"GATE", "SIMION", "COMSOL"} or not re.fullmatch(r"[A-Za-z_]\w*", stage):
        raise ValueError("stage call requires a known role and named stage")
    if os.environ.get(_TOKEN):
        if _read_result(_bridge("assert")).get("heavy") is not True:
            raise RuntimeError("Stage call requires an inherited heavy grant")
        completion["host_release"] = {"inherited": True, "token": os.environ[_TOKEN], "result": None, "error": None}
        try:
            return getattr(importlib.import_module(module), function)(*args, **kwargs)
        except BaseException as error:
            error.host_release = completion["host_release"]
            error.host_release_confirmed = False
            raise
    if os.environ.get(_REENTRY):
        raise RuntimeError("Managed Python reentry lost its heavy token")
    directory = Path(tempfile.mkdtemp(prefix="host-resource-python-call-"))
    failure = None
    try:
        result_path = directory / "result.json"
        result = _bridge("call", module=module, function=function, role=role, stage=stage,
                         args=_encode_value(args), kwargs=_encode_value(kwargs), result_path=str(result_path))
        return _read_call_result(result_path, result, f"{module}.{function}", completion)
    except BaseException as error:
        failure = error
        if hasattr(error, "bridge_process_exit_confirmed"):
            completion["bridge_process_exit_confirmed"] = error.bridge_process_exit_confirmed
            completion["bridge_process_returncode"] = getattr(error, "bridge_process_returncode", None)
            if error.bridge_process_exit_confirmed is True:
                try:
                    receipt = json.loads(result_path.read_text(encoding="utf-8"))
                    if (not isinstance(receipt, dict) or receipt.get("schema_version") != 1
                            or receipt.get("role") != _CALL_RESULT_ROLE):
                        raise ValueError("result envelope identity differs")
                    _record_host_completion(receipt, completion)
                except (OSError, ValueError, KeyError, TypeError) as receipt_error:
                    error.add_note(f"Host release unconfirmed after bridge failure: {receipt_error}")
        else:
            error.bridge_process_exit_confirmed = completion["bridge_process_exit_confirmed"]
            error.bridge_process_returncode = completion["bridge_process_returncode"]
        error.host_release = completion["host_release"]
        error.host_release_confirmed = completion["host_release_confirmed"]
        raise
    finally:
        if failure is not None and getattr(failure, "bridge_process_exit_confirmed", True) is False:
            failure.add_note(f"BRIDGE_RESULT_RETAINED={directory}; owner exit unconfirmed")
        else:
            try:
                shutil.rmtree(directory)
            except BaseException as cleanup_error:
                if failure is None:
                    raise
                failure.add_note(f"Bridge result cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}")


def _execute_call() -> None:
    """Internal bridge target; stdin carries data, never executable source."""
    request = json.load(sys.stdin)
    path = Path(request["result_path"])
    try:
        if _read_result(_bridge("assert")).get("heavy") is not True:
            raise RuntimeError("Managed function has no verified heavy grant")
        result = getattr(importlib.import_module(request["module"]), request["function"])(
            *_decode_value(request["args"]), **_decode_value(request["kwargs"]))
        _write_call_result(path, status="success", value=_encode_value(result))
    except BaseException as error:
        try:
            _write_call_result(path, status="failed", error=_worker_error(error))
        except BaseException as publication_error:
            error.add_note(f"Bridge error publication failed: {type(publication_error).__name__}: {publication_error}")
        raise
