"""Mechanical interfaces of the native guide inlet and LP extraction shield.

Consume the provider's resolved CSG in its native local frame. No geometry,
voltages, particle observations or solver electrode numbering are generated.
"""
from __future__ import annotations

import math
from typing import Any

from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import _guide_solids


def _guide_inlet_port(native_projection: dict[str, Any]) -> dict[str, Any]:
    """Publish the actual upstream ends of the native guide's eight rods.

    This open rod envelope is neither a plate aperture nor a particle cut. The
    HP entrance lens lies downstream and is not the entrance of the full IP.
    """
    rods = _guide_solids(native_projection)
    first = rods[0]
    x = first["x_min_mm"]
    radius = math.hypot(first["center_y_mm"], first["center_z_mm"]) - first["radius_mm"]
    if len({(rod["center_y_mm"], rod["center_z_mm"]) for rod in rods}) != len(rods):
        raise ValueError("IP guide inlet requires distinct physical rods")
    if radius <= 0 or any(
        rod["x_min_mm"] != x or rod["x_max_mm"] <= x or rod["x_max_mm"] != first["x_max_mm"]
        or not math.isclose(math.hypot(rod["center_y_mm"], rod["center_z_mm"])
                            - rod["radius_mm"], radius, rel_tol=0, abs_tol=1e-12)
        for rod in rods
    ):
        raise ValueError("IP guide inlet requires a common circular open rod end")
    return dict(surface_kind="open_rod_entrance", center_mm=[x, 0., 0.],
        outward_normal=[-1, 0, 0], wall_thickness_mm=None,
        cross_section=dict(shape="open_rod_envelope", inscribed_radius_mm=radius))


def _box(shape: dict[str, Any]) -> tuple[list, list]:
    if shape.get("shape") != "box":
        raise ValueError("IP E14 extraction shield requires resolved box solids and cutout")
    low, high = shape["min_mm"], shape["max_mm"]
    if (len(low) != 3 or len(high) != 3
            or any(not math.isfinite(v) for v in [*low, *high])
            or any(a >= b for a, b in zip(low, high, strict=True))):
        raise ValueError("IP E14 extraction shield has invalid box bounds")
    return low, high


def _extraction_exit_port(native_projection: dict[str, Any]) -> dict[str, Any]:
    """Publish the +y outer opening of the single E14 shield in native mm.

    The current provider represents this continuous shield by four box walls
    and one rectangular extraction subtraction. Other topologies are rejected.
    """
    selected = [e for e in native_projection.get("electrodes", []) if e["electrode_id"] == 14]
    if len(selected) != 1:
        raise ValueError("IP E14 extraction shield is missing or ambiguous")
    shield = selected[0]
    if (shield.get("name") != "lp_commonmode_shield"
            or len(shield["solids"]) != 4 or len(shield["cutouts"]) != 1):
        raise ValueError("IP E14 extraction shield requires its four walls and one cutout")
    solids = [_box(shape) for shape in shield["solids"]]
    outer_y = max(high[1] for _, high in solids)
    walls = [(low, high) for low, high in solids if high[1] == outer_y]
    if len(walls) != 1:
        raise ValueError("IP E14 extraction outer wall is ambiguous")
    low, high = walls[0]
    cut_low, cut_high = _box(shield["cutouts"][0])
    if not (cut_low[1] <= low[1] < high[1] <= cut_high[1]
            and all(low[a] < cut_low[a] < cut_high[a] < high[a] for a in (0, 2))):
        raise ValueError("IP E14 extraction cutout does not pass through the outer wall with a closed rim")
    return {
            "surface_kind": "aperture_outer_face",
            "center_mm": [(cut_low[0] + cut_high[0]) / 2, outer_y, (cut_low[2] + cut_high[2]) / 2],
            "outward_normal": [0, 1, 0], "wall_thickness_mm": high[1] - low[1],
            "cross_section": {
                "shape": "rectangle", "width_mm": cut_high[2] - cut_low[2],
                "height_mm": cut_high[0] - cut_low[0],
                "width_axis": [0, 0, -1], "height_axis": [1, 0, 0],
            },
    }


def resolve_assembly_interface(
    native_projection: dict[str, Any], *, geometry_profile_id: str | None = None,
) -> dict[str, Any]:
    """Publish both ports and the provider's named electrode assemblies.

    Electrode IDs retain the native provider objects and their electrical groups.
    A multi-solid object is not split into new electrodes or SIMION PA numbers.
    """
    frame = native_projection.get("frame_id")
    if (frame != "dual_pressure_ion_processor_local_v1"
            or native_projection.get("length_unit") != "mm"
            or native_projection.get("role") != "native_electrode_geometry_projection"):
        raise ValueError("IP assembly requires the provider native local frame and mm projection")
    electrodes = sorted(native_projection["electrodes"], key=lambda item: item["electrode_id"])
    ids = [item["electrode_id"] for item in electrodes]
    if len(ids) != len(set(ids)):
        raise ValueError("IP assembly electrode identities are ambiguous")
    if not {1, 2, 14}.issubset(ids):
        raise ValueError("IP assembly requires the guide rods and extraction shield")
    return dict(schema_version=1, role="component_geometry_interface",
        project_id="dual_pressure_rectilinear_ion_processor", variant_id="native_ion_processor",
        geometry_profile_id=geometry_profile_id, local_frame_id=frame, length_unit="mm",
        ports=dict(guide_inlet=_guide_inlet_port(native_projection),
                   extraction_exit=_extraction_exit_port(native_projection)),
        component_electrodes=[dict(component_electrode_id=item["electrode_id"], role=item["name"],
                                   electrical_group_id=item["electrode_id"]) for item in electrodes])
