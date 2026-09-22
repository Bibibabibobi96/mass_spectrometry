"""Bounded, provider-owned voltage search for an existing two-zone PA.

The controller searches only the first-gap voltage drop.  Each candidate
preserves the campaign's final axial energy and derives the complete native
Fast-Adjust table.  It consumes the existing component-focus analysis result;
it does not build, copy, refine, or otherwise mutate a PA family.
"""
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
    """Raised when a bounded component-focus search cannot continue."""


_ROLE = "orthogonal_accelerator_component_focus_fast_adjust_controller"
_STATE_KEYS = {
    "schema_version", "role", "status", "campaign_sha256", "bounds_v",
    "maximum_trials", "records", "next_gap1_voltage_drop_v",
}


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


def _bounds(values: list[object]) -> tuple[float, float]:
    if len(values) != 2:
        raise ComponentFocusFastAdjustError("gap1 voltage-drop bounds require two values")
    lower, upper = (_number(value, "gap1 voltage-drop bound") for value in values)
    if not 0.0 < lower < upper:
        raise ComponentFocusFastAdjustError("gap1 voltage-drop bounds are invalid")
    return lower, upper


def _gap1_drop(campaign: dict[str, Any]) -> float:
    voltages = campaign["operating_point"]["electrode_voltages_v"]
    drop = _number(voltages[1], "repeller voltage") - _number(voltages[2], "grid1 voltage")
    if drop <= 0.0:
        raise ComponentFocusFastAdjustError("campaign first-gap voltage drop must be positive")
    return drop


def _candidate_campaign(campaign: dict[str, Any], drop: float) -> dict[str, Any]:
    """Return one run-local voltage campaign at ``drop`` volts.

    The PA geometry and its plan are deliberately not part of this result.
    The first-zone field changes while the final nominal axial energy is held
    fixed, so candidate flights all use the same published native family.
    """
    profile = _load_geometry_profile(campaign["geometry_profile_id"])
    gap1, gap2 = float(profile["gap_1_mm"]), float(profile["gap_2_mm"])
    center_z = _number(campaign["release_spec"]["geometry"]["center_mm"][2], "release centre z")
    release_position = gap1 + gap2 - center_z
    if not 0.0 < release_position < gap1:
        raise ComponentFocusFastAdjustError("release centre is outside provider first acceleration gap")
    base_drop = _gap1_drop(campaign)
    base = campaign["operating_point"]["electrode_voltages_v"]
    energy = _number(base[1], "repeller voltage") - base_drop * release_position / gap1
    repeller = energy + drop * release_position / gap1
    grid1 = repeller - drop
    candidate = json.loads(json.dumps(campaign))
    candidate["operating_point"]["electrode_voltages_v"] = [
        0.0, repeller, grid1, 0.0,
        *(grid1 * index / 6.0 for index in range(5, 0, -1)),
    ]
    return candidate


def _load_analysis(path: Path) -> tuple[float, bool]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComponentFocusFastAdjustError("component-focus analysis is unreadable") from error
    if not isinstance(value, dict) or value.get("role") != "orthogonal_accelerator_component_focus_analysis":
        raise ComponentFocusFastAdjustError("component-focus analysis identity is invalid")
    metrics, hard_gate = value.get("focus_metrics"), value.get("hard_gate")
    if not isinstance(metrics, dict) or not isinstance(hard_gate, dict):
        raise ComponentFocusFastAdjustError("component-focus analysis lacks focus metrics")
    p2p = _number(metrics.get("peak_to_peak_t_ns"), "focus peak-to-peak time")
    accepted = value.get("status") == "candidate_complete" and hard_gate == {"complete_transport_passed": True}
    return p2p, accepted


def _next_from_records(records: list[dict[str, Any]], lower: float, upper: float) -> float | None:
    """Select one unused bounded point from up to five direct p2p samples."""
    used = {float(record["gap1_voltage_drop_v"]) for record in records}
    if len(records) == 1:
        seed = records[0]["gap1_voltage_drop_v"]
        proposal = seed - (upper - lower) / 10.0
    elif len(records) == 2:
        seed = records[0]["gap1_voltage_drop_v"]
        proposal = seed + (upper - lower) / 10.0
    else:
        ordered = sorted(records, key=lambda record: record["peak_to_peak_t_ns"])
        best = ordered[0]
        by_voltage = sorted(records, key=lambda record: record["gap1_voltage_drop_v"])
        index = by_voltage.index(best)
        left = by_voltage[index - 1] if index else None
        right = by_voltage[index + 1] if index + 1 < len(by_voltage) else None
        if left is not None and right is not None:
            x1, y1 = left["gap1_voltage_drop_v"], left["peak_to_peak_t_ns"]
            x2, y2 = best["gap1_voltage_drop_v"], best["peak_to_peak_t_ns"]
            x3, y3 = right["gap1_voltage_drop_v"], right["peak_to_peak_t_ns"]
            denominator = (x1 - x2) * (x1 - x3) * (x2 - x3)
            vertex = None
            if abs(denominator) > 1.0e-12:
                a = (x3 * (y2 - y1) + x2 * (y1 - y3) + x1 * (y3 - y2)) / denominator
                b = (x3**2 * (y1 - y2) + x2**2 * (y3 - y1) + x1**2 * (y2 - y3)) / denominator
                if a > 0.0:
                    vertex = -b / (2.0 * a)
            proposal = vertex if vertex is not None and left["gap1_voltage_drop_v"] < vertex < right["gap1_voltage_drop_v"] else (left["gap1_voltage_drop_v"] + right["gap1_voltage_drop_v"]) / 2.0
        elif left is not None:
            proposal = (lower + best["gap1_voltage_drop_v"]) / 2.0
        elif right is not None:
            proposal = (best["gap1_voltage_drop_v"] + upper) / 2.0
        else:
            return None
    proposal = min(upper, max(lower, proposal))
    if any(math.isclose(proposal, value, rel_tol=0.0, abs_tol=1.0e-9) for value in used):
        unused = [value for value in (lower, upper) if not any(math.isclose(value, seen, abs_tol=1.0e-9) for seen in used)]
        return unused[0] if unused else None
    return proposal


def initialize(campaign_path: Path, bounds_v: list[object], maximum_trials: int) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    lower, upper = _bounds(bounds_v)
    if maximum_trials < 3 or maximum_trials > 5:
        raise ComponentFocusFastAdjustError("maximum trials must be between 3 and 5")
    seed = _gap1_drop(campaign)
    if not lower <= seed <= upper:
        raise ComponentFocusFastAdjustError("campaign first-gap voltage drop is outside controller bounds")
    return {
        "schema_version": 1, "role": _ROLE, "status": "running",
        "campaign_sha256": _sha256(campaign_path), "bounds_v": [lower, upper],
        "maximum_trials": maximum_trials, "records": [],
        "next_gap1_voltage_drop_v": seed,
    }


def record_analysis(state: dict[str, Any], analysis_path: Path) -> dict[str, Any]:
    if set(state) != _STATE_KEYS or state.get("schema_version") != 1 or state.get("role") != _ROLE:
        raise ComponentFocusFastAdjustError("controller state is invalid")
    if state["status"] != "running" or state["next_gap1_voltage_drop_v"] is None:
        raise ComponentFocusFastAdjustError("controller has no pending candidate")
    p2p, accepted = _load_analysis(analysis_path)
    records = state["records"]
    if not isinstance(records, list) or len(records) >= state["maximum_trials"]:
        raise ComponentFocusFastAdjustError("controller record count is invalid")
    records.append({"gap1_voltage_drop_v": state["next_gap1_voltage_drop_v"], "peak_to_peak_t_ns": p2p,
                    "analysis_sha256": _sha256(analysis_path), "accepted": accepted})
    lower, upper = _bounds(state["bounds_v"])
    if accepted:
        state["status"] = "accepted"
        state["next_gap1_voltage_drop_v"] = None
    elif len(records) == state["maximum_trials"]:
        state["status"] = "exhausted"
        state["next_gap1_voltage_drop_v"] = None
    else:
        candidate = _next_from_records(records, lower, upper)
        if candidate is None:
            state["status"] = "exhausted"
            state["next_gap1_voltage_drop_v"] = None
        else:
            state["next_gap1_voltage_drop_v"] = candidate
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--bounds-v", type=float, nargs=2)
    parser.add_argument("--maximum-trials", type=int)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--candidate-campaign", type=Path)
    parser.add_argument("--selected-campaign", type=Path)
    args = parser.parse_args()
    try:
        if args.state.exists():
            state = json.loads(args.state.read_text(encoding="utf-8"))
            if state.get("campaign_sha256") != _sha256(args.campaign):
                raise ComponentFocusFastAdjustError("controller state belongs to a different campaign")
        else:
            if args.bounds_v is None or args.maximum_trials is None:
                raise ComponentFocusFastAdjustError("new controller state requires bounds and maximum trials")
            state = initialize(args.campaign, args.bounds_v, args.maximum_trials)
        if args.analysis is not None:
            state = record_analysis(state, args.analysis)
        if args.candidate_campaign is not None:
            candidate = state.get("next_gap1_voltage_drop_v")
            if candidate is None:
                raise ComponentFocusFastAdjustError("controller has no pending candidate campaign")
            args.candidate_campaign.parent.mkdir(parents=True, exist_ok=True)
            args.candidate_campaign.write_text(json.dumps(_candidate_campaign(_load_campaign(args.campaign), candidate), indent=2) + "\n", encoding="utf-8")
        if args.selected_campaign is not None:
            accepted = [record for record in state["records"] if record["accepted"]]
            if state["status"] != "accepted" or len(accepted) != 1:
                raise ComponentFocusFastAdjustError("controller has no accepted voltage campaign")
            args.selected_campaign.parent.mkdir(parents=True, exist_ok=True)
            args.selected_campaign.write_text(json.dumps(_candidate_campaign(
                _load_campaign(args.campaign), accepted[0]["gap1_voltage_drop_v"]), indent=2) + "\n", encoding="utf-8")
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_FAST_ADJUST=FAIL ERROR={error}")
        return 1
    print("ACCELERATOR_COMPONENT_FOCUS_FAST_ADJUST=PASS "
          f"STATUS={state['status']} TRIALS={len(state['records'])} "
          f"NEXT={state['next_gap1_voltage_drop_v']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
