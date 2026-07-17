"""Write a reproducible manifest for one simulation or build run."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def resolve_path(value: str, base: Path, project_root: Path | None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    root = project_root if project_root is not None else base
    return (root / path).resolve()


def file_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if path.is_file():
        record.update(bytes=path.stat().st_size, sha256=sha256(path))
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
    run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
    project_root_value = run_config.get("project_root")
    project_root = Path(project_root_value).resolve() if project_root_value else None
    base = run_config_path.parent

    inputs = {
        name: file_record(resolve_path(value, base, project_root))
        for name, value in run_config.get("inputs", {}).items()
        if isinstance(value, str)
    }
    outputs = [file_record(resolve_path(value, base, project_root)) for value in args.output]
    missing_inputs = [name for name, record in inputs.items() if not record["exists"]]
    if missing_inputs:
        raise SystemExit(f"missing run inputs: {', '.join(missing_inputs)}")

    manifest = {
        "schema_version": 1,
        "role": "simulation_run_manifest",
        "run_id": run_config.get("run_id"),
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
    destination = args.manifest or run_config_path.with_name("run_manifest.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"RUN_MANIFEST=PASS PATH={destination}")


if __name__ == "__main__":
    main()
