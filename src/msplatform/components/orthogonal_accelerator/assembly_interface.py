"""OA mechanical ports and scientific groups derived from resolved geometry.

Coordinates and dimensions are local millimetres. No voltage, particle, clock,
solver numbering or assembled-field qualification is created by this module.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from msplatform.contracts.machine_contracts import validate_schema
from .electrode_topology import _mechanical_groups
from .sectioned_geometry import resolve_bare_three_zone_component, validate_standalone_first_gap_port
from .two_zone_geometry import resolve_closed_two_zone_geometry


def _validate_assembly_inputs(requirements: Mapping[str, Any], geometry_profile_id: str | None) -> str:
    if not isinstance(requirements, Mapping):
        raise ValueError("assembly requirements must be an object")
    if geometry_profile_id is not None and (
        not isinstance(geometry_profile_id, str) or not geometry_profile_id.strip()
        or geometry_profile_id != geometry_profile_id.strip()
    ):
        raise ValueError("assembly geometry_profile_id must be null or a nonempty trimmed string")
    return str(requirements.get("variant_id"))


def _two_zone_component_electrodes(geometry: Mapping[str, Any]) -> list[dict[str, Any]]:
    roles = [
        (geometry["grounded_enclosure"]["component_electrode_id"], "grounded_shield"),
        (geometry["repeller"]["component_electrode_id"], "repeller"),
        (geometry["grid_supports"][0]["component_electrode_id"], "grid1"),
        (geometry["grid_supports"][1]["component_electrode_id"], "exit_grid"),
        *((ring["component_electrode_id"], "ring") for ring in geometry["rings"]),
    ]
    return [{"component_electrode_id": electrode_id, "role": role} for electrode_id, role in roles]


def build_assembly_interface(resolved: Mapping[str, Any], *, geometry_profile_id: str | None,
                             schema_version: int = 3) -> dict[str, Any]:
    """Publish current component3 or an explicitly versioned historical data view."""
    if type(schema_version) is not int or schema_version not in (1, 2, 3):
        raise ValueError("assembly interface schema_version must be explicitly 1, 2 or 3")
    if not isinstance(resolved, Mapping):
        raise ValueError("resolved OA geometry must be a mapping")
    variant = resolved.get("variant_id")
    if variant is None and resolved.get("role") == "orthogonal_accelerator_sectioned_three_zone_geometry":
        variant = "three_zone"
    if variant == "two_zone":
        if resolved.get("role") != "orthogonal_accelerator_two_zone_geometry":
            raise ValueError("unknown two-zone resolved geometry")
        if geometry_profile_id is None or resolved.get("geometry_profile_id") != geometry_profile_id:
            raise ValueError("two-zone interface requires its resolved geometry_profile_id")
        frame = "orthogonal_accelerator_exit_origin_v1"
        opening = dict(x_min_mm=-resolved["aperture_half_x_mm"], x_max_mm=resolved["aperture_half_x_mm"],
                       y_min_mm=-resolved["aperture_half_y_mm"], y_max_mm=resolved["aperture_half_y_mm"],
                       z_min_mm=0.0, z_max_mm=resolved["enclosure"]["guard_wall_mm"])
        x_min, x_max = float(opening["x_min_mm"]), float(opening["x_max_mm"])
        y_min, y_max = float(opening["y_min_mm"]), float(opening["y_max_mm"])
        z_min, z_max = float(opening["z_min_mm"]), float(opening["z_max_mm"])
        ports = {"axial_exit": {
            "surface_kind": "aperture_outer_face",
            "center_mm": [(x_min + x_max) / 2.0, (y_min + y_max) / 2.0, z_min],
            "outward_normal": [0, 0, -1],
            "wall_thickness_mm": z_max - z_min,
            "cross_section": {"shape": "rectangle", "width_mm": x_max - x_min, "height_mm": y_max - y_min,
                              "width_axis": [1, 0, 0], "height_axis": [0, 1, 0]},
        }}
        port = resolved["side_entry"]
        if port is not None:
            center = list(port["center_mm"])
            center[1] = port["physical_cutout_box_mm"][1]
            ports["side_entry"] = {
                "surface_kind": "aperture_outer_face", "center_mm": center,
                "outward_normal": list(port["normal"]), "wall_thickness_mm": resolved["enclosure"]["guard_wall_mm"],
                "cross_section": {"shape": "rectangle", "width_mm": 2 * port["half_width_x_mm"],
                                  "height_mm": 2 * port["half_width_z_mm"],
                                  "width_axis": [1, 0, 0], "height_axis": [0, 0, 1]},
            }
        if schema_version == 1:
            component_electrodes = _two_zone_component_electrodes({
                "grounded_enclosure": {"component_electrode_id": 15},
                "repeller": {"component_electrode_id": 22},
                "grid_supports": [{"component_electrode_id": item["id"]} for item in resolved["grid_supports"]],
                "rings": [{"component_electrode_id": item["id"]} for item in resolved["rings"]],
            })
    elif variant == "three_zone":
        if resolved.get("role") != "orthogonal_accelerator_sectioned_three_zone_geometry":
            raise ValueError("three-zone interface requires standalone resolved geometry")
        validate_standalone_first_gap_port(resolved)
        port = resolved["port"]
        frame = resolved["coordinate_frame"]
        center = list(port["center_mm"])
        center[0] = port["flange_min_mm"]
        ports = {"side_entry": {
            "surface_kind": "aperture_outer_face", "center_mm": center,
            "outward_normal": [-1, 0, 0], "wall_thickness_mm": port["wall_thickness_mm"],
            "cross_section": {"shape": "rectangle", "width_mm": port["width_mm"], "height_mm": port["height_mm"],
                              "width_axis": [0, 1, 0], "height_axis": [0, 0, 1]},
        }}
        if schema_version == 1:
            electrodes = resolved["electrodes"]
            roles = [
                (electrodes["grounded_shield_id"], "grounded_shield"),
                (electrodes["accelerator_repeller_id"], "repeller"),
                (electrodes["accelerator_grid1_id"], "grid1"),
                (electrodes["accelerator_intermediate2_id"], "intermediate2"),
                (electrodes["accelerator_grid2_id"], "exit_grid"),
                *((electrode_id, "ring") for electrode_id in electrodes["accelerator_ring_ids"]),
            ]
            component_electrodes = [{"component_electrode_id": electrode_id, "role": role}
                                    for electrode_id, role in roles]
    else:
        raise ValueError("assembly interface requires two_zone or three_zone")
    if schema_version in (2, 3):
        _, groups = _mechanical_groups(resolved)
        if schema_version == 3:
            component_electrodes = [
                {"electrode_group_id": group_id, "role": roles[0]} for group_id, roles, _ in groups
            ]
        else:
            names = {"intermediate_grid_1": "grid1", "intermediate_grid_2": "intermediate2"}
            sheet_role = "grid_support" if variant == "two_zone" else "ideal_zero_thickness_sheet"
            component_electrodes = [
                {"component_electrode_id": names.get(group_id, group_id),
                 "role": sheet_role if group_id in {"intermediate_grid_1", "intermediate_grid_2", "exit_grid"} else roles[0]}
                for group_id, roles, _ in groups
            ]
    result = {
        "schema_version": schema_version, "role": "component_geometry_interface",
        "project_id": "orthogonal_accelerator", "variant_id": variant,
        "geometry_profile_id": geometry_profile_id, "local_frame_id": frame,
        "length_unit": "mm", "ports": ports, "component_electrodes": component_electrodes,
    }
    schema = {1: "component_geometry_interface.schema.json", 2: "component_geometry_interface_v2.schema.json",
              3: "component_geometry_interface_v3.schema.json"}[schema_version]
    validate_schema(result, schema)
    return result


def resolve_assembly_interface(requirements: Mapping[str, Any], *, geometry_profile_id: str | None,
                               schema_version: int = 3,
                               geometry_profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve explicit OA requirements without reading a project or launching tools."""
    variant = _validate_assembly_inputs(requirements, geometry_profile_id)
    if variant == "two_zone":
        if geometry_profile is None:
            raise ValueError("two-zone interface requires explicit geometry_profile content")
        model = resolve_closed_two_zone_geometry(requirements, geometry_profile_id=geometry_profile_id,
                                                geometry_profile=geometry_profile)
        from dataclasses import asdict
        resolved = {**asdict(model), "schema_version": 1, "role": "orthogonal_accelerator_two_zone_geometry",
                    "variant_id": "two_zone", "geometry_profile_id": geometry_profile_id}
    elif variant == "three_zone":
        if geometry_profile is not None or (schema_version == 3 and geometry_profile_id is not None):
            raise ValueError("current three-zone OA rejects profile content that is not a geometric input")
        resolved = resolve_bare_three_zone_component(dict(requirements))
    else:
        raise ValueError("assembly interface requires two_zone or three_zone")
    return build_assembly_interface(resolved, geometry_profile_id=geometry_profile_id, schema_version=schema_version)
