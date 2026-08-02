"""Verify artifact v2 structure; hash large formal assets only when requested."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from common.contracts.artifact_retention import validate_retention
except ModuleNotFoundError:
    from artifact_retention import validate_retention

try:
    from common.contracts.artifact_naming import (
        validate_archive_id,
        validate_formal_asset_name,
        validate_run_id,
        validate_task_id,
    )
except ModuleNotFoundError:
    from artifact_naming import (
        validate_archive_id,
        validate_formal_asset_name,
        validate_run_id,
        validate_task_id,
    )

try:
    from common.contracts.file_identity import file_sha256
except ModuleNotFoundError:
    from file_identity import file_sha256

try:
    from common.contracts.artifact_identity_archive import (
        legacy_artifact_location,
        validate_identity_archive_manifest,
        validate_plan,
        validate_pruning_journal,
        verify_pruned_inventory,
    )
except ModuleNotFoundError:
    from artifact_identity_archive import (
        legacy_artifact_location,
        validate_identity_archive_manifest,
        validate_plan,
        validate_pruning_journal,
        verify_pruned_inventory,
    )


ALLOWED_PROJECT_ENTRIES = {"00_README.txt", "formal", "runs", "archive", "scratch"}
REQUIRED_RUN_FILES = {"run_config.json", "summary.json", "run_manifest.json"}
LEGACY_POLICY = {
    "migration_kind": "administrative_rename_only",
    "artifact_access": "read_only",
    "new_runs_allowed": False,
    "verification_identity": "recorded_project_id",
    "claim_policy": "preserve_original_status_and_claim_limits_no_promotion",
}


def verify_record(root: Path, record: dict, verify_hashes: bool) -> Path:
    relative = Path(record["path"])
    if relative.is_absolute():
        raise AssertionError(f"manifest path must be relative: {relative}")
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise AssertionError(f"manifest file is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise AssertionError(f"manifest byte count differs: {path}")
    if verify_hashes and file_sha256(path) != record["sha256"]:
        raise AssertionError(f"manifest SHA-256 differs: {path}")
    return path


def legacy_identity(repository_root: Path, project_id: str) -> dict | None:
    """Resolve one retired artifact identity without requiring its old source tree."""

    matches: list[tuple[str, dict]] = []
    active_ids: set[str] = set()
    for descriptor_path in sorted(
        (repository_root / "projects").glob("*/config/project.json")
    ):
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8-sig"))
        current_id = descriptor.get("project_id")
        if current_id != descriptor_path.parents[1].name:
            raise AssertionError(f"project descriptor identity differs: {descriptor_path}")
        active_ids.add(current_id)
        matches.extend(
            (current_id, mapping)
            for mapping in descriptor.get("legacy_identities", [])
            if mapping.get("project_id") == project_id
        )
    if len(matches) > 1:
        raise AssertionError(f"{project_id}: duplicate legacy identity mappings")
    if not matches:
        return None
    if project_id in active_ids:
        raise AssertionError(f"{project_id}: legacy identity is still an active project")
    current_id, mapping = matches[0]
    expected = LEGACY_POLICY
    for field, value in expected.items():
        if mapping.get(field) != value:
            raise AssertionError(f"{project_id}: invalid legacy identity field {field}")
    try:
        legacy_artifact_location(mapping, current_id)
    except ValueError as exc:
        raise AssertionError(f"{project_id}: invalid legacy artifact location") from exc
    return mapping


def verify_retired_validation_record(record: dict, project_id: str) -> None:
    """Validate immutable provenance whose retired repository path no longer exists."""

    try:
        relative = Path(record["path"])
        bytes_count = int(record["bytes"])
        sha256 = str(record["sha256"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AssertionError(
            f"{project_id}: invalid retired validation contract record"
        ) from exc
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) < 4
        or relative.parts[:3] != ("projects", project_id, "config")
        or relative.suffix.lower() != ".json"
    ):
        raise AssertionError(
            f"{project_id}: retired validation contract path differs"
        )
    if bytes_count <= 0 or re.fullmatch(r"[0-9A-Fa-f]{64}", sha256) is None:
        raise AssertionError(
            f"{project_id}: retired validation contract identity differs"
        )


def verify_formal(project: Path, verify_hashes: bool = False, repository_root: Path | None = None) -> None:
    formal = project / "formal"
    if formal.exists():
        retired_identity = (
            legacy_identity(repository_root, project.name)
            if repository_root is not None
            else None
        )
        asset_manifest_path = formal / "asset_manifest.json"
        if not asset_manifest_path.is_file():
            raise AssertionError(f"{project.name}: formal/asset_manifest.json is missing")
        manifest = json.loads(asset_manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("schema_version") != 1 or manifest.get("role") != "formal_asset_manifest":
            raise AssertionError(f"{project.name}: invalid formal asset manifest identity")
        if manifest.get("project") != project.name:
            raise AssertionError(f"{project.name}: formal asset manifest project differs")
        source = manifest.get("source_run", {})
        source_id = source.get("run_id")
        validate_run_id(source_id)
        if source.get("path") != f"runs/{source_id}":
            raise AssertionError(f"{project.name}: formal source run path differs")
        for role in ("run_config", "summary", "run_manifest"):
            verify_record(project, source[role], verify_hashes)
        assets = manifest.get("assets", {})
        if not assets:
            raise AssertionError(f"{project.name}: formal asset manifest has no assets")
        for record in assets.values():
            verify_record(formal, record, verify_hashes)
        if repository_root is not None:
            if retired_identity is None:
                verify_record(
                    repository_root, manifest["validation_contract"], verify_hashes
                )
            else:
                verify_retired_validation_record(
                    manifest["validation_contract"], project.name
                )
        if retired_identity is None:
            for role in ("comsol_model", "solidworks_assembly"):
                if role in assets and "naming_exception" not in assets[role]:
                    validate_formal_asset_name(
                        Path(assets[role]["path"]).name, project.name
                    )


def verify_project(
    project: Path, verify_hashes: bool = False, repository_root: Path | None = None
) -> tuple[int, int]:
    unexpected = {entry.name for entry in project.iterdir()} - ALLOWED_PROJECT_ENTRIES
    if unexpected:
        raise AssertionError(f"{project.name}: unexpected top-level entries: {sorted(unexpected)}")
    if not (project / "00_README.txt").is_file():
        raise AssertionError(f"{project.name}: 00_README.txt is missing")
    verify_formal(project, verify_hashes, repository_root)

    run_count = 0
    runs = project / "runs"
    if runs.exists():
        for run in (item for item in runs.iterdir() if item.is_dir()):
            validate_run_id(run.name)
            missing = REQUIRED_RUN_FILES - {item.name for item in run.iterdir() if item.is_file()}
            if missing:
                raise AssertionError(f"{run}: missing {sorted(missing)}")
            config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))
            if config.get("run_id") != run.name or manifest.get("run_id") != run.name:
                raise AssertionError(f"{run}: folder, config, and manifest run_id differ")
            if manifest.get("schema_version") == 2:
                retention = validate_retention(config.get("artifact_retention"))
                if manifest.get("artifact_retention") != {
                    "policy_version": retention.policy_version,
                    "class": retention.class_id,
                    "reason": retention.reason,
                }:
                    raise AssertionError(f"{run}: retention identity differs")
            run_count += 1

    archive_count = 0
    archive_root = project / "archive"
    if archive_root.exists():
        for archive in (item for item in archive_root.iterdir() if item.is_dir()):
            validate_archive_id(archive.name)
            manifest_path = archive / "archive_manifest.json"
            if not manifest_path.is_file():
                raise AssertionError(f"{archive}: archive_manifest.json is missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if manifest.get("archive_id") != archive.name:
                raise AssertionError(f"{archive}: folder and manifest archive_id differ")
            if manifest.get("role") == "artifact_identity_archive_manifest":
                migration_path = archive / "identity_migration_manifest.json"
                if not migration_path.is_file():
                    raise AssertionError(f"{archive}: identity migration manifest is missing")
                migration = json.loads(migration_path.read_text(encoding="utf-8-sig"))
                try:
                    validate_plan(migration)
                    validate_identity_archive_manifest(manifest, migration)
                except ValueError as exc:
                    raise AssertionError(f"{archive}: identity migration contract differs") from exc
                if (
                    migration.get("status") != "relocated_verified"
                    or migration.get("current_project_id") != project.name
                    or migration.get("destination_root")
                    != f"{project.name}/archive/{archive.name}/legacy-project-root"
                ):
                    raise AssertionError(f"{archive}: relocated identity differs")
                pruning_path = archive / "pruning_manifest.json"
                if pruning_path.exists():
                    pruning = json.loads(pruning_path.read_text(encoding="utf-8-sig"))
                    try:
                        validate_pruning_journal(pruning, migration)
                    except ValueError as exc:
                        raise AssertionError(f"{archive}: pruning journal differs") from exc
                    if pruning.get("state") != "complete":
                        raise AssertionError(f"{archive}: pruning journal is incomplete")
                    verify_pruned_inventory(
                        migration,
                        project.parent,
                        verify_hashes=verify_hashes,
                    )
                elif manifest.get("deletion_performed"):
                    raise AssertionError(f"{archive}: pruning journal is missing")
            archive_count += 1
    scratch = project / "scratch"
    if scratch.exists():
        for task in (item for item in scratch.iterdir() if item.is_dir()):
            validate_task_id(task.name)
    return run_count, archive_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--verify-hashes", action="store_true")
    parser.add_argument("--formal-only", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--repository-root", type=Path)
    args = parser.parse_args()
    projects = args.root.resolve()
    repository_root = args.repository_root.resolve() if args.repository_root else None
    project_dirs = [project for project in projects.iterdir() if project.is_dir()]
    if args.project:
        selected = projects / args.project
        if not selected.is_dir():
            raise FileNotFoundError(f"artifact project is absent: {selected}")
        project_dirs = [selected]
    if args.formal_only:
        for project in project_dirs:
            verify_formal(project, args.verify_hashes, repository_root)
        print(f"FORMAL_ASSET_LAYOUT=PASS PROJECTS={len(project_dirs)} HASHES={args.verify_hashes}")
        return
    totals = [verify_project(project, args.verify_hashes, repository_root) for project in project_dirs]
    print(f"ARTIFACT_LAYOUT=PASS PROJECTS={len(totals)} RUNS={sum(x for x, _ in totals)} ARCHIVES={sum(y for _, y in totals)}")


if __name__ == "__main__":
    main()
