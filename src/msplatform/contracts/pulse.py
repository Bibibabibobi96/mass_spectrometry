"""Pure pulse authoring and field-reference projection."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any


def field_reference_drive(drive: Mapping[str, Any]) -> dict:
    """Derive one fixed OFF/ON field model without selecting the final pulse time."""
    result = copy.deepcopy(dict(drive))
    pulse = result.get("pulse")
    if not isinstance(pulse, dict) or pulse.get("mode") != "discover":
        return result
    if set(pulse) != {"mode", "width_us", "candidate_times_us"}:
        raise ValueError("discovery pulse fields differ")
    width, times = pulse["width_us"], pulse["candidate_times_us"]
    if (type(width) not in (int, float) or not math.isfinite(width) or width <= 0
            or not isinstance(times, list) or not times
            or any(type(t) not in (int, float) or not math.isfinite(t) or not math.isfinite(t + width)
                   or t + width <= t for t in times)
            or any(a >= b for a, b in zip(times, times[1:]))):
        raise ValueError("discovery requires finite ordered candidate times and a positive pulse width")
    result["pulse"] = {"mode": "timed", "time_us": times[0], "width_us": width}
    return result
