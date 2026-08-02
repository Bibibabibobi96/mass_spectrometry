"""Verify and copy the current Formal SIMION package to a disposable runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path, PurePosixPath

from common.contracts.file_identity import file_sha256


PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError(f"unsafe Formal asset path: {value!r}")
    return Path(*pure.parts)


def verify_record(root: Path, record: dict) -> Path:
    path = (root / safe_relative(str(record.get("path", "")))).resolve(strict=True)
    path.relative_to(root.resolve(strict=True))
    if (
        not path.is_file()
        or path.stat().st_size != int(record.get("bytes", -1))
        or file_sha256(path) != str(record.get("sha256", "")).upper()
    ):
        raise ValueError(f"Formal SIMION asset identity differs: {path}")
    return path


def stage_runtime(artifact_root: Path, destination: Path, receipt: Path) -> dict:
    """Copy one manifest-verified SIMION package and write its source receipt."""
    artifact_root = artifact_root.resolve(strict=True)
    formal = (artifact_root / "formal").resolve(strict=True)
    manifest_path = formal / "asset_manifest.json"
    manifest = load_json(manifest_path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("role") != "formal_asset_manifest"
        or manifest.get("project") != PROJECT_ID
    ):
        raise ValueError("Formal asset manifest identity differs")
    records = {
        role: record
        for role, record in manifest.get("assets", {}).items()
        if str(record.get("path", "")).startswith("simion/")
    }
    if not records:
        raise ValueError("Formal asset manifest has no SIMION package")
    expected_paths = {str(record["path"])[len("simion/") :] for record in records.values()}
    formal_simion = formal / "simion"
    actual_paths = {
        path.relative_to(formal_simion).as_posix()
        for path in formal_simion.rglob("*")
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ValueError("Formal SIMION package file set differs from its asset manifest")

    destination = destination.resolve()
    destination.relative_to(artifact_root)
    if formal == destination or formal in destination.parents:
        raise ValueError("runtime destination must remain outside Formal")
    staging = destination.with_name(f".{destination.name}.staging")
    if destination.exists() or staging.exists():
        raise FileExistsError(f"SIMION runtime destination already exists: {destination}")
    try:
        staging.mkdir(parents=True)
        asset_receipts = []
        for role, record in sorted(records.items()):
            source = verify_record(formal, record)
            relative = str(record["path"])[len("simion/") :]
            target = staging / safe_relative(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if target.stat().st_size != int(record["bytes"]) or file_sha256(target) != record["sha256"]:
                raise ValueError(f"staged SIMION runtime asset differs: {target}")
            asset_receipts.append({"role": role, **record})
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    payload = {
        "schema_version": 1,
        "role": "oa_tof_formal_simion_runtime_receipt",
        "project": PROJECT_ID,
        "release_id": manifest["release_id"],
        "formal_asset_manifest": {
            "path": str(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "sha256": file_sha256(manifest_path),
        },
        "assets": asset_receipts,
    }
    try:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    result = stage_runtime(args.artifact_root, args.destination, args.receipt)
    print(
        f"FORMAL_SIMION_RUNTIME_STAGE=PASS RELEASE_ID={result['release_id']} "
        f"ASSETS={len(result['assets'])}"
    )


if __name__ == "__main__":
    main()
