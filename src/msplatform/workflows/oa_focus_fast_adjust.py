"""Bounded axial-voltage correction for one geometry-qualified accelerator PA."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from msplatform.io.file_identity import file_sha256
from msplatform.components.orthogonal_accelerator.focus_voltage_adjustment import (
    ComponentFocusFastAdjustError, _number, _parameters, _candidate_campaign,
    advance_adjustment_state,
)
from msplatform.workflows.oa_focus_analysis import _load_campaign
from msplatform.components.orthogonal_accelerator.focus_campaign import geometry_profile_identity




_ROLE = "orthogonal_accelerator_component_focus_fast_adjust_controller"
_STATE_KEYS = {
    "schema_version", "role", "status", "campaign_sha256", "maximum_trials",
    "records", "next_parameters", "phase", "geometry_profile_sha256", "base_record_index", "probe_relative_step",
    "best_record_index",
}








def _load_analysis(path: Path, *, geometry_profile: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComponentFocusFastAdjustError("component-focus analysis is unreadable") from error
    if not isinstance(value, dict) or value.get("schema_version") != 2 or value.get("role") != "orthogonal_accelerator_component_focus_analysis":
        raise ComponentFocusFastAdjustError("component-focus analysis identity is invalid")
    identity = value.get("identity")
    if not isinstance(identity, dict) or identity.get("geometry_profile_sha256") != geometry_profile_identity(geometry_profile):
        raise ComponentFocusFastAdjustError("component-focus analysis belongs to a different geometry profile")
    metrics, hard_gate, energy = value.get("focus_metrics"), value.get("hard_gate"), value.get("exit_energy_assessment")
    if not isinstance(metrics, dict) or not isinstance(hard_gate, dict) or not isinstance(energy, dict):
        raise ComponentFocusFastAdjustError("component-focus analysis lacks focus or exit-energy evidence")
    center, cohort, tolerances = energy.get("center_particle"), energy.get("cohort"), energy.get("tolerances")
    if not isinstance(center, dict) or not isinstance(cohort, dict) or not isinstance(tolerances, dict):
        raise ComponentFocusFastAdjustError("component-focus exit-energy evidence is incomplete")
    axial = _number(center.get("axial_energy_residual_per_charge_v"), "center axial-energy residual")
    slow_tolerance = _number(tolerances.get("maximum_exit_slow_energy_error_per_charge_v"), "slow-energy tolerance")
    axial_tolerance = _number(tolerances.get("maximum_exit_axial_energy_error_per_charge_v"), "axial-energy tolerance")
    transverse_tolerance = _number(tolerances.get("maximum_exit_transverse_energy_error_per_charge_v"), "transverse-energy tolerance")
    velocity_bias_tolerance = _number(tolerances.get("maximum_exit_transverse_velocity_bias_mm_per_us"), "transverse-velocity bias tolerance")
    cohort_slow = _number(cohort.get("maximum_absolute_slow_energy_residual_per_charge_v"), "cohort slow-energy residual")
    cohort_axial = _number(cohort.get("maximum_absolute_axial_energy_residual_per_charge_v"), "cohort axial-energy residual")
    cohort_transverse = _number(cohort.get("maximum_absolute_transverse_energy_residual_per_charge_v"), "cohort transverse-energy residual")
    mean_delta_vx = _number(cohort.get("mean_delta_vx_mm_per_us"), "cohort mean transverse-velocity bias")
    center_delta_vx = _number(center.get("delta_vx_mm_per_us"), "center transverse-velocity bias")
    if min(slow_tolerance, axial_tolerance, transverse_tolerance, velocity_bias_tolerance) <= 0.0:
        raise ComponentFocusFastAdjustError("exit-energy tolerances must be positive")
    accepted = (
        value.get("status") == "candidate_complete"
        and hard_gate.get("complete_transport_passed") is True
        and hard_gate.get("exit_slow_energy_passed") is True
        and hard_gate.get("exit_axial_energy_passed") is True
        and hard_gate.get("exit_transverse_energy_passed") is True
        and hard_gate.get("exit_transverse_velocity_bias_passed") is True
    )
    transport_complete = hard_gate.get("complete_transport_passed") is True
    geometry_acceptable = (
        transport_complete
        and cohort_slow <= slow_tolerance
        and cohort_transverse <= transverse_tolerance
        and abs(center_delta_vx) <= velocity_bias_tolerance
        and abs(mean_delta_vx) <= velocity_bias_tolerance
    )
    geometry_diagnostic = (
        "transport_incomplete"
        if not transport_complete
        else (
            "cohort_Ex_Ey_geometry_gate_passed"
            if geometry_acceptable
            else "cohort_Ex_Ey_geometry_gate_failed"
        )
    )
    return {
        "analysis_sha256": file_sha256(path).lower(), "residuals": [axial],
        "maximum_normalized_residual": abs(axial) / axial_tolerance,
        "score": max(cohort_slow / slow_tolerance, cohort_axial / axial_tolerance,
                     cohort_transverse / transverse_tolerance),
        "peak_to_peak_t_ns": _number(metrics.get("peak_to_peak_t_ns"), "focus peak-to-peak time"),
        "accepted": accepted, "geometry_acceptable": geometry_acceptable,
        "geometry_diagnostic": geometry_diagnostic,
        "center_axial_energy_passed": abs(axial) <= axial_tolerance,
        "valid": transport_complete,
    }










def initialize(campaign_path: Path, maximum_trials: int, *, geometry_profile: dict[str, Any]) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path, geometry_profile=geometry_profile)
    if maximum_trials < 4 or maximum_trials > 20:
        raise ComponentFocusFastAdjustError("maximum trials must be between 4 and 20")
    return {
        "schema_version": 2, "role": _ROLE, "status": "running",
        "campaign_sha256": file_sha256(campaign_path).lower(), "maximum_trials": maximum_trials,
        "geometry_profile_sha256": geometry_profile_identity(geometry_profile),
        "records": [], "next_parameters": _parameters(campaign), "phase": "base",
        "base_record_index": None, "probe_relative_step": None, "best_record_index": None,
    }


def record_analysis(state: dict[str, Any], analysis_path: Path, campaign: dict[str, Any], *, geometry_profile: dict[str, Any]) -> dict[str, Any]:
    if set(state) != _STATE_KEYS or state.get("schema_version") != 2 or state.get("role") != _ROLE:
        raise ComponentFocusFastAdjustError("controller state is invalid")
    if state["geometry_profile_sha256"] != geometry_profile_identity(geometry_profile):
        raise ComponentFocusFastAdjustError("controller state belongs to a different geometry profile")
    if state["status"] != "running" or not isinstance(state["next_parameters"], dict):
        raise ComponentFocusFastAdjustError("controller has no pending candidate")
    record = {"kind": state["phase"], "parameters": state["next_parameters"], **_load_analysis(analysis_path, geometry_profile=geometry_profile)}
    return advance_adjustment_state(state, record, campaign, geometry_profile=geometry_profile)


def _write_campaign(path: Path, campaign: dict[str, Any], parameters: dict[str, float], *, geometry_profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_candidate_campaign(campaign, parameters, geometry_profile=geometry_profile), indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--component-contract", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--maximum-trials", type=int)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--candidate-campaign", type=Path)
    parser.add_argument("--selected-campaign", type=Path)
    parser.add_argument("--best-campaign", type=Path)
    args = parser.parse_args()
    try:
        raw_campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
        geometry_profile = json.loads(args.component_contract.read_text(encoding="utf-8"))["geometry_profiles"][raw_campaign["geometry_profile_id"]]
        campaign = _load_campaign(args.campaign, geometry_profile=geometry_profile)
        if args.state.exists():
            state = json.loads(args.state.read_text(encoding="utf-8"))
            if set(state) != _STATE_KEYS or state.get("schema_version") != 2 or state.get("role") != _ROLE:
                raise ComponentFocusFastAdjustError("controller state is invalid")
            if state.get("geometry_profile_sha256") != geometry_profile_identity(geometry_profile):
                raise ComponentFocusFastAdjustError("controller state belongs to a different geometry profile")
            if state.get("campaign_sha256") != file_sha256(args.campaign).lower():
                raise ComponentFocusFastAdjustError("controller state belongs to a different campaign")
        else:
            if args.maximum_trials is None:
                raise ComponentFocusFastAdjustError("new controller state requires maximum trials")
            state = initialize(args.campaign, args.maximum_trials, geometry_profile=geometry_profile)
        if args.analysis is not None:
            state = record_analysis(state, args.analysis, campaign, geometry_profile=geometry_profile)
        if args.candidate_campaign is not None:
            if not isinstance(state.get("next_parameters"), dict):
                raise ComponentFocusFastAdjustError("controller has no pending candidate campaign")
            _write_campaign(args.candidate_campaign, campaign, state["next_parameters"], geometry_profile=geometry_profile)
        if args.selected_campaign is not None:
            accepted = [record for record in state["records"] if record["accepted"]]
            if state["status"] != "accepted" or len(accepted) != 1:
                raise ComponentFocusFastAdjustError("controller has no accepted campaign")
            _write_campaign(args.selected_campaign, campaign, accepted[0]["parameters"], geometry_profile=geometry_profile)
        if args.best_campaign is not None:
            index = state.get("best_record_index")
            if not isinstance(index, int):
                raise ComponentFocusFastAdjustError("controller has no evaluated campaign")
            _write_campaign(args.best_campaign, campaign, state["records"][index]["parameters"], geometry_profile=geometry_profile)
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_FAST_ADJUST=FAIL ERROR={error}")
        return 1
    print(f"ACCELERATOR_COMPONENT_FOCUS_FAST_ADJUST=PASS STATUS={state['status']} TRIALS={len(state['records'])} NEXT={state['next_parameters']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
