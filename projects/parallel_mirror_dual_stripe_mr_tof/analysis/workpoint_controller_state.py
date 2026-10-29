"""Pure voltage-step, candidate acceptance and local-recovery state transitions.

The workflow owns files, manifests and solver calls. This module receives their
validated projections. Historical recovery formats enter only through the
explicit checkpoint importer; ordinary preparation requires the current format.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError

RECOVERY_VERSION = 8
RECOVERY_ROLE = "mrtof_downstream_workpoint_local_model_recovery"


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CandidateContractError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateContractError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def relative_voltage_step(profile: Mapping[str, Any], maximum_scaled_residual: float | None) -> float:
    """Select the contract-owned coarse/medium/fine fractional voltage step."""
    tiers = profile.get("jacobian_relative_step_tiers")
    keys = {"coarse", "medium", "fine", "medium_maximum_scaled_residual", "fine_maximum_scaled_residual"}
    if not isinstance(tiers, Mapping) or set(tiers) != keys:
        raise CandidateContractError("relative voltage step tiers are invalid")
    coarse, medium, fine = (_finite(tiers[key], key) for key in ("coarse", "medium", "fine"))
    medium_limit = _finite(tiers["medium_maximum_scaled_residual"], "medium threshold")
    fine_limit = _finite(tiers["fine_maximum_scaled_residual"], "fine threshold")
    if not 0 < fine < medium < coarse or not 0 < fine_limit < medium_limit:
        raise CandidateContractError("relative voltage step tiers must decrease toward convergence")
    if maximum_scaled_residual is None:
        return coarse
    residual = _finite(maximum_scaled_residual, "maximum scaled residual")
    return fine if residual <= fine_limit else medium if residual <= medium_limit else coarse


def voltage_stencil_steps(voltages_v: Sequence[float], profile: Mapping[str, Any],
                          maximum_scaled_residual: float | None = None) -> list[float]:
    """Return the four positive S1/S2/P1/P2 stencil magnitudes in volts."""
    if len(voltages_v) != 4:
        raise CandidateContractError("stencil requires S1/S2/P1/P2 voltages")
    relative = relative_voltage_step(profile, maximum_scaled_residual)
    return [relative * max(abs(_finite(value, "voltage")), 1.0) for value in voltages_v]


def bootstrap_stencil_configuration(voltages_v: Sequence[float], profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return the existing four steps and coarse-relative retry scales together."""
    steps = voltage_stencil_steps(voltages_v, profile)
    tiers = profile["jacobian_relative_step_tiers"]
    coarse = float(tiers["coarse"])
    return dict(forward_steps_v=steps,
                stencil_step_scales=[1.0, float(tiers["medium"]) / coarse, float(tiers["fine"]) / coarse])


def continuation_transport_candidates(seed: Mapping[str, Any], profile: Mapping[str, Any]) -> list[list[float]]:
    """Plan the original bounded P1/P2 search in tier, axis, then signed order."""
    tiers = profile["jacobian_relative_step_tiers"]
    relative = [_finite(tiers[key], key) for key in ("coarse", "medium", "fine")]
    if len(set(relative)) != 3 or any(value <= 0 for value in relative):
        raise CandidateContractError("Continuation transport-seed search requires three positive contract relative tiers.")
    origin = [_finite(value, "continuation prism voltage") for value in seed["prism_voltages_v"]]
    bounds = seed["prism_voltage_bounds_v"]
    if len(origin) != 2 or len(bounds) != 2 or any(len(pair) != 2 for pair in bounds):
        raise CandidateContractError("Continuation transport seed must bind two prism voltages and bounds.")
    candidates = [origin[:]]
    for step in relative:
        for axis in (0, 1):
            for direction in (1, -1):
                candidate = origin[:]
                candidate[axis] += direction * step * max(abs(origin[axis]), 1.0)
                if float(bounds[axis][0]) <= candidate[axis] <= float(bounds[axis][1]):
                    candidates.append(candidate)
    return candidates


def center_trial_physical_gate(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one verified observation with the existing PowerShell gate semantics.

    The caller preserves the original numeric conversion before transport. Status
    comparison is case-insensitive; collision and event proof require booleans.
    """
    reasons = []
    status = observation.get("status")
    if not isinstance(status, str) or status.casefold() not in ("full_drift_observed", "target_phase_observed", "detected"):
        reasons.append("target_phase_status_invalid")
    termination = observation.get("termination_diagnostic")
    if not isinstance(termination, Mapping) or termination.get("physical_collision") is not False:
        reasons.append("collision_absence_not_proven")
    residuals = observation.get("residuals")
    target = "Stripe_target_phase_y_minus_origin_mm"
    if (not isinstance(residuals, Mapping) or residuals.get(target) is None
            or not math.isfinite(float(residuals[target]))):
        reasons.append("target_phase_residual_missing")
    static = observation.get("static_return_diagnostic")
    if (not isinstance(static, Mapping) or not isinstance(static.get("status"), str)
            or static["status"].casefold() != "detector_hit" or static.get("event_contract_ok") is not True):
        reasons.append("static_detector_contract_failed")
    return dict(passed=not reasons, reasons=reasons)


def center_residual_gate(status: str | None, names: Sequence[str],
                         residuals: Mapping[str, Any], tolerances: Mapping[str, Any]) -> dict[str, Any]:
    """Classify verified centre residuals against the frozen handoff tolerances.

    Names and numeric representations come from the runner after its original
    authored/materialized handoff identity checks. Missing values fail in order.
    """
    failed = []
    if not isinstance(status, str) or status.casefold() != "observed":
        failed.append("center_particle_workpoint_observation_incomplete")
    else:
        for name in names:
            if name not in residuals or name not in tolerances:
                failed.append(name)
                continue
            value, limit = float(residuals[name]), float(tolerances[name])
            if not math.isfinite(value) or not math.isfinite(limit) or limit <= 0 or abs(value) > limit:
                failed.append(name)
    return dict(passed=not failed, failed=failed)


def plan_bootstrap_stencil(voltages_v: Sequence[float], forward_steps_v: Sequence[float],
                           step_scales: Sequence[float] | None = None) -> dict[str, Any]:
    """Plan ordered alternatives; the workflow rechecks each saved identity on use.

    A group stops at its first physically accepted observation. Planning does not
    inspect later manifests or advance any saved child/attempt/checkpoint state.
    """
    seed = [float(value) for value in voltages_v]
    steps = [float(value) for value in forward_steps_v]
    scales = [float(value) for value in (step_scales if step_scales is not None else [1.0])]
    if not scales or any(not math.isfinite(value) or not 0 < value <= 1 for value in scales):
        raise CandidateContractError("Bootstrap stencil step scales are invalid.")
    groups = []
    for axis in range(-1, 4):
        trials = []
        for scale in ([1.0] if axis < 0 else scales):
            for direction in ([0] if axis < 0 else [1, -1]):
                # Preserve both multiplications, including their binary64 rounding.
                signed = 0.0 if axis < 0 else direction * steps[axis] * scale
                voltage = seed[:]
                if axis >= 0:
                    voltage[axis] += signed
                trials.append(dict(direction=direction, step_scale=scale, signed_step_v=signed,
                                   voltages_v=voltage, tier_index=0 if scale == 1.0 else scales.index(scale) + 1))
        groups.append(dict(axis=axis, trials=trials))
    return dict(step_scales=scales, groups=groups)


def prepare_imported_stencil_column(state: Mapping[str, Any], axis: int, anchor_v: Sequence[float],
                                    actual_v: Sequence[float], tiers: Sequence[float]) -> dict[str, Any]:
    """Project one identity-checked column immediately before its existing completion.

    The caller reads columns in their original order. This projection neither
    reads a later child nor changes when the workflow publishes its checkpoint.
    """
    result = copy.deepcopy(dict(state))
    anchor, actual = float(anchor_v[axis]), float(actual_v[axis])
    matches = []
    for index, relative in enumerate(tiers):
        size = float(relative) * max(abs(anchor), 1.0)
        if actual == anchor + size or actual == anchor - size:
            matches.append(index)
    if len(matches) == 1:
        result["local_model_tier_index"] = max(result["local_model_tier_index"], matches[0])
    result["flight_count"] += 1
    return dict(state=result, selected=dict(axis=axis, signed_step_v=actual - anchor))


def validate_recovery_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the separate frozen controller policy; no physical defaults."""
    required = {"schema_version", "role", "maximum_recovery_rounds", "total_probe_budget"}
    if (set(policy) != required or policy.get("schema_version") != 1
            or policy.get("role") != "mrtof_local_model_recovery_policy"):
        raise CandidateContractError("local model recovery policy identity differs")
    for key in ("maximum_recovery_rounds", "total_probe_budget"):
        if type(policy[key]) is not int or policy[key] <= 0:
            raise CandidateContractError(f"recovery policy {key} must be a positive integer")
    # Three rounds use the two adjacent ratios from the scientific contract tiers.
    if policy["maximum_recovery_rounds"] != 3:
        raise CandidateContractError("recovery rounds must correspond to coarse, medium and fine tiers")
    return dict(policy)


def _resume(state: dict[str, Any], action: str) -> None:
    state.update(status="probing", terminal_reason=None, model=None, next_action=action)


def _same_trigger(state: Mapping[str, Any], decision: Mapping[str, Any]) -> bool:
    return (state["accepted_anchor"]["record"]["voltages_v"] == decision["recovery_state"]["accepted_anchor"]["voltages_v"]
            and state["trigger"]["iteration"] == decision["iteration"]
            and state["trigger"]["reason"] == decision["recovery_state"]["model_invalid_reason"])


def _correct_anchor_evidence(state: dict[str, Any], evidence: Mapping[str, Any]) -> None:
    if state["accepted_anchor"]["evidence"]["materialization"] != evidence["materialization"]:
        state["accepted_anchor"]["evidence"] = copy.deepcopy(evidence)
        if state["status"] == "validated":
            _resume(state, "revalidate_local_model_against_corrected_anchor_evidence")
            state.update(model_version=0, history_validation=None)


def import_recovery_checkpoint(stored: Mapping[str, Any], history: Mapping[str, Any],
                               profile: Mapping[str, Any], policy: Mapping[str, Any],
                               decision: Mapping[str, Any] | None = None,
                               evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a declared frozen v5/v6/v7 checkpoint into a new run's v8 copy.

    These are the formats present in the 17 retained MR controller checkpoints
    inspected on 2026-10-27. Unknown formats need a separately reviewed importer.
    Probe records and signed steps remain unchanged. Corrected anchor evidence
    supplied by the verified lineage can invalidate the old model before import.
    """
    policy = validate_recovery_policy(policy)
    version = stored.get("recovery_policy_version")
    if (stored.get("role") != RECOVERY_ROLE or type(version) is not int
            or version not in (5, 6, 7, RECOVERY_VERSION)):
        raise CandidateContractError("unsupported recovery checkpoint; explicit v5/v6/v7 import required")
    state = copy.deepcopy(dict(stored))
    # Preserve the original order: lineage correction invalidates an old model
    # before the historical repeat-recovery transition chooses its fine tier.
    if decision is not None and evidence is not None and _same_trigger(state, decision):
        _correct_anchor_evidence(state, evidence)
    if version == RECOVERY_VERSION:
        _validate_current_recovery(state, policy)
        return state
    exhausted = state.get("status") == "terminal" and state.get("terminal_reason") == "model_recovery_exhausted"
    if version == 5:
        # Preserve the old v5 -> v6 transition at the explicit import boundary.
        state["maximum_recovery_rounds"] = policy["maximum_recovery_rounds"]
        state["total_probe_budget"] = policy["total_probe_budget"]
        used = sum(p["status"] in ("started", "accepted_physical_probe", "rejected_physical_probe", "failed")
                   for p in state["probes"])
        state["probe_budget_remaining"] = max(0, policy["total_probe_budget"] - used)
        if exhausted and state.get("model") is None and state["recovery_round"] < state["maximum_recovery_rounds"]:
            state = advance_recovery_round(state, profile)
            _resume(state, "refresh_independent_s_columns_at_next_relative_tier")
    if version < 7 and state["status"] != "validated" and any(
            d.get("recovery_resume_proposal") is True for d in history["decisions"]):
        anchor = state["accepted_anchor"]["record"]["voltages_v"]
        steps = voltage_stencil_steps(anchor, profile, 0.0)
        state.update(recovery_round=state["maximum_recovery_rounds"], probe_steps_v=steps[:2],
                     allowed_abs_step_v=steps[:2], history_validation=None)
        _resume(state, "refresh_independent_s_columns_at_persisted_fine_relative_tier")
    state["recovery_policy_version"] = RECOVERY_VERSION
    state["checkpoint_import"] = {"source_policy_version": version, "target_policy_version": RECOVERY_VERSION}
    _validate_current_recovery(state, policy)
    return state


def _validate_current_recovery(state: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    if state.get("role") != RECOVERY_ROLE or state.get("recovery_policy_version") != RECOVERY_VERSION:
        raise CandidateContractError("ordinary recovery requires current format; import the parent checkpoint explicitly")
    for key in ("maximum_recovery_rounds", "total_probe_budget"):
        if state.get(key) != policy[key]:
            raise CandidateContractError(f"recovery checkpoint differs from frozen policy: {key}")


def advance_recovery_round(state: Mapping[str, Any], profile: Mapping[str, Any],
                           *, replenish_columns: bool = False) -> dict[str, Any]:
    """Contract-derived tier reduction; retain the existing column retry policy."""
    result = copy.deepcopy(dict(state))
    next_round = int(result["recovery_round"]) + 1
    if next_round > int(result["maximum_recovery_rounds"]):
        raise CandidateContractError("recovery has no smaller contract tier")
    relative_voltage_step(profile, None)
    tiers = profile["jacobian_relative_step_tiers"]
    levels = [tiers[name] for name in ("coarse", "medium", "fine")]
    factor = levels[next_round - 1] / levels[next_round - 2]
    result["recovery_round"] = next_round
    result["probe_steps_v"] = [value * factor for value in result["probe_steps_v"]]
    result["allowed_abs_step_v"] = list(result["probe_steps_v"])
    if replenish_columns:
        result["probe_budget_remaining"] += len(result["probe_steps_v"])
    return result


def prepare_recovery_state(decision: Mapping[str, Any], evidence: Mapping[str, Any],
                           stored: Mapping[str, Any] | None, profile: Mapping[str, Any],
                           policy: Mapping[str, Any], history: Mapping[str, Any]) -> dict[str, Any]:
    """Prepare a new or current-format state without interpreting old versions."""
    policy = validate_recovery_policy(policy)
    anchor = decision["recovery_state"]["accepted_anchor"]
    steps = voltage_stencil_steps(anchor["voltages_v"], profile, anchor["maximum_scaled_abs_residual"])[:2]
    state = dict(schema_version=1, role=RECOVERY_ROLE, recovery_policy_version=RECOVERY_VERSION,
                 status="probing", accepted_anchor=dict(record=copy.deepcopy(anchor), evidence=copy.deepcopy(evidence)),
                 trigger=dict(iteration=decision["iteration"], reason=decision["recovery_state"]["model_invalid_reason"],
                              decision=copy.deepcopy(decision)),
                 model_version=0, allowed_abs_step_v=steps[:], probe_steps_v=steps[:], recovery_round=1,
                 maximum_recovery_rounds=policy["maximum_recovery_rounds"], trusted_prediction_count=0,
                 total_probe_budget=policy["total_probe_budget"], probe_budget_remaining=policy["total_probe_budget"],
                 probes=[], history_validation=None, model=None, next_action="probe_missing_independent_s_columns")
    restored = False
    if stored is not None:
        _validate_current_recovery(stored, policy)
        if _same_trigger(stored, decision):
            state = copy.deepcopy(dict(stored))
            restored = True
    if not restored and any(d.get("recovery_resume_proposal") is True for d in history["decisions"]):
        steps = voltage_stencil_steps(anchor["voltages_v"], profile, 0.0)[:2]
        state.update(recovery_round=policy["maximum_recovery_rounds"], probe_steps_v=steps[:],
                     allowed_abs_step_v=steps[:],
                     next_action="refresh_independent_s_columns_at_persisted_fine_relative_tier")
    _correct_anchor_evidence(state, evidence)
    exhausted = state["status"] == "terminal" and state.get("terminal_reason") == "model_recovery_exhausted"
    validation = state.get("history_validation")
    if exhausted and state.get("model") is None and isinstance(validation, Mapping):
        if validation["eligible_observation_count"] == 0 and state["recovery_round"] >= state["maximum_recovery_rounds"]:
            _resume(state, "re_evaluate_saved_final_radius_columns_as_provisional_model")
        elif not validation["passed"] and state["recovery_round"] < state["maximum_recovery_rounds"]:
            state = advance_recovery_round(state, profile, replenish_columns=True)
            _resume(state, "refresh_independent_s_columns_at_smaller_local_scale")
    return state


def _recovery_model_inputs(state: Mapping[str, Any]) -> dict[str, Any]:
    columns = []
    for axis in (0, 1):
        accepted = [probe for probe in state["probes"] if int(probe["axis"]) == axis
                    and str(probe["status"]).casefold() == "accepted_physical_probe"
                    and int(probe["round"]) == int(state["recovery_round"])]
        if len(accepted) != 1:
            raise CandidateContractError("Accepted local S probe columns are incomplete.")
        columns.append(copy.deepcopy(accepted[0]))
    return dict(columns=columns, supported_directions=[int(probe["direction"]) for probe in columns],
                trusted_radius_linf_v=max(float(state["probe_steps_v"][0]), float(state["probe_steps_v"][1])))


def plan_recovery_probe(state: Mapping[str, Any], directions: Sequence[int],
                        profile: Mapping[str, Any]) -> dict[str, Any]:
    """Choose one whole physical probe or the original end-of-round action.

    This runs after the workflow saves prepared/completed evidence. The returned
    started record is given its run ID and saved before its physical dispatch.
    """
    result = copy.deepcopy(dict(state))
    current = int(result["recovery_round"])
    for axis in (0, 1):
        existing = [probe for probe in result["probes"] if int(probe["axis"]) == axis
                    and str(probe["status"]).casefold() == "accepted_physical_probe" and int(probe["round"]) == current]
        if len(existing) > 1:
            raise CandidateContractError("Recovery has more than one accepted physical probe for an axis and round.")
        if existing:
            continue
        preferred = int(directions[axis])
        for direction in dict.fromkeys((preferred, -preferred)):
            if any(int(probe["axis"]) == axis and int(probe["direction"]) == direction
                   and int(probe["round"]) == current for probe in result["probes"]):
                continue
            if result["probe_budget_remaining"] <= 0:
                break
            trial = [float(value) for value in result["accepted_anchor"]["record"]["voltages_v"]]
            signed = direction * float(result["probe_steps_v"][axis])
            trial[axis] += signed
            result["probes"].append(dict(round=current, axis=axis, direction=direction,
                                         signed_step_v=signed, status="started"))
            result["probe_budget_remaining"] -= 1
            return dict(action="probe", state=result, voltages_v=trial)
        if current < int(result["maximum_recovery_rounds"]):
            result = advance_recovery_round(result, profile, replenish_columns=False)
            result.update(status="retry", model=None, next_action="refresh_independent_s_columns_at_next_relative_tier")
        else:
            result.update(status="terminal", terminal_reason="model_recovery_exhausted", next_action="stop_with_best_accepted_workpoint")
        return dict(action="return", state=result)
    return dict(action="refresh", state=result, **_recovery_model_inputs(result))


def _powershell_boolean(value: Any) -> bool:
    """Preserve the former -not predicate for JSON model validation values."""
    if isinstance(value, Mapping):
        return True
    if isinstance(value, list):
        return _powershell_boolean(value[0]) if len(value) == 1 else bool(value)
    return bool(value)


def complete_recovery_model(state: Mapping[str, Any], model: Mapping[str, Any],
                            profile: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the existing final-radius provisional policy without changing it.

    Publication and the model SHA remain with the caller: it writes a changed
    model first, then binds its actual file hash to the returned model projection.
    """
    result, updated = copy.deepcopy(dict(state)), copy.deepcopy(dict(model))
    validation = updated["history_validation"]
    if not isinstance(validation, Mapping):
        # The former strict-mode PS property access also failed before final Save.
        raise CandidateContractError("Recovery model history validation is not an object.")
    current, maximum = int(result["recovery_round"]), int(result["maximum_recovery_rounds"])
    inputs = _recovery_model_inputs(result)
    # The old PS [int] conversion rounds numeric JSON values, rather than truncating.
    no_nearby = round(float(validation["eligible_observation_count"] or 0)) == 0
    publish_model = not _powershell_boolean(validation["passed"]) and no_nearby and current >= maximum
    if publish_model:
        validation.update(passed=True, validation_status="provisional_no_nearby_history",
                          first_correction_requires_real_prediction_acceptance=True,
                          first_correction_max_linf_v=inputs["trusted_radius_linf_v"])
    if validation["passed"] is not True:
        if current < maximum:
            result = advance_recovery_round(result, profile, replenish_columns=True)
            result.update(status="retry", history_validation=validation, model=None,
                          next_action="refresh_independent_s_columns_at_smaller_local_scale")
        else:
            result.update(status="terminal", terminal_reason="model_recovery_exhausted", history_validation=validation,
                          next_action="stop_with_best_accepted_workpoint")
        projection = None
    else:
        result.update(status="validated", model_version=2, history_validation=validation,
                      next_action="resume_bounded_s_solve_from_accepted_anchor")
        projection = dict(local_s_physical_jacobian_columns=updated["local_s_physical_jacobian_columns"],
                          trusted_radius_linf_v=inputs["trusted_radius_linf_v"], supported_directions=inputs["supported_directions"])
    return dict(state=result, model=updated, publish_model=publish_model, model_projection=projection)


def complete_staged_trial(state: Mapping[str, Any], pending: Mapping[str, Any],
                          checked: Mapping[str, Any], prediction: Mapping[str, Any],
                          loop: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the measured candidate/stencil decision after the workflow verifies identity.

    The return value contains only state and history projections. The caller owns
    their publication and the public compose-payload lifecycle operation.
    """
    result = copy.deepcopy(dict(state))
    result.setdefault("local_model_tier_index", 0)
    result.setdefault("consecutive_candidate_rejections", 0)
    decision = pending["decision"]
    child = pending["child_manifest"]
    history_decision = None
    payload_use = "keep"
    qualified = checked.get("full_workpoint_qualified") is True

    def accept_anchor() -> None:
        result.update(anchor_manifest=child, columns={}, attempts=[], consecutive_candidate_rejections=0)

    if decision["status"] == "needs_stencil":
        if qualified:
            history_decision = copy.deepcopy(dict(checked))
            accept_anchor()
            result.update(step_factor=1.0, completion_attempted=False)
        else:
            result["attempts"].append(copy.deepcopy(pending["selected"]))
            result["columns"][str(pending["selected"]["axis"])] = child
            if checked.get("full_workpoint_qualified") is False:
                payload_use = "stencil"
    else:
        history_decision = copy.deepcopy(dict(checked))
        history_decision["prediction_assessment"] = copy.deepcopy(prediction)
        result["prediction_assessment"] = copy.deepcopy(prediction)
        stage_changed = checked["next_action"] in ("prism_preclosure", "stripe_preclosure") and checked["next_action"] != state["stage"]
        joint_p_rejected = decision.get("refinement_mode") == "joint_ps_constrained" and checked["next_action"] == "prism_preclosure"
        rejected = (checked["status"] == "terminal" and not qualified) or joint_p_rejected
        improved = (not rejected and "maximum_scaled_abs_residual" in checked
                    and checked["maximum_scaled_abs_residual"] <= (1.0 - loop["minimum_relative_improvement"]) * decision["maximum_scaled_abs_residual"])
        if qualified or (not rejected and (stage_changed or improved or decision["next_action"] == "complete_N1")):
            accept_anchor()
            if stage_changed:
                result["local_model_tier_index"] = 0
                result.pop("prism_model_manifest", None)
            result["step_factor"] = (state["step_factor"] * decision["backtrack_multiplier"]
                                     if prediction["status"] == "poor" else 1.0)
            if decision["next_action"] != "complete_N1":
                result["completion_attempted"] = False
        else:
            result["step_factor"] *= decision["backtrack_multiplier"]
            if state["stage"] == "stripe_preclosure":
                result["consecutive_candidate_rejections"] += 1
            if rejected and checked.get("full_workpoint_qualified") is False:
                payload_use = "rejected_candidate"
    result.pop("pending_trial", None)
    return dict(state=result, history_decision=history_decision, compose_payload_use=payload_use)


def _voltages(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise CandidateContractError(f"{label} must contain S1/S2/P1/P2")
    return [_finite(item, label) for item in value]


def _stripe_stage_axes(active: list[int], profile: Mapping[str, Any]) -> list[int]:
    if "single_stripe_refinement_mode" in profile:
        if profile["single_stripe_refinement_mode"] != "joint_ps_constrained" or active != [0]:
            raise CandidateContractError("Joint P/S refinement requires the explicit single-S1 profile.")
        return [0, 2, 3]
    return active


def _staged_axes(stage: str, profile: Mapping[str, Any]) -> list[int]:
    names = profile.get("active_stripe_axes")
    if names not in (["stripe_1_voltage_v"], ["stripe_1_voltage_v", "stripe_2_voltage_v"]):
        raise CandidateContractError("Active Stripe axes must explicitly declare S1 or S1/S2 in canonical order.")
    if stage == "prism_preclosure":
        return [2, 3]
    if stage != "stripe_preclosure":
        raise CandidateContractError("unknown staged controller stage")
    return _stripe_stage_axes(list(range(len(names))), profile)


def restored_stage_columns(stage: str, profile: Mapping[str, Any]) -> list[int]:
    """Project saved-column axes with the former PS input representation.

    Restore historically treats non-prism stages as Stripe. Its name check is
    case-insensitive, while Array.IndexOf is exact; keep that identity behavior
    here without weakening the ordinary planner's canonical profile validation.
    """
    if stage.casefold() == "prism_preclosure":
        return [2, 3]
    names = profile["active_stripe_axes"]
    names = names if isinstance(names, list) else [names]
    canonical = ["stripe_1_voltage_v", "stripe_2_voltage_v"]
    if ",".join(names).casefold() not in (canonical[0], ",".join(canonical)):
        raise CandidateContractError("Active Stripe axes must explicitly declare S1 or S1/S2 in canonical order.")
    active = [canonical.index(name) if name in canonical else -1 for name in names]
    projected = dict(profile)
    if "single_stripe_refinement_mode" in projected:
        projected["single_stripe_refinement_mode"] = str(projected["single_stripe_refinement_mode"]).casefold()
    return _stripe_stage_axes(active, projected)


def main_iteration_budget(maximum_iterations: int, terminal_decision: Mapping[str, Any] | None,
                          *, next_iteration: int | None = None, phase: str = "start") -> dict[str, Any]:
    """Apply the main-flight budget at its original pre/post-loop boundary."""
    if phase not in ("start", "exhausted"):
        raise CandidateContractError("unknown main iteration budget phase")
    terminal = copy.deepcopy(terminal_decision)
    if terminal is None and (phase == "exhausted" or next_iteration > maximum_iterations):
        terminal = dict(schema_version=1, role="mrtof_downstream_workpoint_iteration_decision",
                        state="terminal", terminal_reason="maximum_iterations",
                        iteration=maximum_iterations if phase == "exhausted" else next_iteration - 1,
                        detail=f"maximum main real centre-flight count {maximum_iterations} reached")
    return dict(maximum_flight_attempts=maximum_iterations, terminal_decision=terminal)


def plan_staged_trial(state: Mapping[str, Any], profile: Mapping[str, Any],
                      decision: Mapping[str, Any] | None = None, *, phase: str = "trial") -> dict[str, Any]:
    """Plan one whole trial without files, a child identity or a solver call.

    The rare prepare phase precedes a fresh scientific decision, preserving the
    saved reset -> decision -> trial order. Trial debits are returned together;
    the workflow attaches and persists pending_trial before executing the child.
    """
    result = copy.deepcopy(dict(state))
    axes = _staged_axes(result["stage"], profile)
    relative_voltage_step(profile, None)
    tiers = [_finite(profile["jacobian_relative_step_tiers"][name], name) for name in ("coarse", "medium", "fine")]
    tier = result["local_model_tier_index"]
    if type(tier) is not int or not 0 <= tier < len(tiers):
        raise CandidateContractError("invalid staged local-model tier")
    for key in ("flight_count", "candidate_count", "consecutive_candidate_rejections"):
        if type(result[key]) is not int or result[key] < 0:
            raise CandidateContractError(f"invalid staged {key}")
    loop = profile["automatic_iteration"]
    response = dict(state=result, action="dispatch", voltages_v=None, selected=None,
                    terminal=None, history_decision=None)

    def terminal(reason: str, detail: str | None = None) -> dict[str, Any]:
        response["action"] = "terminal"
        response["terminal"] = dict(state="terminal", terminal_reason=reason, full_workpoint_qualified=False)
        if detail is not None:
            response["terminal"]["detail"] = detail
        return response

    if phase == "prepare":
        response["action"] = "continue"
        if result["stage"] != "stripe_preclosure" or result["consecutive_candidate_rejections"] < loop["maximum_consecutive_non_improving_iterations"]:
            return response
        if tier >= len(tiers) - 1:
            return terminal("model_recovery_exhausted", "All contract S local-model tiers rejected candidates.")
        response["history_decision"] = dict(status="local_model_refresh", reason="consecutive_rejected_S_candidates",
                                            anchor_manifest=result["anchor_manifest"], previous_columns=result["columns"],
                                            previous_relative_tier=tiers[tier], next_relative_tier=tiers[tier + 1],
                                            full_workpoint_qualified=False)
        result.update(local_model_tier_index=tier + 1, consecutive_candidate_rejections=0,
                      columns={}, attempts=[], step_factor=1.0)
        return response
    if phase != "trial" or not isinstance(decision, Mapping):
        raise CandidateContractError("staged trial requires a decision and a known phase")
    if decision["status"] == "terminal":
        response.update(action="terminal", terminal=copy.deepcopy(dict(decision)))
        return response
    if decision["next_action"] in ("prism_preclosure", "stripe_preclosure"):
        result.update(stage=decision["next_action"], columns={}, attempts=[], step_factor=1.0,
                      local_model_tier_index=0, consecutive_candidate_rejections=0)
        result.pop("prism_model_manifest", None)
        response["action"] = "stage_transition"
        return response
    voltages = _voltages(decision["next_voltages_v"], "next voltages")
    response["voltages_v"] = voltages
    if decision["status"] == "needs_stencil":
        axis = decision["required_axes"][0]
        if type(axis) is not int or axis not in axes:
            raise CandidateContractError("Controller requested an inactive stage stencil axis.")
        anchor = _voltages(decision["voltages_v"], "anchor voltages")
        lower = _voltages(decision["resolved_numerics"]["lower_bounds_v"], "lower bounds")
        upper = _voltages(decision["resolved_numerics"]["upper_bounds_v"], "upper bounds")
        if any(lo > hi for lo, hi in zip(lower, upper)):
            raise CandidateContractError("staged lower bounds exceed upper bounds")
        if result["stage"] == "stripe_preclosure":
            residual_tier = tiers.index(relative_voltage_step(profile, decision["maximum_scaled_abs_residual"]))
            result["local_model_tier_index"] = max(tier, residual_tier)
        start = result["local_model_tier_index"] if result["stage"] == "stripe_preclosure" else 0
        selected = None
        for index in range(start, len(tiers)):
            for direction in (1, -1):
                # Preserve the original multiplication and exact attempt comparison.
                step = direction * tiers[index] * max(abs(anchor[axis]), 1.0)
                used = any(item["axis"] == axis and item["signed_step_v"] == step for item in result["attempts"])
                target = anchor[axis] + step
                if not used and lower[axis] <= target <= upper[axis] and selected is None:
                    selected = dict(axis=axis, signed_step_v=step)
                    if result["stage"] == "stripe_preclosure":
                        result["local_model_tier_index"] = index
        if selected is None:
            return terminal("model_recovery_exhausted", "No measurable same-anchor stage column within contract tiers.")
        voltages = anchor[:]
        voltages[axis] += selected["signed_step_v"]
        response.update(voltages_v=voltages, selected=selected)
    elif decision["status"] == "proposed":
        if result["candidate_count"] >= loop["maximum_iterations"]:
            return terminal("maximum_iterations")
        anchor = _voltages(decision["voltages_v"], "anchor voltages")
        factor = _finite(result["step_factor"], "step factor")
        voltages = [anchor[i] + factor * (voltages[i] - anchor[i]) for i in range(4)]
        response["voltages_v"] = voltages
        if max(abs(voltages[i] - anchor[i]) for i in range(4)) < loop["minimum_step_linf_v"]:
            return terminal("step_too_small")
        result["candidate_count"] += 1
    elif decision["next_action"] == "complete_N1":
        if result["completion_attempted"]:
            return terminal("missing_target_phase", "The complete centre flight still lacks measurable stage events.")
        result["completion_attempted"] = True
    else:
        return terminal(decision["status"], decision["next_action"])
    if len(profile["active_stripe_axes"]) == 1 and voltages[1] != 0.0:
        raise CandidateContractError("Inactive S2 must remain at the authored zero-volt seed.")
    result["flight_count"] += 1
    return response


def recovery_probe_directions(history: Any, anchor: Mapping[str, Any],
                              state: Mapping[str, Any], decision: Mapping[str, Any]) -> list[int]:
    """Preserve the actual History argument semantics, then trigger/hint priority.

    The workflow passes the history document itself, not its decisions list.
    That mapping yields the default sides unless it itself has observation_record.
    Traversing history['decisions'] here would change the existing scientific policy.
    """
    anchor_v = _voltages(anchor["voltages_v"], "recovery anchor")
    items = [history] if isinstance(history, Mapping) else history
    directions = [1, 1]
    for axis in (0, 1):
        candidates = []
        for item in items:
            record = item.get("observation_record") if isinstance(item, Mapping) else None
            values = record.get("voltages_v") if isinstance(record, Mapping) else None
            if not isinstance(values, (list, tuple)) or len(values) != 4:
                continue
            voltage = _voltages(values, "history voltages")
            if abs(voltage[2] - anchor_v[2]) > 1e-10 or abs(voltage[3] - anchor_v[3]) > 1e-10:
                continue
            delta = voltage[axis] - anchor_v[axis]
            if abs(delta) <= 1e-12:
                continue
            candidates.append((max(abs(voltage[0] - anchor_v[0]), abs(voltage[1] - anchor_v[1])), delta))
        if candidates:
            delta = min(candidates, key=lambda pair: pair[0])[1]
            directions[axis] = 1 if delta > 0 else -1
    trigger = state.get("trigger", {}).get("decision", {}).get("observation_record")
    if isinstance(trigger, Mapping) and isinstance(trigger.get("voltages_v"), (list, tuple)) and len(trigger["voltages_v"]) == 4:
        values = _voltages(trigger["voltages_v"], "trigger voltages")
        for axis in (0, 1):
            delta = values[axis] - anchor_v[axis]
            if abs(delta) > 1e-12:
                directions[axis] = 1 if delta > 0 else -1
    hint = decision.get("recovery_state", {}).get("initial_probe_directions")
    if isinstance(hint, (list, tuple)) and len(hint) == 2:
        # PowerShell's numeric [int] cast rounds to nearest, ties to even.
        converted = [int(value) if isinstance(value, str) else round(_finite(value, "direction hint")) for value in hint]
        if all(value in (-1, 1) for value in converted):
            directions = converted
    return directions


def interrupted_topology_recovery_decision(history: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project only the existing unambiguous persisted S-only topology transition."""
    decisions = history["decisions"]
    anchors = [index for index, value in enumerate(decisions) if isinstance(value, Mapping)
               and value.get("coordinate_group") == "stripe_1_stripe_2" and isinstance(value.get("accepted_workpoint"), Mapping)]
    if not anchors or anchors[-1] == len(decisions) - 1:
        return None
    anchor = decisions[anchors[-1]]["accepted_workpoint"]
    if not isinstance(anchor.get("voltages_v"), (list, tuple)) or len(anchor["voltages_v"]) != 4:
        return None
    anchor_v = _voltages(anchor["voltages_v"], "topology anchor")
    first = None
    for candidate in decisions[anchors[-1] + 1:]:
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("state") == "recovery_required":
            return None
        recovery = candidate.get("recovery_state")
        if (candidate.get("coordinate_group") == "physical_topology_backtrack"
                and candidate.get("invalid_trial_reason") == "collision_or_invalid_topology"
                and isinstance(recovery, Mapping) and isinstance(recovery.get("recovery_origin_voltages_v"), (list, tuple))):
            first = candidate
            break
    if first is None or len(first["recovery_state"]["recovery_origin_voltages_v"]) != 4:
        return None
    origin = _voltages(first["recovery_state"]["recovery_origin_voltages_v"], "topology origin")
    if abs(origin[2] - anchor_v[2]) > 1e-10 or abs(origin[3] - anchor_v[3]) > 1e-10:
        return None
    if any(abs(origin[axis] - anchor_v[axis]) <= 1e-12 for axis in (0, 1)):
        return None
    directions = [1 if origin[axis] > anchor_v[axis] else -1 for axis in (0, 1)]
    return dict(schema_version=1, role="mrtof_downstream_workpoint_iteration_decision", state="recovery_required", terminal_reason=None,
                iteration=first["iteration"], coordinate_group="stripe_1_stripe_2", observation_record=copy.deepcopy(anchor),
                accepted_workpoint=copy.deepcopy(anchor), candidate_accepted=False, invalid_trial_reason="collision_or_invalid_topology",
                invalid_trial_detail="persisted S-only topology loss before automatic local-model recovery", invalid_candidate_voltages_v=origin,
                prediction_assessment=dict(accepted=False, topology_valid=False, model_invalid_reason="s_only_topology_loss", candidate_voltages_v=origin),
                recovery_state=dict(schema_version=1, accepted_anchor=copy.deepcopy(anchor),
                                    advance_multiplier=_finite(first["recovery_state"]["advance_multiplier"], "advance multiplier"),
                                    backtrack_multiplier=_finite(first["recovery_state"]["backtrack_multiplier"], "backtrack multiplier"),
                                    rejected_line_count=1, recovery_origin_voltages_v=origin, model_invalid_reason="s_only_topology_loss",
                                    trusted_prediction_count=0, initial_probe_directions=directions),
                next_action="refresh_independent_s_columns_after_persisted_s_only_topology_loss")


def dispatch_controller_request(request: Mapping[str, Any]) -> Any:
    """Internal stdin bridge used by the existing controller CLI."""
    action = request["action"]
    if action == "voltage_stencil_steps":
        return voltage_stencil_steps(request["voltages_v"], request["profile"], request.get("maximum_scaled_residual"))
    if action == "bootstrap_stencil_configuration":
        return bootstrap_stencil_configuration(request["voltages_v"], request["profile"])
    if action == "continuation_transport_candidates":
        return continuation_transport_candidates(request["seed"], request["profile"])
    if action == "center_trial_physical_gate":
        return center_trial_physical_gate(request["observation"])
    if action == "plan_bootstrap_stencil":
        return plan_bootstrap_stencil(request["voltages_v"], request["forward_steps_v"], request.get("step_scales"))
    if action == "prepare_imported_stencil_column":
        return prepare_imported_stencil_column(request["state"], request["axis"], request["anchor_v"], request["actual_v"], request["tiers"])
    if action == "plan_recovery_probe":
        return plan_recovery_probe(request["state"], request["directions"], request["profile"])
    if action == "complete_recovery_model":
        return complete_recovery_model(request["state"], request["model"], request["profile"])
    if action == "restored_stage_columns":
        return restored_stage_columns(request["stage"], request["profile"])
    if action == "main_iteration_budget":
        return main_iteration_budget(request["maximum_iterations"], request["terminal_decision"],
                                     next_iteration=request.get("next_iteration"), phase=request["phase"])
    if action == "validate_recovery_policy":
        return validate_recovery_policy(request["policy"])
    if action == "import_recovery_checkpoint":
        return import_recovery_checkpoint(request["stored"], request["history"], request["profile"], request["policy"],
                                          request.get("decision"), request.get("evidence"))
    if action == "prepare_recovery_state":
        state = prepare_recovery_state(request["decision"], request["evidence"], request["stored"], request["profile"], request["policy"], request["history"])
        if request.get("include_probe_directions") is True:
            return dict(state=state, required_directions=recovery_probe_directions(request["history"], request["decision"]["recovery_state"]["accepted_anchor"], state, request["decision"]))
        return state
    if action == "advance_recovery_round":
        return advance_recovery_round(request["state"], request["profile"], replenish_columns=request["replenish_columns"])
    if action == "complete_staged_trial":
        return complete_staged_trial(request["state"], request["pending"], request["checked"], request["prediction"], request["loop"])
    if action == "plan_staged_trial":
        return plan_staged_trial(request["state"], request["profile"], request.get("decision"), phase=request.get("phase", "trial"))
    if action == "interrupted_topology_recovery_decision":
        return interrupted_topology_recovery_decision(request["history"])
    raise CandidateContractError(f"unknown controller request: {action}")
