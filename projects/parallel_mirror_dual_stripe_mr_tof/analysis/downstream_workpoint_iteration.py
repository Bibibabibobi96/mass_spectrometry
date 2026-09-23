"""Finite-state controller for real-flight downstream workpoint iteration.

The controller is solver-neutral: one invocation consumes exactly one genuine
centre-particle observation and either accepts it, stops with a named terminal
reason, or proposes one bounded P1/P2 or S1/S2 trust-region step.  The calling
workflow owns SIMION execution and manifest publication.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
    native_bank_identity,
    assert_trial_matches_jacobian,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


TERMINAL_REASONS = {
    "success",
    "collision_or_invalid_topology",
    "missing_target_phase",
    "residual_stagnation",
    "two_point_cycle",
    "oscillation",
    "step_too_small",
    "maximum_iterations",
    "voltage_bound",
    "solver_failure",
    "model_recovery_exhausted",
}
ACCEPTANCE_NAMES = (
    RESIDUAL_NAMES[0],
    "P1_P2_P2_shield_low_field_angle_degrees",
    RESIDUAL_NAMES[2],
    RESIDUAL_NAMES[3],
)
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be a JSON object")
    return value


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateContractError(f"{label} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def _vector(values: object, length: int, label: str) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.shape != (length,) or not np.all(np.isfinite(result)):
        raise CandidateContractError(f"{label} must contain {length} finite values")
    return result


def _terminal(reason: str, *, iteration: int, detail: str, record: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if reason not in TERMINAL_REASONS:
        raise AssertionError(reason)
    result: dict[str, Any] = {
        "schema_version": 1,
        "role": "mrtof_downstream_workpoint_iteration_decision",
        "state": "terminal",
        "terminal_reason": reason,
        "iteration": iteration,
        "detail": detail,
    }
    if record is not None:
        result["observation_record"] = dict(record)
    return result


def solver_failure_decision(iteration: int, detail: str) -> dict[str, Any]:
    """Return the explicit terminal state used when a child solver run fails."""
    return _terminal("solver_failure", iteration=iteration, detail=detail)


def resolve_operating_cache_binding(
    identity: Mapping[str, Any],
    protection: Mapping[str, Any],
    *,
    expected_lease_id: str | None = None,
    expected_lease_owner: str | None = None,
) -> dict[str, Any]:
    """Bind a synthesis identity to the cache key published by its lease receipt.

    The synthesis identity intentionally has no cache key.  The child runner's
    manifest-bound protection receipt is the publication authority for that key.
    """
    native = identity.get("role") == "mrtof_private_native_corridor_family"
    bank = native_bank_identity(identity) if native else None
    if not native and (identity.get("schema_version") != 2 or identity.get("role") != "simion_standalone_operating_pa_group"):
        raise CandidateContractError("operating PA cache identity is invalid")
    if not native and (not isinstance(identity.get("members"), list) or not isinstance(identity.get("synthesis"), Mapping)):
        raise CandidateContractError("operating PA cache identity is incomplete")
    expected_protection_role = (
        "mrtof_native_corridor_protection_renewal"
        if native
        else "mrtof_local_operating_cache_protection_renewal"
    )
    if protection.get("schema_version") != 1 or protection.get("role") != expected_protection_role:
        raise CandidateContractError("operating-cache protection receipt is invalid")
    if protection.get("status") != "success":
        raise CandidateContractError("operating-cache protection renewal did not succeed")
    lease_id = protection.get("lease_id")
    lease_owner = protection.get("lease_owner")
    if not isinstance(lease_id, str) or not lease_id:
        raise CandidateContractError("operating-cache protection receipt lacks lease_id")
    if not isinstance(lease_owner, str) or not lease_owner:
        raise CandidateContractError("operating-cache protection receipt lacks lease_owner")
    if expected_lease_id is not None and lease_id != expected_lease_id:
        raise CandidateContractError("operating-cache protection lease_id differs")
    if expected_lease_owner is not None and lease_owner != expected_lease_owner:
        raise CandidateContractError("operating-cache protection lease_owner differs")
    cache_key = protection.get("cache_key")
    if not isinstance(cache_key, str) or SHA256_PATTERN.fullmatch(cache_key) is None:
        raise CandidateContractError("operating-cache protection receipt lacks a SHA-256 cache_key")
    renewal = protection.get("renewal")
    if not isinstance(renewal, Mapping):
        raise CandidateContractError("operating-cache protection receipt lacks renewal evidence")
    if renewal.get("lease_id") != lease_id or renewal.get("owner") != lease_owner:
        raise CandidateContractError("nested renewal lease identity differs from receipt")
    protected_keys = renewal.get("protected_cache_keys")
    if not isinstance(protected_keys, list) or cache_key.lower() not in {
        str(value).lower() for value in protected_keys
    }:
        raise CandidateContractError("renewed lease does not protect the published cache_key")
    generation_directory = protection.get("generation_directory")
    if not isinstance(generation_directory, str) or not generation_directory:
        raise CandidateContractError("operating-cache protection receipt lacks generation_directory")
    normalized_parts = [part.lower() for part in Path(generation_directory).parts]
    if cache_key.lower() not in normalized_parts or "generations" not in normalized_parts:
        raise CandidateContractError("cache generation_directory is inconsistent with cache_key")
    if native:
        if bank["cache_key"] != cache_key.upper():
            raise CandidateContractError("native bank cache_key differs from protection receipt")
        if Path(str(identity.get("generation_directory", ""))).resolve() != Path(generation_directory).resolve():
            raise CandidateContractError("native bank generation_directory differs from protection receipt")
    return {
        **({"native_bank_identity": bank} if native else {}),
        "schema_version": 1,
        "role": "mrtof_operating_cache_binding",
        "cache_key": cache_key.upper(),
        "generation_directory": generation_directory,
        "lease_id": lease_id,
        "lease_owner": lease_owner,
    }


def _profile(contract: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    profile = contract.get("downstream_fixed_grid_workpoint_profile")
    if not isinstance(profile, Mapping) or profile.get("schema_version") != 1:
        raise CandidateContractError("downstream workpoint profile is invalid")
    loop = profile.get("automatic_iteration")
    required = {
        "schema_version", "maximum_iterations", "damping_factor",
        "minimum_step_linf_v", "minimum_relative_improvement",
        "maximum_consecutive_non_improving_iterations", "cycle_voltage_tolerance_v",
        "oscillation_window", "capacity_protection_ttl_seconds", "acceptance_tolerances",
    }
    optional = {"advance_multiplier", "backtrack_multiplier"}
    if (
        not isinstance(loop, Mapping)
        or not required <= set(loop) <= required | optional
        or loop.get("schema_version") != 1
    ):
        raise CandidateContractError("automatic downstream iteration contract is incomplete")
    return profile, loop


def _observation_record(
    observation: Mapping[str, Any], materialization: Mapping[str, Any], profile: Mapping[str, Any]
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    residual_map = observation.get("residuals")
    if not isinstance(residual_map, Mapping):
        raise CandidateContractError("real flight lacks downstream residuals")
    residuals = np.asarray([_finite(residual_map.get(name), name) for name in RESIDUAL_NAMES])
    target_ratio = _finite(
        materialization.get("target_low_field_tangent_ratio_vy_over_vz"), "target tangent ratio"
    )
    angle_degrees = math.degrees(
        math.atan(target_ratio + residuals[1]) - math.atan(target_ratio)
    )
    tolerances = profile["automatic_iteration"]["acceptance_tolerances"]
    if not isinstance(tolerances, Mapping) or set(tolerances) != set(ACCEPTANCE_NAMES):
        raise CandidateContractError("automatic iteration tolerances must name all four residuals")
    physical = residuals.copy()
    physical[1] = angle_degrees
    tolerance_vector = np.asarray([
        _finite(tolerances[name], f"{name} acceptance tolerance") for name in ACCEPTANCE_NAMES
    ])
    if np.any(tolerance_vector <= 0.0):
        raise CandidateContractError("automatic iteration acceptance tolerances must be positive")
    voltages = _vector([
        *materialization.get("stripe_biases_v", []),
        *materialization.get("prism_voltages_v", []),
    ], 4, "materialized downstream voltages")
    scaled = physical / tolerance_vector
    record = {
        "voltages_v": voltages.tolist(),
        "residuals": dict(zip(RESIDUAL_NAMES, residuals.tolist(), strict=True)),
        "physical_acceptance_residuals": dict(zip(RESIDUAL_NAMES, physical.tolist(), strict=True)),
        "acceptance_tolerances": dict(zip(ACCEPTANCE_NAMES, tolerance_vector.tolist(), strict=True)),
        "scaled_residual_norm": float(np.linalg.norm(scaled)),
        "maximum_scaled_abs_residual": float(np.max(np.abs(scaled))),
    }
    return record, residuals, voltages


def _physical_jacobian(
    jacobian: np.ndarray, *, target_ratio: float, tangent_residual: float
) -> np.ndarray:
    """Convert the P2 tangent row to the angle unit used for acceptance."""
    physical = jacobian.copy()
    physical[1] *= math.degrees(1.0 / (1.0 + (target_ratio + tangent_residual) ** 2))
    return physical


def _record_physical_vector(record: Mapping[str, Any]) -> np.ndarray:
    return np.asarray([
        _finite(record["physical_acceptance_residuals"][name], name)
        for name in RESIDUAL_NAMES
    ])


def _record_tolerances(record: Mapping[str, Any]) -> np.ndarray:
    return np.asarray([
        _finite(record["acceptance_tolerances"][name], f"{name} tolerance")
        for name in ACCEPTANCE_NAMES
    ])


def _accepted_anchor(
    history: Sequence[Mapping[str, Any]], coordinate_group: str
) -> Mapping[str, Any] | None:
    """Find the latest explicitly accepted point in the current control phase."""
    for item in reversed(history):
        if not isinstance(item, Mapping) or (
            item.get("coordinate_group") != coordinate_group
            and item.get("rejected_coordinate_group") != coordinate_group
        ):
            continue
        accepted = item.get("accepted_workpoint")
        if isinstance(accepted, Mapping):
            return accepted
    # Checkpoints created before explicit acceptance records only prove a valid
    # flight.  They are a one-time recovery anchor, never a reason to accept a
    # later degrading point.
    for item in reversed(history):
        if isinstance(item, Mapping) and item.get("coordinate_group") == coordinate_group:
            record = item.get("observation_record")
            if isinstance(record, Mapping):
                return record
    return None


def select_best_physical_workpoint(history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Select the lowest-demand P-qualified physical flight for downstream use.

    A controller can reject a physically complete flight solely because its
    improvement is below the iteration floor.  That evidence remains eligible
    for Candidate bunch screening; topology/collision failures never are.  P
    voltage magnitude is the primary selection criterion once P1/P2 have met
    their physical constraints.  Residuals then distinguish electrically
    equivalent choices.
    """
    candidates: list[tuple[tuple[float, float, float, float, int], Mapping[str, Any]]] = []
    for ordinal, item in enumerate(history, start=1):
        if not isinstance(item, Mapping):
            continue
        record = item.get("observation_record")
        eligible = (
            (item.get("candidate_accepted") is True and item.get("invalid_trial_reason") is None)
            or item.get("invalid_trial_reason") == "residual_stagnation"
        )
        if not eligible or not isinstance(record, Mapping):
            continue
        try:
            norm = _finite(record["scaled_residual_norm"], "physical workpoint residual norm")
            maximum = _finite(record["maximum_scaled_abs_residual"], "physical workpoint maximum residual")
            if norm < 0.0 or maximum < 0.0:
                continue
            voltages = _vector(record["voltages_v"], 4, "physical workpoint voltages")
            residuals = record["physical_acceptance_residuals"]
            tolerances = record["acceptance_tolerances"]
            if not isinstance(residuals, Mapping) or not isinstance(tolerances, Mapping):
                continue
            if not all(name in residuals for name in RESIDUAL_NAMES):
                continue
            if not all(name in tolerances for name in ACCEPTANCE_NAMES):
                continue
            p_residuals = _record_physical_vector(record)[:2]
            p_tolerances = _record_tolerances(record)[:2]
            if np.any(p_tolerances <= 0.0) or np.any(np.abs(p_residuals) > p_tolerances):
                continue
        except (CandidateContractError, KeyError, TypeError):
            continue
        p_peak_abs_v = float(np.max(np.abs(voltages[2:])))
        p_total_abs_v = float(np.sum(np.abs(voltages[2:])))
        candidates.append(((p_peak_abs_v, p_total_abs_v, norm, maximum, ordinal), record))
    if not candidates:
        raise CandidateContractError(
            "history has no topology-valid, P1/P2-qualified physical workpoint eligible for downstream screening"
        )
    (p_peak_abs_v, p_total_abs_v, norm, maximum, ordinal), record = min(candidates, key=lambda value: value[0])
    residuals = record["physical_acceptance_residuals"]
    tolerances = record["acceptance_tolerances"]
    warnings = [
        {
            "residual": name,
            "value": float(residuals[name]),
            "tolerance": float(tolerances[name]),
        }
        for name in (RESIDUAL_NAMES[0], RESIDUAL_NAMES[2], RESIDUAL_NAMES[3])
        if name in tolerances and abs(float(residuals[name])) > float(tolerances[name])
    ]
    return {
        "schema_version": 1,
        "role": "mrtof_best_physical_workpoint_handoff",
        "status": "warning" if warnings else "within_tolerance",
        "qualification": "candidate_bunch_screening_authorized",
        "selected_history_ordinal": ordinal,
        "selected_workpoint": dict(record),
        "scaled_residual_norm": norm,
        "maximum_scaled_abs_residual": maximum,
        "selection_order": [
            "maximum_abs_p1_p2_voltage_v",
            "sum_abs_p1_p2_voltage_v",
            "scaled_residual_norm",
            "maximum_scaled_abs_residual",
            "history_ordinal",
        ],
        "selected_p1_p2_voltage_magnitude": {
            "maximum_abs_v": p_peak_abs_v,
            "sum_abs_v": p_total_abs_v,
        },
        "warnings": warnings,
        "next_action": "materialize_private_composed_operating_pa_then_run_complete_n100_n1000_bunches",
    }


def _factor(loop: Mapping[str, Any], name: str, legacy_name: str) -> float:
    """Read a named controller factor while preserving the frozen legacy contract."""
    value = loop.get(name, loop[legacy_name])
    factor = _finite(value, name)
    if not 0.0 < factor <= 1.0:
        raise CandidateContractError(f"{name} must be in (0, 1]")
    return factor


def _latest_recovery_state(history: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for item in reversed(history):
        if not isinstance(item, Mapping):
            continue
        state = item.get("recovery_state")
        if isinstance(state, Mapping) and state.get("schema_version") == 1:
            return state
    return None


def _recovery_state(
    *,
    anchor: Mapping[str, Any] | None,
    advance_multiplier: float,
    backtrack_multiplier: float,
    rejected_line_count: int = 0,
    recovery_origin_voltages_v: Sequence[float] | None = None,
    model_invalid_reason: str | None = None,
    trusted_prediction_count: int = 0,
) -> dict[str, Any]:
    """Create the complete JSON-safe state needed to resume controller recovery."""
    if rejected_line_count < 0 or trusted_prediction_count < 0:
        raise CandidateContractError("recovery counters must be non-negative")
    result: dict[str, Any] = {
        "schema_version": 1,
        "accepted_anchor": dict(anchor) if isinstance(anchor, Mapping) else None,
        "advance_multiplier": advance_multiplier,
        "backtrack_multiplier": backtrack_multiplier,
        "rejected_line_count": rejected_line_count,
        "recovery_origin_voltages_v": (
            _vector(recovery_origin_voltages_v, 4, "recovery origin voltages").tolist()
            if recovery_origin_voltages_v is not None else None
        ),
        "model_invalid_reason": model_invalid_reason,
        "trusted_prediction_count": trusted_prediction_count,
    }
    return result


def _prediction_direction_error(
    previous: Mapping[str, Any] | None,
    record: Mapping[str, Any],
    rows: np.ndarray,
) -> bool:
    """Return whether a prior model predicted the opposite local residual change."""
    if not isinstance(previous, Mapping):
        return False
    base = previous.get("observation_record")
    predicted = previous.get("predicted_physical_acceptance_residuals")
    if not isinstance(base, Mapping) or not isinstance(predicted, Mapping):
        return False
    try:
        base_vector = _record_physical_vector(base)[rows]
        predicted_vector = np.asarray([_finite(predicted[name], name) for name in RESIDUAL_NAMES])[rows]
        observed_vector = _record_physical_vector(record)[rows]
    except (KeyError, TypeError, CandidateContractError):
        return False
    predicted_change = predicted_vector - base_vector
    observed_change = observed_vector - base_vector
    return bool(
        np.linalg.norm(predicted_change) > np.finfo(float).eps
        and np.linalg.norm(observed_change) > np.finfo(float).eps
        and float(predicted_change @ observed_change) < 0.0
    )


def _same_rejected_line(
    history: Sequence[Mapping[str, Any]], anchor: Mapping[str, Any] | None, coordinate_group: str
) -> int:
    """Count consecutive rejected candidates that retreat along one anchor ray."""
    if anchor is None:
        return 0
    anchor_v = _vector(anchor["voltages_v"], 4, "accepted anchor voltages")
    directions: list[np.ndarray] = []
    for item in reversed(history):
        legacy_s_rejection = (
            coordinate_group == "stripe_1_stripe_2"
            and item.get("coordinate_group") == "physical_topology_backtrack"
            and item.get("invalid_trial_reason") == "residual_stagnation"
        ) if isinstance(item, Mapping) else False
        if not isinstance(item, Mapping) or (
            item.get("coordinate_group") != coordinate_group
            and item.get("rejected_coordinate_group") != coordinate_group
            and not legacy_s_rejection
        ):
            break
        if item.get("candidate_accepted") is not False and item.get("rejected_coordinate_group") != coordinate_group:
            break
        record = item.get("observation_record")
        if not isinstance(record, Mapping):
            break
        direction = _vector(record["voltages_v"], 4, "rejected candidate voltages") - anchor_v
        if np.linalg.norm(direction) <= np.finfo(float).eps:
            break
        directions.append(direction / np.linalg.norm(direction))
    if len(directions) < 2:
        return len(directions)
    reference = directions[0]
    return len(directions) if all(float(reference @ direction) > 0.999 for direction in directions[1:]) else 1


def _latest_phase_jacobian(
    history: Sequence[Mapping[str, Any]], coordinate_group: str, fallback: np.ndarray
) -> np.ndarray:
    for item in reversed(history):
        if not isinstance(item, Mapping) or item.get("coordinate_group") != coordinate_group:
            continue
        if coordinate_group == "stripe_1_stripe_2":
            validation = item.get("local_s_model_validation")
            columns = np.asarray(item.get("local_s_physical_jacobian_columns"), dtype=float)
            if (
                isinstance(validation, Mapping)
                and validation.get("passed") is True
                and columns.shape == (4, 2)
                and np.all(np.isfinite(columns))
            ):
                return merge_s_local_jacobian(fallback, columns)
        candidate = np.asarray(item.get("local_physical_jacobian_rows"), dtype=float)
        if candidate.shape == (4, 4) and np.all(np.isfinite(candidate)):
            return candidate
    return fallback


def _broyden_update(
    jacobian: np.ndarray, anchor: Mapping[str, Any] | None, record: Mapping[str, Any]
) -> np.ndarray:
    """Use one accepted same-branch secant without discarding the base model."""
    if anchor is None:
        return jacobian
    delta_v = _vector(record["voltages_v"], 4, "accepted voltages") - _vector(
        anchor["voltages_v"], 4, "anchor voltages"
    )
    squared = float(delta_v @ delta_v)
    if squared <= np.finfo(float).tiny:
        return jacobian
    delta_r = _record_physical_vector(record) - _record_physical_vector(anchor)
    return jacobian + np.outer(delta_r - jacobian @ delta_v, delta_v) / squared


def refresh_s_local_jacobian(
    anchor: Mapping[str, Any], stripe_1: Mapping[str, Any], stripe_2: Mapping[str, Any]
) -> np.ndarray:
    """Measure the two S columns from independent accepted-anchor flights."""
    anchor_v = _vector(anchor["voltages_v"], 4, "S refresh anchor voltages")
    anchor_r = _record_physical_vector(anchor)
    columns: list[np.ndarray] = []
    for index, sample in enumerate((stripe_1, stripe_2)):
        delta = _vector(sample["voltages_v"], 4, "S refresh sample voltages") - anchor_v
        changed = np.flatnonzero(np.abs(delta) > 0.0)
        if changed.tolist() != [index]:
            raise CandidateContractError("S refresh samples must independently perturb S1 then S2")
        columns.append((_record_physical_vector(sample) - anchor_r) / delta[index])
    return np.column_stack(columns)


def merge_s_local_jacobian(base_jacobian: np.ndarray, s_columns: np.ndarray) -> np.ndarray:
    """Replace only the two S columns of a full physical Jacobian."""
    base = np.asarray(base_jacobian, dtype=float)
    columns = np.asarray(s_columns, dtype=float)
    if base.shape != (4, 4) or not np.all(np.isfinite(base)):
        raise CandidateContractError("base physical Jacobian must be a finite 4x4 matrix")
    if columns.shape != (4, 2) or not np.all(np.isfinite(columns)):
        raise CandidateContractError("local S Jacobian columns must be a finite 4x2 matrix")
    merged = base.copy()
    merged[:, :2] = columns
    return merged


def validate_s_local_jacobian_against_history(
    anchor: Mapping[str, Any],
    s_columns: np.ndarray,
    history: Sequence[Mapping[str, Any]],
    *,
    maximum_normalized_prediction_error: float = 1.0,
    maximum_comparisons: int | None = None,
    trusted_radius_linf_v: float | None = None,
    supported_directions: Sequence[int] | None = None,
    position_tolerance_mm: float | None = None,
) -> dict[str, Any]:
    """Check a refreshed S model against already observed anchor-local flights.

    Only records whose P voltages equal the anchor are comparable: the S-only
    model is not permitted to silently explain a coupled P perturbation.
    """
    maximum_error = _finite(maximum_normalized_prediction_error, "maximum normalized prediction error")
    if maximum_error <= 0.0:
        raise CandidateContractError("maximum normalized prediction error must be positive")
    if maximum_comparisons is not None and maximum_comparisons < 1:
        raise CandidateContractError("maximum local-model history comparisons must be positive")
    if trusted_radius_linf_v is not None and trusted_radius_linf_v <= 0.0:
        raise CandidateContractError("local-model trusted radius must be positive")
    if supported_directions is not None:
        if len(supported_directions) != 2 or any(direction not in (-1, 1) for direction in supported_directions):
            raise CandidateContractError("local-model supported directions must contain two signs")
    anchor_v = _vector(anchor["voltages_v"], 4, "local-model anchor voltages")
    anchor_r = _record_physical_vector(anchor)
    tolerances = _record_tolerances(anchor)
    if position_tolerance_mm is not None:
        tolerance = _finite(position_tolerance_mm, "local-model position tolerance")
        if tolerance <= 0.0:
            raise CandidateContractError("local-model position tolerance must be positive")
        tolerances[[0, 2, 3]] = tolerance
    columns = np.asarray(s_columns, dtype=float)
    if columns.shape != (4, 2) or not np.all(np.isfinite(columns)):
        raise CandidateContractError("local S Jacobian columns must be a finite 4x2 matrix")
    comparisons: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, Mapping):
            continue
        record = item.get("observation_record")
        if not isinstance(record, Mapping):
            continue
        voltages = _vector(record["voltages_v"], 4, "local-model history voltages")
        delta = voltages - anchor_v
        if np.max(np.abs(delta)) <= np.finfo(float).eps:
            continue
        if np.max(np.abs(delta[2:])) > np.finfo(float).eps:
            continue
        actual = _record_physical_vector(record)
        predicted = anchor_r + columns @ delta[:2]
        normalized_error = (predicted - actual) / tolerances
        predicted_change = predicted[2:] - anchor_r[2:]
        actual_change = actual[2:] - anchor_r[2:]
        direction_consistent = bool(
            np.linalg.norm(predicted_change) <= np.finfo(float).eps
            or np.linalg.norm(actual_change) <= np.finfo(float).eps
            or float(predicted_change @ actual_change) >= 0.0
        )
        error_norm = float(np.linalg.norm(normalized_error[2:]))
        distance = float(np.max(np.abs(delta[:2])))
        within_radius = bool(trusted_radius_linf_v is None or distance <= trusted_radius_linf_v + np.finfo(float).eps)
        direction_supported = supported_directions is None or all(
            abs(delta[index]) <= np.finfo(float).eps or int(np.sign(delta[index])) == supported_directions[index]
            for index in range(2)
        )
        eligible = bool(within_radius and direction_supported)
        comparisons.append({
            "voltages_v": voltages.tolist(),
            "s_delta_v": delta[:2].tolist(),
            "predicted_physical_acceptance_residuals": dict(zip(RESIDUAL_NAMES, predicted.tolist(), strict=True)),
            "actual_physical_acceptance_residuals": dict(zip(RESIDUAL_NAMES, actual.tolist(), strict=True)),
            "normalized_s_prediction_error": error_norm,
            "direction_consistent": direction_consistent,
            "local_distance_linf_v": distance,
            "within_trusted_radius": within_radius,
            "direction_supported": direction_supported,
            "eligible_for_acceptance": eligible,
            "explained": eligible and direction_consistent and error_norm <= maximum_error,
        })
    if maximum_comparisons is not None:
        comparisons = comparisons[-maximum_comparisons:]
    eligible = [item for item in comparisons if item["eligible_for_acceptance"]]
    return {
        "schema_version": 1,
        "role": "mrtof_s_local_jacobian_history_validation",
        "anchor_voltages_v": anchor_v.tolist(),
        "maximum_normalized_prediction_error": maximum_error,
        "maximum_comparisons": maximum_comparisons,
        "trusted_radius_linf_v": trusted_radius_linf_v,
        "position_tolerance_mm": position_tolerance_mm,
        "supported_directions": list(supported_directions) if supported_directions is not None else None,
        "comparable_observation_count": len(comparisons),
        "eligible_observation_count": len(eligible),
        "comparisons": comparisons,
        "passed": bool(eligible) and all(item["explained"] for item in eligible),
    }


def _invalid_trial_backtrack(
    *,
    prior: Mapping[str, Any],
    materialization: Mapping[str, Any],
    loop: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    iteration: int,
    reason: str,
    detail: str,
) -> dict[str, Any]:
    """Backtrack one invalid real-flight step toward the latest valid point."""
    maximum_iterations = int(loop["maximum_iterations"])
    current = _vector([
        *materialization.get("stripe_biases_v", []),
        *materialization.get("prism_voltages_v", []),
    ], 4, "materialized downstream voltages")
    accepted_indices = [
        index for index, item in enumerate(history)
        if isinstance(item, Mapping) and isinstance(item.get("accepted_workpoint"), Mapping)
    ]
    if accepted_indices:
        anchor_index = accepted_indices[-1]
        anchor = _vector(history[anchor_index]["accepted_workpoint"].get("voltages_v"), 4, "latest accepted voltages")
    else:
        valid_records = [
            item["observation_record"]
            for item in history
            if isinstance(item, Mapping) and isinstance(item.get("observation_record"), Mapping)
        ]
        anchor = _vector(
            valid_records[-1].get("voltages_v") if valid_records else prior.get("baseline_voltages_v"),
            4, "recovery anchor voltages",
        )
        anchor_index = -1
    backtrack_multiplier = _factor(loop, "backtrack_multiplier", "damping_factor")
    if backtrack_multiplier >= 1.0:
        raise CandidateContractError("invalid-flight backtracking requires backtrack_multiplier in (0, 1)")
    previous_state = _latest_recovery_state(history)
    repeated_rejections = sum(
        item.get("coordinate_group") == "physical_topology_backtrack"
        for item in history[anchor_index + 1:]
        if isinstance(item, Mapping)
    )
    invalid_attempt_count = 1 + repeated_rejections
    # A S-only proposal is made only after the P constraints have been
    # accepted.  If its first real flight loses topology, repeatedly bisecting
    # the coupled proposal does not identify which S column caused the loss.
    # Ask the existing independent-column recovery instead.  The failed
    # candidate remains recorded as topology evidence, while the accepted
    # anchor remains the only point from which recovery may solve.
    s_displacement = current[:2] - anchor[:2]
    p_displacement = current[2:] - anchor[2:]
    if (
        reason == "collision_or_invalid_topology"
        and accepted_indices
        and repeated_rejections == 0
        and float(np.max(np.abs(s_displacement))) > 1e-12
        and float(np.max(np.abs(p_displacement))) <= 1e-10
        and isinstance(history[anchor_index].get("accepted_workpoint"), Mapping)
    ):
        accepted_anchor = history[anchor_index]["accepted_workpoint"]
        decision = _local_model_refresh_required(
            iteration=iteration,
            coordinate_group="stripe_1_stripe_2",
            record=accepted_anchor,
            anchor=accepted_anchor,
            loop=loop,
            assessment={
                "accepted": False,
                "topology_valid": False,
                "model_invalid_reason": "s_only_topology_loss",
                "candidate_voltages_v": current.tolist(),
            },
            reason="s_only_topology_loss",
            rejected_line_count=1,
        )
        directions = [int(1 if value > 0 else -1) if abs(value) > 1e-12 else 1
                      for value in s_displacement]
        decision.update({
            "invalid_trial_reason": reason,
            "invalid_trial_detail": detail,
            "invalid_candidate_voltages_v": current.tolist(),
        })
        decision["recovery_state"].update({
            "initial_probe_directions": directions,
            "recovery_origin_voltages_v": current.tolist(),
        })
        decision["next_action"] = "refresh_independent_s_columns_after_s_only_topology_loss"
        return decision
    if maximum_iterations < 1 or invalid_attempt_count >= maximum_iterations:
        return _terminal(
            reason, iteration=iteration,
            detail=f"{detail}; maximum invalid-flight backtrack count {maximum_iterations} reached",
            record=None,
        )
    # Always shrink the original rejected ray.  Re-applying a power to the
    # already shrunken proposal caused 1 -> 1/2 -> 1/8 -> 1/64 steps.
    origin = current
    if isinstance(previous_state, Mapping):
        stored_origin = previous_state.get("recovery_origin_voltages_v")
        stored_anchor = previous_state.get("accepted_anchor")
        if isinstance(stored_origin, list) and isinstance(stored_anchor, Mapping):
            if np.allclose(_vector(stored_anchor.get("voltages_v"), 4, "stored recovery anchor"), anchor):
                origin = _vector(stored_origin, 4, "stored recovery origin")
    backtrack_factor = backtrack_multiplier ** (1 + repeated_rejections)
    proposed = anchor + backtrack_factor * (origin - anchor)
    correction = proposed - current
    minimum_step = _finite(loop["minimum_step_linf_v"], "minimum voltage step")
    if float(np.max(np.abs(correction))) < minimum_step:
        return _terminal(reason, iteration=iteration, detail=f"{detail}; backtrack step is too small", record=None)
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_workpoint_iteration_decision",
        "state": "continue",
        "terminal_reason": None,
        "iteration": iteration,
        "coordinate_group": "physical_topology_backtrack",
        "invalid_trial_reason": reason,
        "invalid_trial_detail": detail,
        "backtrack_anchor_voltages_v": anchor.tolist(),
        "backtrack_factor": backtrack_factor,
        "applied_correction_v": correction.tolist(),
        "proposed_voltages_v": proposed.tolist(),
        "candidate_accepted": False,
        "recovery_state": _recovery_state(
            anchor={"voltages_v": anchor.tolist()},
            advance_multiplier=_factor(loop, "advance_multiplier", "damping_factor"),
            backtrack_multiplier=backtrack_multiplier,
            rejected_line_count=repeated_rejections + 1,
            recovery_origin_voltages_v=origin,
        ),
        "next_action": "retry_real_center_flight_with_reduced_step_on_reused_fixed_response_fields",
    }


def _local_model_refresh_required(
    *,
    iteration: int,
    coordinate_group: str,
    record: Mapping[str, Any],
    anchor: Mapping[str, Any] | None,
    loop: Mapping[str, Any],
    assessment: Mapping[str, Any],
    reason: str,
    rejected_line_count: int,
    candidate_accepted: bool = False,
) -> dict[str, Any]:
    """Persist a solver-neutral request for independent local derivative flights."""
    if coordinate_group != "stripe_1_stripe_2":
        raise CandidateContractError("local model refresh is currently defined only for S coordinates")
    if anchor is None:
        raise CandidateContractError("local model refresh requires an accepted anchor")
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_workpoint_iteration_decision",
        "state": "recovery_required",
        "terminal_reason": None,
        "iteration": iteration,
        "coordinate_group": coordinate_group,
        "observation_record": dict(record),
        "accepted_workpoint": dict(record if candidate_accepted else anchor),
        "candidate_accepted": candidate_accepted,
        "prediction_assessment": dict(assessment),
        "recovery_state": _recovery_state(
            anchor=record if candidate_accepted else anchor,
            advance_multiplier=_factor(loop, "advance_multiplier", "damping_factor"),
            backtrack_multiplier=_factor(loop, "backtrack_multiplier", "damping_factor"),
            rejected_line_count=rejected_line_count,
            model_invalid_reason=reason,
        ),
        "next_action": "refresh_independent_s_local_derivative_columns_from_accepted_anchor",
    }


def decide_iteration(
    prior: Mapping[str, Any],
    observation: Mapping[str, Any],
    materialization: Mapping[str, Any],
    contract: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    iteration: int,
    *,
    recovery_resume: bool = False,
) -> dict[str, Any]:
    """Advance the finite-state machine after one real centre flight."""
    if iteration < 1:
        raise CandidateContractError("iteration must be positive")
    profile, loop = _profile(contract)
    if tuple(prior.get("unknown_names", ())) != UNKNOWN_NAMES or tuple(
        prior.get("residual_names", ())
    ) != RESIDUAL_NAMES:
        raise CandidateContractError("prior workpoint Jacobian identity differs")
    if prior.get("status") not in {"linearized_candidate_step", "transported_linearized_candidate_step"}:
        raise CandidateContractError("prior workpoint is not an eligible real-flight seed")

    termination = observation.get("termination_diagnostic")
    if isinstance(termination, Mapping) and termination.get("physical_collision") is True:
        return _invalid_trial_backtrack(
            prior=prior, materialization=materialization, loop=loop, history=history, iteration=iteration,
            reason="collision_or_invalid_topology", detail="real centre particle collided with an electrode",
        )
    if observation.get("status") != "full_drift_observed":
        return _invalid_trial_backtrack(
            prior=prior, materialization=materialization, loop=loop, history=history, iteration=iteration,
            reason="collision_or_invalid_topology", detail=f"real flight status is {observation.get('status')!r}",
        )
    topology = observation.get("return_topology")
    if topology not in {"exact_target_k_phase_return", "coordinate_return_before_target_phase"}:
        return _invalid_trial_backtrack(
            prior=prior, materialization=materialization, loop=loop, history=history, iteration=iteration,
            reason="collision_or_invalid_topology", detail=f"unsupported return topology {topology!r}",
        )
    residual_map = observation.get("residuals")
    if not isinstance(residual_map, Mapping) or RESIDUAL_NAMES[3] not in residual_map:
        return _invalid_trial_backtrack(
            prior=prior, materialization=materialization, loop=loop, history=history, iteration=iteration,
            reason="missing_target_phase", detail="real flight did not record a target-K phase y sample",
        )

    static_return = observation.get("static_return_diagnostic")
    if (
        not isinstance(static_return, Mapping)
        or static_return.get("status") != "detector_hit"
        or static_return.get("event_contract_ok") is not True
    ):
        return _invalid_trial_backtrack(
            prior=prior, materialization=materialization, loop=loop, history=history, iteration=iteration,
            reason="collision_or_invalid_topology",
            detail="real flight did not complete the declared static detector-return topology",
        )

    record, residuals, voltages = _observation_record(observation, materialization, profile)
    if record["maximum_scaled_abs_residual"] <= 1.0:
        return _terminal(
            "success", iteration=iteration,
            detail="all four real-flight residuals and the static detector-return contract pass",
            record=record,
        )

    previous_records = [
        item["observation_record"]
        for item in history
        if isinstance(item, Mapping) and isinstance(item.get("observation_record"), Mapping)
    ]
    cycle_tolerance = _finite(loop["cycle_voltage_tolerance_v"], "cycle voltage tolerance")
    if len(previous_records) >= 2:
        two_back = _vector(previous_records[-2].get("voltages_v"), 4, "two-back voltages")
        if float(np.max(np.abs(voltages - two_back))) <= cycle_tolerance:
            return _terminal(
                "two_point_cycle", iteration=iteration,
                detail="voltage vector returned to the two-back point", record=record,
            )

    target_ratio = _finite(materialization.get("target_low_field_tangent_ratio_vy_over_vz"), "target tangent ratio")
    angle_tolerance = _finite(
        profile["automatic_iteration"]["acceptance_tolerances"][ACCEPTANCE_NAMES[1]],
        "angle acceptance tolerance",
    )
    angle_residual = math.degrees(math.atan(target_ratio + residuals[1]) - math.atan(target_ratio))
    prism_out = (
        abs(residuals[0]) > _finite(
            profile["automatic_iteration"]["acceptance_tolerances"][RESIDUAL_NAMES[0]],
            "position tolerance",
        )
        or abs(angle_residual) > angle_tolerance
    )
    coordinate_group = "prism_1_prism_2" if prism_out else "stripe_1_stripe_2"
    rows = np.asarray([0, 1] if prism_out else [2, 3])
    indices = np.asarray([2, 3] if prism_out else [0, 1])
    maximum_iterations = int(loop["maximum_iterations"])
    valid_group_iteration = 1 + sum(
        isinstance(item, Mapping)
        and item.get("coordinate_group") == coordinate_group
        and isinstance(item.get("observation_record"), Mapping)
        for item in history
    )
    if maximum_iterations < 1 or (not recovery_resume and valid_group_iteration >= maximum_iterations):
        return _terminal(
            "maximum_iterations", iteration=iteration,
            detail=(f"maximum valid-flight iteration count {maximum_iterations} reached for "
                    f"{coordinate_group}"),
            record=record,
        )

    def active_scaled(record_value: Mapping[str, Any]) -> np.ndarray:
        residual_values = np.asarray([
            _finite(record_value["physical_acceptance_residuals"][name], name)
            for name in RESIDUAL_NAMES
        ])
        tolerance_values = np.asarray([
            _finite(record_value["acceptance_tolerances"][name], f"{name} tolerance")
            for name in ACCEPTANCE_NAMES
        ])
        return residual_values[rows] / tolerance_values[rows]

    anchor = _accepted_anchor(history, coordinate_group)
    if recovery_resume and coordinate_group != "stripe_1_stripe_2":
        raise CandidateContractError("recovery resume is only valid for the S1/S2 phase")
    current_active_norm = float(np.linalg.norm(active_scaled(record)))
    anchor_active_norm = float(np.linalg.norm(active_scaled(anchor))) if anchor is not None else None
    improvement_floor = _finite(loop["minimum_relative_improvement"], "improvement floor")
    if not 0.0 <= improvement_floor < 1.0:
        raise CandidateContractError("automatic iteration improvement floor is invalid")
    accepted = recovery_resume or anchor_active_norm is None or current_active_norm <= (
        (1.0 - improvement_floor) * anchor_active_norm
    )
    previous_decision = history[-1] if history and isinstance(history[-1], Mapping) else None
    prediction_assessment: dict[str, Any] = {
        "anchor_active_scaled_norm": anchor_active_norm,
        "actual_active_scaled_norm": current_active_norm,
        "accepted": accepted,
    }
    if isinstance(previous_decision, Mapping) and previous_decision.get("coordinate_group") == coordinate_group:
        predicted = previous_decision.get("predicted_physical_acceptance_residuals")
        if isinstance(predicted, Mapping) and anchor is not None:
            predicted_record = {**record, "physical_acceptance_residuals": predicted}
            predicted_norm = float(np.linalg.norm(active_scaled(predicted_record)))
            predicted_reduction = anchor_active_norm - predicted_norm
            actual_reduction = anchor_active_norm - current_active_norm
            prediction_assessment.update({
                "predicted_active_scaled_norm": predicted_norm,
                "predicted_reduction": predicted_reduction,
                "actual_reduction": actual_reduction,
                "realized_over_predicted_reduction": (
                    actual_reduction / predicted_reduction
                    if predicted_reduction > np.finfo(float).eps else None
                ),
            })
    direction_wrong = _prediction_direction_error(previous_decision, record, rows)
    prediction_assessment["prediction_direction_wrong"] = direction_wrong
    rejected_line_count = _same_rejected_line(history, anchor, coordinate_group)
    if not accepted:
        rejected_line_count += 1
        if coordinate_group == "stripe_1_stripe_2" and (
            direction_wrong or rejected_line_count >= 2
        ):
            reason = (
                "prediction_direction_wrong"
                if direction_wrong else "consecutive_same_direction_rejected_candidates"
            )
            prediction_assessment["model_invalid_reason"] = reason
            return _local_model_refresh_required(
                iteration=iteration,
                coordinate_group=coordinate_group,
                record=record,
                anchor=anchor,
                loop=loop,
                assessment=prediction_assessment,
                reason=reason,
                rejected_line_count=rejected_line_count,
            )
        rejected = _invalid_trial_backtrack(
            prior=prior, materialization=materialization, loop=loop, history=history, iteration=iteration,
            reason="residual_stagnation",
            detail=(f"{coordinate_group} candidate was physically valid but its scaled residual norm "
                    f"rose from {anchor_active_norm:.6g} to {current_active_norm:.6g}"),
        )
        rejected["observation_record"] = record
        rejected["prediction_assessment"] = prediction_assessment
        rejected["candidate_accepted"] = False
        rejected["rejected_coordinate_group"] = coordinate_group
        rejected["recovery_state"] = _recovery_state(
            anchor=anchor,
            advance_multiplier=_factor(loop, "advance_multiplier", "damping_factor"),
            backtrack_multiplier=_factor(loop, "backtrack_multiplier", "damping_factor"),
            rejected_line_count=rejected_line_count,
            recovery_origin_voltages_v=rejected.get("recovery_state", {}).get("recovery_origin_voltages_v"),
        )
        return rejected

    if coordinate_group == "stripe_1_stripe_2" and direction_wrong and not recovery_resume:
        prediction_assessment["model_invalid_reason"] = "prediction_direction_wrong"
        return _local_model_refresh_required(
            iteration=iteration,
            coordinate_group=coordinate_group,
            record=record,
            anchor=anchor,
            loop=loop,
            assessment=prediction_assessment,
            reason="prediction_direction_wrong",
            rejected_line_count=0,
            candidate_accepted=True,
        )

    phase_records: list[Mapping[str, Any]] = []
    for item in reversed(history):
        if not isinstance(item, Mapping):
            continue
        historical_record = item.get("observation_record")
        if not isinstance(historical_record, Mapping):
            continue
        if item.get("coordinate_group") != coordinate_group:
            break
        phase_records.append(historical_record)
    phase_records.reverse()

    non_improving_limit = int(loop["maximum_consecutive_non_improving_iterations"])
    if non_improving_limit < 1:
        raise CandidateContractError("automatic iteration improvement controls are invalid")
    norms = [float(np.linalg.norm(active_scaled(item))) for item in phase_records] + [
        float(np.linalg.norm(active_scaled(record)))
    ]
    non_improving = 0
    for previous, current in zip(reversed(norms[:-1]), reversed(norms[1:])):
        relative = (previous - current) / max(previous, np.finfo(float).tiny)
        if relative >= improvement_floor:
            break
        non_improving += 1
    if non_improving >= non_improving_limit and not recovery_resume:
        return _terminal(
            "residual_stagnation", iteration=iteration,
            detail=(f"{coordinate_group} residual norm failed to improve for "
                    f"{non_improving} consecutive valid flights"),
            record=record,
        )

    oscillation_window = int(loop["oscillation_window"])
    residual_history = [active_scaled(item) for item in phase_records[-max(0, oscillation_window - 1):]] + [
        active_scaled(record)
    ]
    if oscillation_window >= 3 and len(residual_history) == oscillation_window:
        flips = [float(np.dot(left, right)) < 0.0 for left, right in zip(residual_history, residual_history[1:])]
        recent_norms = norms[-oscillation_window:]
        if all(flips) and min(recent_norms) >= (1.0 - improvement_floor) * recent_norms[0]:
            return _terminal(
                "oscillation", iteration=iteration,
                detail=f"residual direction alternated for {oscillation_window} flights without improvement",
                record=record,
            )

    base_jacobian = np.asarray(prior.get("physical_jacobian_rows"), dtype=float)
    if base_jacobian.shape != (4, 4) or not np.all(np.isfinite(base_jacobian)):
        raise CandidateContractError("prior physical Jacobian must be a finite 4x4 matrix")
    physical_jacobian = _physical_jacobian(
        base_jacobian,
        target_ratio=target_ratio,
        tangent_residual=residuals[1],
    )
    jacobian = _latest_phase_jacobian(history, coordinate_group, physical_jacobian)
    jacobian = _broyden_update(jacobian, anchor, record)
    subsystem = jacobian[np.ix_(rows, indices)]
    if np.linalg.matrix_rank(subsystem) != 2:
        return _terminal(
            "solver_failure", iteration=iteration,
            detail="selected two-coordinate Jacobian is rank deficient", record=record,
        )
    numerics = prior.get("resolved_numerics")
    if not isinstance(numerics, Mapping):
        raise CandidateContractError("prior workpoint lacks resolved numerics")
    parameter_scales = _vector(numerics.get("parameter_scales_v"), 4, "parameter voltage scales")[indices]
    tolerances = _record_tolerances(record)[rows]
    scaled_subsystem = (subsystem / tolerances[:, None]) * parameter_scales[None, :]
    condition_number = float(np.linalg.cond(scaled_subsystem))
    scaled_residual = _record_physical_vector(record)[rows] / tolerances
    if not math.isfinite(condition_number):
        return _terminal("solver_failure", iteration=iteration,
                         detail="selected scaled two-coordinate Jacobian is singular", record=record)
    try:
        if condition_number > 100.0:
            # The scale makes the ridge dimensionless.  It prevents the nearly
            # parallel S controls from turning small flight noise into a large step.
            ridge = 1.0e-4
            normalized = np.linalg.solve(
                scaled_subsystem.T @ scaled_subsystem + ridge * np.eye(2),
                -scaled_subsystem.T @ scaled_residual,
            )
            model_solver = "ridge_regularized_scaled_least_squares"
        else:
            normalized = np.linalg.solve(scaled_subsystem, -scaled_residual)
            model_solver = "scaled_direct_solve"
    except np.linalg.LinAlgError as exc:
        return _terminal("solver_failure", iteration=iteration,
                         detail=f"two-coordinate scaled solve failed: {exc}", record=record)
    raw = normalized * parameter_scales
    previous_state = _latest_recovery_state(history)
    advance_multiplier = _factor(loop, "advance_multiplier", "damping_factor")
    trusted_prediction_count = 0
    if isinstance(previous_state, Mapping):
        advance_multiplier = _finite(
            previous_state.get("advance_multiplier", advance_multiplier), "stored advance multiplier"
        )
        trusted_prediction_count = int(previous_state.get("trusted_prediction_count", 0))
        if trusted_prediction_count < 0:
            raise CandidateContractError("stored trusted prediction count is invalid")
    rho = prediction_assessment.get("realized_over_predicted_reduction")
    if isinstance(rho, (int, float)) and math.isfinite(float(rho)) and float(rho) >= 0.75:
        trusted_prediction_count += 1
        advance_multiplier = min(1.0, advance_multiplier + 0.25)
        prediction_assessment["prediction_confidence"] = "trusted"
    else:
        trusted_prediction_count = 0
        if isinstance(rho, (int, float)) and math.isfinite(float(rho)):
            # A physical improvement can still be a poor local prediction.
            # Preserve that accepted evidence for the Broyden update, but do
            # not let the next proposal inherit its prior aggressive range.
            advance_multiplier *= _factor(loop, "backtrack_multiplier", "damping_factor")
            prediction_assessment["prediction_confidence"] = "poor_shrunk"
        else:
            prediction_assessment["prediction_confidence"] = "unmeasured"
    raw *= advance_multiplier
    maximum = _vector(numerics.get("maximum_abs_step_v"), 4, "maximum voltage step")[indices]
    provisional_bound = None
    if recovery_resume:
        for item in reversed(history):
            if not isinstance(item, Mapping) or item.get("coordinate_group") != coordinate_group:
                continue
            validation = item.get("local_s_model_validation")
            if isinstance(validation, Mapping) and (
                validation.get("validation_status") == "provisional_no_nearby_history"
                and validation.get("first_correction_requires_real_prediction_acceptance") is True
            ):
                provisional_bound = _finite(
                    validation.get("first_correction_max_linf_v"),
                    "provisional S recovery correction bound",
                )
                if provisional_bound <= 0.0:
                    raise CandidateContractError("provisional S recovery correction bound must be positive")
                maximum = np.minimum(maximum, provisional_bound)
                break
    lower = _vector(numerics.get("lower_bounds_v"), 4, "lower voltage bounds")[indices]
    upper = _vector(numerics.get("upper_bounds_v"), 4, "upper voltage bounds")[indices]
    alpha = 1.0
    for offset, component in enumerate(raw):
        if component != 0.0:
            alpha = min(alpha, maximum[offset] / abs(component))
        coordinate = voltages[indices[offset]]
        if component > 0.0:
            alpha = min(alpha, (upper[offset] - coordinate) / component)
        elif component < 0.0:
            alpha = min(alpha, (lower[offset] - coordinate) / component)
    alpha = max(0.0, min(1.0, float(alpha)))
    if alpha <= 0.0:
        return _terminal(
            "voltage_bound", iteration=iteration,
            detail="no bounded trust-region step remains", record=record,
        )
    delta = np.zeros(4)
    delta[indices] = alpha * raw
    minimum_step = _finite(loop["minimum_step_linf_v"], "minimum voltage step")
    if float(np.max(np.abs(delta))) < minimum_step:
        return _terminal(
            "step_too_small", iteration=iteration,
            detail=f"bounded step is smaller than {minimum_step} V", record=record,
        )
    proposed = voltages + delta
    predicted_physical = _record_physical_vector(record) + jacobian @ delta
    prediction_assessment["next_advance_multiplier"] = advance_multiplier
    if recovery_resume:
        prediction_assessment["recovery_resume"] = True
        prediction_assessment["first_real_prediction_acceptance_required"] = True
        prediction_assessment["provisional_local_model_bound_v"] = provisional_bound
    return {
        "schema_version": 1,
        "role": "mrtof_downstream_workpoint_iteration_decision",
        "state": "continue",
        "terminal_reason": None,
        "iteration": iteration,
        "coordinate_group": coordinate_group,
        "observation_record": record,
        "accepted_workpoint": record,
        "candidate_accepted": True,
        "recovery_resume_proposal": recovery_resume,
        "prediction_assessment": prediction_assessment,
        "recovery_state": _recovery_state(
            anchor=record,
            advance_multiplier=advance_multiplier,
            backtrack_multiplier=_factor(loop, "backtrack_multiplier", "damping_factor"),
            trusted_prediction_count=trusted_prediction_count,
        ),
        "local_physical_jacobian_rows": jacobian.tolist(),
        "scaled_subsystem_condition_number": condition_number,
        "model_solver": model_solver,
        "predicted_physical_acceptance_residuals": dict(
            zip(RESIDUAL_NAMES, predicted_physical.tolist(), strict=True)
        ),
        "raw_damped_subsystem_step_v": raw.tolist(),
        "trust_scale": alpha,
        "applied_correction_v": delta.tolist(),
        "proposed_voltages_v": proposed.tolist(),
        "next_action": "run_real_center_flight_on_reused_fixed_response_fields",
    }


def _print_iteration_summary(result: Mapping[str, Any], observation: Mapping[str, Any]) -> None:
    iteration = result.get("iteration")
    static = observation.get("static_return_diagnostic")
    detector_pass = bool(
        isinstance(static, Mapping)
        and static.get("status") == "detector_hit"
        and static.get("event_contract_ok") is True
    )
    record = result.get("observation_record")
    if isinstance(record, Mapping):
        values = record["physical_acceptance_residuals"]
        limits = record["acceptance_tolerances"]
        metric_fields = (
            ("mirror_y_mm", RESIDUAL_NAMES[0], ACCEPTANCE_NAMES[0]),
            ("p2_angle_deg", RESIDUAL_NAMES[1], ACCEPTANCE_NAMES[1]),
            ("slow_turn_y_mm", RESIDUAL_NAMES[2], ACCEPTANCE_NAMES[2]),
            ("target_phase_y_mm", RESIDUAL_NAMES[3], ACCEPTANCE_NAMES[3]),
        )
        fields = []
        for label, value_name, limit_name in metric_fields:
            value = float(values[value_name])
            limit = float(limits[limit_name])
            fields.extend((
                f"{label}={value:.12g}", f"{label}_limit={limit:.12g}",
                f"{label}_result={'PASS' if abs(value) <= limit else 'FAIL'}",
            ))
        print(
            "MRTOF_WORKPOINT_TOLERANCE "
            f"iteration={iteration} topology={observation.get('return_topology')} "
            f"detector_result={'PASS' if detector_pass else 'FAIL'} " + " ".join(fields),
            flush=True,
        )
    else:
        print(
            "MRTOF_WORKPOINT_TOLERANCE "
            f"iteration={iteration} topology={observation.get('return_topology')} "
            f"detector_result={'PASS' if detector_pass else 'FAIL'} evidence=INVALID "
            f"reason={result.get('invalid_trial_reason', result.get('terminal_reason'))}",
            flush=True,
        )
    correction = result.get("applied_correction_v")
    proposed = result.get("proposed_voltages_v")
    if isinstance(correction, list) and isinstance(proposed, list):
        print(
            "MRTOF_WORKPOINT_STEP "
            f"iteration={iteration} group={result.get('coordinate_group')} "
            f"delta_v={','.join(f'{float(value):.12g}' for value in correction)} "
            f"proposed_v={','.join(f'{float(value):.12g}' for value in proposed)}",
            flush=True,
        )
    assessment = result.get("prediction_assessment")
    if isinstance(assessment, Mapping):
        fields = [f"{name}={value}" for name, value in assessment.items()]
        print(
            "MRTOF_WORKPOINT_MODEL "
            f"iteration={iteration} group={result.get('coordinate_group')} "
            f"condition={result.get('scaled_subsystem_condition_number')} "
            f"solver={result.get('model_solver')} {' '.join(fields)}",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--child-manifest", type=Path)
    parser.add_argument("--materialization", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--iteration", type=int)
    parser.add_argument("--cache-identity", type=Path)
    parser.add_argument("--cache-protection-renewal", type=Path)
    parser.add_argument("--expected-lease-id")
    parser.add_argument("--expected-lease-owner")
    parser.add_argument("--refresh-anchor-observation", type=Path)
    parser.add_argument("--refresh-anchor-materialization", type=Path)
    parser.add_argument("--refresh-s1-observation", type=Path)
    parser.add_argument("--refresh-s1-materialization", type=Path)
    parser.add_argument("--refresh-s2-observation", type=Path)
    parser.add_argument("--refresh-s2-materialization", type=Path)
    parser.add_argument("--refresh-history", type=Path)
    parser.add_argument("--refresh-history-window", type=int, default=2)
    parser.add_argument("--refresh-trusted-radius-linf-v", type=float)
    parser.add_argument("--refresh-supported-directions", nargs=2, type=int)
    parser.add_argument("--refresh-position-tolerance-mm", type=float)
    parser.add_argument("--recovery-resume", action="store_true",
                        help="derive the first bounded S candidate from a saved accepted anchor; no flight is implied")
    parser.add_argument("--select-best-physical-workpoint", action="store_true",
                        help="emit the best complete physical workpoint for warning-qualified bunch screening")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.select_best_physical_workpoint:
        if args.history is None:
            parser.error("--select-best-physical-workpoint requires --history")
        history = _load(args.history, "iteration history").get("decisions")
        if not isinstance(history, list):
            raise CandidateContractError("iteration history must contain a decisions list")
        result = select_best_physical_workpoint(history)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"MRTOF_BEST_PHYSICAL_WORKPOINT={result['status']}")
        return 0
    if args.cache_identity is not None:
        if args.cache_protection_renewal is None:
            parser.error("--cache-protection-renewal is required with --cache-identity")
        result = resolve_operating_cache_binding(
            _load(args.cache_identity, "operating PA cache identity"),
            _load(args.cache_protection_renewal, "operating-cache protection renewal"),
            expected_lease_id=args.expected_lease_id,
            expected_lease_owner=args.expected_lease_owner,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"MRTOF_OPERATING_CACHE={result['cache_key']}")
        return 0
    refresh_paths = (
        args.refresh_anchor_observation, args.refresh_anchor_materialization,
        args.refresh_s1_observation, args.refresh_s1_materialization,
        args.refresh_s2_observation, args.refresh_s2_materialization,
    )
    if any(path is not None for path in refresh_paths):
        if (any(path is None for path in refresh_paths) or args.contract is None or args.prior is None
                or args.refresh_history is None):
            parser.error("S refresh requires --prior, --contract, --refresh-history, and all six refresh observation/materialization paths")
        profile, _ = _profile(_load(args.contract, "workpoint contract"))
        records = []
        for observation_path, materialization_path, label in (
            (args.refresh_anchor_observation, args.refresh_anchor_materialization, "anchor"),
            (args.refresh_s1_observation, args.refresh_s1_materialization, "S1"),
            (args.refresh_s2_observation, args.refresh_s2_materialization, "S2"),
        ):
            record, _, _ = _observation_record(_load(observation_path, f"S refresh {label} observation"),
                                                _load(materialization_path, f"S refresh {label} materialization"), profile)
            records.append(record)
        prior = _load(args.prior, "prior workpoint")
        base = np.asarray(prior["physical_jacobian_rows"], dtype=float)
        if base.shape != (4, 4) or not np.all(np.isfinite(base)):
            raise CandidateContractError("S refresh prior Jacobian is invalid")
        columns = refresh_s_local_jacobian(*records)
        history = _load(args.refresh_history, "S refresh history").get("decisions")
        if not isinstance(history, list):
            raise CandidateContractError("S refresh history decisions are invalid")
        validation = validate_s_local_jacobian_against_history(
            records[0], columns, history,
            maximum_comparisons=args.refresh_history_window,
            trusted_radius_linf_v=args.refresh_trusted_radius_linf_v,
            supported_directions=args.refresh_supported_directions,
            position_tolerance_mm=args.refresh_position_tolerance_mm,
        )
        refreshed = merge_s_local_jacobian(base, columns)
        result = {"schema_version": 1, "role": "mrtof_s_local_jacobian_refresh",
                  "anchor_record": records[0], "local_s_physical_jacobian_columns": columns.tolist(),
                  "local_physical_jacobian_rows": refreshed.tolist(), "history_validation": validation}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"MRTOF_S_LOCAL_JACOBIAN_REFRESH={'PASS' if validation['passed'] else 'REJECTED'}")
        return 0
    required = {
        "--prior": args.prior,
        "--child-manifest": args.child_manifest,
        "--observation": args.observation,
        "--materialization": args.materialization,
        "--contract": args.contract,
        "--history": args.history,
        "--iteration": args.iteration,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error(f"decision mode requires {', '.join(missing)}")
    history = _load(args.history, "iteration history").get("decisions")
    if not isinstance(history, list):
        raise CandidateContractError("iteration history must contain a decisions list")
    prior = _load(args.prior, "prior workpoint")
    child = assert_trial_matches_jacobian(prior, args.child_manifest)
    records = child["consumer_projection"]["records"]
    from common.contracts.file_identity import file_sha256
    for name, path in (("two_prism_trial_observation.json", args.observation),
                       ("two_prism_trial_materialization.json", args.materialization)):
        if file_sha256(path).lower() != str(records[name]["sha256"]).lower():
            raise CandidateContractError(f"decision input differs from child manifest: {name}")
    observation = _load(args.observation, "real-flight observation")
    result = decide_iteration(
        prior,
        observation,
        _load(args.materialization, "real-flight materialization"),
        _load(args.contract, "project contract"),
        history,
        args.iteration,
        recovery_resume=args.recovery_resume,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_DOWNSTREAM_ITERATION={result['state']}:{result['terminal_reason']}")
    _print_iteration_summary(result, observation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
