"""Write a reproducible manifest for one simulation or build run."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from common.contracts.artifact_naming import validate_run_id
    from common.contracts.file_identity import file_sha256
    from common.contracts.recorded_file_removal import write_json_atomic
except ModuleNotFoundError:
    from artifact_naming import validate_run_id
    from file_identity import file_sha256
    from recorded_file_removal import write_json_atomic


def retention_api() -> tuple[Any, Any, Any, Any]:
    """Import the v2-only retention API without breaking frozen v1 writers."""

    try:
        from common.contracts.artifact_retention import (
            classify_file,
            load_failed_recovery_exemptions,
            validate_retained_files,
            validate_retention,
        )
    except ModuleNotFoundError:
        from artifact_retention import (
            classify_file,
            load_failed_recovery_exemptions,
            validate_retained_files,
            validate_retention,
        )
    return (
        classify_file,
        load_failed_recovery_exemptions,
        validate_retained_files,
        validate_retention,
    )


def resolve_path(value: str, base: Path, project_root: Path | None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    root = project_root if project_root is not None else base
    return (root / path).resolve()


TERMINAL_JOURNAL_NAME = ".run_terminal_publication.json"


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def file_record(
    path: Path,
    retention_role: str | None = None,
    *,
    recorded_path: Path | None = None,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _json_bytes(document) if document is not None else None
    exists = payload is not None or path.is_file()
    record: dict[str, Any] = {"path": str(recorded_path or path), "exists": exists}
    if payload is not None:
        record.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest().upper())
    elif path.is_file():
        record.update(bytes=path.stat().st_size, sha256=file_sha256(path))
    if retention_role is not None:
        record["retention_role"] = retention_role
    return record


def build_run_manifest(
    run_config_path: Path,
    status: str,
    *,
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
        (
            classify_file,
            load_failed_recovery_exemptions,
            validate_retained_files,
            validate_retention,
        ) = retention_api()
        retention = validate_retention(run_config.get("artifact_retention"))

    inputs: dict[str, dict[str, Any]] = {}
    for name, value in run_config.get("inputs", {}).items():
        if isinstance(value, str):
            declared = resolve_path(value, base, project_root)
            actual, recorded = actual_and_recorded(declared)
            inputs[name] = file_record(actual, recorded_path=recorded)
    resolved_outputs = [
        resolve_path(str(path), base, project_root) for path in (output_paths or [])
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


def require_completed_terminal_publication(manifest_path: Path) -> None:
    """Reject a manifest while its sibling journal still owns completion."""

    if (manifest_path.resolve().parent / TERMINAL_JOURNAL_NAME).is_file():
        raise ValueError("run terminal publication is incomplete; replay its journal")


def replay_terminal_publication(run_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Idempotently replay the sole durable terminal-publication journal."""

    root = run_root.resolve()
    journal_path = root / TERMINAL_JOURNAL_NAME
    journal = json.loads(journal_path.read_text(encoding="utf-8-sig"))
    documents = journal.get("documents") if isinstance(journal, dict) else None
    if (
        journal.get("schema_version") != 1
        or journal.get("role") != "run_terminal_publication_journal"
        or not isinstance(documents, dict)
        or set(documents) != {"summary.json", "run_manifest.json"}
        or not all(isinstance(value, dict) for value in documents.values())
        or documents["summary.json"].get("status")
        != documents["run_manifest.json"].get("status")
        or documents["run_manifest.json"].get("run_id") != journal.get("run_id")
    ):
        raise ValueError("terminal publication journal is invalid")
    summary = documents["summary.json"]
    manifest = documents["run_manifest.json"]
    write_json_atomic(root / "summary.json", summary)
    write_json_atomic(root / "run_manifest.json", manifest)
    journal_path.unlink()
    return summary, manifest


def publish_terminal_state(
    run_root: Path,
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Journal and publish summary plus manifest as one replayable intent."""

    root = run_root.resolve()
    journal_path = root / TERMINAL_JOURNAL_NAME
    journal = {
        "schema_version": 1,
        "role": "run_terminal_publication_journal",
        "run_id": manifest.get("run_id"),
        "documents": {"summary.json": summary, "run_manifest.json": manifest},
    }
    if journal_path.exists():
        existing = json.loads(journal_path.read_text(encoding="utf-8-sig"))
        if existing != journal:
            raise ValueError("another terminal publication is already pending")
    else:
        write_json_atomic(journal_path, journal)
    return replay_terminal_publication(root)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-config", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--status",
        required=True,
        choices=("success", "failed", "interrupted", "checkpoint", "superseded"),
    )
    parser.add_argument("--software", action="append", default=[])
    parser.add_argument("--output", action="append", default=[])
    args = parser.parse_args()

    run_config_path = args.run_config.resolve()
    output_paths = [Path(value) for value in args.output]
    try:
        manifest = build_run_manifest(
            run_config_path,
            args.status,
            software=args.software,
            output_paths=output_paths,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    destination = args.manifest or run_config_path.with_name("run_manifest.json")
    write_json_atomic(destination, manifest)
    print(f"RUN_MANIFEST=PASS PATH={destination}")


if __name__ == "__main__":
    main()
