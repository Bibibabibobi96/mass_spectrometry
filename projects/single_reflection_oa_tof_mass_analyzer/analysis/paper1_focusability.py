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
    particle_ids: Iterable[int], *, salt: str
) -> tuple[CohortAssignment, ...]:
    """Split unique IDs by SHA-256 without consulting any detector-level outcome."""

    if not salt:
        raise ValueError("cohort salt must be non-empty")
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
        role = (
            "development" if bucket < 0.50 else "validation" if bucket < 0.70
            else "optimization" if bucket < 0.85 else "locked_test"
        )
        result.append(CohortAssignment(identifier, role))
    if not result:
        raise ValueError("at least one particle ID is required")
    return tuple(result)


def load_frozen_pre_pulse_source(path: Path) -> FrozenPrePulseSource:
    """Load one shared-time OA pre-pulse state table and reject downstream outcomes."""

    aliases = {
        "x_mm": ("x_mm", "position_x_mm"), "y_mm": ("y_mm", "position_y_mm"),
        "z_mm": ("z_mm", "position_z_mm"), "vx_m_per_s": ("vx_m_per_s", "velocity_x_m_s"),
        "vy_m_per_s": ("vy_m_per_s", "velocity_y_m_s"), "vz_m_per_s": ("vz_m_per_s", "velocity_z_m_s"),
    }
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or rows[0] is None:
        raise ValueError("pre-pulse source table is empty")
    fields = set(rows[0])
    event_key = "event" if "event" in fields else "state_event" if "state_event" in fields else None
    time_key = "instrument_time_us" if "instrument_time_us" in fields else None
    if event_key is None or time_key is None or "particle_id" not in fields:
        raise ValueError("pre-pulse source table lacks particle ID, event, or instrument time")
    resolved = {name: next((item for item in choices if item in fields), None) for name, choices in aliases.items()}
    if any(value is None for value in resolved.values()):
        raise ValueError("pre-pulse source table lacks canonical six-dimensional state")
    allowed_events = {"pre_pulse_state", "accelerator_pre_pulse"}
    if any(row[event_key] not in allowed_events for row in rows):
        raise ValueError("source table is not an OA pre-pulse checkpoint")
    identifiers = np.asarray([int(row["particle_id"]) for row in rows], dtype=np.int64)
    if np.any(identifiers < 1) or np.unique(identifiers).size != identifiers.size:
        raise ValueError("pre-pulse source particle IDs must be unique positive integers")
    times = np.asarray([float(row[time_key]) for row in rows], dtype=float)
    if not np.isfinite(times).all() or not np.allclose(times, times[0], rtol=0.0, atol=1e-12):
        raise ValueError("pre-pulse source states must share one instrument time")
    state = np.column_stack([
        np.asarray([float(row[str(resolved[name])]) for row in rows], dtype=float)
        for name in aliases
    ])
    if not np.isfinite(state).all():
        raise ValueError("pre-pulse source state must be finite")
    return FrozenPrePulseSource(identifiers, state, float(times[0]))


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
) -> SourceConditionModel:
    """Fit a detector-blind conditional source model with shrinkage covariance."""

    condition_values = _matrix(condition, "condition")
    state_values = _matrix(state, "state")
    if condition_values.shape[0] != state_values.shape[0]:
        raise ValueError("condition and state must have the same row count")
    if len(condition_names) != condition_values.shape[1] or len(state_names) != state_values.shape[1]:
        raise ValueError("state or condition names do not match array columns")
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
    cutoff = float(np.quantile(mahalanobis, 0.95))
    return SourceConditionModel(
        tuple(condition_names), tuple(state_names), degree, center, scale,
        coefficients, covariance, factor, state_values.shape[0],
        float(np.mean(mahalanobis > cutoff)), np.sqrt(np.mean(residual * residual, axis=0)),
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


def _null_space(matrix: NDArray[np.float64], column_count: int) -> NDArray[np.float64]:
    if matrix.size == 0:
        return np.eye(column_count)
    _, singular, vectors_t = np.linalg.svd(matrix, full_matrices=True)
    tolerance = max(matrix.shape) * np.finfo(float).eps * (singular[0] if singular.size else 1.0)
    rank = int(np.sum(singular > tolerance))
    return vectors_t[rank:].T.copy()


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
    null_space = _null_space(constraints, scale.size)
    if null_space.shape[1] == 0:
        raise ValueError("constraints leave no feasible control direction")
    b = factor.T @ gradient
    a = factor.T @ scaled_response @ null_space
    singular = np.linalg.svd(a, compute_uv=False)
    tolerance = max(a.shape) * np.finfo(float).eps * (singular[0] if singular.size else 1.0)
    rank = int(np.sum(singular > tolerance))
    condition_number = math.inf if rank == 0 else float(singular[0] / singular[rank - 1])
    eta_reference, *_ = np.linalg.lstsq(a, -b, rcond=tolerance)
    reference_variance = float(np.dot(b + a @ eta_reference, b + a @ eta_reference))
    lower = problem.lower_eta if problem.lower_eta is not None else np.full(null_space.shape[1], -np.inf)
    upper = problem.upper_eta if problem.upper_eta is not None else np.full(null_space.shape[1], np.inf)
    lower_values, upper_values = _vector(lower, "lower_eta"), _vector(upper, "upper_eta")
    if lower_values.shape != eta_reference.shape or upper_values.shape != eta_reference.shape or np.any(lower_values > upper_values):
        raise ValueError("eta bounds do not match the feasible control dimension")
    radius = problem.trust_radius
    if radius is not None and (not math.isfinite(radius) or radius <= 0.0):
        raise ValueError("trust_radius must be finite and positive")
    objective = lambda eta: float(np.dot(b + a @ eta, b + a @ eta))
    constraints_qp = [] if radius is None else [{"type": "ineq", "fun": lambda eta: radius**2 - float(np.dot(eta, eta))}]
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
        active, float(np.linalg.norm(constraints @ (null_space @ eta))),
    )
