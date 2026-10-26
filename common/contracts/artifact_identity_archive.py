"""Resolve and verify immutable archives created by completed identity migrations."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

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
LOCATION_SCHEMA_VERSION = 1
READ_ONLY_IDENTITY_POLICY = {
    "artifact_access": "read_only",
    "new_runs_allowed": False,
    "verification_identity": "recorded_project_id",
    "claim_policy": "preserve_original_status_and_claim_limits_no_promotion",
}


@dataclass(frozen=True)
class HistoricalProjectIdentity:
    """One recorded identity and the unchanged owner of its artifact location."""

    project_id: str
    artifact_owner_project_id: str
    policy: dict
    legacy_mapping: dict | None


def load_retired_project_descriptors(descriptor: dict, repository_root: Path) -> list[dict]:
    """Read hash-bound retired descriptors without registering their capabilities.

    Paths are repository-relative frozen history. Raw bytes, recorded project IDs
    and read-only policy must match; no source or artifact files are modified.
    """
    repository = repository_root.resolve()
    current_id = descriptor["project_id"]
    result: list[dict] = []
    seen: set[str] = set()
    required = {"project_id", "path", "bytes", "sha256", "source_commit"} | set(READ_ONLY_IDENTITY_POLICY)
    for record in descriptor.get("retired_project_descriptors", []):
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError(f"{current_id}: retired descriptor fields differ")
        retired_id = record["project_id"]
        if (
            not isinstance(retired_id, str)
            or re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", retired_id) is None
            or retired_id == current_id
            or retired_id in seen
        ):
            raise ValueError(f"{current_id}: retired descriptor project identity differs")
        seen.add(retired_id)
        for field, value in READ_ONLY_IDENTITY_POLICY.items():
            if record.get(field) != value or (field == "new_runs_allowed" and record[field] is not False):
                raise ValueError(f"{retired_id}: invalid retired identity field {field}")
        expected_path = f"projects/{current_id}/docs/history/retired_projects/{retired_id}/config/project.json"
        if record["path"] != expected_path:
            raise ValueError(f"{retired_id}: retired descriptor path differs")
        if re.fullmatch(r"[0-9a-fA-F]{40}", str(record["source_commit"])) is None:
            raise ValueError(f"{retired_id}: retired descriptor source commit differs")
        path = (repository / expected_path).resolve()
        path.relative_to(repository)
        size = record["bytes"]
        digest = record["sha256"]
        if (
            not isinstance(size, int) or isinstance(size, bool) or size <= 0
            or not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None
            or not path.is_file() or path.stat().st_size != size
            or file_sha256(path) != digest.upper()
        ):
            raise ValueError(f"{retired_id}: frozen retired descriptor identity differs")
        retired = json.loads(path.read_text(encoding="utf-8-sig"))
        if (
            not isinstance(retired, dict)
            or retired.get("project_id") != retired_id
            or retired.get("retired_project_descriptors")
        ):
            raise ValueError(f"{retired_id}: frozen retired descriptor project differs")
        result.append(retired)
    return result


def historical_project_identities(
    descriptor: dict, repository_root: Path
) -> Iterator[HistoricalProjectIdentity]:
    """Yield retired owners and aliases using each original archive owner."""
    current_id = descriptor["project_id"]
    for mapping in descriptor.get("legacy_identities", []):
        legacy_artifact_location(mapping, current_id)
        yield HistoricalProjectIdentity(mapping["project_id"], current_id, mapping, mapping)
    retired = load_retired_project_descriptors(descriptor, repository_root)
    for binding, previous in zip(descriptor.get("retired_project_descriptors", []), retired):
        owner = previous["project_id"]
        yield HistoricalProjectIdentity(owner, owner, binding, None)
        for mapping in previous.get("legacy_identities", []):
            legacy_artifact_location(mapping, owner)
            yield HistoricalProjectIdentity(mapping["project_id"], owner, mapping, mapping)


def assert_new_run_project_allowed(repository_root: Path, project_id: str) -> None:
    """Reject explicitly retired owners/aliases before run creation; leave other owners unchanged."""
    for path in sorted((repository_root / "projects").glob("*/config/project.json")):
        descriptor = json.loads(path.read_text(encoding="utf-8-sig"))
        if descriptor.get("project_id") != path.parents[1].name:
            raise ValueError(f"project descriptor identity differs: {path}")
        for identity in historical_project_identities(descriptor, repository_root):
            if identity.project_id == project_id:
                raise ValueError(f"{project_id}: retired project identity is read-only; new runs are forbidden")


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
    workspace = workspace_root.resolve()
    root = (workspace / _relative_path(str(location["active_root"]))).resolve()
    root.relative_to(workspace)
    if location["state"] == "archived_verified":
        manifest_path = (
            workspace / _relative_path(str(location["migration_manifest"]))
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


def validate_plan(plan: dict) -> None:
    """Validate the frozen closed-world inventory of a completed migration."""

    if plan.get("schema_version") != SCHEMA_VERSION or plan.get("role") != ROLE:
        raise ValueError("migration manifest identity differs")
    validate_archive_id(plan.get("migration_id"))
    source = _relative_path(plan.get("source_root"))
    destination = _relative_path(plan.get("destination_root"))
    if len(source.parts) != 1 or len(destination.parts) != 4:
        raise ValueError("migration root structure differs")
    if destination.parts[:2] != (plan.get("current_project_id"), "archive"):
        raise ValueError("destination current project differs")
    if (
        destination.parts[2] != plan.get("migration_id")
        or destination.parts[3] != "legacy-project-root"
    ):
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
        or manifest.get("identity_migration_manifest") != "identity_migration_manifest.json"
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
        or journal.get("removed_bytes") != sum(int(record["bytes"]) for record in expected)
    ):
        raise ValueError("pruning journal totals differ")


def verify_pruned_inventory(
    plan: dict, artifact_projects_root: Path, *, verify_hashes: bool = True
) -> None:
    """Verify retained files and absence of every frozen prune candidate."""

    validate_plan(plan)
    projects = artifact_projects_root.resolve()
    payload = projects / _relative_path(plan["destination_root"])
    archive = payload.parent
    journal = json.loads(
        (archive / "pruning_manifest.json").read_text(encoding="utf-8-sig")
    )
    validate_pruning_journal(journal, plan)
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


def main() -> None:
    """Expose the read-only project guard used before creating a run package."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--check-new-run-project", required=True)
    args = parser.parse_args()
    try:
        assert_new_run_project_allowed(args.repository_root.resolve(), args.check_new_run_project)
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(1, f"NEW_RUN_PROJECT=FAIL {exc}\n")
    print(f"NEW_RUN_PROJECT=PASS PROJECT={args.check_new_run_project}")


if __name__ == "__main__":
    main()
