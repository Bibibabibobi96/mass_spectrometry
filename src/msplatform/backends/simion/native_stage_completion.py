"""Adapt existing project stage receipts into the public owner's writer facts.

No process launching, resource allocation, scientific input or publication lives
here. The original receipt remains the evidence; unknown writers stay unknown.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError("native completion must be an object")
    return value


def _unknown_observation(powershell_owner: bool) -> dict[str, Any]:
    result = {"exit_confirmed": False, "returncode": None}
    if powershell_owner:
        result.update(process_id=None, process_started_at_utc_ticks=None)
    return result


def _observation(observation: dict[str, Any], managed: dict[str, Any] | None,
                 powershell_owner: bool) -> dict[str, Any]:
    result = {key: observation.get(key) for key in ("exit_confirmed", "returncode")}
    if powershell_owner:
        if managed is None:
            raise RuntimeError("PowerShell owner requires the actual managed worker identity")
        result.update(process_id=managed["worker_process_id"],
                      process_started_at_utc_ticks=managed["worker_started_at_utc_ticks"])
    return result


def append_native_stage_completion(
    writer: dict[str, Any] | None, receipt_path: Path, *, role: str,
    run_id: str, context_sha256: str | None = None,
    original_failure: BaseException | None = None, powershell_owner: bool = False,
) -> None:
    """Retain native/worker/release facts and preserve the original command error.

    The PS projection includes the managed worker's real PID and birth tick;
    the Python owner retains its existing two-field observation contract.
    """
    failure = original_failure
    try:
        if writer is not None:
            release_id = receipt_path.stem
            if not receipt_path.is_file():
                writer["operations"].append({"operation_id": release_id,
                    "observation": _unknown_observation(powershell_owner),
                    "resource_release_id": release_id})
            else:
                receipt = _load(receipt_path)
                if receipt.get("schema_version") != 1 or receipt.get("role") != role or receipt.get("run_id") != run_id:
                    raise RuntimeError(f"native completion identity differs: {receipt_path}")
                if role in {"oatof_component_build_completion", "oatof_candidate_flight_process_result"} and receipt.get("context_sha256") != context_sha256:
                    raise RuntimeError(f"native completion scientific context differs: {receipt_path}")
                if role == "oatof_candidate_flight_process_result":
                    operations = [{"operation_id": "flight", "observation": {
                        "exit_confirmed": receipt.get("native_exit_confirmed", False),
                        "returncode": receipt.get("native_returncode")},
                        "managed_process_completion": receipt.get("managed_process_completion")}]
                else:
                    operations = receipt["operations"]
                for operation in operations:
                    managed = None
                    observation = operation["observation"]
                    if role in {"oatof_component_build_completion", "oatof_candidate_flight_process_result"}:
                        managed = operation.get("managed_process_completion") or {}
                        if (managed.get("schema_version") != 1
                                or managed.get("role") != "repository_managed_python_completion"
                                or type(managed.get("exit_code")) is not int
                                or any(managed.get(key) is not True for key in (
                                    "ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed",
                                    "stdout_drained", "stderr_drained"))
                                or type(managed.get("worker_process_id")) is not int
                                or managed["worker_process_id"] <= 0
                                or type(managed.get("worker_started_at_utc_ticks")) is not int
                                or managed["worker_started_at_utc_ticks"] <= 0):
                            raise RuntimeError(f"managed writer completion is unconfirmed: {operation['operation_id']}")
                        if managed["exit_code"] and failure is None:
                            failure = RuntimeError(f"managed writer failed ({managed['exit_code']}): {operation['operation_id']}")
                    writer["operations"].append({
                        "operation_id": f"{release_id}.{operation['operation_id']}",
                        "observation": _observation(observation, managed, powershell_owner),
                        "resource_release_id": release_id,
                    })
                if operations:
                    writer["resource_releases"].append({"release_id": release_id, "completion_receipt": receipt})
    except BaseException as receipt_error:
        if writer is not None:
            writer["operations"].append({"operation_id": receipt_path.stem + ".unconfirmed",
                "observation": _unknown_observation(powershell_owner),
                "resource_release_id": receipt_path.stem})
        if failure is None:
            raise
        failure.add_note(f"Native completion validation also failed: {receipt_error}")
    if failure is not None:
        raise failure
