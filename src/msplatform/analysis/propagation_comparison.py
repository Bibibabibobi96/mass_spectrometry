"""Descriptive same-mother propagation differences, without acceptance thresholds.

Inputs are already collected CSV1 states for one explicitly declared plane
occurrence, plus the actual collector plane rows. No event is localized here.
The source adapter owns record verification and world-frame transformation.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import math
from typing import Any

from msplatform.analysis.particle_census import partition_cohort, subset_efficiency
from msplatform.assembly.handoff import HandoffMother, _validate_mother
from msplatform.contracts.clock import ClockIdentity, require_same_clock
from msplatform.contracts.particle_state import validate_component_particle_state_rows, _validate_lineage


_IDENTITY = ("parent_particle_id", "generation", "lineage_birth_time_us", "species_id", "mass_amu", "charge_state", "particle_weight", "particle_birth_time_us")
_SCALARS = ("instrument_time_us", "particle_age_us", "lineage_age_us", "kinetic_energy_eV")


def _finite(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("collector plane values must be finite numbers")
    return float(value)


from msplatform.contracts.particle_state import binary64_serialization_close as _serialized_equal


def _require_lineage_identity(mother):
    for number, (pid, record) in enumerate(mother.records.items(), 2):
        if any(key not in record for key in _IDENTITY):
            raise ValueError("original mother lacks complete parent/generation/lineage identity")
        if (type(record["generation"]) is not int or
                (record["parent_particle_id"] is not None and type(record["parent_particle_id"]) is not int)):
            raise ValueError("original mother lineage identity requires typed integers")
        _finite(record["lineage_birth_time_us"])
        _validate_lineage(dict(record, particle_id=pid), number)


def _events(events: Sequence[Mapping[str, Any]], mother: set[int], selection: tuple) -> dict:
    result, identities = {}, set()
    for event in events:
        pid = event["particle_id"]
        key = (pid, event["observation_id"], event["direction"], event["occurrence"])
        if (type(pid) is not int or pid not in mother or type(key[3]) is not int or key[3] < 1
                or not isinstance(key[1], str) or not key[1] or key[2] not in {"outward", "inward"}
                or key in identities):
            raise ValueError("invalid or duplicate original plane event identity")
        identities.add(key)
        if key[1:] == selection:
            result[pid] = dict(event)
    return result


def _states(rows, events, mother, clock):
    parsed = validate_component_particle_state_rows(rows).rows if rows else []
    result = {}
    for row in parsed:
        pid = row["particle_id"]
        if pid not in mother.records or pid not in events:
            raise ValueError("state lacks original mother or declared occurrence evidence")
        if row["clock_epoch_id"] != clock.clock_epoch_id:
            raise ValueError("state clock differs from explicit authority")
        if any(row[key] != mother.records[pid][key] for key in _IDENTITY):
            raise ValueError("state species, weight or original birth differs from mother")
        event = events[pid]
        expected = {"instrument_time_us": _finite(event["instrument_time_us"])}
        for axis in "xyz":
            expected[f"position_{axis}_mm"] = _finite(event[f"{axis}_mm"])
            expected[f"velocity_{axis}_m_s"] = _finite(event[f"v{axis}_mm_per_us"]) * 1000.
        if any(not _serialized_equal(row[key], value) for key, value in expected.items()):
            raise ValueError("CSV1 state differs from its actual collector plane event")
        result[pid] = row
    return result


def _differences(pid, left, right):
    if left["frame_id"] != right["frame_id"]:
        raise ValueError("paired state frames differ; transform explicitly before comparison")
    delta = {key: right[key]-left[key] for key in _SCALARS}
    for field, unit in (("position", "mm"), ("velocity", "m_s")):
        values = [right[f"{field}_{axis}_{unit}"]-left[f"{field}_{axis}_{unit}"] for axis in "xyz"]
        delta[f"{field}_components_{unit}"] = values
        delta[f"{field}_norm_{unit}"] = math.hypot(*values)
    phase = left["phase_rad"], right["phase_rad"]
    missing = []
    if None in phase or left["phase_reference_id"] != right["phase_reference_id"]:
        delta.update(phase_raw_rad=None, phase_wrapped_rad=None)
        missing.append("phase: missing value or different phase reference")
    else:
        delta["phase_raw_rad"] = phase[1]-phase[0]
        delta["phase_wrapped_rad"] = math.remainder(delta["phase_raw_rad"], 2*math.pi)
    if any(not math.isfinite(value) for value in delta.values() if isinstance(value, (int, float))):
        raise ValueError("nonfinite propagation difference")
    return dict(particle_id=pid, right_minus_left=delta, insufficient_fields=missing)


def compare_propagations(left_states: Sequence[Mapping[str, Any]], right_states: Sequence[Mapping[str, Any]], *,
                         mother: HandoffMother, left_clock: ClockIdentity, right_clock: ClockIdentity,
                         left_fates: Mapping[int, str], right_fates: Mapping[int, str],
                         observation_id: str, direction: str, occurrence: int,
                         left_events: Sequence[Mapping[str, Any]], right_events: Sequence[Mapping[str, Any]]) -> dict:
    """Compare CSV1 at a declared collector event by original ID, right minus left.

    Same authority, mother species/weight/birth, units and paired frames are
    validated. Fate labels are caller-owned complete classifications; unknown
    and censored remain visible. Missing events/states/phase yield descriptive
    insufficiency, never inferred loss or automatic propagation. Event binding
    uses the existing serialization allowance only within each input branch.
    Wrapped phase is the signed principal difference from math.remainder.
    This does not apply a convergence criterion, threshold or scientific verdict.
    """
    require_same_clock(left_clock, right_clock)
    _validate_mother(mother)
    _require_lineage_identity(mother)
    if (not isinstance(observation_id, str) or not observation_id or direction not in {"outward", "inward"}
            or type(occurrence) is not int or occurrence < 1 or not mother.records):
        raise ValueError("an explicit plane occurrence and full original mother are required")
    ids = list(mother.records)
    weights = {pid: record["particle_weight"] for pid, record in mother.records.items()}
    partitions = []
    for fates in (left_fates, right_fates):
        categories = list(dict.fromkeys(fates.values()))
        partitions.append(partition_cohort(ids, fates.items(), categories=categories, relative_weights=weights))
    selection = observation_id, direction, occurrence
    events = [_events(items, set(ids), selection) for items in (left_events, right_events)]
    states = [_states(rows, event, mother, clock) for rows, event, clock in
              zip((left_states, right_states), events, (left_clock, right_clock), strict=True)]
    matched = [pid for pid in ids if pid in states[0] and pid in states[1]]
    pairs = [_differences(pid, states[0][pid], states[1][pid]) for pid in matched]
    missing = {name: [pid for pid in ids if pid not in state] for name, state in zip(("left", "right"), states)}
    return dict(schema_version=1, role="propagation_comparison", status=("insufficient_observations"
        if any(missing.values()) or any(pair["insufficient_fields"] for pair in pairs) else "comparison_completed"),
        selection=dict(observation_id=observation_id, direction=direction, occurrence=occurrence),
        mother_records=copy.deepcopy(dict(mother.records)), mother_fates=copy.deepcopy(list(mother.fates)),
        clock=dict(clock_epoch_id=left_clock.clock_epoch_id, authority_sha256=left_clock.authority_sha256),
        matched_particle_ids=matched, missing_state_particle_ids=missing,
        unmatched_particle_ids={name: [pid for pid in ids if pid in states[index] and pid not in states[1-index]]
            for index, name in enumerate(("left", "right"))},
        unobserved_in_both_particle_ids=[pid for pid in ids if pid not in states[0] and pid not in states[1]],
        event_without_state={name:[pid for pid in ids if pid in event and pid not in state]
            for name,event,state in zip(("left","right"),events,states,strict=True)},
        fates=dict(left=copy.deepcopy(dict(left_fates)), right=copy.deepcopy(dict(right_fates))),
        fate_partitions=dict(left=partitions[0],right=partitions[1]),
        fate_differences=[dict(particle_id=pid,left=left_fates[pid],right=right_fates[pid])
                          for pid in ids if left_fates[pid] != right_fates[pid]],
        pairs=pairs, claim="descriptive differences only; no threshold verdict or convergence qualification")


def _observed_event_rows(rows, mother, event):
    selected = {}
    for row in rows:
        if not isinstance(row, Mapping) or {"observation_id", "direction", "occurrence"} & row.keys():
            raise ValueError("canonical event comparison rejects plane or mixed event identity")
        pid = row["particle_id"]
        if type(pid) is not int or pid not in mother or not isinstance(row["event"], str) or not row["event"]:
            raise ValueError("canonical event identity differs from original mother")
        values = {key: _finite(row[key]) for key in ("instrument_time_us", "x_mm", "y_mm", "z_mm")}
        if row["event"] != event:
            continue
        if pid in selected:
            raise ValueError("selected canonical event repeats an original particle ID; no first/last fallback")
        selected[pid] = values
    return selected


def compare_observed_events(left_events, right_events, *, mother: HandoffMother,
                            left_clock: ClockIdentity, right_clock: ClockIdentity,
                            left_fates, right_fates, selected_particle_ids, event: str,
                            left_frame_id: str | None, right_frame_id: str | None) -> dict:
    """Describe actual canonical-event t/xyz only, without fabricating CSV1 state.

    Complete mother metadata and caller classifications remain the denominator.
    This method has no velocity, energy or phase observation. Completion means
    calculation only, never equality, accuracy, convergence or Formal status.
    """
    _validate_mother(mother)
    _require_lineage_identity(mother)
    require_same_clock(left_clock, right_clock)
    if not isinstance(event, str) or not event:
        raise ValueError("an explicit canonical event is required")
    ids = list(mother.records)
    weights = {pid: row["particle_weight"] for pid, row in mother.records.items()}
    population = subset_efficiency(ids, selected_particle_ids, ids, relative_weights=weights)
    selected = population["numerator_particle_ids"]
    partitions = [partition_cohort(ids, fates.items(), categories=list(dict.fromkeys(fates.values())),
                                 relative_weights=weights) for fates in (left_fates, right_fates)]
    events = [_observed_event_rows(rows, set(ids), event) for rows in (left_events, right_events)]
    matched = [pid for pid in selected if pid in events[0] and pid in events[1]]
    frames_known = all(isinstance(frame, str) and frame for frame in (left_frame_id, right_frame_id))
    if frames_known and left_frame_id != right_frame_id:
        raise ValueError("canonical event frames differ; transform explicitly before comparison")
    if matched and not frames_known:
        raise ValueError("matched canonical event positions require explicit actual frames")
    pairs = []
    for pid in matched:
        left, right = events[0][pid], events[1][pid]
        delta = [right[axis + "_mm"] - left[axis + "_mm"] for axis in "xyz"]
        time_delta = right["instrument_time_us"] - left["instrument_time_us"]
        if not all(math.isfinite(value) for value in [time_delta, *delta]):
            raise ValueError("nonfinite observed event difference")
        pairs.append(dict(particle_id=pid, right_minus_left=dict(instrument_time_us=time_delta,
            position_components_mm=delta, position_norm_mm=math.hypot(*delta))))
    missing = {name: [pid for pid in selected if pid not in rows]
               for name, rows in zip(("left", "right"), events)}
    coverage = {name: subset_efficiency(ids, [pid for pid in selected if pid in rows], ids, relative_weights=weights)
                for name, rows in zip(("left", "right"), events)}
    return dict(schema_version=1, role="observed_event_comparison", method="event_time_position",
        status="insufficient_observations" if not matched or any(missing.values()) else "comparison_completed",
        mother_records=copy.deepcopy(dict(mother.records)), mother_fates=copy.deepcopy(list(mother.fates)),
        clock=dict(clock_epoch_id=left_clock.clock_epoch_id, authority_sha256=left_clock.authority_sha256),
        frame_ids=dict(left=left_frame_id, right=right_frame_id), selected_population=population, coverage=coverage,
        selection=dict(event=event, particle_ids=selected), matched_particle_ids=matched,
        missing_observation_particle_ids=missing, pairs=pairs,
        fates=dict(left=copy.deepcopy(dict(left_fates)), right=copy.deepcopy(dict(right_fates))), fate_partitions=partitions,
        fate_differences=[dict(particle_id=pid, left=left_fates[pid], right=right_fates[pid])
                          for pid in ids if left_fates[pid] != right_fates[pid]],
        unavailable_quantities=["velocity", "kinetic_energy", "phase", "particle_age", "lineage_age"],
        claim="actual event time/position differences only; no equality, accuracy or scientific qualification")
