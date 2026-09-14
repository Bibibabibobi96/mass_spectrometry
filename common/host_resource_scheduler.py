"""Atomic host-stage admission; SQLite reservations survive client crashes.

The PowerShell adapter supplies a fresh host/process snapshot. Budgets are
admission promises, not OS limits. No process is killed by this scheduler.
Only process death with matching creation identity releases a crashed grant;
an unresponsive but living process remains reserved.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
import sys
import uuid
from typing import Any


class StaleSnapshotError(ValueError):
    """The client must recollect telemetry; this transaction changed no state."""

def load_policy() -> dict[str, Any]:
    """Read the single versioned host admission policy, excluding scientific input."""
    return json.loads(Path(__file__).with_name("host_resource_policy.json").read_text("utf-8"))


def validate_budget(budget: dict[str, Any]) -> dict[str, Any]:
    """Validate v1 budgets; the additive heavy_stage flag defaults to false."""
    fields = {"schema_version", "cpu_cores", "memory_bytes", "io_slots",
              "exclusive_resources", "unknown_peak"}
    if set(budget) - {"heavy_stage"} != fields or budget["schema_version"] != 1:
        raise ValueError("resource budget must contain exactly the version 1 fields")
    for key in ("cpu_cores", "memory_bytes", "io_slots"):
        value = budget[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
        if key != "cpu_cores" and not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
    resources = budget["exclusive_resources"]
    if not isinstance(resources, list) or any(not isinstance(x, str) or not x.strip() for x in resources):
        raise ValueError("exclusive_resources must contain nonempty names")
    if len(resources) != len(set(resources)) or not isinstance(budget["unknown_peak"], bool):
        raise ValueError("duplicate resource names or non-boolean unknown_peak")
    if not isinstance(budget.get("heavy_stage", False), bool):
        raise ValueError("heavy_stage must be boolean")
    return {**budget, "heavy_stage": budget.get("heavy_stage", False)}


def _is_heavy(budget: dict[str, Any]) -> bool:
    return budget.get("heavy_stage", False)


def _identity(process: dict[str, Any]) -> tuple[int, str]:
    return int(process["pid"]), str(process["started"])


def _processes(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    if snapshot.get("complete") is not True:
        raise ValueError("host process snapshot is incomplete; admission is closed")
    for key in ("observed_at_ticks", "logical_processors", "total_memory_bytes", "available_memory_bytes", "cpu_percent"):
        value = snapshot.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid or unavailable host telemetry: {key}")
    if snapshot["observed_at_ticks"] <= 0 or snapshot["logical_processors"] < 1 or snapshot["cpu_percent"] > 100:
        raise ValueError("invalid host observation time, processor count, or CPU percentage")
    if snapshot["available_memory_bytes"] > snapshot["total_memory_bytes"] or not isinstance(snapshot.get("io_pressure"), bool):
        raise ValueError("invalid available memory or I/O observation")
    for process in snapshot["processes"]:
        memory = process.get("memory_bytes")
        if isinstance(memory, bool) or not isinstance(memory, int) or memory < 0:
            raise ValueError("invalid process managed memory observation")
    return {int(p["pid"]): p for p in snapshot["processes"]}


def _refresh(record: dict[str, Any], processes: dict[int, dict[str, Any]]) -> bool:
    """Retain observed descendants, including descendants of an exited owner."""
    roots = {_identity(p) for p in record["processes"]}
    live = {pid for pid, started in roots if pid in processes and str(processes[pid]["started"]) == started}
    # Windows keeps ParentProcessId after parent exit. Creation ordering avoids
    # claiming an older process when a PID has been recycled.
    parent_birth = {pid: started for pid, started in roots}
    changed = True
    while changed:
        changed = False
        for pid, process in processes.items():
            parent = int(process.get("parent_pid", 0))
            if pid in live or parent not in parent_birth:
                continue
            if str(process["started"]) < parent_birth[parent]:
                continue
            if parent in processes and str(processes[parent]["started"]) != parent_birth[parent]:
                # A child born BEFORE a reused PID's new creation time belongs
                # to the old parent; never discard that still-live orphan.
                if str(process["started"]) >= str(processes[parent]["started"]):
                    continue
            live.add(pid)
            parent_birth[pid] = str(process["started"])
            changed = True
    record["processes"] = [{"pid": pid, "started": started} for pid, started in sorted(
        roots | {_identity(processes[pid]) for pid in live})]
    record["resident_bytes"] = sum(int(processes[pid].get("memory_bytes", 0)) for pid in live)
    record["live_process_ids"] = sorted(live)
    # Console hosts stay in identity and managed-memory accounting. Only a
    # verified system image, classified by the OS adapter, is not stage work.
    record["console_host_process_ids"] = sorted(
        pid for pid in live if processes[pid].get("is_system_console_host") is True)
    return bool(live)


def _reserved(record: dict[str, Any]) -> int:
    peak = int(record["budget"]["memory_bytes"]) if record["status"] == "acquired" else 0
    return max(peak, int(record["retained_bytes"]), int(record.get("resident_bytes", 0)))


def _reason(candidate: dict[str, Any], records: list[dict[str, Any]], snapshot: dict[str, Any], policy: dict[str, Any]) -> str:
    active = [r for r in records if r is not candidate and r["status"] == "acquired"]
    parked = [r for r in records if r is not candidate and r["status"] != "acquired" and _reserved(r)]
    budget = candidate["budget"]
    if _is_heavy(budget) and any(_is_heavy(r["budget"]) for r in active):
        return "heavy_stage_active"
    exclusive = set(budget["exclusive_resources"])
    if any(exclusive.intersection(r["budget"]["exclusive_resources"]) for r in active):
        return "exclusive_resource_in_use"
    if snapshot.get("cpu_percent") is None or snapshot.get("available_memory_bytes") is None:
        return "telemetry_unavailable"
    if snapshot["cpu_percent"] >= policy["cpu_admission_percent"]:
        return "cpu_pressure"
    if not _is_heavy(budget) and snapshot["cpu_percent"] + 100 * budget["cpu_cores"] / snapshot["logical_processors"] > policy["cpu_admission_percent"]:
        return "cpu_headroom"
    if snapshot["available_memory_bytes"] < policy["memory_admission_reserve_bytes"]:
        return "memory_pressure"
    if sum(r["budget"]["cpu_cores"] for r in active) + budget["cpu_cores"] > snapshot["logical_processors"]:
        return "cpu_budget_full"
    if sum(r["budget"]["io_slots"] for r in active) + budget["io_slots"] > policy["io_slots"]:
        return "io_budget_full"
    if budget["io_slots"] and snapshot.get("io_pressure", True):
        return "io_pressure"
    others = active + parked
    candidate_peak = max(budget["memory_bytes"], candidate["retained_bytes"], candidate.get("resident_bytes", 0))
    total = sum(_reserved(r) for r in others) + candidate_peak
    # Do not double-count resident RAM already absent from available physical
    # memory. Reserve the not-yet-resident remainder of EVERY active promise.
    headroom = sum(max(0, _reserved(r) - r.get("resident_bytes", 0)) for r in others)
    headroom += max(0, candidate_peak - candidate.get("resident_bytes", 0))
    if total > snapshot["total_memory_bytes"] - policy["memory_admission_reserve_bytes"] or headroom > snapshot["available_memory_bytes"] - policy["memory_admission_reserve_bytes"]:
        return "memory_budget_full"
    return ""


def _admit(records: list[dict[str, Any]], snapshot: dict[str, Any], policy: dict[str, Any]) -> None:
    blocked: list[dict[str, Any]] = []
    barred_classes: set[bool] = set()
    for record in sorted((r for r in records if r["status"] == "waiting"), key=lambda r: r["sequence"]):
        heavy = _is_heavy(record["budget"])
        if heavy in barred_classes:
            record["reason"] = "same_class_queue_barrier"
            continue
        reason = _reason(record, records, snapshot, policy)
        if reason:
            record["reason"] = reason
            blocked.append(record)
            if record["bypasses"] >= policy["maximum_queue_bypasses"]:
                barred_classes.add(heavy)
            continue
        record["status"] = "acquired"
        record["reason"] = ""
        for older in blocked:
            if _is_heavy(older["budget"]) == heavy:
                older["bypasses"] += 1
                if older["bypasses"] >= policy["maximum_queue_bypasses"]:
                    barred_classes.add(heavy)


def transact(path: Path, request: dict[str, Any], snapshot: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply one atomic operation; errors roll back, never erase other grants."""
    policy = load_policy() if policy is None else policy
    processes = _processes(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=30)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, document TEXT NOT NULL)")
        row = connection.execute("SELECT document FROM state WHERE id=1").fetchone()
        state = json.loads(row[0]) if row else {"schema_version": 1, "sequence": 0, "records": []}
        if state["schema_version"] != 1:
            raise ValueError("unsupported scheduler state; refusing to reset live reservations")
        if snapshot["observed_at_ticks"] <= state.get("observed_at_ticks", 0):
            raise StaleSnapshotError("telemetry predates the last committed observation; recollect before retry")
        result = _apply(state, request, snapshot, processes, policy)
        state["observed_at_ticks"] = snapshot["observed_at_ticks"]
        connection.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(state),))
        return result


def _validate_capacity(budget: dict[str, Any], snapshot: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    budget = validate_budget(budget)
    if budget["cpu_cores"] > snapshot["logical_processors"] or budget["io_slots"] > policy["io_slots"]:
        raise ValueError("request exceeds configured host CPU or I/O capacity")
    if not _is_heavy(budget) and 100 * budget["cpu_cores"] / snapshot["logical_processors"] > policy["cpu_admission_percent"]:
        raise ValueError("light request exceeds the CPU admission ceiling even on an idle host")
    if budget["memory_bytes"] > snapshot["total_memory_bytes"] - policy["memory_admission_reserve_bytes"]:
        raise ValueError("request exceeds host memory capacity")
    return budget


def _apply(state: dict[str, Any], request: dict[str, Any], snapshot: dict[str, Any], processes: dict[int, dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    records = state["records"]
    unknown = set(snapshot.get("unknown_process_ids", []))
    if any(unknown.intersection(p["pid"] for p in r["processes"]) for r in records):
        raise ValueError("a reserved process creation identity is unavailable; reservations are unchanged")
    records[:] = [r for r in records if _refresh(r, processes)]
    operation = request["operation"]
    token = request.get("token")
    record = next((r for r in records if r["token"] == token), None)
    owner = request.get("owner")
    if operation == "request":
        if record is None:
            if _identity(owner) != _identity(processes.get(int(owner["pid"]), {"pid": 0, "started": ""})):
                raise ValueError("request owner creation identity is not live")
            budget = _validate_capacity(request["budget"], snapshot, policy)
            state["sequence"] += 1
            record = {"token": token or uuid.uuid4().hex, "owner": owner, "processes": [owner],
                      "role": request["role"], "run_id": request.get("run_id", ""), "stage": request["stage"],
                      "budget": budget, "sequence": state["sequence"], "status": "waiting", "reason": "queued",
                      "retained_bytes": 0, "bypasses": 0}
            _refresh(record, processes)
            records.append(record)
    elif operation == "status":
        _admit(records, snapshot, policy)
        return {"schema_version": 1, "records": records}
    elif record is None:
        if operation == "release":
            return {"status": "released", "token": token}
        raise ValueError("resource token is absent or owner and descendants have exited")
    if operation not in {"request", "status"} and owner != record["owner"]:
        if operation not in {"inherit", "register"} or int(owner["pid"]) not in record["live_process_ids"] or _identity(owner) != _identity(processes[int(owner["pid"])]):
            raise ValueError("only the owner or a live descendant may use this reservation")
    if operation == "transition":
        if record["status"] != "acquired":
            raise ValueError("stage transition requires an acquired grant")
        if any(pid != int(record["owner"]["pid"]) and pid not in record["console_host_process_ids"]
               for pid in record["live_process_ids"]):
            raise ValueError("live descendants still own this stage; wait for their terminal state before transition")
        retained = request["retained_memory_bytes"]
        if isinstance(retained, bool) or not isinstance(retained, int) or retained < 0:
            raise ValueError("retained_memory_bytes must be a nonnegative integer")
        if retained > snapshot["total_memory_bytes"] - policy["memory_admission_reserve_bytes"]:
            raise ValueError("declared retained memory exceeds host capacity")
        record["retained_bytes"] = max(retained, record["resident_bytes"])
        record["budget"] = _validate_capacity(request["budget"], snapshot, policy)
        state["sequence"] += 1
        record.update(stage=request["stage"], sequence=state["sequence"], status="waiting", bypasses=0)
    elif operation == "register":
        process = processes.get(int(request["process_id"]))
        if process is None or int(process["pid"]) not in record["live_process_ids"]:
            raise ValueError("registered process must be a live descendant of the owner")
        record["processes"].append({"pid": process["pid"], "started": process["started"]})
    elif operation == "inherit":
        if record["status"] != "acquired":
            raise ValueError("cannot inherit a waiting reservation")
        if request.get("require_heavy_stage") and not _is_heavy(record["budget"]):
            raise ValueError("execution requires an heavy stage grant")
        requested = request.get("budget")
        if requested is not None:
            requested = validate_budget(requested)
            parent = record["budget"]
            if _is_heavy(requested) and not _is_heavy(parent):
                raise ValueError("child requires an heavy stage grant")
            if not _is_heavy(parent) and not set(requested["exclusive_resources"]).issubset(parent["exclusive_resources"]):
                raise ValueError("parent grant does not own the required exclusive resources")
            exceeded = [f"{key}: requested={requested[key]}, parent={parent[key]}"
                        for key in ("cpu_cores", "memory_bytes", "io_slots") if requested[key] > parent[key]]
            if not _is_heavy(parent) and exceeded:
                raise ValueError("child requirements exceed the inherited stage budget: " + "; ".join(exceeded))
    elif operation == "release":
        # An explicit boundary release cannot discard an orphaned solver.
        children = [p for p in record["processes"] if _identity(p) != _identity(record["owner"]) and int(p["pid"]) in record["live_process_ids"]]
        # The console can outlive an interactive caller's completed task. Its
        # ordinary RAM remains in host telemetry, but owns no future task peak.
        work_children = [p for p in children if int(p["pid"]) not in record["console_host_process_ids"]]
        if work_children:
            record["processes"] = children
            record["reason"] = "owner_released_descendants_still_live"
        else:
            records.remove(record)
            return {"status": "released", "token": token}
    elif operation not in {"request", "poll", "transition", "register", "inherit"}:
        raise ValueError(f"unknown operation: {operation}")
    _admit(records, snapshot, policy)
    return dict(record)


def main() -> int:
    """Internal PowerShell JSON transport; no solver or process launching."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    try:
        result = transact(args.state, payload["request"], payload["snapshot"])
    except StaleSnapshotError:
        print("HOST_RESOURCE_SNAPSHOT_STALE", file=sys.stderr)
        return 75
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
