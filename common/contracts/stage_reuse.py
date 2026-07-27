"""Single-parent, content-addressed reuse of successful run stages."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, TypeAlias

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256


SCHEMA_VERSION = 1
RECEIPT_ROLE = "successful_stage_receipt"
PROVENANCE_ROLE = "stage_reuse_provenance"
CONTEXT_CATEGORIES = ("inputs", "source", "solver")
TERMINAL_STATUSES = ("success", "failed")
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

PathMap: TypeAlias = Mapping[str, str | Path]
ContextPaths: TypeAlias = Mapping[str, PathMap]

class StageReuseError(ValueError):
    """Raised when stage reuse identity or evidence is incomplete."""

def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageReuseError(f"{description} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise StageReuseError(f"{description} must be a JSON object")
    return value

def _identifier(value: Any, description: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise StageReuseError(f"{description} must match {IDENTIFIER_PATTERN.pattern}: {value!r}")
    return value

def _inside_file(path: str | Path, root: Path, description: str) -> Path:
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError as exc:
        raise StageReuseError(f"{description} is missing: {path}") from exc
    if not resolved.is_file():
        raise StageReuseError(f"{description} must be a file: {resolved}")
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise StageReuseError(f"{description} must be inside run root: {resolved}") from exc
    return resolved

def _record(path: str | Path, root: Path, description: str) -> dict[str, Any]:
    resolved = _inside_file(path, root, description)
    return {
        "path": resolved.relative_to(root).as_posix(), "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }

def _verify_relative_record(
    value: Any,
    root: Path,
    description: str,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"path", "bytes", "sha256"}:
        raise StageReuseError(f"{description} record fields are invalid")
    relative = value["path"]
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise StageReuseError(f"{description}.path must be relative")
    path = _inside_file(root / relative, root, description)
    if value["bytes"] != path.stat().st_size:
        raise StageReuseError(f"{description} byte count changed")
    sha256 = value["sha256"]
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9A-F]{64}", sha256):
        raise StageReuseError(f"{description}.sha256 must be uppercase SHA-256")
    if file_sha256(path) != sha256:
        raise StageReuseError(f"{description} SHA-256 changed")
    return path, dict(value)

def _manifest_binds(
    manifest: dict[str, Any],
    path: Path,
    expected: dict[str, Any],
) -> bool:
    records = list(manifest.get("inputs", {}).values()) + list(manifest.get("outputs", []))
    for record in records:
        if not isinstance(record, dict):
            continue
        recorded_path = Path(str(record.get("path", ""))).resolve()
        if (
            recorded_path == path
            and record.get("bytes") == expected["bytes"]
            and str(record.get("sha256", "")).upper() == expected["sha256"]
        ):
            return True
    return False

def _stage_is_success(summary: dict[str, Any], stage_id: str) -> None:
    stages = summary.get("stages")
    if not isinstance(stages, list):
        raise StageReuseError("parent summary must contain a stages array")
    matches = [
        stage for stage in stages
        if isinstance(stage, dict) and stage.get("stage_id") == stage_id
    ]
    if len(matches) != 1 or matches[0].get("status") != "success":
        raise StageReuseError(f"parent summary must mark exactly one {stage_id!r} stage as success")

def _validate_context(context: ContextPaths) -> None:
    if not isinstance(context, Mapping) or set(context) != set(CONTEXT_CATEGORIES):
        raise StageReuseError(f"context categories must be exactly {', '.join(CONTEXT_CATEGORIES)}")
    for category in CONTEXT_CATEGORIES:
        entries = context[category]
        if not isinstance(entries, Mapping) or not entries:
            raise StageReuseError(f"context category {category!r} must not be empty")
        for name in entries:
            _identifier(name, f"{category} identity name")

def _context_records(context: ContextPaths, root: Path) -> dict[str, Any]:
    _validate_context(context)
    return {
        category: {
            name: _record(path, root, f"{category} identity {name!r}")
            for name, path in sorted(context[category].items())
        } for category in CONTEXT_CATEGORIES
    }

def _declared_child_inputs(config: dict[str, Any], current_root: Path) -> dict[str, Path]:
    inputs = config.get("inputs")
    if not isinstance(inputs, dict):
        raise StageReuseError("current run config must declare an inputs object")
    project_root_value = config.get("project_root")
    base = Path(project_root_value).resolve() if project_root_value else current_root
    declared: dict[str, Path] = {}
    for name, value in inputs.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise StageReuseError("current run config inputs must map names to paths")
        path = Path(value)
        declared[name] = path.resolve() if path.is_absolute() else (base / path).resolve()
    return declared

def _validate_live_manifest(root: Path, project: str) -> None:
    manifest = _load_json(root / "run_manifest.json", "live run manifest")
    summary = _load_json(root / "summary.json", "live run summary")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("role") != "simulation_run_manifest"
        or manifest.get("run_id") != root.name
        or manifest.get("project") != project
        or manifest.get("status") != "interrupted"
        or manifest.get("lifecycle_state") != "provisional"
        or summary.get("status") not in {"interrupted", "running"}
    ):
        raise StageReuseError("existing run manifest is not a live provisional manifest")

def write_stage_receipt(
    run_root: str | Path,
    *,
    project: str,
    stage_id: str,
    context: ContextPaths,
    outputs: PathMap,
    allow_provisional_manifest: bool = False,
) -> Path:
    """Write a receipt before the parent run's final manifest is created."""
    root = Path(run_root).resolve(strict=True)
    if (root / "run_manifest.json").exists():
        if not allow_provisional_manifest:
            raise StageReuseError("stage receipt cannot be added after the final run manifest")
        _validate_live_manifest(root, project)
    run_config = _load_json(root / "run_config.json", "run config")
    summary = _load_json(root / "summary.json", "run summary")
    run_id = run_config.get("run_id")
    if not isinstance(run_id, str):
        raise StageReuseError("run config must contain a string run_id")
    validate_run_id(run_id)
    if root.name != run_id or run_config.get("project") != project:
        raise StageReuseError("run config identity does not match receipt request")
    stage = _identifier(stage_id, "stage_id")
    _stage_is_success(summary, stage)
    if not isinstance(outputs, Mapping) or not outputs:
        raise StageReuseError("stage outputs must not be empty")
    output_records: dict[str, Any] = {}
    for name, path in sorted(outputs.items()):
        _identifier(name, "stage output name")
        output_records[name] = _record(path, root, f"stage output {name!r}")
    receipt = {
        "schema_version": SCHEMA_VERSION, "role": RECEIPT_ROLE,
        "project": project, "run_id": run_id, "stage_id": stage, "status": "success",
        "context": _context_records(context, root), "outputs": output_records,
    }
    destination = root / "stage_receipts" / f"{stage}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination

def _validate_parent(root: Path, project: str) -> tuple[dict[str, Any], dict[str, Any]]:
    config_path = root / "run_config.json"
    summary_path = root / "summary.json"
    manifest_path = root / "run_manifest.json"
    config = _load_json(config_path, "parent run config")
    summary = _load_json(summary_path, "parent summary")
    manifest = _load_json(manifest_path, "parent manifest")
    run_id = config.get("run_id")
    if not isinstance(run_id, str):
        raise StageReuseError("parent run config must contain a string run_id")
    validate_run_id(run_id)
    if root.name != run_id or config.get("project") != project:
        raise StageReuseError("parent run config identity does not match")
    manifest_identity = (
        manifest.get("schema_version"), manifest.get("role"),
        manifest.get("run_id"), manifest.get("project"),
    )
    if manifest_identity != (1, "simulation_run_manifest", run_id, project):
        raise StageReuseError("parent manifest identity does not match")
    status = manifest.get("status")
    if status not in TERMINAL_STATUSES or summary.get("status") != status:
        raise StageReuseError("parent summary and manifest must share a reusable terminal status")
    config_record = manifest.get("run_config")
    actual_config = _record(config_path, root, "parent run_config")
    if (
        not isinstance(config_record, dict)
        or Path(str(config_record.get("path", ""))).resolve() != config_path
        or config_record.get("bytes") != actual_config["bytes"]
        or str(config_record.get("sha256", "")).upper() != actual_config["sha256"]
    ):
        raise StageReuseError("parent manifest run_config identity changed")
    summary_record = _record(summary_path, root, "parent summary")
    if not _manifest_binds(manifest, summary_path, summary_record):
        raise StageReuseError("parent summary is not hash-bound by parent manifest")
    return summary, manifest

def _validate_receipt(
    root: Path,
    project: str,
    stage_id: str,
    summary: dict[str, Any],
    manifest: dict[str, Any],
    current_context: ContextPaths,
    current_root: Path,
) -> dict[str, Any]:
    receipt_path = root / "stage_receipts" / f"{stage_id}.json"
    receipt = _load_json(receipt_path, f"stage receipt {stage_id!r}")
    expected_fields = {
        "schema_version", "role", "project", "run_id", "stage_id", "status", "context", "outputs"
    }
    if set(receipt) != expected_fields or (
        receipt["schema_version"],
        receipt["role"],
        receipt["project"],
        receipt["run_id"],
        receipt["stage_id"],
        receipt["status"],
    ) != (SCHEMA_VERSION, RECEIPT_ROLE, project, root.name, stage_id, "success"):
        raise StageReuseError(f"stage receipt {stage_id!r} identity is invalid")
    _stage_is_success(summary, stage_id)
    receipt_record = _record(receipt_path, root, f"stage receipt {stage_id!r}")
    if not _manifest_binds(manifest, receipt_path, receipt_record):
        raise StageReuseError(f"stage receipt {stage_id!r} is not bound by parent manifest")
    _validate_context(current_context)
    parent_context = receipt["context"]
    if not isinstance(parent_context, dict) or set(parent_context) != set(CONTEXT_CATEGORIES):
        raise StageReuseError("parent receipt context categories are invalid")
    compared: dict[str, Any] = {}
    for category in CONTEXT_CATEGORIES:
        if not isinstance(parent_context[category], dict) or set(
            parent_context[category]
        ) != set(current_context[category]):
            raise StageReuseError(f"{category} identity keys do not match parent")
        compared[category] = {}
        for name, value in sorted(parent_context[category].items()):
            parent_path, parent_record = _verify_relative_record(
                value, root, f"parent {category} identity {name!r}"
            )
            if not _manifest_binds(manifest, parent_path, parent_record):
                raise StageReuseError(f"parent {category} identity {name!r} is not manifest-bound")
            current_record = _record(
                current_context[category][name],
                current_root,
                f"current {category} identity {name!r}",
            )
            if (parent_record["bytes"], parent_record["sha256"]) != (
                current_record["bytes"], current_record["sha256"]
            ):
                raise StageReuseError(f"{category} identity {name!r} changed")
            compared[category][name] = {
                "parent": parent_record,
                "current": current_record,
            }
    outputs: dict[str, Any] = {}
    if not isinstance(receipt["outputs"], dict) or not receipt["outputs"]:
        raise StageReuseError("parent receipt outputs are invalid")
    for name, value in sorted(receipt["outputs"].items()):
        path, record = _verify_relative_record(value, root, f"parent output {name!r}")
        if not _manifest_binds(manifest, path, record):
            raise StageReuseError(f"parent output {name!r} is not manifest-bound")
        outputs[name] = record
    return {"stage_id": stage_id, "receipt": receipt_record, "context": compared, "outputs": outputs}

def validate_and_write_stage_reuse(
    current_run_root: str | Path,
    *,
    parent_run_root: str | Path,
    project: str,
    stage_contexts: Mapping[str, ContextPaths],
    allow_provisional_manifest: bool = False,
) -> Path:
    """Validate one parent and publish child-run provenance."""
    current_root = Path(current_run_root).resolve(strict=True)
    parent_root = Path(parent_run_root).resolve(strict=True)
    if current_root == parent_root:
        raise StageReuseError("current and parent run roots must be different")
    if (current_root / "run_manifest.json").exists():
        if not allow_provisional_manifest:
            raise StageReuseError("current run is already finalized by run_manifest.json")
        _validate_live_manifest(current_root, project)
    current_config = _load_json(current_root / "run_config.json", "current run config")
    current_run_id = current_config.get("run_id")
    if not isinstance(current_run_id, str):
        raise StageReuseError("current run config must contain a string run_id")
    validate_run_id(current_run_id)
    if current_root.name != current_run_id or current_config.get("project") != project:
        raise StageReuseError("current run config identity does not match")
    if current_run_id == parent_root.name:
        raise StageReuseError("current and parent run IDs must be different")
    if not isinstance(stage_contexts, Mapping) or not stage_contexts:
        raise StageReuseError("at least one stage must be requested")
    declared_inputs = _declared_child_inputs(current_config, current_root)
    for category, entries in stage_contexts.items():
        _identifier(category, "stage_id")
        _validate_context(entries)
        for identity_paths in entries.values():
            for path in identity_paths.values():
                if Path(path).resolve(strict=True) not in declared_inputs.values():
                    raise StageReuseError("current context is not declared by current run_config.inputs")
    destination = current_root / "inputs" / "stage_reuse_provenance.json"
    if declared_inputs.get("stage_reuse_provenance") != destination:
        raise StageReuseError(
            "current run_config.inputs must predeclare stage_reuse_provenance"
        )
    summary, manifest = _validate_parent(parent_root, project)
    stages = [
        _validate_receipt(
            parent_root, project, _identifier(stage_id, "stage_id"),
            summary, manifest, context, current_root,
        ) for stage_id, context in sorted(stage_contexts.items())
    ]
    parent_manifest = parent_root / "run_manifest.json"
    provenance = {
        "schema_version": SCHEMA_VERSION, "role": PROVENANCE_ROLE, "project": project,
        "run_id": current_run_id, "parent_run_id": parent_root.name,
        "parent_run_status": manifest["status"],
        "parent_manifest": {
            "bytes": parent_manifest.stat().st_size, "sha256": file_sha256(parent_manifest)
        },
        "reused_stages": stages,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(provenance, indent=2, ensure_ascii=False) + "\n"
    if destination.exists():
        if destination.read_text(encoding="utf-8-sig") != serialized:
            raise StageReuseError(f"reuse provenance already exists with different content: {destination}")
        return destination
    destination.write_text(serialized, encoding="utf-8")
    return destination
