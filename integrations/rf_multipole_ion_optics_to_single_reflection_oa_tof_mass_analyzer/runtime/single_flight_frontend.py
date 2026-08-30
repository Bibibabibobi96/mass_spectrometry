"""Compile the directly mated multipole and oaTOF accelerator into one SIMION PA."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.grounded_shield import (
    render_grounded_circular_to_rectangular_connection,
    render_fixed_upstream_shield_connector,
    require_grounded_potential,
)
from common.multipole.simion_geometry import (
    render_axis_mapped_segmented_rod_array_gem,
    segmented_rod_electrode_ids,
)
from common.simion.aperture import resolve_rectangular_aperture_discretization
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import (
    ACCELERATOR_RING_COUNT,
    FRONTEND_ELECTRODES,
    ROD_ELECTRODE_IDS,
    THREE_ZONE_FRONTEND_ELECTRODES,
    require_published_frontend_electrodes,
    resolve_frontend_electrode_topology,
)



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


def _cylinder_z(cx: float, cy: float, cz: float, radius: float, length: float) -> str:
    """Return a z-axis circular electrode primitive in the planar frontend PA."""

    return (
        f"locate({_fmt(cx)},{_fmt(cy)},{_fmt(cz)}) {{ "
        f"cylinder(0,0,0,{_fmt(radius)},,{_fmt(length)}) }}"
    )


def _require_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), abs_tol=1e-9):
        raise ValueError(f"{label} differs: actual={actual}, expected={expected}")


def resolve_positive_gap_domain_split(
    frontend: dict[str, Any], connection: dict[str, Any]
) -> dict[str, float] | None:
    """Partition a long grounded connector into two disjoint fine domains.

    The upstream fine PA ends 10 mm after the perforated connector terminal.
    The accelerator fine PA begins 10 mm upstream of the accelerator aperture.
    The intervening grounded sleeve belongs only to the common coarse bridge
    PA.  Fine PA fields never overlap and therefore need no runtime handoff
    selector or field superposition rule.
    """

    connector = connection.get("connector")
    if not isinstance(connector, dict):
        raise ValueError("domain split requires a connector contract")
    length_mm = float(connector.get("length_mm", float("nan")))
    if not math.isfinite(length_mm) or length_mm < 0.0:
        raise ValueError("connector length must be finite and nonnegative")
    if length_mm == 0.0:
        return None
    minimum_length_mm = 50.0
    endpoint_guard_mm = 10.0
    if length_mm < minimum_length_mm:
        return None
    source_exit = frontend.get("source_exit_center_mm")
    if not isinstance(source_exit, dict):
        raise ValueError("domain split frontend source exit is missing")
    exit_x = float(source_exit.get("x", float("nan")))
    if not math.isfinite(exit_x):
        raise ValueError("domain split source exit x coordinate is invalid")
    terminal_end_x = exit_x - length_mm
    upstream_end_x = terminal_end_x + endpoint_guard_mm
    accelerator_start_x = exit_x - endpoint_guard_mm
    if upstream_end_x >= accelerator_start_x:
        raise ValueError("domain split has no coarse grounded-sleeve interval")
    return {
        "connector_length_mm": length_mm,
        "terminal_end_x_mm": terminal_end_x,
        "upstream_end_x_mm": upstream_end_x,
        "accelerator_start_x_mm": accelerator_start_x,
        "coarse_sleeve_x_min_mm": upstream_end_x,
        "coarse_sleeve_x_max_mm": accelerator_start_x,
        "endpoint_guard_mm": endpoint_guard_mm,
    }


def _electrode_namespace(
    rod_ids: list[int], ring_count: int, *, three_zone: bool = False
) -> dict[str, Any]:
    if rod_ids != list(ROD_ELECTRODE_IDS):
        raise ValueError(
            "single-flight runtime requires the published rod PA basis IDs 1..8"
        )
    if ring_count != ACCELERATOR_RING_COUNT:
        raise ValueError("single-flight runtime requires exactly five accelerator rings")
    result = {
        key: list(value) if isinstance(value, list) else value
        for key, value in (
            THREE_ZONE_FRONTEND_ELECTRODES if three_zone else FRONTEND_ELECTRODES
        ).items()
    }
    require_published_frontend_electrodes(result)
    return result


def _render_accelerator_local_geometry(
    geometry: dict[str, Any],
    *,
    cell_x_mm: float,
    cell_z_mm: float,
    electrodes: dict[str, Any],
    render_intermediate2_sheet: bool = False,
    render_region: str = "whole_accelerator",
) -> list[str]:
    """Render accelerator geometry with native one-row ideal grids.

    SIMION treats a zero-grid-unit-thick electrode as one electrode-point row:
    it contributes to Refine but particles pass through it. A real wire mesh
    is a different physical profile and must not be routed through this helper.
    """
    axis_x = float(geometry["axis_x_mm"])
    axis_y = float(geometry["axis_y_mm"])
    grounded_shield_id = int(electrodes["grounded_shield_id"])
    repeller_id = int(electrodes["accelerator_repeller_id"])
    grid1_id = int(electrodes["accelerator_grid1_id"])
    ring_ids = [int(value) for value in electrodes["accelerator_ring_ids"]]
    grid2_id = int(electrodes["accelerator_grid2_id"])
    cross_section = str(geometry.get("cross_section", "square"))
    if cross_section not in {"square", "cylindrical"}:
        raise ValueError("accelerator cross section is unsupported")
    if render_region not in {"whole_accelerator", "entrance", "intermediate2"}:
        raise ValueError("accelerator local geometry region is unsupported")
    include_entrance = render_region in {"whole_accelerator", "entrance"}
    include_downstream = render_region == "whole_accelerator"
    if cross_section == "square":
        entrance_lines = [
        f"  e({grounded_shield_id}) {{ fill {{",
        f"    within {{ {_box(axis_x, axis_y, float(geometry['shield_center_z_mm']), float(geometry['shield_outer_width_mm']), float(geometry['shield_outer_width_mm']), float(geometry['shield_span_z_mm']))} }}",
        f"    notin {{ {_box(axis_x, axis_y, float(geometry['shield_center_z_mm']), float(geometry['shield_inner_width_mm']), float(geometry['shield_inner_width_mm']), float(geometry['shield_span_z_mm']))} }}",
        f"    notin_inside_or_on {{ {_box(float(geometry['negative_x_face_mm'])+float(geometry['shield_wall_mm'])/2, float(geometry['port_center_y_mm']), float(geometry['port_center_z_mm']), float(geometry['shield_wall_mm'])+2*cell_x_mm, float(geometry['numerical_port_width_mm']), float(geometry['numerical_port_height_mm']))} }}",
        "  } }",
        f"  e({grounded_shield_id}) {{ fill {{ within {{ {_box(axis_x, axis_y, float(geometry['shield_back_z_mm'])+float(geometry['shield_wall_mm'])/2, float(geometry['shield_outer_width_mm']), float(geometry['shield_outer_width_mm']), float(geometry['shield_wall_mm']))} }} }} }}",
        f"  e({repeller_id}) {{ fill {{ within {{ {_box(axis_x,axis_y,float(geometry['repeller_front_z_mm'])-float(geometry['repeller_thickness_mm'])/2,float(geometry['electrode_width_mm']),float(geometry['electrode_width_mm']),float(geometry['repeller_thickness_mm']))} }} }} }}",
        "  ; Zero-grid-unit sheets are one-row ideal 100% transmission grids.",
        f"  e({grid1_id}) {{ fill {{ within {{ {_box(axis_x,axis_y,float(geometry['grid1_z_mm']),float(geometry['electrode_width_mm']),float(geometry['electrode_width_mm']),0.0)} }} }} }}",
        ]
        plate = lambda z, width: _box(axis_x, axis_y, z, width, width, 0.0)
        ring_outer = lambda z: _box(
            axis_x, axis_y, z, float(geometry["electrode_width_mm"]),
            float(geometry["electrode_width_mm"]), float(geometry["ring_thickness_mm"])
        )
        ring_inner = lambda z: _box(
            axis_x, axis_y, z, float(geometry["bore_width_mm"]),
            float(geometry["bore_width_mm"]), float(geometry["ring_thickness_mm"]) + cell_z_mm
        )
    else:
        outer_radius = float(geometry["shield_outer_width_mm"]) / 2.0
        inner_radius = float(geometry["shield_inner_width_mm"]) / 2.0
        electrode_radius = float(geometry["electrode_width_mm"]) / 2.0
        bore_radius = float(geometry["bore_width_mm"]) / 2.0
        entrance_lines = [
            f"  e({grounded_shield_id}) {{ fill {{",
            f"    within {{ {_cylinder_z(axis_x, axis_y, float(geometry['shield_center_z_mm']), outer_radius, float(geometry['shield_span_z_mm']))} }}",
            f"    notin {{ {_cylinder_z(axis_x, axis_y, float(geometry['shield_center_z_mm']), inner_radius, float(geometry['shield_span_z_mm']) + 2*cell_z_mm)} }}",
            f"    notin_inside_or_on {{ {_box(float(geometry['negative_x_face_mm'])+float(geometry['shield_wall_mm'])/2, float(geometry['port_center_y_mm']), float(geometry['port_center_z_mm']), float(geometry['shield_wall_mm'])+2*cell_x_mm, float(geometry['numerical_port_width_mm']), float(geometry['numerical_port_height_mm']))} }}",
            "  } }",
            f"  e({grounded_shield_id}) {{ fill {{ within {{ {_cylinder_z(axis_x, axis_y, float(geometry['shield_back_z_mm'])+float(geometry['shield_wall_mm'])/2, outer_radius, float(geometry['shield_wall_mm']))} }} }} }}",
            f"  e({repeller_id}) {{ fill {{ within {{ {_cylinder_z(axis_x, axis_y, float(geometry['repeller_front_z_mm'])-float(geometry['repeller_thickness_mm'])/2, electrode_radius, float(geometry['repeller_thickness_mm']))} }} }} }}",
            "  ; Zero-grid-unit circular sheets are one-row ideal 100% transmission grids.",
            f"  e({grid1_id}) {{ fill {{ within {{ {_cylinder_z(axis_x,axis_y,float(geometry['grid1_z_mm']),electrode_radius,0.0)} }} }} }}",
        ]
        plate = lambda z, width: _cylinder_z(axis_x, axis_y, z, width / 2.0, 0.0)
        ring_outer = lambda z: _cylinder_z(axis_x, axis_y, z, electrode_radius, float(geometry["ring_thickness_mm"]))
        ring_inner = lambda z: _cylinder_z(axis_x, axis_y, z, bore_radius, float(geometry["ring_thickness_mm"]) + cell_z_mm)
    lines = entrance_lines if include_entrance else []
    intermediate2_id = electrodes.get("accelerator_intermediate2_id")
    if intermediate2_id is not None and render_intermediate2_sheet:
        lines.append(
            f"  e({int(intermediate2_id)}) {{ fill {{ within {{ {plate(float(geometry['intermediate2_z_mm']), float(geometry['electrode_width_mm']))} }} }} }}"
        )
    ring_count = int(geometry["ring_count"])
    ring_z_mm = geometry.get("ring_z_mm")
    if ring_z_mm is None:
        ring_pitch = float(geometry["ring_pitch_mm"])
        ring_z_mm = [
            float(geometry["grid1_z_mm"]) + index * ring_pitch
            for index in range(1, ring_count + 1)
        ]
    if not isinstance(ring_z_mm, list) or len(ring_z_mm) != ring_count:
        raise ValueError("accelerator ring_z_mm must match ring_count")
    if include_downstream:
        for ring_index in range(1, ring_count + 1):
            ring_z = float(ring_z_mm[ring_index - 1])
            lines.extend(
                [
                    f"  e({ring_ids[ring_index-1]}) {{ fill {{",
                    f"    within {{ {ring_outer(ring_z)} }}",
                    f"    notin {{ {ring_inner(ring_z)} }}",
                    "  } }",
                ]
            )
        lines.append(
            f"  e({grid2_id}) {{ fill {{ within {{ {plate(float(geometry['grid2_z_mm']), float(geometry['shield_inner_width_mm']))} }} }} }}"
        )
    return lines


def _aligned_index(value: float, origin: float, cell: float, label: str) -> int:
    coordinate = (value - origin) / cell
    nearest = round(coordinate)
    if not math.isclose(coordinate, nearest, abs_tol=1e-8):
        raise ValueError(f"accelerator overlay {label} is not aligned to the coarse grid")
    return int(nearest)


def _outward_aligned_boundary(
    value: float, origin: float, cell: float, *, side: str
) -> float:
    """Expand one overlay boundary to the enclosing coarse-PA node."""
    coordinate = (value - origin) / cell
    nearest = round(coordinate)
    if math.isclose(coordinate, nearest, abs_tol=1e-8):
        return value
    elif side == "min":
        index = math.floor(coordinate)
    elif side == "max":
        index = math.ceil(coordinate)
    else:
        raise ValueError("accelerator overlay boundary side is invalid")
    return origin + index * cell


def compile_accelerator_overlay(
    frontend: dict[str, Any],
    *,
    cell_mm_xyz: dict[str, float],
    region_id: str = "whole_accelerator",
    intermediate_half_span_mm: float = 2.0,
) -> tuple[str, dict[str, Any]]:
    """Compile one boundary-coupled accelerator PA from the coarse frontend.

    ``whole_accelerator`` preserves the historical five-instance overlay.
    ``entrance`` covers the shield port, repeller and first ideal grid; and
    ``intermediate2`` covers only the three-zone zero-thickness grid.  The
    latter two profiles are deliberately separate because a rectangular PA
    cannot represent two distant fine-mesh islands without also refining the
    complete interval between them.
    """
    if frontend.get("role") != "rf_oatof_simion_single_flight_frontend_contract":
        raise ValueError("accelerator overlay requires a compiled frontend contract")
    if set(cell_mm_xyz) != {"x", "y", "z"}:
        raise ValueError("accelerator overlay cell_mm_xyz must contain exactly x, y and z")
    fine = {axis: float(cell_mm_xyz[axis]) for axis in ("x", "y", "z")}
    coarse = {axis: float(frontend["cell_mm_xyz"][axis]) for axis in ("x", "y", "z")}
    if not all(math.isfinite(value) and value > 0 for value in fine.values()):
        raise ValueError("accelerator overlay cell sizes must be finite and positive")
    if not math.isclose(coarse["x"], coarse["y"], abs_tol=1e-12):
        raise ValueError(
            "accelerator overlay requires transverse x-y symmetry in the coarse frontend PA"
        )
    if not math.isclose(fine["x"], fine["y"], abs_tol=1e-12):
        raise ValueError("accelerator overlay must preserve x-y transverse grid symmetry")
    for axis in ("x", "y", "z"):
        ratio = coarse[axis] / fine[axis]
        if ratio < 1 or not math.isclose(ratio, round(ratio), abs_tol=1e-12):
            raise ValueError(
                "accelerator overlay cells must be integer refinements of the governed coarse grid"
            )
    if region_id not in {"whole_accelerator", "entrance", "intermediate2"}:
        raise ValueError("accelerator overlay region_id is unsupported")
    if not math.isfinite(intermediate_half_span_mm) or intermediate_half_span_mm <= 0:
        raise ValueError("accelerator intermediate overlay half span must be finite and positive")

    geometry = dict(frontend["accelerator_local_region"])
    electrodes = dict(frontend["electrodes"])
    topology = resolve_frontend_electrode_topology(electrodes)
    origin = frontend["instance_origin_mm"]
    half_width = float(geometry["shield_outer_width_mm"]) / 2
    if region_id == "whole_accelerator":
        z_min = float(geometry["shield_back_z_mm"]) - coarse["z"]
        # Keep one non-electrode coarse cell beyond grid2 before the outer
        # Dirichlet face; the overlay is suppressed in the outer guard cell.
        z_max = float(geometry["grid2_z_mm"]) + 2 * coarse["z"]
    elif region_id == "entrance":
        z_min = float(geometry["shield_back_z_mm"]) - coarse["z"]
        # One guard cell after grid1 makes the interface external to the
        # zero-thickness electrode itself.
        z_max = float(geometry["grid1_z_mm"]) + 2 * coarse["z"]
    else:
        if topology["topology_id"] != "three_zone_frontend_v1":
            raise ValueError("intermediate2 overlay requires the three-zone frontend")
        intermediate2_z = float(geometry["intermediate2_z_mm"])
        z_min = intermediate2_z - intermediate_half_span_mm
        z_max = intermediate2_z + intermediate_half_span_mm
    bounds = {
        "x_min": float(geometry["negative_x_face_mm"]),
        "x_max": float(geometry["axis_x_mm"]) + half_width + coarse["x"],
        "y_min": float(geometry["axis_y_mm"]) - half_width - coarse["y"],
        "y_max": float(geometry["axis_y_mm"]) + half_width + coarse["y"],
        "z_min": z_min,
        "z_max": z_max,
    }
    for axis in ("x", "y", "z"):
        bounds[f"{axis}_min"] = _outward_aligned_boundary(
            bounds[f"{axis}_min"], float(origin[axis]), coarse[axis], side="min"
        )
        bounds[f"{axis}_max"] = _outward_aligned_boundary(
            bounds[f"{axis}_max"], float(origin[axis]), coarse[axis], side="max"
        )
    for axis in ("x", "y", "z"):
        _aligned_index(bounds[f"{axis}_min"], float(origin[axis]), coarse[axis], f"{axis}_min")
        _aligned_index(bounds[f"{axis}_max"], float(origin[axis]), coarse[axis], f"{axis}_max")
    dimensions: dict[str, int] = {}
    for axis in ("x", "y", "z"):
        span = bounds[f"{axis}_max"] - bounds[f"{axis}_min"]
        coordinate = span / fine[axis]
        nearest = round(coordinate)
        if not math.isclose(coordinate, nearest, abs_tol=1e-8):
            raise ValueError(f"accelerator overlay {axis} span is not aligned to the fine grid")
        dimensions[f"n{axis}"] = int(nearest) + 1
    if (
        topology["topology_id"] == "three_zone_frontend_v1"
        and region_id in {"whole_accelerator", "intermediate2"}
    ):
        _aligned_index(
            float(geometry["intermediate2_z_mm"]),
            bounds["z_min"],
            fine["z"],
            "intermediate2_z_mm",
        )

    missing_physical_electrodes = (
        [
            *electrodes["multipole_rod_ids"],
            electrodes["entrance_reference_sleeve_id"],
        ]
        if region_id == "whole_accelerator"
        else list(topology["basis_electrode_ids"])
    )
    boundary_sentinels = [
        f"  e({electrode_id}) {{ fill {{ within {{ "
        f"{_box(bounds['x_min'], bounds['y_min'] + offset * fine['y'], bounds['z_min'], fine['x']/2, fine['y']/2, fine['z']/2)}"
        " } } }"
        for offset, electrode_id in enumerate(missing_physical_electrodes, start=1)
    ]
    lines = [
        "; Generated boundary-coupled accelerator overlay; do not edit.",
        "; outer faces are replaced by coarse-PA Dirichlet basis values before Refine",
        f"pa_define({dimensions['nx']},{dimensions['ny']},{dimensions['nz']},planar,none,electrostatic,,{_fmt(fine['x'])},{_fmt(fine['y'])},{_fmt(fine['z'])},surface=none)",
        f"locate({_fmt(-bounds['x_min'])},{_fmt(-bounds['y_min'])},{_fmt(-bounds['z_min'])}) {{",
        *_render_accelerator_local_geometry(
            geometry,
            cell_x_mm=fine["x"],
            cell_z_mm=fine["z"],
            electrodes=electrodes,
            render_intermediate2_sheet=region_id in {"whole_accelerator", "intermediate2"},
            render_region=region_id,
        ),
        "  ; Boundary-only sentinels initialize every required frontend PA basis.",
        *boundary_sentinels,
        f"  e({electrodes['entrance_plate_id']}) {{ fill {{ within {{ {_box(bounds['x_min'],bounds['y_min'],bounds['z_min'],fine['x']/2,fine['y']/2,fine['z']/2)} }} }} }}",
        "}",
        "",
    ]
    contract = {
        "schema_version": 1,
        "role": "rf_oatof_simion_accelerator_overlay_contract",
        "region_id": region_id,
        "frame_id": frontend["frame_id"],
        "cell_mm_xyz": fine,
        "dimensions": dimensions,
        "instance_origin_mm": {
            "x": bounds["x_min"],
            "y": bounds["y_min"],
            "z": bounds["z_min"],
        },
        "instance_bounds_mm": bounds,
        "active_bounds_mm": {
            f"{axis}_{side}": bounds[f"{axis}_{side}"]
            + (coarse[axis] if side == "min" else -coarse[axis])
            for axis in ("x", "y", "z")
            for side in ("min", "max")
        },
        "boundary_condition": {
            "mode": "coarse_electrode_basis_dirichlet_v1",
            "faces": ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"],
            "coarse_frontend_role": frontend["role"],
            "basis_electrode_ids": list(topology["basis_electrode_ids"]),
        },
        "electrodes": dict(frontend["electrodes"]),
        "boundary_family_sentinel_electrode_ids": [
            *missing_physical_electrodes,
            electrodes["entrance_plate_id"],
        ],
    }
    return "\n".join(lines), contract


def compile_accelerator_main(
    frontend: dict[str, Any],
    oatof: dict[str, Any],
    *,
    cell_mm_xyz: dict[str, float],
    connection: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Compile the local physical geometry for a standalone three-zone PA.

    The resulting GEM is intentionally *not* an independently valid field
    solution at the side-port boundary.  A future runtime must initialize its
    complete electrode basis from a matching coarse bridge PA before Refine;
    this compiler records that requirement rather than silently treating the
    isolated PA as a replacement for the coupled frontend field.
    """
    if frontend.get("role") != "rf_oatof_simion_single_flight_frontend_contract":
        raise ValueError("accelerator main requires a compiled frontend contract")
    if set(cell_mm_xyz) != {"x", "y", "z"}:
        raise ValueError("accelerator main cell_mm_xyz must contain exactly x, y and z")
    cells = {axis: float(cell_mm_xyz[axis]) for axis in ("x", "y", "z")}
    if not all(math.isfinite(value) and value > 0 for value in cells.values()):
        raise ValueError("accelerator main cell sizes must be finite and positive")
    if not math.isclose(cells["x"], cells["y"], abs_tol=1e-12):
        raise ValueError("accelerator main requires transverse x-y grid symmetry")

    topology = oatof.get("accelerator_topology")
    if not isinstance(topology, dict) or frontend.get("accelerator_topology_id") is None:
        raise ValueError("accelerator main requires a three-zone accelerator topology")
    required_plane_roles = ("repeller", "intermediate1", "intermediate2", "exit")
    planes = topology.get("planes_global_z_mm")
    potentials = topology.get("potentials_v")
    if not isinstance(planes, dict) or not isinstance(potentials, dict) or (
        set(planes) != set(required_plane_roles)
        or set(potentials) != set(required_plane_roles)
    ):
        raise ValueError("accelerator main requires exactly four named planes and potentials")
    plane_values = {role: float(planes[role]) for role in required_plane_roles}
    potential_values = {role: float(potentials[role]) for role in required_plane_roles}
    if not all(math.isfinite(value) for value in (*plane_values.values(), *potential_values.values())):
        raise ValueError("accelerator main planes and potentials must be finite")
    if not all(
        plane_values[left] < plane_values[right]
        for left, right in zip(required_plane_roles, required_plane_roles[1:])
    ):
        raise ValueError("accelerator main planes must be strictly increasing")
    if not all(
        potential_values[left] > potential_values[right]
        for left, right in zip(required_plane_roles, required_plane_roles[1:])
    ):
        raise ValueError("accelerator main potentials must be strictly decreasing")

    geometry = dict(frontend.get("accelerator_local_region", {}))
    electrodes = dict(frontend.get("electrodes", {}))
    electrode_topology = resolve_frontend_electrode_topology(electrodes)
    if electrode_topology["topology_id"] != "three_zone_frontend_v1":
        raise ValueError("accelerator main requires the published three-zone electrode topology")
    for role, field in (
        ("repeller", "repeller_front_z_mm"),
        ("intermediate1", "grid1_z_mm"),
        ("intermediate2", "intermediate2_z_mm"),
        ("exit", "grid2_z_mm"),
    ):
        if field not in geometry:
            raise ValueError(f"accelerator main geometry is missing {field}")
        _require_close(float(geometry[field]), plane_values[role], f"accelerator main {role} plane")

    placement = geometry.get("ring_placement")
    ring_z_mm = geometry.get("ring_z_mm")
    if (
        not isinstance(placement, dict)
        or placement.get("policy_id") != "three_zone_zonewise_equal_subdivision_1p4_v1"
        or not isinstance(placement.get("zone_ring_counts"), dict)
        or not isinstance(ring_z_mm, list)
    ):
        raise ValueError("accelerator main requires the declared three-zone ring placement")
    zone_ring_counts = placement["zone_ring_counts"]
    if set(zone_ring_counts) != {"zone2", "zone3"} or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in zone_ring_counts.values()
    ):
        raise ValueError("accelerator main ring placement counts are invalid")
    zone2_ring_count = zone_ring_counts["zone2"]
    zone3_ring_count = zone_ring_counts["zone3"]
    if len(ring_z_mm) != zone2_ring_count + zone3_ring_count:
        raise ValueError("accelerator main ring placement count differs")
    expected_ring_z = [
        plane_values["intermediate1"] + (index + .5) * (
            plane_values["intermediate2"] - plane_values["intermediate1"]
        ) / zone2_ring_count
        for index in range(zone2_ring_count)
    ] + [
        *[
            plane_values["intermediate2"]
            + index * (plane_values["exit"] - plane_values["intermediate2"]) / (zone3_ring_count + 1)
            for index in range(1, zone3_ring_count + 1)
        ],
    ]
    resolved_ring_z = [float(value) for value in ring_z_mm]
    if any(
        not math.isfinite(actual) or not math.isclose(actual, expected, abs_tol=1e-9)
        for actual, expected in zip(resolved_ring_z, expected_ring_z)
    ):
        raise ValueError("accelerator main ring placement differs from the declared policy")

    requested_realization = (
        oatof.get("geometry_derivation", {})
        .get("accelerator", {})
        .get("realization_id")
    )
    expected_cross_section = {
        "square_3d": "square",
        "cylindrical_3d": "cylindrical",
    }.get(requested_realization)
    if expected_cross_section is None or geometry.get("cross_section") != expected_cross_section:
        raise ValueError("accelerator main realization differs from the compiled frontend")
    cylindrical_sideport = frontend.get("cylindrical_sideport")
    if expected_cross_section == "cylindrical":
        if not isinstance(cylindrical_sideport, dict) or cylindrical_sideport.get("profile_id") != (
            "grounded_circular_to_cylindrical_sideport_v1"
        ):
            raise ValueError("accelerator main requires the cylindrical side-port collar contract")
    elif cylindrical_sideport is not None:
        raise ValueError("square accelerator main must not receive a cylindrical side-port collar")

    split = (
        resolve_positive_gap_domain_split(frontend, connection)
        if connection is not None
        else None
    )
    half_width = float(geometry["shield_outer_width_mm"]) / 2.0
    bridge_cells = frontend.get("cell_mm_xyz")
    if not isinstance(bridge_cells, dict) or set(bridge_cells) != {"x", "y", "z"}:
        raise ValueError("accelerator main requires the governed bridge cell declaration")
    bridge_x_margin = float(bridge_cells["x"])
    bridge_y_margin = float(bridge_cells["y"])
    if not all(math.isfinite(value) and value > 0 for value in (bridge_x_margin, bridge_y_margin)):
        raise ValueError("accelerator main bridge cells must be finite and positive")
    physical_z_min = float(geometry["shield_back_z_mm"]) - cells["z"]
    z_min = plane_values["exit"] - math.ceil(
        (plane_values["exit"] - physical_z_min) / cells["z"]
    ) * cells["z"]
    z_max = plane_values["exit"] + 2.0 * cells["z"]
    x_min = (
        float(split["accelerator_start_x_mm"])
        if split is not None
        else float(geometry["negative_x_face_mm"])
    )
    # The local intermediate-grid overlay uses the governed coarse bridge
    # envelope on its external faces.  Keep the main PA's outer guard at least
    # that large, so the overlay can obtain every Dirichlet boundary value from
    # the main fine-basis family rather than falling back to the coarse PA.
    raw_x_max = float(geometry["axis_x_mm"]) + half_width + bridge_x_margin
    # Preserve the physical aperture-minus-10 mm start.  The far exterior
    # padding can safely grow by less than one cell to close the PA lattice.
    x_max = x_min + math.ceil((raw_x_max - x_min) / cells["x"]) * cells["x"]
    bounds = {
        "x_min": x_min,
        "x_max": x_max,
        "y_min": float(geometry["axis_y_mm"]) - half_width - bridge_y_margin,
        "y_max": float(geometry["axis_y_mm"]) + half_width + bridge_y_margin,
        "z_min": z_min,
        "z_max": z_max,
    }
    dimensions: dict[str, int] = {}
    for axis in ("x", "y", "z"):
        span = bounds[f"{axis}_max"] - bounds[f"{axis}_min"]
        count = round(span / cells[axis])
        if not math.isclose(span / cells[axis], count, abs_tol=1e-8):
            raise ValueError(f"accelerator main {axis} span is not aligned to its grid")
        dimensions[f"n{axis}"] = int(count) + 1
    for role in ("intermediate1", "intermediate2", "exit"):
        _aligned_index(plane_values[role], z_min, cells["z"], f"{role}_z_mm")

    # The bridge PA is deliberately only a remote Dirichlet-boundary source.
    # Its coarse rasterization of the side opening has no authority over the
    # physical aperture.  Recompute the actual scanned aperture on this fine
    # accelerator grid, where the entrance face and its edge field are made.
    fine_aperture_discretization: dict[str, Any] | None = None
    if connection is not None:
        aperture = connection.get("transition_aperture")
        source_exit = frontend.get("source_exit_center_mm")
        if not isinstance(aperture, dict) or not isinstance(source_exit, dict):
            raise ValueError("accelerator main aperture geometry is missing")
        fine_aperture_discretization = resolve_rectangular_aperture_discretization(
            mechanical_width_mm=float(aperture["full_width_mm"]),
            mechanical_height_mm=float(aperture["full_height_mm"]),
            cell_mm_xyz=cells,
            flange_x_min_mm=float(geometry["negative_x_face_mm"]),
            flange_x_max_mm=float(geometry["negative_x_face_mm"])
            + float(geometry["shield_wall_mm"]),
            center_y_mm=float(source_exit["y"]),
            center_z_mm=float(source_exit["z"]),
            pa_origin_y_mm=bounds["y_min"],
            pa_origin_z_mm=bounds["z_min"],
        )
        geometry["numerical_port_width_mm"] = float(
            fine_aperture_discretization["numerical_carve_width_mm"]
        )
        geometry["numerical_port_height_mm"] = float(
            fine_aperture_discretization["numerical_carve_height_mm"]
        )

    missing_basis_ids = [
        electrode_id
        for electrode_id in electrode_topology["basis_electrode_ids"]
        if electrode_id not in {
            int(electrodes["grounded_shield_id"]),
            int(electrodes["accelerator_repeller_id"]),
            int(electrodes["accelerator_grid1_id"]),
            int(electrodes["accelerator_intermediate2_id"]),
            int(electrodes["accelerator_grid2_id"]),
            *[int(value) for value in electrodes["accelerator_ring_ids"]],
        }
    ]
    sentinels = [
        f"  e({electrode_id}) {{ fill {{ within {{ {_box(bounds['x_min'], bounds['y_min'] + offset * cells['y'], bounds['z_min'], cells['x']/2, cells['y']/2, cells['z']/2)} }} }} }}"
        for offset, electrode_id in enumerate(missing_basis_ids, start=1)
    ]
    connector_lines: list[str] = []
    if split is not None:
        junction = frontend.get("junction_enclosure")
        source_exit = frontend.get("source_exit_center_mm")
        if not isinstance(junction, dict) or not isinstance(source_exit, dict):
            raise ValueError("domain split main connector geometry is missing")
        if cylindrical_sideport is None:
            connector_lines, _ = render_fixed_upstream_shield_connector(
                electrode_id=int(electrodes["grounded_shield_id"]),
                sleeve_x_min_mm=float(split["accelerator_start_x_mm"]),
                sleeve_x_max_mm=float(source_exit["x"]), center_y_mm=float(source_exit["y"]),
                center_z_mm=float(source_exit["z"]), outer_radius_mm=float(junction["outer_radius_mm"]),
                inner_radius_mm=float(junction["inner_radius_mm"]), cell_mm_xyz=cells,
            )
        else:
            sideport_lines, rendered_sideport = render_grounded_circular_to_rectangular_connection(
                electrode_id=int(electrodes["grounded_shield_id"]),
                sleeve_x_min_mm=float(split["accelerator_start_x_mm"]),
                sleeve_x_max_mm=float(source_exit["x"]),
                flange_thickness_mm=float(cylindrical_sideport["positive_volume_overlap_mm"]),
                center_y_mm=float(source_exit["y"]), center_z_mm=float(source_exit["z"]),
                outer_radius_mm=float(cylindrical_sideport["outer_radius_mm"]),
                inner_radius_mm=float(cylindrical_sideport["connector_inner_radius_mm"]),
                aperture_width_mm=float(cylindrical_sideport["mechanical_aperture_mm"]["width"]),
                aperture_height_mm=float(cylindrical_sideport["mechanical_aperture_mm"]["height"]),
                cell_mm_xyz=cells, pa_origin_y_mm=bounds["y_min"], pa_origin_z_mm=bounds["z_min"],
            )
            connector_lines = ["  ; Grounded cylindrical side-port collar/end plate.", *sideport_lines]
            cylindrical_sideport = {**cylindrical_sideport, "fine_aperture_discretization": rendered_sideport["aperture_discretization"]}
    gem_lines = [
        "; Generated standalone three-zone accelerator main PA; do not edit.",
        "; It requires bridge-electrode-basis Dirichlet initialization before Refine.",
        f"pa_define({dimensions['nx']},{dimensions['ny']},{dimensions['nz']},planar,none,electrostatic,,{_fmt(cells['x'])},{_fmt(cells['y'])},{_fmt(cells['z'])},surface=none)",
        f"locate({_fmt(-bounds['x_min'])},{_fmt(-bounds['y_min'])},{_fmt(-bounds['z_min'])}) {{",
        *connector_lines,
        *_render_accelerator_local_geometry(
            geometry,
            cell_x_mm=cells["x"],
            cell_z_mm=cells["z"],
            electrodes=electrodes,
            render_intermediate2_sheet=True,
        ),
        "  ; Boundary-only sentinels initialize absent upstream-electrode bases.",
        *sentinels,
        "}",
        "",
    ]
    contract = {
        "schema_version": 1,
        "role": "rf_oatof_simion_accelerator_main_contract",
        "frame_id": frontend["frame_id"],
        "status": "bridge_coupling_required",
        "cell_mm_xyz": cells,
        "dimensions": dimensions,
        "instance_origin_mm": {
            axis: bounds[f"{axis}_min"] for axis in ("x", "y", "z")
        },
        "instance_bounds_mm": bounds,
        "cross_section": expected_cross_section,
        "cylindrical_sideport": cylindrical_sideport,
        "accelerator_port_aperture": {
            "authority": "fine_accelerator_main_pa_v1",
            "discretization": fine_aperture_discretization,
            "grid_alignment_policy": "warn_only_use_fine_realization_v1",
            "coarse_frontend_discretization_is_non_authoritative": connection
            is not None,
        },
        "accelerator_topology_id": frontend["accelerator_topology_id"],
        "axial_planes_global_z_mm": plane_values,
        "potentials_v": potential_values,
        "ring_placement": {
            "policy_id": placement["policy_id"],
            "zone_ring_counts": dict(placement["zone_ring_counts"]),
            "ring_z_mm": resolved_ring_z,
        },
        "electrodes": electrodes,
        "boundary_condition": {
            "mode": "bridge_electrode_basis_dirichlet_required_v1",
            "direct_refinement_prohibited": True,
            "basis_electrode_ids": list(electrode_topology["basis_electrode_ids"]),
            "missing_basis_sentinel_electrode_ids": missing_basis_ids,
        },
        "domain_split": (
            {
                **split,
                "partition_policy_id": "grounded_sleeve_disjoint_fine_domains_v1",
            }
            if split is not None
            else None
        ),
    }
    return "\n".join(gem_lines), contract


def compile_upstream_bridge(
    upstream: dict[str, Any],
    oatof: dict[str, Any],
    connection: dict[str, Any],
    *,
    cell_mm_xyz: dict[str, float],
) -> tuple[str, dict[str, Any]]:
    """Compile the upstream-plus-port PA used by a future bridge coupling.

    This PA deliberately stops at the grounded side-port screen.  It does not
    contain the axial accelerator body, its ideal sheets, or its rings.  Its
    field is therefore not a replacement for a coupled single-PA solution:
    every electrode basis must be initialized from a common coarse bridge PA
    before refinement.  The existing full frontend compiler remains the
    authority for validating the shared resolved inputs.
    """
    if set(cell_mm_xyz) != {"x", "y", "z"}:
        raise ValueError("upstream bridge cell_mm_xyz must contain exactly x, y and z")
    cells = {axis: float(cell_mm_xyz[axis]) for axis in ("x", "y", "z")}
    if not all(math.isfinite(value) and value > 0 for value in cells.values()):
        raise ValueError("upstream bridge cell sizes must be finite and positive")
    if not math.isclose(cells["x"], cells["y"], abs_tol=1e-12):
        raise ValueError("upstream bridge requires transverse x-y grid symmetry")

    # Reuse the established input and topology validation without changing the
    # historical full-frontend output or its runtime semantics.
    _, frontend = compile_frontend(
        upstream, oatof, connection, cell_mm_xyz=cells
    )
    local = dict(frontend["accelerator_local_region"])
    electrodes = dict(frontend["electrodes"])
    topology = resolve_frontend_electrode_topology(electrodes)
    connector = connection["connector"]
    connector_length = float(connector["length_mm"])
    split = resolve_positive_gap_domain_split(frontend, connection)
    exit_x = float(frontend["source_exit_center_mm"]["x"])
    center_y = float(frontend["source_exit_center_mm"]["y"])
    center_z = float(frontend["source_exit_center_mm"]["z"])
    source_zero_x = float(connection["spatial_registration"]["translation_mm"][0])
    enclosure = upstream["geometry_mm"]["enclosure"]
    outer_radius = float(enclosure["shield_outer_radius_mm"])
    inner_radius = float(enclosure["shield_inner_radius_mm"])
    source_x_min = source_zero_x + float(enclosure["vacuum_z_min_mm"])
    source_mating_center = connection["port_geometry"]["upstream"]["mating_surface"]["center_mm"]
    shield_x_max = source_zero_x + float(source_mating_center[2])
    shield_wall = float(local["shield_wall_mm"])
    x_max = (
        float(split["upstream_end_x_mm"])
        if split is not None
        else exit_x + shield_wall + cells["x"]
    )
    # The terminal-plus-10 mm boundary is physical.  Anchor the otherwise
    # padding-only upstream minimum to it, rather than shifting this endpoint
    # to a grid node and silently changing the disjoint-domain contract.
    x_min = x_max - math.ceil(
        (x_max - source_x_min + cells["x"]) / cells["x"]
    ) * cells["x"]
    y_min = -math.ceil((outer_radius + cells["y"]) / cells["y"]) * cells["y"]
    y_max = -y_min
    z_min = center_z - math.ceil((outer_radius + cells["z"]) / cells["z"]) * cells["z"]
    z_max = center_z + math.ceil((outer_radius + cells["z"]) / cells["z"]) * cells["z"]
    bounds = {
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "z_min": z_min,
        "z_max": z_max,
    }
    dimensions = {
        f"n{axis}": int(round((bounds[f"{axis}_max"] - bounds[f"{axis}_min"]) / cells[axis])) + 1
        for axis in ("x", "y", "z")
    }
    for axis in ("x", "y", "z"):
        span = bounds[f"{axis}_max"] - bounds[f"{axis}_min"]
        if not math.isclose(span / cells[axis], round(span / cells[axis]), abs_tol=1e-8):
            raise ValueError(f"upstream bridge {axis} span is not aligned to its grid")

    aperture = connection["transition_aperture"]
    aperture_discretization = resolve_rectangular_aperture_discretization(
        mechanical_width_mm=float(aperture["full_width_mm"]),
        mechanical_height_mm=float(aperture["full_height_mm"]),
        cell_mm_xyz=cells,
        flange_x_min_mm=exit_x,
        flange_x_max_mm=exit_x + shield_wall,
        center_y_mm=center_y,
        center_z_mm=center_z,
        pa_origin_y_mm=y_min,
        pa_origin_z_mm=z_min,
    )
    port_width = float(aperture_discretization["numerical_carve_width_mm"])
    port_height = float(aperture_discretization["numerical_carve_height_mm"])
    segmented_rods = upstream["segmentation"]["segmented_rod_array"]
    grounded_shield_id = int(electrodes["grounded_shield_id"])
    entrance_reference_id = int(electrodes["entrance_reference_sleeve_id"])
    entrance_plate_id = int(electrodes["entrance_plate_id"])
    lines = [
        "; Generated upstream bridge PA; do not edit.",
        "; Bridge-electrode-basis Dirichlet initialization is required before Refine.",
        f"pa_define({dimensions['nx']},{dimensions['ny']},{dimensions['nz']},planar,none,electrostatic,,{_fmt(cells['x'])},{_fmt(cells['y'])},{_fmt(cells['z'])},surface=none)",
        f"locate({_fmt(-x_min)},{_fmt(-y_min)},{_fmt(-z_min)}) {{",
        *render_axis_mapped_segmented_rod_array_gem(
            segmented_rods,
            axial_origin_mm=source_zero_x,
            transverse_origin_mm=(center_y, center_z),
            rotation_axis=1,
            rotation_degrees=90,
            indent="  ",
            significant_digits=12,
        ).splitlines(),
    ]
    shield_length = shield_x_max - source_x_min
    lines.extend(
        [
            f"  e({grounded_shield_id}) {{ fill {{",
            f"    within {{ locate({_fmt(shield_x_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(shield_length)}) }} }}",
            f"    notin_inside {{ locate({_fmt(shield_x_max+cells['x'])},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(inner_radius)},,{_fmt(shield_length+2*cells['x'])}) }} }}",
            "  } }",
        ]
    )
    entrance_min = source_zero_x + float(enclosure["entrance_outer_endcap_upstream_face_z_mm"])
    entrance_max = source_zero_x + float(enclosure["entrance_outer_endcap_downstream_face_z_mm"])
    entrance_radius = float(upstream["interfaces_mm"]["entrance"]["aperture_radius_mm"])
    plate_min = source_zero_x + float(
        upstream["interfaces_mm"]["entrance"]["aperture_plate_upstream_face_z_mm"]
    )
    plate_max = source_zero_x + float(
        upstream["interfaces_mm"]["entrance"]["aperture_plate_downstream_face_z_mm"]
    )
    sleeve = upstream["axial_dc"]["entrance_reference_sleeve"]
    sleeve_min = source_zero_x + float(sleeve["upstream_face_z_mm"])
    sleeve_max = source_zero_x + float(sleeve["downstream_face_z_mm"])
    sleeve_outer = float(sleeve["outer_radius_mm"])
    sleeve_inner = float(sleeve["inner_radius_mm"])
    insulated_radius = sleeve_outer + float(sleeve["minimum_insulation_gap_mm"])
    lines.extend(
        [
            f"  e({grounded_shield_id}) {{ fill {{ within {{ locate({_fmt(entrance_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(entrance_max-entrance_min)}) }} }} notin_inside {{ locate({_fmt(entrance_max+cells['x'])},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(insulated_radius)},,{_fmt(entrance_max-entrance_min+2*cells['x'])}) }} }} }} }}",
            f"  e({entrance_plate_id}) {{ fill {{ within {{ locate({_fmt(plate_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(plate_max-plate_min)}) }} }} notin_inside {{ locate({_fmt(plate_max+cells['x'])},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(entrance_radius)},,{_fmt(plate_max-plate_min+2*cells['x'])}) }} }} }} }}",
            f"  e({entrance_reference_id}) {{ fill {{ within {{ locate({_fmt(sleeve_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(sleeve_outer)},,{_fmt(sleeve_max-sleeve_min)}) }} }} notin_inside {{ locate({_fmt(sleeve_max+cells['x'])},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(sleeve_inner)},,{_fmt(sleeve_max-sleeve_min+2*cells['x'])}) }} }} }} }}",
        ]
    )
    terminal = upstream.get("downstream_terminal", {})
    terminal_end_x = shield_x_max
    if connector_length > 0.0:
        thickness = float(terminal["electrode_thickness_mm"])
        terminal_end_x += thickness
        terminal_aperture = frontend["connector_terminal"]["aperture"]
        if terminal_aperture["shape"] == "circular":
            terminal_void = f"locate({_fmt(terminal_end_x+cells['x'])},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(float(terminal_aperture['radius_mm']))},,{_fmt(thickness+2*cells['x'])}) }}"
        else:
            terminal_void = _box(shield_x_max + thickness / 2, center_y, center_z, thickness + 2*cells["x"], float(terminal_aperture["width_mm"]), float(terminal_aperture["height_mm"]))
        lines.extend(["  ; Integration-owned grounded connector terminal.", f"  e({grounded_shield_id}) {{ fill {{ within {{ locate({_fmt(terminal_end_x)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(inner_radius)},,{_fmt(thickness)}) }} }} notin_inside {{ {terminal_void} }} }} }}"])
    connector_lines, connector_contract = render_fixed_upstream_shield_connector(
        electrode_id=grounded_shield_id,
        sleeve_x_min_mm=terminal_end_x,
        sleeve_x_max_mm=(float(split["upstream_end_x_mm"]) if split is not None else exit_x),
        center_y_mm=center_y,
        center_z_mm=center_z,
        outer_radius_mm=outer_radius,
        inner_radius_mm=inner_radius,
        cell_mm_xyz=cells,
    )
    lines.extend(connector_lines)
    screen_span_y = port_width + 2 * shield_wall + 2 * cells["y"]
    screen_span_z = port_height + 2 * shield_wall + 2 * cells["z"]
    if split is None:
        # Direct mating has no connector overlap; the upstream PA owns the
        # local grounded port screen exactly as in the validated legacy path.
        lines.extend(
            [
                "  ; Local grounded accelerator-entry screen; no axial accelerator body.",
                f"  e({grounded_shield_id}) {{ fill {{ within {{ {_box(exit_x + shield_wall/2, center_y, center_z, shield_wall, screen_span_y, screen_span_z)} }} notin_inside_or_on {{ {_box(exit_x + shield_wall/2, center_y, center_z, shield_wall+2*cells['x'], port_width, port_height)} }} }} }}",
            ]
        )
    physical_ids = {
        *[int(value) for value in electrodes["multipole_rod_ids"]],
        grounded_shield_id,
        entrance_reference_id,
        entrance_plate_id,
    }
    missing_basis_ids = [
        electrode_id for electrode_id in topology["basis_electrode_ids"] if electrode_id not in physical_ids
    ]
    lines.extend(
        [
            "  ; Boundary-only sentinels retain absent accelerator bases for bridge transfer.",
            *[
                f"  e({electrode_id}) {{ fill {{ within {{ {_box(x_min, y_min + offset*cells['y'], z_min, cells['x']/2, cells['y']/2, cells['z']/2)} }} }} }}"
                for offset, electrode_id in enumerate(missing_basis_ids, start=1)
            ],
            "}",
            "",
        ]
    )
    contract = {
        "schema_version": 1,
        "role": "rf_oatof_simion_upstream_bridge_contract",
        "frame_id": frontend["frame_id"],
        "status": "bridge_coupling_required",
        "cell_mm_xyz": cells,
        "dimensions": dimensions,
        "instance_origin_mm": {axis: bounds[f"{axis}_min"] for axis in ("x", "y", "z")},
        "instance_bounds_mm": bounds,
        "source_exit_center_mm": dict(frontend["source_exit_center_mm"]),
        "junction_enclosure": {**connector_contract, "profile_gap_mm": connector_length},
        "accelerator_entry_shield": {
            "owner": "accelerator_main" if split is not None else "upstream_bridge",
            "numerical_port_aperture_discretization": aperture_discretization,
            "screen_span_mm": {"y": screen_span_y, "z": screen_span_z},
            "cylindrical_sideport": frontend.get("cylindrical_sideport"),
        },
        "cylindrical_sideport": frontend.get("cylindrical_sideport"),
        "connector_terminal": dict(frontend["connector_terminal"]),
        "domain_split": (
            {
                **split,
                "partition_policy_id": "grounded_sleeve_disjoint_fine_domains_v1",
            }
            if split is not None
            else None
        ),
        "electrodes": electrodes,
        "boundary_condition": {
            "mode": "bridge_electrode_basis_dirichlet_required_v1",
            "direct_refinement_prohibited": True,
            "basis_electrode_ids": list(topology["basis_electrode_ids"]),
            "missing_basis_sentinel_electrode_ids": missing_basis_ids,
        },
    }
    return "\n".join(lines), contract


def compile_frontend(
    upstream: dict[str, Any],
    oatof: dict[str, Any],
    connection: dict[str, Any],
    *,
    cell_mm_xyz: dict[str, float] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return a composite GEM and its placement/electrode contract."""
    cells = {"x": 0.2, "y": 0.2, "z": 0.2} if cell_mm_xyz is None else cell_mm_xyz
    if set(cells) != {"x", "y", "z"}:
        raise ValueError("single-flight frontend cell_mm_xyz must contain exactly x, y and z")
    cell_x_mm, cell_y_mm, cell_z_mm = (
        float(cells[axis]) for axis in ("x", "y", "z")
    )
    if upstream.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("upstream input is not a multipole resolved design")
    if oatof.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("oaTOF input is not a resolved geometry contract")
    if not all(
        math.isfinite(value) and value > 0
        for value in (cell_x_mm, cell_y_mm, cell_z_mm)
    ):
        raise ValueError("single-flight frontend cell sizes must be finite and positive")
    connector = connection.get("connector", {})
    connector_length = float(connector.get("length_mm", -1.0))
    if connector_length < 0:
        raise ValueError("single-flight grounded connector length must be nonnegative")
    require_grounded_potential(connector.get("shield_potential_V"), "connection profile shield")
    if connector.get("cross_section_binding") != "upstream_grounded_shield_v1":
        raise ValueError("connector must inherit the upstream grounded shield cross section")
    require_grounded_potential(
        upstream["axial_dc"]["upstream_shield_potential_V"], "multipole shield"
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

    connector_terminal_present = connector_length > 0.0
    terminal = upstream.get("downstream_terminal", {})
    connector_terminal_aperture: dict[str, Any] | None = None
    terminal_radius: float | None = None
    terminal_width: float | None = None
    terminal_height: float | None = None
    terminal_shape: str | None = None
    if connector_terminal_present:
        if (
            terminal.get("owner") != "downstream"
            or terminal.get("upstream_terminal_electrode_present") is not False
        ):
            raise ValueError("nonzero-gap frontend requires one connector-owned terminal")
        require_grounded_potential(
            terminal["terminal_potential_V"], "connector terminal shield"
        )
        terminal_aperture = terminal.get("aperture")
        if not isinstance(terminal_aperture, dict):
            raise ValueError("connector-terminal aperture is missing")
        terminal_shape = terminal_aperture.get("shape")
        if terminal_shape == "circular":
            try:
                raw_terminal_radius = terminal_aperture["radius_mm"]
                if isinstance(raw_terminal_radius, bool):
                    raise TypeError("boolean radius is not physical")
                terminal_radius = float(raw_terminal_radius)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("circular connector-terminal aperture radius is invalid") from error
            if not math.isfinite(terminal_radius) or terminal_radius <= 0:
                raise ValueError("circular connector-terminal aperture radius must be finite and positive")
            connector_terminal_aperture = {"shape": "circular", "radius_mm": terminal_radius}
        elif terminal_shape == "rectangular":
            try:
                terminal_width = float(terminal_aperture["width_mm"])
                terminal_height = float(terminal_aperture["height_mm"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("rectangular connector-terminal aperture dimensions are invalid") from error
            if not all(math.isfinite(value) and value > 0 for value in (terminal_width, terminal_height)):
                raise ValueError("rectangular connector-terminal aperture dimensions must be finite and positive")
            connector_terminal_aperture = {
                "shape": "rectangular",
                "width_mm": terminal_width,
                "height_mm": terminal_height,
            }
        else:
            raise ValueError("connector-terminal aperture shape is unsupported")
    aperture = connection["transition_aperture"]
    exit_global = aperture["center_mm"]
    exit_x, center_y, center_z = map(float, exit_global)
    source_zero_x = float(registration["translation_mm"][0])
    accelerator = oatof["geometry_derivation"]["accelerator"]
    accelerator_topology = oatof.get("accelerator_topology")
    three_zone = accelerator_topology is not None
    if three_zone:
        if set(accelerator_topology) != {
            "topology_id",
            "planes_global_z_mm",
            "potentials_v",
        } or not isinstance(accelerator_topology.get("topology_id"), str) or not (
            accelerator_topology["topology_id"]
        ):
            raise ValueError("oaTOF accelerator_topology differs from the published three-zone contract")
        planes = accelerator_topology["planes_global_z_mm"]
        potentials = accelerator_topology["potentials_v"]
        plane_roles = ("repeller", "intermediate1", "intermediate2", "exit")
        if set(planes) != set(plane_roles) or set(potentials) != set(plane_roles):
            raise ValueError("three-zone accelerator requires exactly four named planes and potentials")
        plane_values = [float(planes[role]) for role in plane_roles]
        potential_values = [float(potentials[role]) for role in plane_roles]
        if not all(math.isfinite(value) for value in plane_values + potential_values):
            raise ValueError("three-zone accelerator planes and potentials must be finite")
        if not all(left < right for left, right in zip(plane_values, plane_values[1:])):
            raise ValueError("three-zone accelerator planes must be strictly increasing")
        if not all(left > right for left, right in zip(potential_values, potential_values[1:])):
            raise ValueError("three-zone accelerator potentials must be strictly decreasing")
    geometry = oatof["geometry_mm"]
    realization = str(
        oatof.get("geometry_derivation", {})
        .get("accelerator", {})
        .get("realization_id", "square_3d")
    )
    cross_section_by_realization = {
        "square_3d": "square",
        "cylindrical_3d": "cylindrical",
    }
    if realization not in cross_section_by_realization:
        raise ValueError("oaTOF accelerator realization is unsupported")
    expected_shield_profile = {
        "square_3d": "grounded_circular_to_rectangular_shield_v1",
        "cylindrical_3d": "grounded_circular_to_cylindrical_sideport_v1",
    }[realization]
    if connector.get("shield_connection_profile_id") != expected_shield_profile:
        raise ValueError(
            "single-flight frontend shield connection profile differs from accelerator realization"
        )
    ring_count = int(oatof["rings"]["accelerator_count"])
    axis_x = float(oatof["coordinate_convention"]["accelerator_axis_x"])
    axis_y = 0.0
    _require_close(center_z, oatof["particle_source"]["center_z_mm"], "port center z")

    enclosure = upstream["geometry_mm"]["enclosure"]
    segmented_rods = upstream["segmentation"]["segmented_rod_array"]
    rods = segmented_rods["electrodes"]
    electrodes = _electrode_namespace(
        segmented_rod_electrode_ids(segmented_rods), ring_count, three_zone=three_zone
    )
    grounded_shield_id = int(electrodes["grounded_shield_id"])
    entrance_reference_id = int(electrodes["entrance_reference_sleeve_id"])
    entrance_plate_id = int(electrodes["entrance_plate_id"])

    outer_radius = float(enclosure["shield_outer_radius_mm"])
    inner_radius = float(enclosure["shield_inner_radius_mm"])
    source_x_min = source_zero_x + float(enclosure["vacuum_z_min_mm"])
    # The connector gap is registered from the provided multipole exit mating
    # surface, not from the historical inner shield end plane.  Using the
    # latter silently adds the 0.5 mm aperture-plate offset to every finite
    # connector.  The integration-owned terminal (when gap > 0) starts at
    # this same registered surface.
    source_mating_center = connection["port_geometry"]["upstream"]["mating_surface"]["center_mm"]
    if not isinstance(source_mating_center, list) or len(source_mating_center) != 3:
        raise ValueError("upstream connector mating-surface center is invalid")
    shield_x_max = source_zero_x + float(source_mating_center[2])
    grid2_z = float(
        accelerator_topology["planes_global_z_mm"]["exit"]
        if three_zone
        else accelerator["canonical_grid2_z_mm"]
    )
    repeller_front_z = float(
        accelerator_topology["planes_global_z_mm"]["repeller"]
        if three_zone
        else accelerator["canonical_repeller_z_mm"]
    )
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
    cylindrical_sideport: dict[str, Any] | None = None
    if realization == "cylindrical_3d":
        accelerator_outer_radius = shield_outer_width / 2
        if outer_radius < accelerator_outer_radius or shield_wall <= 0:
            raise ValueError("cylindrical side-port collar cannot enclose the accelerator shell")
        cylindrical_sideport = {
            "profile_id": "grounded_circular_to_cylindrical_sideport_v1",
            "topology": "grounded_circular_sideport_collar_end_plate_v1",
            "grounded_electrode_id": grounded_shield_id,
            "outer_radius_mm": outer_radius,
            "connector_inner_radius_mm": inner_radius,
            "accelerator_shell_outer_radius_mm": accelerator_outer_radius,
            "accelerator_shell_inner_radius_mm": shield_inner_width / 2,
            "accelerator_shell_wall_mm": shield_wall,
            "collar_x_min_mm": negative_x_face,
            "collar_x_max_mm": negative_x_face + shield_wall,
            "positive_volume_overlap_mm": shield_wall,
            "mechanical_aperture_mm": {
                "width": float(aperture["full_width_mm"]),
                "height": float(aperture["full_height_mm"]),
            },
        }

    x_min = exit_x - math.ceil(
        (exit_x - source_x_min + cell_x_mm) / cell_x_mm
    ) * cell_x_mm
    x_max = axis_x + shield_outer_width / 2 + cell_x_mm
    y_min = -math.ceil((outer_radius + cell_y_mm) / cell_y_mm) * cell_y_mm
    y_max = -y_min
    physical_z_min = min(center_z - outer_radius, shield_back_z) - cell_z_mm
    z_min = grid2_z - math.ceil(
        (grid2_z - physical_z_min) / cell_z_mm
    ) * cell_z_mm
    # The local accelerator overlay imposes its outer Dirichlet face one
    # additional coarse cell beyond its active outlet guard cell.  A second
    # coarse cell merely places that face on the final PA node; the basis
    # transfer requires it to be strictly inside the coarse PA.  Retain one
    # further guard cell after grid2.
    z_max = max(center_z + outer_radius, grid2_z + 3 * cell_z_mm)
    nx = math.ceil((x_max - x_min) / cell_x_mm) + 1
    ny = math.ceil((y_max - y_min) / cell_y_mm) + 1
    nz = math.ceil((z_max - z_min) / cell_z_mm) + 1

    lines = [
        "; Generated single-flight multipole + oaTOF accelerator frontend; do not edit.",
        f"; upstream_resolved_sha256={upstream['resolved_sha256']}",
        f"; electrode {electrodes['multipole_rod_ids'][0]}..{electrodes['multipole_rod_ids'][-1]}=multipole rods; {grounded_shield_id}=all grounded shields and connector; {electrodes['accelerator_repeller_id']}..{electrodes['accelerator_grid2_id']}=oaTOF accelerator; {entrance_reference_id}=functional entrance-reference sleeve",
        f"pa_define({nx},{ny},{nz},planar,none,electrostatic,,{_fmt(cell_x_mm)},{_fmt(cell_y_mm)},{_fmt(cell_z_mm)},surface=none)",
        f"locate({_fmt(-x_min)},{_fmt(-y_min)},{_fmt(-z_min)}) {{",
    ]
    lines.extend(
        render_axis_mapped_segmented_rod_array_gem(
            segmented_rods,
            axial_origin_mm=source_zero_x,
            transverse_origin_mm=(center_y, center_z),
            rotation_axis=1,
            rotation_degrees=90,
            indent="  ",
            significant_digits=12,
        ).splitlines()
    )

    shield_length = shield_x_max - source_x_min
    lines.extend(
        [
            f"  e({grounded_shield_id}) {{ fill {{",
            f"    within {{ locate({_fmt(shield_x_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(shield_length)}) }} }}",
            f"    notin_inside {{ locate({_fmt(shield_x_max+cell_x_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(inner_radius)},,{_fmt(shield_length+2*cell_x_mm)}) }} }}",
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
            f"  e({grounded_shield_id}) {{ fill {{",
            f"    within {{ locate({_fmt(entrance_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(entrance_max-entrance_min)}) }} }}",
            f"    notin_inside {{ locate({_fmt(entrance_max+cell_x_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(insulated_radius)},,{_fmt(entrance_max-entrance_min+2*cell_x_mm)}) }} }}",
            "  } }",
            f"  e({entrance_plate_id}) {{ fill {{",
            f"    within {{ locate({_fmt(entrance_plate_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(outer_radius)},,{_fmt(entrance_plate_max-entrance_plate_min)}) }} }}",
            f"    notin_inside {{ locate({_fmt(entrance_plate_max+cell_x_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(entrance_radius)},,{_fmt(entrance_plate_max-entrance_plate_min+2*cell_x_mm)}) }} }}",
            "  } }",
            "  ; Functional source-reference sleeve; this is not a shield electrode.",
            f"  e({entrance_reference_id}) {{ fill {{",
            f"    within {{ locate({_fmt(sleeve_max)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(sleeve_outer)},,{_fmt(sleeve_max-sleeve_min)}) }} }}",
            f"    notin_inside {{ locate({_fmt(sleeve_max+cell_x_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(sleeve_inner)},,{_fmt(sleeve_max-sleeve_min+2*cell_x_mm)}) }} }}",
            "  } }",
        ]
    )

    shield_center_z = (shield_back_z + grid2_z) / 2
    shield_span_z = grid2_z - shield_back_z
    port_width = float(aperture["full_width_mm"])
    port_height = float(aperture["full_height_mm"])
    rod_end_x = source_zero_x + max(float(item["z_max_mm"]) for item in rods)
    terminal_surface_x = shield_x_max
    if shield_x_max + 1e-12 < rod_end_x:
        raise ValueError("multipole rods extend beyond the connector entrance plane")
    _require_close(exit_x - terminal_surface_x, connector_length, "registered connector gap")
    terminal_thickness = 0.0
    terminal_end_x = terminal_surface_x
    if connector_terminal_present:
        terminal_thickness = float(terminal["electrode_thickness_mm"])
        if not math.isfinite(terminal_thickness) or terminal_thickness <= 0:
            raise ValueError("connector-terminal thickness must be finite and positive")
        if connector_length + 1e-12 < terminal_thickness:
            raise ValueError("connector gap is shorter than its physical terminal plate")
        terminal_end_x = terminal_surface_x + terminal_thickness
        if terminal_shape == "circular":
            terminal_void = (
                f"locate({_fmt(terminal_end_x + cell_x_mm)},{_fmt(center_y)},{_fmt(center_z)},1,90) "
                f"{{ cylinder(0,0,0,{_fmt(terminal_radius)},,{_fmt(terminal_thickness + 2 * cell_x_mm)}) }}"
            )
        else:
            terminal_void = _box(
                terminal_surface_x + terminal_thickness / 2,
                center_y,
                center_z,
                terminal_thickness + 2 * cell_x_mm,
                float(terminal_width),
                float(terminal_height),
            )
        lines.extend(
            [
                "  ; Integration-owned grounded connector terminal at the connector entrance.",
                f"  e({grounded_shield_id}) {{ fill {{",
                f"    within {{ locate({_fmt(terminal_end_x)},{_fmt(center_y)},{_fmt(center_z)},1,90) {{ cylinder(0,0,0,{_fmt(inner_radius)},,{_fmt(terminal_thickness)}) }} }}",
                f"    notin_inside {{ {terminal_void} }}",
                "  } }",
            ]
        )
    if cylindrical_sideport is None:
        connection_lines, connection_contract = render_fixed_upstream_shield_connector(
            electrode_id=grounded_shield_id, sleeve_x_min_mm=terminal_end_x,
            sleeve_x_max_mm=exit_x, center_y_mm=center_y, center_z_mm=center_z,
            outer_radius_mm=outer_radius, inner_radius_mm=inner_radius,
            cell_mm_xyz={"x": cell_x_mm, "y": cell_y_mm, "z": cell_z_mm},
        )
    else:
        connection_lines, rendered_sideport = render_grounded_circular_to_rectangular_connection(
            electrode_id=grounded_shield_id, sleeve_x_min_mm=terminal_end_x,
            sleeve_x_max_mm=exit_x, flange_thickness_mm=shield_wall,
            center_y_mm=center_y, center_z_mm=center_z, outer_radius_mm=outer_radius,
            inner_radius_mm=inner_radius, aperture_width_mm=port_width,
            aperture_height_mm=port_height,
            cell_mm_xyz={"x": cell_x_mm, "y": cell_y_mm, "z": cell_z_mm},
            pa_origin_y_mm=y_min, pa_origin_z_mm=z_min,
        )
        connection_lines.insert(0, "  ; Grounded cylindrical side-port collar/end plate.")
        cylindrical_sideport["coarse_aperture_discretization"] = rendered_sideport["aperture_discretization"]
        connection_contract = {**rendered_sideport, "profile_id": cylindrical_sideport["profile_id"]}
    lines.extend(connection_lines)
    aperture_discretization = resolve_rectangular_aperture_discretization(
        mechanical_width_mm=port_width,
        mechanical_height_mm=port_height,
        cell_mm_xyz={"x": cell_x_mm, "y": cell_y_mm, "z": cell_z_mm},
        flange_x_min_mm=exit_x,
        flange_x_max_mm=exit_x + shield_wall,
        center_y_mm=center_y,
        center_z_mm=center_z,
        pa_origin_y_mm=y_min,
        pa_origin_z_mm=z_min,
    )
    numerical_port_width = float(aperture_discretization["numerical_carve_width_mm"])
    numerical_port_height = float(aperture_discretization["numerical_carve_height_mm"])
    electrode_width = 2 * (
        float(geometry["accelerator_bore_half"])
        + float(geometry["accelerator_ring_width"])
    )
    bore_width = 2 * float(geometry["accelerator_bore_half"])
    grid1_z = float(
        accelerator_topology["planes_global_z_mm"]["intermediate1"]
        if three_zone
        else accelerator["canonical_grid1_z_mm"]
    )
    stage2 = grid2_z - grid1_z if three_zone else float(accelerator["d2_mm"])
    ring_thickness = float(geometry["accelerator_ring_thickness"])
    placement = oatof["rings"].get("accelerator_placement")
    if placement is not None:
        if not three_zone or set(placement) != {
            "policy_id",
            "zone_ring_counts",
            "minimum_grid_to_ring_edge_clearance_mm",
            "minimum_observed_grid_to_ring_edge_clearance_mm",
            "ring_z_mm",
        } or placement["policy_id"] != "three_zone_zonewise_equal_subdivision_1p4_v1":
            raise ValueError("accelerator ring placement policy identity differs")
        counts = placement["zone_ring_counts"]
        if set(counts) != {"zone2", "zone3"} or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in counts.values()
        ) or sum(counts.values()) != ring_count:
            raise ValueError("accelerator ring placement count differs")
        zone2_ring_count = counts["zone2"]
        zone3_ring_count = counts["zone3"]
        intermediate2_z = float(
            accelerator_topology["planes_global_z_mm"]["intermediate2"]
        )
        expected_ring_z = [
            grid1_z + (index + .5) * (intermediate2_z - grid1_z) / zone2_ring_count
            for index in range(zone2_ring_count)
        ]
        expected_ring_z.extend(
            intermediate2_z + index * (grid2_z - intermediate2_z) / (zone3_ring_count + 1)
            for index in range(1, zone3_ring_count + 1)
        )
        ring_z_mm = [float(value) for value in placement["ring_z_mm"]]
        if len(ring_z_mm) != ring_count or any(
            not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
            for actual, expected in zip(ring_z_mm, expected_ring_z)
        ):
            raise ValueError("accelerator ring placement centers differ")
        zone2_ring_z = ring_z_mm[:zone2_ring_count]
        zone3_ring_z = ring_z_mm[zone2_ring_count:]
        edge_clearances = [
            zone2_ring_z[0] - ring_thickness / 2.0 - grid1_z,
            intermediate2_z - zone2_ring_z[-1] - ring_thickness / 2.0,
            zone3_ring_z[0] - ring_thickness / 2.0 - intermediate2_z,
            grid2_z - zone3_ring_z[-1] - ring_thickness / 2.0,
        ]
        edge_clearance = min(edge_clearances)
        required_clearance = float(
            placement["minimum_grid_to_ring_edge_clearance_mm"]
        )
        if edge_clearance + 1e-12 < required_clearance or not math.isclose(
            edge_clearance,
            float(placement["minimum_observed_grid_to_ring_edge_clearance_mm"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise ValueError("accelerator grid-to-ring edge clearance differs")
        ring_pitch = None
    else:
        ring_pitch = stage2 / (ring_count + 1)
        ring_z_mm = [
            grid1_z + index * ring_pitch for index in range(1, ring_count + 1)
        ]
    accelerator_local_region: dict[str, Any] = {
        "cross_section": cross_section_by_realization[realization],
        "axis_x_mm": axis_x,
        "axis_y_mm": axis_y,
        "shield_center_z_mm": shield_center_z,
        "shield_outer_width_mm": shield_outer_width,
        "shield_inner_width_mm": shield_inner_width,
        "shield_span_z_mm": shield_span_z,
        "negative_x_face_mm": negative_x_face,
        "shield_wall_mm": shield_wall,
        "shield_back_z_mm": shield_back_z,
        "port_center_y_mm": center_y,
        "port_center_z_mm": center_z,
        "numerical_port_width_mm": numerical_port_width,
        "numerical_port_height_mm": numerical_port_height,
        "electrode_width_mm": electrode_width,
        "bore_width_mm": bore_width,
        "repeller_front_z_mm": repeller_front_z,
        "repeller_thickness_mm": repeller_thickness,
        "grid1_z_mm": grid1_z,
        "grid2_z_mm": grid2_z,
        "ring_count": ring_count,
        "ring_thickness_mm": ring_thickness,
        # This opening belongs to the accelerator shield, not the connector.
        "accelerator_port_aperture_discretization": aperture_discretization,
    }
    if ring_pitch is not None:
        accelerator_local_region["ring_pitch_mm"] = ring_pitch
    else:
        accelerator_local_region["ring_placement"] = {
            "policy_id": placement["policy_id"],
            "zone_ring_counts": dict(placement["zone_ring_counts"]),
            "minimum_grid_to_ring_edge_clearance_mm": required_clearance,
            "minimum_observed_grid_to_ring_edge_clearance_mm": edge_clearance,
        }
    if three_zone:
        accelerator_local_region.update(
            {
                "intermediate2_z_mm": float(
                    accelerator_topology["planes_global_z_mm"]["intermediate2"]
                ),
                "ring_z_mm": ring_z_mm,
                "intermediate2_grid_provider": "accelerator_overlay",
            }
        )
    lines.extend(
        _render_accelerator_local_geometry(
            accelerator_local_region,
            cell_x_mm=cell_x_mm,
            cell_z_mm=cell_z_mm,
            electrodes=electrodes,
        )
    )
    if three_zone:
        lines.extend(
            [
                f"  ; ID {electrodes['accelerator_intermediate2_id']} is a coarse boundary sentinel; the exact sheet is owned by the accelerator overlay.",
                f"  e({electrodes['accelerator_intermediate2_id']}) {{ fill {{ within {{ {_box(x_min,y_min,z_min,0.0,0.0,0.0)} }} }} }}",
            ]
        )
    lines.extend(["}", ""])

    contract = {
        "schema_version": 2,
        "role": "rf_oatof_simion_single_flight_frontend_contract",
        "frame_id": "oatof_global",
        "cell_mm_xyz": {"x": cell_x_mm, "y": cell_y_mm, "z": cell_z_mm},
        "dimensions": {"nx": nx, "ny": ny, "nz": nz},
        "instance_origin_mm": {"x": x_min, "y": y_min, "z": z_min},
        "source_exit_center_mm": {"x": exit_x, "y": center_y, "z": center_z},
        "junction_enclosure": {
            "rod_end_to_accelerator_shield_mm": round(exit_x - rod_end_x, 12),
            "profile_gap_mm": round(connector_length, 12),
            **connection_contract,
        },
        "cylindrical_sideport": cylindrical_sideport,
        "aperture": {"shape": "rectangular", "width_mm": port_width, "height_mm": port_height},
        "accelerator_port_aperture_authority": {
            "mode": "coarse_bridge_boundary_only_v1",
            "authoritative_provider": "rf_oatof_simion_accelerator_main_contract",
            "rule": (
                "The global coarse PA does not define the scanned accelerator "
                "opening; the fine accelerator PA recomputes it on its own grid."
            ),
        },
        "connector_terminal": {
            "present": connector_terminal_present,
            "owner": "integration" if connector_terminal_present else None,
            "position": "connector_entrance" if connector_terminal_present else None,
            "potential_V": 0.0 if connector_terminal_present else None,
            "outer_radius_source": "connector.cross_section_binding" if connector_terminal_present else None,
            "outer_radius_mm": inner_radius if connector_terminal_present else None,
            "thickness_mm": terminal_thickness if connector_terminal_present else None,
            "aperture": connector_terminal_aperture,
        },
        "electrodes": electrodes,
        "entrance_reference_sleeve": dict(sleeve),
        "accelerator_local_region": accelerator_local_region,
        "ideal_grid_model": {
            "model_id": "simion_one_row_zero_width_native_transmission",
            "grid_roles": [
                "accelerator_grid1",
                *(["accelerator_intermediate2"] if three_zone else []),
                "accelerator_grid2",
            ],
            "real_wire_mesh_requires_separate_profile": True,
        },
    }
    if three_zone:
        contract["accelerator_topology_id"] = accelerator_topology["topology_id"]
    return "\n".join(lines), contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--oatof", required=True, type=Path)
    parser.add_argument("--connection", required=True, type=Path)
    parser.add_argument("--gem", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--cell-mm-x", type=float, default=0.2)
    parser.add_argument("--cell-mm-y", type=float, default=0.2)
    parser.add_argument("--cell-mm-z", type=float, default=0.2)
    parser.add_argument("--overlay-gem", type=Path)
    parser.add_argument("--overlay-contract", type=Path)
    parser.add_argument("--overlay-cell-mm-x", type=float)
    parser.add_argument("--overlay-cell-mm-y", type=float)
    parser.add_argument("--overlay-cell-mm-z", type=float)
    parser.add_argument(
        "--overlay-region-id",
        choices=("whole_accelerator", "entrance", "intermediate2"),
        default="whole_accelerator",
    )
    parser.add_argument("--overlay-intermediate-half-span-mm", type=float, default=2.0)
    parser.add_argument("--upstream-bridge-gem", type=Path)
    parser.add_argument("--upstream-bridge-contract", type=Path)
    parser.add_argument("--accelerator-main-gem", type=Path)
    parser.add_argument("--accelerator-main-contract", type=Path)
    parser.add_argument("--partition-cell-mm-x", type=float)
    parser.add_argument("--partition-cell-mm-y", type=float)
    parser.add_argument("--partition-cell-mm-z", type=float)
    args = parser.parse_args()
    gem, contract = compile_frontend(
        _load(args.upstream),
        _load(args.oatof),
        _load(args.connection),
        cell_mm_xyz={"x": args.cell_mm_x, "y": args.cell_mm_y, "z": args.cell_mm_z},
    )
    args.gem.parent.mkdir(parents=True, exist_ok=True)
    args.contract.parent.mkdir(parents=True, exist_ok=True)
    args.gem.write_text(gem, encoding="utf-8", newline="\n")
    args.contract.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8", newline="\n")
    partition_outputs = (
        args.upstream_bridge_gem,
        args.upstream_bridge_contract,
        args.accelerator_main_gem,
        args.accelerator_main_contract,
    )
    partition_requested = any(value is not None for value in partition_outputs)
    if partition_requested:
        if any(value is None for value in partition_outputs) or any(
            value is None
            for value in (
                args.partition_cell_mm_x,
                args.partition_cell_mm_y,
                args.partition_cell_mm_z,
            )
        ):
            raise ValueError(
                "partitioned PA compilation requires both GEM/contract outputs "
                "and all three partition cell sizes"
            )
        partition_cells = {
            "x": args.partition_cell_mm_x,
            "y": args.partition_cell_mm_y,
            "z": args.partition_cell_mm_z,
        }
        upstream_bridge_gem, upstream_bridge_contract = compile_upstream_bridge(
            _load(args.upstream),
            _load(args.oatof),
            _load(args.connection),
            cell_mm_xyz=partition_cells,
        )
        accelerator_main_gem, accelerator_main_contract = compile_accelerator_main(
            contract,
            _load(args.oatof),
            cell_mm_xyz=partition_cells,
            connection=_load(args.connection),
        )
        for output_path, output in (
            (args.upstream_bridge_gem, upstream_bridge_gem),
            (args.upstream_bridge_contract, json.dumps(upstream_bridge_contract, indent=2) + "\n"),
            (args.accelerator_main_gem, accelerator_main_gem),
            (args.accelerator_main_contract, json.dumps(accelerator_main_contract, indent=2) + "\n"),
        ):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8", newline="\n")
    overlay_requested = args.overlay_gem is not None or args.overlay_contract is not None
    if overlay_requested:
        if args.overlay_gem is None or args.overlay_contract is None or any(
            value is None
            for value in (
                args.overlay_cell_mm_x,
                args.overlay_cell_mm_y,
                args.overlay_cell_mm_z,
            )
        ):
            raise ValueError("accelerator overlay output and all three cell sizes are required")
        overlay_gem, overlay_contract = compile_accelerator_overlay(
            contract,
            cell_mm_xyz={
                "x": args.overlay_cell_mm_x,
                "y": args.overlay_cell_mm_y,
                "z": args.overlay_cell_mm_z,
            },
            region_id=args.overlay_region_id,
            intermediate_half_span_mm=args.overlay_intermediate_half_span_mm,
        )
        args.overlay_gem.parent.mkdir(parents=True, exist_ok=True)
        args.overlay_contract.parent.mkdir(parents=True, exist_ok=True)
        args.overlay_gem.write_text(overlay_gem, encoding="utf-8", newline="\n")
        args.overlay_contract.write_text(
            json.dumps(overlay_contract, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(f"SINGLE_FLIGHT_FRONTEND=PASS GEM={args.gem} CONTRACT={args.contract}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
