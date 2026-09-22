"""Correct S1/S2 after a real fixed-grid flight while keeping P1/P2 frozen.

The accepted prism pair already owns the two injection conditions.  This
module therefore solves only the two Stripe conditions (slow-turn L and
return phase) from the previously audited finite-field Jacobian.  It never
launches SIMION and never changes mirror, prism, accelerator, or geometry.
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
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    analyze_trial,
)


EXPECTED_UNKNOWNS = (
    "stripe_1_voltage_v", "stripe_2_voltage_v",
    "prism_1_voltage_v", "prism_2_voltage_v",
)
EXPECTED_RESIDUALS = (
    "P1_P2_positive_mirror_turn_y_mm",
    "P1_P2_P2_shield_low_field_signed_vy_over_vz",
    "Stripe_slow_turn_y_minus_L_mm",
    "Stripe_target_phase_y_minus_origin_mm",
)


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be a JSON object")
    return value


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateContractError(f"{label} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def solve_locked_prism_stripe_step(
    prior: Mapping[str, Any],
    observation: Mapping[str, Any],
    materialization: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one bounded two-variable Stripe correction."""
    prior_role = prior.get("role")
    full_workpoint_prior = prior_role == "mrtof_downstream_fixed_grid_workpoint_audit"
    iterative_stripe_prior = prior_role == "mrtof_locked_prism_stripe_workpoint_step"
    if (prior.get("status") not in {
            "linearized_candidate_step", "transported_linearized_candidate_step",
        }
            or not (full_workpoint_prior or iterative_stripe_prior)
            or (full_workpoint_prior and (
                tuple(prior.get("unknown_names", ())) != EXPECTED_UNKNOWNS
                or tuple(prior.get("residual_names", ())) != EXPECTED_RESIDUALS
            ))
            or (iterative_stripe_prior and (
                prior.get("locked_coordinates") != ["prism_1_voltage_v", "prism_2_voltage_v"]
                or prior.get("solved_coordinates") != ["stripe_1_voltage_v", "stripe_2_voltage_v"]
            ))):
        raise CandidateContractError("prior workpoint Jacobian identity differs")
    if observation.get("status") != "full_drift_observed":
        raise CandidateContractError("confirmation flight did not observe a full drift return")
    return_topology = observation.get("return_topology")
    if return_topology not in {
        "exact_target_k_phase_return", "coordinate_return_before_target_phase",
    }:
        raise CandidateContractError(
            "confirmation flight has not reached the target-K mirror phase; "
            "restore the valid topology before a target-phase Newton step"
        )
    target_k = _finite(materialization.get("target_drift_period_ratio"), "target K")
    if target_k != _finite(prior.get("target_drift_period_ratio"), "prior target K"):
        raise CandidateContractError("confirmation flight changes target K")
    stripes = materialization.get("stripe_biases_v")
    prisms = materialization.get("prism_voltages_v")
    if not isinstance(stripes, list) or len(stripes) != 2:
        raise CandidateContractError("confirmation materialization lacks S1/S2")
    if not isinstance(prisms, list) or len(prisms) != 2:
        raise CandidateContractError("confirmation materialization lacks P1/P2")
    current = np.asarray([*stripes, *prisms], dtype=float)
    prior_proposal = np.asarray(prior.get("proposed_voltages_v"), dtype=float)
    if current.shape != (4,) or prior_proposal.shape != (4,) or not np.allclose(
        current, prior_proposal, rtol=0.0, atol=1.0e-10,
    ):
        raise CandidateContractError("confirmation voltages differ from the prior proposal")

    residual_map = observation.get("residuals")
    if not isinstance(residual_map, Mapping):
        raise CandidateContractError("confirmation observation lacks residuals")
    if (return_topology == "coordinate_return_before_target_phase"
            and "Stripe_target_phase_y_minus_origin_mm" not in residual_map):
        raise CandidateContractError(
            "confirmation flight has no observed target-K phase sample; "
            "restore the valid topology before a target-phase Newton step"
        )
    actual = np.asarray([
        _finite(residual_map.get(name), name) for name in EXPECTED_RESIDUALS
    ])
    target_ratio = _finite(
        materialization.get("target_low_field_tangent_ratio_vy_over_vz"),
        "target tangent ratio",
    )
    profile = contract.get("downstream_fixed_grid_workpoint_profile")
    if not isinstance(profile, Mapping) or profile.get("schema_version") != 1:
        raise CandidateContractError("downstream workpoint profile is invalid")
    position_tolerance = _finite(profile.get("position_residual_scale_mm"), "position tolerance")
    angle_tolerance_deg = _finite(profile.get("angle_residual_scale_degrees"), "angle tolerance")
    actual_angle_residual_deg = math.degrees(
        math.atan(target_ratio + actual[1]) - math.atan(target_ratio)
    )
    if abs(actual[0]) > position_tolerance or abs(actual_angle_residual_deg) > angle_tolerance_deg:
        raise CandidateContractError(
            "P1/P2 handoff is not accepted; Stripe-only correction is not allowed"
        )

    jacobian = np.asarray(prior.get("physical_jacobian_rows"), dtype=float)
    if jacobian.shape != (4, 4) or not np.all(np.isfinite(jacobian)):
        raise CandidateContractError("prior physical Jacobian must be a finite 4x4 matrix")
    stripe_jacobian = jacobian[2:4, 0:2]
    if np.linalg.matrix_rank(stripe_jacobian) != 2:
        raise CandidateContractError("locked-prism Stripe subsystem is not full rank")
    stripe_residual = actual[2:4]
    raw_delta = np.linalg.solve(stripe_jacobian, -stripe_residual)
    numerics = prior.get("resolved_numerics")
    if not isinstance(numerics, Mapping):
        raise CandidateContractError("prior workpoint lacks resolved numerics")
    maximum = np.asarray(numerics.get("maximum_abs_step_v"), dtype=float)[:2]
    lower = np.asarray(numerics.get("lower_bounds_v"), dtype=float)[:2]
    upper = np.asarray(numerics.get("upper_bounds_v"), dtype=float)[:2]
    if any(value.shape != (2,) or not np.all(np.isfinite(value)) for value in (maximum, lower, upper)):
        raise CandidateContractError("Stripe trust limits or bounds are invalid")
    nonzero = np.abs(raw_delta) > 0.0
    alpha = min(1.0, float(np.min(maximum[nonzero] / np.abs(raw_delta[nonzero])))) if np.any(nonzero) else 1.0
    for index, component in enumerate(raw_delta):
        if component > 0.0:
            alpha = min(alpha, float((upper[index] - current[index]) / component))
        elif component < 0.0:
            alpha = min(alpha, float((lower[index] - current[index]) / component))
    alpha = max(0.0, min(1.0, alpha))
    if alpha <= 0.0:
        raise CandidateContractError("no bounded Stripe correction is available")
    stripe_delta = alpha * raw_delta
    full_delta = np.asarray([stripe_delta[0], stripe_delta[1], 0.0, 0.0])
    proposed = current + full_delta
    predicted = actual + jacobian @ full_delta
    predicted_angle_residual_deg = math.degrees(
        math.atan(target_ratio + predicted[1]) - math.atan(target_ratio)
    )
    if (
        abs(predicted[0]) > position_tolerance
        or abs(predicted_angle_residual_deg) > angle_tolerance_deg
    ):
        raise CandidateContractError("Stripe correction would invalidate accepted P1/P2 handoff")
    return {
        "schema_version": 1,
        "role": "mrtof_locked_prism_stripe_workpoint_step",
        "status": "linearized_candidate_step",
        "qualification": "real_flight_corrected_candidate__requires_center_flight_confirmation",
        "target_drift_period_ratio": target_k,
        "locked_coordinates": ["prism_1_voltage_v", "prism_2_voltage_v"],
        "solved_coordinates": ["stripe_1_voltage_v", "stripe_2_voltage_v"],
        "baseline_voltages_v": current.tolist(),
        "baseline_residuals": dict(zip(EXPECTED_RESIDUALS, actual.tolist(), strict=True)),
        "p1_p2_acceptance": {
            "position_tolerance_mm": position_tolerance,
            "angle_tolerance_degrees": angle_tolerance_deg,
            "observed_angle_residual_degrees": actual_angle_residual_deg,
        },
        "stripe_jacobian_rows": stripe_jacobian.tolist(),
        "physical_jacobian_rows": jacobian.tolist(),
        "stripe_jacobian_condition_number": float(np.linalg.cond(stripe_jacobian)),
        "unbounded_stripe_correction_v": raw_delta.tolist(),
        "trust_scale": alpha,
        "applied_correction_v": full_delta.tolist(),
        "proposed_voltages_v": proposed.tolist(),
        "predicted_residuals": dict(zip(EXPECTED_RESIDUALS, predicted.tolist(), strict=True)),
        "predicted_angle_residual_degrees": predicted_angle_residual_deg,
        "resolved_numerics": dict(numerics),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-proposal", required=True, type=Path)
    parser.add_argument("--confirmation-log", required=True, type=Path)
    parser.add_argument("--confirmation-receipt", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--observation-output", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    observation = analyze_trial(
        log_path=args.confirmation_log,
        trial_receipt_path=args.confirmation_receipt,
        output_path=args.observation_output,
    )
    prior = _load(args.prior_proposal, "prior workpoint proposal")
    materialization = _load(args.confirmation_receipt, "confirmation materialization")
    contract = _load(args.contract, "project contract")
    result = solve_locked_prism_stripe_step(prior, observation, materialization, contract)
    result["inputs"] = {
        "prior_proposal": {"path": str(args.prior_proposal.resolve()), "sha256": file_sha256(args.prior_proposal)},
        "confirmation_log": {"path": str(args.confirmation_log.resolve()), "sha256": file_sha256(args.confirmation_log)},
        "confirmation_receipt": {"path": str(args.confirmation_receipt.resolve()), "sha256": file_sha256(args.confirmation_receipt)},
        "contract": {"path": str(args.contract.resolve()), "sha256": file_sha256(args.contract)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("MRTOF_LOCKED_PRISM_STRIPE_STEP=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
