"""Audit one bounded finite-3-D downstream Newton-direction trial.

This module deliberately does not choose a trust-region radius or a physical
acceptance tolerance.  It proves that a supplied SIMION trial is a positive
scalar multiple of the audited local Newton direction, compares actual and
predicted scaled-objective reductions, and requires a new Jacobian before any
further step can be proposed.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_voltage_definition import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
    _load,
    _trial,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def _definition_summary(manifest_path: Path) -> dict[str, Any]:
    manifest = _load(manifest_path)
    base = manifest_path.resolve().parent
    allowed_modes = {
        "finite_3d_downstream_voltage_definition_audit",
        "finite_3d_downstream_central_difference_audit",
    }
    if (
        manifest.get("status") != "success"
        or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") not in allowed_modes
    ):
        raise CandidateContractError(f"not a successful downstream definition audit: {manifest_path}")
    verify_record("run_config", manifest["run_config"], base_dir=base)
    summaries: list[Path] = []
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"output {index}", record, base_dir=base)
        path = record_path(record, base_dir=base)
        if path.name == "summary.json":
            summaries.append(path)
    if len(summaries) != 1:
        raise CandidateContractError("definition manifest must bind exactly one summary.json")
    return _load(summaries[0])


def _vector(value: Any, length: int, label: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length:
        raise CandidateContractError(f"{label} must contain {length} values")
    result = np.asarray(value, dtype=float)
    if result.shape != (length,) or not np.all(np.isfinite(result)):
        raise CandidateContractError(f"{label} must be a finite vector")
    return result


def assess_bounded_step(
    definition: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Compare one actual trial with its audited local linear prediction."""
    role = definition.get("role")
    if role == "mrtof_finite_3d_downstream_voltage_definition_audit":
        classification = definition.get("classification", {})
        jacobian_value = definition.get("physical_jacobian_rows")
        correction_value = definition.get("undamped_linear_correction_v")
        derivative_kind = "forward"
    elif role == "mrtof_finite_3d_downstream_central_difference_audit":
        classification = definition.get("classifications", {}).get("central", {})
        jacobian_value = definition.get("physical_jacobians", {}).get("central")
        correction_value = definition.get("central_undamped_linear_correction_v")
        derivative_kind = "central"
    else:
        raise CandidateContractError("bounded step requires a supported downstream definition role")
    if (
        definition.get("status") != "success"
        or definition.get("unknown_names") != list(UNKNOWN_NAMES)
        or definition.get("residual_names") != list(RESIDUAL_NAMES)
        or classification.get("status") != "square_exact"
    ):
        raise CandidateContractError("bounded step requires one square-exact downstream definition")
    baseline = definition.get("baseline")
    if not isinstance(baseline, dict) or candidate.get("frozen_problem") != baseline.get("frozen_problem"):
        raise CandidateContractError("candidate and definition do not share one frozen physical problem")
    n = len(UNKNOWN_NAMES)
    p0 = _vector(baseline.get("parameters"), n, "baseline parameters")
    r0 = _vector(baseline.get("residuals"), n, "baseline residuals")
    p1 = _vector(candidate.get("parameters"), n, "candidate parameters")
    r1 = _vector(candidate.get("residuals"), n, "candidate residuals")
    correction = _vector(correction_value, n, "Newton correction")
    scales = _vector(definition.get("residual_scales"), n, "residual scales")
    jacobian = np.asarray(jacobian_value, dtype=float)
    if jacobian.shape != (n, n) or not np.all(np.isfinite(jacobian)) or np.any(scales <= 0.0):
        raise CandidateContractError("definition has an invalid Jacobian or residual scale")
    delta = p1 - p0
    if not np.any(delta):
        raise CandidateContractError("candidate must differ from the definition baseline")
    active = np.abs(correction) > 64.0 * np.finfo(float).eps * np.maximum(np.abs(p0), 1.0)
    if np.any(np.abs(delta[~active]) > 1e-10):
        raise CandidateContractError("candidate changes a coordinate absent from the Newton direction")
    ratios = delta[active] / correction[active]
    alpha = float(np.median(ratios))
    if alpha <= 0.0 or not math.isfinite(alpha):
        raise CandidateContractError("candidate is not a positive Newton-direction step")
    direction_error = float(np.max(np.abs(delta - alpha * correction)))
    direction_scale = max(float(np.max(np.abs(delta))), 1.0)
    if direction_error > 1e-9 * direction_scale:
        raise CandidateContractError("candidate is not one scalar multiple of the Newton direction")
    predicted = r0 + jacobian @ delta

    def objective(residual: np.ndarray) -> float:
        scaled = residual / scales
        return 0.5 * float(scaled @ scaled)

    objective0 = objective(r0)
    objective_predicted = objective(predicted)
    objective1 = objective(r1)
    predicted_reduction = objective0 - objective_predicted
    actual_reduction = objective0 - objective1
    if predicted_reduction <= 0.0:
        raise CandidateContractError("local model does not predict descent for the supplied step")
    ratio = actual_reduction / predicted_reduction
    descent = actual_reduction > 0.0
    return {
        "schema_version": 1,
        "role": "mrtof_finite_3d_downstream_bounded_step_audit",
        "status": "success",
        "qualification": (
            "descent_observed__new_jacobian_required"
            if descent
            else "actual_objective_increased__step_rejected"
        ),
        "definition_run_id": baseline.get("run_id"),
        "definition_derivative_kind": derivative_kind,
        "candidate_run_id": candidate.get("run_id"),
        "unknown_names": list(UNKNOWN_NAMES),
        "residual_names": list(RESIDUAL_NAMES),
        "baseline_parameters_v": p0.tolist(),
        "candidate_parameters_v": p1.tolist(),
        "bounded_delta_v": delta.tolist(),
        "maximum_absolute_coordinate_step_v": float(np.max(np.abs(delta))),
        "newton_direction_fraction": alpha,
        "baseline_residuals": r0.tolist(),
        "predicted_residuals": predicted.tolist(),
        "actual_residuals": r1.tolist(),
        "residual_scales": scales.tolist(),
        "baseline_scaled_objective": objective0,
        "predicted_scaled_objective": objective_predicted,
        "actual_scaled_objective": objective1,
        "predicted_objective_reduction": predicted_reduction,
        "actual_objective_reduction": actual_reduction,
        "actual_to_predicted_reduction_ratio": ratio,
        "iteration_authority": "none__this_audit_does_not_choose_the_next_radius_or_publish_a_voltage",
        "required_next_action": "recompute_four_axis_jacobian_at_candidate_before_any_further_step",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition-manifest", required=True, type=Path)
    parser.add_argument("--candidate-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = assess_bounded_step(
        _definition_summary(args.definition_manifest), _trial(args.candidate_manifest)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "MRTOF_DOWNSTREAM_BOUNDED_STEP=PASS "
        f"QUALIFICATION={result['qualification']} "
        f"RATIO={result['actual_to_predicted_reduction_ratio']:.12g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
