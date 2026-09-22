"""Compare three completed single-centre SIMION trajectory-step runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    parse_events,
)

_PROJECT = "parallel_mirror_dual_stripe_mr_tof"
_MODE = "finite_3d_two_prism_voltage_trial"
_EVENTS = ("drift_phase_return", "return_positive_mirror_turn", "detector")
_STATE_FIELDS = ("t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
_IDENTITY_INPUTS = (
    "geometry_run_manifest", "mirror_run_manifest", "stripe_run_manifest",
    "accelerator_run_manifest", "accelerator_pulse_schedule",
    "trajectory_numerics_contract", "flight_program", "mirror_cycle_counter", "voltage_map",
    "native_corridor_bank_run_manifest", "native_corridor_bank_publication",
    "native_corridor_runtime_receipt", "native_system_runtime_bundle",
    "native_global_fallback_pa", "read_only_accelerator_pa", "read_only_detector_pa",
    "frozen_source_fly2",
)
_IDENTITY_TRIAL_FIELDS = (
    "flight_scope", "selected_axial_energy_per_charge_v",
    "source_slow_kinetic_energy_per_charge_v", "source_position_project_mm",
    "source_direction_project", "source_particle_count", "source_time_of_birth_us",
    "source_clock_basis", "source_expected_particle_ids", "source_selection",
    "particle_mass_th", "charge_state", "mirror_voltages_v", "stripe_biases_v",
    "prism_voltages_v", "accelerator_endpoint_voltages_v", "accelerator_ring_voltages_v",
    "analyzer_electrode_voltages_v", "detector_box_mm", "drift_phase_contract",
    "detector_return_policy_authority", "target_drift_period_ratio",
    "target_half_oscillation_count", "runtime_fast_adjust_enable",
    "accelerator_instance", "accelerator_pulse",
)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be finite") from error
    if not math.isfinite(number):
        raise CandidateContractError(f"{label} must be finite")
    return number


def _manifest_record(manifest: dict[str, Any], path: Path, label: str) -> dict[str, Any]:
    resolved = path.resolve()
    records = [
        record for record in manifest.get("outputs", [])
        if isinstance(record, dict)
        and isinstance(record.get("path"), str)
        and Path(record["path"]).resolve() == resolved
    ]
    if len(records) != 1:
        raise CandidateContractError(f"{label} is not uniquely bound by the run manifest")
    record = records[0]
    if (
        not path.is_file()
        or path.stat().st_size != int(record.get("bytes", -1))
        or _sha256(path).lower() != str(record.get("sha256", "")).lower()
    ):
        raise CandidateContractError(f"{label} differs from its run-manifest record")
    return record


def _input_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("run manifest has no input bindings")
    identity: dict[str, Any] = {}
    for name in _IDENTITY_INPUTS:
        record = inputs.get(name)
        if record is None and name == "accelerator_pulse_schedule":
            identity[name] = None
            continue
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            raise CandidateContractError(f"run manifest lacks input identity: {name}")
        identity[name] = {
            "bytes": int(record.get("bytes", -1)),
            "sha256": record["sha256"].lower(),
        }
    return identity


def _one_event(events: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    selected = [event for event in events if event["kind"] == kind and int(event["ion"]) == 1]
    if len(selected) != 1:
        raise CandidateContractError(f"single-centre log requires exactly one ion-1 {kind} event")
    return selected[0]


def _event_state(event: dict[str, Any], label: str) -> dict[str, float]:
    return {field: _finite(event.get(field), f"{label} {field}") for field in _STATE_FIELDS}


def _read_run(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "run_manifest.json"
    config_path = run_dir / "run_config.json"
    summary_path = run_dir / "summary.json"
    trial_path = run_dir / "results" / "two_prism_trial_materialization.json"
    observation_path = run_dir / "results" / "two_prism_trial_observation.json"
    log_path = run_dir / "logs" / "native_two_prism_flight.log"
    manifest = _load_object(manifest_path, "run manifest")
    if (
        manifest.get("project") != _PROJECT
        or manifest.get("mode") != _MODE
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("each convergence input must be a successful MR-TOF trial")
    config = _load_object(config_path, "run config")
    summary = _load_object(summary_path, "run summary")
    trial = _load_object(trial_path, "trial materialization")
    observation = _load_object(observation_path, "trial observation")
    for path, label in (
        (summary_path, "run summary"), (trial_path, "trial materialization"),
        (observation_path, "trial observation"), (log_path, "native flight log"),
    ):
        _manifest_record(manifest, path, label)
    if (
        summary.get("status") != "success"
        or trial.get("status") != "materialized"
        or trial.get("source_particle_count") != 1
        or trial.get("source_expected_particle_ids") != [1]
        or trial.get("source_selection") is not None
        or observation.get("status") != "full_drift_observed"
    ):
        raise CandidateContractError("convergence input is not a completed unselected single-centre flight")
    diagnostic = observation.get("static_return_diagnostic")
    if (
        not isinstance(diagnostic, dict)
        or diagnostic.get("status") != "detector_hit"
        or diagnostic.get("event_contract_ok") is not True
        or diagnostic.get("errors") != []
        or diagnostic.get("required_event_order")
        != ["drift_phase_return", "return_p2_entry", "return_p2_pass",
            "return_positive_mirror_turn", "detector"]
    ):
        raise CandidateContractError("single-centre run does not prove the current natural-return topology")
    profile = trial.get("trajectory_profile")
    if not isinstance(profile, dict):
        raise CandidateContractError("trial materialization lacks its trajectory profile")
    maximum_step_us = _finite(profile.get("maximum_step_us"), "maximum trajectory step")
    if maximum_step_us <= 0:
        raise CandidateContractError("maximum trajectory step must be positive")
    events = parse_events(log_path.read_text(encoding="utf-8"))
    phase = _one_event(events, "drift_phase_return")
    positive_turn = _one_event(events, "return_positive_mirror_turn")
    detector = _one_event(events, "detector")
    terminal = _one_event(events, "terminal")
    if not (
        _finite(phase.get("t_us"), "phase time")
        < _finite(positive_turn.get("t_us"), "positive-turn time")
        < _finite(detector.get("t_us"), "detector time")
    ):
        raise CandidateContractError("natural-return event order is invalid")
    detector_state = _event_state(terminal, "detector terminal")
    detector_time = _finite(detector.get("t_us"), "detector t_us")
    if abs(detector_state["t_us"] - detector_time) > maximum_step_us:
        raise CandidateContractError("detector and terminal times differ by more than one step")
    for coordinate, velocity in (("x_mm", "vx_mm_us"), ("y_mm", "vy_mm_us"),
                                 ("z_mm", "vz_mm_us")):
        displacement_bound = abs(detector_state[velocity]) * maximum_step_us + 1e-9
        if abs(detector_state[coordinate] - _finite(
            detector.get(coordinate), f"detector {coordinate}",
        )) > displacement_bound:
            raise CandidateContractError("detector and terminal positions exceed one-step motion")
    if int(terminal.get("splat", 0)) != 1 or detector_state["vz_mm_us"] >= 0:
        raise CandidateContractError("detector terminal is not the required z-negative programmatic hit")
    trial_identity = {name: trial.get(name) for name in _IDENTITY_TRIAL_FIELDS}
    parameters = config.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("flight_scope") != trial["flight_scope"]:
        raise CandidateContractError("run config and trial flight scope differ")
    return {
        "run_id": str(manifest.get("run_id")),
        "run_dir": str(run_dir),
        "maximum_step_us": maximum_step_us,
        "trajectory_profile": profile,
        "identity": {"inputs": _input_identity(manifest), "trial": trial_identity},
        "events": {
            "drift_phase_return": _event_state(phase, "drift phase return"),
            "return_positive_mirror_turn": _event_state(positive_turn, "return positive mirror turn"),
            "detector": detector_state,
        },
        "event_provenance": {"detector_velocity_source": "terminal_matched_to_detector"},
        "evidence": {
            "manifest_sha256": _sha256(manifest_path),
            "summary_sha256": _sha256(summary_path),
            "native_log_sha256": _sha256(log_path),
            "trial_receipt_sha256": _sha256(trial_path),
            "observation_sha256": _sha256(observation_path),
        },
    }


def _event_difference(coarser: dict[str, float], finer: dict[str, float]) -> dict[str, Any]:
    signed = {field: finer[field] - coarser[field] for field in _STATE_FIELDS}
    return {"finer_minus_coarser": signed, "absolute_difference": {
        field: abs(value) for field, value in signed.items()
    }}


def analyze_timestep_convergence(run_dirs: list[Path]) -> dict[str, Any]:
    if len(run_dirs) != 3:
        raise CandidateContractError("trajectory-step convergence requires exactly three runs")
    levels = [_read_run(path) for path in run_dirs]
    if len({item["run_id"] for item in levels}) != 3:
        raise CandidateContractError("trajectory-step convergence requires three distinct runs")
    reference_identity = levels[0]["identity"]
    if any(item["identity"] != reference_identity for item in levels[1:]):
        raise CandidateContractError(
            "geometry, PA, voltage, source, program, pulse, or topology identity differs across runs"
        )
    levels.sort(key=lambda item: item["maximum_step_us"], reverse=True)
    steps = [item["maximum_step_us"] for item in levels]
    if not steps[0] > steps[1] > steps[2]:
        raise CandidateContractError("trajectory-step levels must be distinct and strictly refining")
    adjacent = []
    for coarser, finer in zip(levels, levels[1:]):
        adjacent.append({
            "coarser_run_id": coarser["run_id"], "finer_run_id": finer["run_id"],
            "coarser_maximum_step_us": coarser["maximum_step_us"],
            "finer_maximum_step_us": finer["maximum_step_us"],
            "refinement_ratio": coarser["maximum_step_us"] / finer["maximum_step_us"],
            "events": {
                name: _event_difference(coarser["events"][name], finer["events"][name])
                for name in _EVENTS
            },
        })
    identity = {
        **reference_identity,
        "canonical_sha256": _canonical_sha256(reference_identity),
    }
    return {
        "schema_version": 1,
        "role": "mrtof_single_center_trajectory_timestep_convergence",
        "status": "candidate_diagnostic",
        "qualification": "three_level_measured_timestep_convergence__acceptance_threshold_not_defined",
        "acceptance_threshold": None,
        "identity": identity,
        "levels": [{key: value for key, value in level.items() if key != "identity"} for level in levels],
        "adjacent_differences": adjacent,
        "interpretation": (
            "Signed and absolute adjacent-level changes are reported without a pass/fail decision. "
            "This is Candidate numerical evidence, not Formal performance qualification."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_timestep_convergence(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("MRTOF_SINGLE_CENTER_TIMESTEP_CONVERGENCE=CANDIDATE_DIAGNOSTIC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
