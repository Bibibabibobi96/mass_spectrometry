"""The single bounded startup decision; historical maintenance remains an explicit outer action."""
from __future__ import annotations
import json
import math
import shutil
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from msplatform.execution import capacity_ledger
from msplatform.execution import capacity_protection as protection
from msplatform.execution.capacity_ledger import CAPACITY_LEDGER_RELATIVE_PATH
from msplatform.execution.resources import resource_path

POLICY_PATH = resource_path("artifact_capacity_policy.json")


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


def _capacity_policy(path: Path | None = None) -> dict[str, Any]:
    return validate_capacity_policy(_load_object(POLICY_PATH if path is None else path))


def validate_capacity_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
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


def capture_capacity_policy(path: Path | None = None) -> dict[str, Any]:
    """Read one deployment selection with its source identity before admission."""
    import hashlib
    from msplatform.io.manifest_records import file_record, verify_record
    source = file_record(POLICY_PATH if path is None else path, "required_evidence")
    policy = _capacity_policy() if path is None else _capacity_policy(path)
    verify_record("selected capacity policy", source)
    return dict(source_record=source, snapshot=policy,
        snapshot_sha256=hashlib.sha256(json.dumps(policy, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest())


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


def _writing_overlaps_current_inputs(
    item: dict[str, Any], root: Path, paths: tuple[Path, ...], keys: set[str],
) -> bool:
    """Match registered input ranges without reading payloads or cache manifests."""

    relative = Path(item["path"])
    if protection.path_is_protected(root / relative, paths):
        return True
    parts = relative.parts
    if parts[:3] == ("common", "simion", "pa_family_cache"):
        tail = parts[3:]
    elif len(parts) >= 5 and parts[0] == "projects" and parts[2] == "cache":
        tail = parts[4:]
    else:
        return False
    # Keys identify cache families, not their generation SHA. Transactions
    # and key-named staging retain the same family identity before publication.
    if tail and tail[0] in {".transactions", ".staging"}:
        tail = tail[1:]
    return bool(tail and tail[0].lower() in keys)


def _startup_capacity_gate(
    root: Path, *, target_bytes: int, minimum_free_bytes: int,
    required_paths: Iterable[Path], required_cache_keys: Iterable[str],
    capacity_ledger_path: Path | None,
    capacity_protection_lease_id: str | None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timings = _timings(policy)
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
    # Every recorded byte remains in resident. An overdue owner recovery only
    # blocks this workflow when its current input range is affected.
    current_paths = tuple(Path(path).resolve(strict=False) for path in (
        *required[0], *(current_lease or {}).get("protected_paths", ()),
    ))
    current_keys = set(required[1]) | set((current_lease or {}).get("protected_cache_keys", ()))
    canonical_root = root.resolve(strict=False)
    blocking_overdue_writing = [
        item for item in overdue_writing
        if _writing_overlaps_current_inputs(item, canonical_root, current_paths, current_keys)
    ]
    blocking_paths = {item["path"] for item in blocking_overdue_writing}
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
        "warnings": [
            {"code": "UNRELATED_WRITING_RECOVERY_REVIEW_OVERDUE", "path": item["path"]}
            for item in overdue_writing if item["path"] not in blocking_paths
        ],
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

def plan_startup(root: Path, *, target_bytes: int, minimum_free_bytes: int,
                 required_paths: Iterable[Path] = (), required_cache_keys: Iterable[str] = (),
                 capacity_ledger_path: Path | None = None,
                 capacity_protection_lease_id: str | None = None,
                 policy: dict[str, Any] | None = None) -> dict[str, Any]:
    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    for value, name in ((target_bytes, "target bytes"), (minimum_free_bytes, "minimum free bytes")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    return _startup_capacity_gate(root, target_bytes=target_bytes, minimum_free_bytes=minimum_free_bytes,
        required_paths=required_paths, required_cache_keys=required_cache_keys,
        capacity_ledger_path=capacity_ledger_path, capacity_protection_lease_id=capacity_protection_lease_id, policy=policy)
