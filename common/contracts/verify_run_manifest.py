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


def verify_record(name: str, record: dict) -> None:
    path = Path(record["path"])
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
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != args.require_status:
        raise AssertionError(
            f"manifest status is {manifest.get('status')!r}, expected {args.require_status!r}"
        )
    verify_record("run_config", manifest["run_config"])
    run_config_path = Path(manifest["run_config"]["path"]).resolve()
    if args.require_local_run_config and run_config_path.parent != args.manifest.resolve().parent:
        raise AssertionError(
            f"manifest run_config is outside its run directory: {run_config_path}"
        )
    run_config = json.loads(run_config_path.read_text(encoding="utf-8-sig"))
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
        verify_record(f"input {name}", record)
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"output {index}", record)
    print(
        f"RUN_MANIFEST_VERIFY=PASS PROJECT={manifest.get('project')} "
        f"RUN_ID={manifest.get('run_id')} OUTPUTS={len(manifest.get('outputs', []))}"
    )


if __name__ == "__main__":
    main()
