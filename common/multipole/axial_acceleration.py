"""Resolve physical rod segmentation and its common-mode voltage profile.

Voltages are electrode potentials in volts and axial dimensions are in
millimetres.  The model applies one common-mode voltage to both RF polarity
groups in each rod segment, preserving the transverse RF/DC drive.  A voltage
staircase creates a real static axial field; an equal-bias profile preserves
the same segmented geometry without claiming segmented-rod acceleration.
"""

from __future__ import annotations

import copy
import math
from typing import Any


MODEL_ID = "multipole.segmented_rod_common_mode_staircase.v2"
SIMION_MAX_ADJUSTABLE_ELECTRODE_ID = 1000
MAX_SEGMENT_COUNT = (SIMION_MAX_ADJUSTABLE_ELECTRODE_ID - 2) // 2


class AxialAccelerationError(ValueError):
    """Raised when an axial-acceleration contract is physically inconsistent."""


def _finite(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise AxialAccelerationError(f"{key} must be a finite number")
    return float(value)


def _resolve_uniform(segmentation: dict[str, Any], rod_length_mm: float) -> list[dict[str, float]]:
    expected = {
        "strategy",
        "segment_count",
        "intersegment_gap_mm",
        "entrance_common_mode_V",
        "exit_common_mode_V",
    }
    if set(segmentation) != expected:
        raise AxialAccelerationError("uniform segmentation fields differ")
    segment_count = segmentation.get("segment_count")
    if not isinstance(segment_count, int) or isinstance(segment_count, bool) or segment_count < 2:
        raise AxialAccelerationError("segment_count must be an integer of at least two")
    if segment_count > MAX_SEGMENT_COUNT:
        raise AxialAccelerationError(
            f"segment_count exceeds the shared SIMION-safe limit of {MAX_SEGMENT_COUNT}"
        )
    gap = _finite(segmentation, "intersegment_gap_mm")
    entrance_v = _finite(segmentation, "entrance_common_mode_V")
    exit_v = _finite(segmentation, "exit_common_mode_V")
    if gap < 0:
        raise AxialAccelerationError("intersegment_gap_mm must be nonnegative")
    segment_length = (rod_length_mm - (segment_count - 1) * gap) / segment_count
    if segment_length <= 0:
        raise AxialAccelerationError("segment gaps consume the complete rod length")
    return [
        {
            "length_mm": segment_length,
            "gap_after_mm": gap if index < segment_count - 1 else 0.0,
            "common_mode_V": entrance_v + index / (segment_count - 1) * (exit_v - entrance_v),
        }
        for index in range(segment_count)
    ]


def _resolve_explicit(segmentation: dict[str, Any]) -> list[dict[str, float]]:
    if set(segmentation) != {"strategy", "segments"}:
        raise AxialAccelerationError("explicit segmentation fields differ")
    source_segments = segmentation.get("segments")
    if not isinstance(source_segments, list) or len(source_segments) < 2:
        raise AxialAccelerationError("explicit segments must contain at least two entries")
    if len(source_segments) > MAX_SEGMENT_COUNT:
        raise AxialAccelerationError(
            f"explicit segment count exceeds the shared SIMION-safe limit of {MAX_SEGMENT_COUNT}"
        )
    segments = []
    for index, source in enumerate(source_segments):
        if not isinstance(source, dict):
            raise AxialAccelerationError("each explicit segment must be an object")
        allowed = {"length_mm", "gap_after_mm", "common_mode_V"}
        if not {"length_mm", "common_mode_V"} <= set(source) or not set(source) <= allowed:
            raise AxialAccelerationError("explicit segment fields differ")
        length = _finite(source, "length_mm")
        gap = _finite(source, "gap_after_mm") if "gap_after_mm" in source else 0.0
        voltage = _finite(source, "common_mode_V")
        if length <= 0 or gap < 0:
            raise AxialAccelerationError("explicit segment lengths must be positive and gaps nonnegative")
        if index == len(source_segments) - 1 and gap != 0:
            raise AxialAccelerationError("the final explicit segment gap_after_mm must be zero or omitted")
        segments.append({"length_mm": length, "gap_after_mm": gap, "common_mode_V": voltage})
    return segments


def resolve_axial_acceleration(
    contract: dict[str, Any],
    *,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
    source_kinetic_energy_ev: float,
    charge_state: int,
    require_positive_energy_gain: bool = True,
) -> dict[str, Any]:
    """Validate one segment profile and derive positions, voltages and energy."""
    expected_keys = {
        "schema_version",
        "role",
        "project_id",
        "model_id",
        "segmentation",
        "output_reference_V",
        "functional_acceptance",
        "claim_limit",
    }
    if set(contract) != expected_keys:
        raise AxialAccelerationError(
            f"axial acceleration fields differ: missing={sorted(expected_keys-set(contract))}, "
            f"unknown={sorted(set(contract)-expected_keys)}"
        )
    if contract.get("schema_version") != 2 or contract.get("role") != "multipole_axial_acceleration_contract":
        raise AxialAccelerationError("axial acceleration schema or role differs")
    if contract.get("model_id") != MODEL_ID:
        raise AxialAccelerationError("unsupported axial acceleration model_id")
    z_min = float(rod_z_min_mm)
    z_max = float(rod_z_max_mm)
    source_energy = float(source_kinetic_energy_ev)
    if not all(math.isfinite(value) for value in (z_min, z_max, source_energy)):
        raise AxialAccelerationError("rod positions and source energy must be finite")
    if z_max <= z_min or source_energy <= 0:
        raise AxialAccelerationError("rod length and source energy must be positive")
    if not isinstance(charge_state, int) or isinstance(charge_state, bool) or charge_state == 0:
        raise AxialAccelerationError("charge_state must be a nonzero integer")
    if not isinstance(require_positive_energy_gain, bool):
        raise AxialAccelerationError("require_positive_energy_gain must be boolean")
    segmentation = contract.get("segmentation")
    if not isinstance(segmentation, dict):
        raise AxialAccelerationError("segmentation must be an object")
    strategy = segmentation.get("strategy")
    if strategy == "uniform":
        source_segments = _resolve_uniform(segmentation, z_max - z_min)
    elif strategy == "explicit":
        source_segments = _resolve_explicit(segmentation)
    else:
        raise AxialAccelerationError("segmentation strategy must be uniform or explicit")
    output_v = _finite(contract, "output_reference_V")
    occupied_length = sum(item["length_mm"] + item["gap_after_mm"] for item in source_segments)
    if not math.isclose(occupied_length, z_max - z_min, rel_tol=0, abs_tol=1e-9):
        raise AxialAccelerationError("segment lengths and gaps must exactly conserve the rod length")
    segments = []
    cursor = z_min
    for index, source in enumerate(source_segments):
        segment_z_max = cursor + source["length_mm"]
        segments.append(
            {
                "segment_id": index + 1,
                "z_min_mm": cursor,
                "z_max_mm": segment_z_max,
                "common_mode_V": source["common_mode_V"],
            }
        )
        cursor = segment_z_max + source["gap_after_mm"]
    entrance_v = segments[0]["common_mode_V"]
    exit_v = segments[-1]["common_mode_V"]
    if not math.isclose(output_v, exit_v, rel_tol=0, abs_tol=1e-12):
        raise AxialAccelerationError("output_reference_V must equal the last rod-segment common mode")
    predicted_gain = charge_state * (entrance_v - output_v)
    if require_positive_energy_gain and predicted_gain <= 0:
        raise AxialAccelerationError("configured potential profile does not accelerate the selected charge sign")
    acceptance = contract.get("functional_acceptance")
    if not isinstance(acceptance, dict) or set(acceptance) != {
        "minimum_transmission",
        "minimum_mean_energy_gain_eV",
        "maximum_mean_output_energy_error_eV",
    }:
        raise AxialAccelerationError("functional_acceptance fields differ")
    for key in acceptance:
        value = _finite(acceptance, key)
        if value < 0:
            raise AxialAccelerationError(f"{key} must be nonnegative")
    if acceptance["minimum_transmission"] > 1:
        raise AxialAccelerationError("minimum_transmission must not exceed one")
    if not isinstance(contract.get("claim_limit"), str) or not contract["claim_limit"].strip():
        raise AxialAccelerationError("claim_limit must be a nonempty string")
    result = copy.deepcopy(contract)
    result["role"] = "multipole_axial_acceleration_resolved_contract"
    result["derived"] = {
        "rod_z_min_mm": z_min,
        "rod_z_max_mm": z_max,
        "segmentation_strategy": strategy,
        "segments": segments,
        "voltage_profile_monotonic": all(
            (right["common_mode_V"] - left["common_mode_V"]) * charge_state <= 0
            for left, right in zip(segments, segments[1:])
        ),
        "charge_state": charge_state,
        "source_kinetic_energy_eV": source_energy,
        "predicted_energy_gain_eV": predicted_gain,
        "predicted_output_energy_eV": source_energy + predicted_gain,
    }
    return result


def segment_rod_array(array: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    """Expand each continuous rod into solver-neutral axial electrode segments."""
    rods = array.get("rods")
    segments = resolved.get("derived", {}).get("segments")
    if not isinstance(rods, list) or not rods or not isinstance(segments, list) or not segments:
        raise AxialAccelerationError("rod array or resolved axial segments are missing")
    expanded = []
    for segment in segments:
        for rod in rods:
            item = copy.deepcopy(rod)
            item["parent_rod_id"] = int(rod["rod_id"])
            item["segment_id"] = int(segment["segment_id"])
            item["common_mode_V"] = float(segment["common_mode_V"])
            item["z_min_mm"] = float(segment["z_min_mm"])
            item["z_max_mm"] = float(segment["z_max_mm"])
            item["electrode_id"] = 2 * (item["segment_id"] - 1) + int(item["electrode_group"])
            expanded.append(item)
    return {
        "schema_version": 1,
        "role": "multipole_segmented_round_rod_array",
        "segment_count": len(segments),
        "electrode_count_per_segment": len(rods),
        "electrodes": expanded,
    }
