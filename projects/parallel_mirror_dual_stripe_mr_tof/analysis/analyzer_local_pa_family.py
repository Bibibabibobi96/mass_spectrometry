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
    return (f"{prefix}.pa#", f"{prefix}.pa0", *(f"{prefix}.pa{index}" for index in range(1, group_count + 1)))


def derive_local_pa_family_contract(
    contract_path: Path,
    region: str,
    scale_factor: float,
    local_gem_path: Path,
    global_family_directory: Path,
    simion_executable: Path,
    simion_release: str,
) -> dict[str, Any]:
    """Return a content identity plus the exact per-response build recipe."""
    if not simion_release.strip() or not simion_executable.is_file():
        raise CandidateContractError("local PA family requires a SIMION release and executable")
    plan = derive_local_refinement_plan(contract_path)
    profile_key = "mirror_turn" if region == "mirror_turn_positive" else region
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
    local_ids = plan["local_fast_adjust_group_ids"]
    recipes: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    for name, physical_ids in groups.items():
        paths: list[str] = []
        for identifier in physical_ids:
            path = global_family_directory / f"mrtof_analyzer.pa{identifier}"
            if not path.is_file():
                raise CandidateContractError(f"global analyser basis is missing: {path}")
            source_hashes[path.name] = file_sha256(path)
            paths.append(str(path.resolve()))
        recipes.append({
            "group": name,
            "local_id": int(local_ids[name]),
            "physical_ids": list(physical_ids),
            "source_basis_paths": paths,
            "output_filename": f"{local_family_prefix(region)}.pa{int(local_ids[name])}",
        })
    global_raw = global_family_directory / "mrtof_analyzer.pa#"
    if not global_raw.is_file():
        raise CandidateContractError("global analyser raw geometry PA is missing")
    source_hashes[global_raw.name] = file_sha256(global_raw)
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
        },
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
    parser.add_argument("--simion-executable", required=True, type=Path)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    document = derive_local_pa_family_contract(
        arguments.contract, arguments.region, arguments.scale_factor,
        arguments.local_gem, arguments.global_family_directory,
        arguments.simion_executable, arguments.simion_release,
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
