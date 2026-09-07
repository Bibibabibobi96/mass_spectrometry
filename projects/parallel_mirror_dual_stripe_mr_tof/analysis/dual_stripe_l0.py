"""Solver-neutral L0 checks for the two-response MR-TOF Stripe topology.

The model intentionally stops before return-time or oscillation predictions:
those require a validated mirror period, injection angle, and three-dimensional
field.  It does prove the lower-level facts needed before that calculation:
positive physical widths, non-degenerate voltage responses, and the exact
nominal-point response factors from the dual-Stripe theory.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_width_evaluator,
    resolve_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


def _condition_number_2x2(a: float, b: float, c: float, d: float) -> float:
    """Return the 2-norm condition number without a numerical-library dependency."""
    trace = a * a + b * b + c * c + d * d
    determinant = a * d - b * c
    discriminant = max(0.0, trace * trace - 4.0 * determinant * determinant)
    singular_max_sq = (trace + math.sqrt(discriminant)) / 2.0
    singular_min_sq = (trace - math.sqrt(discriminant)) / 2.0
    if singular_min_sq <= 0.0:
        return math.inf
    return math.sqrt(singular_max_sq / singular_min_sq)


def _width_bounds(record: dict[str, Any]) -> tuple[float, float]:
    polygon = record["polygon_yz_mm"]
    if len(polygon) < 4 or len(polygon) % 2:
        raise CandidateContractError("resolved Stripe polygon must contain paired lower and upper edges")
    count = len(polygon) // 2
    lower = polygon[:count]
    upper = list(reversed(polygon[count:]))
    widths = []
    for low, high in zip(lower, upper):
        if low[0] != high[0]:
            raise CandidateContractError("resolved Stripe edge y samples are inconsistent")
        widths.append(float(high[1]) - float(low[1]))
    if min(widths) <= 0.0:
        raise CandidateContractError("resolved Stripe contains a non-positive physical width")
    return min(widths), max(widths)


def _width_samples(record: dict[str, Any]) -> tuple[tuple[float, float], ...]:
    """Return common-y physical plate separations from one resolved Stripe."""
    polygon = record["polygon_yz_mm"]
    count = len(polygon) // 2
    lower = polygon[:count]
    upper = list(reversed(polygon[count:]))
    return tuple((float(low[0]), float(high[1]) - float(low[1])) for low, high in zip(lower, upper))


def _linear_width_report(samples: tuple[tuple[float, float], ...]) -> dict[str, float]:
    """Fit the endpoint-constrained linear width term and expose its residual."""
    first_y, first_width = samples[0]
    last_y, last_width = samples[-1]
    slope = (last_width - first_width) / (last_y - first_y)
    maximum_residual = max(abs(width - (first_width + slope * (y - first_y))) for y, width in samples)
    return {
        "intercept_at_first_y_mm": first_width,
        "slope_mm_per_mm": slope,
        "maximum_residual_mm": maximum_residual,
    }


def invert_nominal_psi_g_response(
    psi: float, g: float, h_1: float, h_2: float,
) -> tuple[float, float]:
    """Invert the dual-Stripe nominal response basis at one ``eta``.

    The hard-boundary response matrix is ``[[1, 1], [h1, h2]]``.  The
    returned normalized contributions are the unique solution for
    ``(psi, g)``; physical widths and their action normalization remain a
    separate, explicitly supplied inverse problem.
    """
    psi_value = _finite(psi, "psi")
    g_value = _finite(g, "g")
    first = _finite(h_1, "h_1")
    second = _finite(h_2, "h_2")
    determinant = first - second
    if determinant == 0.0:
        raise CandidateContractError("dual Stripe response basis is singular")
    return (
        (g_value - second * psi_value) / determinant,
        (first * psi_value - g_value) / determinant,
    )


def endpoint_regularized_kappa(
    psi_at_eta: Callable[[float], float], *, initial_panels: int = 32,
    max_refinements: int = 12, relative_tolerance: float = 1e-8,
) -> float:
    """Integrate ``kappa(1)`` with the theory's endpoint substitution.

    For ``eta = 1-u²``, the integrand becomes
    ``2u / sqrt(psi(1)-psi(1-u²))``.  Midpoint quadrature avoids evaluating
    the removable endpoint directly and convergence under panel doubling is
    an explicit validity condition.
    """
    if not callable(psi_at_eta):
        raise CandidateContractError("psi_at_eta must be callable")
    if not isinstance(initial_panels, int) or initial_panels < 2:
        raise CandidateContractError("endpoint regularization needs at least two initial panels")
    if not isinstance(max_refinements, int) or max_refinements < 1:
        raise CandidateContractError("endpoint regularization needs a positive refinement count")
    if not isinstance(relative_tolerance, (int, float)) or not 0.0 < float(relative_tolerance) < 1.0:
        raise CandidateContractError("endpoint regularization tolerance must lie between zero and one")
    endpoint = _finite(psi_at_eta(1.0), "psi(1)")
    previous: float | None = None
    for refinement in range(max_refinements):
        panels = initial_panels * (2 ** refinement)
        total = 0.0
        for index in range(panels):
            u = (index + 0.5) / panels
            difference = endpoint - _finite(psi_at_eta(1.0 - u * u), "psi(eta)")
            if difference <= 0.0:
                raise CandidateContractError("psi(eta) must remain strictly below psi(1) on the turning interval")
            total += 2.0 * u / math.sqrt(difference)
        current = total / panels
        if previous is not None and abs(current - previous) <= float(relative_tolerance) * max(1.0, abs(current)):
            return current
        previous = current
    raise CandidateContractError("endpoint-regularized kappa integral did not converge")


def endpoint_regularized_tau_g(
    psi_at_eta: Callable[[float], float], g_at_eta: Callable[[float], float], eta_turn: float,
    *, initial_panels: int = 32, max_refinements: int = 12, relative_tolerance: float = 1e-8,
) -> float:
    """Integrate the generalized time response using ``eta=eta_turn-u²``.

    This is the same endpoint regularization required for ``kappa`` but for
    the dual-Stripe ``tau_g`` numerator.  It refuses an invalid return branch
    instead of silently truncating before the turning singularity.
    """
    if not callable(psi_at_eta) or not callable(g_at_eta):
        raise CandidateContractError("tau_g requires callable psi and g profiles")
    turn = _finite(eta_turn, "eta_turn")
    if turn <= 0.0 or not isinstance(initial_panels, int) or initial_panels < 2:
        raise CandidateContractError("tau_g needs a positive turn and at least two initial panels")
    if not isinstance(max_refinements, int) or max_refinements < 1 or not 0.0 < float(relative_tolerance) < 1.0:
        raise CandidateContractError("tau_g refinement controls are invalid")
    endpoint = _finite(psi_at_eta(turn), "psi(eta_turn)")
    previous: float | None = None
    upper_u = math.sqrt(turn)
    for refinement in range(max_refinements):
        panels = initial_panels * (2 ** refinement)
        total = 0.0
        for index in range(panels):
            u = upper_u * (index + 0.5) / panels
            eta = turn - u * u
            difference = endpoint - _finite(psi_at_eta(eta), "psi(eta)")
            if difference <= 0.0:
                raise CandidateContractError("psi(eta) must remain strictly below psi(eta_turn) on the tau_g interval")
            total += 2.0 * u * _finite(g_at_eta(eta), "g(eta)") / math.sqrt(difference)
        current = upper_u * total / panels
        if previous is not None and abs(current - previous) <= float(relative_tolerance) * max(1.0, abs(current)):
            return current
        previous = current
    raise CandidateContractError("endpoint-regularized tau_g integral did not converge")


def tau_g_derivative_at_turn(
    psi_at_eta: Callable[[float], float], g_at_eta: Callable[[float], float], eta_turn: float,
    *, step: float,
) -> float:
    """Return a centered, regularized derivative of ``tau_g(eta_turn)``."""
    turn = _finite(eta_turn, "eta_turn")
    increment = _finite(step, "tau_g derivative step")
    if increment <= 0.0 or turn - increment <= 0.0:
        raise CandidateContractError("tau_g derivative step must remain inside the physical positive turn domain")
    upper = endpoint_regularized_tau_g(psi_at_eta, g_at_eta, turn + increment)
    lower = endpoint_regularized_tau_g(psi_at_eta, g_at_eta, turn - increment)
    return (upper - lower) / (2.0 * increment)


def identify_fixed_cad_component_shapes(contract: dict[str, Any]) -> dict[str, Any]:
    """Fit the declared polynomial/linear structure of the frozen CAD curves.

    Width baselines are removed at the theory entrance ``y=0`` and the two
    variations are fitted in physical distance from that plane.  This proves
    structural agreement without assuming the current coefficients equal the
    paper's printed values.  It deliberately does not infer ``L``: rescaling
    ``L`` and the dimensionless polynomial coefficients describes the same
    physical curve, so shape structure alone is rank-deficient in that scale.
    """
    l0 = contract.get("dual_stripe_l0")
    stripe = contract.get("dual_stripe")
    if not isinstance(l0, dict) or not isinstance(stripe, dict):
        raise CandidateContractError("fixed CAD Stripe identification requires dual_stripe and dual_stripe_l0")
    settings = l0.get("fixed_cad_shape_identification")
    theory = stripe.get("theory_profile")
    if not isinstance(settings, dict) or not isinstance(theory, dict):
        raise CandidateContractError("fixed CAD Stripe identification contract is required")
    polynomial_degree = settings.get("set_1_polynomial_degree")
    linear_degree = settings.get("set_2_polynomial_degree")
    if polynomial_degree != 5 or linear_degree != 1:
        raise CandidateContractError("current fixed CAD structure requires set-1 degree five and set-2 degree one")
    multipliers = tuple(settings.get("sampling_multipliers", []))
    if not multipliers or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in multipliers):
        raise CandidateContractError("Stripe shape sampling multipliers must be positive integers")
    if tuple(sorted(set(multipliers))) != multipliers:
        raise CandidateContractError("Stripe shape sampling multipliers must be unique and increasing")
    y_span = tuple(_finite(value, "Stripe active y span") for value in theory.get("active_y_span_mm", []))
    entry = _finite(l0.get("theory_stripe_entrance", {}).get("project_y_mm"), "Stripe theory entrance y")
    if len(y_span) != 2 or not y_span[0] < entry <= y_span[1] or entry != y_span[1]:
        raise CandidateContractError("fixed CAD Stripe identification requires the y=0 entrance at the active-span endpoint")
    samples_per_span = theory.get("sampling_per_nonzero_knot_span")
    if not isinstance(samples_per_span, int) or isinstance(samples_per_span, bool) or samples_per_span < 2:
        raise CandidateContractError("native Stripe sampling density must be an integer of at least two")
    nonzero_spans = []
    for set_name in ("set_1", "set_2"):
        definition = theory.get(set_name)
        if not isinstance(definition, dict):
            raise CandidateContractError(f"Stripe shape definition {set_name} is required")
        counts = []
        for edge_name in ("lower_edge", "upper_edge"):
            edge = definition.get(edge_name)
            if isinstance(edge, dict) and edge.get("basis") == "cubic_bspline":
                knots = tuple(_finite(value, f"{set_name} knot") for value in edge.get("knots", []))
                counts.append(sum(right > left for left, right in zip(knots, knots[1:])))
        nonzero_spans.append(max(counts, default=1))
    base_intervals = max(nonzero_spans) * samples_per_span
    first_width = compile_dual_stripe_width_evaluator(contract, "set_1")
    second_width = compile_dual_stripe_width_evaluator(contract, "set_2")
    first_baseline = first_width(entry)
    second_baseline = second_width(entry)
    active_length = entry - y_span[0]

    def fit_at_multiplier(multiplier: int) -> dict[str, Any]:
        interval_count = base_intervals * multiplier
        distances = np.linspace(0.0, active_length, interval_count + 1)
        physical_y = entry - distances
        high_values = np.asarray([first_width(float(value)) - first_baseline for value in physical_y])
        linear_values = np.asarray([second_width(float(value)) - second_baseline for value in physical_y])
        scaled_distance = distances / active_length
        polynomial_matrix = np.column_stack([
            scaled_distance ** power for power in range(1, polynomial_degree + 1)
        ])
        normalized_coefficients = np.linalg.lstsq(polynomial_matrix, high_values, rcond=None)[0]
        linear_matrix = scaled_distance.reshape((-1, 1))
        normalized_linear = float(np.linalg.lstsq(linear_matrix, linear_values, rcond=None)[0][0])
        high_residual = polynomial_matrix @ normalized_coefficients - high_values
        linear_residual = normalized_linear * scaled_distance - linear_values
        return {
            "sampling_multiplier": multiplier,
            "sample_count": interval_count + 1,
            "set_1_coefficients_for_normalized_active_distance_mm": [
                float(value) for value in normalized_coefficients
            ],
            "set_1_coefficients_per_physical_mm_power": [
                float(value / active_length ** power)
                for power, value in enumerate(normalized_coefficients, start=1)
            ],
            "set_2_coefficient_for_normalized_active_distance_mm": normalized_linear,
            "set_2_coefficient_per_physical_mm": normalized_linear / active_length,
            "set_1_rms_residual_mm": float(np.sqrt(np.mean(high_residual * high_residual))),
            "set_1_max_abs_residual_mm": float(np.max(np.abs(high_residual))),
            "set_2_rms_residual_mm": float(np.sqrt(np.mean(linear_residual * linear_residual))),
            "set_2_max_abs_residual_mm": float(np.max(np.abs(linear_residual))),
        }

    fits = [fit_at_multiplier(value) for value in multipliers]
    selected = fits[-1]
    nodes = tuple(_finite(value, "time-platform eta node") for value in l0["time_platform_constraint"]["eta_turn_nodes"])
    return {
        "schema_version": 1,
        "role": "fixed_cad_dual_stripe_component_shape_identification",
        "status": "diagnostic_structure_fitted__L_and_voltage_solution_pending",
        "source_geometry": "native frozen theory B-spline knot/control contract",
        "component_basis": settings.get("basis"),
        "width_baselines_at_entry_mm": {"set_1": first_baseline, "set_2": second_baseline},
        "active_distance_mm": active_length,
        "sampling_convergence": fits,
        "selected_fit": selected,
        "drift_length_identifiability": {
            "status": "underdetermined_from_shape_structure_alone",
            "reason": "For any positive L, coefficients can be transformed so the same polynomial in physical distance is written in eta=distance/L. Geometry structure therefore supplies no independent L equation.",
            "coefficient_transform": "If b_k multiplies physical distance^k, the eta coefficient is b_k*L^k; a separate normalization may move one further common scale.",
            "required_closure": "Derive L/turning from the coupled mirror receipt, Stripe action/normalization, target K, and path-ordered P1/P2 entrance state, then evaluate whether every requested eta node lies inside the frozen active span.",
        },
        "time_platform_node_span": {
            "eta_turn_nodes": list(nodes),
            "available_active_distance_mm": active_length,
            "status": "pending_independently_closed_L",
        },
        "theory_identity": {
            "status": "paper_relations_preserved__instance_values_pending",
            "invariants": [
                "the same dimensionless polynomial-plus-linear function structure",
                "the same action, pseudopotential, kappa, tau_g, K, L, W, and injection-angle relations",
                "the same nominal normalization and turning-point semantics",
            ],
            "instance_specific_outputs": [
                "polynomial and linear coefficients",
                "drift length L",
                "axial width W",
                "Stripe and prism voltages",
            ],
            "interpretation_guard": "A geometric polynomial component and a geometric linear component must not be equated term-by-term to psi_s and psi_m before the current instance normalization and voltage response have been solved. Shape structure alone cannot prove compatibility or incompatibility of the complete paper-equivalent equations.",
        },
        "limitations": [
            "This verifies the current polynomial/linear component structure; it neither assumes nor identifies the paper's printed coefficients.",
            "L is scale-degenerate in a free polynomial coefficient fit and is not published from geometry alone.",
            "No CAD-fit acceptance tolerance is declared, so raw residuals and sampling convergence are reported without promotion to Candidate.",
            "The physical dual-Stripe psi/g response, exact determination rank, P1/P2 transport, and finite three-dimensional fields remain unevaluated.",
        ],
    }


def analyze_dual_stripe_l0(
    contract: dict[str, Any],
    biases_v: Sequence[float],
) -> dict[str, Any]:
    """Check nominal dual-Stripe response independence and resolved widths.

    ``h_i=sqrt(w0/(w0-v_i))`` follows the project theory.  The matrix
    ``[[1,1],[h1,h2]]`` maps the two nominal spatial contributions to
    ``(psi,g)`` and is the unit-independent conditioning diagnostic.
    """
    nominal_energy = _finite(contract["nominal"]["energy_per_charge_v"], "nominal.energy_per_charge_v")
    stripe = contract["dual_stripe"]
    if len(biases_v) != 2:
        raise CandidateContractError("dual Stripe L0 requires exactly two explicit trial biases")
    v1 = _finite(biases_v[0], "Stripe trial set-1 bias")
    v2 = _finite(biases_v[1], "Stripe trial set-2 bias")
    if nominal_energy <= 0.0 or v1 == 0.0 or v2 == 0.0 or v1 == v2:
        raise CandidateContractError("dual Stripe biases must be distinct non-zero values")
    if nominal_energy <= v1 or nominal_energy <= v2:
        raise CandidateContractError("dual Stripe positive bias removes nominal transmission margin")
    h1 = math.sqrt(nominal_energy / (nominal_energy - v1))
    h2 = math.sqrt(nominal_energy / (nominal_energy - v2))
    determinant = h2 - h1
    condition = _condition_number_2x2(1.0, 1.0, h1, h2)
    if determinant == 0.0 or not math.isfinite(condition):
        raise CandidateContractError("dual Stripe response matrix is singular")
    resolved = resolve_geometry(contract)
    width_1 = _width_bounds(resolved["stripe_electrodes"][0])
    width_2 = _width_bounds(resolved["stripe_electrodes"][2])
    component_interpretation = stripe["theory_profile"].get("component_interpretation")
    if component_interpretation != (
        "set_1 total width is the high-order response; set_2 total width is the linear response. "
        "Their action-normalization and voltage solution remain an L0 inverse problem, not CAD data."
    ):
        raise CandidateContractError("dual Stripe component interpretation is not the qualified theory-CAD mapping")
    linear_report = _linear_width_report(_width_samples(resolved["stripe_electrodes"][2]))
    return {
        "model": "dual_stripe_nominal_response_l0",
        "energy_per_charge_v": nominal_energy,
        "biases_v": [v1, v2],
        "h_factors": [h1, h2],
        "response_matrix": [[1.0, 1.0], [h1, h2]],
        "response_matrix_determinant": determinant,
        "response_matrix_condition_number_2": condition,
        "physical_width_bounds_mm": {"set_1": list(width_1), "set_2": list(width_2)},
        "theory_cad_component_mapping": {
            "high_order_width_response": "set_1",
            "linear_width_response": "set_2",
            "linear_width_fit": linear_report,
        },
        "geometry_status": "positive B-spline-evaluated widths; central-ground opening and three-dimensional clearance remain gated",
        "not_evaluated": ["target_psi_g_fit", "voltage_inverse_solution", "mirror_period", "return_time", "oscillation_count", "time_platform"],
    }
