"""Cache MR-TOF 0.25-mm fixed Dirichlet operating PAs.

This adapter owns only the project identity.  Immutable publication, byte
validation, locking, and writable materialization are delegated to
``common.simion.pa_family_cache``.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import (
    CacheDisposition,
    CacheProbe,
    PAFamilyCacheError,
    canonical_pa_family_cache_key,
    materialize_pa_family_cache,
    probe_pa_family_cache,
    publish_pa_family_cache,
    validate_pa_family_cache_generation,
)


SCHEMA_VERSION = 1
ROLE = "mrtof_fixed_dirichlet_operating_pa"
MIRROR_GROUPS = ("mirror_B", "mirror_C", "mirror_D", "mirror_E")
FIXED_ZERO_GROUPS = (
    "drift_stripe_set_1",
    "drift_stripe_set_2",
    "prism_1",
    "prism_2",
)
FINE_MESH_MM_PER_GU = (0.25, 0.25, 0.25)
PARENT_MESH_MM_PER_GU = (0.5, 0.5, 0.5)
LOCAL_CONTRACT_ROLE = "mrtof_analyzer_local_pa_family_contract"
MIRROR_REGIONS = ("mirror_turn_negative", "mirror_turn_positive")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PAFamilyCacheError(f"{label} must be a JSON object: {path}")
    return value


def _content_identity(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise PAFamilyCacheError(f"{label} is missing: {path}")
    return {"bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _output_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).name != value
        or value in {"cache_manifest.json", "current_generation.json"}
    ):
        raise PAFamilyCacheError(
            f"fixed operating PA output name must be one direct filename: {value!r}"
        )
    return value


def _mirror_voltages(values: Sequence[float]) -> dict[str, float]:
    if isinstance(values, (str, bytes)) or len(values) != len(MIRROR_GROUPS):
        raise PAFamilyCacheError("fixed operating PA requires exactly four B-E voltages")
    result: dict[str, float] = {}
    for group, raw_value in zip(MIRROR_GROUPS, values, strict=True):
        value = float(raw_value)
        if not math.isfinite(value):
            raise PAFamilyCacheError(f"fixed operating PA voltage is not finite: {group}")
        result[group] = value
    return result


def _validated_local_contract(
    path: Path,
) -> tuple[dict[str, Any], Mapping[str, Any], str]:
    contract = _load_object(path, "local-family contract")
    if (
        contract.get("schema_version") != 1
        or contract.get("role") != LOCAL_CONTRACT_ROLE
        or contract.get("status") != "buildable"
    ):
        raise PAFamilyCacheError("local-family contract role, version, or status differs")
    region = contract.get("region")
    if region not in MIRROR_REGIONS:
        raise PAFamilyCacheError("fixed operating PA requires a mirror-turn local-family contract")
    scale_factor = contract.get("scale_factor")
    if (
        isinstance(scale_factor, bool)
        or not isinstance(scale_factor, (int, float))
        or float(scale_factor) != 0.25
    ):
        raise PAFamilyCacheError("fixed operating PA requires the 0.25-mm local-family contract")
    identity = contract.get("identity")
    if not isinstance(identity, Mapping):
        raise PAFamilyCacheError("local-family contract has no cache identity")
    family_key = canonical_pa_family_cache_key(identity)
    mesh = identity.get("mesh")
    if not isinstance(mesh, Mapping) or tuple(mesh.get("mm_per_gu", ())) != FINE_MESH_MM_PER_GU:
        raise PAFamilyCacheError("local-family contract mesh is not 0.25 mm/gu in all axes")
    namespace = identity.get("basis_namespace")
    local_ids = namespace.get("local_group_ids") if isinstance(namespace, Mapping) else None
    expected_groups = (*MIRROR_GROUPS, *FIXED_ZERO_GROUPS)
    if (
        not isinstance(local_ids, Mapping)
        or set(local_ids) != set(expected_groups)
        or any(local_ids[group] != index for index, group in enumerate(expected_groups, 1))
    ):
        raise PAFamilyCacheError("local-family contract voltage-group namespace differs")
    return contract, identity, family_key


def build_fixed_dirichlet_operating_pa_identity(
    local_family_contract_path: Path,
    parent_half_mm_pa_path: Path,
    target_mirror_voltages_v: Sequence[float],
    dirichlet_builder_path: Path,
    output_name: str,
) -> dict[str, Any]:
    """Bind one fixed fine-grid solve to every numerical and builder input."""
    contract, family_identity, family_key = _validated_local_contract(
        local_family_contract_path
    )
    voltages = _mirror_voltages(target_mirror_voltages_v)
    name = _output_name(output_name)
    local_contract_content = _content_identity(
        local_family_contract_path, "local-family contract"
    )
    parent_content = _content_identity(parent_half_mm_pa_path, "parent 0.5-mm PA")
    builder_content = _content_identity(dirichlet_builder_path, "Dirichlet builder")
    return {
        "geometry": {
            "artifact_role": ROLE,
            "schema_version": SCHEMA_VERSION,
            "local_family_contract": {
                "content": local_contract_content,
                "family_cache_key": family_key,
                "region": contract["region"],
                "scale_factor": float(contract["scale_factor"]),
            },
            "parent_operating_pa": {
                "content": parent_content,
                "mesh_mm_per_gu": list(PARENT_MESH_MM_PER_GU),
            },
        },
        "gem": family_identity["gem"],
        "basis_namespace": {
            "local_group_ids": family_identity["basis_namespace"]["local_group_ids"],
            "target_voltage_by_group_v": voltages,
            "fixed_zero_groups": list(FIXED_ZERO_GROUPS),
        },
        "mesh": family_identity["mesh"],
        "grid_phase": family_identity["grid_phase"],
        "surface": family_identity["surface"],
        "simion_identity": family_identity["simion_identity"],
        "refine_policy": {
            "mode": "installed_default",
            "convergence_override": None,
            "operation": "fixed_dirichlet_operating_pa_refine",
            "parent_mesh_mm_per_gu": list(PARENT_MESH_MM_PER_GU),
            "local_family_refine_policy": family_identity["refine_policy"],
        },
        "builder_identity": {
            "operation": "build_dirichlet_patch_operating_pa",
            "implementation": builder_content,
            "output_name": name,
        },
    }


def probe_fixed_dirichlet_operating_pa_cache(
    cache_root: Path, identity: Mapping[str, Any], output_name: str,
):
    """Probe one fixed operating PA through the shared cache."""
    return probe_pa_family_cache(
        cache_root, identity, expected_filenames=(_output_name(output_name),)
    )


def publish_fixed_dirichlet_operating_pa_cache(
    cache_root: Path,
    identity: Mapping[str, Any],
    output_name: str,
    source_directory: Path,
):
    """Publish one completed fixed operating PA through the shared cache."""
    return publish_pa_family_cache(
        cache_root, identity, source_directory, (_output_name(output_name),)
    )


def materialize_fixed_dirichlet_operating_pa_cache(
    cache_root: Path,
    identity: Mapping[str, Any],
    output_name: str,
    destination_directory: Path,
    expected_generation_sha256: str | None = None,
):
    """Materialize an exact cache hit as a writable private PA."""
    name = _output_name(output_name)
    cache_key = canonical_pa_family_cache_key(identity)
    if expected_generation_sha256 is None:
        probe = probe_pa_family_cache(cache_root, identity, expected_filenames=(name,))
        if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
            raise PAFamilyCacheError(
                f"cannot materialize fixed operating PA {probe.cache_key}: "
                f"{probe.disposition.value}: {probe.detail}"
            )
        generation = probe.generation_directory
    else:
        generation_sha256 = str(expected_generation_sha256).upper()
        if len(generation_sha256) != 64 or any(
            character not in "0123456789ABCDEF" for character in generation_sha256
        ):
            raise PAFamilyCacheError("expected fixed operating PA generation SHA-256 is invalid")
        generation = Path(cache_root) / cache_key / "generations" / generation_sha256
        manifest = validate_pa_family_cache_generation(
            generation, expected_cache_key=cache_key, expected_filenames=(name,)
        )
        if str(manifest["generation_sha256"]).upper() != generation_sha256:
            raise PAFamilyCacheError("fixed operating PA generation identity differs")
        probe = CacheProbe(
            CacheDisposition.HIT,
            cache_key,
            generation_directory=generation,
            detail="pinned_generation_verified",
        )
    return probe, materialize_pa_family_cache(
        generation,
        destination_directory,
        expected_filenames=(name,),
    )


def _parse_voltages(value: str) -> tuple[float, ...]:
    try:
        values = tuple(float(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("B-E voltages must be comma-separated numbers") from exc
    if len(values) != len(MIRROR_GROUPS) or any(not math.isfinite(item) for item in values):
        raise argparse.ArgumentTypeError("B-E voltages must contain exactly four finite numbers")
    return values


def main(arguments: Sequence[str] | None = None) -> int:
    """Run one explicit cache operation without invoking SIMION."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("probe", "publish", "materialize"), required=True)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--local-family-contract", required=True, type=Path)
    parser.add_argument("--parent-half-mm-pa", required=True, type=Path)
    parser.add_argument("--target-mirror-voltages-v", required=True, type=_parse_voltages)
    parser.add_argument("--dirichlet-builder", required=True, type=Path)
    parser.add_argument("--output-name", required=True)
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--destination-directory", type=Path)
    parser.add_argument("--expected-generation-sha256")
    args = parser.parse_args(arguments)
    identity = build_fixed_dirichlet_operating_pa_identity(
        args.local_family_contract,
        args.parent_half_mm_pa,
        args.target_mirror_voltages_v,
        args.dirichlet_builder,
        args.output_name,
    )
    if args.action == "probe":
        if (
            args.source_directory is not None
            or args.destination_directory is not None
            or args.expected_generation_sha256 is not None
        ):
            parser.error("probe accepts no source, destination, or expected generation")
        result = probe_fixed_dirichlet_operating_pa_cache(
            args.cache_root, identity, args.output_name
        )
        document: dict[str, Any] = {
            "identity": identity,
            "disposition": result.disposition.value,
            "cache_key": result.cache_key,
            "generation_directory": (
                str(result.generation_directory) if result.generation_directory else None
            ),
            "detail": result.detail,
        }
    elif args.action == "publish":
        if (
            args.source_directory is None
            or args.destination_directory is not None
            or args.expected_generation_sha256 is not None
        ):
            parser.error("publish requires --source-directory and forbids destination or expected generation")
        result = publish_fixed_dirichlet_operating_pa_cache(
            args.cache_root, identity, args.output_name, args.source_directory
        )
        document = {
            "identity": identity,
            "disposition": result.disposition.value,
            "cache_key": result.cache_key,
            "generation_sha256": result.generation_sha256,
            "generation_directory": str(result.generation_directory),
        }
    else:
        if args.destination_directory is None or args.source_directory is not None:
            parser.error("materialize requires --destination-directory and forbids --source-directory")
        probe, result = materialize_fixed_dirichlet_operating_pa_cache(
            args.cache_root,
            identity,
            args.output_name,
            args.destination_directory,
            args.expected_generation_sha256,
        )
        document = {
            "identity": identity,
            "disposition": "materialized",
            "cache_key": probe.cache_key,
            "generation_sha256": probe.generation_directory.name,
            "generation_directory": str(probe.generation_directory),
            "destination_directory": str(result.destination_directory),
            "files": list(result.files),
        }
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
