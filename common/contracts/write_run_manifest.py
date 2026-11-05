"""Write a reproducible manifest for one simulation or build run."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

try:
    from common.contracts.recorded_file_removal import write_json_atomic
    from common.contracts.capacity_protection import process_file_lock
except ModuleNotFoundError:
    from recorded_file_removal import write_json_atomic
    from capacity_protection import process_file_lock


from msplatform.execution import manifest_records as _manifest_records
from msplatform.execution import manifest_publication as _manifest_publication
from msplatform.execution.terminal_publication import (
    TERMINAL_JOURNAL_NAME as TERMINAL_JOURNAL_NAME,
    TERMINAL_LOCK_NAME as TERMINAL_LOCK_NAME,
    TERMINAL_STATUSES,
    _can_replace_provisional,
    require_completed_terminal_publication,
    replay_terminal_publication as replay_terminal_publication,
    publish_terminal_state as publish_terminal_state,
)


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


resolve_path = _manifest_publication.resolve_path




_json_bytes = _manifest_records._json_bytes


def file_record(
    path: Path,
    retention_role: str | None = None,
    *,
    recorded_path: Path | None = None,
    document: dict[str, Any] | None = None,
    _identity_cache: dict[tuple[Any, ...], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """Delegate exact identity to the installed owner with legacy retention policy."""
    return _manifest_records.file_record(path, retention_role, recorded_path=recorded_path,
        document=document, _identity_cache=_identity_cache,
        retention_classifier=lambda *args, **kwargs: retention_api()[0](*args, **kwargs))


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
    """Delegate the original build to one installed implementation."""
    return _manifest_publication.build_run_manifest(run_config_path, status,
        retention_api=retention_api, software=software, output_paths=output_paths,
        actual_root=actual_root, recorded_root=recorded_root, virtual_documents=virtual_documents,
        extra_fields=extra_fields, allow_missing_inputs=allow_missing_inputs)












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
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
