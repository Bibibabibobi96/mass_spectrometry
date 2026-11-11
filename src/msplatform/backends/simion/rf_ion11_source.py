"""Decode source formats and transform actual WB six-dimensional states to RF.

SIMION azimuth/elevation are not the conventional spherical XYZ tuple: native
WB velocity is (s*cos(el)*cos(az), s*sin(el), -s*cos(el)*sin(az)). See official
https://simion.com/info/particle_initial_conditions.html (read 2026-11-03).
RF local axes are x=WB+z, y=WB-y, z=WB+x; positions additionally get the explicit
axial offset. This is the existing simion_ion11_to_multipole_canonical.v1
interpretation, not a new source, clock origin or physical charge constraint.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

from msplatform.contracts.particle_physics import (
    AMU_KG, ELEMENTARY_CHARGE_C as E_CHARGE_C,
)


def _decode_ion11_workbench_row(row: list[str], particle_id: int) -> dict:
    """Decode one protocol row into actual WB mm/m/s/us, without RF rotation."""
    if len(row) != 11:
        raise ValueError(f"row {particle_id} has {len(row)} columns, expected 11")
    birth_time_us, mass_amu, _, x, y, z, azimuth_deg, elevation_deg, energy_ev, _, _ = map(float, row)
    if mass_amu <= 0 or energy_ev < 0:
        raise ValueError(f"row {particle_id} has invalid mass or kinetic energy")
    speed_m_s = math.sqrt(2 * energy_ev * E_CHARGE_C / (mass_amu * AMU_KG))
    azimuth_rad = math.radians(azimuth_deg)
    elevation_rad = math.radians(elevation_deg)
    # Preserve the original scalar operation order, but name the actual basis.
    axial = speed_m_s * math.cos(elevation_rad) * math.cos(azimuth_rad)
    azimuth_transverse = speed_m_s * math.cos(elevation_rad) * math.sin(azimuth_rad)
    elevation_transverse = speed_m_s * math.sin(elevation_rad)
    return dict(position_mm=(x, y, z), velocity_m_s=(axial, elevation_transverse, -azimuth_transverse),
                birth_time_us=birth_time_us, kinetic_energy_ev=energy_ev)


def _transform_workbench_to_rf_source(state: dict, axial_offset_mm: float) -> dict[str, float]:
    """Apply proper R=[[0,0,1],[0,-1,0],[1,0,0]], t=(0,0,offset) to WB6D.

    Component selection implements R without a sum that changes signed zero.
    Only positions receive translation; birth/energy remain unchanged.
    """
    x, y, z = state["position_mm"]
    vx, vy, vz = state["velocity_m_s"]
    return {
        "time_us": state["birth_time_us"], "elapsed_time_us": 0.0,
        "axial_z_mm": x + axial_offset_mm, "transverse_x_mm": z, "transverse_y_mm": -y,
        "velocity_axial_m_s": vx, "velocity_x_m_s": vz, "velocity_y_m_s": -vy,
        "kinetic_energy_eV": state["kinetic_energy_ev"],
    }


def read_ion11_source_states(path: Path, axial_offset_mm: float = 0.0) -> dict[int, dict[str, float]]:
    """Read RF event source expectations from standard ION11, preserving row IDs.

    Input positions are WB mm, angles degrees, birth us, mass amu, kinetic eV.
    Output uses RF local axes above, velocities m/s and unchanged birth us.
    Offset is explicit WB+x/RF+z placement, not a new clock or transverse origin.
    This reader preserves the old format validation; no charge policy is added.
    """
    result = {}
    rows = csv.reader(path.read_text(encoding="utf-8-sig").splitlines())
    for particle_id, row in enumerate(rows, start=1):
        result[particle_id] = _transform_workbench_to_rf_source(
            _decode_ion11_workbench_row(row, particle_id), axial_offset_mm)
    return result
