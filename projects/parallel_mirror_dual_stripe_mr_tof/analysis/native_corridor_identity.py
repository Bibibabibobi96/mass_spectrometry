"""Derive the frozen identity of the one active MR-TOF PA family.

The native corridor is the only adjustable analyser field in the current
MR-TOF workflow.  This module intentionally has no generic component-cache
CLI and no local/patch-family branches: publication and consumption belong to
the common transaction owner.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_geometry import (
    build_native_corridor_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_plan import (
    derive_native_corridor_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def native_corridor_family_filenames() -> tuple[str, ...]:
    """Return the raw, controller, and eight Fast Adjust response names."""

    prefix = "mrtof_analyzer_corridor"
    return (f"{prefix}.pa#", f"{prefix}.pa0", *(f"{prefix}.pa{identifier}" for identifier in range(1, 9)))


def _corridor_response_identity(response_recipe_path: Path, coarse_raw_path: Path) -> dict[str, Any]:
    """Return recipe identities without reading published PA payloads."""

    try:
        document = json.loads(response_recipe_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError("corridor response recipe is not valid JSON") from exc
    recipes = document.get("response_recipes") if isinstance(document, dict) else None
    if not isinstance(recipes, list) or len(recipes) != 8:
        raise CandidateContractError("corridor response recipe must contain eight response_recipes")
    coarse_generation = document.get("coarse_raw_generation_identity")

    def trusted_generation(value: object, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CandidateContractError(f"corridor {label} generation identity is invalid")
        cache_key = str(value.get("cache_key", ""))
        generation = str(value.get("generation_sha256", ""))
        if len(cache_key) != 64 or len(generation) != 64 or any(
            character not in "0123456789abcdefABCDEF" for character in cache_key + generation
        ):
            raise CandidateContractError(f"corridor {label} generation identity is not a SHA-256 pair")
        return {"cache_key": cache_key.upper(), "generation_sha256": generation.upper()}

    if document.get("schema_version") != 2 or not isinstance(coarse_generation, dict):
        raise CandidateContractError(
            "corridor response recipe must carry one verified coarse generation identity"
        )
    coarse_record = coarse_generation.get("member")
    if not isinstance(coarse_record, dict):
        coarse_record = document.get("coarse_raw_member")
    if not isinstance(coarse_record, dict):
        raise CandidateContractError("corridor recipe has no trusted coarse raw member record")
    coarse_bytes = coarse_record.get("bytes")
    coarse_sha = str(coarse_record.get("sha256", ""))
    if not isinstance(coarse_bytes, int) or coarse_bytes < 0 or len(coarse_sha) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in coarse_sha
    ):
        raise CandidateContractError("corridor coarse raw member identity is invalid")
    normalized: list[dict[str, Any]] = []
    for expected_id, item in enumerate(sorted(recipes, key=lambda value: int(value.get("local_id", -1))), 1):
        if not isinstance(item, dict) or int(item.get("local_id", -1)) != expected_id:
            raise CandidateContractError("corridor response recipes must cover local IDs 1..8")
        names = item.get("scratch_basis_names")
        physical_ids = item.get("physical_ids")
        expected_names = [f"mrtof_analyzer.pa{value}" for value in physical_ids or []]
        if (
            not isinstance(names, list)
            or not names
            or not isinstance(physical_ids, list)
            or names != expected_names
        ):
            raise CandidateContractError(f"corridor response recipe {expected_id} has invalid basis inventory")
        normalized.append(
            {
                "local_id": expected_id,
                "physical_ids": [int(value) for value in physical_ids],
                "scratch_basis_names": names,
                "output_filename": str(item.get("output_filename", "")),
            }
        )
    if not coarse_raw_path.is_file() or coarse_raw_path.name != "mrtof_analyzer.pa#":
        raise CandidateContractError("corridor coarse raw member path is invalid")
    if coarse_raw_path.stat().st_size != coarse_bytes:
        raise CandidateContractError("corridor coarse raw member size differs")
    return {
        "recipe_sha256": file_sha256(response_recipe_path),
        "recipe_size_bytes": response_recipe_path.stat().st_size,
        "response_count": len(normalized), "responses": normalized,
        "coarse_raw_generation": {**trusted_generation(coarse_generation, "coarse raw"),
                                   "member": {"sha256": coarse_sha.upper(), "bytes": coarse_bytes}},
    }


def build_native_corridor_identity(
    contract_path: Path, gem_path: Path, simion_executable: Path, simion_release: str,
    response_recipe_path: Path, coarse_raw_path: Path,
) -> dict[str, Any]:
    """Build the native corridor cache identity from its frozen inputs."""

    if not isinstance(simion_release, str) or not simion_release.strip():
        raise CandidateContractError("SIMION release label is required for PA cache identity")
    if not gem_path.is_file() or not simion_executable.is_file() or not response_recipe_path.is_file():
        raise CandidateContractError("native corridor identity requires existing GEM, recipe, and SIMION executable files")
    plan = derive_native_corridor_plan(contract_path)
    response_identity = _corridor_response_identity(
        response_recipe_path, coarse_raw_path
    )
    grouped = {
        local_id: sorted(
            int(physical_id)
            for physical_id, mapped_local_id in plan[
                "physical_to_local_electrode_id"
            ].items()
            if int(mapped_local_id) == local_id
        )
        for local_id in range(1, 9)
    }
    if [item["physical_ids"] for item in response_identity["responses"]] != [
        grouped[local_id] for local_id in range(1, 9)
    ]:
        raise CandidateContractError(
            "corridor response recipe physical groups differ from the corridor plan"
        )
    canonical_gem = build_native_corridor_gem(contract_path).encode("utf-8")
    if gem_path.read_bytes() != canonical_gem:
        raise CandidateContractError("native corridor GEM differs from the canonical contract-derived GEM")
    project = Path(__file__).resolve().parents[1]
    repository = project.parents[1]
    simion_directory = project / "simion"
    common_simion = repository / "common" / "simion"
    return {
        "geometry": {"component_role": "mrtof_analyzer_corridor_pa_family",
                     "representation": "contract_derived_component_gem_utf8_lf_v1",
                     "canonical_component_gem_sha256": hashlib.sha256(canonical_gem).hexdigest().upper(),
                     "corridor_plan": {key: plan[key] for key in ("box_project_mm", "mesh_mm_per_gu", "grid_shape")}},
        "gem": {"sha256": file_sha256(gem_path)},
        "basis_namespace": {"family_role": "mrtof_analyzer_corridor_pa_family",
                            "stable_local_ids": list(range(1, 9)),
                            "physical_to_local_electrode_id": plan["physical_to_local_electrode_id"],
                            "fixed_zero_electrode_ids": plan["fixed_zero_electrode_ids"],
                            "native_fast_adjust_reference_voltage_v": 10000.0},
        "mesh": {"mm_per_gu": [float(value) for value in plan["mesh_mm_per_gu"]]},
        "grid_phase": {"origin_mm": list(plan["box_project_mm"][:3]),
                       "pa_span_mm": [plan["box_project_mm"][index + 3] - plan["box_project_mm"][index] for index in range(3)],
                       "grid_shape": plan["grid_shape"]},
        "surface": str(plan["surface_mode"]),
        "simion_identity": {"release": simion_release, "executable_sha256": file_sha256(simion_executable)},
        "refine_policy": {"mode": "installed_default", "convergence_override": None,
                          "solutions": "pa0_and_each_declared_basis", "native_corridor_direct_response": True,
                          "native_response_output_basis_voltage_v": 10000.0,
                          "cache_recovery_policy": "none_reconstructible",
                          "response_recipe_identity": response_identity},
        "builder_identity": {"identity_schema": "mrtof_analyzer_corridor_identity_v1",
                             "verification_order": "fast_adjust_before_final_inventory_and_seal_v1",
                             "native_corridor_geometry_generator_sha256": file_sha256(project / "analysis" / "native_corridor_geometry.py"),
                             "native_fast_adjust_assembler_sha256": file_sha256(common_simion / "assemble_native_fast_adjust_family.lua"),
                             "physical_basis_builder_sha256": file_sha256(simion_directory / "build_component_basis.lua"),
                             "id_remapper_sha256": file_sha256(common_simion / "remap_pa_electrode_ids.lua"),
                             "dirichlet_builder_sha256": file_sha256(common_simion / "build_dirichlet_patch_basis.lua")},
    }
