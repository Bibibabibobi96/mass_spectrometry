"""SIMION aperture rasterization of a provider-owned physical opening."""
from __future__ import annotations
import math
from typing import Any, Mapping
from .aperture import resolve_rectangular_aperture_discretization

def project_side_opening(
    geometry: dict[str, Any], *, side_opening: Mapping[str, Any],
    cell_mm_xyz: Mapping[str, float], pa_origin_mm: Mapping[str, float],
) -> dict[str, Any]:
    """Apply one explicit physical opening and its native grid projection in place.

    The outer-face centre is an input, not inferred from the particle source.
    The existing aperture compiler owns rasterization; no new CSG is created.
    Return that compiler's discretization, also retained in the rendered region.
    """
    if set(side_opening) != {"center_mm", "width_mm", "height_mm"}:
        raise ValueError("accelerator side opening requires center_mm, width_mm and height_mm")
    center = side_opening["center_mm"]
    if not isinstance(center, (list, tuple)) or len(center) != 3:
        raise ValueError("accelerator side opening center_mm must have three coordinates")
    x, y, z = map(float, center)
    face = float(geometry["negative_x_face_mm"])
    wall = float(geometry["shield_wall_mm"])
    if not all(math.isfinite(value) for value in (x, y, z)) or not math.isclose(
        x, face, rel_tol=0, abs_tol=1e-9,
    ):
        raise ValueError(f"accelerator side opening must lie on outer wall x={face:g} mm; received {center}")
    discretization = resolve_rectangular_aperture_discretization(
        mechanical_width_mm=float(side_opening["width_mm"]),
        mechanical_height_mm=float(side_opening["height_mm"]),
        cell_mm_xyz=dict(cell_mm_xyz), normal_axis="x",
        flange_min_mm=x, flange_max_mm=x + wall,
        center_mm={"x": (x + x + wall) / 2, "y": y, "z": z},
        pa_origin_mm=dict(pa_origin_mm),
        boolean_boundary_policy="exclude_shape_inside_or_on_v1",
    )
    geometry.update({
        "port_center_y_mm": y, "port_center_z_mm": z,
        "numerical_port_width_mm": float(discretization["numerical_carve_width_mm"]),
        "numerical_port_height_mm": float(discretization["numerical_carve_height_mm"]),
        "accelerator_port_aperture_discretization": discretization,
    })
    return discretization
