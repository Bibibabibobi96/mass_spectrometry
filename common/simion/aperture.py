"""Repository-wide discretization contract for rectangular SIMION apertures."""

from __future__ import annotations

import math
from typing import Any

from common.contracts.machine_contracts import validate_schema


def resolve_rectangular_aperture_discretization(
    *,
    mechanical_width_mm: float,
    mechanical_height_mm: float,
    cell_mm_xyz: dict[str, float],
    normal_axis: str,
    flange_min_mm: float,
    flange_max_mm: float,
    center_mm: dict[str, float],
    pa_origin_mm: dict[str, float],
    boolean_boundary_policy: str,
) -> dict[str, Any]:
    """Validate an aperture and return its shared GEM/compiled-PA contract."""
    if normal_axis not in ("x", "y", "z"):
        raise ValueError("SIMION aperture normal_axis must be x, y or z")
    if boolean_boundary_policy not in (
        "exclude_shape_inside_only_v1", "exclude_shape_inside_or_on_v1"
    ):
        raise ValueError("unsupported SIMION aperture boolean boundary policy")
    for name, coordinates in (("cell_mm_xyz", cell_mm_xyz), ("center_mm", center_mm),
                              ("pa_origin_mm", pa_origin_mm)):
        if set(coordinates) != {"x", "y", "z"}:
            raise ValueError(f"SIMION aperture {name} must contain exactly x, y and z")
        if any(isinstance(v, bool) or not math.isfinite(float(v)) for v in coordinates.values()):
            raise ValueError(f"SIMION aperture {name} must contain finite coordinates")
    width_axis, height_axis = (a for a in "xyz" if a != normal_axis)
    width_cell = float(cell_mm_xyz[width_axis])
    height_cell = float(cell_mm_xyz[height_axis])
    values = (mechanical_width_mm, mechanical_height_mm, flange_min_mm, flange_max_mm)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("SIMION aperture dimensions and bounds must be finite")
    if min(mechanical_width_mm, mechanical_height_mm, *cell_mm_xyz.values()) <= 0:
        raise ValueError("SIMION aperture dimensions and cell size must be positive")
    if flange_max_mm < flange_min_mm:
        raise ValueError("SIMION aperture flange bounds are reversed")
    # Equal-sized physical apertures are valid.  Accept equality robustly
    # across JSON-to-float roundoff (for example 1.0 mm on a 1.0 mm grid).
    dimension_tolerance_mm = 16 * max(
        math.ulp(max(abs(mechanical_width_mm), abs(width_cell), 1.0)),
        math.ulp(max(abs(mechanical_height_mm), abs(height_cell), 1.0)),
    )
    if (
        mechanical_width_mm + dimension_tolerance_mm < width_cell
        or mechanical_height_mm + dimension_tolerance_mm < height_cell
    ):
        raise ValueError(
            "SIMION aperture width and height must each be at least one SIMION cell"
        )

    width_cells = mechanical_width_mm / width_cell
    height_cells = mechanical_height_mm / height_cell
    edge_coordinates = {
        f"{axis}_{side}": (float(center_mm[axis]) + sign * size / 2 - float(pa_origin_mm[axis])) / cell
        for axis, size, cell in ((width_axis, mechanical_width_mm, width_cell),
                                 (height_axis, mechanical_height_mm, height_cell))
        for side, sign in (("min", -1), ("max", 1))
    }

    def on_integer(value: float, cell_mm: float) -> bool:
        tolerance_cells = max(
            1e-9 / cell_mm,
            16 * math.ulp(max(abs(value), 1.0)),
        )
        return abs(value - round(value)) <= tolerance_cells

    width_integer = on_integer(width_cells, width_cell)
    height_integer = on_integer(height_cells, height_cell)
    edge_alignment = {
        name: on_integer(value, float(cell_mm_xyz[name[0]]))
        for name, value in edge_coordinates.items()
    }
    # Preserve the shared warning semantics for either explicit boolean policy.
    # A centred physical edge can correctly
    # lie halfway between nodes: that is a grid cell face, not a geometry
    # error.  Warn only when an edge is neither a node nor a cell face.
    edge_compatible = {
        name: on_integer(
            2 * value, float(cell_mm_xyz[name[0]])
        )
        for name, value in edge_coordinates.items()
    }
    warnings: list[str] = []
    if not width_integer:
        warnings.append("aperture_width_not_integer_cell_multiple")
    if not height_integer:
        warnings.append("aperture_height_not_integer_cell_multiple")
    if not edge_compatible[f"{width_axis}_min"] or not edge_compatible[f"{width_axis}_max"]:
        warnings.append(f"aperture_{width_axis}_edges_not_on_grid_nodes")
    if not edge_compatible[f"{height_axis}_min"] or not edge_compatible[f"{height_axis}_max"]:
        warnings.append(f"aperture_{height_axis}_edges_not_on_grid_nodes")

    contract = {
        "schema_version": 3,
        "role": "simion_rectangular_aperture_discretization",
        "mechanical_width_mm": round(mechanical_width_mm, 12),
        "mechanical_height_mm": round(mechanical_height_mm, 12),
        "cell_mm_xyz": {a: round(float(cell_mm_xyz[a]), 12) for a in "xyz"},
        "normal_axis": normal_axis,
        "center_mm": {a: round(float(center_mm[a]), 12) for a in "xyz"},
        "pa_origin_mm": {a: round(float(pa_origin_mm[a]), 12) for a in "xyz"},
        "boolean_boundary_policy": boolean_boundary_policy,
        "numerical_carve_width_mm": round(mechanical_width_mm, 12),
        "numerical_carve_height_mm": round(mechanical_height_mm, 12),
        "compiled_pa_open_column_check_required": True,
        "flange_min_mm": round(flange_min_mm, 12),
        "flange_max_mm": round(flange_max_mm, 12),
        "grid_alignment": {
            "width_cells": round(width_cells, 12),
            "height_cells": round(height_cells, 12),
            "width_is_integer_cell_multiple": width_integer,
            "height_is_integer_cell_multiple": height_integer,
            "edge_grid_coordinates": {
                name: round(value, 12)
                for name, value in edge_coordinates.items()
            },
            "edges_on_grid_nodes": edge_alignment,
            "warnings": warnings,
        },
    }
    validate_schema(
        contract,
        "simion_rectangular_aperture_discretization.schema.json",
    )
    return contract
