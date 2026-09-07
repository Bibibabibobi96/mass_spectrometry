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
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from scipy.optimize import least_squares

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    analyze_dual_stripe_l0,
    identify_fixed_cad_component_shapes,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_mirror_stripe_l0 import (
    StripeHardBoundary,
    coupled_reduced_period_mm_per_sqrt_v,
    derive_coupled_drift_state,
    derive_turning_y_from_entry_direction,
    time_platform_derivative_residuals,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_candidate_receipt import (
    ManagedMirrorCandidate,
    load_managed_mirror_candidate,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import reduced_period
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_width_evaluator,
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

    def first(y_mm: float) -> float:
        distance = -float(y_mm)
        return first_baseline + sum(value * distance**power for power, value in enumerate(coefficients, 1))

    def second(y_mm: float) -> float:
        return second_baseline + linear * -float(y_mm)

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
    direction_sign = 1.0 if turn > entry else -1.0
    length = state.drift_length_l_mm
    lower = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        target_oscillation_count=target_k,
        stripes=stripes,
        entry_y_mm=entry,
        turning_y_mm=entry + direction_sign * length * (1.0 - kappa_derivative_step),
    )
    upper = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy,
        target_oscillation_count=target_k,
        stripes=stripes,
        entry_y_mm=entry,
        turning_y_mm=entry + direction_sign * length * (1.0 + kappa_derivative_step),
    )
    kappa_prime = (upper.nominal_kappa_1 - lower.nominal_kappa_1) / (2.0 * kappa_derivative_step)
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


def build_operating_seed_report(mirror_manifest: Path, downstream_contract: Path) -> dict[str, Any]:
    """Search with the structural surrogate and publish native-geometry seed diagnostics."""
    mirror = load_managed_mirror_candidate(mirror_manifest, downstream_contract)
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
        compile_dual_stripe_width_evaluator(contract, name) for name in ("set_1", "set_2")
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
            "time_platform_tau_g_derivatives": dict(zip((str(value) for value in nodes), time_residuals)),
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
        "qualification": "analytic_seed_only__time_platform_energy_and_P1_P2_pending",
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
            "Only the contract target K and kappa-prime=0 determine this two-voltage seed; raw time-platform and energy residuals are not acceptance-tested.",
            "P1/P2 transport, finite three-dimensional fields, and SIMION flight remain pending.",
        ],
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
