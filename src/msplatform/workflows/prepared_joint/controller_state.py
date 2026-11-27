"""Legacy stdio transport for the MR controller state owner."""
from __future__ import annotations

from typing import Any, Mapping
from msplatform.components.multi_reflection_tof.candidate_contract import CandidateContractError
from msplatform.components.multi_reflection_tof.workpoint_controller_state import (
    advance_recovery_round,
    bootstrap_stencil_configuration,
    center_trial_physical_gate,
    complete_recovery_model,
    complete_staged_trial,
    continuation_transport_candidates,
    import_recovery_checkpoint,
    interrupted_topology_recovery_decision,
    main_iteration_budget,
    plan_bootstrap_stencil,
    plan_recovery_probe,
    plan_staged_trial,
    prepare_imported_stencil_column,
    prepare_recovery_state,
    recovery_probe_directions,
    restored_stage_columns,
    validate_recovery_policy,
    voltage_stencil_steps,
)


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


def main() -> int:
    """Transport one internal controller request through the pure owner."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-request", choices=("-",), required=True,
                        help=argparse.SUPPRESS)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.output != "-":
        parser.error("internal controller request writes only to stdout")
    print(json.dumps(dispatch_controller_request(json.load(sys.stdin))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
