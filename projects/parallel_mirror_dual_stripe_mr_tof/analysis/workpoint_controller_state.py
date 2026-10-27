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


def dispatch_controller_request(request: Mapping[str, Any]) -> Any:
    """Internal stdin bridge used by the existing controller CLI."""
    action = request["action"]
    if action == "voltage_stencil_steps":
        return voltage_stencil_steps(request["voltages_v"], request["profile"], request.get("maximum_scaled_residual"))
    if action == "validate_recovery_policy":
        return validate_recovery_policy(request["policy"])
    if action == "import_recovery_checkpoint":
        return import_recovery_checkpoint(request["stored"], request["history"], request["profile"], request["policy"],
                                          request.get("decision"), request.get("evidence"))
    if action == "prepare_recovery_state":
        return prepare_recovery_state(request["decision"], request["evidence"], request["stored"], request["profile"], request["policy"], request["history"])
    if action == "advance_recovery_round":
        return advance_recovery_round(request["state"], request["profile"], replenish_columns=request["replenish_columns"])
    if action == "complete_staged_trial":
        return complete_staged_trial(request["state"], request["pending"], request["checked"], request["prediction"], request["loop"])
    raise CandidateContractError(f"unknown controller request: {action}")
