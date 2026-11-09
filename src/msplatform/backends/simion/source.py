"""SIMION source-state reader and pure clock serializers; no producer or process access."""
from __future__ import annotations
import csv
import json
import math
import re
from typing import Any
from pathlib import Path
from msplatform.contracts.clock import seconds_to_microseconds
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.contracts.rigid_transform import PhaseSpaceState, RigidTransform

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


def load_initial_state(path: Path) -> tuple[list[float], list[int], list[list[float]]]:
    """Load canonical clocks, retained row IDs and velocities in mm/us.

    A restart can reindex its SIMION rows while preserving the mother-cohort
    identity in the separate row map.  The state-file ID is therefore only
    validated locally; the row map is the authority for source IDs.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("single-flight initial state is empty")
    id_column = "particle_id" if "particle_id" in rows[0] else "simulation_particle_id"
    actual_ids = [int(row[id_column]) for row in rows]
    if any(value <= 0 for value in actual_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ValueError("single-flight initial-state particle IDs must be unique and positive")
    values = [float(row["instrument_time_us"]) for row in rows]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("single-flight birth times must be non-negative")
    velocities = [[float(row[f"velocity_{axis}_m_s"]) / 1000.0 for axis in "xyz"] for row in rows]
    if any(not math.isfinite(value) for velocity in velocities for value in velocity):
        raise ValueError("single-flight initial velocities must be finite")
    return values, actual_ids, velocities



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


def execution_particle_ids(provenance: dict, legacy_count: int) -> list[int]:
    """Read the declared execution IDs; only named legacy provenance uses 1..N.

    Modern provenance must carry the complete original mother and selected IDs.
    This function never reconstructs the mother from the execution survivors.
    """
    if type(provenance.get("schema_version")) is not int:
        raise ValueError("source provenance version must be an integer")
    if provenance.get("schema_version") == 2:
        if provenance.get("role") != "single_reflection_canonical_source_provenance":
            raise ValueError("unknown canonical source provenance role")
        ids = provenance.get("execution_particle_ids")
        mother = provenance.get("mother_particle_ids")
        records = provenance.get("mother_records")
        fates = provenance.get("mother_fates")
        for group in (ids, mother):
            if not isinstance(group, list) or any(type(pid) is not int or pid <= 0 for pid in group) or len(set(group)) != len(group):
                raise ValueError("canonical source IDs must be explicit positive unique lists")
        if (not mother or not set(ids) <= set(mother) or not isinstance(records, list)
                or [row["particle_id"] for row in records] != mother
                or not isinstance(fates, list) or {row["particle_id"] for row in fates} != set(mother)
                or len(fates) != len(mother)):
            raise ValueError("canonical source requires complete original mother records and fates")
        if len(ids) != provenance.get("particle_count"):
            raise ValueError("canonical source declared execution count differs")
        if provenance.get("state_kind") not in {"source_birth", "plane_crossing", "time_snapshot"}:
            raise ValueError("unsupported canonical source state kind")
        _validate_clock_records(provenance.get("clock_records"), provenance.get("clock_authority_sha256", ""))
        events = provenance.get("consumed_plane_events")
        if not isinstance(events, list) or (provenance["state_kind"] != "plane_crossing" and events):
            raise ValueError("canonical source consumed-event declaration differs")
        if provenance["state_kind"] == "plane_crossing" and [row["particle_id"] for row in events] != ids:
            raise ValueError("plane source must bind one consumed event per actual state")
        validate_native_particle_ids(ids)
        return list(ids)
    if provenance.get("schema_version") != 1 or provenance.get("role") != "single_reflection_source_provenance":
        raise ValueError("unsupported source provenance version/role")
    if provenance.get("source_kind") == "recorded_pre_pulse_state":
        ids = provenance.get("continued_particle_ids")
        if not isinstance(ids, list):
            raise ValueError("legacy continuation requires explicit retained IDs")
        return ids
    if provenance.get("source_kind") not in {"recorded_birth", "release_spec"}:
        raise ValueError("unknown legacy source kind")
    return list(range(1, legacy_count + 1))


def _validate_clock_records(clock_records, authority_sha256):
    if not isinstance(authority_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", authority_sha256):
        raise ValueError("canonical source authority SHA-256 is missing")
    if not isinstance(clock_records, dict) or set(clock_records) != {"clock_authority", "instrument_epoch"}:
        raise ValueError("canonical source requires both original clock records")
    for record in clock_records.values():
        if (not isinstance(record, dict) or record.get("exists") is not True or not isinstance(record.get("path"), str)
                or not record["path"] or type(record.get("bytes")) is not int or record["bytes"] <= 0
                or not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[a-fA-F0-9]{64}", record["sha256"])):
            raise ValueError("canonical source clock record lacks its frozen identity")
    if clock_records["instrument_epoch"]["sha256"].upper() != authority_sha256.upper():
        raise ValueError("canonical source instrument epoch differs from handoff authority")


def project_source_states(states, *, mother, clock, state_kind, clock_records, consumed_plane_events=()):
    """Project existing CSV1 states, full mother and explicit clock into SIMION rows.

    source_birth requires the entire original cohort at its actual original
    birth times. Plane/snapshot rows are already selected, verified W3 states;
    this is a format projection, never propagation, selection or resampling.
    Native TOB remains0; its per-row origin is the actual start/arrival time.
    Statistical weights remain metadata and never become SIMION charge factors.
    The outer owner validates producer completion and actual referenced files.
    """
    from copy import deepcopy
    from msplatform.assembly.handoff import HandoffMother, _validate_mother
    from msplatform.contracts.clock import ClockIdentity
    from msplatform.contracts.particle_state import validate_component_particle_state_rows
    if not isinstance(mother, HandoffMother) or not isinstance(clock, ClockIdentity):
        raise ValueError("SIMION source requires canonical mother and clock objects")
    if state_kind not in {"source_birth", "plane_crossing", "time_snapshot"}:
        raise ValueError("unsupported canonical source state kind")
    _validate_mother(mother)
    _validate_clock_records(clock_records, clock.authority_sha256)
    canonical = validate_component_particle_state_rows(states).rows if states else []
    ids = [row["particle_id"] for row in canonical]
    if not mother.records or not set(ids) <= set(mother.records):
        raise ValueError("source states escape the complete original mother")
    if state_kind == "source_birth" and ids != list(mother.records):
        raise ValueError("birth source must contain the full original mother in declared order")
    if len({row["frame_id"] for row in canonical}) > 1:
        raise ValueError("one SIMION source requires one explicit spatial frame")
    for row in canonical:
        original = mother.records[row["particle_id"]]
        if row["clock_epoch_id"] != clock.clock_epoch_id:
            raise ValueError("canonical source row clock differs from authority")
        for field in ("parent_particle_id", "generation", "species_id", "mass_amu", "charge_state", "particle_weight",
                      "lineage_birth_time_us", "particle_birth_time_us"):
            if row[field] != original[field]:
                raise ValueError("source changes original mother lineage, species, weight or birth")
        if state_kind == "source_birth" and (row["instrument_time_us"] != original["particle_birth_time_us"] or row["particle_age_us"] != 0):
            raise ValueError("birth source is not at each original birth with age0")
    rows = []
    for row in canonical:
        item = {"particle_id": str(row["particle_id"]), "instrument_time_us": format(row["instrument_time_us"], ".17g"),
                "mass_amu": format(row["mass_amu"], ".17g"), "charge_state": str(row["charge_state"])}
        for axis in "xyz":
            item["position_" + axis + "_mm"] = format(row["position_" + axis + "_mm"], ".17g")
            item["velocity_" + axis + "_m_s"] = format(row["velocity_" + axis + "_m_s"], ".17g")
        item["kinetic_energy_eV"] = format(row["kinetic_energy_eV"], ".17g")
        rows.append({key: item[key] for key in GLOBAL_COLUMNS})
    consumed = validate_consumed_plane_events(consumed_plane_events, state_kind=state_kind, source_rows=rows)
    for row, event in zip(canonical, consumed, strict=True) if state_kind == "plane_crossing" else ():
        if row["state_event"] != event["observation_id"] + "." + event["direction"] + "." + str(event["occurrence"]):
            raise ValueError("plane source state does not match its consumed event identity")
    provenance = dict(schema_version=2, role="single_reflection_canonical_source_provenance",
        state_kind=state_kind, consumed_plane_events=consumed, particle_count=len(rows), execution_particle_ids=ids,
        mother_particle_ids=list(mother.records), mother_records=[{**deepcopy(record), "particle_id": pid} for pid, record in mother.records.items()],
        mother_fates=deepcopy(list(mother.fates)), clock_epoch_id=clock.clock_epoch_id,
        clock_authority_sha256=clock.authority_sha256, clock_records=deepcopy(clock_records),
        target_frame_id=canonical[0]["frame_id"] if canonical else None,
        state_time_semantics="original_birth_instrument_time" if state_kind == "source_birth" else
                             "per_particle_arrival_instrument_time_without_original_birth_reset")
    execution_particle_ids(provenance, len(rows))
    return rows, provenance


def project_handoff_source(handoff, *, clock_records, consumed_plane_events=()):
    """Project the actual W3 result through the same sole source-state projector.

    Zero transfer returns no rows/full mother; the outer owner must not Fly an
    empty source or serialize a fabricated nonempty canonical transfer table.
    """
    from msplatform.assembly.handoff import HandoffResult
    if not isinstance(handoff, HandoffResult) or handoff.state_kind not in {"plane_crossing", "time_snapshot"}:
        raise ValueError("SIMION handoff source requires an actual supported W3 result")
    rows, provenance = project_source_states(handoff.rows, mother=handoff.mother, clock=handoff.clock.target,
        state_kind=handoff.state_kind, clock_records=clock_records, consumed_plane_events=consumed_plane_events)
    if provenance["execution_particle_ids"] != list(handoff.selected_particle_ids):
        raise ValueError("handoff selected-ID declaration differs from actual states")
    return rows, provenance


MAX_EXACT_NATIVE_PARTICLE_ID = 2**53 - 1


def validate_native_particle_ids(ids):
    """Reject unsupported IDs before Lua binary64 transport, never round them.

    Canonical contracts may represent larger Python integers; this backend's
    numeric native row-map ABI currently supports only exact integers below2^53.
    """
    if (any(type(pid) is not int or not 0 < pid <= MAX_EXACT_NATIVE_PARTICLE_ID for pid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("SIMION numeric particle-ID ABI requires unique integers in1..2^53-1")
    return list(ids)


def prepare_plane_handoff_states(observations, *, observation_id, direction, occurrence,
                                 source_instance_id, target_instance_id, frame_id,
                                 transform, clock, mother, producer_completed):
    """Select one genuinely observed occurrence into existing CSV1/W3 state.

    The outer owner verifies original producer completion and file identities.
    Position/velocity are the declared accepted-step interpolation estimate,
    not an exact native landing or qualified integration error bound.
    """
    from msplatform.assembly.handoff import HandoffSelection, prepare_handoff_states
    from msplatform.contracts.clock import age_us
    from msplatform.contracts.particle_physics import kinetic_energy_ev, mass_to_charge_th
    if (producer_completed is not True or observations.get("schema_version") != 1
            or observations.get("role") != "single_reflection_plane_observations"
            or observations.get("status") != "complete"
            or direction not in {"outward", "inward"} or type(occurrence) is not int or occurrence < 1):
        raise ValueError("plane handoff requires completed producer and explicit complete event occurrence")
    declared = [row for row in observations["definitions"] if row["observation_id"] == observation_id]
    if len(declared) != 1 or declared[0]["source_instance_id"] != source_instance_id:
        raise ValueError("plane handoff observation/source definition differs")
    selected = [row for row in observations["rows"] if row["observation_id"] == observation_id
                and row["direction"] == direction and row["occurrence"] == occurrence]
    by_id = {}
    for row in selected:
        pid = row["particle_id"]
        if pid in by_id or pid not in mother.records:
            raise ValueError("plane selection duplicates or escapes the original mother")
        if row["method"] != "accepted_step_linear_interpolation":
            raise ValueError("unsupported plane event localization")
        by_id[pid] = row
    ids = [pid for pid in mother.records if pid in by_id]
    states = []
    for pid in ids:
        observed, original = by_id[pid], mother.records[pid]
        time = observed["instrument_time_us"]
        mass, charge = original["mass_amu"], original["charge_state"]
        velocity = [observed["v" + axis + "_mm_per_us"] * 1000 for axis in "xyz"]
        state = {key: original[key] for key in ("parent_particle_id", "generation", "species_id", "particle_weight",
                                                 "lineage_birth_time_us", "particle_birth_time_us")}
        state.update(particle_id=pid, source_component_id=source_instance_id, target_component_id=target_instance_id,
            state_event=observation_id + "." + direction + "." + str(occurrence), frame_id=frame_id,
            clock_epoch_id=clock.source.clock_epoch_id, instrument_time_us=time,
            lineage_age_us=age_us(time, birth_time_us=original["lineage_birth_time_us"]),
            particle_age_us=age_us(time, birth_time_us=original["particle_birth_time_us"]),
            last_component_elapsed_time_us=age_us(time, birth_time_us=original["source_component_entry_time_us"]),
            mass_amu=mass, charge_state=charge, mass_to_charge_Th=mass_to_charge_th(mass, charge),
            kinetic_energy_eV=kinetic_energy_ev(mass, *velocity), phase_reference_id=None, phase_rad=None)
        # Phase is deliberately not fabricated from a TRACE position. The same
        # field/clock authority drives the receiver; no phase sample is claimed.
        state.update({"position_" + a + "_mm": observed[a + "_mm"] for a in "xyz"})
        state.update({"velocity_" + a + "_m_s": value for a, value in zip("xyz", velocity, strict=True)})
        states.append(state)
    return prepare_handoff_states(states, transform=transform, clock=clock,
        selection=HandoffSelection("plane_crossing", tuple(ids)), mother=mother)


def validate_consumed_plane_events(events, *, state_kind, source_rows):
    """Bind explicit already-consumed event identities to exact restart rows.

    This validates provenance and source equality, never estimates plane
    membership, shifts position/time or selects a later successful trajectory.
    """
    from copy import deepcopy
    if not isinstance(events, (list, tuple)):
        raise ValueError("consumed plane events must be an explicit sequence")
    if state_kind != "plane_crossing":
        if events:
            raise ValueError("birth/snapshot sources cannot consume a plane event")
        return []
    if len(events) != len(source_rows):
        raise ValueError("plane source requires one consumed event per state")
    keys = {"particle_id", "observation_id", "direction", "occurrence", "instrument_time_us", "position_mm"}
    for event, row in zip(events, source_rows, strict=True):
        if (not isinstance(event, dict) or set(event) != keys
                or type(event["particle_id"]) is not int or event["particle_id"] != int(row["particle_id"])
                or not isinstance(event["observation_id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", event["observation_id"])
                or event["direction"] not in {"outward", "inward"}
                or type(event["occurrence"]) is not int or event["occurrence"] < 1
                or type(event["instrument_time_us"]) not in (int, float)
                or not math.isfinite(event["instrument_time_us"])
                or event["instrument_time_us"] != float(row["instrument_time_us"])
                or not isinstance(event["position_mm"], list) or len(event["position_mm"]) != 3
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in event["position_mm"])
                or event["position_mm"] != [float(row["position_"+a+"_mm"]) for a in "xyz"]):
            raise ValueError("consumed event identity/start time/position differs from actual source")
    return deepcopy(list(events))


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
            seconds_to_microseconds(float(row["birth_time_s"])),
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


def project_direct_velocity(*, particle_id: int, time_us: float, position_mm: list[float],
                            velocity_m_s: list[float], energy_ev: float, mass_amu: float,
                            charge_state: int, beam_position_mm: list[float],
                            beam_direction: list[float], weight: float, color: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project caller-selected 6D to a Lua state and direct-velocity standard beam.

    The caller owns coordinate transforms and clock epoch. The beam direction
    is supplied in its target frame; its magnitude is not used to infer energy.
    IDs here are solver ordinals, with original identity retained by the caller.
    """
    if any(len(values) != 3 for values in (position_mm, velocity_m_s, beam_position_mm, beam_direction)):
        raise ValueError("particle position and velocity require three components")
    state = dict(particle_id=particle_id, t=time_us, x=position_mm[0], y=position_mm[1], z=position_mm[2],
                 vx=velocity_m_s[0]/1000, vy=velocity_m_s[1]/1000, vz=velocity_m_s[2]/1000, ke=energy_ev)
    beam = dict(tob=time_us, mass=mass_amu, charge=charge_state, x=beam_position_mm[0], y=beam_position_mm[1],
                z=beam_position_mm[2], direction=beam_direction, ke=energy_ev, cwf=weight, color=color)
    return state, beam


def render_standard_beams(beams: list[dict[str, Any]]) -> str:
    """Render standard_beam records whose values are already in SIMION coordinates."""
    lines = ["particles {", "  coordinates = 0,"]
    for index, beam in enumerate(beams):
        comma = "," if index < len(beams) - 1 else ""
        lines.extend([
            "  standard_beam {", "    n = 1,", f"    tob = {beam['tob']},",
            f"    mass = {beam['mass']},", f"    charge = {beam['charge']},",
        ])
        if "direction" in beam:
            direction = beam["direction"]
            if not isinstance(direction, (list, tuple)) or len(direction) != 3:
                raise ValueError("standard beam direction must contain three components")
            lines.extend([
                f"    position = vector({beam['x']},{beam['y']},{beam['z']}),",
                f"    direction = vector({direction[0]},{direction[1]},{direction[2]}),",
                f"    ke = {beam['ke']},",
            ])
        else:
            lines.extend([
                f"    x = {beam['x']},", f"    y = {beam['y']},", f"    z = {beam['z']},",
                f"    ke = {beam['ke']},", f"    az = {beam['az']},", f"    el = {beam['el']},",
            ])
        lines.extend([
            f"    cwf = {beam['cwf']},", f"    color = {beam['color']}", f"  }}{comma}",
        ])
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_source_states(states: list[dict[str, Any]], *, significant_digits: int = 15) -> str:
    """Render workbench states; 17 digits preserve binary64, default 15 is legacy."""
    if isinstance(significant_digits, bool) or not isinstance(significant_digits, int) or significant_digits not in (15, 17):
        raise ValueError("source-state significant_digits must be 15 or 17")
    precision = f".{significant_digits}g"
    lines = ["return {"]
    for state in states:
        lines.append(
            f"  [{int(state['particle_id'])}]={{t={state['t']:{precision}},x={state['x']:{precision}},"
            f"y={state['y']:{precision}},z={state['z']:{precision}},vx={state['vx']:{precision}},"
            f"vy={state['vy']:{precision}},vz={state['vz']:{precision}},ke={state['ke']:{precision}}" + "},"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"
