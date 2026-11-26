"""Convert verified SIMION collection facts into solver-neutral SI records."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from msplatform.contracts.particle_state import binary64_serialization_close
from msplatform.physics import CONSTANTS
from msplatform.results.model import TraceResult


def _unique(rows: Sequence[Mapping[str, Any]], label: str) -> dict[int, Mapping[str, Any]]:
    result = {}
    for row in rows:
        pid = row['particle_id']
        if type(pid) is not int or pid <= 0 or pid in result:
            raise ValueError(f'{label} has invalid or duplicate particle identity')
        result[pid] = row
    return result


def _close(a: float, b: float) -> bool:
    return binary64_serialization_close(float(a), float(b))


def _coordinates(row: Mapping[str, Any]) -> tuple[list[float], list[float], float]:
    values = [float(row[key]) for key in ('x_mm', 'y_mm', 'z_mm',
              'vx_mm_per_us', 'vy_mm_per_us', 'vz_mm_per_us', 'instrument_time_us')]
    if not all(math.isfinite(x) for x in values):
        raise ValueError('native state must contain finite 6D and experiment time')
    return [x * 1e-3 for x in values[:3]], [v * 1e3 for v in values[3:6]], values[6] * 1e-6


def _snapshot_matches_source(snapshot: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    return (_close(snapshot['instrument_time_us'], row['instrument_time_us']) and
            all(_close(snapshot[f'{axis}_mm'], row[f'position_{axis}_mm']) and
                _close(snapshot[f'v{axis}_mm_per_us'], row[f'velocity_{axis}_m_s'] / 1000)
                for axis in 'xyz'))


def _state_row(pid: int, species: str, state: Mapping[str, Any], *, backend_version: str) -> dict[str, Any]:
    position, velocity, time = _coordinates(state)
    return dict(particle_id=pid, species_id=species, position_m=position, velocity_m_s=velocity, time_s=time,
                physical_outcome='unknown', stop_reason='normal', component_id=None, electrode_id=None,
                surface_id=None, attribution_method='unavailable', attribution_status='unavailable', started=True,
                backend_version=backend_version, native_termination_code=None, native_entity_id=None, detail=None)


def adapt_native_results(source_rows: Mapping[int, Mapping[str, Any]], collection: Mapping[str, Any], *,
                         backend_version: str, observation_bindings: Mapping[str, Mapping[str, Any]],
                         observation_times_us: Sequence[float], constants: Mapping[str, Any],
                         detector_instance: int) -> TraceResult:
    """Adapt collector-verified primary births and actual native 6D records.

    Each plane ID is explicitly bound to component/surface/electrode and kind;
    missing or contradictory native evidence raises instead of inventing outcomes.
    """
    if not isinstance(backend_version, str) or not backend_version:
        raise ValueError('native backend version is required')
    if not isinstance(constants, Mapping) or dict(constants) != dict(CONSTANTS):
        raise ValueError('native conversion requires the explicitly frozen supported constant set')
    if type(detector_instance) is not int or detector_instance <= 0:
        raise ValueError('detector workbench instance must be explicitly bound')
    ids = list(source_rows)
    if not ids or any(type(pid) is not int or pid <= 0 for pid in ids):
        raise ValueError('frozen source requires unique positive particle IDs')
    if collection.get('native_complete') is not True or collection.get('observation_complete') is False:
        raise ValueError('incomplete native execution or observation evidence')
    terminal = _unique(collection['native_terminals'], 'native terminals')
    taxonomy = _unique(collection['census']['terminal_taxonomy']['particle_outcomes'], 'terminal taxonomy')
    evidence = collection['terminal_evidence']
    if evidence.get('status') != 'recorded_v1':
        raise ValueError('verified V1 actual native birth/terminal evidence is required')
    raw = _unique(evidence['particle_evidence'], 'terminal evidence')
    if any(set(part) != set(ids) for part in (terminal, taxonomy, raw)):
        raise ValueError('source, terminal, taxonomy and actual birth identities must close')
    for name, binding in observation_bindings.items():
        if (not isinstance(name, str) or not name or set(binding) != {'component_id','surface_id','electrode_id','kind'}
                or not all(isinstance(binding[k], str) and binding[k] for k in ('component_id','surface_id'))
                or binding['kind'] not in {'detector','observation'}
                or (binding['electrode_id'] is not None and not isinstance(binding['electrode_id'], str))):
            raise ValueError('plane identity binding is incomplete or invalid')
    requested = list(observation_times_us)
    if any(type(t) not in (int, float) or not math.isfinite(t) for t in requested) or requested != sorted(set(requested)):
        raise ValueError('selected experiment times must be unique, finite and sorted')
    planes = collection.get('plane_observations', {'status': 'complete', 'rows': []})
    if planes.get('status') != 'complete':
        raise ValueError('plane observations are incomplete')
    by_particle: dict[int, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {pid: [] for pid in ids}
    for row in planes['rows']:
        pid, name = row['particle_id'], row['observation_id']
        if pid not in by_particle or name not in observation_bindings or row['direction'] not in {'inward','outward'}:
            raise ValueError('plane observation identity/direction lacks its explicit binding')
        by_particle[pid].append((row, observation_bindings[name]))
    samples = {}
    for row in collection.get('native_shared_states', []):
        key = (row['particle_id'], row['instrument_time_us'])
        if key[0] not in source_rows or key[1] not in requested or key in samples:
            raise ValueError('native trajectory sample identity/time is undeclared or duplicate')
        if not source_rows[key[0]]['instrument_time_us'] <= key[1] <= terminal[key[0]]['instrument_time_us']:
            raise ValueError('native trajectory sample is outside the actual lifetime')
        samples[key] = row
    detector_events = _unique([row for row in collection.get('canonical_events', [])
                               if row.get('event') == 'detector_crossing'], 'native detector events')
    if not set(detector_events) <= set(ids):
        raise ValueError('native detector event references a foreign particle')
    initial_rows, terminal_rows, event_rows, sample_rows, missing_detector = [], [], [], [], []
    for pid in ids:
        source = source_rows[pid]
        if source.get('particle_id') != pid or source.get('parent_particle_id') is not None or source.get('generation') != 0:
            raise ValueError('only explicitly identified primary births are supported')
        record = raw[pid]['raw']
        phases = {item['event']: item for item in record['records']}
        if record.get('status') != 'recorded_v1' or len(phases) != len(record['records']):
            raise ValueError('native callback evidence is incomplete or duplicated')
        if 'initialize' not in phases or 'terminate' not in phases or not _snapshot_matches_source(phases['initialize'], source):
            raise ValueError('actual native birth differs from frozen source')
        native_terminal, final = terminal[pid], phases['terminate']
        if any(not _close(final[k], native_terminal[k]) for k in ('instrument_time_us','x_mm','y_mm','z_mm','vx_mm_per_us','vy_mm_per_us','vz_mm_per_us')) or final['instance'] != native_terminal['instance']:
            raise ValueError('terminal 6D callback differs from collected native terminal')
        species = source['species_id']
        mass = float(source['mass_amu']) * CONSTANTS['atomic_mass_constant_kg']
        charge_state, weight = source['charge_state'], float(source['particle_weight'])
        if type(charge_state) is not int or charge_state == 0 or mass <= 0 or not math.isfinite(mass) or not math.isfinite(weight) or weight <= 0:
            raise ValueError('native species mass/charge/weight invalid')
        start_p, start_v, start_t = _coordinates(phases['initialize'])
        initial_rows.append(dict(particle_id=pid, species_id=species, position_m=start_p, velocity_m_s=start_v,
                                 time_s=start_t, mass_kg=mass, charge_state=charge_state,
                                 charge_c=charge_state * CONSTANTS['elementary_charge_c'], weight=weight,
                                 parent_particle_id=None, lineage_status='primary_birth'))
        end_time = float(native_terminal['instrument_time_us'])
        if end_time < source['instrument_time_us']:
            raise ValueError('native terminal precedes actual birth')
        crossings = sorted(by_particle[pid], key=lambda entry: (entry[0]['instrument_time_us'], entry[0]['observation_id']))
        detection = [(row, binding) for row, binding in crossings if binding['kind'] == 'detector']
        native_detector = taxonomy[pid]['category'] == 'detector_crossing'
        if native_detector:
            if pid not in detector_events or native_terminal['instance'] != detector_instance:
                raise ValueError('native detector taxonomy lacks its bound detector instance/event')
            if len(detection) != 1:
                missing_detector.append(pid)
        elif pid in detector_events:
            raise ValueError('native detector event conflicts with terminal taxonomy')
        detected = native_detector and len(detection) == 1
        result = _state_row(pid, species, native_terminal, backend_version=backend_version)
        result['native_termination_code'] = None if final['splat'] is None else str(final['splat'])
        category = taxonomy[pid]['category']
        result['detail'] = 'native_category=' + str(category) + '; native_instance=' + str(native_terminal['instance'])
        if category in {'programmatic_age_stop', 'programmatic_deadline_stop', 'timeout_splat'}:
            result['stop_reason'] = 'time_limit'
        if detected:
            binding = detection[0][1]
            result.update(physical_outcome='detected', component_id=binding['component_id'],
                          electrode_id=binding['electrode_id'], surface_id=binding['surface_id'],
                          attribution_method='declared_plane_observation', attribution_status='known')
        terminal_rows.append(result)
        for index, (row, binding) in enumerate(crossings, start=1):
            if not source['instrument_time_us'] <= row['instrument_time_us'] <= end_time:
                raise ValueError('plane observation outside native lifetime')
            event = _state_row(pid, species, row, backend_version=backend_version)
            event.update(event_kind=binding['kind'], event_sequence=index,
                         crossing_direction=1 if row['direction'] == 'outward' else -1,
                         component_id=binding['component_id'], electrode_id=binding['electrode_id'],
                         surface_id=binding['surface_id'], attribution_method=row['method'], attribution_status='known')
            event_rows.append(event)
        for time in requested:
            if source['instrument_time_us'] <= time <= end_time:
                key = (pid, time)
                if key not in samples:
                    raise ValueError('selected native trajectory observation is missing')
                sample_rows.append((pid, *_coordinates(samples[key])))
    trajectories = {'particle_id': np.array([r[0] for r in sample_rows], dtype=np.int64),
                    'time_s': np.array([r[3] for r in sample_rows], dtype=np.float64),
                    'position_m': np.array([r[1] for r in sample_rows], dtype=np.float64).reshape(-1, 3),
                    'velocity_m_s': np.array([r[2] for r in sample_rows], dtype=np.float64).reshape(-1, 3)}
    return TraceResult(initial_rows, terminal_rows, event_rows, trajectories, 'succeeded',
                       {'status': 'incomplete' if missing_detector else 'complete', 'mother_count': len(ids),
                        'terminal_record_count': len(ids), 'missing_terminal_particle_ids': [],
                        'missing_detector_observation_particle_ids': missing_detector})
