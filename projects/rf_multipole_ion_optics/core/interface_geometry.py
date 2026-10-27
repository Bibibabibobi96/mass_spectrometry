"""Resolve the shared axial interface layout around a multipole rod array."""

from __future__ import annotations

import math
from typing import Any
from collections.abc import Mapping



class InterfaceGeometryError(ValueError):
    """Raised when a multipole interface layout is inconsistent."""


def _nonnegative(value: float, label: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise InterfaceGeometryError(f"{label} must be finite and nonnegative")
    return value


def _positive(value: float, label: str) -> float:
    value = _nonnegative(value, label)
    if value == 0:
        raise InterfaceGeometryError(f"{label} must be positive")
    return value


def build_axial_interface_layout(
    *,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
    entrance: dict[str, Any],
    exit_interface: dict[str, Any],
) -> dict[str, Any]:
    """Derive canonical interface faces and event planes from mechanical primitives."""
    rod_z_min = float(rod_z_min_mm)
    rod_z_max = float(rod_z_max_mm)
    if not all(math.isfinite(value) for value in (rod_z_min, rod_z_max)) or rod_z_max <= rod_z_min:
        raise InterfaceGeometryError("rod z range must be finite and increasing")

    def mechanical_values(
        spec: dict[str, Any], side: str, offset_field: str
    ) -> tuple[float, float, float, float, float]:
        return (
            _positive(spec["aperture_radius_mm"], f"{side} aperture radius"),
            _positive(spec["plate_thickness_mm"], f"{side} plate thickness"),
            _nonnegative(spec["rod_clearance_mm"], f"{side} rod clearance"),
            _nonnegative(spec["connector_length_mm"], f"{side} connector length"),
            _positive(spec[offset_field], f"{side} {offset_field}"),
        )

    in_aperture, in_thickness, in_clearance, in_connector, release_offset = (
        mechanical_values(entrance, "entrance", "release_offset_mm")
    )
    out_aperture, out_thickness, out_clearance, out_connector, census_offset = (
        mechanical_values(exit_interface, "exit", "census_offset_mm")
    )
    entrance_plate_downstream = rod_z_min - in_clearance
    entrance_plate_upstream = entrance_plate_downstream - in_thickness
    entrance_connector_upstream = entrance_plate_upstream - in_connector
    exit_plate_upstream = rod_z_max + out_clearance
    exit_plate_downstream = exit_plate_upstream + out_thickness
    exit_connector_downstream = exit_plate_downstream + out_connector
    layout = {
        "entrance": {
            "aperture_radius_mm": in_aperture,
            "aperture_plate_upstream_face_z_mm": entrance_plate_upstream,
            "aperture_plate_downstream_face_z_mm": entrance_plate_downstream,
            "connector_length_mm": in_connector,
            "connector_upstream_face_z_mm": entrance_connector_upstream,
            "connector_downstream_face_z_mm": entrance_plate_upstream,
            "release_plane_z_mm": entrance_connector_upstream - release_offset,
        },
        "exit": {
            "aperture_radius_mm": out_aperture,
            "aperture_plate_upstream_face_z_mm": exit_plate_upstream,
            "aperture_plate_downstream_face_z_mm": exit_plate_downstream,
            "aperture_crossing_plane_z_mm": exit_plate_downstream,
            "connector_length_mm": out_connector,
            "connector_upstream_face_z_mm": exit_plate_downstream,
            "connector_downstream_face_z_mm": exit_connector_downstream,
            "handoff_plane_z_mm": exit_connector_downstream,
            "census_plane_z_mm": exit_connector_downstream + census_offset,
        },
    }
    if "connector_shape" in entrance:
        layout["entrance"]["connector_shape"] = entrance["connector_shape"]
    if "connector_shape" in exit_interface:
        layout["exit"]["connector_shape"] = exit_interface["connector_shape"]
    return layout



def build_enclosure_layout(geometry: Mapping[str, Any]) -> dict[str, Any]:
    """Compile real shell/endcap annuli and ports, independently of the numeric box.

    Missing enclosure means bare rods. Endcaps extend inward from the declared
    shell faces, have the shell inner radius as their outer radius, and belong
    to the same grounded conductor. No absent cap becomes a zero-volume body.
    """
    enclosure = geometry.get("enclosure", {"model": "bare"})
    if enclosure["model"] == "bare":
        ports = {}
        for side, sign, plane in (("entrance", -1, geometry["rod_z_min"]),
                                  ("exit", 1, geometry["rod_z_max"])):
            ports["mechanical_" + side] = dict(
                surface_kind="open_rod_" + side, center_mm=[0., 0., float(plane)],
                outward_normal=[0, 0, sign], wall_thickness_mm=None,
                cross_section=dict(shape="open_rod_envelope",
                                   inscribed_radius_mm=float(geometry["inscribed_radius_r0"])))
        return dict(bodies=[], ports=ports)
    if enclosure["model"] != "cylindrical_grounded_shell":
        raise InterfaceGeometryError("physical annuli require bare rods or the cylindrical grounded shell")
    inner = _positive(enclosure["inner_radius_mm"], "shell inner radius")
    wall = _positive(enclosure["wall_thickness_mm"], "shell wall thickness")
    lower, upper = float(enclosure["z_min_mm"]), float(enclosure["z_max_mm"])
    if not math.isfinite(lower) or not math.isfinite(upper) or upper <= lower:
        raise InterfaceGeometryError("shell axial bounds must be finite and increasing")
    bodies = [dict(role="shell", inner_radius_mm=inner, outer_radius_mm=inner + wall,
                   z_min_mm=lower, z_max_mm=upper)]
    ports = {}
    cap_faces = {}
    for side, sign, plane in (("entrance", -1, lower), ("exit", 1, upper)):
        cap = enclosure.get("endcaps", {}).get(side)
        aperture, thickness = inner, None
        if cap is not None:
            aperture = _positive(cap["aperture_radius_mm"], side + " endcap aperture")
            thickness = _positive(cap["thickness_mm"], side + " endcap thickness")
            if aperture >= inner or thickness >= upper - lower:
                raise InterfaceGeometryError("endcap requires a real annulus and thickness within the shell span")
            start, end = (plane, plane + thickness) if side == "entrance" else (plane - thickness, plane)
            bodies.append(dict(role=side + "_endcap", inner_radius_mm=aperture,
                               outer_radius_mm=inner, z_min_mm=start, z_max_mm=end))
            cap_faces[side] = (start, end)
        ports["mechanical_" + side] = dict(
            surface_kind="aperture_outer_face", center_mm=[0., 0., plane],
            outward_normal=[0, 0, sign], wall_thickness_mm=thickness,
            cross_section=dict(shape="circle", radius_mm=aperture))
    if len(cap_faces) == 2 and cap_faces["entrance"][1] > cap_faces["exit"][0]:
        raise InterfaceGeometryError("entrance and exit endcaps overlap axially")
    return dict(bodies=bodies, ports=ports)


def transport_observations(resolved: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read explicit observations; the independent rectangular reference owns its layout."""
    geometry = resolved["geometry_mm"]
    if geometry["enclosure"]["model"] != "rectangular_reference_enclosure_v1":
        return geometry["observations"]
    interfaces = resolved["interfaces_mm"]
    return dict(release_plane_z_mm=interfaces["entrance"]["release_plane_z_mm"],
                handoff_plane_z_mm=interfaces["exit"]["handoff_plane_z_mm"],
                census_plane_z_mm=interfaces["exit"]["census_plane_z_mm"],
                acceptance_radius_mm=interfaces["exit"]["aperture_radius_mm"])


def transport_numerical_domain(resolved: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read the declared numerical domain, with no inference from physical shell size."""
    geometry = resolved["geometry_mm"]
    if geometry["enclosure"]["model"] != "rectangular_reference_enclosure_v1":
        return geometry["numerical_domain"]
    enclosure = geometry["enclosure"]
    return dict(radius_mm=enclosure["outer_half_width_mm"],
                z_min_mm=enclosure["vacuum_z_min_mm"], z_max_mm=enclosure["vacuum_z_max_mm"],
                working_region_radius_mm=enclosure["working_region_radius_mm"])
