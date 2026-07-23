"""Resolve one solver-neutral circular-rod multipole geometry description."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
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


def resolve_round_rod_geometry(
    baseline: dict[str, Any],
    finite_3d: dict[str, Any],
    field_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Return the complete rod array and interface positions for all solvers."""
    multipole = baseline["multipole"]
    electrode_count = int(multipole["electrode_count"])
    radial_order = int(multipole["radial_order_n"])
    selected = field_metrics["selected_candidate"]
    r0 = float(baseline["geometry_mm"]["inscribed_radius_r0"])
    rod_radius = float(selected["rod_radius_mm"])
    center_radius = float(selected["rod_center_radius_mm"])
    if min(r0, rod_radius, center_radius) <= 0 or not math.isclose(
        center_radius, r0 + rod_radius, rel_tol=0, abs_tol=1e-9
    ):
        raise RoundRodGeometryError("selected circular-rod dimensions are inconsistent with r0")
    identity = finite_3d["multipole"]
    if identity != {"radial_order_n": radial_order, "electrode_count": electrode_count}:
        raise RoundRodGeometryError("finite-3D and baseline multipole identities differ")
    geometry = finite_3d["geometry_mm"]
    derived = finite_3d["derived_geometry_mm"]
    orientation = float(multipole.get("orientation_rad", 0.0))
    array = build_round_rod_array(
        radial_order_n=radial_order,
        electrode_count=electrode_count,
        inscribed_radius_r0_mm=r0,
        rod_radius_mm=rod_radius,
        rod_z_min_mm=float(geometry["rod_z_min"]),
        rod_z_max_mm=float(derived["rod_z_max"]),
        orientation_rad=orientation,
    )
    return {
        "schema_version": 1,
        "role": "multipole_round_rod_geometry_resolved_contract",
        "project_id": baseline["project_id"],
        "coordinate_id": baseline["conventions"]["coordinate_id"],
        "identity": {
            "radial_order_n": radial_order,
            "electrode_count": electrode_count,
            "orientation_rad": orientation,
        },
        "array_mm": array,
        "grounded_enclosure_mm": {
            "shield_inner_radius": float(geometry["grounded_shield_inner_radius"]),
            "shield_outer_radius": float(derived["shield_outer_radius"]),
            "vacuum_z_min": float(derived["vacuum_z_min"]),
            "vacuum_z_max": float(derived["vacuum_z_max"]),
        },
        "interfaces_mm": {
            "source_z": float(derived["source_z"]),
            "entrance_plate_z_min": float(derived["entrance_plate_z_min"]),
            "entrance_plate_z_max": float(derived["entrance_plate_z_max"]),
            "entrance_aperture_radius": float(geometry["entrance_interface"]["aperture_radius_mm"]),
            "exit_plate_z_min": float(derived["exit_plate_z_min"]),
            "exit_plate_z_max": float(derived["exit_plate_z_max"]),
            "exit_aperture_radius": float(geometry["exit_interface"]["aperture_radius_mm"]),
            "entrance_connector_length": float(geometry["entrance_interface"]["connector_length_mm"]),
            "entrance_connector_shape": geometry["entrance_interface"]["connector_shape"],
            "exit_connector_length": float(geometry["exit_interface"]["connector_length_mm"]),
            "exit_connector_shape": geometry["exit_interface"]["connector_shape"],
            "detector_z": float(derived["detector_z"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--finite-3d", required=True, type=Path)
    parser.add_argument("--field-metrics", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    result = resolve_round_rod_geometry(load(args.baseline), load(args.finite_3d), load(args.field_metrics))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
