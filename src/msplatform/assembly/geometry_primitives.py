"""Solver-neutral finite scalar and affine point utilities."""
from __future__ import annotations

import math
from typing import Any


def _finite(value: Any) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numeric assembly input required")
    return float(value)


def _point(point: list, rotation: list, translation: list) -> list:
    return [sum(a * b for a, b in zip(row, point)) + shift for row, shift in zip(rotation, translation)]


def polygon_membership(point: tuple[float, float], polygon: list[list[float]]) -> tuple[bool, float]:
    y, z = point
    inside = False
    distance = math.inf
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        y0, z0 = float(start[0]), float(start[1])
        y1, z1 = float(end[0]), float(end[1])
        dy, dz = y1 - y0, z1 - z0
        scale = dy * dy + dz * dz
        along = 0.0 if scale == 0.0 else max(0.0, min(1.0, ((y - y0) * dy + (z - z0) * dz) / scale))
        distance = min(distance, math.hypot(y - (y0 + along * dy), z - (z0 + along * dz)))
        if (z0 > z) != (z1 > z):
            crossing_y = y0 + (z - z0) * dy / dz
            if y < crossing_y:
                inside = not inside
    return inside, distance
