"""Solver-neutral finite scalar and affine point utilities."""
from __future__ import annotations

from typing import Any


def _finite(value: Any) -> float:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numeric assembly input required")
    return float(value)


def _point(point: list, rotation: list, translation: list) -> list:
    return [sum(a * b for a, b in zip(row, point)) + shift for row, shift in zip(rotation, translation)]
