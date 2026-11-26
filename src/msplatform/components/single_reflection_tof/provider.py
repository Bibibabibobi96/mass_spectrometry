"""Resolve explicit downstream-only physical design without a solver."""
from __future__ import annotations

import copy
from typing import Any, Mapping
from .geometry import DOWNSTREAM_GEOMETRY_KEYS, resolve_downstream_geometry
from .geometry_members import iter_downstream_members


def resolve_component(design: Mapping[str, Any], *, geometry_profile_id: str | None = None) -> dict:
    """Resolve version 1 downstream data and its mechanical enclosure interface."""
    keys = {"schema_version", "role", "local_frame_id", "geometry_mm", "coordinate_convention", "rings", "electrodes_v"}
    if not isinstance(design, Mapping) or set(design) != keys or type(design["schema_version"]) is not int or design["schema_version"] != 1 or design["role"] != "single_reflection_tof_design":
        raise ValueError("explicit version 1 downstream TOF design required")
    if geometry_profile_id is not None:
        raise ValueError("single reflection TOF has no selectable geometry profile")
    frame = design["local_frame_id"]
    if not isinstance(frame, str) or not frame.strip() or frame != frame.strip():
        raise ValueError("explicit downstream local frame required")
    doc = copy.deepcopy(dict(design))
    if (set(doc["geometry_mm"]) != DOWNSTREAM_GEOMETRY_KEYS or
            set(doc["coordinate_convention"]) != {"reflectron_axis", "detector_x"} or
            set(doc["rings"]) != {"stage1_count", "stage2_count"} or
            set(doc["electrodes_v"]) != {"entgrid", "midgrid", "backplate"}):
        raise ValueError("downstream design fields differ from the declared physical contract")
    axis = doc["coordinate_convention"]["reflectron_axis"]
    if not isinstance(axis, list) or len(axis) != 2:
        raise ValueError("reflectron_axis requires two local coordinates")
    physical = resolve_downstream_geometry(doc["geometry_mm"], doc["coordinate_convention"], doc["rings"], doc["electrodes_v"])
    members = iter_downstream_members(physical, frame=frame)
    groups = {}
    for member in members:
        groups.setdefault(member["electrode_group_id"], member["member_id"])
    g, c = doc["geometry_mm"], doc["coordinate_convention"]
    radius = g["flight_tube_r"] + g["flight_tube_wall"]
    x, y = c["reflectron_axis"]
    dr = g["detector_radius"]
    bounds = {"min": [min(x-radius, c["detector_x"]-dr), min(y-radius, -dr),
                       min(g["shield_outer_z_min"], g["detector_z"]-g["detector_thickness"])],
              "max": [max(x+radius, c["detector_x"]+dr), max(y+radius, dr),
                       max(g["L_flight"] + physical["local_extents"]["reflectron_axial_span_mm"], g["detector_z"])]}
    interface = {"schema_version": 4, "role": "component_geometry_interface", "project_id": "single_reflection_tof",
                 "variant_id": "single_reflection_tof", "geometry_profile_id": None, "local_frame_id": frame,
                 "length_unit": "mm", "ports": {},
                 "component_electrodes": [{"electrode_group_id": group, "role": role} for group, role in groups.items()],
                 "material_bounds_mm": bounds, "vacuum_domains": [physical["vacuum_domain"]]}
    return {"resolved_design": doc, "assembly_interface": interface}
