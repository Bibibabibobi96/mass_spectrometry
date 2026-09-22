"""Verify a complete run manifest or an explicit downstream-consumer projection."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from common.contracts.file_identity import file_sha256
    from common.contracts.write_run_manifest import require_completed_terminal_publication
except ModuleNotFoundError:
    from file_identity import file_sha256
    from write_run_manifest import require_completed_terminal_publication


def retention_api() -> tuple[Any, Any, Any, Any]:
    """Import the v2-only retention API without breaking frozen v1 verifiers."""

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


def record_path(record: dict, *, base_dir: Path | None = None) -> Path:
    """Resolve an absolute record or a historical run-relative record."""

    path = Path(record["path"])
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path.resolve()


def verify_record(
    name: str, record: dict, *, base_dir: Path | None = None
) -> None:
    path = record_path(record, base_dir=base_dir)
    if not path.is_file():
        raise AssertionError(f"manifest {name} is missing: {path}")
    if path.stat().st_size != record.get("bytes"):
        raise AssertionError(f"manifest {name} byte count changed: {path}")
    if file_sha256(path) != str(record.get("sha256", "")).upper():
        raise AssertionError(f"manifest {name} SHA-256 changed: {path}")


def require_equal(name: str, actual: Any, expected: str, *, sha256: bool = False) -> None:
    actual_text = "" if actual is None else str(actual)
    if sha256:
        actual_text = actual_text.upper()
        expected = expected.upper()
    if actual_text != expected:
        raise AssertionError(f"{name} is {actual!r}, expected {expected!r}")


def _consumed_input(value: list[str]) -> tuple[str, Path]:
    name, path_text = value
    if not name or name.strip() != name:
        raise argparse.ArgumentTypeError("consumed input name must be nonempty and trimmed")
    return name, Path(path_text).resolve()


def _select_consumed_output(
    records: list[dict], expected_path: Path, *, base_dir: Path
) -> tuple[int, dict]:
    matches = [
        (index, record)
        for index, record in enumerate(records, start=1)
        if record_path(record, base_dir=base_dir) == expected_path
    ]
    if len(matches) != 1:
        raise AssertionError(
            "consumer projection output is not uniquely declared by the manifest: "
            f"{expected_path}"
        )
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--require-status", default="success")
    parser.add_argument("--require-local-run-config", action="store_true")
    parser.add_argument("--require-run-id")
    parser.add_argument("--require-project")
    parser.add_argument("--require-mode")
    parser.add_argument("--require-design-profile-id")
    parser.add_argument("--require-parent-resolved-design-sha256")
    parser.add_argument("--require-particle-source-sha256")
    parser.add_argument("--consumer-projection-id")
    parser.add_argument(
        "--consumed-input",
        action="append",
        nargs=2,
        default=[],
        metavar=("NAME", "PATH"),
        help="verify and path-bind one manifest input in a named consumer projection",
    )
    parser.add_argument(
        "--consumed-output",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="verify and path-bind one manifest output in a named consumer projection",
    )
    args = parser.parse_args()
    projection_selected = args.consumer_projection_id is not None
    if projection_selected:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", args.consumer_projection_id):
            parser.error(
                "--consumer-projection-id must be a stable lowercase identifier"
            )
        if not args.consumed_input and not args.consumed_output:
            parser.error(
                "a consumer projection requires --consumed-input or --consumed-output"
            )
    elif args.consumed_input or args.consumed_output:
        parser.error(
            "consumed record selectors require --consumer-projection-id"
        )
    manifest_path = args.manifest.resolve()
    require_completed_terminal_publication(manifest_path)
    manifest_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    schema_version = manifest.get("schema_version", 1)
    if schema_version not in {1, 2}:
        raise AssertionError(f"unsupported run manifest schema_version: {schema_version!r}")
    if manifest.get("status") != args.require_status:
        raise AssertionError(
            f"manifest status is {manifest.get('status')!r}, expected {args.require_status!r}"
        )
    verify_record("run_config", manifest["run_config"], base_dir=manifest_dir)
    run_config_path = record_path(manifest["run_config"], base_dir=manifest_dir)
    if args.require_local_run_config and run_config_path.parent != manifest_dir:
        raise AssertionError(
            f"manifest run_config is outside its run directory: {run_config_path}"
        )
    run_config = json.loads(run_config_path.read_text(encoding="utf-8-sig"))
    retention = None
    if schema_version == 2:
        (
            classify_file,
            load_failed_recovery_exemptions,
            validate_retained_files,
            validate_retention,
        ) = retention_api()
        if run_config.get("schema_version") != 2:
            raise AssertionError("v2 manifest requires v2 run_config")
        retention = validate_retention(run_config.get("artifact_retention"))
        if manifest.get("artifact_retention") != {
            "policy_version": retention.policy_version,
            "class": retention.class_id,
            "reason": retention.reason,
        }:
            raise AssertionError("manifest artifact_retention differs from run_config")
    for field, expected in (
        ("run_id", args.require_run_id),
        ("project", args.require_project),
        ("mode", args.require_mode),
    ):
        if expected is not None:
            require_equal(f"manifest {field}", manifest.get(field), expected)
            require_equal(f"run_config {field}", run_config.get(field), expected)
    parameters = run_config.get("parameters", {})
    provenance = run_config.get("provenance", {})
    if args.require_design_profile_id is not None:
        require_equal(
            "run_config parameters.design_profile_id",
            parameters.get("design_profile_id"),
            args.require_design_profile_id,
        )
    if args.require_parent_resolved_design_sha256 is not None:
        require_equal(
            "run_config provenance.parent_resolved_design_sha256",
            provenance.get("parent_resolved_design_sha256"),
            args.require_parent_resolved_design_sha256,
            sha256=True,
        )
    if args.require_particle_source_sha256 is not None:
        require_equal(
            "run_config provenance.particle_source_sha256",
            provenance.get("particle_source_sha256"),
            args.require_particle_source_sha256,
            sha256=True,
        )
    manifest_inputs = manifest.get("inputs", {})
    manifest_outputs = manifest.get("outputs", [])
    if not isinstance(manifest_inputs, dict):
        raise AssertionError("manifest inputs must be an object")
    if not isinstance(manifest_outputs, list):
        raise AssertionError("manifest outputs must be an array")
    if projection_selected:
        consumed_inputs = [_consumed_input(value) for value in args.consumed_input]
        input_names = [name for name, _ in consumed_inputs]
        if len(input_names) != len(set(input_names)):
            raise AssertionError("consumer projection repeats an input name")
        output_paths = [path.resolve() for path in args.consumed_output]
        if len(output_paths) != len(set(output_paths)):
            raise AssertionError("consumer projection repeats an output path")
        for name, expected_path in consumed_inputs:
            if name not in manifest_inputs:
                raise AssertionError(
                    f"consumer projection input is not declared by the manifest: {name}"
                )
            record = manifest_inputs[name]
            actual_path = record_path(record, base_dir=manifest_dir)
            if actual_path != expected_path:
                raise AssertionError(
                    f"consumer projection input {name} path is {actual_path}, "
                    f"expected {expected_path}"
                )
            verify_record(f"consumed input {name}", record, base_dir=manifest_dir)
        for expected_path in output_paths:
            index, record = _select_consumed_output(
                manifest_outputs, expected_path, base_dir=manifest_dir
            )
            verify_record(f"consumed output {index}", record, base_dir=manifest_dir)
            if retention is not None:
                expected_role = classify_file(
                    record_path(record, base_dir=manifest_dir),
                    bytes_count=int(record["bytes"]),
                )
                if record.get("retention_role") != expected_role:
                    raise AssertionError(
                        f"output {index} retention_role differs: "
                        f"{record.get('retention_role')!r}"
                    )
    else:
        for name, record in manifest_inputs.items():
            verify_record(f"input {name}", record, base_dir=manifest_dir)
        for index, record in enumerate(manifest_outputs, start=1):
            verify_record(f"output {index}", record, base_dir=manifest_dir)
            if retention is not None:
                expected_role = classify_file(
                    record_path(record, base_dir=manifest_dir),
                    bytes_count=int(record["bytes"]),
                )
                if record.get("retention_role") != expected_role:
                    raise AssertionError(
                        f"output {index} retention_role differs: "
                        f"{record.get('retention_role')!r}"
                    )
    if (
        not projection_selected
        and retention is not None
        and manifest.get("status") not in {"interrupted", "checkpoint"}
    ):
        run_files = [
            path
            for path in manifest_dir.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.resolve() != manifest_path
        ]
        exemptions = (
            load_failed_recovery_exemptions(manifest_dir, retention)
            if manifest.get("status") == "failed"
            else set()
        )
        validate_retained_files(retention, run_files, exempt_paths=exemptions)
    scope = "consumer_projection" if projection_selected else "full"
    projection_text = (
        f" PROJECTION={args.consumer_projection_id} "
        f"CONSUMED_INPUTS={len(args.consumed_input)} "
        f"CONSUMED_OUTPUTS={len(args.consumed_output)}"
        if projection_selected
        else f" OUTPUTS={len(manifest_outputs)}"
    )
    print(
        f"RUN_MANIFEST_VERIFY=PASS SCOPE={scope} "
        f"PROJECT={manifest.get('project')} RUN_ID={manifest.get('run_id')}"
        f"{projection_text}"
    )


if __name__ == "__main__":
    main()
