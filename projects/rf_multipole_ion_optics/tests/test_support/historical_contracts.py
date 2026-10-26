"""Read exact retired contract sources without consulting active replacements."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


def historical_path(project_root: Path, source_path: str) -> Path:
    """Return one manifest-bound source after checking its frozen bytes and SHA."""
    archive_root = project_root / "docs/history/retired_projects"
    manifest = json.loads(
        (archive_root / "migration_manifest.json").read_text(encoding="utf-8")
    )
    matches = [
        entry for entry in manifest["entries"]
        if entry["source_path"] == source_path
    ]
    if len(matches) != 1:
        raise AssertionError(f"Historical source must have one frozen mapping: {source_path}")
    entry = matches[0]
    path = archive_root / entry["archive_path"]
    data = path.read_bytes()
    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"].lower():
        raise AssertionError(f"Historical source identity differs: {source_path}")
    return path


def historical_source_exists(project_root: Path, source_path: str) -> bool:
    """Check old source presence, without claiming its recorded SHA is current.

    Frozen scientific payloads retain manifest byte validation. Ordinary source
    remains in the manifest's fixed Git context; no active checkout fallback is
    permitted. This does not establish preregistered implementation equivalence.
    """
    manifest = json.loads(
        (project_root / "docs/history/retired_projects/migration_manifest.json")
        .read_text(encoding="utf-8")
    )
    if any(entry["source_path"] == source_path for entry in manifest["entries"]):
        return historical_path(project_root, source_path).is_file()
    source_commit = manifest["source_commit"]
    if not re.fullmatch(r"[0-9a-fA-F]{40}", source_commit):
        raise AssertionError("Historical Git context must be one full commit SHA")
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{source_commit}:{source_path}"],
        cwd=project_root.parents[1], capture_output=True, check=False, timeout=30,
    )
    return result.returncode == 0
