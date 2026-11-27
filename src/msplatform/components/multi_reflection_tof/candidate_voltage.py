"""Pure MR P/S electrode grouping and complete candidate voltage projection."""
from __future__ import annotations

import copy
import math
from typing import Any

PS_GROUPS = {"s1": (11, 12), "s2": (13, 14), "p1": (16,), "p2": (17,)}


def candidate_authority(
    source: dict[str, Any],
    candidate: dict[str, float],
    *,
    mirror_voltages_v: list[float] | None = None,
) -> dict[str, Any]:
    """Derive the single complete voltage authority without changing fixed fields."""
    if set(candidate) != set(PS_GROUPS):
        raise ValueError("candidate must specify exactly s1, s2, p1, p2 in volts")
    voltages = source["analyzer_electrode_voltages_v"]
    if len(voltages) != 20 or any(not math.isfinite(float(v)) for v in voltages):
        raise ValueError("source requires twenty finite analyzer voltages")
    result = copy.deepcopy(source)
    if mirror_voltages_v is not None:
        if len(mirror_voltages_v) != 5 or any(not math.isfinite(float(v)) for v in mirror_voltages_v):
            raise ValueError("mirror requires five finite absolute physical voltages")
        result["analyzer_electrode_voltages_v"][:10] = list(mirror_voltages_v) * 2
    for name, ids in PS_GROUPS.items():
        value = float(candidate[name])
        if not math.isfinite(value):
            raise ValueError("candidate voltages must be finite")
        for electrode in ids:
            result["analyzer_electrode_voltages_v"][electrode - 1] = value
    return result
