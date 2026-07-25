"""Interface-readiness particle-source identities and energy policy."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from projects.rf_quadrupole_collision_cooling.analysis.paired_particle_source_bundle import (
    generate_bundle,
    validate_bundle,
)


CONTROL_POINT_ID = "official_100amu_2eV"
CANDIDATE_POINT_ID = "rf_to_oatof_100amu_5eV"
POINT_IDS = (CONTROL_POINT_ID, CANDIDATE_POINT_ID)
BUNDLE_ROLE = "rf_quadrupole_paired_particle_source_bundle"
BUNDLE_VERSION = "rf_interface_paired_latent_family.v2"

POINT_POLICY = {
    CONTROL_POINT_ID: {
        "mass_amu": 100.0,
        "charge_state": 1,
        "kinetic_energy_eV": {
            "distribution": "uniform",
            "min": 1.8,
            "max": 2.2,
        },
    },
    CANDIDATE_POINT_ID: {
        "mass_amu": 100.0,
        "charge_state": 1,
        "kinetic_energy_eV": {
            "distribution": "fixed",
            "value": 5.0,
        },
    },
}


def _same_number(actual: Any, expected: float) -> bool:
    try:
        value = float(actual)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value == expected


def load_interface_point_specs(source_family_path: Path) -> dict[str, dict[str, Any]]:
    family = json.loads(source_family_path.read_text(encoding="utf-8-sig"))
    points = family.get("operating_points")
    if not isinstance(points, dict) or not set(POINT_IDS).issubset(points):
        raise ValueError(
            "interface source family must contain both governed bundle points"
        )
    validated: dict[str, dict[str, Any]] = {}
    for point_id in POINT_IDS:
        point = points.get(point_id)
        policy = POINT_POLICY[point_id]
        if not isinstance(point, dict):
            raise ValueError(f"interface point specification is missing: {point_id}")
        if not _same_number(point.get("mass_amu"), policy["mass_amu"]):
            raise ValueError(f"interface point mass differs: {point_id}")
        if point.get("charge_state") != policy["charge_state"]:
            raise ValueError(f"interface point charge state differs: {point_id}")
        energy = point.get("kinetic_energy_eV")
        expected_energy = policy["kinetic_energy_eV"]
        if not isinstance(energy, dict) or energy.get("distribution") != expected_energy[
            "distribution"
        ]:
            raise ValueError(f"interface point energy distribution differs: {point_id}")
        for field, expected in expected_energy.items():
            if field == "distribution":
                continue
            if not _same_number(energy.get(field), float(expected)):
                raise ValueError(f"interface point energy policy differs: {point_id}")
        validated[point_id] = point
    return validated


def generate_interface_bundle(
    source_family_path: Path,
    distribution_path: Path,
    resolved_path: Path,
    output_dir: Path,
    *,
    seed: int | None = None,
) -> dict[str, Any]:
    point_specs = load_interface_point_specs(source_family_path)
    return generate_bundle(
        source_family_path,
        distribution_path,
        resolved_path,
        output_dir,
        point_ids=POINT_IDS,
        point_specs=point_specs,
        bundle_role=BUNDLE_ROLE,
        bundle_version=BUNDLE_VERSION,
        seed=seed,
    )


def validate_interface_bundle(
    metadata_path: Path,
    source_family_path: Path,
    distribution_path: Path,
    resolved_path: Path,
) -> dict[str, Any]:
    point_specs = load_interface_point_specs(source_family_path)
    return validate_bundle(
        metadata_path,
        source_family_path,
        distribution_path,
        resolved_path,
        point_ids=POINT_IDS,
        point_specs=point_specs,
        bundle_role=BUNDLE_ROLE,
        bundle_version=BUNDLE_VERSION,
    )
