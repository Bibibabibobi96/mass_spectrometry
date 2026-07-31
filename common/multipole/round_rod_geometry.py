"""Build one solver-neutral circular-rod multipole array."""

from __future__ import annotations

import math
from typing import Any


class RoundRodGeometryError(ValueError):
    """Raised when the common rod-array inputs are inconsistent."""


def build_round_rod_array(
    *,
    radial_order_n: int,
    electrode_count: int,
    inscribed_radius_r0_mm: float,
    rod_radius_mm: float,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
    orientation_rad: float = 0.0,
) -> dict[str, Any]:
    """Build the solver-neutral circular-rod array shared by every multipole."""
    if electrode_count != 2 * radial_order_n or electrode_count < 4:
        raise RoundRodGeometryError("electrode_count must equal 2*radial_order_n and be at least four")
    values = (
        inscribed_radius_r0_mm,
        rod_radius_mm,
        rod_z_min_mm,
        rod_z_max_mm,
        orientation_rad,
    )
    if not all(math.isfinite(float(value)) for value in values):
        raise RoundRodGeometryError("rod-array dimensions and orientation must be finite")
    if inscribed_radius_r0_mm <= 0 or rod_radius_mm <= 0 or rod_z_max_mm <= rod_z_min_mm:
        raise RoundRodGeometryError("rod-array radii must be positive and z_max must exceed z_min")
    center_radius = inscribed_radius_r0_mm + rod_radius_mm
    rods = []
    for index in range(electrode_count):
        angle = orientation_rad + 2 * math.pi * index / electrode_count
        rods.append(
            {
                "rod_id": index + 1,
                "electrode_group": 1 if index % 2 == 0 else 2,
                "angle_rad": angle,
                "center_x_mm": center_radius * math.cos(angle),
                "center_y_mm": center_radius * math.sin(angle),
                "radius_mm": rod_radius_mm,
                "z_min_mm": rod_z_min_mm,
                "z_max_mm": rod_z_max_mm,
            }
        )
    return {
        "inscribed_radius_r0": inscribed_radius_r0_mm,
        "rod_radius": rod_radius_mm,
        "rod_center_radius": center_radius,
        "rod_length": rod_z_max_mm - rod_z_min_mm,
        "rods": rods,
    }
