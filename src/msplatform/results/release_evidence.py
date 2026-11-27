"""Decode exact v1 historical asset inventories into neutral evidence records."""
from __future__ import annotations
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def decode_historical_release(manifest: Mapping[str, Any], manifest_record: Mapping[str, Any],
                              paths: Mapping[str, Path]) -> dict[str, Any]:
    """Describe frozen evidence only; do not infer a new qualification or publish it."""
    if (manifest.get("schema_version") != 1 or manifest.get("role") != "formal_asset_manifest"
            or not isinstance(manifest.get("project"), str) or not manifest.get("project")
            or not isinstance(manifest.get("release_id"), str) or not manifest.get("release_id")
            or not isinstance(manifest.get("assets"), dict) or not paths or not set(paths) <= set(manifest["assets"])):
        raise ValueError("historical release inventory differs")
    assets = {}
    for role in sorted(paths):
        record = manifest["assets"][role]
        path = Path(paths[role])
        if (not isinstance(role, str) or not role or not isinstance(record, dict)
                or not path.is_absolute() or type(record.get("bytes")) is not int
                or record["bytes"] < 0 or not isinstance(record.get("sha256"), str)):
            raise ValueError("historical release record differs")
        assets[role] = {"path": str(path), "bytes": record["bytes"], "sha256": record["sha256"].upper(),
                        "historical_path": record["path"]}
    return {"schema_version": 1, "role": "historical_release_evidence", "project_id": manifest["project"],
            "historical_release_id": manifest["release_id"], "source_manifest": dict(manifest_record),
            "historical_source_run": manifest.get("source_run"),
            "historical_validation_contract": manifest.get("validation_contract"),
            "selected_roles": sorted(paths), "assets": assets, "qualification": "historical_evidence_only"}
