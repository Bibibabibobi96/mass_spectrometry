"""Analyze a complete three-arm reflectron resolution comparison."""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Mapping


def compare_resolutions(modes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Compare the three recorded metrics; missing/invalid resolution is inconclusive."""
    baseline, compensated, ideal = (
        modes[label]["canonical_peak_metrics"].get("mass_resolution")
        for label in ("baseline", "compensated", "ideal_reflectron")
    )
    supported = (all(value is not None and math.isfinite(float(value))
                     for value in (baseline, compensated, ideal))
                 and baseline > 0 and ideal > 0)
    return {
        "scientific_result": ("resolution_gain" if compensated > baseline else "no_resolution_gain")
                             if supported else "INCONCLUSIVE",
        "resolution_gain_ratio": compensated / baseline if supported else None,
        "remaining_gap_ratio_to_ideal_reflectron": (ideal - compensated) / ideal if supported else None,
    }


def compile_compensated_study(study: Mapping[str, Any], *, instance_id: str, fit: Mapping[str, Any]) -> dict[str, Any]:
    """Derive a new Study author document by replacing only the fitted ring drives.

    The caller persists the returned document as a new author and binds its
    bytes in a new recipe; this never changes a resolved recipe or a field.
    """
    if not isinstance(study, Mapping) or not isinstance(instance_id, str) or not instance_id:
        raise ValueError("explicit Study and TOF instance are required")
    if not isinstance(fit, Mapping) or fit.get("status") != "success" or fit.get("role") != "oatof_reflectron_monotone_axis_field_voltage_fit":
        raise ValueError("a successful reflectron voltage fit is required")
    try:
        groups = study["drive"]["groups"][instance_id]
        endpoints = fit["fixed_endpoints_V"]
        mid, back = endpoints["midgrid"], endpoints["backplate"]
        if (not isinstance(groups, Mapping) or endpoints["entrance"] != 0.0 or endpoints["shield"] != 0.0
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in (mid, back))
                or not 0 < mid <= back):
            raise ValueError("fit endpoints are invalid")
        for name, value in (("reflectron_midgrid", mid), ("reflectron_backplate", back)):
            if groups[name] != {"kind": "static", "voltage_v": value}:
                raise ValueError("fit endpoints differ from the original Study drive")
        replacement = {}
        for stage, lower, upper in ((1, 0.0, mid), (2, mid, back)):
            count = fit[f"stage{stage}_count"]
            values = fit[f"stage{stage}_ring_voltages_V"]
            baseline = fit[f"baseline_stage{stage}_ring_voltages_V"]
            if (type(count) is not int or count < 1 or not isinstance(values, list) or len(values) != count
                    or not isinstance(baseline, list) or len(baseline) != count):
                raise ValueError("fit ring counts differ")
            last = lower
            for index, (value, original) in enumerate(zip(values, baseline, strict=True), 1):
                if (type(value) not in (int, float) or not math.isfinite(value) or not last <= value <= upper
                        or type(original) not in (int, float) or not math.isfinite(original)):
                    raise ValueError("fit voltages must be finite and monotone within endpoints")
                name = f"reflectron_stage{stage}_ring_{index}"
                old = groups[name]
                if not isinstance(old, Mapping) or set(old) != {"kind", "voltage_v"} or old["kind"] != "static":
                    raise ValueError("Study reflectron rings must be explicit static drives")
                from msplatform.contracts.particle_state import binary64_serialization_close
                if not binary64_serialization_close(float(old["voltage_v"]), float(original)):
                    raise ValueError("fit baseline differs from the original Study drive")
                replacement[name] = {"kind": "static", "voltage_v": float(value)}
                last = value
    except (KeyError, TypeError) as exc:
        raise ValueError("Study or fit omits explicit reflectron drive fields") from exc
    actual_rings = {name for name in groups if re.fullmatch(r"reflectron_stage[12]_ring_\d+", name)}
    if actual_rings != set(replacement):
        raise ValueError("fit ring IDs differ from the original Study drive")
    result = copy.deepcopy(dict(study))
    result["drive"]["groups"][instance_id].update(replacement)
    return result
