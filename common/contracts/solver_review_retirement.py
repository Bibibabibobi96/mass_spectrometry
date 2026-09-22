"""Governed retirement of superseded ``solver_review`` native payloads.

The original run manifest remains immutable historical evidence.  A completed
retirement receipt becomes the only valid verifier for the reduced run.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
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
TERMINAL_STATUSES = {
    "success", "completed", "failed", "interrupted", "cancelled", "aborted",
}
LEGACY_INITIALIZATION_SUMMARY = {
    "schema_version": 1,
    "role": "run_package_initialization_summary",
    "status": "checkpoint",
    "reason": "Run package initialized; task-specific inputs are not frozen yet.",
}


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
    allow_legacy_initialization_summary: bool = False,
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
    legacy_initialization_summary = (
        allow_legacy_initialization_summary
        and manifest_status == "success"
        and summary == LEGACY_INITIALIZATION_SUMMARY
    )
    if manifest_status not in allowed or (
        summary_status != manifest_status and not legacy_initialization_summary
    ):
        expected = "/".join(sorted(allowed))
        raise RetirementError(
            f"{label} is not a complete {expected} run: {run_id} "
            f"(manifest={manifest_status!r}, summary={summary_status!r})"
        )
    if config.get("formal_gate_passed") is not False or manifest.get("formal_eligible") is not False:
        raise RetirementError(f"Formal or ambiguously non-Formal run cannot be retired: {run_id}")
    try:
        retention = validate_retention(config.get("artifact_retention"))
        manifest_retention = validate_retention(manifest.get("artifact_retention"))
    except ValueError as exc:
        raise RetirementError(f"invalid solver_review retention: {run_id}: {exc}") from exc
    if retention.class_id != "solver_review":
        raise RetirementError(f"run is not solver_review: {run_id}")
    if manifest_retention.class_id != "solver_review":
        raise RetirementError(f"manifest retention differs: {run_id}")
    return {
        "dir": run,
        "config": config,
        "summary": summary,
        "manifest": manifest,
        "legacy_initialization_summary": legacy_initialization_summary,
    }


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


def structured_target_references(value: Any, target: Path, run_id: str) -> set[str]:
    """Return exact structured references below ``target``.

    The empty string denotes the target run as a whole.  Other values are
    normalized target-relative paths.  Arbitrary prose and substring matches
    are deliberately ignored; callers decide whether a referenced file is in
    the payload they propose to remove or in the light evidence they retain.
    """

    if isinstance(value, dict):
        return set().union(
            *(structured_target_references(member, target, run_id) for member in value.values())
        ) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(
            *(structured_target_references(member, target, run_id) for member in value)
        ) if value else set()
    if not isinstance(value, str):
        return set()
    raw = value.strip().replace("\\", "/")
    if not raw:
        return set()
    normalized = posixpath.normpath(raw).rstrip("/").casefold()
    normalized_run_id = run_id.casefold()
    target_path = target.resolve().as_posix().rstrip("/").casefold()
    if normalized in {normalized_run_id, target_path} or normalized.endswith(
        f"/runs/{normalized_run_id}"
    ):
        return {""}
    prefixes = (f"{target_path}/", f"/runs/{normalized_run_id}/")
    for prefix in prefixes:
        if prefix == prefixes[1]:
            marker = normalized.rfind(prefix)
            if marker < 0:
                continue
            relative = normalized[marker + len(prefix):]
        elif normalized.startswith(prefix):
            relative = normalized[len(prefix):]
        else:
            continue
        if relative and relative != "." and not relative.startswith("../"):
            return {relative}
    return set()


def _downstream_references(
    artifact_root: Path, target: Path, run_id: str, *,
    removable_paths: Iterable[str] = (), preserved_paths: Iterable[str] = (),
) -> dict[str, list[dict[str, str]]]:
    references: dict[str, list[dict[str, str]]] = {
        "active": [],
        "active_preserved": [],
        "historical": [],
        "corrupt_run_config_reference_unavailable": [],
    }
    removable = {posixpath.normpath(item).casefold() for item in removable_paths}
    preserved = {posixpath.normpath(item).casefold() for item in preserved_paths}
    for run_dir in artifact_root.glob("projects/*/runs/*"):
        if not run_dir.is_dir() or run_dir.resolve() == target.resolve():
            continue
        path = run_dir / "run_config.json"
        manifest_path = run_dir / "run_manifest.json"
        manifest: dict[str, Any] | None = None
        try:
            manifest = _json(manifest_path)
            manifest_status = str(manifest.get("status", "")).lower()
            if manifest.get("run_id") not in {None, run_dir.name}:
                manifest_status = "invalid_or_unreadable"
        except RetirementError:
            manifest_status = "missing_or_unreadable"
        category = (
            "historical" if manifest_status in TERMINAL_STATUSES else "active"
        )
        config: dict[str, Any] | None = None
        if path.exists():
            try:
                config = _json(path)
            except RetirementError:
                # A non-terminal run with a damaged run_config must not pin
                # every retirement target merely because its path exists.
                # First use the valid manifest's local run_config record to
                # distinguish content corruption from an unreadable parser.
                manifest_record = manifest.get("run_config") if manifest else None
                identity_matches = False
                identity_checkable = False
                if isinstance(manifest_record, dict):
                    try:
                        recorded_path = record_path(manifest_record, base_dir=run_dir)
                        identity_checkable = recorded_path == path
                        if identity_checkable:
                            verify_record(
                                "downstream run_config",
                                manifest_record,
                                base_dir=run_dir,
                            )
                            identity_matches = True
                    except (AssertionError, KeyError, OSError, TypeError, ValueError):
                        identity_matches = False
                if category == "active" and identity_checkable and not identity_matches:
                    references["corrupt_run_config_reference_unavailable"].append(
                        {
                            "run_config_path": str(path),
                            "manifest_status": manifest_status,
                            "reason": "corrupt_run_config_reference_unavailable",
                        }
                    )
                else:
                    references[category].append(
                        {
                            "run_config_path": str(path),
                            "manifest_status": manifest_status,
                            "reason": "run_config_unreadable_reference_uncertain",
                        }
                    )
        configured = set()
        if config is not None:
            configured.update(structured_target_references(config, target, run_id))
        if manifest is not None:
            configured.update(structured_target_references(manifest, target, run_id))
        for relative in sorted(configured):
            item = {
                "run_config_path": str(path),
                "manifest_status": manifest_status,
                "reason": "configured_target_run_dependency" if not relative else "configured_target_file_dependency",
            }
            if relative:
                item["path"] = relative
            if category == "historical":
                references[category].append(item)
            elif not relative or relative in removable:
                references["active"].append(item)
            elif relative in preserved:
                references["active_preserved"].append(item)
    for category in references:
        references[category].sort(key=lambda item: (item["run_config_path"], item.get("path", "")))
    return references


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
    if (
        run["dir"] / "summary.json" not in result
        and not run.get("legacy_initialization_summary")
    ):
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
        target_run,
        allowed_statuses=("success", "failed"),
        label="target",
        allow_legacy_initialization_summary=True,
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
    downstream_refs = _downstream_references(
        artifact_root,
        target_run,
        target_run.name,
        removable_paths=(item["path"] for item in removed),
        preserved_paths=(item["path"] for item in preserved),
    )
    if downstream_refs["active"]:
        raise RetirementError(
            "target still has active references in downstream run_config: "
            f"{downstream_refs['active']}"
        )
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
        "target_legacy_initialization_summary": target[
            "legacy_initialization_summary"
        ],
        "target_manifest": {"bytes": (target_run / "run_manifest.json").stat().st_size, "sha256": file_sha256(target_run / "run_manifest.json")},
        "replacement_manifest": {"bytes": (replacement_run / "run_manifest.json").stat().st_size, "sha256": file_sha256(replacement_run / "run_manifest.json")},
        "original_file_inventory": inventory,
        "removed_files": removed,
        "preserved_files": preserved,
        "bytes_to_release": sum(item["bytes"] for item in removed_current),
        "total_retired_bytes": sum(item["bytes"] for item in removed),
        "historical_document_references": document_refs,
        "historical_downstream_references": downstream_refs["historical"],
        "active_preserved_file_references": downstream_refs["active_preserved"],
        "corrupt_run_config_reference_unavailable": downstream_refs[
            "corrupt_run_config_reference_unavailable"
        ],
        "capacity_protection_audit": leases["audit"],
        "recovery_of_pending_receipt_sha256": prior_pending_sha,
    }


def apply_retirement(plan: dict[str, Any]) -> dict[str, Any]:
    if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
        raise RetirementError("apply requires the shared HostExecutionLease")
    try:
        artifact_root = Path(plan["artifact_root"]).resolve()
    except (KeyError, TypeError, ValueError) as exc:
        raise RetirementError("retirement plan lacks governed root identity") from exc
    target = _under(Path(plan["target_run_path"]), artifact_root)
    receipt_path = target / RECEIPT_NAME
    with protection.capacity_decision_lock(artifact_root):
        leases = protection.load_capacity_protection_leases(artifact_root)
        if protection.path_is_protected(target, leases["protected_paths"]):
            raise RetirementError(
                "target gained an active capacity protection lease before apply"
            )
        downstream = _downstream_references(
            artifact_root,
            target,
            target.name,
            removable_paths=(item["path"] for item in plan["removed_files"]),
            preserved_paths=(item["path"] for item in plan["preserved_files"]),
        )
        if downstream["active"]:
            raise RetirementError(
                "target gained active references before retirement decision: "
                f"{downstream['active']}"
            )
        if receipt_path.exists():
            marker = _json(receipt_path)
            if not (
                marker.get("lifecycle_status") == "retirement_pending"
                and marker.get("target_manifest") == plan.get("target_manifest")
                and marker.get("replacement_manifest") == plan.get("replacement_manifest")
            ):
                raise RetirementError("target already has another retirement marker")
        else:
            _atomic_json(
                receipt_path,
                {
                    **plan,
                    "role": "solver_review_retirement_receipt",
                    "status": "preflight_pending",
                    "lifecycle_status": "retirement_pending",
                    "started_at_utc": datetime.now(timezone.utc).isoformat().replace(
                        "+00:00", "Z"
                    ),
                },
            )
    return _apply_retirement_locked(plan)


def _apply_retirement_locked(plan: dict[str, Any]) -> dict[str, Any]:
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
        target,
        allowed_statuses=("success", "failed"),
        label="target",
        allow_legacy_initialization_summary=True,
    )
    if plan.get("target_terminal_status") != target_state["manifest"]["status"]:
        raise RetirementError("target terminal status changed before apply")
    if bool(plan.get("target_legacy_initialization_summary")) != bool(
        target_state["legacy_initialization_summary"]
    ):
        raise RetirementError("target legacy summary state changed before apply")
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
    downstream_refs = _downstream_references(
        artifact_root,
        target,
        target.name,
        removable_paths=(item["path"] for item in plan["removed_files"]),
        preserved_paths=(item["path"] for item in plan["preserved_files"]),
    )
    if downstream_refs["active"]:
        raise RetirementError(
            "target gained active references in downstream run_config before apply: "
            f"{downstream_refs['active']}"
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
        "apply_historical_document_references": document_refs,
        "apply_historical_downstream_references": downstream_refs["historical"],
        "apply_active_preserved_file_references": downstream_refs["active_preserved"],
        "apply_corrupt_run_config_reference_unavailable": downstream_refs[
            "corrupt_run_config_reference_unavailable"
        ],
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
                for _ in remove_recorded_files(
                    target, [item], identities_verified=True
                ):
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
    manifest_status = _json(run_dir / "run_manifest.json").get("status")
    summary = _json(run_dir / "summary.json")
    legacy_initialization_summary = receipt.get(
        "target_legacy_initialization_summary", False
    )
    if not isinstance(legacy_initialization_summary, bool):
        raise RetirementError("retirement target legacy summary flag is invalid")
    if manifest_status != target_status or (
        summary.get("status") != target_status
        and not (
            legacy_initialization_summary
            and target_status == "success"
            and summary == LEGACY_INITIALIZATION_SUMMARY
        )
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
