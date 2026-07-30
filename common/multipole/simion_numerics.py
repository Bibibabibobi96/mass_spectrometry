"""Normalize SIMION cell spacing to the canonical three-axis contract."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

CELL_AXES = ("x", "y", "z")


def normalize_cell_mm_xyz(value: Any) -> dict[str, float]:
    """Return positive finite ``x/y/z`` cell spacing in millimetres.

    A scalar is the retained legacy representation and expands isotropically.
    The canonical representation is an object containing exactly ``x``, ``y``,
    and ``z``.
    """

    if isinstance(value, bool):
        raise ValueError("SIMION cell spacing must be positive finite numbers")
    if isinstance(value, (int, float)):
        scalar = float(value)
        if not math.isfinite(scalar) or scalar <= 0:
            raise ValueError("SIMION cell spacing must be positive finite numbers")
        return {axis: scalar for axis in CELL_AXES}
    if not isinstance(value, Mapping) or set(value) != set(CELL_AXES):
        raise ValueError("cell_mm_xyz must contain exactly x, y, and z")
    result: dict[str, float] = {}
    for axis in CELL_AXES:
        axis_value = value[axis]
        if isinstance(axis_value, bool) or not isinstance(axis_value, (int, float)):
            raise ValueError("SIMION cell spacing must be positive finite numbers")
        result[axis] = float(axis_value)
        if not math.isfinite(result[axis]) or result[axis] <= 0:
            raise ValueError("SIMION cell spacing must be positive finite numbers")
    return result


def normalize_simion_solver_numerics(
    numerics: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one SIMION numerics object without retaining a scalar alias."""

    has_legacy = "cell_mm" in numerics
    has_canonical = "cell_mm_xyz" in numerics
    if has_legacy == has_canonical:
        raise ValueError(
            "SIMION numerics must define exactly one of cell_mm or cell_mm_xyz"
        )
    result = dict(numerics)
    spacing = result.pop("cell_mm") if has_legacy else result["cell_mm_xyz"]
    result["cell_mm_xyz"] = normalize_cell_mm_xyz(spacing)
    return result
