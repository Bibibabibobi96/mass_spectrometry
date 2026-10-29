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

from common.contracts.particle_physics import kinetic_energy_ev
from common.simion.native_completion import parse_fly_completed_line
from integrations.runtime.single_flight_source import binary64_serialization_close as _close

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
