"""Explicit bare-guide adapter for the existing sectioned three-zone provider.

This is a geometry adapter, not a solver or an alternative accelerator model.
All dimensions and ring positions are authored. Existing sectioned rendering
owns the CSG, including its ideal sheets and negative-x side opening.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from projects.orthogonal_accelerator.simion.sectioned_accelerator import render_accelerator_local_geometry

ROLE = "orthogonal_accelerator_bare_three_zone_requirements"
_GEOMETRY_KEYS = {
    "cross_section", "axis_x_mm", "axis_y_mm", "shield_center_z_mm",
    "shield_outer_width_mm", "shield_inner_width_mm", "shield_span_z_mm",
    "negative_x_face_mm", "shield_wall_mm", "shield_back_z_mm",
    "port_center_y_mm", "port_center_z_mm", "numerical_port_width_mm",
    "numerical_port_height_mm", "electrode_width_mm", "bore_width_mm",
    "repeller_front_z_mm", "repeller_thickness_mm", "grid1_z_mm",
    "intermediate2_z_mm", "grid2_z_mm", "ring_count", "ring_thickness_mm", "ring_z_mm",
}


def resolve_bare_three_zone_component(requirements: dict[str, Any]) -> dict[str, Any]:
    """Validate and project explicit sectioned geometry; choose no dimensions."""
    if (not isinstance(requirements, dict) or set(requirements) != {"schema_version", "role", "variant_id", "geometry"}
            or type(requirements["schema_version"]) is not int or requirements["schema_version"] != 1
            or requirements["role"] != ROLE or requirements["variant_id"] != "three_zone"):
        raise ValueError("explicit bare three-zone geometry requirements required")
    g = copy.deepcopy(requirements["geometry"])
    if not isinstance(g, dict) or set(g) != _GEOMETRY_KEYS:
        raise ValueError("complete explicit sectioned three-zone geometry required")
    if g["cross_section"] not in {"square", "cylindrical"}:
        raise ValueError("sectioned three-zone cross section must be square or cylindrical")
    if type(g["ring_count"]) is not int or g["ring_count"] < 1:
        raise ValueError("sectioned ring count must be a positive integer")
    for key in _GEOMETRY_KEYS - {"cross_section", "ring_count", "ring_z_mm"}:
        if isinstance(g[key], bool) or not isinstance(g[key], (int, float)) or not math.isfinite(g[key]):
            raise ValueError("sectioned dimensions must be finite numbers")
    lengths = ("shield_outer_width_mm", "shield_inner_width_mm", "shield_span_z_mm", "shield_wall_mm",
               "numerical_port_width_mm", "numerical_port_height_mm", "electrode_width_mm", "bore_width_mm",
               "repeller_thickness_mm", "ring_thickness_mm")
    if any(g[k] <= 0 for k in lengths):
        raise ValueError("sectioned physical lengths must be positive")
    def equal(a: float, b: float) -> bool:
        return math.isclose(a, b, rel_tol=0., abs_tol=32 * math.ulp(max(1., abs(a), abs(b))))
    if (not equal(g["shield_inner_width_mm"], g["shield_outer_width_mm"] - 2*g["shield_wall_mm"])
            or not equal(g["negative_x_face_mm"], g["axis_x_mm"] - g["shield_outer_width_mm"]/2)
            or not equal(g["shield_span_z_mm"], g["grid2_z_mm"] - g["shield_back_z_mm"])
            or not equal(g["shield_center_z_mm"], (g["grid2_z_mm"] + g["shield_back_z_mm"])/2)):
        raise ValueError("sectioned shield dimensions or side-face registration disagree")
    planes = dict(repeller=g["repeller_front_z_mm"], grid1=g["grid1_z_mm"],
                  intermediate2=g["intermediate2_z_mm"], exit=g["grid2_z_mm"])
    if not all(a < b for a, b in zip(list(planes.values()), list(planes.values())[1:])):
        raise ValueError("sectioned three-zone planes must increase along extraction +z")
    if not (g["bore_width_mm"] < g["electrode_width_mm"] < g["shield_inner_width_mm"]
            and g["shield_back_z_mm"] + g["shield_wall_mm"] < planes["repeller"] - g["repeller_thickness_mm"]):
        raise ValueError("sectioned electrodes require real shield and rear clearance")
    width, height = g["numerical_port_width_mm"], g["numerical_port_height_mm"]
    if (abs(g["port_center_y_mm"] - g["axis_y_mm"]) + width/2 >= g["shield_inner_width_mm"]/2
            or g["port_center_z_mm"] - height/2 <= planes["repeller"]
            or g["port_center_z_mm"] + height/2 >= planes["grid1"]):
        raise ValueError("side entry must fit strictly inside the first gap and lateral cavity")
    rings = g["ring_z_mm"]
    if (not isinstance(rings, list) or len(rings) != g["ring_count"]
            or any(isinstance(z, bool) or not isinstance(z, (int, float)) or not math.isfinite(z) for z in rings)
            or any(a >= b for a, b in zip(rings, rings[1:]))):
        raise ValueError("sectioned ring positions must be explicit, finite and ordered")
    for z in rings:
        interval = ((planes["grid1"], planes["intermediate2"]) if z < planes["intermediate2"]
                    else (planes["intermediate2"], planes["exit"]))
        if not interval[0] < z - g["ring_thickness_mm"]/2 < z + g["ring_thickness_mm"]/2 < interval[1]:
            raise ValueError("sectioned ring metal overlaps an ideal sheet or leaves its zone")
    if any(b-a <= g["ring_thickness_mm"] for a, b in zip(rings, rings[1:])):
        raise ValueError("sectioned rings overlap")
    if not any(z < planes["intermediate2"] for z in rings) or not any(z > planes["intermediate2"] for z in rings):
        raise ValueError("sectioned rings must represent both downstream zones")
    electrodes = dict(grounded_shield_id=1, accelerator_repeller_id=2,
                      accelerator_grid1_id=3, accelerator_intermediate2_id=4,
                      accelerator_grid2_id=5, accelerator_ring_ids=list(range(6, 6+len(rings))))
    half = g["shield_outer_width_mm"]/2
    bounds = dict(x_min=g["axis_x_mm"]-half, x_max=g["axis_x_mm"]+half,
                  y_min=g["axis_y_mm"]-half, y_max=g["axis_y_mm"]+half,
                  z_min=g["shield_back_z_mm"], z_max=planes["exit"])
    cavity = g["shield_inner_width_mm"]/2
    first_gap = dict(x_min=g["axis_x_mm"]-cavity, x_max=g["axis_x_mm"]+cavity,
                     y_min=g["axis_y_mm"]-cavity, y_max=g["axis_y_mm"]+cavity,
                     z_min=planes["repeller"], z_max=planes["grid1"])
    port = dict(normal_axis="x", flange_min_mm=g["negative_x_face_mm"],
                flange_max_mm=g["negative_x_face_mm"]+g["shield_wall_mm"],
                center_mm=[g["negative_x_face_mm"]+g["shield_wall_mm"]/2, g["port_center_y_mm"], g["port_center_z_mm"]],
                width_mm=width, height_mm=height, wall_thickness_mm=g["shield_wall_mm"],
                boolean_boundary_policy="exclude_shape_inside_or_on_v1")
    def box(width: float, z0: float, z1: float) -> dict[str, float]:
        return dict(x_min_mm=g["axis_x_mm"]-width/2, x_max_mm=g["axis_x_mm"]+width/2,
                    y_min_mm=g["axis_y_mm"]-width/2, y_max_mm=g["axis_y_mm"]+width/2,
                    z_min_mm=z0, z_max_mm=z1)
    repeller = dict(component_electrode_id=2,
                    solid_box_mm=box(g["electrode_width_mm"], planes["repeller"]-g["repeller_thickness_mm"], planes["repeller"]))
    sheets = [dict(component_electrode_id=pid, name=name, grid_z_mm=planes[name],
                   sheet_box_mm=box(g["shield_inner_width_mm"] if name == "exit" else g["electrode_width_mm"], planes[name], planes[name]))
              for pid, name in ((3, "grid1"), (4, "intermediate2"), (5, "exit"))]
    return dict(schema_version=1, role="orthogonal_accelerator_sectioned_three_zone_geometry",
                coordinate_frame="sectioned_accelerator_cartesian", acceleration_direction="+z", slow_axis="x",
                geometry=g, electrodes=electrodes, planes=planes, ring_z_mm=list(rings), actual_bounds_mm=bounds,
                port=port, first_gap_bounds_mm=first_gap,
                canonical_electrodes=dict(schema_version=1, coordinate_frame="sectioned_accelerator_cartesian",
                    representation="existing_sectioned_provider__ideal_zero_thickness_sheets",
                    geometry=copy.deepcopy(g), electrodes=copy.deepcopy(electrodes),
                    repeller=repeller, ideal_sheets=sheets,
                    first_gap_bounds_mm=first_gap, first_gap_region="shield_cavity_between_repeller_and_grid1__not_a_support_aperture",
                    generated_entrance_sleeve=False, generated_entrance_plate=False))


def render_bare_three_zone_electrode_body(resolved: dict[str, Any], *, cell_mm_xyz: dict[str, float],
                                          local_electrode_ids: dict[int, int]) -> list[str]:
    """Render the existing provider body in its native frame and explicit namespace."""
    if (not isinstance(resolved, dict) or resolved.get("role") != "orthogonal_accelerator_sectioned_three_zone_geometry"):
        raise ValueError("resolved sectioned three-zone geometry required")
    if set(cell_mm_xyz) != set("xyz") or any(isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v <= 0 for v in cell_mm_xyz.values()):
        raise ValueError("finite positive complete xyz grid required")
    g = resolved["geometry"]
    original = resolved["electrodes"]
    ids = {1, 2, 3, 4, 5, *original["accelerator_ring_ids"]}
    if (set(local_electrode_ids) != ids or any(type(v) is not int or v <= 0 for v in local_electrode_ids.values())
            or len(set(local_electrode_ids.values())) != len(ids)):
        raise ValueError("sectioned component namespace must map every physical electrode exactly once")
    electrodes = {k: [local_electrode_ids[i] for i in v] if isinstance(v, list) else local_electrode_ids[v]
                  for k, v in original.items()}
    return render_accelerator_local_geometry(g, cell_x_mm=cell_mm_xyz["x"], cell_z_mm=cell_mm_xyz["z"],
                                             electrodes=electrodes, render_intermediate2_sheet=True)
