"""Detector-blind source modelling and local J2 focusability calculations.

The module is solver-independent.  It consumes frozen pre-pulse state arrays and
time-sensitivity arrays supplied by a caller; it never reads detector outcomes,
starts a solver, or chooses a Candidate geometry.
"""

from __future__ import annotations

import hashlib
import math
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.stats import chi2


_ROLES = ("development", "validation", "optimization", "locked_test")


@dataclass(frozen=True)
class CohortAssignment:
    """Deterministic detector-blind assignment for one particle identifier."""

    particle_id: int
    role: str


@dataclass(frozen=True)
class FrozenPrePulseSource:
    """Canonical six-dimensional source state at one common OA pre-pulse instant."""

    particle_ids: NDArray[np.int64]
    state: NDArray[np.float64]
    pulse_eligibility: NDArray[np.bool_]
    instrument_time_us: float
    state_names: tuple[str, ...] = (
        "x_mm", "y_mm", "z_mm", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s"
    )


@dataclass(frozen=True)
class SourceConditionModel:
    """Polynomial conditional mean and residual covariance for one source state."""

    condition_names: tuple[str, ...]
    state_names: tuple[str, ...]
    degree: int
    condition_center: NDArray[np.float64]
    condition_scale: NDArray[np.float64]
    coefficients: NDArray[np.float64]
    covariance: NDArray[np.float64]
    covariance_factor: NDArray[np.float64]
    effective_sample_count: int
    tail_fraction: float
    residual_rms: NDArray[np.float64]
    pulse_eligible_fraction: float
    transverse_emittance_x_mm_m_per_s: float | None
    transverse_emittance_y_mm_m_per_s: float | None

    def predict_mean(self, condition: NDArray[np.float64]) -> NDArray[np.float64]:
        """Return conditional means for ``condition`` with shape ``(n, k)``."""

        values = _matrix(condition, "condition")
        if values.shape[1] != len(self.condition_names):
            raise ValueError("condition column count differs from the fitted model")
        features = _polynomial_features(
            (values - self.condition_center) / self.condition_scale, self.degree
        )
        return features @ self.coefficients


@dataclass(frozen=True)
class CovarianceBin:
    """Detector-blind local residual covariance in one condition bin."""

    lower_condition: float
    upper_condition: float
    sample_count: int
    covariance: NDArray[np.float64]


@dataclass(frozen=True)
class SourceConditionAssessment:
    """C1 diagnostics that may be computed without detector arrival data."""

    selected_model: SourceConditionModel
    covariance_bins: tuple[CovarianceBin, ...]
    residual_mode_variance: NDArray[np.float64]
    residual_mode_bootstrap_alignment: NDArray[np.float64]


@dataclass(frozen=True)
class FocusabilityProblem:
    """Scaled local J2 inputs at one source bin or a stacked collection of bins."""

    time_gradient: NDArray[np.float64]
    design_response: NDArray[np.float64]
    source_factor: NDArray[np.float64]
    constraint_jacobian: NDArray[np.float64]
    parameter_scale: NDArray[np.float64]
    lower_eta: NDArray[np.float64] | None = None
    upper_eta: NDArray[np.float64] | None = None
    trust_radius: float | None = None
    rank_relative_tolerance: float | None = None


@dataclass(frozen=True)
class PredictionResult:
    """Result of the source-whitened local constrained least-squares problem."""

    eta: NDArray[np.float64]
    null_space: NDArray[np.float64]
    singular_values: NDArray[np.float64]
    effective_rank: int
    condition_number: float
    initial_conditional_variance: float
    predicted_conditional_variance: float
    local_reference_minimum: float
    focusability_fraction: float
    active_constraints: tuple[str, ...]
    constraint_residual_norm: float
    rank_tolerance: float


def _matrix(values: NDArray[np.float64] | Sequence[Sequence[float]], label: str) -> NDArray[np.float64]:
    result = np.asarray(values, dtype=float)
    if result.ndim != 2 or result.shape[0] == 0 or result.shape[1] == 0:
        raise ValueError(f"{label} must be a non-empty two-dimensional array")
    if not np.isfinite(result).all():
        raise ValueError(f"{label} must be finite")
    return result


def _vector(values: NDArray[np.float64] | Sequence[float], label: str) -> NDArray[np.float64]:
    result = np.asarray(values, dtype=float)
    if result.ndim != 1 or result.size == 0 or not np.isfinite(result).all():
        raise ValueError(f"{label} must be a non-empty finite vector")
    return result


def assign_detector_blind_cohorts(
    particle_ids: Iterable[int], *, salt: str,
    role_upper_bounds: Sequence[tuple[str, float]] | None = None,
) -> tuple[CohortAssignment, ...]:
    """Split unique IDs by SHA-256 without consulting any detector-level outcome."""

    if not salt:
        raise ValueError("cohort salt must be non-empty")
    bounds = role_upper_bounds or (
        ("development", 0.50),
        ("validation", 0.70),
        ("optimization", 0.85),
        ("locked_test", 1.00),
    )
    if (
        len(bounds) != 4
        or tuple(role for role, _ in bounds) != (
            "development", "validation", "optimization", "locked_test"
        )
        or any(
            not isinstance(upper, float) or not 0.0 < upper <= 1.0
            for _, upper in bounds
        )
        or any(current[1] >= following[1] for current, following in zip(bounds, bounds[1:]))
        or bounds[-1][1] != 1.0
    ):
        raise ValueError("cohort role upper bounds must be increasing and end at 1.0")
    result: list[CohortAssignment] = []
    seen: set[int] = set()
    for particle_id in particle_ids:
        identifier = int(particle_id)
        if identifier < 1 or identifier in seen:
            raise ValueError("particle IDs must be unique positive integers")
        seen.add(identifier)
        bucket = int.from_bytes(
            hashlib.sha256(f"{salt}:{identifier}".encode("utf-8")).digest()[:8],
            "big",
        ) / 2**64
        role = next(role for role, upper in bounds if bucket < upper)
        result.append(CohortAssignment(identifier, role))
    if not result:
        raise ValueError("at least one particle ID is required")
    return tuple(result)


def load_frozen_pre_pulse_source(
    path: Path, *, time_series_sample_index: int | None = None
) -> FrozenPrePulseSource:
    """Load one shared-time OA pre-pulse state table and reject downstream outcomes.

    A governed pre-pulse time-series record is not itself a source checkpoint:
    callers must select exactly one positive ``time_series_sample_index``.  The
    SIMION time-series writer records velocities in mm/us; those fields are
    explicitly converted to the canonical m/s state basis here.  This loader
    deliberately returns only states observed alive at the selected checkpoint;
    the associated full-mother loss census remains a separate required receipt.
    """

    aliases = {
        "x_mm": ("x_mm", "position_x_mm"),
        "y_mm": ("y_mm", "position_y_mm"),
        "z_mm": ("z_mm", "position_z_mm"),
        "vx_m_per_s": ("vx_m_per_s", "velocity_x_m_s", "vx_mm_per_us"),
        "vy_m_per_s": ("vy_m_per_s", "velocity_y_m_s", "vy_mm_per_us"),
        "vz_m_per_s": ("vz_m_per_s", "velocity_z_m_s", "vz_mm_per_us"),
    }
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or rows[0] is None:
        raise ValueError("pre-pulse source table is empty")
    fields = set(rows[0])
    event_key = "event" if "event" in fields else "state_event" if "state_event" in fields else None
    time_key = "instrument_time_us" if "instrument_time_us" in fields else None
    if time_key is None or "particle_id" not in fields:
        raise ValueError(
            "pre-pulse source table lacks particle ID or instrument time"
        )
    time_series_event = "pre_pulse_time_series_state"
    # A manifest-bound restart state intentionally has no event column: it is
    # a single canonical source checkpoint, not a re-usable time series.  Its
    # caller must separately validate the materialization receipt.  Do not
    # confuse this with accepting arbitrary event-less CSV files.
    restart_columns = {
        "mass_amu", "charge_state", "position_x_mm", "position_y_mm",
        "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s",
        "kinetic_energy_eV",
    }
    if event_key is None:
        if time_series_sample_index is not None:
            raise ValueError("sample index is invalid for a canonical pre-pulse restart")
        if not restart_columns.issubset(fields):
            raise ValueError("event-less pre-pulse source is not a canonical restart state")
        pulse_eligibility = np.ones(len(rows), dtype=bool)
    else:
        event_values = {row[event_key] for row in rows}
        if event_values == {time_series_event}:
            if time_series_sample_index is None or time_series_sample_index < 1:
                raise ValueError(
                    "pre-pulse time-series source requires one positive sample index"
                )
            if "sample_index" not in fields or "survival_status" not in fields:
                raise ValueError("pre-pulse time-series source lacks sample/status fields")
            rows = [
                row for row in rows
                if int(row["sample_index"]) == time_series_sample_index
            ]
            if not rows:
                raise ValueError("pre-pulse time-series sample index is absent")
            if any(row["survival_status"].strip().lower() != "alive" for row in rows):
                raise ValueError("selected pre-pulse time-series state is not alive")
            pulse_eligibility = np.ones(len(rows), dtype=bool)
        else:
            if time_series_sample_index is not None:
                raise ValueError("sample index is only valid for a pre-pulse time-series source")
            if "pulse_eligibility" not in fields:
                raise ValueError("pre-pulse source table lacks pulse eligibility")
            pulse_eligibility = None
    resolved = {
        name: next((item for item in choices if item in fields), None)
        for name, choices in aliases.items()
    }
    if any(value is None for value in resolved.values()):
        raise ValueError("pre-pulse source table lacks canonical six-dimensional state")
    allowed_events = {"pre_pulse_state", "accelerator_pre_pulse", time_series_event}
    if event_key is not None and any(row[event_key] not in allowed_events for row in rows):
        raise ValueError("source table is not an OA pre-pulse checkpoint")
    identifiers = np.asarray([int(row["particle_id"]) for row in rows], dtype=np.int64)
    if np.any(identifiers < 1) or np.unique(identifiers).size != identifiers.size:
        raise ValueError("pre-pulse source particle IDs must be unique positive integers")
    times = np.asarray([float(row[time_key]) for row in rows], dtype=float)
    if not np.isfinite(times).all() or not np.allclose(times, times[0], rtol=0.0, atol=1e-12):
        raise ValueError("pre-pulse source states must share one instrument time")
    state = np.column_stack([
        np.asarray([float(row[str(resolved[name])]) for row in rows], dtype=float)
        * (1000.0 if str(resolved[name]).endswith("_mm_per_us") else 1.0)
        for name in aliases
    ])
    if not np.isfinite(state).all():
        raise ValueError("pre-pulse source state must be finite")
    if pulse_eligibility is None:
        eligibility = np.asarray(
            [
                {"eligible": True, "ineligible": False}.get(
                    row["pulse_eligibility"].strip().lower(), None
                )
                for row in rows
            ],
            dtype=object,
        )
        if any(value is None for value in eligibility):
            raise ValueError("pulse eligibility must be eligible or ineligible")
    else:
        eligibility = pulse_eligibility
    return FrozenPrePulseSource(
        identifiers, state, np.asarray(eligibility, dtype=bool), float(times[0])
    )


def _polynomial_features(values: NDArray[np.float64], degree: int) -> NDArray[np.float64]:
    if degree not in (1, 2):
        raise ValueError("only affine and restricted quadratic source models are supported")
    columns = [np.ones(values.shape[0]), *[values[:, index] for index in range(values.shape[1])]]
    if degree == 2:
        columns.extend(
            values[:, left] * values[:, right]
            for left in range(values.shape[1])
            for right in range(left, values.shape[1])
        )
    return np.column_stack(columns)


def fit_source_condition_model(
    condition: NDArray[np.float64] | Sequence[Sequence[float]],
    state: NDArray[np.float64] | Sequence[Sequence[float]],
    *,
    condition_names: Sequence[str],
    state_names: Sequence[str],
    degree: int,
    pulse_eligible_fraction: float = 1.0,
) -> SourceConditionModel:
    """Fit a detector-blind conditional source model with shrinkage covariance."""

    condition_values = _matrix(condition, "condition")
    state_values = _matrix(state, "state")
    if condition_values.shape[0] != state_values.shape[0]:
        raise ValueError("condition and state must have the same row count")
    if len(condition_names) != condition_values.shape[1] or len(state_names) != state_values.shape[1]:
        raise ValueError("state or condition names do not match array columns")
    if not math.isfinite(pulse_eligible_fraction) or not 0.0 < pulse_eligible_fraction <= 1.0:
        raise ValueError("pulse_eligible_fraction must lie in (0, 1]")
    if condition_values.shape[0] <= _polynomial_features(condition_values[:1], degree).shape[1]:
        raise ValueError("source cohort is too small for the requested conditional model")
    center = np.mean(condition_values, axis=0)
    scale = np.std(condition_values, axis=0, ddof=0)
    if np.any(scale <= np.finfo(float).eps):
        raise ValueError("condition coordinates must have non-zero scale")
    features = _polynomial_features((condition_values - center) / scale, degree)
    coefficients, _, rank, _ = np.linalg.lstsq(features, state_values, rcond=None)
    if rank < features.shape[1]:
        raise ValueError("conditional model design matrix is rank deficient")
    residual = state_values - features @ coefficients
    covariance = residual.T @ residual / residual.shape[0]
    trace_scale = float(np.trace(covariance) / covariance.shape[0])
    covariance = 0.95 * covariance + 0.05 * trace_scale * np.eye(covariance.shape[0])
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    if np.any(eigenvalues <= 0.0):
        raise ValueError("regularized covariance is not positive definite")
    factor = eigenvectors @ np.diag(np.sqrt(eigenvalues))
    mahalanobis = np.sum(np.linalg.solve(factor, residual.T) ** 2, axis=0)
    # A sample quantile would force this fraction to about five percent by
    # construction.  Use the reference chi-square tail instead so that C1 can
    # distinguish a genuinely heavy residual tail from a near-Gaussian cloud.
    cutoff = float(chi2.ppf(0.975, df=residual.shape[1]))
    name_to_index = {name: index for index, name in enumerate(state_names)}

    def emittance(position: str, velocity: str) -> float | None:
        if position not in name_to_index or velocity not in name_to_index:
            return None
        plane = state_values[:, [name_to_index[position], name_to_index[velocity]]]
        determinant = float(np.linalg.det(np.cov(plane, rowvar=False, ddof=0)))
        return math.sqrt(max(0.0, determinant))

    return SourceConditionModel(
        tuple(condition_names), tuple(state_names), degree, center, scale,
        coefficients, covariance, factor, state_values.shape[0],
        float(np.mean(mahalanobis > cutoff)), np.sqrt(np.mean(residual * residual, axis=0)),
        pulse_eligible_fraction,
        emittance("x_mm", "vx_m_per_s"),
        emittance("y_mm", "vy_m_per_s"),
    )


def assess_source_condition(
    *,
    development_condition: NDArray[np.float64] | Sequence[Sequence[float]],
    development_state: NDArray[np.float64] | Sequence[Sequence[float]],
    validation_condition: NDArray[np.float64] | Sequence[Sequence[float]],
    validation_state: NDArray[np.float64] | Sequence[Sequence[float]],
    condition_names: Sequence[str],
    state_names: Sequence[str],
    pulse_eligible_fraction: float,
    covariance_bin_count: int = 4,
    bootstrap_replicates: int = 200,
    bootstrap_seed: int = 20260825,
) -> SourceConditionAssessment:
    """Select a blind source model and quantify C1 covariance/mode stability.

    The caller must provide only the development and validation cohorts.  This
    deliberate interface makes it impossible to use an optimization or locked
    cohort for model selection by accident.
    """

    if covariance_bin_count < 2:
        raise ValueError("covariance_bin_count must be at least two")
    if bootstrap_replicates < 1:
        raise ValueError("bootstrap_replicates must be positive")
    development_condition_values = _matrix(development_condition, "development_condition")
    development_state_values = _matrix(development_state, "development_state")
    validation_condition_values = _matrix(validation_condition, "validation_condition")
    validation_state_values = _matrix(validation_state, "validation_state")
    candidates = tuple(
        fit_source_condition_model(
            development_condition_values,
            development_state_values,
            condition_names=condition_names,
            state_names=state_names,
            degree=degree,
            pulse_eligible_fraction=pulse_eligible_fraction,
        )
        for degree in (1, 2)
    )
    selected = choose_detector_blind_model(
        validation_condition_values, validation_state_values, candidates
    )
    residual = development_state_values - selected.predict_mean(development_condition_values)
    ordering = np.argsort(development_condition_values[:, 0], kind="stable")
    groups = np.array_split(ordering, covariance_bin_count)
    if any(group.size < 2 for group in groups):
        raise ValueError("development cohort is too small for covariance bins")
    covariance_bins = tuple(
        CovarianceBin(
            float(np.min(development_condition_values[group, 0])),
            float(np.max(development_condition_values[group, 0])),
            int(group.size),
            np.cov(residual[group], rowvar=False, ddof=0),
        )
        for group in groups
    )
    eigenvalues, eigenvectors = np.linalg.eigh(selected.covariance)
    descending = np.argsort(eigenvalues)[::-1]
    mode_variance = eigenvalues[descending]
    reference_modes = eigenvectors[:, descending]
    generator = np.random.default_rng(bootstrap_seed)
    alignments = np.empty((bootstrap_replicates, residual.shape[1]), dtype=float)
    for index in range(bootstrap_replicates):
        sample = residual[generator.integers(0, residual.shape[0], residual.shape[0])]
        values, vectors = np.linalg.eigh(np.cov(sample, rowvar=False, ddof=0))
        modes = vectors[:, np.argsort(values)[::-1]]
        alignments[index] = np.abs(np.sum(reference_modes * modes, axis=0))
    return SourceConditionAssessment(
        selected, covariance_bins, mode_variance, np.quantile(alignments, 0.025, axis=0)
    )


def choose_detector_blind_model(
    validation_condition: NDArray[np.float64],
    validation_state: NDArray[np.float64],
    models: Sequence[SourceConditionModel],
) -> SourceConditionModel:
    """Choose the lowest validation MSE model; detector metrics are unavailable here."""

    if not models:
        raise ValueError("at least one source model is required")
    state_values = _matrix(validation_state, "validation_state")
    scores = []
    for model in models:
        if state_values.shape[1] != len(model.state_names):
            raise ValueError("validation state does not match a source model")
        predicted = model.predict_mean(validation_condition)
        scores.append(float(np.mean((state_values - predicted) ** 2)))
    return models[int(np.argmin(scores))]


def _rank_tolerance(
    singular_values: NDArray[np.float64], shape: tuple[int, int], relative: float | None
) -> float:
    """Return the frozen absolute SVD cutoff for one scaled matrix."""

    if relative is not None and (not math.isfinite(relative) or relative <= 0.0):
        raise ValueError("rank_relative_tolerance must be finite and positive")
    leading = float(singular_values[0]) if singular_values.size else 1.0
    factor = relative if relative is not None else max(shape) * np.finfo(float).eps
    return factor * leading


def _null_space(
    matrix: NDArray[np.float64], column_count: int, relative_tolerance: float | None
) -> NDArray[np.float64]:
    if matrix.size == 0:
        return np.eye(column_count)
    _, singular, vectors_t = np.linalg.svd(matrix, full_matrices=True)
    tolerance = _rank_tolerance(singular, matrix.shape, relative_tolerance)
    rank = int(np.sum(singular > tolerance))
    return vectors_t[rank:].T.copy()


def stack_focusability_problems(
    problems: Sequence[FocusabilityProblem],
) -> FocusabilityProblem:
    """Stack frozen condition bins into one source-weighted local problem.

    All bins must use the same scaled control coordinates and equality
    constraints.  Their state dimensions may differ, but each block retains its
    own covariance factor; this is the executable form of the theory's
    ``A_stack``/``b_stack`` construction.
    """

    if not problems:
        raise ValueError("at least one focusability bin is required")
    first = problems[0]
    scale = _vector(first.parameter_scale, "parameter_scale")
    constraints = np.asarray(first.constraint_jacobian, dtype=float)
    if constraints.ndim != 2 or constraints.shape[1] != scale.size:
        raise ValueError("first constraint Jacobian has an invalid shape")
    for problem in problems:
        if not np.allclose(_vector(problem.parameter_scale, "parameter_scale"), scale):
            raise ValueError("stacked bins must have identical parameter scales")
        if not np.allclose(np.asarray(problem.constraint_jacobian, dtype=float), constraints):
            raise ValueError("stacked bins must have identical constraint Jacobians")
        if problem.lower_eta is not None or problem.upper_eta is not None or problem.trust_radius is not None:
            raise ValueError("bounds belong to the stacked problem, not individual bins")
        if problem.rank_relative_tolerance != first.rank_relative_tolerance:
            raise ValueError("stacked bins must have one rank tolerance")
    total_dimension = sum(_vector(item.time_gradient, "time_gradient").size for item in problems)
    factor = np.zeros((total_dimension, total_dimension), dtype=float)
    cursor = 0
    for item in problems:
        item_factor = _matrix(item.source_factor, "source_factor")
        next_cursor = cursor + item_factor.shape[0]
        factor[cursor:next_cursor, cursor:next_cursor] = item_factor
        cursor = next_cursor
    return FocusabilityProblem(
        time_gradient=np.concatenate([_vector(item.time_gradient, "time_gradient") for item in problems]),
        design_response=np.vstack([_matrix(item.design_response, "design_response") for item in problems]),
        source_factor=factor,
        constraint_jacobian=constraints,
        parameter_scale=scale,
        rank_relative_tolerance=first.rank_relative_tolerance,
    )


def evaluate_focusability(problem: FocusabilityProblem) -> PredictionResult:
    """Solve the local source-whitened constrained QP and report its scope-limited floor."""

    gradient = _vector(problem.time_gradient, "time_gradient")
    response = _matrix(problem.design_response, "design_response")
    factor = _matrix(problem.source_factor, "source_factor")
    constraints = np.asarray(problem.constraint_jacobian, dtype=float)
    scale = _vector(problem.parameter_scale, "parameter_scale")
    if response.shape[0] != gradient.size or factor.shape != (gradient.size, gradient.size):
        raise ValueError("state dimensions of g, G, and L must agree")
    if response.shape[1] != scale.size or np.any(scale <= 0.0):
        raise ValueError("parameter scale must be positive and match G")
    if constraints.ndim != 2 or constraints.shape[1] != scale.size or not np.isfinite(constraints).all():
        raise ValueError("constraint Jacobian has an invalid shape")
    scaled_response = response * scale[np.newaxis, :]
    null_space = _null_space(
        constraints, scale.size, problem.rank_relative_tolerance
    )
    b = factor.T @ gradient
    a = factor.T @ scaled_response @ null_space
    singular = np.linalg.svd(a, compute_uv=False)
    tolerance = _rank_tolerance(
        singular, a.shape, problem.rank_relative_tolerance
    )
    rank = int(np.sum(singular > tolerance))
    condition_number = math.inf if rank == 0 else float(singular[0] / singular[rank - 1])
    eta_reference = (
        np.zeros(0, dtype=float)
        if null_space.shape[1] == 0
        else np.linalg.lstsq(a, -b, rcond=tolerance)[0]
    )
    reference_variance = float(np.dot(b + a @ eta_reference, b + a @ eta_reference))
    lower = problem.lower_eta if problem.lower_eta is not None else np.full(null_space.shape[1], -np.inf)
    upper = problem.upper_eta if problem.upper_eta is not None else np.full(null_space.shape[1], np.inf)
    lower_values, upper_values = np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
    if (
        lower_values.ndim != 1
        or upper_values.ndim != 1
        or not np.all(np.isfinite(lower_values) | np.isinf(lower_values))
        or not np.all(np.isfinite(upper_values) | np.isinf(upper_values))
    ):
        raise ValueError("eta bounds must be finite or infinite vectors")
    if lower_values.shape != eta_reference.shape or upper_values.shape != eta_reference.shape or np.any(lower_values > upper_values):
        raise ValueError("eta bounds do not match the feasible control dimension")
    radius = problem.trust_radius
    if radius is not None and (not math.isfinite(radius) or radius <= 0.0):
        raise ValueError("trust_radius must be finite and positive")
    objective = lambda eta: float(np.dot(b + a @ eta, b + a @ eta))
    constraints_qp = [] if radius is None else [{"type": "ineq", "fun": lambda eta: radius**2 - float(np.dot(eta, eta))}]
    if eta_reference.size == 0:
        eta = eta_reference
    else:
        solution = minimize(objective, np.clip(eta_reference, lower_values, upper_values), method="SLSQP", bounds=list(zip(lower_values, upper_values, strict=True)), constraints=constraints_qp, options={"ftol": 1e-12, "maxiter": 500})
        if not solution.success:
            raise ValueError(f"bounded focusability QP failed: {solution.message}")
        eta = np.asarray(solution.x, dtype=float)
    active = tuple(
        name for name, values in (("lower", np.isclose(eta, lower_values)), ("upper", np.isclose(eta, upper_values)))
        if bool(np.any(values))
    ) + (("trust_radius",) if radius is not None and math.isclose(float(np.linalg.norm(eta)), radius, rel_tol=1e-8, abs_tol=1e-10) else ())
    initial = float(np.dot(b, b))
    predicted = objective(eta)
    return PredictionResult(
        eta, null_space, singular, rank, condition_number, initial, predicted,
        reference_variance, 0.0 if initial == 0.0 else 1.0 - reference_variance / initial,
        active, float(np.linalg.norm(constraints @ (null_space @ eta))), tolerance,
    )
