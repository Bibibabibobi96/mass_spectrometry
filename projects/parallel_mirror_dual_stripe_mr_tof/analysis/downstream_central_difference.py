"""Audit central finite differences for the 3-D Stripe/P1/P2 solve.

This consumes a baseline plus paired positive/negative single-coordinate
SIMION trials.  It compares the forward, backward, and central Jacobians,
including the effective two-Stripe response after locally eliminating P1/P2.
The reported Newton correction is diagnostic only and is never executed here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_voltage_definition import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
    _finite,
    _trial,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    classify_constraint_system,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


def _axis_delta(
    trial: dict[str, Any], baseline_parameters: np.ndarray, index: int, sign: int
) -> float:
    delta = np.asarray(trial["parameters"], dtype=float) - baseline_parameters
    tolerance = np.maximum(1e-12, 1e-12 * np.maximum(np.abs(baseline_parameters), 1.0))
    changed = np.flatnonzero(np.abs(delta) > tolerance)
    if changed.tolist() != [index] or sign * delta[index] <= 0.0:
        direction = "positively" if sign > 0 else "negatively"
        raise CandidateContractError(
            f"axis trial {index + 1} must {direction} perturb only {UNKNOWN_NAMES[index]}"
        )
    return float(abs(delta[index]))


def _classification(
    jacobian: np.ndarray,
    residuals: np.ndarray,
    parameter_scales: list[float],
    residual_scales: list[float],
    rank_tolerance: float,
) -> dict[str, Any]:
    return asdict(
        classify_constraint_system(
            UNKNOWN_NAMES,
            RESIDUAL_NAMES,
            jacobian_rows=jacobian.tolist(),
            residuals=residuals.tolist(),
            parameter_scales=parameter_scales,
            residual_scales=residual_scales,
            relative_rank_tolerance=rank_tolerance,
        )
    )


def _effective_stripe_response(scaled_jacobian: np.ndarray) -> dict[str, Any]:
    # Rows 0:2 are the P1/P2 hand-off constraints.  Columns 2:4 are
    # P1/P2.  Eliminate those local prism coordinates before evaluating how
    # independently the two Stripe coordinates control the two drift targets.
    a = scaled_jacobian[:2, :2]
    b = scaled_jacobian[:2, 2:]
    c = scaled_jacobian[2:, :2]
    d = scaled_jacobian[2:, 2:]
    try:
        effective = c - d @ np.linalg.solve(b, a)
        prism_rank = int(np.linalg.matrix_rank(b))
    except np.linalg.LinAlgError:
        return {
            "status": "prism_handoff_block_singular",
            "prism_handoff_rank": int(np.linalg.matrix_rank(b)),
            "matrix": None,
            "singular_values": None,
            "condition_number_2": math.inf,
        }
    singular = np.linalg.svd(effective, compute_uv=False)
    condition = math.inf if singular[-1] == 0.0 else float(singular[0] / singular[-1])
    return {
        "status": "evaluated",
        "prism_handoff_rank": prism_rank,
        "matrix": effective.tolist(),
        "singular_values": singular.tolist(),
        "condition_number_2": condition,
    }


def audit_central_difference(
    *,
    contract_path: Path,
    baseline_manifest: Path,
    plus_manifests: Sequence[Path],
    minus_manifests: Sequence[Path],
) -> dict[str, Any]:
    """Return derivative-convergence evidence without selecting a new point."""
    if len(plus_manifests) != len(UNKNOWN_NAMES) or len(minus_manifests) != len(UNKNOWN_NAMES):
        raise CandidateContractError("exactly four ordered positive and four negative trials are required")
    contract = load_contract(contract_path)
    baseline = _trial(baseline_manifest)
    plus = [_trial(path) for path in plus_manifests]
    minus = [_trial(path) for path in minus_manifests]
    if any(
        trial["frozen_problem"] != baseline["frozen_problem"]
        for trial in plus + minus
    ):
        raise CandidateContractError("central-difference trials do not share one frozen physical problem")

    p0 = np.asarray(baseline["parameters"], dtype=float)
    r0 = np.asarray(baseline["residuals"], dtype=float)
    forward_columns: list[np.ndarray] = []
    backward_columns: list[np.ndarray] = []
    central_columns: list[np.ndarray] = []
    steps: list[float] = []
    step_mismatch: list[float] = []
    for index, (positive, negative) in enumerate(zip(plus, minus)):
        hp = _axis_delta(positive, p0, index, +1)
        hm = _axis_delta(negative, p0, index, -1)
        allowed = max(1e-12, 1e-9 * max(hp, hm, 1.0))
        if abs(hp - hm) > allowed:
            raise CandidateContractError(
                f"positive/negative steps for {UNKNOWN_NAMES[index]} are not symmetric"
            )
        rp = np.asarray(positive["residuals"], dtype=float)
        rm = np.asarray(negative["residuals"], dtype=float)
        forward_columns.append((rp - r0) / hp)
        backward_columns.append((r0 - rm) / hm)
        central_columns.append((rp - rm) / (hp + hm))
        steps.append(0.5 * (hp + hm))
        step_mismatch.append(hp - hm)

    forward = np.column_stack(forward_columns)
    backward = np.column_stack(backward_columns)
    central = np.column_stack(central_columns)
    frozen = baseline["frozen_problem"]
    length_scale = _finite(frozen["target_slow_turn_y_mm"], "drift-length scale")
    energy_scale = _finite(
        frozen["target_slow_kinetic_energy_per_charge_v"], "slow-energy scale"
    )
    k_scale = _finite(frozen["target_oscillation_count"], "target-K scale")
    parameter_scales = [max(abs(value), 1.0) for value in p0]
    residual_scales = [length_scale, energy_scale, length_scale, k_scale]
    rank_tolerance = _finite(
        contract["dual_stripe_l0"]["determination_numerics"][
            "relative_singular_value_rank_tolerance"
        ],
        "relative singular-value rank tolerance",
    )

    pscale = np.asarray(parameter_scales, dtype=float)
    rscale = np.asarray(residual_scales, dtype=float)
    scaled = {
        "forward": forward * pscale[np.newaxis, :] / rscale[:, np.newaxis],
        "backward": backward * pscale[np.newaxis, :] / rscale[:, np.newaxis],
        "central": central * pscale[np.newaxis, :] / rscale[:, np.newaxis],
    }
    column_disagreement: list[dict[str, float | str]] = []
    for index, name in enumerate(UNKNOWN_NAMES):
        fcol = scaled["forward"][:, index]
        bcol = scaled["backward"][:, index]
        ccol = scaled["central"][:, index]
        denominator = max(float(np.linalg.norm(ccol)), np.finfo(float).eps)
        column_disagreement.append(
            {
                "unknown": name,
                "scaled_forward_backward_difference_norm_2": float(np.linalg.norm(fcol - bcol)),
                "relative_to_scaled_central_column_norm_2": float(
                    np.linalg.norm(fcol - bcol) / denominator
                ),
            }
        )

    correction = None
    central_classification = _classification(
        central, r0, parameter_scales, residual_scales, rank_tolerance
    )
    if central_classification["status"] == "square_exact":
        correction = np.linalg.solve(central, -r0).tolist()

    return {
        "schema_version": 1,
        "role": "mrtof_finite_3d_downstream_central_difference_audit",
        "status": "success",
        "qualification": "derivative_convergence_evidence_only__iteration_not_authorized",
        "unknown_names": list(UNKNOWN_NAMES),
        "residual_names": list(RESIDUAL_NAMES),
        "baseline": baseline,
        "plus_trials": plus,
        "minus_trials": minus,
        "symmetric_steps_v": steps,
        "signed_step_mismatch_v": step_mismatch,
        "parameter_scales_v": parameter_scales,
        "residual_scales": residual_scales,
        "physical_jacobians": {
            "forward": forward.tolist(),
            "backward": backward.tolist(),
            "central": central.tolist(),
        },
        "classifications": {
            "forward": _classification(forward, r0, parameter_scales, residual_scales, rank_tolerance),
            "backward": _classification(backward, r0, parameter_scales, residual_scales, rank_tolerance),
            "central": central_classification,
        },
        "scaled_forward_backward_column_disagreement": column_disagreement,
        "effective_two_stripe_responses": {
            name: _effective_stripe_response(matrix) for name, matrix in scaled.items()
        },
        "central_undamped_linear_correction_v": correction,
        "iteration_status": "not_executed__central_difference_audit_does_not_choose_a_trust_radius",
        "limits": [
            "one center ion at one analyzer mesh and time-step setting",
            "the central Newton correction is diagnostic and is not an accepted voltage point",
            "no derivative-convergence acceptance tolerance is invented by this audit",
            "mirror and accelerator voltages remain frozen",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--plus-manifest", required=True, action="append", type=Path)
    parser.add_argument("--minus-manifest", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit_central_difference(
        contract_path=args.contract,
        baseline_manifest=args.baseline_manifest,
        plus_manifests=args.plus_manifest,
        minus_manifests=args.minus_manifest,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    central = result["classifications"]["central"]
    effective = result["effective_two_stripe_responses"]["central"]
    print(
        "MRTOF_DOWNSTREAM_CENTRAL_DIFFERENCE=PASS "
        f"CLASS={central['status']} COND={central['condition_number_2']:.12g} "
        f"STRIPE_COND={effective['condition_number_2']:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
