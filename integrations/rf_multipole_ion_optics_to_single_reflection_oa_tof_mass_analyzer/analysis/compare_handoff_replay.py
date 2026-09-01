"""Compare a continuous SIMION pulse trace with a restart replay at that pulse.

The comparison is intentionally diagnostic-only.  It does not create a run or
qualify a restart as an interchangeable full mother-cohort result.  Its input
identity is the producer particle ID, which is preserved through each
run-local ``single_flight_particle_row_map.csv``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import (
    DETECTOR_PATTERN,
    NON_DETECTOR_SPLAT_PATTERN,
    PULSE_STATE_PATTERN,
    STATE_PATTERN,
)


STATE_COLUMNS = (
    "particle_id", "instrument_time_us", "mass_amu", "charge_state", "position_x_mm", "position_y_mm",
    "position_z_mm", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s",
    "kinetic_energy_eV",
)
ROW_MAP_COLUMNS = ("simulation_particle_id", "source_particle_id")
TOLERANCE_KEYS = (
    "position_rowwise_abs_tolerance_mm", "velocity_rowwise_abs_tolerance_m_per_s",
    "clock_abs_tolerance_us", "energy_abs_tolerance_eV",
)
BATCH_LOG_PATTERN = re.compile(r"simion__batch(?P<index>\d+)\.stdout\.log$")


def _read_csv(path: Path, expected_columns: Sequence[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(expected_columns):
            raise ValueError(f"CSV columns differ: {path}")
        return list(reader)


def _read_row_map(path: Path) -> dict[int, int]:
    rows = _read_csv(path, ROW_MAP_COLUMNS)
    mapping: dict[int, int] = {}
    for row in rows:
        simulation_id = int(row["simulation_particle_id"])
        source_id = int(row["source_particle_id"])
        if simulation_id < 1 or source_id < 1 or simulation_id in mapping:
            raise ValueError(f"particle row map is invalid: {path}")
        mapping[simulation_id] = source_id
    if not mapping:
        raise ValueError(f"particle row map is empty: {path}")
    if sorted(mapping) != list(range(1, len(mapping) + 1)):
        raise ValueError(f"particle row map IDs are not contiguous: {path}")
    return mapping


def _read_restart_state(path: Path) -> dict[int, dict[str, float]]:
    rows = _read_csv(path, STATE_COLUMNS)
    state: dict[int, dict[str, float]] = {}
    for row in rows:
        particle_id = int(row["particle_id"])
        values = {name: float(row[name]) for name in STATE_COLUMNS if name != "particle_id"}
        if particle_id < 1 or particle_id in state or not all(math.isfinite(value) for value in values.values()):
            raise ValueError(f"restart state is invalid: {path}")
        state[particle_id] = values
    if not state:
        raise ValueError(f"restart state is empty: {path}")
    return state


def _read_tolerances(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("role") != "canonical_pulse_restart_target_state_validation":
        raise ValueError("restart validation role differs")
    source = data.get("tolerances")
    if not isinstance(source, dict):
        raise ValueError("restart validation tolerances are missing")
    tolerances = {key: float(source[key]) for key in TOLERANCE_KEYS}
    if any(not math.isfinite(value) or value < 0 for value in tolerances.values()):
        raise ValueError("restart validation tolerances are invalid")
    return tolerances


def _read_batch_plan(path: Path) -> dict[int, dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("role") != "simion_single_wave_particle_batch_plan":
        raise ValueError("SIMION batch plan role differs")
    batches = data.get("batches")
    if not isinstance(batches, list) or not batches:
        raise ValueError("SIMION batch plan batches are missing")
    result: dict[int, dict[str, int]] = {}
    for batch in batches:
        if not isinstance(batch, dict):
            raise ValueError("SIMION batch plan batch is invalid")
        values = {key: int(batch[key]) for key in ("index", "count", "particle_id_min", "particle_id_max", "simion_particle_id_offset")}
        if (values["index"] < 1 or values["count"] < 1 or values["particle_id_min"] != values["simion_particle_id_offset"] + 1 or values["particle_id_max"] != values["simion_particle_id_offset"] + values["count"] or values["index"] in result):
            raise ValueError("SIMION batch plan batch is invalid")
        result[values["index"]] = values
    if sorted(result) != list(range(1, len(result) + 1)):
        raise ValueError("SIMION batch plan indices are not contiguous")
    return result


def _parse_one_batch(path: Path) -> tuple[dict[int, float], dict[int, dict[str, dict[str, float] | int]], dict[int, str]]:
    """Parse one stdout log, where SIMION ion numbering is batch-local."""
    pulse_time_by_ion: dict[int, float] = {}
    states_by_ion: dict[int, dict[str, dict[str, float] | int]] = {}
    terminal_by_ion: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        pulse = PULSE_STATE_PATTERN.search(line)
        if pulse:
            ion = int(pulse.group("ion"))
            if ion in pulse_time_by_ion:
                raise ValueError(f"duplicate pulse TRACE for SIMION ion {ion} in {path}")
            pulse_time_by_ion[ion] = float(pulse.group("t"))
            continue
        state = STATE_PATTERN.search(line)
        if state and state.group("event") in {"pre_pulse_state", "source_release"}:
            ion = int(state.group("ion"))
            event = state.group("event")
            records = states_by_ion.setdefault(ion, {})
            if event in records:
                raise ValueError(f"duplicate {event} TRACE for SIMION ion {ion} in {path}")
            records[event] = {name: float(state.group(name)) for name in ("t", "x", "y", "z", "vx", "vy", "vz")}
            if state.group("particle_id") is not None:
                records["particle_id"] = int(state.group("particle_id"))
            continue
        detector = DETECTOR_PATTERN.search(line)
        if detector:
            ion = int(detector.group("ion"))
            category = "detector_crossing"
        else:
            splat = NON_DETECTOR_SPLAT_PATTERN.search(line)
            if not splat:
                continue
            ion = int(splat.group("ion"))
            category = f"non_detector_splat_instance_{int(splat.group('instance'))}"
        if ion in terminal_by_ion:
            raise ValueError(f"duplicate terminal TRACE for SIMION ion {ion} in {path}")
        terminal_by_ion[ion] = category
    return pulse_time_by_ion, states_by_ion, terminal_by_ion


def _parse_traces(
    paths: Iterable[Path], simulation_to_producer: dict[int, int],
    batch_plan: dict[int, dict[str, int]], *, clock_tolerance_us: float,
) -> tuple[dict[int, dict[str, float]], dict[int, str]]:
    """Map each batch-local SIMION ion number through its ordered row-map slice."""
    pulse_by_producer: dict[int, dict[str, float]] = {}
    terminal_by_producer: dict[int, str] = {}
    seen_batch_indices: set[int] = set()
    for path in paths:
        match = BATCH_LOG_PATTERN.search(path.name)
        if not match or int(match.group("index")) not in batch_plan:
            raise ValueError(f"TRACE path does not identify a declared SIMION batch: {path}")
        batch_index = int(match.group("index"))
        if batch_index in seen_batch_indices:
            raise ValueError(f"duplicate SIMION batch TRACE: {path}")
        seen_batch_indices.add(batch_index)
        plan = batch_plan[batch_index]
        pulse_time_by_ion, states_by_ion, terminal_by_ion = _parse_one_batch(path)
        batch_ions = sorted(pulse_time_by_ion)
        if any(ion < 1 or ion > plan["count"] for ion in batch_ions):
            raise ValueError(f"batch pulse TRACE ion ID is outside its declared batch: {path}")
        if not set(pulse_time_by_ion).issubset(terminal_by_ion):
            raise ValueError(f"batch pulse survivor lacks a terminal TRACE: {path}")
        for ion in batch_ions:
            simulation_id = plan["simion_particle_id_offset"] + ion
            if simulation_id not in simulation_to_producer:
                raise ValueError("batch TRACE particle is absent from frozen particle row map")
            records = states_by_ion.get(ion, {})
            state = records.get("pre_pulse_state") or records.get("source_release")
            if not isinstance(state, dict):
                raise ValueError(f"batch lacks a pulse-epoch state TRACE for SIMION ion {ion}: {path}")
            logged_particle_id = records.get("particle_id")
            if logged_particle_id is not None and logged_particle_id != simulation_id:
                raise ValueError(f"source-release particle ID differs from batch plan: {path}")
            if abs(state["t"] - pulse_time_by_ion[ion]) > clock_tolerance_us:
                raise ValueError(f"pulse-epoch state clock differs from handoff pulse TRACE: {path}")
            producer_id = simulation_to_producer[simulation_id]
            if producer_id in pulse_by_producer:
                raise ValueError("producer particle ID appears in multiple batches")
            pulse_by_producer[producer_id] = state
            terminal_by_producer[producer_id] = terminal_by_ion[ion]
    if seen_batch_indices != set(batch_plan):
        raise ValueError("batch TRACE rows do not cover frozen particle row map")
    return pulse_by_producer, terminal_by_producer


def _failure(reason: str, **details: Any) -> dict[str, Any]:
    return {"schema_version": 1, "role": "rf_oatof_handoff_replay_comparison", "status": "FAIL", "reason": reason, **details}


def _state_errors(actual: dict[str, float], expected: dict[str, float]) -> dict[str, float]:
    return {
        "position_mm": max(abs(actual[axis] - expected[f"position_{axis}_mm"]) for axis in "xyz"),
        "velocity_m_per_s": max(abs(1000.0 * actual[f"v{axis}"] - expected[f"velocity_{axis}_m_s"]) for axis in "xyz"),
        "clock_us": abs(actual["t"] - expected["instrument_time_us"]),
        "energy_eV": abs(
            kinetic_energy_ev(
                expected["mass_amu"],
                *(1000.0 * actual[f"v{axis}"] for axis in "xyz"),
            ) - expected["kinetic_energy_eV"]
        ),
    }


def _maximum_errors(records: Iterable[dict[str, float]]) -> dict[str, float]:
    return {key: max((record[key] for record in records), default=0.0) for key in ("position_mm", "velocity_m_per_s", "clock_us", "energy_eV")}


def _within_tolerances(errors: dict[str, float], tolerances: dict[str, float]) -> bool:
    return (
        errors["position_mm"] <= tolerances["position_rowwise_abs_tolerance_mm"]
        and errors["velocity_m_per_s"] <= tolerances["velocity_rowwise_abs_tolerance_m_per_s"]
        and errors["clock_us"] <= tolerances["clock_abs_tolerance_us"]
        and errors["energy_eV"] <= tolerances["energy_abs_tolerance_eV"]
    )


def compare(
    continuous_trace_paths: Sequence[Path],
    continuous_row_map_path: Path,
    continuous_batch_plan_path: Path,
    restart_trace_paths: Sequence[Path],
    restart_state_path: Path,
    restart_row_map_path: Path,
    restart_batch_plan_path: Path,
    restart_validation_path: Path,
) -> dict[str, Any]:
    """Return a PASS/FAIL replay comparison without altering either source run."""
    try:
        continuous_map = _read_row_map(continuous_row_map_path)
        restart_map = _read_row_map(restart_row_map_path)
        restart_state = _read_restart_state(restart_state_path)
        tolerances = _read_tolerances(restart_validation_path)
        continuous_batch_plan = _read_batch_plan(continuous_batch_plan_path)
        restart_batch_plan = _read_batch_plan(restart_batch_plan_path)
        if set(restart_map) != set(restart_state):
            return _failure("restart_state_and_row_map_particle_sets_differ")
        continuous_pulse, continuous_terminal = _parse_traces(continuous_trace_paths, continuous_map, continuous_batch_plan, clock_tolerance_us=tolerances["clock_abs_tolerance_us"])
        restart_pulse, restart_terminal = _parse_traces(restart_trace_paths, restart_map, restart_batch_plan, clock_tolerance_us=tolerances["clock_abs_tolerance_us"])
        expected_producer_ids = {restart_map[particle_id] for particle_id in restart_state}
        if set(restart_pulse) != expected_producer_ids:
            return _failure("restart_pulse_trace_particle_set_differs_from_restart_state")
        continuous_by_producer = {producer_id: state for producer_id, state in continuous_pulse.items() if producer_id in expected_producer_ids}
        restart_by_producer = restart_pulse
        if set(continuous_by_producer) != expected_producer_ids:
            return _failure("continuous_pulse_trace_does_not_cover_restart_producer_set", expected_producer_count=len(expected_producer_ids), observed_producer_count=len(continuous_by_producer))
        if set(restart_by_producer) != expected_producer_ids:
            return _failure("restart_pulse_trace_does_not_cover_restart_producer_set", expected_producer_count=len(expected_producer_ids), observed_producer_count=len(restart_by_producer))
        continuous_clock = {state["t"] for state in continuous_by_producer.values()}
        restart_clock = {state["t"] for state in restart_by_producer.values()}
        if len(continuous_clock) != 1 or len(restart_clock) != 1:
            return _failure("pulse_trace_clock_is_not_single_valued")
        continuous_time = next(iter(continuous_clock))
        restart_time = next(iter(restart_clock))
        if abs(continuous_time - restart_time) > tolerances["clock_abs_tolerance_us"]:
            return _failure("continuous_and_restart_pulse_clocks_differ", continuous_pulse_time_us=continuous_time, restart_pulse_time_us=restart_time)

        restart_terminal_by_producer = restart_terminal
        continuous_terminal_by_producer = {producer_id: category for producer_id, category in continuous_terminal.items() if producer_id in expected_producer_ids}
        if set(continuous_terminal_by_producer) != expected_producer_ids or set(restart_terminal_by_producer) != expected_producer_ids:
            return _failure("terminal_trace_particle_set_does_not_cover_paired_producers", expected_producer_count=len(expected_producer_ids), continuous_terminal_count=len(continuous_terminal_by_producer), restart_terminal_count=len(restart_terminal_by_producer))

        continuous_errors: list[dict[str, float]] = []
        restart_errors: list[dict[str, float]] = []
        terminal_mismatches: list[int] = []
        for restart_id, producer_id in restart_map.items():
            expected = restart_state[restart_id]
            continuous_errors.append(_state_errors(continuous_by_producer[producer_id], expected))
            restart_errors.append(_state_errors(restart_by_producer[producer_id], expected))
            if continuous_terminal_by_producer[producer_id] != restart_terminal_by_producer[producer_id]:
                terminal_mismatches.append(producer_id)
        continuous_maximum_errors = _maximum_errors(continuous_errors)
        restart_maximum_errors = _maximum_errors(restart_errors)
        state_pass = _within_tolerances(continuous_maximum_errors, tolerances) and _within_tolerances(restart_maximum_errors, tolerances)
        return {
            "schema_version": 1,
            "role": "rf_oatof_handoff_replay_comparison",
            "status": "PASS" if state_pass and not terminal_mismatches else "FAIL",
            "paired_identity": "producer_particle_id",
            "paired_producer_particle_count": len(expected_producer_ids),
            "pulse_time_us": continuous_time,
            "restart_validation_contract": {
                "path": str(restart_validation_path),
                "tolerances": tolerances,
            },
            "maximum_errors": {
                "continuous_trace_vs_restart_state": continuous_maximum_errors,
                "restart_trace_vs_restart_state": restart_maximum_errors,
            },
            "terminal_category_mismatch_producer_particle_ids": terminal_mismatches,
            "terminal_category_match": not terminal_mismatches,
            "limitations": ["This diagnostic compares only the restart-selected producer IDs; it does not turn a conditional restart into a complete-mother-cohort result."],
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _failure("invalid_comparison_input", detail=str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuous-trace", action="append", required=True, type=Path)
    parser.add_argument("--continuous-particle-row-map", required=True, type=Path)
    parser.add_argument("--continuous-batch-plan", required=True, type=Path)
    parser.add_argument("--restart-trace", action="append", required=True, type=Path)
    parser.add_argument("--restart-state", required=True, type=Path)
    parser.add_argument("--restart-particle-row-map", required=True, type=Path)
    parser.add_argument("--restart-batch-plan", required=True, type=Path)
    parser.add_argument("--restart-validation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.continuous_trace, args.continuous_particle_row_map, args.continuous_batch_plan, args.restart_trace, args.restart_state, args.restart_particle_row_map, args.restart_batch_plan, args.restart_validation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"HANDOFF_REPLAY_COMPARISON={result['status']} OUTPUT={args.output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
