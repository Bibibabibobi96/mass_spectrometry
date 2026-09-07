"""Solver-neutral L0 checks for the two-response MR-TOF Stripe topology.

The model intentionally stops before return-time or oscillation predictions:
those require a validated mirror period, injection angle, and three-dimensional
field.  It does prove the lower-level facts needed before that calculation:
positive physical widths, non-degenerate voltage responses, and the exact
nominal-point response factors from the dual-Stripe theory.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
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


def analyze_dual_stripe_l0(contract: dict[str, Any]) -> dict[str, Any]:
    """Check nominal dual-Stripe response independence and resolved widths.

    ``h_i=sqrt(w0/(w0-v_i))`` follows the project theory.  The matrix
    ``[[1,1],[h1,h2]]`` maps the two nominal spatial contributions to
    ``(psi,g)`` and is the unit-independent conditioning diagnostic.
    """
    nominal_energy = _finite(contract["nominal"]["energy_per_charge_v"], "nominal.energy_per_charge_v")
    stripe = contract["dual_stripe"]
    v1 = _finite(stripe["set_1_bias_v"], "dual_stripe.set_1_bias_v")
    v2 = _finite(stripe["set_2_bias_v"], "dual_stripe.set_2_bias_v")
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
