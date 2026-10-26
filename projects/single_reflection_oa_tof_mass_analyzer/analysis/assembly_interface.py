"""Complete provider electrode identity and actual mechanical entry of oaTOF.

Physical IDs come from the provider's final design projection, independently of
native PA domains, solver electrode numbers and numerical detector markers.
"""
from __future__ import annotations

import math

from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_physical_geometry
from typing import Any

from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import (
    ResolvedAcceleratorGeometry,
)


def resolve_assembly_interface(
    resolved: dict[str, Any], *, projection: ResolvedAcceleratorGeometry,
    geometry_profile_id: str | None,
) -> dict[str, Any]:
    """Publish the real outer side face of an already projected square shield.

    Coordinates are in the existing oatof_global frame, in mm. The exact region
    is also consumed by the native renderer; neither its geometry nor its port
    is reconstructed here. Missing ports, curved faces and conflicting geometry
    raise ValueError. No files are read/written and the projection is unchanged.
    """
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
        if (abs(y - float(g["axis_y_mm"])) + width / 2 >= float(g["shield_inner_width_mm"]) / 2
                or z - height / 2 <= float(g["shield_back_z_mm"]) + wall
                or z + height / 2 >= float(g["grid2_z_mm"])):
            raise ValueError("oaTOF side-shield aperture crosses a wall corner or axial end")
    except (KeyError, TypeError) as error:
        raise ValueError(f"oaTOF side-shield rendered projection is incomplete: {error}") from error
    return {
        "schema_version": 1, "role": "component_geometry_interface",
        "project_id": "single_reflection_oa_tof_mass_analyzer",
        "variant_id": projection.variant_id, "geometry_profile_id": geometry_profile_id,
        "local_frame_id": projection.local_frame_id, "length_unit": "mm",
        "ports": {"side_entry": {
            "surface_kind": "aperture_outer_face", "center_mm": [face, y, z],
            "outward_normal": [-1, 0, 0], "wall_thickness_mm": wall,
            "cross_section": {"shape": "rectangle", "width_mm": width, "height_mm": height,
                              "width_axis": [0, 1, 0], "height_axis": [0, 0, 1]},
        }},
        "component_electrodes": [
            {key: item[key] for key in ("component_electrode_id", "role", "electrical_group_id")}
            for item in resolve_physical_geometry(resolved, accelerator_projection=projection)["electrodes"]
        ],
    }
