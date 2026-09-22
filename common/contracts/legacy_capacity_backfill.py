"""Keep an artifact scope below a governed capacity watermark.

The gate is deliberately conservative.  It only ever removes reconstructible
material.  Candidates receive a deletion priority from the checked-in policy:
lower-priority material is evicted first, then the oldest item within that
same priority. Reusable cache age means its last recorded successful
consumption, falling back to its generation publication time when no such
record exists. Formal evidence, active runs, and explicitly protected paths
are never candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common.contracts import capacity_ledger
from common.contracts import capacity_protection as protection
from common.contracts.artifact_retention import classify_file, validate_retention
from common.contracts.recorded_file_removal import remove_recorded_files, write_json_atomic as _write_json_atomic
from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import verify_record

GIB = 1024**3
# Run manifests in this repository publish successful solver work as
# ``success``. Terminal runs cannot keep a reconstructible cache active.
TERMINAL = {"success", "completed", "failed", "interrupted", "cancelled", "aborted"}
POLICY_PATH = Path(__file__).with_name("legacy_capacity_backfill_policy.json")
DISPOSAL_RECEIPT_DIRECTORY = Path("common") / "capacity_disposal_receipts"
CAPACITY_LEDGER_RELATIVE_PATH = capacity_ledger.CAPACITY_LEDGER_RELATIVE_PATH
HEAVY_RETENTION_ROLES = {"solver_native_binary", "dense_trajectory", "large_optional"}
LEGACY_INITIALIZATION_SUMMARY = {
    "schema_version": 1,
    "role": "run_package_initialization_summary",
    "status": "checkpoint",
    "reason": "Run package initialized; task-specific inputs are not frozen yet.",
}


class _PhaseTimings:
    """Bounded timing receipt; thresholds warn but never alter safety decisions."""

    def __init__(self, warning_seconds: float = 5.0, review_seconds: float = 60.0) -> None:
        self.started = time.perf_counter()
        self.phases: dict[str, float] = {}
        self.warning_seconds = float(warning_seconds)
        self.review_seconds = float(review_seconds)

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


def _finish_timed_receipt(receipt: dict[str, Any], timings: _PhaseTimings, mode: str) -> dict[str, Any]:
    receipt["execution_mode"] = mode
    receipt["timing"] = timings.finish()
    return receipt


_load_capacity_ledger = capacity_ledger.load_capacity_ledger
record_capacity_object = capacity_ledger.record_capacity_object
retire_capacity_object = capacity_ledger.retire_capacity_object


def _load_baseline_measurement(path: Path | None, expected_sha256: str | None) -> int | None:
    """Load a verified small gate receipt; never use it as a PA identity."""

    if path is None and expected_sha256 is None:
        return None
    if path is None or expected_sha256 is None or not protection.CACHE_KEY.fullmatch(expected_sha256):
        raise ValueError("capacity baseline receipt requires a valid SHA-256")
    if not path.is_file() or path.is_symlink() or file_sha256(path).lower() != expected_sha256.lower():
        raise ValueError("capacity baseline receipt identity differs")
    document = _load_object(path)
    if document is None or document.get("role") != "artifact_capacity_gate":
        raise ValueError("capacity baseline receipt role differs")
    value = document.get("measured_after_bytes", document.get("estimated_upper_bound_after_bytes"))
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("capacity baseline receipt lacks a valid measured byte count")
    return value


def _startup_capacity_gate(
    root: Path, *, target_bytes: int, minimum_free_bytes: int,
    required_headroom_bytes: int, protected_paths: Iterable[Path],
    protected_cache_keys: Iterable[str], known_measured_bytes: int | None,
    maximum_new_artifact_bytes: int | None, capacity_ledger: Path | None,
    capacity_protection_lease_id: str | None,
) -> dict[str, Any]:
    """Make the launch decision without scanning runs, caches, or PA payloads."""

    timings = _PhaseTimings()
    with timings.phase("disk_usage"):
        free_bytes = shutil.disk_usage(root).free
    with timings.phase("ledger_and_leases"):
        ledger = _load_capacity_ledger(root, capacity_ledger)
        leases = protection.load_capacity_protection_leases(root)
    explicit_paths = [str(Path(item).absolute()) for item in protected_paths]
    explicit_keys = sorted({str(item).lower() for item in protected_cache_keys})
    commitment = int(leases.get("committed_new_bytes", 0))
    if known_measured_bytes is not None and maximum_new_artifact_bytes is None:
        raise ValueError("known capacity fast path requires maximum new bytes")
    if known_measured_bytes is not None and known_measured_bytes < 0:
        raise ValueError("known measured bytes must be nonnegative")
    if maximum_new_artifact_bytes is None:
        maximum_new_artifact_bytes = 0
    if maximum_new_artifact_bytes < 0:
        raise ValueError("maximum new artifact bytes must be nonnegative")
    current_lease = next((
        item for item in leases.get("audit", ())
        if item.get("status") == "active"
        and item.get("lease_id") == capacity_protection_lease_id
    ), None)
    baseline = known_measured_bytes
    if baseline is None and ledger is not None:
        baseline = int(ledger["resident_bytes"])
    current_commitment = 0 if current_lease is None else int(current_lease.get("committed_new_bytes", 0))
    lease_is_trusted = current_lease is not None and current_commitment >= maximum_new_artifact_bytes
    required_free = minimum_free_bytes + required_headroom_bytes + commitment
    projected = None if baseline is None else baseline + maximum_new_artifact_bytes
    safe = (
        projected is not None
        and projected + required_headroom_bytes <= target_bytes
        and free_bytes >= required_free
        and lease_is_trusted
    )
    return _finish_timed_receipt({
        "schema_version": 1, "role": "artifact_capacity_gate",
        "artifact_root": str(root), "target_bytes": target_bytes,
        "required_headroom_bytes": required_headroom_bytes,
        "minimum_free_bytes": minimum_free_bytes,
        "free_bytes_before": free_bytes,
        "known_measured_bytes": baseline,
        "maximum_new_artifact_bytes": maximum_new_artifact_bytes,
        "estimated_upper_bound_bytes": projected,
        "required_free_bytes": required_free,
        "free_deficit_bytes": max(0, required_free - free_bytes),
        "protected_paths": explicit_paths,
        "protected_cache_keys": explicit_keys,
        "protection_lease_audit": leases["audit"],
        "capacity_protection_lease_id": capacity_protection_lease_id,
        "capacity_ledger": str((capacity_ledger or root / CAPACITY_LEDGER_RELATIVE_PATH).absolute()),
        "ledger_status": "accepted" if ledger is not None else "missing_or_invalid",
        "measurement_mode": "STARTUP_LEDGER" if ledger is not None else "STARTUP_BLOCKED_LEDGER_REQUIRED",
        "candidate_discovery_performed": False, "candidate_count": None,
        "planned": [], "projected_bytes": projected, "satisfied": safe,
        "blocking_reason": None if safe else "SAFETY_DECISION_UNAVAILABLE",
    }, timings, "startup")


def _ledger_candidates(
    root: Path, ledger: dict[str, Any], protected_paths: Iterable[Path],
    protected_cache_keys: Iterable[str], policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build maintenance candidates from ledger records only."""

    protected = tuple(Path(item).absolute() for item in protected_paths)
    keys = {str(item).lower() for item in protected_cache_keys}
    candidates: list[dict[str, Any]] = []
    for item in ledger.get("objects", []):
        if not isinstance(item, dict) or item.get("class") not in {
            "published_cache", "rebuildable_payload",
        }:
            continue
        if item.get("status") != "ready" or item.get("pin") is True:
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str):
            continue
        try:
            target, _ = capacity_ledger.capacity_object_path(root, raw_path)
        except (OSError, RuntimeError, ValueError):
            continue
        if protection.path_is_protected(target, protected) or target.name.lower() in keys:
            continue
        value = item.get("bytes")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            continue
        candidates.append({
            "level": "RUN_PAYLOAD" if item["class"] == "rebuildable_payload" else "L2",
            "operation": "retire_ledger_object",
            "reason": f"ledger_ready_{item['class']}",
            "path": str(target), "bytes": value,
            "timestamp": float(item.get("last_used_epoch", 0) or 0),
            "ledger_record": item,
            "deletion_priority": int(policy.get("rebuildable_payload_priority", 20)),
        })
    return sorted(candidates, key=lambda item: (item["deletion_priority"], item["timestamp"], item["path"]))


def _plan_from_ledger(
    root: Path, *, target_bytes: int, minimum_free_bytes: int,
    required_headroom_bytes: int, protected_paths: Iterable[Path],
    protected_cache_keys: Iterable[str], capacity_ledger: Path | None,
) -> dict[str, Any]:
    """Plan maintenance without enumerating runs or cache payloads."""

    timings = _PhaseTimings()
    with timings.phase("ledger_and_leases"):
        ledger = _load_capacity_ledger(root, capacity_ledger)
        leases = protection.load_capacity_protection_leases(root)
    if ledger is None:
        return _finish_timed_receipt({
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "measurement_mode": "MAINTENANCE_LEDGER_REQUIRED",
            "candidate_discovery_performed": False, "candidate_count": None,
            "planned": [], "satisfied": False,
            "blocking_reason": "SAFETY_DECISION_UNAVAILABLE",
        }, timings, "maintenance")
    with timings.phase("disk_usage"):
        free_bytes = shutil.disk_usage(root).free
    commitment = int(leases.get("committed_new_bytes", 0))
    measured = int(ledger["resident_bytes"])
    required_free = minimum_free_bytes + required_headroom_bytes + commitment
    candidates = _ledger_candidates(
        root, ledger, [*protected_paths, *leases["protected_paths"]],
        [*protected_cache_keys, *leases["protected_cache_keys"]], _capacity_policy(),
    )
    projected = measured
    limit = min(target_bytes - required_headroom_bytes, measured - max(0, required_free - free_bytes))
    planned: list[dict[str, Any]] = []
    for candidate in candidates:
        if projected <= limit:
            break
        planned.append(candidate)
        projected -= int(candidate["bytes"])
    return _finish_timed_receipt({
        "schema_version": 1, "role": "artifact_capacity_gate",
        "artifact_root": str(root), "target_bytes": target_bytes,
        "required_headroom_bytes": required_headroom_bytes,
        "minimum_free_bytes": minimum_free_bytes,
        "free_bytes_before": free_bytes,
        "measured_bytes": measured, "required_free_bytes": required_free,
        "candidate_discovery_performed": True, "candidate_count": len(candidates),
        "planned": planned, "planned_bytes": sum(int(item["bytes"]) for item in planned),
        "projected_bytes": projected, "satisfied": projected <= limit,
        "capacity_ledger": str((capacity_ledger or root / CAPACITY_LEDGER_RELATIVE_PATH).absolute()),
        "protection_lease_audit": leases["audit"],
        "measurement_mode": "LEDGER_MAINTENANCE",
    }, timings, "maintenance")


def _published_cache_identity(pointer_path: Path) -> tuple[str, str] | None:
    """Return one closed current cache identity without hashing its payload.

    Both registered pointer schemas publish the pointer last.  A hexadecimal
    token is therefore a cache key only when the containing key directory,
    pointer, selected generation, and manifest form one matching identity
    chain.  This prevents unrelated file SHA-256 values in active run records
    from pinning cache entries.
    """

    key = pointer_path.parent.name.lower()
    if not protection.CACHE_KEY.fullmatch(key):
        return None
    pointer = _load_cache_identity_object(pointer_path)
    if pointer is None:
        return None
    declared_key = pointer.get("cache_key")
    if declared_key is not None and str(declared_key).lower() != key:
        return None
    relative = pointer.get("generation_relative_path")
    if isinstance(relative, str):
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            return None
        generation = relative_path.name
        manifest_path = pointer_path.parent / relative_path / "cache_manifest.json"
    else:
        generation = pointer.get("generation_sha256")
        if not isinstance(generation, str):
            return None
        manifest_path = (
            pointer_path.parent / "generations" / generation / "cache_manifest.json"
        )
    manifest = _load_cache_identity_object(manifest_path)
    if manifest is None:
        return None
    role = str(manifest.get("role", ""))
    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        return None
    if (
        str(manifest.get("cache_key", "")).lower() != key
        or str(manifest.get("generation_sha256", "")) != generation
    ):
        return None
    if schema_version < 3 and not (
        schema_version >= 1 and role == "simion_pa_family_cache"
    ):
        return None
    return key, role


def _published_pa_cache_key(pointer_path: Path) -> str | None:
    """Return a closed published key only when it is a PA-family cache."""

    identity = _published_cache_identity(pointer_path)
    if identity is None:
        return None
    key, role = identity
    if role != "simion_pa_family_cache" and not role.endswith("_pa_cache"):
        return None
    return key


def _current_generation_pointers(root: Path) -> list[Path]:
    """Enumerate pointer files while tolerating concurrently removed children."""

    pointers: list[Path] = []

    def visit(directory: Path) -> None:
        try:
            entries = os.scandir(directory)
        except FileNotFoundError:
            return
        with entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        visit(Path(entry.path))
                    elif (
                        entry.is_file(follow_symlinks=False)
                        and entry.name == "current_generation.json"
                    ):
                        pointers.append(Path(entry.path))
                except FileNotFoundError:
                    # Capacity preflights and failed-run cleanup may remove a
                    # temporary sibling after its directory entry was read.
                    # A disappeared node cannot be a retained publication.
                    continue

    visit(root)
    return pointers


def snapshot_published_pa_cache_keys(root: Path) -> dict[str, Any]:
    """Freeze all valid PA-family publications visible at run startup."""

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    keys = sorted({
        key
        for pointer in _current_generation_pointers(root)
        if (key := _published_pa_cache_key(pointer)) is not None
    })
    return {
        "schema_version": 1,
        "role": "artifact_capacity_published_pa_cache_protection_snapshot",
        "artifact_root": str(root),
        "captured_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "protected_cache_keys": keys,
        "protected_cache_key_count": len(keys),
    }


def _is_registered_cache_pointer(root: Path, pointer: Path) -> bool:
    """Return whether a pointer occupies one registered cache-key location."""

    try:
        relative = pointer.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    parts = tuple(part.lower() for part in relative.parts)
    if len(parts) == 6 and (
        parts[0] == "projects"
        and parts[2] == "cache"
        and parts[-1] == "current_generation.json"
    ):
        return True
    return (
        len(parts) == 5
        and parts[:3] == ("common", "simion", "pa_family_cache")
        and parts[-1] == "current_generation.json"
    )


def _published_cache_keys(root: Path) -> set[str]:
    """Return cache keys backed by a registered closed publication identity."""

    return {
        identity[0]
        for pointer in _current_generation_pointers(root)
        if _is_registered_cache_pointer(root, pointer)
        if (identity := _published_cache_identity(pointer)) is not None
    }


def _capacity_policy() -> dict[str, Any]:
    """Load and minimally validate the versioned repository eviction policy."""

    policy = _load_object(POLICY_PATH)
    if policy is None or int(policy.get("schema_version", 0)) != 1:
        raise RuntimeError(f"invalid artifact-capacity policy: {POLICY_PATH}")
    for field in ("target_gib", "minimum_free_gib"):
        value = policy.get(field)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
                or (field == "target_gib" and value == 0)):
            raise RuntimeError(f"invalid {field} in {POLICY_PATH}")
    roles = policy.get("l2_role_deletion_priorities")
    if not isinstance(roles, dict):
        raise RuntimeError(f"invalid L2 role priorities in {POLICY_PATH}")
    for field in (
        "unmanaged_run_deletion_priority",
        "explicit_success_build_payload_deletion_priority",
        "default_l2_deletion_priority",
        "l1_deletion_priority",
        "l3_deletion_priority",
    ):
        if not isinstance(policy.get(field), int) or int(policy[field]) < 0:
            raise RuntimeError(f"invalid {field} in {POLICY_PATH}")
    grace = policy.get("unmanaged_run_grace_seconds")
    if isinstance(grace, bool) or not isinstance(grace, int) or grace < 0:
        raise RuntimeError(f"invalid unmanaged_run_grace_seconds in {POLICY_PATH}")
    if any(not isinstance(value, int) or value < 0 for value in roles.values()):
        raise RuntimeError(f"invalid L2 role priority in {POLICY_PATH}")
    return policy


def _deletion_priority(*, level: str, cache_role: str | None, policy: dict[str, Any]) -> int:
    """Return a policy-owned priority; unknown published roles stay conservative."""

    if level == "L1":
        return int(policy["l1_deletion_priority"])
    if level == "L3":
        return int(policy["l3_deletion_priority"])
    if level != "L2":
        raise ValueError(f"unknown artifact cleanup level: {level}")
    role_priorities = policy["l2_role_deletion_priorities"]
    return int(role_priorities.get(cache_role, policy["default_l2_deletion_priority"]))


def _directory_bytes(root: Path) -> dict[Path, int]:
    """Return inclusive byte counts for every real directory in one walk.

    Capacity planning needs both the whole artifact footprint and individual
    cache footprints.  Re-walking each cache made a dry-run scale with the
    number of cache keys.  A bottom-up walk preserves the exact file and
    symlink rules while sharing that I/O across all candidates.
    """
    sizes: dict[Path, int] = {}

    def measure(directory: Path) -> int:
        """Measure once with DirEntry's cached type/stat information.

        This is the bounded slow path: no valid conservative upper bound is
        available, so the gate must inspect the artifact tree before it may
        remove anything.  ``os.walk`` reconstructs paths and performs fresh
        metadata lookups for every file; on the large PA cache that makes an
        otherwise single walk unnecessarily slow.  ``scandir`` retains the
        same no-symlink accounting rule while avoiding those extra lookups.
        """
        total = 0
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        total += measure(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except FileNotFoundError:
                    # A concurrent preflight may remove its temporary child
                    # after enumeration. Missing children consume no bytes;
                    # permission and other I/O failures must still propagate.
                    continue
        sizes[directory] = total
        return total

    measure(root)
    return sizes


def _load_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _load_cache_identity_object(path: Path) -> dict[str, Any] | None:
    """Read a deletion-governing cache identity without hiding I/O denial.

    Missing or malformed JSON is an incomplete cache identity.  Permission
    errors and other storage failures are different: treating them as a
    damaged L1 cache could authorize deletion of a valid publication whose
    pointer or manifest merely could not be inspected.
    """

    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        raise
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _active_cache_keys(
    root: Path, published_cache_keys: set[str] | None = None,
) -> set[str]:
    """Protect real published keys referenced by non-terminal run identity."""

    published = (
        _published_cache_keys(root)
        if published_cache_keys is None
        else published_cache_keys
    )
    referenced = {
        key.lower()
        for _, text in _active_run_reference_texts(root)
        for key in protection.CACHE_KEY.findall(text)
    }
    return referenced & published


def _last_successful_cache_uses(
    root: Path, published_cache_keys: set[str] | None = None,
) -> dict[str, tuple[float, str]]:
    """Return each cache key's latest successful, manifest-recorded consumer.

    Filesystem atime is frequently disabled or changed by backup/indexing, so
    it is not evidence that a simulation consumed a cache. A terminal
    ``success``/``completed`` run manifest is durable, auditable evidence.
    The scan runs only after the fast capacity paths establish that cleanup is
    necessary.
    """

    published = (
        _published_cache_keys(root)
        if published_cache_keys is None
        else published_cache_keys
    )
    latest: dict[str, tuple[float, str]] = {}
    for run_dir in _run_directories(root):
        manifest = run_dir / "run_manifest.json"
        document = _load_object(manifest)
        if document is None or str(document.get("status", "")).lower() not in {"success", "completed"}:
            continue
        observed = protection.parse_utc_timestamp(document.get("recorded_at_utc"))
        if observed is None:
            continue
        try:
            keys = {key.lower() for key in protection.CACHE_KEY.findall(manifest.read_text(encoding="utf-8-sig"))}
        except (OSError, UnicodeDecodeError):
            continue
        for key in keys & published:
            if key not in latest or observed[0] > latest[key][0]:
                latest[key] = observed
    return latest


def _is_capacity_excluded_path(path: Path) -> bool:
    """Exclude preserved evidence and scratch requiring object-specific review."""

    return any(part.lower() in {"formal", "archive", "scratch"} for part in path.parts)


def _run_directories(root: Path) -> tuple[Path, ...]:
    """Return only registered ``projects/<project>/runs/<run_id>`` directories."""

    projects_root = root.absolute() / "projects"
    if not projects_root.is_dir():
        return ()
    runs: list[Path] = []
    for project_dir in projects_root.iterdir():
        run_root = project_dir / "runs"
        if not project_dir.is_dir() or not run_root.is_dir():
            continue
        runs.extend(
            run_dir.absolute()
            for run_dir in run_root.iterdir()
            if run_dir.is_dir() and not run_dir.is_symlink()
        )
    return tuple(sorted(runs))


def _active_run_reference_texts(root: Path) -> tuple[tuple[Path, str], ...]:
    """Protect frozen preparation inputs until a terminal manifest exists."""

    values: list[tuple[Path, str]] = []
    for run_dir in _run_directories(root):
        if not any(
            (run_dir / name).is_file()
            for name in ("run_manifest.json", "run_config.json")
        ):
            continue
        manifest_path = run_dir / "run_manifest.json"
        manifest = _load_object(manifest_path)
        if (
            manifest is not None
            and str(manifest.get("status", "")).lower() in TERMINAL
        ):
            continue
        text_parts: list[str] = []
        for path in (manifest_path, run_dir / "run_config.json"):
            try:
                text_parts.append(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError):
                # An unreadable active identity is ambiguous.  Its own run is
                # still protected by status; unrelated candidates are not
                # inferred from bytes that cannot be inspected.
                continue
        values.append((run_dir, "\n".join(text_parts)))
    return tuple(values)


def audit_checkpoint_terminalization(root: Path) -> dict[str, Any]:
    """Report terminal summaries that still lack a terminal manifest.

    This is deliberately read-only.  Summary status and process absence are
    not terminalization authority; the owning runner must review the actual
    outputs and use the existing verified run-manifest entrypoint.
    """

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    findings: list[dict[str, Any]] = []
    for run_dir in _run_directories(root):
        summary = _load_object(run_dir / "summary.json")
        if summary is None:
            continue
        summary_status = str(summary.get("status", "")).lower()
        manifest_path = run_dir / "run_manifest.json"
        manifest = _load_object(manifest_path)
        if manifest is not None:
            manifest_status = (
                str(manifest.get("status", "")).lower()
                or "invalid_or_missing_status"
            )
        elif manifest_path.exists():
            manifest_status = "unreadable_or_invalid"
        else:
            manifest_status = "missing"
        if manifest_status in TERMINAL and summary_status not in TERMINAL:
            findings.append(
                {
                    "run_path": str(run_dir),
                    "summary_status": summary_status or "invalid_or_missing_status",
                    "manifest_status": manifest_status,
                    "status": "terminal_manifest_summary_status_debt",
                    "reason": (
                        "terminal manifest remains authoritative; the present non-terminal "
                        "summary is legacy status debt requiring explicit review"
                    ),
                }
            )
            continue
        if summary_status not in TERMINAL:
            continue
        if manifest_status in TERMINAL:
            continue
        findings.append(
            {
                "run_path": str(run_dir),
                "summary_status": summary_status,
                "manifest_status": manifest_status,
                "status": "explicit_terminalization_required",
                "terminalization_entrypoint": (
                    "Write-VerifiedRunManifest/Write-TerminalRunRecord"
                ),
                "reason": (
                    "terminal summary is diagnostic only; inspect the actual run, "
                    "outputs, references, and provenance before verified manifest "
                    "terminalization"
                ),
            }
        )
    return {
        "schema_version": 1,
        "role": "artifact_checkpoint_terminalization_audit",
        "artifact_root": str(root),
        "finding_count": len(findings),
        "findings": findings,
    }


def _has_active_run_reference(
    candidate: Path, active_references: Iterable[tuple[Path, str]]
) -> bool:
    candidate = candidate.absolute()
    path_spellings = {str(candidate), candidate.as_posix()}
    for active_dir, text in active_references:
        if active_dir == candidate:
            continue
        if candidate.name in text or any(value in text for value in path_spellings):
            return True
    return False


def _cache_candidate(cache_key_dir: Path, protected_keys: set[str], last_successful_uses: dict[str, tuple[float, str]],
                     protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
                     policy: dict[str, Any]) -> dict[str, Any] | None:
    if _is_capacity_excluded_path(cache_key_dir) or protection.path_is_protected(cache_key_dir, protected_paths):
        return None
    name = cache_key_dir.name.lower()
    mtime = cache_key_dir.stat().st_mtime
    payload = {"path": str(cache_key_dir), "bytes": directory_bytes.get(cache_key_dir, 0), "timestamp": mtime}
    if name.startswith("b-") and not (cache_key_dir / "cache_manifest.json").exists():
        # Age alone does not establish that a staging writer has stopped or
        # that its unpublished bytes are reconstructible. Review it explicitly.
        return None
    if not protection.CACHE_KEY.fullmatch(name) or name in protected_keys:
        return None
    pointer = cache_key_dir / "current_generation.json"
    if not pointer.is_file():
        return None
    selected = _load_cache_identity_object(pointer)
    relative = selected.get("generation_relative_path") if selected else None
    if isinstance(relative, str):
        generation = Path(relative).name
        published = cache_key_dir / relative / "cache_manifest.json"
    else:
        generation_value = selected.get("generation_sha256") if selected else None
        generation = generation_value if isinstance(generation_value, str) else ""
        published = (
            cache_key_dir / "generations" / generation / "cache_manifest.json"
            if generation
            else None
        )
    manifest = (
        _load_cache_identity_object(published)
        if published and published.is_file()
        else None
    )
    role = str(manifest.get("role", "")) if manifest else ""
    schema_version = int(manifest.get("schema_version", 0)) if manifest else 0
    verified = bool(
        manifest
        and (
            schema_version >= 3
            or (schema_version >= 1 and role == "simion_pa_family_cache")
        )
        and str(manifest.get("cache_key", "")).lower() == name
        and str(manifest.get("generation_sha256", "")).lower() == generation.lower()
    )
    if not verified:
        # A malformed pointer or selected generation is an incomplete cache,
        # not a published L2 object.  It is only eligible as L1 and never if
        # a caller explicitly pins the key.
        payload.update(level="L1", reason="damaged_or_incomplete_cache_generation",
                       deletion_priority=_deletion_priority(level="L1", cache_role=None, policy=policy))
        return payload
    last_use = last_successful_uses.get(name)
    if last_use is None:
        payload.update(
            timestamp=published.stat().st_mtime,
            eviction_time_basis="generation_publication_time",
        )
    else:
        payload.update(
            timestamp=last_use[0],
            last_successful_use_at_utc=last_use[1],
            eviction_time_basis="last_successful_cache_consumption",
        )
    cache_role = str(manifest.get("role", cache_key_dir.parent.name))
    payload.update(level="L2", reason="inactive_reconstructible_published_cache", cache_role=cache_role,
                   deletion_priority=_deletion_priority(level="L2", cache_role=cache_role, policy=policy))
    return payload


def _cache_candidates(root: Path, protected_keys: set[str], last_successful_uses: dict[str, tuple[float, str]],
                       protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
                      policy: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for cache_root in root.rglob("cache"):
        if not cache_root.is_dir() or _is_capacity_excluded_path(cache_root):
            continue
        for role_dir in cache_root.iterdir():
            if not role_dir.is_dir() or _is_capacity_excluded_path(role_dir):
                continue
            for child in role_dir.iterdir():
                if child.is_dir():
                    candidate = _cache_candidate(child, protected_keys, last_successful_uses, protected_paths, directory_bytes, policy)
                    if candidate:
                        candidates.append(candidate)
    common_pa_family_cache = root / "common" / "simion" / "pa_family_cache"
    if common_pa_family_cache.is_dir() and not _is_capacity_excluded_path(
        common_pa_family_cache
    ):
        for child in common_pa_family_cache.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                candidate = _cache_candidate(
                    child,
                    protected_keys,
                    last_successful_uses,
                    protected_paths,
                    directory_bytes,
                    policy,
                )
                if candidate:
                    candidates.append(candidate)
    return candidates


def _compact_candidates(root: Path, protected_paths: Iterable[Path], policy: dict[str, Any]) -> list[dict[str, Any]]:
    from common.contracts import reconcile_interrupted_compact_runs as compact

    candidates: list[dict[str, Any]] = []
    for run_dir in _run_directories(root):
        if protection.path_is_protected(run_dir, protected_paths):
            continue
        try:
            report = compact.inspect_run(run_dir)
        except (AssertionError, KeyError, TypeError, ValueError):
            continue
        if report["removable_bytes"]:
            candidates.append({"level": "L3", "reason": "verified_interrupted_compact_payload",
                               "path": str(run_dir), "bytes": int(report["removable_bytes"]),
                               "timestamp": run_dir.stat().st_mtime, "compact_report": report,
                               "deletion_priority": _deletion_priority(level="L3", cache_role=None, policy=policy)})
    return candidates


def _unmanaged_run_candidates(
    root: Path, protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
    active_references: Iterable[tuple[Path, str]], now: float,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return old run-shaped trees that never published identity evidence."""

    candidates: list[dict[str, Any]] = []
    grace = int(policy["unmanaged_run_grace_seconds"])
    for run_dir in _run_directories(root):
        if (
            protection.path_is_protected(run_dir, protected_paths)
            or (run_dir / "run_manifest.json").exists()
            or (run_dir / "summary.json").exists()
            or (run_dir / "run_config.json").exists()
            or _has_active_run_reference(run_dir, active_references)
            or _unmanaged_run_receipt_path(root, run_dir).exists()
        ):
            continue
        created = run_dir.stat().st_ctime
        if now - created < grace:
            continue
        candidates.append({
            "level": "L1",
            "operation": "remove_unmanaged_run_with_receipt",
            "reason": "old_unmanaged_unreferenced_run",
            "path": str(run_dir),
            "bytes": directory_bytes.get(run_dir, 0),
            "timestamp": created,
            "eviction_time_basis": "run_directory_creation_time",
            "deletion_priority": int(policy["unmanaged_run_deletion_priority"]),
        })
    return candidates


def _manifest_recorded_paths(run_dir: Path, manifest: dict[str, Any]) -> set[Path]:
    """Resolve manifest records conservatively without trusting escaping paths."""

    recorded = {
        (run_dir / "run_manifest.json").resolve(),
        (run_dir / "run_config.json").resolve(),
        (run_dir / "summary.json").resolve(),
    }
    verify_record("run_config", manifest["run_config"], base_dir=run_dir)
    for section in ("inputs", "outputs"):
        values = manifest.get(section, {} if section == "inputs" else [])
        records = values.values() if isinstance(values, dict) else values
        if not isinstance(records, (list, tuple, type({}.values()))):
            raise ValueError(f"manifest {section} records differ")
        for index, record in enumerate(records):
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise ValueError(f"manifest {section} record differs")
            verify_record(f"{section} {index}", record, base_dir=run_dir)
            path = (run_dir / record["path"]).resolve()
            try:
                path.relative_to(run_dir.resolve())
            except ValueError as exc:
                raise ValueError("manifest record escapes its run") from exc
            recorded.add(path)
    return recorded


def _is_solver_review_retention(value: object) -> bool:
    """Return whether one retention object is a valid solver-review contract."""

    try:
        return validate_retention(value).class_id == "solver_review"
    except (KeyError, TypeError, ValueError):
        return False


def _success_build_payload_candidate(
    run_dir: Path, protected_paths: Iterable[Path], directory_bytes: dict[Path, int],
    active_references: Iterable[tuple[Path, str]], policy: dict[str, Any],
) -> dict[str, Any] | None:
    """Inspect one explicitly authorized success build without weakening success runs."""

    run_dir = run_dir.absolute()
    if (
        run_dir.parent.name != "runs"
        or not run_dir.is_dir()
        or _is_capacity_excluded_path(run_dir)
        or protection.path_is_protected(run_dir, protected_paths)
        or _has_active_run_reference(run_dir, active_references)
        or (run_dir / "capacity_retirement_actions.json").exists()
    ):
        return None
    manifest = _load_object(run_dir / "run_manifest.json")
    summary = _load_object(run_dir / "summary.json")
    config = _load_object(run_dir / "run_config.json")
    if manifest is None or summary is None or config is None:
        return None
    summary_status = str(summary.get("status", "")).lower()
    legacy_solver_review = (
        summary == LEGACY_INITIALIZATION_SUMMARY
        and _is_solver_review_retention(config.get("artifact_retention"))
        and _is_solver_review_retention(manifest.get("artifact_retention"))
    )
    if (
        manifest.get("status") != "success"
        or (summary_status != "success" and not legacy_solver_review)
        or bool(manifest.get("formal_eligible"))
        or bool(summary.get("formal_eligible"))
        or bool(config.get("formal_gate_passed"))
        or config.get("run_id") != run_dir.name
        or len(run_dir.name.split("__")) < 2
        or run_dir.name.split("__")[1] != "build"
    ):
        return None
    try:
        recorded = _manifest_recorded_paths(run_dir, manifest)
    except (AssertionError, KeyError, TypeError, ValueError):
        return None
    removable: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.resolve() in recorded:
            continue
        role = classify_file(path)
        if role in HEAVY_RETENTION_ROLES:
            removable.append({
                "path": path.relative_to(run_dir).as_posix(),
                "bytes": path.stat().st_size,
                "retention_role": role,
            })
    removable_bytes = sum(int(item["bytes"]) for item in removable)
    if not removable_bytes:
        return None
    recorded_at = protection.parse_utc_timestamp(manifest.get("recorded_at_utc"))
    timestamp = recorded_at[0] if recorded_at is not None else run_dir.stat().st_mtime
    return {
        "level": "RUN_PAYLOAD",
        "operation": "retire_explicit_success_build_payload",
        "reason": "explicit_rebuildable_unreferenced_success_build_payload",
        "path": str(run_dir),
        "bytes": removable_bytes,
        "timestamp": timestamp,
        "eviction_time_basis": (
            "success_manifest_recorded_at_utc" if recorded_at is not None
            else "run_directory_modification_time"
        ),
        "removable": removable,
        "deletion_priority": int(policy["explicit_success_build_payload_deletion_priority"]),
    }


def _unmanaged_run_receipt_path(root: Path, run_dir: Path) -> Path:
    identity = hashlib.sha256(str(run_dir.absolute()).encode("utf-8")).hexdigest()[:16]
    return root / DISPOSAL_RECEIPT_DIRECTORY / f"unmanaged_run_{identity}.json"


def _file_disposal_records(run_dir: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("capacity disposal path escapes its run") from exc
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"capacity disposal file is missing or not regular: {path}")
        records.append({
            "path": relative.as_posix(),
            "bytes": path.stat().st_size,
            "sha256": file_sha256(path),
        })
    return records


def _remove_tree_with_receipt(root: Path, target: Path, *, reason: str,
                              receipt_path: Path) -> tuple[Path, int]:
    """Freeze every regular file before removing an audited candidate tree."""
    target.resolve().relative_to(root.resolve())
    if target == root or _is_capacity_excluded_path(target):
        raise ValueError("capacity disposal target is protected")
    if receipt_path.exists():
        raise ValueError("capacity disposal receipt already exists; review prior disposition")
    entries = sorted(target.rglob("*"))
    if target.is_symlink() or any(path.is_symlink() for path in entries):
        raise ValueError("capacity disposal tree contains a symbolic link")
    directories = [path for path in entries if path.is_dir()]
    files = [path for path in entries if path.is_file()]
    records = _file_disposal_records(target, files)
    receipt = {
        "schema_version": 1,
        "role": "artifact_capacity_disposal_receipt",
        "status": "pending",
        "reason": reason,
        "target_path": str(target),
        "files": records,
        "removed_bytes": sum(int(item["bytes"]) for item in records),
    }
    _write_json_atomic(receipt_path, receipt)
    removed_bytes = 0
    for record in remove_recorded_files(target, records, missing_ok=True):
        removed_bytes += int(record["bytes"])
    # Remove only the preflight directories, non-recursively. New files keep
    # their parent alive and leave the receipt pending for manual review.
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True) + [target]:
        try:
            directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            if directory.exists():
                continue
            raise
    receipt["removed_bytes"] = removed_bytes
    if target.exists():
        receipt["reason_incomplete"] = "unlisted_files_or_nonempty_directories_remain"
        _write_json_atomic(receipt_path, receipt)
        raise ValueError(f"capacity disposal retained unlisted files: {target}")
    receipt["status"] = "complete"
    _write_json_atomic(receipt_path, receipt)
    return receipt_path, removed_bytes


def resume_pending_disposals(root: Path) -> list[dict[str, Any]]:
    """Finish exact, identity-bound capacity removals interrupted by file locks.

    The original pending receipt is the sole deletion authority.  Missing
    recorded files are treated as already removed; surviving files must still
    match their frozen size and SHA-256.  New or unlisted files keep the target
    and receipt pending for review.
    """

    root = root.resolve()
    receipt_root = root / DISPOSAL_RECEIPT_DIRECTORY
    if not receipt_root.is_dir():
        return []
    leases = protection.load_capacity_protection_leases(root)
    completed: list[dict[str, Any]] = []
    for receipt_path in sorted(receipt_root.glob("*.json")):
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        if (
            not isinstance(receipt, dict)
            or receipt.get("role") != "artifact_capacity_disposal_receipt"
            or receipt.get("status") != "pending"
        ):
            continue
        target = Path(str(receipt.get("target_path", ""))).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("pending capacity disposal target escapes artifact root") from exc
        if target == root or _is_capacity_excluded_path(target):
            raise ValueError("pending capacity disposal target is protected")
        if protection.path_is_protected(target, leases["protected_paths"]):
            raise ValueError(f"pending capacity disposal target has an active path lease: {target}")
        if target.name.lower() in leases["protected_cache_keys"]:
            raise ValueError(f"pending capacity disposal cache key has an active lease: {target.name}")
        records = receipt.get("files")
        if not isinstance(records, list) or any(
            not isinstance(record, dict)
            or set(record) != {"path", "bytes", "sha256"}
            for record in records
        ):
            raise ValueError(f"pending capacity disposal inventory is invalid: {receipt_path}")
        for _ in remove_recorded_files(target, records, missing_ok=True):
            pass
        if target.exists():
            entries = sorted(target.rglob("*"), key=lambda path: len(path.parts), reverse=True)
            if any(path.is_symlink() or path.is_file() for path in entries):
                raise ValueError(f"pending capacity disposal retained unlisted files: {target}")
            for directory in [path for path in entries if path.is_dir()] + [target]:
                try:
                    directory.rmdir()
                except FileNotFoundError:
                    continue
        if target.exists():
            raise ValueError(f"pending capacity disposal target remains nonempty: {target}")
        complete = {
            **receipt,
            "status": "complete",
            "removed_bytes": sum(int(record["bytes"]) for record in records),
            "resumed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        complete.pop("reason_incomplete", None)
        _write_json_atomic(receipt_path, complete)
        completed.append(
            {
                "receipt": str(receipt_path),
                "target_path": str(target),
                "removed_bytes": complete["removed_bytes"],
            }
        )
    return completed


def _apply_ledger_object(root: Path, item: dict[str, Any], ledger_path: Path) -> dict[str, Any]:
    """Mark retirement under lock, remove outside it, then finalize under lock."""

    target, _ = capacity_ledger.capacity_object_path(root, str(item["path"]))
    receipt_path = root / DISPOSAL_RECEIPT_DIRECTORY / (
        f"ledger_{hashlib.sha256(str(target).encode('utf-8')).hexdigest()[:16]}.json"
    )
    expected_bytes = capacity_ledger.mark_retirement_pending(
        root, path=target, ledger_path=ledger_path,
    )
    try:
        receipt, removed_bytes = _remove_tree_with_receipt(
            root, target, reason="ledger_object_retirement", receipt_path=receipt_path,
        )
    except Exception as exc:
        capacity_ledger.record_retirement_error(
            root, path=target, ledger_path=ledger_path,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    if removed_bytes != expected_bytes:
        capacity_ledger.record_retirement_error(
            root, path=target, ledger_path=ledger_path,
            error=f"removed byte count {removed_bytes} differs from ledger {expected_bytes}",
        )
        raise ValueError("removed byte count differs from the calibrated ledger")
    capacity_ledger.finalize_retirement(
        root, path=target, removed_bytes=removed_bytes, ledger_path=ledger_path,
    )
    return {"path": str(target), "bytes": removed_bytes, "disposal_receipt": str(receipt)}


def _remove_unmanaged_run_with_receipt(root: Path, run_dir: Path) -> tuple[Path, int]:
    return _remove_tree_with_receipt(
        root, run_dir, reason="old_unmanaged_unreferenced_run",
        receipt_path=_unmanaged_run_receipt_path(root, run_dir),
    )


def _retire_success_build_payload(run_dir: Path, removable: Iterable[dict[str, Any]]) -> tuple[Path, int]:
    paths = [run_dir / str(item["path"]) for item in removable]
    records = _file_disposal_records(run_dir, paths)
    receipt_path = run_dir / "capacity_retirement_actions.json"
    manifest_path = run_dir / "run_manifest.json"
    receipt = {
        "schema_version": 1,
        "role": "artifact_capacity_success_build_payload_retirement",
        "status": "pending",
        "reason": "explicit_rebuildable_unreferenced_success_build_payload",
        "run_id": run_dir.name,
        "source_manifest_sha256": file_sha256(manifest_path),
        "removed": records,
        "removed_bytes": sum(int(item["bytes"]) for item in records),
    }
    _write_json_atomic(receipt_path, receipt)
    for _ in remove_recorded_files(run_dir, records):
        pass
    receipt["status"] = "complete"
    _write_json_atomic(receipt_path, receipt)
    return receipt_path, int(receipt["removed_bytes"])


def plan(root: Path, *, target_bytes: int, minimum_free_bytes: int,
         required_headroom_bytes: int = 0,
         protected_paths: Iterable[Path] = (),
         protected_cache_keys: Iterable[str] = (),
         rebuildable_success_build_runs: Iterable[Path] = (),
         known_measured_bytes: int | None = None,
         maximum_new_artifact_bytes: int | None = None,
         execution_mode: str = "startup",
         capacity_ledger: Path | None = None,
         capacity_protection_lease_id: str | None = None) -> dict[str, Any]:
    """Plan disposal with explicit byte budgets; CLI defaults belong to policy."""

    # Keep the caller's absolute spelling.  On Windows, resolve() can rewrite
    # an 8.3 temporary-root path to its long form, making the receipt disagree
    # with the paths accepted by the caller despite denoting the same cache.
    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    if execution_mode not in {"startup", "maintenance", "legacy-backfill"}:
        raise ValueError("execution mode must be startup, maintenance, or legacy-backfill")
    if execution_mode != "startup" and (known_measured_bytes is None) != (maximum_new_artifact_bytes is None):
        raise ValueError("known capacity fast path requires both byte values")
    if known_measured_bytes is not None and (
        known_measured_bytes < 0 or maximum_new_artifact_bytes is None
        or maximum_new_artifact_bytes < 0
    ):
        raise ValueError("known capacity fast-path bytes must be nonnegative")
    if execution_mode == "startup":
        return _startup_capacity_gate(
            root,
            target_bytes=target_bytes,
            minimum_free_bytes=minimum_free_bytes,
            required_headroom_bytes=required_headroom_bytes,
            protected_paths=protected_paths,
            protected_cache_keys=protected_cache_keys,
            known_measured_bytes=known_measured_bytes,
            maximum_new_artifact_bytes=maximum_new_artifact_bytes,
            capacity_ledger=capacity_ledger,
            capacity_protection_lease_id=capacity_protection_lease_id,
        )
    if execution_mode == "maintenance" and capacity_ledger is not None:
        return _plan_from_ledger(
            root, target_bytes=target_bytes, minimum_free_bytes=minimum_free_bytes,
            required_headroom_bytes=required_headroom_bytes,
            protected_paths=protected_paths, protected_cache_keys=protected_cache_keys,
            capacity_ledger=capacity_ledger,
        )
    if execution_mode == "maintenance":
        # Historical exhaustive discovery is an explicit backfill operation;
        # normal maintenance cannot silently fall through to it.
        timings = _PhaseTimings()
        return _finish_timed_receipt({
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "measurement_mode": "MAINTENANCE_LEDGER_REQUIRED",
            "candidate_discovery_performed": False, "candidate_count": None,
            "planned": [], "satisfied": False,
            "blocking_reason": "SAFETY_DECISION_UNAVAILABLE",
        }, timings, "maintenance")
    explicit_protected = tuple(path.absolute() for path in protected_paths)
    explicit_keys = {
        str(key).lower() for key in protected_cache_keys
        if protection.CACHE_KEY.fullmatch(str(key))
    }
    explicit_success_build_runs: list[Path] = []
    for value in rebuildable_success_build_runs:
        candidate = Path(value).absolute()
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("rebuildable success build run must remain below artifact root") from exc
        explicit_success_build_runs.append(candidate)
    explicit_success_build_runs = sorted(set(explicit_success_build_runs), key=str)
    leases = protection.load_capacity_protection_leases(root)
    protected = tuple(sorted(
        {*explicit_protected, *leases["protected_paths"]}, key=str
    ))
    leased_and_explicit_keys = explicit_keys | leases["protected_cache_keys"]
    protection_fields = {
        "explicit_protected_paths": [str(path) for path in explicit_protected],
        "explicit_protected_cache_keys": sorted(explicit_keys),
        "explicit_rebuildable_success_build_runs": [
            str(path) for path in explicit_success_build_runs
        ],
        "protected_paths": [str(path) for path in protected],
        "protected_cache_keys": sorted(leased_and_explicit_keys),
        "protection_lease_audit": leases["audit"],
        "checkpoint_terminalization_audit": audit_checkpoint_terminalization(root),
    }
    # A launch receipt plus its governed maximum transient footprint supplies
    # a conservative upper bound while the shared solver lease excludes a
    # second concurrent SIMION publication.  Avoid a full artifact walk when
    # that upper bound is already safely below the watermark and the physical
    # disk floor is met.  This is an optimization only: uncertainty falls back
    # to the existing exhaustive, level-then-age planner.
    free_bytes = shutil.disk_usage(root).free
    if (
        known_measured_bytes is not None
        and known_measured_bytes + maximum_new_artifact_bytes + required_headroom_bytes
        <= target_bytes
        and free_bytes >= minimum_free_bytes
    ):
        upper_bound = known_measured_bytes + maximum_new_artifact_bytes
        return {
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "free_bytes_before": free_bytes,
            **protection_fields,
            "measurement_mode": "SAFE_NO_RECONCILIATION",
            "known_measured_bytes": known_measured_bytes,
            "maximum_new_artifact_bytes": maximum_new_artifact_bytes,
            "estimated_upper_bound_bytes": upper_bound,
            "free_deficit_bytes": 0, "measured_bytes": known_measured_bytes,
            "limit_bytes": target_bytes - required_headroom_bytes,
            "active_cache_key_count": None, "candidate_count": 0,
            "planned": [], "projected_bytes": upper_bound, "satisfied": True,
        }
    directory_bytes = _directory_bytes(root)
    measured = directory_bytes[root]
    if minimum_free_bytes < 0:
        raise ValueError("minimum free bytes must be nonnegative")
    free_bytes = shutil.disk_usage(root).free
    # A current full measurement can close the ordinary no-cleanup case without
    # enumerating cache manifests or interrupted runs.  apply() repeats this
    # measurement immediately before publication; if the state changed, it
    # falls through to the established L1/L2/L3 planner below.
    if (
        measured + required_headroom_bytes <= target_bytes
        and free_bytes >= minimum_free_bytes
    ):
        return {
            "schema_version": 1, "role": "artifact_capacity_gate",
            "artifact_root": str(root), "target_bytes": target_bytes,
            "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes,
            "free_bytes_before": free_bytes,
            **protection_fields,
            "measurement_mode": "FULL_NO_RECONCILIATION",
            "free_deficit_bytes": 0, "measured_bytes": measured,
            "limit_bytes": target_bytes - required_headroom_bytes,
            "active_cache_key_count": None, "candidate_count": 0,
            "planned": [], "projected_bytes": measured, "satisfied": True,
        }
    now = time.time()
    policy = _capacity_policy()
    published_cache_keys = _published_cache_keys(root)
    active_keys = _active_cache_keys(root, published_cache_keys)
    last_successful_uses = _last_successful_cache_uses(root, published_cache_keys)
    active_references = _active_run_reference_texts(root)
    active_keys.update(leased_and_explicit_keys)
    # Failed/interrupted runs remain evidence; only the registered compact
    # payload path may retire their reconstructible heavy outputs.
    candidates = _unmanaged_run_candidates(
        root, protected, directory_bytes, active_references, now, policy
    )
    candidates.extend(_cache_candidates(root, active_keys, last_successful_uses, protected, directory_bytes, policy))
    candidates.extend(_compact_candidates(root, protected, policy))
    registered_run_dirs = set(_run_directories(root))
    for run_dir in explicit_success_build_runs:
        if run_dir not in registered_run_dirs:
            continue
        candidate = _success_build_payload_candidate(
            run_dir, protected, directory_bytes, active_references, policy
        )
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (item["deletion_priority"], item["timestamp"], item["path"]))
    free_deficit = max(0, minimum_free_bytes - free_bytes)
    # Every byte removed from this artifact root returns one byte to the same
    # volume.  Intersect the repository watermark with the physical-free-space
    # requirement so the repository policy's priority-then-age ordering remains the sole deletion
    # policy.
    limit = min(target_bytes - required_headroom_bytes, measured - free_deficit)
    planned: list[dict[str, Any]] = []
    projected = measured
    for candidate in candidates:
        if projected <= limit:
            break
        planned.append(candidate)
        projected -= candidate["bytes"]
    return {"schema_version": 1, "role": "artifact_capacity_gate", "artifact_root": str(root),
            "target_bytes": target_bytes, "required_headroom_bytes": required_headroom_bytes,
            "minimum_free_bytes": minimum_free_bytes, "free_bytes_before": free_bytes,
            "explicit_protected_paths": protection_fields["explicit_protected_paths"],
            "explicit_protected_cache_keys": protection_fields["explicit_protected_cache_keys"],
            "explicit_rebuildable_success_build_runs": protection_fields[
                "explicit_rebuildable_success_build_runs"
            ],
            "protected_paths": [str(path) for path in protected],
            "protected_cache_keys": sorted(active_keys),
            "protection_lease_audit": leases["audit"],
            "checkpoint_terminalization_audit": protection_fields[
                "checkpoint_terminalization_audit"
            ],
            "free_deficit_bytes": free_deficit,
            "measured_bytes": measured, "limit_bytes": limit, "active_cache_key_count": len(active_keys),
            "candidate_count": len(candidates), "planned": planned, "projected_bytes": projected,
            "satisfied": projected <= limit}


def apply(receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("measurement_mode") == "LEDGER_MAINTENANCE":
        root = Path(receipt["artifact_root"])
        ledger_path = Path(receipt["capacity_ledger"])
        removed: list[dict[str, Any]] = []
        for item in receipt.get("planned", []):
            if item.get("operation") != "retire_ledger_object":
                continue
            removed.append(_apply_ledger_object(root, item, ledger_path))
        ledger = _load_capacity_ledger(root, ledger_path)
        outcome = dict(receipt)
        outcome.update(
            applied=True, removed=removed,
            removed_bytes=sum(int(item["bytes"]) for item in removed),
            measured_after_bytes=None if ledger is None else int(ledger["resident_bytes"]),
            free_bytes_after=shutil.disk_usage(root).free,
        )
        outcome["satisfied_after_apply"] = bool(
            ledger is not None and int(ledger["resident_bytes"]) + int(receipt["required_headroom_bytes"])
            <= int(receipt["target_bytes"])
            and outcome["free_bytes_after"] >= int(receipt["required_free_bytes"])
        )
        return outcome
    if receipt.get("execution_mode") == "startup":
        # Startup is a bounded admission decision.  It must never fall through
        # into the historical maintenance scanner merely because --apply was
        # supplied by a lifecycle adapter.
        outcome = dict(receipt)
        outcome.update(
            applied=bool(receipt.get("satisfied")),
            removed=[], removed_bytes=0,
            free_bytes_after=shutil.disk_usage(Path(receipt["artifact_root"])).free,
            satisfied_after_apply=bool(receipt.get("satisfied")),
        )
        return outcome
    # Active SIMION does not prohibit cleanup: plan() excludes every cache key
    # mentioned by a non-terminal manifest, and the plan is refreshed here to
    # close the interval between a capacity decision and deletion.  This keeps
    # the disk floor enforceable while another independent channel is solving.
    root = Path(receipt["artifact_root"])
    if receipt.get("measurement_mode") == "FULL_NO_RECONCILIATION":
        sizes = _directory_bytes(root)
        measured_after = sizes[root]
        free_after = shutil.disk_usage(root).free
        if (
            measured_after + int(receipt["required_headroom_bytes"])
            <= int(receipt["target_bytes"])
            and free_after >= int(receipt["minimum_free_bytes"])
        ):
            outcome = dict(receipt)
            outcome.update(
                applied=True, removed=[], removed_bytes=0,
                measured_after_bytes=measured_after,
                free_bytes_after=free_after,
                satisfied_after_apply=True,
            )
            return outcome
    if receipt.get("measurement_mode") == "SAFE_NO_RECONCILIATION":
        outcome = dict(receipt)
        outcome.update(
            applied=True, removed=[], removed_bytes=0,
            measured_after_bytes=receipt["known_measured_bytes"],
            estimated_upper_bound_after_bytes=receipt["estimated_upper_bound_bytes"],
            free_bytes_after=shutil.disk_usage(root).free,
            satisfied_after_apply=True,
        )
        return outcome
    receipt = plan(
        root,
        target_bytes=int(receipt["target_bytes"]),
        required_headroom_bytes=int(receipt["required_headroom_bytes"]),
        minimum_free_bytes=int(receipt["minimum_free_bytes"]),
        protected_paths=(
            Path(path) for path in receipt.get(
                "explicit_protected_paths", receipt.get("protected_paths", ())
            )
        ),
        protected_cache_keys=receipt.get(
            "explicit_protected_cache_keys", receipt.get("protected_cache_keys", ())
        ),
        rebuildable_success_build_runs=(
            Path(path) for path in receipt.get(
                "explicit_rebuildable_success_build_runs", ()
            )
        ),
        execution_mode="legacy-backfill",
    )
    removed: list[dict[str, Any]] = []
    for item in receipt["planned"]:
        path = Path(item["path"])
        if item.get("operation") == "remove_unmanaged_run_with_receipt":
            receipt_path, removed_bytes = _remove_unmanaged_run_with_receipt(root, path)
            removed.append({
                "path": str(path), "level": item["level"], "bytes": removed_bytes,
                "disposal_receipt": str(receipt_path),
            })
            continue
        if item.get("operation") == "retire_explicit_success_build_payload":
            receipt_path, removed_bytes = _retire_success_build_payload(
                path, item["removable"]
            )
            removed.append({
                "path": str(path), "level": item["level"], "bytes": removed_bytes,
                "retirement_receipt": str(receipt_path),
            })
            continue
        if item["level"] in {"L1", "L2"}:
            identity = hashlib.sha256(str(path.absolute()).encode("utf-8")).hexdigest()[:16]
            receipt_path = root / DISPOSAL_RECEIPT_DIRECTORY / f"cache_{identity}_{time.time_ns()}.json"
            receipt_path, removed_bytes = _remove_tree_with_receipt(
                root, path, reason=item["reason"], receipt_path=receipt_path,
            )
            if removed_bytes:
                removed.append({"path": str(path), "level": item["level"], "bytes": removed_bytes,
                                "disposal_receipt": str(receipt_path)})
            continue
        else:
            from common.contracts import reconcile_interrupted_compact_runs as compact

            actions = compact.apply_run(path)
            removed.append({"path": str(path), "level": item["level"], "bytes": item["bytes"],
                            "retention_actions": str(actions)})
            continue
    receipt = dict(receipt)
    receipt["applied"] = True
    receipt["removed"] = removed
    receipt["removed_bytes"] = sum(item["bytes"] for item in removed)
    receipt["measured_after_bytes"] = _directory_bytes(Path(receipt["artifact_root"]))[
        Path(receipt["artifact_root"])
    ]
    receipt["free_bytes_after"] = shutil.disk_usage(Path(receipt["artifact_root"])).free
    receipt["satisfied_after_apply"] = (
        receipt["measured_after_bytes"] + receipt["required_headroom_bytes"] <= receipt["target_bytes"]
        and receipt["free_bytes_after"] >= receipt["minimum_free_bytes"]
    )
    return receipt


def main() -> None:
    policy = _capacity_policy()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    standalone_actions = parser.add_mutually_exclusive_group()
    standalone_actions.add_argument(
        "--snapshot-published-pa-cache-keys", action="store_true"
    )
    standalone_actions.add_argument(
        "--audit-checkpoint-terminalization", action="store_true"
    )
    standalone_actions.add_argument("--resume-pending-disposals", action="store_true")
    standalone_actions.add_argument("--create-protection-lease")
    standalone_actions.add_argument("--renew-protection-lease")
    standalone_actions.add_argument("--delete-protection-lease")
    parser.add_argument("--lease-owner")
    parser.add_argument("--lease-ttl-seconds", type=int)
    parser.add_argument("--committed-new-bytes", type=int)
    parser.add_argument("--target-gib", type=float, default=policy["target_gib"])
    parser.add_argument("--required-headroom-bytes", type=int, default=0)
    parser.add_argument("--minimum-free-gib", type=float, default=policy["minimum_free_gib"])
    parser.add_argument("--protect-path", action="append", type=Path, default=[])
    parser.add_argument("--protect-cache-key", action="append", default=[])
    parser.add_argument("--known-measured-bytes", type=int)
    parser.add_argument("--maximum-new-artifact-bytes", type=int)
    parser.add_argument("--capacity-baseline-receipt", type=Path)
    parser.add_argument("--capacity-baseline-receipt-sha256")
    parser.add_argument(
        "--execution-mode", choices=("startup", "maintenance", "legacy-backfill"),
        default="startup",
    )
    parser.add_argument("--capacity-ledger", type=Path)
    parser.add_argument("--capacity-protection-lease-id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.resume_pending_disposals:
        if (
            args.apply
            or args.snapshot_published_pa_cache_keys
            or args.audit_checkpoint_terminalization
            or args.create_protection_lease
            or args.renew_protection_lease
            or args.delete_protection_lease
        ):
            parser.error("pending disposal resume is a standalone action")
        if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
            parser.error("pending disposal resume requires the shared HostExecutionLease")
        print(json.dumps({"resumed": resume_pending_disposals(args.artifact_root)}, indent=2))
        return
    if args.snapshot_published_pa_cache_keys:
        if args.apply:
            parser.error("published PA cache protection snapshot is read-only")
        print(json.dumps(snapshot_published_pa_cache_keys(args.artifact_root), indent=2))
        return
    if args.audit_checkpoint_terminalization:
        if args.apply or args.snapshot_published_pa_cache_keys:
            parser.error("checkpoint terminalization audit is read-only and standalone")
        print(json.dumps(audit_checkpoint_terminalization(args.artifact_root), indent=2))
        return
    if args.create_protection_lease:
        if args.apply or not args.lease_owner or args.lease_ttl_seconds is None:
            parser.error("lease creation requires owner and TTL, and cannot use --apply")
        try:
            lease = protection.create_capacity_protection_lease(
                args.artifact_root,
                lease_id=args.create_protection_lease,
                owner=args.lease_owner,
                ttl_seconds=args.lease_ttl_seconds,
                protected_cache_keys=args.protect_cache_key,
                protected_paths=args.protect_path,
                committed_new_bytes=(
                    0 if args.committed_new_bytes is None else args.committed_new_bytes
                ),
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(lease, indent=2))
        return
    if args.renew_protection_lease:
        if args.apply or not args.lease_owner or args.lease_ttl_seconds is None:
            parser.error("lease renewal requires owner and TTL, and cannot use --apply")
        try:
            lease = protection.renew_capacity_protection_lease(
                args.artifact_root,
                lease_id=args.renew_protection_lease,
                owner=args.lease_owner,
                ttl_seconds=args.lease_ttl_seconds,
                protected_cache_keys=args.protect_cache_key,
                protected_paths=args.protect_path,
                committed_new_bytes=args.committed_new_bytes,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(lease, indent=2))
        return
    if args.delete_protection_lease:
        if args.apply:
            parser.error("lease deletion cannot use --apply")
        try:
            deleted = protection.delete_capacity_protection_lease(
                args.artifact_root, lease_id=args.delete_protection_lease
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(deleted, indent=2))
        return
    if (args.target_gib <= 0 or args.required_headroom_bytes < 0 or
            args.minimum_free_gib < 0):
        parser.error("capacity values must be nonnegative and target positive")
    if args.apply and not os.environ.get(
        "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"
    ):
        parser.error(
            "--apply requires the shared HostExecutionLease; use "
            "Invoke-ArtifactCapacityGate from PowerShell 7"
        )
    try:
        baseline = _load_baseline_measurement(
            args.capacity_baseline_receipt, args.capacity_baseline_receipt_sha256
        )
        if baseline is not None and args.known_measured_bytes is not None:
            parser.error("capacity baseline receipt and raw known measurement are mutually exclusive")
        receipt = plan(args.artifact_root, target_bytes=int(args.target_gib * GIB),
                       required_headroom_bytes=args.required_headroom_bytes,
                       minimum_free_bytes=int(args.minimum_free_gib * GIB),
                       protected_paths=args.protect_path,
                       protected_cache_keys=args.protect_cache_key,
                       known_measured_bytes=baseline if baseline is not None else args.known_measured_bytes,
                       maximum_new_artifact_bytes=args.maximum_new_artifact_bytes,
                       execution_mode=args.execution_mode,
                       capacity_ledger=args.capacity_ledger,
                       capacity_protection_lease_id=args.capacity_protection_lease_id)
        if args.apply:
            receipt = apply(receipt)
    except protection.CapacityProtectionLeaseError as exc:
        print(json.dumps(exc.audit, indent=2), file=sys.stderr)
        sys.exit(2)
    if args.apply:
        satisfied = receipt["satisfied_after_apply"]
    else:
        satisfied = receipt["satisfied"]
    print(json.dumps(receipt, indent=2))
    if not satisfied:
        sys.exit(2)


if __name__ == "__main__":
    main()
