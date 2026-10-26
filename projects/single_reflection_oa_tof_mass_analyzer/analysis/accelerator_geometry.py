"""Resolved oaTOF accelerator solids used by the existing sectioned renderer.

This provider owns the physical envelope and ring placement. Integration owns
connection requests and solver electrode numbering. The projection is the
accelerator portion of an oaTOF assembly, not another OA instance to assemble.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from common.simion.aperture import resolve_rectangular_aperture_discretization


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


@dataclass(frozen=True)
class ResolvedAcceleratorGeometry:
    """One local physical projection; solver aperture rasterization adds no solids."""

    variant_id: str
    local_frame_id: str
    local_region: dict[str, Any]


def resolve_accelerator_geometry(
    oatof: Mapping[str, Any], *, variant_id: str,
) -> ResolvedAcceleratorGeometry:
    """Resolve existing square/cylindrical two/three-zone solids in local mm.

    Input is the already compiled oaTOF geometry, never the ideal longitudinal
    Candidate alone. This pure projection preserves the sectioned renderer's
    dimensions and formulas. Missing/conflicting geometry raises ValueError.
    """
    if oatof.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("accelerator geometry requires resolved oaTOF geometry")
    if oatof.get("coordinate_convention", {}).get("frame_id") != "oatof_global":
        raise ValueError("accelerator geometry requires frame oatof_global")
    try:
        return _resolve_geometry(oatof, variant_id=variant_id)
    except (KeyError, TypeError) as error:
        raise ValueError(f"oaTOF accelerator geometry is incomplete: {error}") from error


def _resolve_geometry(oatof: Mapping[str, Any], *, variant_id: str) -> ResolvedAcceleratorGeometry:
    geometry = oatof["geometry_mm"]
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
    variants = {
        "two_zone_square": (False, "square_3d", "square"),
        "three_zone_square": (True, "square_3d", "square"),
        "two_zone_cylindrical": (False, "cylindrical_3d", "cylindrical"),
        "three_zone_cylindrical": (True, "cylindrical_3d", "cylindrical"),
    }
    if variant_id not in variants:
        raise ValueError(f"unsupported oaTOF accelerator variant: {variant_id}")
    expected_three_zone, realization, cross_section = variants[variant_id]
    if three_zone != expected_three_zone:
        raise ValueError(f"oaTOF accelerator topology conflicts with variant {variant_id}")
    # Existing two-zone resolved geometry predates realization_id and explicitly
    # describes a square body. The caller still selects its variant explicitly.
    declared_realization = accelerator.get("realization_id")
    if declared_realization is not None and declared_realization != realization:
        raise ValueError(f"oaTOF accelerator realization conflicts with variant {variant_id}")
    if declared_realization is None and realization != "square_3d":
        raise ValueError("cylindrical accelerator requires its explicit realization_id")
    ring_count = int(oatof["rings"]["accelerator_count"])
    axis_x = float(oatof["coordinate_convention"]["accelerator_axis_x"])
    axis_y = 0.0
    grid2_z = float(
        accelerator_topology["planes_global_z_mm"]["exit"]
        if three_zone else accelerator["canonical_grid2_z_mm"]
    )
    repeller_front_z = float(
        accelerator_topology["planes_global_z_mm"]["repeller"]
        if three_zone else accelerator["canonical_repeller_z_mm"]
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
    shield_center_z = (shield_back_z + grid2_z) / 2
    shield_span_z = grid2_z - shield_back_z
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
        } or placement["policy_id"] not in {
            "three_zone_zonewise_equal_subdivision_1p4_v1",
            "three_zone_zonewise_equal_subdivision_v1",
        }:
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
            grid1_z + index * (intermediate2_z - grid1_z) / (zone2_ring_count + 1)
            for index in range(1, zone2_ring_count + 1)
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
        "cross_section": cross_section,
        "axis_x_mm": axis_x,
        "axis_y_mm": axis_y,
        "shield_center_z_mm": shield_center_z,
        "shield_outer_width_mm": shield_outer_width,
        "shield_inner_width_mm": shield_inner_width,
        "shield_span_z_mm": shield_span_z,
        "negative_x_face_mm": negative_x_face,
        "shield_wall_mm": shield_wall,
        "shield_back_z_mm": shield_back_z,
        "electrode_width_mm": electrode_width,
        "bore_width_mm": bore_width,
        "repeller_front_z_mm": repeller_front_z,
        "repeller_thickness_mm": repeller_thickness,
        "grid1_z_mm": grid1_z,
        "grid2_z_mm": grid2_z,
        "ring_count": ring_count,
        "ring_z_mm": ring_z_mm,
        "ring_thickness_mm": ring_thickness,
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
                "intermediate2_grid_provider": "accelerator_main",
            }
        )
    if not all(math.isfinite(value) for value in accelerator_local_region.values() if isinstance(value, (int, float))):
        raise ValueError("oaTOF accelerator dimensions must be finite")
    if min(shield_wall, shield_inner_width, shield_span_z, repeller_thickness, ring_thickness) <= 0:
        raise ValueError("oaTOF accelerator solid dimensions must be positive")
    return ResolvedAcceleratorGeometry(variant_id, "oatof_global", accelerator_local_region)
