"""Create a traceable SIMION run-local operating-point variation.

This is deliberately a run adapter, not a geometry or hardware-voltage writer.
It derives every field from an already materialized Candidate operating point and
permits only explicit, structured diagnostic overrides.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


class OperatingPointVariationError(ValueError):
    """Raised when a variation would be ambiguous or unsafe to materialize."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OperatingPointVariationError(f"{label} must be finite")
    return float(value)


def _numbers(text: str, label: str, count: int) -> list[float]:
    try:
        values = [float(value.strip()) for value in text.split(",")]
    except ValueError as error:
        raise OperatingPointVariationError(f"{label} contains a non-numeric value") from error
    if len(values) != count or not all(math.isfinite(value) for value in values):
        raise OperatingPointVariationError(f"{label} requires {count} finite values")
    return values


def _field(source: str, name: str, count: int | None = None) -> float | list[float]:
    if count is None:
        match = re.search(rf"\b{re.escape(name)}\s*=\s*([^,}}]+)", source)
        if not match:
            raise OperatingPointVariationError(f"base operating point lacks {name}")
        return _finite(float(match.group(1).strip()), name)
    match = re.search(rf"\b{re.escape(name)}\s*=\s*\{{([^}}]+)\}}", source)
    if not match:
        raise OperatingPointVariationError(f"base operating point lacks {name}")
    return _numbers(match.group(1), name, count)


def load_operating_point(path: Path) -> dict[str, Any]:
    """Parse the strict generated Lua sidecar shape, rejecting arbitrary Lua."""
    source = path.read_text(encoding="utf-8")
    if "return {" not in source:
        raise OperatingPointVariationError("base sidecar is not a generated Lua return table")
    return {
        "mirror_voltages_v": _field(source, "mirror_voltages_v", 5),
        "stripe_biases_v": _field(source, "stripe_biases_v", 2),
        "prism_voltages_v": _field(source, "prism_voltages_v", 2),
        "accelerator_voltages_v": _field(source, "accelerator_voltages_v", 3),
        "accelerator_ring_voltages_v": _field(source, "accelerator_ring_voltages_v", 5),
        "detector_box_mm": _field(source, "detector_box_mm", 6),
        "trajectory_quality": _field(source, "trajectory_quality"),
        "maximum_step_us": _field(source, "maximum_step_us"),
        "full_path_timeout_us": _field(source, "full_path_timeout_us"),
        "nonaccelerator_scale": _field(source, "nonaccelerator_scale"),
        "target_oscillation_count": _field(source, "target_oscillation_count"),
    }


def apply_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply only declared diagnostic degrees of freedom to a base point."""
    allowed = {
        "mirror_voltage_multipliers", "stripe_biases_v", "nonaccelerator_scale",
        "trajectory_quality", "maximum_step_us",
    }
    unknown = set(overrides) - allowed
    if unknown:
        raise OperatingPointVariationError(f"unsupported operating-point overrides: {sorted(unknown)}")
    result = {key: (list(value) if isinstance(value, list) else value) for key, value in base.items()}
    if "mirror_voltage_multipliers" in overrides:
        multipliers = [_finite(value, "mirror_voltage_multipliers") for value in overrides["mirror_voltage_multipliers"]]
        if len(multipliers) != 5 or abs(multipliers[0] - 1.0) > 1e-12:
            raise OperatingPointVariationError("mirror_voltage_multipliers requires five values with grounded A multiplier 1")
        result["mirror_voltages_v"] = [
            value * multiplier for value, multiplier in zip(result["mirror_voltages_v"], multipliers)
        ]
    if "stripe_biases_v" in overrides:
        values = [_finite(value, "stripe_biases_v") for value in overrides["stripe_biases_v"]]
        if len(values) != 2:
            raise OperatingPointVariationError("stripe_biases_v requires exactly two values")
        result["stripe_biases_v"] = values
    if "nonaccelerator_scale" in overrides:
        scale = _finite(overrides["nonaccelerator_scale"], "nonaccelerator_scale")
        if scale <= 0.0:
            raise OperatingPointVariationError("nonaccelerator_scale must be positive")
        result["nonaccelerator_scale"] = scale
    for field in ("trajectory_quality", "maximum_step_us"):
        if field in overrides:
            value = _finite(overrides[field], field)
            if value <= 0.0:
                raise OperatingPointVariationError(f"{field} must be positive")
            result[field] = value
    return result


def render_operating_point(point: dict[str, Any], receipt_sha256: str) -> str:
    """Render the only Lua table shape consumed by ``mrtof_candidate.lua``."""
    values = lambda name: ", ".join(f"{value:.17g}" for value in point[name])
    scalar = lambda name: f"{float(point[name]):.17g}"
    return (
        "-- Generated run-local SIMION diagnostic variation; do not edit.\n"
        f"-- base_operating_point_sha256={receipt_sha256}\n"
        "return { "
        f"mirror_voltages_v = {{ {values('mirror_voltages_v')} }}, "
        f"stripe_biases_v = {{ {values('stripe_biases_v')} }}, "
        f"prism_voltages_v = {{ {values('prism_voltages_v')} }}, "
        f"accelerator_voltages_v = {{ {values('accelerator_voltages_v')} }}, "
        f"accelerator_ring_voltages_v = {{ {values('accelerator_ring_voltages_v')} }}, "
        f"detector_box_mm = {{ {values('detector_box_mm')} }}, detector_normal_project = '+z', "
        f"trajectory_quality = {scalar('trajectory_quality')}, "
        f"maximum_step_us = {scalar('maximum_step_us')}, "
        f"full_path_timeout_us = {scalar('full_path_timeout_us')}, "
        f"nonaccelerator_scale = {scalar('nonaccelerator_scale')}, "
        f"target_oscillation_count = {scalar('target_oscillation_count')} }}\n"
    )


def materialize_variation(base_path: Path, overrides_path: Path, output_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Write one derived sidecar and its machine-readable receipt."""
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    if not isinstance(overrides, dict) or not isinstance(overrides.get("overrides"), dict):
        raise OperatingPointVariationError("variation JSON requires an overrides object")
    base = load_operating_point(base_path)
    point = apply_overrides(base, overrides["overrides"])
    base_hash = _sha256(base_path)
    output_path.write_text(render_operating_point(point, base_hash), encoding="utf-8", newline="\n")
    receipt = {
        "schema_version": 1,
        "status": "diagnostic_only__not_candidate_operating_point",
        "purpose": overrides.get("purpose", "unspecified diagnostic"),
        "base_operating_point": {"filename": base_path.name, "sha256": base_hash},
        "overrides": overrides["overrides"],
        "resolved_operating_point": point,
        "output": {"filename": output_path.name, "sha256": _sha256(output_path)},
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize a run-local SIMION operating-point variation.")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overrides", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    materialize_variation(arguments.base, arguments.overrides, arguments.output, arguments.receipt)
    print(f"SIMION_OPERATING_POINT_VARIATION=PASS output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
