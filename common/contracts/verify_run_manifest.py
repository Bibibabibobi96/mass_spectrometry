"""Recompute every file record in a simulation run manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--require-status", default="success")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if manifest.get("status") != args.require_status:
        raise AssertionError(
            f"manifest status is {manifest.get('status')!r}, expected {args.require_status!r}"
        )
    verify_record("run_config", manifest["run_config"])
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
