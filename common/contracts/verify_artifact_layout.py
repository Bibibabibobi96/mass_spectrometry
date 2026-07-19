"""Verify the live artifact v2 structure without reading large binary content."""

from __future__ import annotations

import argparse
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


def verify_project(project: Path) -> tuple[int, int]:
    unexpected = {entry.name for entry in project.iterdir()} - ALLOWED_PROJECT_ENTRIES
    if unexpected:
        raise AssertionError(f"{project.name}: unexpected top-level entries: {sorted(unexpected)}")
    if not (project / "00_README.txt").is_file():
        raise AssertionError(f"{project.name}: 00_README.txt is missing")
    formal = project / "formal"
    if formal.exists():
        asset_manifest_path = formal / "asset_manifest.json"
        if not asset_manifest_path.is_file():
            raise AssertionError(f"{project.name}: formal/asset_manifest.json is missing")
        assets = json.loads(asset_manifest_path.read_text(encoding="utf-8-sig")).get("assets", {})
        for role in ("comsol_model", "solidworks_assembly"):
            if role in assets:
                validate_formal_asset_name(Path(assets[role]["path"]).name, project.name)

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
    args = parser.parse_args()
    projects = args.root.resolve()
    totals = [verify_project(project) for project in projects.iterdir() if project.is_dir()]
    print(f"ARTIFACT_LAYOUT=PASS PROJECTS={len(totals)} RUNS={sum(x for x, _ in totals)} ARCHIVES={sum(y for _, y in totals)}")


if __name__ == "__main__":
    main()
