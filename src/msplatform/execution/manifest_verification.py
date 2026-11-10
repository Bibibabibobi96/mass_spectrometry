"""Verify one run manifest or an explicit path-bound consumer projection."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from typing import Any
from collections.abc import Sequence
from msplatform.io.manifest_records import record_path, require_completed_terminal_publication
from msplatform.execution.retention import verify_record


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


class _ProjectionArgumentError(ValueError):
    """A projection option error shared by the typed API and argparse boundary."""


def _validate_projection_arguments(consumer_projection_id: str | None,
                                   consumed_inputs: Sequence[tuple[str, Path]],
                                   consumed_outputs: Sequence[Path]) -> bool:
    projection_selected = consumer_projection_id is not None
    if projection_selected:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", consumer_projection_id):
            raise _ProjectionArgumentError(
                "--consumer-projection-id must be a stable lowercase identifier"
            )
        if not consumed_inputs and not consumed_outputs:
            raise _ProjectionArgumentError(
                "a consumer projection requires --consumed-input or --consumed-output"
            )
    elif consumed_inputs or consumed_outputs:
        raise _ProjectionArgumentError(
            "consumed record selectors require --consumer-projection-id"
        )
    return projection_selected


def verify_run_manifest(
    manifest_path: Path, *, require_status: str = "success",
    require_local_run_config: bool = False, require_run_id: str | None = None,
    require_project: str | None = None, require_mode: str | None = None,
    require_design_profile_id: str | None = None,
    require_parent_resolved_design_sha256: str | None = None,
    require_particle_source_sha256: str | None = None,
    consumer_projection_id: str | None = None,
    consumed_inputs: Sequence[tuple[str, Path]] = (),
    consumed_outputs: Sequence[Path] = (), retention_api=None,
) -> dict[str, Any]:
    """Verify the same full manifest or explicit consumed projection without a process.

    Typed selectors are (manifest input name, expected path) pairs and output paths.
    Retention is supplied by the actual caller; the default remains generic policy.
    Integrity and policy exceptions propagate directly. No owner, host context,
    process isolation or execution timeout is added by this read-only API.
    """
    if retention_api is None:
        from msplatform.execution.retention import retention_api
    projection_selected = _validate_projection_arguments(
        consumer_projection_id, consumed_inputs, consumed_outputs)
    manifest_path = Path(manifest_path).resolve()
    require_completed_terminal_publication(manifest_path)
    manifest_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    schema_version = manifest.get("schema_version", 1)
    if schema_version not in {1, 2}:
        raise AssertionError(f"unsupported run manifest schema_version: {schema_version!r}")
    if manifest.get("status") != require_status:
        raise AssertionError(
            f"manifest status is {manifest.get('status')!r}, expected {require_status!r}"
        )
    identity_cache: dict[tuple[Any, ...], tuple[int, str]] = {}
    verify_record("run_config", manifest["run_config"], base_dir=manifest_dir, _identity_cache=identity_cache)
    run_config_path = record_path(manifest["run_config"], base_dir=manifest_dir)
    if require_local_run_config and run_config_path.parent != manifest_dir:
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
        ("run_id", require_run_id),
        ("project", require_project),
        ("mode", require_mode),
    ):
        if expected is not None:
            require_equal(f"manifest {field}", manifest.get(field), expected)
            require_equal(f"run_config {field}", run_config.get(field), expected)
    parameters = run_config.get("parameters", {})
    provenance = run_config.get("provenance", {})
    if require_design_profile_id is not None:
        require_equal(
            "run_config parameters.design_profile_id",
            parameters.get("design_profile_id"),
            require_design_profile_id,
        )
    if require_parent_resolved_design_sha256 is not None:
        require_equal(
            "run_config provenance.parent_resolved_design_sha256",
            provenance.get("parent_resolved_design_sha256"),
            require_parent_resolved_design_sha256,
            sha256=True,
        )
    if require_particle_source_sha256 is not None:
        require_equal(
            "run_config provenance.particle_source_sha256",
            provenance.get("particle_source_sha256"),
            require_particle_source_sha256,
            sha256=True,
        )
    manifest_inputs = manifest.get("inputs", {})
    manifest_outputs = manifest.get("outputs", [])
    if not isinstance(manifest_inputs, dict):
        raise AssertionError("manifest inputs must be an object")
    if not isinstance(manifest_outputs, list):
        raise AssertionError("manifest outputs must be an array")
    if projection_selected:
        selected_inputs = [_consumed_input([name, str(path)]) for name, path in consumed_inputs]
        input_names = [name for name, _ in selected_inputs]
        if len(input_names) != len(set(input_names)):
            raise AssertionError("consumer projection repeats an input name")
        output_paths = [path.resolve() for path in consumed_outputs]
        if len(output_paths) != len(set(output_paths)):
            raise AssertionError("consumer projection repeats an output path")
        for name, expected_path in selected_inputs:
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
            verify_record(f"consumed input {name}", record, base_dir=manifest_dir, _identity_cache=identity_cache)
        for expected_path in output_paths:
            index, record = _select_consumed_output(
                manifest_outputs, expected_path, base_dir=manifest_dir
            )
            verify_record(f"consumed output {index}", record, base_dir=manifest_dir, _identity_cache=identity_cache)
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
            verify_record(f"input {name}", record, base_dir=manifest_dir, _identity_cache=identity_cache)
        for index, record in enumerate(manifest_outputs, start=1):
            verify_record(f"output {index}", record, base_dir=manifest_dir, _identity_cache=identity_cache)
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
        f" PROJECTION={consumer_projection_id} "
        f"CONSUMED_INPUTS={len(consumed_inputs)} "
        f"CONSUMED_OUTPUTS={len(consumed_outputs)}"
        if projection_selected
        else f" OUTPUTS={len(manifest_outputs)}"
    )
    diagnostic = (
        f"RUN_MANIFEST_VERIFY=PASS SCOPE={scope} "
        f"PROJECT={manifest.get('project')} RUN_ID={manifest.get('run_id')}"
        f"{projection_text}"
    )
    return dict(status="PASS", scope=scope, project=manifest.get("project"),
                run_id=manifest.get("run_id"), consumer_projection_id=consumer_projection_id,
                consumed_input_count=len(consumed_inputs),
                consumed_output_count=len(consumed_outputs), output_count=len(manifest_outputs),
                diagnostic=diagnostic)


def main(*, retention_api=None) -> None:
    """Parse the existing CLI and delegate to its sole verification implementation."""
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
    try:
        result = verify_run_manifest(
            args.manifest, require_status=args.require_status,
            require_local_run_config=args.require_local_run_config,
            require_run_id=args.require_run_id, require_project=args.require_project,
            require_mode=args.require_mode, require_design_profile_id=args.require_design_profile_id,
            require_parent_resolved_design_sha256=args.require_parent_resolved_design_sha256,
            require_particle_source_sha256=args.require_particle_source_sha256,
            consumer_projection_id=args.consumer_projection_id,
            consumed_inputs=tuple((name, Path(path)) for name, path in args.consumed_input),
            consumed_outputs=tuple(args.consumed_output), retention_api=retention_api)
    except _ProjectionArgumentError as error:
        parser.error(str(error))
    print(result["diagnostic"])


if __name__ == "__main__":
    main()
