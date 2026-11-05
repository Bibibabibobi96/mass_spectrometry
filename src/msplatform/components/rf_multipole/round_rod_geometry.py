"""Build and query solver-neutral multipole rod arrays."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np


class RoundRodGeometryError(ValueError):
    """Raised when the common rod-array inputs are inconsistent."""


def _validate_array_inputs(
    *,
    radial_order_n: int,
    electrode_count: int,
    inscribed_radius_r0_mm: float,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
) -> None:
    if electrode_count != 2 * radial_order_n or electrode_count < 4:
        raise RoundRodGeometryError("electrode_count must equal 2*radial_order_n and be at least four")
    values = (
        inscribed_radius_r0_mm,
        rod_z_min_mm,
        rod_z_max_mm,
    )
    if not all(math.isfinite(float(value)) for value in values):
        raise RoundRodGeometryError("rod-array dimensions must be finite")
    if inscribed_radius_r0_mm <= 0 or rod_z_max_mm <= rod_z_min_mm:
        raise RoundRodGeometryError("rod-array radii must be positive and z_max must exceed z_min")


def _ellipse_cross_section(cross_section: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "shape",
        "semi_major_axis_mm",
        "semi_minor_axis_mm",
        "major_axis_orientation",
    }
    if set(cross_section) != expected:
        raise RoundRodGeometryError(
            "ellipse cross_section must contain shape, semi_major_axis_mm, "
            "semi_minor_axis_mm and major_axis_orientation only"
        )
    semi_major = float(cross_section["semi_major_axis_mm"])
    semi_minor = float(cross_section["semi_minor_axis_mm"])
    orientation = cross_section["major_axis_orientation"]
    if not math.isfinite(semi_major) or not math.isfinite(semi_minor):
        raise RoundRodGeometryError("ellipse semi-axes must be finite")
    if semi_major <= 0 or semi_minor <= 0 or semi_major < semi_minor:
        raise RoundRodGeometryError(
            "ellipse semi-axes must be positive and semi_major_axis_mm must not be smaller"
        )
    if orientation not in {"radial", "tangential"}:
        raise RoundRodGeometryError(
            "ellipse major_axis_orientation must be radial or tangential"
        )
    return {
        "shape": "ellipse",
        "semi_major_axis_mm": semi_major,
        "semi_minor_axis_mm": semi_minor,
        "major_axis_orientation": orientation,
    }


def build_rod_array(
    *,
    radial_order_n: int,
    electrode_count: int,
    inscribed_radius_r0_mm: float,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
    rod_radius_mm: float | None = None,
    orientation_rad: float = 0.0,
    cross_section: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a round-default or explicitly elliptical multipole rod array in mm."""
    _validate_array_inputs(
        radial_order_n=radial_order_n,
        electrode_count=electrode_count,
        inscribed_radius_r0_mm=inscribed_radius_r0_mm,
        rod_z_min_mm=rod_z_min_mm,
        rod_z_max_mm=rod_z_max_mm,
    )
    if not math.isfinite(float(orientation_rad)):
        raise RoundRodGeometryError("rod-array orientation must be finite")
    section = {"shape": "round"} if cross_section is None else dict(cross_section)
    if section.get("shape") == "round":
        if set(section) != {"shape"}:
            raise RoundRodGeometryError("round cross_section accepts only shape")
        if rod_radius_mm is None or not math.isfinite(float(rod_radius_mm)) or rod_radius_mm <= 0:
            raise RoundRodGeometryError("rod_radius_mm must be finite and positive for round rods")
        return _build_round_rod_array(
            radial_order_n=radial_order_n,
            electrode_count=electrode_count,
            inscribed_radius_r0_mm=inscribed_radius_r0_mm,
            rod_radius_mm=rod_radius_mm,
            rod_z_min_mm=rod_z_min_mm,
            rod_z_max_mm=rod_z_max_mm,
            orientation_rad=orientation_rad,
        )
    if section.get("shape") != "ellipse":
        raise RoundRodGeometryError("cross_section shape must be round or ellipse")
    if rod_radius_mm is not None:
        raise RoundRodGeometryError("rod_radius_mm must be omitted for ellipse rods")
    ellipse = _ellipse_cross_section(section)
    radial_extent = (
        ellipse["semi_major_axis_mm"]
        if ellipse["major_axis_orientation"] == "radial"
        else ellipse["semi_minor_axis_mm"]
    )
    center_radius = inscribed_radius_r0_mm + radial_extent
    rods = []
    for index in range(electrode_count):
        angle = orientation_rad + 2 * math.pi * index / electrode_count
        major_axis_angle = angle + (
            0.0 if ellipse["major_axis_orientation"] == "radial" else math.pi / 2
        )
        rods.append(
            {
                "rod_id": index + 1,
                "electrode_group": 1 if index % 2 == 0 else 2,
                "angle_rad": angle,
                "center_x_mm": center_radius * math.cos(angle),
                "center_y_mm": center_radius * math.sin(angle),
                "semi_major_axis_mm": ellipse["semi_major_axis_mm"],
                "semi_minor_axis_mm": ellipse["semi_minor_axis_mm"],
                "major_axis_angle_rad": major_axis_angle,
                "z_min_mm": rod_z_min_mm,
                "z_max_mm": rod_z_max_mm,
            }
        )
    return {
        "inscribed_radius_r0": inscribed_radius_r0_mm,
        "cross_section": ellipse,
        "rod_center_radius": center_radius,
        "rod_length": rod_z_max_mm - rod_z_min_mm,
        "rods": rods,
    }


def _build_round_rod_array(
    *,
    radial_order_n: int,
    electrode_count: int,
    inscribed_radius_r0_mm: float,
    rod_radius_mm: float,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
    orientation_rad: float,
) -> dict[str, Any]:
    """Build the legacy round-rod document without changing its serialized form."""
    center_radius = inscribed_radius_r0_mm + rod_radius_mm
    rods = []
    for index in range(electrode_count):
        angle = orientation_rad + 2 * math.pi * index / electrode_count
        rods.append(
            {
                "rod_id": index + 1,
                "electrode_group": 1 if index % 2 == 0 else 2,
                "angle_rad": angle,
                "center_x_mm": center_radius * math.cos(angle),
                "center_y_mm": center_radius * math.sin(angle),
                "radius_mm": rod_radius_mm,
                "z_min_mm": rod_z_min_mm,
                "z_max_mm": rod_z_max_mm,
            }
        )
    return {
        "inscribed_radius_r0": inscribed_radius_r0_mm,
        "rod_radius": rod_radius_mm,
        "rod_center_radius": center_radius,
        "rod_length": rod_z_max_mm - rod_z_min_mm,
        "rods": rods,
    }


def build_round_rod_array(
    *,
    radial_order_n: int,
    electrode_count: int,
    inscribed_radius_r0_mm: float,
    rod_radius_mm: float,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
    orientation_rad: float = 0.0,
) -> dict[str, Any]:
    """Build the legacy circular-rod array through the round-default API."""
    return build_rod_array(
        radial_order_n=radial_order_n,
        electrode_count=electrode_count,
        inscribed_radius_r0_mm=inscribed_radius_r0_mm,
        rod_radius_mm=rod_radius_mm,
        rod_z_min_mm=rod_z_min_mm,
        rod_z_max_mm=rod_z_max_mm,
        orientation_rad=orientation_rad,
    )


def points_inside_rods(
    points_xy_mm: np.ndarray,
    rod_array: Mapping[str, Any],
    *,
    include_boundary: bool = True,
) -> np.ndarray:
    """Return one Boolean per ``(x, y)`` point indicating membership in any rod."""
    points = np.asarray(points_xy_mm, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or not np.all(np.isfinite(points)):
        raise RoundRodGeometryError("points_xy_mm must be a finite N-by-2 array")
    rods = rod_array.get("rods")
    if not isinstance(rods, list) or not rods:
        raise RoundRodGeometryError("rod_array must contain a non-empty rods list")
    inside = np.zeros(points.shape[0], dtype=bool)
    for rod in rods:
        dx = points[:, 0] - float(rod["center_x_mm"])
        dy = points[:, 1] - float(rod["center_y_mm"])
        if "radius_mm" in rod:
            normalized_radius_squared = (dx * dx + dy * dy) / float(rod["radius_mm"]) ** 2
        else:
            angle = float(rod["major_axis_angle_rad"])
            along_major = dx * math.cos(angle) + dy * math.sin(angle)
            along_minor = -dx * math.sin(angle) + dy * math.cos(angle)
            normalized_radius_squared = (
                (along_major / float(rod["semi_major_axis_mm"])) ** 2
                + (along_minor / float(rod["semi_minor_axis_mm"])) ** 2
            )
        inside |= (
            normalized_radius_squared <= 1.0
            if include_boundary
            else normalized_radius_squared < 1.0
        )
    return inside
