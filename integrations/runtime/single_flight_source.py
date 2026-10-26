"""Preserve frozen particle identities, clocks and direct-velocity source projection."""

from __future__ import annotations

import math
import json
import re
from pathlib import Path
from typing import Any, Mapping

from common.contracts.particle_physics import (
    kinetic_energy_ev,
)
from common.contracts.rigid_transform import PhaseSpaceState, RigidTransform


SOURCE_COLUMNS = [
    "particle_id",
    "birth_time_s",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_m_s",
    "vy_m_s",
    "vz_m_s",
    "mass_amu",
    "charge_state",
]


def binary64_serialization_close(a: float, b: float) -> bool:
    """Binary64 serialization allowance, not a physical matching tolerance."""
    return abs(a - b) <= 32 * math.ulp(max(1., abs(a), abs(b)))


_CANONICAL_PRE_PULSE_COLUMNS = {
    "particle_id",
    "event",
    "instrument_time_us",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_mm_per_us",
    "vy_mm_per_us",
    "vz_mm_per_us",
    "kinetic_energy_eV",
}


def select_timed_pre_pulse_states(
    collection: Mapping[str, Any], pulse_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Consume recorded timed states, optionally selecting decision-eligible IDs.

    The caller owns publication and file-identity validation.  This pure
    boundary validates only the already-read scientific records and returns
    the canonical rows in recorded order (or decision ID order), together
    with the full source-release mother IDs and their original birth times.
    ``pulse_time_us`` is the recorded state time for every returned row; it is
    deliberately distinct from ``original_birth_times_us``.
    """
    flight = collection.get("flight")
    pulse = flight.get("pulse") if isinstance(flight, dict) else None
    selection = pulse_decision.get("selection") if isinstance(pulse_decision, Mapping) else None
    selected = selection.get("selected") if isinstance(selection, dict) else None
    particle_ids = selected.get("eligible_ids") if isinstance(selected, dict) else None
    pulse_time = (pulse_decision.get("actual_pulse_time_us") if isinstance(pulse_decision, Mapping)
                  else pulse.get("time_us") if isinstance(pulse, dict) else None)
    execution_cohort_count = selection.get("execution_cohort_count") if isinstance(selection, dict) else None
    if pulse_decision is not None and (not isinstance(pulse_decision, Mapping) or
        pulse_decision.get("schema_version") != 2
        or pulse_decision.get("role")
        != "single_reflection_actual_occupancy_pulse_decision"
        or pulse_decision.get("status") != "success"
        or pulse_decision.get("selection_uses_future_terminal_outcome") is not False
        or not isinstance(selection, dict)
        or selection.get("status") != "selected"
        or selection.get("selected_time_us") != pulse_time
        or not isinstance(particle_ids, list)
        or not particle_ids
        or any(type(value) is not int or value <= 0 for value in particle_ids)
        or len(set(particle_ids)) != len(particle_ids)
        or type(execution_cohort_count) is not int
        or execution_cohort_count < len(particle_ids)
        or type(pulse_time) not in (int, float)
        or not math.isfinite(pulse_time)
    ):
        raise ValueError("frozen winner pulse decision is invalid")
    rows = collection.get("canonical_events")
    if (
        collection.get("schema_version") != 1
        or collection.get("role") != "single_reflection_complete_mother_collection"
        or collection.get("phase") != "full_instrument"
        or collection.get("native_complete") is not True
        or not isinstance(collection.get("clock_epoch_id"), str)
        or not collection["clock_epoch_id"].strip()
        or not isinstance(rows, list)
        or not isinstance(pulse, dict)
        or pulse.get("mode") != "timed"
        or type(pulse.get("time_us")) not in (int, float)
        or type(pulse_time) not in (int, float)
        or not math.isfinite(pulse_time)
        or not binary64_serialization_close(float(pulse["time_us"]), float(pulse_time))
    ):
        raise ValueError("frozen collection is not a complete timed source")
    if any(not isinstance(row, dict) or _CANONICAL_PRE_PULSE_COLUMNS - set(row) for row in rows):
        raise ValueError("canonical collection events are missing required state columns")

    births_by_id: dict[int, float] = {}
    for row in rows:
        if row["event"] != "source_release":
            continue
        particle_id = int(row["particle_id"])
        if particle_id in births_by_id:
            raise ValueError("canonical collection lacks one source_release row per mother particle")
        birth_time = float(row["instrument_time_us"])
        if not math.isfinite(birth_time):
            raise ValueError("canonical event instrument_time_us must be finite")
        births_by_id[particle_id] = birth_time
    mother_ids = list(births_by_id)
    if not mother_ids:
        raise ValueError("canonical collection lacks one source_release row per mother particle")
    if pulse_decision is not None and len(mother_ids) != execution_cohort_count:
        raise ValueError("winner pulse decision execution cohort differs from canonical collection")
    if pulse_decision is None:
        particle_ids = [row["particle_id"] for row in rows if row["event"] == "pre_pulse_state"]
        if not particle_ids or any(type(value) is not int or value <= 0 for value in particle_ids):
            raise ValueError("canonical collection lacks valid recorded pre-pulse particles")
    selected_id_set = set(particle_ids)
    if not selected_id_set <= set(mother_ids):
        raise ValueError("selected timed source is outside the canonical mother cohort")

    selected_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row["event"] != "pre_pulse_state" or int(row["particle_id"]) not in selected_id_set:
            continue
        particle_id = int(row["particle_id"])
        if particle_id in selected_by_id:
            raise ValueError("canonical collection repeats a selected timed source particle")
        selected_by_id[particle_id] = row
    missing = [particle_id for particle_id in particle_ids if particle_id not in selected_by_id]
    if missing:
        raise ValueError("canonical collection lacks a selected timed source pre-pulse particle")
    selected_rows = [selected_by_id[particle_id] for particle_id in particle_ids]
    state_times = {float(row["instrument_time_us"]) for row in selected_rows}
    if any(not math.isfinite(value) for value in state_times):
        raise ValueError("canonical event instrument_time_us must be finite")
    if len(state_times) != 1:
        raise ValueError("selected pre-pulse particles do not share one pulse time")
    state_time = next(iter(state_times))
    if not binary64_serialization_close(state_time, float(pulse_time)):
        raise ValueError("canonical pre-pulse time differs from frozen source pulse time")
    return {
        "clock_epoch_id": collection["clock_epoch_id"],
        "pulse_time_us": state_time,
        "selected_particle_ids": list(particle_ids),
        "selected_rows": selected_rows,
        "mother_particle_ids": sorted(mother_ids),
        "original_birth_times_us": births_by_id,
        "selection_basis": ("detector_blind_pulse_decision_eligible_ids" if pulse_decision is not None
                            else "all_recorded_timed_pre_pulse_states"),
    }


def published_producer_input(
    manifest: Mapping[str, Any], embedded_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Project an embedded identity onto one successful producer's input records.

    Return its unique canonical input path without reading or hashing payloads.
    Historical embedded paths remain provenance, not enduring file locations.
    Callers still verify the selected file and the collection's output binding.
    """
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success":
        raise ValueError("SIMION producer manifest must be a terminal success run")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("SIMION producer manifest lacks input records")
    if (type(embedded_record.get("bytes")) is not int
            or embedded_record["bytes"] < 0
            or not isinstance(embedded_record.get("sha256"), str)
            or len(embedded_record["sha256"]) != 64):
        raise ValueError("embedded producer input lacks a complete file identity")
    matches = {}
    for record in inputs.values():
        if (isinstance(record, dict) and record.get("exists") is True and record.get("path")
                and all(record.get(key) == embedded_record[key] for key in ("bytes", "sha256"))):
            path = Path(record["path"]).resolve()
            matches[path] = {**record, "path": str(path)}
    if len(matches) != 1:
        raise ValueError("producer input identity must bind exactly one canonical path")
    return next(iter(matches.values()))


def require_producer_manifest_binding(
    manifest: Mapping[str, Any], *, geometry_path: Path, geometry_record: Mapping[str, Any],
    collection_path: Path, collection_record: Mapping[str, Any],
    pulse_decision_path: Path | None = None, pulse_decision_record: Mapping[str, Any] | None = None,
    required_input_records: Mapping[Path, Mapping[str, Any]] | None = None,
) -> None:
    """Require one successful producer to publish the exact small scientific inputs.

    This checks only manifest record membership and supplied small-file records.
    Callers own each file's identity verification before this boundary; no
    payloads are read or hashed here.
    """
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success":
        raise ValueError("SIMION producer manifest must be a terminal success run")
    inputs = manifest.get("inputs")
    outputs = manifest.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        raise ValueError("SIMION producer manifest lacks input/output records")

    def matches(record: Any, path: Path, expected: Mapping[str, Any]) -> bool:
        return (
            isinstance(record, dict)
            and record.get("exists") is True
            and record.get("path") is not None
            and Path(record["path"]).resolve() == path.resolve()
            and record.get("bytes") == expected.get("bytes")
            and record.get("sha256") == expected.get("sha256")
        )

    if not any(matches(record, geometry_path, geometry_record) for record in inputs.values()):
        raise ValueError("SIMION producer manifest does not bind the resolved geometry")
    for path, record in (required_input_records or {}).items():
        if not any(matches(candidate, path, record) for candidate in inputs.values()):
            raise ValueError("SIMION producer manifest does not bind a required source input")
    if not any(matches(record, collection_path, collection_record) for record in outputs):
        raise ValueError("SIMION producer manifest does not publish the canonical collection")
    if (pulse_decision_path is None) != (pulse_decision_record is None):
        raise ValueError("pulse decision path and record must be declared together")
    if pulse_decision_path is not None and not any(matches(record, pulse_decision_path, pulse_decision_record) for record in outputs):
        raise ValueError("SIMION producer manifest does not publish the frozen pulse decision")


GLOBAL_COLUMNS = [
    "particle_id",
    "instrument_time_us",
    "mass_amu",
    "charge_state",
    "position_x_mm",
    "position_y_mm",
    "position_z_mm",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "velocity_z_m_s",
    "kinetic_energy_eV",
]


def render_restart_fly2(rows: list[dict[str, str]]) -> str:
    """Render official individual-particle FLY2 direct-velocity definitions."""
    lines = ["particles {", "  coordinates = 0,"]
    for row in rows:
        position = ", ".join(row[f"position_{axis}_mm"] for axis in "xyz")
        velocity = ", ".join(
            format(float(row[f"velocity_{axis}_m_s"]) / 1000.0, ".17g")
            for axis in "xyz"
        )
        lines.append(
            "  standard_beam { tob = 0, mass = "
            + row["mass_amu"] + ", charge = " + row["charge_state"]
            + ", cwf = 1, color = 0, position = vector(" + position
            + "), velocity = vector(" + velocity + ") },"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def transform_source_rows(
    source_rows: list[dict[str, str]],
    transform: RigidTransform,
) -> list[dict[str, str]]:
    """Map parsed source rows once, retaining IDs, species and birth times.

    Positions use Rr+t in mm, velocities use Rv in m/s, and seconds become us.
    Invalid frames, non-finite states or duplicate IDs raise ValueError.
    This pure function performs no I/O, propagation, selection or ION encoding.
    """
    if not source_rows:
        raise ValueError("mother sample is empty")
    global_rows: list[dict[str, str]] = []
    actual_ids = [int(row["particle_id"]) for row in source_rows]
    if any(particle_id < 1 for particle_id in actual_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ValueError("mother-sample particle IDs must be positive and unique")
    for row in source_rows:
        particle_id = int(row["particle_id"])
        state = transform.transform_state(PhaseSpaceState(
            transform.from_frame_id,
            tuple(float(row[f"{axis}_mm"]) for axis in "xyz"),
            tuple(float(row[f"v{axis}_m_s"]) for axis in "xyz"),
            float(row["birth_time_s"]) * 1e6,
        ))
        x, y, z = state.position_mm
        vx, vy, vz = state.velocity_m_s
        mass = float(row["mass_amu"])
        charge = int(row["charge_state"])
        time_us = state.instrument_time_us
        energy = kinetic_energy_ev(mass, vx, vy, vz)
        global_rows.append(
            {
                "particle_id": str(particle_id),
                "instrument_time_us": format(time_us, ".17g"),
                "mass_amu": format(mass, ".17g"),
                "charge_state": str(charge),
                "position_x_mm": format(x, ".17g"),
                "position_y_mm": format(y, ".17g"),
                "position_z_mm": format(z, ".17g"),
                "velocity_x_m_s": format(vx, ".17g"),
                "velocity_y_m_s": format(vy, ".17g"),
                "velocity_z_m_s": format(vz, ".17g"),
                "kinetic_energy_eV": format(energy, ".17g"),
            }
        )
    return global_rows


def canonical_clock_lua() -> str:
    """Retain row identity and source-origin-plus-elapsed instrument time."""
    return """local function single_flight_source_row_index()
  return ion_number+single_flight_particle_id_offset
end
local function single_flight_canonical_particle_id()
  local particle_id=single_flight_source_particle_id[single_flight_source_row_index()]
  assert(particle_id~=nil,'explicit single-flight row map is missing a source particle ID')
  return particle_id
end
local function single_flight_instrument_time_us()
  local origin=single_flight_time_origin_us[single_flight_source_row_index()]
  assert(origin~=nil,'absolute single-flight clock is missing particle time origin')
  return origin+ion_time_of_flight
end
local function single_flight_restore_source_velocity(velocities)
  local velocity=assert(velocities[single_flight_source_row_index()],
    'frozen source velocity row is missing')
  ion_vx_mm,ion_vy_mm,ion_vz_mm=velocity[1],velocity[2],velocity[3]
end
handoff_instrument_time_us=single_flight_instrument_time_us
"""


def lua_number(value: float) -> str:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Lua numeric value must be finite")
    return format(result, ".17g")


def lua_value(value: object) -> str:
    """Serialize a validated Python contract fragment as deterministic Lua."""
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return lua_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return "{" + ",".join(lua_value(item) for item in value) + "}"
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ValueError(f"Lua contract key is not one identifier: {key!r}")
            items.append(f"{key}={lua_value(item)}")
        return "{" + ",".join(items) + "}"
    raise ValueError(f"unsupported Lua contract value: {type(value).__name__}")
