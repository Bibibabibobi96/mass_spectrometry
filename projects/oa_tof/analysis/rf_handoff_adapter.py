"""Validate the RF-to-oaTOF particle identity and SIMION state adapter."""

from __future__ import annotations

import csv
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from common.contracts.component_particle_state import (
    csv_columns as component_particle_state_columns,
    validate_component_particle_state_csv,
)
from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C,
    kinetic_energy_ev,
)
from common.contracts.rigid_transform import FramedVector, RigidTransform
from projects.rf_quadrupole_collision_cooling.analysis.migrate_legacy_component_particle_state import (
    LEGACY_25_COLUMNS as LEGACY_PROJECTION_COLUMNS,
)


_ACCELERATOR_PA_TO_GLOBAL = RigidTransform(
    "oatof_accelerator_pa",
    "oatof_global",
    ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    (0.0, 0.0, 0.0),
)


def _read_exact_csv(path: Path, expected_columns: Sequence[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(expected_columns):
            raise ValueError(
                f"handoff particle-state columns differ: {reader.fieldnames}; "
                f"expected {list(expected_columns)}"
            )
        rows = list(reader)
    if not rows:
        raise ValueError("handoff particle-state CSV must contain at least one row")
    return rows


def load_handoff_particle_states(
    path: Path,
    *,
    legacy_projection: bool,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Load either public v1 state or the explicitly historical projection table.

    The legacy table is intentionally not padded or renamed into public v1. Its
    missing species, weight, and phase-reference bindings require an upstream
    migration, so this adapter only exposes it to modes already marked inactive.
    """
    if legacy_projection:
        rows = _read_exact_csv(path, LEGACY_PROJECTION_COLUMNS)
        return rows, {
            "format": "legacy_25_column_component_handoff",
            "schema_version": None,
            "validated_by": "oa_tof_explicit_legacy_projection_adapter",
            "rows": len(rows),
            "public_v1": False,
        }
    report = validate_component_particle_state_csv(path)
    rows = _read_exact_csv(path, component_particle_state_columns())
    return rows, {
        "format": "component_particle_state_csv_v1",
        "schema_version": report["schema_version"],
        "validated_by": "common.contracts.component_particle_state",
        "rows": report["rows"],
        "public_v1": True,
    }


def _finite_float(row: Mapping[str, str], field: str, source: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{source} requires numeric field {field}") from error
    if not math.isfinite(value):
        raise ValueError(f"{source} field {field} must be finite")
    return value


def _positive_int(row: Mapping[str, str], field: str, source: str) -> int:
    value = _finite_float(row, field, source)
    integer = int(value)
    if integer <= 0 or value != integer:
        raise ValueError(f"{source} field {field} must be a positive integer")
    return integer


def ordered_solver_identity_map(
    canonical_rows: Sequence[Mapping[str, str]],
    row_map_rows: Sequence[Mapping[str, str]],
) -> dict[int, int]:
    """Return solver-row to canonical-ID mapping after strict one-to-one checks."""
    if not canonical_rows or len(canonical_rows) != len(row_map_rows):
        raise ValueError("canonical and row-map particle counts differ or are empty")
    canonical_ids: list[int] = []
    solver_to_particle: dict[int, int] = {}
    mapped_particle_ids: set[int] = set()
    for expected_solver_row, (state, mapping) in enumerate(
        zip(canonical_rows, row_map_rows), start=1
    ):
        particle_id = _positive_int(state, "particle_id", "canonical state")
        if particle_id in canonical_ids:
            raise ValueError("canonical particle IDs must be unique")
        canonical_ids.append(particle_id)
        solver_row = _positive_int(mapping, "solver_row_index", "row map")
        mapped_particle_id = _positive_int(mapping, "particle_id", "row map")
        if solver_row != expected_solver_row:
            raise ValueError("row map must be ordered by contiguous solver_row_index")
        if solver_row in solver_to_particle or mapped_particle_id in mapped_particle_ids:
            raise ValueError("row map must preserve a one-to-one particle identity")
        if mapped_particle_id != particle_id:
            raise ValueError("row map does not preserve canonical particle identity")
        solver_to_particle[solver_row] = particle_id
        mapped_particle_ids.add(mapped_particle_id)
    return solver_to_particle


def decode_simion_accelerator_velocity(
    mass_amu: float,
    energy_ev: float,
    azimuth_deg: float,
    elevation_deg: float,
) -> tuple[float, float, float]:
    """Decode ION direction through the frozen oaTOF accelerator instance axes."""
    values = (mass_amu, energy_ev, azimuth_deg, elevation_deg)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("SIMION velocity adapter values must be finite")
    if mass_amu <= 0 or energy_ev < 0:
        raise ValueError("SIMION velocity adapter requires positive mass and nonnegative energy")
    speed = math.sqrt(
        2.0 * energy_ev * ELEMENTARY_CHARGE_C / (mass_amu * AMU_KG)
    )
    azimuth = math.radians(azimuth_deg)
    elevation = math.radians(elevation_deg)
    local_x = speed * math.cos(elevation) * math.cos(azimuth)
    local_y = speed * math.cos(elevation) * math.sin(azimuth)
    local_z = speed * math.sin(elevation)
    local_velocity = FramedVector(
        _ACCELERATOR_PA_TO_GLOBAL.from_frame_id,
        (local_x, local_y, local_z),
        "polar",
    )
    return _ACCELERATOR_PA_TO_GLOBAL.transform_vector(local_velocity).components


def encode_simion_accelerator_velocity(
    velocity_m_s: Sequence[float],
) -> tuple[float, float]:
    """Encode one oaTOF-global velocity as SIMION azimuth and elevation."""
    global_velocity = FramedVector(
        _ACCELERATOR_PA_TO_GLOBAL.to_frame_id,
        velocity_m_s,
        "polar",
    )
    local_x, local_y, local_z = (
        _ACCELERATOR_PA_TO_GLOBAL.inverse()
        .transform_vector(global_velocity)
        .components
    )
    azimuth_deg = math.degrees(math.atan2(local_y, local_x))
    elevation_deg = math.degrees(
        math.atan2(local_z, math.hypot(local_x, local_y))
    )
    return azimuth_deg, elevation_deg


def validate_ion_velocity_adapter(
    state: Mapping[str, str],
    mapping: Mapping[str, str],
    ion: Sequence[str],
    tolerance: float = 1e-10,
) -> None:
    """Require canonical velocity, row-map angles and ION angles to be equivalent."""
    velocity = tuple(
        _finite_float(state, f"velocity_{axis}_m_s", "canonical state")
        for axis in "xyz"
    )
    mass_amu = _finite_float(state, "mass_amu", "canonical state")
    energy_ev = _finite_float(state, "kinetic_energy_eV", "canonical state")
    if mass_amu <= 0 or energy_ev < 0:
        raise ValueError("canonical mass and kinetic energy are invalid")
    velocity_energy_ev = kinetic_energy_ev(mass_amu, *velocity)
    if not math.isclose(
        velocity_energy_ev, energy_ev, rel_tol=tolerance, abs_tol=1e-12
    ):
        raise ValueError("canonical kinetic energy and velocity are inconsistent")

    ion_azimuth = float(ion[6])
    ion_elevation = float(ion[7])
    map_azimuth = _finite_float(mapping, "azimuth_deg", "row map")
    map_elevation = _finite_float(mapping, "elevation_deg", "row map")
    if not all(math.isfinite(value) for value in (ion_azimuth, ion_elevation)):
        raise ValueError("ION direction angles must be finite")
    if not (
        math.isclose(ion_azimuth, map_azimuth, rel_tol=0.0, abs_tol=1e-10)
        and math.isclose(ion_elevation, map_elevation, rel_tol=0.0, abs_tol=1e-10)
    ):
        raise ValueError("ION direction angles differ from the row-map adapter")

    decoded = decode_simion_accelerator_velocity(
        mass_amu, energy_ev, ion_azimuth, ion_elevation
    )
    if any(
        not math.isclose(actual, expected, rel_tol=tolerance, abs_tol=1e-8)
        for actual, expected in zip(decoded, velocity)
    ):
        raise ValueError("ION direction does not preserve canonical three-dimensional velocity")
