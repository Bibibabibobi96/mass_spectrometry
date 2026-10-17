"""Close a measured-source MR flight against its entire upstream mother cohort.

This solver-independent consumer reports recorded detector arrivals and elapsed
handoff times separately. It does not invoke the OA ideal-source analyzer, fit
an undeclared peak model, or grant physical/field/performance qualification.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import shutil
import statistics
from typing import Any

from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.component_particle_state import validate_component_particle_state_csv
from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import FLY_COMPLETED, parse_events


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _identity(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _load_source(path: Path) -> tuple[dict[str, Any], dict[int, dict[str, str]], list[dict[str, str]], Path]:
    receipt = _read(path)
    if (receipt.get("schema_version") != 1 or receipt.get("role") != "mrtof_measured_component_source"
            or receipt.get("status") != "prepared_only" or receipt.get("source_materialization_ready") is not True):
        raise ValueError("Unsupported prepared measured-source receipt")
    for name, record in {**receipt["inputs"], **receipt["outputs"]}.items():
        verify_record(name, record, base_dir=path.parent)
    state_path = record_path(receipt["outputs"]["component_particle_state"], base_dir=path.parent)
    census_path = record_path(receipt["outputs"]["source_census"], base_dir=path.parent)
    validation = validate_component_particle_state_csv(state_path)
    clock_path = record_path(receipt["outputs"]["clock_authority"], base_dir=path.parent)
    clock = validate_clock_authority(clock_path, path.parent)
    epoch_path = record_path(receipt["outputs"]["instrument_epoch"], base_dir=path.parent)
    if (validation["frame_ids"] != [receipt["frame_id"]]
            or validation["clock_epoch_ids"] != [receipt["clock_epoch_id"]]
            or clock["clock_epoch_id"] != receipt["clock_epoch_id"]
            or _read(epoch_path)["instrument_time_us"] != receipt["solver_epoch_instrument_time_us"]):
        raise ValueError("Prepared source clock/frame authority differs")
    states = {int(row["particle_id"]): row for row in _rows(state_path)}
    census = _rows(census_path)
    transferred = {int(row["particle_id"]) for row in census if row["transfer_status"] == "transferred"}
    lost = {int(row["particle_id"]) for row in census if row["transfer_status"] == "not_transferred"}
    counts = {"source": len(census), "transferred": len(states), "not_transferred": len(lost)}
    if (len({int(row["particle_id"]) for row in census}) != len(census)
            or transferred != set(states) or transferred & lost or len(transferred | lost) != len(census)
            or counts != receipt["counts"]):
        raise ValueError("Prepared source complete mother census does not close")
    return receipt, states, census, census_path


def _log_roundoff_us(time_us: float) -> float:
    # mrtof_candidate.lua emits event t_us with %.12g: half its last decimal.
    return 0.5 * 10 ** (math.floor(math.log10(abs(time_us))) - 11) if time_us else 0.0


def _close_events(text: str, states: dict[int, dict[str, str]]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    events = parse_events(text)
    completed = list(FLY_COMPLETED.finditer(text))
    if not completed or sum(int(match["splats"]) for match in completed) != len(states):
        raise ValueError("Fly completion count differs from transferred source")
    terminals, detectors, splats = {}, {}, {}
    for event in events:
        particle = int(event["ion"])
        if particle not in states:
            raise ValueError(f"Unknown downstream particle ID: {particle}")
        time = float(event["t_us"])
        birth = float(states[particle]["instrument_time_us"])
        if time + _log_roundoff_us(time) < birth:
            raise ValueError(f"Absolute event clock precedes measured handoff: {particle}")
        if particle in terminals:
            raise ValueError(f"Event follows terminal or duplicate terminal: {particle}")
        # Different interpolated plane events may print out of chronological
        # order within one solver step; retain their recorded times unchanged.
        kind = event["kind"]
        target = {"terminal": terminals, "detector": detectors, "splat": splats}.get(kind)
        if target is not None:
            if particle in target:
                raise ValueError(f"Duplicate {kind} for particle: {particle}")
            target[particle] = event
    if set(terminals) != set(states):
        raise ValueError(f"Missing downstream terminal IDs: {sorted(set(states)-set(terminals))}")
    for particle, terminal in terminals.items():
        code = int(terminal["splat"])
        if particle in splats and int(splats[particle]["code"]) != code:
            raise ValueError(f"Splat and terminal codes conflict: {particle}")
        if (particle in detectors) != (code == 1):
            raise ValueError(f"Detector and terminal codes conflict: {particle}")
    return events, terminals, detectors


def _statistics(values: list[float], basis: str) -> dict[str, Any]:
    return {"time_basis": basis, "unit": "us", "count": len(values),
            "mean": statistics.fmean(values) if values else None,
            "population_sigma": statistics.pstdev(values) if len(values) >= 2 else None,
            "minimum": min(values) if values else None, "maximum": max(values) if values else None,
            "range": max(values)-min(values) if len(values) >= 2 else None,
            "width_status": "observed_population_sigma_and_range" if len(values) >= 2 else "unavailable_fewer_than_two_hits",
            "fwhm": None, "resolution": None, "peak_status": "unavailable_no_declared_peak_analysis_contract"}


def _population_rows(census: list[dict[str, str]], states: dict[int, dict[str, str]],
                     terminals: dict[int, dict[str, Any]], detectors: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for original in census:
        particle = int(original["particle_id"])
        row = {"particle_id": particle, "upstream_transfer_status": original["transfer_status"],
               "upstream_terminal_reason": original["terminal_reason"],
               "upstream_terminal_instrument_time_us": original["instrument_time_us"],
               "handoff_instrument_time_us": "", "downstream_status": "not_transferred",
               "downstream_terminal_splat": "", "downstream_terminal_instrument_time_us": "",
               "detector_arrival_instrument_time_us": "", "detector_time_since_handoff_us": ""}
        for axis in "xyz":
            row[f"terminal_position_{axis}_mm"] = ""
            row[f"terminal_velocity_{axis}_m_s"] = ""
        if particle in states:
            handoff = float(states[particle]["instrument_time_us"])
            terminal = terminals[particle]
            code = int(terminal["splat"])
            row.update(handoff_instrument_time_us=handoff,
                       downstream_status="detected" if particle in detectors else ("timeout" if code == 2 else "loss"),
                       downstream_terminal_splat=code, downstream_terminal_instrument_time_us=terminal["t_us"])
            for axis in "xyz":
                row[f"terminal_position_{axis}_mm"] = terminal[f"{axis}_mm"]
                row[f"terminal_velocity_{axis}_m_s"] = terminal[f"v{axis}_mm_us"] * 1000
            if particle in detectors:
                arrival = float(detectors[particle]["t_us"])
                row.update(detector_arrival_instrument_time_us=arrival,
                           detector_time_since_handoff_us=arrival-handoff)
        result.append(row)
    return result


def analyze_measured_component(log_path: Path, source_receipt_path: Path, output_directory: Path) -> dict[str, Any]:
    """Publish complete per-ID census and observed timing from absolute-time logs.

    Source receipt is the authority for original IDs, initial 6D, clock and full
    mother census. Invalid/duplicate/unknown/missing lifecycles fail before any
    output. No solver, GUI, propagation or undeclared peak fitting is performed.
    """
    if output_directory.exists():
        raise FileExistsError(f"Refusing to overwrite measured analysis: {output_directory}")
    receipt, states, census, census_path = _load_source(source_receipt_path)
    events, terminals, detectors = _close_events(log_path.read_text(encoding="utf-8-sig"), states)
    rows = _population_rows(census, states, terminals, detectors)
    counts = {"mother_source": len(census), "upstream_not_transferred": receipt["counts"]["not_transferred"],
              "downstream_released": len(states), "detected": len(detectors),
              "downstream_timeout": sum(row["downstream_status"] == "timeout" for row in rows),
              "downstream_loss": sum(row["downstream_status"] == "loss" for row in rows)}
    arrivals = [float(event["t_us"]) for event in detectors.values()]
    elapsed = [float(event["t_us"])-float(states[particle]["instrument_time_us"]) for particle, event in detectors.items()]
    output_directory.mkdir(parents=True)
    shutil.copyfile(census_path, output_directory / "upstream_source_census.csv")
    with (output_directory / "particle_census.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _write(output_directory / "parsed_events.json", events)
    report = {"schema_version": 1, "role": "mrtof_measured_component_analysis", "status": "population_closed",
              "qualification": "recorded_lifecycle_and_timing_only", "physical_performance_pass": None,
              "counts": counts, "clock_epoch_id": receipt["clock_epoch_id"], "frame_id": receipt["frame_id"],
              "detected_fraction_of_mother": len(detectors)/len(census),
              "detected_fraction_of_handoff": len(detectors)/len(states),
              "absolute_arrival": _statistics(arrivals, "canonical_absolute_instrument_time_us"),
              "elapsed_since_handoff": _statistics(elapsed, "per_particle_elapsed_since_measured_handoff_diagnostic_only"),
              "peak_time_policy": "Use common absolute arrival axis for packet width; never subtract individual handoff times for peak analysis.",
              "plot_consumer": "particle_census.csv and parsed_events.json retain original IDs/absolute times for existing MR diagnostic plotting; no OA ideal-source receipt is fabricated.",
              "inputs": {"log": _identity(log_path), "source_receipt": _identity(source_receipt_path)},
              "outputs": {path.stem: _identity(path) for path in sorted(output_directory.iterdir())}}
    _write(output_directory / "analysis_receipt.json", report)
    return report
