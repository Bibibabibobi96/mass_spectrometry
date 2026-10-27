"""Finite-state controller for real-flight downstream workpoint iteration.

The controller is solver-neutral: one invocation consumes exactly one genuine
centre-particle observation and either accepts it, stops with a named terminal
reason, or proposes one bounded P1/P2 or S1/S2 trust-region step.  The calling
workflow owns SIMION execution and manifest publication.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import linprog

from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.file_identity import file_sha256

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import (
    RESIDUAL_NAMES,
    UNKNOWN_NAMES,
    native_bank_identity,
    assert_trial_matches_jacobian,
    _trial,
    resolve_numerics,
    resolve_active_stripe_axes,
    workpoint_residual_names,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point import (
    measured_prism_jacobian,
    _same_frozen_problem,
)


from projects.parallel_mirror_dual_stripe_mr_tof.analysis.workpoint_controller_state import (
    dispatch_controller_request, relative_voltage_step,
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


def resolve_prism_controller_policy(
    policy_path: Path,
) -> dict[str, Any]:
    """Resolve a frozen P-only controller authority without changing flight inputs."""
    policy = _load(policy_path, "prism controller policy")
    if (set(policy) != {"schema_version", "role", "scope", "prediction_error_fraction_of_acceptance_tolerance",
                       "trusted_advance_multiplier"}
            or policy["schema_version"] != 1
            or policy["role"] != "mrtof_prism_controller_policy"
            or policy["scope"] != "future_prism_proposals"):
        raise CandidateContractError("prism controller policy identity or scope differs")
    quality = _finite(policy["prediction_error_fraction_of_acceptance_tolerance"], "P prediction quality fraction")
    advance = _finite(policy["trusted_advance_multiplier"], "P trusted Newton fraction")
    if not 0 < quality < 1 or not 0 < advance <= 1:
        raise CandidateContractError("P controller quality and Newton fractions are invalid")
    return dict(path=str(policy_path.resolve()), sha256=file_sha256(policy_path), **policy)


def assert_bounded_controller_resume(
    previous: Mapping[str, Any], current: Mapping[str, Any], stage_state: Mapping[str, Any] | None,
    *, budget_only: bool = False,
) -> dict[str, Any]:
    """Validate an explicit total budget extension or the original bounded advance change.

    ``None`` checks contract compatibility before a stage state is available;
    actual checkpoint resume must pass its sealed state to preserve debits.
    """
    old, new = copy.deepcopy(dict(previous)), copy.deepcopy(dict(current))
    old_loop = old["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]
    new_loop = new["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]
    old_advance = _factor(old_loop, "advance_multiplier", "damping_factor")
    new_advance = _factor(new_loop, "advance_multiplier", "damping_factor")
    old_max, new_max = old_loop["maximum_iterations"], new_loop["maximum_iterations"]
    used = stage_state["candidate_count"] if stage_state is not None else None
    if (any(isinstance(x, bool) or not isinstance(x, int) for x in (old_max, new_max))
            or old_max < 1 or new_max < old_max
            or (stage_state is not None and (type(used) is not int or not 0 <= used <= old_max))):
        raise CandidateContractError("controller resume requires a nondecreasing integer total budget and preserved debits")
    only_budget = old_advance == new_advance and new_max > old_max
    legacy_advance = (not budget_only and old_advance == .5 and new_loop.get("advance_multiplier") == 1.0
                      and not isinstance(new_loop.get("advance_multiplier"), bool)
                      and new_max in (old_max, old_max + 1))
    if not (only_budget or legacy_advance):
        raise CandidateContractError("controller resume requires only a larger total budget or the bounded half-to-full advance")
    for loop in (old_loop, new_loop):
        if not only_budget:
            loop.pop("advance_multiplier", None)
        loop.pop("maximum_iterations")
    if old != new:
        raise CandidateContractError("controller resume differs beyond advance and candidate limit")
    return dict(advance_multiplier=dict(previous=old_advance, current=new_advance),
                maximum_iterations=dict(previous=old_max, current=new_max),
                preserved_candidate_count=used,
                change_kind="execution_budget_only" if only_budget else "bounded_half_to_full_advance")


def assess_staged_prediction(
    decision: Mapping[str, Any], anchor: Mapping[str, Any], current: Mapping[str, Any],
    contract: Mapping[str, Any], policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Assess measured P/S prediction using the existing policy's tolerance fraction, not a voltage policy."""
    predicted = decision.get("predicted_physical_acceptance_residuals")
    if policy is None or not isinstance(predicted, Mapping):
        return dict(status="unmeasured", reason="no_quality_authority_or_prediction")
    if (current["observation"].get("return_topology") != anchor["observation"].get("return_topology")
            or current["observation"].get("termination_diagnostic", {}).get("physical_collision") is True):
        return dict(status="unmeasured", reason="changed_or_invalid_return_branch")
    profile, _ = _profile(contract)
    try:
        if decision.get("next_action") == "run_P_candidate":
            # The frozen decision contains the CLI-compiled proposal bounds.
            numerics = (decision["resolved_numerics"] if "resolved_numerics" in decision
                        else resolve_numerics(contract, current))
            if not isinstance(numerics, Mapping):
                raise CandidateContractError("staged prediction resolved numerics must be an object")
            result = decide_prism_preclosure(current, None, None, contract,
                                            numerics, require_columns=False)
            actual = result["physical_acceptance_residuals"]
            names = result.get("prism_acceptance_names", ACCEPTANCE_NAMES[:2])
            tolerances = (result["prism_acceptance_tolerances"] if "prism_acceptance_tolerances" in result else
                          [profile["automatic_iteration"]["acceptance_tolerances"][name] for name in names])
        else:
            if _slow_turn_signature_comparison(anchor, current) == "mismatch":
                return dict(status="unmeasured", reason="changed_slow_turn_branch")
            record = _stripe_stage_record(current, profile)
            actual = record["physical_acceptance_residuals"]
            names, tolerances = record.get("residual_names", RESIDUAL_NAMES), _record_tolerances(record)
    except (KeyError, CandidateContractError):
        return dict(status="unmeasured", reason="missing_valid_stage_events")
    if set(predicted) != set(names):
        return dict(status="unmeasured", reason="incomplete_prediction_rows")
    observed_v = _vector(current["voltages_v"], 4, "executed voltages")
    base_values = decision.get("physical_acceptance_residuals")
    if decision.get("next_action") == "run_P_candidate" and "physical_jacobian_rows" in decision:
        axes, model = (2, 3), decision["physical_jacobian_rows"]
    elif "joint_physical_jacobian_columns" in decision:
        axes, model = tuple(decision["joint_active_axes"]), decision["joint_physical_jacobian_columns"]
        base_values = decision["observation_record"]["physical_acceptance_residuals"]
    elif "local_s_physical_jacobian_columns" in decision:
        axes, model = resolve_active_stripe_axes(profile), decision["local_s_physical_jacobian_columns"]
        base_values = decision["observation_record"]["physical_acceptance_residuals"]
    else:
        axes, model = (), None
    if model is not None:
        matrix = np.asarray(model, dtype=float)
        if matrix.shape != (len(names), len(axes)) or not np.all(np.isfinite(matrix)):
            raise CandidateContractError("staged prediction model rows or columns differ")
        executed = observed_v - _vector(decision["voltages_v"], 4, "prediction anchor voltages")
        computed = np.asarray([_finite(base_values[name], name) for name in names]) + matrix @ executed[list(axes)]
        predicted = dict(zip(names, computed.tolist(), strict=True))
    elif decision.get("next_voltages_v") != observed_v.tolist():
        return dict(status="unmeasured", reason="executed_step_differs_without_a_model")
    errors = {name: (_finite(actual[name], name)-_finite(predicted[name], name)) /
              _finite(tolerance, name+" tolerance") for name, tolerance in zip(names, tolerances, strict=True)}
    maximum = max(abs(value) for value in errors.values())
    threshold = _finite(policy["prediction_error_fraction_of_acceptance_tolerance"], "prediction quality fraction")
    wrong_direction = False
    if isinstance(base_values, Mapping) and all(name in base_values for name in names):
        predicted_change = np.asarray([(predicted[name]-base_values[name])/tol for name, tol in zip(names, tolerances, strict=True)])
        actual_change = np.asarray([(actual[name]-base_values[name])/tol for name, tol in zip(names, tolerances, strict=True)])
        wrong_direction = float(predicted_change @ actual_change) < 0
    return dict(status="trusted" if maximum <= threshold and not wrong_direction else "poor", normalized_errors=errors,
                prediction_direction_wrong=wrong_direction, predicted_executed_residuals=dict(predicted),
                maximum_normalized_error=maximum, threshold_fraction=threshold,
                threshold_authority=policy.get("path"), scope="measured_prediction_quality_only")


def _field_binding_reference(field_binding: Mapping[str, Any]) -> dict[str, Any]:
    reference = {name: copy.deepcopy(field_binding[name]) for name in (
        "mode", "path", "representation", "response_weight_l1_norm", "sources"
    ) if name in field_binding}
    if "response_terms" in field_binding:
        reference["response_terms"] = [
            {"coefficient": term["coefficient"], "binding_path": term["binding_path"]}
            for term in field_binding["response_terms"]
        ]
    return reference


def compact_saved_iteration_state(value: Any) -> Any:
    """Read saved controller evidence without duplicating sealed field payloads."""
    if isinstance(value, list):
        return [compact_saved_iteration_state(item) for item in value]
    if not isinstance(value, Mapping):
        return copy.deepcopy(value)
    source = dict(value)
    stage_record = source.pop("stage_observation_record", None)
    if stage_record is not None:
        source.setdefault("observation_record", stage_record)
    result = {name: compact_saved_iteration_state(item) for name, item in source.items()}
    if ("voltages_v" in source and "residuals" in source
            and isinstance(source.get("field_binding"), Mapping)):
        result["field_binding"] = _field_binding_reference(source["field_binding"])
    return result


def _observation_record(
    observation: Mapping[str, Any], materialization: Mapping[str, Any], profile: Mapping[str, Any]
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    residual_map = observation.get("residuals")
    if not isinstance(residual_map, Mapping):
        raise CandidateContractError("real flight lacks downstream residuals")
    names = workpoint_residual_names(materialization)
    residuals = np.asarray([_finite(residual_map.get(name), name) for name in names])
    target_ratio = _finite(
        materialization.get("target_low_field_tangent_ratio_vy_over_vz"), "target tangent ratio"
    )
    tolerances = profile["automatic_iteration"]["acceptance_tolerances"]
    if not isinstance(tolerances, Mapping) or set(tolerances) != set(ACCEPTANCE_NAMES):
        raise CandidateContractError("automatic iteration tolerances must name all four residuals")
    physical = residuals.copy()
    target = materialization.get("prism_handoff_target")
    acceptance_names = names if target is not None else ACCEPTANCE_NAMES
    if target is None:
        physical[1] = math.degrees(math.atan(target_ratio + residuals[1]) - math.atan(target_ratio))
    tolerance_vector = np.asarray([
        _finite(tolerances[name], f"{name} acceptance tolerance") for name in ACCEPTANCE_NAMES
    ])
    if target is not None:
        tolerance_vector[1] = _finite(target.get("energy_tolerance_per_charge_v"), "clean energy tolerance")
    if np.any(tolerance_vector <= 0.0):
        raise CandidateContractError("automatic iteration acceptance tolerances must be positive")
    voltages = _vector([
        *materialization.get("stripe_biases_v", []),
        *materialization.get("prism_voltages_v", []),
    ], 4, "materialized downstream voltages")
    scaled = physical / tolerance_vector
    record = {
        "voltages_v": voltages.tolist(),
        "residuals": dict(zip(names, residuals.tolist(), strict=True)),
        "physical_acceptance_residuals": dict(zip(names, physical.tolist(), strict=True)),
        "acceptance_tolerances": dict(zip(acceptance_names, tolerance_vector.tolist(), strict=True)),
        "scaled_residual_norm": float(np.linalg.norm(scaled)),
        "maximum_scaled_abs_residual": float(np.max(np.abs(scaled))),
    }
    if target is not None:
        record.update(residual_names=list(names), acceptance_names=list(acceptance_names), prism_handoff_target=copy.deepcopy(target))
    field_binding = materialization.get("field_binding")
    if field_binding is not None:
        if (not isinstance(field_binding, Mapping)
                or field_binding.get("mode") not in ("comsol_static_scalar_v", "native_static_pa")
                or not isinstance(field_binding.get("path"), str)
                or not field_binding["path"]):
            raise CandidateContractError("static observation requires its actually flown field binding")
        # The sealed child materialization owns the full field authority.  A
        # controller history needs its actual reference, not another field tree.
        record["field_binding"] = _field_binding_reference(field_binding)
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
        for name in record.get("residual_names", RESIDUAL_NAMES)
    ])


def _record_tolerances(record: Mapping[str, Any]) -> np.ndarray:
    return np.asarray([
        _finite(record["acceptance_tolerances"][name], f"{name} tolerance")
        for name in record.get("acceptance_names", ACCEPTANCE_NAMES)
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
    """Select the lowest-demand fully qualified flight for downstream use.

    A controller can reject a physically complete flight solely because its
    improvement is below the iteration floor.  That evidence remains eligible
    for Candidate bunch screening; topology/collision failures never are.  P
    voltage magnitude is the primary selection criterion once P1/P2 have met
    their physical constraints.  Residuals then distinguish electrically
    equivalent choices. No warning-only point can authorize bunch flight.
    """
    candidates: list[tuple[tuple[float, float, float, float, int], Mapping[str, Any]]] = []
    for ordinal, item in enumerate(history, start=1):
        if not isinstance(item, Mapping):
            continue
        record = item.get("observation_record")
        eligible = (
            (item.get("candidate_accepted") is True and item.get("invalid_trial_reason") is None)
            or item.get("invalid_trial_reason") == "residual_stagnation"
            or item.get("terminal_reason") == "success"
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
            if not all(name in residuals for name in record.get("residual_names", RESIDUAL_NAMES)):
                continue
            if not all(name in tolerances for name in record.get("acceptance_names", ACCEPTANCE_NAMES)):
                continue
            physical_residuals = _record_physical_vector(record)
            physical_tolerances = _record_tolerances(record)
            if np.any(physical_tolerances <= 0.0) or np.any(
                np.abs(physical_residuals) > physical_tolerances
            ):
                continue
        except (CandidateContractError, KeyError, TypeError):
            continue
        p_peak_abs_v = float(np.max(np.abs(voltages[2:])))
        p_total_abs_v = float(np.sum(np.abs(voltages[2:])))
        candidates.append(((p_peak_abs_v, p_total_abs_v, norm, maximum, ordinal), record))
    if not candidates:
        raise CandidateContractError(
            "history has no topology-valid workpoint satisfying every downstream tolerance"
        )
    (p_peak_abs_v, p_total_abs_v, norm, maximum, ordinal), record = min(candidates, key=lambda value: value[0])
    return {
        "schema_version": 1,
        "role": "mrtof_best_physical_workpoint_handoff",
        "status": "within_tolerance",
        "qualification": "candidate_bunch_screening_authorized",
        "selected_history_ordinal": ordinal,
        "selected_workpoint": copy.deepcopy(dict(record)),
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
        "warnings": [],
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
    topology_boundary_voltages_v: Sequence[float] | None = None,
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
        "topology_boundary_voltages_v": (
            _vector(topology_boundary_voltages_v, 4, "topology boundary voltages").tolist()
            if topology_boundary_voltages_v is not None else None
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
    anchor: Mapping[str, Any], stripe_1: Mapping[str, Any], stripe_2: Mapping[str, Any] | None,
    *, axes: Sequence[int] = (0, 1),
) -> np.ndarray:
    """Measure the named S columns from independent accepted-anchor flights."""
    anchor_v = _vector(anchor["voltages_v"], 4, "S refresh anchor voltages")
    anchor_r = _record_physical_vector(anchor)
    columns: list[np.ndarray] = []
    samples = (stripe_1, stripe_2)
    for index in axes:
        sample = samples[index]
        if sample is None:
            raise CandidateContractError("S refresh is missing an active-axis observation")
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
            topology_boundary_voltages_v=(
                current
                if reason == "collision_or_invalid_topology"
                else (
                    previous_state.get("topology_boundary_voltages_v")
                    if isinstance(previous_state, Mapping) else None
                )
            ),
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


def scaled_two_coordinate_step(
    subsystem: np.ndarray, residuals: np.ndarray,
    parameter_scales: np.ndarray, tolerances: np.ndarray,
) -> tuple[np.ndarray, str, float]:
    """Shared scaled correction; rectangular S1 uses measured least squares."""
    scaled = (subsystem / tolerances[:, None]) * parameter_scales[None, :]
    condition = float(np.linalg.cond(scaled))
    rhs = residuals / tolerances
    if not math.isfinite(condition):
        raise np.linalg.LinAlgError("selected scaled two-coordinate Jacobian is singular")
    if scaled.shape[0] != scaled.shape[1]:
        normalized, _remaining, rank, _singular = np.linalg.lstsq(scaled, -rhs, rcond=None)
        if rank != scaled.shape[1]:
            raise np.linalg.LinAlgError("selected rectangular Jacobian lacks an active voltage direction")
        method = "scaled_rectangular_least_squares"
    elif condition > 100.0:
        normalized = np.linalg.solve(
            scaled.T @ scaled + 1.0e-4 * np.eye(2), -scaled.T @ rhs,
        )
        method = "ridge_regularized_scaled_least_squares"
    else:
        normalized = np.linalg.solve(scaled, -rhs)
        method = "scaled_direct_solve"
    return normalized * parameter_scales, method, condition


def bounded_coordinate_step(
    voltages: np.ndarray, raw: np.ndarray, maximum: np.ndarray,
    lower: np.ndarray, upper: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Scale a continuous direction once, preserving its two-axis direction."""
    alpha = 1.0
    for offset, component in enumerate(raw):
        if component != 0.0:
            alpha = min(alpha, maximum[offset] / abs(component))
        if component > 0.0:
            alpha = min(alpha, (upper[offset] - voltages[offset]) / component)
        elif component < 0.0:
            alpha = min(alpha, (lower[offset] - voltages[offset]) / component)
    alpha = max(0.0, min(1.0, float(alpha)))
    return alpha * raw, alpha


def _prism_stage_record(trial: Mapping[str, Any]) -> dict[str, Any]:
    observation, materialization = trial["observation"], trial["materialization"]
    stage = observation.get("center_particle_prism_handoff_validation")
    if not isinstance(stage, Mapping) or stage.get("status") != "observed" or stage.get("particle_id") != 1:
        raise CandidateContractError("P preclosure requires the observed independent centre P handoff")
    frozen = trial.get("frozen_problem")
    if not isinstance(frozen, Mapping) or not frozen:
        raise CandidateContractError("P preclosure requires the existing frozen field/source problem")
    prisms = _vector(materialization.get("prism_voltages_v"), 2, "P voltages")
    if observation.get("prism_voltages_v") != prisms.tolist():
        raise CandidateContractError("P observation and materialization voltages differ")
    stripes = _vector(materialization.get("stripe_biases_v"), 2, "S voltages")
    residuals = stage.get("residuals")
    if not isinstance(residuals, Mapping):
        raise CandidateContractError("P stage residuals are missing")
    states = {}
    for name in ("p2_low_field_reference_state", "positive_mirror_turn_state"):
        state = stage.get(name)
        if not isinstance(state, Mapping):
            raise CandidateContractError(f"P stage lacks {name}")
        states[name] = {key: _vector(state.get(key), 3, name).tolist()
                        for key in ("position_mm", "velocity_mm_per_us")}
    names = workpoint_residual_names(materialization)[:2]
    target = materialization.get("prism_handoff_target")
    if target is not None:
        if stripes[1] != 0.0:
            raise CandidateContractError("clean-phase P stage must keep inactive S2 grounded")
        state = stage.get("first_clean_phase_state")
        if not isinstance(state, Mapping):
            raise CandidateContractError("clean P stage lacks its first central phase state")
        states["first_clean_phase_state"] = copy.deepcopy(state)
    source_identity = {key: materialization.get("inputs", {}).get(key) for key in (
        "contract_sha256", "reviewed_contract_sha256", "mirror_summary_sha256",
        "stripe_summary_sha256", "accelerator_receipt_sha256")}
    science_inputs = frozen.get("inputs", {})
    for raw_key, science_key in (
        ("contract_sha256", "trajectory_physics_contract_sha256"),
        ("reviewed_contract_sha256", "reviewed_physics_contract_sha256"),
    ):
        if science_key in science_inputs:
            # _trial already verified the raw sealed record before this projection.
            source_identity[raw_key] = science_inputs[science_key]
    if "source_center_projection" in frozen:
        if not isinstance(frozen["source_center_projection"],Mapping):
            raise CandidateContractError("P preclosure source projection must be an object")
        selection = materialization.get("source_selection", {})
        mother_keys = ("source_receipt_sha256", "parent_particle_states_sha256", "parent_particle_count")
        centroid = frozen["source_center_projection"].get("role") == "measured_exit_centroid"
        if centroid:
            center = frozen["source_center_projection"]
            if (materialization.get("source_projection") != "measured_exit_centroid"
                    or center.get("cohort") != "constructed_measured_exit_centroid_probe"
                    or not isinstance(center.get("mother_source_receipt"), Mapping)
                    or not isinstance(center.get("probe_source_receipt"), Mapping)
                    or center["probe_source_receipt"].get("role") != "mrtof_measured_exit_centroid_probe_source"
                    or SHA256_PATTERN.fullmatch(str(center["probe_source_receipt"].get("canonical_sha256",""))) is None
                    or not isinstance(center.get("state"), Mapping)
                    or selection):
                raise CandidateContractError("Measured centroid P source lacks its independent probe identity")
            source_identity["center"] = copy.deepcopy(center)
        elif (not isinstance(selection, Mapping)
                or selection.get("role") != "contiguous_frozen_source_diagnostic_selection"
                or any(selection.get(key) is None for key in mother_keys)):
            raise CandidateContractError("P preclosure centre source lacks its frozen mother identity")
        else:
            source_identity["center"] = copy.deepcopy(frozen["source_center_projection"])
        # Mother identity remains in the sealed materialization. A physically
        # identical selected centre may come from a different diagnostic cohort.
    return dict(
        prism_voltages_v=prisms.tolist(), stripe_biases_v=stripes.tolist(),
        residual_vector=[_finite(residuals.get(name), name) for name in names],
        **({"prism_handoff_target": copy.deepcopy(target), "residual_names": list(names),
            "residual_scales": [trial["frozen_problem"]["targets"]["target_slow_turn_y_mm"], target["slow_energy_reference_per_charge_v"]]}
           if target is not None else {}),
        source_identity=source_identity,
        target_positive_mirror_turn_y_mm=_finite(
            materialization.get("target_positive_mirror_turn_y_mm"), "P turn target"),
        target_low_field_tangent_ratio_vy_over_vz=_finite(
            materialization.get("target_low_field_tangent_ratio_vy_over_vz"), "P angle target"),
        p2_low_field_reference_section=materialization["p2_low_field_reference_section"],
        frozen_problem=copy.deepcopy(dict(frozen)), **states,
    )


def _missing_prism_stage_decision(trial: Mapping[str, Any]) -> dict[str, Any] | None:
    """Valid flight inputs with an absent P event are physical rejects, not corrupt contracts."""
    observation, receipt = trial["observation"], trial["materialization"]
    frozen = trial.get("frozen_problem")
    if not isinstance(frozen, Mapping) or not frozen:
        raise CandidateContractError("P preclosure requires the existing frozen field/source problem")
    prisms = _vector(receipt.get("prism_voltages_v"), 2, "P voltages")
    stripes = _vector(receipt.get("stripe_biases_v"), 2, "S voltages")
    if observation.get("prism_voltages_v") != prisms.tolist():
        raise CandidateContractError("P observation and materialization voltages differ")
    stage = observation.get("center_particle_prism_handoff_validation")
    if isinstance(stage, Mapping) and stage.get("status") == "observed":
        if stage.get("particle_id") != 1:
            raise CandidateContractError("P stage must observe the controlled centre particle")
        return None
    if stage is not None and (not isinstance(stage, Mapping) or stage.get("status") not in {
            "incomplete", "not_available__legacy_source_receipt"}):
        raise CandidateContractError("P stage observation status is invalid")
    voltages = [*stripes.tolist(), *prisms.tolist()]
    return dict(schema_version=1, role="mrtof_prism_preclosure_decision",
                coordinate_group="prism_1_prism_2", status="terminal", state="terminal",
                terminal_reason="collision_or_invalid_topology", next_action="stop_preclosure",
                stage_only=True, full_workpoint_qualified=False, stage_observation_available=False,
                voltages_v=voltages, next_voltages_v=voltages,
                detail="Independent centre P handoff events are unavailable",
                stage_observation=copy.deepcopy(stage),
                termination_diagnostic=copy.deepcopy(observation.get("termination_diagnostic")))


def decide_prism_preclosure(
    baseline: Mapping[str, Any], prism_1_trial: Mapping[str, Any] | None,
    prism_2_trial: Mapping[str, Any] | None, contract: Mapping[str, Any],
    resolved_numerics: Mapping[str, Any],
    *, require_columns: bool = True, controller_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """P-only preclosure; completion authorizes only the next full N=1 check."""
    profile, loop = _profile(contract)
    rejected = _missing_prism_stage_decision(baseline)
    if rejected is not None:
        return rejected
    seed = _prism_stage_record(baseline)
    if seed.get("prism_handoff_target") is not None and resolve_active_stripe_axes(profile) != (0,):
        raise CandidateContractError("clean-phase P target requires only active S1")
    voltages = np.asarray(seed["stripe_biases_v"] + seed["prism_voltages_v"])
    residuals = np.asarray(seed["residual_vector"])
    ratio = seed["target_low_field_tangent_ratio_vy_over_vz"]
    physical = residuals.copy()
    names = tuple(seed.get("residual_names", RESIDUAL_NAMES[:2]))
    acceptance_names = names if seed.get("prism_handoff_target") is not None else ACCEPTANCE_NAMES[:2]
    if seed.get("prism_handoff_target") is None:
        physical[1] = math.degrees(math.atan(ratio + residuals[1]) - math.atan(ratio))
    tolerances = np.asarray([
        _finite(loop["acceptance_tolerances"][name], name) for name in ACCEPTANCE_NAMES[:2]
    ])
    if seed.get("prism_handoff_target") is not None:
        tolerances[1] = seed["prism_handoff_target"]["energy_tolerance_per_charge_v"]
    if np.any(tolerances <= 0):
        raise CandidateContractError("P acceptance tolerances must be positive")
    maximum_residual = float(np.max(np.abs(physical / tolerances)))
    lower = _vector(resolved_numerics.get("lower_bounds_v"), 4, "lower voltage bounds")[2:]
    upper = _vector(resolved_numerics.get("upper_bounds_v"), 4, "upper voltage bounds")[2:]
    if np.any(lower >= upper) or np.any(voltages[2:] < lower) or np.any(voltages[2:] > upper):
        raise CandidateContractError("P baseline lies outside compiled voltage bounds")
    result = dict(
        schema_version=1, role="mrtof_prism_preclosure_decision",
        coordinate_group="prism_1_prism_2",
        stage_only=True, full_workpoint_qualified=False,
        voltages_v=voltages.tolist(), next_voltages_v=voltages.tolist(),
        residuals=dict(zip(names, residuals.tolist(), strict=True)),
        physical_acceptance_residuals=dict(zip(acceptance_names, physical.tolist(), strict=True)),
        maximum_scaled_abs_residual=maximum_residual, observation_record=seed,
    )
    if seed.get("prism_handoff_target") is not None:
        result.update(prism_residual_names=list(names), prism_acceptance_names=list(acceptance_names), prism_acceptance_tolerances=tolerances.tolist())
    if maximum_residual <= 1.0:
        return dict(result, status="stage_passed", next_action="complete_N1")
    if prism_1_trial is None or prism_2_trial is None:
        if not require_columns:
            return dict(result, status="needs_stencil", next_action="measure_stencil")
        raise CandidateContractError("P correction requires both same-anchor measured columns")
    p1, p2 = _prism_stage_record(prism_1_trial), _prism_stage_record(prism_2_trial)
    if any(trial["stripe_biases_v"] != seed["stripe_biases_v"] for trial in (p1, p2)):
        raise CandidateContractError("P preclosure must keep both S voltages fixed")
    jacobian, steps, classification = measured_prism_jacobian(seed, p1, p2, dict(contract))
    physical_jacobian = jacobian.copy()
    if seed.get("prism_handoff_target") is None:
        physical_jacobian[1] *= math.degrees(1.0 / (1.0 + (ratio + residuals[1]) ** 2))
    result.update(finite_difference_steps_v=steps, classification=classification)
    if controller_policy is not None:
        result.update(prism_controller_policy=dict(controller_policy),
                      prediction_quality={"status": "provisional_new_measured_model"},
                      measured_model_bounds_v=[(voltages[2:]-np.abs(steps)).tolist(),
                                               (voltages[2:]+np.abs(steps)).tolist()])
    return _propose_prism_step(result, physical_jacobian, contract, resolved_numerics)


def _propose_prism_step(
    result: dict[str, Any], physical_jacobian: np.ndarray,
    contract: Mapping[str, Any], resolved_numerics: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the same scaled, continuous bounded P step to a measured or transported model."""
    profile, loop = _profile(contract)
    voltages = np.asarray(result["voltages_v"])
    names = result.get("prism_acceptance_names", ACCEPTANCE_NAMES[:2])
    physical = np.asarray([result["physical_acceptance_residuals"][n] for n in names])
    tolerances = np.asarray(result.get("prism_acceptance_tolerances", [loop["acceptance_tolerances"][n] for n in ACCEPTANCE_NAMES[:2]]))
    lower = np.asarray(resolved_numerics["lower_bounds_v"])[2:]
    upper = np.asarray(resolved_numerics["upper_bounds_v"])[2:]
    parameter_scales = _vector(resolved_numerics.get("parameter_scales_v"), 4, "parameter scales")[2:]
    if np.any(parameter_scales <= 0):
        raise CandidateContractError("P parameter scales must be positive")
    raw, method, condition = scaled_two_coordinate_step(
        physical_jacobian, physical, parameter_scales, tolerances,
    )
    advance = _factor(loop, "advance_multiplier", "damping_factor")
    policy = result.get("prism_controller_policy")
    if policy is not None:
        if result["prediction_quality"]["status"] == "trusted":
            advance = policy["trusted_advance_multiplier"]
        relative = profile["jacobian_relative_step_tiers"]["coarse"]
        model_lower, model_upper = np.asarray(result["measured_model_bounds_v"])
        lower, upper = np.maximum(lower, model_lower), np.minimum(upper, model_upper)
    else:
        relative = relative_voltage_step(profile, result["maximum_scaled_abs_residual"])
    raw *= advance
    maximum = relative * np.maximum(np.abs(voltages[2:]), 1.0)
    delta, alpha = bounded_coordinate_step(voltages[2:], raw, maximum, lower, upper)
    if alpha <= 0.0:
        if policy is not None:
            return dict(result, status="needs_stencil", next_action="measure_stencil",
                        model_refresh_reason="measured_P_model_boundary")
        return dict(result, status="voltage_bound", next_action="stop_P_preclosure")
    if float(np.max(np.abs(delta))) < _finite(loop["minimum_step_linf_v"], "minimum step"):
        return dict(result, status="step_too_small", next_action="stop_P_preclosure")
    proposed = voltages.copy()
    proposed[2:] += delta
    if policy is not None:
        # Only remove endpoint addition roundoff; the bounded direction and
        # measured box are unchanged, with no physical tolerance relaxation.
        proposed[2:] = np.clip(proposed[2:], lower, upper)
        delta = proposed[2:] - voltages[2:]
    return dict(
        result, status="proposed", next_action="run_P_candidate",
        next_voltages_v=proposed.tolist(), applied_step_v=[0.0, 0.0, *delta.tolist()],
        physical_jacobian_rows=physical_jacobian.tolist(),
        predicted_physical_acceptance_residuals=dict(zip(names, (physical+physical_jacobian@delta).tolist(), strict=True)),
        model_solver=method, scaled_condition_number=condition,
        relative_trust_tier=relative, damping_line_factor=alpha,
        **({"resolved_advance_multiplier": advance} if policy is not None else {}),
    )


def decide_transported_prism_preclosure(
    baseline: Mapping[str, Any], prior: Mapping[str, Any],
    prior_anchor: Mapping[str, Any], contract: Mapping[str, Any],
    resolved_numerics: Mapping[str, Any],
    *, controller_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reuse a sealed measured P model only inside its measured finite-difference extent.

    The current point supplies real stage evidence, not a new Jacobian. Lack of
    measured improvement or disagreement with the predicted direction requests fresh columns.
    """
    result = decide_preclosure_stage("prism_preclosure", baseline, None, None, contract, resolved_numerics)
    if result["status"] != "needs_stencil":
        return result
    if prior.get("role") != "mrtof_prism_preclosure_decision" or prior.get("status") != "proposed":
        raise CandidateContractError("prior P decision must contain a measured proposed P step")
    if prior.get("model_representation") == "transported_local_approximation":
        raise CandidateContractError("prior P decision must be the original measured model")
    seed, current = _prism_stage_record(prior_anchor), _prism_stage_record(baseline)
    _same_frozen_problem([seed, current, dict(prior["observation_record"])])
    if current["stripe_biases_v"] != seed["stripe_biases_v"]:
        raise CandidateContractError("transported P correction must keep S fixed")
    origin = _vector(prior.get("voltages_v"), 4, "prior P voltages")
    if origin.tolist() != seed["stripe_biases_v"] + seed["prism_voltages_v"]:
        raise CandidateContractError("prior P decision does not match its real anchor")
    jacobian = np.asarray(prior.get("physical_jacobian_rows"), dtype=float)
    if jacobian.shape != (2, 2) or not np.all(np.isfinite(jacobian)):
        raise CandidateContractError("prior P decision requires a finite measured 2x2 model")
    extent = np.abs(_vector(prior.get("finite_difference_steps_v"), 2, "measured P steps"))
    if np.any(extent <= 0):
        raise CandidateContractError("prior P measurement extent must be positive")
    _, loop = _profile(contract)
    names = result.get("prism_acceptance_names", ACCEPTANCE_NAMES[:2])
    physical = np.asarray([result["physical_acceptance_residuals"][n] for n in names])
    previous = np.asarray([prior["physical_acceptance_residuals"][n] for n in names])
    tolerances = np.asarray(result.get("prism_acceptance_tolerances", [loop["acceptance_tolerances"][n] for n in ACCEPTANCE_NAMES[:2]]))
    displacement = np.asarray(result["voltages_v"])[2:] - origin[2:]
    predicted_change = jacobian @ displacement
    improvement = 1 - result["maximum_scaled_abs_residual"] / _finite(
        prior["maximum_scaled_abs_residual"], "prior P residual")
    reason = None
    if np.any(np.abs(displacement) > extent):
        reason = "outside_measured_P_extent"
    elif (improvement < _finite(loop["minimum_relative_improvement"], "minimum improvement")
          or float(np.dot((physical - previous) / tolerances, predicted_change / tolerances)) <= 0):
        reason = "unconfirmed_P_model_improvement"
    prediction_error = float(np.max(np.abs((physical - previous - predicted_change) / tolerances)))
    if controller_policy is not None:
        result.update(prism_controller_policy=dict(controller_policy),
                      prediction_quality={"status": "trusted" if reason is None and prediction_error <=
                          controller_policy["prediction_error_fraction_of_acceptance_tolerance"] else "untrusted",
                          "maximum_error_fraction_of_acceptance_tolerance": prediction_error},
                      measured_model_bounds_v=[(origin[2:]-extent).tolist(), (origin[2:]+extent).tolist()])
        if reason is None and result["prediction_quality"]["status"] != "trusted":
            reason = "P_model_prediction_error"
    if reason is not None:
        return dict(result, model_refresh_reason=reason)
    result.update(finite_difference_steps_v=prior["finite_difference_steps_v"],
                  classification=prior["classification"],
                  model_representation="transported_local_approximation", requires_real_flight=True,
                  measured_model_anchor_voltages_v=origin.tolist())
    proposed = _propose_prism_step(result, jacobian, contract, resolved_numerics)
    if proposed["status"] == "proposed":
        delta = np.asarray(proposed["applied_step_v"])[2:]
        prediction = physical + jacobian @ delta
        target = np.asarray(proposed["next_voltages_v"])[2:]
        outside = (np.any(target < origin[2:] - extent) or np.any(target > origin[2:] + extent)
                   if controller_policy is not None else np.any(np.abs(target - origin[2:]) > extent))
        if (outside
                or np.max(np.abs(prediction / tolerances)) >= result["maximum_scaled_abs_residual"]):
            return dict(result, status="needs_stencil", next_action="measure_stencil",
                        model_refresh_reason="proposal_outside_P_model_or_no_predicted_improvement")
        proposed["predicted_physical_acceptance_residuals"] = dict(zip(
            names, prediction.tolist(), strict=True))
    return proposed


def _stripe_stage_observation(observation: Mapping[str, Any]) -> Any:
    """An explicit stage rejection never falls back to full-flight observations."""
    return observation.get("center_particle_stripe_stage_validation",
                           observation.get("center_particle_workpoint_validation"))


def _stripe_stage_record(trial: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    """Consume the existing controlled centre-event extraction, not a fitted residual."""
    observation = trial["observation"]
    centre = _stripe_stage_observation(observation)
    if not isinstance(centre, Mapping) or centre.get("status") != "observed" or centre.get("particle_id") != 1:
        raise CandidateContractError("S preclosure requires observed controlled centre slow-turn/target-K events")
    residuals = centre.get("residuals")
    if not isinstance(residuals, Mapping):
        raise CandidateContractError("controlled centre residuals are missing")
    original = observation.get("residuals") or {}
    for name in workpoint_residual_names(trial["materialization"]):
        value = _finite(residuals.get(name), name)
        if original.get(name) is not None and _finite(original[name], name) != value:
            raise CandidateContractError("controlled centre and trial residuals differ")
    record, _, _ = _observation_record(
        {**observation, "residuals": residuals}, trial["materialization"], profile,
    )
    record["first_slow_turn_signature"] = centre.get("first_slow_turn_signature", {
        "status": "unknown", "reason": "legacy observation lacks first slow-turn signature",
    })
    return record


def _slow_turn_signature_comparison(anchor: Mapping[str, Any], sample: Mapping[str, Any]) -> str:
    """Reject evidenced local-phase changes, while retaining explicit legacy unknowns."""
    keys, unknown = [], False
    for trial in (anchor, sample):
        stage = _stripe_stage_observation(trial["observation"])
        signature = stage.get("first_slow_turn_signature") if isinstance(stage, Mapping) else None
        if signature is None:
            unknown = True
            continue
        if not isinstance(signature, Mapping):
            raise CandidateContractError("invalid first slow-turn signature")
        if signature.get("status") == "unknown":
            unknown = True
            continue
        key = signature.get("phase_key")
        if signature.get("status") != "observed" or not isinstance(key, Mapping):
            raise CandidateContractError("invalid first slow-turn signature")
        numbers = _vector(key.get("fast_turn_numbers"), 2, "slow-turn adjacent fast numbers")
        signs = _vector(key.get("sampled_vy_signs"), 2, "slow-turn sampled vy signs")
        if (numbers[1] != numbers[0] + 1 or np.any(numbers != np.floor(numbers))
                or key.get("direction_z") not in (-1, 1) or np.any(np.abs(signs) != 1)):
            raise CandidateContractError("invalid first slow-turn phase/direction key")
        # Adjacent vy signs diagnose nearby extra zeros; they do not identify this root.
        keys.append((numbers.tolist(), key["direction_z"]))
    if unknown:
        return "unknown"
    return "matched" if keys[0] == keys[1] else "mismatch"


def _stage_stencils(
    baseline: Mapping[str, Any], samples: Sequence[Mapping[str, Any] | None],
    axes: Sequence[int], *, stripe: bool,
) -> tuple[list[int], dict[str, str]]:
    """Identity failures raise; absent physical stage events reject only that column."""
    missing, rejections = [], {}
    anchor = np.asarray(baseline["materialization"]["stripe_biases_v"]
                        + baseline["materialization"]["prism_voltages_v"])
    for axis, sample in zip(axes, samples, strict=True):
        if sample is None:
            missing.append(axis)
            continue
        if sample.get("frozen_problem") != baseline.get("frozen_problem"):
            raise CandidateContractError("stage stencils differ in frozen field/source problem")
        receipt = sample["materialization"]
        voltage = _vector(receipt.get("stripe_biases_v", []) + receipt.get("prism_voltages_v", []),
                          4, "stage stencil voltages")
        if np.flatnonzero(voltage - anchor).tolist() != [axis]:
            raise CandidateContractError("stage stencil must perturb only its named voltage axis")
        stage = (_stripe_stage_observation(sample["observation"]) if stripe else
                 sample["observation"].get("center_particle_prism_handoff_validation"))
        if isinstance(stage, Mapping) and stage.get("status") == "observed" and stage.get("particle_id") != 1:
            raise CandidateContractError("stage stencil must observe the controlled centre particle")
        if not isinstance(stage, Mapping) or stage.get("status") != "observed" or stage.get("particle_id") != 1:
            missing.append(axis)
            rejections[str(axis)] = str(stage.get("reason", "controlled stage events unavailable")) if isinstance(stage, Mapping) else "controlled stage events unavailable"
        else:
            _same_frozen_problem([_prism_stage_record(baseline), _prism_stage_record(sample)])
            if stripe and _slow_turn_signature_comparison(baseline, sample) == "mismatch":
                missing.append(axis)
                rejections[str(axis)] = "first slow-turn local phase/direction differs from anchor"
    return missing, rejections


def joint_ps_refinement_enabled(profile: Mapping[str, Any], materialization: Mapping[str, Any]) -> bool:
    mode = profile.get("single_stripe_refinement_mode")
    if mode is None:
        return False
    if (mode != "joint_ps_constrained" or resolve_active_stripe_axes(profile) != (0,)
            or (materialization.get("prism_handoff_target") or {}).get("mode") != "converging_clean_phase_energy"
            or materialization["stripe_biases_v"][1] != 0.0):
        raise CandidateContractError("joint P/S refinement requires the explicit clean-energy single-S1 grounded-S2 scheme")
    return True


def _joint_ps_step(columns: np.ndarray, residuals: np.ndarray, tolerances: np.ndarray,
                   voltages: np.ndarray, numerics: Mapping[str, Any], relative: float) -> tuple[np.ndarray, np.ndarray]:
    """Minimize the worst S residual inside the original P acceptance window.

    SciPy HiGHS solves this four-variable linear program: three scaled voltage
    increments and a nonnegative maximum normalized S residual. No P equality
    or regularization is added. Recheck its model constraints before real Fly.
    """
    axes = np.asarray([0, 2, 3])
    scales = _vector(numerics["parameter_scales_v"], 4, "joint parameter scales")[axes]
    if (columns.shape != (4, 3) or residuals.shape != (4,) or tolerances.shape != (4,)
            or not all(np.all(np.isfinite(v)) for v in (columns, residuals, tolerances, voltages, scales))
            or np.any(tolerances <= 0) or np.any(scales <= 0)):
        raise CandidateContractError("joint P/S model requires finite 4x3 columns and positive scales")
    a = columns * scales / tolerances[:, None]
    r = residuals / tolerances
    trust = np.minimum(_vector(numerics["maximum_abs_step_v"], 4, "joint maximum step")[axes],
                       relative * np.maximum(np.abs(voltages[axes]), 1.0))
    lower = np.maximum(_vector(numerics["lower_bounds_v"], 4, "joint lower bounds")[axes] - voltages[axes],
                       -trust) / scales
    upper = np.minimum(_vector(numerics["upper_bounds_v"], 4, "joint upper bounds")[axes] - voltages[axes],
                       trust) / scales
    matrix = np.vstack((np.c_[a[:2], np.zeros(2)], np.c_[-a[:2], np.zeros(2)],
                        np.c_[a[2:], -np.ones(2)], np.c_[-a[2:], -np.ones(2)]))
    rhs = np.r_[1-r[:2], 1+r[:2], -r[2:], r[2:]]
    compatibility = _finite(numerics["compatibility_tolerance"], "joint model compatibility")
    solved = linprog([0., 0., 0., 1.], A_ub=matrix, b_ub=rhs,
                     bounds=[*zip(lower, upper, strict=True), (0., None)], method="highs",
                     options={"primal_feasibility_tolerance": compatibility,
                              "dual_feasibility_tolerance": compatibility})
    if not solved.success or not np.all(np.isfinite(solved.x)):
        raise CandidateContractError(f"joint P/S linear program failed: {solved.status}: {solved.message}")
    if np.any(matrix @ solved.x - rhs > compatibility):
        raise CandidateContractError("joint P/S linear program violates its model constraints")
    delta = solved.x[:3] * scales
    if np.any(delta/scales < lower-compatibility) or np.any(delta/scales > upper+compatibility):
        raise CandidateContractError("joint P/S linear program violates its voltage bounds")
    return delta, residuals + columns @ delta


def _decide_joint_ps_refinement(baseline: Mapping[str, Any], samples: Sequence[Mapping[str, Any] | None],
                                profile: Mapping[str, Any], loop: Mapping[str, Any],
                                numerics: Mapping[str, Any], initial: Mapping[str, Any]) -> dict[str, Any]:
    axes = (0, 2, 3)
    record = _stripe_stage_record(baseline, profile)
    residuals, tolerances = _record_physical_vector(record), _record_tolerances(record)
    voltages = np.asarray(record["voltages_v"])
    result = dict(initial, refinement_mode="joint_ps_constrained")
    missing, rejected = _stage_stencils(baseline, samples, axes, stripe=True)
    # P probes may leave the P window, but each measured column needs the full
    # real return branch. Measurement qualification is not candidate acceptance.
    for axis, sample in zip(axes, samples, strict=True):
        if axis in missing:
            continue
        observation = sample["observation"]
        returned = observation.get("static_return_diagnostic", {})
        if (observation.get("return_topology") != baseline["observation"].get("return_topology")
                or returned.get("status") != "detector_hit" or returned.get("event_contract_ok") is not True
                or observation.get("termination_diagnostic", {}).get("physical_collision") is not False):
            missing.append(axis)
            rejected[str(axis)] = "joint column lacks the anchor's complete collision-free return branch"
    if missing:
        return dict(result, status="needs_stencil", next_action="measure_stencil",
                    required_axes=sorted(missing), stencil_rejections=rejected)
    columns = []
    for axis, sample in zip(axes, samples, strict=True):
        measured = _stripe_stage_record(sample, profile)
        _same_frozen_problem([_prism_stage_record(baseline), _prism_stage_record(sample)])
        step = measured["voltages_v"][axis] - voltages[axis]
        columns.append((_record_physical_vector(measured)-residuals)/step)
    columns = np.column_stack(columns)
    relative = relative_voltage_step(profile, float(np.max(np.abs(residuals[2:]/tolerances[2:]))))
    try:
        delta, _ = _joint_ps_step(columns, residuals, tolerances, voltages, numerics, relative)
    except CandidateContractError as error:
        return dict(result, status="terminal", state="terminal", terminal_reason="solver_failure",
                    next_action="stop_S_preclosure", detail=str(error))
    delta *= _factor(loop, "advance_multiplier", "damping_factor")
    predicted = residuals + columns @ delta
    if np.max(np.abs(delta)) < _finite(loop["minimum_step_linf_v"], "minimum step"):
        return dict(result, status="step_too_small", next_action="stop_S_preclosure")
    if np.max(np.abs(predicted[2:]/tolerances[2:])) >= (
            1-_finite(loop["minimum_relative_improvement"], "relative improvement"))*result["maximum_scaled_abs_residual"]:
        return dict(result, status="residual_stagnation", next_action="stop_S_preclosure")
    proposed, applied = voltages.copy(), np.zeros(4)
    proposed[list(axes)] += delta
    applied[list(axes)] = delta
    return dict(result, status="proposed", next_action="run_S_candidate", next_voltages_v=proposed.tolist(),
                applied_step_v=applied.tolist(), predicted_s_residuals_mm=predicted[2:].tolist(),
                predicted_physical_acceptance_residuals=dict(zip(record["residual_names"], predicted.tolist(), strict=True)),
                joint_physical_jacobian_columns=columns.tolist(), joint_active_axes=list(axes),
                model_solver="bounded_linear_minimax__prism_acceptance_inequalities", relative_trust_tier=relative)


def decide_stripe_preclosure(
    baseline: Mapping[str, Any], stripe_1_trial: Mapping[str, Any] | None,
    stripe_2_trial: Mapping[str, Any] | None, contract: Mapping[str, Any],
    resolved_numerics: Mapping[str, Any], *, prism_1_trial: Mapping[str, Any] | None = None,
    prism_2_trial: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close actual S events at a passed P anchor; full transport stays a separate requirement."""
    profile, loop = _profile(contract)
    joint = joint_ps_refinement_enabled(profile, baseline["materialization"])
    axes = resolve_active_stripe_axes(profile)
    if axes == (0,):
        if baseline["materialization"]["stripe_biases_v"][1] != 0.0:
            raise CandidateContractError("inactive S2 must remain grounded at zero volts")
        if stripe_2_trial is not None:
            raise CandidateContractError("inactive S2 cannot supply a voltage stencil")
    p = decide_prism_preclosure(baseline, None, None, contract, resolved_numerics, require_columns=False)
    if p["status"] == "terminal":
        return p
    if p["status"] != "stage_passed":
        return dict(p, status="stage_required", next_action="prism_preclosure", stage_next="prism_preclosure")
    centre = _stripe_stage_observation(baseline["observation"])
    if not isinstance(centre, Mapping) or centre.get("status") != "observed":
        termination = baseline["observation"].get("termination_diagnostic", {})
        reason = ("collision_or_invalid_topology" if termination.get("physical_collision") is True
                  or termination.get("kind") == "programmatic_topology_rejection" else "missing_target_phase")
        return dict(p, status="terminal", state="terminal", terminal_reason=reason,
                    next_action="stop_preclosure", coordinate_group="stripe_1_stripe_2")
    record = _stripe_stage_record(baseline, profile)
    voltages = np.asarray(record["voltages_v"])
    residuals = _record_physical_vector(record)[2:]
    tolerances = _record_tolerances(record)[2:]
    maximum_residual = float(np.max(np.abs(residuals / tolerances)))
    indices = np.asarray(axes, dtype=int)
    lower = _vector(resolved_numerics.get("lower_bounds_v"), 4, "lower voltage bounds")[indices]
    upper = _vector(resolved_numerics.get("upper_bounds_v"), 4, "upper voltage bounds")[indices]
    if np.any(lower >= upper) or np.any(voltages[indices] < lower) or np.any(voltages[indices] > upper):
        raise CandidateContractError("S baseline lies outside compiled voltage bounds")
    result = dict(schema_version=1, role="mrtof_stripe_preclosure_decision",
                  coordinate_group="stripe_1_stripe_2", stage_only=True,
                  full_workpoint_qualified=False, observation_record=record,
                  active_stripe_axes=[UNKNOWN_NAMES[axis] for axis in axes],
                  voltages_v=voltages.tolist(), next_voltages_v=voltages.tolist(),
                  maximum_scaled_abs_residual=maximum_residual)
    if maximum_residual <= 1.0:
        observation = baseline["observation"]
        termination = observation.get("termination_diagnostic", {})
        static = observation.get("static_return_diagnostic", {})
        qualified = (observation.get("status") == "full_drift_observed"
                     and observation.get("return_topology") in {
                         "exact_target_k_phase_return", "coordinate_return_before_target_phase"}
                     and termination.get("physical_collision") is False
                     and static.get("status") == "detector_hit"
                     and static.get("event_contract_ok") is True
                     and record["maximum_scaled_abs_residual"] <= 1.0)
        return dict(result, status="terminal", state="terminal",
                    terminal_reason="success" if qualified else "collision_or_invalid_topology",
                    next_action="complete" if qualified else "stop_preclosure",
                    stage_only=not qualified, full_workpoint_qualified=qualified)
    if joint:
        return _decide_joint_ps_refinement(baseline, (stripe_1_trial, prism_1_trial, prism_2_trial),
                                           profile, loop, resolved_numerics, result)
    samples = tuple((stripe_1_trial, stripe_2_trial)[axis] for axis in axes)
    missing, rejections = _stage_stencils(baseline, samples, axes, stripe=True)
    signature_checks = {str(axis): _slow_turn_signature_comparison(baseline, sample)
                        for axis, sample in zip(axes, samples, strict=True) if sample is not None}
    result["slow_turn_signature_compatibility"] = {
        "status": ("mismatch" if "mismatch" in signature_checks.values() else
                   "matched" if len(signature_checks) == len(axes) and
                   all(value == "matched" for value in signature_checks.values()) else "unknown"),
        "axes": signature_checks,
    }
    for axis, sample in zip(axes, samples, strict=True):
        if axis in missing:
            continue
        prism = decide_prism_preclosure(
            sample, None, None, contract, resolved_numerics, require_columns=False,
        )
        if prism["status"] != "stage_passed":
            missing.append(axis)
            rejections[str(axis)] = "S stencil P handoff is not within acceptance tolerances"
    missing.sort()
    if missing:
        return dict(result, status="needs_stencil", next_action="measure_stencil",
                    required_axes=missing, stencil_rejections=rejections)
    records = tuple(None if trial is None else _stripe_stage_record(trial, profile)
                    for trial in (stripe_1_trial, stripe_2_trial))
    columns = refresh_s_local_jacobian(record, *records, axes=axes)
    scales = _vector(resolved_numerics.get("parameter_scales_v"), 4, "parameter scales")[indices]
    if np.any(scales <= 0.0):
        raise CandidateContractError("S parameter scales must be positive")
    scaled = columns[2:] * scales / tolerances[:, None]
    result["scaled_rank"] = int(np.linalg.matrix_rank(scaled))
    try:
        raw, method, condition = scaled_two_coordinate_step(columns[2:], residuals, scales, tolerances)
    except np.linalg.LinAlgError as error:
        return dict(result, status="terminal", state="terminal", terminal_reason="solver_failure",
                    next_action="stop_S_preclosure", detail=str(error))
    raw *= _factor(loop, "advance_multiplier", "damping_factor")
    relative = relative_voltage_step(profile, maximum_residual)
    delta, alpha = bounded_coordinate_step(
        voltages[indices], raw, relative * np.maximum(np.abs(voltages[indices]), 1.0), lower, upper,
    )
    if alpha <= 0.0 or float(np.max(np.abs(delta))) < _finite(loop["minimum_step_linf_v"], "minimum step"):
        return dict(result, status="voltage_bound" if alpha <= 0.0 else "step_too_small",
                    next_action="stop_S_preclosure")
    proposed = voltages.copy()
    proposed[indices] += delta
    applied = np.zeros(4)
    applied[indices] = delta
    return dict(result, status="proposed", next_action="run_S_candidate",
                next_voltages_v=proposed.tolist(), applied_step_v=applied.tolist(),
                predicted_s_residuals_mm=(residuals + columns[2:] @ delta).tolist(),
                local_s_physical_jacobian_columns=columns.tolist(), model_solver=method,
                scaled_condition_number=condition, relative_trust_tier=relative, damping_line_factor=alpha)


def decide_preclosure_stage(
    stage: str, baseline: Mapping[str, Any], sample_1: Mapping[str, Any] | None,
    sample_2: Mapping[str, Any] | None, contract: Mapping[str, Any],
    resolved_numerics: Mapping[str, Any],
    *, controller_policy: Mapping[str, Any] | None = None,
    joint_prism_trials: Sequence[Mapping[str, Any] | None] = (None, None),
) -> dict[str, Any]:
    """The original controller's two-coordinate bootstrap, without a fictitious full Jacobian."""
    if stage == "stripe_preclosure":
        return decide_stripe_preclosure(baseline, sample_1, sample_2, contract, resolved_numerics,
                                       prism_1_trial=joint_prism_trials[0], prism_2_trial=joint_prism_trials[1])
    if stage != "prism_preclosure":
        raise CandidateContractError("unknown preclosure stage")
    passed = decide_prism_preclosure(baseline, None, None, contract, resolved_numerics, require_columns=False)
    if passed["status"] == "terminal":
        return passed
    if passed["status"] == "stage_passed":
        centre = _stripe_stage_observation(baseline["observation"])
        if isinstance(centre, Mapping) and centre.get("status") == "observed" and centre.get("particle_id") == 1:
            return dict(passed, next_action="stripe_preclosure", stage_next="stripe_preclosure")
        return passed
    # A missing column is normal bootstrap progress, not an optimizer failure.
    missing, rejections = _stage_stencils(baseline, (sample_1, sample_2), (2, 3), stripe=False)
    if missing:
        return dict(passed, status="needs_stencil", next_action="measure_stencil",
                    required_axes=missing, stencil_rejections=rejections)
    return decide_prism_preclosure(baseline, sample_1, sample_2, contract, resolved_numerics,
                                  controller_policy=controller_policy)


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
    if resolve_active_stripe_axes(profile) != (0, 1):
        raise CandidateContractError("single active Stripe requires the staged controller, not dual-axis recovery")
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
    # Recovery intentionally replays the accepted anchor once to derive the
    # first candidate from the newly measured local S columns.  It is not a
    # second real flight and therefore cannot be a physical two-point cycle.
    if not recovery_resume and len(previous_records) >= 2:
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
    previous_state = _latest_recovery_state(history)
    previous_assessment = (
        previous_decision.get("prediction_assessment")
        if isinstance(previous_decision, Mapping) else None
    )
    boundary_limited_candidate = bool(
        coordinate_group == "prism_1_prism_2"
        and isinstance(previous_assessment, Mapping)
        and previous_assessment.get("topology_boundary_radius_linf_v") is not None
        and isinstance(previous_state, Mapping)
        and isinstance(previous_state.get("topology_boundary_voltages_v"), list)
    )
    prediction_assessment: dict[str, Any] = {
        "anchor_active_scaled_norm": anchor_active_norm,
        "actual_active_scaled_norm": current_active_norm,
        "accepted": accepted,
    }
    if (
        isinstance(previous_decision, Mapping)
        and (
            previous_decision.get("coordinate_group") == "physical_topology_backtrack"
            or boundary_limited_candidate
        )
        and anchor_active_norm is not None
        and current_active_norm < anchor_active_norm
    ):
        # A real collision established a topology boundary.  A valid midpoint
        # or subsequent boundary-limited candidate that improves the residual
        # must become the new valid endpoint even when its deliberately small
        # step cannot clear the ordinary percentage-improvement floor.
        accepted = True
        prediction_assessment["accepted"] = True
        prediction_assessment["acceptance_basis"] = "improving_topology_backtrack"
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
    rho = prediction_assessment.get("realized_over_predicted_reduction")
    trusted_recovery_prediction = bool(
        isinstance(previous_decision, Mapping)
        and previous_decision.get("recovery_resume_proposal") is True
        and isinstance(rho, (int, float))
        and math.isfinite(float(rho))
        and float(rho) >= 0.75
        and float(prediction_assessment.get("actual_reduction", 0.0)) > 0.0
        and not direction_wrong
    )
    if trusted_recovery_prediction:
        # The first correction after a fine local refresh is intentionally
        # radius-limited.  Judge it by agreement with that measured model;
        # the global percentage-improvement floor would otherwise reject the
        # very small safe step before its trust radius can grow.
        accepted = True
        prediction_assessment["accepted"] = True
        prediction_assessment["acceptance_basis"] = "trusted_recovery_prediction"
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
            detail=(f"{coordinate_group} candidate was physically valid but did not meet the minimum "
                    f"relative-improvement floor: scaled residual norm {anchor_active_norm:.6g} -> "
                    f"{current_active_norm:.6g}"),
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
            topology_boundary_voltages_v=(
                rejected.get("recovery_state", {}).get("topology_boundary_voltages_v")
            ),
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
    if non_improving >= non_improving_limit and not recovery_resume and not trusted_recovery_prediction:
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
    try:
        raw, model_solver, condition_number = scaled_two_coordinate_step(
            subsystem, _record_physical_vector(record)[rows], parameter_scales, tolerances,
        )
    except np.linalg.LinAlgError as exc:
        return _terminal("solver_failure", iteration=iteration,
                         detail=f"two-coordinate scaled solve failed: {exc}", record=record)
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
    relative_step = relative_voltage_step(
        profile, _finite(record["maximum_scaled_abs_residual"], "maximum scaled residual")
    )
    maximum = relative_step * np.maximum(np.abs(voltages[indices]), 1.0)
    topology_boundary_origin = None
    if coordinate_group == "prism_1_prism_2" and isinstance(previous_state, Mapping):
        stored_boundary = previous_state.get("topology_boundary_voltages_v")
        if isinstance(stored_boundary, list):
            origin = _vector(stored_boundary, 4, "stored topology boundary voltages")
            remaining = origin[indices] - voltages[indices]
            if float(raw @ remaining) > 0.0:
                # A real flight already proved ``origin`` invalid and the
                # current point valid.  Continue toward that boundary only by
                # bisecting the remaining voltage gap; otherwise the normal
                # percentage trust tier can repeatedly jump across it.
                boundary_radius = (
                    _factor(loop, "backtrack_multiplier", "damping_factor")
                    * float(np.max(np.abs(remaining)))
                )
                if boundary_radius > 0.0:
                    maximum = np.minimum(maximum, boundary_radius)
                    topology_boundary_origin = origin
                    prediction_assessment["topology_boundary_radius_linf_v"] = boundary_radius
    provisional_bound = None
    if recovery_resume:
        for item in reversed(history):
            if not isinstance(item, Mapping) or item.get("coordinate_group") != coordinate_group:
                continue
            recovery_model = item.get("recovery_state", {}).get("model")
            if isinstance(recovery_model, Mapping) and recovery_model.get("trusted_radius_linf_v") is not None:
                provisional_bound = _finite(
                    recovery_model["trusted_radius_linf_v"], "S recovery trusted radius"
                )
                maximum = np.minimum(maximum, provisional_bound)
                break
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
    else:
        for item in reversed(history):
            if not isinstance(item, Mapping) or item.get("recovery_resume_proposal") is not True:
                continue
            assessment = item.get("prediction_assessment")
            if isinstance(assessment, Mapping) and assessment.get("provisional_local_model_bound_v") is not None:
                provisional_bound = _finite(
                    assessment["provisional_local_model_bound_v"], "persisted S recovery trusted radius"
                )
                # Grow only after each trusted real prediction.  Never jump
                # directly from the recovered local radius back to the 1% tier.
                maximum = np.minimum(maximum, provisional_bound * (2.0 ** min(trusted_prediction_count, 4)))
                prediction_assessment["recovery_trust_bound_v"] = float(np.max(maximum))
                break
    lower = _vector(numerics.get("lower_bounds_v"), 4, "lower voltage bounds")[indices]
    upper = _vector(numerics.get("upper_bounds_v"), 4, "upper voltage bounds")[indices]
    active_delta, alpha = bounded_coordinate_step(
        voltages[indices], raw, maximum, lower, upper,
    )
    if alpha <= 0.0:
        return _terminal(
            "voltage_bound", iteration=iteration,
            detail="no bounded trust-region step remains", record=record,
        )
    delta = np.zeros(4)
    delta[indices] = active_delta
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
            topology_boundary_voltages_v=topology_boundary_origin,
        ),
        "local_physical_jacobian_rows": jacobian.tolist(),
        "scaled_subsystem_condition_number": condition_number,
        "model_solver": model_solver,
        "relative_trust_limit": relative_step,
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


def _derive_saved_slow_signature(trial: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    """Project a missing signature from sealed raw events without rewriting old evidence."""
    stage = _stripe_stage_observation(trial["observation"])
    if (not isinstance(stage, Mapping) or stage.get("status") != "observed"
            or "first_slow_turn_signature" in stage):
        return trial
    signature = {"status": "unknown", "reason": "sealed centre flight log is unavailable"}
    manifest = _load(manifest_path, "source trial manifest")
    logs = [record for record in manifest.get("outputs", [])
            if record_path(record, base_dir=manifest_path.parent).name == "native_two_prism_flight.log"]
    if len(logs) > 1:
        raise CandidateContractError("trial binds duplicate centre flight logs")
    if logs and record_path(logs[0], base_dir=manifest_path.parent).exists():
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import _first_slow_turn_signature
        verify_record("first slow-turn source log", logs[0], base_dir=manifest_path.parent)
        events = parse_events(record_path(logs[0], base_dir=manifest_path.parent).read_text(encoding="utf-8"))
        origins = [event for event in events if event["kind"] == "drift_phase_origin" and event["ion"] == 1]
        if len(origins) != 1 or stage.get("particle_id") != 1:
            raise CandidateContractError("saved slow-turn signature lacks unique centre phase origin")
        slows = [event for event in events if event["kind"] == "slow_turn" and event["ion"] == 1
                 and event["t_us"] > origins[0]["t_us"]]
        if not slows or slows[0].get("n") != 1:
            raise CandidateContractError("saved first slow-turn identity differs from stage observation")
        measured = _finite(slows[0].get("y_mm"), "saved first slow-turn y") - _finite(
            trial["materialization"].get("target_slow_turn_y_mm"), "target slow-turn y")
        if measured != _finite(stage.get("residuals", {}).get(RESIDUAL_NAMES[2]), "saved slow-turn residual"):
            raise CandidateContractError("saved first slow-turn value differs from stage observation")
        signature = _first_slow_turn_signature(events, slows[0])
    field = ("center_particle_stripe_stage_validation" if "center_particle_stripe_stage_validation"
             in trial["observation"] else "center_particle_workpoint_validation")
    trial["observation"][field] = dict(stage, first_slow_turn_signature=signature)
    return trial


def load_measured_centroid_closure_target(path: Path, source_receipt_path: Path,
                                         contract_path: Path) -> dict[str, Any]:
    """Import the explicit audited target; never synthesize an old OA target."""
    from common.contracts.component_particle_state import DERIVED_RELATIVE_TOLERANCE, DERIVED_ABSOLUTE_TOLERANCE
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import resolve_converging_prism_target
    target = _load(path, "measured centroid closure target")
    required = {"schema_version", "role", "inputs", "source_energy_ledger", "prism_handoff_target",
                "target_positive_mirror_turn_y_mm", "target_low_field_tangent_ratio_vy_over_vz",
                "target_slow_turn_y_mm", "target_k", "qualification"}
    if (set(target) != required or target["schema_version"] != 1
            or target["role"] != "mrtof_measured_centroid_closure_target_authority"
            or set(target["inputs"]) != {"interface_energy_field_audit", "trajectory_contract", "mother_source_receipt"}):
        raise CandidateContractError("Measured centroid target schema differs")
    for key, record in target["inputs"].items():
        verify_record(key, record)
    if file_sha256(contract_path).lower() != target["inputs"]["trajectory_contract"]["sha256"].lower():
        # The author's original bytes remain authoritative. Execution budget is
        # independent of the target; every other JSON field must remain exact.
        assert_bounded_controller_resume(
            _load(Path(target["inputs"]["trajectory_contract"]["path"]), "target author trajectory contract"),
            _load(contract_path, "current execution contract"), None, budget_only=True)
    source = _load(source_receipt_path, "constructed probe source")
    if source.get("role") != "mrtof_measured_exit_centroid_probe_source" or source.get("counts") != dict(source=1,transferred=1,not_transferred=0):
        raise CandidateContractError("Measured closure requires the independent constructed probe")
    mother_record = source["inputs"]["mother_source_receipt"]
    verify_record("probe mother receipt",mother_record)
    mother = _load(Path(mother_record["path"]),"probe mother receipt")
    original = mother.get("inputs",{}).get("prepared_source_receipt",mother_record)
    verify_record("original mother receipt",original)
    expected = target["inputs"]["mother_source_receipt"]
    if original["sha256"].lower() != expected["sha256"].lower():
        raise CandidateContractError("Measured closure target names a different mother source")
    original_mother = _load(Path(original["path"]),"original measured population")
    for name in ("component_particle_state", "source_census"):
        if mother["outputs"][name]["sha256"].lower() != original_mother["outputs"][name]["sha256"].lower():
            raise CandidateContractError("Probe mother canonical population differs from target")
    ledger = target["source_energy_ledger"]
    ledger_keys = {"mean_particle_kinetic_energy_ev_per_q", "kinetic_energy_of_mean_velocity_ev_per_q",
                   "centroid_joint_phi_v", "centroid_joint_hamiltonian_ev_per_q"}
    if not isinstance(ledger,Mapping) or set(ledger) != ledger_keys:
        raise CandidateContractError("Measured centroid source energy ledger differs")
    ledger = {key:_finite(value,key) for key,value in ledger.items()}
    close = lambda a,b: math.isclose(a,b,rel_tol=DERIVED_RELATIVE_TOLERANCE,abs_tol=DERIVED_ABSOLUTE_TOLERANCE)
    charge = abs(_finite(source["charge_state"],"probe charge"))
    if (not close(ledger["mean_particle_kinetic_energy_ev_per_q"],source["mean_particle_kinetic_energy_eV"]/charge)
            or not close(ledger["kinetic_energy_of_mean_velocity_ev_per_q"],source["centroid_kinetic_energy_eV"]/charge)
            or not close(ledger["centroid_joint_hamiltonian_ev_per_q"],
                         ledger["kinetic_energy_of_mean_velocity_ev_per_q"]+ledger["centroid_joint_phi_v"])):
        raise CandidateContractError("Measured target K, mean(K), or Hamiltonian ledger differs")
    resolved = target["prism_handoff_target"]
    authored_keys = ("mode", "axial_energy_per_charge_v", "mirror_axial_width_w_mm",
                     "slow_energy_reference_per_charge_v", "total_energy_reference_per_charge_v",
                     "clean_reference_slow_energy_per_charge_v")
    contract = copy.deepcopy(_load(contract_path,"measured trajectory contract"))
    contract["prism_transport"]["handoff_target"] = {key:resolved[key] for key in authored_keys}
    # This target resolver consumes only the already-frozen MR tilt and slot
    # bridges. Resolving an unrelated OA assembly would require launch geometry
    # and is not part of measured-source action target validation.
    bridges=contract["dual_stripe"]["beam_slot_y_bridges_mm"]
    model_geometry=dict(mirror_convergence_transform=contract["mirror"]["convergence_transform"],
        metadata=dict(ion_foil_slot_bridge_from_min_y_mm=bridges["from_min_y_mm"],
                      ion_foil_slot_bridge_from_max_y_mm=bridges["from_max_y_mm"]))
    recomputed=resolve_converging_prism_target(contract,model_geometry)
    if recomputed != resolved:
        raise CandidateContractError("Measured target differs from the existing resolved L0 target/tolerance authority")
    # The source Hamiltonian alone does not specify clean-plane K, Ex or Ey.
    # Reference energy/angle must be authored from the acquired clean state and
    # its actual potential; no Phi=0 or Ez=H substitution is permitted here.
    if _finite(target["target_low_field_tangent_ratio_vy_over_vz"],"target tangent") <= 0:
        raise CandidateContractError("Measured target reference tangent must be positive")
    for key in ("target_positive_mirror_turn_y_mm", "target_slow_turn_y_mm", "target_k"):
        _finite(target[key],key)
    return target


def load_prepared_centroid_trial(manifest_path: Path, target_path: Path,
                                 contract_path: Path) -> dict[str, Any]:
    """Read published N1 projection, including retired light evidence, without PA I/O."""
    manifest = _load(manifest_path,"measured joint child manifest")
    if (manifest.get("status") != "success" or manifest.get("mode") != "prepared_joint"
            or manifest.get("project") != "instrument_assembly"):
        raise CandidateContractError("Prepared controller requires a published successful measured joint N1")
    records = [record for record in manifest["outputs"] if Path(record["path"]).name == "controller_projection.json"]
    if len(records) != 1:
        raise CandidateContractError("Prepared child must bind exactly one controller projection")
    verify_record("measured child projection",records[0])
    projection = _load(Path(records[0]["path"]),"measured child projection")
    if projection.get("role") != "mrtof_measured_exit_centroid_controller_projection":
        raise CandidateContractError("Prepared child projection role differs")
    for key,record in projection["inputs"].items():
        verify_record(key,record)
    preparation = _load(Path(projection["inputs"]["preparation"]["path"]),"measured child preparation")
    if (preparation.get("source_mode") != "centroid_probe" or preparation.get("launched_particle_count") != 1
            or preparation.get("mother_particle_count") != 1 or preparation.get("expected_particle_ids") != [1]):
        raise CandidateContractError("Prepared controller cannot consume the full mother population as an N1 probe")
    for key in ("source_receipt", "field_binding", "trajectory_contract"):
        verify_record(key,preparation[key])
    source_path = Path(preparation["source_receipt"]["path"])
    target = load_measured_centroid_closure_target(target_path,source_path,contract_path)
    from common.contracts.write_run_manifest import file_record
    scientific_contract = target["inputs"]["trajectory_contract"]
    scientific_document = _load(Path(scientific_contract["path"]), "target author trajectory contract")
    actual_contract = file_record(contract_path)
    budget_change = None
    if actual_contract["sha256"].lower() != scientific_contract["sha256"].lower():
        budget_change = assert_bounded_controller_resume(scientific_document,
            _load(contract_path, "current execution contract"), None, budget_only=True)
    recorded_contract = preparation["trajectory_contract"]
    if recorded_contract["sha256"].lower() != scientific_contract["sha256"].lower():
        assert_bounded_controller_resume(scientific_document,
            _load(Path(recorded_contract["path"]), "recorded trial execution contract"), None, budget_only=True)
    provenance = dict(target_author_trajectory_contract=copy.deepcopy(scientific_contract),
        consumed_execution_contract=actual_contract, recorded_trial_execution_contract=copy.deepcopy(recorded_contract),
        execution_budget_change=budget_change)
    source = _load(source_path,"constructed probe receipt")
    if projection["inputs"]["source_receipt"] != preparation["source_receipt"]:
        raise CandidateContractError("Published probe source differs from prepared source authority")
    for key,record in source["outputs"].items():
        verify_record(key,record)
    observation,materialization = copy.deepcopy(projection["observation"]),copy.deepcopy(projection["materialization"])
    from common.contracts.component_particle_state import load_component_particle_state_csv
    canonical=Path(source["outputs"]["component_particle_state"]["path"])
    rows=load_component_particle_state_csv(canonical).rows
    if len(rows)!=1 or rows[0]["particle_id"]!=1 or rows[0]["state_event"]!="constructed_measured_exit_centroid":
        raise CandidateContractError("Prepared source is not the independent constructed centroid")
    row=rows[0]
    primary=materialization["source_center_state"]
    if (list(primary["position_mm"]) != [row[f"position_{a}_mm"] for a in "xyz"]
            or list(primary["velocity_mm_per_us"]) != [row[f"velocity_{a}_m_s"]/1000 for a in "xyz"]
            or primary["instrument_time_us"] != row["instrument_time_us"]
            or row["clock_epoch_id"] != source["clock_epoch_id"]):
        raise CandidateContractError("Measured stage source 6D or canonical clock differs")
    field=projection.get("field_authority_projection",{})
    if (field.get("role") != "mrtof_measured_centroid_live_field_projection" or field.get("schema_version") != 1
            or field.get("binding_record") != preparation["field_binding"]):
        raise CandidateContractError("Prepared child lacks its manifest-bound live-field lightweight projection")
    binding=field["normalized_binding"]
    values = binding["authority"]["analyzer_electrode_voltages_v"]
    ip_values=sorted([item for item in binding["authority"]["component_voltages_v"] if item["component_namespace"]=="ion_processor"],
                     key=lambda item:item["component_electrode_id"])
    if (values != field["analyzer_electrode_voltages_v"] or ip_values != field["ion_processor_component_voltages_v15"]
            or field["native_operator"] != projection["frozen_problem"]["static_field_problem"]):
        raise CandidateContractError("Prepared lightweight actual voltage/operator projections differ")
    if (materialization["prism_voltages_v"] != [values[15],values[16]]
            or materialization["stripe_biases_v"] != [values[10],values[12]]
            or observation["prism_voltages_v"] != materialization["prism_voltages_v"]):
        raise CandidateContractError("Prepared observation P/S voltages differ from actual bound field")
    materialization.update({key:copy.deepcopy(target[key]) for key in (
        "prism_handoff_target","target_positive_mirror_turn_y_mm","target_low_field_tangent_ratio_vy_over_vz","target_slow_turn_y_mm")})
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import ProjectPhaseSpaceState
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
        _bunch_center_prism_handoff_validation,_bunch_center_stripe_stage_validation,
        _bunch_center_workpoint_validation,_termination_diagnostic,_static_return_diagnostic,
    )
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import summarize_events
    materialization.update(particle_mass_th=source["mass_amu"],charge_state=source["charge_state"],
                           target_drift_period_ratio=target["target_k"])
    primary=materialization["source_center_state"]
    source_state=ProjectPhaseSpaceState(tuple(primary["position_mm"]),tuple(primary["velocity_mm_per_us"]))
    events=observation["events"]
    p_stage=_bunch_center_prism_handoff_validation(events,materialization,source_state=source_state)
    s_stage=_bunch_center_stripe_stage_validation(events,materialization,source_state=source_state)
    whole=_bunch_center_workpoint_validation(events,materialization,source_state=source_state)
    integrity=summarize_events(events,target["target_k"],reported_splat_count=1,expected_particle_ids=(1,),completion_count=1)
    termination=_termination_diagnostic(events)
    returned=_static_return_diagnostic(events,target["target_k"])
    observation.update(center_particle_prism_handoff_validation=p_stage,center_particle_stripe_stage_validation=s_stage,
        center_particle_workpoint_validation=whole,cohort_analysis=integrity,termination_diagnostic=termination,
        static_return_diagnostic=returned,extraction_diagnostic=returned,
        residuals=s_stage.get("residuals",p_stage.get("residuals",{})),
        qualification="measured_centroid_candidate_original_staged_workflow__not_N100_qualification")
    if whole.get("status")=="observed" and integrity["event_integrity_passed"] and returned["event_contract_ok"]:
        observation.update(status="full_drift_observed",return_topology="exact_target_k_phase_return",
                           fractional_k=returned.get("fractional_k"))
    else:
        observation["status"]="measured_centroid_observation_incomplete"
    center=copy.deepcopy(projection["frozen_problem"]["source_center_projection"])
    center["mother_source_receipt"]={key:target["inputs"]["mother_source_receipt"][key] for key in ("bytes","sha256")}
    center["probe_source_receipt"]={"role":source["role"],"canonical_sha256":source["outputs"]["component_particle_state"]["sha256"]}
    frozen=dict(source_center_projection=center,targets={key:target[key] for key in (
        "target_positive_mirror_turn_y_mm","target_low_field_tangent_ratio_vy_over_vz","target_slow_turn_y_mm","target_k")},
        prism_handoff_target=target["prism_handoff_target"],static_field_problem=field["native_operator"],
        selected_axial_energy_per_charge_v=target["prism_handoff_target"]["axial_energy_per_charge_v"],
        inputs=dict(closure_target_sha256=file_sha256(target_path),trajectory_contract_sha256=scientific_contract["sha256"]))
    materialization["controller_contract_provenance"] = provenance
    return dict(manifest=str(manifest_path),observation=observation,materialization=materialization,
                voltages_v=[*materialization["stripe_biases_v"],*materialization["prism_voltages_v"]],
                frozen_problem=frozen,consumer_projection=dict(records={"measured_projection":records[0]}))


def load_measured_centroid_initial_proposal(path: Path) -> dict[str, Any]:
    """Read a bounded topology seed, never assign residuals to absent events."""
    proposal=_load(path,"measured centroid initial proposal")
    if (set(proposal) != {"schema_version","role","initial_prism_voltages_v","prism_bounds_v","inputs","derivation","qualification",
                         "full_workpoint_qualified","source_state_unchanged","target_authority_status"}
            or proposal["schema_version"] != 1 or proposal["role"] != "mrtof_measured_centroid_prism_initial_proposal"
            or set(proposal["inputs"]) != {"interface_energy_field_audit","old_oa_flight_log","ip_baseline_flight_log","seed_derivation"}
            or set(proposal["prism_bounds_v"]) != {"p1","p2"}
            or proposal["qualification"] != "initial_topology_seed_only"
            or proposal["full_workpoint_qualified"] is not False or proposal["source_state_unchanged"] is not True
            or proposal["target_authority_status"] != "not_assigned_until_actual_clean_reference_is_observed"):
        raise CandidateContractError("Measured centroid initial proposal schema differs")
    for key,record in proposal["inputs"].items():
        verify_record(key,record)
    values=_vector(proposal["initial_prism_voltages_v"],2,"initial P seed")
    for index,key in enumerate(("p1","p2")):
        lo,hi=_vector(proposal["prism_bounds_v"][key],2,"explicit P bounds")
        if not lo<hi or not lo<=values[index]<=hi or (index==0 and lo<=0) or (index==1 and hi>=0):
            raise CandidateContractError("Measured centroid topology seed must lie inside explicit positive-P1/negative-P2 bounds")
    return proposal


def materialize_prepared_staged_adapter(manifest_path: Path, target_path: Path,
                                        contract_path: Path, output_directory: Path) -> dict[str, Any]:
    """Write explicitly measured views for the original staged workflow slots."""
    from common.contracts.write_run_manifest import file_record
    trial=load_prepared_centroid_trial(manifest_path,target_path,contract_path)
    identity=file_sha256(manifest_path)[:12]+"_"+file_sha256(target_path)[:12]
    output_directory.mkdir(parents=True,exist_ok=True)
    outputs={}
    for key in ("observation","materialization"):
        path=output_directory/f"iteration_measured_{identity}_{key}.json"
        # Phase-space tuples become JSON arrays on disk. Compare the persisted
        # representation so an identical second slot read stays idempotent.
        document=json.loads(json.dumps(trial[key]))
        if path.exists():
            if _load(path,key) != document:
                raise CandidateContractError("A frozen target-version adapter would change existing stage evidence")
        else:
            path.write_text(json.dumps(document,indent=2)+"\n",encoding="utf-8")
        outputs[key]=file_record(path)
    return dict(schema_version=1,role="mrtof_measured_centroid_original_staged_adapter",
                inputs=dict(child_manifest=file_record(manifest_path),target_authority=file_record(target_path),
                            trajectory_contract=file_record(contract_path)),outputs=outputs,
                source_projection="measured_exit_centroid",workflow="existing_P_then_S_phase_then_P_reclosure",
                field_payload_opened=False,full_population_qualified=False)


def reanchor_prepared_target(state: Mapping[str, Any], *, anchor_manifest: Path,
                             target_path: Path, contract_path: Path,
                             previous_target_path: Path | None = None) -> dict[str, Any]:
    """Use a new explicit engineering target version and discard stale columns."""
    from common.contracts.write_run_manifest import file_record
    if "target_reanchor" in state:
        raise CandidateContractError("Repeated target re-anchor would overwrite existing debit evidence")
    if state.get("pending_trial") is not None:
        raise CandidateContractError("Target re-anchor requires the pending real flight to finish first")
    trial=load_prepared_centroid_trial(anchor_manifest,target_path,contract_path)
    if previous_target_path is not None:
        previous = _load(previous_target_path, "previous explicit target")
        current = _load(target_path, "new explicit target")
        expected = copy.deepcopy(previous)
        old_l = _finite(previous.get("target_slow_turn_y_mm"), "previous slow-turn target")
        new_l = _finite(current.get("target_slow_turn_y_mm"), "new slow-turn target")
        if old_l == new_l:
            raise CandidateContractError("Target re-anchor requires an explicitly changed slow-turn target")
        expected["target_slow_turn_y_mm"] = current["target_slow_turn_y_mm"]
        if current != expected:
            raise CandidateContractError("Target re-anchor differs beyond the slow-turn correction")
        old_trial = load_prepared_centroid_trial(anchor_manifest, previous_target_path, contract_path)
        for key in ("source_center_projection", "static_field_problem", "selected_axial_energy_per_charge_v"):
            if old_trial["frozen_problem"][key] != trial["frozen_problem"][key]:
                raise CandidateContractError("Target re-anchor source or operator differs")
    reset=copy.deepcopy(dict(state))
    for key in ("prism_model_manifest","prediction_assessment","pending_trial"):
        reset.pop(key,None)
    reset.update(stage="prism_preclosure",anchor_manifest=str(anchor_manifest.resolve()),columns={},attempts=[],
                 step_factor=1.0,completion_attempted=False,local_model_tier_index=0,consecutive_candidate_rejections=0)
    reset["target_reanchor"]=dict(role="mrtof_measured_target_reanchor",target_authority=file_record(target_path),
        anchor_manifest=file_record(anchor_manifest),prior_columns=copy.deepcopy(state.get("columns",{})),
        reason="explicit_new_target_version__remeasure_P_columns_before_S_phase",source_unchanged=True,
        source_identity=trial["frozen_problem"]["source_center_projection"],full_workpoint_qualified=False)
    return reset


def prepare_measured_centroid_acquisition(*, prepared_run: Path, contract_path: Path,
                                         proposal_path: Path, p1_response: Path, p2_response: Path,
                                         field_run_id: str, output_directory: Path) -> dict[str, Any]:
    """Freeze the topology-only request for the existing public provider and runner."""
    from common.contracts.write_run_manifest import file_record
    from common.contracts.frozen_inputs import freeze_file
    from integrations.workflows.accelerator_interface.prepare import verified_preparation_reference
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding, load_native_response_basis
    proposal=load_measured_centroid_initial_proposal(proposal_path)
    binding_path=verified_preparation_reference(prepared_run,"results/joint_workbench/static_field_binding.json")
    binding=load_binding(binding_path)
    if binding.get("accelerator_provider") != "dual_pressure_rectilinear_ion_processor":
        raise CandidateContractError("Acquisition requires the measured IP replacement field")
    for axis,path in (("p1",p1_response),("p2",p2_response)):
        response=load_native_response_basis(path,binding)
        # The loader validates the complete same-operator identity. The named
        # descriptor must also belong to the requested coordinate.
        if response.get("response_basis",{}).get("axis",_load(path,"response basis").get("axis")) != axis:
            raise CandidateContractError("Acquisition response coordinate differs")
    output_directory.mkdir(parents=True,exist_ok=True)
    inputs={name:freeze_file(path,output_directory/(name+path.suffix)) for name,path in (
        ("initial_proposal",proposal_path),("trajectory_contract",contract_path),
        ("p1_response_descriptor",p1_response),("p2_response_descriptor",p2_response))}
    values=binding["authority"]["analyzer_electrode_voltages_v"]
    request=dict(schema_version=1,role="mrtof_native_static_field_provider_request",
        source_binding_path=str(binding_path),source_field_manifest=binding.get("descriptor_owner",binding["manifest"]),
        numerical_contract_path=inputs["trajectory_contract"]["path"],run_id=field_run_id,
        candidate_voltages_v=dict(s1=values[10],s2=values[12],
                                 p1=proposal["initial_prism_voltages_v"][0],p2=proposal["initial_prism_voltages_v"][1]),
        response_basis_paths=dict(p1=str(p1_response.resolve()),p2=str(p2_response.resolve())))
    request_path=output_directory/"acquisition_field_request.json"
    request_path.write_text(json.dumps(request,indent=2)+"\n",encoding="utf-8")
    result=dict(schema_version=1,role="mrtof_measured_centroid_topology_acquisition_preparation",
        inputs=inputs,field_request=file_record(request_path),prepared_run=str(prepared_run.resolve()),
        qualification="initial_topology_seed_only",full_workpoint_qualified=False,
        physical_target_assigned=False,source_state_unchanged=True)
    (output_directory/"acquisition_preparation.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


def _load_stage_trial(manifest_path: Path, replay_path: Path | None = None) -> dict[str, Any]:
    """Overlay only registered stage evidence from one published log reanalysis."""
    trial = _trial(manifest_path, require_target_phase=False)
    records = trial["consumer_projection"]["records"]
    for key, filename in (("observation", "two_prism_trial_observation.json"),
                          ("materialization", "two_prism_trial_materialization.json")):
        trial[key] = _load(record_path(records[filename], base_dir=manifest_path.parent), key)
    if replay_path is None:
        return _derive_saved_slow_signature(trial, manifest_path)
    replay = _load(replay_path, "P handoff replay manifest")
    if (replay.get("status") != "success" or replay.get("project") != "parallel_mirror_dual_stripe_mr_tof"
            or replay.get("mode") != "prism_handoff_log_reanalysis"):
        raise CandidateContractError("P handoff replay is not a published successful reanalysis")
    config_record = replay["run_config"]
    verify_record("run_config", config_record, base_dir=replay_path.parent)
    config = _load(record_path(config_record, base_dir=replay_path.parent), "replay config")
    source = _load(manifest_path, "source manifest")
    labels = [label for label, run_id in config["parameters"]["source_runs"].items()
              if run_id == source["run_id"]]
    if not labels:
        return _derive_saved_slow_signature(trial, manifest_path)
    if len(labels) != 1:
        raise CandidateContractError("P replay must identify exactly one original trial")
    label = labels[0]
    for suffix, expected in (("manifest", trial["manifest_sha256"]),
                             ("materialization", records["two_prism_trial_materialization.json"]["sha256"])):
        record = replay["inputs"][f"{label}_{suffix}"]
        verify_record(f"{label}_{suffix}", record, base_dir=replay_path.parent)
        if str(record["sha256"]).lower() != str(expected).lower():
            raise CandidateContractError("P replay differs from the original trial evidence")
    observations = [record for record in replay["outputs"]
                    if record_path(record, base_dir=replay_path.parent).name == f"{label}_observation.json"]
    if len(observations) != 1:
        raise CandidateContractError("P replay must bind one selected observation")
    verify_record("replayed observation", observations[0], base_dir=replay_path.parent)
    observed = _load(record_path(observations[0], base_dir=replay_path.parent), "replayed observation")
    # Preserve all full-flight evidence; a later collision does not erase a completed stage.
    trial["replayed_stage_fields"] = []
    for name in ("center_particle_prism_handoff_validation", "center_particle_stripe_stage_validation"):
        if name in observed:
            trial["observation"][name] = observed[name]
            trial["replayed_stage_fields"].append(name)
    trial["prism_handoff_replay_manifest"] = str(replay_path.resolve())
    return _derive_saved_slow_signature(trial, manifest_path)


def _load_prior_prism_decision(
    manifest_path: Path, contract: Mapping[str, Any], *, trial_loader=None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read a sealed P decision and its registered real anchor without touching field payloads."""
    manifest = _load(manifest_path, "prior P decision manifest")
    if (manifest.get("status") != "success"
            or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"):
        raise CandidateContractError("prior P decision manifest must be published successful evidence")
    inputs = manifest.get("inputs", {})
    for name in ("baseline_manifest", "workpoint_contract"):
        if name not in inputs:
            raise CandidateContractError(f"prior P decision is missing registered {name}")
        verify_record(name, inputs[name], base_dir=manifest_path.parent)
    if _load(record_path(inputs["workpoint_contract"], base_dir=manifest_path.parent), "prior contract") != contract:
        raise CandidateContractError("prior P decision uses a different workpoint contract")
    decisions = []
    for record in manifest.get("outputs", []):
        path = record_path(record, base_dir=manifest_path.parent)
        if path.suffix.lower() == ".json":
            verify_record("prior P decision output", record, base_dir=manifest_path.parent)
            value = _load(path, "prior P output")
            if value.get("role") == "mrtof_prism_preclosure_decision":
                decisions.append(value)
    if len(decisions) != 1:
        raise CandidateContractError("prior P manifest must register exactly one P decision")
    anchor_path = record_path(inputs["baseline_manifest"], base_dir=manifest_path.parent)
    if Path(decisions[0]["anchor_manifest"]).resolve() != anchor_path.resolve():
        raise CandidateContractError("prior P decision anchor differs from registered source")
    return decisions[0], (_load_stage_trial(anchor_path) if trial_loader is None else trial_loader(anchor_path))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-request", choices=("-",), help=argparse.SUPPRESS)
    parser.add_argument("--prior", type=Path)
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--child-manifest", type=Path)
    parser.add_argument("--control-stage", choices=("prism_preclosure", "stripe_preclosure"))
    parser.add_argument("--prepared-target-authority",type=Path)
    parser.add_argument("--prepared-initial-proposal",type=Path)
    parser.add_argument("--prism-handoff-replay-manifest", type=Path)
    parser.add_argument("--prior-prism-decision-manifest", type=Path)
    parser.add_argument("--p1-child-manifest", type=Path)
    parser.add_argument("--p2-child-manifest", type=Path)
    parser.add_argument("--s1-child-manifest", type=Path)
    parser.add_argument("--s2-child-manifest", type=Path)
    parser.add_argument("--materialization", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--prism-controller-policy", type=Path)
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
                        help="emit the best fully qualified physical workpoint for bunch screening")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.controller_request is not None:
        if str(args.output) != "-":
            parser.error("internal controller request writes only to stdout")
        print(json.dumps(dispatch_controller_request(json.load(sys.stdin))))
        return 0
    if args.prior_prism_decision_manifest is not None and args.control_stage != "prism_preclosure":
        parser.error("--prior-prism-decision-manifest is only available for prism_preclosure")
    if args.control_stage is not None:
        if args.child_manifest is None or args.contract is None:
            parser.error("preclosure requires --child-manifest and --contract")
        if args.prepared_initial_proposal is not None and args.prepared_target_authority is None:
            parser.error("--prepared-initial-proposal requires --prepared-target-authority")
        if args.prepared_target_authority is not None and args.prism_handoff_replay_manifest is not None:
            parser.error("Measured centroid projections cannot overlay legacy OA handoff replays")
        loader = (lambda path: load_prepared_centroid_trial(path,args.prepared_target_authority,args.contract)
                  if args.prepared_target_authority is not None else _load_stage_trial(path,args.prism_handoff_replay_manifest))
        baseline = loader(args.child_manifest)
        contract = _load(args.contract, "workpoint contract")
        policy = None
        if args.prism_controller_policy is not None:
            if args.control_stage != "prism_preclosure":
                parser.error("prism controller policy is only available for prism_preclosure")
            policy = resolve_prism_controller_policy(args.prism_controller_policy)
        numerics = resolve_numerics(contract, baseline)
        if args.prepared_initial_proposal is not None:
            proposal=load_measured_centroid_initial_proposal(args.prepared_initial_proposal)
            numerics["lower_bounds_v"][2:]=[proposal["prism_bounds_v"][key][0] for key in ("p1","p2")]
            numerics["upper_bounds_v"][2:]=[proposal["prism_bounds_v"][key][1] for key in ("p1","p2")]
        paths = ((args.p1_child_manifest, args.p2_child_manifest) if args.control_stage == "prism_preclosure"
                 else (args.s1_child_manifest, args.s2_child_manifest))
        samples = [None if path is None else loader(path)
                   for path in paths]
        joint_prisms = (None, None)
        if args.control_stage == "stripe_preclosure" and joint_ps_refinement_enabled(
                contract["downstream_fixed_grid_workpoint_profile"], baseline["materialization"]):
            joint_prisms = tuple(None if path is None else loader(path)
                                 for path in (args.p1_child_manifest, args.p2_child_manifest))
        if args.prior_prism_decision_manifest is not None:
            if args.control_stage != "prism_preclosure" or any(path is not None for path in paths):
                parser.error("--prior-prism-decision-manifest requires P stage without new P columns")
            result = decide_preclosure_stage(args.control_stage, baseline, *samples, contract, numerics,
                                            controller_policy=policy, joint_prism_trials=joint_prisms)
            if result["status"] == "needs_stencil":
                prior, prior_anchor = _load_prior_prism_decision(args.prior_prism_decision_manifest, contract,trial_loader=loader)
                result = decide_transported_prism_preclosure(baseline, prior, prior_anchor, contract, numerics,
                                                            controller_policy=policy)
                result["measured_model_decision_manifest"] = str(args.prior_prism_decision_manifest.resolve())
        else:
            result = decide_preclosure_stage(args.control_stage, baseline, *samples, contract, numerics,
                                            controller_policy=policy, joint_prism_trials=joint_prisms)
        stage_field = ("center_particle_stripe_stage_validation" if args.control_stage == "stripe_preclosure"
                       else "center_particle_prism_handoff_validation")
        axes = (0, 1) if args.control_stage == "stripe_preclosure" else (2, 3)
        result["replayed_stage_axes"] = [axis for axis, sample in zip(axes, samples, strict=True)
                                         if sample is not None and stage_field in sample.get("replayed_stage_fields", [])]
        profile, loop = _profile(contract)
        observed = ((_stripe_stage_observation(baseline["observation"]) or {})
                    if args.control_stage == "stripe_preclosure" else
                    baseline["observation"].get("center_particle_prism_handoff_validation", {}))
        result.setdefault("stage_observation_available", observed.get("status") == "observed" and observed.get("particle_id") == 1)
        if result["stage_observation_available"]:
            if "observation_record" not in result:
                result["observation_record"] = (_stripe_stage_record(baseline, profile)
                                                if args.control_stage == "stripe_preclosure"
                                                else _prism_stage_record(baseline))
        result["resolved_numerics"] = numerics
        result["backtrack_multiplier"] = _factor(loop, "backtrack_multiplier", "damping_factor")
        result["anchor_manifest"] = str(args.child_manifest.resolve())
        if policy is not None:
            result["prism_controller_policy"] = policy
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"MRTOF_PRECLOSURE={args.control_stage}:{result['status']}")
        return 0
    if args.prism_controller_policy is not None:
        parser.error("prism controller policy requires --control-stage prism_preclosure")
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
