"""TTL artifact protection shared by cleanup and layout verification.

This module owns lease schema and path coverage; the capacity CLI owns commands.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Normal runtime ownership migrated; historical maintenance remains here.
from msplatform.execution.capacity_protection import (
    CACHE_KEY as CACHE_KEY,
    CAPACITY_DECISION_LOCK_NAME as CAPACITY_DECISION_LOCK_NAME,
    CapacityProtectionLeaseError as CapacityProtectionLeaseError,
    DEFAULT_MAX_LEASE_LIFETIME_SECONDS as DEFAULT_MAX_LEASE_LIFETIME_SECONDS,
    DISPOSAL_RECEIPT_DIRECTORY as DISPOSAL_RECEIPT_DIRECTORY,
    LEASE_ID as LEASE_ID,
    PROTECTION_LEASE_DIRECTORY as PROTECTION_LEASE_DIRECTORY,
    _assert_not_pending_disposal as _assert_not_pending_disposal,
    _closure_deadline as _closure_deadline,
    _create_capacity_protection_lease_unlocked as _create_capacity_protection_lease_unlocked,
    _delete_capacity_protection_lease_unlocked as _delete_capacity_protection_lease_unlocked,
    _lease_closure_deadline as _lease_closure_deadline,
    _lease_path as _lease_path,
    _load_capacity_protection_leases_unlocked as _load_capacity_protection_leases_unlocked,
    _pending_disposal_targets as _pending_disposal_targets,
    _pending_disposal_targets_from_receipts as _pending_disposal_targets_from_receipts,
    _relative_protected_path as _relative_protected_path,
    _renew_capacity_protection_lease_unlocked as _renew_capacity_protection_lease_unlocked,
    _validated_commitment as _validated_commitment,
    _validated_lease_id as _validated_lease_id,
    capacity_decision_lock as capacity_decision_lock,
    create_capacity_protection_lease as create_capacity_protection_lease,
    delete_capacity_protection_lease as delete_capacity_protection_lease,
    load_capacity_protection_leases as load_capacity_protection_leases,
    parse_utc_timestamp as parse_utc_timestamp,
    path_is_protected as path_is_protected,
    renew_capacity_protection_lease as renew_capacity_protection_lease,
)

PROTECTION_LEASE_PRUNING_RECEIPT_DIRECTORY = (
    Path("common") / "capacity_protection_lease_pruning_receipts"
)
# A caller may choose a shorter, explicit closure date.  The default keeps
# existing short workflow callers usable while still making every new lease
# finite and preventing a sequence of renewals from becoming permanent.




from msplatform.execution.file_lock import process_file_lock as process_file_lock






































def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """Durably replace a small lease receipt without leaving a partial JSON file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(document, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _pending_disposal_references_lease(
    root: Path, *, lease_id: str, lease_path: Path,
) -> bool:
    """Fail closed if a durable pending disposal still names this lease.

    Receipts evolved independently, so this checks exact JSON scalar values
    rather than owning a second receipt schema.  Matching the precise lease id
    or its absolute/root-relative path is conservative and avoids pruning an
    audit record needed to resume a pending disposal.
    """

    receipt_root = root / DISPOSAL_RECEIPT_DIRECTORY
    if not receipt_root.exists():
        return False
    if not receipt_root.is_dir() or receipt_root.is_symlink():
        raise ValueError("capacity disposal receipt directory is not a real directory")
    values = {
        lease_id,
        str(lease_path.absolute()),
        lease_path.relative_to(root).as_posix(),
    }

    def contains_reference(value: object) -> bool:
        if isinstance(value, str):
            return value in values
        if isinstance(value, list):
            return any(contains_reference(item) for item in value)
        if isinstance(value, dict):
            return any(contains_reference(item) for item in value.values())
        return False

    for receipt_path in sorted(receipt_root.glob("*.json"), key=lambda item: item.name):
        if receipt_path.stat().st_size == 0:
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"capacity disposal receipt is unreadable: {receipt_path}"
            ) from exc
        if not isinstance(receipt, dict):
            raise ValueError(f"capacity disposal receipt is not an object: {receipt_path}")
        if (
            receipt.get("role") == "artifact_capacity_disposal_receipt"
            and receipt.get("status") == "pending"
            and contains_reference(receipt)
        ):
            return True
    return False


def _expired_lease_for_pruning(path: Path, *, now_timestamp: float) -> dict[str, Any] | None:
    """Validate one lease as an expired, exact pruning candidate."""

    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapacityProtectionLeaseError(path, f"lease JSON is unreadable: {exc}") from exc
    if not isinstance(document, dict):
        raise CapacityProtectionLeaseError(path, "lease JSON must be an object")
    try:
        lease_id = _validated_lease_id(document.get("lease_id"))
    except ValueError as exc:
        raise CapacityProtectionLeaseError(path, str(exc)) from exc
    expiry = parse_utc_timestamp(document.get("expires_at_utc"))
    created = parse_utc_timestamp(document.get("created_at_utc"))
    allowed_fields = {
        "schema_version", "role", "lease_id", "owner", "created_at_utc",
        "expires_at_utc", "closure_deadline_at_utc", "protected_cache_keys",
        "protected_paths", "committed_new_bytes",
    }
    if (
        document.get("schema_version") != 1
        or document.get("role") != "artifact_capacity_protection_lease"
        or path.name != f"{lease_id}.json"
        or not isinstance(document.get("owner"), str)
        or not document["owner"].strip()
        or created is None
        or expiry is None
        or created[0] >= expiry[0]
        or set(document) - allowed_fields
    ):
        raise CapacityProtectionLeaseError(path, "expired lease fields differ from schema version 1")
    try:
        _lease_closure_deadline(document, created=created, expiry=expiry)
        _validated_commitment(document.get("committed_new_bytes", 0))
    except ValueError as exc:
        raise CapacityProtectionLeaseError(path, str(exc)) from exc
    if expiry[0] > now_timestamp:
        return None
    return document


def _prune_expired_capacity_protection_leases_unlocked(
    root: Path, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Receipt-delete expired leases that no pending disposal still references."""

    from common.contracts.file_identity import file_sha256

    root = root.absolute()
    if not root.is_dir():
        raise ValueError("artifact root must exist")
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lease_root = root / PROTECTION_LEASE_DIRECTORY
    outcome: dict[str, Any] = {
        "schema_version": 1,
        "role": "artifact_capacity_protection_lease_pruning",
        "status": "complete",
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "pruned": [],
        "skipped_pending_disposal": [],
    }
    if not lease_root.exists():
        return outcome
    if not lease_root.is_dir() or lease_root.is_symlink():
        raise CapacityProtectionLeaseError(lease_root, "lease root is not a real directory")
    # Validate the entire active view first.  A malformed active lease must not
    # be hidden by deleting unrelated expired evidence in the same pass.
    _load_capacity_protection_leases_unlocked(root, now=observed)
    for path in sorted(lease_root.iterdir(), key=lambda item: item.name):
        if path.name == CAPACITY_DECISION_LOCK_NAME and path.is_file():
            continue
        if not path.is_file() or path.is_symlink() or path.suffix != ".json":
            raise CapacityProtectionLeaseError(path, "lease directory contains a non-JSON file")
        document = _expired_lease_for_pruning(path, now_timestamp=observed.timestamp())
        if document is None:
            continue
        lease_id = str(document["lease_id"])
        if _pending_disposal_references_lease(root, lease_id=lease_id, lease_path=path):
            outcome["skipped_pending_disposal"].append({
                "lease_id": lease_id, "path": str(path),
            })
            continue
        receipt_path = (
            root / PROTECTION_LEASE_PRUNING_RECEIPT_DIRECTORY / f"lease_{lease_id}.json"
        )
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"lease pruning receipt is unreadable: {receipt_path}") from exc
            expected = receipt.get("file")
            if (
                not isinstance(receipt, dict)
                or receipt.get("role") != "artifact_capacity_protection_lease_pruning_receipt"
                or receipt.get("lease_id") != lease_id
                or receipt.get("target_path") != str(path)
                or receipt.get("status") not in {"pending", "complete"}
                or not isinstance(expected, dict)
                or expected.get("path") != path.relative_to(root).as_posix()
                or isinstance(expected.get("bytes"), bool)
                or not isinstance(expected.get("bytes"), int)
                or int(expected["bytes"]) < 0
                or not isinstance(expected.get("sha256"), str)
                or re.fullmatch(r"[A-F0-9]{64}", expected["sha256"]) is None
            ):
                raise ValueError("lease pruning receipt conflicts with expired lease")
            if receipt.get("status") == "complete":
                if path.exists():
                    raise ValueError("completed lease pruning target reappeared")
                outcome["pruned"].append({"lease_id": lease_id, "path": str(path), "resumed": True})
                continue
            if not path.exists():
                receipt["status"] = "complete"
                receipt["completed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                _write_json_atomic(receipt_path, receipt)
                outcome["pruned"].append({"lease_id": lease_id, "path": str(path), "resumed": True})
                continue
        else:
            expected = {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
            receipt = {
                "schema_version": 1,
                "role": "artifact_capacity_protection_lease_pruning_receipt",
                "status": "pending",
                "reason": "expired_finite_protection_lease",
                "lease_id": lease_id,
                "target_path": str(path),
                "file": expected,
                "observed_at_utc": outcome["observed_at_utc"],
            }
            _write_json_atomic(receipt_path, receipt)
        expected_bytes = int(expected["bytes"])
        expected_sha256 = str(expected["sha256"])
        if path.exists():
            if path.stat().st_size != expected_bytes or file_sha256(path) != expected_sha256:
                raise ValueError("expired lease changed after pruning receipt was sealed")
            path.unlink()
        receipt["status"] = "complete"
        receipt["completed_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_json_atomic(receipt_path, receipt)
        outcome["pruned"].append({"lease_id": lease_id, "path": str(path), "receipt": str(receipt_path)})
    return outcome


def prune_expired_capacity_protection_leases(
    root: Path, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Prune only expired, receipt-unreferenced protection leases."""

    with capacity_decision_lock(root):
        return _prune_expired_capacity_protection_leases_unlocked(root, now=now)
