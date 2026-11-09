"""Read manifest-bound SFI inherited case identities; never plan or execute replay."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any,Mapping
from msplatform.io.manifest_records import record_path,file_record,verify_record


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _identity(record: Mapping[str, Any], label: str) -> tuple[int, str]:
    size, digest = record.get("bytes"), record.get("sha256")
    if type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{label} identity is invalid")
    return size, digest.upper()


def _manifest_records(manifest: Mapping[str, Any]) -> dict[Path, tuple[int, str]]:
    inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        raise ValueError("single-reflection continuation parent manifest records are invalid")
    records: dict[Path, tuple[int, str]] = {}
    for record in [*inputs.values(), *outputs]:
        if not isinstance(record, Mapping):
            raise ValueError("single-reflection continuation parent manifest record is invalid")
        path = record_path(dict(record)).resolve()
        identity = _identity(record, "parent manifest")
        previous = records.setdefault(path, identity)
        if previous != identity:
            raise ValueError("single-reflection continuation parent manifest has conflicting records")
    return records


def _parent(preparation: Mapping[str, Any], *, retention_classifier=None) -> tuple[Path, dict[str, Any], dict[Path, tuple[int, str]], dict[str, Any]]:
    record = preparation.get("input_records", {}).get("continuation_parent_manifest")
    if not isinstance(record, dict) or not isinstance(record.get("source_path"), str):
        raise ValueError("single-reflection continuation requires a frozen parent manifest")
    try:
        verify_record("frozen continuation parent manifest", record, retention_classifier=retention_classifier)
    except AssertionError as error:
        raise ValueError("single-reflection continuation frozen parent manifest differs") from error
    parent_manifest = Path(record["source_path"]).resolve()
    if parent_manifest.name != "run_manifest.json" or not parent_manifest.is_file():
        raise ValueError("single-reflection continuation parent manifest source path is invalid")
    if _identity(file_record(parent_manifest,retention_classifier=retention_classifier), "parent manifest") != _identity(record, "frozen parent manifest"):
        raise ValueError("single-reflection continuation parent manifest differs from its frozen input")
    manifest = _read(record_path(record), "frozen continuation parent manifest")
    return parent_manifest.parent, manifest, _manifest_records(manifest), record


def parent_case_records(preparation: Mapping[str, Any], workbench: Mapping[str, Any],
                        case: Mapping[str, Any], *, replay: bool = False, retention_classifier=None) -> dict[Path, dict[str, Any]]:
    """Authorize only exact reused artifacts from the published common phase plan."""
    binding = case.get("replay_continuation_source" if replay else "continuation_source")
    if binding is None:
        return {}
    planned = workbench.get("replay_continuation" if replay else "continuation")
    if not isinstance(planned, Mapping):
        raise ValueError("parent case lacks its explicit continuation plan")
    parent, _, records, _ = _parent(preparation,retention_classifier=retention_classifier)
    plan_record = planned["plan_record"]
    verify_record("whole-unit continuation plan", plan_record,retention_classifier=retention_classifier)
    plan = _read(record_path(plan_record), "whole-unit continuation plan")
    units = [unit for unit in plan["units"] if unit["key"] == case["case_id"]]
    if len(units) != 1 or units[0] != binding or binding.get("action") != "reuse":
        raise ValueError("parent case differs from explicit common reuse plan")
    if Path(plan["predecessor"]["run_dir"]).resolve() != parent:
        raise ValueError("parent case continuation owner differs")
    allowed = {}
    for artifact in binding["terminal_outputs"]:
        path = Path(artifact["path"]).resolve()
        if not Path(artifact["path"]).is_absolute() or plan.get("schema_version") != 2:
            raise ValueError("parent case requires the current absolute whole-unit plan")
        identity = records.get(path)
        if identity is None or identity[1] != artifact["sha256"].upper():
            raise ValueError("parent case artifact is not manifest-bound")
        record = dict(path=str(path), exists=True, bytes=identity[0], sha256=identity[1])
        verify_record("reused artifact", record,retention_classifier=retention_classifier)
        allowed[path] = record
    return allowed
