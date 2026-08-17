"""Deterministic scaled root collection for three-zone ideal oa-TOF theory.

The solver is intentionally small and policy-free: campaigns provide every seed,
bound, finite-difference step, tolerance, iteration limit, and acceptance threshold.
All converged roots are retained and clustered; no preferred branch is hidden here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np
from numpy.typing import NDArray

from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    DesignEvaluation,
    InnerSolution,
    OuterGeometry,
    PhysicsGateLimits,
    ReflectronGeometry,
    TheoryDomainError,
    TimeDerivatives,
    compute_time_derivatives,
    derive_three_zone_state,
    evaluate_three_zone_design,
    source_energy_per_charge,
)


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _positive(value: float, name: str) -> float:
    result = _finite(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be > 0")
    return result


@dataclass(frozen=True)
class RootSeed:
    """One scaled three-zone root seed ``(U/Wc, F2*LR2/Wc, eta/eta_scale)``."""

    u: float
    f: float
    eta_hat: float

    def as_array(self) -> NDArray[np.float64]:
        """Return the seed as a new float array."""

        values = np.asarray((self.u, self.f, self.eta_hat), dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError("RootSeed values must be finite")
        return values


@dataclass(frozen=True)
class TwoZoneRootSeed:
    """One scaled eta=0 root seed ``(U/Wc, F2*LR2/Wc)``."""

    u: float
    f: float

    def as_array(self) -> NDArray[np.float64]:
        """Return the seed as a new float array."""

        values = np.asarray((self.u, self.f), dtype=float)
        if not np.all(np.isfinite(values)):
            raise ValueError("TwoZoneRootSeed values must be finite")
        return values


@dataclass(frozen=True)
class RootBounds:
    """Closed scaled-coordinate bounds for three-zone roots."""

    lower_u: float
    upper_u: float
    lower_f: float
    upper_f: float
    lower_eta_hat: float
    upper_eta_hat: float

    def __post_init__(self) -> None:
        pairs = (
            (self.lower_u, self.upper_u, "u"),
            (self.lower_f, self.upper_f, "f"),
            (self.lower_eta_hat, self.upper_eta_hat, "eta_hat"),
        )
        for lower, upper, name in pairs:
            if _finite(lower, f"lower_{name}") >= _finite(upper, f"upper_{name}"):
                raise ValueError(f"{name} bounds are reversed or empty")
        if self.lower_u <= 0.0 or self.lower_f <= 0.0:
            raise ValueError("u and f bounds must be strictly positive")

    def contains(self, values: NDArray[np.float64]) -> bool:
        """Return whether a three-coordinate vector lies in the closed box."""

        lower = np.asarray((self.lower_u, self.lower_f, self.lower_eta_hat))
        upper = np.asarray((self.upper_u, self.upper_f, self.upper_eta_hat))
        return bool(np.all(values >= lower) and np.all(values <= upper))


@dataclass(frozen=True)
class TwoZoneRootBounds:
    """Closed scaled-coordinate bounds for eta=0 roots."""

    lower_u: float
    upper_u: float
    lower_f: float
    upper_f: float

    def __post_init__(self) -> None:
        if _finite(self.lower_u, "lower_u") >= _finite(self.upper_u, "upper_u"):
            raise ValueError("u bounds are reversed or empty")
        if _finite(self.lower_f, "lower_f") >= _finite(self.upper_f, "upper_f"):
            raise ValueError("f bounds are reversed or empty")
        if self.lower_u <= 0.0 or self.lower_f <= 0.0:
            raise ValueError("u and f bounds must be strictly positive")

    def contains(self, values: NDArray[np.float64]) -> bool:
        """Return whether a two-coordinate vector lies in the closed box."""

        lower = np.asarray((self.lower_u, self.lower_f))
        upper = np.asarray((self.upper_u, self.upper_f))
        return bool(np.all(values >= lower) and np.all(values <= upper))


@dataclass(frozen=True)
class JacobianSettings:
    """Caller-owned scaled coordinates and finite-difference audit settings."""

    eta_scale: float
    step_u: float
    step_f: float
    step_eta_hat: float
    stability_step_multiplier: float
    rank_relative_tolerance: float

    def __post_init__(self) -> None:
        _positive(self.eta_scale, "eta_scale")
        _positive(self.step_u, "step_u")
        _positive(self.step_f, "step_f")
        _positive(self.step_eta_hat, "step_eta_hat")
        _positive(self.stability_step_multiplier, "stability_step_multiplier")
        _positive(self.rank_relative_tolerance, "rank_relative_tolerance")

    def three_zone_steps(self) -> NDArray[np.float64]:
        """Return the three-zone central-difference steps."""

        return np.asarray((self.step_u, self.step_f, self.step_eta_hat))

    def two_zone_steps(self) -> NDArray[np.float64]:
        """Return the eta=0 central-difference steps."""

        return np.asarray((self.step_u, self.step_f))


@dataclass(frozen=True)
class JacobianLimits:
    """Caller-owned root, conditioning, stability, and Gamma3 acceptance limits."""

    root_residual_absolute_max: float
    minimum_reciprocal_condition: float
    maximum_condition_number: float
    maximum_jacobian_stability_relative_error: float
    minimum_gamma3_uncertainty_multiple: float

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if _finite(value, name) < 0.0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class RootSearchSettings:
    """Deterministic three-zone multi-start and clustering policy."""

    seeds: tuple[RootSeed, ...]
    bounds: RootBounds
    convergence_tolerance: float
    maximum_iterations: int
    maximum_backtracks: int
    cluster_distance: float
    jacobian: JacobianSettings
    limits: JacobianLimits

    def __post_init__(self) -> None:
        if not self.seeds:
            raise ValueError("at least one RootSeed is required")
        _positive(self.convergence_tolerance, "convergence_tolerance")
        if (
            isinstance(self.maximum_iterations, bool)
            or not isinstance(self.maximum_iterations, int)
            or self.maximum_iterations < 1
        ):
            raise ValueError("maximum_iterations must be an integer >= 1")
        if (
            isinstance(self.maximum_backtracks, bool)
            or not isinstance(self.maximum_backtracks, int)
            or self.maximum_backtracks < 0
        ):
            raise ValueError("maximum_backtracks must be an integer >= 0")
        _positive(self.cluster_distance, "cluster_distance")


@dataclass(frozen=True)
class TwoZoneRootSearchSettings:
    """Deterministic eta=0 multi-start and clustering policy."""

    seeds: tuple[TwoZoneRootSeed, ...]
    bounds: TwoZoneRootBounds
    convergence_tolerance: float
    maximum_iterations: int
    maximum_backtracks: int
    cluster_distance: float
    jacobian: JacobianSettings
    limits: JacobianLimits

    def __post_init__(self) -> None:
        if not self.seeds:
            raise ValueError("at least one TwoZoneRootSeed is required")
        _positive(self.convergence_tolerance, "convergence_tolerance")
        if (
            isinstance(self.maximum_iterations, bool)
            or not isinstance(self.maximum_iterations, int)
            or self.maximum_iterations < 1
        ):
            raise ValueError("maximum_iterations must be an integer >= 1")
        if (
            isinstance(self.maximum_backtracks, bool)
            or not isinstance(self.maximum_backtracks, int)
            or self.maximum_backtracks < 0
        ):
            raise ValueError("maximum_backtracks must be an integer >= 0")
        _positive(self.cluster_distance, "cluster_distance")


@dataclass(frozen=True)
class ScaledResiduals:
    """Dimensionless derivative residuals over the exact source energy span."""

    energy_half_span_v: float
    reference_time_mm_sqrt_v: float
    values: tuple[float, ...]

    @property
    def infinity_norm(self) -> float:
        """Return the maximum absolute scaled residual."""

        return max(abs(value) for value in self.values)


@dataclass(frozen=True)
class JacobianAudit:
    """Scaled Jacobian, conditioning, stability, and optional Gamma3 audit."""

    residuals: ScaledResiduals
    jacobian: NDArray[np.float64]
    singular_values: tuple[float, ...]
    numerical_rank: int
    condition_number: float
    reciprocal_condition: float
    jacobian_stability_relative_error: float
    gamma3_scaled: float | None
    gamma3_step_uncertainty: float | None
    root_residual_passed: bool
    full_rank_passed: bool
    reciprocal_condition_passed: bool
    engineering_condition_passed: bool
    jacobian_stability_passed: bool
    gamma3_passed: bool | None

    @property
    def passed(self) -> bool:
        """Return the conjunction of all applicable numerical acceptance gates."""

        checks = (
            self.root_residual_passed,
            self.full_rank_passed,
            self.reciprocal_condition_passed,
            self.engineering_condition_passed,
            self.jacobian_stability_passed,
        )
        return all(checks) and (self.gamma3_passed is not False)


@dataclass(frozen=True)
class RootAttempt:
    """One deterministic Newton attempt, successful or not."""

    seed: tuple[float, ...]
    converged: bool
    iterations: int
    reason: str
    coordinates: tuple[float, ...]
    residuals: tuple[float, ...] | None


@dataclass(frozen=True)
class RootCandidate:
    """One clustered formula root with exact physics and numerical audits."""

    coordinates: tuple[float, ...]
    inner: InnerSolution
    derivatives: TimeDerivatives
    evaluation: DesignEvaluation
    jacobian_audit: JacobianAudit
    source_seed_indices: tuple[int, ...]

    @property
    def accepted(self) -> bool:
        """Return whether both the exact physics and numerical gates pass."""

        return self.evaluation.gates.passed and self.jacobian_audit.passed


@dataclass(frozen=True)
class RootCollection:
    """All attempts and all distinct clustered roots in deterministic order."""

    attempts: tuple[RootAttempt, ...]
    candidates: tuple[RootCandidate, ...]

    @property
    def accepted_candidates(self) -> tuple[RootCandidate, ...]:
        """Return accepted candidates without changing their deterministic order."""

        return tuple(candidate for candidate in self.candidates if candidate.accepted)


def inner_from_scaled_coordinates(
    source: AffineSource,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    coordinates: Sequence[float],
    *,
    eta_scale: float,
) -> InnerSolution:
    """Convert scaled root coordinates to physical reflectron variables and eta."""

    if len(coordinates) not in (2, 3):
        raise ValueError("scaled coordinates must have length 2 or 3")
    values = np.asarray(coordinates, dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("scaled coordinates must be finite")
    scale = _positive(eta_scale, "eta_scale")
    center_energy = (
        outer.nominal_energy_per_charge_v + source.chi_center_sqrt_v**2
    )
    eta = 0.0 if len(values) == 2 else float(values[2]) * scale
    return InnerSolution(
        stage1_voltage_drop_v=float(values[0]) * center_energy,
        stage2_field_v_per_mm=(
            float(values[1]) * center_energy / reflectron.stage2_length_mm
        ),
        eta=eta,
    )


def _energy_half_span_v(
    source: AffineSource,
    outer: OuterGeometry,
    eta: float,
    width_mm: float,
) -> float:
    state = derive_three_zone_state(source, outer, eta)
    endpoints = np.asarray(
        (
            source.center_x_mm - width_mm / 2.0,
            source.center_x_mm + width_mm / 2.0,
        )
    )
    energy = np.asarray(source_energy_per_charge(source, state, endpoints))
    return float(np.max(np.abs(energy - state.center_energy_per_charge_v)))


def evaluate_scaled_residuals(
    source: AffineSource,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    *,
    width_mm: float,
    derivative_count: int,
) -> tuple[ScaledResiduals, TimeDerivatives]:
    """Return dimensionless ``Dn*DeltaW^n/(n!*tau_ref)`` residuals."""

    width = _positive(width_mm, "width_mm")
    if derivative_count not in (2, 3):
        raise ValueError("derivative_count must be 2 or 3")
    state = derive_three_zone_state(source, outer, inner.eta)
    derivatives = compute_time_derivatives(source, state, reflectron, inner)
    half_span = _energy_half_span_v(source, outer, inner.eta, width)
    reference_time = abs(derivatives.center_normalized_time_mm_sqrt_v)
    if reference_time == 0.0:
        raise TheoryDomainError("center normalized time must be nonzero")
    derivative_values = derivatives.as_array()
    residuals = tuple(
        float(
            derivative_values[order - 1]
            * half_span**order
            / (math.factorial(order) * reference_time)
        )
        for order in range(1, derivative_count + 1)
    )
    return ScaledResiduals(half_span, reference_time, residuals), derivatives


def _central_jacobian(
    residual_function: Callable[[NDArray[np.float64]], NDArray[np.float64]],
    coordinates: NDArray[np.float64],
    steps: NDArray[np.float64],
) -> NDArray[np.float64]:
    columns: list[NDArray[np.float64]] = []
    for index, step in enumerate(steps):
        plus = coordinates.copy()
        minus = coordinates.copy()
        plus[index] += step
        minus[index] -= step
        columns.append((residual_function(plus) - residual_function(minus)) / (2.0 * step))
    return np.column_stack(columns)


def _matrix_diagnostics(
    jacobian: NDArray[np.float64],
    rank_relative_tolerance: float,
) -> tuple[tuple[float, ...], int, float, float]:
    singular = np.linalg.svd(jacobian, compute_uv=False)
    maximum = float(singular[0])
    minimum = float(singular[-1])
    tolerance = rank_relative_tolerance * maximum
    rank = int(np.count_nonzero(singular > tolerance))
    condition = math.inf if minimum == 0.0 else maximum / minimum
    reciprocal = 0.0 if not math.isfinite(condition) else 1.0 / condition
    return tuple(float(value) for value in singular), rank, condition, reciprocal


def _relative_matrix_change(
    first: NDArray[np.float64], second: NDArray[np.float64]
) -> float:
    denominator = max(float(np.linalg.norm(first)), np.finfo(float).tiny)
    return float(np.linalg.norm(second - first) / denominator)


def _gamma3(jacobian: NDArray[np.float64]) -> float:
    root_block = jacobian[:2, :2]
    eta_column = jacobian[:2, 2]
    third_root_row = jacobian[2, :2]
    return float(
        jacobian[2, 2]
        - third_root_row @ np.linalg.solve(root_block, eta_column)
    )


def _build_audit(
    residuals: ScaledResiduals,
    jacobian: NDArray[np.float64],
    alternate: NDArray[np.float64],
    settings: JacobianSettings,
    limits: JacobianLimits,
) -> JacobianAudit:
    singular, rank, condition, reciprocal = _matrix_diagnostics(
        jacobian, settings.rank_relative_tolerance
    )
    stability = _relative_matrix_change(jacobian, alternate)
    gamma: float | None = None
    gamma_uncertainty: float | None = None
    gamma_passed: bool | None = None
    if jacobian.shape == (3, 3) and rank == 3:
        try:
            gamma = _gamma3(jacobian)
            alternate_gamma = _gamma3(alternate)
        except np.linalg.LinAlgError:
            gamma_passed = False
        else:
            gamma_uncertainty = abs(alternate_gamma - gamma)
            gamma_passed = abs(gamma) >= (
                limits.minimum_gamma3_uncertainty_multiple * gamma_uncertainty
            )
    return JacobianAudit(
        residuals=residuals,
        jacobian=jacobian,
        singular_values=singular,
        numerical_rank=rank,
        condition_number=condition,
        reciprocal_condition=reciprocal,
        jacobian_stability_relative_error=stability,
        gamma3_scaled=gamma,
        gamma3_step_uncertainty=gamma_uncertainty,
        root_residual_passed=(
            residuals.infinity_norm <= limits.root_residual_absolute_max
        ),
        full_rank_passed=rank == jacobian.shape[1],
        reciprocal_condition_passed=(
            reciprocal >= limits.minimum_reciprocal_condition
        ),
        engineering_condition_passed=(
            condition <= limits.maximum_condition_number
        ),
        jacobian_stability_passed=(
            stability <= limits.maximum_jacobian_stability_relative_error
        ),
        gamma3_passed=gamma_passed,
    )


def audit_scaled_jacobian(
    source: AffineSource,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    *,
    width_mm: float,
    settings: JacobianSettings,
    limits: JacobianLimits,
) -> JacobianAudit:
    """Audit the scaled three-variable ``D1..D3`` residual Jacobian and Gamma3."""

    center_energy = (
        outer.nominal_energy_per_charge_v + source.chi_center_sqrt_v**2
    )
    coordinates = np.asarray(
        (
            inner.stage1_voltage_drop_v / center_energy,
            inner.stage2_field_v_per_mm * reflectron.stage2_length_mm / center_energy,
            inner.eta / settings.eta_scale,
        )
    )

    def residual_function(values: NDArray[np.float64]) -> NDArray[np.float64]:
        trial = inner_from_scaled_coordinates(
            source, outer, reflectron, values, eta_scale=settings.eta_scale
        )
        residual, _ = evaluate_scaled_residuals(
            source,
            outer,
            reflectron,
            trial,
            width_mm=width_mm,
            derivative_count=3,
        )
        return np.asarray(residual.values)

    residuals, _ = evaluate_scaled_residuals(
        source,
        outer,
        reflectron,
        inner,
        width_mm=width_mm,
        derivative_count=3,
    )
    steps = settings.three_zone_steps()
    jacobian = _central_jacobian(residual_function, coordinates, steps)
    alternate = _central_jacobian(
        residual_function, coordinates, steps * settings.stability_step_multiplier
    )
    return _build_audit(residuals, jacobian, alternate, settings, limits)


def audit_two_zone_jacobian(
    source: AffineSource,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    inner: InnerSolution,
    *,
    width_mm: float,
    settings: JacobianSettings,
    limits: JacobianLimits,
) -> JacobianAudit:
    """Audit the eta=0 scaled two-variable ``D1,D2`` residual Jacobian."""

    if inner.eta != 0.0:
        raise ValueError("audit_two_zone_jacobian requires eta == 0")
    center_energy = (
        outer.nominal_energy_per_charge_v + source.chi_center_sqrt_v**2
    )
    coordinates = np.asarray(
        (
            inner.stage1_voltage_drop_v / center_energy,
            inner.stage2_field_v_per_mm * reflectron.stage2_length_mm / center_energy,
        )
    )

    def residual_function(values: NDArray[np.float64]) -> NDArray[np.float64]:
        trial = inner_from_scaled_coordinates(
            source, outer, reflectron, values, eta_scale=settings.eta_scale
        )
        residual, _ = evaluate_scaled_residuals(
            source,
            outer,
            reflectron,
            trial,
            width_mm=width_mm,
            derivative_count=2,
        )
        return np.asarray(residual.values)

    residuals, _ = evaluate_scaled_residuals(
        source,
        outer,
        reflectron,
        inner,
        width_mm=width_mm,
        derivative_count=2,
    )
    steps = settings.two_zone_steps()
    jacobian = _central_jacobian(residual_function, coordinates, steps)
    alternate = _central_jacobian(
        residual_function, coordinates, steps * settings.stability_step_multiplier
    )
    return _build_audit(residuals, jacobian, alternate, settings, limits)


def _newton_attempt(
    seed: NDArray[np.float64],
    bounds_contains: Callable[[NDArray[np.float64]], bool],
    residual_function: Callable[[NDArray[np.float64]], NDArray[np.float64]],
    steps: NDArray[np.float64],
    *,
    residual_tolerance: float,
    maximum_iterations: int,
    maximum_backtracks: int,
) -> RootAttempt:
    coordinates = seed.copy()
    seed_tuple = tuple(float(value) for value in seed)
    if not bounds_contains(coordinates):
        return RootAttempt(seed_tuple, False, 0, "seed_out_of_bounds", seed_tuple, None)
    last_residual: NDArray[np.float64] | None = None
    for iteration in range(maximum_iterations + 1):
        try:
            residual = residual_function(coordinates)
        except (TheoryDomainError, ValueError, FloatingPointError):
            return RootAttempt(
                seed_tuple,
                False,
                iteration,
                "domain_error",
                tuple(float(value) for value in coordinates),
                None if last_residual is None else tuple(float(value) for value in last_residual),
            )
        last_residual = residual
        norm = float(np.max(np.abs(residual)))
        if norm <= residual_tolerance:
            return RootAttempt(
                seed_tuple,
                True,
                iteration,
                "converged",
                tuple(float(value) for value in coordinates),
                tuple(float(value) for value in residual),
            )
        if iteration == maximum_iterations:
            break
        try:
            jacobian = _central_jacobian(residual_function, coordinates, steps)
            delta = np.linalg.solve(jacobian, -residual)
        except (TheoryDomainError, ValueError, FloatingPointError, np.linalg.LinAlgError):
            return RootAttempt(
                seed_tuple,
                False,
                iteration,
                "jacobian_failure",
                tuple(float(value) for value in coordinates),
                tuple(float(value) for value in residual),
            )
        accepted = False
        for backtrack in range(maximum_backtracks + 1):
            trial = coordinates + delta / (2.0**backtrack)
            if not bounds_contains(trial):
                continue
            try:
                trial_residual = residual_function(trial)
            except (TheoryDomainError, ValueError, FloatingPointError):
                continue
            if float(np.max(np.abs(trial_residual))) < norm:
                coordinates = trial
                accepted = True
                break
        if not accepted:
            return RootAttempt(
                seed_tuple,
                False,
                iteration,
                "line_search_failure",
                tuple(float(value) for value in coordinates),
                tuple(float(value) for value in residual),
            )
    return RootAttempt(
        seed_tuple,
        False,
        maximum_iterations,
        "maximum_iterations",
        tuple(float(value) for value in coordinates),
        None if last_residual is None else tuple(float(value) for value in last_residual),
    )


def _cluster_attempts(
    attempts: Sequence[RootAttempt], cluster_distance: float
) -> list[list[int]]:
    clusters: list[list[int]] = []
    centers: list[NDArray[np.float64]] = []
    for index, attempt in enumerate(attempts):
        if not attempt.converged:
            continue
        coordinates = np.asarray(attempt.coordinates)
        match = next(
            (
                cluster_index
                for cluster_index, center in enumerate(centers)
                if float(np.linalg.norm(coordinates - center)) <= cluster_distance
            ),
            None,
        )
        if match is None:
            clusters.append([index])
            centers.append(coordinates)
        else:
            clusters[match].append(index)
            members = np.asarray([attempts[item].coordinates for item in clusters[match]])
            centers[match] = np.mean(members, axis=0)
    return clusters


def _best_cluster_attempt(
    attempts: Sequence[RootAttempt], indices: Sequence[int]
) -> RootAttempt:
    return min(
        (attempts[index] for index in indices),
        key=lambda item: max(abs(value) for value in item.residuals or (math.inf,)),
    )


def collect_three_zone_roots(
    source: AffineSource,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    *,
    width_mm: float,
    cohort_sample_count: int,
    physics_limits: PhysicsGateLimits,
    settings: RootSearchSettings,
) -> RootCollection:
    """Collect and cluster every converged ``D1=D2=D3=0`` root from supplied seeds."""

    def residual_function(values: NDArray[np.float64]) -> NDArray[np.float64]:
        inner = inner_from_scaled_coordinates(
            source, outer, reflectron, values, eta_scale=settings.jacobian.eta_scale
        )
        residuals, _ = evaluate_scaled_residuals(
            source,
            outer,
            reflectron,
            inner,
            width_mm=width_mm,
            derivative_count=3,
        )
        return np.asarray(residuals.values)

    attempts = tuple(
        _newton_attempt(
            seed.as_array(),
            settings.bounds.contains,
            residual_function,
            settings.jacobian.three_zone_steps(),
            residual_tolerance=settings.convergence_tolerance,
            maximum_iterations=settings.maximum_iterations,
            maximum_backtracks=settings.maximum_backtracks,
        )
        for seed in settings.seeds
    )
    candidates: list[RootCandidate] = []
    for cluster in _cluster_attempts(attempts, settings.cluster_distance):
        best = _best_cluster_attempt(attempts, cluster)
        inner = inner_from_scaled_coordinates(
            source,
            outer,
            reflectron,
            best.coordinates,
            eta_scale=settings.jacobian.eta_scale,
        )
        evaluation = evaluate_three_zone_design(
            source,
            outer,
            reflectron,
            inner,
            width_mm=width_mm,
            sample_count=cohort_sample_count,
            physics_limits=physics_limits,
        )
        audit = audit_scaled_jacobian(
            source,
            outer,
            reflectron,
            inner,
            width_mm=width_mm,
            settings=settings.jacobian,
            limits=settings.limits,
        )
        candidates.append(
            RootCandidate(
                coordinates=best.coordinates,
                inner=inner,
                derivatives=evaluation.derivatives,
                evaluation=evaluation,
                jacobian_audit=audit,
                source_seed_indices=tuple(cluster),
            )
        )
    return RootCollection(attempts, tuple(candidates))


def collect_two_zone_roots(
    source: AffineSource,
    outer: OuterGeometry,
    reflectron: ReflectronGeometry,
    *,
    width_mm: float,
    cohort_sample_count: int,
    physics_limits: PhysicsGateLimits,
    settings: TwoZoneRootSearchSettings,
) -> RootCollection:
    """Collect paired eta=0 ``D1=D2=0`` roots over the supplied common seeds."""

    def residual_function(values: NDArray[np.float64]) -> NDArray[np.float64]:
        inner = inner_from_scaled_coordinates(
            source, outer, reflectron, values, eta_scale=settings.jacobian.eta_scale
        )
        residuals, _ = evaluate_scaled_residuals(
            source,
            outer,
            reflectron,
            inner,
            width_mm=width_mm,
            derivative_count=2,
        )
        return np.asarray(residuals.values)

    attempts = tuple(
        _newton_attempt(
            seed.as_array(),
            settings.bounds.contains,
            residual_function,
            settings.jacobian.two_zone_steps(),
            residual_tolerance=settings.convergence_tolerance,
            maximum_iterations=settings.maximum_iterations,
            maximum_backtracks=settings.maximum_backtracks,
        )
        for seed in settings.seeds
    )
    candidates: list[RootCandidate] = []
    for cluster in _cluster_attempts(attempts, settings.cluster_distance):
        best = _best_cluster_attempt(attempts, cluster)
        inner = inner_from_scaled_coordinates(
            source,
            outer,
            reflectron,
            best.coordinates,
            eta_scale=settings.jacobian.eta_scale,
        )
        evaluation = evaluate_three_zone_design(
            source,
            outer,
            reflectron,
            inner,
            width_mm=width_mm,
            sample_count=cohort_sample_count,
            physics_limits=physics_limits,
        )
        audit = audit_two_zone_jacobian(
            source,
            outer,
            reflectron,
            inner,
            width_mm=width_mm,
            settings=settings.jacobian,
            limits=settings.limits,
        )
        candidates.append(
            RootCandidate(
                coordinates=best.coordinates,
                inner=inner,
                derivatives=evaluation.derivatives,
                evaluation=evaluation,
                jacobian_audit=audit,
                source_seed_indices=tuple(cluster),
            )
        )
    return RootCollection(attempts, tuple(candidates))
