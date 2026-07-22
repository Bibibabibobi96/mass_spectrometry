"""Resolve segmented-rod axial acceleration for the RF multipole family.

Voltages are electrode potentials in volts and axial dimensions are in
millimetres.  The model applies one common-mode voltage to both RF polarity
groups in each rod segment, preserving the transverse RF/DC drive while
creating a real static axial field between adjacent segments.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any


MODEL_ID = "multipole.segmented_rod_common_mode_staircase.v1"


class AxialAccelerationError(ValueError):
    """Raised when an axial-acceleration contract is physically inconsistent."""


def _finite(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise AxialAccelerationError(f"{key} must be a finite number")
    return float(value)


def resolve_axial_acceleration(
    contract: dict[str, Any],
    *,
    rod_z_min_mm: float,
    rod_z_max_mm: float,
    source_kinetic_energy_ev: float,
    charge_state: int,
) -> dict[str, Any]:
    """Validate one mode and derive segment positions, voltages and energy gain."""
    expected_keys = {
        "schema_version",
        "role",
        "project_id",
        "model_id",
        "segment_count",
        "intersegment_gap_mm",
        "entrance_common_mode_V",
        "exit_common_mode_V",
        "output_reference_V",
        "functional_acceptance",
        "claim_limit",
    }
    if set(contract) != expected_keys:
        raise AxialAccelerationError(
            f"axial acceleration fields differ: missing={sorted(expected_keys-set(contract))}, "
            f"unknown={sorted(set(contract)-expected_keys)}"
        )
    if contract.get("schema_version") != 1 or contract.get("role") != "multipole_axial_acceleration_contract":
        raise AxialAccelerationError("axial acceleration schema or role differs")
    if contract.get("model_id") != MODEL_ID:
        raise AxialAccelerationError("unsupported axial acceleration model_id")
    segment_count = contract.get("segment_count")
    if not isinstance(segment_count, int) or isinstance(segment_count, bool) or segment_count < 2:
        raise AxialAccelerationError("segment_count must be an integer of at least two")
    z_min = float(rod_z_min_mm)
    z_max = float(rod_z_max_mm)
    source_energy = float(source_kinetic_energy_ev)
    if not all(math.isfinite(value) for value in (z_min, z_max, source_energy)):
        raise AxialAccelerationError("rod positions and source energy must be finite")
    if z_max <= z_min or source_energy <= 0:
        raise AxialAccelerationError("rod length and source energy must be positive")
    if not isinstance(charge_state, int) or isinstance(charge_state, bool) or charge_state == 0:
        raise AxialAccelerationError("charge_state must be a nonzero integer")
    gap = _finite(contract, "intersegment_gap_mm")
    entrance_v = _finite(contract, "entrance_common_mode_V")
    exit_v = _finite(contract, "exit_common_mode_V")
    output_v = _finite(contract, "output_reference_V")
    if gap <= 0:
        raise AxialAccelerationError("intersegment_gap_mm must be positive")
    metal_length = (z_max - z_min) - (segment_count - 1) * gap
    if metal_length <= 0:
        raise AxialAccelerationError("segment gaps consume the complete rod length")
    segment_length = metal_length / segment_count
    segments = []
    for index in range(segment_count):
        segment_z_min = z_min + index * (segment_length + gap)
        fraction = index / (segment_count - 1)
        segments.append(
            {
                "segment_id": index + 1,
                "z_min_mm": segment_z_min,
                "z_max_mm": segment_z_min + segment_length,
                "common_mode_V": entrance_v + fraction * (exit_v - entrance_v),
            }
        )
    if not math.isclose(output_v, exit_v, rel_tol=0, abs_tol=1e-12):
        raise AxialAccelerationError("output_reference_V must equal the last rod-segment common mode")
    predicted_gain = charge_state * (entrance_v - output_v)
    if predicted_gain <= 0:
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
        "segment_length_mm": segment_length,
        "segments": segments,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--rod-geometry", required=True, type=Path)
    parser.add_argument("--source-energy-ev", required=True, type=float)
    parser.add_argument("--charge-state", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--segmented-rods-output", type=Path)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    geometry = json.loads(args.rod_geometry.read_text(encoding="utf-8-sig"))
    array = geometry["array_mm"] if "array_mm" in geometry else geometry["rod_array_mm"]
    rods = array["rods"]
    resolved = resolve_axial_acceleration(
        contract,
        rod_z_min_mm=float(rods[0]["z_min_mm"]),
        rod_z_max_mm=float(rods[0]["z_max_mm"]),
        source_kinetic_energy_ev=args.source_energy_ev,
        charge_state=args.charge_state,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
    if args.segmented_rods_output is not None:
        args.segmented_rods_output.parent.mkdir(parents=True, exist_ok=True)
        args.segmented_rods_output.write_text(
            json.dumps(segment_rod_array(array, resolved), indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
