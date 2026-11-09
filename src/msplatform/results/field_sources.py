"""Read terminal single-reflection field producer identities without execution or payload scans."""
from __future__ import annotations
import json
from pathlib import Path
from msplatform.io.manifest_records import record_path, verify_record, require_completed_terminal_publication


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))



def _require_field_source_binding(records: list[dict], source: Path, identity: dict, producer: Path) -> None:
    matches = [record for record in records if record_path(record, base_dir=producer) == source]
    if (len(matches) != 1 or matches[0].get("bytes") != identity["bytes"]
            or str(matches[0].get("sha256", "")).upper() != identity["sha256"].upper()):
        raise ValueError(f"field source is not uniquely identity-bound by its producer manifest: {source}")

def _source_identity_path(records: list[dict], identity: dict, producer: Path) -> Path:
    """Find the receipt producer's frozen scientific input by its bound identity."""
    owner_inputs = (producer / "inputs").resolve()
    matches = []
    for record in records:
        if (record.get("bytes") != identity.get("bytes")
                or str(record.get("sha256", "")).upper() != str(identity.get("sha256", "")).upper()):
            continue
        path = record_path(record, base_dir=producer)
        if path.is_relative_to(owner_inputs):
            matches.append(path)
    if len(matches) != 1:
        raise ValueError("frontend field identity is not uniquely bound by its receipt producer manifest")
    return matches[0]

def _read_field_source_manifest(producer: Path, *, statuses: set[str] | None = None,
                                stopped_receipt: dict | None = None, retention_classifier=None) -> dict:
    """Validate a managed source run without scanning its output payloads."""
    manifest_path = producer / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("field source requires its managed producer run manifest")
    require_completed_terminal_publication(manifest_path)
    manifest = _read(manifest_path)
    allowed = {"success", "failed", "interrupted", "superseded"} if statuses is None else statuses
    if (manifest.get("schema_version") != 2 or manifest.get("role") != "simulation_run_manifest"
            or manifest.get("status") not in allowed):
        raise ValueError("field source producer must have a terminal current run manifest")
    config_record = manifest.get("run_config", {})
    if manifest["status"] == "checkpoint" and stopped_receipt is not None:
        if (not isinstance(stopped_receipt, dict) or stopped_receipt.get("schema_version") != 1
                or stopped_receipt.get("role") != "run_capacity_lifecycle_receipt"
                or stopped_receipt.get("action") != "seal_stopped_payload"
                or stopped_receipt.get("status") != "ready" or stopped_receipt.get("run_status") != "checkpoint"
                or Path(str(stopped_receipt.get("run_directory", ""))).resolve() != producer.resolve()):
            raise ValueError("field continuation requires its public stopped checkpoint receipt")
        # Initialization manifests precede code/input freezing. Only the public
        # stopped receipt binds the final config; it grants no completed output.
        config_record = stopped_receipt.get("run_config", {})
    if (not config_record.get("path")
            or record_path(config_record, base_dir=producer) != producer / "run_config.json"):
        raise ValueError("field source producer manifest must bind its local run_config")
    verify_record("field source producer run_config", config_record, base_dir=producer, retention_classifier=retention_classifier)
    config = _read(producer / "run_config.json")
    if (config.get("schema_version") != 2 or config.get("project") != "instrument_assembly"
            or any(config.get(key) != manifest.get(key) for key in ("run_id", "project", "mode"))
            or manifest.get("run_id") != producer.name):
        raise ValueError("field source producer managed run identity differs")
    return manifest
