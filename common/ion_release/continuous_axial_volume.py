"""Deterministic materialization of a continuous axial cylinder source.

This module owns the legacy continuous-front-end source contract so every
consumer reaches it through :mod:`common.ion_release`.  Its field names and
random-draw order are deliberately retained: active source specifications and
their deterministic CSV sequences therefore remain compatible.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C


COLUMNS = (
    "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "vx_m_s",
    "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
)
ROLE = "continuous_axial_volume_ion_beam_source"
METHOD = "independent_spatial_velocity_ion_source_snapshot_v1"
CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY = (
    "ion_source_volume_cylinder_v1", METHOD,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


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


def validate_continuous_axial_volume_spec(spec: Mapping[str, Any]) -> None:
    """Validate the complete, versioned continuous-source request."""
    if not isinstance(spec, dict):
        raise ValueError("continuous axial-volume source specification must be an object")
    if spec.get("role") != ROLE or spec.get("method") != METHOD:
        raise ValueError("continuous axial-volume source role/method is invalid")
    if spec.get("source_region_model") != CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY[0]:
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


def generate_continuous_axial_volume_states(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate solver-neutral states in the historical deterministic order."""
    validate_continuous_axial_volume_spec(spec)
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
    birth_time = _number(spec["snapshot_time_s"], "snapshot_time_s")
    center_x = float(geometry["center_x_mm"])
    center_y = float(geometry["center_y_mm"])
    mean_vx = float(distribution["mean_vx_m_s"])
    mean_vy = float(distribution["mean_vy_m_s"])
    states: list[dict[str, Any]] = []
    for particle_id in range(1, count + 1):
        radial = radius * math.sqrt(rng.random())
        azimuth = 2.0 * math.pi * rng.random()
        z = center_z + length * (rng.random() - 0.5)
        vx = rng.gauss(mean_vx, sigma_vx)
        vy = rng.gauss(mean_vy, sigma_vy)
        vz = _truncated_normal(rng, mean_vz, sigma_vz, min_vz)
        states.append({
            "particle_id": particle_id, "birth_time_s": birth_time,
            "x_mm": center_x + radial * math.cos(azimuth),
            "y_mm": center_y + radial * math.sin(azimuth), "z_mm": z,
            "vx_m_s": vx, "vy_m_s": vy, "vz_m_s": vz,
            "mass_amu": float(ion["mass_amu"]),
            "charge_state": int(ion["charge_state"]),
        })
    return states


def _serialized_rows(states: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{
        "particle_id": str(int(state["particle_id"])),
        "birth_time_s": format(float(state["birth_time_s"]), ".17g"),
        **{name: format(float(state[name]), ".17g") for name in COLUMNS[2:-1]},
        "charge_state": str(int(state["charge_state"])),
    } for state in states]


def _state_identity(states: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "ordered_particle_ids_sha256": _sha256_text(
            _canonical_json([int(state["particle_id"]) for state in states])
        ),
        "canonical_states_sha256": _sha256_text(_canonical_json(states)),
    }


def rows(spec: Mapping[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Return canonical CSV rows and the historical receipt payload."""
    states = generate_continuous_axial_volume_states(spec)
    materialized = _serialized_rows(states)
    energies = [
        0.5 * float(state["mass_amu"]) * AMU_KG * sum(
            float(state[f"v{axis}_m_s"]) ** 2 for axis in "xyz"
        ) / ELEMENTARY_CHARGE_C
        for state in states
    ]
    receipt = {
        "schema_version": 1, "role": ROLE, "method": METHOD,
        "source_region_model": spec["source_region_model"],
        "particle_count": int(spec["particle_count"]),
        "source_frame_id": spec["source_frame_id"], "seed": int(spec["seed"]),
        "geometry_mm": spec["geometry_mm"],
        "velocity_distribution": {
            **spec["velocity_distribution"],
            "components": "independent_gaussian_with_positive_vz_truncation",
        },
        "snapshot_time_s": float(spec["snapshot_time_s"]),
        "primary_table_time_semantics": "all_rows_are_states_at_snapshot_time_s",
        "phase_space_assumption": "spatial_density_and_velocity_distribution_are_independent; no_z_vz_correlation_prescribed",
        "kinetic_energy_eV": {
            "mean": sum(energies) / len(energies), "minimum": min(energies),
            "maximum": max(energies),
        },
        "integration_precondition": "ion_source_volume_model; downstream_fields_have_not_yet_acted",
    }
    return materialized, receipt


def materialize_continuous_axial_volume_release(
    spec: Mapping[str, Any], state_table_path: Path, receipt_path: Path,
    spec_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the canonical table and receipt for a registered release."""
    materialized, receipt = rows(spec)
    state_table_path.parent.mkdir(parents=True, exist_ok=True)
    with state_table_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialized)
    receipt["release_spec"] = dict(spec)
    receipt["release_spec_sha256"] = _sha256_text(_canonical_json(spec))
    receipt["state_identity"] = _state_identity(
        generate_continuous_axial_volume_states(spec)
    )
    receipt["status"] = "materialized"
    receipt["source_spec"] = dict(spec_record) if spec_record is not None else None
    receipt["particle_source"] = {
        "path": state_table_path.name, "sha256": file_sha256(state_table_path),
        "particle_count": int(spec["particle_count"]),
        "sampling_mode": "continuous_injection_full_population",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def materialize_continuous_axial_volume_release_from_file(
    spec_path: Path, state_table_path: Path, receipt_path: Path,
) -> dict[str, Any]:
    spec_path = spec_path.resolve(strict=True)
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release specification is unreadable") from error
    if not isinstance(spec, dict):
        raise ValueError("source specification must be an object")
    return materialize_continuous_axial_volume_release(
        spec, state_table_path, receipt_path,
        {"path": str(spec_path), "bytes": spec_path.stat().st_size, "sha256": file_sha256(spec_path)},
    )


def validate_materialized_continuous_axial_volume_release(receipt_path: Path) -> dict[str, Any]:
    """Validate receipt bindings and exact deterministic reconstruction."""
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("release receipt is unreadable") from error
    if not isinstance(receipt, dict) or receipt.get("status") != "materialized":
        raise ValueError("release receipt identity is invalid")
    spec = receipt.get("release_spec")
    if not isinstance(spec, dict):
        raise ValueError("release receipt lacks its release specification")
    validate_continuous_axial_volume_spec(spec)
    if receipt.get("release_spec_sha256") != _sha256_text(_canonical_json(spec)):
        raise ValueError("release specification identity changed")
    source_spec = receipt.get("source_spec")
    if source_spec is not None:
        if not isinstance(source_spec, dict) or not isinstance(source_spec.get("path"), str):
            raise ValueError("release receipt source-spec binding is incomplete")
        source_path = Path(source_spec["path"])
        if not source_path.is_file() or source_path.stat().st_size != source_spec.get("bytes") or file_sha256(source_path) != source_spec.get("sha256"):
            raise ValueError("release source specification identity changed")
    particle_source = receipt.get("particle_source")
    if not isinstance(particle_source, dict):
        raise ValueError("release receipt particle-source binding is incomplete")
    table_path = receipt_path.parent / str(particle_source.get("path", ""))
    if not table_path.is_file() or file_sha256(table_path) != particle_source.get("sha256"):
        raise ValueError("release state-table identity changed")
    with table_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("release state-table columns changed")
        actual = list(reader)
    states = generate_continuous_axial_volume_states(spec)
    expected = _serialized_rows(states)
    if actual != expected:
        raise ValueError("release state-table differs from deterministic specification")
    if receipt.get("state_identity") != _state_identity(states):
        raise ValueError("release state identity changed")
    return receipt


__all__ = [
    "COLUMNS", "CONTINUOUS_AXIAL_VOLUME_RELEASE_KEY", "METHOD", "ROLE",
    "generate_continuous_axial_volume_states",
    "materialize_continuous_axial_volume_release",
    "materialize_continuous_axial_volume_release_from_file", "rows",
    "validate_continuous_axial_volume_spec",
    "validate_materialized_continuous_axial_volume_release",
]
