"""Read manifest-bound MR reference evidence without loading native payloads."""
from __future__ import annotations

import json
from pathlib import Path

from msplatform.io.manifest_records import record_path
from msplatform.execution.retention import verify_record


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
