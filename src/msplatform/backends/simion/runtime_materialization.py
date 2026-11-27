"""Materialize a manifest-authenticated SIMION runtime from a frozen asset."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any

from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import file_record
from msplatform.execution.native_source_guard import guard_formal_v1


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError(f"unsafe Formal asset path: {value!r}")
    return Path(*pure.parts)



def stage_verified_simion_runtime(
    *, artifact_project_root: Path, destination: Path,
    receipt: Path, project_id: str,
) -> tuple[dict[str, Any], list[Path]]:
    """Copy exactly one manifest-listed SIMION package outside Formal."""
    artifact_project_root = artifact_project_root.resolve(strict=True)
    formal = (artifact_project_root / "formal").resolve(strict=True)
    manifest_path = formal / "asset_manifest.json"
    manifest_record = file_record(manifest_path)
    with guard_formal_v1(manifest_record, project_id=project_id,
                         artifact_project_root=artifact_project_root) as (manifest, guarded_paths):
        records = {role: manifest["assets"][role] for role in guarded_paths}
        expected_paths = {str(record["path"])[len("simion/"):] for record in records.values()}
        if len(expected_paths) != len(records):
            raise ValueError("Formal SIMION package repeats an asset path")
        formal_simion = formal / "simion"
        actual_paths = {
            path.relative_to(formal_simion).as_posix()
            for path in formal_simion.rglob("*") if path.is_file()
        }
        if actual_paths != expected_paths:
            raise ValueError("Formal SIMION package file set differs from its asset manifest")
        destination = destination.resolve()
        if formal == destination or formal in destination.parents:
            raise ValueError("runtime destination must remain outside Formal")
        staging = destination.with_name(f".{destination.name}.staging")
        if destination.exists() or staging.exists():
            raise FileExistsError("SIMION runtime destination already exists")
        staged_files: list[Path] = []
        try:
            staging.mkdir(parents=True)
            asset_receipts = []
            for role, record in sorted(records.items()):
                source = guarded_paths[role]
                relative = str(record["path"])[len("simion/"):]
                target = staging / _safe_relative(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if (target.stat().st_size != int(record["bytes"])
                        or file_sha256(target).upper() != str(record["sha256"]).upper()):
                    raise ValueError(f"staged SIMION runtime asset differs: {target}")
                staged_files.append(destination / _safe_relative(relative))
                asset_receipts.append({"role": role, **record})
            os.replace(staging, destination)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        payload = {
            "schema_version": 1,
            "role": "oa_tof_formal_simion_runtime_receipt",
            "project": project_id,
            "release_id": manifest["release_id"],
            "formal_asset_manifest": manifest_record,
            "assets": asset_receipts,
        }
        try:
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8", newline="\n")
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            raise
        return payload, staged_files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()
    payload, _ = stage_verified_simion_runtime(artifact_project_root=args.artifact_root,
        destination=args.destination, receipt=args.receipt, project_id=args.project_id)
    print(f"SIMION_RUNTIME_STAGE=PASS RELEASE_ID={payload['release_id']} ASSETS={len(payload['assets'])}")


if __name__ == "__main__":
    main()
