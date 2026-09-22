"""Bind MR-TOF PA families to the device-neutral SIMION cache.

This module owns only MR component semantics: local basis namespaces, PA
filenames and the project-frame grid phase.  Cache publication, byte inventory
and atomic materialization remain in :mod:`common.simion.pa_family_cache`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import (
    CacheDisposition,
    CacheProbe,
    MaterializedFamily,
    PAFamilyCacheError,
    ensure_pa_family_cache,
    materialize_pa_family_cache,
    probe_pa_family_cache,
    publish_pa_family_cache,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import (
    build_analyzer_gem,
    resolve_static_iob_origins,
)


PAComponent = Literal["analyzer", "analyzer_corridor"]
_COMPONENT_IDS: dict[PAComponent, tuple[int, ...]] = {
    "analyzer": tuple(range(1, 21)),
    "analyzer_corridor": tuple(range(1, 9)),
}


def pa_family_filenames(component: PAComponent) -> tuple[str, ...]:
    """Return the complete run-local PA family required by one MR component."""
    ids = _COMPONENT_IDS[component]
    prefix = f"mrtof_{component}"
    return (f"{prefix}.pa#", f"{prefix}.pa0", *(f"{prefix}.pa{identifier}" for identifier in ids))



def _require_corridor_generation_inputs(
    response_recipe_path: Path | None,
    coarse_raw_path: Path | None,
) -> tuple[Path, Path]:
    """Resolve the two non-PA inputs that define a corridor response family."""
    if response_recipe_path is None or coarse_raw_path is None:
        raise CandidateContractError(
            "analyzer_corridor identity requires response_recipe_path and coarse_raw_path"
        )
    recipe = response_recipe_path.resolve()
    coarse = coarse_raw_path.resolve()
    if not recipe.is_file():
        raise CandidateContractError("corridor response recipe must be an existing file")
    return recipe, coarse


def _corridor_response_identity(response_recipe_path: Path, coarse_raw_path: Path) -> dict[str, Any]:
    """Return content identities without reading any published corridor PA."""
    try:
        document = json.loads(response_recipe_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError("corridor response recipe is not valid JSON") from exc
    recipes = document.get("response_recipes") if isinstance(document, dict) else None
    if not isinstance(recipes, list) or len(recipes) != 8:
        raise CandidateContractError("corridor response recipe must contain eight response_recipes")
    source_generation = document.get("source_generation_identity")
    coarse_generation = document.get("coarse_raw_generation_identity")
    if not isinstance(source_generation, dict) or not isinstance(coarse_generation, dict):
        raise CandidateContractError(
            "corridor response recipe must carry verified source/coarse generation identities"
        )

    def trusted_generation(value: object, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CandidateContractError(f"corridor {label} generation identity is invalid")
        cache_key = str(value.get("cache_key", ""))
        generation = str(value.get("generation_sha256", ""))
        if len(cache_key) != 64 or len(generation) != 64:
            raise CandidateContractError(f"corridor {label} generation identity is not a SHA-256 pair")
        if any(character not in "0123456789abcdefABCDEF" for character in cache_key + generation):
            raise CandidateContractError(f"corridor {label} generation identity is not hexadecimal")
        return {"cache_key": cache_key.upper(), "generation_sha256": generation.upper()}

    coarse_record = coarse_generation.get("member")
    if not isinstance(coarse_record, dict):
        # The member record is nested in the recipe so the generation pointer
        # remains usable even when the prepared path is not materialized.
        coarse_record = document.get("coarse_raw_member")
    if not isinstance(coarse_record, dict):
        raise CandidateContractError("corridor recipe has no trusted coarse raw member record")
    source_generation = trusted_generation(source_generation, "source")
    coarse_generation = trusted_generation(coarse_generation, "coarse raw")
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
        paths = item.get("source_basis_paths")
        physical_ids = item.get("physical_ids")
        if not isinstance(paths, list) or not paths or not isinstance(physical_ids, list) or len(paths) != len(physical_ids):
            raise CandidateContractError(f"corridor response recipe {expected_id} has invalid basis inventory")
        source_records = item.get("source_basis_identities")
        if not isinstance(source_records, list) or len(source_records) != len(paths):
            raise CandidateContractError(
                f"corridor response recipe {expected_id} lacks trusted basis identities"
            )
        sources = []
        for record in source_records:
            if not isinstance(record, dict):
                raise CandidateContractError(f"corridor response recipe {expected_id} basis identity is invalid")
            size = record.get("bytes")
            sha = str(record.get("sha256", ""))
            if not isinstance(size, int) or size < 0 or len(sha) != 64 or any(
                character not in "0123456789abcdefABCDEF" for character in sha
            ):
                raise CandidateContractError(f"corridor response recipe {expected_id} basis identity is invalid")
            sources.append({"sha256": sha.upper(), "bytes": size})
        normalized.append({
            "local_id": expected_id,
            "physical_ids": [int(value) for value in physical_ids],
            "source_basis": sources,
            "output_filename": str(item.get("output_filename", "")),
        })
    return {
        "recipe_sha256": file_sha256(response_recipe_path),
        "recipe_size_bytes": response_recipe_path.stat().st_size,
        "source_generation": source_generation,
        "response_count": len(normalized),
        "responses": normalized,
        "coarse_raw_generation": {
            **coarse_generation,
            "member": {"sha256": coarse_sha.upper(), "bytes": coarse_bytes},
        },
    }


def _component_span(contract: dict[str, Any], component: PAComponent) -> list[float]:
    value = contract["simion"].get(f"{component}_pa_span_mm")
    if not isinstance(value, list) or len(value) != 3:
        raise CandidateContractError(f"simion.{component}_pa_span_mm must have three values")
    return [float(item) for item in value]


def build_pa_family_identity(
    contract_path: Path,
    component: PAComponent,
    gem_path: Path,
    simion_executable: Path,
    simion_release: str,
    response_recipe_path: Path | None = None,
    coarse_raw_path: Path | None = None,
) -> dict[str, Any]:
    """Derive every content identity needed to reuse one independently refined PA.

    ``simion_release`` is passed explicitly because a text label alone is not
    enough; it is bound together with the executable bytes.  The source GEM
    must exactly match the component generated from the contract. Whole-machine
    provenance belongs to the run receipt, not this independent PA's cache key.
    """
    if component not in _COMPONENT_IDS:
        raise CandidateContractError(f"unsupported cached PA component: {component}")
    if not isinstance(simion_release, str) or not simion_release.strip():
        raise CandidateContractError("SIMION release label is required for PA cache identity")
    if not gem_path.is_file() or not simion_executable.is_file():
        raise CandidateContractError("PA cache identity requires existing GEM and SIMION executable files")
    contract = load_contract(contract_path)
    if component == "analyzer_corridor":
        # Lazy imports avoid the existing plan -> family-filename dependency
        # becoming a module-import cycle for accelerator/analyser callers.
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_plan import derive_native_corridor_plan
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_geometry import build_native_corridor_gem
        corridor_plan = derive_native_corridor_plan(contract_path)
    else:
        corridor_plan = None
    if corridor_plan is not None:
        mesh = corridor_plan["mesh_mm_per_gu"]
        origin = corridor_plan["box_project_mm"][:3]
        span = [corridor_plan["box_project_mm"][index + 3] - corridor_plan["box_project_mm"][index] for index in range(3)]
        generator = build_native_corridor_gem
        corridor_inputs = _require_corridor_generation_inputs(response_recipe_path, coarse_raw_path)
        response_identity = _corridor_response_identity(*corridor_inputs)
    else:
        mesh = contract["simion"]["component_mesh_mm_per_gu"].get(component)
        if not isinstance(mesh, list) or len(mesh) != 3 or any(float(value) <= 0.0 for value in mesh):
            raise CandidateContractError(f"simion.component_mesh_mm_per_gu.{component} must be three positive values")
        origins = resolve_static_iob_origins(contract_path)
        origin = origins[component]
        span = _component_span(contract, component)
        generator = build_analyzer_gem
        response_identity = None
    canonical_gem = generator(contract_path).encode("utf-8")
    if gem_path.read_bytes() != canonical_gem:
        raise CandidateContractError("component GEM differs from the canonical contract-derived GEM")
    gem_sha256 = hashlib.sha256(canonical_gem).hexdigest().upper()
    project = Path(__file__).resolve().parents[1]
    simion_directory = project / "simion"
    repository = project.parents[1]
    common_simion = repository / "common" / "simion"
    if corridor_plan is not None:
        # Keep this identity independent of adapter/CLI refactors and IOB
        # priority changes.  Only code that can change the corridor PA bytes
        # is bound here.
        builder_identity = {
            "identity_schema": "mrtof_analyzer_corridor_identity_v1",
            "verification_order": "fast_adjust_before_final_inventory_and_seal_v1",
            "native_corridor_geometry_generator_sha256": file_sha256(
                Path(__file__).with_name("native_corridor_geometry.py")
            ),
            "native_corridor_controller_sha256": file_sha256(
                simion_directory / "create_native_corridor_controller.lua"
            ),
            "id_remapper_sha256": file_sha256(common_simion / "remap_pa_electrode_ids.lua"),
            "dirichlet_builder_sha256": file_sha256(common_simion / "build_dirichlet_patch_basis.lua"),
        }
    else:
        builder_identity = {
            "build_component_pa_lua_sha256": file_sha256(simion_directory / "build_component_pa.lua"),
            "build_component_basis_lua_sha256": file_sha256(simion_directory / "build_component_basis.lua"),
            "pa_family_cache_adapter_sha256": file_sha256(Path(__file__)),
        }
    return {
        "geometry": {
            "component_role": f"mrtof_{component}_pa_family",
            "representation": "contract_derived_component_gem_utf8_lf_v1",
            "canonical_component_gem_sha256": gem_sha256,
            **(
                {
                    "corridor_plan": {
                        "box_project_mm": corridor_plan["box_project_mm"],
                        "mesh_mm_per_gu": corridor_plan["mesh_mm_per_gu"],
                        "grid_shape": corridor_plan["grid_shape"],
                    }
                }
                if corridor_plan is not None else {}
            ),
        },
        "gem": {"sha256": file_sha256(gem_path)},
        "basis_namespace": {
            "family_role": f"mrtof_{component}_pa_family",
            "stable_local_ids": list(_COMPONENT_IDS[component]),
            **(
                {
                    "physical_to_local_electrode_id": corridor_plan["physical_to_local_electrode_id"],
                    "fixed_zero_electrode_ids": corridor_plan["fixed_zero_electrode_ids"],
                }
                if corridor_plan is not None else {}
            ),
            **(
                {"native_fast_adjust_reference_voltage_v": 10000.0}
                if corridor_plan is not None else {}
            ),
        },
        "mesh": {"mm_per_gu": [float(value) for value in mesh]},
        "grid_phase": {
            "origin_mm": list(origin),
            "pa_span_mm": span,
            **(
                {"grid_shape": corridor_plan["grid_shape"]}
                if corridor_plan is not None else {}
            ),
        },
        "surface": "none",
        "simion_identity": {
            "release": simion_release,
            "executable_sha256": file_sha256(simion_executable),
        },
        "refine_policy": {
            "mode": "installed_default",
            "convergence_override": None,
            "solutions": "pa0_and_each_declared_basis",
            **(
                {
                    "native_corridor_direct_response": True,
                    "native_response_output_basis_voltage_v": 10000.0,
                    "cache_recovery_policy": "none_reconstructible",
                }
                if corridor_plan is not None else {}
            ),
            **(
                {"response_recipe_identity": response_identity}
                if corridor_plan is not None else {}
            ),
        },
        "builder_identity": builder_identity,
    }


def probe_component_pa_cache(
    cache_root: Path, contract_path: Path, component: PAComponent, gem_path: Path,
    simion_executable: Path, simion_release: str,
    response_recipe_path: Path | None = None, coarse_raw_path: Path | None = None,
) -> tuple[dict[str, Any], CacheProbe]:
    """Return the frozen component identity and its fail-closed cache disposition."""
    identity = build_pa_family_identity(
        contract_path, component, gem_path, simion_executable, simion_release,
        response_recipe_path, coarse_raw_path,
    )
    return identity, probe_pa_family_cache(
        cache_root, identity, expected_filenames=component_pa_cache_filenames(component)
    )


def ensure_component_pa_cache(
    cache_root: Path,
    contract_path: Path,
    component: PAComponent,
    gem_path: Path,
    simion_executable: Path,
    simion_release: str,
    response_recipe_path: Path | None = None, coarse_raw_path: Path | None = None,
) -> tuple[dict[str, Any], CacheProbe]:
    """Return a usable component cache state, repairing one v2 member."""

    identity = build_pa_family_identity(
        contract_path, component, gem_path, simion_executable, simion_release,
        response_recipe_path, coarse_raw_path,
    )
    return identity, ensure_pa_family_cache(
        cache_root,
        identity,
        expected_filenames=component_pa_cache_filenames(component),
    )


def publish_component_pa_cache(
    cache_root: Path, contract_path: Path, component: PAComponent, gem_path: Path, source_directory: Path,
    simion_executable: Path, simion_release: str,
    response_recipe_path: Path | None = None, coarse_raw_path: Path | None = None,
) -> dict[str, Any]:
    """Publish a completed local PA family after Refine and basis generation."""
    canonical_source_gem = source_directory / f"mrtof_{component}.gem"
    if not canonical_source_gem.is_file():
        raise PAFamilyCacheError(
            "PA-cache publication requires the exact canonical source GEM beside its PA family: "
            f"{canonical_source_gem}"
        )
    if file_sha256(canonical_source_gem) != file_sha256(gem_path):
        raise PAFamilyCacheError(
            "PA-cache publication source GEM differs from the requested component GEM"
        )
    identity = build_pa_family_identity(
        contract_path, component, gem_path, simion_executable, simion_release,
        response_recipe_path, coarse_raw_path,
    )
    publication = publish_pa_family_cache(
        cache_root, identity, source_directory, component_pa_cache_filenames(component)
    )
    return {"identity": identity, "disposition": publication.disposition.value,
            "cache_key": publication.cache_key, "generation_sha256": publication.generation_sha256,
            "generation_directory": str(publication.generation_directory)}


def materialize_component_pa_cache(
    cache_root: Path, contract_path: Path, component: PAComponent, gem_path: Path, destination_directory: Path,
    simion_executable: Path, simion_release: str,
    response_recipe_path: Path | None = None, coarse_raw_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize a hit into a run SIMION directory, preserving frozen sidecars."""
    identity, probe = probe_component_pa_cache(
        cache_root, contract_path, component, gem_path, simion_executable, simion_release,
        response_recipe_path, coarse_raw_path,
    )
    if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
        raise PAFamilyCacheError(f"cannot materialize {component} PA family from cache: {probe.disposition.value}: {probe.detail}")
    result: MaterializedFamily = materialize_pa_family_cache(
        probe.generation_directory, destination_directory,
        expected_filenames=component_pa_cache_filenames(component),
    )
    return {"identity": identity, "disposition": "materialized", "cache_key": probe.cache_key,
            "generation_directory": str(result.source_generation_directory),
            "predecessor_generation_directory": (
                str(result.predecessor_generation_directory)
                if result.predecessor_generation_directory else None
            ),
            "repair_receipt_path": (
                str(result.repair_receipt_path) if result.repair_receipt_path else None
            ),
            "destination_directory": str(result.destination_directory),
            "files": list(result.files)}


def main() -> int:
    """Run one explicit cache operation; a miss deliberately never invokes SIMION."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("probe", "ensure", "publish", "materialize"), required=True
    )
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--component", choices=("analyzer", "analyzer_corridor"), required=True)
    parser.add_argument("--gem", required=True, type=Path)
    parser.add_argument("--simion-executable", required=True, type=Path)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--run-simion-directory", required=True, type=Path)
    parser.add_argument("--response-recipe", type=Path)
    parser.add_argument("--coarse-raw", type=Path)
    arguments = parser.parse_args()
    component: PAComponent = arguments.component
    if arguments.action in {"probe", "ensure"}:
        operation = (
            probe_component_pa_cache
            if arguments.action == "probe"
            else ensure_component_pa_cache
        )
        identity, probe = operation(
            arguments.cache_root, arguments.contract, component, arguments.gem,
            arguments.simion_executable, arguments.simion_release,
            arguments.response_recipe, arguments.coarse_raw,
        )
        document: dict[str, Any] = {
            "identity": identity,
            "disposition": probe.disposition.value,
            "cache_key": probe.cache_key,
            "detail": probe.detail,
            "generation_directory": (
                str(probe.generation_directory)
                if probe.generation_directory is not None else None
            ),
        }
    elif arguments.action == "publish":
        document = publish_component_pa_cache(
            arguments.cache_root, arguments.contract, component, arguments.gem, arguments.run_simion_directory,
            arguments.simion_executable, arguments.simion_release,
            arguments.response_recipe, arguments.coarse_raw,
        )
    else:
        document = materialize_component_pa_cache(
            arguments.cache_root, arguments.contract, component, arguments.gem, arguments.run_simion_directory,
            arguments.simion_executable, arguments.simion_release,
            arguments.response_recipe, arguments.coarse_raw,
        )
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
