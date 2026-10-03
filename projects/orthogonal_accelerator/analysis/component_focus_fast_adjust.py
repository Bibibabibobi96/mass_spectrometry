"""Bounded axial-voltage correction for one geometry-qualified accelerator PA."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from projects.orthogonal_accelerator.analysis.component_focus_analysis import _load_campaign
from projects.orthogonal_accelerator.simion.two_zone_candidate import _load_geometry_profile


class ComponentFocusFastAdjustError(ValueError):
    """Raised when the bounded accelerator correction cannot continue."""


_ROLE = "orthogonal_accelerator_component_focus_fast_adjust_controller"
_STATE_KEYS = {
    "schema_version", "role", "status", "campaign_sha256", "maximum_trials",
    "records", "next_parameters", "phase", "base_record_index", "probe_relative_step",
    "best_record_index",
}
_TIERS = ((2.0, 0.0005), (10.0, 0.0025), (math.inf, 0.01))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ComponentFocusFastAdjustError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ComponentFocusFastAdjustError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise ComponentFocusFastAdjustError(f"{label} must be finite")
    return result


def _parameters(campaign: dict[str, Any]) -> dict[str, float]:
    point = campaign["operating_point"]
    return {
        "instance_center_y_mm": _number(point["instance_center_y_mm"], "instance center y"),
        "finite_3d_gain_correction_v": _number(
            point["finite_3d_gain_correction_v"], "finite-3D gain correction",
        ),
    }


def _candidate_campaign(campaign: dict[str, Any], parameters: dict[str, float]) -> dict[str, Any]:
    """Change only runtime placement and voltages; PA geometry remains untouched."""
    profile = _load_geometry_profile(campaign["geometry_profile_id"])
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    ring_count = int(profile["ring_count"])
    center_z = _number(campaign["release_spec"]["geometry"]["center_mm"][2], "release centre z")
    release_position = gap1 + gap2 - center_z
    if not 0.0 < release_position < gap1:
        raise ComponentFocusFastAdjustError("release centre is outside provider first acceleration gap")
    base = campaign["operating_point"]["electrode_voltages_v"]
    drop = _number(base[1], "repeller voltage") - _number(base[2], "grid1 voltage")
    base_correction = _number(
        campaign["operating_point"]["finite_3d_gain_correction_v"], "base finite-3D gain correction",
    )
    theoretical_energy = _number(base[1], "repeller voltage") - drop * release_position / gap1 - base_correction
    correction = _number(parameters["finite_3d_gain_correction_v"], "candidate finite-3D gain correction")
    applied_energy = theoretical_energy + correction
    repeller = applied_energy + drop * release_position / gap1
    grid1 = repeller - drop
    candidate = json.loads(json.dumps(campaign))
    candidate["operating_point"]["instance_center_y_mm"] = _number(
        parameters["instance_center_y_mm"], "candidate instance center y",
    )
    candidate["operating_point"]["finite_3d_gain_correction_v"] = correction
    candidate["operating_point"]["electrode_voltages_v"] = [
        0.0, repeller, grid1, 0.0,
        *(grid1 * index / (ring_count + 1) for index in range(ring_count, 0, -1)),
    ]
    return candidate


def _load_analysis(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComponentFocusFastAdjustError("component-focus analysis is unreadable") from error
    if not isinstance(value, dict) or value.get("role") != "orthogonal_accelerator_component_focus_analysis":
        raise ComponentFocusFastAdjustError("component-focus analysis identity is invalid")
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
        "analysis_sha256": _sha256(path), "residuals": [axial],
        "maximum_normalized_residual": abs(axial) / axial_tolerance,
        "score": max(cohort_slow / slow_tolerance, cohort_axial / axial_tolerance,
                     cohort_transverse / transverse_tolerance),
        "peak_to_peak_t_ns": _number(metrics.get("peak_to_peak_t_ns"), "focus peak-to-peak time"),
        "accepted": accepted, "geometry_acceptable": geometry_acceptable,
        "geometry_diagnostic": geometry_diagnostic,
        "center_axial_energy_passed": abs(axial) <= axial_tolerance,
        "valid": transport_complete,
    }


def _tier(maximum_normalized_residual: float) -> float:
    return next(step for limit, step in _TIERS if maximum_normalized_residual <= limit)


def _scale(campaign: dict[str, Any]) -> float:
    profile = _load_geometry_profile(campaign["geometry_profile_id"])
    base = campaign["operating_point"]["electrode_voltages_v"]
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    release_z = _number(campaign["release_spec"]["geometry"]["center_mm"][2], "release centre z")
    release_position = gap1 + gap2 - release_z
    correction = _number(campaign["operating_point"]["finite_3d_gain_correction_v"], "finite-3D gain correction")
    target = _number(base[1], "repeller voltage") - (_number(base[1], "repeller voltage") - _number(base[2], "grid1 voltage")) * release_position / gap1 - correction
    return abs(target)


def _probe(base: dict[str, float], relative_step: float, scale: float) -> dict[str, float]:
    result = dict(base)
    result["finite_3d_gain_correction_v"] += relative_step * scale
    return result


def _solution(records: list[dict[str, Any]], base_index: int, relative_step: float, scale: float) -> dict[str, float]:
    base, gain_probe = records[base_index:base_index + 2]
    if gain_probe["kind"] != "gain_probe":
        raise ComponentFocusFastAdjustError("real-flight axial-voltage probe is incomplete")
    r0, rg = base["residuals"][0], gain_probe["residuals"][0]
    dg = gain_probe["parameters"]["finite_3d_gain_correction_v"] - base["parameters"]["finite_3d_gain_correction_v"]
    derivative = (rg - r0) / dg
    if abs(derivative) <= 1.0e-12:
        raise ComponentFocusFastAdjustError("real-flight axial-voltage response is singular")
    delta_gain = -r0 / derivative
    trust_gain = relative_step * scale
    delta_gain = max(-trust_gain, min(trust_gain, delta_gain))
    return {
        "instance_center_y_mm": base["parameters"]["instance_center_y_mm"],
        "finite_3d_gain_correction_v": base["parameters"]["finite_3d_gain_correction_v"] + delta_gain,
    }


def initialize(campaign_path: Path, maximum_trials: int) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    if maximum_trials < 4 or maximum_trials > 20:
        raise ComponentFocusFastAdjustError("maximum trials must be between 4 and 20")
    return {
        "schema_version": 1, "role": _ROLE, "status": "running",
        "campaign_sha256": _sha256(campaign_path), "maximum_trials": maximum_trials,
        "records": [], "next_parameters": _parameters(campaign), "phase": "base",
        "base_record_index": None, "probe_relative_step": None, "best_record_index": None,
    }


def record_analysis(state: dict[str, Any], analysis_path: Path, campaign: dict[str, Any]) -> dict[str, Any]:
    if set(state) != _STATE_KEYS or state.get("schema_version") != 1 or state.get("role") != _ROLE:
        raise ComponentFocusFastAdjustError("controller state is invalid")
    if state["status"] != "running" or not isinstance(state["next_parameters"], dict):
        raise ComponentFocusFastAdjustError("controller has no pending candidate")
    record = {"kind": state["phase"], "parameters": state["next_parameters"], **_load_analysis(analysis_path)}
    records = state["records"]
    records.append(record)
    best = state["best_record_index"]
    if record["valid"] and (best is None or record["score"] < records[best]["score"]):
        state["best_record_index"] = len(records) - 1
    if record["accepted"]:
        state["status"], state["next_parameters"] = "accepted", None
        return state
    if not record["geometry_acceptable"] or record["center_axial_energy_passed"]:
        state["status"], state["next_parameters"] = "exhausted", None
        return state
    if len(records) >= state["maximum_trials"]:
        state["status"], state["next_parameters"] = "exhausted", None
        return state
    scale = _scale(campaign)
    if state["phase"] in {"base", "solution"}:
        state["base_record_index"] = len(records) - 1
        state["probe_relative_step"] = _tier(record["maximum_normalized_residual"])
        state["next_parameters"] = _probe(record["parameters"], state["probe_relative_step"], scale)
        state["phase"] = "gain_probe"
    elif state["phase"] == "gain_probe":
        state["next_parameters"] = _solution(records, state["base_record_index"], state["probe_relative_step"], scale)
        state["phase"] = "solution"
    else:
        raise ComponentFocusFastAdjustError("controller phase is invalid")
    return state


def _write_campaign(path: Path, campaign: dict[str, Any], parameters: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_candidate_campaign(campaign, parameters), indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--maximum-trials", type=int)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--candidate-campaign", type=Path)
    parser.add_argument("--selected-campaign", type=Path)
    parser.add_argument("--best-campaign", type=Path)
    args = parser.parse_args()
    try:
        campaign = _load_campaign(args.campaign)
        if args.state.exists():
            state = json.loads(args.state.read_text(encoding="utf-8"))
            if state.get("campaign_sha256") != _sha256(args.campaign):
                raise ComponentFocusFastAdjustError("controller state belongs to a different campaign")
        else:
            if args.maximum_trials is None:
                raise ComponentFocusFastAdjustError("new controller state requires maximum trials")
            state = initialize(args.campaign, args.maximum_trials)
        if args.analysis is not None:
            state = record_analysis(state, args.analysis, campaign)
        if args.candidate_campaign is not None:
            if not isinstance(state.get("next_parameters"), dict):
                raise ComponentFocusFastAdjustError("controller has no pending candidate campaign")
            _write_campaign(args.candidate_campaign, campaign, state["next_parameters"])
        if args.selected_campaign is not None:
            accepted = [record for record in state["records"] if record["accepted"]]
            if state["status"] != "accepted" or len(accepted) != 1:
                raise ComponentFocusFastAdjustError("controller has no accepted campaign")
            _write_campaign(args.selected_campaign, campaign, accepted[0]["parameters"])
        if args.best_campaign is not None:
            index = state.get("best_record_index")
            if not isinstance(index, int):
                raise ComponentFocusFastAdjustError("controller has no evaluated campaign")
            _write_campaign(args.best_campaign, campaign, state["records"][index]["parameters"])
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_FAST_ADJUST=FAIL ERROR={error}")
        return 1
    print(f"ACCELERATOR_COMPONENT_FOCUS_FAST_ADJUST=PASS STATUS={state['status']} TRIALS={len(state['records'])} NEXT={state['next_parameters']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
