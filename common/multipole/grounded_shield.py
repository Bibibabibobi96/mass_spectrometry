"""Fail-closed contracts and SIMION geometry for grounded shield connections."""

from __future__ import annotations

import math
from typing import Any

from common.simion.aperture import (
    resolve_rectangular_aperture_discretization,
)


GROUND_POTENTIAL_V = 0.0


def require_grounded_potential(value: Any, label: str) -> float:
    """Return 0 V or reject values that would expose a biased shield."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) != GROUND_POTENTIAL_V
    ):
        raise ValueError(f"{label} must be exactly 0 V (grounded)")
    return GROUND_POTENTIAL_V


def render_grounded_circular_to_rectangular_connection(
    *,
    electrode_id: int,
    sleeve_x_min_mm: float,
    sleeve_x_max_mm: float,
    flange_thickness_mm: float,
    center_y_mm: float,
    center_z_mm: float,
    outer_radius_mm: float,
    inner_radius_mm: float,
    aperture_width_mm: float,
    aperture_height_mm: float,
    cell_mm_xyz: dict[str, float],
    pa_origin_y_mm: float,
    pa_origin_z_mm: float,
) -> tuple[list[str], dict[str, Any]]:
    """Render a closed grounded sleeve and apertured flange in an x-axis GEM frame."""
    if set(cell_mm_xyz) != {"x", "y", "z"}:
        raise ValueError("grounded connection cell_mm_xyz must contain exactly x, y and z")
    cell_x_mm = float(cell_mm_xyz["x"])
    cell_y_mm = float(cell_mm_xyz["y"])
    cell_z_mm = float(cell_mm_xyz["z"])
    values = {
        "sleeve_x_min_mm": sleeve_x_min_mm,
        "sleeve_x_max_mm": sleeve_x_max_mm,
        "flange_thickness_mm": flange_thickness_mm,
        "outer_radius_mm": outer_radius_mm,
        "inner_radius_mm": inner_radius_mm,
        "aperture_width_mm": aperture_width_mm,
        "aperture_height_mm": aperture_height_mm,
        "cell_x_mm": cell_x_mm,
        "cell_y_mm": cell_y_mm,
        "cell_z_mm": cell_z_mm,
    }
    if not isinstance(electrode_id, int) or electrode_id <= 0:
        raise ValueError("grounded connection electrode_id must be a positive integer")
    if not all(math.isfinite(float(value)) for value in values.values()):
        raise ValueError("grounded connection dimensions must be finite")
    if sleeve_x_max_mm < sleeve_x_min_mm or flange_thickness_mm <= 0:
        raise ValueError("grounded connection axial dimensions are inconsistent")
    if not (0 < inner_radius_mm < outer_radius_mm):
        raise ValueError("grounded connection radii are inconsistent")
    if min(aperture_width_mm, aperture_height_mm, *cell_mm_xyz.values()) <= 0:
        raise ValueError("grounded connection aperture and cell size must be positive")
    if math.hypot(aperture_width_mm / 2, aperture_height_mm / 2) >= outer_radius_mm:
        raise ValueError("grounded connection aperture exceeds the flange envelope")

    fmt = lambda value: format(float(value), ".12g")
    flange_x_max_mm = sleeve_x_max_mm + flange_thickness_mm
    aperture_discretization = resolve_rectangular_aperture_discretization(
        mechanical_width_mm=aperture_width_mm,
        mechanical_height_mm=aperture_height_mm,
        cell_mm_xyz=cell_mm_xyz,
        flange_x_min_mm=sleeve_x_max_mm,
        flange_x_max_mm=flange_x_max_mm,
        center_y_mm=center_y_mm,
        center_z_mm=center_z_mm,
        pa_origin_y_mm=pa_origin_y_mm,
        pa_origin_z_mm=pa_origin_z_mm,
    )
    numerical_aperture_width_mm = aperture_discretization[
        "numerical_carve_width_mm"
    ]
    numerical_aperture_height_mm = aperture_discretization[
        "numerical_carve_height_mm"
    ]
    locate = f"locate({fmt(flange_x_max_mm)},{fmt(center_y_mm)},{fmt(center_z_mm)},1,90)"
    sleeve_length = sleeve_x_max_mm - sleeve_x_min_mm
    lines: list[str] = []
    if sleeve_length > 0:
        lines.extend(
            [
                f"  e({electrode_id}) {{ fill {{",
                f"    within {{ locate({fmt(sleeve_x_max_mm)},{fmt(center_y_mm)},{fmt(center_z_mm)},1,90) {{ cylinder(0,0,0,{fmt(outer_radius_mm)},,{fmt(sleeve_length)}) }} }}",
                f"    notin_inside {{ locate({fmt(sleeve_x_max_mm+cell_x_mm)},{fmt(center_y_mm)},{fmt(center_z_mm)},1,90) {{ cylinder(0,0,0,{fmt(inner_radius_mm)},,{fmt(sleeve_length+2*cell_x_mm)}) }} }}",
                "  } }",
            ]
        )
    flange_start = sleeve_x_max_mm
    lines.extend(
        [
            f"  e({electrode_id}) {{ fill {{",
            f"    within {{ {locate} {{ cylinder(0,0,0,{fmt(outer_radius_mm)},,{fmt(flange_thickness_mm)}) }} }}",
            f"    notin_inside_or_on {{ centered_box3D({fmt(flange_start+flange_thickness_mm/2)},{fmt(center_y_mm)},{fmt(center_z_mm)},{fmt(flange_thickness_mm+2*cell_x_mm)},{fmt(numerical_aperture_width_mm)},{fmt(numerical_aperture_height_mm)}) }}",
            "  } }",
        ]
    )
    return lines, {
        "topology": "grounded_circular_sleeve_with_apertured_flange",
        "shield_potential_V": GROUND_POTENTIAL_V,
        "grounded_sleeve_length_mm": round(sleeve_length, 12),
        "flange_thickness_mm": round(flange_thickness_mm, 12),
        "full_radial_enclosure": True,
        "shared_ground_electrode_id": electrode_id,
        "aperture_discretization": aperture_discretization,
    }
