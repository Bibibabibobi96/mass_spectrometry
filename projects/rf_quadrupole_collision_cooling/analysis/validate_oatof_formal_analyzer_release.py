"""Validate the current oa-TOF Formal SIMION analyzer release for S3 use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _verify_file_record(
    record: dict[str, Any], path: Path, expected_relative_path: str
) -> None:
    if record.get("path") != expected_relative_path:
        raise ValueError(f"Formal record path differs: {record.get('path')}")
    if path.stat().st_size != int(record["bytes"]) or _sha256(path) != record["sha256"]:
        raise ValueError(f"Formal record identity differs: {path}")


def _output_record(delivery: dict[str, Any], expected_path: Path) -> dict[str, Any]:
    matches = [
        record
        for record in delivery.get("outputs", [])
        if Path(record["path"]).resolve() == expected_path.resolve()
    ]
    if len(matches) != 1:
        raise ValueError(f"Formal delivery output must resolve uniquely: {expected_path}")
    record = matches[0]
    if (
        not record.get("exists")
        or expected_path.stat().st_size != int(record["bytes"])
        or _sha256(expected_path) != record["sha256"]
    ):
        raise ValueError(f"Formal delivery output identity differs: {expected_path}")
    return record


def _stable_asset(entry: dict[str, Any], role: str) -> dict[str, Any]:
    matches = [asset for asset in entry.get("assets", []) if asset.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"SIMION stable entry requires one {role} asset")
    return matches[0]


def validate(
    asset_manifest_path: Path,
    validation_contract_path: Path,
    delivery_manifest_path: Path,
    formal_root: Path,
    stable_entry_path: Path,
    baseline_path: Path,
    resolved_geometry_path: Path,
    formal_lua_path: Path,
) -> dict[str, Any]:
    """Validate current Formal authority and the analyzer assets consumed by S3."""
    asset_manifest = _load(asset_manifest_path)
    validation = _load(validation_contract_path)
    delivery = _load(delivery_manifest_path)
    stable = _load(stable_entry_path)
    resolved = _load(resolved_geometry_path)

    if (
        asset_manifest.get("schema_version") != 1
        or asset_manifest.get("role") != "formal_asset_manifest"
        or asset_manifest.get("project") != "oa_tof"
    ):
        raise ValueError("oaTOF Formal asset-manifest identity differs")
    if (
        validation.get("status") != "formal_cross_solver_validation"
        or validation.get("simion", {}).get("model_role") != "formal"
    ):
        raise ValueError("oaTOF Formal validation-contract identity differs")
    release_id = validation.get("run_id")
    promotion = validation.get("promotion_evidence", {})
    if (
        asset_manifest.get("release_id") != release_id
        or asset_manifest.get("source_run", {}).get("run_id") != release_id
        or asset_manifest.get("source_run", {}).get("run_manifest", {}).get("sha256")
        != promotion.get("validation_run_manifest_sha256")
    ):
        raise ValueError("oaTOF Formal release and validation run differ")

    _verify_file_record(
        asset_manifest["validation_contract"],
        validation_contract_path,
        "projects/oa_tof/config/formal_validation.json",
    )
    delivery_record = asset_manifest["assets"]["simion_delivery_manifest"]
    _verify_file_record(
        delivery_record,
        delivery_manifest_path,
        "simion/run_manifest.json",
    )

    simion = validation["simion"]
    if (
        simion.get("delivery_manifest_artifact_relative_path")
        != "formal/simion/run_manifest.json"
        or simion.get("delivery_manifest_sha256") != delivery_record["sha256"]
        or delivery.get("role") != "simulation_run_manifest"
        or delivery.get("status") != "success"
        or delivery.get("project") != "oa_tof"
        or delivery.get("mode") != "formal_delivery"
        or delivery.get("formal_eligible") is not True
    ):
        raise ValueError("oaTOF Formal SIMION delivery authority differs")

    baseline_sha256 = _sha256(baseline_path)
    if (
        validation.get("physical_contract") != "baseline.json"
        or validation.get("physical_contract_sha256") != baseline_sha256
        or resolved.get("inputs", {}).get("baseline_sha256") != baseline_sha256
        or resolved.get("coordinate_convention", {}).get("frame_id") != "oatof_global"
    ):
        raise ValueError("oaTOF Formal physical-contract identity differs")

    iob_path = formal_root / "oatof_ideal_grounded.iob"
    checksum_path = formal_root / "SHA256SUMS.csv"
    program_path = formal_root / "oatof_ideal_grounded.lua"
    iob_record = _output_record(delivery, iob_path)
    checksum_record = _output_record(delivery, checksum_path)
    program_record = _output_record(delivery, program_path)
    if (
        simion.get("iob_artifact_relative_path")
        != "formal/simion/oatof_ideal_grounded.iob"
        or simion.get("iob_sha256") != iob_record["sha256"]
    ):
        raise ValueError("oaTOF Formal SIMION IOB differs from validation contract")

    entries = stable.get("entries", [])
    if (
        stable.get("schema_version") not in (1, 2)
        or stable.get("role")
        != "Implementation hash manifest for the current formal SIMION delivery."
        or stable.get("artifact_workspace_relative") != "formal/simion"
        or len(entries) != 1
        or entries[0].get("trajectory_quality") != 8
        or entries[0].get("expected_instances") != 4
    ):
        raise ValueError("oaTOF SIMION stable-entry identity differs")
    entry = entries[0]
    stable_checks = {
        "iob": (iob_path, iob_record),
        "program": (program_path, program_record),
        "sha256_manifest": (checksum_path, checksum_record),
        "run_manifest": (
            delivery_manifest_path,
            {
                "sha256": delivery_record["sha256"],
                "bytes": delivery_record["bytes"],
            },
        ),
    }
    for role, (path, authority) in stable_checks.items():
        record = _stable_asset(entry, role)
        if (
            record.get("relative_path") != path.name
            or int(record["bytes"]) != int(authority["bytes"])
            or record["sha256"] != authority["sha256"]
        ):
            raise ValueError(f"oaTOF SIMION stable-entry {role} identity differs")
    if _sha256(formal_lua_path) != _stable_asset(entry, "program")["sha256"]:
        raise ValueError("Frozen oaTOF Formal Lua differs from stable entry")

    return {
        "status": "PASS",
        "release_id": release_id,
        "delivery_run_id": delivery["run_id"],
        "iob_sha256": iob_record["sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-manifest", type=Path, required=True)
    parser.add_argument("--validation-contract", type=Path, required=True)
    parser.add_argument("--delivery-manifest", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--stable-entry", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--resolved-geometry", type=Path, required=True)
    parser.add_argument("--formal-lua", type=Path, required=True)
    args = parser.parse_args()
    result = validate(
        args.asset_manifest,
        args.validation_contract,
        args.delivery_manifest,
        args.formal_root,
        args.stable_entry,
        args.baseline,
        args.resolved_geometry,
        args.formal_lua,
    )
    print(
        "OATOF_FORMAL_ANALYZER_RELEASE=PASS "
        f"RELEASE={result['release_id']} DELIVERY={result['delivery_run_id']}"
    )


if __name__ == "__main__":
    main()
