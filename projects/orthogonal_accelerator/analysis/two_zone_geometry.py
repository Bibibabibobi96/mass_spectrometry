"""Owned OA profiles and solver-neutral rectangular mechanical geometry.

The component contract owns physical dimensions. Callers provide explicit
source/focus requirements and placement; the closed model uses the existing
exit-origin frame. PA meshes, storage offsets and GEM belong to adapters.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from dataclasses import dataclass
import json
from pathlib import Path
from math import isclose, isfinite


class TwoZoneGeometryError(ValueError):
    """Raised when a solver-neutral two-zone geometric invariant is invalid."""


@dataclass(frozen=True)
class UniformRingPlaneLayout:
    """Interior ring planes in the declared start-to-end direction, in mm."""

    pitch_mm: float
    centers_mm: tuple[float, ...]


@dataclass(frozen=True)
class ShieldedRectangularEnclosure:
    """Rectangular two-zone electrode/grounded-shell dimensions in mm."""

    electrode_half_x_mm: float
    electrode_half_y_mm: float
    guard_half_x_mm: float
    guard_half_y_mm: float
    guard_wall_mm: float
    guard_inner_half_x_mm: float
    guard_inner_half_y_mm: float
    lateral_clearance_mm: float
    rear_cap_inner_z_mm: float
    rear_cap_outer_z_mm: float


def _positive(value: float, name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or numeric <= 0.0:
        raise TwoZoneGeometryError(f"{name} must be finite and positive")
    return numeric


def derive_uniform_ring_planes(
    start_mm: float, end_mm: float, ring_count: int, *, ring_thickness_mm: float | None = None
) -> UniformRingPlaneLayout:
    """Return equally spaced interior ring centers from ``start_mm`` to ``end_mm``.

    ``start_mm`` and ``end_mm`` may be either increasing or decreasing.  When
    a physical ring thickness is supplied, it must be strictly less than the
    derived pitch so adjacent rings cannot overlap.
    """
    if isinstance(ring_count, bool) or not isinstance(ring_count, int) or ring_count < 0:
        raise TwoZoneGeometryError("ring_count must be a nonnegative integer")
    start, end = float(start_mm), float(end_mm)
    if not isfinite(start) or not isfinite(end) or isclose(start, end, abs_tol=1e-12):
        raise TwoZoneGeometryError("ring-plane endpoints must be finite and distinct")
    pitch = abs(end - start) / (ring_count + 1)
    if ring_thickness_mm is not None and _positive(ring_thickness_mm, "ring_thickness_mm") >= pitch:
        raise TwoZoneGeometryError("ring_thickness_mm must be smaller than the derived ring pitch")
    direction = 1.0 if end > start else -1.0
    return UniformRingPlaneLayout(
        pitch_mm=pitch,
        centers_mm=tuple(start + direction * index * pitch for index in range(1, ring_count + 1)),
    )


def derive_shielded_rectangular_enclosure(
    *, electrode_outer_width_x_mm: float, electrode_outer_height_y_mm: float,
    guard_outer_width_x_mm: float, guard_outer_height_y_mm: float,
    guard_wall_thickness_mm: float, lateral_clearance_mm: float,
    repeller_z_mm: float, repeller_thickness_z_mm: float, rear_gap_mm: float,
) -> ShieldedRectangularEnclosure:
    """Derive a finite grounded rectangular shell for acceleration toward -z.

    ``repeller_z_mm`` denotes the repeller face facing the acceleration gap;
    its material and rear clearance extend toward increasing z.  Consumers
    using a +z accelerating frame must transform their input/output explicitly.
    This function does not place the enclosure in an instrument frame.
    """
    electrode_half_x = _positive(electrode_outer_width_x_mm, "electrode_outer_width_x_mm") / 2.0
    electrode_half_y = _positive(electrode_outer_height_y_mm, "electrode_outer_height_y_mm") / 2.0
    guard_half_x = _positive(guard_outer_width_x_mm, "guard_outer_width_x_mm") / 2.0
    guard_half_y = _positive(guard_outer_height_y_mm, "guard_outer_height_y_mm") / 2.0
    wall = _positive(guard_wall_thickness_mm, "guard_wall_thickness_mm")
    clearance = _positive(lateral_clearance_mm, "lateral_clearance_mm")
    rear_gap = _positive(rear_gap_mm, "rear_gap_mm")
    repeller_z = float(repeller_z_mm)
    repeller_thickness = _positive(repeller_thickness_z_mm, "repeller_thickness_z_mm")
    if not isfinite(repeller_z) or wall >= min(guard_half_x, guard_half_y):
        raise TwoZoneGeometryError("grounded enclosure requires a finite repeller position and finite wall")
    inner_x, inner_y = guard_half_x - wall, guard_half_y - wall
    if not isclose(inner_x - electrode_half_x, clearance, abs_tol=1e-9) or not isclose(
        inner_y - electrode_half_y, clearance, abs_tol=1e-9
    ):
        raise TwoZoneGeometryError("electrode must retain the declared equal lateral clearance to the grounded wall")
    rear_inner = repeller_z + repeller_thickness + rear_gap
    return ShieldedRectangularEnclosure(
        electrode_half_x_mm=electrode_half_x,
        electrode_half_y_mm=electrode_half_y,
        guard_half_x_mm=guard_half_x,
        guard_half_y_mm=guard_half_y,
        guard_wall_mm=wall,
        guard_inner_half_x_mm=inner_x,
        guard_inner_half_y_mm=inner_y,
        lateral_clearance_mm=clearance,
        rear_cap_inner_z_mm=rear_inner,
        rear_cap_outer_z_mm=rear_inner + wall,
    )


# This is the component's current prototype geometry profile, rather than a
# consumer-selected design.  Its dimensions have not received field/trajectory
# qualification; the compiler can prove containment and the declared finite
# envelope only.
CLOSED_TWO_ZONE_PROFILE_ID = "closed_two_zone_compact_mr_axial_r3_gap1_4mm"
_GEOMETRY_PROFILE_KEYS = {
    "gap_1_mm", "gap_2_mm", "ring_count", "ring_thickness_z_mm",
    "aperture_width_x_mm", "aperture_height_y_mm", "electrode_outer_width_x_mm",
    "electrode_outer_height_y_mm", "guard_outer_width_x_mm", "guard_outer_height_y_mm",
    "guard_wall_thickness_mm", "lateral_clearance_mm", "repeller_thickness_z_mm", "rear_gap_mm",
    "qualified_source_envelope_radius_mm", "qualified_source_envelope_height_mm",
}


def load_geometry_profile(profile_id: str = CLOSED_TWO_ZONE_PROFILE_ID) -> Mapping[str, float | int]:
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
            if isinstance(value, bool):
                raise TwoZoneGeometryError(f"closed two-zone profile.{key} must be finite and positive")
            try:
                values[key] = _positive(value, f"closed two-zone profile.{key}")
            except (TypeError, ValueError) as error:
                raise TwoZoneGeometryError(f"closed two-zone profile.{key} must be finite and positive") from error
    return values



_REQUIRED_REQUEST_KEYS = {
    "schema_version", "role", "variant_id", "acceleration_direction", "source_cylinder",
    "focus", "compaction", "local_pa", "placement",
}

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


@dataclass(frozen=True)
class ClosedTwoZoneGeometry:
    """Owned mechanics in the existing exit-origin frame; no PA projection."""

    geometry_profile_id: str
    enclosure: ShieldedRectangularEnclosure
    local_exit_z_mm: float
    local_repeller_z_mm: float
    gap_1_mm: float
    gap_2_mm: float
    repeller_thickness_mm: float
    aperture_half_x_mm: float
    aperture_half_y_mm: float
    grid_supports: tuple[Mapping[str, Any], ...]
    rings: tuple[Mapping[str, Any], ...]
    source_cylinder_radius_mm: float
    source_cylinder_height_mm: float
    source_center_z_mm: float
    side_entry: Mapping[str, Any] | None


def resolve_closed_two_zone_geometry(requirements: Mapping[str, Any], *, geometry_profile_id: str = CLOSED_TWO_ZONE_PROFILE_ID) -> ClosedTwoZoneGeometry:
    """Compile the fixed closed-end two-zone topology from a consumer request.

    The request contains interface envelope, placement and source requirements.
    It deliberately has no electrode-shape, end-cap, grid-support or ring-plane
    fields: this provider derives those structures and rejects every topology
    other than a solid positive-z repeller/rear cap with a negative-z exit grid.
    """
    version = requirements.get("schema_version") if isinstance(requirements, Mapping) else None
    keys = _REQUIRED_REQUEST_KEYS | ({"side_entry"} if version == 2 else set())
    keys -= {"local_pa"}
    if "local_pa" in requirements:
        keys.add("local_pa")
    request = _mapping(requirements, "two-zone accelerator requirements", keys)
    geometry = load_geometry_profile(geometry_profile_id)
    if (type(version) is not int or version not in (1, 2)
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
    exit_z = 0.0
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
    local_supports = tuple({**support,
                            "grid_z_mm": float(support["grid_z_mm"]) + local_offset_z,
                            "front_z_mm": float(support["front_z_mm"]) + local_offset_z,
                            "back_z_mm": float(support["back_z_mm"]) + local_offset_z}
                           for support in grid_supports)
    local_rings = tuple({**ring, "center_z_mm": float(ring["center_z_mm"]) + local_offset_z}
                        for ring in rings)
    side_entry = None
    if version == 2:
        port = _mapping(request["side_entry"], "side_entry", {"face", "half_width_x_mm", "half_width_z_mm"})
        if port["face"] != "negative_y":
            raise TwoZoneGeometryError("side_entry must select the negative-y wall")
        half_x = _finite_positive(port["half_width_x_mm"], "side_entry.half_width_x_mm")
        half_z = _finite_positive(port["half_width_z_mm"], "side_entry.half_width_z_mm")
        center_z = exit_z + gap_2 + gap_1/2
        if half_x >= enclosure.guard_inner_half_x_mm or half_z >= gap_1/2:
            raise TwoZoneGeometryError("side entry must remain strictly inside the first gap and between wall corners")
        physical_box = [-half_x, -enclosure.guard_half_y_mm, center_z-half_z,
                        half_x, -enclosure.guard_inner_half_y_mm, center_z+half_z]
        # Test the actual three-dimensional boxes, never whole-z slabs. The
        # support frames terminate inside the wall and may overlap port z.
        for solid in (
            [-enclosure.electrode_half_x_mm, -enclosure.electrode_half_y_mm, repeller_z,
             enclosure.electrode_half_x_mm, enclosure.electrode_half_y_mm, repeller_z+repeller_thickness],
            [-enclosure.guard_half_x_mm, -enclosure.guard_half_y_mm, enclosure.rear_cap_inner_z_mm,
             enclosure.guard_half_x_mm, enclosure.guard_half_y_mm, enclosure.rear_cap_outer_z_mm],
            *[[-float(s["outer_half_x_mm"]), -float(s["outer_half_y_mm"]), float(s["front_z_mm"]),
               float(s["outer_half_x_mm"]), float(s["outer_half_y_mm"]), float(s["back_z_mm"])] for s in local_supports],
        ):
            if all(max(physical_box[a], solid[a]) <= min(physical_box[a+3], solid[a+3]) for a in range(3)):
                raise TwoZoneGeometryError("side entry intersects a solid electrode or cap")
        side_entry = {
            "face": "negative_y", "center_mm": [0.0, -(enclosure.guard_half_y_mm+enclosure.guard_inner_half_y_mm)/2, center_z],
            "normal": [0, -1, 0], "half_width_x_mm": half_x, "half_width_z_mm": half_z,
            "physical_cutout_box_mm": physical_box, "component_electrode_id": 15,
            "scope": "Explicit grounded negative-y side entry; no repeller/cap opening or Fly collision override",
        }
    return ClosedTwoZoneGeometry(
        geometry_profile_id, enclosure, exit_z, repeller_z, gap_1, gap_2,
        repeller_thickness, aperture_x, aperture_y, local_supports, local_rings,
        radius, height, source_center_z, side_entry,
    )
