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

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    endpoint_regularized_kappa,
    tau_g_derivative_at_turn,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    compile_dual_stripe_width_evaluator,
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
    stripe_handoff_residuals,
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

    first_width = compile_dual_stripe_width_evaluator(contract, "set_1")
    second_width = compile_dual_stripe_width_evaluator(contract, "set_2")
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
    predicted_oscillation_count: float
    target_oscillation_count_residual: float
    response_h_factors: tuple[float, ...]


@dataclass(frozen=True)
class ConstraintClassification:
    """Rank-based determination state for a declared nonlinear solve at one trial."""

    unknown_count: int
    declared_constraint_count: int
    independent_constraint_rank: int | None
    augmented_rank: int | None
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
    eta_derivative_step: float
    stripe_target_position_mm: tuple[float, float, float] | None = None
    stripe_target_unit_direction_project: tuple[float, float, float] | None = None
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


def _matrix_rank(rows: Sequence[Sequence[float]], columns: int, tolerance: float = 1e-10) -> int:
    """Compute a small dense matrix rank without adding a second numeric stack."""
    if columns <= 0 or not rows:
        return 0
    matrix = [[_finite(value, "Jacobian element") for value in row] for row in rows]
    if any(len(row) != columns for row in matrix):
        raise CandidateContractError("each Jacobian row must have one element per declared unknown")
    scale = max(1.0, *(abs(value) for row in matrix for value in row))
    threshold = tolerance * scale
    rank = 0
    for column in range(columns):
        pivot = max(range(rank, len(matrix)), key=lambda index: abs(matrix[index][column]))
        if abs(matrix[pivot][column]) <= threshold:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        pivot_value = matrix[rank][column]
        for row in range(rank + 1, len(matrix)):
            factor = matrix[row][column] / pivot_value
            for trailing in range(column, columns):
                matrix[row][trailing] -= factor * matrix[rank][trailing]
        rank += 1
        if rank == len(matrix):
            break
    return rank


def classify_constraint_system(
    unknown_names: Sequence[str],
    constraint_names: Sequence[str],
    *,
    jacobian_rows: Sequence[Sequence[float]] | None = None,
    residuals: Sequence[float] | None = None,
) -> ConstraintClassification:
    """Classify a solve by independent rank, not merely equation counting.

    Without a numerical Jacobian, the result is deliberately ``rank_unverified``.
    When residuals are supplied, the augmented rank detects an incompatible
    linearized system; redundant, compatible residuals do not falsely make an
    exactly determined system over-defined.
    """
    unknowns = tuple(unknown_names)
    constraints = tuple(constraint_names)
    if not unknowns or not constraints or any(not isinstance(name, str) or not name for name in unknowns + constraints):
        raise CandidateContractError("constraint classification needs nonempty named unknowns and constraints")
    if len(set(unknowns)) != len(unknowns) or len(set(constraints)) != len(constraints):
        raise CandidateContractError("constraint classification names must be unique")
    if jacobian_rows is None:
        return ConstraintClassification(len(unknowns), len(constraints), None, None, "rank_unverified", "a numerical Jacobian is required before determination can be claimed")
    if len(jacobian_rows) != len(constraints):
        raise CandidateContractError("Jacobian must have one row per declared constraint")
    rank = _matrix_rank(jacobian_rows, len(unknowns))
    augmented_rank: int | None = None
    if residuals is not None:
        if len(residuals) != len(constraints):
            raise CandidateContractError("residual vector must have one value per declared constraint")
        augmented_rank = _matrix_rank(
            [tuple(row) + (-_finite(value, "residual"),) for row, value in zip(jacobian_rows, residuals)],
            len(unknowns) + 1,
        )
        if augmented_rank > rank:
            return ConstraintClassification(len(unknowns), len(constraints), rank, augmented_rank, "overdetermined_incompatible", "the linearized residual equations are incompatible")
    if rank < len(unknowns):
        return ConstraintClassification(len(unknowns), len(constraints), rank, augmented_rank, "underdetermined", "independent constraints leave one or more physical degrees of freedom")
    return ConstraintClassification(len(unknowns), len(constraints), rank, augmented_rank, "exactly_determined", "independent constraint rank equals the declared physical degrees of freedom")


def require_exactly_determined(classification: ConstraintClassification) -> None:
    """Refuse publication of a solved parameter set unless its rank closes."""
    if classification.status != "exactly_determined":
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
    central_period = periods[1]
    state = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energies[1], trial.mirror_design),
        energy_per_charge_v=energies[1],
        target_oscillation_count=trial.target_oscillation_count,
        stripes=trial.stripes,
        entry_y_mm=trial.stripe_entry_y_mm,
        turning_y_mm=trial.nominal_turning_y_mm,
    )
    length = state.drift_length_l_mm
    direction = 1.0 if trial.nominal_turning_y_mm > trial.stripe_entry_y_mm else -1.0
    step = _finite(trial.eta_derivative_step, "eta derivative step")
    if step <= 0.0 or 1.0 - step <= 0.0:
        raise CandidateContractError("eta derivative step must bracket the nominal turning point")
    lower_state = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energies[1], trial.mirror_design),
        energy_per_charge_v=energies[1], target_oscillation_count=trial.target_oscillation_count,
        stripes=trial.stripes, entry_y_mm=trial.stripe_entry_y_mm,
        turning_y_mm=trial.stripe_entry_y_mm + direction * length * (1.0 - step),
    )
    upper_state = derive_coupled_drift_state(
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energies[1], trial.mirror_design),
        energy_per_charge_v=energies[1], target_oscillation_count=trial.target_oscillation_count,
        stripes=trial.stripes, entry_y_mm=trial.stripe_entry_y_mm,
        turning_y_mm=trial.stripe_entry_y_mm + direction * length * (1.0 + step),
    )
    time_residuals = time_platform_derivative_residuals(
        mirror_reduced_period_mm_per_sqrt_v=reduced_period(energies[1], trial.mirror_design),
        energy_per_charge_v=energies[1], stripes=trial.stripes,
        entry_y_mm=trial.stripe_entry_y_mm, nominal_turning_y_mm=trial.nominal_turning_y_mm,
        eta_turn_nodes=trial.time_platform_eta_nodes, derivative_step=step,
    )
    residuals = [
        ("three_point_low_relative", (periods[0] - central_period) / central_period),
        ("three_point_high_relative", (periods[2] - central_period) / central_period),
        ("target_oscillation_count", state.target_oscillation_count_residual),
        ("spatial_return_kappa_prime", (upper_state.nominal_kappa_1 - lower_state.nominal_kappa_1) / (2.0 * step)),
    ]
    residuals.extend((f"time_platform_tau_g_prime_eta_{node:.12g}", value) for node, value in zip(trial.time_platform_eta_nodes, time_residuals))
    transport_values = (
        trial.stripe_target_position_mm,
        trial.stripe_target_unit_direction_project,
        trial.two_prism_transport_observation,
    )
    if any(value is not None for value in transport_values):
        if any(value is None for value in transport_values):
            raise CandidateContractError("joint P1/P2 trial needs target position, target direction, and observed transport together")
        residuals.extend(stripe_handoff_residuals(
            trial.two_prism_transport_observation,
            trial.stripe_target_position_mm,
            trial.stripe_target_unit_direction_project,
        ))
    return JointL0ResidualReport(tuple(residuals), state, tuple(periods))


def finite_difference_joint_jacobian(
    variable_names: Sequence[str],
    parameter_values: Sequence[float],
    parameter_steps: Sequence[float],
    trial_from_parameters: Callable[[tuple[float, ...]], JointL0Trial],
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
    rows = [[] for _ in center.residuals]
    for index, step in enumerate(steps):
        lower = list(values)
        upper = list(values)
        lower[index] -= step
        upper[index] += step
        lower_result = evaluate_joint_l0_trial(trial_from_parameters(tuple(lower)))
        upper_result = evaluate_joint_l0_trial(trial_from_parameters(tuple(upper)))
        if lower_result.residual_names() != center.residual_names() or upper_result.residual_names() != center.residual_names():
            raise CandidateContractError("joint residual identity changed across a Jacobian perturbation")
        for row, low, high in zip(rows, lower_result.residual_vector(), upper_result.residual_vector()):
            row.append((high - low) / (2.0 * step))
    return center, classify_constraint_system(names, center.residual_names(), jacobian_rows=rows, residuals=center.residual_vector())


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
    report, classification = finite_difference_joint_jacobian(names, solved, steps, trial_from_parameters)
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


def _pseudopotential_difference_v(
    energy_per_charge_v: float,
    coupled_period_mm_per_sqrt_v: float,
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
    return -action_change / coupled_period_mm_per_sqrt_v


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
    baselines = tuple(stripe.width_mm(entry) for stripe in stripes)
    biases = tuple(_finite(stripe.bias_v, "Stripe bias_v") for stripe in stripes)
    period = coupled_reduced_period_mm_per_sqrt_v(mirror_period, energy, baselines, biases)
    slow_energy = energy * (direction[1] / norm) ** 2
    if not 0.0 < slow_energy < energy:
        raise CandidateContractError("entry ray must have a nonzero, non-total slow y energy")

    def residual(y_mm: float) -> float:
        return _pseudopotential_difference_v(energy, period, stripes, entry, y_mm) - slow_energy

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
    coupled_period_mm_per_sqrt_v: float,
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
        coupled_period_mm_per_sqrt_v * turning_pseudopotential_v
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
    baselines = tuple(stripe.width_mm(entry) for stripe in stripes)
    biases = tuple(stripe.bias_v for stripe in stripes)
    period = coupled_reduced_period_mm_per_sqrt_v(
        mirror_reduced_period_mm_per_sqrt_v, energy_per_charge_v, baselines, biases,
    )
    turning_phi = _pseudopotential_difference_v(energy_per_charge_v, period, stripes, entry, nominal_turn)
    if turning_phi <= 0.0:
        raise CandidateContractError("nominal time-platform turn must have positive pseudopotential")

    def physical_y(eta: float) -> float:
        return entry + direction * length * _finite(eta, "eta")

    def psi_at_eta(eta: float) -> float:
        return _pseudopotential_difference_v(
            energy_per_charge_v, period, stripes, entry, physical_y(eta),
        ) / turning_phi

    def g_at_eta(eta: float) -> float:
        return _time_response_g(
            energy_per_charge_v, period, turning_phi, stripes, entry, physical_y(eta),
        )

    return tuple(
        tau_g_derivative_at_turn(psi_at_eta, g_at_eta, node, step=derivative_step)
        for node in nodes
    )


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
    turning_phi = _pseudopotential_difference_v(energy, period, stripes, entry, turning)
    if not 0.0 < turning_phi < energy:
        raise CandidateContractError("chosen physical turning section must have pseudopotential strictly between zero and nominal energy")
    sine_theta = math.sqrt(turning_phi / energy)
    length = abs(turning - entry)
    width = period * math.sqrt(energy)
    direction = 1.0 if turning > entry else -1.0

    def psi_at_eta(eta: float) -> float:
        eta_value = _finite(eta, "eta")
        if not 0.0 <= eta_value <= 1.0:
            raise CandidateContractError("eta must lie on the physical entry-to-turning interval")
        return _pseudopotential_difference_v(
            energy, period, stripes, entry, entry + direction * length * eta_value,
        ) / turning_phi

    kappa = endpoint_regularized_kappa(psi_at_eta)
    predicted_k = length * kappa / (width * sine_theta)
    h_factors = tuple(math.sqrt(energy / (energy - bias)) for bias in biases)
    return CoupledDriftState(
        mirror_reduced_period_mm_per_sqrt_v=mirror_period,
        coupled_reduced_period_mm_per_sqrt_v=period,
        axial_width_w_mm=width,
        drift_length_l_mm=length,
        turning_pseudopotential_v=turning_phi,
        nominal_injection_angle_rad=math.asin(sine_theta),
        nominal_kappa_1=kappa,
        predicted_oscillation_count=predicted_k,
        target_oscillation_count_residual=predicted_k - target_oscillation_count,
        response_h_factors=h_factors,
    )
