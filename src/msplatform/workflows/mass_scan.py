"""Mass-scan orchestration over the existing canonical release and result contracts."""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from msplatform.ion_release.authoring import sample_release
from msplatform.results.model import TraceResult
from msplatform.results.particle_data import _validate_records, summarize_particle_data


def prepare_mass_scan(request: Mapping[str, Any]) -> list:
    """Freeze one canonical realization per species with globally unique IDs.

    Omitted IDs allocate the lowest unused positive integers in species order.
    Explicit weight maps for omitted IDs use the sampler's local IDs 1..N.
    Each returned realization records its actual ID mapping and source specification.
    """
    if (not isinstance(request, Mapping) or set(request) != {'schema_version', 'role', 'species_requests'}
            or type(request['schema_version']) is not int or request['schema_version'] != 1
            or request['role'] != 'canonical_mass_scan_request'
            or not isinstance(request['species_requests'], list) or not request['species_requests']):
        raise ValueError('mass scan requires a nonempty canonical species request list')
    requests = copy.deepcopy(request['species_requests'])
    if any(not isinstance(row, dict) for row in requests):
        raise ValueError('species requests must be objects')
    species = [row.get('species_id') for row in requests]
    if any(not isinstance(x, str) or not x.strip() for x in species) or len(set(species)) != len(species):
        raise ValueError('mass scan species IDs must be nonempty and unique')
    if any(row.get('clock') != requests[0].get('clock') for row in requests):
        raise ValueError('mass scan species must share the same clock identity')
    used = set()
    for row in requests:
        ids = row.get('particle_ids')
        if ids is not None:
            if (not isinstance(ids, list) or any(type(pid) is not int or not 0 < pid < 2**63 for pid in ids)
                    or len(set(ids)) != len(ids) or used.intersection(ids)):
                raise ValueError('explicit mass scan particle IDs must be globally unique positive int64')
            used.update(ids)
    next_id = 1
    for row in requests:
        if row.get('particle_ids') is not None:
            continue
        count = row.get('release_spec', {}).get('particle_count')
        if type(count) is not int or count <= 0:
            raise ValueError('species particle_count must be positive integer')
        ids = []
        while len(ids) < count:
            if next_id >= 2**63:
                raise ValueError('mass scan particle IDs exceed int64')
            if next_id not in used:
                ids.append(next_id)
                used.add(next_id)
            next_id += 1
        weights = row.get('relative_weights')
        if weights is not None:
            if not isinstance(weights, Mapping) or set(weights) != {str(i) for i in range(1, count + 1)}:
                raise ValueError('implicit ID weights must use canonical species-local keys 1..N')
            row['relative_weights'] = {str(pid): weights[str(i)] for i, pid in enumerate(ids, 1)}
        row['particle_ids'] = ids
    return [sample_release(row) for row in requests]


def merge_mass_scan(results: Sequence[TraceResult]) -> TraceResult:
    """Combine complete independent batches while preserving every original ID."""
    if not isinstance(results, Sequence) or not results:
        raise ValueError('mass scan requires nonempty batch results')
    initial, terminal, events, arrays, seen, lineages = [], [], [], [], set(), set()
    for result in results:
        if not isinstance(result, TraceResult) or result.execution_status != 'succeeded' or result.data_integrity.get('status') != 'complete':
            raise ValueError('mass scan cannot merge failed or incomplete batches')
        ids = [r['particle_id'] for r in result.initial_states]
        terminal_ids = [r['particle_id'] for r in result.terminal_states]
        if (not ids or any(type(pid) is not int or pid <= 0 for pid in ids) or len(ids) != len(set(ids))
                or seen.intersection(ids) or len(terminal_ids) != len(set(terminal_ids)) or set(terminal_ids) != set(ids)):
            raise ValueError('batch mother and terminal IDs must close uniquely')
        if any(row['stop_reason'] in {'cancelled', 'numerical_failure'} or not row['started']
               or row['time_s'] is None for row in result.terminal_states):
            raise ValueError('batch contains an unsuccessful or missing terminal record')
        identity = {row['particle_id']: row['species_id'] for row in result.initial_states}
        if any(row['particle_id'] not in identity or row['species_id'] != identity[row['particle_id']]
               for row in [*result.terminal_states, *result.events]):
            raise ValueError('batch event or terminal species identity disagrees with its mother')
        trajectory = result.trajectories
        if set(trajectory) != {'particle_id', 'time_s', 'position_m', 'velocity_m_s'}:
            raise ValueError('invalid trajectory columns')
        n = len(trajectory['particle_id'])
        if any(np.asarray(trajectory[k]).shape != ((n, 3) if k in {'position_m','velocity_m_s'} else (n,)) for k in trajectory):
            raise ValueError('invalid trajectory shapes')
        if any(np.asarray(trajectory[k]).dtype != np.dtype('int64' if k == 'particle_id' else 'float64')
               or not np.all(np.isfinite(trajectory[k])) for k in trajectory):
            raise ValueError('invalid trajectory types or values')
        if not set(map(int, trajectory['particle_id'])) <= set(ids):
            raise ValueError('trajectory contains foreign particle IDs')
        lineage = {row.get('lineage_status') for row in result.initial_states}
        if lineage not in ({'primary_birth'}, {'unavailable_initial_snapshot'}):
            raise ValueError('batch initial lineage is unsupported or mixed')
        lineages.update(lineage)
        if len(lineages) != 1:
            raise ValueError('batch initial lineage contracts disagree')
        _validate_records(dict(schema_version=2 if lineage == {'primary_birth'} else 1,
            execution_status=result.execution_status, initial_states=result.initial_states,
            terminal_states=result.terminal_states, events=result.events, trajectories=trajectory))
        seen.update(ids)
        initial.extend(copy.deepcopy(result.initial_states))
        terminal.extend(copy.deepcopy(result.terminal_states))
        events.extend(copy.deepcopy(result.events))
        arrays.append(trajectory)
    merged = {key: np.concatenate([np.asarray(a[key]) for a in arrays], axis=0) for key in arrays[0]}
    from msplatform.results.detector_observation import merge_detector_observations
    batch_integrity = [result.data_integrity for result in results]
    coverage = merge_detector_observations([(result.initial_states, result.data_integrity) for result in results])
    return TraceResult(initial, terminal, events, merged, 'succeeded',
                       dict(status='complete', mother_count=len(initial), terminal_record_count=len(terminal),
                            missing_terminal_particle_ids=[], batch_integrity=batch_integrity,
                            detector_observation=coverage))


def analyze_mass_scan(data: Mapping[str, Any]) -> dict[str, Any]:
    """Report cohort detection and analysis admission independently of tracking."""
    lineage = {row.get('lineage_status') for row in data['initial_states']}
    if lineage not in ({'primary_birth'}, {'unavailable_initial_snapshot'}):
        raise ValueError('analysis requires one supported initial lineage contract')
    _validate_records(dict(data, schema_version=2 if lineage == {'primary_birth'} else 1))
    summary = summarize_particle_data(data)
    if summary['execution_status'] != 'succeeded' or summary['data_integrity'].get('status') != 'complete' or summary['missing_terminal_ids']:
        raise ValueError('analysis requires a complete successful census')
    initial = data['initial_states']
    by_id = {row['particle_id']: row for row in initial}
    if len(by_id) != len(initial):
        raise ValueError('duplicate mother IDs')
    species = list(dict.fromkeys(row['species_id'] for row in initial))
    detected = {row['particle_id'] for row in data['terminal_states'] if row['physical_outcome'] == 'detected'}
    rows = []
    eligible_mz = set()
    unavailable_species = False
    batches = data['data_integrity'].get('batch_integrity')
    def detector_complete(cohort):
        expected = {row['particle_id'] for row in cohort}
        records = ([item.get('detector_observation') for item in batches] if isinstance(batches, list)
                   else [data['data_integrity'].get('detector_observation')])
        covered = set()
        seen = set()
        from msplatform.results.detector_observation import validate_detector_observation
        mother = set(by_id)
        for record in records:
            if not isinstance(record, dict):
                continue
            validate_detector_observation(record, record.get('cohort_particle_ids', []))
            record_ids = set(record['cohort_particle_ids'])
            if not record_ids <= mother or seen.intersection(record_ids):
                raise ValueError('detector batch coverage overlaps or exceeds the mother cohort')
            seen.update(record_ids)
            overlap = expected.intersection(record.get('cohort_particle_ids', []))
            if overlap and record.get('status') == 'complete':
                covered.update(overlap)
        return covered == expected
    for sid in species:
        cohort = [row for row in initial if row['species_id'] == sid]
        identities = {(row['mass_kg'], row['charge_state']) for row in cohort}
        if len(identities) != 1:
            raise ValueError('species mass and charge must remain constant')
        mass, charge = next(iter(identities))
        if type(charge) is not int or charge == 0:
            raise ValueError('species charge must be nonzero integer')
        hits = sum(row['particle_id'] in detected for row in cohort)
        available = detector_complete(cohort)
        unavailable_species |= not available
        if available and hits >= 3:
            eligible_mz.add(mass / abs(charge))
        row = dict(species_id=sid, particle_count=len(cohort), detected_count=hits if available else None,
                   detection_fraction=hits / len(cohort) if available else None,
                   weighted_detection_fraction=(math.fsum(item['weight'] for item in cohort if item['particle_id'] in detected)
                       / math.fsum(item['weight'] for item in cohort)) if available else None,
                   peak_analysis=dict(status=('applicable' if hits >= 3 else 'not_applicable') if available else 'unavailable',
                       reason=(None if hits >= 3 else 'insufficient_detected_particles') if available else 'detector_observation_unavailable'))
        if not available:
            row['observed_detected_count'] = hits
        rows.append(row)
    calibration_status = ('applicable' if len(eligible_mz) >= 3 else
                          'unavailable' if unavailable_species else 'not_applicable')
    return dict(summary=summary, species=rows,
                calibration_analysis=dict(status=calibration_status,
                    reason=None if calibration_status == 'applicable' else
                           'detector_observation_unavailable' if calibration_status == 'unavailable' else
                           'insufficient_distinct_species_with_detected_particles'))
