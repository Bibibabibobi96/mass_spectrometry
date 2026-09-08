"""Coupled hard-boundary L0 primitives for the fixed-geometry MR-TOF.

The manufactured mirror geometry is fixed while its voltages are adjustable.
The mirror voltage is solved first by the independent mirror L0/L1 workflow.
Its verified period and corresponding ``W`` are downstream inputs here, never
Stripe-dependent mirror-fit coordinates.  This module then keeps the Stripe
baseline action in the complete analyser-period evaluation.

It is deliberately solver-neutral and one-dimensional.  Finite 3-D fields,
the transverse Poincare map, and the prism hand-offs remain separate gates.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    endpoint_regularized_kappa,
    kappa_derivative_at_turn,
    tau_g_derivative_at_turn,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_path_length_evaluator,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    reduced_period,
)
from scipy.optimize import brentq, least_squares
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    TwoPrismTransportObservation,
    prism_turn_handoff_residuals,
)


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class StripeHardBoundary:
    """One non-overlapping physical Stripe response along the nominal ray."""

    bias_v: float
    width_at_y_mm: Callable[[float], float]

    def width_mm(self, y_mm: float) -> float:
        width = _finite(self.width_at_y_mm(_finite(y_mm, "stripe y")), "Stripe width")
        if width <= 0.0:
            raise CandidateContractError("physical Stripe width must be positive")
        return width


def stripes_from_contract(
    contract: dict[str, object],
    biases_v: Sequence[float],
) -> tuple[StripeHardBoundary, StripeHardBoundary]:
    """Bind an explicit voltage trial to the two frozen B-spline widths.

    Geometry contracts do not own an operating point.  In particular, this
    adapter must never fall back to the voltages used only to make a geometry
    review IOB visually distinguishable.
    """
    stripe = contract.get("dual_stripe")
    if not isinstance(stripe, dict):
        raise CandidateContractError("dual Stripe contract is required")
    if len(biases_v) != 2:
        raise CandidateContractError("dual Stripe trial requires exactly two explicit biases")
    first_bias, second_bias = (
        _finite(biases_v[0], "Stripe trial set-1 bias"),
        _finite(biases_v[1], "Stripe trial set-2 bias"),
    )

    first_width = compile_dual_stripe_path_length_evaluator(contract, "set_1")
    second_width = compile_dual_stripe_path_length_evaluator(contract, "set_2")
    return StripeHardBoundary(first_bias, first_width), StripeHardBoundary(second_bias, second_width)


@dataclass(frozen=True)
class CoupledDriftState:
    """All slow-drift scalars derived from one simultaneous voltage trial."""

    mirror_reduced_period_mm_per_sqrt_v: float
    coupled_reduced_period_mm_per_sqrt_v: float
    axial_width_w_mm: float
    drift_length_l_mm: float
    turning_pseudopotential_v: float
    nominal_injection_angle_rad: float
    nominal_kappa_1: float
    paper_normalized_oscillation_count: float
    predicted_oscillation_count: float
    target_oscillation_count_residual: float
    response_h_factors: tuple[float, ...]


@dataclass(frozen=True)
class DimensionlessPsiGPolynomialFit:
    """Instance-specific polynomial identification on one derived drift length."""

    eta_max: float
    sample_count: int
    polynomial_degree: int
    psi_coefficients_by_power: tuple[float, ...]
    g_coefficients_by_power: tuple[float, ...]
    psi_at_nominal_turn: float
    g_at_nominal_turn: float
    psi_fit_at_nominal_turn: float
    g_fit_at_nominal_turn: float
    psi_rms_fit_residual: float
    psi_max_abs_fit_residual: float
    g_rms_fit_residual: float
    g_max_abs_fit_residual: float


@dataclass(frozen=True)
class ConstraintClassification:
    """Rank-based determination state for a declared nonlinear solve at one trial."""

    unknown_count: int
    declared_constraint_count: int
    independent_constraint_rank: int | None
    augmented_rank: int | None
    nullity: int | None
    redundant_constraint_count: int | None
    singular_values: tuple[float, ...] | None
    condition_number_2: float | None
    scaled_irreducible_residual_norm_2: float | None
    scaled_residual_norm_2: float | None
    status: str
    reason: str


@dataclass(frozen=True)
class JointL0Trial:
    """One downstream Stripe trial consuming a fixed mirror-theory design."""

    mirror_design: MirrorL0Design
    energy_points_v: tuple[float, float, float]
    stripes: tuple[StripeHardBoundary, ...]
    stripe_entry_y_mm: float
    nominal_turning_y_mm: float
    target_oscillation_count: int
    time_platform_eta_nodes: tuple[float, ...]
    kappa_derivative_step: float
    time_platform_derivative_step: float
    energy_derivative_step_v: float
    prism_target_turn_y_mm: float | None = None
    prism_target_slow_kinetic_energy_per_charge_v: float | None = None
    particle_mass_th: float | None = None
    charge_state: int | None = None
    two_prism_transport_observation: TwoPrismTransportObservation | None = None


@dataclass(frozen=True)
class JointL0ResidualReport:
    """Named residuals and derived state for one complete L0/L1 trial."""

    residuals: tuple[tuple[str, float], ...]
    drift_state: CoupledDriftState
    coupled_reduced_periods_mm_per_sqrt_v: tuple[float, float, float]

    def residual_vector(self) -> tuple[float, ...]:
        return tuple(value for _name, value in self.residuals)

    def residual_names(self) -> tuple[str, ...]:
        return tuple(name for name, _value in self.residuals)


def classify_constraint_system(
    unknown_names: Sequence[str],
    constraint_names: Sequence[str],
    *,
    jacobian_rows: Sequence[Sequence[float]] | None = None,
    residuals: Sequence[float] | None = None,
    parameter_scales: Sequence[float] | None = None,
    residual_scales: Sequence[float] | None = None,
    relative_rank_tolerance: float = 1e-10,
    compatibility_tolerance: float = 1e-8,
) -> ConstraintClassification:
    """Classify a locally linearized solve with a scaled SVD.

    Without a numerical Jacobian, the result is deliberately ``rank_unverified``.
    The SVD is applied to ``diag(1/r_scale) J diag(p_scale)``.  When a residual
    is supplied, its projection on the Jacobian's left null space is the part
    that no local parameter correction can remove.  This distinguishes a
    square determined system from an overdetermined but consistent system and
    from a locally incompatible one.
    """
    unknowns = tuple(unknown_names)
    constraints = tuple(constraint_names)
    if not unknowns or not constraints or any(not isinstance(name, str) or not name for name in unknowns + constraints):
        raise CandidateContractError("constraint classification needs nonempty named unknowns and constraints")
    if len(set(unknowns)) != len(unknowns) or len(set(constraints)) != len(constraints):
        raise CandidateContractError("constraint classification names must be unique")
    if jacobian_rows is None:
        return ConstraintClassification(
            len(unknowns), len(constraints), None, None, None, None, None, None,
            None, None, "rank_unverified",
            "a numerical Jacobian is required before determination can be claimed",
        )
    if len(jacobian_rows) != len(constraints):
        raise CandidateContractError("Jacobian must have one row per declared constraint")
    matrix = np.asarray(jacobian_rows, dtype=float)
    if matrix.shape != (len(constraints), len(unknowns)) or not np.all(np.isfinite(matrix)):
        raise CandidateContractError("each finite Jacobian row must have one element per declared unknown")
    p_scales = np.ones(len(unknowns)) if parameter_scales is None else np.asarray(parameter_scales, dtype=float)
    r_scales = np.ones(len(constraints)) if residual_scales is None else np.asarray(residual_scales, dtype=float)
    if p_scales.shape != (len(unknowns),) or r_scales.shape != (len(constraints),):
        raise CandidateContractError("classification scales must match the named parameters and constraints")
    if not np.all(np.isfinite(p_scales)) or not np.all(np.isfinite(r_scales)) or np.any(p_scales <= 0.0) or np.any(r_scales <= 0.0):
        raise CandidateContractError("classification scales must be finite and positive")
    rank_tolerance = _finite(relative_rank_tolerance, "relative rank tolerance")
    consistency_tolerance = _finite(compatibility_tolerance, "compatibility tolerance")
    if not 0.0 < rank_tolerance < 1.0 or consistency_tolerance < 0.0:
        raise CandidateContractError("rank and compatibility tolerances are invalid")
    scaled_matrix = matrix * p_scales[np.newaxis, :] / r_scales[:, np.newaxis]
    left_vectors, singular_values, _right_vectors = np.linalg.svd(scaled_matrix, full_matrices=True)
    threshold = rank_tolerance * (float(singular_values[0]) if singular_values.size else 1.0)
    rank = int(np.count_nonzero(singular_values > threshold))
    nullity = len(unknowns) - rank
    redundancy = len(constraints) - rank
    finite_singular_values = singular_values[singular_values > threshold]
    condition = (
        float(finite_singular_values[0] / finite_singular_values[-1])
        if rank == len(unknowns) and finite_singular_values.size
        else math.inf
    )
    augmented_rank: int | None = None
    irreducible_norm: float | None = None
    scaled_residual_norm: float | None = None
    if residuals is not None:
        if len(residuals) != len(constraints):
            raise CandidateContractError("residual vector must have one value per declared constraint")
        scaled_residual = np.asarray([_finite(value, "residual") for value in residuals]) / r_scales
        scaled_residual_norm = float(np.linalg.norm(scaled_residual))
        left_null = left_vectors[:, rank:]
        irreducible_norm = float(np.linalg.norm(left_null.T @ scaled_residual))
        augmented_rank = rank + int(irreducible_norm > consistency_tolerance)
        if irreducible_norm > consistency_tolerance:
            return ConstraintClassification(
                len(unknowns), len(constraints), rank, augmented_rank, nullity, redundancy,
                tuple(float(value) for value in singular_values), condition,
                irreducible_norm, scaled_residual_norm, "locally_incompatible",
                "the scaled residual has a component outside the local Jacobian column space",
            )
    if rank < len(unknowns):
        status = "underdetermined"
        reason = "independent constraints leave one or more local physical degrees of freedom"
    elif len(constraints) == len(unknowns):
        status = "square_exact"
        reason = "a square full-rank local system determines every declared physical degree of freedom"
    else:
        status = "overdetermined_consistent"
        reason = "the full-column-rank overdetermined system is locally consistent within the declared scaled tolerance"
    return ConstraintClassification(
        len(unknowns), len(constraints), rank, augmented_rank, nullity, redundancy,
        tuple(float(value) for value in singular_values), condition,
        irreducible_norm, scaled_residual_norm, status, reason,
    )


def require_exactly_determined(classification: ConstraintClassification) -> None:
    """Refuse publication of a solved parameter set unless its rank closes."""
    if classification.status not in {"square_exact", "overdetermined_consistent"}:
        raise CandidateContractError(f"joint solve cannot publish remaining parameters: {classification.status}: {classification.reason}")


def evaluate_joint_l0_trial(trial: JointL0Trial) -> JointL0ResidualReport:
    """Evaluate all declared analytic L0/L1 residuals at one physical trial.

    This calculation deliberately has no optimizer or fallback values.  The
    caller supplies the physical Stripe entry and nominal turning sections;
    P1/P2 shooting owns their eventual determination.  The three-point
    residual includes the two Stripe baseline actions at *each* energy point.
    """
    energies = tuple(_finite(value, "joint energy point") for value in trial.energy_points_v)
    if len(energies) != 3 or tuple(sorted(energies)) != energies:
        raise CandidateContractError("joint L0 trial needs three ordered energy points")
    if len(trial.stripes) != 2:
        raise CandidateContractError("joint L0 trial needs exactly the two theoretical Stripe responses")
    periods = []
    for energy in energies:
        mirror_period = reduced_period(energy, trial.mirror_design)
        baseline_widths = tuple(stripe.width_mm(trial.stripe_entry_y_mm) for stripe in trial.stripes)
        periods.append(coupled_reduced_period_mm_per_sqrt_v(
            mirror_period, energy, baseline_widths, tuple(stripe.bias_v for stripe in trial.stripes),
        ))
    state = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energies[1], trial.mirror_design),
        energy_per_charge_v=energies[1],
        target_oscillation_count=trial.target_oscillation_count,
        stripes=trial.stripes,
        entry_y_mm=trial.stripe_entry_y_mm,
        turning_y_mm=trial.nominal_turning_y_mm,
    )
    kappa_step = _finite(trial.kappa_derivative_step, "kappa derivative step")
    time_step = _finite(trial.time_platform_derivative_step, "time-platform derivative step")
    if min(kappa_step, time_step) <= 0.0 or 1.0 - max(kappa_step, time_step) <= 0.0:
        raise CandidateContractError("dimensionless derivative steps must bracket the nominal turning point")
    kappa_prime = spatial_return_kappa_derivative_residual(
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energies[1], trial.mirror_design),
        energy_per_charge_v=energies[1],
        stripes=trial.stripes,
        entry_y_mm=trial.stripe_entry_y_mm,
        nominal_turning_y_mm=trial.nominal_turning_y_mm,
        derivative_step=kappa_step,
    )
    time_residuals = time_platform_derivative_residuals(
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energies[1], trial.mirror_design),
        energy_per_charge_v=energies[1], stripes=trial.stripes,
        entry_y_mm=trial.stripe_entry_y_mm, nominal_turning_y_mm=trial.nominal_turning_y_mm,
        eta_turn_nodes=trial.time_platform_eta_nodes, derivative_step=time_step,
    )
    energy_step = _finite(trial.energy_derivative_step_v, "energy derivative step")
    if energy_step <= 0.0 or energies[0] - energy_step <= 0.0:
        raise CandidateContractError("energy derivative step must be positive and remain inside the physical energy domain")
    baseline_widths = tuple(stripe.width_mm(trial.stripe_entry_y_mm) for stripe in trial.stripes)
    biases = tuple(stripe.bias_v for stripe in trial.stripes)
    energy_slopes = tuple(
        coupled_normalized_period_slope_at_energy(
            trial.mirror_design,
            energy,
            baseline_widths,
            biases,
            energy_step,
        )
        for energy in energies
    )
    residuals = [
        (f"full_analyser_period_slope_at_{energy:.12g}V", slope)
        for energy, slope in zip(energies, energy_slopes)
    ]
    residuals.extend([
        ("target_oscillation_count", state.target_oscillation_count_residual),
        ("spatial_return_kappa_prime", kappa_prime),
    ])
    residuals.extend((f"time_platform_tau_g_prime_eta_{node:.12g}", value) for node, value in zip(trial.time_platform_eta_nodes, time_residuals))
    transport_values = (
        trial.prism_target_turn_y_mm,
        trial.prism_target_slow_kinetic_energy_per_charge_v,
        trial.particle_mass_th,
        trial.charge_state,
        trial.two_prism_transport_observation,
    )
    if any(value is not None for value in transport_values):
        if any(value is None for value in transport_values):
            raise CandidateContractError("joint P1/P2 trial needs turn y, slow energy, particle identity, and observed transport together")
        residuals.extend(prism_turn_handoff_residuals(
            trial.two_prism_transport_observation,
            target_turn_y_mm=trial.prism_target_turn_y_mm,
            target_slow_kinetic_energy_per_charge_v=trial.prism_target_slow_kinetic_energy_per_charge_v,
            particle_mass_th=trial.particle_mass_th,
            charge_state=trial.charge_state,
        ))
    return JointL0ResidualReport(tuple(residuals), state, tuple(periods))


def finite_difference_joint_jacobian(
    variable_names: Sequence[str],
    parameter_values: Sequence[float],
    parameter_steps: Sequence[float],
    trial_from_parameters: Callable[[tuple[float, ...]], JointL0Trial],
    *,
    parameter_scales: Sequence[float] | None = None,
    residual_scales: Sequence[float] | None = None,
    selected_residual_names: Sequence[str] | None = None,
    relative_rank_tolerance: float = 1e-10,
    compatibility_tolerance: float = 1e-8,
) -> tuple[JointL0ResidualReport, ConstraintClassification]:
    """Differentiate the actual joint residual vector and classify its rank.

    Infeasible perturbations are intentionally errors: replacing them by an
    arbitrary penalty would make a rank statement depend on optimizer policy
    rather than on the declared physics.
    """
    names = tuple(variable_names)
    values = tuple(_finite(value, "joint parameter") for value in parameter_values)
    steps = tuple(_finite(value, "joint parameter step") for value in parameter_steps)
    if len(names) != len(values) or len(steps) != len(values) or any(step <= 0.0 for step in steps):
        raise CandidateContractError("joint Jacobian needs matched named values and positive central-difference steps")
    center = evaluate_joint_l0_trial(trial_from_parameters(values))
    available_names = center.residual_names()
    selected_names = (
        tuple(selected_residual_names)
        if selected_residual_names is not None else available_names
    )
    if not selected_names or len(set(selected_names)) != len(selected_names):
        raise CandidateContractError("joint Jacobian residual selection must be nonempty and unique")
    missing = [name for name in selected_names if name not in available_names]
    if missing:
        raise CandidateContractError(
            f"joint Jacobian selected unknown residuals: {', '.join(missing)}"
        )
    selected_indices = tuple(available_names.index(name) for name in selected_names)
    rows = [[] for _ in selected_names]
    for index, step in enumerate(steps):
        lower = list(values)
        upper = list(values)
        lower[index] -= step
        upper[index] += step
        lower_result = evaluate_joint_l0_trial(trial_from_parameters(tuple(lower)))
        upper_result = evaluate_joint_l0_trial(trial_from_parameters(tuple(upper)))
        if lower_result.residual_names() != available_names or upper_result.residual_names() != available_names:
            raise CandidateContractError("joint residual identity changed across a Jacobian perturbation")
        lower_values = lower_result.residual_vector()
        upper_values = upper_result.residual_vector()
        for row, index in zip(rows, selected_indices):
            row.append((upper_values[index] - lower_values[index]) / (2.0 * step))
    center_values = center.residual_vector()
    return center, classify_constraint_system(
        names,
        selected_names,
        jacobian_rows=rows,
        residuals=tuple(center_values[index] for index in selected_indices),
        parameter_scales=parameter_scales,
        residual_scales=residual_scales,
        relative_rank_tolerance=relative_rank_tolerance,
        compatibility_tolerance=compatibility_tolerance,
    )


def solve_exactly_determined_joint_l0(
    variable_names: Sequence[str],
    initial_values: Sequence[float],
    lower_bounds: Sequence[float],
    upper_bounds: Sequence[float],
    jacobian_steps: Sequence[float],
    residual_scales: dict[str, float],
    residual_tolerances: dict[str, float],
    maximum_function_evaluations: int,
    trial_from_parameters: Callable[[tuple[float, ...]], JointL0Trial],
) -> tuple[JointL0ResidualReport, ConstraintClassification, tuple[float, ...]]:
    """Solve only an explicitly bounded, scaled, and exactly determined problem.

    There are intentionally no default bounds, weights, tolerances, iteration
    budget, or acceptance thresholds.  A least-squares iterate is merely a search aid;
    it is rejected unless the physical Jacobian is exactly determined and each
    unscaled named residual satisfies the caller's frozen tolerance.
    """
    names = tuple(variable_names)
    initial = tuple(_finite(value, "joint initial parameter") for value in initial_values)
    lower = tuple(_finite(value, "joint lower bound") for value in lower_bounds)
    upper = tuple(_finite(value, "joint upper bound") for value in upper_bounds)
    steps = tuple(_finite(value, "joint Jacobian step") for value in jacobian_steps)
    if not names or len(set(names)) != len(names) or len(initial) != len(names) or len(lower) != len(names) or len(upper) != len(names):
        raise CandidateContractError("joint solve needs unique named variables and matched initial/bound vectors")
    if any(not low < value < high for low, value, high in zip(lower, initial, upper)):
        raise CandidateContractError("each joint initial value must lie strictly inside its explicit bounds")
    if any(step <= 0.0 for step in steps) or len(steps) != len(names):
        raise CandidateContractError("joint solve needs a positive Jacobian step for every variable")
    if not isinstance(maximum_function_evaluations, int) or isinstance(maximum_function_evaluations, bool) or maximum_function_evaluations <= 0:
        raise CandidateContractError("joint solve needs an explicit positive maximum function-evaluation count")
    initial_report = evaluate_joint_l0_trial(trial_from_parameters(initial))
    residual_names = initial_report.residual_names()
    if set(residual_scales) != set(residual_names) or set(residual_tolerances) != set(residual_names):
        raise CandidateContractError("joint solve needs one explicit scale and tolerance for every named residual")
    scales = tuple(_finite(residual_scales[name], f"residual scale {name}") for name in residual_names)
    tolerances = tuple(_finite(residual_tolerances[name], f"residual tolerance {name}") for name in residual_names)
    if any(value <= 0.0 for value in scales) or any(value < 0.0 for value in tolerances):
        raise CandidateContractError("joint residual scales must be positive and tolerances non-negative")

    def scaled_residual(values) -> tuple[float, ...]:
        report = evaluate_joint_l0_trial(trial_from_parameters(tuple(float(value) for value in values)))
        if report.residual_names() != residual_names:
            raise CandidateContractError("joint residual identity changed during optimization")
        return tuple(value / scale for value, scale in zip(report.residual_vector(), scales))

    result = least_squares(
        scaled_residual,
        initial,
        bounds=(lower, upper),
        max_nfev=maximum_function_evaluations,
    )
    solved = tuple(float(value) for value in result.x)
    report, classification = finite_difference_joint_jacobian(
        names,
        solved,
        steps,
        trial_from_parameters,
        parameter_scales=tuple(high - low for low, high in zip(lower, upper)),
        residual_scales=scales,
    )
    require_exactly_determined(classification)
    failures = [
        (name, value, tolerance)
        for name, value, tolerance in zip(report.residual_names(), report.residual_vector(), tolerances)
        if abs(value) > tolerance
    ]
    if failures:
        details = ", ".join(f"{name}={value:.6g} exceeds {tolerance:.6g}" for name, value, tolerance in failures)
        raise CandidateContractError(f"joint solve did not meet its explicit residual tolerances: {details}")
    if not result.success:
        raise CandidateContractError(f"joint optimizer did not converge: {result.message}")
    return report, classification, solved


def reduced_action_delta_mm_sqrt_v(energy_per_charge_v: float, bias_v: float, width_mm: float) -> float:
    """Return the hard-boundary action perturbation after common factors cancel.

    It is ``2 S (sqrt(E-v)-sqrt(E))`` in ``mm sqrt(V)``.  The common
    ``sqrt(2mq)`` factor has been removed consistently from action and period.
    """
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    bias = _finite(bias_v, "Stripe bias_v")
    width = _finite(width_mm, "Stripe width_mm")
    if energy <= 0.0 or width <= 0.0:
        raise CandidateContractError("Stripe energy and physical width must be positive")
    if energy - bias <= 0.0:
        raise CandidateContractError("Stripe bias removes nominal hard-boundary transmission")
    return 2.0 * width * (math.sqrt(energy - bias) - math.sqrt(energy))


def reduced_action_energy_derivative_mm_per_sqrt_v(energy_per_charge_v: float, bias_v: float, width_mm: float) -> float:
    """Return the matching reduced-period correction ``d(delta action)/dE``."""
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    bias = _finite(bias_v, "Stripe bias_v")
    width = _finite(width_mm, "Stripe width_mm")
    if energy <= 0.0 or width <= 0.0 or energy - bias <= 0.0:
        raise CandidateContractError("Stripe hard-boundary period correction is outside transmission")
    return width * (1.0 / math.sqrt(energy - bias) - 1.0 / math.sqrt(energy))


def coupled_reduced_period_mm_per_sqrt_v(
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    baseline_widths_mm: Sequence[float],
    biases_v: Sequence[float],
) -> float:
    """Add both physical Stripe baseline actions to a same-trial mirror period."""
    mirror_period = _finite(mirror_reduced_period_mm_per_sqrt_v, "mirror reduced period")
    if mirror_period <= 0.0 or len(baseline_widths_mm) != len(biases_v) or not baseline_widths_mm:
        raise CandidateContractError("coupled period needs a positive mirror period and matched nonempty Stripe responses")
    period = mirror_period + sum(
        reduced_action_energy_derivative_mm_per_sqrt_v(energy_per_charge_v, bias, width)
        for bias, width in zip(biases_v, baseline_widths_mm)
    )
    if period <= 0.0:
        raise CandidateContractError("Stripe baseline action makes the coupled period non-positive")
    return period


def adiabatic_fast_phase_oscillation_count(
    *,
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    turning_y_mm: float,
    initial_panels: int = 32,
    max_refinements: int = 12,
    relative_tolerance: float = 1e-8,
) -> float:
    """Integrate the complete out-and-back fast phase with Stripe biases on.

    T0 remains the bare-mirror period.  The integrand instead uses
    Tz(E,y)=T0(E)+partial_E DeltaJ_stripe(E,y) at every slow coordinate.
    Endpoint substitution eta=1-u^2 removes the slow-turn singularity.
    The resulting dimensionless value counts complete fast oscillations and
    reduces to the paper's L*kappa/(W*sin(theta)) only when the local period
    is independent of y.
    """
    mirror_period = _finite(mirror_reduced_period_mm_per_sqrt_v, "mirror reduced period")
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    entry = _finite(entry_y_mm, "entry_y_mm")
    turning = _finite(turning_y_mm, "turning_y_mm")
    tolerance = _finite(relative_tolerance, "fast-phase quadrature tolerance")
    if mirror_period <= 0.0 or energy <= 0.0 or turning == entry:
        raise CandidateContractError("fast-phase integral needs positive mirror physics and a nonzero drift interval")
    if not isinstance(initial_panels, int) or isinstance(initial_panels, bool) or initial_panels < 2:
        raise CandidateContractError("fast-phase integral needs at least two initial panels")
    if not isinstance(max_refinements, int) or isinstance(max_refinements, bool) or max_refinements < 1:
        raise CandidateContractError("fast-phase integral needs a positive refinement count")
    if not 0.0 < tolerance < 1.0:
        raise CandidateContractError("fast-phase quadrature tolerance must lie between zero and one")
    direction = 1.0 if turning > entry else -1.0
    length = abs(turning - entry)
    turning_phi = _pseudopotential_difference_v(energy, mirror_period, stripes, entry, turning)
    if not 0.0 < turning_phi < energy:
        raise CandidateContractError("fast-phase integral needs a physical slow turning branch")

    def physical_y(eta: float) -> float:
        return entry + direction * length * eta

    def one_way_energy(y_mm: float) -> float:
        value = turning_phi - _pseudopotential_difference_v(
            energy, mirror_period, stripes, entry, y_mm,
        )
        if value <= 0.0:
            raise CandidateContractError("fast-phase integral left the physical slow branch")
        return value

    def local_period(y_mm: float) -> float:
        return coupled_reduced_period_mm_per_sqrt_v(
            mirror_period,
            energy,
            tuple(stripe.width_mm(y_mm) for stripe in stripes),
            tuple(stripe.bias_v for stripe in stripes),
        )

    previous: float | None = None
    for refinement in range(max_refinements):
        order = initial_panels * (2 ** refinement)
        nodes, weights = np.polynomial.legendre.leggauss(order)
        integral = 0.0
        for node, weight in zip(nodes, weights):
            u = 0.5 * (float(node) + 1.0)
            eta = 1.0 - u * u
            y_mm = physical_y(eta)
            integrand = 2.0 * u / (local_period(y_mm) * math.sqrt(one_way_energy(y_mm)))
            integral += float(weight) * integrand
        current = length * 0.5 * integral
        if previous is not None and abs(current - previous) <= tolerance * max(1.0, abs(current)):
            return current
        previous = current
    raise CandidateContractError("endpoint-regularized fast-phase integral did not converge")


def coupled_normalized_period_slope_at_energy(
    mirror_design: MirrorL0Design,
    energy_per_charge_v: float,
    baseline_widths_mm: Sequence[float],
    biases_v: Sequence[float],
    derivative_step_v: float,
) -> float:
    """Return the local normalized full-analyser period slope at one energy.

    The same fixed hardware widths and Stripe biases are used at the lower,
    centre, and upper energy.  This is a local derivative at each declared
    energy node, not a replacement by two endpoint-to-centre period
    differences.
    """
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    step = _finite(derivative_step_v, "full-analyser period derivative step")
    if step <= 0.0 or energy - step <= 0.0:
        raise CandidateContractError("full-analyser period derivative step leaves the positive energy domain")

    def period(node: float) -> float:
        return coupled_reduced_period_mm_per_sqrt_v(
            reduced_period(node, mirror_design),
            node,
            baseline_widths_mm,
            biases_v,
        )

    center = period(energy)
    return (period(energy + step) - period(energy - step)) / (2.0 * step * center)


def _pseudopotential_difference_v(
    energy_per_charge_v: float,
    mirror_period_mm_per_sqrt_v: float,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    y_mm: float,
) -> float:
    """Return ``Phi(y)-Phi(entry)`` from the exact Stripe action difference."""
    action_change = sum(
        reduced_action_delta_mm_sqrt_v(energy_per_charge_v, stripe.bias_v, stripe.width_mm(y_mm))
        - reduced_action_delta_mm_sqrt_v(energy_per_charge_v, stripe.bias_v, stripe.width_mm(entry_y_mm))
        for stripe in stripes
    )
    return -action_change / mirror_period_mm_per_sqrt_v


def derive_turning_y_from_entry_direction(
    *,
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    entry_unit_direction_project: Sequence[float],
    search_end_y_mm: float,
    sample_count: int,
) -> float:
    """Find the first slow-drift turning section implied by the injected ray.

    The fast/slow theory supplies the slow energy as
    ``E*(v_y/|v|)^2``.  A physical turning point is the first section reached
    along the signed y direction where the exact coupled Stripe
    pseudopotential difference equals that energy.  Search limits and sample
    count are explicit caller-owned numerical contract fields; neither a CAD
    box nor a published reference length is substituted here.
    """
    mirror_period = _finite(mirror_reduced_period_mm_per_sqrt_v, "mirror reduced period")
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    entry = _finite(entry_y_mm, "entry_y_mm")
    search_end = _finite(search_end_y_mm, "turning search end_y_mm")
    direction = tuple(_finite(value, "entry direction") for value in entry_unit_direction_project)
    if len(direction) != 3 or mirror_period <= 0.0 or energy <= 0.0 or search_end == entry:
        raise CandidateContractError("turning-point derivation needs a nonzero three-component ray, positive energy/period, and nonzero search interval")
    norm = math.sqrt(sum(value * value for value in direction))
    if norm <= 0.0 or direction[1] == 0.0:
        raise CandidateContractError("turning-point derivation needs a nonzero y-directed entry ray")
    if (search_end - entry) * direction[1] <= 0.0:
        raise CandidateContractError("turning search interval must follow the injected y direction")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 2:
        raise CandidateContractError("turning-point derivation needs an explicit integer sample count of at least two")
    slow_energy = energy * (direction[1] / norm) ** 2
    if not 0.0 < slow_energy < energy:
        raise CandidateContractError("entry ray must have a nonzero, non-total slow y energy")

    def residual(y_mm: float) -> float:
        return _pseudopotential_difference_v(energy, mirror_period, stripes, entry, y_mm) - slow_energy

    previous_y, previous_value = entry, residual(entry)
    for index in range(1, sample_count + 1):
        current_y = entry + (search_end - entry) * index / sample_count
        current_value = residual(current_y)
        if current_value == 0.0:
            return current_y
        if previous_value * current_value < 0.0:
            return brentq(residual, previous_y, current_y)
        previous_y, previous_value = current_y, current_value
    raise CandidateContractError("no physical slow-drift turning point lies in the explicit search interval")


def derive_coupled_drift_state_from_entry_direction(
    *,
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    target_oscillation_count: int,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    entry_unit_direction_project: Sequence[float],
    search_end_y_mm: float,
    sample_count: int,
) -> CoupledDriftState:
    """Derive the turning section from one injected ray, then evaluate L/W/K."""
    turning = derive_turning_y_from_entry_direction(
        mirror_reduced_period_mm_per_sqrt_v=mirror_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy_per_charge_v,
        stripes=stripes,
        entry_y_mm=entry_y_mm,
        entry_unit_direction_project=entry_unit_direction_project,
        search_end_y_mm=search_end_y_mm,
        sample_count=sample_count,
    )
    return derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=mirror_reduced_period_mm_per_sqrt_v,
        energy_per_charge_v=energy_per_charge_v,
        target_oscillation_count=target_oscillation_count,
        stripes=stripes,
        entry_y_mm=entry_y_mm,
        turning_y_mm=turning,
    )


def _time_response_g(
    energy_per_charge_v: float,
    mirror_period_mm_per_sqrt_v: float,
    turning_pseudopotential_v: float,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    y_mm: float,
) -> float:
    """Return the theory's normalized exact hard-boundary ``g`` response."""
    derivative_change = sum(
        reduced_action_energy_derivative_mm_per_sqrt_v(energy_per_charge_v, stripe.bias_v, stripe.width_mm(y_mm))
        - reduced_action_energy_derivative_mm_per_sqrt_v(energy_per_charge_v, stripe.bias_v, stripe.width_mm(entry_y_mm))
        for stripe in stripes
    )
    return 2.0 * energy_per_charge_v * derivative_change / (
        mirror_period_mm_per_sqrt_v * turning_pseudopotential_v
    )


def fit_dimensionless_psi_g_profiles(
    *,
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    nominal_turning_y_mm: float,
    eta_max: float,
    polynomial_degree: int,
    sample_count: int,
) -> DimensionlessPsiGPolynomialFit:
    """Identify the active instance's dimensionless ``psi`` and ``g`` coefficients.

    The fit is constrained to have zero constant term because both responses
    are physical differences from the Stripe entrance.  ``L`` and the
    normalization are derived from the supplied nominal physical turn; no
    paper coefficient or independent drift-length value enters this report.
    """
    mirror_period = _finite(mirror_reduced_period_mm_per_sqrt_v, "mirror reduced period")
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    entry = _finite(entry_y_mm, "entry_y_mm")
    nominal_turn = _finite(nominal_turning_y_mm, "nominal_turning_y_mm")
    maximum_eta = _finite(eta_max, "dimensionless profile eta maximum")
    if mirror_period <= 0.0 or energy <= 0.0 or maximum_eta < 1.0:
        raise CandidateContractError("dimensionless profile fit needs positive physics and eta_max at least one")
    if not isinstance(polynomial_degree, int) or isinstance(polynomial_degree, bool) or polynomial_degree < 1:
        raise CandidateContractError("dimensionless profile polynomial degree must be a positive integer")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count <= polynomial_degree:
        raise CandidateContractError("dimensionless profile fit needs more samples than coefficients")
    length = abs(nominal_turn - entry)
    if length <= 0.0 or len(stripes) != 2:
        raise CandidateContractError("dimensionless profile fit needs a nonzero turn and two Stripe responses")
    direction = 1.0 if nominal_turn > entry else -1.0
    turning_phi = _pseudopotential_difference_v(energy, mirror_period, stripes, entry, nominal_turn)
    if turning_phi <= 0.0:
        raise CandidateContractError("dimensionless profile nominal turn must have positive pseudopotential")
    eta_values = np.linspace(0.0, maximum_eta, sample_count)
    matrix = np.column_stack([eta_values**power for power in range(1, polynomial_degree + 1)])
    psi_values = np.asarray([
        _pseudopotential_difference_v(
            energy, mirror_period, stripes, entry, entry + direction * length * float(eta),
        ) / turning_phi
        for eta in eta_values
    ])
    g_values = np.asarray([
        _time_response_g(
            energy, mirror_period, turning_phi, stripes, entry,
            entry + direction * length * float(eta),
        )
        for eta in eta_values
    ])
    psi_coefficients = np.linalg.lstsq(matrix, psi_values, rcond=None)[0]
    g_coefficients = np.linalg.lstsq(matrix, g_values, rcond=None)[0]
    psi_residual = matrix @ psi_coefficients - psi_values
    g_residual = matrix @ g_coefficients - g_values

    def polynomial_at_one(coefficients: np.ndarray) -> float:
        return float(np.sum(coefficients))

    return DimensionlessPsiGPolynomialFit(
        eta_max=maximum_eta,
        sample_count=sample_count,
        polynomial_degree=polynomial_degree,
        psi_coefficients_by_power=tuple(float(value) for value in psi_coefficients),
        g_coefficients_by_power=tuple(float(value) for value in g_coefficients),
        psi_at_nominal_turn=1.0,
        g_at_nominal_turn=_time_response_g(
            energy, mirror_period, turning_phi, stripes, entry, nominal_turn,
        ),
        psi_fit_at_nominal_turn=polynomial_at_one(psi_coefficients),
        g_fit_at_nominal_turn=polynomial_at_one(g_coefficients),
        psi_rms_fit_residual=float(np.sqrt(np.mean(psi_residual * psi_residual))),
        psi_max_abs_fit_residual=float(np.max(np.abs(psi_residual))),
        g_rms_fit_residual=float(np.sqrt(np.mean(g_residual * g_residual))),
        g_max_abs_fit_residual=float(np.max(np.abs(g_residual))),
    )


def time_platform_derivative_residuals(
    *,
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    nominal_turning_y_mm: float,
    eta_turn_nodes: Sequence[float],
    derivative_step: float,
) -> tuple[float, ...]:
    """Evaluate the four-node ``d(tau_g)/d(eta_turn)`` residual family.

    The nominal physical turning section defines ``eta=1``.  Every requested
    node is mapped to the same physical direction and must remain inside both
    frozen Stripe profiles.  This function is only an L0 residual evaluator;
    rank closure decides whether those residuals determine a solution.
    """
    entry = _finite(entry_y_mm, "entry_y_mm")
    nominal_turn = _finite(nominal_turning_y_mm, "nominal_turning_y_mm")
    length = abs(nominal_turn - entry)
    if length <= 0.0 or not eta_turn_nodes:
        raise CandidateContractError("time platform needs a nonzero nominal drift length and named nodes")
    nodes = tuple(_finite(node, "time-platform eta node") for node in eta_turn_nodes)
    if any(node <= 0.0 for node in nodes):
        raise CandidateContractError("time-platform eta nodes must be positive")
    direction = 1.0 if nominal_turn > entry else -1.0
    mirror_period = _finite(mirror_reduced_period_mm_per_sqrt_v, "mirror reduced period")
    turning_phi = _pseudopotential_difference_v(
        energy_per_charge_v, mirror_period, stripes, entry, nominal_turn,
    )
    if turning_phi <= 0.0:
        raise CandidateContractError("nominal time-platform turn must have positive pseudopotential")

    def physical_y(eta: float) -> float:
        return entry + direction * length * _finite(eta, "eta")

    def psi_at_eta(eta: float) -> float:
        return _pseudopotential_difference_v(
            energy_per_charge_v, mirror_period, stripes, entry, physical_y(eta),
        ) / turning_phi

    def g_at_eta(eta: float) -> float:
        return _time_response_g(
            energy_per_charge_v, mirror_period, turning_phi, stripes, entry, physical_y(eta),
        )

    return tuple(
        tau_g_derivative_at_turn(psi_at_eta, g_at_eta, node, step=derivative_step)
        for node in nodes
    )


def spatial_return_kappa_derivative_residual(
    *,
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    nominal_turning_y_mm: float,
    derivative_step: float,
) -> float:
    """Evaluate the paper's ``kappa'(1)`` on one fixed nominal profile."""
    mirror_period = _finite(mirror_reduced_period_mm_per_sqrt_v, "mirror reduced period")
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    entry = _finite(entry_y_mm, "entry_y_mm")
    nominal_turn = _finite(nominal_turning_y_mm, "nominal_turning_y_mm")
    length = abs(nominal_turn - entry)
    if mirror_period <= 0.0 or energy <= 0.0 or length <= 0.0:
        raise CandidateContractError("kappa derivative needs a positive mirror period, energy, and nominal length")
    direction = 1.0 if nominal_turn > entry else -1.0
    turning_phi = _pseudopotential_difference_v(
        energy, mirror_period, stripes, entry, nominal_turn,
    )
    if turning_phi <= 0.0:
        raise CandidateContractError("kappa derivative nominal turn must have positive pseudopotential")

    def psi_at_eta(eta: float) -> float:
        return _pseudopotential_difference_v(
            energy,
            mirror_period,
            stripes,
            entry,
            entry + direction * length * _finite(eta, "eta"),
        ) / turning_phi

    return kappa_derivative_at_turn(psi_at_eta, 1.0, step=derivative_step)


def derive_coupled_drift_state(
    *,
    mirror_reduced_period_mm_per_sqrt_v: float,
    energy_per_charge_v: float,
    target_oscillation_count: int,
    stripes: Sequence[StripeHardBoundary],
    entry_y_mm: float,
    turning_y_mm: float,
) -> CoupledDriftState:
    """Evaluate ``L, W, kappa, theta`` for one fully specified physical trial.

    ``turning_y_mm`` is a physical section selected by the downstream Stripe
    problem, not a second definition of ``L``.  This routine derives the
    injection angle from the turning energy and reports the resulting K
    residual.  The mirror period is a verified input; downstream optimizers
    may vary only their own Stripe/prism coordinates and must not re-fit mirror
    voltage. It is an evaluator, not a parameter solver: callers must classify
    their physical unknown/constraint system with
    :func:`classify_constraint_system` and call
    :func:`require_exactly_determined` before publishing a solution.
    """
    mirror_period = _finite(mirror_reduced_period_mm_per_sqrt_v, "mirror reduced period")
    energy = _finite(energy_per_charge_v, "energy_per_charge_v")
    entry = _finite(entry_y_mm, "entry_y_mm")
    turning = _finite(turning_y_mm, "turning_y_mm")
    if mirror_period <= 0.0 or energy <= 0.0:
        raise CandidateContractError("mirror reduced period and nominal energy must be positive")
    if not isinstance(target_oscillation_count, int) or isinstance(target_oscillation_count, bool) or target_oscillation_count <= 0:
        raise CandidateContractError("target oscillation count must be a positive integer")
    if not stripes or turning == entry:
        raise CandidateContractError("coupled drift needs nonempty Stripe responses and a nonzero physical drift interval")
    baselines = tuple(stripe.width_mm(entry) for stripe in stripes)
    biases = tuple(_finite(stripe.bias_v, "Stripe bias_v") for stripe in stripes)
    period = coupled_reduced_period_mm_per_sqrt_v(mirror_period, energy, baselines, biases)
    turning_phi = _pseudopotential_difference_v(energy, mirror_period, stripes, entry, turning)
    if not 0.0 < turning_phi < energy:
        raise CandidateContractError("chosen physical turning section must have pseudopotential strictly between zero and nominal energy")
    sine_theta = math.sqrt(turning_phi / energy)
    length = abs(turning - entry)
    width = mirror_period * math.sqrt(energy)
    direction = 1.0 if turning > entry else -1.0

    def psi_at_eta(eta: float) -> float:
        eta_value = _finite(eta, "eta")
        if not 0.0 <= eta_value <= 1.0:
            raise CandidateContractError("eta must lie on the physical entry-to-turning interval")
        return _pseudopotential_difference_v(
            energy, mirror_period, stripes, entry, entry + direction * length * eta_value,
        ) / turning_phi

    kappa = endpoint_regularized_kappa(psi_at_eta)
    paper_normalized_k = length * kappa / (width * sine_theta)
    predicted_k = adiabatic_fast_phase_oscillation_count(
        mirror_reduced_period_mm_per_sqrt_v=mirror_period,
        energy_per_charge_v=energy,
        stripes=stripes,
        entry_y_mm=entry,
        turning_y_mm=turning,
    )
    h_factors = tuple(math.sqrt(energy / (energy - bias)) for bias in biases)
    return CoupledDriftState(
        mirror_reduced_period_mm_per_sqrt_v=mirror_period,
        coupled_reduced_period_mm_per_sqrt_v=period,
        axial_width_w_mm=width,
        drift_length_l_mm=length,
        turning_pseudopotential_v=turning_phi,
        nominal_injection_angle_rad=math.asin(sine_theta),
        nominal_kappa_1=kappa,
        paper_normalized_oscillation_count=paper_normalized_k,
        predicted_oscillation_count=predicted_k,
        target_oscillation_count_residual=predicted_k - target_oscillation_count,
        response_h_factors=h_factors,
    )
