"""Verify artifact v2 structure; hash large formal assets only when requested."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from artifact_naming import (
    validate_archive_id,
    validate_formal_asset_name,
    validate_run_id,
    validate_task_id,
)


ALLOWED_PROJECT_ENTRIES = {"00_README.txt", "formal", "runs", "archive", "scratch"}
REQUIRED_RUN_FILES = {"run_config.json", "summary.json", "run_manifest.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


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
    if verify_hashes and sha256(path) != record["sha256"]:
        raise AssertionError(f"manifest SHA-256 differs: {path}")
    return path


def verify_formal(project: Path, verify_hashes: bool = False, repository_root: Path | None = None) -> None:
    formal = project / "formal"
    if formal.exists():
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
            verify_record(repository_root, manifest["validation_contract"], verify_hashes)
        for role in ("comsol_model", "solidworks_assembly"):
            if role in assets and "naming_exception" not in assets[role]:
                validate_formal_asset_name(Path(assets[role]["path"]).name, project.name)


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
    parser.add_argument("--repository-root", type=Path)
    args = parser.parse_args()
    projects = args.root.resolve()
    repository_root = args.repository_root.resolve() if args.repository_root else None
    project_dirs = [project for project in projects.iterdir() if project.is_dir()]
    if args.formal_only:
        for project in project_dirs:
            verify_formal(project, args.verify_hashes, repository_root)
        print(f"FORMAL_ASSET_LAYOUT=PASS PROJECTS={len(project_dirs)} HASHES={args.verify_hashes}")
        return
    totals = [verify_project(project, args.verify_hashes, repository_root) for project in project_dirs]
    print(f"ARTIFACT_LAYOUT=PASS PROJECTS={len(totals)} RUNS={sum(x for x, _ in totals)} ARCHIVES={sum(y for _, y in totals)}")


if __name__ == "__main__":
    main()
