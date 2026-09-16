"""Finite candidate scan of the native dual-Stripe projective shape domain.

This module deliberately does not claim exhaustive root isolation.  It covers
the real projective line with ``theta in [0, pi)`` so that the ``r=infinity``
point is not lost, separates sampled admissible arcs at the normalization pole
and turning violations, brackets sign-changing kappa-prime roots, and reports
near-zero same-sign samples as unresolved candidates.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence

from scipy.optimize import brentq

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
    endpoint_regularized_kappa,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


@dataclass(frozen=True)
class ProjectiveKappaNumerics:
    """Explicit endpoint-integration and finite-difference controls."""

    derivative_step: float
    initial_panels: int
    maximum_integral_refinements: int
    integral_relative_tolerance: float


@dataclass(frozen=True)
class NativeStripeProjectiveScanNumerics:
    """All finite scan, root-isolation, and work-budget controls."""

    theta_sample_count: int
    admissibility_eta_sample_count: int
    adaptive_refinement_levels: int
    normalization_pole_absolute_tolerance: float
    root_absolute_tolerance: float
    root_relative_tolerance: float
    maximum_root_iterations: int
    near_zero_candidate_threshold: float
    maximum_sample_kappa_prime_evaluations: int
    maximum_root_refinement_kappa_prime_evaluations: int
    kappa: ProjectiveKappaNumerics


@dataclass(frozen=True)
class ProjectiveInvalidBoundary:
    """One finite-resolution transition between admissible and invalid samples."""

    theta_interval_rad: tuple[float, float]
    boundary_kind: str
    left_status: str
    right_status: str


@dataclass(frozen=True)
class ProjectiveBracketedRoot:
    """One sign-changing root returned by the scalar bracketing solver."""

    theta_rad: float
    relative_action_weight_ratio: float | None
    kappa_prime: float
    bracket_theta_rad: tuple[float, float]
    iterations: int


@dataclass(frozen=True)
class ProjectiveNearZeroCandidate:
    """A sampled same-sign minimum that is not a bracketed root."""

    theta_rad: float
    relative_action_weight_ratio: float | None
    absolute_kappa_prime: float
    neighbor_theta_interval_rad: tuple[float, float]
    reason: str


@dataclass(frozen=True)
class ProjectiveUnresolvedBracket:
    """An observed sign-change bracket that could not be refined."""

    bracket_theta_rad: tuple[float, float]
    bracket_kappa_prime: tuple[float, float]
    reason: str


@dataclass(frozen=True)
class ProjectiveAdmissibleArc:
    """One sampled connected arc on the real projective line."""

    arc_index: int
    theta_intervals_rad: tuple[tuple[float, float], ...]
    sampled_theta_count: int
    bracketed_roots: tuple[ProjectiveBracketedRoot, ...]
    unresolved_brackets: tuple[ProjectiveUnresolvedBracket, ...]
    near_zero_unresolved_candidates: tuple[ProjectiveNearZeroCandidate, ...]


@dataclass(frozen=True)
class NativeStripeProjectiveScanResult:
    """Finite candidate inventory; never a proof of root completeness."""

    geometry_input_identity_source: str
    entry_y_mm: float
    turning_y_mm: float
    drift_length_l_mm: float
    drift_direction_sign: float
    delta_path_lengths_at_turn_mm: tuple[float, float]
    normalization_pole_theta_rad: float
    normalization_pole_ratio: float | None
    admissible_arcs: tuple[ProjectiveAdmissibleArc, ...]
    invalid_boundaries: tuple[ProjectiveInvalidBoundary, ...]
    sample_kappa_prime_evaluations_used: int
    sample_kappa_prime_evaluation_budget: int
    sample_budget_status: str
    root_refinement_kappa_prime_evaluations_used: int
    root_refinement_kappa_prime_evaluation_budget: int
    root_refinement_budget_status: str
    sample_integral_failure_count: int
    root_refinement_failure_count: int
    completeness_status: str
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _Sample:
    theta: float
    status: str
    residual: float | None
    residual_status: str


class _EvaluationBudgetExhausted(CandidateContractError):
    """Internal typed signal separating work budget from integration failure."""


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateContractError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


def _positive_integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CandidateContractError(f"{name} must be a positive integer")
    return value


def _validate_numerics(value: object) -> NativeStripeProjectiveScanNumerics:
    if not isinstance(value, NativeStripeProjectiveScanNumerics):
        raise CandidateContractError("projective scan requires explicit named numerical controls")
    _positive_integer(value.theta_sample_count, "theta sample count")
    _positive_integer(value.admissibility_eta_sample_count, "admissibility eta sample count")
    if value.theta_sample_count < 4 or value.admissibility_eta_sample_count < 2:
        raise CandidateContractError("projective scan needs at least four theta and two eta samples")
    if not isinstance(value.adaptive_refinement_levels, int) or isinstance(
        value.adaptive_refinement_levels, bool
    ) or value.adaptive_refinement_levels < 0:
        raise CandidateContractError("adaptive refinement levels must be a nonnegative integer")
    _positive_integer(value.maximum_root_iterations, "maximum root iterations")
    _positive_integer(value.maximum_sample_kappa_prime_evaluations, "sample kappa-prime evaluation budget")
    _positive_integer(
        value.maximum_root_refinement_kappa_prime_evaluations,
        "root-refinement kappa-prime evaluation reserve",
    )
    for field_value, name in (
        (value.normalization_pole_absolute_tolerance, "normalization pole tolerance"),
        (value.root_absolute_tolerance, "root absolute tolerance"),
        (value.root_relative_tolerance, "root relative tolerance"),
        (value.near_zero_candidate_threshold, "near-zero candidate threshold"),
    ):
        if _finite(field_value, name) <= 0.0:
            raise CandidateContractError(f"{name} must be positive")
    if not isinstance(value.kappa, ProjectiveKappaNumerics):
        raise CandidateContractError("projective scan requires explicit kappa integration controls")
    step = _finite(value.kappa.derivative_step, "kappa derivative step")
    _positive_integer(value.kappa.initial_panels, "kappa initial panels")
    _positive_integer(value.kappa.maximum_integral_refinements, "kappa integral refinements")
    integral_tolerance = _finite(value.kappa.integral_relative_tolerance, "kappa integral tolerance")
    if value.kappa.initial_panels < 2:
        raise CandidateContractError("kappa integration needs at least two initial panels")
    if not 0.0 < step < 1.0 or not 0.0 < integral_tolerance < 1.0:
        raise CandidateContractError("kappa derivative step and integral tolerance are outside their domains")
    if value.root_relative_tolerance < 4.0 * math.ulp(1.0):
        raise CandidateContractError("root relative tolerance is below the scalar solver domain")
    return value


def _projective_ratio(theta: float) -> float | None:
    cosine = math.cos(theta)
    if abs(cosine) <= 8.0 * math.ulp(1.0):
        return None
    return math.sin(theta) / cosine


def _evaluate_kappa_prime(
    psi_at_eta: Callable[[float], float], numerics: ProjectiveKappaNumerics,
) -> float:
    """Differentiate the existing endpoint integral with explicit settings."""
    step = numerics.derivative_step

    def kappa_at_turn(turn: float) -> float:
        return turn * endpoint_regularized_kappa(
            lambda unit_eta: psi_at_eta(turn * unit_eta),
            initial_panels=numerics.initial_panels,
            max_refinements=numerics.maximum_integral_refinements,
            relative_tolerance=numerics.integral_relative_tolerance,
        )

    return (kappa_at_turn(1.0 + step) - kappa_at_turn(1.0 - step)) / (2.0 * step)


def scan_native_stripe_projective_candidates(
    path_length_functions: Sequence[Callable[[float], float]],
    *,
    entry_y_mm: float,
    drift_length_l_mm: float,
    drift_direction_sign: float,
    geometry_input_identity_source: str,
    numerics: NativeStripeProjectiveScanNumerics,
) -> NativeStripeProjectiveScanResult:
    """Scan finite candidates over the complete ``theta in [0, pi)`` chart.

    The returned inventory is resolution- and budget-bounded.  Sign-changing
    roots are bracketed; sampled same-sign near-zero minima remain unresolved.
    Unsampled narrow or even-multiplicity roots remain possible by design.
    """
    controls = _validate_numerics(numerics)
    if len(path_length_functions) != 2 or any(not callable(item) for item in path_length_functions):
        raise CandidateContractError("projective scan requires exactly two native path functions")
    if not isinstance(geometry_input_identity_source, str) or not geometry_input_identity_source.strip():
        raise CandidateContractError("projective scan requires a nonempty geometry identity source")
    entry = _finite(entry_y_mm, "Stripe entry y")
    length = _finite(drift_length_l_mm, "Stripe drift length L")
    direction = _finite(drift_direction_sign, "Stripe drift direction")
    if length <= 0.0 or isinstance(drift_direction_sign, bool) or direction not in (-1.0, 1.0):
        raise CandidateContractError("projective scan requires positive L and an explicit +/-1 direction")
    paths = tuple(path_length_functions)
    turning = entry + direction * length
    entry_paths = tuple(_finite(path(entry), "Stripe path at entry") for path in paths)

    def delta(index: int, eta: float) -> float:
        coordinate = entry + direction * length * _finite(eta, "projective eta")
        width = _finite(paths[index](coordinate), "native Stripe path length")
        if width <= 0.0 or entry_paths[index] <= 0.0:
            raise CandidateContractError("native Stripe path lengths must remain positive")
        return width - entry_paths[index]

    endpoint_deltas = (delta(0, 1.0), delta(1, 1.0))
    if endpoint_deltas == (0.0, 0.0):
        raise CandidateContractError("native Stripe paths have no nominal turning response")
    pole_theta = math.atan2(-endpoint_deltas[0], endpoint_deltas[1]) % math.pi
    pole_ratio = _projective_ratio(pole_theta)
    final_count = controls.theta_sample_count * (2 ** controls.adaptive_refinement_levels)
    theta_values = tuple((index + 0.5) * math.pi / final_count for index in range(final_count))
    sample_evaluation_cache: dict[float, float] = {}
    root_evaluation_cache: dict[float, float] = {}
    sample_budget_exhausted = False
    root_budget_exhausted = False
    sample_integral_failure_count = 0
    root_refinement_failure_count = 0

    def profile(theta: float) -> Callable[[float], float]:
        cosine, sine = math.cos(theta), math.sin(theta)
        denominator = cosine * endpoint_deltas[0] + sine * endpoint_deltas[1]
        if abs(denominator) <= controls.normalization_pole_absolute_tolerance:
            raise CandidateContractError("projective sample is at the normalization pole")
        return lambda eta: (cosine * delta(0, eta) + sine * delta(1, eta)) / denominator

    def admissibility(theta: float) -> str:
        try:
            psi = profile(theta)
        except CandidateContractError:
            return "normalization_pole"
        for turn in (1.0 - controls.kappa.derivative_step, 1.0 + controls.kappa.derivative_step):
            endpoint = psi(turn)
            for index in range(controls.admissibility_eta_sample_count):
                eta = turn * index / controls.admissibility_eta_sample_count
                if endpoint - psi(eta) <= 0.0:
                    return "turning_inadmissible"
        return "admissible"

    def sample_residual(theta: float) -> float:
        nonlocal sample_budget_exhausted
        key = theta % math.pi
        if key in sample_evaluation_cache:
            return sample_evaluation_cache[key]
        if len(sample_evaluation_cache) >= controls.maximum_sample_kappa_prime_evaluations:
            sample_budget_exhausted = True
            raise _EvaluationBudgetExhausted("projective sample evaluation budget exhausted")
        value = _finite(_evaluate_kappa_prime(profile(key), controls.kappa), "projective kappa-prime")
        sample_evaluation_cache[key] = value
        return value

    def root_residual(theta: float) -> float:
        nonlocal root_budget_exhausted
        key = theta % math.pi
        if key in sample_evaluation_cache:
            return sample_evaluation_cache[key]
        if key in root_evaluation_cache:
            return root_evaluation_cache[key]
        if len(root_evaluation_cache) >= controls.maximum_root_refinement_kappa_prime_evaluations:
            root_budget_exhausted = True
            raise _EvaluationBudgetExhausted("projective root-refinement reserve exhausted")
        value = _finite(_evaluate_kappa_prime(profile(key), controls.kappa), "projective kappa-prime")
        root_evaluation_cache[key] = value
        return value

    samples: list[_Sample] = []
    for theta in theta_values:
        status = admissibility(theta)
        value = None
        residual_status = "not_applicable"
        if status == "admissible":
            try:
                value = sample_residual(theta)
                residual_status = "evaluated"
            except _EvaluationBudgetExhausted:
                residual_status = "sample_budget_unresolved"
            except CandidateContractError:
                sample_integral_failure_count += 1
                residual_status = "integral_unresolved"
        samples.append(_Sample(theta, status, value, residual_status))

    def edge_crosses_pole(index: int) -> bool:
        left = samples[index].theta
        right = samples[(index + 1) % len(samples)].theta
        if index == len(samples) - 1:
            right += math.pi
        pole = pole_theta
        if pole <= left:
            pole += math.pi
        return left < pole < right

    blocked_edges = tuple(
        samples[index].status != "admissible"
        or samples[(index + 1) % len(samples)].status != "admissible"
        or edge_crosses_pole(index)
        for index in range(len(samples))
    )
    invalid_boundaries: list[ProjectiveInvalidBoundary] = []
    for index, left in enumerate(samples):
        right = samples[(index + 1) % len(samples)]
        status_transition = (left.status == "admissible") != (right.status == "admissible")
        pole_boundary = edge_crosses_pole(index)
        if status_transition or pole_boundary:
            right_theta = right.theta + (math.pi if index == len(samples) - 1 else 0.0)
            invalid_boundaries.append(ProjectiveInvalidBoundary(
                theta_interval_rad=(left.theta, right_theta),
                boundary_kind=(
                    "normalization_pole" if pole_boundary else "turning_or_integral_admissibility_transition"
                ),
                left_status=left.status,
                right_status=right.status,
            ))

    admissible_indices = [index for index, sample in enumerate(samples) if sample.status == "admissible"]
    starts = [
        index for index in admissible_indices
        if blocked_edges[(index - 1) % len(samples)]
    ]
    if admissible_indices and not starts:
        starts = [admissible_indices[0]]
    components: list[list[int]] = []
    for start in starts:
        component: list[int] = []
        index = start
        while samples[index].status == "admissible":
            component.append(index)
            if blocked_edges[index]:
                break
            index = (index + 1) % len(samples)
            if index == start:
                break
        components.append(component)

    arcs: list[ProjectiveAdmissibleArc] = []
    for arc_index, indices in enumerate(components):
        points: list[tuple[_Sample, float]] = []
        previous_theta: float | None = None
        for index in indices:
            sample = samples[index]
            theta = sample.theta
            if previous_theta is not None and theta < previous_theta:
                theta += math.pi
            previous_theta = theta
            points.append((sample, theta))
        roots: list[ProjectiveBracketedRoot] = []
        unresolved_brackets: list[ProjectiveUnresolvedBracket] = []
        bracket_sample_indices: set[int] = set()
        for point_index in range(len(points) - 1):
            (left, left_theta), (right, right_theta) = points[point_index], points[point_index + 1]
            if left.residual is None or right.residual is None or left.residual * right.residual > 0.0:
                continue
            try:
                if left.residual == 0.0:
                    root_theta, iterations = left_theta, 0
                elif right.residual == 0.0:
                    root_theta, iterations = right_theta, 0
                else:
                    root_theta, details = brentq(
                        root_residual,
                        left_theta,
                        right_theta,
                        xtol=controls.root_absolute_tolerance,
                        rtol=controls.root_relative_tolerance,
                        maxiter=controls.maximum_root_iterations,
                        full_output=True,
                        disp=False,
                    )
                    if not details.converged:
                        raise CandidateContractError("projective scalar root did not converge")
                    iterations = details.iterations
                candidate = ProjectiveBracketedRoot(
                    theta_rad=root_theta % math.pi,
                    relative_action_weight_ratio=_projective_ratio(root_theta),
                    kappa_prime=root_residual(root_theta),
                    bracket_theta_rad=(left_theta % math.pi, right_theta % math.pi),
                    iterations=iterations,
                )
                if not any(
                    min(
                        abs(candidate.theta_rad - known.theta_rad),
                        math.pi - abs(candidate.theta_rad - known.theta_rad),
                    ) <= controls.root_absolute_tolerance
                    for known in roots
                ):
                    roots.append(candidate)
                bracket_sample_indices.update((point_index, point_index + 1))
            except _EvaluationBudgetExhausted:
                unresolved_brackets.append(ProjectiveUnresolvedBracket(
                    bracket_theta_rad=(left_theta % math.pi, right_theta % math.pi),
                    bracket_kappa_prime=(left.residual, right.residual),
                    reason="root_refinement_evaluation_reserve_exhausted",
                ))
                bracket_sample_indices.update((point_index, point_index + 1))
            except CandidateContractError:
                root_refinement_failure_count += 1
                unresolved_brackets.append(ProjectiveUnresolvedBracket(
                    bracket_theta_rad=(left_theta % math.pi, right_theta % math.pi),
                    bracket_kappa_prime=(left.residual, right.residual),
                    reason="root_refinement_integral_or_profile_failure",
                ))
                bracket_sample_indices.update((point_index, point_index + 1))
            except ValueError:
                root_refinement_failure_count += 1
                unresolved_brackets.append(ProjectiveUnresolvedBracket(
                    bracket_theta_rad=(left_theta % math.pi, right_theta % math.pi),
                    bracket_kappa_prime=(left.residual, right.residual),
                    reason="root_refinement_scalar_solver_failure",
                ))
                bracket_sample_indices.update((point_index, point_index + 1))

        near_zero: list[ProjectiveNearZeroCandidate] = []
        for point_index in range(1, len(points) - 1):
            point, point_theta = points[point_index]
            previous = points[point_index - 1][0]
            following = points[point_index + 1][0]
            if (
                point_index in bracket_sample_indices
                or point.residual is None
                or previous.residual is None
                or following.residual is None
            ):
                continue
            magnitude = abs(point.residual)
            if (
                magnitude <= controls.near_zero_candidate_threshold
                and magnitude <= abs(previous.residual)
                and magnitude <= abs(following.residual)
            ):
                near_zero.append(ProjectiveNearZeroCandidate(
                    theta_rad=point_theta % math.pi,
                    relative_action_weight_ratio=_projective_ratio(point_theta),
                    absolute_kappa_prime=magnitude,
                    neighbor_theta_interval_rad=(
                        points[point_index - 1][1] % math.pi,
                        points[point_index + 1][1] % math.pi,
                    ),
                    reason="sampled_same_sign_near_zero_minimum__even_or_narrow_root_unresolved",
                ))

        raw_intervals: list[tuple[float, float]] = []
        interval_start = samples[indices[0]].theta
        previous = indices[0]
        for index in indices[1:]:
            if index != previous + 1:
                raw_intervals.append((interval_start, samples[previous].theta))
                interval_start = samples[index].theta
            previous = index
        raw_intervals.append((interval_start, samples[previous].theta))
        arcs.append(ProjectiveAdmissibleArc(
            arc_index=arc_index,
            theta_intervals_rad=tuple(raw_intervals),
            sampled_theta_count=len(indices),
            bracketed_roots=tuple(roots),
            unresolved_brackets=tuple(unresolved_brackets),
            near_zero_unresolved_candidates=tuple(near_zero),
        ))

    return NativeStripeProjectiveScanResult(
        geometry_input_identity_source=geometry_input_identity_source.strip(),
        entry_y_mm=entry,
        turning_y_mm=turning,
        drift_length_l_mm=length,
        drift_direction_sign=direction,
        delta_path_lengths_at_turn_mm=endpoint_deltas,
        normalization_pole_theta_rad=pole_theta,
        normalization_pole_ratio=pole_ratio,
        admissible_arcs=tuple(arcs),
        invalid_boundaries=tuple(invalid_boundaries),
        sample_kappa_prime_evaluations_used=len(sample_evaluation_cache),
        sample_kappa_prime_evaluation_budget=controls.maximum_sample_kappa_prime_evaluations,
        sample_budget_status="exhausted" if sample_budget_exhausted else "completed_within_budget",
        root_refinement_kappa_prime_evaluations_used=len(root_evaluation_cache),
        root_refinement_kappa_prime_evaluation_budget=(
            controls.maximum_root_refinement_kappa_prime_evaluations
        ),
        root_refinement_budget_status=(
            "exhausted" if root_budget_exhausted else "completed_within_budget"
        ),
        sample_integral_failure_count=sample_integral_failure_count,
        root_refinement_failure_count=root_refinement_failure_count,
        completeness_status="finite_candidate_scan_only__not_exhaustive_or_unique",
        limitations=(
            "Turning admissibility is sampled, not interval-certified on each B-spline span.",
            "Only sign-changing roots are bracketed; even-multiplicity and unsampled narrow roots may remain.",
            "Near-zero same-sign samples are unresolved candidates, not roots or no-root certificates.",
        ),
    )
