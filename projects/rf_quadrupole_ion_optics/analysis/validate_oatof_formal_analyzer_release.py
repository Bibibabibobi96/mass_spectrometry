"""Validate the current oa-TOF Formal SIMION analyzer release for transport use."""

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


def _verify_stable_manifest_record(
    record: dict[str, Any], path: Path, expected_relative_path: str
) -> None:
    if record.get("relative_path") != expected_relative_path:
        raise ValueError(
            f"Stable manifest path differs: {record.get('relative_path')}"
        )
    if path.stat().st_size != int(record["bytes"]) or _sha256(path) != record["sha256"]:
        raise ValueError(f"Stable manifest identity differs: {path}")


def _delivery_asset_record(
    delivery: dict[str, Any], expected_name: str, expected_path: Path
) -> dict[str, Any]:
    matches = [
        record
        for record in delivery.get("assets", {}).values()
        if record.get("path") == expected_name
    ]
    if len(matches) != 1:
        raise ValueError(f"Formal delivery asset must resolve uniquely: {expected_name}")
    record = matches[0]
    if (
        expected_path.stat().st_size != int(record["bytes"])
        or _sha256(expected_path) != record["sha256"]
    ):
        raise ValueError(f"Formal delivery asset identity differs: {expected_path}")
    return record


def _release_asset_record(
    asset_manifest: dict[str, Any],
    role: str,
    expected_relative_path: str,
    expected_path: Path,
) -> dict[str, Any]:
    record = asset_manifest.get("assets", {}).get(role)
    if not isinstance(record, dict):
        raise ValueError(f"Formal asset manifest requires one {role} record")
    _verify_file_record(record, expected_path, expected_relative_path)
    return record


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
    """Validate current Formal authority and the consumed analyzer assets."""
    asset_manifest = _load(asset_manifest_path)
    validation = _load(validation_contract_path)
    delivery = _load(delivery_manifest_path)
    stable = _load(stable_entry_path)
    resolved = _load(resolved_geometry_path)

    if (
        asset_manifest.get("schema_version") != 1
        or asset_manifest.get("role") != "formal_asset_manifest"
        or asset_manifest.get("project") != "single_reflection_oa_tof_mass_analyzer"
    ):
        raise ValueError("oaTOF Formal asset-manifest identity differs")
    if (
        validation.get("schema_version") != 5
        or validation.get("status") != "formal_cross_solver_validation"
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
        "projects/single_reflection_oa_tof_mass_analyzer/config/formal_validation.json",
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
        or delivery.get("schema_version") != 1
        or delivery.get("role") != "oa_tof_simion_formal_delivery_manifest"
        or delivery.get("status") != "success"
        or delivery.get("project") != "single_reflection_oa_tof_mass_analyzer"
        or delivery.get("release_id") != release_id
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

    checksum_path = formal_root / "SHA256SUMS.csv"
    required_assets = {
        "iob": ("simion_iob", "oatof_ideal_grounded.iob"),
        "con": ("simion_con", "oatof_ideal_grounded.con"),
        "program": ("simion_program", "oatof_ideal_grounded.lua"),
        "fly2": ("simion_fly2", "oatof_ideal_grounded.fly2"),
        "ion": ("shared_particle_table", "oatof_comsol_524amu_gaussian_N1000.ion"),
    }
    release_records: dict[str, dict[str, Any]] = {}
    for stable_role, (release_role, filename) in required_assets.items():
        path = formal_root / filename
        release_record = _release_asset_record(
            asset_manifest,
            release_role,
            f"simion/{filename}",
            path,
        )
        delivery_record_for_asset = _delivery_asset_record(delivery, filename, path)
        if (
            int(release_record["bytes"]) != int(delivery_record_for_asset["bytes"])
            or release_record["sha256"] != delivery_record_for_asset["sha256"]
        ):
            raise ValueError(
                f"oaTOF Formal {stable_role} release and delivery identities differ"
            )
        release_records[stable_role] = release_record
    checksum_record = _release_asset_record(
        asset_manifest,
        "simion_sha256_manifest",
        "simion/SHA256SUMS.csv",
        checksum_path,
    )
    iob_record = release_records["iob"]
    program_record = release_records["program"]
    if (
        simion.get("iob_artifact_relative_path")
        != "formal/simion/oatof_ideal_grounded.iob"
        or simion.get("iob_sha256") != iob_record["sha256"]
    ):
        raise ValueError("oaTOF Formal SIMION IOB differs from validation contract")

    entries = stable.get("entries", [])
    expected_required_assets = {
        role: release_role
        for role, (release_role, _filename) in required_assets.items()
    }
    if (
        stable.get("schema_version") != 2
        or stable.get("role")
        != "Stable runtime requirements and manifest bindings for the current formal SIMION delivery."
        or stable.get("artifact_workspace_relative") != "formal"
        or len(entries) != 1
        or entries[0].get("required_assets") != expected_required_assets
        or entries[0].get("gui_requirements")
        != {
            "expected_instances": 4,
            "trajectory_quality": 8,
            "program_enabled": True,
            "data_recording_enabled": True,
        }
    ):
        raise ValueError("oaTOF SIMION stable-entry identity differs")
    entry = entries[0]
    _verify_stable_manifest_record(
        entry.get("manifests", {}).get("formal_asset_manifest", {}),
        asset_manifest_path,
        "asset_manifest.json",
    )
    _verify_stable_manifest_record(
        entry.get("manifests", {}).get("simion_delivery_manifest", {}),
        delivery_manifest_path,
        "simion/run_manifest.json",
    )
    if _sha256(formal_lua_path) != program_record["sha256"]:
        raise ValueError("Frozen oaTOF Formal Lua differs from stable entry")

    return {
        "status": "PASS",
        "release_id": release_id,
        "delivery_run_id": delivery["release_id"],
        "iob_sha256": iob_record["sha256"],
        "checksum_sha256": checksum_record["sha256"],
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
