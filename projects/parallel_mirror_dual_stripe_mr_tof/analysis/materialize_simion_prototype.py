"""Retained source-identity and timeout helpers for the current MR-TOF trial.

The former prototype materialization CLI and first-prism-only producer are
retired; current trial and event-analysis consumers retain these helpers.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import derive_mirror_boundaries


def _finite_number(value: object, label: str) -> float:
    """Return one finite contract scalar or fail before a solver run."""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _particle_source_record(
    path: Path, particle_source: dict[str, Any], count_key: str,
    source_profile_id: str | None = None,
) -> dict[str, Any]:
    """Bind the sole standard-beam source to SIMION's one-based ion identities."""
    count = particle_source[count_key]
    if type(count) is not int or count <= 0:
        raise CandidateContractError("particle source count must be a positive integer")
    particle_ids = list(range(1, count + 1))
    identity = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    return {"filename": path.name, "sha256": file_sha256(path).lower(),
            "particle_count_contract_key": count_key, "particle_count": count,
            "source_profile_id": source_profile_id,
            "expected_particle_ids": particle_ids,
            "expected_particle_ids_sha256": hashlib.sha256(identity).hexdigest()}


def _full_path_timeout_us(contract: dict[str, Any], particle_source: dict[str, Any], target_k: float) -> float:
    """Derive a finite diagnostic bound from frozen axial geometry and species."""
    simion = contract["simion"]
    multiplier = _finite_number(
        simion.get("full_path_timeout_axial_path_multiplier"),
        "simion.full_path_timeout_axial_path_multiplier",
    )
    if multiplier <= 1.0:
        raise CandidateContractError("full-path timeout factor must retain more than one axial reference path")
    species = particle_source["species"]
    mass_th = _finite_number(species.get("mass_th"), "particle_source.species.mass_th")
    charge_e = abs(_finite_number(species.get("charge_e"), "particle_source.species.charge_e"))
    diagnostic = particle_source.get("mirror_internal_diagnostic")
    if not isinstance(diagnostic, dict):
        raise CandidateContractError("full-path timeout requires the mirror-internal diagnostic profile")
    energy_ev = _finite_number(
        diagnostic.get("axial_kinetic_energy_ev"),
        "particle_source.mirror_internal_diagnostic.axial_kinetic_energy_ev",
    )
    if mass_th <= 0.0 or charge_e <= 0.0 or energy_ev <= 0.0:
        raise CandidateContractError("full-path timeout requires positive species mass, charge, and energy")
    terminal = float(derive_mirror_boundaries(contract["mirror"])["terminal_electrode_plane_z_mm"])
    speed_mm_us = math.sqrt(2.0 * energy_ev * 1.602176634e-19 / (mass_th * 1.66053906660e-27)) * 1e-3
    return multiplier * target_k * (4.0 * terminal) / speed_mm_us
