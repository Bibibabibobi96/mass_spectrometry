"""Convert explicit COMSOL 6.4 particle observations into SI result records.

COMSOL `mphparticle`: https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_ref.9.51.html
`cpt.fs` and `cpt.st`: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html
Consulted 2026-11-27. Native index is mapped through the frozen release table;
coordinates are never used to guess an electrode or terminal entity.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

import numpy as np
from msplatform.results.model import TraceResult

_COLUMNS = ('particle_id', 'native_particle_index', 'instrument_time_us', 'x_mm', 'y_mm', 'z_mm',
            'vx_m_per_s', 'vy_m_per_s', 'vz_m_per_s', 'state_present', 'solver_raw_status', 'solver_stop_time_us')


def read_observations(path: Path, *, initial_states: list[dict], epoch_us: float, backend_version: str,
                      observation_times_us: list[float], position_atol_m: float, velocity_atol_m_s: float,
                      boundary_policy: str, detector_contract: dict | None = None) -> TraceResult:
    """Read published native rows with exact IDs and classify missing facts explicitly.

    A verified Freeze wall preserves impact 6D; missing or other stopped states
    are not inferred from coordinates or an unsupported wall condition.
    """
    if not isinstance(initial_states, list) or not initial_states or not isinstance(backend_version, str) or not backend_version:
        raise ValueError('explicit nonempty source and COMSOL version required')
    if type(epoch_us) not in (int, float) or not math.isfinite(epoch_us):
        raise ValueError('epoch must be finite')
    if boundary_policy != 'metal_and_outer_freeze_ideal_pass':
        raise ValueError('validated COMSOL freeze/pass boundary policy is required')
    if (not isinstance(observation_times_us, list) or len(observation_times_us) < 2
            or any(type(t) not in (int, float) or not math.isfinite(t) for t in observation_times_us)
            or any(a >= b for a, b in zip(observation_times_us, observation_times_us[1:]))
            or any(type(t) not in (int, float) or not math.isfinite(t) or t <= 0
                   for t in (position_atol_m, velocity_atol_m_s))):
        raise ValueError('explicit observation times and physical birth tolerances are required')
    source = {p['particle_id']: dict(p) for p in initial_states}
    if len(source) != len(initial_states) or any(type(pid) is not int or pid <= 0 for pid in source):
        raise ValueError('source particle IDs must be unique positive integers')
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        columns = tuple(reader.fieldnames or ())
        monitored = columns == (*_COLUMNS, 'detector_flag')
        if columns != _COLUMNS and not monitored:
            raise ValueError('COMSOL particle columns differ from the native contract')
        if monitored != (detector_contract is not None):
            raise ValueError('native detector flags require their verified detector contract')
        if monitored and (not isinstance(detector_contract, dict) or
                detector_contract.get('surface_id') != 'detector_active_face' or
                not detector_contract.get('instance_id') or not detector_contract.get('member_id')):
            raise ValueError('verified detector contract is invalid')
        rows = list(reader)
    grouped: dict[int, list[dict[str, Any]]] = {pid: [] for pid in source}
    indices = {}
    for raw in rows:
        try:
            pid, idx, present, status = (int(raw[k]) for k in ('particle_id', 'native_particle_index', 'state_present', 'solver_raw_status'))
            time = float(raw['instrument_time_us'])
            stop = float(raw['solver_stop_time_us'])
            state = [float(raw[k]) for k in _COLUMNS[3:9]]
            detector_flag = float(raw['detector_flag']) if monitored else None
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError('invalid native particle observation') from error
        if (pid not in source or idx < 1 or present not in (0, 1) or status not in range(5)
                or not math.isfinite(time) or (present and not all(math.isfinite(v) for v in state))):
            raise ValueError('native particle identity, state or status invalid')
        if pid in indices and indices[pid] != idx or idx in indices.values() and indices.get(pid) != idx:
            raise ValueError('native particle index mapping changed or duplicated')
        indices[pid] = idx
        grouped[pid].append({'time_s': (time - epoch_us) * 1e-6, 'state': state, 'present': bool(present),
                             'status': status, 'stop_s': (stop - epoch_us) * 1e-6 if math.isfinite(stop) else None,
                             'detector_flag': detector_flag})
    terminals, samples, missing, detector_missing, events = [], [], [], [], []
    for pid, initial in source.items():
        entries = grouped[pid]
        if any(a['time_s'] >= b['time_s'] for a, b in zip(entries, entries[1:])):
            raise ValueError('native observation times must strictly increase per particle')
        if not entries or not entries[0]['present']:
            raise ValueError('native original birth record is missing')
        start = entries[0]
        if (start['time_s'] != initial['time_s']
                or any(abs(v * 1e-3 - expected) > position_atol_m for v, expected in zip(start['state'][:3], initial['position_m'], strict=True))
                or any(abs(v - expected) > velocity_atol_m_s for v, expected in zip(start['state'][3:], initial['velocity_m_s'], strict=True))):
            raise ValueError('native initial state does not match frozen original birth')
        for row in entries:
            if row['present']:
                samples.append((pid, row['time_s'], [v * 1e-3 for v in row['state'][:3]], row['state'][3:]))
        final = entries[-1] if entries else None
        # COMSOL 6.4 Freeze preserves both position and velocity after impact.
        # The entity remains unknown; no electrode is inferred from coordinates.
        expected_times = [(t - epoch_us) * 1e-6 for t in observation_times_us]
        complete_samples = bool(final and final['present'] and [item['time_s'] for item in entries] == expected_times)
        active = bool(complete_samples and final['status'] == 1 and all(item['present'] for item in entries))
        frozen = bool(complete_samples and final['status'] == 2 and final['stop_s'] is not None
                      and initial['time_s'] <= final['stop_s'] <= final['time_s'])
        complete = active or frozen
        if not complete:
            missing.append(pid)
            if monitored:
                detector_missing.append(pid)
            continue
        if monitored:
            flags = [entry['detector_flag'] for entry in entries]
            if any(flag not in (0.0, 1.0) for flag in flags) or any(a > b for a, b in zip(flags, flags[1:])):
                detector_missing.append(pid)
                detected = False
            else:
                detected = flags[-1] == 1.0
                if detected and not frozen:
                    raise ValueError('native detector flag contradicts terminal Freeze status')
        else:
            detected = False
        state = final['state'] if complete else None
        terminals.append({'particle_id': pid, 'species_id': initial['species_id'],
                          'position_m': None if state is None else [v * 1e-3 for v in state[:3]],
                          'velocity_m_s': None if state is None else state[3:],
                          'time_s': final['stop_s'] if frozen else final['time_s'],
                          'physical_outcome': 'unknown', 'stop_reason': 'normal' if frozen else 'time_limit',
                          'started': bool(final and final['status'] != 0), 'component_id': None, 'electrode_id': None, 'surface_id': None,
                          'attribution_method': 'unavailable', 'attribution_status': 'unavailable',
                          'backend_version': backend_version, 'native_termination_code': None if final is None else str(final['status']),
                          'native_entity_id': None, 'detail': None if final is None else f"native_stop_time_s={final['stop_s']}"})
        if detected:
            terminal = terminals[-1]
            terminal.update(physical_outcome='detected', component_id=detector_contract['instance_id'],
                            electrode_id=detector_contract['member_id'], surface_id=detector_contract['surface_id'],
                            attribution_method='native_detector_wall_auxiliary', attribution_status='known')
            normal_velocity = sum(a * b for a, b in zip(terminal['velocity_m_s'], detector_contract['normal'], strict=True))
            direction = (normal_velocity > 0) - (normal_velocity < 0)
            event = dict(terminal, event_kind='detector', event_sequence=1, crossing_direction=direction)
            events.append(event)
    arrays = {'particle_id': np.array([s[0] for s in samples], dtype=np.int64),
              'time_s': np.array([s[1] for s in samples], dtype=np.float64),
              'position_m': np.array([s[2] for s in samples], dtype=np.float64).reshape(-1, 3),
              'velocity_m_s': np.array([s[3] for s in samples], dtype=np.float64).reshape(-1, 3)}
    from msplatform.results.detector_observation import detector_observation
    detector_status = ('unavailable' if not monitored else 'incomplete' if detector_missing else 'complete')
    detector_reason = ('detector_observation_unsupported' if not monitored else
                       'detector_observation_incomplete' if detector_missing else None)
    return TraceResult(list(source.values()), terminals, events, arrays, 'succeeded',
                       {'status': 'incomplete' if missing or detector_missing else 'complete', 'mother_count': len(source),
                        'terminal_record_count': len(terminals), 'missing_terminal_particle_ids': missing,
                        'missing_detector_observation_particle_ids': detector_missing,
                        'detector_observation': detector_observation(detector_status, sorted(source),
                            missing_particle_ids=detector_missing, reason=detector_reason)})
