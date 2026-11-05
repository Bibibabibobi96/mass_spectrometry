"""Scientific static-ground fact, independent of native aperture rendering."""
from __future__ import annotations
import math
from typing import Any

GROUND_POTENTIAL_V = 0.0

def require_grounded_potential(value: Any, label: str) -> float:
    """Return 0 V or reject values that would expose a biased shield."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) != GROUND_POTENTIAL_V
    ):
        raise ValueError(f"{label} must be exactly 0 V (grounded)")
    return GROUND_POTENTIAL_V
