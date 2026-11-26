"""Check existing host ownership and writer-completion evidence for Store controls.

This is not a scheduler or an alternate host ledger. Host state is read-only;
missing/unknown state is never evidence that a process has stopped.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from contextlib import closing
from contextvars import ContextVar
from typing import Any, Mapping

from msplatform.execution.owner import validate_writer_completion
from msplatform.execution.host_resource_scheduler import _same_creation_time


_SCOPE = ContextVar("native_artifact_scope", default=None)


@contextmanager
def protect_native_controls(store, *, run_id: str, claim_ids: tuple[str, ...],
                            reservation_ids: tuple[str, ...], work_directory: Path):
    """Associate an already held Store writer and controls with one native call chain."""
    token = _SCOPE.set({"store": store, "run_id": run_id, "claim_ids": claim_ids,
                        "reservation_ids": reservation_ids, "work_directory": Path(work_directory)})
    try:
        yield
    finally:
        _SCOPE.reset(token)


def current_native_artifact_scope():
    """Return this execution context's explicit Store controls, if any."""
    return _SCOPE.get()


def acquired_host_owner(path: Path, token: str) -> dict:
    """Read the one current acquired host owner; absence never proves release."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT document FROM state WHERE id=1").fetchone()
    state = json.loads(row[0]) if row else {}
    matches = [item for item in state.get("records", []) if item.get("token") == token and item.get("status") == "acquired"]
    if len(matches) != 1:
        raise ValueError("host token has no unique acquired owner")
    owner = matches[0]["owner"]
    validate_host_binding(path, token, owner)
    return owner


def validate_host_binding(path: Path, token: str, owner: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the exact acquired scheduler token and its creation identity."""
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or not isinstance(token, str) or not token:
        raise ValueError("an existing absolute host state and token are required")
    owner = dict(owner)
    if (set(owner) != {"pid", "started"} or type(owner["pid"]) is not int or owner["pid"] <= 0
            or not isinstance(owner["started"], str) or not owner["started"].isdecimal()):
        raise ValueError("host owner requires its PID and creation identity")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT document FROM state WHERE id=1").fetchone()
    if row is None:
        raise ValueError("host scheduler state is unavailable")
    state = json.loads(row[0])
    if state.get("schema_version") != 1 or not isinstance(state.get("records"), list):
        raise ValueError("host scheduler state differs")
    matches = [item for item in state["records"] if item.get("token") == token]
    if len(matches) != 1 or matches[0].get("status") != "acquired" or matches[0].get("owner") != owner:
        raise ValueError("host token is not acquired by the stated owner")
    info = path.stat()
    return {"host_state_path": str(path.resolve()), "host_owner": owner,
            "host_file_id": [info.st_dev, info.st_ino], "record": matches[0]}


def validate_host_worker(path: Path, token: str, owner: Mapping[str, Any],
                         process_id: int, started_at_utc_ticks: int) -> None:
    """Require this worker to be an exact registered host work root."""
    record = validate_host_binding(path, token, owner)["record"]
    roots = record.get("work_roots")
    if not isinstance(roots, list) or not any(
        type(item.get("pid")) is int and item["pid"] == process_id
        and isinstance(item.get("started"), str) and item["started"].isdecimal()
        and int(item["started"]) == started_at_utc_ticks for item in roots if isinstance(item, dict)
    ):
        raise ValueError("worker is not an exact registered host work root")


def validate_native_completion(binding: Mapping[str, Any], completion: Mapping[str, Any]) -> None:
    """Validate exact operation, worker identity and owned host release receipt."""
    operation_id = binding["operation_id"]
    operations = completion.get("operations")
    releases = completion.get("resource_releases")
    if not isinstance(operations, list) or len(operations) != 1 or not isinstance(releases, list) or len(releases) != 1:
        raise ValueError("one exact native operation and release are required")
    validate_writer_completion(writers_stopped=completion.get("writers_stopped") is True,
        expected_operation_ids=(operation_id,), operations=operations, resource_releases=releases)
    observation = operations[0]["observation"]
    release = releases[0]["completion_receipt"]["host_release"]
    if (operations[0]["operation_id"] != operation_id or release["token"] != binding["host_token"]
            or observation["process_id"] != binding["worker_pid"]
            or not _same_creation_time(str(observation["process_started_at_utc_ticks"]), str(binding["worker_started"]))):
        raise ValueError("native completion does not match the bound operation, token and worker")
    path = Path(binding["host_state_path"])
    if not path.is_file():
        raise ValueError("host state is unavailable; completion cannot be reconciled")
    info = path.stat()
    if [info.st_dev, info.st_ino] != binding["host_file_id"]:
        raise ValueError("host state identity changed; completion cannot be reconciled")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT document FROM state WHERE id=1").fetchone()
    state = json.loads(row[0]) if row else None
    if (not isinstance(state, dict) or state.get("schema_version") != 1
            or not isinstance(state.get("records"), list)):
        raise ValueError("host state is unavailable; completion cannot be reconciled")
    if any(item.get("token") == binding["host_token"] for item in state["records"]):
        raise ValueError("host token remains present; its work may still be live")


def reconcile_native_receipt(store, receipt_path: Path) -> bool:
    """Reconcile the original owner's durable receipt after a controller exits."""
    path = Path(receipt_path).absolute()
    if not path.name.endswith(".receipt.json"):
        raise ValueError("native receipt role differs")
    prefix = str(path)[:-len(".receipt.json")]
    receipt = json.loads(path.read_text(encoding="utf-8"))
    worker = json.loads(Path(prefix + ".worker.json").read_text(encoding="utf-8"))
    host = json.loads(Path(prefix + ".host.json").read_text(encoding="utf-8"))
    ack = json.loads(Path(prefix + ".ack.json").read_text(encoding="utf-8"))
    nonce, binding_id = receipt.get("nonce"), receipt.get("binding_id")
    if (not isinstance(nonce, str) or not nonce or ack.get("nonce") != nonce or worker.get("nonce") != nonce
            or host.get("nonce") != nonce or ack.get("binding_id") != binding_id or worker.get("binding_id") != binding_id):
        raise ValueError("native registration and release receipts differ")
    with store._db() as db:
        row = db.execute("""SELECT b.run_id,b.host_token,b.operation_id,b.worker_pid,b.worker_started,
            b.host_state_path,b.host_file_id,e.work FROM native_bindings b
            JOIN run_execution e ON e.id=b.run_id WHERE b.id=?""", (binding_id,)).fetchone()
    if row is None or path.parent != store.root / "work" / row[7] or host.get("token") != row[1]:
        raise ValueError("native receipt is not bound to this run and host")
    native = receipt.get("receipt")
    if not isinstance(native, dict):
        raise ValueError("native owner completion is unavailable")
    if native.get("error") is not None or not isinstance(native.get("observation"), dict):
        raise ValueError("native owner completion is unavailable")
    observation = native["observation"]
    completion = {"writers_stopped": True, "operations": [{"operation_id": row[2], "resource_release_id": "host",
        "observation": {"exit_confirmed": True, "returncode": observation["exit_code"],
                        "process_id": observation["root_process_id"],
                        "process_started_at_utc_ticks": observation["root_process_started_at_utc_ticks"]}}],
        "resource_releases": [{"release_id": "host", "completion_receipt": {"host_release": native["host_release"]}}]}
    process_id, started = worker.get("process_id"), worker.get("started_at_utc_ticks")
    binding = {"host_token": row[1], "operation_id": row[2], "worker_pid": process_id,
               "worker_started": started, "host_state_path": row[5], "host_file_id": json.loads(row[6])}
    validate_native_completion(binding, completion)
    with store._transaction() as db:
        current = db.execute("SELECT worker_pid,worker_started,state FROM native_bindings WHERE id=?", (binding_id,)).fetchone()
        if current[2] == "complete":
            return False
        if current[:2] == (None, None):
            db.execute("UPDATE native_bindings SET worker_pid=?,worker_started=? WHERE id=? AND state='active'",
                       (process_id, started, binding_id))
        elif current[:2] != (process_id, started):
            raise ValueError("native registration identity differs from Store")
    return store.complete_native_controls(binding_id, completion=completion)
