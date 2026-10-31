"""Render the owned closed-end two-zone accelerator PA geometry.

An instrument supplies its frozen placement, mesh, and interface envelope as a
plain specification.  This component owns all electrode topology: a solid
repeller, a closed positive-z grounded cap, the negative-z exit grid, grid1,
and the interior acceleration rings.  Consumers cannot select an alternate
end topology through this API.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isclose, isfinite
from typing import Any, Mapping, Sequence

from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
    CLOSED_TWO_ZONE_PROFILE_ID,
    resolve_closed_two_zone_geometry,
    ShieldedRectangularEnclosure,
    TwoZoneGeometryError,
)
from projects.orthogonal_accelerator.simion.rectangular_accelerator import (
    emit_closed_two_zone_endplates,
    emit_grounded_enclosure,
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
    side_entry: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable projection without exposing geometry inputs."""
        result = {
            "geometry_profile_id": self.geometry_profile_id,
            "acceleration_direction": self.acceleration_direction,
            "local_exit_z_mm": self.local_exit_z_mm,
            "local_repeller_z_mm": self.local_repeller_z_mm,
            "gap_1_mm": self.gap_1_mm,
            "gap_2_mm": self.gap_2_mm,
            "ring_count": len(self.ring_centers_z_mm),
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
        if self.side_entry is not None:
            result["side_entry"] = dict(self.side_entry)
        return result


@dataclass(frozen=True)
class ResolvedClosedTwoZoneElectrodes:
    """Mechanical primitives projected into the explicit SIMION PA frame."""

    enclosure: ShieldedRectangularEnclosure
    local_exit_z_mm: float
    local_repeller_z_mm: float
    repeller_thickness_mm: float
    aperture_half_x_mm: float
    aperture_half_y_mm: float
    pa_y_offset_mm: float
    grid_supports: tuple[Mapping[str, float | int], ...]
    rings: tuple[Mapping[str, float | int], ...]
    local_electrode_ids: Mapping[int, int]
    side_entry: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return local boxes, apertures and transparent sheets, all in mm."""
        enclosure = self.enclosure
        aperture_x, aperture_y = self.aperture_half_x_mm, self.aperture_half_y_mm

        def box(x: float, y: float, z_min: float, z_max: float) -> dict[str, float]:
            return {"x_min_mm": -x, "x_max_mm": x, "y_min_mm": -y,
                    "y_max_mm": y, "z_min_mm": z_min, "z_max_mm": z_max}

        grounded = {
            "component_electrode_id": 15, "local_pa_electrode_id": self.local_electrode_ids[15],
            "outer_box_mm": box(enclosure.guard_half_x_mm, enclosure.guard_half_y_mm,
                                self.local_exit_z_mm, enclosure.rear_cap_outer_z_mm),
            "cavity_box_mm": box(enclosure.guard_inner_half_x_mm, enclosure.guard_inner_half_y_mm,
                                 self.local_exit_z_mm, enclosure.rear_cap_inner_z_mm),
            "exit_opening_box_mm": box(aperture_x, aperture_y, self.local_exit_z_mm,
                                       self.local_exit_z_mm + enclosure.guard_wall_mm),
        }
        if self.side_entry is not None:
            grounded["side_entry"] = dict(self.side_entry)
        repeller = {
            "component_electrode_id": 22, "local_pa_electrode_id": self.local_electrode_ids[22],
            "solid_box_mm": box(enclosure.electrode_half_x_mm, enclosure.electrode_half_y_mm,
                                self.local_repeller_z_mm,
                                self.local_repeller_z_mm + self.repeller_thickness_mm),
        }
        supports = []
        for support in self.grid_supports:
            component_id = int(support["id"])
            z_min, z_max = float(support["front_z_mm"]), float(support["back_z_mm"])
            ax, ay = float(support["aperture_half_x_mm"]), float(support["aperture_half_y_mm"])
            supports.append({
                "component_electrode_id": component_id,
                "local_pa_electrode_id": self.local_electrode_ids[component_id],
                "frame_outer_box_mm": box(float(support["outer_half_x_mm"]),
                                          float(support["outer_half_y_mm"]), z_min, z_max),
                "aperture_box_mm": box(ax, ay, z_min, z_max),
                "ideal_sheet_mm": {"x_min_mm": -ax, "x_max_mm": ax,
                                   "y_min_mm": -ay, "y_max_mm": ay,
                                   "z_mm": float(support["grid_z_mm"])},
                "transmission": "ideal_transparent",
            })
        rings = []
        for ring in self.rings:
            component_id = int(ring["id"])
            center, thickness = float(ring["center_z_mm"]), float(ring["thickness_z_mm"])
            rings.append({
                "component_electrode_id": component_id,
                "local_pa_electrode_id": self.local_electrode_ids[component_id],
                "outer_box_mm": box(enclosure.electrode_half_x_mm,
                                    enclosure.electrode_half_y_mm,
                                    center - thickness / 2.0, center + thickness / 2.0),
                "aperture_box_mm": box(aperture_x, aperture_y,
                                      center - thickness / 2.0, center + thickness / 2.0),
            })
        return {"schema_version": 2 if self.side_entry is not None else 1,
                "coordinate_frame": "accelerator_centered_transverse_local_z_mm",
                "local_to_pa_translation_mm": [0.0, self.pa_y_offset_mm, 0.0],
                "acceleration_direction": "-z", "grounded_enclosure": grounded,
                "repeller": repeller, "grid_supports": supports, "rings": rings}


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
    resolved_electrodes: ResolvedClosedTwoZoneElectrodes


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


def _resolve_closed_two_zone_projection(requirements: Mapping[str, Any], *, geometry_profile_id: str = CLOSED_TWO_ZONE_PROFILE_ID):
    """Project the single owned mechanical model into a frozen SIMION PA."""
    model = resolve_closed_two_zone_geometry(requirements, geometry_profile_id=geometry_profile_id)
    local = _mapping(requirements["local_pa"], "local_pa", {"span_mm", "mesh_mm_per_gu", "exit_z_mm", "margin_z_mm"})
    span = _triple(local["span_mm"], "local_pa.span_mm")
    mesh = _triple(local["mesh_mm_per_gu"], "local_pa.mesh_mm_per_gu")
    exit_z = _finite_positive(local["exit_z_mm"], "local_pa.exit_z_mm")
    margin_z = _finite_positive(local["margin_z_mm"], "local_pa.margin_z_mm")
    original = model.enclosure
    if 2.0 * original.guard_half_x_mm > span[0] or 2.0 * original.guard_half_y_mm > span[1]:
        raise TwoZoneGeometryError("local PA transverse span cannot enclose the grounded accelerator")
    enclosure = replace(original, rear_cap_inner_z_mm=original.rear_cap_inner_z_mm+exit_z,
                        rear_cap_outer_z_mm=original.rear_cap_outer_z_mm+exit_z)
    repeller_z = model.local_repeller_z_mm+exit_z
    ring_count = len(model.rings)
    local_ids = {15: 1, 22: 2, 23: 3, 24: 4, **{26 + index: 5 + index for index in range(ring_count)}}
    local_supports = tuple({**item, **{key: float(item[key])+exit_z
                            for key in ("grid_z_mm", "front_z_mm", "back_z_mm")}} for item in model.grid_supports)
    local_rings = tuple({**item, "center_z_mm": float(item["center_z_mm"])+exit_z} for item in model.rings)
    side_entry = None
    if model.side_entry is not None:
        side_entry = dict(model.side_entry)
        center = list(side_entry["center_mm"]); center[2] += exit_z
        box = list(side_entry["physical_cutout_box_mm"]); box[2] += exit_z; box[5] += exit_z
        side_entry.update(center_mm=center, physical_cutout_box_mm=box,
                          local_pa_electrode_id=local_ids[15], potential_v=0.0,
                          boolean_cut_padding_y_mm=mesh[1], boolean_transverse_expansion_mm=0.0)
    resolved_electrodes = ResolvedClosedTwoZoneElectrodes(
        enclosure, exit_z, repeller_z, model.repeller_thickness_mm,
        model.aperture_half_x_mm, model.aperture_half_y_mm,
        span[1]/2.0, local_supports, local_rings, local_ids, side_entry,
    )
    if enclosure.rear_cap_outer_z_mm+margin_z > span[2]+1e-9:
        raise TwoZoneGeometryError("accelerator local PA z span does not enclose both endplates and margins")
    if not isclose((span[0]/2.0)/mesh[0], round((span[0]/2.0)/mesh[0]), rel_tol=0.0, abs_tol=1e-9):
        raise TwoZoneGeometryError("x-mirrored accelerator half-span must end on the frozen mesh")
    return model, resolved_electrodes, span, mesh, margin_z


def resolve_closed_two_zone_electrodes(requirements: Mapping[str, Any], *, geometry_profile_id: str = CLOSED_TWO_ZONE_PROFILE_ID) -> ResolvedClosedTwoZoneElectrodes:
    """Resolve a validated PA-coordinate projection without rendering any GEM."""
    return _resolve_closed_two_zone_projection(requirements, geometry_profile_id=geometry_profile_id)[1]


def _project_closed_two_zone_layout(model, resolved_electrodes) -> CompiledTwoZoneLayout:
    enclosure = resolved_electrodes.enclosure
    exit_z, repeller_z = resolved_electrodes.local_exit_z_mm, resolved_electrodes.local_repeller_z_mm
    local_rings, side_entry = resolved_electrodes.rings, resolved_electrodes.side_entry
    static_y_extent = 2.0*enclosure.guard_half_y_mm
    static_axial_length = enclosure.rear_cap_outer_z_mm-exit_z
    resolved_layout = CompiledTwoZoneLayout(
        model.geometry_profile_id, "-z", exit_z, repeller_z, model.gap_1_mm, model.gap_2_mm,
        tuple(float(item["center_z_mm"]) for item in local_rings), model.source_center_z_mm+exit_z,
        model.source_center_z_mm-model.source_cylinder_radius_mm+exit_z,
        model.source_center_z_mm+model.source_cylinder_radius_mm+exit_z,
        model.source_cylinder_radius_mm, model.source_cylinder_height_mm,
        2.0*model.aperture_half_x_mm, 2.0*model.aperture_half_y_mm,
        static_y_extent, static_axial_length, side_entry,
    )
    return resolved_layout


def resolve_closed_two_zone_layout(requirements: Mapping[str, Any], *, geometry_profile_id: str = CLOSED_TWO_ZONE_PROFILE_ID) -> CompiledTwoZoneLayout:
    """Project physical layout into the validated PA frame without GEM output."""
    model, electrodes, _, _, _ = _resolve_closed_two_zone_projection(requirements, geometry_profile_id=geometry_profile_id)
    return _project_closed_two_zone_layout(model, electrodes)


def compile_closed_two_zone_accelerator(requirements: Mapping[str, Any], *, geometry_profile_id: str = CLOSED_TWO_ZONE_PROFILE_ID) -> CompiledTwoZoneAccelerator:
    """Render the single owned model through its validated PA projection."""
    model, resolved_electrodes, span, mesh, margin_z = _resolve_closed_two_zone_projection(
        requirements, geometry_profile_id=geometry_profile_id,
    )
    enclosure = resolved_electrodes.enclosure
    exit_z, repeller_z = resolved_electrodes.local_exit_z_mm, resolved_electrodes.local_repeller_z_mm
    local_ids = resolved_electrodes.local_electrode_ids
    side_entry = resolved_electrodes.side_entry
    placement = requirements["placement"]
    global_exit_z = float(placement["global_exit_z_mm"])
    supports = tuple({**item, **{key: float(item[key])+global_exit_z
                       for key in ("grid_z_mm", "front_z_mm", "back_z_mm")}} for item in model.grid_supports)
    rings = tuple({**item, "center_z_mm": float(item["center_z_mm"])+global_exit_z} for item in model.rings)
    gem = render_closed_two_zone_local_pa(
        span_mm=span, mesh_mm_per_gu=mesh, local_exit_z_mm=exit_z, local_repeller_z_mm=repeller_z,
        focus_y_mm=float(placement["focus_y_mm"]), global_repeller_z_mm=float(placement["global_repeller_z_mm"]),
        enclosure=enclosure, repeller_thickness_mm=model.repeller_thickness_mm,
        aperture_half_x_mm=model.aperture_half_x_mm, aperture_half_y_mm=model.aperture_half_y_mm,
        local_margin_z_mm=margin_z, grid_support_frames=supports, stage_2_rings=rings,
        local_electrode_ids=local_ids, global_exit_z_mm=global_exit_z, side_entry=side_entry,
    )
    resolved_layout = _project_closed_two_zone_layout(model, resolved_electrodes)
    static_y_extent = resolved_layout.static_minimum_y_extent_mm
    static_axial_length = resolved_layout.static_axial_length_mm
    return CompiledTwoZoneAccelerator(
        gem, exit_z, repeller_z, model.source_cylinder_radius_mm, model.source_cylinder_height_mm,
        model.source_center_z_mm, static_y_extent, static_axial_length, resolved_layout, resolved_electrodes,
    )


def render_closed_two_zone_local_pa(
    *, span_mm: Sequence[float], mesh_mm_per_gu: Sequence[float],
    local_exit_z_mm: float, local_repeller_z_mm: float, focus_y_mm: float, global_repeller_z_mm: float,
    enclosure: ShieldedRectangularEnclosure, repeller_thickness_mm: float,
    aperture_half_x_mm: float, aperture_half_y_mm: float,
    local_margin_z_mm: float, grid_support_frames: Sequence[Mapping[str, Any]],
    stage_2_rings: Sequence[Mapping[str, Any]], local_electrode_ids: Mapping[int, int],
    global_exit_z_mm: float,
    side_entry: Mapping[str, Any] | None = None,
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
    local_repeller = float(local_repeller_z_mm)
    if local_repeller <= local_exit_z_mm:
        raise TwoZoneGeometryError("local repeller must remain behind the negative-z exit")
    if enclosure.rear_cap_outer_z_mm + float(local_margin_z_mm) > span_z + 1e-9:
        raise TwoZoneGeometryError("accelerator local PA z span does not enclose both endplates and margins")
    stored_x_span = span_x / 2.0
    if not isclose(stored_x_span / mesh_x, round(stored_x_span / mesh_x), rel_tol=0.0, abs_tol=1e-9):
        raise TwoZoneGeometryError("x-mirrored accelerator half-span must end on the frozen mesh")
    offset_z = float(local_exit_z_mm) - float(global_exit_z_mm)
    lines = [
        "; Local closed-end two-zone accelerator PA generated by orthogonal_accelerator; local +z is project +z.",
        f"; global repeller z={_number(global_repeller_z_mm)} mm; global focus=(0,{_number(focus_y_mm)},0) mm.",
        f"# local contract_mmgu_x, contract_mmgu_y, contract_mmgu_z = {_number(mesh_x)}, {_number(mesh_y)}, {_number(mesh_z)}",
        "# local mmgu_x = _G.var and _G.var.mmgu_x or contract_mmgu_x",
        "# local mmgu_y = _G.var and _G.var.mmgu_y or contract_mmgu_y",
        "# local mmgu_z = _G.var and _G.var.mmgu_z or contract_mmgu_z",
        "# assert(mmgu_x == contract_mmgu_x and mmgu_y == contract_mmgu_y and mmgu_z == contract_mmgu_z, 'runtime mesh must equal frozen accelerator component contract')",
        f"# local physical_x_span, stored_x_span, y_span, z_span = {_number(span_x)}, {_number(stored_x_span)}, {_number(span_y)}, {_number(span_z)}",
        "# local nx = math.floor(stored_x_span/mmgu_x + 0.5) + 1",
        "# local ny = math.floor(y_span/mmgu_y + 0.5) + 1",
        "# local nz = math.floor(z_span/mmgu_z + 0.5) + 1",
        "pa_define($(nx),$(ny),$(nz),planar,x,electrostatic,, $(mmgu_x),$(mmgu_y),$(mmgu_z),surface=none)",
        "locate(0,$(y_span/2),0) {",
    ]
    resolved = ResolvedClosedTwoZoneElectrodes(
        enclosure, float(local_exit_z_mm), local_repeller, float(repeller_thickness_mm),
        float(aperture_half_x_mm), float(aperture_half_y_mm), span_y/2,
        tuple({**support,
               "grid_z_mm": float(support["grid_z_mm"])+offset_z,
               "front_z_mm": float(support["front_z_mm"])+offset_z,
               "back_z_mm": float(support["back_z_mm"])+offset_z} for support in grid_support_frames),
        tuple({**ring, "center_z_mm": float(ring["center_z_mm"])+offset_z} for ring in stage_2_rings),
        local_electrode_ids, side_entry,
    )
    lines.extend(render_closed_two_zone_electrode_body(resolved))
    lines.extend(("}", ""))
    return "\n".join(lines)


def render_closed_two_zone_electrode_body(
    resolved: ResolvedClosedTwoZoneElectrodes, *,
    local_electrode_ids: Mapping[int, int] | None = None,
) -> list[str]:
    """Render canonical electrodes in the centered transverse component frame.

    There is no PA header, transverse storage offset or instrument placement.
    Axial coordinates are the resolved local z coordinates, including its
    explicit exit plane. A consumer may wrap these lines in official GEM
    locate/rotate operations and supply its own one-to-one local ID namespace.
    Geometry, ideal sheets, physical side entry and Boolean extents remain
    provider-owned; the namespace never rewrites text or changes geometry.
    """
    if not isinstance(resolved, ResolvedClosedTwoZoneElectrodes):
        raise TwoZoneGeometryError("canonical resolved two-zone electrodes required")
    ids = resolved.local_electrode_ids if local_electrode_ids is None else local_electrode_ids
    required = {15, 22, *[int(s["id"]) for s in resolved.grid_supports],
                *[int(r["id"]) for r in resolved.rings]}
    if (not isinstance(ids, Mapping) or set(ids) != required
            or any(type(key) is not int for key in ids)
            or any(type(value) is not int or value < 1 for value in ids.values())
            or len(set(ids.values())) != len(ids)):
        raise TwoZoneGeometryError("local electrode namespace must exactly and uniquely map every canonical electrode")
    enclosure = resolved.enclosure
    ground_id, repeller_id = ids[15], ids[22]
    local_exit_z_mm = resolved.local_exit_z_mm
    aperture_half_x_mm, aperture_half_y_mm = resolved.aperture_half_x_mm, resolved.aperture_half_y_mm
    endplates = emit_closed_two_zone_endplates(
        grounded_id=ground_id, repeller_id=repeller_id, enclosure=enclosure,
        exit_z_mm=local_exit_z_mm, repeller_front_z_mm=resolved.local_repeller_z_mm,
        repeller_back_z_mm=resolved.local_repeller_z_mm+resolved.repeller_thickness_mm,
        repeller_half_x_mm=enclosure.electrode_half_x_mm,
        repeller_half_y_mm=enclosure.electrode_half_y_mm,
    )
    if resolved.side_entry is not None:
        endplates["grounded_rear_cap"] = emit_grounded_enclosure(
            enclosure, exit_z_mm=local_exit_z_mm,
            negative_y_entry_box_mm=resolved.side_entry["physical_cutout_box_mm"],
            entry_cut_padding_mm=float(resolved.side_entry["boolean_cut_padding_y_mm"]),
        )
    lines = [
        "  ; Closed positive-z grounded cap; the negative-z exit remains open.",
        f"  e({ground_id}) {{ {endplates['grounded_rear_cap']} notin {{ box3D(-{_number(aperture_half_x_mm)},-{_number(aperture_half_y_mm)},{_number(local_exit_z_mm-1)},{_number(aperture_half_x_mm)},{_number(aperture_half_y_mm)},{_number(local_exit_z_mm+1)}) }} }}",
        "  ; Solid repeller; no coaxial return aperture is permitted.",
        endplates["repeller"],
    ]
    for support in resolved.grid_supports:
        electrode_id = ids[int(support["id"])]
        lines.extend((
            emit_open_rectangular_frame(
                electrode_id, outer_half_x_mm=float(support["outer_half_x_mm"]),
                outer_half_y_mm=float(support["outer_half_y_mm"]),
                aperture_half_x_mm=float(support["aperture_half_x_mm"]),
                aperture_half_y_mm=float(support["aperture_half_y_mm"]),
                front_z_mm=float(support["front_z_mm"]),
                back_z_mm=float(support["back_z_mm"]),
                cut_padding_mm=float(support["thickness_z_mm"]),
            ),
            emit_ideal_grid(
                electrode_id, half_x_mm=float(support["aperture_half_x_mm"]),
                half_y_mm=float(support["aperture_half_y_mm"]),
                z_mm=float(support["grid_z_mm"]),
            ),
        ))
    for ring in resolved.rings:
        thickness = float(ring["thickness_z_mm"])
        center = float(ring["center_z_mm"])
        lines.append(emit_open_rectangular_frame(
            ids[int(ring["id"])],
            outer_half_x_mm=enclosure.electrode_half_x_mm,
            outer_half_y_mm=enclosure.electrode_half_y_mm,
            aperture_half_x_mm=aperture_half_x_mm,
            aperture_half_y_mm=aperture_half_y_mm,
            front_z_mm=center - thickness / 2.0, back_z_mm=center + thickness / 2.0,
            cut_padding_mm=1.0,
        ))
    return lines
