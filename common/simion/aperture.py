"""Repository-wide discretization contract for rectangular SIMION apertures."""

from __future__ import annotations

import math
from typing import Any

from common.contracts.machine_contracts import validate_schema


def resolve_rectangular_aperture_discretization(
    *,
    mechanical_width_mm: float,
    mechanical_height_mm: float,
    cell_mm: float,
    flange_x_min_mm: float,
    flange_x_max_mm: float,
    center_y_mm: float,
    center_z_mm: float,
    pa_origin_y_mm: float,
    pa_origin_z_mm: float,
) -> dict[str, Any]:
    """Validate an aperture and return its shared GEM/compiled-PA contract."""
    values = (
        mechanical_width_mm,
        mechanical_height_mm,
        cell_mm,
        flange_x_min_mm,
        flange_x_max_mm,
        center_y_mm,
        center_z_mm,
        pa_origin_y_mm,
        pa_origin_z_mm,
    )
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("SIMION aperture dimensions and bounds must be finite")
    if min(mechanical_width_mm, mechanical_height_mm, cell_mm) <= 0:
        raise ValueError("SIMION aperture dimensions and cell size must be positive")
    if flange_x_max_mm < flange_x_min_mm:
        raise ValueError("SIMION aperture flange bounds are reversed")
    if mechanical_width_mm < cell_mm or mechanical_height_mm < cell_mm:
        raise ValueError(
            "SIMION aperture width and height must each be at least one SIMION cell"
        )

    width_cells = mechanical_width_mm / cell_mm
    height_cells = mechanical_height_mm / cell_mm
    edge_coordinates = {
        "y_min": (center_y_mm - mechanical_width_mm / 2 - pa_origin_y_mm)
        / cell_mm,
        "y_max": (center_y_mm + mechanical_width_mm / 2 - pa_origin_y_mm)
        / cell_mm,
        "z_min": (center_z_mm - mechanical_height_mm / 2 - pa_origin_z_mm)
        / cell_mm,
        "z_max": (center_z_mm + mechanical_height_mm / 2 - pa_origin_z_mm)
        / cell_mm,
    }

    def on_integer(value: float) -> bool:
        tolerance_cells = max(
            1e-9 / cell_mm,
            16 * math.ulp(max(abs(value), 1.0)),
        )
        return abs(value - round(value)) <= tolerance_cells

    width_integer = on_integer(width_cells)
    height_integer = on_integer(height_cells)
    edge_alignment = {
        name: on_integer(value) for name, value in edge_coordinates.items()
    }
    warnings: list[str] = []
    if not width_integer:
        warnings.append("aperture_width_not_integer_cell_multiple")
    if not height_integer:
        warnings.append("aperture_height_not_integer_cell_multiple")
    if not edge_alignment["y_min"] or not edge_alignment["y_max"]:
        warnings.append("aperture_y_edges_not_on_grid_nodes")
    if not edge_alignment["z_min"] or not edge_alignment["z_max"]:
        warnings.append("aperture_z_edges_not_on_grid_nodes")

    contract = {
        "schema_version": 1,
        "role": "simion_rectangular_aperture_discretization",
        "mechanical_width_mm": round(mechanical_width_mm, 12),
        "mechanical_height_mm": round(mechanical_height_mm, 12),
        "cell_mm": round(cell_mm, 12),
        "boolean_boundary_policy": "exclude_shape_inside_or_on_v1",
        "numerical_carve_width_mm": round(mechanical_width_mm, 12),
        "numerical_carve_height_mm": round(mechanical_height_mm, 12),
        "compiled_pa_open_column_check_required": True,
        "flange_x_min_mm": round(flange_x_min_mm, 12),
        "flange_x_max_mm": round(flange_x_max_mm, 12),
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
