"""Provider-owned mechanical interfaces for OA assembly.

All coordinates and dimensions are local millimetres. This interface publishes
geometry and component electrode identities, not voltages, particle handoffs,
clock authority, solver numbering or an assembled-field qualification.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from projects.orthogonal_accelerator.simion.bare_three_zone_component import (
    resolve_bare_three_zone_component,
)
from projects.orthogonal_accelerator.simion.two_zone_candidate import (
    compile_closed_two_zone_accelerator,
)


def _validate_assembly_inputs(
    requirements: Mapping[str, Any], geometry_profile_id: str | None,
) -> str:
    """Validate the identity of the complete provider interface."""
    if not isinstance(requirements, Mapping):
        raise ValueError("assembly requirements must be an object")
    if geometry_profile_id is not None and (
        not isinstance(geometry_profile_id, str) or not geometry_profile_id.strip()
        or geometry_profile_id != geometry_profile_id.strip()
    ):
        raise ValueError("assembly geometry_profile_id must be null or a nonempty trimmed string")
    return str(requirements.get("variant_id"))


def _two_zone_component_electrodes(geometry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Publish the physical identities from one resolved two-zone geometry."""
    roles = [
        (geometry["grounded_enclosure"]["component_electrode_id"], "grounded_shield"),
        (geometry["repeller"]["component_electrode_id"], "repeller"),
        (geometry["grid_supports"][0]["component_electrode_id"], "grid1"),
        (geometry["grid_supports"][1]["component_electrode_id"], "exit_grid"),
        *((ring["component_electrode_id"], "ring") for ring in geometry["rings"]),
    ]
    return [
        {"component_electrode_id": electrode_id, "role": role}
        for electrode_id, role in roles
    ]


def resolve_assembly_interface(
    requirements: Mapping[str, Any], *, geometry_profile_id: str | None,
) -> dict[str, Any]:
    """Compile a schema-1 local mechanical interface from explicit OA inputs.

    The profile selects the existing two-zone geometry; for the explicit
    three-zone geometry it may be null when no named profile exists; a label
    never substitutes for frozen input identity. The side-entry centre lies on
    the outer wall, not its midplane.
    Two-zone geometry publishes its axial exit and any actual side entry;
    three-zone geometry publishes its confirmed side entry only. Invalid inputs
    and unknown variants raise ValueError. No files or inputs are changed.
    """
    variant = _validate_assembly_inputs(requirements, geometry_profile_id)
    if variant == "two_zone":
        if geometry_profile_id is None:
            raise ValueError("two-zone assembly requires an explicit geometry_profile_id")
        resolved = compile_closed_two_zone_accelerator(
            requirements, geometry_profile_id=geometry_profile_id,
        ).resolved_electrodes
        geometry = resolved.to_dict()
        frame = geometry["coordinate_frame"]
        if geometry["acceleration_direction"] != "-z":
            raise ValueError("closed two-zone axial exit must have negative-z acceleration")
        opening = geometry["grounded_enclosure"]["exit_opening_box_mm"]
        x_min, x_max = float(opening["x_min_mm"]), float(opening["x_max_mm"])
        y_min, y_max = float(opening["y_min_mm"]), float(opening["y_max_mm"])
        z_min, z_max = float(opening["z_min_mm"]), float(opening["z_max_mm"])
        ports = {"axial_exit": {
            "surface_kind": "aperture_outer_face",
            "center_mm": [(x_min + x_max) / 2.0, (y_min + y_max) / 2.0, z_min],
            "outward_normal": [0, 0, -1],
            "wall_thickness_mm": z_max - z_min,
            "cross_section": {
                "shape": "rectangle", "width_mm": x_max - x_min, "height_mm": y_max - y_min,
                "width_axis": [1, 0, 0], "height_axis": [0, 1, 0],
            },
        }}
        port = resolved.side_entry
        if port is not None:
            center = list(port["center_mm"])
            center[1] = port["physical_cutout_box_mm"][1]
            ports["side_entry"] = {
                "surface_kind": "aperture_outer_face", "center_mm": center,
                "outward_normal": list(port["normal"]),
                "wall_thickness_mm": resolved.enclosure.guard_wall_mm,
                "cross_section": {
                    "shape": "rectangle", "width_mm": 2 * port["half_width_x_mm"],
                    "height_mm": 2 * port["half_width_z_mm"],
                    "width_axis": [1, 0, 0], "height_axis": [0, 0, 1],
                },
            }
        component_electrodes = _two_zone_component_electrodes(geometry)
    elif variant == "three_zone":
        resolved = resolve_bare_three_zone_component(dict(requirements))
        port = resolved["port"]
        frame = resolved["coordinate_frame"]
        center = list(port["center_mm"])
        center[0] = port["flange_min_mm"]
        ports = {"side_entry": {
            "surface_kind": "aperture_outer_face", "center_mm": center,
            "outward_normal": [-1, 0, 0], "wall_thickness_mm": port["wall_thickness_mm"],
            "cross_section": {
                "shape": "rectangle", "width_mm": port["width_mm"], "height_mm": port["height_mm"],
                "width_axis": [0, 1, 0], "height_axis": [0, 0, 1],
            },
        }}
        electrodes = resolved["electrodes"]
        roles = [
            (electrodes["grounded_shield_id"], "grounded_shield"),
            (electrodes["accelerator_repeller_id"], "repeller"),
            (electrodes["accelerator_grid1_id"], "grid1"),
            (electrodes["accelerator_intermediate2_id"], "intermediate2"),
            (electrodes["accelerator_grid2_id"], "exit_grid"),
            *((electrode_id, "ring") for electrode_id in electrodes["accelerator_ring_ids"]),
        ]
        component_electrodes = [
            {"component_electrode_id": electrode_id, "role": role}
            for electrode_id, role in roles
        ]
    else:
        raise ValueError("assembly interface requires two_zone or three_zone")
    return {
        "schema_version": 1,
        "role": "component_geometry_interface",
        "project_id": "orthogonal_accelerator",
        "variant_id": variant,
        "geometry_profile_id": geometry_profile_id,
        "local_frame_id": frame,
        "length_unit": "mm",
        "ports": ports,
        "component_electrodes": component_electrodes,
    }
