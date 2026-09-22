"""Render the owned closed-end two-zone accelerator PA geometry.

An instrument supplies its frozen placement, mesh, and interface envelope as a
plain specification.  This component owns all electrode topology: a solid
repeller, a closed positive-z grounded cap, the negative-z exit grid, grid1,
and the interior acceleration rings.  Consumers cannot select an alternate
end topology through this API.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
    ShieldedRectangularEnclosure,
    TwoZoneGeometryError,
    derive_shielded_rectangular_enclosure,
    derive_uniform_ring_planes,
)
from projects.orthogonal_accelerator.simion.rectangular_accelerator import (
    emit_closed_two_zone_endplates,
    emit_ideal_grid,
    emit_open_rectangular_frame,
)


def _number(value: float) -> str:
    numeric = float(value)
    if numeric != numeric or abs(numeric) == float("inf"):
        raise TwoZoneGeometryError("accelerator GEM value must be finite")
    return f"{numeric:.12g}"


@dataclass(frozen=True)
class CompiledTwoZoneLayout:
    """Provider-owned geometry facts that consumers may serialize and validate."""

    geometry_profile_id: str
    acceleration_direction: str
    local_exit_z_mm: float
    local_repeller_z_mm: float
    gap_1_mm: float
    gap_2_mm: float
    ring_centers_z_mm: tuple[float, ...]
    source_center_z_mm: float
    source_z_minimum_mm: float
    source_z_maximum_mm: float
    source_cylinder_radius_mm: float
    source_cylinder_height_mm: float
    aperture_width_x_mm: float
    aperture_height_y_mm: float
    static_minimum_y_extent_mm: float
    static_axial_length_mm: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable projection without exposing geometry inputs."""
        return {
            "geometry_profile_id": self.geometry_profile_id,
            "acceleration_direction": self.acceleration_direction,
            "local_exit_z_mm": self.local_exit_z_mm,
            "local_repeller_z_mm": self.local_repeller_z_mm,
            "gap_1_mm": self.gap_1_mm,
            "gap_2_mm": self.gap_2_mm,
            "ring_centers_z_mm": list(self.ring_centers_z_mm),
            "source_center_z_mm": self.source_center_z_mm,
            "source_z_minimum_mm": self.source_z_minimum_mm,
            "source_z_maximum_mm": self.source_z_maximum_mm,
            "source_cylinder": {
                "radius_mm": self.source_cylinder_radius_mm,
                "height_mm": self.source_cylinder_height_mm,
            },
            "aperture_width_x_mm": self.aperture_width_x_mm,
            "aperture_height_y_mm": self.aperture_height_y_mm,
            "static_minimum_y_extent_mm": self.static_minimum_y_extent_mm,
            "static_axial_length_mm": self.static_axial_length_mm,
        }


@dataclass(frozen=True)
class CompiledTwoZoneAccelerator:
    """Closed-end local PA and its provider-owned resolved geometry."""

    gem: str
    local_exit_z_mm: float
    local_repeller_z_mm: float
    source_cylinder_radius_mm: float
    source_cylinder_height_mm: float
    source_center_z_mm: float
    static_minimum_y_extent_mm: float
    static_axial_length_mm: float
    layout: CompiledTwoZoneLayout


_REQUIRED_REQUEST_KEYS = {
    "schema_version", "role", "variant_id", "acceleration_direction", "source_cylinder",
    "focus", "compaction", "local_pa", "placement",
}

# This is the component's current prototype geometry profile, rather than a
# consumer-selected design.  Its dimensions have not received field/trajectory
# qualification; the compiler can prove containment and the declared finite
# envelope only.
_CLOSED_TWO_ZONE_PROFILE_ID = "closed_two_zone_compact_mr_axial_r3_gap1_4mm"
_GEOMETRY_PROFILE_KEYS = {
    "gap_1_mm", "gap_2_mm", "ring_count", "ring_thickness_z_mm",
    "aperture_width_x_mm", "aperture_height_y_mm", "electrode_outer_width_x_mm",
    "electrode_outer_height_y_mm", "guard_outer_width_x_mm", "guard_outer_height_y_mm",
    "guard_wall_thickness_mm", "lateral_clearance_mm", "repeller_thickness_z_mm", "rear_gap_mm",
}


def _load_geometry_profile(profile_id: str = _CLOSED_TWO_ZONE_PROFILE_ID) -> Mapping[str, float | int]:
    """Load the sole component-owned physical profile from its frozen contract."""
    path = Path(__file__).parents[1] / "config" / "component_contract.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        profiles = document["geometry_profiles"]
        profile = profiles[profile_id]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise TwoZoneGeometryError("closed two-zone geometry profile is unavailable") from error
    if not isinstance(profile, Mapping) or set(profile) != _GEOMETRY_PROFILE_KEYS:
        raise TwoZoneGeometryError("closed two-zone geometry profile has missing or unknown fields")
    values: dict[str, float | int] = {}
    for key, value in profile.items():
        if key == "ring_count":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise TwoZoneGeometryError("closed two-zone ring_count must be a positive integer")
            values[key] = value
        else:
            values[key] = _finite_positive(value, f"closed two-zone profile.{key}")
    return values


def _mapping(value: Any, label: str, expected: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise TwoZoneGeometryError(f"{label} has missing or unknown fields")
    return value


def _finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise TwoZoneGeometryError(f"{label} must be finite and positive")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise TwoZoneGeometryError(f"{label} must be finite and positive") from error
    if not isfinite(result) or result <= 0.0:
        raise TwoZoneGeometryError(f"{label} must be finite and positive")
    return result


def _triple(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise TwoZoneGeometryError(f"{label} must contain three values")
    return tuple(_finite_positive(item, label) for item in value)  # type: ignore[return-value]


def compile_closed_two_zone_accelerator(requirements: Mapping[str, Any], *, geometry_profile_id: str = _CLOSED_TWO_ZONE_PROFILE_ID) -> CompiledTwoZoneAccelerator:
    """Compile the fixed closed-end two-zone topology from a consumer request.

    The request contains interface envelope, placement and source requirements.
    It deliberately has no electrode-shape, end-cap, grid-support or ring-plane
    fields: this provider derives those structures and rejects every topology
    other than a solid positive-z repeller/rear cap with a negative-z exit grid.
    """
    request = _mapping(requirements, "two-zone accelerator requirements", _REQUIRED_REQUEST_KEYS)
    geometry = _load_geometry_profile(geometry_profile_id)
    if (request["schema_version"] != 1
            or request["role"] != "orthogonal_accelerator_two_zone_requirements"
            or request["variant_id"] != "two_zone"
            or request["acceleration_direction"] != "-z"):
        raise TwoZoneGeometryError("requirements do not select the owned closed-end -z two-zone accelerator")
    source = _mapping(request["source_cylinder"], "source_cylinder", {"radius_mm", "height_mm"})
    radius = _finite_positive(source["radius_mm"], "source_cylinder.radius_mm")
    height = _finite_positive(source["height_mm"], "source_cylinder.height_mm")
    focus = _mapping(request["focus"], "focus", {"mode", "focus_plane"})
    if focus["mode"] != "two_zone_time_focus" or not isinstance(focus["focus_plane"], str) or not focus["focus_plane"]:
        raise TwoZoneGeometryError("requirements must declare a named two-zone time-focus plane")
    compaction = _mapping(request["compaction"], "compaction", {"axes", "objective"})
    if compaction["axes"] != ["y", "z"] or compaction["objective"] != "minimize_subject_to_focus":
        raise TwoZoneGeometryError("requirements must retain y/z compaction subject to focus")
    local = _mapping(request["local_pa"], "local_pa", {"span_mm", "mesh_mm_per_gu", "exit_z_mm", "margin_z_mm"})
    span = _triple(local["span_mm"], "local_pa.span_mm")
    mesh = _triple(local["mesh_mm_per_gu"], "local_pa.mesh_mm_per_gu")
    exit_z = _finite_positive(local["exit_z_mm"], "local_pa.exit_z_mm")
    margin_z = _finite_positive(local["margin_z_mm"], "local_pa.margin_z_mm")
    gap_1 = float(geometry["gap_1_mm"])
    gap_2 = float(geometry["gap_2_mm"])
    ring_count = int(geometry["ring_count"])
    ring_thickness = float(geometry["ring_thickness_z_mm"])
    aperture_x = float(geometry["aperture_width_x_mm"]) / 2.0
    aperture_y = float(geometry["aperture_height_y_mm"]) / 2.0
    # The local axial convention rises from the negative-z exit to the positive-z
    # repeller.  The first acceleration gap is therefore the interval above
    # grid1, not the interval adjacent to the exit.  Keep ``source_in_gap_1``
    # in the theory convention (distance from the repeller towards the exit),
    # then convert it once into the provider's exit-origin coordinate.
    source_in_gap_1 = gap_1 / 2.0
    if source_in_gap_1 - radius <= 0.0 or source_in_gap_1 + radius >= gap_1:
        raise TwoZoneGeometryError("provider first gap cannot contain the requested cylindrical source in z")
    source_center_z = gap_2 + gap_1 - source_in_gap_1
    if aperture_x < radius or aperture_y < max(radius, height / 2.0):
        raise TwoZoneGeometryError("provider aperture cannot contain the requested cylindrical source")
    repeller_thickness = float(geometry["repeller_thickness_z_mm"])
    repeller_z = exit_z + gap_2 + gap_1
    enclosure = derive_shielded_rectangular_enclosure(
        electrode_outer_width_x_mm=float(geometry["electrode_outer_width_x_mm"]),
        electrode_outer_height_y_mm=float(geometry["electrode_outer_height_y_mm"]),
        guard_outer_width_x_mm=float(geometry["guard_outer_width_x_mm"]),
        guard_outer_height_y_mm=float(geometry["guard_outer_height_y_mm"]),
        guard_wall_thickness_mm=float(geometry["guard_wall_thickness_mm"]),
        lateral_clearance_mm=float(geometry["lateral_clearance_mm"]),
        repeller_z_mm=repeller_z, repeller_thickness_z_mm=repeller_thickness,
        rear_gap_mm=float(geometry["rear_gap_mm"]),
    )
    if 2.0 * enclosure.guard_half_x_mm > span[0] or 2.0 * enclosure.guard_half_y_mm > span[1]:
        raise TwoZoneGeometryError("local PA transverse span cannot enclose the grounded accelerator")
    placement = _mapping(request["placement"], "placement", {"focus_y_mm", "global_repeller_z_mm", "global_exit_z_mm"})
    focus_y = float(placement["focus_y_mm"])
    global_repeller_z = float(placement["global_repeller_z_mm"])
    global_exit_z = float(placement["global_exit_z_mm"])
    if not all(isfinite(value) for value in (focus_y, global_repeller_z, global_exit_z)):
        raise TwoZoneGeometryError("placement values must be finite")
    if abs(global_repeller_z - global_exit_z - gap_1 - gap_2) > 1e-9:
        raise TwoZoneGeometryError("placement must preserve the provider-owned repeller-to-exit separation")
    local_offset_z = exit_z - global_exit_z
    layout = derive_uniform_ring_planes(
        global_exit_z + gap_2, global_exit_z, ring_count, ring_thickness_mm=ring_thickness
    )
    local_ids = {15: 1, 22: 2, 23: 3, 24: 4, **{26 + index: 5 + index for index in range(ring_count)}}
    grid_supports = (
        {"id": 23, "grid_z_mm": global_exit_z + gap_2,
         "front_z_mm": global_exit_z + gap_2 - ring_thickness / 2.0,
         "back_z_mm": global_exit_z + gap_2 + ring_thickness / 2.0, "thickness_z_mm": ring_thickness,
         "outer_half_x_mm": enclosure.electrode_half_x_mm, "outer_half_y_mm": enclosure.electrode_half_y_mm,
         "aperture_half_x_mm": aperture_x, "aperture_half_y_mm": aperture_y},
        {"id": 24, "grid_z_mm": global_exit_z, "front_z_mm": global_exit_z - ring_thickness / 2.0,
         "back_z_mm": global_exit_z + ring_thickness / 2.0, "thickness_z_mm": ring_thickness,
         "outer_half_x_mm": enclosure.guard_inner_half_x_mm, "outer_half_y_mm": enclosure.guard_inner_half_y_mm,
         "aperture_half_x_mm": aperture_x, "aperture_half_y_mm": aperture_y},
    )
    rings = tuple({"id": 26 + index, "center_z_mm": center, "thickness_z_mm": ring_thickness}
                  for index, center in enumerate(layout.centers_mm))
    gem = render_closed_two_zone_local_pa(
        span_mm=span, mesh_mm_per_gu=mesh, local_exit_z_mm=exit_z, local_repeller_z_mm=repeller_z,
        focus_y_mm=focus_y, global_repeller_z_mm=global_repeller_z, enclosure=enclosure,
        repeller_thickness_mm=repeller_thickness, aperture_half_x_mm=aperture_x,
        aperture_half_y_mm=aperture_y, local_margin_z_mm=margin_z,
        grid_support_frames=grid_supports, stage_2_rings=rings, local_electrode_ids=local_ids,
        global_exit_z_mm=global_exit_z,
    )
    static_y_extent = 2.0 * enclosure.guard_half_y_mm
    static_axial_length = enclosure.rear_cap_outer_z_mm - exit_z
    resolved_layout = CompiledTwoZoneLayout(
        geometry_profile_id, "-z", exit_z, repeller_z, gap_1, gap_2,
        tuple(center + local_offset_z for center in layout.centers_mm), source_center_z + exit_z,
        source_center_z - radius + exit_z, source_center_z + radius + exit_z,
        radius, height, 2.0 * aperture_x, 2.0 * aperture_y,
        static_y_extent, static_axial_length,
    )
    return CompiledTwoZoneAccelerator(
        gem, exit_z, repeller_z, radius, height, source_center_z,
        static_y_extent, static_axial_length, resolved_layout,
    )


def render_closed_two_zone_local_pa(
    *, span_mm: Sequence[float], mesh_mm_per_gu: Sequence[float],
    local_exit_z_mm: float, local_repeller_z_mm: float, focus_y_mm: float, global_repeller_z_mm: float,
    enclosure: ShieldedRectangularEnclosure, repeller_thickness_mm: float,
    aperture_half_x_mm: float, aperture_half_y_mm: float,
    local_margin_z_mm: float, grid_support_frames: Sequence[Mapping[str, Any]],
    stage_2_rings: Sequence[Mapping[str, Any]], local_electrode_ids: Mapping[int, int],
    global_exit_z_mm: float,
) -> str:
    """Render one complete local two-zone accelerator PA from frozen inputs."""
    if len(span_mm) != 3 or len(mesh_mm_per_gu) != 3:
        raise TwoZoneGeometryError("accelerator PA span and mesh must each have three values")
    span_x, span_y, span_z = (float(value) for value in span_mm)
    mesh_x, mesh_y, mesh_z = (float(value) for value in mesh_mm_per_gu)
    if min(span_x, span_y, span_z, mesh_x, mesh_y, mesh_z) <= 0.0:
        raise TwoZoneGeometryError("accelerator PA span and mesh must be positive")
    if not (0.0 < aperture_half_x_mm < enclosure.electrode_half_x_mm and
            0.0 < aperture_half_y_mm < enclosure.electrode_half_y_mm):
        raise TwoZoneGeometryError("accelerator aperture must retain electrode material")
    ground_id, repeller_id = int(local_electrode_ids[15]), int(local_electrode_ids[22])
    local_repeller = float(local_repeller_z_mm)
    if local_repeller <= local_exit_z_mm:
        raise TwoZoneGeometryError("local repeller must remain behind the negative-z exit")
    endplates = emit_closed_two_zone_endplates(
        grounded_id=ground_id, repeller_id=repeller_id, enclosure=enclosure,
        exit_z_mm=float(local_exit_z_mm), repeller_front_z_mm=local_repeller,
        repeller_back_z_mm=local_repeller + float(repeller_thickness_mm),
        repeller_half_x_mm=enclosure.electrode_half_x_mm,
        repeller_half_y_mm=enclosure.electrode_half_y_mm,
    )
    if enclosure.rear_cap_outer_z_mm + float(local_margin_z_mm) > span_z + 1e-9:
        raise TwoZoneGeometryError("accelerator local PA z span does not enclose both endplates and margins")
    offset_z = float(local_exit_z_mm) - float(global_exit_z_mm)
    lines = [
        "; Local closed-end two-zone accelerator PA generated by orthogonal_accelerator; local +z is project +z.",
        f"; global repeller z={_number(global_repeller_z_mm)} mm; global focus=(0,{_number(focus_y_mm)},0) mm.",
        f"# local contract_mmgu_x, contract_mmgu_y, contract_mmgu_z = {_number(mesh_x)}, {_number(mesh_y)}, {_number(mesh_z)}",
        "# local mmgu_x = _G.var and _G.var.mmgu_x or contract_mmgu_x",
        "# local mmgu_y = _G.var and _G.var.mmgu_y or contract_mmgu_y",
        "# local mmgu_z = _G.var and _G.var.mmgu_z or contract_mmgu_z",
        "# assert(mmgu_x == contract_mmgu_x and mmgu_y == contract_mmgu_y and mmgu_z == contract_mmgu_z, 'runtime mesh must equal frozen accelerator component contract')",
        f"# local x_span, y_span, z_span = {_number(span_x)}, {_number(span_y)}, {_number(span_z)}",
        "# local nx = math.floor(x_span/mmgu_x + 0.5) + 1",
        "# local ny = math.floor(y_span/mmgu_y + 0.5) + 1",
        "# local nz = math.floor(z_span/mmgu_z + 0.5) + 1",
        "pa_define($(nx),$(ny),$(nz),planar,none,electrostatic,, $(mmgu_x),$(mmgu_y),$(mmgu_z),surface=none)",
        "locate($(x_span/2),$(y_span/2),0) {",
        "  ; Closed positive-z grounded cap; the negative-z exit remains open.",
        f"  e({ground_id}) {{ {endplates['grounded_rear_cap']} notin {{ box3D(-{_number(aperture_half_x_mm)},-{_number(aperture_half_y_mm)},{_number(local_exit_z_mm-1)},{_number(aperture_half_x_mm)},{_number(aperture_half_y_mm)},{_number(local_exit_z_mm+1)}) }} }}",
        "  ; Solid repeller; no coaxial return aperture is permitted.",
        endplates["repeller"],
    ]
    for support in grid_support_frames:
        electrode_id = int(local_electrode_ids[int(support["id"])])
        lines.extend((
            emit_open_rectangular_frame(
                electrode_id, outer_half_x_mm=float(support["outer_half_x_mm"]),
                outer_half_y_mm=float(support["outer_half_y_mm"]),
                aperture_half_x_mm=float(support["aperture_half_x_mm"]),
                aperture_half_y_mm=float(support["aperture_half_y_mm"]),
                front_z_mm=float(support["front_z_mm"]) + offset_z,
                back_z_mm=float(support["back_z_mm"]) + offset_z,
                cut_padding_mm=float(support["thickness_z_mm"]),
            ),
            emit_ideal_grid(
                electrode_id, half_x_mm=float(support["aperture_half_x_mm"]),
                half_y_mm=float(support["aperture_half_y_mm"]),
                z_mm=float(support["grid_z_mm"]) + offset_z,
            ),
        ))
    for ring in stage_2_rings:
        thickness = float(ring["thickness_z_mm"])
        center = float(ring["center_z_mm"]) + offset_z
        lines.append(emit_open_rectangular_frame(
            int(local_electrode_ids[int(ring["id"])]),
            outer_half_x_mm=enclosure.electrode_half_x_mm,
            outer_half_y_mm=enclosure.electrode_half_y_mm,
            aperture_half_x_mm=aperture_half_x_mm,
            aperture_half_y_mm=aperture_half_y_mm,
            front_z_mm=center - thickness / 2.0, back_z_mm=center + thickness / 2.0,
            cut_padding_mm=1.0,
        ))
    lines.extend(("}", ""))
    return "\n".join(lines)
