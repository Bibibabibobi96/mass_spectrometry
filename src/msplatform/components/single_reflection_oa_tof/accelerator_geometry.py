"""Resolved oaTOF accelerator solids used by the existing sectioned renderer.

This provider owns the physical envelope and ring placement. Integration owns
connection requests and solver electrode numbering. The projection is the
accelerator portion of an oaTOF assembly, not another OA instance to assemble.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import math
from typing import Any, Mapping





@dataclass(frozen=True)
class ResolvedAcceleratorGeometry:
    """One local physical projection; solver aperture rasterization adds no solids."""

    variant_id: str
    local_frame_id: str
    local_region: dict[str, Any]


def _resolve_side_entry_port(
    projection: ResolvedAcceleratorGeometry, *, geometry_profile_id: str | None,
) -> dict[str, Any]:
    """Validate and publish the existing instrument wall opening once."""
    if projection.local_frame_id != "oatof_global":
        raise ValueError("oaTOF side-shield interface requires frame oatof_global")
    if projection.variant_id not in {"two_zone_square", "three_zone_square"}:
        raise ValueError(f"oaTOF side-shield planar interface does not support {projection.variant_id}")
    if geometry_profile_id is not None and (not isinstance(geometry_profile_id, str) or not geometry_profile_id.strip()):
        raise ValueError("geometry_profile_id must be null or a nonempty string")
    g = projection.local_region
    try:
        aperture = g["accelerator_port_aperture_discretization"]
        face, wall = float(g["negative_x_face_mm"]), float(g["shield_wall_mm"])
        y, z = float(g["port_center_y_mm"]), float(g["port_center_z_mm"])
        width, height = float(aperture["mechanical_width_mm"]), float(aperture["mechanical_height_mm"])
        outer_face = float(g["axis_x_mm"]) - float(g["shield_outer_width_mm"]) / 2
        inner_face = float(g["axis_x_mm"]) - float(g["shield_inner_width_mm"]) / 2
        actual = (face, face + wall, aperture["flange_min_mm"], aperture["flange_max_mm"],
                  aperture["center_mm"]["x"], aperture["center_mm"]["y"], aperture["center_mm"]["z"])
        expected = (outer_face, inner_face, face, face + wall, (face + face + wall) / 2, y, z)
        if g["cross_section"] != "square" or aperture["normal_axis"] != "x" or any(
            not math.isclose(a, b, rel_tol=0, abs_tol=1e-9) for a, b in zip(actual, expected)
        ):
            raise ValueError("oaTOF side-shield aperture does not traverse its actual outer and inner walls")
        if not all(math.isfinite(value) and value > 0 for value in (wall, width, height)):
            raise ValueError("oaTOF side-shield aperture dimensions must be finite and positive")
        # An aperture extending past a corner/end is a different solid topology.
        from msplatform.components.orthogonal_accelerator.sectioned_geometry import validate_sectioned_wall_opening
        physical_opening = dict(port_center_y_mm=y, port_center_z_mm=z,
            numerical_port_width_mm=width, numerical_port_height_mm=height,
            axis_y_mm=float(g["axis_y_mm"]), shield_inner_width_mm=float(g["shield_inner_width_mm"]),
            shield_back_z_mm=float(g["shield_back_z_mm"]), shield_wall_mm=wall, grid2_z_mm=float(g["grid2_z_mm"]))
        try:
            validate_sectioned_wall_opening(physical_opening)
        except ValueError as error:
            raise ValueError("oaTOF side-shield aperture crosses a wall corner or axial end") from error
    except (KeyError, TypeError) as error:
        raise ValueError(f"oaTOF side-shield rendered projection is incomplete: {error}") from error
    return {
            "surface_kind": "aperture_outer_face", "center_mm": [face, y, z],
            "outward_normal": [-1, 0, 0], "wall_thickness_mm": wall,
            "cross_section": {"shape": "rectangle", "width_mm": width, "height_mm": height,
                              "width_axis": [0, 1, 0], "height_axis": [0, 0, 1]},
        }


def resolve_oa_provider(
    oatof_resolved: Mapping[str, Any], *, projection: ResolvedAcceleratorGeometry,
    geometry_profile_id: str | None,
) -> dict[str, Any]:
    """Compile the actual three-zone square portion with the OA provider.

    The axes are aligned, but their frame labels retain their provider meaning.
    Mechanical port dimensions come from the aperture's physical inputs, never
    its mesh carve. This boundary does not support the legacy two-zone model.
    """
    from msplatform.components.orthogonal_accelerator.sectioned_geometry import (
        SECTIONED_GEOMETRY_FIELDS, project_instrument_sectioned_mechanics,
    )
    from msplatform.components.single_reflection_oa_tof.accelerator_electrical import (
        resolve_accelerator_electrical_design,
    )

    if projection.variant_id != "three_zone_square" or projection.local_frame_id != "oatof_global":
        raise ValueError("OA provider projection supports only three_zone_square in oatof_global")
    expected = resolve_accelerator_geometry(oatof_resolved, variant_id=projection.variant_id)
    # The explicit opening is applied after the provider's physical body projection.
    if any(projection.local_region.get(key) != value for key, value in expected.local_region.items()):
        raise ValueError("OA provider projection differs from the resolved physical body")
    try:
        geometry = {key: copy.deepcopy(projection.local_region[key]) for key in SECTIONED_GEOMETRY_FIELDS}
        aperture = projection.local_region["accelerator_port_aperture_discretization"]
        geometry["numerical_port_width_mm"] = aperture["mechanical_width_mm"]
        geometry["numerical_port_height_mm"] = aperture["mechanical_height_mm"]
    except (KeyError, TypeError) as error:
        raise ValueError("OA provider requires an explicit physical side opening") from error
    # Reuse the instrument's complete existing wall/port guard. Its opening is
    # not the standalone OA component's stricter first-gap capability.
    port = _resolve_side_entry_port(projection, geometry_profile_id=geometry_profile_id)
    source = dict(schema_version=1, role="oatof_validated_sectioned_accelerator_geometry",
                  producer="single_reflection_oa_tof_mass_analyzer", frame_id="oatof_global", geometry=geometry)
    mechanical = project_instrument_sectioned_mechanics(source)
    electrical = resolve_accelerator_electrical_design(
        oatof_resolved, variant_id=projection.variant_id, geometry_projection=projection, schema_version=2,
    )
    return dict(schema_version=1, role="oatof_oa_provider_projection", source=source,
                mechanical=mechanical, ports={"side_entry": port}, electrical=electrical,
                frame_transform=dict(from_frame="sectioned_accelerator_cartesian", to_frame="oatof_global",
                    rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], translation_mm=[0, 0, 0]))


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


def apply_side_opening(projection: ResolvedAcceleratorGeometry, *, side_opening: Mapping[str, Any]) -> ResolvedAcceleratorGeometry:
    """Return the actual mechanical wall opening without a solver mesh carve.

    The physical aperture view has no native labels, cell sizes or raster bounds.
    A backend may add its own discretization from these same mechanical inputs.
    """
    if set(side_opening) != {"center_mm", "width_mm", "height_mm"}:
        raise ValueError("side opening requires center_mm, width_mm and height_mm")
    center = side_opening["center_mm"]
    if not isinstance(center, (list, tuple)) or len(center) != 3:
        raise ValueError("side opening center_mm must have three coordinates")
    x, y, z = map(float, center)
    width, height = float(side_opening["width_mm"]), float(side_opening["height_mm"])
    g = copy.deepcopy(projection.local_region)
    face, wall = float(g["negative_x_face_mm"]), float(g["shield_wall_mm"])
    if not all(math.isfinite(value) for value in (x, y, z, width, height)) or min(width, height) <= 0:
        raise ValueError("side opening must have finite coordinates and positive dimensions")
    if not math.isclose(x, face, rel_tol=0, abs_tol=1e-9):
        raise ValueError("side opening must lie on the actual outer wall")
    g.update(port_center_y_mm=y, port_center_z_mm=z,
        numerical_port_width_mm=width, numerical_port_height_mm=height,
        accelerator_port_aperture_discretization=dict(mechanical_width_mm=width, mechanical_height_mm=height,
            normal_axis="x", flange_min_mm=x, flange_max_mm=x+wall,
            center_mm=dict(x=(x+x+wall)/2, y=y, z=z)))
    result = ResolvedAcceleratorGeometry(projection.variant_id, projection.local_frame_id, g)
    _resolve_side_entry_port(result, geometry_profile_id=None)
    return result
