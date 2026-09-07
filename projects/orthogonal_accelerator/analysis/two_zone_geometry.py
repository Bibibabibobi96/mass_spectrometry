"""Solver-neutral rectangular accelerator geometry owned by this project.

The module deliberately has no instrument baseline, voltage contract, CAD dimensions,
or SIMION syntax.  Each instrument supplies those values; it calls these functions
only to derive an evenly distributed second-region ring sequence and a
rectangular shield enclosure without duplicating their invariants.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite


class TwoZoneGeometryError(ValueError):
    """Raised when a solver-neutral two-zone geometric invariant is invalid."""


@dataclass(frozen=True)
class UniformRingPlaneLayout:
    """Interior ring planes in the declared start-to-end direction, in mm."""

    pitch_mm: float
    centers_mm: tuple[float, ...]


@dataclass(frozen=True)
class ShieldedRectangularEnclosure:
    """Rectangular two-zone electrode/grounded-shell dimensions in mm."""

    electrode_half_x_mm: float
    electrode_half_y_mm: float
    guard_half_x_mm: float
    guard_half_y_mm: float
    guard_wall_mm: float
    guard_inner_half_x_mm: float
    guard_inner_half_y_mm: float
    lateral_clearance_mm: float
    rear_cap_inner_z_mm: float
    rear_cap_outer_z_mm: float


def _positive(value: float, name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or numeric <= 0.0:
        raise TwoZoneGeometryError(f"{name} must be finite and positive")
    return numeric


def derive_uniform_ring_planes(
    start_mm: float, end_mm: float, ring_count: int, *, ring_thickness_mm: float | None = None
) -> UniformRingPlaneLayout:
    """Return equally spaced interior ring centers from ``start_mm`` to ``end_mm``.

    ``start_mm`` and ``end_mm`` may be either increasing or decreasing.  When
    a physical ring thickness is supplied, it must be strictly less than the
    derived pitch so adjacent rings cannot overlap.
    """
    if isinstance(ring_count, bool) or not isinstance(ring_count, int) or ring_count < 0:
        raise TwoZoneGeometryError("ring_count must be a nonnegative integer")
    start, end = float(start_mm), float(end_mm)
    if not isfinite(start) or not isfinite(end) or isclose(start, end, abs_tol=1e-12):
        raise TwoZoneGeometryError("ring-plane endpoints must be finite and distinct")
    pitch = abs(end - start) / (ring_count + 1)
    if ring_thickness_mm is not None and _positive(ring_thickness_mm, "ring_thickness_mm") >= pitch:
        raise TwoZoneGeometryError("ring_thickness_mm must be smaller than the derived ring pitch")
    direction = 1.0 if end > start else -1.0
    return UniformRingPlaneLayout(
        pitch_mm=pitch,
        centers_mm=tuple(start + direction * index * pitch for index in range(1, ring_count + 1)),
    )


def derive_shielded_rectangular_enclosure(
    *, electrode_outer_width_x_mm: float, electrode_outer_height_y_mm: float,
    guard_outer_width_x_mm: float, guard_outer_height_y_mm: float,
    guard_wall_thickness_mm: float, lateral_clearance_mm: float,
    repeller_z_mm: float, repeller_thickness_z_mm: float, rear_gap_mm: float,
) -> ShieldedRectangularEnclosure:
    """Derive a finite grounded rectangular shell for acceleration toward -z.

    ``repeller_z_mm`` denotes the repeller face facing the acceleration gap;
    its material and rear clearance extend toward increasing z.  Consumers
    using a +z accelerating frame must transform their input/output explicitly.
    This function does not place the enclosure in an instrument frame.
    """
    electrode_half_x = _positive(electrode_outer_width_x_mm, "electrode_outer_width_x_mm") / 2.0
    electrode_half_y = _positive(electrode_outer_height_y_mm, "electrode_outer_height_y_mm") / 2.0
    guard_half_x = _positive(guard_outer_width_x_mm, "guard_outer_width_x_mm") / 2.0
    guard_half_y = _positive(guard_outer_height_y_mm, "guard_outer_height_y_mm") / 2.0
    wall = _positive(guard_wall_thickness_mm, "guard_wall_thickness_mm")
    clearance = _positive(lateral_clearance_mm, "lateral_clearance_mm")
    rear_gap = _positive(rear_gap_mm, "rear_gap_mm")
    repeller_z = float(repeller_z_mm)
    repeller_thickness = _positive(repeller_thickness_z_mm, "repeller_thickness_z_mm")
    if not isfinite(repeller_z) or wall >= min(guard_half_x, guard_half_y):
        raise TwoZoneGeometryError("grounded enclosure requires a finite repeller position and finite wall")
    inner_x, inner_y = guard_half_x - wall, guard_half_y - wall
    if not isclose(inner_x - electrode_half_x, clearance, abs_tol=1e-9) or not isclose(
        inner_y - electrode_half_y, clearance, abs_tol=1e-9
    ):
        raise TwoZoneGeometryError("electrode must retain the declared equal lateral clearance to the grounded wall")
    rear_inner = repeller_z + repeller_thickness + rear_gap
    return ShieldedRectangularEnclosure(
        electrode_half_x_mm=electrode_half_x,
        electrode_half_y_mm=electrode_half_y,
        guard_half_x_mm=guard_half_x,
        guard_half_y_mm=guard_half_y,
        guard_wall_mm=wall,
        guard_inner_half_x_mm=inner_x,
        guard_inner_half_y_mm=inner_y,
        lateral_clearance_mm=clearance,
        rear_cap_inner_z_mm=rear_inner,
        rear_cap_outer_z_mm=rear_inner + wall,
    )
