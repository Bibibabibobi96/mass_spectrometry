"""Validate sealed owner dispositions for legacy calibration and maintenance.

It turns an owner-approved, whole-range *metadata* inventory into the existing
ledger ``disposition`` shape.  Maintenance can activate an existing approval;
it never discovers or infers the owner's authority to abandon a range.
The PA family was content-sealed when it was built.  Retirement therefore
checks the recorded generation, paths and sizes once, without re-hashing a
large payload merely to delete it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

from common.contracts import capacity_ledger, capacity_protection
from common.contracts.artifact_retention import classify_file
from common.contracts.run_capacity_lifecycle import (
    HEAVY_RETENTION_ROLES,
    partial_retirement_is_protected,
    recorded_heavy_identity,
)
from common.contracts.recorded_file_removal import write_json_atomic

SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
ROLE = "artifact_capacity_owner_retirement_disposition"
OWNER_DISPOSITION_DIRECTORY = Path("common") / "capacity_calibration" / "owner_dispositions"


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


def _run_target(target_relative: str) -> tuple[str, str]:
    """Require the narrow historical-run scope of user abandonment.

    GUI review packages and PA generations have their own owners and retirement
    protocols.  This bridge is deliberately limited to an exact project run,
    so it cannot turn an arbitrary registered directory into a deletion plan.
    """

    parts = Path(target_relative).parts
    if len(parts) != 4 or parts[0] != "projects" or parts[2] != "runs":
        raise ValueError("owner disposition authoring requires one exact project run target")
    owner, run_id = parts[1], parts[3]
    if not owner or not run_id:
        raise ValueError("owner disposition authoring run target is invalid")
    return owner, run_id


def _target_inventory(target: Path) -> list[dict[str, Any]]:
    """Freeze paths and sizes only; retirement must not re-read payload bytes."""

    records: list[dict[str, Any]] = []
    for item in sorted(target.rglob("*"), key=lambda candidate: candidate.as_posix()):
        if _link_or_reparse(item):
            raise ValueError("owner disposition target contains a symbolic link")
        if item.is_file():
            records.append({
                "path": item.relative_to(target).as_posix(),
                "bytes": item.stat().st_size,
            })
    if not records:
        raise ValueError("owner disposition inventory is empty")
    return records


def _range_contains(range_path: str, path: str) -> bool:
    return path == range_path or path.startswith(range_path + "/")


def _ranges_overlap(left: str, right: str) -> bool:
    return _range_contains(left, right) or _range_contains(right, left)


def _regular_target_file(target: Path, relative: str) -> Path:
    """Return one target-local file without allowing an intermediate link."""

    candidate = target
    for part in Path(relative).parts:
        candidate = candidate / part
        if _link_or_reparse(candidate):
            raise ValueError("owner disposition target path traverses a symbolic link")
    if not candidate.is_file():
        raise ValueError("owner disposition partial inventory differs from target")
    return candidate


def _partial_run_records(
    root: Path, ledger: dict[str, Any], *, target: Path, target_relative: str, owner: str,
) -> list[dict[str, Any]]:
    """Return only preclassified, manifest-identified heavy file entries.

    A directory range cannot be split safely by an abandonment document.  The
    existing partial-retirement executor already owns that transition, so the
    owner document is limited to exact leaf ledger entries it can consume.
    """

    entries = ledger["objects"]
    overlaps = [
        item for item in entries
        if item.get("status") != "retired" and _ranges_overlap(str(item.get("path", "")), target_relative)
    ]
    if any(not _range_contains(target_relative, str(item["path"])) for item in overlaps):
        raise ValueError("owner disposition target is only part of a registered range")
    records: list[dict[str, Any]] = []
    for entry in overlaps:
        path = root / str(entry["path"])
        if not path.is_file():
            continue
        path = _regular_target_file(target, path.relative_to(target).as_posix())
        if classify_file(path, bytes_count=int(entry["bytes"])) not in HEAVY_RETENTION_ROLES:
            continue
        if (
            entry.get("class") != "rebuildable_payload"
            or entry.get("status") != "writing"
            or entry.get("owner") != owner
            or entry.get("pin") is not False
            or entry.get("disposition")
            or entry.get("recovery_reason") not in {
                "structured_nonterminal_run_reference", "run_contract_missing_or_invalid",
            }
        ):
            raise ValueError("owner disposition heavy file is not an eligible owner-managed writing entry")
        if path.stat().st_size != int(entry["bytes"]):
            raise ValueError("owner disposition heavy file differs from its registered bytes")
        if partial_retirement_is_protected(root, ledger, entry, path):
            raise ValueError("owner disposition heavy file has active protection")
        identity = recorded_heavy_identity(target, path, int(entry["bytes"]))
        if identity is None:
            raise ValueError("owner disposition heavy file lacks one manifest identity")
        records.append({
            "path": path.relative_to(target).as_posix(),
            "bytes": int(entry["bytes"]),
        })
    if not records:
        raise ValueError("owner disposition run has no classified eligible heavy ledger file")
    return sorted(records, key=lambda item: item["path"])


def _read_owner_disposition_target(document_path: Path) -> str:
    """Read only small governance metadata while checking target conflicts."""

    try:
        document = json.loads(document_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("owner disposition document is unreadable") from exc
    if not isinstance(document, dict):
        raise ValueError("owner disposition document is unreadable")
    return _relative(document.get("target_path"))


def author_owner_disposition(
    root: Path, *, target_path: Path | str, authority_evidence_path: Path | str,
) -> dict[str, Any]:
    """Seal an explicitly authorized historical run for the existing owner route.

    The caller's use of this narrow owner entry is the explicit abandonment
    decision.  It records only existing heavy *file* ranges that the partial
    retirement executor can remove.  Configurations, results, unlisted files,
    and directory ranges remain untouched.  It does not activate or remove
    the run; maintenance remains the sole execution path.
    """

    root = root.resolve(strict=False)
    target, target_relative = capacity_ledger.capacity_object_path(root, target_path)
    target_relative = _relative(target_relative)
    owner, _ = _run_target(target_relative)
    if not target.is_dir() or _link_or_reparse(target):
        raise ValueError("owner disposition target is not a regular directory")
    evidence, evidence_relative = capacity_ledger.capacity_object_path(root, authority_evidence_path)
    if not _range_contains(target_relative, evidence_relative) or not evidence.is_file() or _link_or_reparse(evidence):
        raise ValueError("owner disposition authority evidence must be a regular file in the target run")
    evidence_in_target = Path(evidence_relative).relative_to(Path(target_relative)).as_posix()

    with capacity_protection.capacity_decision_lock(root):
        ledger = capacity_ledger.load_capacity_ledger(root)
        if ledger is None:
            raise ValueError("capacity ledger is missing or invalid")
        if evidence_in_target not in {record["path"] for record in _target_inventory(target)}:
            raise ValueError("owner disposition authority evidence is not in the target inventory")
        records = _partial_run_records(
            root, ledger, target=target, target_relative=target_relative,
            owner=owner,
        )
        generation = hashlib.sha256(_canonical({
            "owner": owner, "target_path": target_relative, "files": records,
        }).encode("utf-8")).hexdigest().upper()
        identity_seed = {
            "owner": owner, "target_path": target_relative,
        "authority_evidence": {"path": evidence_in_target},
        "generation": generation, "manifest_path": evidence_in_target,
        "files": records, "decision": "explicit_user_authorized_abandonment",
        "scope": "partial_run_heavy_files",
        }
        disposition_id = hashlib.sha256(_canonical(identity_seed).encode("utf-8")).hexdigest().upper()
        document = {
            "schema_version": 3, "role": ROLE, "status": "retire_approved",
            "owner": owner, "target_path": target_relative,
            "authority_evidence": {"path": evidence_in_target},
            "decision": "explicit_user_authorized_abandonment",
            "scope": "partial_run_heavy_files",
            "disposition": {
                "id": disposition_id, "generation": generation,
                "manifest_path": evidence_in_target, "files": records,
            },
        }
        directory = root / OWNER_DISPOSITION_DIRECTORY
        document_path = directory / f"{disposition_id}.json"
        if document_path.exists():
            existing = load_legacy_owner_disposition(root, document_path)
            if (
                existing["path"] != target_relative
                or existing["disposition"] != document["disposition"]
                or not existing["explicit_user_abandonment"]
            ):
                raise ValueError("existing owner disposition conflicts with sealed authorization")
            return {
                "document_path": str(document_path), "disposition_id": disposition_id,
                "bytes": sum(record["bytes"] for record in records), "created": False,
            }
        if directory.exists() and (not directory.is_dir() or directory.is_symlink()):
            raise ValueError("owner disposition directory is not a regular directory")
        if directory.exists():
            for existing_path in sorted(directory.glob("*.json")):
                if _read_owner_disposition_target(existing_path) == target_relative:
                    raise ValueError("existing owner disposition already targets this run")
        write_json_atomic(document_path, document)
        return {
            "document_path": str(document_path), "disposition_id": disposition_id,
            "bytes": sum(record["bytes"] for record in records), "created": True,
        }


def load_legacy_owner_disposition(root: Path, document_path: Path) -> dict[str, Any]:
    """Return a verified ledger candidate from one fixed governance document."""

    root = root.resolve(strict=False)
    try:
        document = json.loads(document_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("owner disposition document is unreadable") from exc
    version = document.get("schema_version") if isinstance(document, dict) else None
    expected_fields = {
        "schema_version", "role", "status", "owner", "target_path",
        "authority_evidence", "disposition",
    }
    scope = document.get("scope") if isinstance(document, dict) else None
    partial_run = scope == "partial_run_heavy_files"
    if version == 3:
        expected_fields.add("decision")
    if partial_run:
        expected_fields.add("scope")
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ValueError("owner disposition document schema differs")
    if version not in {2, 3} or document.get("role") != ROLE or document.get("status") != "retire_approved":
        raise ValueError("owner disposition document role or status differs")
    decision = document.get("decision")
    if version == 3 and decision != "explicit_user_authorized_abandonment":
        raise ValueError("owner disposition decision differs")
    owner = document.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner disposition owner is invalid")
    target_relative = _relative(document["target_path"])
    expected_owner = _expected_owner(target_relative)
    if owner.strip() != expected_owner:
        raise ValueError("owner disposition owner differs from target namespace")
    if partial_run:
        _run_target(target_relative)
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
    if manifest_path != evidence_path or (not partial_run and evidence_path not in seen):
        raise ValueError("owner disposition evidence is not bound to inventory")
    identity_seed = {
        "owner": owner.strip(), "target_path": target_relative,
        "authority_evidence": {"path": evidence_path},
        "generation": disposition["generation"].upper(),
        "manifest_path": manifest_path, "files": records,
    }
    if version == 3:
        identity_seed["decision"] = decision
    if partial_run:
        identity_seed["scope"] = scope
    expected_id = hashlib.sha256(_canonical(identity_seed).encode("utf-8")).hexdigest().upper()
    if disposition["id"].upper() != expected_id or document_path.name != f"{expected_id}.json":
        raise ValueError("owner disposition id or filename differs")
    declared = {item["path"]: item["bytes"] for item in records}
    if partial_run:
        for relative, bytes_count in declared.items():
            item = _regular_target_file(target, relative)
            if item.stat().st_size != bytes_count:
                raise ValueError("owner disposition partial inventory differs from target")
    else:
        actual: dict[str, int] = {}
        for item in target.rglob("*"):
            if item.is_symlink():
                raise ValueError("owner disposition target contains a symbolic link")
            if item.is_file():
                relative = item.relative_to(target).as_posix()
                actual[relative] = item.stat().st_size
        if actual != declared:
            raise ValueError("owner disposition inventory differs from target")
    return {
        "path": target_relative, "class": "rebuildable_payload", "bytes": sum(item["bytes"] for item in records),
        "status": "ready", "pin": False, "owner_hint": owner.strip(),
        "explicit_user_abandonment": version == 3,
        "partial_run": partial_run,
        "disposition": {"id": expected_id, "generation": disposition["generation"].upper(),
                        "manifest_path": manifest_path, "files": records},
    }


def _activate_candidate(
    root: Path, ledger: dict[str, Any], candidate: dict[str, Any],
    *, approved_paths: set[str],
) -> dict[str, Any] | None:
    """Bind one sealed whole-range decision without inferring abandonment.

    Legacy calibration recorded some ranges file-by-file.  An owner may later
    seal the *whole* unchanged range for retirement.  Consolidating those
    rows is administrative only: the exact disposition still drives removal.
    """

    target, relative = capacity_ledger.capacity_object_path(root, candidate["path"])
    prefix = relative + "/"
    entries = [
        item for item in ledger["objects"]
        if item.get("path") == relative or item.get("path", "").startswith(prefix)
    ]
    expected = {
        "path": relative, "class": "rebuildable_payload",
        "bytes": candidate["bytes"], "status": "ready", "pin": False,
        "owner": candidate["owner_hint"], "disposition": candidate["disposition"],
    }
    if len(entries) == 1 and entries[0] == expected:
        return None
    # The original PA-only bridge remains strict.  Generic ranges may be
    # represented by one writing directory or by its complete writing-file
    # inventory, but never by a partial, pinned, or live-consumed range.
    if (
        len(entries) == 1
        and entries[0].get("class") == "published_cache"
        and entries[0].get("status") == "writing"
        and entries[0].get("recovery_reason") == "legacy_pa_cache_missing_owner_transaction"
        and entries[0].get("owner") == candidate["owner_hint"]
        and entries[0].get("identity", "").upper() == candidate["disposition"]["generation"]
        and entries[0].get("bytes") == candidate["bytes"]
    ):
        capacity_ledger._assert_unleased(root, target)
    else:
        if not entries or any(
            item.get("class") != "rebuildable_payload"
            or item.get("status") != "writing"
            or item.get("pin") is not False
            or item.get("owner") != candidate["owner_hint"]
            or item.get("disposition")
            for item in entries
        ):
            raise ValueError("owner disposition conflicts with the current managed writing range")
        active_paths = {item["path"] for item in entries}
        recorded_bytes = sum(int(item["bytes"]) for item in entries)
        if recorded_bytes != candidate["bytes"] and not candidate["explicit_user_abandonment"]:
            raise ValueError("owner disposition bytes differ from managed writing range")
        for item in entries:
            for consumer in item.get("consumers", []):
                if consumer not in active_paths and not any(
                    consumer == approved or consumer.startswith(approved + "/")
                    for approved in approved_paths
                ):
                    consumer_entry = next(
                        (candidate for candidate in ledger["objects"]
                         if candidate.get("path") == consumer), None,
                    )
                    if not (
                        candidate["explicit_user_abandonment"]
                        and consumer_entry is not None
                        and consumer_entry.get("status") in {"writing", "retired"}
                    ):
                        raise ValueError("owner disposition has an external resident consumer")
                    capacity_ledger._assert_unleased(root, root / consumer)
        capacity_ledger._assert_unleased(root, target)
    retired_paths = {item["path"] for item in entries}
    ledger["objects"] = [
        item for item in ledger["objects"] if item.get("path") not in retired_paths
    ] + [expected]
    if 'recorded_bytes' in locals() and recorded_bytes != candidate["bytes"]:
        ledger["resident_bytes"] += candidate["bytes"] - recorded_bytes
    return {"path": relative, "bytes": candidate["bytes"]}


def _activate_partial_candidate(
    root: Path, ledger: dict[str, Any], candidate: dict[str, Any],
) -> dict[str, Any] | None:
    """Mark only sealed heavy file ranges for the existing partial executor."""

    target, relative = capacity_ledger.capacity_object_path(root, candidate["path"])
    owner, _ = _run_target(relative)
    by_path = {str(item["path"]): item for item in ledger["objects"]}
    changed = False
    for record in candidate["disposition"]["files"]:
        path = _regular_target_file(target, str(record["path"]))
        file_relative = capacity_ledger.capacity_object_path(root, path)[1]
        entry = by_path.get(file_relative)
        if entry is None:
            raise ValueError("owner disposition partial file is no longer registered")
        if entry.get("status") == "retired":
            continue
        if (
            not path.is_file()
            or path.stat().st_size != int(record["bytes"])
            or entry.get("class") != "rebuildable_payload"
            or entry.get("status") != "writing"
            or entry.get("owner") != owner
            or entry.get("pin") is not False
            or entry.get("disposition")
            or entry.get("recovery_reason") not in {
                "structured_nonterminal_run_reference", "run_contract_missing_or_invalid",
            }
            or classify_file(path, bytes_count=int(entry["bytes"])) not in HEAVY_RETENTION_ROLES
            or partial_retirement_is_protected(root, ledger, entry, path)
            or recorded_heavy_identity(target, path, int(entry["bytes"])) is None
        ):
            raise ValueError("owner disposition partial file is no longer eligible")
        if entry.get("recovery_task") != "explicit_user_authorized_abandonment":
            entry["recovery_task"] = "explicit_user_authorized_abandonment"
            changed = True
    return {
        "path": relative,
        "bytes": candidate["bytes"],
    } if changed else None


def activate_owner_dispositions(root: Path) -> dict[str, Any]:
    """Bind sealed owner decisions into the existing retirement path.

    It never discovers candidates or infers owner authority.  Maintenance
    consumes an exact owner-provided disposition before it plans deletion.
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
                if raw.get("scope") == "partial_run_heavy_files":
                    continue
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
        approved_paths = {
            candidate["path"] for _, candidate in approved if not candidate["partial_run"]
        }
        for _, candidate in approved:
            if candidate["partial_run"]:
                activated_entry = _activate_partial_candidate(root, ledger, candidate)
            else:
                activated_entry = _activate_candidate(
                    root, ledger, candidate, approved_paths=approved_paths,
                )
            if activated_entry is not None:
                activated.append(activated_entry)
        if activated:
            write_json_atomic(capacity_ledger.resolve_ledger_path(root), ledger)
    return {
        "activated_count": len(activated),
        "activated_bytes": sum(item["bytes"] for item in activated),
        "archived_document_count": archived_count,
    }


def main(argv: list[str] | None = None) -> int:
    """Expose only the owner-authoring step; maintenance remains separate."""

    parser = argparse.ArgumentParser(
        description="Seal one registered abandoned project run for owner maintenance.",
    )
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--target-path", required=True)
    parser.add_argument("--authority-evidence-path", required=True)
    arguments = parser.parse_args(argv)
    print(json.dumps(author_owner_disposition(
        arguments.workspace_root,
        target_path=arguments.target_path,
        authority_evidence_path=arguments.authority_evidence_path,
    ), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
