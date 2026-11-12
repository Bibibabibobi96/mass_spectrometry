"""Complete resolved MR analyzer electrode interface and its actual entry face."""
from __future__ import annotations

import math
from typing import Any

from .geometry_contract import CENTRAL_GROUND_ELECTRODE_ID


def _component_electrodes(resolved: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect actual electrical identities, including shared closure/ground solids."""
    roles: dict[int, str] = {}

    def add(electrode: dict[str, Any], role: str) -> None:
        identity = electrode.get("id")
        if type(identity) is not int or identity <= 0 or identity in roles:
            raise ValueError(f"MR {role} has an invalid or duplicate electrode identity")
        roles[identity] = role

    for group, role in (("mirror_electrodes", "mirror"), ("stripe_electrodes", "stripe"),
                        ("prism_electrodes", "prism"), ("prism_ground_shields", "prism_ground_shield")):
        if not resolved.get(group):
            raise ValueError(f"MR complete analyzer requires {group}")
        for electrode in resolved[group]:
            add(electrode, role)
    if not resolved.get("mirror_e_closures"):
        raise ValueError("MR complete analyzer requires mirror_e_closures")
    closure_ids: set[int] = set()
    for closure in resolved["mirror_e_closures"]:
        identity = closure.get("id")
        if type(identity) is not int or roles.get(identity) != "mirror" or identity in closure_ids:
            raise ValueError("MR mirror closure must share one existing mirror electrode identity")
        closure_ids.add(identity)
    for group in ("central_ground_electrodes", "mirror_ground_shields"):
        if not resolved.get(group):
            raise ValueError(f"MR complete analyzer requires {group}")
    add({"id": CENTRAL_GROUND_ELECTRODE_ID}, "central_ground")
    add(resolved.get("detector", {}), "detector")
    return [{"component_electrode_id": identity, "role": roles[identity]} for identity in sorted(roles)]


def resolve_assembly_interface(
    resolved_geometry: dict[str, Any], *, geometry_profile_id: str | None = None, schema_version: int = 1,
) -> dict[str, Any]:
    """Publish the actual +z slot mouth of the resolved accelerator_exit frame.

    Supports the current single rectangular extrusion with one rectangular
    through-slot and a recessed Prism clearance. It does not approximate other
    CSG topologies by their bounding boxes.
    """
    if type(schema_version) is not int or schema_version not in (1, 3):
        raise ValueError("MR interface requires schema version 1 or 3")
    frame = resolved_geometry.get("frame_id")
    if (resolved_geometry.get("project_id") != "parallel_mirror_dual_stripe_mr_tof"
            or frame != "astral.xyz.reflection_z.drift_y.transverse_x.v2"):
        raise ValueError("MR accelerator_exit frame requires the provider's resolved MR project frame")
    selected = [s for s in resolved_geometry.get("prism_ground_shields", []) if s["station"] == "accelerator_exit"]
    if len(selected) != 1:
        raise ValueError("MR accelerator_exit frame is missing or ambiguous")
    shield = selected[0]
    if (shield["id"] != 18 or shield.get("mechanical_component") != "grounded_1_single_frame"
            or shield.get("topology") != "single_continuous_frame_with_rectangular_slots"
            or len(shield["body_sections"]) != 1 or len(shield["rectangular_slots_mm"]) != 1):
        raise ValueError("MR E18 accelerator_exit requires its single frame body and rectangular slot")
    body = shield["body_sections"][0]
    polygon, x = body["polygon_yz_mm"], body["x"]
    if len(polygon) != 4 or any(len(p) != 2 for p in polygon) or len(x) != 2:
        raise ValueError("MR E18 accelerator_exit body is not a rectangular extrusion")
    slot = shield["rectangular_slots_mm"][0]
    clearance = shield["prism_clearance_polygon_yz_mm"]
    if (len(slot) != 6 or not clearance or any(len(p) != 2 for p in clearance)
            or any(not math.isfinite(v) for v in [*x, *slot, *[v for p in polygon + clearance for v in p]])):
        raise ValueError("MR E18 accelerator_exit body or slot has invalid bounds")
    y0, y1 = min(p[0] for p in polygon), max(p[0] for p in polygon)
    z0, z1 = min(p[1] for p in polygon), max(p[1] for p in polygon)
    if (x[0] >= x[1] or y0 >= y1 or z0 >= z1
            or set(map(tuple, polygon)) != {(y0, z0), (y0, z1), (y1, z0), (y1, z1)}
            or any(a[0] != b[0] and a[1] != b[1] for a, b in zip(polygon, polygon[1:] + polygon[:1]))
            or shield["outer_polygon_yz_mm"] != polygon or shield["x"] != x):
        raise ValueError("MR E18 accelerator_exit body and declared outer face differ")
    if not (x[0] < slot[0] < slot[3] < x[1] and y0 < slot[1] < slot[4] < y1
            and slot[2] <= z0 < z1 == slot[5]
            and max(p[1] for p in clearance) < z1):
        raise ValueError("MR E18 accelerator_exit slot does not reach the actual outer face with a closed rectangular rim")
    electrodes = _component_electrodes(resolved_geometry)
    if schema_version == 3:
        electrodes = _scientific_groups(resolved_geometry, electrodes)
    return {
        "schema_version": schema_version, "role": "component_geometry_interface",
        "project_id": "parallel_mirror_dual_stripe_mr_tof",
        "variant_id": "complete_mr_analyzer", "geometry_profile_id": geometry_profile_id,
        "local_frame_id": frame, "length_unit": "mm",
        "ports": {"accelerator_entry": {
            "surface_kind": "aperture_outer_face",
            "center_mm": [(slot[0] + slot[3]) / 2, (slot[1] + slot[4]) / 2, z1],
            "outward_normal": [0, 0, 1], "wall_thickness_mm": None,
            "cross_section": {"shape": "rectangle", "width_mm": slot[3] - slot[0],
                              "height_mm": slot[4] - slot[1], "width_axis": [1, 0, 0], "height_axis": [0, 1, 0]},
        }},
        "component_electrodes": electrodes,
    }


def _scientific_groups(resolved: dict[str, Any], electrodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project physical order and stations, keeping each distinct conductor."""
    from .resolved_geometry import DUAL_STRIPE_PHYSICAL_INSTANCE_INVARIANT

    mirrors = resolved["mirror_electrodes"]
    if len(mirrors) != 10:
        raise ValueError("MR physical topology requires five mirror layers per side")
    names = {}
    for index, row in enumerate(mirrors):
        side = "positive" if index % 2 == 0 else "negative"
        names[row["id"]] = f"{side}_mirror_layer_{index // 2 + 1}"
    for instance in DUAL_STRIPE_PHYSICAL_INSTANCE_INVARIANT:
        side = "positive" if instance.reflection_axis_sign > 0 else "negative"
        names[instance.electrode_id] = f"{side}_stripe_{instance.set_name}"
    for section, suffix in (("prism_electrodes", "prism"), ("prism_ground_shields", "prism_shield")):
        for row in resolved[section]:
            if row["station"] not in ("accelerator_exit", "central_ground_left"):
                raise ValueError("MR prism station is unsupported")
            names[row["id"]] = f"{row['station']}_{suffix}"
    names[CENTRAL_GROUND_ELECTRODE_ID] = "central_ground"
    names[resolved["detector"]["id"]] = "detector"
    if len(names) != len(electrodes) or set(names) != {row["component_electrode_id"] for row in electrodes}:
        raise ValueError("MR resolved physical members differ from supported complete topology")
    shields = resolved["mirror_ground_shields"]
    if len(shields) != 2 or any(row.get("role") != "inner_stripe_facing_4mm_slot" for row in shields):
        raise ValueError("MR requires one mirror ground shield on each side")
    groups = [{"electrode_group_id": names[row["component_electrode_id"]], "role": row["role"]}
              for row in electrodes]
    groups.extend({"electrode_group_id": f"{side}_mirror_ground_shield", "role": "mirror_ground_shield"}
                  for side in ("positive", "negative"))
    return groups
