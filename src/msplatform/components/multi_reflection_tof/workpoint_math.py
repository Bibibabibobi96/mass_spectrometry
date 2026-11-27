"""MR workpoint bounded model and constrained linear program."""
from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import linprog

from msplatform.components.multi_reflection_tof.candidate_contract import CandidateContractError
from msplatform.components.multi_reflection_tof.constraint_classification import classify_constraint_system


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateContractError(f"{label} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _vector(values: object, length: int, label: str) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.shape != (length,) or not np.all(np.isfinite(result)):
        raise CandidateContractError(f"{label} must contain {length} finite values")
    return result


def _joint_ps_step(columns: np.ndarray, residuals: np.ndarray, tolerances: np.ndarray,
                   voltages: np.ndarray, numerics: Mapping[str, Any], relative: float) -> tuple[np.ndarray, np.ndarray]:
    """Minimize the worst S residual inside the original P acceptance window.

    SciPy HiGHS solves this four-variable linear program: three scaled voltage
    increments and a nonnegative maximum normalized S residual. No P equality
    or regularization is added. Recheck its model constraints before real Fly.
    """
    axes = np.asarray([0, 2, 3])
    scales = _vector(numerics["parameter_scales_v"], 4, "joint parameter scales")[axes]
    if (columns.shape != (4, 3) or residuals.shape != (4,) or tolerances.shape != (4,)
            or not all(np.all(np.isfinite(v)) for v in (columns, residuals, tolerances, voltages, scales))
            or np.any(tolerances <= 0) or np.any(scales <= 0)):
        raise CandidateContractError("joint P/S model requires finite 4x3 columns and positive scales")
    a = columns * scales / tolerances[:, None]
    r = residuals / tolerances
    trust = np.minimum(_vector(numerics["maximum_abs_step_v"], 4, "joint maximum step")[axes],
                       relative * np.maximum(np.abs(voltages[axes]), 1.0))
    lower = np.maximum(_vector(numerics["lower_bounds_v"], 4, "joint lower bounds")[axes] - voltages[axes],
                       -trust) / scales
    upper = np.minimum(_vector(numerics["upper_bounds_v"], 4, "joint upper bounds")[axes] - voltages[axes],
                       trust) / scales
    matrix = np.vstack((np.c_[a[:2], np.zeros(2)], np.c_[-a[:2], np.zeros(2)],
                        np.c_[a[2:], -np.ones(2)], np.c_[-a[2:], -np.ones(2)]))
    rhs = np.r_[1-r[:2], 1+r[:2], -r[2:], r[2:]]
    compatibility = _finite(numerics["compatibility_tolerance"], "joint model compatibility")
    solved = linprog([0., 0., 0., 1.], A_ub=matrix, b_ub=rhs,
                     bounds=[*zip(lower, upper, strict=True), (0., None)], method="highs",
                     options={"primal_feasibility_tolerance": compatibility,
                              "dual_feasibility_tolerance": compatibility})
    if not solved.success or not np.all(np.isfinite(solved.x)):
        raise CandidateContractError(f"joint P/S linear program failed: {solved.status}: {solved.message}")
    if np.any(matrix @ solved.x - rhs > compatibility):
        raise CandidateContractError("joint P/S linear program violates its model constraints")
    delta = solved.x[:3] * scales
    if np.any(delta/scales < lower-compatibility) or np.any(delta/scales > upper+compatibility):
        raise CandidateContractError("joint P/S linear program violates its voltage bounds")
    return delta, residuals + columns @ delta


def merge_s_local_jacobian(base_jacobian: np.ndarray, s_columns: np.ndarray) -> np.ndarray:
    """Replace only the two S columns of a full physical Jacobian."""
    base = np.asarray(base_jacobian, dtype=float)
    columns = np.asarray(s_columns, dtype=float)
    if base.shape != (4, 4) or not np.all(np.isfinite(base)):
        raise CandidateContractError("base physical Jacobian must be a finite 4x4 matrix")
    if columns.shape != (4, 2) or not np.all(np.isfinite(columns)):
        raise CandidateContractError("local S Jacobian columns must be a finite 4x2 matrix")
    merged = base.copy()
    merged[:, :2] = columns
    return merged

UNKNOWN_NAMES = (
    "stripe_1_voltage_v",
    "stripe_2_voltage_v",
    "prism_1_voltage_v",
    "prism_2_voltage_v",
)
RESIDUAL_NAMES = (
    "P1_P2_positive_mirror_turn_y_mm",
    "P1_P2_P2_shield_low_field_signed_vy_over_vz",
    "Stripe_slow_turn_y_minus_L_mm",
    "Stripe_target_phase_y_minus_origin_mm",
)



def _strict_finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def solve_linearized_step(
    baseline: Mapping[str, Any],
    perturbations: Sequence[Mapping[str, Any]],
    *,
    lower_bounds_v: Sequence[float],
    upper_bounds_v: Sequence[float],
    parameter_scales_v: Sequence[float],
    residual_scales: Sequence[float],
    maximum_abs_step_v: Sequence[float],
    relative_rank_tolerance: float,
    compatibility_tolerance: float,
) -> dict[str, Any]:
    """Return a full-rank signed one-sided Jacobian correction with one trust scale."""
    if len(perturbations) != 4:
        raise CandidateContractError("downstream workpoint needs exactly four perturbations")
    vectors = [np.asarray(item["voltages_v"], dtype=float) for item in (baseline, *perturbations)]
    residual_vectors = [np.asarray(item["residual_vector"], dtype=float) for item in (baseline, *perturbations)]
    if any(value.shape != (4,) or not np.all(np.isfinite(value)) for value in (*vectors, *residual_vectors)):
        raise CandidateContractError("downstream voltage and residual vectors must be finite four-vectors")
    if any(item["frozen_problem"] != baseline["frozen_problem"] for item in perturbations):
        raise CandidateContractError("downstream perturbations change the frozen physical problem")
    base_v, base_r = vectors[0], residual_vectors[0]
    columns: list[np.ndarray] = []
    steps: list[float] = []
    for index, trial_v in enumerate(vectors[1:]):
        delta = trial_v - base_v
        changed = np.flatnonzero(delta != 0.0)
        if changed.tolist() != [index]:
            raise CandidateContractError(
                f"perturbation {index + 1} must change only {UNKNOWN_NAMES[index]} by a nonzero step"
            )
        steps.append(float(delta[index]))
        columns.append((residual_vectors[index + 1] - base_r) / delta[index])
    jacobian = np.column_stack(columns)
    lower = np.asarray(lower_bounds_v, dtype=float)
    upper = np.asarray(upper_bounds_v, dtype=float)
    parameter_scales = np.asarray(parameter_scales_v, dtype=float)
    residual_scale_array = np.asarray(residual_scales, dtype=float)
    maximum_step = np.asarray(maximum_abs_step_v, dtype=float)
    if any(value.shape != (4,) or not np.all(np.isfinite(value)) for value in (lower, upper, parameter_scales, residual_scale_array, maximum_step)):
        raise CandidateContractError("downstream bounds, scales, and trust limits must be finite four-vectors")
    if np.any(lower >= base_v) or np.any(base_v >= upper):
        raise CandidateContractError("baseline downstream voltages must lie strictly inside their bounds")
    if np.any(parameter_scales <= 0.0) or np.any(residual_scale_array <= 0.0) or np.any(maximum_step <= 0.0):
        raise CandidateContractError("downstream scales and trust limits must be positive")
    rank_tolerance = _strict_finite(relative_rank_tolerance, "relative rank tolerance")
    if rank_tolerance <= 0.0:
        raise CandidateContractError("relative rank tolerance must be positive")
    result = solve_with_jacobian(
        baseline,
        jacobian,
        lower_bounds_v=lower,
        upper_bounds_v=upper,
        parameter_scales_v=parameter_scales,
        residual_scales=residual_scale_array,
        maximum_abs_step_v=maximum_step,
        relative_rank_tolerance=rank_tolerance,
        compatibility_tolerance=compatibility_tolerance,
    )
    return {"stencil_steps_v": steps, **result}


def solve_with_jacobian(
    baseline: Mapping[str, Any],
    jacobian_rows: Sequence[Sequence[float]],
    *,
    lower_bounds_v: Sequence[float],
    upper_bounds_v: Sequence[float],
    parameter_scales_v: Sequence[float],
    residual_scales: Sequence[float],
    maximum_abs_step_v: Sequence[float],
    relative_rank_tolerance: float,
    compatibility_tolerance: float,
) -> dict[str, Any]:
    """Apply one bounded Newton step from an already audited local Jacobian."""
    base_v = np.asarray(baseline["voltages_v"], dtype=float)
    base_r = np.asarray(baseline["residual_vector"], dtype=float)
    jacobian = np.asarray(jacobian_rows, dtype=float)
    lower = np.asarray(lower_bounds_v, dtype=float)
    upper = np.asarray(upper_bounds_v, dtype=float)
    parameter_scales = np.asarray(parameter_scales_v, dtype=float)
    residual_scale_array = np.asarray(residual_scales, dtype=float)
    maximum_step = np.asarray(maximum_abs_step_v, dtype=float)
    if (base_v.shape != (4,) or base_r.shape != (4,) or jacobian.shape != (4, 4)
            or not np.all(np.isfinite(base_v)) or not np.all(np.isfinite(base_r))
            or not np.all(np.isfinite(jacobian))):
        raise CandidateContractError("downstream baseline and Jacobian must be finite four-dimensional arrays")
    if any(value.shape != (4,) or not np.all(np.isfinite(value))
           for value in (lower, upper, parameter_scales, residual_scale_array, maximum_step)):
        raise CandidateContractError("downstream bounds, scales, and trust limits must be finite four-vectors")
    if np.any(lower >= base_v) or np.any(base_v >= upper):
        raise CandidateContractError("baseline downstream voltages must lie strictly inside their bounds")
    if np.any(parameter_scales <= 0.0) or np.any(residual_scale_array <= 0.0) or np.any(maximum_step <= 0.0):
        raise CandidateContractError("downstream scales and trust limits must be positive")
    rank_tolerance = _strict_finite(relative_rank_tolerance, "relative rank tolerance")
    if rank_tolerance <= 0.0:
        raise CandidateContractError("relative rank tolerance must be positive")
    classification = classify_constraint_system(
        UNKNOWN_NAMES,
        RESIDUAL_NAMES,
        jacobian_rows=jacobian.tolist(),
        residuals=base_r.tolist(),
        parameter_scales=parameter_scales.tolist(),
        residual_scales=residual_scale_array.tolist(),
        relative_rank_tolerance=rank_tolerance,
        compatibility_tolerance=compatibility_tolerance,
    )
    if classification.status != "square_exact":
        raise CandidateContractError(
            f"downstream finite-3-D Jacobian is not square exact: {classification.status}"
        )
    raw_step = np.linalg.solve(jacobian, -base_r)
    nonzero = np.abs(raw_step) > 0
    alpha = min(1.0, float(np.min(maximum_step[nonzero] / np.abs(raw_step[nonzero])))) if np.any(nonzero) else 1.0
    for index, component in enumerate(raw_step):
        if component > 0.0:
            alpha = min(alpha, float((upper[index] - base_v[index]) / component))
        elif component < 0.0:
            alpha = min(alpha, float((lower[index] - base_v[index]) / component))
    alpha = max(0.0, min(1.0, alpha))
    if alpha <= 0.0:
        raise CandidateContractError("no positive bounded trust step is available")
    applied = alpha * raw_step
    proposed = base_v + applied
    predicted = base_r + jacobian @ applied
    return {
        "unknown_names": list(UNKNOWN_NAMES),
        "residual_names": list(RESIDUAL_NAMES),
        "baseline_voltages_v": base_v.tolist(),
        "baseline_residuals": dict(zip(RESIDUAL_NAMES, base_r.tolist())),
        "physical_jacobian_rows": jacobian.tolist(),
        "classification": asdict(classification),
        "unbounded_linear_correction_v": raw_step.tolist(),
        "trust_scale": alpha,
        "applied_correction_v": applied.tolist(),
        "proposed_voltages_v": proposed.tolist(),
        "predicted_residuals": dict(zip(RESIDUAL_NAMES, predicted.tolist())),
    }


def resolve_active_stripe_axes(profile: Mapping[str, Any]) -> tuple[int, ...]:
    """Resolve the explicitly authored voltage coordinates, without a default."""
    names = profile.get("active_stripe_axes")
    if names == [UNKNOWN_NAMES[0]]:
        return (0,)
    if names == list(UNKNOWN_NAMES[:2]):
        return (0, 1)
    raise CandidateContractError("active_stripe_axes must explicitly name S1 alone or S1/S2 in canonical order")


def resolve_numerics(contract: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Derive bounded local-solve controls from the baseline and frozen trial."""
    profile = contract["downstream_fixed_grid_workpoint_profile"]
    if profile["schema_version"] != 1 or profile["parameter_scale_rule"] != "absolute_baseline_voltage":
        raise CandidateContractError("unsupported downstream workpoint profile")
    if profile["voltage_bounds_rule"] != "stripe_seed_energy_envelope_with_baseline_sign__prism_initial_search_window":
        raise CandidateContractError("unsupported downstream voltage envelope rule")
    energy = _strict_finite(baseline["frozen_problem"]["selected_axial_energy_per_charge_v"], "axial energy")
    deviation = _strict_finite(contract["accelerator_energy_contract"]["maximum_particle_net_gain_deviation_per_charge_v"], "energy half-window")
    seed = contract["dual_stripe_l0"]["operating_seed_search"]
    floor = energy * _strict_finite(seed["minimum_abs_bias_fraction_of_nominal_energy"], "minimum bias fraction")
    if energy <= deviation or deviation <= 0 or floor <= 0:
        raise CandidateContractError("invalid downstream energy/bias envelope")
    voltage = baseline["voltages_v"]
    axes = resolve_active_stripe_axes(profile)
    if not voltage[0] < -floor or (axes == (0, 1) and not voltage[1] > floor):
        raise CandidateContractError("active downstream Stripe seed has invalid bias polarity")
    if axes == (0,) and voltage[1] != 0.0:
        raise CandidateContractError("inactive S2 must remain grounded at zero volts")
    prism_window = contract["prism_transport"]["two_prism_injection_l0"]["voltage_polarity_contract"]["current_initial_search_window_v"]
    target_ratio = baseline["frozen_problem"]["targets"]["target_low_field_tangent_ratio_vy_over_vz"]
    angle_scale = math.radians(_strict_finite(profile["angle_residual_scale_degrees"], "angle scale"))
    if not 0 < angle_scale < math.pi / 2:
        raise CandidateContractError("angle scale must be positive and below 90 degrees")
    target_angle = math.atan(target_ratio)
    ratio_scale = min(math.tan(target_angle + angle_scale) - target_ratio,
                      target_ratio - math.tan(target_angle - angle_scale))
    target = baseline["frozen_problem"].get("prism_handoff_target")
    if target is not None:
        if axes != (0,):
            raise CandidateContractError("clean-phase Prism target requires the single-S1 staged controller")
        ratio_scale = _strict_finite(target.get("energy_tolerance_per_charge_v"), "clean-phase energy scale")
    tiers = profile["jacobian_relative_step_tiers"]
    coarse_relative_step = _strict_finite(tiers["coarse"], "coarse relative voltage step")
    if coarse_relative_step <= 0.0:
        raise CandidateContractError("coarse relative voltage step must be positive")
    parameter_scales = [max(abs(value), 1.0) for value in voltage]
    return {
        "active_stripe_axes": [UNKNOWN_NAMES[axis] for axis in axes],
        "lower_bounds_v": [-energy, floor if 1 in axes else 0.0, prism_window["prism_1"][0], prism_window["prism_2"][0]],
        "upper_bounds_v": [-floor, math.nextafter(energy - deviation, -math.inf) if 1 in axes else 0.0, prism_window["prism_1"][1], prism_window["prism_2"][1]],
        "parameter_scales_v": parameter_scales,
        "residual_scales": [profile["position_residual_scale_mm"], ratio_scale,
                            profile["slow_turn_residual_scale_mm"], profile["return_phase_residual_scale_mm"]],
        "maximum_abs_step_v": [coarse_relative_step * value for value in parameter_scales],
        "relative_rank_tolerance": contract["dual_stripe_l0"]["determination_numerics"]["relative_singular_value_rank_tolerance"],
        "compatibility_tolerance": contract["dual_stripe_l0"]["determination_numerics"]["scaled_irreducible_residual_norm_tolerance"],
    }
