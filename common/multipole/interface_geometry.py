"""Resolve the shared axial interface layout around a multipole rod array."""

from __future__ import annotations

import math
from typing import Any


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
    """Return plate, optional connector, source, and observation-plane positions."""
    rod_z_min = float(rod_z_min_mm)
    rod_z_max = float(rod_z_max_mm)
    if not all(math.isfinite(value) for value in (rod_z_min, rod_z_max)) or rod_z_max <= rod_z_min:
        raise InterfaceGeometryError("rod z range must be finite and increasing")

    def values(spec: dict[str, Any], side: str) -> tuple[float, float, float, float, float]:
        return (
            _positive(spec["aperture_radius_mm"], f"{side} aperture radius"),
            _positive(spec["plate_thickness_mm"], f"{side} plate thickness"),
            _nonnegative(spec["rod_clearance_mm"], f"{side} rod clearance"),
            _nonnegative(spec["connector_length_mm"], f"{side} connector length"),
            _positive(spec["particle_plane_distance_mm"], f"{side} particle-plane distance"),
        )

    in_aperture, in_thickness, in_clearance, in_connector, in_distance = values(entrance, "entrance")
    out_aperture, out_thickness, out_clearance, out_connector, out_distance = values(
        exit_interface, "exit"
    )
    entrance_plate_max = rod_z_min - in_clearance
    entrance_plate_min = entrance_plate_max - in_thickness
    exit_plate_min = rod_z_max + out_clearance
    exit_plate_max = exit_plate_min + out_thickness
    layout = {
        "entrance": {
            "aperture_radius_mm": in_aperture,
            "plate_z_min_mm": entrance_plate_min,
            "plate_z_max_mm": entrance_plate_max,
            "connector_length_mm": in_connector,
            "connector_z_min_mm": entrance_plate_min - in_connector,
            "connector_z_max_mm": entrance_plate_min,
            "particle_plane_z_mm": entrance_plate_min - in_connector - in_distance,
        },
        "exit": {
            "aperture_radius_mm": out_aperture,
            "plate_z_min_mm": exit_plate_min,
            "plate_z_max_mm": exit_plate_max,
            "connector_length_mm": out_connector,
            "connector_z_min_mm": exit_plate_max,
            "connector_z_max_mm": exit_plate_max + out_connector,
            "particle_plane_z_mm": exit_plate_max + out_connector + out_distance,
        },
    }
    if "connector_shape" in entrance:
        layout["entrance"]["connector_shape"] = entrance["connector_shape"]
    if "connector_shape" in exit_interface:
        layout["exit"]["connector_shape"] = exit_interface["connector_shape"]
    return layout
