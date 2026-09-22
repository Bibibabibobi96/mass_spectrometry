"""Owner-authorized retirement of explicit children in calibrated source scratch.

This maintenance entry point never treats the ``repository_scratch`` external
scope itself as a deletion target.  Approval must name exact normalized child
directories; the ledger retains the root scope and only decrements its bytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any

from common.contracts import capacity_ledger
from common.contracts.file_identity import file_sha256
from common.contracts.recorded_file_removal import remove_recorded_files, write_json_atomic

RECEIPTS = Path("common") / "capacity_disposal_receipts"
ROLE = "historical_source_scratch_disposition"


def _normalized_child(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("retirement target must be a nonempty normalized relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or Path(value).is_absolute() or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != value):
        raise ValueError("retirement target must be an exact normalized relative path")
    return path.as_posix()


def _overlaps(left: str, right: str) -> bool:
    a, b = PurePosixPath(left).parts, PurePosixPath(right).parts
    return a[:len(b)] == b or b[:len(a)] == a


def _target_path(source: Path, relative: str, *, require_exists: bool) -> Path:
    target = source.joinpath(*PurePosixPath(relative).parts)
    try:
        target.relative_to(source)
    except ValueError as exc:
        raise ValueError("retirement target escapes source scratch") from exc
    if target.is_symlink():
        raise ValueError("retirement target is a symbolic link")
    if require_exists and (not target.exists() or not target.is_dir()):
        raise ValueError("retirement target must be one existing regular directory")
    if target.exists():
        try:
            target.resolve().relative_to(source)
        except ValueError as exc:
            raise ValueError("retirement target resolves outside source scratch") from exc
    return target


def _assert_regular_components(source: Path, relative: str) -> Path:
    """Reject a symlink inserted between planning and an individual removal."""
    current = source
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("source scratch disposition encountered a symbolic link")
    try:
        current.resolve(strict=False).relative_to(source)
    except ValueError as exc:
        raise ValueError("source scratch disposition path escapes source scratch") from exc
    return current


def _approved_targets(document: dict[str, Any], source: Path, *, require_exists: bool) -> list[str]:
    values = document.get("retirement_targets")
    if not isinstance(values, list) or not values:
        raise ValueError("authorization evidence must name retirement_targets")
    targets = [_normalized_child(value) for value in values]
    if len(set(targets)) != len(targets):
        raise ValueError("authorization evidence repeats a retirement target")
    for index, target in enumerate(targets):
        if any(_overlaps(target, other) for other in targets[:index]):
            raise ValueError("authorization retirement targets overlap")
        _target_path(source, target, require_exists=require_exists)
    return sorted(targets)


def _assert_unprotected(document: dict[str, Any], targets: list[str]) -> None:
    values = document.get("protected_paths", [])
    if not isinstance(values, list):
        raise ValueError("authorization protected_paths must be a list")
    protected = [_normalized_child(value) for value in values]
    if any(_overlaps(target, protected_path) for target in targets for protected_path in protected):
        raise ValueError("authorization evidence protects a retirement target")


def _authorization(path: Path, digest: str, owner: str, source: Path, *, require_targets: bool) -> tuple[dict[str, Any], list[str]]:
    if not path.is_file() or path.is_symlink() or file_sha256(path).upper() != digest.upper():
        raise ValueError("authorization evidence identity differs")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError("authorization evidence is unreadable") from exc
    if (not isinstance(document, dict) or document.get("status") != "approved"
            or document.get("owner") != owner or document.get("retirement_authorized") is not True):
        raise ValueError("authorization evidence lacks approved owner retirement authority")
    if Path(str(document.get("source_root", ""))).resolve(strict=False) != source:
        raise ValueError("authorization source root differs")
    consumers = document.get("active_consumers", [])
    if not isinstance(consumers, list) or consumers:
        raise ValueError("authorization evidence has active or foreign consumers")
    targets = _approved_targets(document, source, require_exists=require_targets)
    _assert_unprotected(document, targets)
    return document, targets


def _inventory(source: Path, targets: list[str]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for target_name in targets:
        target = _target_path(source, target_name, require_exists=True)
        for item in sorted(target.rglob("*"), key=lambda value: value.as_posix()):
            if item.is_symlink():
                raise ValueError("source scratch inventory contains a symbolic link")
            if item.is_file():
                files.append({"target": target_name, "path": item.relative_to(source).as_posix(),
                              "bytes": item.stat().st_size, "sha256": file_sha256(item)})
    return files


def _external_scope(root: Path, source: Path) -> dict[str, Any]:
    ledger = capacity_ledger.load_capacity_ledger(root)
    if ledger is None:
        raise ValueError("calibrated capacity ledger is required")
    external = next((item for item in ledger["external_scopes"] if item["role"] == "repository_scratch"), None)
    if external is None or external["path"] != str(source):
        raise ValueError("source scratch root is not the calibrated repository_scratch scope")
    return external


def plan(artifact_root: Path, *, source_root: Path, owner: str, evidence: Path, evidence_sha256: str) -> dict[str, Any]:
    root, source = artifact_root.resolve(strict=False), source_root.resolve(strict=False)
    if not source.is_dir() or source.is_symlink():
        raise ValueError("source scratch root must be one regular directory")
    if not owner.strip():
        raise ValueError("source scratch owner is required")
    _, targets = _authorization(evidence, evidence_sha256, owner, source, require_targets=True)
    external = _external_scope(root, source)
    files = _inventory(source, targets)
    total, scope_bytes = sum(int(item["bytes"]) for item in files), int(external["bytes"])
    if total > scope_bytes:
        raise ValueError("authorized source scratch targets exceed calibrated external scope")
    did = file_sha256(evidence).upper()
    receipt = root / RECEIPTS / f"source_scratch_{did}.json"
    return {"schema_version": 2, "role": ROLE, "status": "planned", "owner": owner,
            "artifact_root": str(root), "source_root": str(source), "scope_role": "repository_scratch",
            "targets": targets, "evidence": str(evidence.resolve()), "evidence_sha256": did,
            "files": files, "bytes": total, "external_scope_bytes_before": scope_bytes,
            "external_scope_bytes_after": scope_bytes - total, "receipt": str(receipt)}


def _immutable_fields(plan_: dict[str, Any]) -> tuple[str, ...]:
    return ("schema_version", "role", "owner", "artifact_root", "source_root", "scope_role", "targets",
            "evidence", "evidence_sha256", "files", "bytes", "external_scope_bytes_before",
            "external_scope_bytes_after", "receipt")


def _load_or_create_receipt(plan_: dict[str, Any]) -> dict[str, Any]:
    receipt = Path(plan_["receipt"])
    if receipt.exists():
        prior = json.loads(receipt.read_text(encoding="utf-8-sig"))
        if not isinstance(prior, dict) or any(prior.get(key) != plan_.get(key) for key in _immutable_fields(plan_)):
            raise ValueError("existing source scratch disposition differs")
        return prior
    pending = {**plan_, "status": "pending", "removal_progress": []}
    write_json_atomic(receipt, pending)
    return pending


def _revalidate_apply_authority(receipt: dict[str, Any]) -> None:
    source = Path(receipt["source_root"])
    _, targets = _authorization(Path(receipt["evidence"]), receipt["evidence_sha256"], receipt["owner"], source, require_targets=False)
    if targets != receipt["targets"]:
        raise ValueError("authorization retirement targets differ from pending disposition")


def _remove_empty_target_tree(source: Path, target_name: str) -> None:
    target = _target_path(source, target_name, require_exists=False)
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError("source scratch target changed into a non-directory")
    for item in sorted(target.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if item.is_symlink():
            raise ValueError("source scratch disposition encountered a symbolic link")
        if item.is_dir():
            item.rmdir()
    target.rmdir()


def _update_external_scope(receipt: dict[str, Any]) -> None:
    root, source = Path(receipt["artifact_root"]), Path(receipt["source_root"])
    before, after = int(receipt["external_scope_bytes_before"]), int(receipt["external_scope_bytes_after"])
    observed = int(_external_scope(root, source)["bytes"])
    if observed == after:
        return
    if observed != before:
        raise ValueError("external scope record differs from pending source scratch disposition")
    capacity_ledger.update_external_scope_bytes(root, role="repository_scratch", path=source,
                                                expected_bytes=before, new_bytes=after)


def apply(plan_: dict[str, Any]) -> dict[str, Any]:
    receipt = _load_or_create_receipt(plan_)
    if receipt.get("status") == "complete":
        return receipt
    if receipt.get("status") != "pending":
        raise ValueError("source scratch disposition receipt is not resumable")
    _revalidate_apply_authority(receipt)
    source = Path(receipt["source_root"])
    if not source.is_dir() or source.is_symlink():
        raise ValueError("source scratch root is not a regular directory")
    receipt_path = Path(receipt["receipt"])
    completed = {item["path"] for item in receipt.get("removal_progress", [])}
    for record in receipt["files"]:
        relative = record["path"]
        _assert_regular_components(source, relative)
        path = source / Path(*PurePosixPath(relative).parts)
        if relative in completed:
            if path.exists():
                raise ValueError("source scratch completed removal reappeared")
            continue
        if path.exists():
            if len(list(remove_recorded_files(source, [record]))) != 1:
                raise ValueError("source scratch recorded removal did not remove its file")
            outcome = "removed"
        else:
            outcome = "missing_at_resume"  # crash after unlink, before receipt refresh
        receipt["removal_progress"].append({"path": relative, "outcome": outcome})
        write_json_atomic(receipt_path, receipt)
    for target in receipt["targets"]:
        _remove_empty_target_tree(source, target)
    _update_external_scope(receipt)
    complete = {**receipt, "status": "complete"}
    write_json_atomic(receipt_path, complete)
    return complete


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    disposition = plan(args.artifact_root, source_root=args.source_root, owner=args.owner,
                       evidence=args.evidence, evidence_sha256=args.evidence_sha256)
    print(json.dumps(apply(disposition) if args.apply else disposition, indent=2))


if __name__ == "__main__":
    main()
