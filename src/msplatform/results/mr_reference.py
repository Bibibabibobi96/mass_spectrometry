"""Read manifest-bound MR reference evidence without loading native payloads."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import record_path
from msplatform.io.manifest_records import verify_record


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def verified_reference(run: Path, relative: str, *, required_status: str = "success") -> Path:
    """Verify the exact consumed record without loading historical field payloads."""
    manifest = _read(run / "run_manifest.json")
    if (required_status not in {"success", "interrupted"}
            or manifest.get("project") != "multi_reflection_tof" or manifest.get("status") != required_status):
        raise ValueError(f"reference must be an MR run with status {required_status}")
    verify_record("reference run config", manifest["run_config"], base_dir=run)
    config = _read(record_path(manifest["run_config"], base_dir=run))
    desired = (run / relative).resolve()
    config_records = [record for record in config.get("inputs", {}).values()
                      if isinstance(record, dict) and {"path", "bytes", "sha256"} <= record.keys()]
    records = [*manifest.get("inputs", {}).values(), *config_records, *manifest["outputs"]]
    matches = [record for record in records if record_path(record, base_dir=run) == desired]
    if not matches:
        raise ValueError(f"reference manifest does not bind {relative}")
    for record in matches:
        verify_record("consumed MR reference", record, base_dir=run)
    return desired


def _identity(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "bytes": path.stat().st_size}


def _bound_file(identity: dict[str, Any], relative_to: Path) -> Path:
    path = Path(identity["path"])
    if not path.is_absolute():
        path = relative_to / path
    if file_sha256(path).lower() != identity["sha256"].lower():
        raise ValueError(f"Bound source SHA-256 differs: {path}")
    if path.stat().st_size != identity["bytes"]:
        raise ValueError(f"Bound source byte count differs: {path}")
    return path


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)
