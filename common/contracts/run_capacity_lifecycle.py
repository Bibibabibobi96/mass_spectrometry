"""Register opted-in runs and execute explicitly approved lifecycle recovery.

Normal registration never discovers or deletes historical runs. The separate
misplaced-light recovery requires a complete sealed backup and exact owner
approval; it does not enable automatic cleanup of retained light evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from msplatform.execution import run_capacity_lifecycle as _runtime_lifecycle
from common.contracts import capacity_ledger
from common.contracts import capacity_protection
from common.contracts.artifact_retention import classify_file
from msplatform.execution.recorded_file_removal import remove_recorded_files, write_json_atomic
from common.contracts.file_identity import canonical_json_sha256
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import file_record
from common.contracts.solver_review_retirement import (
    RECEIPT_NAME, _assert_runtime_retirement_unprotected, verify_retirement, select_retirement_receipt,
    _verify_retirement_with_leases,
)


TERMINAL_STATUSES = {"success", "failed", "interrupted"}
HEAVY_RETENTION_ROLES = {
    "solver_native_binary", "dense_trajectory", "large_optional",
}
WRITING_REVIEW_DAYS = 7
READY_REVIEW_DAYS = 30
SEALED_CHECKPOINT_REASON = "owner sealed checkpoint; continuation requires a new run"
SEALED_PAYLOAD_REASON_PREFIX = "owner sealed stopped payload; "
LEGACY_LIGHT_EVIDENCE_BUDGET_BYTES = 26_214_400
PARTIAL_RETIREMENT_RECEIPT = "partial_retirement_actions.json"
PARTIAL_RETIREMENT_RECEIPT_FIELDS = {
    "schema_version", "role", "status", "approved", "removed_bytes", "preserved",
}


_run_lifecycle_duties = _runtime_lifecycle._run_lifecycle_duties


_load_json = _runtime_lifecycle._load_json


_run_context = _runtime_lifecycle._run_context


resolve_consumed_run_capacity_owner = _runtime_lifecycle.resolve_consumed_run_capacity_owner



_inventory = _runtime_lifecycle._inventory


register_writing_range = _runtime_lifecycle.register_writing_range


register_writing = _runtime_lifecycle.register_writing


def _legacy_retirement_receipt(run_dir: Path) -> Path:
    verify_retirement(run_dir)
    return select_retirement_receipt(run_dir)[0]


def assert_retention_complete(artifact_root: Path, run_config: Path) -> dict[str, Any]:
    return _runtime_lifecycle.assert_retention_complete(artifact_root, run_config,
        retirement_receipt_name=RECEIPT_NAME,
        retirement_receipt_validator=_legacy_retirement_receipt)


def finalize_ready(artifact_root: Path, run_config: Path) -> dict[str, Any]:
    return _runtime_lifecycle.finalize_ready(artifact_root, run_config,
        classify_file=classify_file, retention_complete=assert_retention_complete)


def _verify_retired_payload_remainder(
    run_dir: Path, config: dict[str, Any], owner: str,
    entry: dict[str, Any], records: list[dict[str, Any]],
    *, _verify_retirement: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, int] | None:
    """Verify the complete retired range independently of its old accounting.

    The new receipt itself occupies bytes. Retain the original owner decision
    and compare complete before/after inventories, rather than subtracting the
    deleted payload size alone or accepting an unexplained current size.
    """
    if config.get("artifact_retention", {}).get("class") != "solver_review" or entry.get("pin") is not True:
        raise ValueError("retirement remainder requires a pinned solver_review owner range")
    receipt_path, _, _ = select_retirement_receipt(run_dir)
    receipt = _load_json(receipt_path, "retirement receipt")
    owner_completion = (receipt.get("retirement_mode") == "completed_experiment"
                        and receipt.get("owner") == owner)
    prepared_gui_supersession = (
        receipt.get("prepared_gui_checkpoint") == {"writing_stopped": True}
        and receipt.get("retirement_mode") is None
        and receipt.get("target_terminal_status") == "checkpoint"
        and config.get("project") == owner
    )
    if (not (owner_completion or prepared_gui_supersession)
            or Path(str(receipt.get("target_run_path", ""))).resolve() != run_dir
            or receipt.get("stopped_checkpoint_runtime") is not None):
        raise ValueError("retirement remainder requires this owner's completed terminal experiment or prepared GUI supersession")

    def inventory(value: object) -> dict[str, tuple[int, str]]:
        if not isinstance(value, list):
            raise ValueError("retirement remainder inventory is invalid")
        result: dict[str, tuple[int, str]] = {}
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("retirement remainder inventory is invalid")
            relative = item.get("path")
            size, digest = item.get("bytes"), item.get("sha256")
            if (not isinstance(relative, str) or not relative
                    or Path(relative).is_absolute() or Path(relative).as_posix() != relative
                    or ".." in Path(relative).parts or relative == receipt_path.name
                    or relative in result or isinstance(size, bool) or not isinstance(size, int) or size < 0
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(character not in "0123456789abcdefABCDEF" for character in digest)):
                raise ValueError("retirement remainder inventory is invalid")
            (run_dir / relative).resolve().relative_to(run_dir)
            result[relative] = (size, digest.upper())
        return result

    original = inventory(receipt.get("original_file_inventory"))
    removed = inventory(receipt.get("removed_files"))
    preserved = inventory(receipt.get("preserved_files"))
    verifier = verify_retirement if _verify_retirement is None else _verify_retirement
    verifier(run_dir)
    removed_bytes = sum(size for size, _ in removed.values())
    if (not removed or removed.keys() & preserved.keys()
            or original != {**removed, **preserved}
            or receipt.get("removed_bytes") != removed_bytes):
        raise ValueError("sealed stopped payload size change is not exactly covered by retirement")
    expected = {path: size for path, (size, _) in preserved.items()}
    expected[receipt_path.name] = receipt_path.stat().st_size
    if {item["path"]: item["bytes"] for item in records} != expected:
        raise ValueError("retirement remainder differs from the preserved inventory and receipt")
    original_bytes = sum(size for size, _ in original.values())
    old_bytes = int(entry["bytes"])
    if old_bytes != original_bytes:
        return dict(old_registered_bytes=old_bytes, original_inventory_bytes=original_bytes,
                    accounting_drift_bytes=old_bytes - original_bytes)
    return None


def seal_checkpoint(artifact_root: Path, run_config: Path, *, owner: str,
                    writing_stopped: bool = False, retain_payload: bool = False,
                    retention_reason: str | None = None) -> dict[str, Any]:
    # These callbacks are invoked only inside the canonical owner's same-root
    # capacity decision lock; standalone verification remains the public route.
    def verify_locked(run_dir: Path) -> dict[str, Any]:
        return _verify_retirement_with_leases(
            run_dir, _leases=capacity_protection._load_capacity_protection_leases_unlocked(artifact_root),
        )

    def verify_remainder_locked(run_dir, config, selected_owner, entry, records):
        return _verify_retired_payload_remainder(
            run_dir, config, selected_owner, entry, records,
            _verify_retirement=verify_locked,
        )

    return _runtime_lifecycle.seal_checkpoint(artifact_root, run_config, owner=owner,
        writing_stopped=writing_stopped, retain_payload=retain_payload,
        retention_reason=retention_reason, classify_file=classify_file,
        retirement_receipt_name=RECEIPT_NAME, verify_retirement=verify_locked,
        assert_retirement_unprotected=_assert_runtime_retirement_unprotected,
        verify_retired_payload_remainder=verify_remainder_locked,
        retention_complete=assert_retention_complete)


def reseal_retired_payload(
    artifact_root: Path, run_config: Path, *, owner: str, writing_stopped: bool = False,
) -> dict[str, Any]:
    """Close a completed partial retirement using its original retention decision.

    No caller-supplied replacement reason is accepted. The normal sealing owner
    rechecks the decision, receipt, inventory and live protections under its lock.
    """
    root = artifact_root.resolve(strict=True)
    run_dir, _, _ = _run_context(root, run_config)
    relative = run_dir.relative_to(root).as_posix()
    ledger = capacity_ledger.load_capacity_ledger(root)
    entry = next((item for item in (ledger or {}).get("objects", []) if item["path"] == relative), None)
    reason = str((entry or {}).get("retention_reason", ""))
    if (entry is None or entry.get("owner") != owner or entry.get("status") != "ready"
            or entry.get("class") != "rebuildable_payload" or entry.get("pin") is not True
            or not reason.startswith(SEALED_PAYLOAD_REASON_PREFIX)
            or not reason[len(SEALED_PAYLOAD_REASON_PREFIX):].strip()
            or not (run_dir / RECEIPT_NAME).is_file()):
        raise ValueError("retirement reseal requires the original pinned, sealed payload owner decision and receipt")
    return seal_checkpoint(root, run_config, owner=owner, writing_stopped=writing_stopped,
                           retain_payload=True, retention_reason=reason[len(SEALED_PAYLOAD_REASON_PREFIX):])


def _legacy_terminal_run_entries(
    root: Path, ledger: dict[str, Any], run_dir: Path,
) -> tuple[list[dict[str, Any]], str] | None:
    """Return one safely consolidatable historical compact run, if any.

    Old manifests already seal terminal outputs and retention decisions, but
    predate the lifecycle opt-in field.  This bridge accepts only a complete
    file-for-file ledger representation of a compact terminal run.  It uses
    sizes and retention roles, never re-hashes payloads and never deletes.
    """

    try:
        manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
    except ValueError:
        return None
    try:
        config = _load_json(run_dir / "run_config.json", "run config")
    except ValueError:
        config = {}
    try:
        retention = _load_json(run_dir / "retention_actions.json", "retention receipt")
    except ValueError:
        retention = {}
    retention_class = config.get("artifact_retention", {}).get("class")
    if retention_class is None:
        # Older run configs predate the retention contract, while their v2
        # terminal manifests still freeze the chosen class.  Consume that
        # sealed record instead of asking the user to reconstruct it.
        retention_class = manifest.get("artifact_retention", {}).get("class")
    if manifest.get("status") not in TERMINAL_STATUSES:
        return None
    sealed_compact = (
        retention_class == "compact"
        and retention.get("role") == "artifact_retention_actions"
        and retention.get("status") == "complete"
        and retention.get("retention_class") == "compact"
    )
    # A historical terminal manifest may predate both retention documents.
    # It can become ready *only* when the entire range is already light
    # evidence; this is a ledger reconciliation, never an authorization to
    # discard payloads or to terminalize a checkpoint.
    terminal_light_only = retention_class is None and not retention
    if not sealed_compact and not terminal_light_only:
        return None
    _, records = _inventory(run_dir)
    if sum(int(record["bytes"]) for record in records) > LEGACY_LIGHT_EVIDENCE_BUDGET_BYTES:
        return None
    if any(
        classify_file(run_dir / record["path"], bytes_count=int(record["bytes"]))
        in HEAVY_RETENTION_ROLES
        for record in records
    ):
        return None
    prefix = capacity_ledger.capacity_object_path(root, run_dir)[1] + "/"
    entries = [
        item for item in ledger["objects"]
        if item.get("path", "").startswith(prefix) and item.get("status") != "retired"
    ]
    expected = {
        prefix + record["path"]: int(record["bytes"])
        for record in records
    }
    actual = {str(item["path"]): int(item["bytes"]) for item in entries}
    if actual != expected or any(
        item.get("class") != "light_evidence"
        or item.get("status") != "writing"
        or item.get("recovery_reason") != "run_contract_missing_or_invalid"
        or item.get("owner") != run_dir.parent.parent.name
        or item.get("consumers")
        for item in entries
    ):
        return None
    reason = (
        "legacy terminal compact run reconciled from sealed manifest and retention receipt"
        if sealed_compact else
        "legacy terminal light-evidence run reconciled from terminal manifest"
    )
    return entries, reason


def _consolidate_legacy_terminal_runs(root: Path) -> dict[str, int]:
    """Atomically replace legacy per-file light evidence with its run range."""

    migrated = migrated_bytes = 0
    with capacity_protection.capacity_decision_lock(root):
        ledger = capacity_ledger.load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("run lifecycle maintenance requires a valid capacity ledger")
        run_dirs = sorted({
            root / Path(*Path(item["path"]).parts[:4])
            for item in ledger["objects"]
            if item.get("status") == "writing"
            and item.get("recovery_reason") == "run_contract_missing_or_invalid"
            and len(Path(item["path"]).parts) >= 5
            and Path(item["path"]).parts[:3] == ("projects", Path(item["path"]).parts[1], "runs")
        })
        replacements: list[tuple[Path, list[dict[str, Any]], dict[str, Any]]] = []
        for run_dir in run_dirs:
            candidate = _legacy_terminal_run_entries(root, ledger, run_dir)
            if candidate is None:
                continue
            entries, reason = candidate
            total = sum(int(item["bytes"]) for item in entries)
            replacements.append((run_dir, entries, {
                "path": capacity_ledger.capacity_object_path(root, run_dir)[1],
                "class": "light_evidence", "bytes": total, "status": "ready", "pin": False,
                **_run_lifecycle_duties(
                    run_dir, review_days=READY_REVIEW_DAYS,
                    reason=reason,
                ),
            }))
        if not replacements:
            return {"migrated_count": 0, "migrated_bytes": 0}
        retired_paths = {entry["path"] for _, entries, _ in replacements for entry in entries}
        ledger["objects"] = [
            entry for entry in ledger["objects"] if entry.get("path") not in retired_paths
        ] + [replacement for _, _, replacement in replacements]
        if not capacity_ledger._is_valid_capacity_ledger(root, ledger):
            raise ValueError("legacy terminal run consolidation would invalidate ledger")
        write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
        migrated = len(replacements)
        migrated_bytes = sum(replacement["bytes"] for _, _, replacement in replacements)
    return {"migrated_count": migrated, "migrated_bytes": migrated_bytes}


def resume_terminal_runs(artifact_root: Path) -> dict[str, int]:
    """Close already-terminal opted-in runs without resuming a computation.

    Maintenance is allowed to make only the ledger transition that the run has
    already earned: a terminal manifest plus a completed retention receipt.
    Checkpoints, incomplete retention, legacy runs, and runs with consumers
    remain writing and are counted as blocked.  This keeps recovery decisions
    with the original workflow while making an interrupted ledger handoff
    idempotently recoverable through the existing run owner.
    """

    root = Path(artifact_root).resolve(strict=False)
    ledger = capacity_ledger.load_capacity_ledger(root)
    if ledger is None:
        raise ValueError("run lifecycle maintenance requires a valid capacity ledger")
    checked = finalized = blocked = 0
    for entry in ledger["objects"]:
        if not (
            entry.get("class") == "rebuildable_payload"
            and entry.get("status") == "writing"
            and entry.get("recovery_reason") == "run_manifest_not_terminal"
        ):
            continue
        run_dir = root / entry["path"]
        if run_dir.parent.name != "runs" or entry.get("consumers"):
            blocked += 1
            continue
        if entry.get("owner") != run_dir.parent.parent.name:
            blocked += 1
            continue
        checked += 1
        try:
            manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
            if manifest.get("status") not in TERMINAL_STATUSES:
                blocked += 1
                continue
            finalize_ready(root, run_dir / "run_config.json")
        except (OSError, ValueError):
            blocked += 1
        else:
            finalized += 1
    legacy = _consolidate_legacy_terminal_runs(root)
    return {
        "checked_count": checked, "finalized_count": finalized, "blocked_count": blocked,
        **legacy,
    }


def _partial_retirement_run(path: Path) -> Path | None:
    """Return the direct run parent for one candidate file."""

    return next((parent for parent in path.parents if parent.parent.name == "runs"), None)


def _approved_partial_receipt(path: Path) -> dict[str, Any]:
    """Load one immutable partial-retirement approval list."""

    receipt = _load_json(path, "partial retirement receipt")
    if (
        set(receipt) != PARTIAL_RETIREMENT_RECEIPT_FIELDS
        or receipt.get("schema_version") != 2
        or receipt.get("role") != "run_partial_retirement_actions"
        or receipt.get("status") not in {"pending", "complete"}
        or receipt.get("preserved") != "all unlisted run files"
        or isinstance(receipt.get("removed_bytes"), bool)
        or not isinstance(receipt.get("removed_bytes"), int)
        or receipt["removed_bytes"] < 0
    ):
        raise ValueError("partial retirement receipt differs from the sealed schema")
    approved = receipt.get("approved")
    if not isinstance(approved, list) or not approved:
        raise ValueError("partial retirement receipt has no approved files")
    expected_paths: list[str] = []
    for record in approved:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "bytes", "sha256", "mtime_ns"}
            or not isinstance(record["path"], str)
            or Path(record["path"]).is_absolute()
            or Path(record["path"]).as_posix() != record["path"]
            or isinstance(record["bytes"], bool)
            or not isinstance(record["bytes"], int)
            or record["bytes"] < 0
            or isinstance(record["mtime_ns"], bool)
            or not isinstance(record["mtime_ns"], int)
            or record["mtime_ns"] < 0
            or not isinstance(record["sha256"], str)
            or len(record["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in record["sha256"].lower())
        ):
            raise ValueError("partial retirement receipt has an invalid approved file")
        expected_paths.append(record["path"])
    if expected_paths != sorted(set(expected_paths)):
        raise ValueError("partial retirement receipt approved files must be sorted and unique")
    return receipt


def partial_retirement_is_protected(
    root: Path, ledger: dict[str, Any], entry: dict[str, Any], path: Path,
    *, by_path: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Check protection with the public locked lease view."""
    if entry.get("pin") is True:
        return True
    return _partial_retirement_is_protected_with_leases(
        root, ledger, entry, path, by_path=by_path,
        _leases=capacity_protection.load_capacity_protection_leases(root),
    )


def _partial_retirement_is_protected_with_leases(
    root: Path, ledger: dict[str, Any], entry: dict[str, Any], path: Path,
    *, by_path: dict[str, dict[str, Any]] | None = None,
    _leases: dict[str, Any],
) -> bool:
    """Reject any live reference or lease before a physical removal."""

    if entry.get("pin") is True:
        return True
    leases = _leases
    if capacity_protection.path_is_protected(path, leases["protected_paths"]):
        return True
    if by_path is None:
        by_path = {str(item["path"]): item for item in ledger["objects"]}
    # Missing consumer records are ambiguous and therefore protected.  A
    # writing consumer is live too; only a retired consumer releases a file.
    return any(
        consumer not in by_path or by_path[consumer].get("status") != "retired"
        for consumer in entry.get("consumers", [])
    )


def recorded_heavy_identity(run_dir: Path, path: Path, bytes_count: int) -> str | None:
    """Return one pre-existing manifest identity without reading payload bytes."""

    try:
        manifest = _load_json(run_dir / "run_manifest.json", "run manifest")
    except ValueError:
        return None
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        return None
    identities: set[str] = set()
    for output in outputs:
        if not isinstance(output, dict):
            continue
        raw_path = output.get("path")
        sha256 = output.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(sha256, str):
            continue
        candidate = Path(raw_path)
        candidate = candidate if candidate.is_absolute() else run_dir / candidate
        if candidate.resolve(strict=False) != path.resolve(strict=False):
            continue
        if output.get("bytes") != bytes_count:
            return None
        normalized = sha256.upper()
        if len(normalized) != 64 or any(character not in "0123456789ABCDEF" for character in normalized):
            return None
        identities.add(normalized)
    return next(iter(identities)) if len(identities) == 1 else None


def _eligible_partial_entries(
    root: Path, ledger: dict[str, Any], run_dir: Path,
    entries: list[dict[str, Any]], by_path: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return this run's explicitly authorized, presently removable files."""

    records: list[dict[str, Any]] = []
    for entry in entries:
        if not (
            entry.get("status") == "writing"
            and entry.get("class") == "rebuildable_payload"
            and entry.get("recovery_reason") in {
                "structured_nonterminal_run_reference", "run_contract_missing_or_invalid",
            }
            and entry.get("recovery_task") == "explicit_user_authorized_abandonment"
        ):
            continue
        path = root / str(entry["path"])
        if not path.is_file():
            continue
        if classify_file(path, bytes_count=int(entry["bytes"])) not in HEAVY_RETENTION_ROLES:
            continue
        if _partial_retirement_is_protected_with_leases(
            root, ledger, entry, path, by_path=by_path,
            _leases=capacity_protection._load_capacity_protection_leases_unlocked(root),
        ):
            continue
        sha256 = recorded_heavy_identity(run_dir, path, int(entry["bytes"]))
        if sha256 is None:
            continue
        records.append({
            "path": path.relative_to(run_dir).as_posix(),
            "bytes": int(entry["bytes"]),
            "sha256": sha256,
            "mtime_ns": path.stat().st_mtime_ns,
        })
    return sorted(records, key=lambda item: str(item["path"]))


def _retire_approved_ledger_entry(
    ledger: dict[str, Any], entry: dict[str, Any], record: dict[str, Any],
) -> None:
    """Apply exactly one physical removal to the resident-byte ledger once."""

    if entry.get("status") == "retired":
        return
    if (
        entry.get("status") != "writing"
        or entry.get("class") != "rebuildable_payload"
        or int(entry.get("bytes", -1)) != int(record["bytes"])
    ):
        raise ValueError("partial retirement ledger entry differs from the approved file")
    path = str(entry["path"])
    entry.clear()
    entry.update({
        "path": path, "class": "rebuildable_payload",
        "bytes": int(record["bytes"]), "status": "retired", "pin": False,
    })
    ledger["resident_bytes"] -= int(record["bytes"])


def resume_partial_retirements(artifact_root: Path) -> dict[str, int]:
    """Execute only prewritten exact approvals and replay interrupted removals.

    Each pending receipt is a durable approval journal.  A missing approved
    file means a previous invocation completed the physical unlink before it
    could publish the ledger transition, so replay records the byte retirement
    exactly once instead of rediscovering or deleting any other run file.
    """

    root = Path(artifact_root).resolve(strict=False)
    completed = removed_bytes = blocked = 0
    with capacity_protection.capacity_decision_lock(root):
        ledger = capacity_ledger.load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("partial retirement requires a valid capacity ledger")
        # These indexes reference the locked ledger's entries, so retirement
        # transitions remain visible to later consumer checks in this pass.
        by_run: dict[Path, list[dict[str, Any]]] = {}
        by_path: dict[str, dict[str, Any]] = {}
        for item in ledger["objects"]:
            by_path[str(item["path"])] = item
            run_dir = _partial_retirement_run(root / str(item["path"]))
            if run_dir is not None:
                by_run.setdefault(run_dir, []).append(item)
        for run_dir, entries in sorted(by_run.items(), key=lambda pair: str(pair[0])):
            receipt_path = run_dir / PARTIAL_RETIREMENT_RECEIPT
            if not receipt_path.exists():
                approved = _eligible_partial_entries(root, ledger, run_dir, entries, by_path)
                if not approved:
                    for entry in entries:
                        path = root / str(entry["path"])
                        if (
                            entry.get("status") == "writing"
                            and entry.get("class") == "rebuildable_payload"
                            and entry.get("recovery_task") == "explicit_user_authorized_abandonment"
                            and path.is_file()
                            and classify_file(path, bytes_count=int(entry["bytes"])) in HEAVY_RETENTION_ROLES
                            and (
                                _partial_retirement_is_protected_with_leases(
                                    root, ledger, entry, path, by_path=by_path,
                                    _leases=capacity_protection._load_capacity_protection_leases_unlocked(root),
                                )
                                or recorded_heavy_identity(run_dir, path, int(entry["bytes"])) is None
                            )
                        ):
                            blocked += 1
                            break
                    continue
                receipt = {
                    "schema_version": 2,
                    "role": "run_partial_retirement_actions",
                    "status": "pending",
                    "approved": approved,
                    "removed_bytes": 0,
                    "preserved": "all unlisted run files",
                }
                write_json_atomic(receipt_path, receipt)
            else:
                try:
                    receipt = _approved_partial_receipt(receipt_path)
                except ValueError:
                    blocked += 1
                    continue
            if receipt["status"] == "complete":
                continue
            run_removed = 0
            try:
                for record in receipt["approved"]:
                    absolute = run_dir / str(record["path"])
                    relative = capacity_ledger.capacity_object_path(root, absolute)[1]
                    entry = by_path.get(relative)
                    if entry is None:
                        raise ValueError("partial retirement ledger entry disappeared")
                    if absolute.exists():
                        if _partial_retirement_is_protected_with_leases(
                            root, ledger, entry, absolute, by_path=by_path,
                            _leases=capacity_protection._load_capacity_protection_leases_unlocked(root),
                        ):
                            raise ValueError("partial retirement approved file is protected")
                        current = absolute.stat()
                        if (
                            current.st_size != int(record["bytes"])
                            or current.st_mtime_ns != int(record["mtime_ns"])
                        ):
                            raise ValueError("partial retirement approved file changed after approval")
                        # The approved SHA-256 was sealed by the existing run
                        # manifest.  Re-hashing a multi-GiB PA here would make
                        # retirement itself a second full payload scan.
                        next(remove_recorded_files(run_dir, [record], identities_verified=True))
                    _retire_approved_ledger_entry(ledger, entry, record)
                    run_removed += int(record["bytes"])
                if not capacity_ledger._is_valid_capacity_ledger(root, ledger):
                    raise ValueError("partial retirement would invalidate the capacity ledger")
                write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
            except (OSError, ValueError):
                blocked += 1
                continue
            receipt["removed_bytes"] = run_removed
            receipt["status"] = "complete"
            write_json_atomic(receipt_path, receipt)
            completed += 1
            removed_bytes += run_removed
    return {"completed_count": completed, "removed_bytes": removed_bytes, "blocked_count": blocked}


def retire_misplaced_light_run(artifact_root: Path, run_config: Path, *,
                               backup_manifest: Path, owner: str, apply: bool = False) -> dict[str, Any]:
    """Retire only a duplicated-runs light package after a complete canonical backup.

    This explicit owner operation preserves the erroneous ledger owner and class.
    It neither relocates identities nor enables general light-evidence cleanup.
    A durable exact-file journal makes interruption replay use the same approval.
    """
    root = artifact_root.resolve(strict=True)
    config_path = run_config.absolute()
    source, relative = capacity_ledger.capacity_object_path(root, config_path.parent)
    parts = Path(relative).parts
    if (config_path.name != "run_config.json" or len(parts) != 5
            or parts[:1] != ("projects",) or parts[2:4] != ("runs", "runs")
            or owner != parts[1]):
        raise ValueError("misplaced recovery requires exact projects/<owner>/runs/runs/<run-id>")
    backup_manifest = backup_manifest.resolve(strict=True)
    backup_run, backup_relative = capacity_ledger.capacity_object_path(root, backup_manifest.parent)
    if (backup_manifest.name != "run_manifest.json"
            or Path(backup_relative).parts[:3] != ("projects", owner, "runs")
            or len(Path(backup_relative).parts) != 4):
        raise ValueError("misplaced backup must be a canonical same-project run")
    repo = Path(__file__).resolve().parents[2]
    # The public full verifier binds every backup input/output, not just a
    # hand-authored inventory. No consumer projection is used for this proof.
    subprocess.run([sys.executable, "-m", "common.contracts.verify_run_manifest", str(backup_manifest),
                    "--require-project", owner, "--require-mode", "misplaced_light_run_backup",
                    "--require-local-run-config"], cwd=repo, check=True, capture_output=True,
                   text=True, encoding="utf-8", timeout=60)
    backup_document = _load_json(backup_manifest, "backup manifest")
    bound_records = [backup_document["run_config"], *backup_document.get("inputs", {}).values(),
                     *backup_document.get("outputs", [])]
    proof_path = backup_run / "results/misplaced_run_backup_receipt.json"
    proof_record = next((r for r in bound_records if Path(r["path"]).resolve() == proof_path), None)
    if proof_record is None:
        raise ValueError("backup manifest does not bind its misplaced-run receipt")
    proof = _load_json(proof_path, "misplaced backup receipt")
    if (proof.get("schema_version") != 1 or proof.get("role") != "misplaced_light_run_backup"
            or Path(proof["source_run"]).resolve() != source
            or Path(proof["source_manifest"]["path"]).resolve() != source / "run_manifest.json"):
        raise ValueError("misplaced backup source identity differs")
    records = []
    snapshots = {}
    for item in proof["inventory"]:
        name = item["path"]
        if capacity_ledger._ledger_relative_path(name) != name or name in snapshots:
            raise ValueError("misplaced backup inventory repeats or escapes its source")
        copy_path = backup_run / "inputs/misplaced_run_snapshot" / name
        record = item["backup_record"]
        if (copy_path.resolve() != copy_path.absolute()
                or Path(record["path"]).resolve() != copy_path.resolve()
                or not any(r == record for r in bound_records)
                or record["bytes"] != item["bytes"] or record["sha256"] != item["sha256"]):
            raise ValueError("misplaced backup copy is not exactly manifest bound")
        verify_record("misplaced backup file", record)
        snapshots[name] = copy_path
        records.append(dict(path=name, bytes=item["bytes"], sha256=item["sha256"]))
    records.sort(key=lambda r: r["path"])
    if not {"run_manifest.json", "run_config.json", "summary.json"}.issubset(snapshots):
        raise ValueError("misplaced backup lacks the original run records")
    archived_config = _load_json(snapshots["run_config.json"], "archived run config")
    archived_manifest = _load_json(snapshots["run_manifest.json"], "archived run manifest")
    original_manifest = next(r for r in records if r["path"] == "run_manifest.json")
    if (any(archived_config.get(k) != archived_manifest.get(k) for k in ("project", "run_id", "mode"))
            or archived_config.get("project") != owner or archived_config.get("run_id") != source.name
            or archived_manifest.get("status") not in TERMINAL_STATUSES
            or archived_config.get("artifact_retention", {}).get("class") != "compact"
            or any(proof["source_manifest"].get(k) != original_manifest[k] for k in ("bytes", "sha256"))):
        raise ValueError("misplaced source scientific owner, terminal state or manifest differs")
    total = sum(r["bytes"] for r in records)
    budget = archived_config.get("capacity_ledger_lifecycle", {}).get("light_evidence_budget_bytes", 0)
    if total > budget or any(classify_file(source / r["path"], bytes_count=r["bytes"]) in HEAVY_RETENTION_ROLES for r in records):
        raise ValueError("misplaced source is not a complete light-evidence package")
    identity = canonical_json_sha256(dict(source=relative, backup=file_record(backup_manifest), files=records))
    journal_path = root / "common/capacity_disposal_receipts" / f"misplaced_light_run_{identity}.json"
    with capacity_protection.capacity_decision_lock(root):
        ledger = capacity_ledger.load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("misplaced recovery requires a valid capacity ledger")
        entry = next((e for e in ledger["objects"] if e["path"] == relative), None)
        journal = _load_json(journal_path, "misplaced recovery journal") if journal_path.exists() else None
        if journal is not None and journal.get("status") not in {"pending", "complete"}:
            raise ValueError("misplaced recovery journal has an invalid state")
        if (entry is None or entry["class"] != "light_evidence" or entry.get("owner") != "runs"
                or entry.get("pin") is not False or entry.get("consumers") or entry["bytes"] != total
                or entry["status"] not in ({"ready"} if journal is None else {"ready", "retirement_pending", "retired"})):
            raise ValueError("misplaced ledger identity, original owner or state differs")
        if any(e.get("path") != relative and any(c == relative or c.startswith(relative + "/")
               for c in e.get("consumers", [])) for e in ledger["objects"]):
            raise ValueError("misplaced source has a registered consumer")
        capacity_ledger._assert_unleased(root, source)
        approval = dict(schema_version=1, role="misplaced_light_run_retirement", disposition_id=identity,
                        source_path=relative, scientific_owner=owner, original_ledger_owner="runs",
                        source_manifest=proof["source_manifest"], backup_manifest=file_record(backup_manifest),
                        backup_receipt=file_record(proof_path), files=records, bytes=total)
        if journal is not None and any(journal.get(k) != v for k, v in approval.items()):
            raise ValueError("misplaced recovery approval differs from its pending journal")
        if journal is None:
            if source.is_symlink() or not source.is_dir():
                raise ValueError("misplaced source is not a regular existing run")
            subprocess.run([sys.executable, "-m", "common.contracts.verify_run_manifest", str(source / "run_manifest.json"),
                            "--require-status", archived_manifest["status"], "--require-project", owner,
                            "--require-run-id", source.name, "--require-local-run-config"], cwd=repo,
                           check=True, capture_output=True, text=True, encoding="utf-8", timeout=60)
            size, inventory = _inventory(source)
            if size != total or {r["path"]: r["bytes"] for r in inventory} != {r["path"]: r["bytes"] for r in records}:
                raise ValueError("misplaced original content is omitted or changed")
        existing = [r for r in records if (source / r["path"]).exists()]
        if source.exists() and {r["path"] for r in _inventory(source)[1]} != {r["path"] for r in existing}:
            raise ValueError("misplaced source gained unapproved content")
        for record in existing:
            if (source / record["path"]).resolve() != (source / record["path"]).absolute():
                raise ValueError("misplaced original file traverses a link")
            verify_record("misplaced original file", {**record, "path": str(source / record["path"])})
        if not apply:
            return dict(approval, status="planned", dry_run=True, journal_path=str(journal_path))
        if journal is None:
            journal = dict(approval, status="pending")
            write_json_atomic(journal_path, journal)
        if entry["status"] == "retired":
            if existing or source.exists():
                raise ValueError("retired misplaced package reappeared")
            if journal["status"] != "complete":
                journal["status"] = "complete"
                write_json_atomic(journal_path, journal)
            return dict(journal, replayed=True)
        if entry["status"] == "ready":
            entry["status"] = "retirement_pending"
            write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
        for _ in remove_recorded_files(source, records, missing_ok=True):
            pass
        if source.exists():
            for directory in sorted((p for p in source.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                directory.rmdir()
            source.rmdir()
        if source.parent.exists() and not any(source.parent.iterdir()):
            # Only the proven duplicated ``runs/runs`` container, never the
            # canonical runs directory or a nonempty sibling collection.
            source.parent.rmdir()
        entry["status"] = "retired"
        entry["retired_at_utc"] = datetime.now(timezone.utc).isoformat()
        ledger["resident_bytes"] -= total
        if not capacity_ledger._is_valid_capacity_ledger(root, ledger):
            raise ValueError("misplaced retirement would invalidate ledger")
        write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
        journal["status"] = "complete"
        write_json_atomic(journal_path, journal)
        return journal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("register-writing-range", "register-writing", "assert-retention", "finalize-ready", "seal-checkpoint", "seal-stopped-payload", "reseal-retired-payload", "retire-misplaced-light-run"), required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-config", type=Path)
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--owner")
    parser.add_argument("--confirm-writing-stopped", action="store_true")
    parser.add_argument("--retention-reason")
    parser.add_argument("--backup-manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.action == "retire-misplaced-light-run":
        if args.run_config is None or args.backup_manifest is None or not args.owner or args.run_directory is not None:
            parser.error("misplaced recovery requires run-config, backup-manifest and scientific owner")
        if args.confirm_writing_stopped or args.retention_reason:
            parser.error("misplaced recovery cannot change retention or checkpoint state")
        if args.apply and not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
            parser.error("--apply requires the shared HostExecutionLease")
        print(json.dumps(retire_misplaced_light_run(args.artifact_root, args.run_config,
            backup_manifest=args.backup_manifest, owner=args.owner, apply=args.apply), indent=2))
        return 0
    if args.apply or args.backup_manifest is not None:
        parser.error("apply and backup-manifest require explicit misplaced-light recovery")
    action = {
        "register-writing-range": register_writing_range,
        "register-writing": register_writing,
        "assert-retention": assert_retention_complete,
        "finalize-ready": finalize_ready,
        "seal-checkpoint": seal_checkpoint,
        "seal-stopped-payload": seal_checkpoint,
        "reseal-retired-payload": reseal_retired_payload,
    }[args.action]
    try:
        if args.action == "register-writing-range":
            if args.run_directory is None or args.run_config is not None:
                raise ValueError("register-writing-range requires --run-directory only")
            result = action(args.artifact_root, args.run_directory)
        else:
            if args.run_config is None or args.run_directory is not None:
                raise ValueError(f"{args.action} requires --run-config only")
            if args.action == "reseal-retired-payload":
                if args.retention_reason is not None:
                    raise ValueError("retirement reseal preserves its original retention reason")
                result = action(args.artifact_root, args.run_config, owner=args.owner,
                                writing_stopped=args.confirm_writing_stopped)
            elif args.action in {"seal-checkpoint", "seal-stopped-payload"}:
                result = action(args.artifact_root, args.run_config, owner=args.owner,
                                writing_stopped=args.confirm_writing_stopped,
                                retain_payload=args.action == "seal-stopped-payload",
                                retention_reason=args.retention_reason)
            else:
                if args.owner is not None or args.confirm_writing_stopped or args.retention_reason is not None:
                    raise ValueError("owner confirmation is only valid for seal-checkpoint")
                result = action(args.artifact_root, args.run_config)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
