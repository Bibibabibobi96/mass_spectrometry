"""Governed retirement of superseded ``solver_review`` native payloads.

The original run manifest remains immutable historical evidence.  A completed
retirement receipt becomes the only valid verifier for the reduced run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common.contracts.recorded_file_removal import remove_recorded_files, write_json_atomic as _atomic_json
from common.contracts.file_identity import file_sha256
from common.contracts.artifact_retention import classify_file, validate_retention
from common.contracts import capacity_protection as protection
from common.contracts.verify_run_manifest import record_path, verify_record

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


def _under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RetirementError(f"path escapes governed root: {path}") from exc
    return resolved


def _load_run(
    run: Path, *, allowed_statuses: Iterable[str] = ("success",), label: str = "run",
) -> dict[str, Any]:
    required = {name: _json(run / name) for name in ("run_config.json", "summary.json", "run_manifest.json")}
    config, summary, manifest = required.values()
    run_id = run.name
    if config.get("run_id") != run_id or manifest.get("run_id") != run_id:
        raise RetirementError(f"run identity mismatch: {run}")
    if summary.get("run_id") not in {None, run_id}:
        raise RetirementError(f"summary run identity mismatch: {run}")
    allowed = set(allowed_statuses)
    manifest_status = manifest.get("status")
    summary_status = summary.get("status")
    if manifest_status not in allowed or summary_status != manifest_status:
        expected = "/".join(sorted(allowed))
        raise RetirementError(
            f"{label} is not a complete {expected} run: {run_id} "
            f"(manifest={manifest_status!r}, summary={summary_status!r})"
        )
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


def _manifest_records(
    run: dict[str, Any], *, retired_paths: Iterable[Path] = (),
) -> dict[Path, dict[str, Any]]:
    """Verify every recorded identity, except receipt-bound partial removals."""
    result: dict[Path, dict[str, Any]] = {}
    retired = set(retired_paths)
    manifest = run["manifest"]
    entries: list[tuple[str, dict[str, Any]]] = [("run_config", manifest.get("run_config", {}))]
    entries.extend((f"input:{name}", record) for name, record in manifest.get("inputs", {}).items())
    entries.extend((f"output:{index}", record) for index, record in enumerate(manifest.get("outputs", [])))
    for role, record in entries:
        if not isinstance(record, dict) or record.get("exists") is not True:
            raise RetirementError(f"invalid manifest record: {role}")
        try:
            path = record_path(record, base_dir=run["dir"])
            if path not in retired:
                verify_record(role, record, base_dir=run["dir"])
        except (AssertionError, KeyError, OSError) as exc:
            raise RetirementError(f"run evidence identity differs: {role}: {exc}") from exc
        result[path] = {"manifest_role": role, "bytes": record.get("bytes"), "sha256": record.get("sha256")}
    if record_path(manifest["run_config"], base_dir=run["dir"]) != run["dir"] / "run_config.json":
        raise RetirementError("manifest does not bind the local run config")
    if run["dir"] / "summary.json" not in result:
        raise RetirementError("manifest does not bind the local summary")
    def configured_paths(value: Any, *, name: str) -> list[Path]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [record_path({"path": value}, base_dir=run["dir"])]
        if isinstance(value, (list, tuple)):
            return [
                path for index, member in enumerate(value)
                for path in configured_paths(member, name=f"{name}[{index}]")
            ]
        if isinstance(value, dict):
            return [
                path for key, member in value.items()
                for path in configured_paths(member, name=f"{name}.{key}")
            ]
        raise RetirementError(f"configured input has an invalid shape: {name}")

    def is_bound_path(configured: Path, recorded: Path) -> bool:
        if configured == recorded:
            return True
        try:
            relative = recorded.relative_to(run["dir"])
        except ValueError:
            return False
        # Short execution aliases can disappear after publication.  Accept
        # their durable artifact copy only when the role record is inside this
        # run and the complete multi-component relative suffix agrees.  An
        # existing divergent source remains ambiguous and fails closed.
        return (
            not configured.exists()
            and len(relative.parts) >= 2
            and tuple(part.lower() for part in configured.parts[-len(relative.parts):])
            == tuple(part.lower() for part in relative.parts)
        )

    for name, configured_value in run["config"].get("inputs", {}).items():
        paths = configured_paths(configured_value, name=name)
        if isinstance(configured_value, str) and configured_value:
            record = manifest.get("inputs", {}).get(name)
            if (
                not isinstance(record, dict)
                or not is_bound_path(
                    paths[0], record_path(record, base_dir=run["dir"])
                )
            ):
                raise RetirementError(f"manifest does not bind configured input: {name}")
        elif any(
            not any(is_bound_path(path, recorded) for recorded in result)
            for path in paths
        ):
            raise RetirementError(f"manifest does not bind configured input collection: {name}")
    return result


def _file_inventory(run: dict[str, Any], *, retired_paths: Iterable[Path] = ()) -> list[dict[str, Any]]:
    root: Path = run["dir"]
    records = _manifest_records(run, retired_paths=retired_paths)
    inventory: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        if path.name == RECEIPT_NAME:
            continue
        record = records.get(path.resolve())
        bytes_count = path.stat().st_size
        manifest_sha = str(record.get("sha256")).upper() if record and record.get("sha256") else None
        actual_sha = file_sha256(path)
        if record and (record["bytes"] != bytes_count or manifest_sha != actual_sha):
            raise RetirementError(f"manifest identity changed: {path}")
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
    input_role_mappings: Iterable[tuple[str, str]],
) -> dict[str, Any]:
    for field in ("project", "mode"):
        if target["config"].get(field) != replacement["config"].get(field):
            raise RetirementError(f"replacement {field} differs")
    required_roles = {role.strip() for role in required_input_roles if role.strip()}
    mappings = [(target_role.strip(), replacement_role.strip())
                for target_role, replacement_role in input_role_mappings]
    if not required_roles and not mappings:
        raise RetirementError(
            "at least one compatibility input role or role mapping is required"
        )
    if any(not target_role or not replacement_role for target_role, replacement_role in mappings):
        raise RetirementError("compatibility input role mappings must name both roles")
    if (
        len({target_role for target_role, _ in mappings}) != len(mappings)
        or len({replacement_role for _, replacement_role in mappings}) != len(mappings)
    ):
        raise RetirementError("compatibility input role mappings must be one-to-one")
    target_roles = set(target["config"].get("inputs", {}))
    replacement_roles = set(replacement["config"].get("inputs", {}))
    missing_target = required_roles - target_roles
    missing_replacement = required_roles - replacement_roles
    if missing_target or missing_replacement:
        raise RetirementError(
            f"three-component geometry identity roles missing: target={sorted(missing_target)}, "
            f"replacement={sorted(missing_replacement)}"
        )
    verified_mappings: list[dict[str, Any]] = []
    for target_role, replacement_role in mappings:
        if target_role not in target_roles or replacement_role not in replacement_roles:
            raise RetirementError(
                "compatibility input mapping roles missing: "
                f"target={target_role!r}, replacement={replacement_role!r}"
            )
        target_record = target["manifest"].get("inputs", {}).get(target_role)
        replacement_record = replacement["manifest"].get("inputs", {}).get(replacement_role)
        if not isinstance(target_record, dict) or not isinstance(replacement_record, dict):
            raise RetirementError(
                "compatibility input mapping lacks manifest records: "
                f"target={target_role!r}, replacement={replacement_role!r}"
            )
        target_identity = (target_record.get("bytes"), str(target_record.get("sha256", "")).upper())
        replacement_identity = (
            replacement_record.get("bytes"),
            str(replacement_record.get("sha256", "")).upper(),
        )
        if target_identity != replacement_identity or not target_identity[1]:
            raise RetirementError(
                "compatibility input mapping identity differs: "
                f"target={target_role!r}, replacement={replacement_role!r}"
            )
        verified_mappings.append({
            "target_role": target_role,
            "replacement_role": replacement_role,
            "bytes": target_identity[0],
            "sha256": target_identity[1],
        })
    return {
        "project": target["config"]["project"],
        "mode": target["config"]["mode"],
        "required_input_roles": sorted(required_roles),
        "replacement_role_superset": required_roles.issubset(replacement_roles),
        "verified_input_role_mappings": verified_mappings,
        "semantics": (
            "same project/mode, caller-declared compatibility input roles, and "
            "identity-equal explicitly mapped legacy roles; "
            "domain-specific topology semantics remain outside the common retirement layer"
        ),
    }


def plan_retirement(
    artifact_root: Path, repository_root: Path, target_run: Path, replacement_run: Path,
    compatibility_assertion: str, compatibility_input_roles: Iterable[str],
    compatibility_input_role_mappings: Iterable[tuple[str, str]] = (),
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
        prior_pending_sha = file_sha256(target_run / RECEIPT_NAME)
    target = _load_run(
        target_run, allowed_statuses=("success", "failed"), label="target"
    )
    replacement = _load_run(replacement_run, label="replacement")
    _manifest_records(replacement)
    if prior_pending_sha and (
        prior["target_manifest"]["sha256"] != file_sha256(target_run / "run_manifest.json")
        or prior["replacement_manifest"]["sha256"] != file_sha256(replacement_run / "run_manifest.json")
        or prior["replacement_run_path"] != str(replacement_run)
    ):
        raise RetirementError("pending retirement manifest identity changed")
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
    leases = protection.load_capacity_protection_leases(artifact_root)
    if protection.path_is_protected(target_run, leases["protected_paths"]):
        raise RetirementError("target is covered by an active capacity protection lease")
    topology = _topology_compatible(
        target, replacement, compatibility_input_roles,
        compatibility_input_role_mappings,
    )
    inventory = _file_inventory(
        target, retired_paths=[_under(target_run / item["path"], target_run) for item in prior_removed_missing],
    )
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
        "artifact_root": str(artifact_root),
        "repository_root": str(repository_root),
        "compatibility_assertion": compatibility_assertion.strip(),
        "compatibility_checks": topology,
        "target_terminal_status": target["manifest"]["status"],
        "target_manifest": {"bytes": (target_run / "run_manifest.json").stat().st_size, "sha256": file_sha256(target_run / "run_manifest.json")},
        "replacement_manifest": {"bytes": (replacement_run / "run_manifest.json").stat().st_size, "sha256": file_sha256(replacement_run / "run_manifest.json")},
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
    try:
        artifact_root = Path(plan["artifact_root"]).resolve()
        repository_root = Path(plan["repository_root"]).resolve()
        target = _under(Path(plan["target_run_path"]), artifact_root)
        replacement = _under(Path(plan["replacement_run_path"]), artifact_root)
    except (KeyError, TypeError, ValueError) as exc:
        raise RetirementError("retirement plan lacks governed root identity") from exc
    for label, path in (("target", target), ("replacement", replacement)):
        if file_sha256(path / "run_manifest.json") != plan[f"{label}_manifest"]["sha256"]:
            raise RetirementError(f"{label} run manifest changed before apply")
    replacement_state = _load_run(replacement, label="replacement")
    _manifest_records(replacement_state)
    target_state = _load_run(
        target, allowed_statuses=("success", "failed"), label="target"
    )
    if plan.get("target_terminal_status") != target_state["manifest"]["status"]:
        raise RetirementError("target terminal status changed before apply")
    if _recorded_at(replacement_state) <= _recorded_at(target_state):
        raise RetirementError("replacement is not newer than target before apply")
    checks = plan.get("compatibility_checks")
    if not isinstance(checks, dict):
        raise RetirementError("retirement plan lacks compatibility checks")
    mapped = checks.get("verified_input_role_mappings", [])
    if not isinstance(mapped, list) or any(not isinstance(item, dict) for item in mapped):
        raise RetirementError("retirement plan compatibility mappings are invalid")
    refreshed_topology = _topology_compatible(
        target_state, replacement_state,
        checks.get("required_input_roles", ()),
        [
            (str(item.get("target_role", "")), str(item.get("replacement_role", "")))
            for item in mapped
        ],
    )
    if refreshed_topology != checks:
        raise RetirementError("retirement compatibility changed before apply")
    document_refs = _git_document_references(repository_root, target.name)
    downstream_refs = _downstream_references(artifact_root, target, target.name)
    if document_refs or downstream_refs:
        raise RetirementError(
            f"target gained active references before apply: "
            f"git_documents={document_refs}, downstream={downstream_refs}"
        )
    leases = protection.load_capacity_protection_leases(artifact_root)
    if protection.path_is_protected(target, leases["protected_paths"]):
        raise RetirementError(
            "target gained an active capacity protection lease before apply"
        )
    _file_inventory(
        target_state, retired_paths=[
            _under(target / item["path"], target)
            for item in plan["removed_files"] if item.get("already_removed_before_resume")
        ],
    )
    receipt_path = target / RECEIPT_NAME
    pending = {
        **plan,
        "role": "solver_review_retirement_receipt",
        "lifecycle_status": "retirement_pending",
        "started_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "apply_capacity_protection_audit": leases["audit"],
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
            try:
                for _ in remove_recorded_files(target, [item]):
                    pass
            except ValueError as exc:
                raise RetirementError(str(exc)) from exc
            removed_bytes += item["bytes"]
        complete = {
            **pending,
            "lifecycle_status": "superseded_payload_retired",
            "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "removed_bytes": removed_bytes,
            "bytes_released_this_apply": plan["bytes_to_release"],
            "verification_semantics": (
                "The immutable original run manifest describes the pre-retirement terminal run and is intentionally no "
                "longer complete on disk. Consumers must reject it and use this receipt verifier for historical "
                "provenance only."
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
    if file_sha256(run_dir / "run_manifest.json") != receipt["target_manifest"]["sha256"]:
        raise RetirementError("original run manifest changed")
    # Receipts written before failed-target retirement existed can only have
    # described successful targets, so preserve their verification contract.
    target_status = receipt.get("target_terminal_status", "success")
    if target_status not in {"success", "failed"}:
        raise RetirementError("retirement target terminal status is invalid")
    if (
        _json(run_dir / "run_manifest.json").get("status") != target_status
        or _json(run_dir / "summary.json").get("status") != target_status
    ):
        raise RetirementError("retirement target terminal status differs")
    replacement = Path(receipt["replacement_run_path"])
    _manifest_records(_load_run(replacement, label="replacement"))
    if file_sha256(replacement / "run_manifest.json") != receipt["replacement_manifest"]["sha256"]:
        raise RetirementError("replacement run manifest changed")
    for item in receipt["removed_files"]:
        if (run_dir / item["path"]).exists():
            raise RetirementError(f"retired heavy payload reappeared: {item['path']}")
    for item in receipt["preserved_files"]:
        path = run_dir / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or file_sha256(path) != item["sha256"]:
            raise RetirementError(f"preserved evidence identity differs: {item['path']}")
    return {
        "schema_version": 1,
        "role": "solver_review_retirement_verification",
        "status": "PASS",
        "run_id": run_dir.name,
        "target_terminal_status": target_status,
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
    parser.add_argument(
        "--compatibility-input-role-map", action="append", default=[],
        metavar="TARGET_ROLE=REPLACEMENT_ROLE",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_retirement(args.verify.resolve())
        else:
            if not all((args.artifact_root, args.repository_root, args.target_run, args.replacement_run, args.compatibility_assertion)):
                parser.error("plan/apply requires artifact root, repository root, target, replacement, and compatibility assertion")
            compatibility_roles: list[str] = []
            mapping_values = list(args.compatibility_input_role_map)
            for value in args.compatibility_input_role:
                # The PowerShell lease-owning wrapper predates the dedicated
                # map switch and forwards this repeatable option.  Accept the
                # same explicit TARGET=REPLACEMENT syntax here so mapped-only
                # retirements still use that governed apply entrypoint.
                if "=" in value:
                    mapping_values.append(value)
                else:
                    compatibility_roles.append(value)
            mappings: list[tuple[str, str]] = []
            for value in mapping_values:
                if "=" not in value:
                    raise RetirementError(
                        "compatibility input role mapping must use TARGET_ROLE=REPLACEMENT_ROLE"
                    )
                target_role, replacement_role = value.split("=", 1)
                if not target_role.strip() or not replacement_role.strip():
                    raise RetirementError(
                        "compatibility input role mapping must name both roles"
                    )
                mappings.append((target_role, replacement_role))
            result = plan_retirement(
                args.artifact_root, args.repository_root, args.target_run,
                args.replacement_run, args.compatibility_assertion,
                compatibility_roles,
                mappings,
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
