"""SIMION-2020 CSG emission for rectangular accelerator electrodes.

Input lengths are resolved millimetres in the caller's explicitly chosen frame.
These functions do not choose a project baseline, grid, ID namespace, voltage,
or placement; the instrument adapter owns those projections. Cut padding is a
numerical Boolean extent, not a physical aperture enlargement.
"""
from __future__ import annotations

from math import isfinite

from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
    ShieldedRectangularEnclosure,
    TwoZoneGeometryError,
)


def _number(value: float) -> str:
    if not isfinite(value):
        raise TwoZoneGeometryError("GEM lengths must be finite")
    return f"{value:.12g}"


def emit_open_rectangular_frame(
    electrode_id: int, *, outer_half_x_mm: float, outer_half_y_mm: float,
    aperture_half_x_mm: float, aperture_half_y_mm: float,
    front_z_mm: float, back_z_mm: float, cut_padding_mm: float,
) -> str:
    """Emit a frame retaining nodes on its exact aperture walls.

    With SIMION 2020 ``surface=none``, ``notin_inside`` removes only the
    aperture interior; ordinary ``notin`` also removes the physical wall.
    The cut extends past both axial faces so it cannot leave bore end caps.
    """
    _check_id(electrode_id)
    if not (0 < aperture_half_x_mm < outer_half_x_mm and
            0 < aperture_half_y_mm < outer_half_y_mm and
            front_z_mm < back_z_mm and cut_padding_mm > 0):
        raise TwoZoneGeometryError("open frame requires positive material, aperture, thickness and padding")
    x, y, ax, ay = (outer_half_x_mm, outer_half_y_mm, aperture_half_x_mm, aperture_half_y_mm)
    return (
        f"  e({electrode_id}) {{ box3D(-{_number(x)},-{_number(y)},{_number(front_z_mm)},"
        f"{_number(x)},{_number(y)},{_number(back_z_mm)}) notin_inside {{ box3D("
        f"-{_number(ax)},-{_number(ay)},{_number(front_z_mm-cut_padding_mm)},"
        f"{_number(ax)},{_number(ay)},{_number(back_z_mm+cut_padding_mm)}) }} }}"
    )


def emit_solid_rectangular_plate(
    electrode_id: int, *, half_x_mm: float, half_y_mm: float,
    front_z_mm: float, back_z_mm: float,
) -> str:
    """Emit a closed extraction/re­peller plate.

    Unlike an intermediate or exit grid, a repeller sits behind the source and
    must establish the first axial field.  Giving it a beam aperture turns it
    into a weak ring and lets the grounded enclosure dominate the on-axis
    potential, which is not the two-zone model.
    """
    _check_id(electrode_id)
    if not (half_x_mm > 0 and half_y_mm > 0 and front_z_mm < back_z_mm):
        raise TwoZoneGeometryError("solid plate requires positive spans and thickness")
    return (
        f"  e({electrode_id}) {{ box3D(-{_number(half_x_mm)},-{_number(half_y_mm)},"
        f"{_number(front_z_mm)},{_number(half_x_mm)},{_number(half_y_mm)},{_number(back_z_mm)}) }}"
    )


def emit_ideal_grid(
    electrode_id: int, *, half_x_mm: float, half_y_mm: float, z_mm: float,
) -> str:
    """Emit a zero-thickness grid; the PA builder must verify raw-node alignment."""
    _check_id(electrode_id)
    if not (half_x_mm > 0 and half_y_mm > 0):
        raise TwoZoneGeometryError("ideal-grid half spans must be positive")
    return (
        f"  e({electrode_id}) {{ box3D(-{_number(half_x_mm)},-{_number(half_y_mm)},"
        f"{_number(z_mm)},{_number(half_x_mm)},{_number(half_y_mm)},{_number(z_mm)}) }}"
    )


def emit_grounded_enclosure(
    enclosure: ShieldedRectangularEnclosure, *, exit_z_mm: float,
) -> str:
    """Emit a -z-facing hollow shell CSG expression, without assigning its ID."""
    if not exit_z_mm < enclosure.rear_cap_inner_z_mm < enclosure.rear_cap_outer_z_mm:
        raise TwoZoneGeometryError("exit must precede the rear cap in the -z accelerating frame")
    x, y = enclosure.guard_half_x_mm, enclosure.guard_half_y_mm
    ix, iy = enclosure.guard_inner_half_x_mm, enclosure.guard_inner_half_y_mm
    return (
        f"box3D(-{_number(x)},-{_number(y)},{_number(exit_z_mm)},"
        f"{_number(x)},{_number(y)},{_number(enclosure.rear_cap_outer_z_mm)}) notin {{ "
        f"box3D(-{_number(ix)},-{_number(iy)},{_number(exit_z_mm)},"
        f"{_number(ix)},{_number(iy)},{_number(enclosure.rear_cap_inner_z_mm)}) }}"
    )


def _check_id(electrode_id: int) -> None:
    if isinstance(electrode_id, bool) or not isinstance(electrode_id, int) or electrode_id < 1:
        raise TwoZoneGeometryError("electrode_id must be a positive integer")
