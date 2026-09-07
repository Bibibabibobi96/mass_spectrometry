"""Derive an instance-specific two-Stripe seed with the paper's theory.

The two seed equations are the nominal oscillation count and spatial-return
condition.  A polynomial/linear fit is used only to find starting roots; every
published number is re-evaluated and Newton-refined against the native frozen
B-spline geometry.  Energy and time-platform residuals remain reported raw and
therefore this module cannot publish a complete downstream operating point.
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from scipy.optimize import least_squares

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    analyze_dual_stripe_l0,
    identify_fixed_cad_component_shapes,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    JointL0Trial,
    StripeHardBoundary,
    coupled_normalized_period_slope_at_energy,
    coupled_reduced_period_mm_per_sqrt_v,
    derive_coupled_drift_state,
    derive_turning_y_from_entry_direction,
    evaluate_joint_l0_trial,
    finite_difference_joint_jacobian,
    spatial_return_kappa_derivative_residual,
    time_platform_derivative_residuals,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_candidate_receipt import (
    ManagedMirrorCandidate,
    load_managed_mirror_candidate,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    derive_mirror_l0_slope_tolerance_per_v,
    reduced_period,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_path_length_evaluator,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


WidthFunction = Callable[[float], float]


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be numeric") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CandidateContractError(f"{label} must be a positive integer")
    return value


def _seed_profile(contract: dict[str, Any]) -> dict[str, Any]:
    block = contract.get("dual_stripe_l0")
    profile = block.get("operating_seed_search") if isinstance(block, dict) else None
    if not isinstance(profile, dict) or profile.get("status") != "paper_theory__instance_specific_K_and_spatial_return_seed":
        raise CandidateContractError("dual_stripe_l0.operating_seed_search is incomplete")
    if profile.get("seed_equations") != ["target_oscillation_count", "spatial_return_kappa_prime"]:
        raise CandidateContractError("Stripe operating seed must retain the declared two paper equations")
    return profile


def _entry_direction_and_search_end(
    contract: dict[str, Any], profile: dict[str, Any],
) -> tuple[tuple[float, float, float], float, int]:
    energy = contract.get("prism_transport", {}).get("energy_partition", {})
    if energy.get("semantics") != "total_kinetic_energy_at_first_prism_ev":
        raise CandidateContractError("Stripe seed requires the declared prism energy partition")
    total = _finite(energy.get("total_kinetic_energy_ev"), "total kinetic energy")
    drift = _finite(energy.get("drift_kinetic_energy_ev"), "drift kinetic energy")
    nominal = _finite(contract.get("nominal", {}).get("energy_per_charge_v"), "nominal energy")
    if total != nominal or not 0.0 < drift < total:
        raise CandidateContractError("Stripe seed energy partition must match the positive nominal energy")
    direction = (0.0, -math.sqrt(drift / total), -math.sqrt(1.0 - drift / total))
    stripe_l0 = contract["dual_stripe_l0"]
    entry = _finite(stripe_l0["theory_stripe_entrance"]["project_y_mm"], "Stripe entry y")
    y_span = tuple(_finite(value, "Stripe active span") for value in contract["dual_stripe"]["theory_profile"]["active_y_span_mm"])
    nodes = tuple(_finite(value, "time-platform node") for value in stripe_l0["time_platform_constraint"]["eta_turn_nodes"])
    if len(y_span) != 2 or entry != y_span[1] or not nodes or min(nodes) <= 0.0:
        raise CandidateContractError("Stripe active span, entry, or time-platform nodes are inconsistent")
    usable_length = (entry - y_span[0]) / max(nodes)
    search_end = entry - usable_length
    theory = contract["dual_stripe"]["theory_profile"]
    samples_per_span = _positive_integer(
        theory.get("sampling_per_nonzero_knot_span"),
        "native Stripe samples per nonzero knot span",
    )
    span_counts = []
    for set_name in ("set_1", "set_2"):
        definition = theory.get(set_name, {})
        for edge_name in ("lower_edge", "upper_edge"):
            edge = definition.get(edge_name, {})
            if edge.get("basis") != "cubic_bspline":
                continue
            order = _positive_integer(edge.get("order"), f"{set_name} {edge_name} order")
            knots = tuple(_finite(value, f"{set_name} {edge_name} knot") for value in edge.get("knots", []))
            if len(knots) <= 2 * order:
                raise CandidateContractError("native Stripe knot vector cannot derive turning-search sampling")
            span_counts.append(sum(right > left for left, right in zip(knots[order - 1:-order], knots[order:1 - order])))
    if not span_counts or min(span_counts) <= 0:
        raise CandidateContractError("native Stripe profiles have no nonzero B-spline spans")
    multiplier = _positive_integer(
        profile.get("turning_search_sampling_multiplier"),
        "turning-search sampling multiplier",
    )
    sample_count = max(span_counts) * samples_per_span * multiplier
    return direction, search_end, sample_count


def _surrogate_widths(contract: dict[str, Any]) -> tuple[WidthFunction, WidthFunction]:
    shape = identify_fixed_cad_component_shapes(contract)
    fit = shape["selected_fit"]
    baselines = shape["width_baselines_at_entry_mm"]
    coefficients = tuple(float(value) for value in fit["set_1_coefficients_per_physical_mm_power"])
    linear = float(fit["set_2_coefficient_per_physical_mm"])
    first_baseline = float(baselines["set_1"])
    second_baseline = float(baselines["set_2"])
    multiplier = _finite(
        contract["dual_stripe"]["theory_profile"]["path_length_mapping"]["profile_width_to_total_S_multiplier"],
        "Stripe surrogate path-length multiplier",
    )
    if multiplier <= 0.0:
        raise CandidateContractError("Stripe surrogate path-length multiplier must be positive")

    def first(y_mm: float) -> float:
        distance = -float(y_mm)
        return multiplier * (
            first_baseline + sum(value * distance**power for power, value in enumerate(coefficients, 1))
        )

    def second(y_mm: float) -> float:
        return multiplier * (second_baseline + linear * -float(y_mm))

    return first, second


def _evaluate_seed_equations(
    mirror: ManagedMirrorCandidate,
    widths: Sequence[WidthFunction],
    biases_v: Sequence[float],
    direction: Sequence[float],
    search_end_y_mm: float,
    sample_count: int,
    kappa_derivative_step: float,
) -> tuple[np.ndarray, tuple[StripeHardBoundary, StripeHardBoundary], float, Any]:
    if len(widths) != 2 or len(biases_v) != 2:
        raise CandidateContractError("Stripe seed evaluation needs two widths and two biases")
    stripes = tuple(
        StripeHardBoundary(_finite(bias, "Stripe seed bias"), width)
        for bias, width in zip(biases_v, widths)
    )
    entry = _finite(mirror.contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"], "Stripe entry")
    target_k = _positive_integer(mirror.contract["nominal"]["target_oscillation_count"], "target K")
    energy = mirror.nominal_energy_per_charge_v
    turn = derive_turning_y_from_entry_direction(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        stripes=stripes,
        entry_y_mm=entry,
        entry_unit_direction_project=direction,
        search_end_y_mm=search_end_y_mm,
        sample_count=sample_count,
    )
    state = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        target_oscillation_count=target_k,
        stripes=stripes,
        entry_y_mm=entry,
        turning_y_mm=turn,
    )
    kappa_prime = spatial_return_kappa_derivative_residual(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        stripes=stripes,
        entry_y_mm=entry,
        nominal_turning_y_mm=turn,
        derivative_step=kappa_derivative_step,
    )
    return np.asarray([state.target_oscillation_count_residual, kappa_prime]), stripes, turn, state


def _central_jacobian(
    evaluator: Callable[[np.ndarray], np.ndarray], values: np.ndarray, step_v: float,
) -> np.ndarray:
    result = np.empty((2, 2), dtype=float)
    for column in range(2):
        lower = values.copy()
        upper = values.copy()
        lower[column] -= step_v
        upper[column] += step_v
        result[:, column] = (evaluator(upper) - evaluator(lower)) / (2.0 * step_v)
    return result


def _bias_pair_is_nondegenerate(values: np.ndarray, profile: dict[str, Any], energy: float) -> bool:
    minimum_abs_fraction = _finite(
        profile.get("minimum_abs_bias_fraction_of_nominal_energy"),
        "minimum bias fraction",
    )
    minimum_ratio = _finite(
        profile.get("minimum_bias_magnitude_ratio"),
        "minimum bias magnitude ratio",
    )
    minimum_separation_fraction = _finite(
        profile.get("minimum_bias_separation_fraction_of_nominal_energy"),
        "minimum separation fraction",
    )
    magnitudes = tuple(abs(float(value)) for value in values)
    if not 0.0 < minimum_ratio < 1.0:
        raise CandidateContractError("minimum bias magnitude ratio must lie strictly between zero and one")
    return (
        min(magnitudes) > minimum_abs_fraction * energy
        and min(magnitudes) / max(magnitudes) >= minimum_ratio
        and abs(float(values[0] - values[1])) > minimum_separation_fraction * energy
    )


def _fixed_hardware_joint_trial(
    mirror: ManagedMirrorCandidate,
    widths: Sequence[WidthFunction],
    biases_v: Sequence[float],
    direction: Sequence[float],
    search_end_y_mm: float,
    sample_count: int,
    kappa_derivative_step: float,
    time_platform_derivative_step: float,
    energy_derivative_step_v: float,
) -> JointL0Trial:
    """Construct one complete fixed-hardware Stripe trial from two biases."""
    contract = mirror.contract
    entry = _finite(contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"], "Stripe entry")
    stripes = tuple(
        StripeHardBoundary(_finite(bias, "Stripe consistency bias"), width)
        for bias, width in zip(biases_v, widths)
    )
    if len(stripes) != 2:
        raise CandidateContractError("fixed-hardware consistency trial requires two Stripe biases")
    turn = derive_turning_y_from_entry_direction(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=mirror.nominal_energy_per_charge_v,
        stripes=stripes,
        entry_y_mm=entry,
        entry_unit_direction_project=direction,
        search_end_y_mm=search_end_y_mm,
        sample_count=sample_count,
    )
    return JointL0Trial(
        mirror_design=mirror.design,
        energy_points_v=mirror.energy_points_v,
        stripes=stripes,
        stripe_entry_y_mm=entry,
        nominal_turning_y_mm=turn,
        target_oscillation_count=_positive_integer(
            contract["nominal"]["target_oscillation_count"], "target K"
        ),
        time_platform_eta_nodes=tuple(
            _finite(value, "time-platform node")
            for value in contract["dual_stripe_l0"]["time_platform_constraint"]["eta_turn_nodes"]
        ),
        kappa_derivative_step=kappa_derivative_step,
        time_platform_derivative_step=time_platform_derivative_step,
        energy_derivative_step_v=energy_derivative_step_v,
    )


def _complete_residual_scales(
    contract: dict[str, Any], names: Sequence[str], energies_v: Sequence[float],
) -> tuple[float, ...]:
    budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
    period_scale = derive_mirror_l0_slope_tolerance_per_v(
        float(budget["minimum_mass_resolution"]),
        float(budget["mirror_time_width_fraction"]),
        tuple(float(value) for value in energies_v),
    )
    return tuple(
        period_scale if name.startswith("full_analyser_period_slope_at_") else 1.0
        for name in names
    )


def _search_complete_fixed_hardware_consistency(mirror: ManagedMirrorCandidate) -> dict[str, Any]:
    """Run a bounded multi-start search over every remaining paper residual.

    The residual scales only condition this diagnostic search.  They are not
    physical acceptance tolerances, so the best iterate is never promoted by
    optimizer success alone.
    """
    contract = mirror.contract
    profile = _seed_profile(contract)
    direction, search_end, sample_count = _entry_direction_and_search_end(contract, profile)
    widths = tuple(compile_dual_stripe_path_length_evaluator(contract, name) for name in ("set_1", "set_2"))
    eta_step = _finite(profile["kappa_derivative_step"], "kappa derivative step")
    time_step = _finite(profile["time_platform_derivative_step"], "time-platform derivative step")
    energy_step = _finite(
        contract["mirror"]["theory_requirements"]["global_l0_search_profile"]["period_slope_derivative_step_v"],
        "full-analyser energy derivative step",
    )
    voltage_step = _finite(profile["native_newton_voltage_step_v"], "Stripe voltage step")
    maximum_evaluations = _positive_integer(
        profile["maximum_surrogate_function_evaluations"], "complete consistency evaluation count"
    )
    refinement_start_count = _positive_integer(
        profile["complete_consistency_refinement_start_count"],
        "complete consistency refinement start count",
    )
    fractions = tuple(_finite(value, "complete consistency start fraction") for value in profile["normalized_start_fractions"])
    energy = mirror.nominal_energy_per_charge_v
    lower = -energy
    upper = math.nextafter(min(mirror.energy_points_v), -math.inf)
    starts = [
        energy * np.asarray((first, second), dtype=float)
        for first in fractions
        for second in fractions
        if first != second
    ]
    feasible_starts = 0
    candidates: list[dict[str, Any]] = []
    screened_starts: list[tuple[float, np.ndarray]] = []
    residual_names: tuple[str, ...] | None = None
    residual_scales: tuple[float, ...] | None = None

    def report_at(values: Sequence[float]):
        trial = _fixed_hardware_joint_trial(
            mirror, widths, values, direction, search_end, sample_count, eta_step, time_step, energy_step,
        )
        return evaluate_joint_l0_trial(trial)

    for start in starts:
        try:
            initial = report_at(start)
        except CandidateContractError:
            continue
        feasible_starts += 1
        if residual_names is None:
            residual_names = initial.residual_names()
            residual_scales = _complete_residual_scales(contract, residual_names, mirror.energy_points_v)
        assert residual_scales is not None
        initial_scaled = np.asarray(initial.residual_vector()) / np.asarray(residual_scales)
        screened_starts.append((float(np.linalg.norm(initial_scaled)), start))

    screened_starts.sort(key=lambda item: item[0])
    refined_starts = screened_starts[:min(refinement_start_count, len(screened_starts))]
    for _initial_norm, start in refined_starts:
        assert residual_scales is not None

        def objective(values: np.ndarray) -> np.ndarray:
            try:
                report = report_at(values)
                if report.residual_names() != residual_names:
                    raise CandidateContractError("complete residual identity changed during search")
                return np.asarray(report.residual_vector()) / np.asarray(residual_scales)
            except CandidateContractError:
                distance = float(np.linalg.norm((values - start) / energy))
                return np.full(len(residual_scales), 1.0e3 + distance)

        def objective_jacobian(values: np.ndarray) -> np.ndarray:
            """Differentiate the nested integral residuals on an absolute voltage scale.

            SciPy's default relative perturbation becomes microscopic for this
            kilovolt-scale solve and samples quadrature noise instead of the
            physical voltage response.  The same contract-owned absolute step
            used by the publication rank audit keeps search and classification
            on one numerical scale.
            """
            columns: list[np.ndarray] = []
            for index in range(len(values)):
                low = values.copy()
                high = values.copy()
                low[index] = max(lower, float(values[index]) - voltage_step)
                high[index] = min(upper, float(values[index]) + voltage_step)
                denominator = high[index] - low[index]
                if denominator <= 0.0:
                    raise CandidateContractError("Stripe voltage Jacobian step collapsed at its bound")
                columns.append((objective(high) - objective(low)) / denominator)
            return np.column_stack(columns)

        result = least_squares(
            objective,
            start,
            bounds=([lower, lower], [upper, upper]),
            jac=objective_jacobian,
            x_scale=np.full(2, energy),
            max_nfev=maximum_evaluations,
        )
        try:
            final_report = report_at(result.x)
        except CandidateContractError:
            continue
        scaled = np.asarray(final_report.residual_vector()) / np.asarray(residual_scales)
        candidates.append({
            "biases_v": [float(value) for value in result.x],
            "scaled_residual_norm_2": float(np.linalg.norm(scaled)),
            "optimizer_success": bool(result.success),
            "optimizer_message": str(result.message),
            "function_evaluations": int(result.nfev),
        })
    if not candidates or residual_names is None or residual_scales is None:
        return {
            "status": "no_feasible_complete_consistency_iterate",
            "attempted_start_count": len(starts),
            "feasible_start_count": feasible_starts,
            "refined_start_count": 0,
            "limitations": ["No physical first-turn trial survived the declared bounded multi-start search."],
        }
    candidates.sort(key=lambda item: (item["scaled_residual_norm_2"], max(abs(v) for v in item["biases_v"])))
    best = candidates[0]

    def trial_from_values(values: tuple[float, ...]) -> JointL0Trial:
        return _fixed_hardware_joint_trial(
            mirror, widths, values, direction, search_end, sample_count, eta_step, time_step, energy_step,
        )

    numerics = contract["dual_stripe_l0"]["determination_numerics"]
    report, classification = finite_difference_joint_jacobian(
        ("stripe_set_1_bias_v", "stripe_set_2_bias_v"),
        tuple(best["biases_v"]),
        (voltage_step, voltage_step),
        trial_from_values,
        parameter_scales=(energy, energy),
        residual_scales=residual_scales,
        relative_rank_tolerance=_finite(
            numerics["relative_singular_value_rank_tolerance"], "rank tolerance"
        ),
        compatibility_tolerance=_finite(
            numerics["scaled_irreducible_residual_norm_tolerance"], "compatibility tolerance"
        ),
    )
    best.update({
        "raw_residuals": dict(report.residuals),
        "residual_scales": dict(zip(report.residual_names(), residual_scales)),
        "determination": asdict(classification),
        "drift_length_L_mm": report.drift_state.drift_length_l_mm,
        "mirror_owned_axial_width_W_mm": report.drift_state.axial_width_w_mm,
        "nominal_kappa_1": report.drift_state.nominal_kappa_1,
        "nominal_injection_angle_degrees": math.degrees(report.drift_state.nominal_injection_angle_rad),
    })
    return {
        "status": "bounded_multistart_complete__not_a_global_proof",
        "attempted_start_count": len(starts),
        "feasible_start_count": feasible_starts,
        "refined_start_count": len(refined_starts),
        "distinct_final_iterate_count": len(candidates),
        "best_iterate": best,
        "paper_turning_normalization": {
            "constraint": "psi(1)-1=0",
            "status": "eliminated_by_deriving_L_from_the_first_physical_5eV_turn",
        },
        "limitations": [
            "Optimizer convergence is a search diagnostic, not an acceptance condition.",
            "The bounded deterministic start grid is not a mathematical proof of global existence or nonexistence.",
        ],
    }


def _build_operating_seed_report_for_mirror(mirror: ManagedMirrorCandidate) -> dict[str, Any]:
    """Search one qualified mirror root and publish native-geometry seed diagnostics."""
    contract = mirror.contract
    profile = _seed_profile(contract)
    direction, search_end, sample_count = _entry_direction_and_search_end(contract, profile)
    kappa_step = _finite(profile.get("kappa_derivative_step"), "kappa derivative step")
    voltage_step = _finite(profile.get("native_newton_voltage_step_v"), "Newton voltage step")
    maximum_newton = _positive_integer(profile.get("maximum_native_newton_iterations"), "Newton iteration count")
    maximum_evaluations = _positive_integer(profile.get("maximum_surrogate_function_evaluations"), "surrogate evaluation count")
    residual_tolerances = tuple(_finite(value, "seed residual tolerance") for value in profile.get("residual_tolerances", []))
    if len(residual_tolerances) != 2 or min(residual_tolerances) <= 0.0 or kappa_step <= 0.0 or voltage_step <= 0.0:
        raise CandidateContractError("Stripe seed numerical controls are incomplete")
    fractions = tuple(_finite(value, "start fraction") for value in profile.get("normalized_start_fractions", []))
    if len(fractions) < 2 or any(value == 0.0 or not -1.0 < value < 1.0 for value in fractions):
        raise CandidateContractError("Stripe seed requires nonzero normalized starts inside the energy envelope")
    energy = mirror.nominal_energy_per_charge_v
    energy_nodes = mirror.energy_points_v
    lower_bound = -energy
    upper_bound = math.nextafter(min(energy_nodes), -math.inf)
    surrogate_widths = _surrogate_widths(contract)

    def evaluate(widths: Sequence[WidthFunction], values: np.ndarray) -> np.ndarray:
        return _evaluate_seed_equations(
            mirror, widths, values, direction, search_end, sample_count, kappa_step,
        )[0]

    surrogate_roots: list[np.ndarray] = []
    starts_attempted = 0
    starts_feasible = 0
    for first_fraction in fractions:
        for second_fraction in fractions:
            if first_fraction == second_fraction:
                continue
            start = energy * np.asarray([first_fraction, second_fraction])
            starts_attempted += 1
            try:
                evaluate(surrogate_widths, start)
            except CandidateContractError:
                continue
            starts_feasible += 1

            def surrogate_objective(values: np.ndarray) -> np.ndarray:
                trial = np.asarray(values, dtype=float)
                try:
                    return evaluate(surrogate_widths, trial)
                except CandidateContractError:
                    distance = float(np.linalg.norm((trial - start) / energy))
                    return np.asarray([1000.0 + distance, 1000.0 + distance])

            result = least_squares(
                surrogate_objective,
                start,
                bounds=([lower_bound, lower_bound], [upper_bound, upper_bound]),
                x_scale="jac",
                max_nfev=maximum_evaluations,
            )
            if not result.success:
                continue
            root = np.asarray(result.x, dtype=float)
            residual = evaluate(surrogate_widths, root)
            if any(abs(value) > 100.0 * tolerance for value, tolerance in zip(residual, residual_tolerances)):
                continue
            if not any(np.linalg.norm(root - known, ord=np.inf) <= voltage_step for known in surrogate_roots):
                surrogate_roots.append(root)
    if not surrogate_roots:
        raise CandidateContractError("no surrogate K/spatial-return root was found in the declared voltage envelope")

    native_widths = tuple(
        compile_dual_stripe_path_length_evaluator(contract, name) for name in ("set_1", "set_2")
    )
    native_roots: list[dict[str, Any]] = []
    for surrogate_root in surrogate_roots:
        values = surrogate_root.copy()
        history: list[dict[str, Any]] = []

        def native_evaluator(trial: np.ndarray) -> np.ndarray:
            return evaluate(native_widths, trial)

        try:
            for iteration in range(maximum_newton):
                residual = native_evaluator(values)
                jacobian = _central_jacobian(native_evaluator, values, voltage_step)
                rank = int(np.linalg.matrix_rank(jacobian))
                history.append({
                    "iteration": iteration,
                    "biases_v": values.tolist(),
                    "residuals": residual.tolist(),
                    "jacobian": jacobian.tolist(),
                    "jacobian_rank": rank,
                })
                if rank != 2:
                    raise CandidateContractError("native Stripe seed Jacobian is rank deficient")
                if all(abs(value) <= tolerance for value, tolerance in zip(residual, residual_tolerances)):
                    break
                values += np.linalg.solve(jacobian, -residual)
                if np.any(values <= lower_bound) or np.any(values >= upper_bound):
                    raise CandidateContractError("native Stripe Newton refinement left its declared envelope")
            residual, stripes, turn, state = _evaluate_seed_equations(
                mirror, native_widths, values, direction, search_end, sample_count, kappa_step,
            )
        except (CandidateContractError, np.linalg.LinAlgError):
            continue
        if any(abs(value) > tolerance for value, tolerance in zip(residual, residual_tolerances)):
            continue
        if not _bias_pair_is_nondegenerate(values, profile, energy):
            continue
        response = analyze_dual_stripe_l0(contract, values)
        entry_y_mm = _finite(
            contract["dual_stripe_l0"]["theory_stripe_entrance"]["project_y_mm"],
            "Stripe entry y",
        )
        periods = [
            coupled_reduced_period_mm_per_sqrt_v(
                reduced_period(node, mirror.design),
                node,
                tuple(width(entry_y_mm) for width in native_widths),
                values,
            )
            for node in energy_nodes
        ]
        central_period = periods[1]
        energy_step = _finite(
            contract["mirror"]["theory_requirements"]["global_l0_search_profile"]["period_slope_derivative_step_v"],
            "full-analyser period derivative step",
        )
        full_analyser_slopes = [
            coupled_normalized_period_slope_at_energy(
                mirror.design,
                node,
                tuple(width(entry_y_mm) for width in native_widths),
                values,
                energy_step,
            )
            for node in energy_nodes
        ]
        nodes = tuple(float(value) for value in contract["dual_stripe_l0"]["time_platform_constraint"]["eta_turn_nodes"])
        time_residuals = time_platform_derivative_residuals(
            mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
            energy_per_charge_v=energy,
            stripes=stripes,
            entry_y_mm=entry_y_mm,
            nominal_turning_y_mm=turn,
            eta_turn_nodes=nodes,
            derivative_step=_finite(profile.get("time_platform_derivative_step"), "time derivative step"),
        )

        def trial_from_biases(biases: tuple[float, ...]) -> JointL0Trial:
            trial_stripes = tuple(
                StripeHardBoundary(bias, width)
                for bias, width in zip(biases, native_widths)
            )
            trial_turn = derive_turning_y_from_entry_direction(
                mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
                energy_per_charge_v=energy,
                stripes=trial_stripes,
                entry_y_mm=entry_y_mm,
                entry_unit_direction_project=direction,
                search_end_y_mm=search_end,
                sample_count=sample_count,
            )
            return JointL0Trial(
                mirror_design=mirror.design,
                energy_points_v=tuple(energy_nodes),
                stripes=trial_stripes,
                stripe_entry_y_mm=entry_y_mm,
                nominal_turning_y_mm=trial_turn,
                target_oscillation_count=int(contract["nominal"]["target_oscillation_count"]),
                time_platform_eta_nodes=nodes,
                kappa_derivative_step=kappa_step,
                time_platform_derivative_step=_finite(
                    profile["time_platform_derivative_step"], "time-platform derivative step"
                ),
                energy_derivative_step_v=energy_step,
            )

        initial_full_report = evaluate_joint_l0_trial(trial_from_biases(tuple(float(value) for value in values)))
        l0_budget = contract["mirror"]["theory_requirements"]["l0_acceptance_budget"]
        period_slope_scale = derive_mirror_l0_slope_tolerance_per_v(
            float(l0_budget["minimum_mass_resolution"]),
            float(l0_budget["mirror_time_width_fraction"]),
            tuple(energy_nodes),
        )
        full_residual_scales = tuple(
            period_slope_scale if name.startswith("full_analyser_period_slope_at_") else 1.0
            for name in initial_full_report.residual_names()
        )
        numerics = contract["dual_stripe_l0"]["determination_numerics"]
        full_report, full_classification = finite_difference_joint_jacobian(
            ("stripe_set_1_bias_v", "stripe_set_2_bias_v"),
            tuple(float(value) for value in values),
            (voltage_step, voltage_step),
            trial_from_biases,
            parameter_scales=(energy, energy),
            residual_scales=full_residual_scales,
            relative_rank_tolerance=_finite(
                numerics["relative_singular_value_rank_tolerance"], "rank tolerance"
            ),
            compatibility_tolerance=_finite(
                numerics["scaled_irreducible_residual_norm_tolerance"],
                "compatibility tolerance",
            ),
        )
        record = {
            "stripe_biases_v": values.tolist(),
            "native_seed_residuals": {
                "target_oscillation_count": float(residual[0]),
                "spatial_return_kappa_prime": float(residual[1]),
            },
            "jacobian_rank": history[-1]["jacobian_rank"],
            "native_newton_history": history,
            "drift_length_L_mm": state.drift_length_l_mm,
            "mirror_owned_axial_width_W_mm": state.axial_width_w_mm,
            "nominal_kappa_1": state.nominal_kappa_1,
            "nominal_injection_angle_degrees": math.degrees(state.nominal_injection_angle_rad),
            "response_matrix_condition_number_2": response["response_matrix_condition_number_2"],
            "full_analyser_reduced_periods_mm_per_sqrt_v": periods,
            "full_analyser_relative_period_residuals": [
                (periods[0] - central_period) / central_period,
                (periods[2] - central_period) / central_period,
            ],
            "full_analyser_normalized_period_slopes_per_v": dict(
                zip((str(value) for value in energy_nodes), full_analyser_slopes)
            ),
            "time_platform_tau_g_derivatives": dict(zip((str(value) for value in nodes), time_residuals)),
            "complete_fixed_hardware_residuals": dict(full_report.residuals),
            "paper_turning_normalization": {
                "constraint": "psi(1)-1=0",
                "residual": 0.0,
                "status": "eliminated_by_deriving_L_from_the_first_physical_5eV_turn",
                "semantics": "This paper relation determines L for each voltage trial; it is not counted again as an independent optimizer residual.",
            },
            "complete_fixed_hardware_residual_scales": dict(
                zip(full_report.residual_names(), full_residual_scales)
            ),
            "complete_fixed_hardware_determination": asdict(full_classification),
        }
        if not any(
            np.linalg.norm(values - np.asarray(known["stripe_biases_v"]), ord=np.inf) <= voltage_step
            for known in native_roots
        ):
            native_roots.append(record)
    if not native_roots:
        raise CandidateContractError("no nondegenerate native-geometry Stripe seed passed the numerical root gate")
    native_roots.sort(key=lambda item: (
        max(abs(value) for value in item["stripe_biases_v"]),
        item["response_matrix_condition_number_2"],
    ))
    selected = native_roots[0]
    return {
        "schema_version": 1,
        "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed",
        "status": "success",
        "qualification": "analytic_seed__complete_fixed_hardware_consistency_diagnostic__P1_P2_pending",
        "managed_mirror_run_id": mirror.run_id,
        "managed_mirror_manifest_sha256": mirror.manifest_sha256,
        "paper_relation_identity": "same equations and dimensionless structure; instance coefficients, L, W, and voltages may differ",
        "seed_equations": profile["seed_equations"],
        "entry_direction_project": list(direction),
        "search_envelope_v": [lower_bound, upper_bound],
        "turning_search_end_y_mm": search_end,
        "turning_search_sample_count": sample_count,
        "start_audit": {
            "attempted": starts_attempted,
            "feasible": starts_feasible,
            "surrogate_root_count": len(surrogate_roots),
            "native_nondegenerate_root_count": len(native_roots),
        },
        "selection_rule": "minimum maximum absolute Stripe voltage, then minimum response-matrix condition number",
        "selected_seed": selected,
        "native_root_family": native_roots,
        "limitations": [
            "The polynomial/linear fit is used only for root discovery; every published seed quantity is native-B-spline evaluated.",
            "Only the contract target K and kappa-prime=0 determine this two-voltage seed; the four time-platform and three local full-analyser energy-slope residuals are classified together but are not acceptance-tested.",
            "P1/P2 transport, finite three-dimensional fields, and SIMION flight remain pending.",
        ],
    }


def build_operating_seed_report(mirror_manifest: Path, downstream_contract: Path) -> dict[str, Any]:
    """Search every managed gamma-target mirror root before downstream selection."""
    mirror = load_managed_mirror_candidate(mirror_manifest, downstream_contract)
    reports: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    consistency_family: list[dict[str, Any]] = []
    branches = [
        replace(
            mirror,
            design=root.design,
            nominal_reduced_period_mm_per_sqrt_v=root.nominal_reduced_period_mm_per_sqrt_v,
            nominal_axial_width_w_mm=root.nominal_axial_width_w_mm,
        )
        for root in mirror.root_family
    ]
    maximum_workers = _positive_integer(
        _seed_profile(mirror.contract)["complete_consistency_maximum_parallel_workers"],
        "complete consistency maximum parallel workers",
    )
    actual_workers = min(maximum_workers, len(branches))
    with ProcessPoolExecutor(max_workers=actual_workers) as executor:
        consistency_results = list(executor.map(_search_complete_fixed_hardware_consistency, branches))
    for index, (root, branch, consistency) in enumerate(
        zip(mirror.root_family, branches, consistency_results)
    ):
        consistency_family.append({
            "mirror_root_index": index,
            "source_l0_restart_index": root.source_l0_restart_index,
            "mirror_owned_axial_width_W_mm": root.nominal_axial_width_w_mm,
            "complete_fixed_hardware_search": consistency,
        })
        try:
            report = _build_operating_seed_report_for_mirror(branch)
        except CandidateContractError as error:
            rejected.append({
                "mirror_root_index": index,
                "source_l0_restart_index": root.source_l0_restart_index,
                "mirror_owned_axial_width_W_mm": root.nominal_axial_width_w_mm,
                "reason": str(error),
            })
            continue
        report["mirror_root_index"] = index
        report["source_l0_restart_index"] = root.source_l0_restart_index
        report["mirror_root_gamma_degrees"] = root.gamma_degrees
        reports.append(report)
    if not reports:
        return {
            "schema_version": 2,
            "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
            "status": "no_two_equation_seed_found",
            "qualification": "negative_analytic_seed_diagnostic__not_an_operating_point",
            "managed_mirror_run_id": mirror.run_id,
            "managed_mirror_manifest_sha256": mirror.manifest_sha256,
            "paper_relation_identity": "same equations and dimensionless structure; instance coefficients, L, W, and voltages may differ",
            "mirror_root_count": len(mirror.root_family),
            "complete_consistency_actual_parallel_workers": actual_workers,
            "successful_mirror_root_count": 0,
            "complete_fixed_hardware_root_family": consistency_family,
            "rejected_mirror_roots": rejected,
            "limitations": [
                "No qualified mirror root produced a native fixed-geometry K/spatial-return seed inside the declared search envelope.",
                "This is a bounded numerical diagnostic, not a proof that no mathematical root exists outside that envelope.",
                "No Stripe voltage, L, prism voltage, SIMION flight, or performance value is published.",
            ],
        }
    reports.sort(key=lambda item: (
        max(abs(value) for value in item["selected_seed"]["stripe_biases_v"]),
        item["selected_seed"]["response_matrix_condition_number_2"],
    ))
    selected = reports[0]
    return {
        **selected,
        "schema_version": 2,
        "role": "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family",
        "mirror_root_count": len(mirror.root_family),
        "complete_consistency_actual_parallel_workers": actual_workers,
        "successful_mirror_root_count": len(reports),
        "selected_mirror_root_index": selected["mirror_root_index"],
        "per_mirror_root_reports": reports,
        "complete_fixed_hardware_root_family": consistency_family,
        "rejected_mirror_roots": rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-manifest", required=True, type=Path)
    parser.add_argument("--downstream-contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = build_operating_seed_report(arguments.mirror_manifest, arguments.downstream_contract)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"MRTOF_DUAL_STRIPE_OPERATING_SEED=PASS OUTPUT={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
