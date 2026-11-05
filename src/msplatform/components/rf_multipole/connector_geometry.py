"""Validate solver-neutral grounded connector cross sections.

Lengths and cross-section dimensions use millimetres.  A zero-length connector
is represented by ``None`` so solver adapters do not create a geometric feature.
"""

from __future__ import annotations

import math
from typing import Any


CONNECTOR_SHAPES = frozenset({"rectangular_bore", "cylindrical_bore"})


def resolve_connector_section(
    *,
    shape: str,
    length_mm: float,
    aperture_radius_mm: float,
    outer_size_mm: float,
) -> dict[str, Any] | None:
    """Return a validated connector descriptor, or ``None`` at zero length."""
    values = (float(length_mm), float(aperture_radius_mm), float(outer_size_mm))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("connector dimensions must be finite")
    length, aperture, outer_size = values
    if shape not in CONNECTOR_SHAPES:
        raise ValueError(f"unsupported connector shape: {shape}")
    if length < 0 or aperture <= 0 or outer_size <= aperture:
        raise ValueError("connector length must be nonnegative and outer size must exceed the aperture")
    if length == 0:
        return None
    return {
        "schema_version": 1,
        "role": "multipole_grounded_connector_section",
        "shape": shape,
        "length_mm": length,
        "aperture_radius_mm": aperture,
        "outer_size_mm": outer_size,
    }
