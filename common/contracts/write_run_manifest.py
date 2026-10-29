"""Write a reproducible manifest for one simulation or build run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from common.contracts.artifact_naming import validate_run_id
    from common.contracts.file_identity import file_sha256, file_sha256_unbuffered
    from common.contracts.recorded_file_removal import write_json_atomic
    from common.contracts.capacity_protection import process_file_lock
except ModuleNotFoundError:
    from artifact_naming import validate_run_id
    from file_identity import file_sha256, file_sha256_unbuffered
    from recorded_file_removal import write_json_atomic
    from capacity_protection import process_file_lock


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
TERMINAL_LOCK_NAME = ".run_terminal_publication.lock"
TERMINAL_STATUSES = {"success", "failed", "interrupted", "superseded"}
# Reuse the validated Windows PA inventory's 8 MiB large-payload read tier.
# This I/O threshold is not a scientific parameter or a retry policy.
_UNBUFFERED_SOLVER_PAYLOAD_BYTES = 8 * 1024 * 1024


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def file_record(
    path: Path,
    retention_role: str | None = None,
    *,
    recorded_path: Path | None = None,
    document: dict[str, Any] | None = None,
    _identity_cache: dict[tuple[Any, ...], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """Record exact bytes with the shared read policy for closed payloads.

    Large Windows solver-native files use the existing unbuffered reader;
    producers must already have stopped writing. Read failures never retry or
    fall back to another view. Virtual documents retain their exact JSON hash.
    The optional private cache belongs to one closed-payload build/verify call;
    default calls always read fresh bytes and never retain record metadata.
    """
    payload = _json_bytes(document) if document is not None else None
    exists = payload is not None or path.is_file()
    record: dict[str, Any] = {"path": str(recorded_path or path), "exists": exists}
    if payload is not None:
        record.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest().upper())
    elif path.is_file():
        metadata = path.stat()
        size = metadata.st_size
        large_windows_file = os.name == "nt" and size >= _UNBUFFERED_SOLVER_PAYLOAD_BYTES
        read_role = retention_role
        if large_windows_file and read_role is None:
            read_role = retention_api()[0](path, bytes_count=size)
        hash_file = file_sha256_unbuffered if (
            large_windows_file and read_role == "solver_native_binary"
        ) else file_sha256
        key = (path.resolve(), hash_file, size, metadata.st_mtime_ns) if _identity_cache is not None else None
        identity = _identity_cache.get(key) if _identity_cache is not None else None
        if identity is None:
            identity = (size, hash_file(path))
            if _identity_cache is not None:
                _identity_cache[key] = identity
        record.update(bytes=identity[0], sha256=identity[1])
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

    identity_cache: dict[tuple[Any, ...], tuple[int, str]] = {}
    inputs: dict[str, dict[str, Any]] = {}
    for name, value in run_config.get("inputs", {}).items():
        if isinstance(value, str):
            declared = resolve_path(value, base, project_root)
            actual, recorded = actual_and_recorded(declared)
            inputs[name] = file_record(actual, recorded_path=recorded, _identity_cache=identity_cache)
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
                _identity_cache=identity_cache,
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
            _identity_cache=identity_cache,
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


def _can_replace_provisional(existing: dict[str, Any], target: dict[str, Any], allowed: bool) -> bool:
    return bool(allowed and existing.get("status") == "interrupted"
                and existing.get("lifecycle_state") == "provisional"
                and existing.get("run_id") == target.get("run_id")
                and existing.get("project") == target.get("project")
                and existing.get("mode") == target.get("mode"))


def _replay_terminal_publication_locked(run_root: Path, *, allow_provisional: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
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
    existing_path = root / "run_manifest.json"
    if existing_path.is_file():
        existing = json.loads(existing_path.read_text(encoding="utf-8-sig"))
        if (existing.get("status") in TERMINAL_STATUSES and existing != manifest
                and not _can_replace_provisional(existing, manifest, allow_provisional)):
            raise ValueError("terminal publication conflicts with the already published manifest")
    write_json_atomic(root / "summary.json", summary)
    write_json_atomic(root / "run_manifest.json", manifest)
    journal_path.unlink()
    return summary, manifest


def replay_terminal_publication(run_root: Path, *, allow_provisional: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Idempotently replay the sole durable terminal-publication journal."""
    root = run_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"terminal run directory is missing: {root}")
    with process_file_lock(root / TERMINAL_LOCK_NAME):
        return _replay_terminal_publication_locked(root, allow_provisional=allow_provisional)


def publish_terminal_state(
    run_root: Path,
    summary: dict[str, Any],
    manifest: dict[str, Any],
    *, allow_provisional: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Journal and publish summary plus manifest as one replayable intent."""

    root = run_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"terminal run directory is missing: {root}")
    journal_path = root / TERMINAL_JOURNAL_NAME
    journal = {
        "schema_version": 1,
        "role": "run_terminal_publication_journal",
        "run_id": manifest.get("run_id"),
        "documents": {"summary.json": summary, "run_manifest.json": manifest},
    }
    with process_file_lock(root / TERMINAL_LOCK_NAME):
        existing_manifest_path = root / "run_manifest.json"
        if existing_manifest_path.is_file():
            existing_manifest = json.loads(existing_manifest_path.read_text(encoding="utf-8-sig"))
            if existing_manifest.get("status") in TERMINAL_STATUSES:
                if existing_manifest != manifest and not _can_replace_provisional(existing_manifest, manifest, allow_provisional):
                    raise ValueError("terminal publication conflicts with the already published manifest")
                if existing_manifest == manifest and not journal_path.exists():
                    existing_summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
                    if existing_summary != summary:
                        raise ValueError("terminal publication conflicts with the already published summary")
                    return summary, manifest
        if journal_path.exists():
            existing = json.loads(journal_path.read_text(encoding="utf-8-sig"))
            if existing != journal:
                raise ValueError("another terminal publication is already pending")
        else:
            write_json_atomic(journal_path, journal)
        return _replay_terminal_publication_locked(root, allow_provisional=allow_provisional)


def publish_run_manifest(
    run_config_path: Path, status: str, *, destination: Path | None = None,
    software: list[str] | None = None, output_paths: list[Path] | None = None,
    actual_root: Path | None = None, recorded_root: Path | None = None,
    virtual_documents: dict[Path, dict[str, Any]] | None = None,
    extra_fields: dict[str, Any] | None = None, allow_missing_inputs: bool = False,
    allow_provisional: bool = False,
) -> dict[str, Any]:
    """Build and atomically publish through the shared terminal exclusion."""
    run_config_path = run_config_path.resolve()
    destination = destination or run_config_path.with_name("run_manifest.json")
    with process_file_lock(run_config_path.parent / TERMINAL_LOCK_NAME):
        require_completed_terminal_publication(run_config_path.parent / "run_manifest.json")
        prior, prior_error = None, None
        is_primary = destination.resolve() == (run_config_path.parent / "run_manifest.json").resolve()
        if is_primary and destination.is_file():
            try:
                prior = json.loads(destination.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                prior_error = error
            if isinstance(prior, dict) and prior.get("status") in TERMINAL_STATUSES:
                current = json.loads(run_config_path.read_text(encoding="utf-8-sig"))
                if not _can_replace_provisional(prior, current, allow_provisional):
                    raise ValueError("cannot replace an already published terminal manifest")
        manifest = build_run_manifest(run_config_path, status, software=software, output_paths=output_paths,
            actual_root=actual_root, recorded_root=recorded_root, virtual_documents=virtual_documents,
            extra_fields=extra_fields, allow_missing_inputs=allow_missing_inputs)
        missing = [record["path"] for record in manifest["outputs"] if not record["exists"]]
        if missing:
            raise ValueError(f"missing run outputs: {missing}")
        if is_primary and destination.is_file() and (prior_error is not None or not isinstance(prior, dict)):
            raise ValueError("existing run manifest is unreadable")
        candidate = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.candidate{destination.suffix}")
        try:
            write_json_atomic(candidate, manifest)
            if candidate.read_bytes() != _json_bytes(manifest):
                raise ValueError("published manifest differs from the computed records")
            os.replace(candidate, destination)
        finally:
            candidate.unlink(missing_ok=True)
        return manifest


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
    parser.add_argument("--output-list-json", type=Path,
                        help="UTF-8 JSON list[str] file, or '-' for stdin; appended after --output")
    args = parser.parse_args()

    run_config_path = args.run_config.resolve()
    destination = args.manifest or run_config_path.with_name("run_manifest.json")
    try:
        output_values = list(args.output)
        if args.output_list_json is not None:
            payload = (sys.stdin.buffer.read().decode("utf-8-sig") if str(args.output_list_json) == "-"
                       else args.output_list_json.read_text(encoding="utf-8-sig"))
            entries = json.loads(payload)
            if not isinstance(entries, list) or any(not isinstance(value, str) for value in entries):
                raise ValueError("--output-list-json requires a JSON list[str]")
            output_values.extend(entries)
        output_paths = [Path(value) for value in output_values]
        publish_run_manifest(run_config_path, args.status, destination=destination,
                             software=args.software, output_paths=output_paths)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
    print(f"RUN_MANIFEST=PASS PATH={destination}")


if __name__ == "__main__":
    main()
