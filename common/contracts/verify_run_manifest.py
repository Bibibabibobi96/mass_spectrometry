"""Recompute every file record in a simulation run manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from common.contracts.file_identity import file_sha256
except ModuleNotFoundError:
    from file_identity import file_sha256


def retention_api() -> tuple[Any, Any, Any]:
    """Import the v2-only retention API without breaking frozen v1 verifiers."""

    try:
        from common.contracts.artifact_retention import (
            classify_file,
            validate_retained_files,
            validate_retention,
        )
    except ModuleNotFoundError:
        from artifact_retention import (
            classify_file,
            validate_retained_files,
            validate_retention,
        )
    return classify_file, validate_retained_files, validate_retention


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
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
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
        classify_file, validate_retained_files, validate_retention = retention_api()
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
    for name, record in manifest.get("inputs", {}).items():
        verify_record(f"input {name}", record, base_dir=manifest_dir)
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"output {index}", record, base_dir=manifest_dir)
        if retention is not None:
            expected_role = classify_file(
                record_path(record, base_dir=manifest_dir),
                bytes_count=int(record["bytes"]),
            )
            if record.get("retention_role") != expected_role:
                raise AssertionError(
                    f"output {index} retention_role differs: {record.get('retention_role')!r}"
                )
    if retention is not None and manifest.get("status") not in {"interrupted", "checkpoint"}:
        run_files = [
            path
            for path in manifest_dir.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.resolve() != manifest_path
        ]
        validate_retained_files(retention, run_files)
    print(
        f"RUN_MANIFEST_VERIFY=PASS PROJECT={manifest.get('project')} "
        f"RUN_ID={manifest.get('run_id')} OUTPUTS={len(manifest.get('outputs', []))}"
    )


if __name__ == "__main__":
    main()
