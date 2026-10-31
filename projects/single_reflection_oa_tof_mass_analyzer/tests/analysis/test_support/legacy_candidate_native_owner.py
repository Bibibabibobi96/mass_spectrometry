"""Read-only Git6041 native owner source witness; never import or execute."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

# Intentionally unbound owner globals: this file is parsed as source evidence,
# never invoked as a substitute process or JSON implementation.
_run_command: Callable[..., None] | None = None
load_json: Callable[[Path], dict[str, Any]] | None = None
raise RuntimeError("Read-only Git6041 source witness; never execute")

def _run_managed_stage_command(
    command: list[str], log_path: Path, plan: dict[str, Any], receipt_path: Path,
    role: str, environment: dict[str, str] | None = None,
) -> None:
    """Carry the actual native and host-owner receipts across the PS boundary."""
    writer = plan.get("writer_completion")
    failure = None
    try:
        _run_command(command, log_path, environment)
    except BaseException as error:
        failure = error
    try:
        if writer is not None:
            release_id = receipt_path.stem
            if not receipt_path.is_file():
                writer["operations"].append({"operation_id": release_id,
                    "observation": {"exit_confirmed": False, "returncode": None},
                    "resource_release_id": release_id})
            else:
                receipt = load_json(receipt_path)
                if receipt.get("schema_version") != 1 or receipt.get("role") != role or receipt.get("run_id") != plan["run_id"]:
                    raise RuntimeError(f"native completion identity differs: {receipt_path}")
                if role in {"oatof_component_build_completion", "oatof_candidate_flight_process_result"} and receipt.get("context_sha256") != plan["context_sha256"]:
                    raise RuntimeError(f"native completion scientific context differs: {receipt_path}")
                if role == "oatof_candidate_flight_process_result":
                    operations = [{"operation_id": "flight", "observation": {
                        "exit_confirmed": receipt.get("native_exit_confirmed", False),
                        "returncode": receipt.get("native_returncode")},
                        "managed_process_completion": receipt.get("managed_process_completion")}]
                else:
                    operations = receipt["operations"]
                for operation in operations:
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
                        "observation": {key: observation.get(key) for key in ("exit_confirmed", "returncode")},
                        "resource_release_id": release_id,
                    })
                if operations:
                    writer["resource_releases"].append({"release_id": release_id, "completion_receipt": receipt})
    except BaseException as receipt_error:
        if writer is not None:
            writer["operations"].append({"operation_id": receipt_path.stem + ".unconfirmed",
                "observation": {"exit_confirmed": False, "returncode": None},
                "resource_release_id": receipt_path.stem})
        if failure is None:
            raise
        failure.add_note(f"Native completion validation also failed: {receipt_error}")
    if failure is not None:
        raise failure
