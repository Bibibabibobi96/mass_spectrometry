"""Bounded startup admission and ledger-only artifact maintenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from common.contracts import capacity_ledger
from common.contracts import capacity_protection as protection
from common.contracts.execution_aliases import execution_alias_root_is_valid
from common.contracts.historical_source_scratch_retirement import apply as apply_source_scratch_disposition
from common.contracts.historical_source_scratch_retirement import plan as plan_source_scratch_disposition
from common.contracts.legacy_owner_disposition import activate_owner_dispositions
from common.contracts.file_identity import file_sha256
from common.contracts.recorded_file_removal import remove_recorded_files, write_json_atomic

GIB = 1024**3
POLICY_PATH = Path(__file__).with_name("artifact_capacity_policy.json")
DISPOSAL_RECEIPT_DIRECTORY = Path("common") / "capacity_disposal_receipts"
CAPACITY_LEDGER_RELATIVE_PATH = capacity_ledger.CAPACITY_LEDGER_RELATIVE_PATH
SCRATCH_DISPOSITION_DIRECTORY = Path("common") / "capacity_calibration" / "scratch_dispositions"

# Compatibility exports for existing publishers while they move to the ledger module.
_load_capacity_ledger = capacity_ledger.load_capacity_ledger
record_capacity_object = capacity_ledger.record_capacity_object
retire_capacity_object = capacity_ledger.retire_capacity_object
touch_capacity_object = capacity_ledger.touch_capacity_object


class _PhaseTimings:
    """Collect bounded phase timings; thresholds warn without changing safety."""

    def __init__(self, warning_seconds: float, review_seconds: float) -> None:
        self.started = time.perf_counter()
        self.phases: dict[str, float] = {}
        self.warning_seconds = warning_seconds
        self.review_seconds = review_seconds

    @contextmanager
    def phase(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = self.phases.get(name, 0.0) + time.perf_counter() - started

    def finish(self) -> dict[str, Any]:
        total = time.perf_counter() - self.started
        warnings: list[dict[str, Any]] = []
        for name, seconds in [("total", total), *self.phases.items()]:
            if seconds > self.review_seconds:
                code, threshold = "PERFORMANCE_REVIEW_REQUIRED", self.review_seconds
            elif seconds > self.warning_seconds:
                code, threshold = "PERFORMANCE_WARNING", self.warning_seconds
            else:
                continue
            warnings.append({
                "scope": "total" if name == "total" else "phase",
                "name": name, "seconds": round(seconds, 6),
                "threshold_seconds": threshold, "code": code,
            })
        return {
            "total_seconds": round(total, 6),
            "phases_seconds": {key: round(value, 6) for key, value in self.phases.items()},
            "performance_warnings": warnings,
        }


def _load_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _capacity_policy() -> dict[str, Any]:
    policy = _load_object(POLICY_PATH)
    expected = {
        "schema_version", "role", "description", "target_gib", "minimum_free_gib",
        "light_evidence_budget_bytes", "startup_gate_target_seconds",
        "startup_gate_deadline_seconds", "eviction_order",
    }
    if policy is None or set(policy) != expected:
        raise RuntimeError("artifact capacity policy fields differ")
    if policy.get("schema_version") != 2 or policy.get("role") != "artifact_capacity_policy":
        raise RuntimeError("artifact capacity policy identity differs")
    for field, positive in (
        ("target_gib", True), ("minimum_free_gib", False),
        ("light_evidence_budget_bytes", False),
        ("startup_gate_target_seconds", True), ("startup_gate_deadline_seconds", True),
    ):
        value = policy.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise RuntimeError(f"artifact capacity policy {field} is invalid")
        if value < 0 or (positive and value <= 0):
            raise RuntimeError(f"artifact capacity policy {field} is invalid")
    if policy["startup_gate_deadline_seconds"] < policy["startup_gate_target_seconds"]:
        raise RuntimeError("artifact capacity policy timing thresholds are inverted")
    if policy.get("eviction_order") != [
        "rebuildable_payload", "published_cache",
    ]:
        raise RuntimeError("artifact capacity policy eviction_order differs")
    return policy


def _timings(policy: dict[str, Any] | None = None) -> _PhaseTimings:
    value = policy or _capacity_policy()
    return _PhaseTimings(
        float(value["startup_gate_target_seconds"]),
        float(value["startup_gate_deadline_seconds"]),
    )


def _finish(receipt: dict[str, Any], timings: _PhaseTimings, mode: str) -> dict[str, Any]:
    receipt["execution_mode"] = mode
    receipt["timing"] = timings.finish()
    return receipt


def _required_scope(
    root: Path, current_lease: dict[str, Any], required_paths: Iterable[Path],
    required_cache_keys: Iterable[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return canonical required scope and the subset absent from this lease."""

    root_resolved = root.resolve(strict=False)
    lease_paths = tuple(
        Path(item).resolve(strict=False)
        for item in current_lease.get("protected_paths", ())
    )
    canonical_paths: list[str] = []
    missing_paths: list[str] = []
    for item in required_paths:
        target = Path(item)
        if not target.is_absolute():
            target = root / target
        target = target.resolve(strict=False)
        if target != root_resolved and root_resolved not in target.parents:
            raise ValueError(f"required input path escapes artifact root: {item}")
        canonical_paths.append(str(target))
        if not any(target == protected or protected in target.parents for protected in lease_paths):
            missing_paths.append(str(target))
    lease_keys = set(current_lease.get("protected_cache_keys", ()))
    canonical_keys: list[str] = []
    missing_keys: list[str] = []
    for item in required_cache_keys:
        key = str(item).lower()
        if protection.CACHE_KEY.fullmatch(key) is None:
            raise ValueError(f"required input cache key is not a SHA-256: {item}")
        canonical_keys.append(key)
        if key not in lease_keys:
            missing_keys.append(key)
    return (
        sorted(set(canonical_paths)), sorted(set(canonical_keys)),
        sorted(set(missing_paths)), sorted(set(missing_keys)),
    )


def _startup_capacity_gate(
    root: Path, *, target_bytes: int, minimum_free_bytes: int,
    required_paths: Iterable[Path], required_cache_keys: Iterable[str],
    capacity_ledger_path: Path | None,
    capacity_protection_lease_id: str | None,
) -> dict[str, Any]:
    timings = _timings()
    with timings.phase("disk_usage"):
        free_bytes = shutil.disk_usage(root).free
    with timings.phase("ledger_and_leases"):
        ledger = capacity_ledger.load_capacity_ledger(root, capacity_ledger_path)
        leases = protection.load_capacity_protection_leases(root)
    if not capacity_protection_lease_id:
        raise ValueError("startup requires capacity_protection_lease_id")
    current_lease = next((
        item for item in leases["audit"]
        if item.get("status") == "active"
        and item.get("lease_id") == capacity_protection_lease_id
    ), None)
    required = ([], [], [], [])
    if current_lease is not None:
        required = _required_scope(
            root, current_lease, required_paths, required_cache_keys,
        )
    current_commitment = (
        None if current_lease is None else int(current_lease["committed_new_bytes"])
    )
    total_commitment = int(leases["committed_new_bytes"])
    other_commitment = (
        None if current_commitment is None else total_commitment - current_commitment
    )
    required_free = minimum_free_bytes + total_commitment
    resident = None if ledger is None else int(ledger["resident_bytes"])
    writing = [] if ledger is None else [
        item for item in ledger["objects"] if item.get("status") == "writing"
    ]
    overdue_writing = [
        item for item in writing
        if date.fromisoformat(item["review_deadline"]) < date.today()
    ]
    # An overdue heavy write has unknown recovery state and can invalidate the
    # repository-wide capacity projection.  It blocks every new heavy write,
    # not just consumers that happen to name the same path.
    blocking_overdue_writing = list(overdue_writing)
    projected = None if resident is None else resident + total_commitment
    legacy_unknown = int(leases["legacy_unknown_commitment_count"])
    scope_satisfied = current_lease is not None and not required[2] and not required[3]
    safe = bool(
        projected is not None
        and projected <= target_bytes
        and free_bytes >= required_free
        and scope_satisfied
        and legacy_unknown == 0
        and not blocking_overdue_writing
    )
    if ledger is None:
        blocking_reason = "CAPACITY_LEDGER_REQUIRED"
    elif current_lease is None:
        blocking_reason = "CURRENT_LEASE_REQUIRED"
    elif legacy_unknown:
        blocking_reason = "ACTIVE_LEASE_COMMITMENT_UNKNOWN"
    elif blocking_overdue_writing:
        blocking_reason = "WRITING_RECOVERY_REVIEW_OVERDUE"
    elif not scope_satisfied:
        blocking_reason = "CURRENT_LEASE_SCOPE_INCOMPLETE"
    elif projected > target_bytes:
        blocking_reason = "TARGET_CAPACITY_EXCEEDED"
    elif free_bytes < required_free:
        blocking_reason = "MINIMUM_FREE_CAPACITY_UNAVAILABLE"
    else:
        blocking_reason = None
    ledger_location = capacity_ledger_path or root / CAPACITY_LEDGER_RELATIVE_PATH
    return _finish({
        "schema_version": 1, "role": "artifact_capacity_gate",
        "artifact_root": str(root), "target_bytes": target_bytes,
        "minimum_free_bytes": minimum_free_bytes, "free_bytes_before": free_bytes,
        "resident_bytes": resident, "required_free_bytes": required_free,
        "free_deficit_bytes": max(0, required_free - free_bytes),
        "required_input_paths": required[0], "required_input_cache_keys": required[1],
        "missing_current_lease_paths": required[2],
        "missing_current_lease_cache_keys": required[3],
        "protection_lease_audit": leases["audit"],
        "capacity_protection_lease_id": capacity_protection_lease_id,
        "current_lease_committed_new_bytes": current_commitment,
        "other_leases_committed_new_bytes": other_commitment,
        "total_active_lease_committed_new_bytes": total_commitment,
        "active_legacy_unknown_commitment_count": legacy_unknown,
        "writing_object_count": len(writing),
        "overdue_writing_object_count": len(overdue_writing),
        "blocking_overdue_writing_object_count": len(blocking_overdue_writing),
        "overdue_writing_objects": [
            {
                "path": item["path"], "owner": item["owner"],
                "recovery_reason": item["recovery_reason"],
                "review_deadline": item["review_deadline"],
            }
            for item in overdue_writing
        ],
        "capacity_ledger": str(ledger_location.absolute()),
        "ledger_status": "accepted" if ledger is not None else "missing_or_invalid",
        "measurement_mode": "STARTUP_LEDGER" if ledger is not None else "STARTUP_BLOCKED_LEDGER_REQUIRED",
        "candidate_discovery_performed": False, "candidate_count": None,
        "planned": [], "projected_bytes": projected, "satisfied": safe,
        "blocking_reason": blocking_reason,
    }, timings, "startup")


def _ledger_candidates(
    root: Path, ledger: dict[str, Any], protected_paths: Iterable[Path],
    protected_cache_keys: Iterable[str], policy: dict[str, Any],
) -> list[dict[str, Any]]:
    protected = tuple(Path(item).resolve(strict=False) for item in protected_paths)
    keys = {str(item).lower() for item in protected_cache_keys}
    eviction_order = {name: index for index, name in enumerate(policy["eviction_order"])}
    candidates: list[dict[str, Any]] = []
    for item in ledger["objects"]:
        object_class = item.get("class")
        if object_class not in {"published_cache", "rebuildable_payload"}:
            continue
        disposition = item.get("disposition")
        if object_class == "published_cache" and item.get("manager") != capacity_ledger.PA_CACHE_MANAGER:
            continue
        allowed_status = {"ready", "retirement_pending"}
        if item.get("status") not in allowed_status or item.get("pin") is True:
            continue
        target, _ = capacity_ledger.capacity_object_path(root, item["path"])
        if protection.path_is_protected(target, protected) or target.name.lower() in keys:
            continue
        candidates.append({
            "operation": (
                "retire_approved_disposition" if disposition
                else "request_retirement" if object_class == "published_cache"
                else "retire_ledger_object"
            ),
            "disposition_id": None if disposition is None else disposition["id"],
            "manager": item.get("manager"),
            "generation": item.get("identity"),
            "cache_key": target.name.lower() if object_class == "published_cache" else None,
            "class": item["class"], "bytes": int(item["bytes"]),
            "timestamp": float(item.get("last_used_epoch", 0) or 0),
            "eviction_order": -1 if disposition else eviction_order[item["class"]],
            "reason": f"ledger_ready_{item['class']}",
            "path": str(target), "must_resume": item.get("status") == "retirement_pending",
        })
    return sorted(
        candidates,
        key=lambda item: (
            not item["must_resume"], item["eviction_order"],
            -item["bytes"] if item["class"] == "rebuildable_payload" else 0,
            item["timestamp"], item["path"],
        ),
    )


def _lease_ids_for_target(
    target: Path, cache_key: str | None, leases: dict[str, Any],
) -> list[str]:
    """Return active lease ids that prevent one exact ledger retirement."""

    matched: list[str] = []
    for lease in leases["audit"]:
        if lease.get("status") != "active":
            continue
        paths = (Path(value).resolve(strict=False) for value in lease.get("protected_paths", ()))
        keys = {str(value).lower() for value in lease.get("protected_cache_keys", ())}
        if protection.path_is_protected(target, paths) or (
            cache_key is not None and cache_key.lower() in keys
        ):
            matched.append(str(lease["lease_id"]))
    return sorted(matched)


def _maintenance_management_summary(
    root: Path, ledger: dict[str, Any], leases: dict[str, Any], *,
    target_bytes: int, required_free_bytes: int, free_bytes: int,
    planned: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Describe managed ranges and automatic next actions without discovery.

    The ledger remains the only source of lifecycle truth.  This summary is
    intentionally a projection: it neither infers owners for external scopes
    nor changes an object's status while reporting it.
    """

    planned_paths = {str(item["path"]) for item in planned}
    aggregates: dict[tuple[str, str, str], dict[str, int]] = {}
    blocked: list[dict[str, Any]] = []
    for item in ledger["objects"]:
        if item.get("status") == "retired":
            continue
        target, _ = capacity_ledger.capacity_object_path(root, item["path"])
        owner = str(item.get("owner", ""))
        aggregate_key = (owner, str(item["class"]), str(item["status"]))
        aggregate = aggregates.setdefault(aggregate_key, {"object_count": 0, "bytes": 0})
        aggregate["object_count"] += 1
        aggregate["bytes"] += int(item["bytes"])
        cache_key = target.name if item["class"] == "published_cache" else None
        lease_ids = _lease_ids_for_target(target, cache_key, leases)
        action: str | None = None
        reason: str | None = None
        if item["status"] == "writing":
            action, reason = "recover_or_disposition", "writing_requires_owner_recovery"
        elif item.get("pin") is True:
            action, reason = "review_pin_for_release", "object_is_pinned"
        elif lease_ids:
            action, reason = "wait_for_or_release_protection_lease", "active_protection_lease"
        elif item["class"] == "light_evidence":
            action, reason = "review_retention_route", "light_evidence_is_not_auto_retired"
        elif str(target) not in planned_paths and item["status"] == "ready":
            # Ready unprotected payloads are valid auto-retirement candidates,
            # but are retained when the configured target is already satisfied.
            action, reason = "retained_until_capacity_requires_retirement", "ready_governed_payload"
        if action is not None:
            blocked.append({
                "owner": owner,
                "path": str(target),
                "class": item["class"],
                "status": item["status"],
                "bytes": int(item["bytes"]),
                "action": action, "reason": reason,
                "protection_lease_ids": lease_ids,
                "recovery_reason": item.get("recovery_reason"),
                "recovery_task": item.get("recovery_task"),
            })
    grouped = [
        {
            "owner": owner, "class": object_class, "status": status,
            "object_count": object_count,
            "bytes": bytes_count,
        }
        for (owner, object_class, status), values in aggregates.items()
        for bytes_count, object_count in [(values["bytes"], values["object_count"])]
    ]
    grouped.sort(key=lambda item: (
        item["owner"], item["class"], item["status"],
    ))
    blocked.sort(key=lambda item: (item["owner"], item["action"], item["path"]))
    resident = int(ledger["resident_bytes"])
    limit = min(target_bytes, resident - max(0, required_free_bytes - free_bytes))
    return {
        "governed_object_groups": grouped,
        "external_scope_groups": [
            {"role": item["role"], "path": item["path"], "bytes": int(item["bytes"])}
            for item in sorted(ledger["external_scopes"], key=lambda value: value["role"])
        ],
        "blocked_owner_actions": blocked,
        "resumable_retirement_count": sum(
            item["status"] == "retirement_pending" for item in ledger["objects"]
        ),
        "capacity_gap_bytes": max(0, resident - limit),
        "next_active_commitments": {
            "committed_new_bytes": int(leases["committed_new_bytes"]),
            "legacy_unknown_commitment_count": int(leases["legacy_unknown_commitment_count"]),
            "required_free_bytes": required_free_bytes,
        },
    }


def _maintenance_plan(
    root: Path, *, target_bytes: int, minimum_free_bytes: int,
    protected_paths: Iterable[Path],
    protected_cache_keys: Iterable[str], capacity_ledger_path: Path | None,
) -> dict[str, Any]:
    policy = _capacity_policy()
    timings = _timings(policy)
    with timings.phase("ledger_and_leases"):
        ledger = capacity_ledger.load_capacity_ledger(root, capacity_ledger_path)
        leases = protection.load_capacity_protection_leases(root)
    if ledger is None:
        return _finish({
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "measurement_mode": "MAINTENANCE_LEDGER_REQUIRED",
            "candidate_discovery_performed": False, "candidate_count": None,
            "planned": [], "satisfied": False,
            "blocking_reason": "SAFETY_DECISION_UNAVAILABLE",
        }, timings, "maintenance")
    if ledger.get("schema_version") != 3:
        return _finish({
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "measurement_mode": "MAINTENANCE_LIFECYCLE_LEDGER_V3_REQUIRED",
            "candidate_discovery_performed": False, "candidate_count": None,
            "planned": [], "satisfied": False,
            "blocking_reason": "LIFECYCLE_LEDGER_V3_REQUIRED",
        }, timings, "maintenance")
    with timings.phase("disk_usage"):
        free_bytes = shutil.disk_usage(root).free
    measured = int(ledger["resident_bytes"])
    if int(leases["legacy_unknown_commitment_count"]):
        return _finish({
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "measurement_mode": "MAINTENANCE_LEASE_COMMITMENT_REQUIRED",
            "candidate_discovery_performed": False, "candidate_count": None,
            "planned": [], "satisfied": False,
            "blocking_reason": "ACTIVE_LEASE_COMMITMENT_UNKNOWN",
        }, timings, "maintenance")
    required_free = minimum_free_bytes + int(leases["committed_new_bytes"])
    candidates = _ledger_candidates(
        root, ledger, [*protected_paths, *leases["protected_paths"]],
        [*protected_cache_keys, *leases["protected_cache_keys"]], policy,
    )
    limit = min(target_bytes, measured - max(0, required_free - free_bytes))
    projected = measured
    planned: list[dict[str, Any]] = []
    for candidate in candidates:
        if projected <= limit and not candidate["must_resume"]:
            break
        planned.append(candidate)
        projected -= candidate["bytes"]
    ledger_location = capacity_ledger_path or root / CAPACITY_LEDGER_RELATIVE_PATH
    management_summary = _maintenance_management_summary(
        root, ledger, leases, target_bytes=target_bytes,
        required_free_bytes=required_free, free_bytes=free_bytes, planned=planned,
    )
    return _finish({
        "schema_version": 1, "role": "artifact_capacity_gate",
        "artifact_root": str(root), "target_bytes": target_bytes,
        "minimum_free_bytes": minimum_free_bytes, "free_bytes_before": free_bytes,
        "required_free_bytes": required_free, "measured_bytes": measured,
        "candidate_discovery_performed": True, "candidate_count": len(candidates),
        "planned": planned, "planned_bytes": sum(item["bytes"] for item in planned),
        "projected_bytes": projected, "satisfied": projected <= limit,
        "capacity_ledger": str(ledger_location.absolute()),
        "protection_lease_audit": leases["audit"],
        "management_summary": management_summary,
        "measurement_mode": "LEDGER_MAINTENANCE",
    }, timings, "maintenance")


def _reconcile_execution_alias_root(root: Path) -> dict[str, int]:
    """Correct the zero-byte administrative junction range without scanning targets."""

    alias_root = root / "common" / "execution_aliases"
    if not alias_root.exists():
        return {"corrected_count": 0, "released_bytes": 0}
    if not execution_alias_root_is_valid(root, alias_root):
        raise RuntimeError("execution alias root is not a bounded internal junction set")
    ledger = capacity_ledger.load_capacity_ledger(root)
    if ledger is None:
        raise RuntimeError("capacity ledger is missing or invalid")
    recorded = next((
        item for item in ledger["objects"]
        if item.get("path") == "common/execution_aliases" and item.get("status") != "retired"
    ), None)
    if recorded is None:
        raise RuntimeError("execution alias root is absent from the calibrated ledger")
    if (
        recorded.get("class") != "light_evidence"
        or recorded.get("owner") != "common.run_artifact_support"
    ):
        raise RuntimeError("execution alias root has an unexpected ledger identity")
    previous_bytes = int(recorded["bytes"])
    if previous_bytes:
        capacity_ledger.record_capacity_object(
            root, path=alias_root, object_class="light_evidence", bytes_count=0,
            owner="common.run_artifact_support",
        )
    return {
        "corrected_count": int(previous_bytes != 0),
        "released_bytes": previous_bytes,
    }


def _register_workspace_scratch_scope(root: Path) -> dict[str, int]:
    """Account for the workspace scratch once, before daily planning."""

    if not root.is_dir():
        return {"registered_count": 0, "registered_bytes": 0}
    source = root.parent / "scratch"
    if not source.exists():
        return {"registered_count": 0, "registered_bytes": 0}
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError("workspace scratch is not a regular directory")
    ledger = capacity_ledger.load_capacity_ledger(root)
    if ledger is None:
        raise RuntimeError("capacity ledger is missing or invalid")
    existing = next((
        item for item in ledger["external_scopes"]
        if item["role"] == "repository_workspace_scratch"
    ), None)
    if existing is not None:
        if existing["path"] != str(source.resolve(strict=False)):
            raise RuntimeError("workspace scratch scope identity differs")
        return {"registered_count": 0, "registered_bytes": int(existing["bytes"])}
    measured = sum(item.stat().st_size for item in source.rglob("*") if item.is_file())
    capacity_ledger.record_external_scope(
        root, role="repository_workspace_scratch", path=source, bytes_count=measured,
    )
    return {"registered_count": 1, "registered_bytes": measured}


def _resume_source_scratch_dispositions(root: Path) -> dict[str, int]:
    """Apply exact owner-authorized source-scratch dispositions during maintenance."""

    directory = root / SCRATCH_DISPOSITION_DIRECTORY
    if not directory.exists():
        return {"completed_count": 0, "newly_removed_bytes": 0, "evidence_archived_count": 0}
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError("source scratch disposition directory is not regular")
    completed_count, newly_removed_bytes = 0, 0
    for evidence in sorted(directory.iterdir()):
        if not evidence.is_file() or evidence.is_symlink() or evidence.suffix != ".json":
            raise RuntimeError("source scratch disposition directory permits only direct JSON documents")
        try:
            document = json.loads(evidence.read_text(encoding="utf-8-sig"))
            source = Path(str(document["source_root"])).resolve(strict=False)
            owner = str(document["owner"])
        except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("source scratch disposition evidence is unreadable") from exc
        digest = file_sha256(evidence)
        receipt_path = root / DISPOSAL_RECEIPT_DIRECTORY / f"source_scratch_{digest.upper()}.json"
        prior = _load_object(receipt_path)
        prior_progress = {
            item["path"] for item in prior.get("removal_progress", [])
        } if isinstance(prior, dict) else set()
        if source.exists():
            completed = apply_source_scratch_disposition(plan_source_scratch_disposition(
                root, source_root=source, owner=owner, evidence=evidence,
                evidence_sha256=digest,
            ))
        else:
            try:
                completed = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("missing source scratch completion receipt") from exc
        if completed.get("status") != "complete":
            raise RuntimeError("source scratch disposition did not complete")
        bytes_by_path = {item["path"]: int(item["bytes"]) for item in completed["files"]}
        newly_removed_bytes += sum(
            bytes_by_path[item["path"]]
            for item in completed.get("removal_progress", [])
            if item["path"] not in prior_progress and item.get("outcome") == "removed"
        )
        completed_count += 1
        evidence.unlink()
    return {
        "completed_count": completed_count,
        "newly_removed_bytes": newly_removed_bytes,
        "evidence_archived_count": completed_count,
    }


def plan(
    root: Path, *, target_bytes: int, minimum_free_bytes: int,
    protected_paths: Iterable[Path] = (), protected_cache_keys: Iterable[str] = (),
    execution_mode: str = "startup",
    capacity_ledger: Path | None = None,
    capacity_protection_lease_id: str | None = None,
) -> dict[str, Any]:
    """Plan one bounded startup decision or ledger-only maintenance pass."""

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    if execution_mode not in {"startup", "maintenance"}:
        raise ValueError("execution mode must be startup or maintenance")
    for value, name in (
        (target_bytes, "target bytes"), (minimum_free_bytes, "minimum free bytes"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if execution_mode == "startup":
        return _startup_capacity_gate(
            root, target_bytes=target_bytes, minimum_free_bytes=minimum_free_bytes,
            required_paths=protected_paths, required_cache_keys=protected_cache_keys,
            capacity_ledger_path=capacity_ledger,
            capacity_protection_lease_id=capacity_protection_lease_id,
        )
    return _maintenance_plan(
        root, target_bytes=target_bytes, minimum_free_bytes=minimum_free_bytes,
        protected_paths=protected_paths, protected_cache_keys=protected_cache_keys,
        capacity_ledger_path=capacity_ledger,
    )


def _inventory_target(root: Path, target: Path) -> tuple[Path, list[dict[str, Any]]]:
    if target.is_symlink():
        raise ValueError(f"ledger retirement target is a symbolic link: {target}")
    files = [target] if target.is_file() else sorted(
        (item for item in target.rglob("*") if item.is_file()), key=str,
    )
    if not target.exists():
        files = []
    if target.exists() and not target.is_file() and not target.is_dir():
        raise ValueError(f"ledger retirement target is not a regular tree: {target}")
    if target.is_dir() and any(item.is_symlink() for item in target.rglob("*")):
        raise ValueError(f"ledger retirement target contains a symbolic link: {target}")
    inventory_root = target.parent if target.is_file() else target
    records = [{
        "path": item.relative_to(inventory_root).as_posix(),
        "bytes": item.stat().st_size, "sha256": file_sha256(item),
    } for item in files]
    return inventory_root, records


def _remove_ledger_target(root: Path, target: Path, expected_bytes: int) -> tuple[Path, int]:
    identity = hashlib.sha256(str(target).encode("utf-8")).hexdigest()
    receipt_path = root / DISPOSAL_RECEIPT_DIRECTORY / f"ledger_{identity}.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        records = receipt.get("files")
        inventory_root = Path(str(receipt.get("inventory_root", ""))).resolve(strict=False)
        if (
            receipt.get("role") != "artifact_capacity_disposal_receipt"
            or receipt.get("reason") != "ledger_object_retirement"
            or receipt.get("target_path") != str(target)
            or receipt.get("expected_bytes") != expected_bytes
            or not isinstance(records, list)
            or sum(int(item.get("bytes", -1)) for item in records) != expected_bytes
            or inventory_root not in {target, target.parent}
        ):
            raise ValueError("ledger disposal receipt conflicts with calibrated object")
        if receipt.get("status") == "complete":
            if target.exists():
                raise ValueError("completed ledger disposal target reappeared")
            return receipt_path, expected_bytes
        if receipt.get("status") != "pending":
            raise ValueError("ledger disposal receipt has an invalid status")
    else:
        inventory_root, records = _inventory_target(root, target)
        measured = sum(int(item["bytes"]) for item in records)
        if measured != expected_bytes:
            raise ValueError(
                f"ledger target bytes {measured} differ from calibrated {expected_bytes}"
            )
        receipt = {
            "schema_version": 1, "role": "artifact_capacity_disposal_receipt",
            "status": "pending", "reason": "ledger_object_retirement",
            "target_path": str(target), "inventory_root": str(inventory_root),
            "expected_bytes": expected_bytes, "files": records,
            "removed": [], "deleting_path": None, "removed_bytes": 0,
        }
        write_json_atomic(receipt_path, receipt)
    removed = set(receipt.get("removed", []))
    active = receipt.get("deleting_path")
    if active and active not in removed and not (inventory_root / active).exists():
        removed.add(active)
        receipt.update(removed=sorted(removed), deleting_path=None)
        receipt["removed_bytes"] = sum(
            int(item["bytes"]) for item in records if item["path"] in removed
        )
        write_json_atomic(receipt_path, receipt)
    for record in records:
        relative = record["path"]
        if relative in removed:
            if (inventory_root / relative).exists():
                raise ValueError("recorded ledger deletion reappeared")
            continue
        receipt["deleting_path"] = relative
        write_json_atomic(receipt_path, receipt)
        _delete_ledger_file(inventory_root, record)
        removed.add(relative)
        receipt.update(removed=sorted(removed), deleting_path=None)
        receipt["removed_bytes"] = sum(
            int(item["bytes"]) for item in records if item["path"] in removed
        )
        write_json_atomic(receipt_path, receipt)
    declared = {str(item["path"]) for item in records}
    if not target.exists():
        if removed != declared:
            raise ValueError("ledger target disappeared before its receipt proved full removal")
        receipt["status"] = "complete"
        write_json_atomic(receipt_path, receipt)
        return receipt_path, expected_bytes
    if target.is_dir():
        for directory in sorted(
            (item for item in target.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts), reverse=True,
        ):
            directory.rmdir()
        target.rmdir()
    receipt["status"] = "complete"
    write_json_atomic(receipt_path, receipt)
    return receipt_path, expected_bytes


def _delete_ledger_file(root: Path, record: dict[str, Any]) -> None:
    # `_inventory_target` has already performed the one complete SHA-256
    # validation and durably recorded that identity before this call.  The
    # object is retirement-pending, so no governed consumer can begin using
    # it.  Rehashing the same multi-gigabyte file here only turns ordinary
    # maintenance into a second full disk pass; `remove_recorded_files` still
    # verifies the exact path, regular-file status, and byte length.
    for _ in remove_recorded_files(root, [record], identities_verified=True):
        pass


def _validate_disposition_tree(target: Path, records: list[dict[str, Any]]) -> None:
    if not target.is_dir() or target.is_symlink():
        raise ValueError("approved disposition target must be one regular directory")
    actual: dict[str, int] = {}
    for item in target.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"approved disposition contains a symbolic link: {item}")
        if item.is_file():
            actual[item.relative_to(target).as_posix()] = item.stat().st_size
    declared = {str(item["path"]): int(item["bytes"]) for item in records}
    if actual != declared:
        raise ValueError("approved disposition tree differs from its sealed file inventory")


def _delete_approved_file(root: Path, record: dict[str, Any]) -> None:
    for _ in remove_recorded_files(root, [record], identities_verified=True):
        pass


def _remove_approved_disposition(
    root: Path, target: Path, entry: dict[str, Any],
) -> tuple[Path, int]:
    disposition = entry["disposition"]
    records = disposition["files"]
    receipt_path = (
        root / DISPOSAL_RECEIPT_DIRECTORY / f"ledger_disposition_{disposition['id']}.json"
    )
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        if (
            receipt.get("role") != "artifact_capacity_disposal_receipt"
            or receipt.get("disposition") != disposition
            or receipt.get("target_path") != str(target)
        ):
            raise ValueError("approved disposition receipt conflicts with ledger")
        if receipt.get("status") == "complete":
            if target.exists():
                raise ValueError("completed approved disposition target reappeared")
            return receipt_path, int(entry["bytes"])
        if receipt.get("status") != "pending":
            raise ValueError("approved disposition receipt has an invalid status")
    else:
        _validate_disposition_tree(target, records)
        receipt = {
            "schema_version": 1, "role": "artifact_capacity_disposal_receipt",
            "status": "pending", "reason": "manager_approved_disposition",
            "target_path": str(target), "disposition": disposition,
            "removed": [], "deleting_path": None, "removed_bytes": 0,
        }
        write_json_atomic(receipt_path, receipt)
    removed = set(receipt["removed"])
    active = receipt.get("deleting_path")
    if active and active not in removed and not (target / active).exists():
        removed.add(active)
        receipt.update(removed=sorted(removed), deleting_path=None)
        receipt["removed_bytes"] = sum(
            int(item["bytes"]) for item in records if item["path"] in removed
        )
        write_json_atomic(receipt_path, receipt)
    for record in records:
        relative = record["path"]
        if relative in removed:
            if (target / relative).exists():
                raise ValueError("recorded disposition deletion reappeared")
            continue
        receipt["deleting_path"] = relative
        write_json_atomic(receipt_path, receipt)
        _delete_approved_file(target, record)
        removed.add(relative)
        receipt.update(removed=sorted(removed), deleting_path=None)
        receipt["removed_bytes"] = sum(
            int(item["bytes"]) for item in records if item["path"] in removed
        )
        write_json_atomic(receipt_path, receipt)
    declared = {str(item["path"]) for item in records}
    if not target.exists():
        if removed != declared:
            raise ValueError(
                "approved disposition target disappeared before full removal was recorded"
            )
        receipt["status"] = "complete"
        write_json_atomic(receipt_path, receipt)
        return receipt_path, int(entry["bytes"])
    for directory in sorted(
        (item for item in target.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts), reverse=True,
    ):
        directory.rmdir()
    target.rmdir()
    receipt["status"] = "complete"
    write_json_atomic(receipt_path, receipt)
    return receipt_path, int(entry["bytes"])


def _apply_ledger_object(root: Path, item: dict[str, Any], ledger_path: Path) -> dict[str, Any]:
    target, _ = capacity_ledger.capacity_object_path(root, item["path"])
    if item.get("operation") == "request_retirement":
        if item.get("manager") != capacity_ledger.PA_CACHE_MANAGER:
            raise ValueError("published cache manager is not registered")
        from common.simion.pa_family_cache import approve_pa_family_cache_retirement

        approve_pa_family_cache_retirement(
            target.parent, item["cache_key"], item["generation"],
        )
        ledger = capacity_ledger.load_capacity_ledger(root, ledger_path)
        entry = next(
            (value for value in ledger["objects"] if value.get("path") == capacity_ledger.capacity_object_path(root, target)[1]),
            None,
        ) if ledger is not None else None
        if entry is None or "disposition" not in entry:
            raise ValueError("PA manager did not publish an approved ledger disposition")
        item = {
            **item, "operation": "retire_approved_disposition",
            "disposition_id": entry["disposition"]["id"],
        }
    if item.get("operation") == "retire_approved_disposition":
        try:
            entry = capacity_ledger.begin_approved_disposition(
                root, path=target, disposition_id=item["disposition_id"],
                ledger_path=ledger_path,
            )
            disposal_receipt, removed = _remove_approved_disposition(root, target, entry)
            capacity_ledger.finalize_retirement(
                root, path=target, removed_bytes=removed, ledger_path=ledger_path,
            )
        except Exception as exc:
            capacity_ledger.record_retirement_error(
                root, path=target, ledger_path=ledger_path,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        return {
            "path": str(target), "bytes": removed,
            "disposal_receipt": str(disposal_receipt),
        }
    expected = capacity_ledger.mark_retirement_pending(
        root, path=target, ledger_path=ledger_path,
    )
    try:
        disposal_receipt, removed = _remove_ledger_target(root, target, expected)
        capacity_ledger.finalize_retirement(
            root, path=target, removed_bytes=removed, ledger_path=ledger_path,
        )
    except Exception as exc:
        capacity_ledger.record_retirement_error(
            root, path=target, ledger_path=ledger_path,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    return {"path": str(target), "bytes": removed, "disposal_receipt": str(disposal_receipt)}


def _maintenance_apply_timings(receipt: dict[str, Any]) -> _PhaseTimings:
    """Continue a maintenance plan's timing receipt through apply and recheck.

    Planning and retirement happen in separate calls so callers can inspect a
    plan before taking a host lease.  When they do apply that exact plan, the
    routine receipt must still show the whole maintenance operation rather
    than making a long deletion look like a fast one.
    """

    plan_seconds = 0.0
    timing = receipt.get("timing")
    if isinstance(timing, dict):
        value = timing.get("total_seconds")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            plan_seconds = max(0.0, float(value))
    timings = _timings()
    timings.phases["plan"] = plan_seconds
    # `_PhaseTimings.finish` derives the end-to-end total from its start.  A
    # plan has already completed, so shift that start back without sleeping or
    # introducing a second timing implementation.
    timings.started -= plan_seconds
    return timings


def apply(receipt: dict[str, Any]) -> dict[str, Any]:
    """Apply a startup recheck or exact ledger retirement plan."""

    root = Path(receipt["artifact_root"])
    if receipt.get("execution_mode") == "startup":
        refreshed = _startup_capacity_gate(
            root, target_bytes=int(receipt["target_bytes"]),
            minimum_free_bytes=int(receipt["minimum_free_bytes"]),
            required_paths=(Path(item) for item in receipt.get("required_input_paths", ())),
            required_cache_keys=receipt.get("required_input_cache_keys", ()),
            capacity_ledger_path=Path(receipt["capacity_ledger"]),
            capacity_protection_lease_id=receipt.get("capacity_protection_lease_id"),
        )
        refreshed.update(
            applied=bool(refreshed["satisfied"]), removed=[], removed_bytes=0,
            free_bytes_after=refreshed["free_bytes_before"],
            satisfied_after_apply=bool(refreshed["satisfied"]),
        )
        return refreshed
    if receipt.get("measurement_mode") != "LEDGER_MAINTENANCE":
        raise ValueError("only startup or ledger maintenance receipts can be applied")
    timings = _maintenance_apply_timings(receipt)
    ledger_path = Path(receipt["capacity_ledger"])
    removed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    with timings.phase("apply"):
        for item in receipt["planned"]:
            try:
                removed.append(_apply_ledger_object(root, item, ledger_path))
            except (OSError, ValueError, RuntimeError, protection.CapacityProtectionLeaseError) as exc:
                # Each target has a durable pending receipt before its bytes are
                # removed.  A target-local failure is therefore resumable and
                # cannot prevent independent governed retirements.  The ledger is
                # the one global authority: its loss stops the pass immediately.
                if capacity_ledger.load_capacity_ledger(root, ledger_path) is None:
                    raise RuntimeError("capacity ledger became unavailable during maintenance") from exc
                failed.append({
                    "path": item["path"], "operation": item["operation"],
                    "error": f"{type(exc).__name__}: {exc}",
                })
    with timings.phase("post_verify"):
        ledger = capacity_ledger.load_capacity_ledger(root, ledger_path)
        free_after = shutil.disk_usage(root).free
        outcome = dict(receipt)
        outcome.update(
            applied=True, removed=removed,
            removed_bytes=sum(item["bytes"] for item in removed),
            measured_after_bytes=None if ledger is None else int(ledger["resident_bytes"]),
            free_bytes_after=free_after,
            failed=failed,
        )
        if ledger is not None:
            leases = protection.load_capacity_protection_leases(root)
            outcome["management_summary_after_apply"] = _maintenance_management_summary(
                root, ledger, leases, target_bytes=int(receipt["target_bytes"]),
                required_free_bytes=int(receipt["required_free_bytes"]),
                free_bytes=free_after,
            )
        outcome["satisfied_after_apply"] = bool(
            ledger is not None
            and int(ledger["resident_bytes"]) <= int(receipt["target_bytes"])
            and free_after >= int(receipt["required_free_bytes"])
        )
    outcome["timing"] = timings.finish()
    return outcome


def _planned_vs_actual(receipt: dict[str, Any]) -> dict[str, int]:
    """Summarize plan execution without leaking target paths into CLI output."""

    planned_count = len(receipt.get("planned", []))
    planned_bytes = int(receipt.get("planned_bytes", sum(
        int(item["bytes"]) for item in receipt.get("planned", [])
    )))
    actual_count = len(receipt.get("removed", []))
    actual_bytes = int(receipt.get("removed_bytes", 0))
    return {
        "planned_object_count": planned_count,
        "planned_bytes": planned_bytes,
        "actual_removed_object_count": actual_count,
        "actual_removed_bytes": actual_bytes,
        "unremoved_object_count": max(0, planned_count - actual_count),
        "unremoved_bytes": max(0, planned_bytes - actual_bytes),
    }


def _failure_reason_summary(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate local retirement failures while retaining detailed evidence elsewhere."""

    groups: dict[tuple[str, str], int] = {}
    for item in receipt.get("failed", []):
        operation = str(item.get("operation", "unknown_operation"))
        error = str(item.get("error", "unknown_error"))
        error_type = error.partition(":")[0].strip() or "unknown_error"
        key = (operation, error_type)
        groups[key] = groups.get(key, 0) + 1
    return [
        {"operation": operation, "reason": reason, "object_count": count}
        for (operation, reason), count in sorted(groups.items())
    ]


def _compact_maintenance_output(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return bounded daily maintenance output without object-level paths.

    Exact candidates, errors, and removal records stay in the in-memory
    detailed receipt and the authoritative ledger/disposal receipts.  The
    ordinary CLI view deliberately carries only action aggregates so a large
    historical ledger cannot turn routine governance into a giant JSON dump.
    """

    summary = receipt.get("management_summary_after_apply") or receipt.get("management_summary")
    if not isinstance(summary, dict):
        return {
            key: value for key, value in receipt.items()
            if key not in {"planned", "removed", "failed", "protection_lease_audit"}
        } | {
            "planned_count": len(receipt.get("planned", [])),
            "removed_count": len(receipt.get("removed", [])),
            "failed_count": len(receipt.get("failed", [])),
            "planned_vs_actual": _planned_vs_actual(receipt),
            "failure_reason_summary": _failure_reason_summary(receipt),
        }
    actions: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in summary["blocked_owner_actions"]:
        key = (str(item["owner"]), str(item["action"]), str(item["reason"]))
        group = actions.setdefault(key, {
            "owner": key[0], "action": key[1], "reason": key[2],
            "object_count": 0, "bytes": 0,
        })
        group["object_count"] += 1
        group["bytes"] += int(item["bytes"])
    owner_actions = sorted(
        actions.values(), key=lambda item: (item["owner"], item["action"], item["reason"]),
    )
    groups = summary["governed_object_groups"]
    compact = {
        "schema_version": receipt.get("schema_version"), "role": receipt.get("role"),
        "execution_mode": receipt.get("execution_mode"),
        "measurement_mode": receipt.get("measurement_mode"),
        "target_bytes": receipt.get("target_bytes"),
        "minimum_free_bytes": receipt.get("minimum_free_bytes"),
        "resident_bytes": receipt.get("measured_after_bytes", receipt.get("measured_bytes")),
        "free_bytes": receipt.get("free_bytes_after", receipt.get("free_bytes_before")),
        "capacity_gap_bytes": summary["capacity_gap_bytes"],
        "satisfied": receipt.get("satisfied_after_apply", receipt.get("satisfied")),
        "satisfied_after_apply": receipt.get("satisfied_after_apply", receipt.get("satisfied")),
        "blocking_reason": receipt.get("blocking_reason"),
        "planned": {
            "object_count": len(receipt.get("planned", [])),
            "bytes": int(receipt.get("planned_bytes", sum(
                int(item["bytes"]) for item in receipt.get("planned", [])
            ))),
        },
        "removed": {
            "object_count": len(receipt.get("removed", [])),
            "bytes": int(receipt.get("removed_bytes", 0)),
        },
        "failed_object_count": len(receipt.get("failed", [])),
        "planned_vs_actual": _planned_vs_actual(receipt),
        "failure_reason_summary": _failure_reason_summary(receipt),
        "governed": {
            "object_count": sum(int(item["object_count"]) for item in groups),
            "bytes": sum(int(item["bytes"]) for item in groups),
        },
        "owner_action_summary": owner_actions,
        "external_scope_summary": [
            {"role": item["role"], "bytes": int(item["bytes"])}
            for item in summary["external_scope_groups"]
        ],
        "resumable_retirement_count": summary["resumable_retirement_count"],
        "next_active_commitments": summary["next_active_commitments"],
        "timing": receipt.get("timing"),
    }
    return compact


def _lease_action(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict[str, Any] | None:
    if args.create_protection_lease:
        if args.apply or not args.lease_owner or args.lease_ttl_seconds is None:
            parser.error("lease creation requires owner and TTL, and cannot use --apply")
        return protection.create_capacity_protection_lease(
            args.artifact_root, lease_id=args.create_protection_lease,
            owner=args.lease_owner, ttl_seconds=args.lease_ttl_seconds,
            protected_cache_keys=args.protect_cache_key, protected_paths=args.protect_path,
            committed_new_bytes=args.committed_new_bytes or 0,
        )
    if args.renew_protection_lease:
        if args.apply or not args.lease_owner or args.lease_ttl_seconds is None:
            parser.error("lease renewal requires owner and TTL, and cannot use --apply")
        return protection.renew_capacity_protection_lease(
            args.artifact_root, lease_id=args.renew_protection_lease,
            owner=args.lease_owner, ttl_seconds=args.lease_ttl_seconds,
            protected_cache_keys=args.protect_cache_key, protected_paths=args.protect_path,
            committed_new_bytes=args.committed_new_bytes,
        )
    if args.delete_protection_lease:
        if args.apply:
            parser.error("lease deletion cannot use --apply")
        return protection.delete_capacity_protection_lease(
            args.artifact_root, lease_id=args.delete_protection_lease,
        )
    return None


def main() -> None:
    policy = _capacity_policy()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--create-protection-lease")
    actions.add_argument("--renew-protection-lease")
    actions.add_argument("--delete-protection-lease")
    parser.add_argument("--lease-owner")
    parser.add_argument("--lease-ttl-seconds", type=int)
    parser.add_argument("--committed-new-bytes", type=int)
    parser.add_argument("--protect-path", action="append", type=Path, default=[])
    parser.add_argument("--protect-cache-key", action="append", default=[])
    parser.add_argument("--execution-mode", choices=("startup", "maintenance"), default="startup")
    parser.add_argument(
        "--maintenance-target-gib", type=float,
        help="explicit cleanup target for this maintenance pass only; cannot raise policy target",
    )
    parser.add_argument("--capacity-ledger", type=Path)
    parser.add_argument("--capacity-protection-lease-id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--detailed-output",
        action="store_true",
        help="emit every planned and removed object; default output is a small gate summary",
    )
    args = parser.parse_args()
    target_gib = policy["target_gib"]
    if args.maintenance_target_gib is not None:
        if args.execution_mode != "maintenance" or any((
            args.create_protection_lease, args.renew_protection_lease,
            args.delete_protection_lease,
        )):
            parser.error("--maintenance-target-gib requires maintenance without a lease action")
        if (
            not math.isfinite(args.maintenance_target_gib)
            or not 0 < args.maintenance_target_gib <= target_gib
        ):
            parser.error("--maintenance-target-gib must be finite, positive, and no greater than policy target")
        target_gib = args.maintenance_target_gib
    try:
        lease = _lease_action(args, parser)
        if lease is not None:
            print(json.dumps(lease, indent=2))
            return
        activation = {"activated_count": 0, "activated_bytes": 0}
        alias_reconciliation = {"corrected_count": 0, "released_bytes": 0}
        if args.execution_mode == "maintenance":
            activation = activate_owner_dispositions(args.artifact_root)
            source_scratch_registration = _register_workspace_scratch_scope(args.artifact_root)
            source_scratch_dispositions = _resume_source_scratch_dispositions(args.artifact_root)
            alias_reconciliation = _reconcile_execution_alias_root(args.artifact_root)
        else:
            source_scratch_registration = {"registered_count": 0, "registered_bytes": 0}
            source_scratch_dispositions = {"completed_count": 0, "removed_bytes": 0}
        receipt = plan(
            args.artifact_root,
            target_bytes=int(target_gib * GIB),
            minimum_free_bytes=int(policy["minimum_free_gib"] * GIB),
            protected_paths=args.protect_path,
            protected_cache_keys=args.protect_cache_key,
            execution_mode=args.execution_mode,
            capacity_ledger=args.capacity_ledger,
            capacity_protection_lease_id=args.capacity_protection_lease_id,
        )
        if args.apply:
            if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
                parser.error("--apply requires the shared HostExecutionLease")
            receipt = apply(receipt)
        # A maintenance pass may retire thousands of individually receipted PA
        # files.  Dumping that entire list on the launcher hot path makes the
        # terminal/PowerShell JSON conversion a material part of the task.  The
        # per-object disposal receipts remain authoritative; ordinary callers
        # only need the gate decision and aggregate counts.  Request detailed
        # output explicitly when auditing a particular maintenance operation.
        if not args.detailed_output and receipt.get("execution_mode") == "maintenance":
            receipt = _compact_maintenance_output(receipt)
        elif not args.detailed_output:
            receipt = {
                key: value
                for key, value in receipt.items()
                if key not in {"planned", "removed"}
            } | {
                "planned_count": len(receipt.get("planned", [])),
                "removed_count": len(receipt.get("removed", [])),
            }
        if activation["activated_count"]:
            receipt["owner_dispositions_activated"] = activation
        if alias_reconciliation["corrected_count"]:
            receipt["administrative_aliases_reconciled"] = alias_reconciliation
        if source_scratch_registration["registered_count"]:
            receipt["repository_workspace_scratch_registered"] = source_scratch_registration
        if source_scratch_dispositions["completed_count"]:
            receipt["source_scratch_dispositions_completed"] = source_scratch_dispositions
        print(json.dumps(receipt, indent=2))
    except (ValueError, RuntimeError, protection.CapacityProtectionLeaseError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
