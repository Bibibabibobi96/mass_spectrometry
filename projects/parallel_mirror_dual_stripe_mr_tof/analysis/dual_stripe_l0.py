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
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from scipy.special import roots_legendre

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_width_evaluator,
    dual_stripe_total_path_scale,
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


@lru_cache(maxsize=None)
def gauss_legendre_rule(order: int) -> tuple[np.ndarray, np.ndarray]:
    """Return one cached, read-only Gauss-Legendre rule without dense eigensolves."""
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        raise CandidateContractError("Gauss-Legendre order must be a positive integer")
    nodes, weights = roots_legendre(order)
    nodes.setflags(write=False)
    weights.setflags(write=False)
    return nodes, weights


def theory_drift_y_mm(contract: dict[str, Any], project_y_mm: float) -> float:
    """Map project/SIMION ``y`` to the paper's positive slow coordinate."""
    try:
        stripe_l0 = contract["dual_stripe_l0"]
        mapping = stripe_l0["coordinate_mapping"]
        registration = stripe_l0["theory_function_coordinate_registration"]
        origin = _finite(mapping["origin_project_y_mm"], "theory drift origin")
        sign = _finite(
            mapping["theory_positive_project_y_sign"],
            "theory drift orientation sign",
        )
        function_zero = _finite(
            registration["function_y_zero_project_y_mm"],
            "registered Stripe function origin",
        )
    except (KeyError, TypeError) as error:
        raise CandidateContractError("explicit theory/project drift-coordinate mapping is required") from error
    if registration.get("status") != "registered_from_theory_basis" or origin != function_zero:
        raise CandidateContractError("project y origin conflicts with the registered Stripe function origin")
    if sign not in (-1.0, 1.0):
        raise CandidateContractError("theory drift orientation sign must be +1 or -1")
    return sign * (_finite(project_y_mm, "project drift y") - origin)


def project_y_from_theory_drift_mm(contract: dict[str, Any], theory_y_mm: float) -> float:
    """Invert :func:`theory_drift_y_mm` without hiding direction in signed ``L``."""
    mapping = contract.get("dual_stripe_l0", {}).get("coordinate_mapping")
    if not isinstance(mapping, dict):
        raise CandidateContractError("explicit theory/project drift-coordinate mapping is required")
    origin = _finite(mapping.get("origin_project_y_mm"), "theory drift origin")
    sign = _finite(mapping.get("theory_positive_project_y_sign"), "theory drift orientation sign")
    if sign not in (-1.0, 1.0):
        raise CandidateContractError("theory drift orientation sign must be +1 or -1")
    project_y = origin + sign * _finite(theory_y_mm, "theory drift y")
    # Reuse the forward validator so function-origin inconsistencies fail closed.
    theory_drift_y_mm(contract, project_y)
    return project_y


def derive_native_stripe_branch_validation_sample_count(contract: dict[str, Any]) -> int:
    """Derive branch sampling from the native B-spline topology and contract."""
    try:
        theory = contract["dual_stripe"]["theory_profile"]
        profile = contract["dual_stripe_l0"]["operating_seed_search"]
        samples_per_span = theory["sampling_per_nonzero_knot_span"]
        multiplier = profile["turning_search_sampling_multiplier"]
    except (KeyError, TypeError) as error:
        raise CandidateContractError("native Stripe branch sampling contract is incomplete") from error
    for value, name in (
        (samples_per_span, "native Stripe samples per knot span"),
        (multiplier, "native Stripe branch sampling multiplier"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise CandidateContractError(f"{name} must be a positive integer")

    span_counts: list[int] = []
    for set_name in ("set_1", "set_2"):
        definition = theory.get(set_name)
        if not isinstance(definition, dict):
            raise CandidateContractError(f"native Stripe {set_name} theory profile is missing")
        for edge_name in ("lower_edge", "upper_edge"):
            edge = definition.get(edge_name)
            if not isinstance(edge, dict) or edge.get("basis") != "cubic_bspline":
                continue
            order = edge.get("order")
            knots = edge.get("knots")
            if (
                not isinstance(order, int)
                or isinstance(order, bool)
                or order <= 0
                or not isinstance(knots, list)
                or len(knots) <= 2 * order
            ):
                raise CandidateContractError("native Stripe B-spline topology is invalid")
            knot_values = tuple(_finite(value, "native Stripe knot") for value in knots)
            span_counts.append(
                sum(
                    right > left
                    for left, right in zip(
                        knot_values[order - 1:-order],
                        knot_values[order:1 - order],
                    )
                )
            )
    if not span_counts or min(span_counts) <= 0:
        raise CandidateContractError("native Stripe profiles have no nonzero B-spline spans")
    return max(span_counts) * samples_per_span * multiplier


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


@dataclass(frozen=True)
class NativeStripeSpatialReturnNumerics:
    """Explicit controls for one native-geometry spatial-return branch solve."""

    kappa_derivative_step: float
    initial_ratio_half_width: float
    search_expansion_factor: float
    maximum_search_expansions: int
    branch_validation_sample_count: int
    root_absolute_tolerance: float
    root_relative_tolerance: float
    maximum_root_iterations: int


@dataclass(frozen=True)
class ManufacturedStripeBasisPathScales:
    """Native path scales relative to one explicitly supplied theory basis."""

    drift_length_l_mm: float
    high_order_response_scale_mm: float
    linear_response_scale_mm: float
    reference_relative_action_weight_ratio: float
    active_eta_max: float
    high_order_projection_rms_residual_mm: float
    high_order_eta_coefficients_mm: tuple[float, ...]
    linear_eta_coefficient_mm: float
    geometry_profile_to_total_path_scales: tuple[float, float]


@dataclass(frozen=True)
class NativeStripeSpatialShapeRoot:
    """A mirror-independent spatial-return root of two native path shapes."""

    geometry_input_identity_source: str
    entry_y_mm: float
    turning_y_mm: float
    drift_length_l_mm: float
    drift_direction_sign: float
    reference_relative_action_weight_ratio: float
    reference_kappa_prime: float
    relative_action_weight_ratio: float
    kappa_1: float
    kappa_prime: float
    delta_path_lengths_at_turn_mm: tuple[float, float]
    root_bracket: tuple[float, float]
    searched_parameter_range: tuple[float, float]
    validated_branch_sample_range: tuple[float, float]
    validated_branch_sample_count: int


@dataclass(frozen=True)
class NativeStripeSpatialReturnRoot:
    """A source-energy amplitude and exact biases on one spatial shape root."""

    shape_root: NativeStripeSpatialShapeRoot
    axial_energy_per_charge_v: float
    source_slow_energy_per_charge_v: float
    mirror_reduced_period_mm_per_sqrt_v: float
    mirror_axial_width_w_mm: float
    continuous_oscillation_count: float
    pseudopotential_path_coefficients_v_per_mm: tuple[float, float]
    stripe_biases_v: tuple[float, float]
    turning_pseudopotential_v: float
    source_slow_energy_mismatch_v: float


def _pseudopotential_path_coefficient_v_per_mm(
    axial_energy_per_charge_v: float,
    bias_v: float,
    mirror_reduced_period_mm_per_sqrt_v: float,
) -> float:
    """Return the exact hard-boundary coefficient in ``Phi=a*delta_S``."""
    energy = _finite(axial_energy_per_charge_v, "axial energy per charge")
    bias = _finite(bias_v, "Stripe bias")
    period = _finite(
        mirror_reduced_period_mm_per_sqrt_v,
        "mirror reduced period",
    )
    if energy <= 0.0 or period <= 0.0 or energy - bias <= 0.0:
        raise CandidateContractError("finite-bias Stripe action requires positive transmitted energy and mirror period")
    return -2.0 * (math.sqrt(energy - bias) - math.sqrt(energy)) / period


def _invert_pseudopotential_path_coefficient_v(
    axial_energy_per_charge_v: float,
    coefficient_v_per_mm: float,
    mirror_reduced_period_mm_per_sqrt_v: float,
) -> float:
    """Invert the exact finite-bias action coefficient without linearization."""
    energy = _finite(axial_energy_per_charge_v, "axial energy per charge")
    coefficient = _finite(coefficient_v_per_mm, "pseudopotential path coefficient")
    period = _finite(
        mirror_reduced_period_mm_per_sqrt_v,
        "mirror reduced period",
    )
    if energy <= 0.0 or period <= 0.0 or coefficient == 0.0:
        raise CandidateContractError("finite-bias inverse requires positive energy/period and nonzero response")
    transmitted_root = math.sqrt(energy) - 0.5 * coefficient * period
    if transmitted_root <= 0.0:
        raise CandidateContractError("finite-bias inverse removes Stripe transmission")
    voltage = energy - transmitted_root * transmitted_root
    if voltage == 0.0 or voltage >= energy:
        raise CandidateContractError("finite-bias inverse produced an invalid Stripe bias")
    return voltage


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


def identify_manufactured_basis_path_scales(
    contract: dict[str, Any],
    *,
    basis_coefficients_c0_to_c5: Sequence[float],
) -> ManufacturedStripeBasisPathScales:
    """Project both native paths onto an explicitly supplied manufactured basis.

    This is a geometry-only adapter.  It consumes neither mirror energy or
    period nor source energy or an old voltage point.  Its ratio
    ``lambda_high/lambda_linear`` is therefore a valid mirror-independent
    branch reference for :func:`solve_native_stripe_spatial_shape_branch`.
    """
    coefficients = tuple(
        _finite(value, "manufactured basis coefficient")
        for value in basis_coefficients_c0_to_c5
    )
    if len(coefficients) != 6:
        raise CandidateContractError("manufactured basis projection requires c0..c5")
    linear_basis = coefficients[0]
    high_basis = coefficients[1:]
    if linear_basis == 0.0 or _polynomial_inner_product(high_basis, high_basis, 1.0) == 0.0:
        raise CandidateContractError("manufactured theory bases must both be nonzero")
    l0 = contract.get("dual_stripe_l0")
    if not isinstance(l0, dict):
        raise CandidateContractError("manufactured basis projection requires the Stripe L0 contract")
    length = _finite(
        l0.get("manufactured_design_abs_drift_length_L_mm"),
        "manufactured-design drift length",
    )
    if length <= 0.0:
        raise CandidateContractError("manufactured-design drift length must be positive")

    shape = identify_fixed_cad_component_shapes(contract)
    selected = shape["selected_fit"]
    physical_high = tuple(
        _finite(value, "fitted high-order physical coefficient")
        for value in selected["set_1_coefficients_per_physical_mm_power"]
    )
    if len(physical_high) != 5:
        raise CandidateContractError("manufactured high-order fit must contain five coefficients")
    set_1_path_scale = dual_stripe_total_path_scale(contract, "set_1")
    set_2_path_scale = dual_stripe_total_path_scale(contract, "set_2")
    geometry_high = tuple(
        set_1_path_scale * value * length**power
        for power, value in enumerate(physical_high, start=1)
    )
    geometry_linear = (
        set_2_path_scale
        * _finite(selected["set_2_coefficient_per_physical_mm"], "fitted linear coefficient")
        * length
    )
    active_eta = _finite(shape["active_distance_mm"], "Stripe active distance") / length
    high_denominator = _polynomial_inner_product(high_basis, high_basis, active_eta)
    high_scale = _polynomial_inner_product(geometry_high, high_basis, active_eta) / high_denominator
    linear_scale = geometry_linear / linear_basis
    if high_scale == 0.0 or linear_scale == 0.0:
        raise CandidateContractError("manufactured basis geometry scales must be nonzero")
    high_residual = tuple(
        actual - high_scale * target
        for actual, target in zip(geometry_high, high_basis)
    )
    high_rms = math.sqrt(
        _polynomial_inner_product(high_residual, high_residual, active_eta) / active_eta
    )
    return ManufacturedStripeBasisPathScales(
        drift_length_l_mm=length,
        high_order_response_scale_mm=high_scale,
        linear_response_scale_mm=linear_scale,
        reference_relative_action_weight_ratio=high_scale / linear_scale,
        active_eta_max=active_eta,
        high_order_projection_rms_residual_mm=high_rms,
        high_order_eta_coefficients_mm=geometry_high,
        linear_eta_coefficient_mm=geometry_linear,
        geometry_profile_to_total_path_scales=(set_1_path_scale, set_2_path_scale),
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
    ``L``.  After removing the registered function-origin baselines, the exact
    hard-boundary shape relation is

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

    basis_scales = identify_manufactured_basis_path_scales(
        contract,
        basis_coefficients_c0_to_c5=coefficients,
    )

    l0 = contract.get("dual_stripe_l0")
    nominal = contract.get("nominal")
    if not isinstance(l0, dict) or not isinstance(nominal, dict):
        raise CandidateContractError("manufactured basis inverse requires Stripe and nominal contracts")
    length = basis_scales.drift_length_l_mm
    width = _finite(mirror_axial_width_w_mm, "mirror-owned axial width W")
    energy = (
        _finite(axial_energy_per_charge_v, "selected axial energy per charge")
        if axial_energy_per_charge_v is not None
        else _finite(nominal.get("energy_per_charge_v"), "nominal axial energy per charge")
    )
    phase_contract = resolve_drift_phase_contract(contract)
    target_period_ratio = phase_contract.target_period_ratio
    if (
        length <= 0.0
        or width <= 0.0
        or energy <= 0.0
        or target_period_ratio <= 0.0
    ):
        raise CandidateContractError("manufactured basis inverse inputs must be positive")

    high_scale = basis_scales.high_order_response_scale_mm
    linear_scale = basis_scales.linear_response_scale_mm
    active_eta = basis_scales.active_eta_max
    geometry_high = basis_scales.high_order_eta_coefficients_mm
    geometry_linear = basis_scales.linear_eta_coefficient_mm

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
    tangent_theta = math.sqrt(drift_energy / energy)
    predicted_oscillations = kappa * length / (width * tangent_theta)
    required_width = kappa * length / (target_period_ratio * tangent_theta)
    exact_k_residual = predicted_oscillations - target_period_ratio
    exact_k_tolerance = _finite(
        contract["mirror"]["theory_requirements"]["exact_k_operating_point_selection"]
        ["maximum_abs_numerical_k_residual"],
        "exact-K numerical residual tolerance",
    )
    if exact_k_tolerance <= 0.0:
        raise CandidateContractError("exact-K numerical residual tolerance must be positive")
    exact_k_satisfied = abs(exact_k_residual) <= exact_k_tolerance
    target_band_lower = target_period_ratio - 0.5
    target_band_upper = target_period_ratio + 0.5
    target_band_margin = min(
        predicted_oscillations - target_band_lower,
        target_band_upper - predicted_oscillations,
    )
    assigned_phase_order = math.floor(predicted_oscillations) + 0.5

    def invert_scale(scale: float) -> tuple[float, float, float]:
        # ``drift_energy / scale`` is the coefficient in Phi=a*delta_S.
        # Use the same exact finite-bias inverse as the native-path root.
        path_coefficient = drift_energy / scale
        voltage = _invert_pseudopotential_path_coefficient_v(
            energy,
            path_coefficient,
            width / math.sqrt(energy),
        )
        root = math.sqrt((energy - voltage) / energy)
        response = 1.0 / root
        reconstructed_coefficient = _pseudopotential_path_coefficient_v_per_mm(
            energy,
            voltage,
            width / math.sqrt(energy),
        )
        reconstructed_scale = drift_energy / reconstructed_coefficient
        return voltage, response, reconstructed_scale

    first_voltage, first_h, first_reconstructed = invert_scale(high_scale)
    second_voltage, second_h, second_reconstructed = invert_scale(linear_scale)
    condition = _condition_number_2x2(1.0, 1.0, first_h, second_h)

    high_rms = basis_scales.high_order_projection_rms_residual_mm
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
        "drift_phase_contract": phase_contract.as_dict(),
        "target_drift_period_ratio": target_period_ratio,
        "predicted_continuous_oscillation_count": predicted_oscillations,
        "oscillation_count_residual": exact_k_residual,
        "nominal_center_exact_K_design_equation": {
            "equation": "T_D(theta_0)/T_0=K",
            "target_period_ratio": target_period_ratio,
            "calculated_T_D_over_T_0": predicted_oscillations,
            "residual": exact_k_residual,
            "maximum_abs_numerical_residual": exact_k_tolerance,
            "status": (
                "satisfied_by_current_analytic_inputs"
                if exact_k_satisfied
                else "unsatisfied_by_current_analytic_inputs"
            ),
            "semantics": (
                "The nominal design centre must solve this equality. A later numerical solver "
                "must use a separately declared numerical residual tolerance; the half-integer "
                "interval is not a substitute for this equation."
            ),
        },
        "nominal_center_oscillation_topology": {
            "nearest_opposite_turn_phase_order": assigned_phase_order,
            "target_period_ratio_interval_lower_exclusive": target_band_lower,
            "target_period_ratio_interval_upper_exclusive": target_band_upper,
            "signed_minimum_boundary_margin": target_band_margin,
            "target_period_ratio_interval_passed": target_band_margin > 0.0,
            "semantics": (
                "This classifies only the nominal center trajectory. The same strict interval must "
                "later hold over the complete accepted bundle in the native three-dimensional field."
            ),
        },
        "nominal_axial_energy_per_charge_v": energy,
        "post_acceleration_total_energy_per_charge_v": selected_total_energy,
        "nominal_kappa_1": kappa,
        "nominal_injection_angle_degrees": math.degrees(math.atan(tangent_theta)),
        "derived_drift_kinetic_energy_per_charge_v": drift_energy,
        "derived_fast_reflection_energy_per_charge_v": energy,
        "mirror_axial_width_required_for_exact_K_mm": required_width,
        "mirror_axial_width_residual_mm": width - required_width,
        "geometry_basis_scales_mm": {
            "set_1_high_order": high_scale,
            "set_2_linear": linear_scale,
        },
        "geometry_profile_to_total_path_scales": {
            "set_1": basis_scales.geometry_profile_to_total_path_scales[0],
            "set_2": basis_scales.geometry_profile_to_total_path_scales[1],
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
                else (
                    "center_exact_K_satisfied__nominal_topology_passes"
                    if exact_k_satisfied
                    else "center_exact_K_unsolved__nominal_topology_only_passes"
                )
            ),
            "independent_fixed_inputs": [
                "manufactured L",
                "target K",
                "independent slow-axis energy E_y",
                "selected mirror-axis energy E_z",
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
    nodes, weights = gauss_legendre_rule(order)
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


def solve_native_stripe_spatial_shape_branch(
    path_length_functions: Sequence[Callable[[float], float]],
    *,
    entry_y_mm: float,
    drift_length_l_mm: float,
    drift_direction_sign: float,
    reference_relative_action_weight_ratio: float,
    geometry_input_identity_source: str,
    numerics: NativeStripeSpatialReturnNumerics,
) -> NativeStripeSpatialShapeRoot:
    """Solve ``kappa'(1)=0`` for the relative action weight of two native paths.

    Only the normalized shape
    ``psi=(delta_S1+r*delta_S2)/(delta_S1(1)+r*delta_S2(1))`` is used here.
    Consequently the result is independent of mirror period, energy, source
    energy, and voltage amplitude.  The named reference ratio selects one
    locally connected physical branch; this routine neither scans all branches
    nor imports a paper coefficient, search envelope, or acceptance tolerance.
    """
    if len(path_length_functions) != 2 or any(
        not callable(function) for function in path_length_functions
    ):
        raise CandidateContractError("native spatial return requires exactly two callable path functions")
    if not isinstance(geometry_input_identity_source, str) or not geometry_input_identity_source.strip():
        raise CandidateContractError("native path geometry needs a nonempty identity source")
    if not isinstance(numerics, NativeStripeSpatialReturnNumerics):
        raise CandidateContractError("native spatial return requires named numerical controls")

    entry = _finite(entry_y_mm, "native Stripe entry y")
    length = _finite(drift_length_l_mm, "native Stripe drift length L")
    direction = _finite(drift_direction_sign, "native Stripe drift direction")
    reference_ratio = _finite(
        reference_relative_action_weight_ratio,
        "reference relative action weight ratio",
    )
    derivative_step = _finite(numerics.kappa_derivative_step, "kappa derivative step")
    initial_half_width = _finite(
        numerics.initial_ratio_half_width,
        "initial ratio search half-width",
    )
    expansion = _finite(
        numerics.search_expansion_factor,
        "ratio search expansion factor",
    )
    absolute_tolerance = _finite(
        numerics.root_absolute_tolerance,
        "root absolute tolerance",
    )
    relative_tolerance = _finite(
        numerics.root_relative_tolerance,
        "root relative tolerance",
    )
    integer_controls = (
        numerics.maximum_search_expansions,
        numerics.branch_validation_sample_count,
        numerics.maximum_root_iterations,
    )
    if (
        length <= 0.0
        or isinstance(drift_direction_sign, bool)
        or direction not in (-1.0, 1.0)
        or derivative_step <= 0.0
        or derivative_step >= 1.0
        or initial_half_width <= 0.0
        or expansion <= 1.0
        or absolute_tolerance <= 0.0
        or relative_tolerance <= 0.0
        or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in integer_controls)
        or numerics.branch_validation_sample_count < 2
    ):
        raise CandidateContractError("native spatial-return branch controls are outside their physical domains")

    turning = entry + direction * length
    paths = tuple(path_length_functions)

    def delta_path(index: int, eta: float) -> float:
        coordinate = entry + direction * length * _finite(eta, "native Stripe eta")
        entry_width = _finite(paths[index](entry), f"native Stripe path {index + 1} at entry")
        width = _finite(paths[index](coordinate), f"native Stripe path {index + 1}")
        if entry_width <= 0.0 or width <= 0.0:
            raise CandidateContractError("native Stripe path lengths must remain positive")
        return width - entry_width

    delta_at_turn = (delta_path(0, 1.0), delta_path(1, 1.0))
    if delta_at_turn == (0.0, 0.0):
        raise CandidateContractError("native Stripe paths have no response at the nominal turn")

    def normalized_profile(ratio: float) -> Callable[[float], float]:
        value = _finite(ratio, "relative action weight ratio")
        denominator = delta_at_turn[0] + value * delta_at_turn[1]
        if denominator == 0.0:
            raise CandidateContractError("relative action weights cancel the nominal turning response")

        def psi(eta: float) -> float:
            return (delta_path(0, eta) + value * delta_path(1, eta)) / denominator

        endpoint = psi(1.0)
        for index in range(numerics.branch_validation_sample_count):
            eta = index / numerics.branch_validation_sample_count
            if endpoint - psi(eta) <= 0.0:
                raise CandidateContractError("relative action weights leave the physical return branch")
        return psi

    def residual(ratio: float) -> float:
        return kappa_derivative_at_turn(
            normalized_profile(ratio),
            1.0,
            step=derivative_step,
        )

    reference_residual = residual(reference_ratio)
    valid_samples: dict[float, float] = {reference_ratio: reference_residual}
    half_width = initial_half_width
    selected_bracket: tuple[float, float] | None = None
    for _ in range(numerics.maximum_search_expansions):
        for ratio in (reference_ratio - half_width, reference_ratio + half_width):
            try:
                valid_samples[ratio] = residual(ratio)
            except CandidateContractError:
                pass
        ordered = sorted(valid_samples.items())
        brackets = [
            (left[0], right[0])
            for left, right in zip(ordered, ordered[1:])
            if left[1] == 0.0 or right[1] == 0.0 or left[1] * right[1] < 0.0
        ]
        if brackets:
            selected_bracket = min(
                brackets,
                key=lambda bounds: min(
                    abs(bounds[0] - reference_ratio),
                    abs(bounds[1] - reference_ratio),
                ),
            )
            break
        half_width *= expansion
    if selected_bracket is None:
        raise CandidateContractError("no spatial-return root was bracketed on the selected native branch")

    lower, upper = selected_bracket
    lower_residual = residual(lower)
    upper_residual = residual(upper)
    root = lower if lower_residual == 0.0 else upper if upper_residual == 0.0 else None
    for _ in range(numerics.maximum_root_iterations):
        if root is not None:
            break
        midpoint = 0.5 * (lower + upper)
        midpoint_residual = residual(midpoint)
        tolerance = absolute_tolerance + relative_tolerance * max(1.0, abs(midpoint))
        if midpoint_residual == 0.0 or upper - lower <= 2.0 * tolerance:
            root = midpoint
            break
        if lower_residual * midpoint_residual < 0.0:
            upper = midpoint
            upper_residual = midpoint_residual
        else:
            lower = midpoint
            lower_residual = midpoint_residual
    if root is None:
        raise CandidateContractError("native spatial-return root did not converge within the named iteration limit")

    root_profile = normalized_profile(root)
    root_residual = residual(root)
    kappa = endpoint_regularized_kappa(root_profile)
    sampled_parameters = tuple(sorted(valid_samples))
    return NativeStripeSpatialShapeRoot(
        geometry_input_identity_source=geometry_input_identity_source.strip(),
        entry_y_mm=entry,
        turning_y_mm=turning,
        drift_length_l_mm=length,
        drift_direction_sign=direction,
        reference_relative_action_weight_ratio=reference_ratio,
        reference_kappa_prime=reference_residual,
        relative_action_weight_ratio=root,
        kappa_1=kappa,
        kappa_prime=root_residual,
        delta_path_lengths_at_turn_mm=delta_at_turn,
        root_bracket=(lower, upper),
        searched_parameter_range=(reference_ratio - half_width, reference_ratio + half_width),
        validated_branch_sample_range=(sampled_parameters[0], sampled_parameters[-1]),
        validated_branch_sample_count=len(sampled_parameters),
    )


def materialize_native_stripe_spatial_return_root(
    shape_root: NativeStripeSpatialShapeRoot,
    *,
    source_slow_energy_per_charge_v: float,
    mirror_reduced_period_mm_per_sqrt_v: float,
    axial_energy_per_charge_v: float,
) -> NativeStripeSpatialReturnRoot:
    """Set the source ``E_y`` amplitude and exactly invert both Stripe biases."""
    if not isinstance(shape_root, NativeStripeSpatialShapeRoot):
        raise CandidateContractError("native Stripe voltage materialization requires a spatial shape root")
    slow_energy = _finite(source_slow_energy_per_charge_v, "source slow energy per charge")
    period = _finite(
        mirror_reduced_period_mm_per_sqrt_v,
        "mirror reduced period",
    )
    energy = _finite(axial_energy_per_charge_v, "axial energy per charge")
    if slow_energy <= 0.0 or period <= 0.0 or energy <= 0.0:
        raise CandidateContractError("native Stripe materialization needs positive E_y, E_z, and mirror period")
    first_delta, second_delta = shape_root.delta_path_lengths_at_turn_mm
    ratio = shape_root.relative_action_weight_ratio
    denominator = first_delta + ratio * second_delta
    if denominator == 0.0:
        raise CandidateContractError("native Stripe root has zero turning-response amplitude")
    first_coefficient = slow_energy / denominator
    second_coefficient = ratio * first_coefficient
    biases = (
        _invert_pseudopotential_path_coefficient_v(energy, first_coefficient, period),
        _invert_pseudopotential_path_coefficient_v(energy, second_coefficient, period),
    )
    reconstructed_coefficients = tuple(
        _pseudopotential_path_coefficient_v_per_mm(energy, bias, period)
        for bias in biases
    )
    turning_pseudopotential = (
        reconstructed_coefficients[0] * first_delta
        + reconstructed_coefficients[1] * second_delta
    )
    axial_width = period * math.sqrt(energy)
    tangent_theta = math.sqrt(slow_energy / energy)
    oscillations = (
        shape_root.drift_length_l_mm
        * shape_root.kappa_1
        / (axial_width * tangent_theta)
    )
    return NativeStripeSpatialReturnRoot(
        shape_root=shape_root,
        axial_energy_per_charge_v=energy,
        source_slow_energy_per_charge_v=slow_energy,
        mirror_reduced_period_mm_per_sqrt_v=period,
        mirror_axial_width_w_mm=axial_width,
        continuous_oscillation_count=oscillations,
        pseudopotential_path_coefficients_v_per_mm=reconstructed_coefficients,
        stripe_biases_v=biases,
        turning_pseudopotential_v=turning_pseudopotential,
        source_slow_energy_mismatch_v=turning_pseudopotential - slow_energy,
    )


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

    Width baselines are removed at the registered theory-function origin
    ``y=0`` and the two variations are fitted in physical distance from that
    plane.  This proves
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
    function_origin = project_y_from_theory_drift_mm(contract, 0.0)
    if len(y_span) != 2 or y_span[0] >= y_span[1] or function_origin != y_span[0]:
        raise CandidateContractError(
            "fixed CAD Stripe identification requires the registered function zero "
            "at the low-y active-profile boundary"
        )
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
    first_baseline = first_width(function_origin)
    second_baseline = second_width(function_origin)
    theory_span = tuple(theory_drift_y_mm(contract, value) for value in y_span)
    if min(theory_span) != 0.0 or max(theory_span) <= 0.0:
        raise CandidateContractError("active Stripe span must run from its theory zero to positive y")
    active_length = max(theory_span)

    def fit_at_multiplier(multiplier: int) -> dict[str, Any]:
        interval_count = base_intervals * multiplier
        distances = np.linspace(0.0, active_length, interval_count + 1)
        physical_y = np.asarray([
            project_y_from_theory_drift_mm(contract, float(distance))
            for distance in distances
        ])
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
        "width_baselines_at_function_origin_mm": {"set_1": first_baseline, "set_2": second_baseline},
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


def audit_theory_function_origin_registration(contract: dict[str, Any]) -> dict[str, Any]:
    """Compare origin candidates derived from the active and physical domains.

    Endpoint coincidence alone cannot select the origin because a translated
    fifth-order polynomial remains fifth order.  This diagnostic translates
    the fitted set-1 polynomial to each domain's lower bound, transforms it
    with the frozen manufactured ``L``, and compares coefficient direction
    with the printed high-order theory basis after eliminating one common
    scale.
    """
    registration = contract.get("dual_stripe_l0", {}).get(
        "theory_function_coordinate_registration"
    )
    if not isinstance(registration, dict):
        raise CandidateContractError("theory-function coordinate registration is required")
    try:
        active_domain = tuple(
            _finite(value, "active theory-function domain")
            for value in registration["active_theory_curve_domain_project_y_mm"]
        )
        body_domain = tuple(
            _finite(value, "whole physical-body domain")
            for value in registration["whole_physical_body_domain_project_y_mm"]
        )
        registered_origin = _finite(
            registration["function_y_zero_project_y_mm"], "registered function origin"
        )
        length = _finite(
            contract["dual_stripe_l0"]["manufactured_design_abs_drift_length_L_mm"],
            "manufactured-design drift length",
        )
        printed = tuple(
            _finite(value, "printed high-order basis coefficient")
            for value in contract["dual_stripe_l0"]["dimensionless_paper_target"]
            ["published_printed_reference_c0_to_c5"][1:]
        )
    except (KeyError, TypeError) as error:
        raise CandidateContractError("function-origin audit inputs are incomplete") from error
    if len(active_domain) != 2 or len(body_domain) != 2 or len(printed) != 5 or length <= 0.0:
        raise CandidateContractError("function-origin audit domains or theory basis are invalid")
    candidates = tuple(dict.fromkeys((active_domain[0], body_domain[0])))
    physical_coefficients = tuple(
        _finite(value, "fitted physical polynomial coefficient")
        for value in identify_fixed_cad_component_shapes(contract)["selected_fit"]
        ["set_1_coefficients_per_physical_mm_power"]
    )
    printed_vector = np.asarray(printed, dtype=float)
    printed_norm_sq = float(printed_vector @ printed_vector)
    comparisons = []
    for origin in candidates:
        translated = np.zeros(5, dtype=float)
        for source_power, coefficient in enumerate(physical_coefficients, start=1):
            for target_power in range(1, source_power + 1):
                translated[target_power - 1] += (
                    coefficient
                    * math.comb(source_power, target_power)
                    * origin ** (source_power - target_power)
                    * length ** target_power
                )
        scale = float((translated @ printed_vector) / printed_norm_sq)
        relative_residual = float(
            np.linalg.norm(translated - scale * printed_vector) / np.linalg.norm(translated)
        )
        comparisons.append({
            "hypothesized_function_zero_project_y_mm": origin,
            "relative_coefficient_direction_residual": relative_residual,
            "eliminated_common_scale": scale,
        })
    ordered = sorted(comparisons, key=lambda item: item["relative_coefficient_direction_residual"])
    selected = ordered[0]
    if selected["hypothesized_function_zero_project_y_mm"] != registered_origin:
        raise CandidateContractError("registered Stripe function origin conflicts with coefficient evidence")
    return {
        "schema_version": 1,
        "status": "registered_origin_has_minimum_theory_basis_direction_residual",
        "comparisons": comparisons,
        "selected_function_zero_project_y_mm": registered_origin,
        "runner_up_to_selected_residual_ratio": (
            ordered[1]["relative_coefficient_direction_residual"]
            / selected["relative_coefficient_direction_residual"]
        ),
        "qualification": "coordinate_diagnostic_not_a_solver_acceptance_threshold",
    }


def analyze_dual_stripe_l0(
    contract: dict[str, Any],
    biases_v: Sequence[float],
    *,
    axial_energy_per_charge_v: float | None = None,
) -> dict[str, Any]:
    """Check nominal dual-Stripe response independence and resolved widths.

    ``h_i=sqrt(w0/(w0-v_i))`` follows the project theory.  The matrix
    ``[[1,1],[h1,h2]]`` maps the two nominal spatial contributions to
    ``(psi,g)`` and is the unit-independent conditioning diagnostic.
    """
    nominal_energy = (
        _finite(axial_energy_per_charge_v, "selected axial energy per charge")
        if axial_energy_per_charge_v is not None
        else _finite(contract["nominal"]["energy_per_charge_v"], "nominal.energy_per_charge_v")
    )
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
