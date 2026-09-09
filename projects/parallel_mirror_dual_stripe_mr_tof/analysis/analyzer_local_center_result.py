"""Summarize one static-injection local-replacement center flight."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    FLY_COMPLETED,
    parse_events,
)


EXPECTED_HANDOFFS = {
    "handoff_negative_central_to_bridge__z_plane",
    "handoff_positive_central_to_bridge__z_plane",
    "handoff_negative_bridge_to_mirror__z_plane",
    "handoff_positive_bridge_to_mirror__z_plane",
}


def analyze(log_path: Path, materialization_path: Path) -> dict[str, object]:
    text = log_path.read_text(encoding="utf-8")
    events = parse_events(text)
    materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
    target_k = int(materialization["target_oscillation_count"])
    completion = list(FLY_COMPLETED.finditer(text))
    terminals = [event for event in events if event["kind"] == "terminal"]
    handoffs = [event for event in events if event["kind"] == "patch_interface"]
    transitions = [event for event in events if event["kind"] == "instance_transition"]
    transition_instances = [int(event["instance"]) for event in transitions]
    observed_handoffs = {str(event["name"]) for event in handoffs}
    errors: list[str] = []
    if len(completion) != 1:
        errors.append("fly_completion_count_not_one")
    if len(terminals) != 1 or int(terminals[0]["ion"]) != 1:
        errors.append("single_center_terminal_missing")
    if any(instance < 0 or instance > 8 for instance in transition_instances):
        errors.append("undeclared_instance_selected")
    if 0 in transition_instances:
        errors.append("trajectory_left_all_declared_pa_instances")
    if not {2, 3, 4, 5, 6}.issubset(transition_instances):
        errors.append("not_all_local_replacement_regions_exercised")
    if observed_handoffs != EXPECTED_HANDOFFS:
        errors.append("local_handoff_set_incomplete")
    target_phase = [
        event for event in events
        if event["kind"] == "target_k_phase_sample" and int(event["k"]) == target_k
    ]
    target_return = [
        event for event in events
        if event["kind"] == "target_k" and int(event["k"]) == target_k
    ]
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_local_replacement_center_flight",
        "status": "success" if not errors else "failed",
        "qualification": "single_center_static_injection_local_mesh_check__not_resolution",
        "errors": errors,
        "target_k": target_k,
        "target_k_phase_sample_count": len(target_phase),
        "target_k_return_count": len(target_return),
        "target_k_phase_y_residuals_mm": [float(event["y_mm"]) for event in target_phase],
        "terminal_splat": int(terminals[0]["splat"]) if len(terminals) == 1 else None,
        "terminal_turn_count": int(terminals[0]["turns"]) if len(terminals) == 1 else None,
        "observed_handoffs": sorted(observed_handoffs),
        "handoff_crossing_count": len(handoffs),
        "instance_transition_sequence": transition_instances,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "materialization_sha256": hashlib.sha256(materialization_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--materialization", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.log, args.materialization)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"MRTOF_LOCAL_CENTER_ANALYSIS={'PASS' if result['status'] == 'success' else 'FAIL'}")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
