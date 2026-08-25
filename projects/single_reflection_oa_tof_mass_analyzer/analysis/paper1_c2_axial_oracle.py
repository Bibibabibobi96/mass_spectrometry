"""C2 axial-only J2/J3 falsification on the exact ideal-field oracle.

This module deliberately reduces a frozen C1 source to its declared OA axial
``z, v_z`` coordinates.  It is a low-cost gate, not a replacement for the
full 6D/3D verification required in C3--C7.  No detector result is read.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from numpy.typing import NDArray

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_focusability import (
    FocusabilityProblem,
    assign_detector_blind_cohorts,
    evaluate_focusability,
    fit_source_condition_model,
    stack_focusability_problems,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    compute_time_derivatives,
    derive_first_order_focus_drift,
    derive_three_zone_state,
    exact_total_normalized_time_from_state,
)


@dataclass(frozen=True)
class AxialC2Source:
    """Frozen axial C1 reduction and its detector-blind cohort membership."""

    source_id: str
    particle_ids: NDArray[np.int64]
    z_mm: NDArray[np.float64]
    vz_m_per_s: NDArray[np.float64]
    roles: NDArray[np.str_]
    selected_degree: int
    mass_to_charge_th: float
    release_position_mm: float


@dataclass(frozen=True)
class AxialC2Design:
    """Exact three-zone oracle controls; eta is omitted for the two-zone arm."""

    source: AffineSource
    outer: OuterGeometry
    reflectron: ReflectronGeometry
    inner: InnerSolution
    include_eta: bool
    parameter_scale: NDArray[np.float64]


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


def load_c2_axial_source(
    *, assessment_path: Path, mass_to_charge_th: float, release_position_mm: float
) -> AxialC2Source:
    """Load C1's frozen state table and retain only the declared axial pair."""

    assessment = _json(assessment_path)
    if assessment.get("qualification") != "DETECTOR_BLIND_SOURCE_ONLY":
        raise ValueError("C2 requires a detector-blind C1 assessment")
    source_id = assessment.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise ValueError("C1 source identifier is absent")
    sample = assessment.get("anchor", {}).get("time_series_sample_index")
    state_record = assessment.get("state_table", {})
    state_path = Path(state_record.get("path", ""))
    if not state_path.is_file():
        raise ValueError("C1 state table is unavailable")
    degree = assessment.get("selected_model", {}).get("degree")
    if degree not in (1, 2):
        raise ValueError("C1 selected model degree is invalid")
    import csv

    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if int(row["sample_index"]) == sample
            and row["survival_status"].strip().lower() == "alive"
        ]
    if not rows:
        raise ValueError("C1 anchor has no alive axial source rows")
    identifiers = np.asarray([int(row["particle_id"]) for row in rows], dtype=np.int64)
    z = np.asarray([float(row["z_mm"]) for row in rows], dtype=float)
    vz = 1000.0 * np.asarray([float(row["vz_mm_per_us"]) for row in rows], dtype=float)
    if not np.isfinite(z).all() or not np.isfinite(vz).all():
        raise ValueError("C1 axial source contains non-finite values")
    salt = assessment.get("cohort", {}).get("salt")
    if not isinstance(salt, str) or not salt:
        raise ValueError("C1 cohort salt is absent")
    roles = np.asarray(
        [item.role for item in assign_detector_blind_cohorts(identifiers, salt=salt)],
        dtype=str,
    )
    return AxialC2Source(
        source_id, identifiers, z, vz, roles, degree,
        float(mass_to_charge_th), float(release_position_mm),
    )


def _source_manifold(source: AxialC2Source) -> tuple[AffineSource, Callable[[NDArray[np.float64]], NDArray[np.float64]]]:
    """Fit the C1-selected axial mean using development plus validation only."""

    selection = np.isin(source.roles, ("development", "validation"))
    fitted = fit_source_condition_model(
        source.z_mm[selection, None], source.vz_m_per_s[selection, None],
        condition_names=("z_mm",), state_names=("vz_m_per_s",),
        degree=source.selected_degree,
    )
    center_z = float(np.mean(source.z_mm[selection]))
    step = max(1e-5, 1e-4 * float(np.std(source.z_mm[selection])))
    mean = lambda z: fitted.predict_mean(np.asarray(z, dtype=float).reshape(-1, 1))[:, 0]
    slope = float((mean(np.asarray([center_z + step]))[0] - mean(np.asarray([center_z - step]))[0]) / (2.0 * step))
    center_velocity = float(mean(np.asarray([center_z]))[0])
    manifold = AffineSource.from_velocity(
        mass_to_charge_th=source.mass_to_charge_th,
        center_x_mm=source.release_position_mm,
        center_velocity_m_per_s=center_velocity,
        velocity_slope_m_per_s_per_mm=slope,
    )
    return manifold, mean


def _controls(design: AxialC2Design) -> NDArray[np.float64]:
    values = [design.inner.stage1_voltage_drop_v, design.inner.stage2_field_v_per_mm]
    if design.include_eta:
        values.append(design.inner.eta)
    return np.asarray(values, dtype=float)


def _inner_from_controls(design: AxialC2Design, values: NDArray[np.float64]) -> InnerSolution:
    if values.size != (3 if design.include_eta else 2):
        raise ValueError("control dimension differs from the selected architecture")
    return InnerSolution(values[0], values[1], values[2] if design.include_eta else 0.0)


def _derivative(function: Callable[[NDArray[np.float64]], NDArray[np.float64]], point: NDArray[np.float64], step: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return a centered finite-difference Jacobian with caller-frozen steps."""

    value = np.asarray(function(point), dtype=float)
    result = np.empty((value.size, point.size), dtype=float)
    for index, delta in enumerate(step):
        if not math.isfinite(float(delta)) or delta <= 0.0:
            raise ValueError("finite-difference steps must be finite and positive")
        plus, minus = point.copy(), point.copy()
        plus[index] += delta
        minus[index] -= delta
        result[:, index] = (function(plus) - function(minus)) / (2.0 * delta)
    return result


def _design_state(design: AxialC2Design, controls: NDArray[np.float64]):
    inner = _inner_from_controls(design, controls)
    state = derive_three_zone_state(design.source, design.outer, inner.eta)
    drift = derive_first_order_focus_drift(design.source, state)
    return state, inner, drift


def _time_gradient(
    design: AxialC2Design, controls: NDArray[np.float64], x_mm: float, vz_m_per_s: float
) -> float:
    """Differentiate exact time with respect to an independent axial velocity residual."""

    state, inner, drift = _design_state(design, controls)
    root = design.source.time_scale_s_per_mm_sqrt_v / 1.0e-3
    # ``time_scale`` stores 1e-3*sqrt((m/q)/2), so this recovers the chi factor.
    chi_step = root * 0.5
    chi = vz_m_per_s * root
    plus = exact_total_normalized_time_from_state(state, design.reflectron, inner, x_mm, chi + chi_step, drift)
    minus = exact_total_normalized_time_from_state(state, design.reflectron, inner, x_mm, chi - chi_step, drift)
    return float((plus - minus) / 1.0) * design.source.time_scale_s_per_mm_sqrt_v * 1.0e6


def analytic_time_gradient(
    design: AxialC2Design, controls: NDArray[np.float64], x_mm: float, vz_m_per_s: float
) -> float:
    """Return the independent analytic ``d t / d v_z`` of the exact oracle.

    The expression differentiates the direct axial-state timing equation at
    fixed position, rather than differentiating the finite-difference routine.
    It is C2's second derivative path; real-field derivatives remain C3 work.
    """

    state, inner, drift = _design_state(design, controls)
    root = design.source.time_scale_s_per_mm_sqrt_v / 1.0e-3
    chi = vz_m_per_s * root
    energy = state.repeller_v - state.field1_v_per_mm * x_mm + chi**2
    if energy <= max(state.grid1_v, inner.stage1_voltage_drop_v):
        raise ValueError("analytic axial state cannot cross accelerator or reflectron")
    root_energy = math.sqrt(energy)
    root_grid1 = math.sqrt(energy - state.grid1_v)
    root_grid2 = math.sqrt(energy - state.grid2_v)
    root_reflectron = math.sqrt(energy - inner.stage1_voltage_drop_v)
    accelerator_energy_gradient = (
        1.0 / (state.field1_v_per_mm * root_grid1)
        + (1.0 / root_grid2 - 1.0 / root_grid1) / state.field2_v_per_mm
        + (1.0 / root_energy - 1.0 / root_grid2) / state.field3_v_per_mm
        - drift / (2.0 * energy**1.5)
    )
    reflectron_field = inner.stage1_voltage_drop_v / design.reflectron.stage1_length_mm
    reflectron_energy_gradient = (
        2.0 / reflectron_field * (1.0 / root_energy - 1.0 / root_reflectron)
        + 2.0 / inner.stage2_field_v_per_mm / root_reflectron
        - (design.reflectron.upstream_drift_mm + design.reflectron.downstream_drift_mm)
        / (2.0 * energy**1.5)
    )
    normalized_gradient = 2.0 * chi * (
        accelerator_energy_gradient + reflectron_energy_gradient
    ) - 2.0 / state.field1_v_per_mm
    return normalized_gradient * root * design.source.time_scale_s_per_mm_sqrt_v * 1.0e6


def _constraint_values(design: AxialC2Design, controls: NDArray[np.float64]) -> NDArray[np.float64]:
    state, inner, _ = _design_state(design, controls)
    derivatives = compute_time_derivatives(design.source, state, design.reflectron, inner)
    return np.asarray((derivatives.d1, derivatives.d2), dtype=float)


def _axial_time_us(
    design: AxialC2Design, controls: NDArray[np.float64], x_mm: NDArray[np.float64], vz_m_per_s: NDArray[np.float64]
) -> NDArray[np.float64]:
    state, inner, drift = _design_state(design, controls)
    root = design.source.time_scale_s_per_mm_sqrt_v / 1.0e-3
    normalized = exact_total_normalized_time_from_state(
        state, design.reflectron, inner, x_mm, vz_m_per_s * root, drift
    )
    return np.asarray(normalized, dtype=float) * design.source.time_scale_s_per_mm_sqrt_v * 1.0e6


def _build_problem(
    source: AxialC2Source, design: AxialC2Design, *, source_weighted: bool
) -> tuple[FocusabilityProblem, dict[str, Any]]:
    manifold, mean = _source_manifold(source)
    design = AxialC2Design(manifold, design.outer, design.reflectron, design.inner, design.include_eta, design.parameter_scale)
    controls = _controls(design)
    steps = np.asarray((1.0, 0.01, 0.01)[:controls.size], dtype=float)
    constraints = _derivative(lambda values: _constraint_values(design, values), controls, steps)
    optimization = source.roles == "optimization"
    ordered = np.argsort(source.z_mm[optimization], kind="stable")
    groups = np.array_split(ordered, 4)
    all_z = source.z_mm[optimization]
    all_vz = source.vz_m_per_s[optimization]
    blocks: list[FocusabilityProblem] = []
    derivative_audits: list[dict[str, float]] = []
    mean_time: list[float] = []
    mean_response: list[NDArray[np.float64]] = []
    mean_weight: list[float] = []
    for group in groups:
        z_bin, vz_bin = all_z[group], all_vz[group]
        center_z = float(np.mean(z_bin))
        center_x = source.release_position_mm + center_z - float(np.mean(source.z_mm[np.isin(source.roles, ("development", "validation"))]))
        residual = vz_bin - mean(z_bin)
        variance = max(float(np.var(residual, ddof=0)), 1e-18)
        center_velocity = float(mean(np.asarray([center_z]))[0])
        gradient = _time_gradient(design, controls, center_x, center_velocity)
        response = _derivative(
            lambda values: np.asarray([_time_gradient(design, values, center_x, center_velocity)]),
            controls, steps,
        )
        response_double_step = _derivative(
            lambda values: np.asarray([_time_gradient(design, values, center_x, center_velocity)]),
            controls, 2.0 * steps,
        )
        analytic_gradient = analytic_time_gradient(
            design, controls, center_x, center_velocity
        )
        derivative_audits.append({
            "analytic_gradient_us_per_m_per_s": analytic_gradient,
            "finite_difference_gradient_us_per_m_per_s": gradient,
            "gradient_relative_error": abs(analytic_gradient - gradient) / max(abs(analytic_gradient), 1e-30),
            "design_response_step_platform_relative_error": float(
                np.linalg.norm(response - response_double_step)
                / max(np.linalg.norm(response), 1e-30)
            ),
        })
        blocks.append(FocusabilityProblem(
            time_gradient=np.asarray([gradient]), design_response=response,
            source_factor=np.asarray([[math.sqrt(variance) if source_weighted else 1.0]]),
            constraint_jacobian=constraints, parameter_scale=design.parameter_scale,
            rank_relative_tolerance=1e-10,
        ))
        mean_time.append(float(_axial_time_us(
            design, controls, np.asarray([center_x]), np.asarray([center_velocity])
        )[0]))
        mean_response.append(_derivative(
            lambda values: _axial_time_us(
                design, values, np.asarray([center_x]), np.asarray([center_velocity])
            ),
            controls, steps,
        )[0])
        mean_weight.append(math.sqrt(group.size / all_z.size))
    # The total objective is Var_j[mu_j + h_j delta] plus the conditional
    # thickness contribution above.  Center both mean blocks under their
    # frozen bin weights; an absolute flight-time offset must not steer J2.
    weights = np.asarray(mean_weight)
    means = np.asarray(mean_time)
    responses = np.asarray(mean_response)
    centered_mean = means - float(np.dot(weights**2, means))
    centered_response = responses - np.sum(weights[:, None]**2 * responses, axis=0)
    blocks.append(FocusabilityProblem(
        time_gradient=weights * centered_mean,
        design_response=weights[:, None] * centered_response,
        source_factor=np.eye(weights.size),
        constraint_jacobian=constraints,
        parameter_scale=design.parameter_scale,
        rank_relative_tolerance=1e-10,
    ))
    stacked = stack_focusability_problems(blocks)
    # C2 is an elimination screen: retain an explicitly local, scaled trust
    # region rather than treating the unconstrained projector minimum as a
    # reachable design.  C3 will establish the real-field trust domain.
    feasible_dimension = stacked.parameter_scale.size - np.linalg.matrix_rank(
        stacked.constraint_jacobian, tol=1e-10 * np.linalg.svd(stacked.constraint_jacobian, compute_uv=False)[0]
    )
    problem = FocusabilityProblem(
        time_gradient=stacked.time_gradient,
        design_response=stacked.design_response,
        source_factor=stacked.source_factor,
        constraint_jacobian=stacked.constraint_jacobian,
        parameter_scale=stacked.parameter_scale,
        lower_eta=np.full(feasible_dimension, -0.5),
        upper_eta=np.full(feasible_dimension, 0.5),
        trust_radius=0.5,
        rank_relative_tolerance=stacked.rank_relative_tolerance,
    )
    return problem, {"design": design, "controls": controls, "steps": steps, "mean": mean, "derivative_audits": derivative_audits, "conditional_mean_bin_time_us": mean_time}


def run_axial_c2_screen(source: AxialC2Source, design: AxialC2Design) -> dict[str, Any]:
    """Run the C2 axial screen for one source/architecture pair."""

    weighted, metadata = _build_problem(source, design, source_weighted=True)
    unweighted, _ = _build_problem(source, design, source_weighted=False)
    weighted_result = evaluate_focusability(weighted)
    unweighted_result = evaluate_focusability(unweighted)
    controls = metadata["controls"]
    delta = design.parameter_scale * (weighted_result.null_space @ weighted_result.eta)
    prediction_controls = controls + delta
    test = source.roles == "locked_test"
    train_z = source.z_mm[np.isin(source.roles, ("development", "validation"))]
    x = source.release_position_mm + source.z_mm[test] - float(np.mean(train_z))
    residual = source.vz_m_per_s[test] - metadata["mean"](source.z_mm[test])
    unweighted_controls = controls + design.parameter_scale * (
        unweighted_result.null_space @ unweighted_result.eta
    )
    unweighted_direct = _axial_time_us(
        metadata["design"], unweighted_controls, x, source.vz_m_per_s[test]
    )
    unweighted_mean = _axial_time_us(
        metadata["design"], unweighted_controls, x, source.vz_m_per_s[test] - residual
    )
    b = weighted.source_factor.T @ weighted.time_gradient
    a = weighted.source_factor.T @ (
        weighted.design_response * weighted.parameter_scale[np.newaxis, :]
    ) @ weighted_result.null_space
    directions: dict[str, dict[str, Any]] = {}
    for name, eta in (
        ("improve", weighted_result.eta),
        ("zero", np.zeros_like(weighted_result.eta)),
        ("worsen", -weighted_result.eta),
    ):
        trial_controls = controls + design.parameter_scale * (weighted_result.null_space @ eta)
        direct = _axial_time_us(metadata["design"], trial_controls, x, source.vz_m_per_s[test])
        direct_mean = _axial_time_us(metadata["design"], trial_controls, x, source.vz_m_per_s[test] - residual)
        directions[name] = {
            "predicted_total_objective_us2": float(np.dot(b + a @ eta, b + a @ eta)),
            "locked_exact_conditional_residual_us": (direct - direct_mean).tolist(),
            "locked_exact_total_time_us": direct.tolist(),
            "locked_exact_total_variance_us2": float(np.var(direct, ddof=0)),
            "controls": trial_controls.tolist(),
        }
    return {
        "source_id": source.source_id,
        "architecture": "three_zone" if design.include_eta else "two_zone",
        "locked_test_count": int(np.sum(test)),
        "constraint_jacobian": weighted.constraint_jacobian.tolist(),
        "finite_difference_steps": metadata["steps"].tolist(),
        "derivative_audits": metadata["derivative_audits"],
        "weighted": {"prediction": _prediction_dict(weighted_result), "controls": prediction_controls.tolist()},
        "unweighted": {
            "prediction": _prediction_dict(unweighted_result),
            "controls": unweighted_controls.tolist(),
            "locked_exact_conditional_residual_variance_us2": float(
                np.var(unweighted_direct - unweighted_mean, ddof=0)
            ),
            "locked_exact_total_variance_us2": float(np.var(unweighted_direct, ddof=0)),
        },
        "directions": directions,
    }


def _prediction_dict(result: Any) -> dict[str, Any]:
    return {
        "eta": result.eta.tolist(), "effective_rank": result.effective_rank,
        "singular_values": result.singular_values.tolist(),
        "condition_number": result.condition_number,
        "initial_conditional_variance": result.initial_conditional_variance,
        "predicted_conditional_variance": result.predicted_conditional_variance,
        "local_reference_minimum": result.local_reference_minimum,
        "focusability_fraction": result.focusability_fraction,
        "active_constraints": list(result.active_constraints),
        "constraint_residual_norm": result.constraint_residual_norm,
        "rank_tolerance": result.rank_tolerance,
    }
