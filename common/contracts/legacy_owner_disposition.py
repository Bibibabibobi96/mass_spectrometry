"""Validate a sealed owner disposition during explicit legacy calibration.

This module is deliberately not used by daily capacity maintenance.  It turns
one owner-approved, whole-range inventory into the existing ledger
``disposition`` shape; maintenance later consumes that already-frozen value.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256

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
    if document.get("schema_version") != 1 or document.get("role") != ROLE or document.get("status") != "retire_approved":
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
    if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}:
        raise ValueError("owner disposition evidence schema differs")
    evidence_path = _relative(evidence.get("path"))
    evidence_sha = evidence.get("sha256")
    if not isinstance(evidence_sha, str) or SHA256.fullmatch(evidence_sha) is None:
        raise ValueError("owner disposition evidence identity is invalid")
    if not isinstance(disposition, dict) or set(disposition) != {"id", "generation", "manifest_sha256", "files"}:
        raise ValueError("owner disposition sealed inventory schema differs")
    if any(not isinstance(disposition.get(key), str) or SHA256.fullmatch(disposition[key]) is None for key in ("id", "generation", "manifest_sha256")):
        raise ValueError("owner disposition identity is invalid")
    files = disposition.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("owner disposition inventory is empty")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in files:
        if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
            raise ValueError("owner disposition inventory record schema differs")
        relative = _relative(record.get("path"))
        if relative in seen or isinstance(record.get("bytes"), bool) or not isinstance(record.get("bytes"), int) or record["bytes"] < 0 or not isinstance(record.get("sha256"), str) or SHA256.fullmatch(record["sha256"]) is None:
            raise ValueError("owner disposition inventory record is invalid")
        seen.add(relative)
        records.append({"path": relative, "bytes": record["bytes"], "sha256": record["sha256"].upper()})
    if evidence_path not in seen or disposition["manifest_sha256"].upper() != evidence_sha.upper():
        raise ValueError("owner disposition evidence is not bound to inventory")
    expected_id = hashlib.sha256(_canonical({
        "owner": owner.strip(), "target_path": target_relative,
        "authority_evidence": {"path": evidence_path, "sha256": evidence_sha.upper()},
        "generation": disposition["generation"].upper(),
        "manifest_sha256": disposition["manifest_sha256"].upper(), "files": records,
    }).encode("utf-8")).hexdigest().upper()
    if disposition["id"].upper() != expected_id or document_path.name != f"{expected_id}.json":
        raise ValueError("owner disposition id or filename differs")
    actual: dict[str, tuple[int, str]] = {}
    for item in target.rglob("*"):
        if item.is_symlink():
            raise ValueError("owner disposition target contains a symbolic link")
        if item.is_file():
            relative = item.relative_to(target).as_posix()
            actual[relative] = (item.stat().st_size, file_sha256(item).upper())
    declared = {item["path"]: (item["bytes"], item["sha256"]) for item in records}
    if actual != declared:
        raise ValueError("owner disposition inventory differs from target")
    if actual[evidence_path][1] != evidence_sha.upper():
        raise ValueError("owner disposition authority evidence differs")
    return {
        "path": target_relative, "class": "rebuildable_payload", "bytes": sum(item["bytes"] for item in records),
        "status": "ready", "pin": False, "owner_hint": owner.strip(),
        "disposition": {"id": expected_id, "generation": disposition["generation"].upper(),
                        "manifest_sha256": disposition["manifest_sha256"].upper(), "files": records},
    }
