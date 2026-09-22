"""Validate sealed owner dispositions for legacy calibration and maintenance.

It turns an owner-approved, whole-range *metadata* inventory into the existing
ledger ``disposition`` shape.  Maintenance can activate an existing approval;
it never discovers or infers the owner's authority to abandon a range.
The PA family was content-sealed when it was built.  Retirement therefore
checks the recorded generation, paths and sizes once, without re-hashing a
large payload merely to delete it.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

from common.contracts import capacity_ledger, capacity_protection
from common.contracts.recorded_file_removal import write_json_atomic

SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
ROLE = "artifact_capacity_owner_retirement_disposition"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("owner disposition path is invalid")
    path = Path(value)
    if path.is_absolute() or path.drive or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("owner disposition path is not canonical relative")
    result = path.as_posix()
    if result != value:
        raise ValueError("owner disposition path is not canonical relative")
    return result


def _link_or_reparse(path: Path) -> bool:
    """Reject links before resolution can erase their lexical presence."""

    try:
        attributes = path.lstat().st_file_attributes
    except AttributeError:
        attributes = 0
    return path.is_symlink() or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _expected_owner(target_relative: str) -> str:
    parts = Path(target_relative).parts
    if len(parts) >= 2 and parts[0] == "projects" and parts[1]:
        return parts[1]
    if len(parts) >= 4 and parts[:3] == ("common", "simion", "pa_family_cache"):
        return "common.simion.pa_family_cache"
    raise ValueError("owner disposition target has no approved owner namespace")


def load_legacy_owner_disposition(root: Path, document_path: Path) -> dict[str, Any]:
    """Return a verified ledger candidate from one fixed governance document."""

    root = root.resolve(strict=False)
    try:
        document = json.loads(document_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("owner disposition document is unreadable") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "role", "status", "owner", "target_path",
        "authority_evidence", "disposition",
    }:
        raise ValueError("owner disposition document schema differs")
    if document.get("schema_version") != 2 or document.get("role") != ROLE or document.get("status") != "retire_approved":
        raise ValueError("owner disposition document role or status differs")
    owner = document.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner disposition owner is invalid")
    target_relative = _relative(document["target_path"])
    expected_owner = _expected_owner(target_relative)
    if owner.strip() != expected_owner:
        raise ValueError("owner disposition owner differs from target namespace")
    target = root
    for part in Path(target_relative).parts:
        target = target / part
        if _link_or_reparse(target):
            raise ValueError("owner disposition target path traverses a symbolic link")
    if not target.is_dir():
        raise ValueError("owner disposition target is not a regular directory")
    evidence = document.get("authority_evidence")
    disposition = document.get("disposition")
    if not isinstance(evidence, dict) or set(evidence) != {"path"}:
        raise ValueError("owner disposition evidence schema differs")
    evidence_path = _relative(evidence.get("path"))
    if not isinstance(disposition, dict) or set(disposition) != {"id", "generation", "manifest_path", "files"}:
        raise ValueError("owner disposition sealed inventory schema differs")
    if any(not isinstance(disposition.get(key), str) or SHA256.fullmatch(disposition[key]) is None for key in ("id", "generation")):
        raise ValueError("owner disposition identity is invalid")
    manifest_path = _relative(disposition.get("manifest_path"))
    files = disposition.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("owner disposition inventory is empty")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in files:
        if not isinstance(record, dict) or set(record) != {"path", "bytes"}:
            raise ValueError("owner disposition inventory record schema differs")
        relative = _relative(record.get("path"))
        if relative in seen or isinstance(record.get("bytes"), bool) or not isinstance(record.get("bytes"), int) or record["bytes"] < 0:
            raise ValueError("owner disposition inventory record is invalid")
        seen.add(relative)
        records.append({"path": relative, "bytes": record["bytes"]})
    if evidence_path not in seen or manifest_path != evidence_path:
        raise ValueError("owner disposition evidence is not bound to inventory")
    expected_id = hashlib.sha256(_canonical({
        "owner": owner.strip(), "target_path": target_relative,
        "authority_evidence": {"path": evidence_path},
        "generation": disposition["generation"].upper(),
        "manifest_path": manifest_path, "files": records,
    }).encode("utf-8")).hexdigest().upper()
    if disposition["id"].upper() != expected_id or document_path.name != f"{expected_id}.json":
        raise ValueError("owner disposition id or filename differs")
    actual: dict[str, int] = {}
    for item in target.rglob("*"):
        if item.is_symlink():
            raise ValueError("owner disposition target contains a symbolic link")
        if item.is_file():
            relative = item.relative_to(target).as_posix()
            actual[relative] = item.stat().st_size
    declared = {item["path"]: item["bytes"] for item in records}
    if actual != declared:
        raise ValueError("owner disposition inventory differs from target")
    return {
        "path": target_relative, "class": "rebuildable_payload", "bytes": sum(item["bytes"] for item in records),
        "status": "ready", "pin": False, "owner_hint": owner.strip(),
        "disposition": {"id": expected_id, "generation": disposition["generation"].upper(),
                        "manifest_path": manifest_path, "files": records},
    }


def activate_owner_dispositions(root: Path) -> dict[str, Any]:
    """Bind owner-approved legacy PA ranges into the current ledger.

    This is the narrow bridge for the historical case where a valid PA family
    predates its owner transaction.  It never discovers candidates, changes a
    transaction-bound family, or removes bytes.  Maintenance calls it before
    planning so owner intent remains the sole admission route to deletion.
    """

    root = root.resolve(strict=False)
    directory = root / "common" / "capacity_calibration" / "owner_dispositions"
    if not directory.exists():
        return {"activated_count": 0, "activated_bytes": 0}
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("owner disposition directory is not a regular directory")
    with capacity_protection.capacity_decision_lock(root):
        ledger = capacity_ledger.load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        archived_count = 0
        for document_path in sorted(directory.glob("*.json")):
            try:
                raw = json.loads(document_path.read_text(encoding="utf-8-sig"))
                disposition = raw["disposition"]
                disposition_id = disposition["id"].upper()
                target_path = _relative(raw["target_path"])
                authorization = {
                    "owner": raw["owner"], "target_path": target_path,
                    "authority_evidence": raw["authority_evidence"],
                }
            except (KeyError, TypeError, ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("owner disposition document is unreadable") from exc
            entry = next((item for item in ledger["objects"] if item.get("path") == target_path), None)
            receipt_path = root / "common" / "capacity_disposal_receipts" / f"ledger_disposition_{disposition_id}.json"
            if (
                entry is None or entry.get("status") != "retired"
                or entry.get("disposition", {}).get("id") != disposition_id
                or not receipt_path.is_file()
            ):
                continue
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("completed owner disposition receipt is unreadable") from exc
            if (
                receipt.get("role") != "artifact_capacity_disposal_receipt"
                or receipt.get("status") != "complete"
                or receipt.get("disposition", {}).get("id") != disposition_id
                or receipt.get("target_path") != str((root / target_path).resolve(strict=False))
            ):
                continue
            existing_authorization = receipt.get("owner_disposition_authorization")
            if existing_authorization is not None and existing_authorization != authorization:
                raise ValueError("completed owner disposition receipt authorization conflicts")
            if existing_authorization is None:
                receipt["owner_disposition_authorization"] = authorization
                write_json_atomic(receipt_path, receipt)
            document_path.unlink()
            archived_count += 1

        approved: list[tuple[Path, dict[str, Any]]] = []
        seen: set[str] = set()
        for document_path in sorted(directory.glob("*.json")):
            candidate = load_legacy_owner_disposition(root, document_path)
            if candidate["path"] in seen:
                raise ValueError("multiple owner dispositions target one managed range")
            seen.add(candidate["path"])
            approved.append((document_path, candidate))
        if not approved:
            return {"activated_count": 0, "activated_bytes": 0,
                    "archived_document_count": archived_count}
        activated: list[dict[str, Any]] = []
        for _, candidate in approved:
            target, relative = capacity_ledger.capacity_object_path(root, candidate["path"])
            entry = next((item for item in ledger["objects"] if item.get("path") == relative), None)
            expected = {
                "path": relative, "class": "rebuildable_payload",
                "bytes": candidate["bytes"], "status": "ready", "pin": False,
                "owner": candidate["owner_hint"], "disposition": candidate["disposition"],
            }
            if entry == expected:
                continue
            if (
                entry is None or entry.get("class") != "published_cache"
                or entry.get("status") != "writing"
                or entry.get("recovery_reason") != "legacy_pa_cache_missing_owner_transaction"
                or entry.get("owner") != candidate["owner_hint"]
                or entry.get("identity", "").upper() != candidate["disposition"]["generation"]
                or entry.get("bytes") != candidate["bytes"]
            ):
                raise ValueError("owner disposition conflicts with the current legacy PA ledger entry")
            capacity_ledger._assert_unleased(root, target)
            entry.clear()
            entry.update(expected)
            activated.append({"path": relative, "bytes": candidate["bytes"]})
        if activated:
            write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
    return {
        "activated_count": len(activated),
        "activated_bytes": sum(item["bytes"] for item in activated),
        "archived_document_count": archived_count,
    }
