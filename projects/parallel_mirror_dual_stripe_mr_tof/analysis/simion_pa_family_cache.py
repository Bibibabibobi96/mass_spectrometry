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
    materialize_pa_family_cache,
    probe_pa_family_cache,
    publish_pa_family_cache,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import (
    build_accelerator_gem,
    build_analyzer_gem,
    resolve_split_iob_origins,
)


PAComponent = Literal["analyzer", "accelerator"]
_COMPONENT_IDS: dict[PAComponent, tuple[int, ...]] = {
    "analyzer": tuple(range(1, 21)),
    "accelerator": tuple(range(1, 10)),
}


def pa_family_filenames(component: PAComponent) -> tuple[str, ...]:
    """Return the complete run-local PA family required by one MR component."""
    ids = _COMPONENT_IDS[component]
    prefix = f"mrtof_{component}"
    return (f"{prefix}.pa#", f"{prefix}.pa0", *(f"{prefix}.pa{identifier}" for identifier in ids))


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
    mesh = contract["simion"]["component_mesh_mm_per_gu"].get(component)
    if not isinstance(mesh, list) or len(mesh) != 3 or any(float(value) <= 0.0 for value in mesh):
        raise CandidateContractError(f"simion.component_mesh_mm_per_gu.{component} must be three positive values")
    origins = resolve_split_iob_origins(contract_path)
    generator = build_analyzer_gem if component == "analyzer" else build_accelerator_gem
    canonical_gem = generator(contract_path).encode("utf-8")
    if gem_path.read_bytes() != canonical_gem:
        raise CandidateContractError("component GEM differs from the canonical contract-derived GEM")
    gem_sha256 = hashlib.sha256(canonical_gem).hexdigest().upper()
    project = Path(__file__).resolve().parents[1]
    simion_directory = project / "simion"
    return {
        "geometry": {
            "component_role": f"mrtof_{component}_pa_family",
            "representation": "contract_derived_component_gem_utf8_lf_v1",
            "canonical_component_gem_sha256": gem_sha256,
        },
        "gem": {"sha256": file_sha256(gem_path)},
        "basis_namespace": {
            "family_role": f"mrtof_{component}_pa_family",
            "stable_local_ids": list(_COMPONENT_IDS[component]),
        },
        "mesh": {"mm_per_gu": [float(value) for value in mesh]},
        "grid_phase": {
            "origin_mm": list(origins[component]),
            "pa_span_mm": _component_span(contract, component),
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
        },
        "builder_identity": {
            "build_component_pa_lua_sha256": file_sha256(simion_directory / "build_component_pa.lua"),
            "build_component_basis_lua_sha256": file_sha256(simion_directory / "build_component_basis.lua"),
            # The adapter itself enforces the source-GEM/PA-family binding
            # below.  Include that enforcement in the numerical cache key so
            # a generation published by an older, weaker adapter cannot be
            # silently reused.
            "pa_family_cache_adapter_sha256": file_sha256(Path(__file__)),
        },
    }


def probe_component_pa_cache(
    cache_root: Path, contract_path: Path, component: PAComponent, gem_path: Path,
    simion_executable: Path, simion_release: str,
) -> tuple[dict[str, Any], CacheProbe]:
    """Return the frozen component identity and its fail-closed cache disposition."""
    identity = build_pa_family_identity(contract_path, component, gem_path, simion_executable, simion_release)
    return identity, probe_pa_family_cache(cache_root, identity, expected_filenames=pa_family_filenames(component))


def publish_component_pa_cache(
    cache_root: Path, contract_path: Path, component: PAComponent, gem_path: Path, source_directory: Path,
    simion_executable: Path, simion_release: str,
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
    identity = build_pa_family_identity(contract_path, component, gem_path, simion_executable, simion_release)
    publication = publish_pa_family_cache(cache_root, identity, source_directory, pa_family_filenames(component))
    return {"identity": identity, "disposition": publication.disposition.value,
            "cache_key": publication.cache_key, "generation_sha256": publication.generation_sha256,
            "generation_directory": str(publication.generation_directory)}


def materialize_component_pa_cache(
    cache_root: Path, contract_path: Path, component: PAComponent, gem_path: Path, destination_directory: Path,
    simion_executable: Path, simion_release: str,
) -> dict[str, Any]:
    """Materialize a hit into a run SIMION directory, preserving frozen sidecars."""
    identity, probe = probe_component_pa_cache(
        cache_root, contract_path, component, gem_path, simion_executable, simion_release,
    )
    if probe.disposition is not CacheDisposition.HIT or probe.generation_directory is None:
        raise PAFamilyCacheError(f"cannot materialize {component} PA family from cache: {probe.disposition.value}: {probe.detail}")
    result: MaterializedFamily = materialize_pa_family_cache(
        probe.generation_directory, destination_directory, expected_filenames=pa_family_filenames(component),
    )
    return {"identity": identity, "disposition": "materialized", "cache_key": probe.cache_key,
            "generation_directory": str(probe.generation_directory), "destination_directory": str(result.destination_directory),
            "files": list(result.files)}


def main() -> int:
    """Run one explicit cache operation; a miss deliberately never invokes SIMION."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("probe", "publish", "materialize"), required=True)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--component", choices=("analyzer", "accelerator"), required=True)
    parser.add_argument("--gem", required=True, type=Path)
    parser.add_argument("--simion-executable", required=True, type=Path)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--run-simion-directory", required=True, type=Path)
    arguments = parser.parse_args()
    component: PAComponent = arguments.component
    if arguments.action == "probe":
        identity, probe = probe_component_pa_cache(
            arguments.cache_root, arguments.contract, component, arguments.gem,
            arguments.simion_executable, arguments.simion_release,
        )
        document: dict[str, Any] = {"identity": identity, "disposition": probe.disposition.value,
                                    "cache_key": probe.cache_key, "detail": probe.detail}
    elif arguments.action == "publish":
        document = publish_component_pa_cache(
            arguments.cache_root, arguments.contract, component, arguments.gem, arguments.run_simion_directory,
            arguments.simion_executable, arguments.simion_release,
        )
    else:
        document = materialize_component_pa_cache(
            arguments.cache_root, arguments.contract, component, arguments.gem, arguments.run_simion_directory,
            arguments.simion_executable, arguments.simion_release,
        )
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
