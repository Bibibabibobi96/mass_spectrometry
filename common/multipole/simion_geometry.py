"""Export the shared circular-rod geometry contract to a SIMION GEM file."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.connector_geometry import CONNECTOR_SHAPES


def render_grouped_rod_array_gem(array: dict[str, Any]) -> str:
    """Render a shared rod-array contract as alternating SIMION electrodes."""
    rods = array["rods"]
    if not rods:
        raise ValueError("rod array must contain at least one rod")
    z_max = float(rods[0]["z_max_mm"])
    lines = [f"locate(0,0,{z_max:.15g}) {{"]
    for group in (1, 2):
        lines.append(f"  e({group}) {{")
        for rod in rods:
            if int(rod["electrode_group"]) != group:
                continue
            x = 0.0 if abs(float(rod["center_x_mm"])) < 1e-12 else float(rod["center_x_mm"])
            y = 0.0 if abs(float(rod["center_y_mm"])) < 1e-12 else float(rod["center_y_mm"])
            length = float(rod["z_max_mm"]) - float(rod["z_min_mm"])
            lines.append(
                "    fill { within { cylinder("
                f"{x:.15g},{y:.15g},0, {float(rod['radius_mm']):.15g},, {length:.15g}) }} }}"
            )
        lines.append("  }")
    lines.extend(["}", ""])
    return "\n".join(lines)


def render_segmented_rod_array_gem(segmented: dict[str, Any]) -> str:
    """Render solver-neutral rod segments using their explicit electrode IDs."""
    electrodes = segmented.get("electrodes", [])
    if not electrodes:
        raise ValueError("segmented rod contract must contain electrodes")
    lines: list[str] = []
    for electrode in electrodes:
        x = float(electrode["center_x_mm"])
        y = float(electrode["center_y_mm"])
        z_min = float(electrode["z_min_mm"])
        z_max = float(electrode["z_max_mm"])
        lines.extend(
            [
                f"locate(0,0,{z_max:.15g}) {{",
                f"  e({int(electrode['electrode_id'])}) {{ fill {{ within {{ cylinder("
                f"{x:.15g},{y:.15g},0, {float(electrode['radius_mm']):.15g},, {z_max-z_min:.15g}) }} }} }}",
                "}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def render_gem(
    geometry: dict[str, Any],
    cell_mm: float,
    segmented_rods: dict[str, Any] | None = None,
    separate_output_electrode: bool = False,
) -> str:
    """Render one finite multipole as a self-contained SIMION GEM."""
    if not math.isfinite(cell_mm) or cell_mm <= 0:
        raise ValueError("cell_mm must be positive")
    enclosure = geometry["grounded_enclosure_mm"]
    interface = geometry["interfaces_mm"]
    _validate_connector_shapes(interface)
    if enclosure.get("model", "cylindrical_grounded_shield_v1") == "rectangular_reference_enclosure_v1":
        return _render_rectangular_reference_gem(
            geometry, cell_mm, segmented_rods, separate_output_electrode
        )
    rods = geometry["array_mm"]["rods"]
    axial_mode = segmented_rods is not None
    if axial_mode:
        rods = segmented_rods.get("electrodes", [])
        segment_count = segmented_rods.get("segment_count")
        if not isinstance(segment_count, int) or segment_count < 2 or not rods:
            raise ValueError("segmented rod contract is incomplete")
        ground_electrode = 2 * segment_count + 1
        output_electrode = ground_electrode + 1
    else:
        ground_electrode = 3
        output_electrode = 4 if separate_output_electrode else 3
    outer = float(enclosure["shield_outer_radius"])
    inner = float(enclosure["shield_inner_radius"])
    z_min = float(enclosure["vacuum_z_min"])
    z_max = float(enclosure["vacuum_z_max"])
    span = z_max - z_min
    nx = math.ceil(2 * outer / cell_mm) + 1
    nz = math.ceil(span / cell_mm) + 1
    lines = [
        "; Generated from the solver-neutral round-rod geometry contract; do not edit.",
        f"pa_define({nx},{nx},{nz},planar,none,electrostatic,,{cell_mm:.12g},{cell_mm:.12g},{cell_mm:.12g},surface=fractional)",
        f"locate({outer:.12g},{outer:.12g},{-z_min:.12g}) {{",
    ]
    for rod in rods:
        lines.extend([
            f"  e({rod.get('electrode_id', rod['electrode_group'])}) {{ fill {{ within {{ cylinder({rod['center_x_mm']:.12g},{rod['center_y_mm']:.12g},{rod['z_max_mm']:.12g},{rod['radius_mm']:.12g},,{rod['z_max_mm']-rod['z_min_mm']:.12g}) }} }} }}",
        ])
    lines.extend([
        f"  e({ground_electrode}) {{ fill {{",
        f"    within {{ cylinder(0,0,{z_max:.12g},{outer:.12g},,{span:.12g}) }}",
        f"    notin_inside {{ cylinder(0,0,{z_max+cell_mm:.12g},{inner:.12g},,{span+2*cell_mm:.12g}) }}",
        "  } }",
        f"  e({ground_electrode}) {{ fill {{ within {{ cylinder(0,0,{z_min+cell_mm:.12g},{outer:.12g},,{cell_mm:.12g}) }} }} }}",
        f"  e({output_electrode}) {{ fill {{ within {{ cylinder(0,0,{z_max:.12g},{outer:.12g},,{cell_mm:.12g}) }} }} }}",
        f"  e({ground_electrode}) {{ fill {{",
        f"    within {{ cylinder(0,0,{interface['entrance_plate_z_max']:.12g},{outer:.12g},,{interface['entrance_plate_z_max']-interface['entrance_plate_z_min']:.12g}) }}",
        f"    notin_inside {{ cylinder(0,0,{interface['entrance_plate_z_max']+cell_mm:.12g},{interface['entrance_aperture_radius']:.12g},,{interface['entrance_plate_z_max']-interface['entrance_plate_z_min']+2*cell_mm:.12g}) }}",
        "  } }",
        f"  e({output_electrode}) {{ fill {{",
        f"    within {{ cylinder(0,0,{interface['exit_plate_z_max']:.12g},{outer:.12g},,{interface['exit_plate_z_max']-interface['exit_plate_z_min']:.12g}) }}",
        f"    notin_inside {{ cylinder(0,0,{interface['exit_plate_z_max']+cell_mm:.12g},{interface['exit_aperture_radius']:.12g},,{interface['exit_plate_z_max']-interface['exit_plate_z_min']+2*cell_mm:.12g}) }}",
        "  } }",
    ])
    entrance_length = float(interface["entrance_connector_length"])
    exit_length = float(interface["exit_connector_length"])
    if entrance_length > 0:
        lines.extend([
            f"  ; connector_shape={interface['entrance_connector_shape']}",
            f"  e({ground_electrode}) {{ fill {{",
            f"    within {{ cylinder(0,0,{interface['entrance_plate_z_min']:.12g},{outer:.12g},,{entrance_length:.12g}) }}",
            f"    notin_inside {{ cylinder(0,0,{interface['entrance_plate_z_min']+cell_mm:.12g},{interface['entrance_aperture_radius']:.12g},,{entrance_length+2*cell_mm:.12g}) }}",
            "  } }",
        ])
    if exit_length > 0:
        lines.extend([
            f"  ; connector_shape={interface['exit_connector_shape']}",
            f"  e({output_electrode}) {{ fill {{",
            f"    within {{ cylinder(0,0,{interface['exit_plate_z_max']+exit_length:.12g},{outer:.12g},,{exit_length:.12g}) }}",
            f"    notin_inside {{ cylinder(0,0,{interface['exit_plate_z_max']+exit_length+cell_mm:.12g},{interface['exit_aperture_radius']:.12g},,{exit_length+2*cell_mm:.12g}) }}",
            "  } }",
        ])
    lines.extend(["}", ""])
    return "\n".join(lines)


def _validate_connector_shapes(interface: dict[str, Any]) -> None:
    for side in ("entrance", "exit"):
        shape = interface.get(f"{side}_connector_shape")
        if shape not in CONNECTOR_SHAPES:
            raise ValueError(f"{side} connector shape is unsupported: {shape}")


def _render_rectangular_reference_gem(
    geometry: dict[str, Any],
    cell_mm: float,
    segmented_rods: dict[str, Any] | None,
    separate_output_electrode: bool,
) -> str:
    enclosure = geometry["grounded_enclosure_mm"]
    reference = enclosure["reference_enclosure"]
    interface = geometry["interfaces_mm"]
    rods = geometry["array_mm"]["rods"]
    if segmented_rods is not None:
        rods = segmented_rods.get("electrodes", [])
        segment_count = segmented_rods.get("segment_count")
        if not isinstance(segment_count, int) or segment_count < 2 or not rods:
            raise ValueError("segmented rod contract is incomplete")
        ground_electrode = 2 * segment_count + 1
        output_electrode = ground_electrode + 1
    else:
        ground_electrode = 3
        output_electrode = 4 if separate_output_electrode else 3
    outer = float(reference["outer_half_width_mm"])
    inner = float(reference["inner_half_width_mm"])
    z_min = float(enclosure["vacuum_z_min"])
    z_max = float(enclosure["vacuum_z_max"])
    nx = math.ceil(outer / cell_mm) + 1
    nz = math.ceil((z_max - z_min) / cell_mm) + 1
    lines = [
        "; Generated from the solver-neutral round-rod geometry contract; do not edit.",
        f"pa_define({nx},{nx},{nz},planar,xy,electrostatic,,{cell_mm:.12g},{cell_mm:.12g},{cell_mm:.12g},surface=fractional)",
    ]
    for rod in rods:
        z0 = float(rod["z_min_mm"])
        z1 = float(rod["z_max_mm"])
        electrode = int(rod.get("electrode_id", rod["electrode_group"]))
        lines.extend(
            [
                f"locate(0,0,{z1:.12g}) {{",
                f"  e({electrode}) {{ fill {{ within {{ cylinder({float(rod['center_x_mm']):.12g},{float(rod['center_y_mm']):.12g},0,{float(rod['radius_mm']):.12g},,{z1-z0:.12g}) }} }} }}",
                "}",
            ]
        )
    _append_rectangular_apertured_section(
        lines,
        ground_electrode,
        outer,
        interface["entrance_aperture_radius"],
        interface["entrance_plate_z_min"],
        float(interface["entrance_plate_z_max"]) - float(interface["entrance_plate_z_min"]),
    )
    exit_z_min = float(reference["exit_enclosure_z_min_mm"])
    exit_z_max = float(reference["exit_enclosure_z_max_mm"])
    front_end = float(reference["exit_front_wall_end_z_mm"])
    lines.extend(
        [
            f"locate(0,0,{exit_z_min:.12g}) {{",
            f"  e({output_electrode}) {{ fill {{",
            f"    within {{ box3d({outer:.12g},{outer:.12g},0,{-outer:.12g},{-outer:.12g},{exit_z_max-exit_z_min:.12g}) }}",
            f"    notin_inside {{ box3d({inner:.12g},{inner:.12g},{front_end-exit_z_min:.12g},{-inner:.12g},{-inner:.12g},1E+6) }}",
            f"    notin_inside {{ cylinder(0,0,{exit_z_max-exit_z_min+cell_mm:.12g},{float(interface['exit_aperture_radius']):.12g},,{exit_z_max-exit_z_min+2*cell_mm:.12g}) }}",
            "  } }",
            f"  e({output_electrode}) {{ fill {{ within {{ cylinder(0,0,{float(interface['detector_z'])-exit_z_min:.12g},{float(interface.get('detector_radius', interface['exit_aperture_radius'])):.12g},,{float(reference['detector_thickness_mm']):.12g}) }} }} }}",
            "}",
        ]
    )
    _append_connector(
        lines,
        ground_electrode,
        interface["entrance_connector_shape"],
        outer,
        interface["entrance_aperture_radius"],
        float(interface["entrance_plate_z_min"]) - float(interface["entrance_connector_length"]),
        interface["entrance_connector_length"],
        cell_mm,
    )
    _append_connector(
        lines,
        output_electrode,
        interface["exit_connector_shape"],
        outer,
        interface["exit_aperture_radius"],
        interface["exit_plate_z_max"],
        interface["exit_connector_length"],
        cell_mm,
    )
    lines.append("")
    return "\n".join(lines)


def _append_rectangular_apertured_section(
    lines: list[str],
    electrode: int,
    outer_half_width_mm: float,
    aperture_radius_mm: float,
    z_min_mm: float,
    length_mm: float,
) -> None:
    lines.extend(
        [
            f"locate(0,0,{float(z_min_mm):.12g}) {{",
            f"  e({electrode}) {{ fill {{",
            f"    within {{ box3d({outer_half_width_mm:.12g},{outer_half_width_mm:.12g},0,{-outer_half_width_mm:.12g},{-outer_half_width_mm:.12g},{float(length_mm):.12g}) }}",
            f"    notin_inside {{ cylinder(0,0,{float(length_mm):.12g},{float(aperture_radius_mm):.12g},,{float(length_mm):.12g}) }}",
            "  } }",
            "}",
        ]
    )


def _append_connector(
    lines: list[str],
    electrode: int,
    shape: str,
    outer_size_mm: float,
    aperture_radius_mm: float,
    z_min_mm: float,
    length_mm: float,
    cell_mm: float,
) -> None:
    length = float(length_mm)
    if length == 0:
        return
    lines.extend([f"; connector_shape={shape}", f"locate(0,0,{float(z_min_mm):.12g}) {{", f"  e({electrode}) {{ fill {{"])
    if shape == "rectangular_bore":
        lines.append(
            f"    within {{ box3d({outer_size_mm:.12g},{outer_size_mm:.12g},0,{-outer_size_mm:.12g},{-outer_size_mm:.12g},{length:.12g}) }}"
        )
    else:
        lines.append(f"    within {{ cylinder(0,0,{length:.12g},{outer_size_mm:.12g},,{length:.12g}) }}")
    lines.extend(
        [
            f"    notin_inside {{ cylinder(0,0,{length+cell_mm:.12g},{float(aperture_radius_mm):.12g},,{length+2*cell_mm:.12g}) }}",
            "  } }",
            "}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--cell-mm", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--segmented-rods", type=Path)
    parser.add_argument("--separate-output-electrode", action="store_true")
    args = parser.parse_args()
    geometry = json.loads(args.geometry.read_text(encoding="utf-8-sig"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    segmented_rods = None
    if args.segmented_rods is not None:
        segmented_rods = json.loads(args.segmented_rods.read_text(encoding="utf-8-sig"))
    args.output.write_text(
        render_gem(geometry, args.cell_mm, segmented_rods, args.separate_output_electrode),
        encoding="ascii",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
