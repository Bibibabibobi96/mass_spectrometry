"""Resolve the shared axial interface layout around a multipole rod array."""

from __future__ import annotations

import math
from typing import Any
from collections.abc import Mapping

from common.contracts.machine_contracts import ContractError


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


def through_exit_geometry(resolved_design: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the explicitly open cylindrical exit; closed or composed models fail."""
    geometry = resolved_design["geometry_mm"]
    enclosure = geometry["enclosure"]
    if enclosure["model"] not in {
        "cylindrical_grounded_shield_through_exit_v1",
        "cylindrical_grounded_shield_through_entrance_exit_v1",
    }:
        raise ContractError("mechanical exit requires the explicit through-exit enclosure model")
    if "downstream_terminal" in resolved_design:
        raise ContractError("through-exit mechanical interface does not support composed downstream terminals")
    interface = resolved_design["interfaces_mm"]["exit"]
    cap_start = float(enclosure["exit_outer_endcap_upstream_face_z_mm"])
    cap_end = float(enclosure["exit_outer_endcap_downstream_face_z_mm"])
    length = float(interface["connector_length_mm"])
    connector_start = float(interface["aperture_plate_downstream_face_z_mm"])
    connector_end = connector_start + length
    if length and (interface["connector_shape"] != "cylindrical_bore" or connector_start > cap_start):
        raise ContractError("through-exit connector must be a continuous coaxial cylindrical bore")
    return dict(surface_z_mm=max(cap_end, connector_end), aperture_radius_mm=float(interface["aperture_radius_mm"]),
                outer_endcap_z_min_mm=cap_start, outer_endcap_z_max_mm=cap_end,
                wall_thickness_mm=cap_end-cap_start if connector_end <= cap_end else None)


def through_entrance_geometry(resolved_design: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the explicit outer entrance bore, never the internal release plane."""
    geometry = resolved_design["geometry_mm"]
    enclosure = geometry["enclosure"]
    if enclosure["model"] != "cylindrical_grounded_shield_through_entrance_exit_v1":
        raise ContractError("mechanical entrance requires the explicit through-entrance-exit enclosure model")
    if "downstream_terminal" in resolved_design:
        raise ContractError("through-entrance mechanical interface does not support composed downstream terminals")
    interface = resolved_design["interfaces_mm"]["entrance"]
    cap_start = float(enclosure["entrance_outer_endcap_upstream_face_z_mm"])
    cap_end = float(enclosure["entrance_outer_endcap_downstream_face_z_mm"])
    length = float(interface["connector_length_mm"])
    connector_start = float(interface["connector_upstream_face_z_mm"])
    connector_end = float(interface["connector_downstream_face_z_mm"])
    if length and (interface["connector_shape"] != "cylindrical_bore" or connector_end < cap_end):
        raise ContractError("through-entrance connector must be a continuous coaxial cylindrical bore")
    return dict(surface_z_mm=min(cap_start, connector_start), aperture_radius_mm=float(interface["aperture_radius_mm"]),
                outer_endcap_z_min_mm=cap_start, outer_endcap_z_max_mm=cap_end,
                wall_thickness_mm=cap_end-cap_start if connector_start >= cap_start else None)


def through_shield_geometry(resolved_design: Mapping[str, Any]) -> dict[str, float]:
    """Return the physical cylindrical side-shell span for an open exit model.

    The numerical vacuum may deliberately extend past the real exit for an
    observation guard.  It is never a material-shell dimension.  The older
    exit-only model retains its existing upstream shell origin; the explicit
    dual-through model starts at the real entrance outer endcap.
    """
    enclosure = resolved_design["geometry_mm"]["enclosure"]
    model = enclosure["model"]
    if model not in {
        "cylindrical_grounded_shield_through_exit_v1",
        "cylindrical_grounded_shield_through_entrance_exit_v1",
    }:
        raise ContractError("physical side shell requires an explicit through-exit enclosure model")
    z_min = float(enclosure["vacuum_z_min_mm"])
    if model == "cylindrical_grounded_shield_through_entrance_exit_v1":
        z_min = float(enclosure["entrance_outer_endcap_upstream_face_z_mm"])
    z_max = float(enclosure["exit_outer_endcap_downstream_face_z_mm"])
    if z_max <= z_min:
        raise ContractError("through side-shell span must be increasing")
    return dict(z_min_mm=z_min, z_max_mm=z_max)
