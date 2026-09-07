"""Coupled hard-boundary L0 primitives for the fixed-geometry MR-TOF.

The manufactured mirror geometry is fixed while its voltages are adjustable.
Consequently the effective axial width ``W`` is a *derived free coordinate* of
the mirror-voltage family, not a mechanical distance and not a second input.
This module keeps the Stripe baseline action in the same period evaluation so
that a sequential ``mirror W -> Stripe`` calculation cannot accidentally
over-define the physical state.

It is deliberately solver-neutral and one-dimensional.  Finite 3-D fields,
the transverse Poincare map, and the prism hand-offs remain separate gates.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    endpoint_regularized_kappa,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
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

    ``turning_y_mm`` is a physical section selected by the coupled shooting
    problem, not a second definition of ``L``.  This routine derives the
    injection angle from the turning energy and reports the resulting K
    residual.  A global optimizer may vary mirror voltages, two Stripe biases,
    and the turning section; it must not inject a separately prescribed W.
    It is an evaluator, not a parameter solver: callers must classify their
    full unknown/constraint system with :func:`classify_constraint_system`
    and call :func:`require_exactly_determined` before publishing a solution.
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
