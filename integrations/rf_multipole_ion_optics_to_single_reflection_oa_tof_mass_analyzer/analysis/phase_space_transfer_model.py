"""Solver-independent local transfer models and detector-blind acceptance gates.

The quadratic map uses the canonical local phase-space order
``(x, y, z, vx, vy, vz)``.  The acceptance-window functions intentionally use
only theoretical source coordinates and a predicted real-minus-ideal field
timing error; detector arrivals and hit labels are not accepted by that API.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from numbers import Integral
from typing import Mapping, Sequence

import numpy as np


PHASE_SPACE_NAMES = (
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_per_s",
    "vy_m_per_s",
    "vz_m_per_s",
)
CONTINUOUS_TARGET_NAMES = (
    "focus_time_ns",
    "detector_time_ns",
    "detector_radius_mm",
)
ACCEPTANCE_FEATURE_NAMES = (
    "x_mm",
    "y_mm",
    "z_mm",
    "angle_x_mrad",
    "angle_y_mrad",
)
FIELD_ERROR_PREDICTION_ROLE = "ideal_field_minus_real_field_predicted_time_error"
CAMPAIGN_ACCEPTANCE_FEATURE_ORDER = ("x", "y", "z", "angle_x", "angle_y")
ACCEPTANCE_WINDOW_PROFILE_ROLE = "rf_oatof_theoretical_acceptance_window_profile"


class TransferModelContractError(ValueError):
    """Raised when a transfer-model input violates its machine contract."""


class AcceptanceCoverageError(TransferModelContractError):
    """Raised when a frozen theoretical window covers too little eligible beam."""


@dataclass(frozen=True)
class FixedIdSplit:
    """Order-independent train/validation identity assignment."""

    train_ids: tuple[int | str, ...]
    validation_ids: tuple[int | str, ...]
    seed: int
    validation_fraction: float


@dataclass(frozen=True)
class TransferPredictions:
    """Continuous map outputs and the fitted hit/loss classification."""

    focus_time_ns: np.ndarray
    detector_time_ns: np.ndarray
    detector_radius_mm: np.ndarray
    hit_score: np.ndarray
    predicted_hit: np.ndarray


@dataclass(frozen=True)
class SecondOrderTransferModel:
    """A complete local six-dimensional second-order polynomial map."""

    phase_center: np.ndarray
    phase_scale: np.ndarray
    feature_names: tuple[str, ...]
    continuous_coefficients: np.ndarray
    hit_coefficients: np.ndarray
    split: FixedIdSplit

    def predict(self, phase_space: np.ndarray) -> TransferPredictions:
        """Predict times (ns), radius (mm), and hit/loss for phase-space rows."""
        phase = _finite_matrix(phase_space, 6, "phase_space")
        scaled = (phase - self.phase_center) / self.phase_scale
        design, names = quadratic_design_matrix(scaled)
        if names != self.feature_names:
            raise RuntimeError("quadratic feature identity changed")
        continuous = design @ self.continuous_coefficients
        hit_score = np.clip(design @ self.hit_coefficients, 0.0, 1.0)
        return TransferPredictions(
            focus_time_ns=continuous[:, 0],
            detector_time_ns=continuous[:, 1],
            detector_radius_mm=continuous[:, 2],
            hit_score=hit_score,
            predicted_hit=hit_score >= 0.5,
        )


@dataclass(frozen=True)
class TransferModelFit:
    """Fitted transfer model plus fixed-split validation metrics."""

    model: SecondOrderTransferModel
    train_rmse: Mapping[str, float | None]
    validation_rmse: Mapping[str, float | None]
    continuous_label_census: Mapping[str, "ContinuousLabelCensus"]
    train_hit_accuracy: float
    validation_hit_accuracy: float


@dataclass(frozen=True)
class ContinuousLabelCensus:
    """Finite-label census for one output without changing the ID population."""

    population_count: int
    train_population_count: int
    validation_population_count: int
    finite_label_count: int
    train_finite_label_count: int
    validation_finite_label_count: int


@dataclass(frozen=True)
class TheoreticalAcceptanceWindow:
    """Frozen theory-centred, detector-blind five-dimensional box."""

    feature_names: tuple[str, ...]
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    center: np.ndarray
    homothetic_scale: float
    final_time_budget_ns: float
    prediction_role: str
    detector_results_used: bool
    synthetic_grid_count: int
    synthetic_grid_coverage_fraction: float
    synthetic_grid_sha256: str

    def contains(self, phase_coordinates: np.ndarray) -> np.ndarray:
        """Return membership for x/y/z and two-angle rows."""
        values = _finite_matrix(phase_coordinates, 5, "phase_coordinates")
        tolerance = 1.0e-12 * np.maximum(1.0, np.maximum(np.abs(self.lower_bounds), np.abs(self.upper_bounds)))
        return np.all(
            (values >= self.lower_bounds - tolerance) & (values <= self.upper_bounds + tolerance),
            axis=1,
        )


@dataclass(frozen=True)
class AcceptanceCoverage:
    """Coverage of a frozen window over the complete pulse-eligible cohort."""

    pulse_eligible_count: int
    accepted_count: int
    coverage_fraction: float
    accepted_particle_ids: tuple[int | str, ...]
    membership: np.ndarray


@dataclass(frozen=True)
class ConstrainedVoltageCandidate:
    """One PA-reusing voltage candidate generated from declared basis weights."""

    candidate_id: str
    coefficients: np.ndarray
    electrode_voltages_v: np.ndarray
    fixed_endpoint_indices: tuple[int, ...]
    pa_rebuild_required: bool = False


@dataclass(frozen=True)
class FrozenCampaignTransferSettings:
    """Pure-analysis settings projected from the governed campaign."""

    campaign_id: str
    execution_state: str
    campaign_feature_order: tuple[str, ...]
    model_feature_order: tuple[str, ...]
    final_time_budget_ns: float
    minimum_pulse_eligible_coverage: float
    mother_sample_count: int
    validation_count: int
    split_seed: int
    candidate_count_maximum: int


def _finite_matrix(values: np.ndarray, columns: int, label: str) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.ndim != 2 or result.shape[1] != columns or result.shape[0] < 1:
        raise TransferModelContractError(f"{label} must have shape (N, {columns}) with N >= 1")
    if not np.all(np.isfinite(result)):
        raise TransferModelContractError(f"{label} must contain only finite values")
    return result


def campaign_transfer_settings(
    campaign: Mapping[str, object],
) -> FrozenCampaignTransferSettings:
    """Validate and project frozen analysis settings without enabling execution.

    The campaign's deterministic N=100 screening size fixes the validation-set
    cardinality, while a hash of the complete optimization contract fixes the
    identity ranking seed.  This does not turn the screening prefix into a
    validation set: the validation identities remain the hash-ranked split.
    """
    if (
        campaign.get("schema_version") != 2
        or campaign.get("role") != "rf_multipole_oatof_experiment_campaign"
        or campaign.get("campaign_id") != "pulse_resolution_optimization"
    ):
        raise TransferModelContractError("campaign is not the pulse-resolution optimization contract")
    contract = campaign.get("pulse_resolution_optimization")
    if not isinstance(contract, Mapping):
        raise TransferModelContractError("campaign lacks pulse-resolution optimization settings")
    if contract.get("execution_state") not in {
        "planning_only_until_adapter_support",
        "n100_baseline_registration_only",
        "n100_arm8_closed_global_field_screening",
    }:
        raise TransferModelContractError("transfer analysis cannot make a pulse-resolution campaign executable")
    clock = contract.get("clock_contract")
    if not isinstance(clock, Mapping) or (
        clock.get("resolution_time_basis") != "detector_time_minus_pulse_effective_time"
        or clock.get("absolute_instrument_clock_is_resolution_claim") is not False
    ):
        raise TransferModelContractError("campaign pulse-effective clock contract differs")
    acceptance = contract.get("acceptance_window")
    if not isinstance(acceptance, Mapping):
        raise TransferModelContractError("campaign acceptance-window settings are absent")
    feature_order = tuple(acceptance.get("allowed_coordinates", ()))
    if feature_order != CAMPAIGN_ACCEPTANCE_FEATURE_ORDER:
        raise TransferModelContractError("campaign acceptance feature order must be x,y,z,angle_x,angle_y")
    if (
        acceptance.get("selection_uses_detector_outcome") is not False
        or acceptance.get("freeze_before_real_beam_application") is not True
        or acceptance.get("outside_window_remains_in_full_beam") is not True
    ):
        raise TransferModelContractError("campaign acceptance window is not detector-blind and frozen")
    budget = float(acceptance.get("tof_error_budget_ns", np.nan))
    coverage = float(acceptance.get("minimum_pulse_eligible_coverage", np.nan))
    if budget != 0.537 or coverage != 0.70:
        raise TransferModelContractError("campaign acceptance budget or coverage differs from the model")
    population = contract.get("population_contract")
    constraints = contract.get("optimization_constraints")
    if not isinstance(population, Mapping) or not isinstance(constraints, Mapping):
        raise TransferModelContractError("campaign population or optimization settings are absent")
    mother_count = int(population.get("mother_sample_count", 0))
    validation_count = int(population.get("screening_prefix_count", 0))
    candidate_count = int(constraints.get("candidate_count_maximum", 0))
    if (
        mother_count != 1000
        or validation_count != 100
        or population.get("screening_is_deterministic_prefix") is not True
        or candidate_count != 5
    ):
        raise TransferModelContractError("campaign population or candidate limits differ")
    canonical_contract = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    split_seed = int.from_bytes(sha256(canonical_contract).digest()[:8], "big")
    return FrozenCampaignTransferSettings(
        campaign_id="pulse_resolution_optimization",
        execution_state=str(contract["execution_state"]),
        campaign_feature_order=feature_order,
        model_feature_order=ACCEPTANCE_FEATURE_NAMES,
        final_time_budget_ns=budget,
        minimum_pulse_eligible_coverage=coverage,
        mother_sample_count=mother_count,
        validation_count=validation_count,
        split_seed=split_seed,
        candidate_count_maximum=candidate_count,
    )


def campaign_fixed_id_split(campaign: Mapping[str, object], particle_ids: Sequence[int | str]) -> FixedIdSplit:
    """Build the campaign-frozen ID split for the complete N=1000 mother sample."""
    settings = campaign_transfer_settings(campaign)
    ids = _validated_ids(particle_ids)
    if len(ids) != settings.mother_sample_count:
        raise TransferModelContractError("campaign transfer split requires the complete N=1000 mother sample")
    return fixed_id_train_validation_split(
        ids,
        validation_fraction=settings.validation_count / settings.mother_sample_count,
        seed=settings.split_seed,
    )


def phase_space_to_acceptance_coordinates(phase_space: np.ndarray) -> np.ndarray:
    """Map x/y/z/vx/vy/vz rows to x/y/z and global-z-referenced angles.

    Positions remain in mm, velocities must be in m/s, and angles are returned
    in mrad using ``atan2(vx, vz)`` and ``atan2(vy, vz)``.  Backward or stalled
    particles have no valid forward acceptance angle and therefore fail closed.
    """
    phase = _finite_matrix(phase_space, 6, "phase_space")
    longitudinal_velocity = phase[:, 5]
    if np.any(longitudinal_velocity <= 0.0):
        raise TransferModelContractError("acceptance angles require strictly positive global vz")
    return np.column_stack(
        [
            phase[:, :3],
            1000.0 * np.arctan2(phase[:, 3], longitudinal_velocity),
            1000.0 * np.arctan2(phase[:, 4], longitudinal_velocity),
        ]
    )


def freeze_campaign_theoretical_acceptance_window(
    campaign: Mapping[str, object],
    synthetic_phase_space: np.ndarray,
    predicted_field_error_time_ns: Sequence[float],
    theory_center: Sequence[float],
    theory_half_widths: Sequence[float],
) -> TheoreticalAcceptanceWindow:
    """Freeze the detector-blind window using only campaign-governed settings."""
    settings = campaign_transfer_settings(campaign)
    acceptance_coordinates = phase_space_to_acceptance_coordinates(synthetic_phase_space)
    return freeze_theoretical_acceptance_window(
        acceptance_coordinates,
        predicted_field_error_time_ns,
        theory_center,
        theory_half_widths,
        final_time_budget_ns=settings.final_time_budget_ns,
    )


def evaluate_campaign_pulse_eligible_coverage(
    campaign: Mapping[str, object],
    window: TheoreticalAcceptanceWindow,
    particle_ids: Sequence[int | str],
    pulse_eligible_phase_space: np.ndarray,
) -> AcceptanceCoverage:
    """Apply a campaign-frozen window to the complete eligible phase space."""
    settings = campaign_transfer_settings(campaign)
    return evaluate_pulse_eligible_coverage(
        window,
        particle_ids,
        phase_space_to_acceptance_coordinates(pulse_eligible_phase_space),
        minimum_coverage_fraction=settings.minimum_pulse_eligible_coverage,
    )


def _validated_ids(particle_ids: Sequence[int | str]) -> tuple[int | str, ...]:
    ids = tuple(
        int(particle_id) if isinstance(particle_id, Integral) and not isinstance(particle_id, bool) else particle_id
        for particle_id in particle_ids
    )
    if len(ids) < 2:
        raise TransferModelContractError("at least two particle IDs are required")
    canonical: list[str] = []
    for particle_id in ids:
        if isinstance(particle_id, bool) or not isinstance(particle_id, (Integral, str)):
            raise TransferModelContractError("particle IDs must be integers or strings")
        if isinstance(particle_id, str) and not particle_id:
            raise TransferModelContractError("particle IDs cannot be empty")
        canonical.append(f"{type(particle_id).__name__}:{particle_id}")
    if len(canonical) != len(set(canonical)):
        raise TransferModelContractError("particle IDs must be unique")
    return ids


def fixed_id_train_validation_split(
    particle_ids: Sequence[int | str],
    *,
    validation_fraction: float = 0.2,
    seed: int = 20260812,
) -> FixedIdSplit:
    """Assign a stable exact-size split by hashing IDs, independent of row order."""
    ids = _validated_ids(particle_ids)
    fraction = float(validation_fraction)
    if not np.isfinite(fraction) or not 0.0 < fraction < 1.0:
        raise TransferModelContractError("validation_fraction must lie in (0, 1)")
    validation_count = min(len(ids) - 1, max(1, int(round(len(ids) * fraction))))

    def rank_key(particle_id: int | str) -> tuple[bytes, str]:
        identity = f"{type(particle_id).__name__}:{particle_id}"
        digest = sha256(f"{seed}:{identity}".encode("utf-8")).digest()
        return digest, identity

    ranked = sorted(ids, key=rank_key)
    validation = tuple(ranked[:validation_count])
    train = tuple(ranked[validation_count:])
    return FixedIdSplit(train, validation, int(seed), fraction)


def quadratic_feature_names() -> tuple[str, ...]:
    """Return intercept, all linear terms, squares, and pairwise interactions."""
    names = ["intercept", *PHASE_SPACE_NAMES]
    for first in range(len(PHASE_SPACE_NAMES)):
        for second in range(first, len(PHASE_SPACE_NAMES)):
            left, right = PHASE_SPACE_NAMES[first], PHASE_SPACE_NAMES[second]
            names.append(f"{left}^2" if first == second else f"{left}*{right}")
    return tuple(names)


def quadratic_design_matrix(phase_space: np.ndarray) -> tuple[np.ndarray, tuple[str, ...]]:
    """Expand six-dimensional rows to the complete 28-term quadratic basis."""
    phase = _finite_matrix(phase_space, 6, "phase_space")
    columns = [np.ones(phase.shape[0]), *(phase[:, index] for index in range(6))]
    for first in range(6):
        for second in range(first, 6):
            columns.append(phase[:, first] * phase[:, second])
    return np.column_stack(columns), quadratic_feature_names()


def _solve_ridge(design: np.ndarray, targets: np.ndarray, ridge: float) -> np.ndarray:
    if ridge == 0.0:
        return np.linalg.lstsq(design, targets, rcond=None)[0]
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    return np.linalg.solve(design.T @ design + penalty, design.T @ targets)


def fit_second_order_transfer_model(
    particle_ids: Sequence[int | str],
    phase_space: np.ndarray,
    continuous_targets: Mapping[str, Sequence[float]],
    hit_status: Sequence[bool | int],
    *,
    validation_fraction: float = 0.2,
    split_seed: int = 20260812,
    ridge: float = 0.0,
) -> TransferModelFit:
    """Fit the local map with a deterministic particle-ID train/validation split."""
    ids = _validated_ids(particle_ids)
    phase = _finite_matrix(phase_space, 6, "phase_space")
    if phase.shape[0] != len(ids):
        raise TransferModelContractError("phase-space rows must match particle IDs")
    if set(continuous_targets) != set(CONTINUOUS_TARGET_NAMES):
        raise TransferModelContractError("continuous targets must be focus time, detector time, and detector radius")
    target = np.column_stack([np.asarray(continuous_targets[name], dtype=float) for name in CONTINUOUS_TARGET_NAMES])
    hits = np.asarray(hit_status)
    if target.shape != (len(ids), 3) or np.any(np.isinf(target)):
        raise TransferModelContractError("continuous target rows must be finite or explicitly missing as NaN")
    if hits.shape != (len(ids),) or not np.all(np.isin(hits, [False, True, 0, 1])):
        raise TransferModelContractError("hit_status must contain one binary value per ID")
    regularization = float(ridge)
    if not np.isfinite(regularization) or regularization < 0.0:
        raise TransferModelContractError("ridge must be finite and nonnegative")

    split = fixed_id_train_validation_split(ids, validation_fraction=validation_fraction, seed=split_seed)
    train_ids = set(split.train_ids)
    train_mask = np.asarray([particle_id in train_ids for particle_id in ids])
    validation_mask = ~train_mask
    center = np.mean(phase[train_mask], axis=0)
    scale = np.std(phase[train_mask], axis=0, ddof=0)
    if np.any(scale <= 0.0):
        raise TransferModelContractError("every phase-space coordinate must vary in training")
    design, names = quadratic_design_matrix((phase - center) / scale)
    continuous_coefficients = np.empty((design.shape[1], len(CONTINUOUS_TARGET_NAMES)))
    label_census: dict[str, ContinuousLabelCensus] = {}
    finite_label_masks: dict[str, np.ndarray] = {}
    for target_index, target_name in enumerate(CONTINUOUS_TARGET_NAMES):
        finite_mask = np.isfinite(target[:, target_index])
        finite_train_mask = train_mask & finite_mask
        finite_validation_mask = validation_mask & finite_mask
        finite_label_masks[target_name] = finite_mask
        label_census[target_name] = ContinuousLabelCensus(
            population_count=len(ids),
            train_population_count=int(np.count_nonzero(train_mask)),
            validation_population_count=int(np.count_nonzero(validation_mask)),
            finite_label_count=int(np.count_nonzero(finite_mask)),
            train_finite_label_count=int(np.count_nonzero(finite_train_mask)),
            validation_finite_label_count=int(np.count_nonzero(finite_validation_mask)),
        )
        if np.count_nonzero(finite_train_mask) < design.shape[1]:
            raise TransferModelContractError(
                f"{target_name} requires at least {design.shape[1]} finite training labels "
                "for the complete second-order map"
            )
        continuous_coefficients[:, target_index] = _solve_ridge(
            design[finite_train_mask], target[finite_train_mask, target_index], regularization
        )
    hit_coefficients = _solve_ridge(design[train_mask], hits[train_mask].astype(float), regularization)
    model = SecondOrderTransferModel(
        phase_center=center,
        phase_scale=scale,
        feature_names=names,
        continuous_coefficients=continuous_coefficients,
        hit_coefficients=hit_coefficients,
        split=split,
    )
    predicted = model.predict(phase)
    predicted_continuous = np.column_stack(
        [predicted.focus_time_ns, predicted.detector_time_ns, predicted.detector_radius_mm]
    )

    def rmse(population_mask: np.ndarray) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for target_index, target_name in enumerate(CONTINUOUS_TARGET_NAMES):
            labelled_mask = population_mask & finite_label_masks[target_name]
            if not np.any(labelled_mask):
                result[target_name] = None
                continue
            residual = predicted_continuous[labelled_mask, target_index] - target[labelled_mask, target_index]
            result[target_name] = float(np.sqrt(np.mean(residual * residual)))
        return result

    def accuracy(mask: np.ndarray) -> float:
        return float(np.mean(predicted.predicted_hit[mask] == hits[mask].astype(bool)))

    return TransferModelFit(
        model=model,
        train_rmse=rmse(train_mask),
        validation_rmse=rmse(validation_mask),
        continuous_label_census=label_census,
        train_hit_accuracy=accuracy(train_mask),
        validation_hit_accuracy=accuracy(validation_mask),
    )


def _grid_digest(points: np.ndarray, errors_ns: np.ndarray) -> str:
    digest = sha256()
    digest.update(np.asarray(points, dtype="<f8").tobytes(order="C"))
    digest.update(np.asarray(errors_ns, dtype="<f8").tobytes(order="C"))
    return digest.hexdigest()


def freeze_theoretical_acceptance_window(
    synthetic_phase_grid: np.ndarray,
    predicted_field_error_time_ns: Sequence[float],
    theory_center: Sequence[float],
    theory_half_widths: Sequence[float],
    *,
    final_time_budget_ns: float = 0.537,
    prediction_role: str = FIELD_ERROR_PREDICTION_ROLE,
) -> TheoreticalAcceptanceWindow:
    """Freeze the largest sampled theory-centred homothetic box within budget.

    The synthetic grid must cover the declared source/angle box.  A shell is
    admitted only when every supplied synthetic point inside it respects the
    predicted field-error contribution to the final timing budget.
    """
    grid = _finite_matrix(synthetic_phase_grid, 5, "synthetic_phase_grid")
    errors = np.asarray(predicted_field_error_time_ns, dtype=float)
    center = np.asarray(theory_center, dtype=float)
    half_widths = np.asarray(theory_half_widths, dtype=float)
    budget = float(final_time_budget_ns)
    if errors.shape != (grid.shape[0],) or not np.all(np.isfinite(errors)):
        raise TransferModelContractError("predicted field-error times must be finite and complete")
    if center.shape != (5,) or not np.all(np.isfinite(center)):
        raise TransferModelContractError("theory_center must contain five finite values")
    if half_widths.shape != (5,) or not np.all(np.isfinite(half_widths)) or np.any(half_widths <= 0.0):
        raise TransferModelContractError("theory_half_widths must contain five positive values")
    if not np.isfinite(budget) or budget <= 0.0:
        raise TransferModelContractError("final_time_budget_ns must be positive")
    if prediction_role != FIELD_ERROR_PREDICTION_ROLE:
        raise TransferModelContractError("acceptance window requires the governed field-error prediction role")
    normalized_radius = np.max(np.abs((grid - center) / half_widths), axis=1)
    if np.any(normalized_radius > 1.0 + 1.0e-12):
        raise TransferModelContractError("synthetic grid lies outside the declared theoretical source box")
    if not np.any(np.all(np.isclose(grid, center, rtol=0.0, atol=1.0e-12), axis=1)):
        raise TransferModelContractError("synthetic grid must include the theoretical source centre")
    for axis in range(5):
        if not np.isclose(
            np.min(grid[:, axis]), center[axis] - half_widths[axis], rtol=0.0, atol=1.0e-12
        ) or not np.isclose(np.max(grid[:, axis]), center[axis] + half_widths[axis], rtol=0.0, atol=1.0e-12):
            raise TransferModelContractError("synthetic grid must span every declared theoretical bound")
    selected_scale: float | None = None
    selected_mask: np.ndarray | None = None
    for scale in np.unique(np.clip(normalized_radius, 0.0, 1.0)):
        mask = normalized_radius <= scale + 1.0e-12
        if np.max(np.abs(errors[mask])) <= budget:
            selected_scale, selected_mask = float(scale), mask
        else:
            break
    if selected_scale is None or selected_mask is None:
        raise TransferModelContractError("the theoretical source centre exceeds the final timing budget")
    extent = selected_scale * half_widths
    return TheoreticalAcceptanceWindow(
        feature_names=ACCEPTANCE_FEATURE_NAMES,
        lower_bounds=center - extent,
        upper_bounds=center + extent,
        center=center,
        homothetic_scale=selected_scale,
        final_time_budget_ns=budget,
        prediction_role=prediction_role,
        detector_results_used=False,
        synthetic_grid_count=grid.shape[0],
        synthetic_grid_coverage_fraction=float(np.mean(selected_mask)),
        synthetic_grid_sha256=_grid_digest(grid, errors),
    )


def evaluate_pulse_eligible_coverage(
    window: TheoreticalAcceptanceWindow,
    particle_ids: Sequence[int | str],
    pulse_eligible_phase_coordinates: np.ndarray,
    *,
    minimum_coverage_fraction: float = 0.70,
) -> AcceptanceCoverage:
    """Apply a previously frozen window to every pulse-eligible particle."""
    ids = _validated_ids(particle_ids)
    coordinates = _finite_matrix(pulse_eligible_phase_coordinates, 5, "pulse_eligible_phase_coordinates")
    if coordinates.shape[0] != len(ids):
        raise TransferModelContractError("eligible coordinates must match particle IDs")
    minimum = float(minimum_coverage_fraction)
    if not np.isfinite(minimum) or not 0.0 < minimum <= 1.0:
        raise TransferModelContractError("minimum coverage must lie in (0, 1]")
    membership = window.contains(coordinates)
    coverage = float(np.mean(membership))
    if coverage + 1.0e-15 < minimum:
        raise AcceptanceCoverageError(
            f"frozen theoretical window coverage {coverage:.6f} is below {minimum:.6f}; "
            "the window must not be narrowed or redefined from detector results"
        )
    return AcceptanceCoverage(
        pulse_eligible_count=len(ids),
        accepted_count=int(np.count_nonzero(membership)),
        coverage_fraction=coverage,
        accepted_particle_ids=tuple(
            particle_id for particle_id, accepted in zip(ids, membership, strict=True) if accepted
        ),
        membership=membership,
    )


def _acceptance_profile_digest(profile_without_digest: Mapping[str, object]) -> str:
    canonical = json.dumps(
        profile_without_digest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def build_theoretical_acceptance_window_profile(
    window: TheoreticalAcceptanceWindow,
    coverage: AcceptanceCoverage,
    *,
    minimum_coverage_fraction: float = 0.70,
    campaign_id: str | None = None,
) -> dict[str, object]:
    """Create a JSON-serializable, detector-blind frozen-window receipt."""
    if window.feature_names != ACCEPTANCE_FEATURE_NAMES:
        raise TransferModelContractError("acceptance window feature identity differs")
    if window.detector_results_used:
        raise TransferModelContractError("a detector-informed window cannot be serialized as theoretical")
    if window.prediction_role != FIELD_ERROR_PREDICTION_ROLE:
        raise TransferModelContractError("acceptance window has the wrong field-error prediction role")
    lower = np.asarray(window.lower_bounds, dtype=float)
    upper = np.asarray(window.upper_bounds, dtype=float)
    center = np.asarray(window.center, dtype=float)
    if (
        lower.shape != (5,)
        or upper.shape != (5,)
        or center.shape != (5,)
        or not np.all(np.isfinite(np.concatenate([lower, upper, center])))
        or np.any(lower > upper)
    ):
        raise TransferModelContractError("acceptance window bounds and centre must be finite five-vectors")
    minimum = float(minimum_coverage_fraction)
    if not np.isfinite(minimum) or not 0.0 < minimum <= 1.0:
        raise TransferModelContractError("minimum coverage must lie in (0, 1]")
    membership = np.asarray(coverage.membership)
    if membership.shape != (coverage.pulse_eligible_count,) or membership.dtype.kind != "b":
        raise TransferModelContractError("coverage membership must be one boolean per pulse-eligible particle")
    accepted_ids = _validated_ids(coverage.accepted_particle_ids)
    accepted_count = int(np.count_nonzero(membership))
    expected_fraction = accepted_count / coverage.pulse_eligible_count
    if (
        coverage.pulse_eligible_count < 1
        or coverage.accepted_count != accepted_count
        or len(accepted_ids) != accepted_count
        or not np.isclose(coverage.coverage_fraction, expected_fraction, rtol=0.0, atol=1.0e-15)
    ):
        raise TransferModelContractError("coverage census is internally inconsistent")
    if coverage.coverage_fraction + 1.0e-15 < minimum:
        raise AcceptanceCoverageError(
            f"frozen theoretical window coverage {coverage.coverage_fraction:.6f} is below {minimum:.6f}"
        )
    profile: dict[str, object] = {
        "schema_version": 1,
        "role": ACCEPTANCE_WINDOW_PROFILE_ROLE,
        "feature_order": list(ACCEPTANCE_FEATURE_NAMES),
        "bounds": {
            name: {"lower": float(lower[index]), "upper": float(upper[index])}
            for index, name in enumerate(ACCEPTANCE_FEATURE_NAMES)
        },
        "center": {name: float(center[index]) for index, name in enumerate(ACCEPTANCE_FEATURE_NAMES)},
        "homothetic_scale": float(window.homothetic_scale),
        "field_error_budget_ns": float(window.final_time_budget_ns),
        "field_error_prediction_role": window.prediction_role,
        "detector_blind_contract": {
            "detector_results_used": False,
            "selection_uses_detector_outcome": False,
            "freeze_before_real_beam_application": True,
            "outside_window_remains_in_full_beam": True,
        },
        "synthetic_grid": {
            "point_count": int(window.synthetic_grid_count),
            "accepted_fraction": float(window.synthetic_grid_coverage_fraction),
            "sha256": window.synthetic_grid_sha256,
        },
        "pulse_eligible_coverage": {
            "population_count": int(coverage.pulse_eligible_count),
            "accepted_count": int(coverage.accepted_count),
            "fraction": float(coverage.coverage_fraction),
            "minimum_required_fraction": minimum,
            "accepted_particle_ids": list(accepted_ids),
        },
    }
    if campaign_id is not None:
        if not isinstance(campaign_id, str) or not campaign_id:
            raise TransferModelContractError("campaign_id must be a nonempty string when supplied")
        profile["campaign_id"] = campaign_id
    profile["profile_sha256"] = _acceptance_profile_digest(profile)
    return profile


def build_campaign_theoretical_acceptance_window_profile(
    campaign: Mapping[str, object],
    window: TheoreticalAcceptanceWindow,
    coverage: AcceptanceCoverage,
) -> dict[str, object]:
    """Bind a frozen theoretical window receipt to the governed campaign."""
    settings = campaign_transfer_settings(campaign)
    if not np.isclose(window.final_time_budget_ns, settings.final_time_budget_ns, rtol=0.0, atol=1.0e-15):
        raise TransferModelContractError("window field-error budget differs from campaign")
    return build_theoretical_acceptance_window_profile(
        window,
        coverage,
        minimum_coverage_fraction=settings.minimum_pulse_eligible_coverage,
        campaign_id=settings.campaign_id,
    )


def load_theoretical_acceptance_window_profile(
    profile: Mapping[str, object],
) -> TheoreticalAcceptanceWindow:
    """Validate a serialized receipt and restore its runner-readable window."""
    if profile.get("schema_version") != 1 or profile.get("role") != ACCEPTANCE_WINDOW_PROFILE_ROLE:
        raise TransferModelContractError("acceptance-window profile identity is invalid")
    supplied_digest = profile.get("profile_sha256")
    unsigned = dict(profile)
    unsigned.pop("profile_sha256", None)
    if not isinstance(supplied_digest, str) or supplied_digest != _acceptance_profile_digest(unsigned):
        raise TransferModelContractError("acceptance-window profile digest differs")
    if tuple(profile.get("feature_order", ())) != ACCEPTANCE_FEATURE_NAMES:
        raise TransferModelContractError("acceptance-window profile feature order differs")
    blind = profile.get("detector_blind_contract")
    if not isinstance(blind, Mapping) or blind != {
        "detector_results_used": False,
        "selection_uses_detector_outcome": False,
        "freeze_before_real_beam_application": True,
        "outside_window_remains_in_full_beam": True,
    }:
        raise TransferModelContractError("acceptance-window profile is not detector-blind")
    bounds = profile.get("bounds")
    center_values = profile.get("center")
    grid = profile.get("synthetic_grid")
    coverage = profile.get("pulse_eligible_coverage")
    if not all(isinstance(item, Mapping) for item in (bounds, center_values, grid, coverage)):
        raise TransferModelContractError("acceptance-window profile sections are incomplete")
    try:
        lower = np.asarray([bounds[name]["lower"] for name in ACCEPTANCE_FEATURE_NAMES], dtype=float)
        upper = np.asarray([bounds[name]["upper"] for name in ACCEPTANCE_FEATURE_NAMES], dtype=float)
        center = np.asarray([center_values[name] for name in ACCEPTANCE_FEATURE_NAMES], dtype=float)
        budget = float(profile["field_error_budget_ns"])
        scale = float(profile["homothetic_scale"])
        point_count = int(grid["point_count"])
        grid_fraction = float(grid["accepted_fraction"])
        eligible_count = int(coverage["population_count"])
        accepted_count = int(coverage["accepted_count"])
        coverage_fraction = float(coverage["fraction"])
        minimum = float(coverage["minimum_required_fraction"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransferModelContractError("acceptance-window profile values are incomplete") from exc
    numeric = np.concatenate([lower, upper, center, [budget, scale, grid_fraction, coverage_fraction, minimum]])
    if not np.all(np.isfinite(numeric)) or np.any(lower > upper) or budget <= 0.0 or scale < 0.0:
        raise TransferModelContractError("acceptance-window profile has invalid numeric values")
    if (
        point_count < 1
        or not 0.0 <= grid_fraction <= 1.0
        or eligible_count < 1
        or not 0 <= accepted_count <= eligible_count
        or not np.isclose(coverage_fraction, accepted_count / eligible_count, rtol=0.0, atol=1.0e-15)
        or not 0.0 < minimum <= 1.0
        or coverage_fraction + 1.0e-15 < minimum
    ):
        raise TransferModelContractError("acceptance-window profile census is invalid")
    accepted_ids = coverage.get("accepted_particle_ids")
    if not isinstance(accepted_ids, list) or len(_validated_ids(accepted_ids)) != accepted_count:
        raise TransferModelContractError("acceptance-window accepted-particle census differs")
    grid_sha = grid.get("sha256")
    if not isinstance(grid_sha, str) or len(grid_sha) != 64:
        raise TransferModelContractError("acceptance-window synthetic-grid identity is invalid")
    prediction_role = profile.get("field_error_prediction_role")
    if prediction_role != FIELD_ERROR_PREDICTION_ROLE:
        raise TransferModelContractError("acceptance-window field-error prediction role differs")
    return TheoreticalAcceptanceWindow(
        feature_names=ACCEPTANCE_FEATURE_NAMES,
        lower_bounds=lower,
        upper_bounds=upper,
        center=center,
        homothetic_scale=scale,
        final_time_budget_ns=budget,
        prediction_role=prediction_role,
        detector_results_used=False,
        synthetic_grid_count=point_count,
        synthetic_grid_coverage_fraction=grid_fraction,
        synthetic_grid_sha256=grid_sha,
    )


def generate_constrained_voltage_candidates(
    nominal_voltages_v: Sequence[float],
    voltage_basis_v: np.ndarray,
    coefficient_proposals: np.ndarray,
    coefficient_bounds: Sequence[tuple[float, float]],
    energy_envelope_min_v: Sequence[float],
    energy_envelope_max_v: Sequence[float],
    *,
    fixed_endpoint_indices: Sequence[int],
    maximum_candidates: int = 5,
) -> tuple[ConstrainedVoltageCandidate, ...]:
    """Compose at most five monotone, fixed-endpoint PA voltage candidates."""
    nominal = np.asarray(nominal_voltages_v, dtype=float)
    basis = np.asarray(voltage_basis_v, dtype=float)
    proposals = np.asarray(coefficient_proposals, dtype=float)
    lower = np.asarray(energy_envelope_min_v, dtype=float)
    upper = np.asarray(energy_envelope_max_v, dtype=float)
    if nominal.ndim != 1 or nominal.size < 3 or not np.all(np.isfinite(nominal)):
        raise TransferModelContractError("nominal voltage profile must be a finite vector")
    if basis.ndim != 2 or basis.shape[1] != nominal.size or not np.all(np.isfinite(basis)):
        raise TransferModelContractError("voltage basis must have shape (K, electrodes)")
    if proposals.ndim != 2 or proposals.shape[1] != basis.shape[0] or not np.all(np.isfinite(proposals)):
        raise TransferModelContractError("coefficient proposals must have shape (candidates, K)")
    if proposals.shape[0] < 1 or proposals.shape[0] > maximum_candidates or maximum_candidates > 5:
        raise TransferModelContractError("candidate proposal count must be between one and five")
    if lower.shape != nominal.shape or upper.shape != nominal.shape or np.any(lower > upper):
        raise TransferModelContractError("energy-envelope bounds must match the voltage profile")
    if not np.all(np.isfinite(lower)) or not np.all(np.isfinite(upper)):
        raise TransferModelContractError("energy-envelope bounds must be finite")
    if len(coefficient_bounds) != basis.shape[0]:
        raise TransferModelContractError("each voltage basis coefficient requires one bound")
    coefficient_lower = np.asarray([item[0] for item in coefficient_bounds], dtype=float)
    coefficient_upper = np.asarray([item[1] for item in coefficient_bounds], dtype=float)
    if (
        np.any(~np.isfinite(coefficient_lower))
        or np.any(~np.isfinite(coefficient_upper))
        or np.any(coefficient_lower > coefficient_upper)
    ):
        raise TransferModelContractError("coefficient bounds are invalid")
    endpoints = tuple(index if index >= 0 else nominal.size + index for index in fixed_endpoint_indices)
    if (
        not endpoints
        or len(endpoints) != len(set(endpoints))
        or any(index < 0 or index >= nominal.size for index in endpoints)
    ):
        raise TransferModelContractError("fixed endpoint indices are invalid")
    tolerance = 1.0e-10
    if np.any(np.abs(basis[:, endpoints]) > tolerance):
        raise TransferModelContractError("voltage basis must be zero at every fixed endpoint")
    if np.any(nominal < lower - tolerance) or np.any(nominal > upper + tolerance):
        raise TransferModelContractError("nominal voltages lie outside the theoretical energy envelope")
    if np.any(np.diff(nominal) < -tolerance):
        raise TransferModelContractError("nominal voltage profile must be monotone nondecreasing")

    candidates: list[ConstrainedVoltageCandidate] = []
    seen: set[bytes] = set()
    for index, coefficients in enumerate(proposals, 1):
        if np.any(coefficients < coefficient_lower - tolerance) or np.any(coefficients > coefficient_upper + tolerance):
            raise TransferModelContractError("candidate coefficient exceeds its engineering residual bound")
        voltages = nominal + coefficients @ basis
        if not np.allclose(voltages[list(endpoints)], nominal[list(endpoints)], rtol=0.0, atol=tolerance):
            raise TransferModelContractError("candidate changes a theory-derived fixed endpoint")
        if np.any(np.diff(voltages) < -tolerance):
            raise TransferModelContractError("candidate voltage profile is not monotone")
        if np.any(voltages < lower - tolerance) or np.any(voltages > upper + tolerance):
            raise TransferModelContractError("candidate voltage profile leaves the theoretical energy envelope")
        identity = np.asarray(voltages, dtype="<f8").tobytes()
        if identity in seen:
            raise TransferModelContractError("candidate voltage profiles must be unique")
        seen.add(identity)
        candidates.append(
            ConstrainedVoltageCandidate(
                candidate_id=f"transfer_model_voltage_{index:02d}",
                coefficients=coefficients.copy(),
                electrode_voltages_v=voltages,
                fixed_endpoint_indices=endpoints,
            )
        )
    return tuple(candidates)
