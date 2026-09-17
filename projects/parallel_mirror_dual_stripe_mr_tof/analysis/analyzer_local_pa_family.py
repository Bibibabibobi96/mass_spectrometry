"""Derive the immutable identity and build recipe for a local analyser PA family."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry import (
    REGIONS,
    _profile_key,
    build_local_patch_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_refinement_plan import (
    derive_local_refinement_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def local_family_prefix(region: str) -> str:
    if region not in REGIONS:
        raise CandidateContractError(f"unsupported analyser patch region: {region}")
    return f"mrtof_analyzer_local_{region}"


def local_pa_family_filenames(region: str, group_count: int) -> tuple[str, ...]:
    if not isinstance(group_count, int) or isinstance(group_count, bool) or group_count <= 0:
        raise CandidateContractError("local PA group count must be a positive integer")
    prefix = local_family_prefix(region)
    return (
        f"{prefix}.pa#",
        f"{prefix}.pa0",
        *(f"{prefix}.pa{index}" for index in range(1, group_count + 1)),
        *(f"{prefix}.response{index}.pa" for index in range(1, group_count + 1)),
    )


def _sha256(value: object, label: str) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdefABCDEF" for character in text):
        raise CandidateContractError(f"prepared analyzer {label} SHA-256 is invalid")
    return text.upper()


def _prepared_source_metadata(receipt_path: Path, required_ids: set[int]) -> dict[str, Any]:
    """Read the immutable source receipt without opening PA payloads.

    The returned paths are deliberately *not* suitable for SIMION.  A runner
    must later provide a guarded short-copy binding before the build recipe
    exposes an actual PA path.
    """
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        prepared = receipt["prepared_standalone_generation"]
        raw = receipt["raw_geometry_generation"]
        responses = prepared["responses_by_physical_id"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CandidateContractError("prepared analyzer source receipt is invalid") from exc
    if receipt.get("role") != "mrtof_reviewed_analyzer_source_cache_receipt" or receipt.get("status") != "success":
        raise CandidateContractError("prepared analyzer source receipt is not successful")

    def generation(value: object, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CandidateContractError(f"prepared analyzer {label} generation is invalid")
        key = _sha256(value.get("cache_key"), f"{label} cache key")
        sha = _sha256(value.get("generation_sha256"), f"{label} generation")
        inventory = value.get("inventory")
        if not isinstance(inventory, list) or not inventory:
            raise CandidateContractError(f"prepared analyzer {label} inventory is invalid")
        return {"cache_key": key, "generation_sha256": sha, "inventory": inventory}

    prepared_identity = generation(prepared, "standalone")
    raw_identity = generation(raw, "raw")
    members: dict[int, dict[str, Any]] = {}
    if not isinstance(responses, dict):
        raise CandidateContractError("prepared analyzer response table is invalid")
    for identifier in required_ids:
        record = responses.get(str(identifier))
        if not isinstance(record, dict) or int(record.get("physical_id", -1)) != identifier:
            raise CandidateContractError(f"prepared analyzer response {identifier} is missing")
        name = str(record.get("name", ""))
        if Path(name).name != name or not name.endswith(".pa"):
            raise CandidateContractError(f"prepared analyzer response {identifier} filename is invalid")
        try:
            size = int(record["bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CandidateContractError(f"prepared analyzer response {identifier} bytes are invalid") from exc
        if size < 0:
            raise CandidateContractError(f"prepared analyzer response {identifier} bytes are invalid")
        members[identifier] = {"physical_id": identifier, "name": name, "bytes": size,
                               "sha256": _sha256(record.get("sha256"), f"response {identifier}")}
    raw_record = raw.get("raw_geometry")
    if not isinstance(raw_record, dict) or str(raw_record.get("name", "")) != "mrtof_analyzer.pa#":
        raise CandidateContractError("prepared analyzer raw geometry is invalid")
    try:
        raw_size = int(raw_record["bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateContractError("prepared analyzer raw geometry bytes are invalid") from exc
    raw_member = {"name": "mrtof_analyzer.pa#", "bytes": raw_size,
                  "sha256": _sha256(raw_record.get("sha256"), "raw geometry")}
    return {"prepared": prepared_identity, "raw": raw_identity,
            "responses": members, "raw_member": raw_member}


def _binding_paths(binding_path: Path, metadata: dict[str, Any]) -> tuple[dict[int, Path], Path]:
    """Validate a runner-produced guarded-copy binding and return only copies."""
    try:
        binding = json.loads(binding_path.read_text(encoding="utf-8-sig"))
        prepared = binding["prepared_standalone_generation"]
        raw = binding["raw_geometry_generation"]
        responses = binding["responses_by_physical_id"]
        raw_record = binding["raw_geometry"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CandidateContractError("prepared analyzer source binding is invalid") from exc
    if binding.get("role") != "mrtof_prepared_analyzer_source_binding" or binding.get("status") != "success":
        raise CandidateContractError("prepared analyzer source binding is not successful")
    for label, actual, expected in (("standalone", prepared, metadata["prepared"]), ("raw", raw, metadata["raw"])):
        if not isinstance(actual, dict) or actual.get("cache_key") != expected["cache_key"] or actual.get("generation_sha256") != expected["generation_sha256"]:
            raise CandidateContractError(f"prepared analyzer {label} binding identity differs")
    paths: dict[int, Path] = {}
    if not isinstance(responses, dict):
        raise CandidateContractError("prepared analyzer binding responses are invalid")
    for identifier, expected in metadata["responses"].items():
        record = responses.get(str(identifier))
        if not isinstance(record, dict) or any(record.get(field) != expected[field] for field in ("name", "bytes", "sha256")):
            raise CandidateContractError(f"prepared analyzer binding response {identifier} differs")
        path = Path(str(record.get("binding_path", "")))
        if not path.is_absolute() or path.name != expected["name"]:
            raise CandidateContractError(f"prepared analyzer binding response {identifier} path is invalid")
        paths[identifier] = path
    if not isinstance(raw_record, dict) or any(raw_record.get(field) != metadata["raw_member"][field] for field in ("name", "bytes", "sha256")):
        raise CandidateContractError("prepared analyzer binding raw geometry differs")
    raw_path = Path(str(raw_record.get("binding_path", "")))
    if not raw_path.is_absolute() or raw_path.name != "mrtof_analyzer.pa#":
        raise CandidateContractError("prepared analyzer binding raw geometry path is invalid")
    return paths, raw_path


def derive_local_pa_family_contract(
    contract_path: Path,
    region: str,
    scale_factor: float,
    local_gem_path: Path,
    global_family_directory: Path,
    simion_executable: Path,
    simion_release: str,
    prepared_source_receipt: Path | None = None,
    prepared_source_binding: Path | None = None,
) -> dict[str, Any]:
    """Return a content identity plus the exact per-response build recipe."""
    if not simion_release.strip() or not simion_executable.is_file():
        raise CandidateContractError("local PA family requires a SIMION release and executable")
    plan = derive_local_refinement_plan(contract_path)
    profile_key = _profile_key(region)
    selected: dict[str, Any] | None = None
    for profile in plan["profiles"]:
        if float(profile["scale_factor"]) == float(scale_factor):
            selected = profile[profile_key]
            break
    if selected is None:
        raise CandidateContractError("local PA family scale is not declared")
    canonical_gem = build_local_patch_gem(contract_path, region, scale_factor).encode("utf-8")
    if not local_gem_path.is_file() or local_gem_path.read_bytes() != canonical_gem:
        raise CandidateContractError("local patch GEM differs from the canonical contract-derived text")
    groups = plan["response_voltage_groups"]
    prepared_paths: dict[int, Path] | None = None
    prepared_metadata: dict[str, Any] | None = None
    global_raw: Path | None = None
    if prepared_source_receipt is not None:
        required_ids = {item for values in groups.values() for item in values}
        prepared_metadata = _prepared_source_metadata(prepared_source_receipt, required_ids)
        if prepared_source_binding is not None:
            prepared_paths, global_raw = _binding_paths(prepared_source_binding, prepared_metadata)
        else:
            # Planning/probing is intentionally payload-free. These opaque
            # placeholders can never be passed to SIMION: only a binding turns
            # this plan into an executable recipe.
            prepared_paths = {
                identifier: Path(f"prepared://{prepared_metadata['prepared']['generation_sha256']}/{record['name']}")
                for identifier, record in prepared_metadata["responses"].items()
            }
            global_raw = Path(f"prepared://{prepared_metadata['raw']['generation_sha256']}/mrtof_analyzer.pa#")
    elif prepared_source_binding is not None:
        raise CandidateContractError("prepared analyzer source binding requires a receipt")
    local_ids = plan["local_fast_adjust_group_ids"]
    recipes: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for name, physical_ids in groups.items():
        paths: list[str] = []
        for identifier in physical_ids:
            path = prepared_paths[identifier] if prepared_paths is not None else global_family_directory / f"mrtof_analyzer.pa{identifier}"
            if prepared_metadata is None and not path.is_file():
                raise CandidateContractError(f"global analyser basis is missing: {path}")
            if prepared_metadata is None:
                source_hashes[path.name] = file_sha256(path)
            else:
                source_hashes[path.name] = prepared_metadata["responses"][identifier]["sha256"]
            paths.append(str(path.resolve()))
        recipes.append({
            "group": name,
            "local_id": int(local_ids[name]),
            "physical_ids": list(physical_ids),
            "source_basis_paths": paths,
            "output_filename": f"{local_family_prefix(region)}.pa{int(local_ids[name])}",
            "standalone_response_filename": (
                f"{local_family_prefix(region)}.response{int(local_ids[name])}.pa"
            ),
        })
    global_raw = global_raw if prepared_paths is not None else global_family_directory / "mrtof_analyzer.pa#"
    if prepared_metadata is None and not global_raw.is_file():
        raise CandidateContractError("global analyser raw geometry PA is missing")
    source_hashes[global_raw.name] = (
        prepared_metadata["raw_member"]["sha256"] if prepared_metadata is not None else file_sha256(global_raw)
    )
    project_root = Path(__file__).resolve().parents[1]
    repository_root = project_root.parents[1]
    common_simion = repository_root / "common" / "simion"
    patch_origin = [float(value) for value in selected["box_project_mm"][:3]]
    family_names = local_pa_family_filenames(region, len(groups))
    identity = {
        "geometry": {
            "component_role": "mrtof_analyzer_local_dirichlet_pa_family",
            "region": region,
            "representation": "contract_derived_clipped_analyzer_gem_utf8_lf_v1",
            "coarse_parent_family": {
                "origin_project_mm": plan["baseline"]["box_project_mm"][:3],
                "mesh_mm_per_gu": plan["baseline"]["mesh_mm_per_gu"],
                "source_file_sha256": dict(sorted(source_hashes.items())),
            },
        },
        "gem": {"sha256": hashlib.sha256(canonical_gem).hexdigest().upper()},
        "basis_namespace": {
            "local_group_ids": local_ids,
            "physical_to_local_electrode_id": plan["physical_to_local_electrode_id"],
            "fixed_zero_electrode_ids": plan["fixed_zero_electrode_ids"],
        },
        "mesh": {"mm_per_gu": selected["mesh_mm_per_gu"]},
        "grid_phase": {
            "origin_project_mm": patch_origin,
            "box_project_mm": selected["box_project_mm"],
            "grid_shape": selected["grid_shape"],
        },
        "surface": "none",
        "simion_identity": {
            "release": simion_release,
            "executable_sha256": file_sha256(simion_executable),
        },
        "refine_policy": {
            "mode": "installed_default",
            "convergence_override": None,
            "solutions": "zero_pa0_and_each_contract_response_group",
            "dirichlet_boundary": {
                "source": "coarse_basis_trilinear_potential_vc_on_all_six_faces",
                "rule": plan["boundary_rule"],
            },
        },
        "builder_identity": {
            "geometry_generator_sha256": file_sha256(Path(__file__).with_name("analyzer_local_patch_geometry.py")),
            "family_adapter_sha256": file_sha256(Path(__file__)),
            "id_remapper_sha256": file_sha256(common_simion / "remap_pa_electrode_ids.lua"),
            "dirichlet_builder_sha256": file_sha256(common_simion / "build_dirichlet_patch_basis.lua"),
            "standalone_response_exporter_sha256": file_sha256(common_simion / "export_standalone_pa.lua"),
            "private_family_stability_policy": (
                "two_consecutive_full_byte_inventories_before_cache_publication_v1"
            ),
        },
    }
    if prepared_metadata is not None:
        identity["geometry"]["prepared_source"] = {
            "prepared_standalone_generation": prepared_metadata["prepared"],
            "raw_geometry_generation": prepared_metadata["raw"],
            "responses_by_physical_id": {
                str(identifier): prepared_metadata["responses"][identifier]
                for identifier in sorted(prepared_metadata["responses"])
            },
            "raw_geometry": prepared_metadata["raw_member"],
        }
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_local_pa_family_contract",
        "status": "buildable",
        "qualification": "local_basis_build_contract__interface_not_yet_verified",
        "region": region,
        "scale_factor": float(scale_factor),
        "family_prefix": local_family_prefix(region),
        "family_filenames": list(family_names),
        "raw_physical_to_local_electrode_id": plan["physical_to_local_electrode_id"],
        "coarse_origin_project_mm": plan["baseline"]["box_project_mm"][:3],
        "coarse_raw_pa_path": str(global_raw.resolve()),
        "patch_origin_project_mm": patch_origin,
        "zero_response": {
            "source_basis_paths": [], "active_local_ids": [],
            "output_filename": f"{local_family_prefix(region)}.pa0",
        },
        "response_recipes": recipes,
        "identity": identity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--region", required=True, choices=REGIONS)
    parser.add_argument("--scale-factor", required=True, type=float)
    parser.add_argument("--local-gem", required=True, type=Path)
    parser.add_argument("--global-family-directory", required=True, type=Path)
    parser.add_argument("--prepared-source-receipt", type=Path)
    parser.add_argument("--prepared-source-binding", type=Path)
    parser.add_argument("--simion-executable", required=True, type=Path)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    document = derive_local_pa_family_contract(
        arguments.contract, arguments.region, arguments.scale_factor,
        arguments.local_gem, arguments.global_family_directory,
        arguments.simion_executable, arguments.simion_release, arguments.prepared_source_receipt,
        arguments.prepared_source_binding,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
