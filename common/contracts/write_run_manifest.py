"""Write a reproducible manifest for one simulation or build run."""

from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from common.contracts.artifact_naming import validate_run_id
    from common.contracts.file_identity import file_sha256
except ModuleNotFoundError:
    from artifact_naming import validate_run_id
    from file_identity import file_sha256


def retention_api() -> tuple[Any, Any, Any]:
    """Import the v2-only retention API without breaking frozen v1 writers."""

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


def resolve_path(value: str, base: Path, project_root: Path | None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    root = project_root if project_root is not None else base
    return (root / path).resolve()


def file_record(path: Path, retention_role: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if path.is_file():
        record.update(bytes=path.stat().st_size, sha256=file_sha256(path))
    if retention_role is not None:
        record["retention_role"] = retention_role
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-config", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--status", required=True, choices=("success", "failed", "interrupted", "superseded"))
    parser.add_argument("--software", action="append", default=[])
    parser.add_argument("--output", action="append", default=[])
    args = parser.parse_args()

    run_config_path = args.run_config.resolve()
    # Windows PowerShell 5.1 writes a UTF-8 BOM by default, while PowerShell 7
    # does not.  Accept both so the provenance gate is independent of which
    # supported launcher produced run_config.json.
    run_config = json.loads(run_config_path.read_text(encoding="utf-8-sig"))
    run_id = run_config.get("run_id")
    if not isinstance(run_id, str):
        raise SystemExit("run_config.json must contain a string run_id")
    validate_run_id(run_id)
    project_root_value = run_config.get("project_root")
    project_root = Path(project_root_value).resolve() if project_root_value else None
    base = run_config_path.parent
    retention = None
    if run_config.get("schema_version") == 2:
        classify_file, validate_retained_files, validate_retention = retention_api()
        retention = validate_retention(run_config.get("artifact_retention"))

    inputs = {
        name: file_record(resolve_path(value, base, project_root))
        for name, value in run_config.get("inputs", {}).items()
        if isinstance(value, str)
    }
    output_paths = [resolve_path(value, base, project_root) for value in args.output]
    if retention is not None and args.status != "interrupted":
        run_files = [
            path
            for path in base.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.name != "run_manifest.json"
        ]
        validate_retained_files(retention, run_files)
    outputs = [
        file_record(
            path,
            classify_file(path) if retention is not None and path.is_file() else None,
        )
        for path in output_paths
    ]
    missing_inputs = [name for name, record in inputs.items() if not record["exists"]]
    if missing_inputs:
        raise SystemExit(f"missing run inputs: {', '.join(missing_inputs)}")

    manifest = {
        "schema_version": 2 if retention is not None else 1,
        "role": "simulation_run_manifest",
        "run_id": run_id,
        "project": run_config.get("project"),
        "mode": run_config.get("mode"),
        "status": args.status,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": platform.node(),
        "python": platform.python_version(),
        "software": args.software,
        "run_config": file_record(run_config_path),
        "inputs": inputs,
        "outputs": outputs,
        "formal_eligible": bool(run_config.get("formal_gate_passed", False))
        and args.status == "success"
        and all(item["exists"] for item in outputs),
    }
    if retention is not None:
        manifest["artifact_retention"] = {
            "policy_version": retention.policy_version,
            "class": retention.class_id,
            "reason": retention.reason,
        }
    destination = args.manifest or run_config_path.with_name("run_manifest.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"RUN_MANIFEST=PASS PATH={destination}")


if __name__ == "__main__":
    main()
