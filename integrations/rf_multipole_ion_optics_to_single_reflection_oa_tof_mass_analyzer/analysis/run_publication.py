"""Transactional manifest lifecycle shared by integration analysis publishers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from common.contracts.machine_contracts import ContractError
from common.contracts.verify_run_manifest import verify_record


def load_json(path: Path, label: str) -> dict[str, Any]:
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


def portable_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise ContractError(f"path is outside workspace: {path}") from error


def write_pending_json(path: Path, value: Mapping[str, Any]) -> None:
    pending = path.with_name(f".{path.name}.pending")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(pending, path)


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
) -> None:
    command = [
        sys.executable,
        "-m",
        "common.contracts.write_run_manifest",
        "--run-config",
        str(run_config),
        "--manifest",
        str(manifest_path),
        "--status",
        status,
        "--software",
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ContractError(
            f"{label} {status} manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
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
    for output in outputs:
        record_for_path(
            manifest.get("outputs"), output, f"{label} {status} output {output.name}"
        )
    verified = subprocess.run(
        [
            sys.executable,
            "-m",
            "common.contracts.verify_run_manifest",
            str(manifest_path),
            "--require-status",
            status,
            "--require-local-run-config",
            "--require-run-id",
            str(config["run_id"]),
            "--require-project",
            project,
            "--require-mode",
            mode,
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if verified.returncode != 0:
        raise ContractError(
            f"{label} {status} manifest verification failed: "
            + (verified.stdout + verified.stderr).strip()
        )


def restore_interrupted(
    *,
    summary_path: Path,
    manifest_path: Path,
    manifest_pending: Path,
    summary_bytes: bytes,
    manifest_bytes: bytes,
) -> None:
    pending = summary_path.with_name(f".{summary_path.name}.pending")
    pending.write_bytes(summary_bytes)
    os.replace(pending, summary_path)
    manifest_pending.write_bytes(manifest_bytes)
    os.replace(manifest_pending, manifest_path)


def terminalize_failure(
    *,
    publish: Callable[..., None],
    repo_root: Path,
    run_config_path: Path,
    summary_path: Path,
    manifest_path: Path,
    manifest_pending: Path,
    failed_summary: Mapping[str, Any],
    candidate_outputs: Sequence[Path],
    interrupted_summary_bytes: bytes,
    interrupted_manifest_bytes: bytes,
) -> None:
    try:
        write_pending_json(summary_path, failed_summary)
        outputs = [path for path in candidate_outputs if path.is_file()]
        if summary_path not in outputs:
            outputs.append(summary_path)
        publish(
            repo_root=repo_root,
            run_config=run_config_path,
            manifest_path=manifest_pending,
            status="failed",
            outputs=outputs,
        )
        os.replace(manifest_pending, manifest_path)
    except (KeyboardInterrupt, SystemExit):
        restore_interrupted(
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            summary_bytes=interrupted_summary_bytes,
            manifest_bytes=interrupted_manifest_bytes,
        )
        raise
    except Exception:
        restore_interrupted(
            summary_path=summary_path,
            manifest_path=manifest_path,
            manifest_pending=manifest_pending,
            summary_bytes=interrupted_summary_bytes,
            manifest_bytes=interrupted_manifest_bytes,
        )
