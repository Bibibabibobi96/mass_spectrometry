"""Small isolated source/policy fixture for real RF owner admission tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def capacity_fixture_source(repository: Path, destination: Path) -> Path:
    """Copy existing code/config once, with test-only bounded disk watermarks.

    The real SQLite ledger, capacity admission and original failure propagation
    remain active. No source solver payload or production policy is modified.
    """
    if destination.exists():
        return destination
    for relative in ("common", "config", "projects/rf_multipole_ion_optics"):
        shutil.copytree(repository / relative, destination / relative,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.mph", "*.pa0", "*.pa#"))
    registry = json.loads((repository / "config/project_registry.json").read_text(encoding="utf-8"))
    project = next(row for row in registry["projects"] if row["project_id"] == "rf_multipole_ion_optics")
    for record in project["retired_project_descriptors"]:
        target = destination / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / record["path"], target)
    policy = destination / "common/contracts/artifact_capacity_policy.json"
    document = json.loads(policy.read_text(encoding="utf-8"))
    document.update(target_gib=.125, minimum_free_gib=0)
    policy.write_text(json.dumps(document), encoding="utf-8")
    return destination
