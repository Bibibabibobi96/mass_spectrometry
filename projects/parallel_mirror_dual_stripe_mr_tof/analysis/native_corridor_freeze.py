"""Freeze the small, solver-independent inputs for one native corridor build.

The published directory contains only the derived plan, the canonical PA-family
identity, the validated upstream response recipe, and a manifest covering those
three files.  Large PA payloads are never hashed here: their already-published
generation manifests supply the trusted byte counts and SHA-256 identities.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import (
    PAFamilyCacheError,
    canonical_pa_family_cache_key,
    validate_pa_family_cache_generation,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_plan import (
    derive_native_corridor_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_geometry import (
    build_native_corridor_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_identity import (
    build_native_corridor_identity,
    native_corridor_family_filenames,
)


PLAN_NAME = "native_corridor_plan.json"
IDENTITY_NAME = "native_corridor_identity.json"
RECIPE_NAME = "native_corridor_response_recipe.json"
MANIFEST_NAME = "native_corridor_freeze_manifest.json"
FROZEN_NAMES = (PLAN_NAME, IDENTITY_NAME, RECIPE_NAME, MANIFEST_NAME)


def _canonical_json(document: object) -> bytes:
    """Return deterministic UTF-8 JSON bytes for a frozen contract."""

    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _sha256_text(value: object, label: str) -> str:
    text = str(value).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise CandidateContractError(f"{label} must be one SHA-256")
    return text


def _trusted_generation(manifest_path: Path, label: str) -> dict[str, Any]:
    """Validate generation metadata and sizes without reading PA payload bytes."""

    manifest_path = manifest_path.resolve()
    if manifest_path.name != "cache_manifest.json":
        raise CandidateContractError(f"{label} must be a PA cache_manifest.json")
    try:
        manifest = validate_pa_family_cache_generation(
            manifest_path.parent, verify_payload=False
        )
    except PAFamilyCacheError as exc:
        raise CandidateContractError(f"{label} is not a trusted PA generation") from exc
    records = {
        str(record["name"]): {
            "name": str(record["name"]),
            "bytes": int(record["bytes"]),
            "sha256": _sha256_text(record["sha256"], f"{label} member SHA-256"),
        }
        for record in manifest["files"]
    }
    return {
        "generation_directory": manifest_path.parent,
        "cache_key": _sha256_text(manifest["cache_key"], f"{label} cache key"),
        "generation_sha256": _sha256_text(
            manifest["generation_sha256"], f"{label} generation"
        ),
        "manifest": {
            "bytes": manifest_path.stat().st_size,
            "sha256": file_sha256(manifest_path).lower(),
        },
        "records": records,
    }


def _derived_recipe(
    plan: Mapping[str, Any],
    source_manifest_path: Path,
    coarse_manifest_path: Path,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Derive all eight response groups from the plan and two generations."""

    source = _trusted_generation(source_manifest_path, "source generation")
    coarse = _trusted_generation(coarse_manifest_path, "coarse raw generation")
    mapping_value = plan.get("physical_to_local_electrode_id")
    if not isinstance(mapping_value, dict):
        raise CandidateContractError("corridor plan has no physical-to-local mapping")
    mapping = {int(physical): int(local) for physical, local in mapping_value.items()}
    grouped = {
        local: sorted(physical for physical, mapped in mapping.items() if mapped == local)
        for local in range(1, 9)
    }
    if any(not physical_ids for physical_ids in grouped.values()):
        raise CandidateContractError("corridor plan does not define all local response IDs 1..8")
    expected_physical_ids = {physical for values in grouped.values() for physical in values}
    response_pattern = re.compile(r"mrtof_analyzer\.response([1-9][0-9]*)\.pa")
    observed_by_id: dict[int, dict[str, Any]] = {}
    for name, record in source["records"].items():
        match = response_pattern.fullmatch(name)
        if match is None:
            raise CandidateContractError(
                f"source generation contains a non-response member: {name}"
            )
        physical_id = int(match.group(1))
        if physical_id in observed_by_id:
            raise CandidateContractError(
                f"source generation repeats physical response ID {physical_id}"
            )
        observed_by_id[physical_id] = record
    if set(observed_by_id) != expected_physical_ids:
        missing = sorted(expected_physical_ids - set(observed_by_id))
        extra = sorted(set(observed_by_id) - expected_physical_ids)
        raise CandidateContractError(
            f"source generation response IDs differ; missing={missing}, extra={extra}"
        )
    if set(coarse["records"]) != {"mrtof_analyzer.pa#"}:
        raise CandidateContractError(
            "coarse generation must contain only mrtof_analyzer.pa#"
        )
    output_names = native_corridor_family_filenames()[2:]
    responses: list[dict[str, Any]] = []
    for local_id in range(1, 9):
        physical_ids = grouped[local_id]
        records = [observed_by_id[physical_id] for physical_id in physical_ids]
        responses.append(
            {
                "group": f"local_response_{local_id}",
                "local_id": local_id,
                "physical_ids": physical_ids,
                "source_basis_paths": [
                    str((source["generation_directory"] / record["name"]).resolve())
                    for record in records
                ],
                "source_basis_identities": [
                    {"bytes": record["bytes"], "sha256": record["sha256"]}
                    for record in records
                ],
                "output_filename": output_names[local_id - 1],
            }
        )
    coarse_record = coarse["records"]["mrtof_analyzer.pa#"]
    coarse_raw_path = (
        coarse["generation_directory"] / coarse_record["name"]
    ).resolve()
    recipe = {
        "schema_version": 1,
        "role": "mrtof_native_corridor_response_recipe",
        "source_generation_identity": {
            "cache_key": source["cache_key"],
            "generation_sha256": source["generation_sha256"],
        },
        "coarse_raw_generation_identity": {
            "cache_key": coarse["cache_key"],
            "generation_sha256": coarse["generation_sha256"],
        },
        "coarse_raw_member": {
            "name": coarse_record["name"],
            "bytes": coarse_record["bytes"],
            "sha256": coarse_record["sha256"],
        },
        "response_recipes": responses,
    }
    provenance = {
        "source_generation": {
            "cache_key": source["cache_key"],
            "generation_sha256": source["generation_sha256"],
            "manifest": source["manifest"],
        },
        "coarse_raw_generation": {
            "cache_key": coarse["cache_key"],
            "generation_sha256": coarse["generation_sha256"],
            "manifest": coarse["manifest"],
        },
    }
    return recipe, coarse_raw_path, provenance


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path).lower(),
    }


def _same_frozen_directory(existing: Path, staged: Path) -> bool:
    if not existing.is_dir() or existing.is_symlink():
        return False
    if {item.name for item in existing.iterdir()} != set(FROZEN_NAMES):
        return False
    return all((existing / name).read_bytes() == (staged / name).read_bytes() for name in FROZEN_NAMES)


def _seal_frozen_directory(directory: Path) -> None:
    """Make the four small frozen contracts read-only after publication."""

    for name in FROZEN_NAMES:
        path = directory / name
        path.chmod(path.stat().st_mode & ~stat.S_IWRITE)


def freeze_native_corridor_inputs(
    *,
    contract_path: Path,
    source_generation_manifest: Path,
    coarse_generation_manifest: Path,
    simion_executable: Path,
    simion_release: str,
    output_directory: Path,
    canonical_gem_path: Path | None = None,
) -> dict[str, Any]:
    """Atomically publish one deterministic four-file corridor freeze package.

    Existing identical output is a cache hit.  Existing non-identical output,
    any recipe/generation mismatch, or any missing source fails without
    replacing the prior package.
    """

    contract_path = contract_path.resolve()
    simion_executable = simion_executable.resolve()
    output_directory = output_directory.resolve()
    if not contract_path.is_file() or not simion_executable.is_file():
        raise CandidateContractError("corridor freeze requires contract and SIMION executable")
    if not isinstance(simion_release, str) or not simion_release.strip():
        raise CandidateContractError("corridor freeze requires a SIMION release label")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}.freeze-", dir=output_directory.parent)
    )
    try:
        plan = derive_native_corridor_plan(contract_path)
        recipe, coarse_raw_path, upstream = _derived_recipe(
            plan,
            source_generation_manifest,
            coarse_generation_manifest,
        )
        plan_path = stage / PLAN_NAME
        recipe_path = stage / RECIPE_NAME
        plan_path.write_bytes(_canonical_json(plan))
        recipe_path.write_bytes(_canonical_json(recipe))
        transient_gem = canonical_gem_path is None
        gem_path = stage / ".canonical_corridor.gem" if transient_gem else canonical_gem_path.resolve()
        if transient_gem:
            gem_path.write_text(
                build_native_corridor_gem(contract_path), encoding="utf-8", newline="\n"
            )
        identity = build_native_corridor_identity(
            contract_path,
            gem_path,
            simion_executable,
            simion_release,
            recipe_path,
            coarse_raw_path,
        )
        identity_path = stage / IDENTITY_NAME
        identity_path.write_bytes(_canonical_json(identity))
        if transient_gem:
            gem_path.unlink()
        files = [_file_record(path) for path in (identity_path, plan_path, recipe_path)]
        files.sort(key=lambda item: item["name"])
        manifest = {
            "schema_version": 1,
            "role": "mrtof_native_corridor_frozen_inputs",
            "status": "frozen",
            "pa_family_cache_key": canonical_pa_family_cache_key(identity),
            "inputs": {
                "baseline_contract": {
                    "bytes": contract_path.stat().st_size,
                    "sha256": file_sha256(contract_path).lower(),
                },
                "canonical_gem": identity["gem"],
                "simion_identity": identity["simion_identity"],
                **upstream,
            },
            "files": files,
        }
        (stage / MANIFEST_NAME).write_bytes(_canonical_json(manifest))
        if {item.name for item in stage.iterdir()} != set(FROZEN_NAMES):
            raise CandidateContractError("corridor freeze staging contains unexpected files")
        if output_directory.exists():
            if not _same_frozen_directory(output_directory, stage):
                raise CandidateContractError(
                    "existing corridor freeze directory differs from requested inputs"
                )
            _seal_frozen_directory(output_directory)
            disposition = "hit"
        else:
            try:
                os.replace(stage, output_directory)
            except FileExistsError:
                if not _same_frozen_directory(output_directory, stage):
                    raise CandidateContractError(
                        "concurrent corridor freeze publication differs"
                    )
                disposition = "hit"
            else:
                _seal_frozen_directory(output_directory)
                disposition = "published"
        return {
            "disposition": disposition,
            "output_directory": str(output_directory),
            "pa_family_cache_key": manifest["pa_family_cache_key"],
            "files": list(FROZEN_NAMES),
        }
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--source-generation-manifest", required=True, type=Path)
    parser.add_argument("--coarse-generation-manifest", required=True, type=Path)
    parser.add_argument("--simion-executable", required=True, type=Path)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--canonical-gem", type=Path)
    arguments = parser.parse_args()
    result = freeze_native_corridor_inputs(
        contract_path=arguments.contract,
        source_generation_manifest=arguments.source_generation_manifest,
        coarse_generation_manifest=arguments.coarse_generation_manifest,
        simion_executable=arguments.simion_executable,
        simion_release=arguments.simion_release,
        output_directory=arguments.output_directory,
        canonical_gem_path=arguments.canonical_gem,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
