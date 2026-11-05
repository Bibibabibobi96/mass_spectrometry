"""Maintain the small, trusted artifact-capacity ledger.

This module never discovers artifacts or hashes payloads.  A ledger may be
created only through :func:`initialize_capacity_ledger`; normal incremental
recording fails closed when that calibrated baseline is absent or invalid.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from common.contracts import capacity_protection as protection
from common.contracts.recorded_file_removal import write_json_atomic


# Normal runtime ownership migrated; historical maintenance remains here.
from msplatform.execution.capacity_ledger import (
    BASE_OBJECT_FIELDS as BASE_OBJECT_FIELDS,
    CAPACITY_LEDGER_RELATIVE_PATH as CAPACITY_LEDGER_RELATIVE_PATH,
    EXTERNAL_SCOPE_ROLES as EXTERNAL_SCOPE_ROLES,
    LEDGER_CLASSES as LEDGER_CLASSES,
    LEDGER_STATUSES as LEDGER_STATUSES,
    LEGACY_LIFECYCLE_FIELDS as LEGACY_LIFECYCLE_FIELDS,
    OPTIONAL_OBJECT_FIELDS as OPTIONAL_OBJECT_FIELDS,
    PA_CACHE_MANAGER as PA_CACHE_MANAGER,
    RECORDABLE_STATUSES as RECORDABLE_STATUSES,
    RECOVERY_FIELDS as RECOVERY_FIELDS,
    SHA256 as SHA256,
    V2_OPTIONAL_OBJECT_FIELDS as V2_OPTIONAL_OBJECT_FIELDS,
    V2_RECOVERY_FIELDS as V2_RECOVERY_FIELDS,
    _is_valid_capacity_ledger as _is_valid_capacity_ledger,
    _ledger_relative_path as _ledger_relative_path,
    _valid_disposition as _valid_disposition,
    _valid_range_owner as _valid_range_owner,
    capacity_object_path as capacity_object_path,
    initialize_capacity_ledger as initialize_capacity_ledger,
    load_capacity_ledger as load_capacity_ledger,
    pending_disposal_targets as pending_disposal_targets,
    record_capacity_object as record_capacity_object,
    resolve_ledger_path as resolve_ledger_path,
)


# Actual PA-cache lifecycle operations have one installed execution owner.
from msplatform.execution.capacity_ledger import (
    PA_RUNTIME_STATE_RELATIVE_PATHS as PA_RUNTIME_STATE_RELATIVE_PATHS,
    _assert_abandoned_pa_transaction_allowed as _assert_abandoned_pa_transaction_allowed,
    _assert_unleased as _assert_unleased,
    _utc_now as _utc_now,
    approve_published_cache_retirement as approve_published_cache_retirement,
    assert_abandoned_pa_transaction_allowed as assert_abandoned_pa_transaction_allowed,
    handoff_prepared_cache_stage as handoff_prepared_cache_stage,
    reconcile_abandoned_pa_transaction as reconcile_abandoned_pa_transaction,
    reconcile_pa_runtime_state as reconcile_pa_runtime_state,
    reconcile_pa_transaction_container_bytes as reconcile_pa_transaction_container_bytes,
    touch_capacity_object as touch_capacity_object,
)

STALE_ATOMIC_TEMP_PREFIX = ".capacity_ledger.json."
STALE_ATOMIC_TEMP_MINIMUM_AGE_SECONDS = 1.0
"""The ledger records *managed ranges*, not duties for individual files.

Each record is an exact directory or generation below the artifact root.  Its
``owner`` covers every file in that range; its class and state select the
existing retention or PA-manager exit path.  ``writing`` is the only resident
state that needs a deadline because it represents an unfinished operation.

The four former lifecycle fields are accepted while reading historical v3
ledgers so an interrupted migration remains inspectable, but new records do
not write them.  They duplicated facts already held by run manifests, PA
transactions, and the retention/retirement entry points.
"""
















def restore_retired_disposition_paths(
    root: Path, *, receipt_path: Path, expected_ledger_sha256: str,
    expected_receipt_sha256: str, apply: bool = False,
) -> dict[str, Any]:
    """Restore one damaged retired inventory path from its completed owner receipt.

    No payload discovery or capacity recalibration is permitted.  Surrogateescape
    preserves malformed input bytes only for comparison; the candidate must encode
    as strict UTF-8 and pass the complete existing ledger validator.
    """
    from common.contracts.file_identity import file_sha256

    root = root.resolve(strict=False)
    expected = expected_ledger_sha256.upper()
    source_sha = expected_receipt_sha256.upper()
    if SHA256.fullmatch(expected) is None or SHA256.fullmatch(source_sha) is None:
        raise ValueError("recovery requires explicit ledger and receipt SHA-256")
    receipt_path = receipt_path.resolve(strict=True)
    directory = root / "common" / "capacity_disposal_receipts"
    if receipt_path.parent != directory.resolve(strict=False):
        raise ValueError("recovery requires a public completed disposal receipt")
    destination = resolve_ledger_path(root)
    recovery_path = directory / f"ledger_path_recovery_{expected}.json"
    raw_path = directory / f"ledger_path_recovery_{expected}_raw.json"
    with protection.capacity_decision_lock(root):
        source_raw = receipt_path.read_bytes()
        if hashlib.sha256(source_raw).hexdigest().upper() != source_sha:
            raise ValueError("completed disposal receipt SHA changed")
        source = json.loads(source_raw.decode("utf-8-sig"))
        prior = None
        if recovery_path.exists():
            prior = json.loads(recovery_path.read_text(encoding="utf-8"))
            if (prior.get("role") != "capacity_ledger_retired_path_recovery"
                    or prior.get("original_sha256") != expected
                    or prior.get("source_receipt_sha256") != source_sha
                    or prior.get("source_receipt_path") != str(receipt_path)
                    or prior.get("status") not in {"pending", "complete"}):
                raise ValueError("recovery publication receipt conflicts")
        backup_raw = None
        if raw_path.exists():
            backup = json.loads(raw_path.read_text(encoding="utf-8"))
            if (set(backup) != {"schema_version", "role", "bytes", "sha256", "base64"}
                    or backup.get("schema_version") != 1
                    or backup.get("role") != "capacity_ledger_damaged_raw_backup"
                    or backup.get("sha256") != expected):
                raise ValueError("recovery raw backup conflicts")
            backup_raw = base64.b64decode(backup["base64"], validate=True)
            if (len(backup_raw) != backup.get("bytes")
                    or hashlib.sha256(backup_raw).hexdigest().upper() != expected):
                raise ValueError("recovery raw backup failed verification")
        current_raw = destination.read_bytes()
        current_sha = hashlib.sha256(current_raw).hexdigest().upper()
        if current_sha != expected:
            if (prior is not None and current_sha == prior.get("candidate_sha256")
                    and backup_raw is not None
                    and load_capacity_ledger(root) is not None):
                if apply and prior["status"] == "pending":
                    prior["status"] = "complete"
                    write_json_atomic(recovery_path, prior)
                return dict(prior, replayed=True)
            raise ValueError("capacity ledger SHA changed before recovery")
        # Decode without replacing any byte, then require the repaired whole
        # document to encode strictly.  No other damaged field can be hidden.
        document = json.loads(current_raw.decode("utf-8-sig", errors="surrogateescape"))
        try:
            current_raw.decode("utf-8-sig")
            valid = _is_valid_capacity_ledger(root, document)
        except (UnicodeDecodeError, ValueError, OSError):
            valid = False
        if valid:
            raise ValueError("valid capacity ledger cannot be overwritten by recovery")
        if (source.get("schema_version") != 1
                or source.get("role") != "artifact_capacity_disposal_receipt"
                or source.get("status") != "complete"
                or source.get("reason") != "manager_approved_disposition"
                or source.get("deleting_path") is not None):
            raise ValueError("recovery source is not a completed approved disposition")
        target, relative = capacity_object_path(root, source["target_path"])
        if str(target) != source["target_path"] or target.exists():
            raise ValueError("completed disposition target differs or reappeared")
        matches = [item for item in document["objects"] if item.get("path") == relative]
        if len(matches) != 1:
            raise ValueError("completed disposition has no unique ledger target")
        entry = matches[0]
        disposition = entry.get("disposition", {})
        sealed = source.get("disposition", {})
        authorization = source.get("owner_disposition_authorization", {})
        if (entry.get("status") != "retired" or entry.get("class") != "rebuildable_payload"
                or entry.get("pin") is not False or entry.get("consumers")
                or not isinstance(entry.get("owner"), str) or not entry["owner"].strip()
                or authorization.get("owner") != entry.get("owner")
                or authorization.get("target_path") != relative
                or authorization.get("authority_evidence", {}).get("path") != sealed.get("manifest_path")
                or not _valid_disposition(sealed, expected_bytes=entry["bytes"])
                or source.get("removed_bytes") != entry["bytes"]
                or source.get("removed") != sorted(item["path"] for item in sealed["files"])
                or receipt_path.name != f"ledger_disposition_{sealed.get('id')}.json"
                or {key: value for key, value in disposition.items() if key != "files"}
                   != {key: value for key, value in sealed.items() if key != "files"}):
            raise ValueError("retired target owner, identity, or completed inventory differs")
        original_files = disposition.get("files", [])
        if len(original_files) != len(sealed["files"]):
            raise ValueError("retired inventory file count differs")
        changes = []
        for index, (old, new) in enumerate(zip(original_files, sealed["files"], strict=True)):
            if {key: value for key, value in old.items() if key != "path"} != {
                    key: value for key, value in new.items() if key != "path"}:
                raise ValueError("retired inventory non-path evidence differs")
            if old.get("path") == new["path"]:
                continue
            value = old.get("path")
            try:
                value.encode("utf-8", errors="strict")
                malformed = _ledger_relative_path(value) is None or any(ord(c) < 32 for c in value)
            except (AttributeError, UnicodeEncodeError):
                malformed = True
            if not malformed:
                raise ValueError("recovery cannot replace a valid retired inventory path")
            changes.append(index)
        if len(changes) != 1:
            raise ValueError("recovery requires exactly one damaged retired inventory path")
        candidate = copy.deepcopy(document)
        candidate["objects"][document["objects"].index(entry)]["disposition"]["files"] = copy.deepcopy(sealed["files"])
        candidate_raw = (json.dumps(candidate, indent=2, ensure_ascii=False) + "\n").encode("utf-8", errors="strict")
        if not _is_valid_capacity_ledger(root, candidate):
            raise ValueError("restored capacity ledger remains invalid")
        result = dict(schema_version=1, role="capacity_ledger_retired_path_recovery", status="pending",
                      original_sha256=expected, original_bytes=len(current_raw),
                      source_receipt_path=str(receipt_path), source_receipt_sha256=source_sha,
                      candidate_sha256=hashlib.sha256(candidate_raw).hexdigest().upper(),
                      raw_backup_path=str(raw_path), target_path=relative, changed_file_indices=changes,
                      resident_bytes=document["resident_bytes"])
        if prior is not None and {**prior, "status": "pending"} != result:
            raise ValueError("recovery publication plan changed")
        if not apply:
            return dict(result, dry_run=True)
        if backup_raw is None:
            write_json_atomic(raw_path, dict(schema_version=1, role="capacity_ledger_damaged_raw_backup",
                bytes=len(current_raw), sha256=expected, base64=base64.b64encode(current_raw).decode("ascii")))
        saved_backup = json.loads(raw_path.read_text(encoding="utf-8"))
        saved_raw = base64.b64decode(saved_backup["base64"], validate=True)
        if saved_raw != current_raw or saved_backup["sha256"] != expected or saved_backup["bytes"] != len(current_raw):
            raise ValueError("recovery raw backup failed verification")
        write_json_atomic(recovery_path, result)
        if file_sha256(destination) != expected or file_sha256(receipt_path) != source_sha:
            raise ValueError("recovery source changed before atomic publication")
        write_json_atomic(destination, candidate)
        if file_sha256(destination) != result["candidate_sha256"] or load_capacity_ledger(root) != candidate:
            raise ValueError("restored capacity ledger publication failed verification")
        result["status"] = "complete"
        write_json_atomic(recovery_path, result)
        return result


def restore_ledger_object_key(
    root: Path, *, receipt_path: Path, expected_ledger_sha256: str,
    expected_receipt_sha256: str, apply: bool = False,
) -> dict[str, Any]:
    """Restore one missing path/class key from an authenticated original object.

    Only a retired unpinned zero-byte path or a ready object's class is covered.
    The complete object must match the source record; only one raw key token
    changes. No payload discovery, class inference or recalibration occurs.
    """
    root = root.resolve(strict=False)
    directory = root / "common" / "capacity_disposal_receipts"
    receipt_path = receipt_path.resolve(strict=True)
    expected, authority = expected_ledger_sha256.upper(), expected_receipt_sha256.upper()
    if receipt_path.parent != directory.resolve() or any(SHA256.fullmatch(s) is None for s in (expected, authority)):
        raise ValueError("object-key recovery requires a public receipt and explicit SHA identities")
    destination = resolve_ledger_path(root)
    recovery_path = directory / f"ledger_key_recovery_{expected}.json"
    backup_path = directory / f"ledger_key_recovery_{expected}_raw.json"
    with protection.capacity_decision_lock(root):
        receipt_raw = receipt_path.read_bytes()
        if hashlib.sha256(receipt_raw).hexdigest().upper() != authority:
            raise ValueError("object-key recovery authority changed")
        receipt = json.loads(receipt_raw)
        if (receipt.get("role") not in {"capacity_ledger_retired_path_recovery",
                "capacity_ledger_retired_key_recovery", "capacity_ledger_object_key_recovery"}
                or receipt.get("status") != "complete"):
            raise ValueError("object-key recovery requires a completed original recovery receipt")
        original_path = Path(receipt["raw_backup_path"]).resolve(strict=True)
        if original_path.parent != directory.resolve():
            raise ValueError("original raw backup is outside public evidence")
        original_backup_raw = original_path.read_bytes()
        backup = json.loads(original_backup_raw)
        original_raw = base64.b64decode(backup["base64"], validate=True)
        if (backup.get("role") != "capacity_ledger_damaged_raw_backup"
                or len(original_raw) != backup.get("bytes")
                or hashlib.sha256(original_raw).hexdigest().upper() != receipt["original_sha256"]
                or backup.get("sha256") != receipt["original_sha256"]):
            raise ValueError("original raw backup identity differs")
        original = json.loads(original_raw.decode("utf-8-sig", errors="surrogateescape"))

        def candidate_from(raw):
            document = json.loads(raw.decode("utf-8-sig"))
            if _is_valid_capacity_ledger(root, document):
                raise ValueError("valid capacity ledger cannot be overwritten")
            missing = [(i, item, {"path", "class"} - item.keys())
                       for i, item in enumerate(document["objects"])
                       if {"path", "class"} - item.keys()]
            if len(missing) != 1 or len(missing[0][2]) != 1:
                raise ValueError("object-key recovery requires exactly one missing path/class key")
            index, item, fields = missing[0]
            restored_key = next(iter(fields))
            unknown = item.keys() - BASE_OBJECT_FIELDS - OPTIONAL_OBJECT_FIELDS
            if len(unknown) != 1:
                raise ValueError("object-key recovery requires one unknown replacement key")
            damaged_key = next(iter(unknown))
            restored = {(restored_key if k == damaged_key else k): v for k, v in item.items()}
            matches = [r for r in original["objects"] if r.get("path") == restored["path"]]
            if matches != [restored]:
                raise ValueError("object differs from original authenticated inventory")
            if restored_key == "path":
                if restored.get("status") != "retired" or restored.get("bytes") != 0 or restored.get("pin"):
                    raise ValueError("path recovery requires one unpinned zero-byte retired record")
                if (root / restored["path"]).exists():
                    raise ValueError("retired payload reappeared")
            elif restored.get("status") != "ready":
                raise ValueError("class recovery requires a ready record")
            needle = json.dumps(damaged_key).encode() + b":"
            if raw.count(needle) != 1:
                raise ValueError("damaged key is not a unique raw token")
            candidate = raw.replace(needle, json.dumps(restored_key).encode() + b":", 1)
            if not _is_valid_capacity_ledger(root, json.loads(candidate)):
                raise ValueError("key restoration does not restore the complete ledger")
            return document, index, damaged_key, restored_key, restored["path"], candidate

        current_raw = destination.read_bytes()
        digest = hashlib.sha256(current_raw).hexdigest().upper()
        if digest != expected:
            if recovery_path.exists():
                prior = json.loads(recovery_path.read_bytes())
                if (prior.get("role") == "capacity_ledger_object_key_recovery"
                        and prior.get("original_sha256") == expected
                        and prior.get("source_receipt_sha256") == authority
                        and prior.get("source_receipt_path") == str(receipt_path)
                        and prior.get("candidate_sha256") == digest
                        and prior.get("status") in {"pending", "complete"}
                        and load_capacity_ledger(root) is not None):
                    saved = json.loads(backup_path.read_bytes())
                    saved_raw = base64.b64decode(saved["base64"], validate=True)
                    if (saved.get("role") != "capacity_ledger_damaged_raw_backup"
                            or saved.get("bytes") != len(saved_raw) or saved.get("sha256") != expected
                            or hashlib.sha256(saved_raw).hexdigest().upper() != expected):
                        raise ValueError("object-key recovery raw evidence differs")
                    _, index, key, restored_key, target, candidate = candidate_from(saved_raw)
                    if (candidate != current_raw or prior.get("damaged_key") != key
                            or prior.get("restored_key") != restored_key or prior.get("object_index") != index
                            or prior.get("target_path") != target):
                        raise ValueError("object-key recovery replay changed more than the original key")
                    if apply and prior["status"] == "pending":
                        prior["status"] = "complete"
                        write_json_atomic(recovery_path, prior)
                    return dict(prior, replayed=True)
            raise ValueError("capacity ledger changed before object-key recovery")
        document, index, key, restored_key, target, candidate_raw = candidate_from(current_raw)
        result = dict(schema_version=1, role="capacity_ledger_object_key_recovery", status="pending",
                      original_sha256=expected, source_receipt_path=str(receipt_path),
                      source_receipt_sha256=authority, candidate_sha256=hashlib.sha256(candidate_raw).hexdigest().upper(),
                      raw_backup_path=str(backup_path), object_index=index, target_path=target,
                      damaged_key=key, restored_key=restored_key, resident_bytes=document["resident_bytes"],
                      change="one raw key token only; all other bytes preserved")
        if recovery_path.exists() and json.loads(recovery_path.read_bytes()) != result:
            raise ValueError("object-key recovery journal conflicts")
        saved_backup = dict(schema_version=1, role="capacity_ledger_damaged_raw_backup",
            bytes=len(current_raw), sha256=expected, base64=base64.b64encode(current_raw).decode("ascii"))
        if backup_path.exists() and json.loads(backup_path.read_bytes()) != saved_backup:
            raise ValueError("object-key recovery raw evidence conflicts")
        if not apply:
            return dict(result, dry_run=True)
        if not backup_path.exists():
            write_json_atomic(backup_path, saved_backup)
        write_json_atomic(recovery_path, result)
        if (destination.read_bytes() != current_raw or receipt_path.read_bytes() != receipt_raw
                or original_path.read_bytes() != original_backup_raw):
            raise ValueError("object-key recovery source changed before publication")
        temporary = destination.with_name(destination.name+".key-recovery")
        if temporary.exists():
            if temporary.read_bytes() != candidate_raw:
                raise ValueError("object-key recovery staging bytes conflict")
        else:
            with temporary.open("xb") as stream:
                stream.write(candidate_raw)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, destination)
        if destination.read_bytes() != candidate_raw or load_capacity_ledger(root) is None:
            raise ValueError("object-key recovery publication failed verification")
        result["status"] = "complete"
        write_json_atomic(recovery_path, result)
        return result


def migrate_v2_ledger_document(
    root: Path, document: object, *, lifecycle_by_path: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a range-managed v3 ledger from an explicit owner assignment.

    ``lifecycle_by_path`` keeps its public name for the narrow historical
    migration API.  Ready ranges provide only ``{"owner": "..."}``; a
    writing range additionally carries its bounded recovery evidence.  The
    helper never infers ownership from a path.
    """

    root = root.resolve(strict=False)
    if not isinstance(document, dict) or document.get("schema_version") != 2:
        raise ValueError("v2 capacity ledger migration requires a valid v2 document")
    if not _is_valid_capacity_ledger(root, document):
        raise ValueError("v2 capacity ledger migration source is invalid")
    if not isinstance(lifecycle_by_path, dict):
        raise ValueError("v2 capacity ledger lifecycle assignments must be a mapping")
    resident_paths = {
        item["path"] for item in document["objects"] if item["status"] != "retired"
    }
    if set(lifecycle_by_path) != resident_paths:
        raise ValueError("v2 capacity ledger migration duties must cover exactly every resident object")
    migrated = json.loads(json.dumps(document))
    migrated["schema_version"] = 3
    for item in migrated["objects"]:
        if item["status"] == "retired":
            continue
        duties = lifecycle_by_path[item["path"]]
        expected = {"owner"}
        allowed = set(expected)
        if item["status"] == "writing":
            expected |= {"recovery_reason", "review_deadline"}
            allowed |= {"recovery_reason", "review_deadline", "recovery_task", "recovery_evidence_paths"}
        if not isinstance(duties, dict) or not expected.issubset(duties) or set(duties) - allowed:
            raise ValueError("v2 capacity ledger migration requires complete range management")
        owner = duties["owner"]
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("v2 capacity ledger range owner must be nonempty")
        item.update(duties)
        item["owner"] = owner.strip()
        if item["class"] == "published_cache":
            item["manager"] = PA_CACHE_MANAGER
    if not _is_valid_capacity_ledger(root, migrated):
        raise ValueError("v2 capacity ledger migration result is invalid")
    return migrated
























def begin_approved_disposition(
    root: Path, *, path: Path | str, disposition_id: str,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Recheck lease and exact manager approval, then make it resumable."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if (
            entry is None or entry.get("class") != "rebuildable_payload"
            or entry.get("status") not in {"ready", "retirement_pending"}
            or entry.get("pin") is not False
            or entry.get("disposition", {}).get("id") != disposition_id.upper()
        ):
            raise ValueError("manager-approved disposition differs from ledger")
        _assert_unleased(root, target)
        if entry["status"] == "ready":
            entry["status"] = "retirement_pending"
            write_json_atomic(destination, ledger)
        return dict(entry)


def retire_capacity_object(
    root: Path, *, path: Path | str, bytes_removed: int | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Record an already-completed whole-object retirement atomically."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if (
            entry is None
            or entry.get("class") != "rebuildable_payload"
            or entry.get("status") != "ready"
            or entry.get("pin") is True
            or "disposition" in entry
        ):
            raise ValueError("ledger object is not eligible for retirement")
        _assert_unleased(root, target)
        amount = int(entry["bytes"] if bytes_removed is None else bytes_removed)
        if amount != int(entry["bytes"]):
            raise ValueError("ledger objects must be retired as one complete object")
        entry["status"] = "retired"
        entry["retired_at_utc"] = _utc_now()
        ledger["resident_bytes"] = int(ledger["resident_bytes"]) - amount
        write_json_atomic(destination, ledger)
    return entry


def recover_stale_atomic_ledger_temps(root: Path) -> dict[str, int]:
    """Retire crash-left ledger publication temps through the normal ledger.

    ``write_json_atomic`` has a bounded 0.75-second replacement retry.  A
    matching temp older than that interval, beside a valid current ledger, is
    therefore a failed publication residue rather than a new artifact.  This
    narrow owner recovery does not inspect its JSON payload or hash it.
    """

    root = root.resolve(strict=False)
    receipt_directory = root / "common" / "capacity_disposal_receipts"
    result = {"checked_count": 0, "retired_count": 0, "removed_bytes": 0,
              "fresh_count": 0, "invalid_count": 0, "replayed_count": 0}
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        now = time.time()
        candidates = [
            item for item in ledger["objects"]
            if item.get("status") in {"writing", "retirement_pending"}
            and item.get("owner") == "common.capacity_lifecycle"
            and Path(str(item.get("path", ""))).parent.as_posix() == "common"
            and Path(str(item.get("path", ""))).name.startswith(STALE_ATOMIC_TEMP_PREFIX)
        ]
        for entry in candidates:
            result["checked_count"] += 1
            target, relative = capacity_object_path(root, entry["path"])
            receipt = receipt_directory / f"atomic-ledger-temp-{target.name}.json"
            if entry["status"] == "retirement_pending" and not target.exists():
                try:
                    receipt_document = json.loads(receipt.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    result["invalid_count"] += 1
                    continue
                if (receipt_document.get("role") != "capacity_ledger_atomic_temp_recovery"
                        or receipt_document.get("status") not in {"retirement_pending", "retired"}
                        or receipt_document.get("target_path") != relative
                        or receipt_document.get("expected_bytes") != int(entry["bytes"])):
                    result["invalid_count"] += 1
                    continue
                entry["status"] = "retired"
                entry["retired_at_utc"] = _utc_now()
                entry.pop("retirement_error", None)
                ledger["resident_bytes"] -= int(entry["bytes"])
                receipt_document["status"] = "retired"
                receipt_document["removed_bytes"] = int(entry["bytes"])
                write_json_atomic(receipt, receipt_document)
                write_json_atomic(resolve_ledger_path(root), ledger)
                result["retired_count"] += 1
                result["removed_bytes"] += int(entry["bytes"])
                result["replayed_count"] += 1
                continue
            if target.is_symlink() or not target.is_file() or target.stat().st_size != int(entry["bytes"]):
                result["invalid_count"] += 1
                continue
            if (entry["status"] == "writing"
                    and now - target.stat().st_mtime < STALE_ATOMIC_TEMP_MINIMUM_AGE_SECONDS):
                result["fresh_count"] += 1
                continue
            _assert_unleased(root, target)
            if entry["status"] == "writing":
                entry["status"] = "retirement_pending"
                entry.pop("recovery_reason", None)
                entry.pop("recovery_task", None)
                entry.pop("recovery_evidence_paths", None)
                write_json_atomic(receipt, {
                    "schema_version": 1,
                    "role": "capacity_ledger_atomic_temp_recovery",
                    "status": "retirement_pending",
                    "target_path": relative,
                    "expected_bytes": int(entry["bytes"]),
                })
                write_json_atomic(resolve_ledger_path(root), ledger)
            try:
                target.unlink()
            except OSError as exc:
                entry["retirement_error"] = f"{type(exc).__name__}: {exc}"
                write_json_atomic(resolve_ledger_path(root), ledger)
                continue
            entry["status"] = "retired"
            entry["retired_at_utc"] = _utc_now()
            ledger["resident_bytes"] -= int(entry["bytes"])
            receipt_document = json.loads(receipt.read_text(encoding="utf-8-sig"))
            receipt_document["status"] = "retired"
            receipt_document["removed_bytes"] = int(entry["bytes"])
            write_json_atomic(receipt, receipt_document)
            write_json_atomic(resolve_ledger_path(root), ledger)
            result["retired_count"] += 1
            result["removed_bytes"] += int(entry["bytes"])
    return result






def mark_retirement_pending(
    root: Path, *, path: Path | str, ledger_path: Path | None = None,
) -> int:
    """Recheck admission and publish pending state within one short lock."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        _assert_unleased(root, target)
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if entry is None or entry.get("status") not in {"ready", "retirement_pending"} or entry.get("pin") is True:
            raise ValueError(f"ledger object is no longer removable: {target}")
        if entry.get("class") != "rebuildable_payload" or "disposition" in entry:
            raise ValueError(f"ledger object class is not removable: {target}")
        if entry["status"] == "ready":
            entry["status"] = "retirement_pending"
            entry.pop("retirement_error", None)
            write_json_atomic(destination, ledger)
        return int(entry["bytes"])


def record_retirement_error(
    root: Path, *, path: Path | str, error: str, ledger_path: Path | None = None,
) -> None:
    """Persist an interrupted retirement reason while leaving it resumable."""

    root = root.resolve(strict=False)
    _, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            return
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if entry is not None and entry.get("status") == "retirement_pending":
            entry["retirement_error"] = error
            write_json_atomic(destination, ledger)


def finalize_retirement(
    root: Path, *, path: Path | str, removed_bytes: int, ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Finalize one pending retirement and debit its calibrated byte count."""

    root = root.resolve(strict=False)
    target, relative = capacity_object_path(root, path)
    destination = resolve_ledger_path(root, ledger_path)
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger became invalid while retirement was in progress")
        entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
        if entry is None or entry.get("status") != "retirement_pending":
            raise ValueError("capacity ledger retirement state changed before finalization")
        expected = int(entry["bytes"])
        if removed_bytes != expected:
            raise ValueError(f"removed byte count {removed_bytes} differs from ledger {expected}")
        entry["status"] = "retired"
        entry["retired_at_utc"] = _utc_now()
        entry.pop("retirement_error", None)
        ledger["resident_bytes"] = int(ledger["resident_bytes"]) - removed_bytes
        write_json_atomic(destination, ledger)
        return entry


def update_external_scope_bytes(
    root: Path, *, role: str, path: Path, expected_bytes: int, new_bytes: int,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically update one calibration-only external scope after exact disposal."""

    if role not in EXTERNAL_SCOPE_ROLES or min(expected_bytes, new_bytes) < 0:
        raise ValueError("external scope update values are invalid")
    root = root.resolve(strict=False)
    destination = resolve_ledger_path(root, ledger_path)
    canonical = str(path.resolve(strict=False))
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        entry = next((item for item in ledger["external_scopes"] if item["role"] == role), None)
        if entry is None or entry["path"] != canonical or int(entry["bytes"]) != expected_bytes:
            raise ValueError("external scope record differs from approved disposition")
        entry["bytes"] = new_bytes
        ledger["resident_bytes"] += new_bytes - expected_bytes
        write_json_atomic(destination, ledger)
        return dict(entry)


def record_external_scope(
    root: Path, *, role: str, path: Path, bytes_count: int,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Register one measured workspace range without rediscovering artifacts."""

    if role not in EXTERNAL_SCOPE_ROLES or isinstance(bytes_count, bool) or bytes_count < 0:
        raise ValueError("external scope record is invalid")
    root = root.resolve(strict=False)
    destination = resolve_ledger_path(root, ledger_path)
    canonical = str(path.resolve(strict=False))
    with protection.capacity_decision_lock(root):
        ledger = load_capacity_ledger(root, destination)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        existing = next((item for item in ledger["external_scopes"] if item["role"] == role), None)
        if existing is not None:
            if existing["path"] != canonical or int(existing["bytes"]) != bytes_count:
                raise ValueError("external scope differs from its calibrated record")
            return dict(existing)
        if any(item["path"] == canonical for item in ledger["external_scopes"]):
            raise ValueError("external scope path is already registered")
        entry = {"role": role, "path": canonical, "bytes": bytes_count}
        ledger["external_scopes"].append(entry)
        ledger["external_scopes"].sort(key=lambda item: item["role"])
        ledger["resident_bytes"] += bytes_count
        write_json_atomic(destination, ledger)
        return dict(entry)
