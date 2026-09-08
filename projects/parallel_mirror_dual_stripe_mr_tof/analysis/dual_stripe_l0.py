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
from functools import lru_cache
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


def _polynomial_inner_product(
    first: Sequence[float], second: Sequence[float], upper: float,
) -> float:
    """Integrate two zero-constant polynomials over ``[0, upper]``."""
    limit = _finite(upper, "polynomial projection upper bound")
    if limit <= 0.0:
        raise CandidateContractError("polynomial projection upper bound must be positive")
    return sum(
        _finite(left, "first polynomial coefficient")
        * _finite(right, "second polynomial coefficient")
        * limit ** (left_power + right_power + 1)
        / (left_power + right_power + 1)
        for left_power, left in enumerate(first, start=1)
        for right_power, right in enumerate(second, start=1)
    )


def derive_manufactured_basis_voltage_seed(
    contract: dict[str, Any],
    *,
    mirror_axial_width_w_mm: float,
    basis_coefficients_c0_to_c5: Sequence[float],
    axial_energy_per_charge_v: float | None = None,
) -> dict[str, Any]:
    """Reverse the manufactured theory-basis scales into nominal biases.

    The current hardware curves were generated as a scaled high-order basis
    ``psi_s`` and a scaled linear basis ``psi_m`` at the manufactured
    ``L``.  After removing the entry baselines, the exact hard-boundary shape
    relation is

    ``S_i = lambda_i p_i`` and
    ``lambda_i = W*w_y/v_i * (1 + sqrt(1-v_i/w0))/2``.

    Therefore each voltage follows algebraically from its fitted geometry
    scale.  The result is the nominal solver-neutral design point; it does
    not remove either voltage from the later finite-field tuning coordinates.
    """
    coefficients = tuple(
        _finite(value, "manufactured basis coefficient")
        for value in basis_coefficients_c0_to_c5
    )
    if len(coefficients) != 6:
        raise CandidateContractError("manufactured basis inverse requires c0..c5")
    linear_basis = coefficients[0]
    high_basis = coefficients[1:]
    if linear_basis == 0.0 or _polynomial_inner_product(high_basis, high_basis, 1.0) == 0.0:
        raise CandidateContractError("manufactured theory bases must both be nonzero")

    l0 = contract.get("dual_stripe_l0")
    nominal = contract.get("nominal")
    if not isinstance(l0, dict) or not isinstance(nominal, dict):
        raise CandidateContractError("manufactured basis inverse requires Stripe and nominal contracts")
    length = _finite(
        l0.get("manufactured_design_abs_drift_length_L_mm"),
        "manufactured-design drift length",
    )
    width = _finite(mirror_axial_width_w_mm, "mirror-owned axial width W")
    energy = (
        _finite(axial_energy_per_charge_v, "selected axial energy per charge")
        if axial_energy_per_charge_v is not None
        else _finite(nominal.get("energy_per_charge_v"), "nominal axial energy per charge")
    )
    oscillations = nominal.get("target_oscillation_count")
    if (
        length <= 0.0
        or width <= 0.0
        or energy <= 0.0
        or not isinstance(oscillations, int)
        or isinstance(oscillations, bool)
        or oscillations <= 0
    ):
        raise CandidateContractError("manufactured basis inverse inputs must be positive")

    shape = identify_fixed_cad_component_shapes(contract)
    selected = shape["selected_fit"]
    physical_high = tuple(
        _finite(value, "fitted high-order physical coefficient")
        for value in selected["set_1_coefficients_per_physical_mm_power"]
    )
    if len(physical_high) != 5:
        raise CandidateContractError("manufactured high-order fit must contain five coefficients")
    geometry_high = tuple(
        value * length**power for power, value in enumerate(physical_high, start=1)
    )
    geometry_linear = (
        _finite(selected["set_2_coefficient_per_physical_mm"], "fitted linear coefficient")
        * length
    )
    active_eta = _finite(shape["active_distance_mm"], "Stripe active distance") / length
    high_denominator = _polynomial_inner_product(high_basis, high_basis, active_eta)
    high_scale = _polynomial_inner_product(geometry_high, high_basis, active_eta) / high_denominator
    linear_scale = geometry_linear / linear_basis
    if high_scale == 0.0 or linear_scale == 0.0:
        raise CandidateContractError("manufactured basis geometry scales must be nonzero")

    def psi(eta: float) -> float:
        coordinate = _finite(eta, "basis eta")
        return linear_basis * coordinate + sum(
            value * coordinate**power for power, value in enumerate(high_basis, start=1)
        )

    kappa = endpoint_regularized_kappa(psi)
    partition = contract.get("prism_transport", {}).get("energy_partition", {})
    if not isinstance(partition, dict) or partition.get("semantics") != (
        "post_acceleration_total_and_orthogonal_components_per_charge_ev"
    ):
        raise CandidateContractError("manufactured basis inverse requires the post-acceleration energy partition")
    total_energy = _finite(partition.get("total_kinetic_energy_ev"), "post-acceleration total energy")
    drift_energy = _finite(partition.get("drift_kinetic_energy_ev"), "drift-direction energy")
    fast_energy = _finite(partition.get("fast_reflection_kinetic_energy_ev"), "fast-reflection energy")
    if drift_energy <= 0.0:
        raise CandidateContractError("post-acceleration drift energy must be positive")
    if axial_energy_per_charge_v is None and (
        fast_energy != energy or total_energy != drift_energy + fast_energy
    ):
        raise CandidateContractError(
            "post-acceleration energy must equal drift energy plus the nominal axial energy"
        )
    selected_total_energy = drift_energy + energy
    sin_theta = math.sqrt(drift_energy / selected_total_energy)
    predicted_oscillations = kappa * length / (width * sin_theta)
    required_width = kappa * length / (oscillations * sin_theta)
    target_band_lower = oscillations - 0.5
    target_band_upper = oscillations + 0.5
    target_band_margin = min(
        predicted_oscillations - target_band_lower,
        target_band_upper - predicted_oscillations,
    )
    assigned_oscillations = math.floor(predicted_oscillations + 0.5)

    def invert_scale(scale: float) -> tuple[float, float, float]:
        # From lambda = W*sin(theta)^2 / [2*(1-r)] with
        # r=sqrt(1-v/w0).  This is algebraically equivalent to the exact
        # finite-bias action relation and remains well behaved for v<0.
        root = 1.0 - width * drift_energy / (2.0 * energy * scale)
        if root <= 0.0:
            raise CandidateContractError("manufactured basis scale removes Stripe transmission")
        voltage = energy * (1.0 - root * root)
        if voltage == 0.0 or voltage >= energy:
            raise CandidateContractError("manufactured basis inverse produced an invalid Stripe bias")
        response = 1.0 / root
        reconstructed_scale = width * drift_energy / (2.0 * energy * (1.0 - root))
        return voltage, response, reconstructed_scale

    first_voltage, first_h, first_reconstructed = invert_scale(high_scale)
    second_voltage, second_h, second_reconstructed = invert_scale(linear_scale)
    condition = _condition_number_2x2(1.0, 1.0, first_h, second_h)

    high_residual = tuple(
        actual - high_scale * target for actual, target in zip(geometry_high, high_basis)
    )
    high_rms = math.sqrt(
        _polynomial_inner_product(high_residual, high_residual, active_eta) / active_eta
    )
    realized_g = (
        first_h * high_basis[0] + second_h * linear_basis,
        *(first_h * value for value in high_basis[1:]),
    )
    paper_g = (high_basis[0] - linear_basis, *high_basis[1:])
    return {
        "status": "analytic_nominal_voltage_seed",
        "qualification": "solver_neutral_hard_boundary_initialization__finite_3d_tuning_pending",
        "manufactured_design_drift_length_L_mm": length,
        "mirror_owned_axial_width_W_mm": width,
        "selected_axial_energy_per_charge_v": energy,
        "selected_total_kinetic_energy_ev": selected_total_energy,
        "target_oscillation_count_K": oscillations,
        "predicted_continuous_oscillation_count": predicted_oscillations,
        "oscillation_count_residual": predicted_oscillations - oscillations,
        "nominal_center_exact_K_design_equation": {
            "equation": "T_D(theta_0)/T_0=K",
            "target_K": oscillations,
            "calculated_T_D_over_T_0": predicted_oscillations,
            "residual": predicted_oscillations - oscillations,
            "status": (
                "satisfied_by_current_analytic_inputs"
                if predicted_oscillations == oscillations
                else "unsatisfied_by_current_analytic_inputs"
            ),
            "semantics": (
                "The nominal design centre must solve this equality. A later numerical solver "
                "must use a separately declared numerical residual tolerance; the half-integer "
                "interval is not a substitute for this equation."
            ),
        },
        "nominal_center_oscillation_topology": {
            "nearest_integer_K": assigned_oscillations,
            "target_K_interval_lower_exclusive": target_band_lower,
            "target_K_interval_upper_exclusive": target_band_upper,
            "signed_minimum_boundary_margin": target_band_margin,
            "target_K_interval_passed": target_band_margin > 0.0,
            "semantics": (
                "This classifies only the nominal center trajectory. The same strict interval must "
                "later hold over the complete accepted bundle in the native three-dimensional field."
            ),
        },
        "nominal_axial_energy_per_charge_v": energy,
        "post_acceleration_total_energy_per_charge_v": total_energy,
        "nominal_kappa_1": kappa,
        "nominal_injection_angle_degrees": math.degrees(math.asin(sin_theta)),
        "derived_drift_kinetic_energy_per_charge_v": drift_energy,
        "derived_fast_reflection_energy_per_charge_v": fast_energy,
        "mirror_axial_width_required_for_exact_K_mm": required_width,
        "mirror_axial_width_residual_mm": width - required_width,
        "geometry_basis_scales_mm": {
            "set_1_high_order": high_scale,
            "set_2_linear": linear_scale,
        },
        "geometry_basis_fit": {
            "active_eta_max": active_eta,
            "set_1_integral_projection_rms_residual_mm": high_rms,
            "set_1_eta_coefficients_mm": list(geometry_high),
            "set_2_eta_linear_coefficient_mm": geometry_linear,
        },
        "stripe_biases_v": [first_voltage, second_voltage],
        "h_factors": [first_h, second_h],
        "response_matrix": [[1.0, 1.0], [first_h, second_h]],
        "response_matrix_condition_number_2": condition,
        "shape_scale_reconstruction_residual_mm": [
            first_reconstructed - high_scale,
            second_reconstructed - linear_scale,
        ],
        "nominal_spatial_response": "psi=psi_s+psi_m by analytic shape-scale inversion",
        "nominal_time_response_coefficients_by_power": list(realized_g),
        "original_paper_time_response_coefficients_by_power": list(paper_g),
        "voltage_authority": (
            "The two values are theory-derived nominal initial voltages for the fixed manufactured "
            "geometry. Both remain adjustable coordinates in finite three-dimensional calibration."
        ),
        "definition_classification": {
            "status": (
                "current_mirror_root_fails_center_exact_K_and_target_topology"
                if target_band_margin <= 0.0
                else "center_exact_K_unsolved__nominal_topology_only_passes"
            ),
            "independent_fixed_inputs": [
                "manufactured L",
                "target K",
                "source-preserved 5 eV drift energy",
                "4000 eV axial energy",
                "two user-confirmed manufactured theory-basis geometry scales",
            ],
            "adjustable_coordinate_implication": (
                "Mirror voltages remain adjustable and must select a mirror-theory-qualified W that "
                "closes the reported K/W residual; v1/v2 then update analytically from that W."
            ),
        },
    }


@lru_cache(maxsize=None)
def _legendre_rule(order: int) -> tuple[np.ndarray, np.ndarray]:
    """Return a cached Gauss--Legendre rule for repeated endpoint integrals."""
    nodes, weights = np.polynomial.legendre.leggauss(order)
    nodes.setflags(write=False)
    weights.setflags(write=False)
    return nodes, weights


def _gauss_legendre_integral(function: Callable[[float], float], upper: float, order: int) -> float:
    nodes, weights = _legendre_rule(order)
    half = upper / 2.0
    return half * sum(
        float(weight) * _finite(function(half * (float(node) + 1.0)), "quadrature integrand")
        for node, weight in zip(nodes, weights)
    )


def endpoint_regularized_kappa(
    psi_at_eta: Callable[[float], float], *, initial_panels: int = 32,
    max_refinements: int = 12, relative_tolerance: float = 1e-8,
) -> float:
    """Integrate ``kappa(1)`` with the theory's endpoint substitution.

    For ``eta = 1-u²``, the integrand becomes
    ``2u / sqrt(psi(1)-psi(1-u²))``.  Gauss--Legendre nodes avoid evaluating
    the removable endpoint directly and convergence under order doubling is
    an explicit validity condition.  This preserves the native profile while
    avoiding thousands of repeated samples per voltage trial.
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
        order = initial_panels * (2 ** refinement)

        def integrand(u: float) -> float:
            difference = endpoint - _finite(psi_at_eta(1.0 - u * u), "psi(eta)")
            if difference <= 0.0:
                raise CandidateContractError("psi(eta) must remain strictly below psi(1) on the turning interval")
            return 2.0 * u / math.sqrt(difference)

        current = _gauss_legendre_integral(integrand, 1.0, order)
        if previous is not None and abs(current - previous) <= float(relative_tolerance) * max(1.0, abs(current)):
            return current
        previous = current
    raise CandidateContractError("endpoint-regularized kappa integral did not converge")


def endpoint_regularized_kappa_at_turn(
    psi_at_eta: Callable[[float], float], eta_turn: float,
) -> float:
    """Evaluate the paper's fixed-profile ``kappa(eta_turn)``.

    ``endpoint_regularized_kappa`` integrates a unit interval.  Rescaling only
    the integration coordinate gives the required physical integral while
    preserving one fixed ``psi(eta)`` and its nominal normalization.
    """
    turn = _finite(eta_turn, "kappa eta_turn")
    if turn <= 0.0:
        raise CandidateContractError("kappa eta_turn must be positive")
    return turn * endpoint_regularized_kappa(lambda unit_eta: psi_at_eta(turn * unit_eta))


def kappa_derivative_at_turn(
    psi_at_eta: Callable[[float], float], eta_turn: float, *, step: float,
) -> float:
    """Differentiate ``kappa(eta_turn)`` on one fixed normalized profile."""
    turn = _finite(eta_turn, "kappa derivative eta_turn")
    increment = _finite(step, "kappa derivative step")
    if increment <= 0.0 or turn - increment <= 0.0:
        raise CandidateContractError("kappa derivative step must stay inside the positive turn domain")
    upper = endpoint_regularized_kappa_at_turn(psi_at_eta, turn + increment)
    lower = endpoint_regularized_kappa_at_turn(psi_at_eta, turn - increment)
    return (upper - lower) / (2.0 * increment)


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
        order = initial_panels * (2 ** refinement)

        def integrand(u: float) -> float:
            eta = turn - u * u
            difference = endpoint - _finite(psi_at_eta(eta), "psi(eta)")
            if difference <= 0.0:
                raise CandidateContractError("psi(eta) must remain strictly below psi(eta_turn) on the tau_g interval")
            return 2.0 * u * _finite(g_at_eta(eta), "g(eta)") / math.sqrt(difference)

        current = _gauss_legendre_integral(integrand, upper_u, order)
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


def paper_dimensionless_condition_residuals(
    coefficients: Sequence[float],
    *,
    eta_turn_nodes: Sequence[float],
    kappa_derivative_step: float,
    tau_derivative_step: float,
) -> tuple[tuple[str, float], ...]:
    """Evaluate the paper's six coefficient conditions without printed values.

    ``coefficients`` are ordered ``c0..c5``.  The first response is
    ``psi_m=c0*eta`` and the remaining polynomial is ``psi_s``; consequently
    ``psi=psi_s+psi_m`` and ``g=psi_s-psi_m``.  This evaluator owns no
    coefficient seed or active-instance geometry and can therefore be used to
    solve the project-selected time-platform nodes without promoting the
    rounded coefficients printed in the paper.
    """
    values = tuple(_finite(value, "dimensionless target coefficient") for value in coefficients)
    nodes = tuple(_finite(value, "dimensionless target eta node") for value in eta_turn_nodes)
    kappa_step = _finite(kappa_derivative_step, "dimensionless target kappa step")
    tau_step = _finite(tau_derivative_step, "dimensionless target tau step")
    if len(values) != 6 or len(nodes) != 4:
        raise CandidateContractError("paper dimensionless target requires c0..c5 and four eta nodes")
    if len(set(nodes)) != len(nodes) or min(nodes) <= 0.0 or min(kappa_step, tau_step) <= 0.0:
        raise CandidateContractError("paper dimensionless target nodes and derivative steps are invalid")
    if any(node - tau_step <= 0.0 for node in nodes) or 1.0 - kappa_step <= 0.0:
        raise CandidateContractError("paper dimensionless derivative stencil left the positive turn domain")

    def psi(eta: float) -> float:
        coordinate = _finite(eta, "dimensionless target eta")
        return values[0] * coordinate + sum(
            values[power] * coordinate**power for power in range(1, 6)
        )

    def g(eta: float) -> float:
        coordinate = _finite(eta, "dimensionless target eta")
        return sum(values[power] * coordinate**power for power in range(1, 6)) - values[0] * coordinate

    residuals = [
        ("nominal_turn_normalization", psi(1.0) - 1.0),
        ("spatial_return_kappa_prime", kappa_derivative_at_turn(psi, 1.0, step=kappa_step)),
    ]
    residuals.extend(
        (
            f"time_platform_tau_g_prime_eta_{node:.12g}",
            tau_g_derivative_at_turn(psi, g, node, step=tau_step),
        )
        for node in nodes
    )
    return tuple(residuals)


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
        "status": "manufactured_theory_basis_fitted__analytic_voltage_inverse_ready",
        "source_geometry": "native frozen theory B-spline knot/control contract",
        "component_basis": settings.get("basis"),
        "width_baselines_at_entry_mm": {"set_1": first_baseline, "set_2": second_baseline},
        "active_distance_mm": active_length,
        "sampling_convergence": fits,
        "selected_fit": selected,
        "drift_length_identifiability": {
            "status": "fixed_by_manufactured_design_contract",
            "reason": "Shape structure alone is scale-degenerate, but the current manufactured design independently fixes L=340 mm. The fitted physical coefficients are transformed with that contract value rather than used to infer L.",
            "coefficient_transform": "If b_k multiplies physical distance^k, the eta coefficient is b_k*L^k; a separate normalization may move one further common scale.",
            "required_closure": "Consume the manufactured L, mirror W, target K and axial energy to invert the two theory-basis geometry scales into nominal Stripe voltages.",
        },
        "time_platform_node_span": {
            "eta_turn_nodes": list(nodes),
            "available_active_distance_mm": active_length,
            "status": "covered_by_manufactured_L_span_check",
        },
        "theory_identity": {
            "status": "user_confirmed_original_geometry_bases__voltage_inverse_ready",
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
            "interpretation_guard": "The user confirms the current curves are scaled psi_s and psi_m geometry bases at L=340 mm. Their scales determine nominal spatial-response voltages, while the resulting finite-bias time response must still be reported independently and checked in the full model.",
        },
        "limitations": [
            "This verifies the current polynomial/linear component fit and consumes the separately declared user authority for its original psi_s/psi_m basis identity.",
            "L remains scale-degenerate in a free shape fit; the current value is supplied only by the manufactured-design contract.",
            "No CAD-fit acceptance tolerance is declared, so raw residuals and sampling convergence are reported without promotion to Candidate.",
            "The nominal voltage inverse is evaluated separately; complete time response, P1/P2 transport, and finite three-dimensional fields remain independent validation stages.",
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
    component_assignment = stripe["theory_profile"].get("component_basis_assignment")
    if component_assignment != {
        "set_1": "user_confirmed_scaled_original_psi_s_high_order_basis",
        "set_2": "user_confirmed_scaled_original_psi_m_linear_basis",
        "termwise_original_paper_geometry_basis_identification": True,
        "basis_coefficient_authority": (
            "dual_stripe_l0.dimensionless_paper_target.published_printed_reference_c0_to_c5"
        ),
        "active_response_authority": (
            "analytic_geometry_scale_inverse_then_finite_3d_voltage_calibration"
        ),
    }:
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
