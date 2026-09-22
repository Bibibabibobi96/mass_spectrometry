"""Transactional manifest lifecycle shared by integration analysis publishers."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.machine_contracts import ContractError
from common.contracts.file_identity import file_sha256
from common.contracts.recorded_file_removal import write_json_atomic
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import (
    build_run_manifest,
    publish_terminal_state,
    require_completed_terminal_publication,
)


def load_json(path: Path, label: str) -> dict[str, Any]:
    if path.name == "run_manifest.json":
        require_completed_terminal_publication(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot load {label}: {path}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def verified_record(label: str, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ContractError(f"{label} record is missing")
    try:
        verify_record(label, record)
    except (AssertionError, KeyError, TypeError) as error:
        raise ContractError(f"{label} record identity failed: {error}") from error
    return record


def record_for_path(records: Any, path: Path, label: str) -> dict[str, Any]:
    iterable = records.values() if isinstance(records, Mapping) else records
    if not isinstance(iterable, (list, tuple, type({}.values()))):
        raise ContractError(f"{label} records are invalid")
    matches = [
        record
        for record in iterable
        if isinstance(record, dict)
        and Path(str(record.get("path", ""))).resolve() == path.resolve()
    ]
    if len(matches) != 1:
        raise ContractError(f"{label} is not bound exactly once")
    return verified_record(label, matches[0])


def portable_path(
    path: Path,
    workspace_root: Path,
    *,
    outside_message: str = "path is outside workspace",
) -> str:
    """Return a portable workspace-relative provenance path."""
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise ContractError(f"{outside_message}: {path}") from error


def freeze_repository_inputs(
    paths: Mapping[str, Path], *, repo_root: Path, run_dir: Path
) -> dict[str, Path]:
    """Copy mutable repository inputs into one run-local provenance snapshot."""

    repo_root = repo_root.resolve()
    frozen: dict[str, Path] = {}
    for name, source in paths.items():
        source = source.resolve()
        try:
            relative = source.relative_to(repo_root)
        except ValueError:
            frozen[name] = source
            continue
        destination = run_dir / "inputs" / "repository_snapshot" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if (
            destination.stat().st_size != source.stat().st_size
            or file_sha256(destination) != file_sha256(source)
        ):
            raise ContractError(f"repository input snapshot identity failed: {source}")
        frozen[name] = destination
    return frozen


def write_pending_json(path: Path, value: Mapping[str, Any]) -> None:
    write_json_atomic(path, dict(value))


def publish_manifest(
    *,
    repo_root: Path,
    run_config: Path,
    manifest_path: Path,
    status: str,
    outputs: Sequence[Path],
    project: str,
    mode: str,
    label: str,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    final_outputs = list(outputs)
    summary_path = run_config.with_name("summary.json")
    if summary is not None and summary_path not in final_outputs:
        final_outputs.append(summary_path)
    manifest = build_run_manifest(
        run_config,
        status,
        software=[f"Python {sys.version_info.major}.{sys.version_info.minor}"],
        output_paths=final_outputs,
        virtual_documents={summary_path: dict(summary)} if summary is not None else None,
    )
    if summary is None:
        write_json_atomic(manifest_path, manifest)
    else:
        publish_terminal_state(run_config.parent, dict(summary), manifest)
    return _verify_published_manifest(
        run_config=run_config,
        manifest_path=manifest_path,
        status=status,
        outputs=final_outputs,
        project=project,
        mode=mode,
        label=label,
    )


def _verify_published_manifest(
    *,
    run_config: Path,
    manifest_path: Path,
    status: str,
    outputs: Sequence[Path],
    project: str,
    mode: str,
    label: str,
) -> dict[str, Any]:
    require_completed_terminal_publication(manifest_path)
    manifest = load_json(manifest_path, f"{label} {status} manifest")
    config = load_json(run_config, f"{label} run_config")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != status
        or manifest.get("run_id") != config.get("run_id")
        or manifest.get("project") != project
        or manifest.get("mode") != mode
        or manifest.get("formal_eligible") is not False
    ):
        raise ContractError(f"{label} {status} manifest identity differs")
    verified_record(f"{label} {status} manifest run_config", manifest.get("run_config"))
    for name, record in manifest.get("inputs", {}).items():
        verified_record(f"{label} {status} input {name}", record)
    for output in outputs:
        record_for_path(
            manifest.get("outputs"), output, f"{label} {status} output {output.name}"
        )
    return manifest
