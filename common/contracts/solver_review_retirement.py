"""Governed retirement of superseded ``solver_review`` native payloads.

The original run manifest remains immutable historical evidence.  A completed
retirement receipt becomes the only valid verifier for the reduced run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common.contracts.artifact_retention import classify_file, validate_retention
from common.contracts.reconcile_artifact_capacity import (
    _load_capacity_protection_leases,
    _protected,
)

RECEIPT_NAME = "solver_review_retirement_receipt.json"
HEAVY_ROLES = {"solver_native_binary", "dense_trajectory"}
class RetirementError(ValueError):
    """One retirement precondition or verification condition failed."""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetirementError(f"unreadable JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RetirementError(f"JSON document must be an object: {path}")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RetirementError(f"path escapes governed root: {path}") from exc
    return resolved


def _load_run(run: Path) -> dict[str, Any]:
    required = {name: _json(run / name) for name in ("run_config.json", "summary.json", "run_manifest.json")}
    config, summary, manifest = required.values()
    run_id = run.name
    if config.get("run_id") != run_id or manifest.get("run_id") != run_id:
        raise RetirementError(f"run identity mismatch: {run}")
    if summary.get("run_id") not in {None, run_id}:
        raise RetirementError(f"summary run identity mismatch: {run}")
    if manifest.get("status") != "success" or summary.get("status") != "success":
        raise RetirementError(f"run is not a complete success: {run_id}")
    if config.get("formal_gate_passed") is not False or manifest.get("formal_eligible") is not False:
        raise RetirementError(f"Formal or ambiguously non-Formal run cannot be retired: {run_id}")
    retention = validate_retention(config.get("artifact_retention"))
    if retention.class_id != "solver_review":
        raise RetirementError(f"run is not solver_review: {run_id}")
    if manifest.get("artifact_retention", {}).get("class") != "solver_review":
        raise RetirementError(f"manifest retention differs: {run_id}")
    return {"dir": run, "config": config, "summary": summary, "manifest": manifest}


def _recorded_at(run: dict[str, Any]) -> datetime:
    text = run["manifest"].get("recorded_at_utc")
    try:
        value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetirementError("manifest recorded_at_utc is invalid") from exc
    if value.tzinfo is None:
        raise RetirementError("manifest recorded_at_utc must be timezone-aware")
    return value.astimezone(timezone.utc)


def _git_document_references(repository: Path, run_id: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repository), "grep", "-l", "-F", "--", run_id, "--", "*.md"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        cwd=repository,
        timeout=30,
    )
    if result.returncode not in {0, 1}:
        raise RetirementError(f"git document reference scan failed: {result.stderr.strip()}")
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def _downstream_references(artifact_root: Path, target: Path, run_id: str) -> list[str]:
    references: list[str] = []
    needle_path = str(target)
    for path in artifact_root.glob("projects/*/runs/*/run_config.json"):
        if path.parent.resolve() == target.resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise RetirementError(f"cannot scan downstream run config: {path}: {exc}") from exc
        if run_id in text or needle_path in text:
            references.append(str(path))
    return sorted(references)


def _manifest_records(run: dict[str, Any]) -> dict[Path, dict[str, Any]]:
    result: dict[Path, dict[str, Any]] = {}
    manifest = run["manifest"]
    entries: list[tuple[str, dict[str, Any]]] = [("run_config", manifest.get("run_config", {}))]
    entries.extend((f"input:{name}", record) for name, record in manifest.get("inputs", {}).items())
    entries.extend((f"output:{index}", record) for index, record in enumerate(manifest.get("outputs", [])))
    for role, record in entries:
        if not isinstance(record, dict) or not record.get("exists"):
            continue
        path = Path(str(record.get("path", ""))).resolve()
        result[path] = {"manifest_role": role, "bytes": record.get("bytes"), "sha256": record.get("sha256")}
    return result


def _file_inventory(run: dict[str, Any]) -> list[dict[str, Any]]:
    root: Path = run["dir"]
    records = _manifest_records(run)
    inventory: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        if path.name == RECEIPT_NAME:
            continue
        record = records.get(path.resolve())
        bytes_count = path.stat().st_size
        manifest_sha = str(record.get("sha256")).upper() if record and record.get("sha256") else None
        actual_sha = _sha(path)
        inventory.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": bytes_count,
            "sha256": actual_sha,
            "manifest_sha256": manifest_sha,
            "manifest_identity_matches": manifest_sha is None or manifest_sha == actual_sha,
            "identity_source": "computed_before_retirement",
            "manifest_role": record.get("manifest_role") if record else None,
            "retention_role": classify_file(path, bytes_count=bytes_count),
        })
    return inventory


def _topology_compatible(
    target: dict[str, Any],
    replacement: dict[str, Any],
    required_input_roles: Iterable[str],
) -> dict[str, Any]:
    for field in ("project", "mode"):
        if target["config"].get(field) != replacement["config"].get(field):
            raise RetirementError(f"replacement {field} differs")
    required_roles = {role.strip() for role in required_input_roles if role.strip()}
    if not required_roles:
        raise RetirementError("at least one compatibility input role is required")
    target_roles = set(target["config"].get("inputs", {}))
    replacement_roles = set(replacement["config"].get("inputs", {}))
    missing_target = required_roles - target_roles
    missing_replacement = required_roles - replacement_roles
    if missing_target or missing_replacement:
        raise RetirementError(
            f"three-component geometry identity roles missing: target={sorted(missing_target)}, "
            f"replacement={sorted(missing_replacement)}"
        )
    return {
        "project": target["config"]["project"],
        "mode": target["config"]["mode"],
        "required_input_roles": sorted(required_roles),
        "replacement_role_superset": required_roles.issubset(replacement_roles),
        "semantics": (
            "same project/mode and caller-declared compatibility input roles; "
            "domain-specific topology semantics remain outside the common retirement layer"
        ),
    }


def plan_retirement(
    artifact_root: Path, repository_root: Path, target_run: Path, replacement_run: Path,
    compatibility_assertion: str, compatibility_input_roles: Iterable[str],
) -> dict[str, Any]:
    artifact_root = artifact_root.resolve()
    repository_root = repository_root.resolve()
    target_run = _under(target_run, artifact_root)
    replacement_run = _under(replacement_run, artifact_root)
    if target_run == replacement_run:
        raise RetirementError("target and replacement must differ")
    if not compatibility_assertion.strip():
        raise RetirementError("a nonempty compatibility assertion is required")
    prior_pending_sha: str | None = None
    prior_removed_missing: list[dict[str, Any]] = []
    if (target_run / RECEIPT_NAME).exists():
        prior = _json(target_run / RECEIPT_NAME)
        if prior.get("lifecycle_status") != "retirement_pending":
            raise RetirementError("target already has a completed retirement receipt")
        prior_removed_missing = [
            {**item, "already_removed_before_resume": True}
            for item in prior.get("removed_files", [])
            if not (target_run / item["path"]).is_file()
        ]
        prior_pending_sha = _sha(target_run / RECEIPT_NAME)
    target = _load_run(target_run)
    replacement = _load_run(replacement_run)
    if _recorded_at(replacement) <= _recorded_at(target):
        raise RetirementError("replacement is not newer than target")
    if target["config"].get("project") != replacement["config"].get("project"):
        raise RetirementError("replacement belongs to another project")
    document_refs = _git_document_references(repository_root, target_run.name)
    downstream_refs = _downstream_references(artifact_root, target_run, target_run.name)
    if document_refs or downstream_refs:
        raise RetirementError(
            f"target still has active references: git_documents={document_refs}, downstream={downstream_refs}"
        )
    leases = _load_capacity_protection_leases(artifact_root)
    if _protected(target_run, leases["protected_paths"]):
        raise RetirementError("target is covered by an active capacity protection lease")
    topology = _topology_compatible(target, replacement, compatibility_input_roles)
    inventory = _file_inventory(target)
    removed_current = [item for item in inventory if item["retention_role"] in HEAVY_ROLES]
    removed = prior_removed_missing + removed_current
    if not removed:
        raise RetirementError("target contains no governed heavy payload")
    preserved = [item for item in inventory if item not in removed]
    return {
        "schema_version": 1,
        "role": "solver_review_retirement_plan",
        "status": "eligible",
        "target_run_id": target_run.name,
        "target_run_path": str(target_run),
        "replacement_run_id": replacement_run.name,
        "replacement_run_path": str(replacement_run),
        "compatibility_assertion": compatibility_assertion.strip(),
        "compatibility_checks": topology,
        "target_manifest": {"bytes": (target_run / "run_manifest.json").stat().st_size, "sha256": _sha(target_run / "run_manifest.json")},
        "replacement_manifest": {"bytes": (replacement_run / "run_manifest.json").stat().st_size, "sha256": _sha(replacement_run / "run_manifest.json")},
        "original_file_inventory": inventory,
        "removed_files": removed,
        "preserved_files": preserved,
        "bytes_to_release": sum(item["bytes"] for item in removed_current),
        "total_retired_bytes": sum(item["bytes"] for item in removed),
        "capacity_protection_audit": leases["audit"],
        "recovery_of_pending_receipt_sha256": prior_pending_sha,
    }


def apply_retirement(plan: dict[str, Any]) -> dict[str, Any]:
    if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
        raise RetirementError("apply requires the shared HostExecutionLease")
    target = Path(plan["target_run_path"])
    receipt_path = target / RECEIPT_NAME
    pending = {
        **plan,
        "role": "solver_review_retirement_receipt",
        "lifecycle_status": "retirement_pending",
        "started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _atomic_json(receipt_path, pending)
    removed_bytes = 0
    try:
        for item in plan["removed_files"]:
            path = _under(target / item["path"], target)
            if item.get("already_removed_before_resume"):
                if path.exists():
                    raise RetirementError(f"previously removed payload reappeared: {item['path']}")
                removed_bytes += item["bytes"]
                continue
            if not path.is_file() or path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
                raise RetirementError(f"heavy payload identity changed before removal: {item['path']}")
            try:
                path.unlink()
            except PermissionError:
                path.chmod(path.stat().st_mode | stat.S_IWRITE)
                path.unlink()
            removed_bytes += item["bytes"]
        complete = {
            **pending,
            "lifecycle_status": "superseded_payload_retired",
            "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "removed_bytes": removed_bytes,
            "bytes_released_this_apply": plan["bytes_to_release"],
            "verification_semantics": (
                "The immutable original run manifest describes the pre-retirement success and is intentionally no longer "
                "complete on disk. Consumers must reject it and use this receipt verifier for historical provenance only."
            ),
        }
        _atomic_json(receipt_path, complete)
        return complete
    except Exception:
        # The pending receipt makes partial deletion explicit and fail-closed.
        raise


def verify_retirement(run_dir: Path) -> dict[str, Any]:
    receipt = _json(run_dir / RECEIPT_NAME)
    if receipt.get("role") != "solver_review_retirement_receipt" or receipt.get("lifecycle_status") != "superseded_payload_retired":
        raise RetirementError("retirement receipt is not complete")
    if receipt.get("target_run_id") != run_dir.name:
        raise RetirementError("retirement target identity differs")
    for name in ("run_config.json", "summary.json", "run_manifest.json"):
        if not (run_dir / name).is_file():
            raise RetirementError(f"required historical record missing: {name}")
    if _sha(run_dir / "run_manifest.json") != receipt["target_manifest"]["sha256"]:
        raise RetirementError("original run manifest changed")
    replacement = Path(receipt["replacement_run_path"])
    _load_run(replacement)
    if _sha(replacement / "run_manifest.json") != receipt["replacement_manifest"]["sha256"]:
        raise RetirementError("replacement run manifest changed")
    for item in receipt["removed_files"]:
        if (run_dir / item["path"]).exists():
            raise RetirementError(f"retired heavy payload reappeared: {item['path']}")
    for item in receipt["preserved_files"]:
        path = run_dir / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
            raise RetirementError(f"preserved evidence identity differs: {item['path']}")
    return {
        "schema_version": 1,
        "role": "solver_review_retirement_verification",
        "status": "PASS",
        "run_id": run_dir.name,
        "replacement_run_id": receipt["replacement_run_id"],
        "removed_bytes": receipt["removed_bytes"],
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--target-run", type=Path)
    parser.add_argument("--replacement-run", type=Path)
    parser.add_argument("--compatibility-assertion")
    parser.add_argument("--compatibility-input-role", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_retirement(args.verify.resolve())
        else:
            if not all((args.artifact_root, args.repository_root, args.target_run, args.replacement_run, args.compatibility_assertion)):
                parser.error("plan/apply requires artifact root, repository root, target, replacement, and compatibility assertion")
            result = plan_retirement(
                args.artifact_root, args.repository_root, args.target_run,
                args.replacement_run, args.compatibility_assertion,
                args.compatibility_input_role,
            )
            if args.apply:
                result = apply_retirement(result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except RetirementError as exc:
        print(json.dumps({"role": "solver_review_retirement_error", "status": "FAIL", "error": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
