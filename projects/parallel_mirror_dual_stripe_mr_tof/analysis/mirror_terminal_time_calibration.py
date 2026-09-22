"""Derive device-specific TE1/TE2 seed directions for terminal-time calibration.

The directions are not copied from Astral.  They are obtained from this
instrument's measured fixed-grid mirror slope Jacobian, with the available
fine-grid gamma gradient used to keep the first-order transverse trace fixed.
They are screening coordinates only until complete 3-D flights measure their
effect at the physical detector plane.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


_GROUPS = ("mirror_B", "mirror_C", "mirror_D", "mirror_E")
_MODES = {
    "TE1": np.asarray((1.0, 1.0, 1.0)),
    "TE2": np.asarray((-1.0, 0.0, 1.0)),
}


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be one JSON object")
    return value


def _record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path).lower(),
    }


def _voltage_bounds(
    contract: Mapping[str, Any], energy_nodes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    try:
        envelope = contract["mirror"]["theory_requirements"]["voltage_envelope_v"]
        supplies = [envelope[name.removeprefix("mirror_")]["power_supply_limits_v"]
                    for name in _GROUPS]
        lower = np.asarray([float(item["minimum_inclusive_v"]) for item in supplies])
        upper = np.asarray([float(item["maximum_inclusive_v"]) for item in supplies])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("mirror power-supply envelope is incomplete") from error
    if lower.shape != (4,) or upper.shape != (4,) or np.any(lower >= upper):
        raise CandidateContractError("mirror power-supply envelope is invalid")
    upper[:3] = np.minimum(upper[:3], float(np.min(energy_nodes)))
    lower[3] = max(lower[3], math.nextafter(float(np.max(energy_nodes)), math.inf))
    return lower, upper


def derive_directions(
    *, correction_path: Path, voltage_point_path: Path, contract_path: Path,
    maximum_abs_seed_step_v: float,
) -> dict[str, Any]:
    correction = _load(correction_path, "fixed-grid mirror correction")
    point = _load(voltage_point_path, "fixed-grid mirror voltage point")
    contract = _load(contract_path, "MR-TOF contract")
    if correction.get("role") != "mrtof_fixed_grid_multifidelity_voltage_correction":
        raise CandidateContractError("fixed-grid correction role is invalid")
    if point.get("role") != "mrtof_fixed_grid_mirror_voltage_point":
        raise CandidateContractError("mirror voltage point role is invalid")
    if not math.isfinite(maximum_abs_seed_step_v) or maximum_abs_seed_step_v <= 0:
        raise CandidateContractError("TE seed voltage step must be positive")

    jacobian = np.asarray(correction.get("updated_local_slope_jacobian_per_v2"), dtype=float)
    gamma_gradient = np.asarray(correction.get("updated_fine_gamma_gradient_per_v"), dtype=float)
    energy_nodes = np.asarray(correction.get("energy_centers_ev"), dtype=float)
    current = np.asarray(point.get("mirror_voltages_v"), dtype=float)
    source = np.asarray(correction.get("proposed_mirror_voltages_v"), dtype=float)
    if (
        jacobian.shape != (3, 4) or gamma_gradient.shape != (4,)
        or energy_nodes.shape != (3,) or current.shape != (5,) or source.shape != (5,)
        or not all(np.all(np.isfinite(value)) for value in (
            jacobian, gamma_gradient, energy_nodes, current, source,
        ))
    ):
        raise CandidateContractError("TE calibration inputs have invalid dimensions or values")
    if current[0] != 0 or source[0] != 0 or not np.allclose(current[1:], source[1:], rtol=0, atol=1e-9):
        raise CandidateContractError("fixed-grid Jacobian and selected mirror point are not colocated")
    if not np.all(np.diff(energy_nodes) > 0):
        raise CandidateContractError("mirror energy nodes must be strictly increasing")

    augmented = np.vstack((jacobian, gamma_gradient))
    rank = int(np.linalg.matrix_rank(augmented))
    if rank != 4:
        raise CandidateContractError("slope-plus-gamma voltage Jacobian is rank deficient")
    condition = float(np.linalg.cond(augmented))
    lower, upper = _voltage_bounds(contract, energy_nodes)
    base = current[1:]
    directions: dict[str, Any] = {}
    for name, mode in _MODES.items():
        raw = np.linalg.solve(augmented, np.concatenate((mode, (0.0,))))
        delta = raw * (maximum_abs_seed_step_v / float(np.max(np.abs(raw))))
        candidates = []
        for sign in (-1, 1):
            trial = base + sign * delta
            if np.any(trial < lower) or np.any(trial > upper):
                raise CandidateContractError(f"{name} seed candidate violates the mirror envelope")
            candidates.append({
                "coordinate": sign,
                "mirror_voltages_v": [0.0, *(float(value) for value in trial)],
                "voltage_delta_v": [float(value) for value in sign * delta],
                "predicted_normalized_period_slope_delta_per_v": [
                    float(value) for value in jacobian @ (sign * delta)
                ],
                "predicted_gamma_trace_delta": float(gamma_gradient @ (sign * delta)),
            })
        directions[name] = {
            "definition": (
                "common three-node normalized-period-slope displacement"
                if name == "TE1"
                else "antisymmetric three-node normalized-period-slope displacement"
            ),
            "unit_mode": [float(value) for value in mode],
            "positive_voltage_delta_v": [float(value) for value in delta],
            "maximum_absolute_seed_step_v": maximum_abs_seed_step_v,
            "candidates": candidates,
        }
    return {
        "schema_version": 1,
        "role": "mrtof_device_specific_terminal_time_calibration_seed",
        "status": "screening_directions_derived",
        "qualification": "fixed_grid_local_jacobian_seed__complete_3d_terminal_flight_pending",
        "calibration_hierarchy": {
            "baseline": (
                "solve and qualify the bare mirror at the central z=0 reference plane for "
                "three-node isochronicity, transverse stability, gamma, and supply limits"
            ),
            "terminal_adjustment": (
                "with geometry, accelerator, Stripe, P1/P2, source, K, detector, and numerics "
                "frozen, vary only the device-specific mirror TE1 coordinate near that baseline"
            ),
            "primary_objective": (
                "zero the first-order arrival-time dispersion at the physical detector plane"
            ),
            "preserved_constraints": [
                "mirror three-node isochronicity budget",
                "transverse stability and gamma budget",
                "target K and current return topology",
                "mirror power-supply envelope",
            ],
            "interpretation": (
                "z=0 is the initial theoretical mirror reference and accelerator handoff, not "
                "an immutable final time-focus plane after terminal calibration"
            ),
        },
        "mirror_groups": list(_GROUPS),
        "base_mirror_voltages_v": [float(value) for value in current],
        "energy_nodes_ev": [float(value) for value in energy_nodes],
        "voltage_bounds_v": {
            name: [float(low), float(high)]
            for name, low, high in zip(_GROUPS, lower, upper, strict=True)
        },
        "jacobian": {
            "normalized_period_slope_per_v2": jacobian.tolist(),
            "gamma_trace_per_v": gamma_gradient.tolist(),
            "augmented_rank": rank,
            "augmented_condition_number": condition,
        },
        "directions": directions,
        "next_measurement": {
            "frozen_inputs": [
                "geometry", "source", "accelerator", "stripe voltages", "P1/P2 voltages",
                "detector plane", "target K", "trajectory numerics",
            ],
            "measured_outputs": [
                "detector_dt_d_source_z", "detector_time_curvature", "K", "return phase",
                "detection topology", "gamma and bare-mirror L0 spot check",
            ],
            "selection_rule": (
                "fit TE1 to zero detector first-order time slope; only then use TE2 if the "
                "remaining detector-time curvature prevents R>=100000"
            ),
        },
        "inputs": {
            "fixed_grid_correction": _record(correction_path),
            "mirror_voltage_point": _record(voltage_point_path),
            "contract": _record(contract_path),
        },
    }


def materialize_variation(
    *, seed_path: Path, mode: str, coordinate: float, output_path: Path,
) -> dict[str, Any]:
    """Freeze one exact mirror-voltage screening point from a derived seed."""
    seed = _load(seed_path, "terminal-time calibration seed")
    if (
        seed.get("schema_version") != 1
        or seed.get("role") != "mrtof_device_specific_terminal_time_calibration_seed"
        or seed.get("status") != "screening_directions_derived"
    ):
        raise CandidateContractError("terminal-time calibration seed identity is invalid")
    if mode not in _MODES:
        raise CandidateContractError("terminal-time calibration mode must be TE1 or TE2")
    if not math.isfinite(coordinate):
        raise CandidateContractError("terminal-time calibration coordinate must be finite")
    base = _vector5(seed.get("base_mirror_voltages_v"), "base mirror voltages")
    if coordinate == 0.0:
        target = base
        delta = [0.0] * 4
    else:
        direction = seed.get("directions", {}).get(mode, {})
        positive = (
            direction.get("positive_voltage_delta_v")
            if isinstance(direction, dict)
            else None
        )
        delta = [coordinate * float(value) for value in positive or ()]
        if len(delta) != 4 or not all(math.isfinite(value) for value in delta):
            raise CandidateContractError("terminal-time voltage delta is invalid")
        target = [0.0, *(float(value) for value in np.asarray(base[1:]) + delta)]
        bounds = seed.get("voltage_bounds_v")
        if not isinstance(bounds, dict):
            raise CandidateContractError("terminal-time seed voltage bounds are missing")
        for name, value in zip(_GROUPS, target[1:], strict=True):
            bound = bounds.get(name)
            if (
                not isinstance(bound, list)
                or len(bound) != 2
                or value < float(bound[0])
                or value > float(bound[1])
            ):
                raise CandidateContractError(
                    f"terminal-time coordinate violates the {name} voltage envelope"
                )
    result = {
        "schema_version": 1,
        "role": "mrtof_terminal_time_mirror_voltage_variation",
        "status": "screening_candidate_materialized",
        "qualification": "diagnostic_only__complete_3d_detector_response_pending",
        "mode": mode,
        "coordinate": coordinate,
        "base_mirror_voltages_v": base,
        "target_mirror_voltages_v": target,
        "voltage_delta_v": delta,
        "source_seed": _record(seed_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def _vector5(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 5:
        raise CandidateContractError(f"{label} must contain five values")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result) or result[0] != 0.0:
        raise CandidateContractError(f"{label} is invalid")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    derive = sub.add_parser("derive")
    derive.add_argument("--fixed-grid-correction", type=Path, required=True)
    derive.add_argument("--mirror-voltage-point", type=Path, required=True)
    derive.add_argument("--contract", type=Path, required=True)
    derive.add_argument("--maximum-absolute-seed-step-v", type=float, default=10.0)
    derive.add_argument("--output", type=Path, required=True)
    variation = sub.add_parser("materialize-variation")
    variation.add_argument("--seed", type=Path, required=True)
    variation.add_argument("--mode", choices=tuple(_MODES), required=True)
    variation.add_argument("--coordinate", type=float, required=True)
    variation.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "derive":
        result = derive_directions(
            correction_path=args.fixed_grid_correction.resolve(),
            voltage_point_path=args.mirror_voltage_point.resolve(),
            contract_path=args.contract.resolve(),
            maximum_abs_seed_step_v=args.maximum_absolute_seed_step_v,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        result = materialize_variation(
            seed_path=args.seed.resolve(), mode=args.mode, coordinate=args.coordinate,
            output_path=args.output.resolve(),
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
