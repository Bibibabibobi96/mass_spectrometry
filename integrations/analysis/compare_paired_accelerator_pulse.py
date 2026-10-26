"""Diagnose paired OA pulse trajectories in mm, m/s and absolute instrument us.

Consumes canonical CSV exports, never solver models. Missing later states and
missed observation times remain explicit; no physical equivalence is inferred.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.verify_run_manifest import record_path
from integrations.runtime.single_flight_source import binary64_serialization_close


FIELDS = ("x_mm", "y_mm", "z_mm", "vx_m_per_s", "vy_m_per_s", "vz_m_per_s")
SOURCE_COLUMNS = ("particle_id", "mass_amu", "charge_state", *FIELDS, "kinetic_energy_eV")
COMSOL_COLUMNS = ("particle_id", "native_particle_index", "instrument_time_us", *FIELDS,
                  "state_present", "solver_raw_status", "solver_stop_time_us")
SIMION_COLUMNS = ("particle_id", "native_particle_index", "event", "instrument_time_us", "requested_time_us",
                  *FIELDS, "state_present", "solver_raw_status", "original_birth_time_us", "terminal_reason")


def _rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"CSV columns/units differ from the paired pulse contract: {path}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"CSV row width differs: {path}")
    return rows


def _finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _particle_id(value: str) -> int:
    number = _finite(value, "particle_id")
    if not number.is_integer() or number <= 0:
        raise ValueError("particle_id must be a positive integer")
    return int(number)


def _declared_time(value: str, times: list[float]) -> float:
    actual = _finite(value, "observation time")
    matches = [time for time in times if binary64_serialization_close(actual, time)]
    if len(matches) != 1:
        raise ValueError(f"observation time is not uniquely declared: {value}")
    return matches[0]


def _initial(row: dict[str, str], source: dict[str, str], time: float, label: str) -> None:
    if (row["state_present"] != "1"
            or not binary64_serialization_close(_finite(row["instrument_time_us"], label), time)
            or any(not binary64_serialization_close(_finite(row[field], label), float(source[field]))
                   for field in FIELDS)):
        raise ValueError(f"{label} differs from original source 6D/clock")


def _observations(rows: list[dict[str, str]], source: dict[int, dict[str, str]], plan: dict,
                  *, simion: bool) -> dict[tuple[int, float], dict[str, str]]:
    observations = {}
    initials = {}
    for row in rows:
        pid = _particle_id(row["particle_id"])
        if pid not in source:
            raise ValueError(f"foreign particle_id: {pid}")
        if row["state_present"] not in ("0", "1"):
            raise ValueError("state_present must be 0 or 1; it does not identify an alive particle")
        _finite(row["instrument_time_us"], "instrument time")
        for field in FIELDS:
            float(row[field])  # Later nonfinite states are reported, not discarded.
        if simion:
            birth = _finite(row["original_birth_time_us"], "original birth time")
            if not binary64_serialization_close(birth, plan["original_birth_times_us"][str(pid)]):
                raise ValueError(f"original birth time differs for particle {pid}")
            if row["event"] == "source_state":
                if pid in initials:
                    raise ValueError(f"duplicate initial particle: {pid}")
                _initial(row, source[pid], plan["source_time_us"], "SIMION source_state")
                initials[pid] = row
                continue
            if row["event"] == "terminal":
                continue
            if row["event"] != "observation":
                raise ValueError(f"unknown SIMION event: {row['event']}")
        time = _declared_time(row["requested_time_us"] if simion else row["instrument_time_us"],
                              plan["observation_times_us"])
        key = (pid, time)
        if key in observations:
            raise ValueError(f"duplicate observation key: {key}")
        observations[key] = row
    if simion and set(initials) != set(source):
        raise ValueError("SIMION source_state initial coverage differs")
    for pid, original in source.items():
        row = observations.get((pid, plan["source_time_us"]))
        if row is None:
            raise ValueError(f"missing initial observation for particle {pid}")
        _initial(row, original, plan["source_time_us"], "initial observation")
    return observations


def _availability(row: dict[str, str] | None, time: float) -> str:
    if row is None:
        return "missing_record"
    if not binary64_serialization_close(float(row["instrument_time_us"]), time):
        return "missed_time"
    if row["state_present"] == "0":
        return "missing_state"
    if any(not math.isfinite(float(row[field])) for field in FIELDS):
        return "nonfinite_state"
    return "available"


def compare_paired_accelerator_pulse(plan_path: Path, comsol_csv: Path, simion_csv: Path,
                                   output_dir: Path) -> dict[str, Any]:
    """Write a full outer-paired diagnostic report and differences CSV.

    Original IDs, source 6D and clock must agree or ValueError is raised. Later
    missing/nonfinite states and missed times are diagnostics, never interpolated.
    Input identity guards belong to the execution owner; payloads are read once.
    """
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    if plan["schema_version"] != 1 or plan["role"] != "paired_accelerator_pulse_plan":
        raise ValueError("paired pulse plan identity differs")
    times = [_finite(value, "declared time") for value in plan["observation_times_us"]]
    if (not times or times[0] != plan["source_time_us"]
            or any(right <= left for left, right in zip(times, times[1:]))):
        raise ValueError("declared times must start at the original source and strictly increase")
    source_rows = _rows(record_path(plan["source_csv"], base_dir=plan_path.parent), SOURCE_COLUMNS)
    source = {_particle_id(row["particle_id"]): row for row in source_rows}
    if (not source or len(source) != len(source_rows) or set(source) != set(plan["selected_particle_ids"])
            or len(source) != plan["particle_count"]):
        raise ValueError("source particle IDs/count differ from plan")
    for row in source.values():
        if (float(row["mass_amu"]) != plan["mass_amu"] or float(row["charge_state"]) != plan["charge_state"]):
            raise ValueError("source species differs from plan")
        for field in FIELDS:
            _finite(row[field], f"source {field}")
    comsol = _observations(_rows(comsol_csv, COMSOL_COLUMNS), source, plan, simion=False)
    simion = _observations(_rows(simion_csv, SIMION_COLUMNS), source, plan, simion=True)
    differences = []
    values = {field: [] for field in FIELDS}
    availability = {backend: {state: 0 for state in
                    ("available", "missing_record", "missing_state", "nonfinite_state", "missed_time")}
                    for backend in ("comsol", "simion")}
    for pid in plan["selected_particle_ids"]:
        for time in times:
            rows = {"comsol": comsol.get((pid, time)), "simion": simion.get((pid, time))}
            states = {name: _availability(row, time) for name, row in rows.items()}
            for name, state in states.items():
                availability[name][state] += 1
            for field in FIELDS:
                record = dict(particle_id=pid, requested_time_us=time, field=field,
                              unit="mm" if field.endswith("_mm") else "m/s")
                pair = []
                for name, row in rows.items():
                    record[name + "_availability"] = states[name]
                    for column in ("instrument_time_us", "state_present", "solver_raw_status", "native_particle_index"):
                        record[name + "_" + column] = row[column] if row else ""
                    record[name + "_value"] = row[field] if row else ""
                    pair.append(float(row[field]) if row else math.nan)
                record["comsol_solver_stop_time_us"] = rows["comsol"]["solver_stop_time_us"] if rows["comsol"] else ""
                record["simion_terminal_reason"] = "unknown"  # Observations do not establish a stopping entity.
                paired = (all(rows.values()) and all(row["state_present"] == "1" for row in rows.values())
                          and all(state != "missed_time" for state in states.values())
                          and all(math.isfinite(value) for value in pair))
                delta = pair[1] - pair[0] if paired else None
                record["simion_minus_comsol"] = delta if delta is not None else ""
                if delta is not None:
                    values[field].append(delta)
                differences.append(record)
    metrics = {field: dict(unit="mm" if field.endswith("_mm") else "m/s", finite_pair_count=len(deltas),
                          max_abs=max(map(abs, deltas)) if deltas else None,
                          rms=math.hypot(*deltas) / math.sqrt(len(deltas)) if deltas else None)
               for field, deltas in values.items()}
    output_dir.mkdir(parents=True, exist_ok=True)
    diff_path = output_dir / "paired_pulse_differences.csv"
    with diff_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(differences[0]))
        writer.writeheader()
        writer.writerows(differences)
    report = dict(schema_version=1, role="paired_accelerator_pulse_comparison", status="comparison_complete",
                  qualification="diagnostic_only", units=dict(position="mm", velocity="m/s", time="us"),
                  delta_definition="simion_minus_comsol", particle_count=len(source),
                  expected_observation_pairs=len(source) * len(times), availability=availability, fields=metrics,
                  clock_epoch_id=plan["clock_epoch_id"], instrument_epoch_us=plan["instrument_epoch_us"],
                  source_time_us=plan["source_time_us"], frame_id=plan["frame_id"],
                  original_mother_particle_ids=plan["original_mother_particle_ids"],
                  selected_particle_ids=plan["selected_particle_ids"],
                  original_birth_times_us=plan["original_birth_times_us"],
                  uncontinued_mother_particle_ids=plan["uncontinued_mother_particle_ids"],
                  stop_reason="unknown; state_present is finite-state availability, not survival",
                  differences_csv=str(diff_path.resolve()))
    (output_dir / "paired_pulse_comparison.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report
