"""Plan, verify, relocate, roll back, and prune retired artifact roots.

Legacy run manifests remain byte-for-byte immutable.  Their absolute paths are
resolved through the exact old-root/new-root prefix recorded by this manifest.
All mutating commands verify the complete source inventory before acting.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from common.contracts.artifact_naming import validate_archive_id
    from common.contracts.file_identity import file_sha256
except ModuleNotFoundError:
    from artifact_naming import validate_archive_id
    from file_identity import file_sha256


SCHEMA_VERSION = 2
ROLE = "artifact_identity_migration_manifest"
ARCHIVE_ROLE = "artifact_identity_archive_manifest"
PRUNING_ROLE = "artifact_identity_pruning_journal"
PRUNING_STATES = {"planned", "in_progress", "quarantined", "deleting", "complete"}
LEGACY_POLICY = {
    "migration_kind": "administrative_rename_only",
    "artifact_access": "read_only",
    "new_runs_allowed": False,
    "verification_identity": "recorded_project_id",
    "claim_policy": "preserve_original_status_and_claim_limits_no_promotion",
}
LOCATION_SCHEMA_VERSION = 1
MODEL_BINARY_SUFFIXES = {".mph"}
FROZEN_INPUT_CONTAINER_NAMES = {
    "input",
    "inputs",
    "frozen_input",
    "frozen_inputs",
    "frozen-input",
    "frozen-inputs",
    "input_snapshot",
    "input_snapshots",
    "input-snapshot",
    "input-snapshots",
    "runtime_snapshot",
    "runtime-snapshot",
    "handoff_project_snapshot",
    "handoff-project-snapshot",
}
TEXT_SUFFIXES = {
    ".csv", ".gem", ".json", ".lua", ".m", ".md", ".ps1", ".py", ".toml",
    ".txt", ".yaml", ".yml",
}
SKIP_REPOSITORY_PARTS = {".git", ".tmp", ".venv", "scratch", "__pycache__"}


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"migration path must be relative: {value}")
    return path


def legacy_artifact_location(mapping: dict, current_project_id: str) -> dict[str, str | None]:
    """Validate one legacy location contract and return its sole active root."""

    legacy_project_id = mapping.get("project_id")
    expected_source = f"artifacts/projects/{legacy_project_id}"
    location = mapping.get("artifact_location")
    if not isinstance(location, dict) or location.get("schema_version") != LOCATION_SCHEMA_VERSION:
        raise ValueError(f"{current_project_id}: legacy artifact location differs")
    state = location.get("state")
    archive_id = location.get("archive_id")
    validate_archive_id(archive_id)
    expected_archive = (
        f"artifacts/projects/{current_project_id}/archive/{archive_id}/legacy-project-root"
    )
    expected_manifest = (
        f"artifacts/projects/{current_project_id}/archive/{archive_id}/"
        "identity_migration_manifest.json"
    )
    if (
        location.get("archive_root") != expected_archive
        or location.get("migration_manifest") != expected_manifest
    ):
        raise ValueError(f"{current_project_id}: legacy archive location differs")
    if state == "source_pending_relocation":
        if location.get("source_root") != expected_source:
            raise ValueError(f"{current_project_id}: pending legacy source differs")
        active_root = expected_source
    elif state == "archived_verified":
        if "source_root" in location:
            raise ValueError(f"{current_project_id}: archived location retains a source root")
        active_root = expected_archive
    else:
        raise ValueError(f"{current_project_id}: legacy artifact location state differs")
    return {
        "state": state,
        "active_root": active_root,
        "source_root": location.get("source_root"),
        "archive_root": expected_archive,
        "migration_manifest": expected_manifest,
    }


def resolve_legacy_artifact_root(
    workspace_root: Path,
    mapping: dict,
    current_project_id: str,
) -> Path:
    """Resolve the one active root and verify archived relocation provenance."""

    location = legacy_artifact_location(mapping, current_project_id)
    root = (workspace_root.resolve() / _relative_path(str(location["active_root"]))).resolve()
    root.relative_to(workspace_root.resolve())
    if location["state"] == "archived_verified":
        manifest_path = (
            workspace_root.resolve()
            / _relative_path(str(location["migration_manifest"]))
        ).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        validate_plan(manifest)
        if (
            manifest.get("status") != "relocated_verified"
            or manifest.get("current_project_id") != current_project_id
            or manifest.get("legacy_project_id") != mapping.get("project_id")
            or manifest.get("legacy_mapping_id") != mapping.get("mapping_id")
            or manifest.get("destination_root")
            != str(location["archive_root"]).removeprefix("artifacts/projects/")
        ):
            raise ValueError(f"{current_project_id}: archived migration identity differs")
    return root


def _is_simion_array(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix in {".pa", ".pa#", ".pa-surf"} or (
        suffix.startswith(".pa") and suffix[3:].isdigit()
    )


def _pruning_reason(relative: Path) -> str | None:
    if relative.parts and relative.parts[0].lower() == "scratch":
        return "non_authoritative_workspace"
    # The binary allow-list applies only inside one run payload.  Existing
    # archive/formal trees and old-root top-level material are evidence, not
    # disposable solver workspaces.
    if len(relative.parts) < 3 or relative.parts[0].lower() != "runs":
        return None
    payload_containers = {part.lower() for part in relative.parts[2:-1]}
    if payload_containers & FROZEN_INPUT_CONTAINER_NAMES:
        return None
    # Unknown containers that explicitly declare frozen/input/snapshot
    # semantics fail closed even before their name is added to the catalog.
    if any(
        "input" in part or "frozen" in part or "snapshot" in part
        for part in payload_containers
    ):
        return None
    suffix = relative.suffix.lower()
    if suffix in MODEL_BINARY_SUFFIXES or _is_simion_array(relative):
        return "rebuildable_solver_or_cad_binary"
    return None


def _repository_run_references(repository_root: Path, run_ids: set[str]) -> dict[str, set[str]]:
    references = {run_id: set() for run_id in run_ids}
    if not run_ids:
        return references
    for path in repository_root.rglob("*"):
        if (
            not path.is_file()
            or path.suffix.lower() not in TEXT_SUFFIXES
            or any(part in SKIP_REPOSITORY_PARTS for part in path.parts)
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        reference_class = (
            "history" if "docs" in path.parts and "history" in path.parts else "active"
        )
        for run_id in run_ids:
            if run_id in text:
                references[run_id].add(reference_class)
    return references


def _formal_run_references(current_root: Path) -> set[str]:
    references: set[str] = set()
    formal = current_root / "formal"
    if not formal.is_dir():
        return references
    for path in formal.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        source = value.get("source_run") if isinstance(value, dict) else None
        if isinstance(source, dict) and isinstance(source.get("run_id"), str):
            references.add(source["run_id"])
    return references


def _manifest_identity_records(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        if "path" in value and ("bytes" in value or "sha256" in value):
            yield value
            return
        for child in value.values():
            yield from _manifest_identity_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _manifest_identity_records(child)


def _manifest_local_relative(
    recorded_path: str,
    manifest_path: Path,
    source: Path,
    recorded_project_id: str,
) -> Path | None:
    raw = Path(recorded_path)
    candidate = raw if raw.is_absolute() else manifest_path.parent / raw
    try:
        return candidate.resolve(strict=False).relative_to(source.resolve())
    except ValueError:
        parts = raw.parts
        lowered = [part.lower() for part in parts]
        anchor = ["artifacts", "projects", recorded_project_id.lower()]
        matches = [
            index
            for index in range(len(parts) - 2)
            if lowered[index : index + 3] == anchor
        ]
        if len(matches) != 1 or matches[0] + 3 >= len(parts):
            return None
        return Path(*parts[matches[0] + 3 :])


def _manifest_identity_anomalies(
    source: Path,
    files_by_path: dict[str, dict[str, object]],
    recorded_project_id: str,
) -> list[dict[str, object]]:
    """Cross-check frozen local input/output identities without rewriting history."""

    anomalies: list[dict[str, object]] = []
    for manifest_path in sorted((source / "runs").glob("*/run_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        run_id = manifest_path.parent.name
        manifest_relative = manifest_path.relative_to(source).as_posix()
        for section in ("inputs", "outputs"):
            for recorded in _manifest_identity_records(manifest.get(section)):
                if recorded.get("exists") is False or not isinstance(
                    recorded.get("path"), str
                ):
                    continue
                relative = _manifest_local_relative(
                    str(recorded["path"]),
                    manifest_path,
                    source,
                    recorded_project_id,
                )
                if relative is None:
                    continue
                normalized = relative.as_posix()
                actual = files_by_path.get(normalized)
                recorded_bytes = recorded.get("bytes")
                recorded_sha256 = recorded.get("sha256")
                mismatches: list[str] = []
                if actual is None:
                    mismatches.append("missing_local_file")
                else:
                    if "bytes" in recorded:
                        if not isinstance(recorded_bytes, int) or recorded_bytes < 0:
                            mismatches.append("invalid_recorded_bytes")
                        elif recorded_bytes != actual["bytes"]:
                            mismatches.append("bytes_mismatch")
                    if "sha256" in recorded:
                        if not isinstance(recorded_sha256, str) or re.fullmatch(
                            r"[0-9A-Fa-f]{64}", recorded_sha256
                        ) is None:
                            mismatches.append("invalid_recorded_sha256")
                        elif recorded_sha256.upper() != actual["sha256"]:
                            mismatches.append("sha256_mismatch")
                if mismatches:
                    anomalies.append(
                        {
                            "path": normalized,
                            "run_id": run_id,
                            "manifest_path": manifest_relative,
                            "manifest_section": section,
                            "recorded_path": str(recorded["path"]),
                            "recorded_bytes": (
                                recorded_bytes if isinstance(recorded_bytes, int) else None
                            ),
                            "actual_bytes": actual["bytes"] if actual else None,
                            "recorded_sha256": (
                                recorded_sha256.upper()
                                if isinstance(recorded_sha256, str)
                                else None
                            ),
                            "actual_sha256": actual["sha256"] if actual else None,
                            "mismatches": mismatches,
                        }
                    )
    return anomalies


def _v2_manifest_outputs(source: Path, recorded_project_id: str) -> set[str]:
    """Return outputs that a v2 terminal manifest already chose to retain."""

    protected: set[str] = set()
    for manifest_path in sorted((source / "runs").glob("*/run_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("schema_version") != 2:
            continue
        for recorded in _manifest_identity_records(manifest.get("outputs")):
            if not isinstance(recorded.get("path"), str):
                continue
            relative = _manifest_local_relative(
                str(recorded["path"]), manifest_path, source, recorded_project_id
            )
            if relative is not None:
                protected.add(relative.as_posix())
    return protected


def _legacy_mapping(
    repository_root: Path,
    current_project_id: str,
    legacy_project_id: str | None,
) -> dict:
    descriptor_path = repository_root / "projects" / current_project_id / "config" / "project.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8-sig"))
    if descriptor.get("project_id") != current_project_id:
        raise ValueError(f"current project identity differs: {descriptor_path}")
    mappings = descriptor.get("legacy_identities", [])
    matches = [
        mapping for mapping in mappings
        if legacy_project_id is None or mapping.get("project_id") == legacy_project_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{current_project_id}: legacy identity selection must resolve exactly once"
        )
    mapping = matches[0]
    for field, expected in LEGACY_POLICY.items():
        if mapping.get(field) != expected:
            raise ValueError(f"{current_project_id}: legacy policy differs for {field}")
    legacy_artifact_location(mapping, current_project_id)
    return mapping


def _build_inventory(
    repository_root: Path,
    current_root: Path,
    inventory_root: Path,
    legacy_project_id: str,
    *,
    protect_formal_bearing_root: bool = True,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, int]]:
    """Freeze one legacy payload and classify only explicitly rebuildable files."""

    run_root = inventory_root / "runs"
    run_ids = (
        {item.name for item in run_root.iterdir() if item.is_dir()}
        if run_root.is_dir()
        else set()
    )
    references = _repository_run_references(repository_root, run_ids)
    formal_run_ids = _formal_run_references(current_root) | _formal_run_references(
        inventory_root
    )
    for run_id in formal_run_ids:
        if run_id in references:
            references[run_id].add("formal")

    formal_bearing_root = (inventory_root / "formal" / "asset_manifest.json").is_file()
    v2_outputs = _v2_manifest_outputs(inventory_root, legacy_project_id)
    files: list[dict[str, object]] = []
    for path in sorted(item for item in inventory_root.rglob("*") if item.is_file()):
        relative = path.relative_to(inventory_root)
        reason = _pruning_reason(relative)
        if (protect_formal_bearing_root and formal_bearing_root) or relative.as_posix() in v2_outputs:
            reason = None
        run_id = (
            relative.parts[1]
            if len(relative.parts) >= 2 and relative.parts[0] == "runs"
            else None
        )
        reference_classes = sorted(references.get(run_id, set())) if run_id else []
        if "formal" in reference_classes:
            reason = None
        files.append(
            {
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
                "disposition": "prune_after_verified_migration" if reason else "retain",
                "reason": reason,
                "run_id": run_id,
                "reference_classes": reference_classes,
            }
        )
    files_by_path = {str(record["path"]): record for record in files}
    identity_anomalies = _manifest_identity_anomalies(
        inventory_root, files_by_path, legacy_project_id
    )
    anomaly_paths = {
        str(anomaly["path"])
        for anomaly in identity_anomalies
        if str(anomaly["path"]) in files_by_path
    }
    for path in anomaly_paths:
        files_by_path[path]["disposition"] = "retain"
        files_by_path[path]["reason"] = "manifest_identity_anomaly"
    prune = [
        item
        for item in files
        if item["disposition"] == "prune_after_verified_migration"
    ]
    inventory = {
        "file_count": len(files),
        "bytes": sum(int(item["bytes"]) for item in files),
        "prune_candidate_file_count": len(prune),
        "prune_candidate_bytes": sum(int(item["bytes"]) for item in prune),
        "identity_anomaly_count": len(identity_anomalies),
        "identity_anomaly_file_count": len(anomaly_paths),
    }
    return files, identity_anomalies, inventory


def build_plan(
    repository_root: Path,
    artifact_projects_root: Path,
    current_project_id: str,
    archive_id: str,
    legacy_project_id: str | None = None,
) -> dict:
    """Build a complete, content-addressed migration plan without writing artifacts."""

    validate_archive_id(archive_id)
    repository_root = repository_root.resolve()
    artifact_projects_root = artifact_projects_root.resolve()
    expected_artifact_projects_root = (
        repository_root.parent / "artifacts" / "projects"
    ).resolve()
    if artifact_projects_root != expected_artifact_projects_root:
        raise ValueError(
            "artifact projects root must be the repository sibling artifacts/projects"
        )
    mapping = _legacy_mapping(repository_root, current_project_id, legacy_project_id)
    legacy_project_id = str(mapping["project_id"])
    location = legacy_artifact_location(mapping, current_project_id)
    if location["state"] != "source_pending_relocation":
        raise ValueError(f"{current_project_id}: legacy artifacts are already relocated")
    source = repository_root.parent / _relative_path(str(location["source_root"]))
    current = artifact_projects_root / current_project_id
    if not source.is_dir() or not current.is_dir():
        raise FileNotFoundError("both legacy and current artifact project roots must exist")
    files, identity_anomalies, inventory = _build_inventory(
        repository_root, current, source, legacy_project_id
    )
    destination = Path(current_project_id) / "archive" / archive_id / "legacy-project-root"
    if location["archive_root"] is not None and (
        str(location["archive_root"]).removeprefix("artifacts/projects/")
        != destination.as_posix()
    ):
        raise ValueError(f"{current_project_id}: requested archive identity differs")
    return {
        "schema_version": SCHEMA_VERSION,
        "role": ROLE,
        "migration_id": archive_id,
        "status": "planned",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_project_id": current_project_id,
        "legacy_project_id": legacy_project_id,
        "legacy_mapping_id": mapping.get("mapping_id"),
        "source_root": legacy_project_id,
        "destination_root": destination.as_posix(),
        "relocation": {
            "kind": "exact_root_prefix",
            "legacy_manifests_rewritten": False,
            "recorded_project_identity_preserved": True,
        },
        "inventory": inventory,
        "identity_anomalies": identity_anomalies,
        "files": files,
    }


def build_pruning_plan(
    repository_root: Path,
    artifact_projects_root: Path,
    current_project_id: str,
    legacy_project_id: str | None = None,
) -> dict:
    """Reclassify one verified migration archive for independent pruning."""

    repository_root = repository_root.resolve()
    artifact_projects_root = artifact_projects_root.resolve()
    mapping = _legacy_mapping(repository_root, current_project_id, legacy_project_id)
    legacy_project_id = str(mapping["project_id"])
    location = legacy_artifact_location(mapping, current_project_id)
    if location["state"] != "archived_verified":
        raise ValueError(f"{current_project_id}: legacy artifacts are not archived_verified")
    archive_manifest_path = (
        repository_root.parent / _relative_path(str(location["migration_manifest"]))
    ).resolve()
    published = _load_plan(archive_manifest_path)
    verify_inventory(published, artifact_projects_root, "destination")
    current = artifact_projects_root / current_project_id
    payload = artifact_projects_root / _relative_path(published["destination_root"])
    files, identity_anomalies, inventory = _build_inventory(
        repository_root,
        current,
        payload,
        legacy_project_id,
        protect_formal_bearing_root=False,
    )
    plan = dict(published)
    plan["recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
    plan["inventory"] = inventory
    plan["identity_anomalies"] = identity_anomalies
    plan["files"] = files
    validate_plan(plan)
    return plan


def validate_plan(plan: dict) -> None:
    """Validate closed-world plan structure before reading either tree."""

    schema_version = plan.get("schema_version")
    if schema_version != SCHEMA_VERSION or plan.get("role") != ROLE:
        raise ValueError("migration manifest identity differs")
    validate_archive_id(plan.get("migration_id"))
    source = _relative_path(plan.get("source_root"))
    destination = _relative_path(plan.get("destination_root"))
    if len(source.parts) != 1 or len(destination.parts) != 4:
        raise ValueError("migration root structure differs")
    if destination.parts[:2] != (plan.get("current_project_id"), "archive"):
        raise ValueError("destination current project differs")
    if destination.parts[2] != plan.get("migration_id") or destination.parts[3] != "legacy-project-root":
        raise ValueError("destination archive identity differs")
    if source.name != plan.get("legacy_project_id"):
        raise ValueError("source legacy project differs")
    records = plan.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("migration manifest has no file inventory")
    paths: set[str] = set()
    for record in records:
        relative = _relative_path(record.get("path"))
        normalized = relative.as_posix()
        if normalized in paths:
            raise ValueError(f"duplicate migration file: {normalized}")
        paths.add(normalized)
        if int(record.get("bytes", -1)) < 0:
            raise ValueError(f"invalid byte count: {normalized}")
        sha256 = record.get("sha256")
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9A-F]{64}", sha256) is None:
            raise ValueError(f"invalid SHA-256: {normalized}")
        disposition = record.get("disposition")
        if disposition not in {"retain", "prune_after_verified_migration"}:
            raise ValueError(f"invalid disposition: {normalized}")
        reason = record.get("reason")
        if disposition == "prune_after_verified_migration" and reason not in {
            "non_authoritative_workspace",
            "rebuildable_solver_or_cad_binary",
        }:
            raise ValueError(f"migration disposition/reason differs: {normalized}")
        if disposition == "retain" and reason not in {None, "manifest_identity_anomaly"}:
            raise ValueError(f"migration disposition/reason differs: {normalized}")
    inventory = plan.get("inventory", {})
    if inventory.get("file_count") != len(records) or inventory.get("bytes") != sum(
        int(record["bytes"]) for record in records
    ):
        raise ValueError("migration inventory totals differ")
    prune = [record for record in records if record["disposition"] == "prune_after_verified_migration"]
    if (
        inventory.get("prune_candidate_file_count") != len(prune)
        or inventory.get("prune_candidate_bytes")
        != sum(int(record["bytes"]) for record in prune)
    ):
        raise ValueError("migration prune inventory totals differ")
    if schema_version == SCHEMA_VERSION:
        anomalies = plan.get("identity_anomalies")
        if not isinstance(anomalies, list):
            raise ValueError("migration identity anomaly audit is missing")
        anomaly_paths: set[str] = set()
        for anomaly in anomalies:
            if not isinstance(anomaly, dict):
                raise ValueError("migration identity anomaly record differs")
            path = _relative_path(anomaly.get("path")).as_posix()
            mismatches = anomaly.get("mismatches")
            if not isinstance(mismatches, list) or not mismatches:
                raise ValueError(f"migration identity anomaly kinds differ: {path}")
            if path in paths:
                anomaly_paths.add(path)
        marked_paths = {
            str(record["path"])
            for record in records
            if record.get("reason") == "manifest_identity_anomaly"
        }
        if marked_paths != anomaly_paths:
            raise ValueError("migration identity anomaly retention differs")
        if (
            inventory.get("identity_anomaly_count") != len(anomalies)
            or inventory.get("identity_anomaly_file_count") != len(anomaly_paths)
        ):
            raise ValueError("migration identity anomaly totals differ")


def validate_identity_archive_manifest(manifest: dict, plan: dict) -> None:
    """Validate the archive wrapper that publishes one relocated legacy tree."""

    required = {
        "schema_version", "role", "archive_id", "project", "reason",
        "recorded_at_utc", "source_layout", "replacement_layout",
        "legacy_project_id", "payload", "identity_migration_manifest",
        "deletion_performed",
    }
    allowed = required | {"pruning_manifest"}
    if frozenset(manifest) not in {frozenset(required), frozenset(allowed)}:
        raise ValueError("identity archive manifest fields differ")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("role") != ARCHIVE_ROLE
        or manifest.get("archive_id") != plan["migration_id"]
        or manifest.get("project") != plan["current_project_id"]
        or manifest.get("reason") != "migration-snapshot"
        or manifest.get("source_layout") != "retired-project-root"
        or manifest.get("replacement_layout") != "current-project-archive"
        or manifest.get("legacy_project_id") != plan["legacy_project_id"]
        or manifest.get("payload") != "legacy-project-root"
        or manifest.get("identity_migration_manifest")
        != "identity_migration_manifest.json"
        or not isinstance(manifest.get("deletion_performed"), bool)
    ):
        raise ValueError("identity archive manifest identity differs")
    if manifest["deletion_performed"] != (manifest.get("pruning_manifest") is not None):
        raise ValueError("identity archive pruning publication differs")


def relocated_manifest_path(recorded_path: str, old_root: Path, new_root: Path) -> Path:
    """Relocate one immutable legacy absolute path through an exact prefix."""

    recorded = Path(recorded_path).resolve(strict=False)
    relative = recorded.relative_to(old_root.resolve(strict=False))
    return new_root.resolve(strict=False) / relative


def verify_inventory(plan: dict, artifact_projects_root: Path, phase: str) -> None:
    """Verify exact file set, sizes, hashes, and recorded run identity."""

    validate_plan(plan)
    if phase not in {"source", "destination"}:
        raise ValueError("phase must be source or destination")
    relative_root = plan["source_root"] if phase == "source" else plan["destination_root"]
    root = artifact_projects_root.resolve() / _relative_path(relative_root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    expected = {record["path"]: record for record in plan["files"]}
    actual = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise ValueError(f"migration file set differs: missing={missing[:3]} unexpected={unexpected[:3]}")
    for relative, record in expected.items():
        path = actual[relative]
        if path.stat().st_size != int(record["bytes"]):
            raise ValueError(f"migration byte count differs: {relative}")
        if file_sha256(path) != record["sha256"]:
            raise ValueError(f"migration SHA-256 differs: {relative}")
    if plan.get("schema_version") == SCHEMA_VERSION:
        live_anomalies = _manifest_identity_anomalies(
            root, expected, str(plan["legacy_project_id"])
        )
        if live_anomalies != plan["identity_anomalies"]:
            raise ValueError("migration manifest identity anomaly audit differs")
    runs = root / "runs"
    if runs.is_dir():
        for manifest_path in runs.glob("*/run_manifest.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if manifest.get("project") != plan["legacy_project_id"]:
                raise ValueError(f"recorded project identity differs: {manifest_path}")


def apply_migration(plan: dict, artifact_projects_root: Path) -> Path:
    """Move a verified legacy root on-volume and publish its archive manifests."""

    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("migration apply requires current identity anomaly audit")
    verify_inventory(plan, artifact_projects_root, "source")
    projects = artifact_projects_root.resolve()
    source = projects / _relative_path(plan["source_root"])
    payload = projects / _relative_path(plan["destination_root"])
    archive = payload.parent
    current_root = projects / plan["current_project_id"]
    if archive.exists():
        raise FileExistsError(archive)
    if not current_root.is_dir():
        raise FileNotFoundError(current_root)
    if source.stat().st_dev != current_root.stat().st_dev:
        raise OSError("source and destination are not on the same volume")
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.mkdir()
    try:
        os.replace(source, payload)
        verify_inventory(plan, artifact_projects_root, "destination")
        published = dict(plan)
        published["status"] = "relocated_verified"
        _atomic_json(archive / "identity_migration_manifest.json", published)
        archive_manifest = {
            "schema_version": 1,
            "role": ARCHIVE_ROLE,
            "archive_id": plan["migration_id"],
            "project": plan["current_project_id"],
            "reason": "migration-snapshot",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_layout": "retired-project-root",
            "replacement_layout": "current-project-archive",
            "legacy_project_id": plan["legacy_project_id"],
            "payload": "legacy-project-root",
            "identity_migration_manifest": "identity_migration_manifest.json",
            "deletion_performed": False,
        }
        validate_identity_archive_manifest(archive_manifest, published)
        _atomic_json(archive / "archive_manifest.json", archive_manifest)
    except Exception:
        if payload.exists() and not source.exists():
            os.replace(payload, source)
        for child in (archive / "identity_migration_manifest.json", archive / "archive_manifest.json"):
            if child.exists():
                child.unlink()
        if archive.exists():
            archive.rmdir()
        raise
    return archive


def rollback_migration(plan: dict, artifact_projects_root: Path) -> None:
    """Reverse an unpruned relocation after verifying the archived payload."""

    projects = artifact_projects_root.resolve()
    source = projects / _relative_path(plan["source_root"])
    payload = projects / _relative_path(plan["destination_root"])
    archive = payload.parent
    if source.exists():
        raise FileExistsError(source)
    pruning_path = archive / "pruning_manifest.json"
    if pruning_path.exists():
        pruning = _load_pruning_journal(pruning_path, plan)
        if pruning["state"] in {"deleting", "complete"}:
            raise ValueError("pruned migration cannot be rolled back byte-for-byte")
        _restore_pruning_quarantine(plan, payload, archive, pruning)
    verify_inventory(plan, artifact_projects_root, "destination")
    os.replace(payload, source)
    for child in (archive / "identity_migration_manifest.json", archive / "archive_manifest.json"):
        if child.exists():
            child.unlink()
    archive.rmdir()
    verify_inventory(plan, artifact_projects_root, "source")


def _pruning_records(plan: dict) -> list[dict[str, object]]:
    return [
        {
            "original_path": f"{plan['source_root']}/{record['path']}",
            "archive_path": f"legacy-project-root/{record['path']}",
            "quarantine_path": f".prune-quarantine/{record['path']}",
            "bytes": record["bytes"],
            "sha256": record["sha256"],
            "reason": record["reason"],
        }
        for record in plan["files"]
        if record["disposition"] == "prune_after_verified_migration"
    ]


def validate_pruning_journal(journal: dict, plan: dict) -> None:
    if (
        journal.get("schema_version") != 1
        or journal.get("role") != PRUNING_ROLE
        or journal.get("archive_id") != plan["migration_id"]
        or journal.get("state") not in PRUNING_STATES
    ):
        raise ValueError("pruning journal identity differs")
    expected = _pruning_records(plan)
    if journal.get("removed") != expected:
        raise ValueError("pruning journal file inventory differs")
    if (
        journal.get("removed_file_count") != len(expected)
        or journal.get("removed_bytes")
        != sum(int(record["bytes"]) for record in expected)
    ):
        raise ValueError("pruning journal totals differ")


def _load_pruning_journal(path: Path, plan: dict) -> dict:
    journal = json.loads(path.read_text(encoding="utf-8-sig"))
    validate_pruning_journal(journal, plan)
    return journal


def _write_pruning_state(path: Path, journal: dict, state: str) -> None:
    if state not in PRUNING_STATES:
        raise ValueError("invalid pruning journal state")
    journal["state"] = state
    journal["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(path, journal)


def _restore_pruning_quarantine(
    plan: dict, payload: Path, archive: Path, journal: dict
) -> None:
    quarantine = archive / ".prune-quarantine"
    for record in journal["removed"]:
        relative = _relative_path(str(record["archive_path"]).removeprefix("legacy-project-root/"))
        source = quarantine / relative
        destination = payload / relative
        if destination.exists():
            if destination.stat().st_size != record["bytes"] or file_sha256(destination) != record["sha256"]:
                raise ValueError(f"prune rollback destination differs: {relative}")
            continue
        if not source.is_file():
            raise ValueError(f"prune rollback source is missing: {relative}")
        if source.stat().st_size != record["bytes"] or file_sha256(source) != record["sha256"]:
            raise ValueError(f"prune rollback source differs: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
    for directory in sorted(
        (path for path in quarantine.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts), reverse=True,
    ):
        directory.rmdir()
    if quarantine.exists():
        quarantine.rmdir()
    (archive / "pruning_manifest.json").unlink()
    verify_inventory(plan, archive.parents[2], "destination")


def verify_pruned_inventory(
    plan: dict, artifact_projects_root: Path, *, verify_hashes: bool = True
) -> None:
    """Verify retained files, completed journal, and absence of all prune candidates."""

    validate_plan(plan)
    projects = artifact_projects_root.resolve()
    payload = projects / _relative_path(plan["destination_root"])
    archive = payload.parent
    pruning_path = archive / "pruning_manifest.json"
    journal = _load_pruning_journal(pruning_path, plan)
    if journal["state"] != "complete":
        raise ValueError("pruning journal is not complete")
    for record in plan["files"]:
        path = payload / _relative_path(record["path"])
        if record["disposition"] == "prune_after_verified_migration":
            if path.exists():
                raise ValueError(f"completed prune candidate remains: {record['path']}")
        elif (
            not path.is_file()
            or path.stat().st_size != record["bytes"]
            or (verify_hashes and file_sha256(path) != record["sha256"])
        ):
            raise ValueError(f"retained migration identity differs: {record['path']}")
    if (archive / ".prune-quarantine").exists():
        raise ValueError("completed pruning retains quarantine")


def prune_migration(
    plan: dict,
    artifact_projects_root: Path,
    *,
    interrupt_after_moves: int | None = None,
    interrupt_after_deletes: int | None = None,
    interrupt_after_complete_journal: bool = False,
) -> dict:
    """Resume-safe quarantine and deletion of preclassified rebuildable payload."""

    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("migration pruning requires current identity anomaly audit")
    projects = artifact_projects_root.resolve()
    payload = projects / _relative_path(plan["destination_root"])
    archive = payload.parent
    pruning_path = archive / "pruning_manifest.json"
    if pruning_path.exists():
        journal = _load_pruning_journal(pruning_path, plan)
        if journal["state"] == "complete":
            verify_pruned_inventory(plan, artifact_projects_root)
            _publish_pruning_completion(archive, plan, journal)
            return journal
    else:
        verify_inventory(plan, artifact_projects_root, "destination")
        published = dict(plan)
        published["status"] = "relocated_verified"
        _atomic_json(archive / "identity_migration_manifest.json", published)
        records = _pruning_records(plan)
        journal = {
            "schema_version": 1,
            "role": PRUNING_ROLE,
            "archive_id": plan["migration_id"],
            "state": "planned",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "removed_file_count": len(records),
            "removed_bytes": sum(int(record["bytes"]) for record in records),
            "removed": records,
        }
        _atomic_json(pruning_path, journal)
    resume_state = journal["state"]
    candidates = [
        record for record in plan["files"]
        if record["disposition"] == "prune_after_verified_migration"
    ]
    if any("formal" in record.get("reference_classes", []) for record in candidates):
        raise ValueError("formal-referenced payload cannot be pruned")
    quarantine = archive / ".prune-quarantine"
    if resume_state != "deleting":
        quarantine.mkdir(parents=True, exist_ok=True)
        _write_pruning_state(pruning_path, journal, "in_progress")
        moved = 0
        for record in journal["removed"]:
            relative = _relative_path(str(record["archive_path"]).removeprefix("legacy-project-root/"))
            target = payload / relative
            staged = quarantine / relative
            if target.is_file():
                if target.stat().st_size != record["bytes"] or file_sha256(target) != record["sha256"]:
                    raise ValueError(f"prune candidate identity differs: {relative}")
                staged.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, staged)
                moved += 1
                if interrupt_after_moves is not None and moved >= interrupt_after_moves:
                    raise RuntimeError("simulated pruning interruption after quarantine move")
            elif not staged.is_file():
                raise ValueError(f"prune candidate is missing from payload and quarantine: {relative}")
            if staged.stat().st_size != record["bytes"] or file_sha256(staged) != record["sha256"]:
                raise ValueError(f"quarantined prune identity differs: {relative}")
        _write_pruning_state(pruning_path, journal, "quarantined")
        _write_pruning_state(pruning_path, journal, "deleting")
    elif not quarantine.is_dir():
        raise ValueError("deleting prune journal has no quarantine")
    deleted = 0
    for record in journal["removed"]:
        relative = _relative_path(str(record["quarantine_path"]).removeprefix(".prune-quarantine/"))
        staged = quarantine / relative
        if staged.is_file():
            if staged.stat().st_size != record["bytes"] or file_sha256(staged) != record["sha256"]:
                raise ValueError(f"quarantined delete identity differs: {relative}")
            staged.unlink()
            deleted += 1
            if interrupt_after_deletes is not None and deleted >= interrupt_after_deletes:
                raise RuntimeError("simulated pruning interruption during delete")
    for directory in sorted(
        (path for path in quarantine.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts), reverse=True,
    ):
        directory.rmdir()
    quarantine.rmdir()
    _write_pruning_state(pruning_path, journal, "complete")
    if interrupt_after_complete_journal:
        raise RuntimeError("simulated pruning interruption after complete journal")
    _publish_pruning_completion(archive, plan, journal)
    verify_pruned_inventory(plan, artifact_projects_root)
    return journal


def _publish_pruning_completion(archive: Path, plan: dict, journal: dict) -> None:
    """Idempotently reconcile a complete journal into its archive wrapper."""

    if journal.get("state") != "complete":
        raise ValueError("cannot publish an incomplete pruning journal")
    archive_manifest_path = archive / "archive_manifest.json"
    archive_manifest = json.loads(archive_manifest_path.read_text(encoding="utf-8"))
    archive_manifest["deletion_performed"] = bool(journal["removed"])
    if journal["removed"]:
        archive_manifest["pruning_manifest"] = "pruning_manifest.json"
    validate_identity_archive_manifest(archive_manifest, plan)
    _atomic_json(archive_manifest_path, archive_manifest)


def _load_plan(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    validate_plan(value)
    return value


def _write_plan(path: Path, plan: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, plan)


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--repository-root", required=True, type=Path)
    plan_parser.add_argument("--artifact-projects-root", required=True, type=Path)
    plan_parser.add_argument("--current-project", required=True)
    plan_parser.add_argument("--legacy-project")
    plan_parser.add_argument("--archive-id", required=True)
    plan_parser.add_argument("--output", type=Path)
    prune_plan_parser = subparsers.add_parser("plan-prune")
    prune_plan_parser.add_argument("--repository-root", required=True, type=Path)
    prune_plan_parser.add_argument("--artifact-projects-root", required=True, type=Path)
    prune_plan_parser.add_argument("--current-project", required=True)
    prune_plan_parser.add_argument("--legacy-project")
    prune_plan_parser.add_argument("--output", type=Path)
    for command in ("verify-source", "verify-destination", "apply", "rollback", "prune"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--artifact-projects-root", required=True, type=Path)
        command_parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command in {"plan", "plan-prune"}:
        plan = (
            build_plan(
                args.repository_root, args.artifact_projects_root,
                args.current_project, args.archive_id, args.legacy_project,
            )
            if args.command == "plan"
            else build_pruning_plan(
                args.repository_root, args.artifact_projects_root,
                args.current_project, args.legacy_project,
            )
        )
        if args.output:
            _write_plan(args.output, plan)
        inventory = plan["inventory"]
        print(
            f"ARTIFACT_IDENTITY_MIGRATION_{args.command.upper().replace('-', '_')}=PASS "
            f"FILES={inventory['file_count']} BYTES={inventory['bytes']} "
            f"PRUNE_FILES={inventory['prune_candidate_file_count']} "
            f"PRUNE_BYTES={inventory['prune_candidate_bytes']} "
            f"IDENTITY_ANOMALIES={inventory['identity_anomaly_count']}"
        )
        return
    plan = _load_plan(args.manifest)
    if args.command == "verify-source":
        verify_inventory(plan, args.artifact_projects_root, "source")
    elif args.command == "verify-destination":
        verify_inventory(plan, args.artifact_projects_root, "destination")
    elif args.command == "apply":
        apply_migration(plan, args.artifact_projects_root)
    elif args.command == "rollback":
        rollback_migration(plan, args.artifact_projects_root)
    elif args.command == "prune":
        prune_migration(plan, args.artifact_projects_root)
    print(f"ARTIFACT_IDENTITY_MIGRATION={args.command.upper().replace('-', '_')}_PASS")


if __name__ == "__main__":
    main()
