"""Compile the directly mated multipole and oaTOF accelerator into one SIMION PA."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.grounded_shield import (
    render_grounded_circular_to_rectangular_connection,
    require_grounded_potential,
)


MULTIPOLE_SHIELD_ELECTRODE = 9
ACCELERATOR_ELECTRODE_OFFSET = 9
ENTRANCE_REFERENCE_ELECTRODE = 18
ENTRANCE_PLATE_ELECTRODE = 19


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _fmt(value: float) -> str:
    return format(float(value), ".12g")


def _box(
    cx: float, cy: float, cz: float, sx: float, sy: float, sz: float
) -> str:
    return (
        f"centered_box3D({_fmt(cx)},{_fmt(cy)},{_fmt(cz)},"
        f"{_fmt(sx)},{_fmt(sy)},{_fmt(sz)})"
    )


def _require_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), abs_tol=1e-9):
        raise ValueError(f"{label} differs: actual={actual}, expected={expected}")


def compile_frontend(
    upstream: dict[str, Any],
    oatof: dict[str, Any],
    connection: dict[str, Any],
    *,
    cell_mm: float = 0.2,
) -> tuple[str, dict[str, Any]]:
    """Return a composite GEM and its placement/electrode contract."""
    if upstream.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("upstream input is not a multipole resolved design")
    if oatof.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("oaTOF input is not a resolved geometry contract")
    if cell_mm <= 0:
        raise ValueError("single-flight frontend cell size must be positive")
    connector = connection.get("connector", {})
    connector_length = float(connector.get("length_mm", -1.0))
    if connector_length < 0:
        raise ValueError("single-flight grounded connector length must be nonnegative")
    if connector.get("shield_connection_profile_id") != (
        "grounded_circular_to_rectangular_shield_v1"
    ):
        raise ValueError("single-flight frontend requires the published grounded shield connector")
    require_grounded_potential(connector.get("shield_potential_V"), "connection profile shield")
    if connector.get("flange_thickness_binding") != (
        "oatof.geometry_mm.accelerator_shield_wall"
    ):
        raise ValueError("grounded connector flange-thickness binding differs")
    require_grounded_potential(
        upstream["axial_dc"]["upstream_shield_potential_V"], "multipole shield"
    )
    require_grounded_potential(
        upstream["downstream_terminal"]["terminal_potential_V"], "downstream terminal shield"
    )
    require_grounded_potential(oatof["electrodes_V"]["shield"], "oaTOF shield")
    registration = connection["spatial_registration"]
    _require_close(
        registration["expected_gap_mm"], connector_length, "connector gap and length"
    )
    if registration.get("rotation_upstream_to_downstream") != [
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]:
        raise ValueError("single-flight frontend requires the canonical axis mapping")

    terminal = upstream["downstream_terminal"]
    if (
        terminal.get("owner") != "downstream"
        or terminal.get("upstream_terminal_electrode_present") is not False
        or terminal["aperture"].get("shape") != "rectangular"
    ):
        raise ValueError("single-flight frontend requires one downstream-owned terminal")
    aperture = connection["transition_aperture"]
    terminal_width = float(terminal["aperture"]["width_mm"])
    terminal_height = float(terminal["aperture"]["height_mm"])
    aperture_width = float(aperture["full_width_mm"])
    aperture_height = float(aperture["full_height_mm"])
    reduced_aperture = not (
        math.isclose(aperture_width, terminal_width, abs_tol=1e-12, rel_tol=0.0)
        and math.isclose(aperture_height, terminal_height, abs_tol=1e-12, rel_tol=0.0)
    )
    reducer_profile = connector.get("aperture_reducer_profile_id")
    if reduced_aperture:
        if reducer_profile != "grounded_rectangular_aperture_reducer_v1":
            raise ValueError("aperture mismatch requires the governed grounded reducer")
        if aperture_width > terminal_width or aperture_height > terminal_height:
            raise ValueError("grounded aperture reducer cannot enlarge the terminal envelope")
    elif reducer_profile is not None:
        raise ValueError("grounded aperture reducer requires a smaller effective aperture")

    exit_local = float(upstream["interfaces_mm"]["exit"]["handoff_plane_z_mm"])
    exit_global = aperture["center_mm"]
    exit_x, center_y, center_z = map(float, exit_global)
    source_zero_x = float(registration["translation_mm"][0])
    _require_close(
        exit_x - (source_zero_x + exit_local), connector_length, "registered connector gap"
    )
    accelerator = oatof["geometry_derivation"]["accelerator"]
    geometry = oatof["geometry_mm"]
    axis_x = float(oatof["coordinate_convention"]["accelerator_axis_x"])
    axis_y = 0.0
    _require_close(center_z, oatof["particle_source"]["center_z_mm"], "port center z")

    enclosure = upstream["geometry_mm"]["enclosure"]
    rods = upstream["segmentation"]["segmented_rod_array"]["electrodes"]
    segment_count = int(upstream["segmentation"]["segmented_rod_array"]["segment_count"])
    if segment_count != 4 or {int(item["electrode_id"]) for item in rods} != set(range(1, 9)):
        raise ValueError("single-flight frontend currently requires the frozen four-segment octupole map")

    outer_radius = float(enclosure["shield_outer_radius_mm"])
    inner_radius = float(enclosure["shield_inner_radius_mm"])
    source_x_min = source_zero_x + float(enclosure["vacuum_z_min_mm"])
    shield_x_max = source_zero_x + float(terminal["upstream_enclosure_end_plane_z_mm"])
    grid2_z = float(accelerator["canonical_grid2_z_mm"])
    repeller_front_z = float(accelerator["canonical_repeller_z_mm"])
    repeller_thickness = float(geometry["accelerator_repeller_thickness"])
    rear_gap = float(geometry["accelerator_rear_clearance"])
    shield_wall = float(geometry["accelerator_shield_wall"])
    shield_back_z = repeller_front_z - repeller_thickness - rear_gap - shield_wall
    shield_outer_width = 2 * (
        float(geometry["accelerator_bore_half"])
        + float(geometry["accelerator_ring_width"])
        + float(geometry["accelerator_insulation_gap"])
        + shield_wall
    )
    shield_inner_width = shield_outer_width - 2 * shield_wall
    negative_x_face = axis_x - shield_outer_width / 2
    _require_close(negative_x_face, exit_x, "mated shield face")

    x_min = exit_x - math.ceil((exit_x - source_x_min + cell_mm) / cell_mm) * cell_mm
    x_max = axis_x + shield_outer_width / 2 + cell_mm
    y_min = -math.ceil((outer_radius + cell_mm) / cell_mm) * cell_mm
    y_max = -y_min
    physical_z_min = min(center_z - outer_radius, shield_back_z) - cell_mm
    z_min = grid2_z - math.ceil((grid2_z - physical_z_min) / cell_mm) * cell_mm
    z_max = max(center_z + outer_radius, grid2_z) + cell_mm
    nx = math.ceil((x_max - x_min) / cell_mm) + 1
    ny = math.ceil((y_max - y_min) / cell_mm) + 1
    nz = math.ceil((z_max - z_min) / cell_mm) + 1

    lines = [
        "; Generated single-flight multipole + oaTOF accelerator frontend; do not edit.",
        f"; upstream_resolved_sha256={upstream['resolved_sha256']}",
        "; electrode 1..8=multipole rods; 9=all grounded shields and connector; 10..17=oaTOF accelerator; 18=functional entrance-reference sleeve",
        f"pa_define({nx},{ny},{nz},planar,none,electrostatic,,{_fmt(cell_mm)},{_fmt(cell_mm)},{_fmt(cell_mm)},surface=fractional)",
        f"locate({_fmt(-x_min)},{_fmt(-y_min)},{_fmt(-z_min)}) {{",
    ]
    for rod in rods:
        z_min_local = float(rod["z_min_mm"])
        z_max_local = float(rod["z_max_mm"])
        endpoint_x = source_zero_x + z_max_local
        rod_y = center_y + float(rod["center_x_mm"])
        rod_z = center_z + float(rod["center_y_mm"])
        lines.append(
            f"  e({int(rod['electrode_id'])}) {{ fill {{ within {{ locate("
            f"{_fmt(endpoint_x)},{_fmt(rod_y)},{_fmt(rod_z)},1,90) {{ cylinder(0,0,0,"
            f"{_fmt(rod['radius_mm'])},,{_fmt(z_max_local-z_min_local)}) }} }} }} }}"
        )

    shield_length = shield_x_max - source_x_min
    lines.extend(
        [
            f"  e({MULTIPOLE_SHIELD_ELECTRODE}) {{ fill {{",
            f"    within {{ locate({_fmt(shield_x_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(shield_length)}) }} }}",
            f"    notin_inside {{ locate({_fmt(shield_x_max+cell_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(inner_radius)},,{_fmt(shield_length+2*cell_mm)}) }} }}",
            "  } }",
        ]
    )
    entrance_min = source_zero_x + float(enclosure["entrance_outer_endcap_upstream_face_z_mm"])
    entrance_max = source_zero_x + float(enclosure["entrance_outer_endcap_downstream_face_z_mm"])
    entrance_radius = float(upstream["interfaces_mm"]["entrance"]["aperture_radius_mm"])
    entrance_plate_min = source_zero_x + float(
        upstream["interfaces_mm"]["entrance"]["aperture_plate_upstream_face_z_mm"]
    )
    entrance_plate_max = source_zero_x + float(
        upstream["interfaces_mm"]["entrance"]["aperture_plate_downstream_face_z_mm"]
    )
    sleeve = upstream["axial_dc"]["entrance_reference_sleeve"]
    sleeve_outer = float(sleeve["outer_radius_mm"])
    sleeve_inner = float(sleeve["inner_radius_mm"])
    insulated_radius = sleeve_outer + float(sleeve["minimum_insulation_gap_mm"])
    sleeve_min = source_zero_x + float(sleeve["upstream_face_z_mm"])
    sleeve_max = source_zero_x + float(sleeve["downstream_face_z_mm"])
    lines.extend(
        [
            f"  e({MULTIPOLE_SHIELD_ELECTRODE}) {{ fill {{",
            f"    within {{ locate({_fmt(entrance_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(entrance_max-entrance_min)}) }} }}",
            f"    notin_inside {{ locate({_fmt(entrance_max+cell_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(insulated_radius)},,{_fmt(entrance_max-entrance_min+2*cell_mm)}) }} }}",
            "  } }",
            f"  e({ENTRANCE_PLATE_ELECTRODE}) {{ fill {{",
            f"    within {{ locate({_fmt(entrance_plate_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(entrance_plate_max-entrance_plate_min)}) }} }}",
            f"    notin_inside {{ locate({_fmt(entrance_plate_max+cell_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(entrance_radius)},,{_fmt(entrance_plate_max-entrance_plate_min+2*cell_mm)}) }} }}",
            "  } }",
            "  ; Functional source-reference sleeve; this is not a shield electrode.",
            f"  e({ENTRANCE_REFERENCE_ELECTRODE}) {{ fill {{",
            f"    within {{ locate({_fmt(sleeve_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(sleeve_outer)},,{_fmt(sleeve_max-sleeve_min)}) }} }}",
            f"    notin_inside {{ locate({_fmt(sleeve_max+cell_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(sleeve_inner)},,{_fmt(sleeve_max-sleeve_min+2*cell_mm)}) }} }}",
            "  } }",
        ]
    )

    shield_center_z = (shield_back_z + grid2_z) / 2
    shield_span_z = grid2_z - shield_back_z
    port_width = float(aperture["full_width_mm"])
    port_height = float(aperture["full_height_mm"])
    rod_end_x = source_zero_x + max(float(item["z_max_mm"]) for item in rods)
    _require_close(
        exit_x - rod_end_x,
        terminal["rod_end_clearance_mm"] + connector_length,
        "rod-to-shield distance",
    )
    junction_guard_length = exit_x - shield_x_max
    _require_close(
        junction_guard_length,
        terminal["upstream_enclosure_to_terminal_clearance_mm"] + connector_length,
        "grounded shield sleeve",
    )
    connection_lines, connection_contract = render_grounded_circular_to_rectangular_connection(
        electrode_id=MULTIPOLE_SHIELD_ELECTRODE,
        sleeve_x_min_mm=shield_x_max,
        sleeve_x_max_mm=exit_x,
        flange_thickness_mm=shield_wall,
        center_y_mm=center_y,
        center_z_mm=center_z,
        outer_radius_mm=outer_radius,
        inner_radius_mm=inner_radius,
        aperture_width_mm=port_width,
        aperture_height_mm=port_height,
        cell_mm=cell_mm,
        pa_origin_y_mm=y_min,
        pa_origin_z_mm=z_min,
    )
    lines.extend(connection_lines)
    aperture_discretization = connection_contract["aperture_discretization"]
    numerical_port_width = float(aperture_discretization["numerical_carve_width_mm"])
    numerical_port_height = float(aperture_discretization["numerical_carve_height_mm"])
    lines.extend(
        [
            f"  e({MULTIPOLE_SHIELD_ELECTRODE}) {{ fill {{",
            f"    within {{ {_box(axis_x, axis_y, shield_center_z, shield_outer_width, shield_outer_width, shield_span_z)} }}",
            f"    notin {{ {_box(axis_x, axis_y, shield_center_z, shield_inner_width, shield_inner_width, shield_span_z)} }}",
            f"    notin_inside_or_on {{ {_box(negative_x_face+shield_wall/2, center_y, center_z, shield_wall+2*cell_mm, numerical_port_width, numerical_port_height)} }}",
            "  } }",
            f"  e({MULTIPOLE_SHIELD_ELECTRODE}) {{ fill {{ within {{ {_box(axis_x, axis_y, shield_back_z+shield_wall/2, shield_outer_width, shield_outer_width, shield_wall)} }} }} }}",
        ]
    )

    electrode_width = 2 * (
        float(geometry["accelerator_bore_half"])
        + float(geometry["accelerator_ring_width"])
    )
    bore_width = 2 * float(geometry["accelerator_bore_half"])
    grid1_z = float(accelerator["canonical_grid1_z_mm"])
    stage2 = float(accelerator["d2_mm"])
    ring_count = int(oatof["rings"]["accelerator_count"])
    ring_pitch = stage2 / (ring_count + 1)
    ring_thickness = float(geometry["accelerator_ring_thickness"])
    lines.append(
        f"  e({ACCELERATOR_ELECTRODE_OFFSET+1}) {{ fill {{ within {{ {_box(axis_x,axis_y,repeller_front_z-repeller_thickness/2,electrode_width,electrode_width,repeller_thickness)} }} }} }}"
    )
    lines.append(
        f"  e({ACCELERATOR_ELECTRODE_OFFSET+2}) {{ fill {{ within {{ {_box(axis_x,axis_y,grid1_z,electrode_width,electrode_width,cell_mm)} }} }} }}"
    )
    for ring_index in range(1, ring_count + 1):
        ring_z = grid1_z + ring_index * ring_pitch
        lines.extend(
            [
                f"  e({ACCELERATOR_ELECTRODE_OFFSET+2+ring_index}) {{ fill {{",
                f"    within {{ {_box(axis_x,axis_y,ring_z,electrode_width,electrode_width,ring_thickness)} }}",
                f"    notin {{ {_box(axis_x,axis_y,ring_z,bore_width,bore_width,ring_thickness+cell_mm)} }}",
                "  } }",
            ]
        )
    lines.append(
        f"  e({ACCELERATOR_ELECTRODE_OFFSET+3+ring_count}) {{ fill {{ within {{ {_box(axis_x,axis_y,grid2_z,shield_inner_width,shield_inner_width,cell_mm)} }} }} }}"
    )
    lines.extend(["}", ""])

    contract = {
        "schema_version": 1,
        "role": "rf_oatof_simion_single_flight_frontend_contract",
        "frame_id": "oatof_global",
        "cell_mm_xyz": {"x": cell_mm, "y": cell_mm, "z": cell_mm},
        "dimensions": {"nx": nx, "ny": ny, "nz": nz},
        "instance_origin_mm": {"x": x_min, "y": y_min, "z": z_min},
        "source_exit_center_mm": {"x": exit_x, "y": center_y, "z": center_z},
        "junction_enclosure": {
            "rod_end_to_accelerator_shield_mm": round(exit_x - rod_end_x, 12),
            "profile_gap_mm": round(connector_length, 12),
            **connection_contract,
        },
        "aperture": {"shape": "rectangular", "width_mm": port_width, "height_mm": port_height},
        "aperture_reducer": {
            "present": reduced_aperture,
            "profile_id": reducer_profile,
            "potential_V": 0.0,
            "terminal_envelope_width_mm": terminal_width,
            "terminal_envelope_height_mm": terminal_height,
        },
        "electrodes": {
            "multipole_rod_ids": list(range(1, 9)),
            "grounded_shield_id": MULTIPOLE_SHIELD_ELECTRODE,
            "accelerator_repeller_id": 10,
            "accelerator_grid1_id": 11,
            "accelerator_ring_ids": list(range(12, 17)),
            "accelerator_grid2_id": 17,
            "entrance_reference_sleeve_id": ENTRANCE_REFERENCE_ELECTRODE,
            "entrance_plate_id": ENTRANCE_PLATE_ELECTRODE,
        },
        "entrance_reference_sleeve": dict(sleeve),
    }
    return "\n".join(lines), contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--oatof", required=True, type=Path)
    parser.add_argument("--connection", required=True, type=Path)
    parser.add_argument("--gem", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--cell-mm", type=float, default=0.2)
    args = parser.parse_args()
    gem, contract = compile_frontend(
        _load(args.upstream), _load(args.oatof), _load(args.connection), cell_mm=args.cell_mm
    )
    args.gem.parent.mkdir(parents=True, exist_ok=True)
    args.contract.parent.mkdir(parents=True, exist_ok=True)
    args.gem.write_text(gem, encoding="utf-8", newline="\n")
    args.contract.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"SINGLE_FLIGHT_FRONTEND=PASS GEM={args.gem} CONTRACT={args.contract}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
