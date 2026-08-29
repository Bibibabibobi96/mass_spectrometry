"""Materialize an independent spatial/energy distribution for an ion source.

This represents ions *inside the ion-source volume*, not a beam already
transported through a multipole.  Position and velocity are independently
sampled: in particular there is deliberately no prescribed z--vz relation.
All rows are one source snapshot and therefore share ``snapshot_time_s``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C

COLUMNS = (
    "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s",
    "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
)
ROLE = "continuous_axial_volume_ion_beam_source"
METHOD = "independent_spatial_velocity_ion_source_snapshot_v1"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _number(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be numeric") from error
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} must be finite" + (" and positive" if positive else ""))
    return result


def validate(spec: dict[str, Any]) -> None:
    if spec.get("role") != ROLE or spec.get("method") != METHOD:
        raise ValueError("continuous axial-volume source role/method is invalid")
    if spec.get("source_region_model") != "ion_source_volume_cylinder_v1":
        raise ValueError("only the ion-source cylinder volume is supported")
    if spec.get("source_frame_id") != "multipole_cartesian_z_axis_v1":
        raise ValueError("ion-source volume frame must be the canonical multipole frame")
    count = spec.get("particle_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("particle_count must be a positive integer")
    if isinstance(spec.get("seed"), bool) or not isinstance(spec.get("seed"), int):
        raise ValueError("seed must be an integer")
    geometry = spec.get("geometry_mm")
    velocity = spec.get("velocity_distribution")
    ion = spec.get("ion")
    if not all(isinstance(value, dict) for value in (geometry, velocity, ion)):
        raise ValueError("geometry_mm, velocity_distribution, and ion are required objects")
    _number(geometry.get("center_x_mm"), "geometry_mm.center_x_mm")
    _number(geometry.get("center_y_mm"), "geometry_mm.center_y_mm")
    _number(geometry.get("radius_mm"), "geometry_mm.radius_mm", positive=True)
    _number(geometry.get("axial_length_mm"), "geometry_mm.axial_length_mm", positive=True)
    _number(geometry.get("center_z_mm"), "geometry_mm.center_z_mm")
    _number(velocity.get("mean_vz_m_s"), "velocity_distribution.mean_vz_m_s", positive=True)
    _number(spec.get("snapshot_time_s"), "snapshot_time_s")
    for axis in "xyz":
        _number(velocity.get(f"mean_v{axis}_m_s"), f"velocity_distribution.mean_v{axis}_m_s")
        _number(velocity.get(f"sigma_v{axis}_m_s"), f"velocity_distribution.sigma_v{axis}_m_s")
        if float(velocity[f"sigma_v{axis}_m_s"]) < 0:
            raise ValueError(f"velocity_distribution.sigma_v{axis}_m_s must be nonnegative")
    _number(velocity.get("minimum_vz_m_s"), "velocity_distribution.minimum_vz_m_s", positive=True)
    if float(velocity["minimum_vz_m_s"]) >= float(velocity["mean_vz_m_s"]):
        raise ValueError("minimum_vz_m_s must be below mean_vz_m_s")
    _number(ion.get("mass_amu"), "ion.mass_amu", positive=True)
    charge = ion.get("charge_state")
    if isinstance(charge, bool) or not isinstance(charge, int) or charge == 0:
        raise ValueError("ion.charge_state must be a nonzero integer")


def _truncated_normal(rng: random.Random, mean: float, sigma: float, minimum: float) -> float:
    if sigma == 0:
        if mean < minimum:
            raise ValueError("mean axial velocity is below the configured minimum")
        return mean
    for _ in range(10_000):
        sample = rng.gauss(mean, sigma)
        if sample >= minimum:
            return sample
    raise RuntimeError("axial Gaussian truncation did not converge")


def rows(spec: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    validate(spec)
    count = int(spec["particle_count"])
    rng = random.Random(int(spec["seed"]))
    geometry = spec["geometry_mm"]
    distribution = spec["velocity_distribution"]
    ion = spec["ion"]
    radius = float(geometry["radius_mm"])
    length = float(geometry["axial_length_mm"])
    center_z = float(geometry["center_z_mm"])
    mean_vz = float(distribution["mean_vz_m_s"])
    sigma_vx = float(distribution["sigma_vx_m_s"])
    sigma_vy = float(distribution["sigma_vy_m_s"])
    sigma_vz = float(distribution["sigma_vz_m_s"])
    min_vz = float(distribution["minimum_vz_m_s"])
    reference_time = _number(spec["snapshot_time_s"], "snapshot_time_s")
    center_x = float(geometry["center_x_mm"])
    center_y = float(geometry["center_y_mm"])
    mean_vx = float(distribution["mean_vx_m_s"])
    mean_vy = float(distribution["mean_vy_m_s"])
    materialized: list[dict[str, str]] = []
    energies: list[float] = []
    for particle_id in range(1, count + 1):
        radial = radius * math.sqrt(rng.random())
        azimuth = 2.0 * math.pi * rng.random()
        z = center_z + length * (rng.random() - 0.5)
        vx = rng.gauss(mean_vx, sigma_vx)
        vy = rng.gauss(mean_vy, sigma_vy)
        vz = _truncated_normal(rng, mean_vz, sigma_vz, min_vz)
        energy = 0.5 * float(ion["mass_amu"]) * AMU_KG * (vx * vx + vy * vy + vz * vz) / ELEMENTARY_CHARGE_C
        energies.append(energy)
        materialized.append({
            "particle_id": str(particle_id), "birth_time_s": format(reference_time, ".17g"),
            "x_mm": format(center_x + radial * math.cos(azimuth), ".17g"),
            "y_mm": format(center_y + radial * math.sin(azimuth), ".17g"), "z_mm": format(z, ".17g"),
            "vx_m_s": format(vx, ".17g"), "vy_m_s": format(vy, ".17g"),
            "vz_m_s": format(vz, ".17g"), "mass_amu": format(float(ion["mass_amu"]), ".17g"),
            "charge_state": str(int(ion["charge_state"])),
        })
    receipt = {
        "schema_version": 1, "role": ROLE, "method": METHOD,
        "source_region_model": spec["source_region_model"], "particle_count": count,
        "source_frame_id": spec["source_frame_id"],
        "seed": int(spec["seed"]), "geometry_mm": geometry,
        "velocity_distribution": {**distribution, "components": "independent_gaussian_with_positive_vz_truncation"},
        "snapshot_time_s": reference_time,
        "primary_table_time_semantics": "all_rows_are_states_at_snapshot_time_s",
        "phase_space_assumption": "spatial_density_and_velocity_distribution_are_independent; no_z_vz_correlation_prescribed",
        "kinetic_energy_eV": {"mean": sum(energies) / len(energies), "minimum": min(energies), "maximum": max(energies)},
        "integration_precondition": "ion_source_volume_model; downstream_fields_have_not_yet_acted",
    }
    return materialized, receipt


def materialize(spec_path: Path, output_path: Path, receipt_path: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    if not isinstance(spec, dict):
        raise ValueError("source specification must be an object")
    materialized, receipt = rows(spec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader(); writer.writerows(materialized)
    receipt["particle_source"] = {
        "path": output_path.name,
        "sha256": _file_sha256(output_path),
        "particle_count": int(spec["particle_count"]),
        "sampling_mode": "continuous_injection_full_population",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    receipt = materialize(args.spec, args.output, args.receipt)
    print(f"CONTINUOUS_AXIAL_VOLUME_SOURCE=PASS PARTICLES={receipt['particle_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
