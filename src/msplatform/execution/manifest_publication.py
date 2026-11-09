"""The original manifest builder with explicit retention callbacks; publishing uses one journal."""
from __future__ import annotations
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from msplatform.execution.artifact_naming import validate_run_id
from msplatform.io.manifest_records import file_record, _json_bytes
from msplatform.execution.terminal_publication import TERMINAL_LOCK_NAME
from msplatform.io.manifest_records import TERMINAL_JOURNAL_NAME


def resolve_path(value: str, base: Path, project_root: Path | None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    root = project_root if project_root is not None else base
    return (root / path).resolve()


def build_run_manifest(
    run_config_path: Path,
    status: str,
    *,
    retention_api: Callable[[], tuple[Any, Any, Any, Any]] | None = None,
    software: list[str] | None = None,
    output_paths: list[Path] | None = None,
    actual_root: Path | None = None,
    recorded_root: Path | None = None,
    virtual_documents: dict[Path, dict[str, Any]] | None = None,
    extra_fields: dict[str, Any] | None = None,
    allow_missing_inputs: bool = False,
) -> dict[str, Any]:
    """Build one manifest without publishing it.

    ``virtual_documents`` describes final JSON bytes which are not published yet;
    this lets a terminal summary and its manifest enter one durable journal.
    """

    def retention_classifier(*args: Any, **kwargs: Any) -> str:
        if retention_api is None:
            raise ValueError("manifest requires its explicit retention policy")
        return retention_api()[0](*args, **kwargs)

    run_config_path = run_config_path.resolve()
    run_config = json.loads(run_config_path.read_text(encoding="utf-8-sig"))
    run_id = run_config.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("run_config.json must contain a string run_id")
    validate_run_id(run_id)
    project_root_value = run_config.get("project_root")
    project_root = Path(project_root_value).resolve() if project_root_value else None
    base = run_config_path.parent
    actual_root = (actual_root or base).resolve()
    recorded_root = (recorded_root or base).resolve()
    virtual = {path.resolve(): value for path, value in (virtual_documents or {}).items()}

    def actual_and_recorded(path: Path) -> tuple[Path, Path]:
        resolved = path.resolve()
        try:
            return actual_root / resolved.relative_to(recorded_root), resolved
        except ValueError:
            try:
                return resolved, recorded_root / resolved.relative_to(actual_root)
            except ValueError:
                return resolved, resolved

    retention = None
    if run_config.get("schema_version") == 2:
        if retention_api is None:
            raise ValueError("manifest requires its explicit retention policy")
        (
            classify_file,
            load_failed_recovery_exemptions,
            validate_retained_files,
            validate_retention,
        ) = retention_api()
        retention = validate_retention(run_config.get("artifact_retention"))

    identity_cache: dict[tuple[Any, ...], tuple[int, str]] = {}
    inputs: dict[str, dict[str, Any]] = {}
    for name, value in run_config.get("inputs", {}).items():
        if isinstance(value, str):
            declared = resolve_path(value, base, project_root)
            actual, recorded = actual_and_recorded(declared)
            input_role = classify_file(actual) if retention is not None and actual.is_file() else None
            inputs[name] = file_record(actual, input_role, recorded_path=recorded,
                _identity_cache=identity_cache, retention_classifier=retention_classifier)
    lock_paths = {(actual_root / TERMINAL_LOCK_NAME).resolve(), (recorded_root / TERMINAL_LOCK_NAME).resolve()}
    resolved_outputs = [
        resolved for path in (output_paths or [])
        if (resolved := resolve_path(str(path), base, project_root)) not in lock_paths
    ]
    if retention is not None and status not in {"interrupted", "checkpoint"}:
        run_files = [
            path
            for path in actual_root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.name not in {"run_manifest.json", TERMINAL_JOURNAL_NAME}
        ]
        exemptions = (
            load_failed_recovery_exemptions(actual_root, retention)
            if status == "failed"
            else set()
        )
        validate_retained_files(retention, run_files, exempt_paths=exemptions)
    outputs = []
    for declared in resolved_outputs:
        actual, recorded = actual_and_recorded(declared)
        document = virtual.get(actual.resolve()) or virtual.get(declared)
        role = None
        if retention is not None and (document is not None or actual.is_file()):
            byte_count = len(_json_bytes(document)) if document is not None else None
            role = classify_file(actual, bytes_count=byte_count)
        outputs.append(
            file_record(
                actual,
                role,
                recorded_path=recorded,
                document=document,
                _identity_cache=identity_cache, retention_classifier=retention_classifier,
            )
        )
    missing_inputs = [name for name, record in inputs.items() if not record["exists"]]
    if missing_inputs and not allow_missing_inputs:
        raise ValueError(f"missing run inputs: {', '.join(missing_inputs)}")

    manifest = {
        "schema_version": 2 if retention is not None else 1,
        "role": "simulation_run_manifest",
        "run_id": run_id,
        "project": run_config.get("project"),
        "mode": run_config.get("mode"),
        "status": status,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": platform.node(),
        "python": platform.python_version(),
        "software": software or [],
        "run_config": file_record(
            run_config_path,
            recorded_path=recorded_root / "run_config.json",
            _identity_cache=identity_cache, retention_classifier=retention_classifier,
        ),
        "inputs": inputs,
        "outputs": outputs,
        "formal_eligible": bool(run_config.get("formal_gate_passed", False))
        and status == "success"
        and all(item["exists"] for item in outputs),
    }
    if retention is not None:
        manifest["artifact_retention"] = {
            "policy_version": retention.policy_version,
            "class": retention.class_id,
            "reason": retention.reason,
        }
    manifest.update(extra_fields or {})
    return manifest
