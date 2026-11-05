"""Canonical native flight events and terminal census, without peak statistics.

Shared by full-instrument collection and legacy statistical analysis. Reading
preserves logged particle identities; finalization converts detector elapsed
clock once using observed births and validates the terminal partition.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import math
import re

import numpy as np
from msplatform.backends.simion.tracking_program import validate_propagation_stop

from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.backends.simion.native_completion import parse_fly_completed_line


STATE_PATTERN = re.compile(
    r"TRACE: (?P<event>source_release|single_flight_handoff|accelerator_sidewall_inner_forward|accelerator_axis_forward|pre_pulse_state|accelerator_grid1_forward|accelerator_intermediate2_forward|local_accelerator_exit|accelerator_focus_forward|reflectron_entrance_forward|reflectron_midgrid_forward|reflectron_turning_point|reflectron_exit_return) "
    r"ion=(?P<ion>\d+)(?: particle_id=(?P<particle_id>\d+))? instrument_time_us=(?P<t>[-+0-9.eE]+) "
    r"(?:tof_since_pulse_us=(?P<tof_since_pulse>[-+0-9.eE]+) )?"
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_per_us=(?P<vx>[-+0-9.eE]+) vy_mm_per_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_per_us=(?P<vz>[-+0-9.eE]+)(?: kinetic_energy_eV=(?P<energy>[-+0-9.eE]+) survival_status=(?P<survival>\w+))?"
    r"(?: step_start_instrument_time_us=(?P<step_start_t>[-+0-9.eE]+) step_end_instrument_time_us=(?P<step_end_t>[-+0-9.eE]+)"
    r" step_start_x_mm=(?P<step_start_x>[-+0-9.eE]+) step_end_x_mm=(?P<step_end_x>[-+0-9.eE]+))?"
)
DETECTOR_PATTERN = re.compile(
    r"TRACE: detector_crossing ion=(?P<ion>\d+) t=(?P<t>[-+0-9.eE]+) "
    r"x=(?P<x>[-+0-9.eE]+) y=(?P<y>[-+0-9.eE]+) z=(?P<z>[-+0-9.eE]+)"
)
NON_DETECTOR_SPLAT_PATTERN = re.compile(
    r"TRACE: non_detector_splat ion=(?P<ion>\d+) instance=(?P<instance>\d+) "
    r"t=(?P<t>[-+0-9.eE]+) x=(?P<x>[-+0-9.eE]+) "
    r"y=(?P<y>[-+0-9.eE]+) z=(?P<z>[-+0-9.eE]+) "
    r"zmax=(?P<zmax>[-+0-9.eE]+)"
)
TIMEOUT_SPLAT_PATTERN = re.compile(
    r"TRACE: timeout_splat ion=(?P<ion>\d+) instance=(?P<instance>\d+) "
    r"instrument_time_us=(?P<t>[-+0-9.eE]+) x_mm=(?P<x>[-+0-9.eE]+) "
    r"y_mm=(?P<y>[-+0-9.eE]+) z_mm=(?P<z>[-+0-9.eE]+) "
    r"zmax_mm=(?P<zmax>[-+0-9.eE]+)"
)

PULSE_PATTERN = re.compile(
    r"TRACE: handoff_pulse_on(?: ion=(?P<ion>\d+))? "
    r"instrument_time_us=(?P<t>[-+0-9.eE]+)"
)
PULSE_STATE_PATTERN = re.compile(
    r"TRACE: handoff_pulse_on ion=(?P<ion>\d+) "
    r"instrument_time_us=(?P<t>[-+0-9.eE]+) "
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) "
    r"z_mm=(?P<z>[-+0-9.eE]+) vx_mm_per_us=(?P<vx>[-+0-9.eE]+) "
    r"vy_mm_per_us=(?P<vy>[-+0-9.eE]+) vz_mm_per_us=(?P<vz>[-+0-9.eE]+)"
)
POST_FOCUS_EVENTS = (
    "accelerator_focus_forward",
    "reflectron_entrance_forward",
    "reflectron_midgrid_forward",
    "reflectron_turning_point",
    "reflectron_exit_return",
    "detector_crossing",
)


REFLECTRON_EVENTS = POST_FOCUS_EVENTS[1:5]
REFLECTRON_PATH_EVENTS = POST_FOCUS_EVENTS[:-1]


_STATE = ('instrument_time_us', 'x_mm', 'y_mm', 'z_mm',
          'vx_mm_per_us', 'vy_mm_per_us', 'vz_mm_per_us')


def read_native_evidence(log: Path, source: dict, flight: dict) -> tuple[dict, dict, list[dict], list[dict]]:
    """Require actual births and raw native stops, retaining original line locations."""
    raw_terminals, locations = {}, {}
    ordered_ids = list(source)
    def global_id(native_ion: int) -> int:
        if not 1 <= native_ion <= len(ordered_ids):
            raise ValueError('native ion index is outside the frozen source cohort')
        return ordered_ids[native_ion - 1]
    completed = False
    births = set()
    pulse_states = {}
    shared_states, seen_shared = [], set()
    pulse = flight['pulse']
    candidate_times = flight.get('observation_times_us', [])
    with log.open(encoding='utf-8-sig') as stream:
        for number, line in enumerate(stream, 1):
            if 'TRACE: native_shared_time ' in line:
                pairs = re.findall(r'(\w+)=([^\s]+)', line.split('TRACE: native_shared_time ', 1)[1])
                fields = dict(pairs)
                if (len(fields) != len(pairs) or set(fields) !=
                        {'ion', 'particle_id', 'instance', *_STATE, 'candidate_time_us', 'kinetic_energy_eV'}):
                    raise ValueError(f'{log}:{number}: malformed actual shared-time state')
                pid = global_id(int(fields.pop('ion')))
                if int(fields['particle_id']) != pid:
                    raise ValueError(f'{log}:{number}: shared-time ID differs from frozen source')
                row = {key: float(value) for key, value in fields.items()}
                target = row['candidate_time_us']
                if (not all(math.isfinite(value) for value in row.values()) or target not in candidate_times
                        or not _close(row['instrument_time_us'], target) or (pid, target) in seen_shared):
                    raise ValueError(f'{log}:{number}: invalid or duplicate actual shared-time observation')
                row.update(particle_id=pid, instance=int(fields['instance']), event='native_shared_time', raw_line_number=number)
                shared_states.append(row)
                seen_shared.add((pid, target))
            if parse_fly_completed_line(line) is not None:
                completed = True
            match = STATE_PATTERN.search(line)
            if 'TRACE: source_release ' in line and match is None:
                raise ValueError(f'{log}:{number}: malformed actual native birth')
            if match:
                pid, event = global_id(int(match['ion'])), match['event']
                if match['particle_id'] is not None and int(match['particle_id']) != pid:
                    raise ValueError(f'{log}:{number}: native ID differs from frozen source')
                canonical = 'multipole_handoff' if event == 'single_flight_handoff' else event
                locations[pid, canonical] = number
                if event == 'source_release':
                    if pid in births:
                        raise ValueError(f'{log}:{number}: particle {pid} duplicate birth')
                    births.add(pid)
                if pulse['mode'] == 'held_off' and event == 'pre_pulse_state':
                    raise ValueError('held-OFF log contains a fictitious pre-pulse observation')
            if PULSE_PATTERN.search(line):
                if pulse['mode'] == 'held_off':
                    raise ValueError('held-OFF log contains a pulse event')
                pulse_match = PULSE_STATE_PATTERN.search(line)
                if pulse_match is None:
                    raise ValueError(f'{log}:{number}: malformed native pulse state')
                pid = global_id(int(pulse_match['ion']))
                if pid in pulse_states:
                    raise ValueError(f'{log}:{number}: duplicate or unknown native pulse particle')
                pulse_states[pid] = dict(particle_id=pid, event='handoff_pulse_on',
                    **{name: float(pulse_match[group]) for name, group in zip(_STATE, ('t', 'x', 'y', 'z', 'vx', 'vy', 'vz'), strict=True)})
                locations[pid, 'handoff_pulse_on'] = number
            if 'TRACE: handoff_terminal_raw ' not in line:
                continue
            pairs = re.findall(r'(\w+)=([^\s]+)', line.split('TRACE: handoff_terminal_raw ', 1)[1])
            fields = dict(pairs)
            if len(fields) != len(pairs) or set(fields) != {'ion', 'instance', *_STATE}:
                raise ValueError(f'{log}:{number}: raw terminal fields differ')
            pid = global_id(int(fields.pop('ion')))
            if pid in raw_terminals:
                raise ValueError(f'{log}:{number}: particle {pid} lacks a unique raw native terminal')
            terminal = {key: float(value) for key, value in fields.items()}
            if not all(math.isfinite(value) for value in terminal.values()):
                raise ValueError(f'{log}:{number}: nonfinite native terminal')
            raw_terminals[pid] = dict(particle_id=pid, **terminal, raw_line_number=number)
    if not completed:
        raise ValueError('native Fly completion sentinel is missing')
    if births != set(source) or set(raw_terminals) != set(source):
        raise ValueError('frozen source cohort requires one actual native birth and raw terminal for every ID')
    return raw_terminals, locations, list(pulse_states.values()), shared_states


def _validate_reflectron_event_order(rows: list[dict[str, object]]) -> None:
    """Reject non-prefix or non-monotonic reflectron checkpoint sequences."""
    by_particle: dict[int, dict[str, float]] = {}
    for row in rows:
        event = str(row["event"])
        if event in REFLECTRON_EVENTS:
            by_particle.setdefault(int(row["particle_id"]), {})[event] = float(
                row["instrument_time_us"]
            )
    for particle_id, observed in by_particle.items():
        observed_indices = [
            index for index, event in enumerate(REFLECTRON_EVENTS) if event in observed
        ]
        if observed_indices != list(range(len(observed_indices))):
            raise ValueError(
                f"reflectron checkpoint sequence is not a prefix: particle={particle_id}"
            )
        times = [observed[event] for event in REFLECTRON_EVENTS[: len(observed_indices)]]
        if any(right <= left for left, right in zip(times, times[1:])):
            raise ValueError(
                f"reflectron checkpoint times are not strictly ordered: particle={particle_id}"
            )


def _resolve_pulse_time_us(
    configured_time_us: float | None, observed_times_us: list[float]
) -> float | None:
    """Resolve one effective pulse time and reject inconsistent log/config clocks."""
    if configured_time_us is not None and not np.isfinite(configured_time_us):
        raise ValueError("pulse effective time must be finite")
    if observed_times_us:
        reference = observed_times_us[0]
        if any(abs(value - reference) > 1e-9 for value in observed_times_us[1:]):
            raise ValueError("SIMION batches report inconsistent pulse effective times")
        if configured_time_us is not None and abs(configured_time_us - reference) > 1e-9:
            raise ValueError("configured and logged pulse effective times differ")
        return reference
    return configured_time_us


def _terminal_taxonomy(
    expected_particle_ids: set[int],
    terminal_outcomes: dict[int, dict[str, object]],
) -> dict[str, object]:
    """Return one exhaustive terminal category for every frozen mother ID."""

    missing = sorted(expected_particle_ids - set(terminal_outcomes))
    if missing:
        raise ValueError("full-flight terminal taxonomy lacks terminal outcome")
    extra = set(terminal_outcomes) - expected_particle_ids
    if extra:
        raise ValueError("full-flight terminal taxonomy has unknown particle ID")
    records = [terminal_outcomes[particle_id] for particle_id in sorted(expected_particle_ids)]
    category_counts: dict[str, int] = {}
    for record in records:
        category = str(record["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "role": "rf_oatof_full_flight_terminal_taxonomy",
        "classification_is_mutually_exclusive_and_exhaustive": True,
        "mother_cohort_count": len(expected_particle_ids),
        "terminal_outcome_count": len(records),
        "category_counts": category_counts,
        "particle_outcomes": records,
    }


def read_native_events(
    log_paths: Sequence[Path], mass_amu: float, ordered_particle_ids: Sequence[int],
    batch_particle_counts: Sequence[int] | None = None,
) -> dict:
    """Read native TRACE rows, terminal records and observed pulse times."""
    launched = len(ordered_particle_ids)
    if batch_particle_counts is None:
        batch_particle_counts = [launched]
    if (
        len(log_paths) != len(batch_particle_counts)
        or any(count < 1 for count in batch_particle_counts)
        or sum(batch_particle_counts) != launched
    ):
        raise ValueError("single-flight batch log/count identity differs")
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    terminal_outcomes: dict[int, dict[str, object]] = {}
    pulse_times: list[float] = []
    offset = 0
    lines: list[tuple[str, int, int]] = []
    for path, count in zip(log_paths, batch_particle_counts, strict=True):
        lines.extend(
            (line, offset, count)
            for line in path.read_text(
                encoding="utf-8-sig", errors="replace"
            ).splitlines()
        )
        offset += count
    for line, particle_offset, batch_count in lines:
        match = STATE_PATTERN.search(line)
        if match:
            event = {
                "source_release": "source_release",
                "single_flight_handoff": "multipole_handoff",
                "accelerator_sidewall_inner_forward": "accelerator_sidewall_inner_forward",
                "accelerator_axis_forward": "accelerator_axis_forward",
                "pre_pulse_state": "pre_pulse_state",
                "local_accelerator_exit": "local_accelerator_exit",
                "accelerator_grid1_forward": "accelerator_grid1_forward",
                "accelerator_intermediate2_forward": "accelerator_intermediate2_forward",
                "accelerator_focus_forward": "accelerator_focus_forward",
                "reflectron_entrance_forward": "reflectron_entrance_forward",
                "reflectron_midgrid_forward": "reflectron_midgrid_forward",
                "reflectron_turning_point": "reflectron_turning_point",
                "reflectron_exit_return": "reflectron_exit_return",
            }[match["event"]]
            local_id = int(match["ion"])
            if not 1 <= local_id <= batch_count:
                raise ValueError("logged particle identity is outside its batch")
            source_row = local_id + particle_offset
            global_id = ordered_particle_ids[source_row - 1]
            if match["particle_id"] is not None and int(match["particle_id"]) != global_id:
                raise ValueError("logged global particle identity differs from batch offset")
            key = (global_id, event)
            if key in seen:
                raise ValueError(f"duplicate checkpoint: particle={key[0]} event={event}")
            seen.add(key)
            vx = float(match["vx"])
            vy = float(match["vy"])
            vz = float(match["vz"])
            recomputed_energy = kinetic_energy_ev(
                mass_amu, 1000.0 * vx, 1000.0 * vy, 1000.0 * vz
            )
            logged_energy = (
                float(match["energy"]) if match["energy"] is not None else None
            )
            if logged_energy is not None and not np.isclose(
                logged_energy,
                recomputed_energy,
                rtol=5e-9,
                atol=5e-10,
            ):
                raise ValueError(
                    f"logged kinetic energy differs from velocity: particle={key[0]} "
                    f"event={event}"
                )
            rows.append({
                "particle_id": key[0], "event": event, "instrument_time_us": float(match["t"]),
                "x_mm": float(match["x"]), "y_mm": float(match["y"]), "z_mm": float(match["z"]),
                "vx_mm_per_us": vx, "vy_mm_per_us": vy, "vz_mm_per_us": vz,
                "kinetic_energy_eV": recomputed_energy,
                "pulse_eligibility": "",
                "pulse_effective_elapsed_us": (
                    float(match["tof_since_pulse"])
                    if match["tof_since_pulse"] is not None else ""
                ),
                "survival_status": match["survival"] or "alive",
            })
            if match["step_start_t"] is not None:
                rows[-1].update({name: float(match[group]) for name, group in (
                    ("step_start_instrument_time_us", "step_start_t"),
                    ("step_end_instrument_time_us", "step_end_t"),
                    ("step_start_x_mm", "step_start_x"), ("step_end_x_mm", "step_end_x"),
                )})
            continue
        match = DETECTOR_PATTERN.search(line)
        if match:
            local_id = int(match["ion"])
            if not 1 <= local_id <= batch_count:
                raise ValueError("logged particle identity is outside its batch")
            source_row = local_id + particle_offset
            key = (ordered_particle_ids[source_row - 1], "detector_crossing")
            if key in seen:
                raise ValueError(f"duplicate detector crossing: particle={key[0]}")
            if key[0] in terminal_outcomes:
                raise ValueError(f"duplicate terminal outcome: particle={key[0]}")
            seen.add(key)
            terminal_outcomes[key[0]] = {
                "particle_id": key[0],
                "category": "detector_crossing",
                "terminal_event": "detector_crossing",
                "instance_id": 4,
                "terminal_instrument_time_us": None,
                "x_mm": float(match["x"]),
                "y_mm": float(match["y"]),
                "z_mm": float(match["z"]),
                "zmax_mm": None,
            }
            rows.append({
                "particle_id": key[0], "event": key[1],
                "solver_local_elapsed_us": float(match["t"]),
                "instrument_time_us": "",
                "x_mm": float(match["x"]), "y_mm": float(match["y"]), "z_mm": float(match["z"]),
                "vx_mm_per_us": "", "vy_mm_per_us": "", "vz_mm_per_us": "",
                "kinetic_energy_eV": "",
                "pulse_eligibility": "",
                "pulse_effective_elapsed_us": "",
                "survival_status": "detected",
            })
            continue
        match = NON_DETECTOR_SPLAT_PATTERN.search(line)
        if match:
            local_id = int(match["ion"])
            if not 1 <= local_id <= batch_count:
                raise ValueError("logged particle identity is outside its batch")
            source_row = local_id + particle_offset
            particle_id = ordered_particle_ids[source_row - 1]
            if particle_id in terminal_outcomes:
                raise ValueError(f"duplicate terminal outcome: particle={particle_id}")
            instance_id = int(match["instance"])
            terminal_outcomes[particle_id] = {
                "particle_id": particle_id,
                "category": f"non_detector_splat_instance_{instance_id}",
                "terminal_event": "non_detector_splat",
                "instance_id": instance_id,
                "terminal_instrument_time_us": float(match["t"]),
                "x_mm": float(match["x"]),
                "y_mm": float(match["y"]),
                "z_mm": float(match["z"]),
                "zmax_mm": float(match["zmax"]),
            }
            continue
        match = TIMEOUT_SPLAT_PATTERN.search(line)
        if match:
            local_id = int(match["ion"])
            if not 1 <= local_id <= batch_count:
                raise ValueError("logged particle identity is outside its batch")
            source_row = local_id + particle_offset
            particle_id = ordered_particle_ids[source_row - 1]
            if particle_id in terminal_outcomes:
                raise ValueError(f"duplicate terminal outcome: particle={particle_id}")
            terminal_outcomes[particle_id] = {
                "particle_id": particle_id,
                "category": "timeout_splat",
                "terminal_event": "timeout_splat",
                "instance_id": int(match["instance"]),
                "terminal_instrument_time_us": float(match["t"]),
                "x_mm": float(match["x"]),
                "y_mm": float(match["y"]),
                "z_mm": float(match["z"]),
                "zmax_mm": float(match["zmax"]),
            }
            continue
        match = PULSE_PATTERN.search(line)
        if match:
            pulse_times.append(float(match["t"]))
    return dict(rows=rows, terminal_outcomes=terminal_outcomes, pulse_times=pulse_times)


def canonical_census(
    evidence: dict, ordered_particle_ids: Sequence[int], *,
    pulse_time_us: float | None = None, require_terminal_taxonomy: bool = True,
) -> dict:
    """Canonicalize rows in place and return event counts and terminal census.

    Statistical callers may reconstruct their separately validated restart
    births before this boundary; complete-mother collection never does so.
    """
    rows = evidence['rows']
    terminal_outcomes = evidence['terminal_outcomes']
    pulse_times = evidence['pulse_times']
    launched = len(ordered_particle_ids)
    expected_particle_ids = set(ordered_particle_ids)
    clock_basis = 'canonical_instrument_time_us'
    rows.sort(key=lambda row: (int(row["particle_id"]), str(row["event"])))
    _validate_reflectron_event_order(rows)
    counts = {event: sum(row["event"] == event for row in rows) for event in (
        "source_release", "multipole_handoff", "accelerator_sidewall_inner_forward", "accelerator_axis_forward", "pre_pulse_state",
        "accelerator_grid1_forward", "accelerator_intermediate2_forward",
        "local_accelerator_exit", "accelerator_focus_forward",
        "reflectron_entrance_forward", "reflectron_midgrid_forward",
        "reflectron_turning_point", "reflectron_exit_return", "detector_crossing",
    )}
    if launched < 1 or any(int(row["particle_id"]) not in expected_particle_ids for row in rows):
        raise ValueError("logged particle identity is outside the launched mother sample")
    effective_pulse_time_us = _resolve_pulse_time_us(pulse_time_us, pulse_times)
    detector_rows = [row for row in rows if row["event"] == "detector_crossing"]
    birth_times = {
        int(row["particle_id"]): float(row["instrument_time_us"])
        for row in rows if row["event"] == "source_release"
    }
    for row in detector_rows:
        particle_id = int(row["particle_id"])
        if particle_id not in birth_times:
            raise ValueError("detector canonical clock lacks source birth authority")
        row["instrument_time_us"] = (
            birth_times[particle_id] + float(row.pop("solver_local_elapsed_us"))
        )
        terminal_outcomes[particle_id]["terminal_instrument_time_us"] = row["instrument_time_us"]
    # Detector logs carry solver-local elapsed time; splat logs already carry
    # canonical instrument time. Reuse the canonical detector conversion above
    # and never add the source epoch to an already canonical splat timestamp.
    for terminal in terminal_outcomes.values():
        terminal["terminal_pulse_effective_elapsed_us"] = (
            float(terminal["terminal_instrument_time_us"]) - effective_pulse_time_us
            if effective_pulse_time_us is not None else None
        )
    terminal_taxonomy = (
        _terminal_taxonomy(expected_particle_ids, terminal_outcomes)
        if require_terminal_taxonomy
        else {
            "role": "rf_oatof_full_flight_terminal_taxonomy",
            "classification_is_mutually_exclusive_and_exhaustive": False,
            "status": "not_applicable_detector_blind_pre_pulse_or_unqualified_analysis",
        }
    )
    for row in rows:
        if effective_pulse_time_us is not None:
            computed = float(row["instrument_time_us"]) - effective_pulse_time_us
            reported = row["pulse_effective_elapsed_us"]
            if reported != "" and abs(float(reported) - computed) > 1e-8:
                raise ValueError("logged pulse-effective checkpoint time is inconsistent")
            row["pulse_effective_elapsed_us"] = computed
    return {
        "schema_version": 1, "role": "single_flight_canonical_census",
        "census": {"launched": launched, **counts}, "terminal_taxonomy": terminal_taxonomy,
        "clock_basis": clock_basis, "pulse_effective_time_us": effective_pulse_time_us,
        "analysis_scope": "complete_mother_canonical_events_and_terminal_census",
        "pulse_eligibility_validation_applied": False,
        "peak_or_bootstrap_computed": False, "formal_gate_passed": False,
    }


def read_plane_observations(log_paths, ordered_particle_ids, batch_counts, definitions, *, consumed_plane_events=()):
    """Read the explicit V1 observation wire without dropping recrossings.

    The caller verifies/freeze-binds the definitions and native producer logs.
    A declared record cap is a retained incomplete fact, never a loss or PASS.
    """
    allowed = {row["observation_id"] for row in definitions}
    if len(allowed) != len(definitions) or not allowed:
        raise ValueError("plane observation definitions must be unique and nonempty")
    if len(log_paths) != len(batch_counts) or sum(batch_counts) != len(ordered_particle_ids):
        raise ValueError("plane observation batch/source binding differs")
    rows, incomplete, unlocalized, seen, occurrence = [], [], [], set(), {}
    for event in consumed_plane_events:
        key = (event["particle_id"], event["observation_id"], event["direction"])
        if event["particle_id"] not in ordered_particle_ids or event["observation_id"] not in allowed or key in occurrence:
            raise ValueError("plane source consumed event differs from actual source/definition")
        occurrence[key] = event["occurrence"]
    numeric = {"instrument_time_us", "x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us",
               "step_start_instrument_time_us", "step_end_instrument_time_us", "signed_distance_before_mm", "signed_distance_after_mm"}
    numeric |= {f"step_{end}_{axis}_mm" for end in ("start", "end") for axis in "xyz"}
    numeric |= {f"step_{end}_v{axis}_mm_per_us" for end in ("start", "end") for axis in "xyz"}
    keys = numeric | {"observation_id", "ion", "particle_id", "direction", "occurrence", "method"}
    offset = 0
    for path, count in zip(log_paths, batch_counts, strict=True):
        with Path(path).open(encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if "PLANE_OBSERVATION_INCOMPLETE_V1:" in line:
                    fields = dict(re.findall(r"(\w+)=([^\s]+)", line.split("PLANE_OBSERVATION_INCOMPLETE_V1:", 1)[1]))
                    if set(fields) != {"observation_id", "reason"} or fields["observation_id"] not in allowed or fields["reason"] != "declared_record_cap":
                        raise ValueError("invalid plane observation incomplete fact")
                    incomplete.append(dict(fields, raw_line_number=line_number, log=str(path)))
                elif "PLANE_BOUNDARY_RETURN_V1:" in line:
                    pairs = re.findall(r"(\w+)=([^\s]+)", line.split("PLANE_BOUNDARY_RETURN_V1:", 1)[1])
                    fields = dict(pairs)
                    endpoint_keys = {f"step_{end}_{axis}_mm" for end in ("start","end") for axis in "xyz"}
                    endpoint_keys |= {f"step_{end}_v{axis}_mm_per_us" for end in ("start","end") for axis in "xyz"}
                    numbers = endpoint_keys | {"interval_start_us", "interval_end_us"}
                    expected = numbers | {"observation_id", "ion", "particle_id", "consumed_direction", "consumed_occurrence", "method"}
                    if len(fields) != len(pairs) or set(fields) != expected:
                        raise ValueError("malformed unlocalized boundary return")
                    native_id,pid = int(fields["ion"]),int(fields["particle_id"])
                    consumed = [event for event in consumed_plane_events if event["particle_id"] == pid and event["observation_id"] == fields["observation_id"]]
                    if (not 1 <= native_id <= count or pid != ordered_particle_ids[offset+native_id-1] or len(consumed) != 1
                            or fields["method"] != "unlocalized_consumed_boundary_return"
                            or fields["consumed_direction"] != consumed[0]["direction"]
                            or int(fields["consumed_occurrence"]) != consumed[0]["occurrence"]):
                        raise ValueError("unlocalized boundary return lacks its source event binding")
                    row = {key:float(fields[key]) for key in numbers}
                    if (not all(math.isfinite(value) for value in row.values()) or row["interval_end_us"] <= row["interval_start_us"]
                            or row["interval_start_us"] != consumed[0]["instrument_time_us"]
                            or [row[f"step_start_{a}_mm"] for a in "xyz"] != consumed[0]["position_mm"]):
                        raise ValueError("unlocalized boundary return initial state/bracket differs")
                    row.update(particle_id=pid,observation_id=fields["observation_id"],consumed_direction=fields["consumed_direction"],
                               consumed_occurrence=int(fields["consumed_occurrence"]),method=fields["method"],
                               raw_line_number=line_number,log=str(path))
                    unlocalized.append(row)
                elif "PLANE_OBSERVATION_V1:" in line:
                    pairs = re.findall(r"(\w+)=([^\s]+)", line.split("PLANE_OBSERVATION_V1:", 1)[1])
                    fields = dict(pairs)
                    if len(fields) != len(pairs) or set(fields) != keys:
                        raise ValueError("malformed plane observation V1 fields")
                    native_id, pid, number = int(fields["ion"]), int(fields["particle_id"]), int(fields["occurrence"])
                    if (not 1 <= native_id <= count or pid != ordered_particle_ids[offset+native_id-1]
                            or fields["observation_id"] not in allowed or fields["direction"] not in {"outward", "inward"}
                            or fields["method"] != "accepted_step_linear_interpolation"):
                        raise ValueError("plane observation identity/direction/method differs")
                    row = {key: float(fields[key]) for key in numeric}
                    if not all(math.isfinite(value) for value in row.values()):
                        raise ValueError("nonfinite plane observation")
                    a, b = row["signed_distance_before_mm"], row["signed_distance_after_mm"]
                    if (not row["step_start_instrument_time_us"] <= row["instrument_time_us"] <= row["step_end_instrument_time_us"]
                            or row["step_start_instrument_time_us"] >= row["step_end_instrument_time_us"]
                            or not ((a < 0 <= b) if fields["direction"] == "outward" else (a > 0 >= b))):
                        raise ValueError("plane observation lacks a valid directed accepted-step bracket")
                    sequence = (pid, fields["observation_id"], fields["direction"])
                    key = (*sequence, number)
                    if key in seen or number != occurrence.get(sequence, 0)+1:
                        raise ValueError("plane occurrence duplicate or gap")
                    seen.add(key); occurrence[sequence] = number
                    row.update(particle_id=pid, observation_id=fields["observation_id"], direction=fields["direction"],
                               occurrence=number, method=fields["method"], raw_line_number=line_number, log=str(path))
                    rows.append(row)
        offset += count
    return dict(schema_version=1, role="single_reflection_plane_observations", status="incomplete" if incomplete or unlocalized else "complete",
                localization_method="accepted_step_linear_interpolation", qualification="event_error_not_yet_native_qualified",
                definitions=definitions, rows=rows, incomplete=incomplete, unlocalized_boundary_returns=unlocalized, consumed_plane_events=list(consumed_plane_events))


def _read_accepted_cut_endpoints(path):
    """Read genuine pre-stop other_actions records; never synthesize them."""
    result = {}
    with path.open(encoding="utf-8", errors="strict") as stream:
        for line in stream:
            if "HANDOFF_ACCEPTED_ENDPOINT_V1:" not in line:
                continue
            pairs = re.findall(r"(\w+)=([^\s]+)", line.split("HANDOFF_ACCEPTED_ENDPOINT_V1:", 1)[1])
            fields = dict(pairs)
            if len(fields) != len(pairs) or "particle_id" not in fields:
                raise ValueError("accepted cut endpoint fields differ")
            pid = int(fields["particle_id"])
            if str(pid) != fields["particle_id"] or pid in result:
                raise ValueError("accepted cut endpoint duplicate or inexact ID")
            result[pid] = fields
    return result


def _validate_accepted_cut_endpoint(accepted, stop, event, terminal):
    """V2 explicitly validates END evidence and native START, without tolerance."""
    if accepted is None or set(accepted) != set(stop) | {"raw_ion_splat", "time_step_us"}:
        raise ValueError("cut stop lacks its exact accepted endpoint record")
    if accepted["raw_ion_splat"] != "0" or not math.isfinite(float(accepted["time_step_us"])) or float(accepted["time_step_us"]) <= 0:
        raise ValueError("accepted cut endpoint requires unsplatted callback and positive actual timestep")
    for key in ("observation_id", "ion", "particle_id", "direction", "occurrence", "instance", "event_instrument_time_us"):
        if accepted[key] != stop[key]:
            raise ValueError("accepted cut endpoint identity differs")
    if accepted["method"] != "other_actions_accepted_step_end":
        raise ValueError("accepted cut endpoint method differs")
    numbers = {key: float(accepted[key]) for key in
               ("endpoint_instrument_time_us", "x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us")}
    if not all(math.isfinite(value) for value in numbers.values()):
        raise ValueError("nonfinite accepted cut endpoint")
    if numbers["endpoint_instrument_time_us"] != event["step_end_instrument_time_us"]:
        raise ValueError("accepted cut endpoint time differs from bracket END")
    for name in ("x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us"):
        if numbers[name] != event["step_end_"+name]:
            raise ValueError("accepted cut endpoint 6D differs from bracket END")
    if int(accepted["instance"]) != terminal["instance"]:
        raise ValueError("accepted cut endpoint native instance differs")


def read_cut_stop_events(log_paths, ordered_ids, batch_counts, policy, observations, native_terminals):
    """Bind declared nonloss endpoint stops to raw terminals and plane estimates.

    This does not relocate either state. Ordinary physical terminal facts may
    not coexist with this classification; the caller checks that partition.
    """
    keys = {"observation_id", "ion", "particle_id", "direction", "occurrence", "event_instrument_time_us",
            "endpoint_instrument_time_us", "instance", "x_mm", "y_mm", "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us", "method"}
    result, offset = {}, 0
    for path, count in zip(log_paths, batch_counts, strict=True):
        accepted = _read_accepted_cut_endpoints(path)
        used = set()
        with path.open(encoding="utf-8", errors="strict") as stream:
            for number, line in enumerate(stream, 1):
                version = 2 if "HANDOFF_CUT_STOP_V2:" in line else 1
                prefix = f"HANDOFF_CUT_STOP_V{version}:"
                if prefix not in line:
                    continue
                if policy is None or observations is None:
                    raise ValueError("undeclared handoff cut stop")
                pairs = re.findall(r"(\w+)=([^\s]+)", line.split(prefix, 1)[1])
                fields = dict(pairs)
                if len(fields) != len(pairs) or set(fields) != keys:
                    raise ValueError("cut stop wire fields differ")
                ion, pid = int(fields["ion"]), int(fields["particle_id"])
                instance = int(fields["instance"])
                if instance < 0 or str(instance) != fields["instance"]:
                    raise ValueError("cut stop instance must be an exact native integer")
                if not 1 <= ion <= count or ordered_ids[offset+ion-1] != pid or pid in result:
                    raise ValueError("cut stop duplicate or native/source identity differs")
                if (fields["observation_id"] != policy["observation_id"] or fields["direction"] != "outward"
                        or fields["occurrence"] != "1" or fields["method"] != ("accepted_step_dual_boundary_stop" if version == 2 else "accepted_step_endpoint_stop")):
                    raise ValueError("cut stop policy/event differs")
                numbers = {key: float(fields[key]) for key in keys-{"observation_id", "direction", "method"}}
                if not all(math.isfinite(v) for v in numbers.values()):
                    raise ValueError("nonfinite cut stop")
                events = [row for row in observations["rows"] if row["particle_id"] == pid and
                          row["observation_id"] == policy["observation_id"] and row["direction"] == "outward" and row["occurrence"] == 1]
                if len(events) != 1:
                    raise ValueError("cut stop lacks its unique original plane event")
                event, terminal = events[0], native_terminals[pid]
                endpoint = numbers["endpoint_instrument_time_us"]
                boundary = "start" if version == 2 else "end"
                if version == 2:
                    _validate_accepted_cut_endpoint(accepted.get(pid), fields, event, terminal)
                    used.add(pid)
                if (numbers["event_instrument_time_us"] != event["instrument_time_us"]
                        or endpoint != event["step_"+boundary+"_instrument_time_us"]
                        or endpoint != terminal["instrument_time_us"] or numbers["instance"] != terminal["instance"]):
                    raise ValueError("cut stop event/bracket/raw endpoint identity differs")
                for axis in "xyz":
                    for name, bracket in ((axis+"_mm", "step_"+boundary+"_"+axis+"_mm"),
                                          ("v"+axis+"_mm_per_us", "step_"+boundary+"_v"+axis+"_mm_per_us")):
                        native_key = axis+"_mm" if name == axis+"_mm" else "v"+axis+"_mm_per_us"
                        if numbers[name] != event[bracket] or numbers[name] != terminal[native_key]:
                            raise ValueError("cut stop actual endpoint differs from raw 6D/bracket")
                result[pid] = dict(particle_id=pid, category="handoff_cut_stop", terminal_event="handoff_cut_stop",
                    instance_id=int(numbers["instance"]), terminal_instrument_time_us=endpoint,
                    observation_id=policy["observation_id"], direction="outward", occurrence=1,
                    event_instrument_time_us=numbers["event_instrument_time_us"],
                    method=fields["method"], native_termination_boundary=boundary,
                    accepted_endpoint=(accepted[pid] if version == 2 else None),
                    log=str(path), raw_line_number=number,
                    **{k:numbers[k] for k in ("x_mm","y_mm","z_mm","vx_mm_per_us","vy_mm_per_us","vz_mm_per_us")})
        if set(accepted) != used:
            raise ValueError("accepted cut endpoint lacks its unique V2 stop")
        offset += count
    return result


from msplatform.contracts.particle_state import binary64_serialization_close


_close = binary64_serialization_close
_X_EVENTS = {'multipole_handoff', 'accelerator_sidewall_inner_forward', 'accelerator_axis_forward'}
_BRACKET = ('step_start_instrument_time_us', 'step_end_instrument_time_us', 'step_start_x_mm', 'step_end_x_mm')


def _matches_verified_cut_observation(row, window):
    """Only the exact original plane estimate can outlive a V2 raw START.

    The caller supplies windows only after dual-endpoint and physical-terminal
    exclusion validation. This is observation validity, not a native lifetime
    extension or a replacement terminal state.
    """
    if window is None or row['event'] not in _X_EVENTS:
        return False
    fields = ('instrument_time_us', 'x_mm', 'y_mm', 'z_mm',
              'vx_mm_per_us', 'vy_mm_per_us', 'vz_mm_per_us', *_BRACKET)
    return all(key in row and row[key] == window[key] for key in fields)


def _validate_states(rows: list[dict], source: dict, terminals: dict, locations: dict, log: Path,
                     *, cut_observation_windows=None) -> None:
    for row in rows:
        pid, event = row['particle_id'], row['event']
        where = f"{log}:{row.get('raw_line_number', locations.get((pid, event), '?'))}: particle {pid} {event}"
        if any(not math.isfinite(value) for value in row.values() if isinstance(value, (int, float))):
            raise ValueError(f'{where}: nonfinite canonical state')
        birth = float(source[pid]['instrument_time_us'])
        end = terminals[pid]['instrument_time_us']
        if end < birth and not _close(end, birth):
            raise ValueError(f'{where}: native terminal precedes birth')
        # Detector crossing is the provider's projected disk intercept, not a
        # second native endpoint; its time may differ from the actual stop.
        if event != 'detector_crossing':
            t = row['instrument_time_us']
            before_birth = t < birth and not _close(t, birth)
            after_terminal = t > end and not _close(t, end)
            window = (cut_observation_windows or {}).get(pid)
            if before_birth or (after_terminal and not _matches_verified_cut_observation(row, window)):
                raise ValueError(f'{where}: state time {t:.17g} outside native lifetime [{birth:.17g},{end:.17g}]')
        if event == 'source_release':
            expected = dict(instrument_time_us=birth)
            expected.update({f'{a}_mm': float(source[pid][f'position_{a}_mm']) for a in 'xyz'})
            expected.update({f'v{a}_mm_per_us': float(source[pid][f'velocity_{a}_m_s']) / 1000 for a in 'xyz'})
            if any(not _close(row[key], value) for key, value in expected.items()):
                raise ValueError(f'{where}: actual birth differs from frozen source/clock')
        if event in _X_EVENTS:
            if not all(key in row for key in _BRACKET):
                raise ValueError(f'{where}: actual native X crossing bracket is missing')
            t0, t1, x0, x1 = (row[key] for key in _BRACKET)
            t = row['instrument_time_us']
            if not t0 <= t <= t1 or t1 <= t0 or not x0 <= row['x_mm'] <= x1 or x1 <= x0:
                raise ValueError(f'{where}: invalid forward native X crossing bracket')


def collect_tracking_logs(log_paths, *, source_rows: dict, source_provenance: dict,
                          flight: dict, batches: Sequence[dict]) -> dict:
    """Collect verified native logs without a checkout, payload or solver.

    The caller binds log/control/source records and native natural-exit facts.
    Source rows are execution-cohort canonical states in the native world frame;
    instrument_time_us is each actual release/start, not original mother birth.
    Full mother/birth/weight/clock records remain in source_provenance unchanged.
    This parser preserves the existing single-species and nonempty-flight scope.
    It does not locate exact physical crossings or grant numerical qualification.
    """
    source, provenance, cases = source_rows, source_provenance, list(batches)
    if not cases or len(log_paths) != len(cases):
        raise ValueError('tracking logs and batch declarations differ')
    logs, counts, seen = [], [], []
    terminals, locations, pulse_states, shared_states = {}, {}, [], []
    ordered_ids = list(source)
    for case, path in zip(cases, log_paths, strict=True):
        low, high = case['source_row_range']
        ids = ordered_ids[low-1:high]
        if ids != case['expected_particle_ids'] or not 1 <= low <= high <= len(source):
            raise ValueError('batch original-ID/source-row binding differs')
        seen.extend(ids)
        path = Path(path).resolve(strict=True)
        part = read_native_evidence(path, {pid:source[pid] for pid in ids}, flight)
        terminals.update(part[0]); locations.update(part[1])
        pulse_states.extend(part[2]); shared_states.extend(part[3])
        logs.append(path); counts.append(len(ids))
    if seen != ordered_ids or len(set(seen)) != len(seen):
        raise ValueError('batch logs duplicate or omit execution cohort IDs')
    log = logs[0]
    masses = {float(row['mass_amu']) for row in source.values()}
    if len(masses) != 1 or min(masses) <= 0:
        raise ValueError('existing single-flight analyzer requires one positive ion mass')
    plane_definitions = [case.get('build_metadata', {}).get('plane_observations') for case in cases]
    if any(value != plane_definitions[0] for value in plane_definitions):
        raise ValueError('batch plane observation definitions differ')
    consumed = [event for case in cases for event in case.get('build_metadata', {}).get('consumed_plane_events', [])]
    plane_observation = (read_plane_observations(logs, list(source), counts, plane_definitions[0], consumed_plane_events=consumed)
                         if plane_definitions[0] is not None else None)
    policies = [case.get('build_metadata', {}).get('propagation_stop') for case in cases]
    if any(value != policies[0] for value in policies):
        raise ValueError('batch propagation stop policies differ')
    stop_policy = policies[0]
    validate_propagation_stop(stop_policy, plane_definitions[0])
    if stop_policy is not None and (provenance.get('schema_version') != 2 or provenance.get('state_kind') != 'source_birth'):
        raise ValueError('segmented upstream cut stop requires a modern source_birth')
    cut_stops = read_cut_stop_events(logs, list(source), counts, stop_policy, plane_observation, terminals)
    evidence = read_native_events(logs, masses.pop(), list(source), counts)
    cut_observation_windows = {}
    if stop_policy is not None:
        mother_births = {row['particle_id']:row['particle_birth_time_us'] for row in provenance['mother_records']}
        deadlines = {}
        for case in cases:
            low,high = case['source_row_range']
            ids = ordered_ids[low-1:high]
            clock = case.get('build_metadata',{}).get('source_clock',{})
            ends, births = clock.get('absolute_deadlines_us'),clock.get('original_birth_times_us')
            if (not isinstance(ends,list) or not isinstance(births,list) or len(ends)!=len(ids) or len(births)!=len(ids)
                    or births != [mother_births[pid] for pid in ids]
                    or births != [float(source[pid]['instrument_time_us']) for pid in ids]
                    or any(type(end) not in (int,float) or not math.isfinite(end) or end<=birth for end,birth in zip(ends,births,strict=True))):
                raise ValueError('cut stop requires actual birth and absolute deadline metadata for every native row')
            deadlines.update(zip(ids,ends,strict=True))
        for pid, stop in cut_stops.items():
            if stop['event_instrument_time_us'] > deadlines[pid]:
                raise ValueError('cut stop event is after the frozen absolute deadline')

            if pid in evidence['terminal_outcomes']:
                raise ValueError('physical terminal cannot be overwritten by handoff cut stop')
            evidence['terminal_outcomes'][pid] = stop
            if stop['accepted_endpoint'] is not None:
                # read_cut_stop_events already proved the unique original event
                # and both raw boundaries; a physical terminal above still wins.
                cut_observation_windows[pid] = next(row for row in plane_observation['rows']
                    if row['particle_id'] == pid and row['observation_id'] == stop['observation_id']
                    and row['direction'] == stop['direction'] and row['occurrence'] == stop['occurrence'])
        for terminal in evidence['terminal_outcomes'].values():
            if terminal['category'] == 'timeout_splat':
                if terminal['terminal_instrument_time_us'] < deadlines[terminal['particle_id']]:
                    raise ValueError('deadline censor precedes the frozen absolute deadline')
                terminal['raw_terminal_category'] = 'timeout_splat'
                terminal['category'] = 'censored_no_handoff_by_deadline'
        evidence['propagation_scope'] = 'segmented_upstream'

    census = canonical_census(evidence, list(source), pulse_time_us=flight['pulse'].get('time_us'))
    if stop_policy is not None:
        census['analysis_scope'] = 'segmented_upstream_complete_mother_and_declared_cut'
        census['terminal_taxonomy']['role'] = 'segmented_upstream_terminal_taxonomy'
    rows = evidence['rows']
    _validate_states(rows, source, terminals, locations, log,
                     cut_observation_windows=cut_observation_windows)
    _validate_states(pulse_states, source, terminals, locations, log)
    _validate_states(shared_states, source, terminals, locations, log)
    if any(not math.isfinite(value) for row in census['terminal_taxonomy']['particle_outcomes']
           for value in row.values() if isinstance(value, (int, float))):
        raise ValueError('nonfinite terminal classification')
    for row in census['terminal_taxonomy']['particle_outcomes']:
        if row['instance_id'] != terminals[row['particle_id']]['instance']:
            raise ValueError(f"particle {row['particle_id']}: terminal classification/native instance differ")
    result = dict(census=census, canonical_events=rows, native_pulse_states=pulse_states,
                  native_shared_states=shared_states, native_terminals=[terminals[pid] for pid in source],
                  native_complete=True)
    if plane_observation is not None:
        result['plane_observations'] = plane_observation
    if stop_policy is not None:
        result.update(propagation_stop=stop_policy, propagation_scope='segmented_upstream',
                      handoff_stop_basis='interpolated crossing separate from actual accepted endpoint',
                      observation_complete=plane_observation['status']=='complete')
    if provenance.get('schema_version') == 2:
        result['original_mother'] = {key: provenance[key] for key in
            ('mother_particle_ids', 'mother_records', 'mother_fates', 'clock_authority_sha256', 'clock_records')}
    return result
