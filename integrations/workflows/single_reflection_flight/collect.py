"""Collect complete-mother native evidence; compare an override-free replay.

The caller owns native execution, admission and publication. This adapter uses
the shared canonical census, without statistical or legacy publication code.
No PA is opened, copied or hashed here.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from common.analysis.particle_events import group_particle_events
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from integrations.runtime.build_single_flight_program import validate_native_flight
from integrations.workflows.single_reflection_flight.pulse import resolve_phase_flight, select_discovery_pulse
from integrations.runtime.single_flight_source import GLOBAL_COLUMNS, binary64_serialization_close as _close
from integrations.workflows.single_reflection_flight.census import (
    canonical_census, read_native_events, read_native_evidence,
)

_X_EVENTS = {'multipole_handoff', 'accelerator_sidewall_inner_forward', 'accelerator_axis_forward'}
_BRACKET = ('step_start_instrument_time_us', 'step_end_instrument_time_us', 'step_start_x_mm', 'step_end_x_mm')


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _collection_input_records(preparation: dict) -> dict:
    records = dict(request_record=preparation['input_records']['request'],
        geometry_record=preparation['outputs']['frontend_geometry'],
        field_design_record=preparation['outputs']['frontend_field_design'],
        source_record=preparation['outputs']['projected_source'])
    return {name: {**record, 'path': str(record_path(record))} for name, record in records.items()}


def _verified(record: dict, label: str, run: Path, allowed: dict | None = None) -> Path:
    path = record_path(record)
    if not path.is_relative_to(run.resolve()) and (allowed is None or path not in allowed
            or any(record.get(key) != allowed[path][key] for key in ('bytes', 'sha256'))):
        raise ValueError(f'{label} escapes the consuming run: {path}')
    verify_record(label, record)
    return path


def _inputs(preparation: dict, workbench: dict, run: Path) -> tuple[dict, dict, dict, dict]:
    if (preparation.get('role') != 'single_reflection_geometry_preparation'
            or workbench.get('role') != 'single_reflection_workbench_preparation'):
        raise ValueError('current preparation/workbench receipts required')
    source_record = preparation['outputs']['projected_source']
    if workbench['source_record'] != source_record or workbench['source_transform_applied'] is not False:
        raise ValueError('workbench must consume the original projected source exactly once')
    source_path = _verified(source_record, 'complete projected source', run)
    provenance = _read(_verified(preparation['outputs']['source_provenance'], 'source provenance', run))
    with source_path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != GLOBAL_COLUMNS:
            raise ValueError('projected source columns differ')
        rows = list(reader)
    ids = [int(row['particle_id']) for row in rows]
    restart_source = provenance.get('source_kind') == 'recorded_pre_pulse_state'
    expected_ids = (provenance.get('continued_particle_ids') if restart_source
                    else list(range(1, preparation['particle_count'] + 1)))
    if (not isinstance(expected_ids, list) or ids != expected_ids
            or len(ids) != workbench['particle_count'] or len(ids) != provenance['particle_count']
            or workbench['clock_epoch_id'] != provenance['clock_epoch_id']):
        raise ValueError('frozen source IDs/count/clock differ from source provenance')
    if restart_source and (provenance.get('continued_particle_count') != len(ids)
            or not set(ids) <= set(provenance.get('original_mother_particle_ids', []))):
        raise ValueError('recorded pre-pulse continuation ledger differs from source')
    if not all(math.isfinite(float(value)) for row in rows for value in row.values()):
        raise ValueError('nonfinite projected source')
    controls = {}
    for index, case in enumerate(workbench.get('batches', [workbench]), 1):
        from integrations.workflows.single_reflection_flight.continuation import parent_case_records
        allowed = parent_case_records(preparation, workbench, case)
        if case.get('flight') != workbench.get('flight'):
            raise ValueError('batch flight differs from the phase flight')
        records = case['outputs']
        if not {'iob', 'program', 'particles', 'build_spec'}.issubset(records):
            raise ValueError('saved workbench controls including IOB are required')
        for key, record in records.items():
            _verified(record, key, run, allowed)
            controls[f'{index}:{key}'] = record
    design = _read(_verified(preparation['outputs']['frontend_field_design'], 'frontend field design', run))
    requires_rf = any(point['kind'] == 'rf_reference' for point in design['working_points'])
    flight = validate_native_flight(workbench.get('flight'), requires_rf=requires_rf)
    request = _read(_verified(preparation['input_records']['request'], 'frozen request', run))
    author = validate_native_flight(request.get('flight'), requires_rf=requires_rf, allow_discovery=True)
    decision = None
    if 'pulse_decision' in workbench['inputs']:
        decision = _read(_verified(workbench['inputs']['pulse_decision'], 'pulse decision', run))
    if flight != resolve_phase_flight(author, phase=workbench['phase'], decision=decision, requires_rf=requires_rf):
        raise ValueError('workbench flight differs from frozen scientific request')
    return dict(zip(ids, rows, strict=True)), flight, controls, provenance



def _validate_states(rows: list[dict], source: dict, terminals: dict, locations: dict, log: Path) -> None:
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
            if (t < birth and not _close(t, birth)) or (t > end and not _close(t, end)):
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


def collect_log(preparation: dict, workbench: dict, run: Path, log: Path | None = None, *, replay: bool = False) -> dict:
    """Collect one complete original-mother flight without reconstruction/statistics."""
    run = run.resolve(strict=True)
    source, flight, controls, provenance = _inputs(preparation, workbench, run)
    cases = workbench.get('batches')
    if cases is None:
        cases = [dict(expected_particle_ids=list(source), source_row_range=[1,len(source)], stdout=str(log))]
    logs, counts, seen = [], [], []
    terminals, locations, pulse_states, shared_states = {}, {}, [], []
    ordered_ids = list(source)
    for case in cases:
        low, high = case['source_row_range']
        ids = ordered_ids[low-1:high]
        if ids != case['expected_particle_ids'] or not 1 <= low <= high <= len(source):
            raise ValueError('batch original-ID/source-row binding differs')
        seen.extend(ids)
        path = Path(case['replay_stdout'] if replay else case['stdout']).resolve(strict=True)
        from integrations.workflows.single_reflection_flight.continuation import parent_case_records
        allowed = parent_case_records(preparation, workbench, case, replay=replay)
        if not path.is_relative_to(run) and path not in allowed:
            raise ValueError('native log must belong to this run')
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
    evidence = read_native_events(logs, masses.pop(), list(source), counts)
    census = canonical_census(evidence, list(source), pulse_time_us=flight['pulse'].get('time_us'))
    rows = evidence['rows']
    _validate_states(rows, source, terminals, locations, log)
    _validate_states(pulse_states, source, terminals, locations, log)
    _validate_states(shared_states, source, terminals, locations, log)
    if any(not math.isfinite(value) for row in census['terminal_taxonomy']['particle_outcomes']
           for value in row.values() if isinstance(value, (int, float))):
        raise ValueError('nonfinite terminal classification')
    for row in census['terminal_taxonomy']['particle_outcomes']:
        if row['instance_id'] != terminals[row['particle_id']]['instance']:
            raise ValueError(f"particle {row['particle_id']}: terminal classification/native instance differ")
    continuation = provenance.get('source_kind') == 'recorded_pre_pulse_state'
    return dict(schema_version=1, role=('single_reflection_recorded_pre_pulse_continuation_collection'
        if continuation else 'single_reflection_complete_mother_collection'),
        phase=workbench['phase'], **_collection_input_records(preparation), clock_epoch_id=workbench['clock_epoch_id'],
        control_records=controls, log_record=[file_record(path) for path in logs], flight=flight, census=census,
        canonical_events=rows, native_pulse_states=pulse_states, native_shared_states=shared_states,
        native_terminals=[terminals[pid] for pid in source],
        native_terminal_basis='actual handoff_terminal_raw; no reconstructed velocity',
        detector_crossing_basis='provider disk-intercept projection; distinct from native terminal state',
        native_complete=True,
        continuation=(dict(original_mother_particle_ids=provenance['original_mother_particle_ids'],
            original_mother_particle_count=provenance['original_mother_particle_count'],
            continued_particle_ids=provenance['continued_particle_ids'],
            continued_particle_count=provenance['continued_particle_count'],
            uncontinued_mother_particle_ids=provenance['uncontinued_mother_particle_ids'],
            restart_state_time_us=provenance['restart_state_time_us'],
            original_birth_times_us=provenance['original_birth_times_us']) if continuation else None),
        claim=('canonical continued-cohort census only; uncontinued mother particles are parent evidence, not losses or terminals'
            if continuation else 'canonical census only; no peak/bootstrap or physical qualification'))


def compare_collections(baseline: dict, replay: dict) -> dict:
    """Compare every per-ID canonical event and native/physical terminal classification."""
    differences = []
    def compare(left, right, path):
        if type(left) is not type(right):
            differences.append(path)
        elif isinstance(left, dict):
            if left.keys() != right.keys():
                differences.append(path + '.keys')
            for key in left.keys() & right.keys():
                if key != 'raw_line_number':
                    compare(left[key], right[key], f'{path}.{key}')
        elif isinstance(left, list):
            if len(left) != len(right):
                differences.append(path + '.length')
            for i, (a, b) in enumerate(zip(left, right)):
                compare(a, b, f'{path}[{i}]')
        elif isinstance(left, float):
            if not _close(left, right):
                differences.append(path)
        elif left != right:
            differences.append(path)
    if baseline.get('role') != replay.get('role'):
        differences.append('role')
    for key in ('phase', 'request_record', 'geometry_record', 'field_design_record',
                'source_record', 'clock_epoch_id', 'control_records', 'flight', 'census', 'native_terminals', 'native_shared_states', 'continuation'):
        compare(baseline[key], replay[key], key)
    compare({row['particle_id']: row for row in baseline['native_pulse_states']},
            {row['particle_id']: row for row in replay['native_pulse_states']}, 'native_pulse_states')
    by_id = [group_particle_events(item['canonical_events'],
        [row['particle_id'] for row in item['native_terminals']]) for item in (baseline, replay)]
    compare(by_id[0], by_id[1], 'particle_events')
    return dict(schema_version=1, role='single_reflection_saved_default_comparison', passed=not differences,
        differences=differences, baseline_log=baseline['log_record'], replay_log=replay['log_record'],
        execution_cohort_count=len(baseline['native_terminals']),
        continued_count=len(baseline['native_terminals']),
        numerical_allowance='binary64_serialization_close: 32 ULP at max(1,abs(a),abs(b)); serialization only',
        claim='saved-default replay parity only; no GUI or physical qualification')


def select_pulse(preparation: dict, run: Path, collection_record: dict) -> dict:
    """Select from one verified discovery collection without reopening its raw log."""
    run = run.resolve(strict=True)
    collection = _read(_verified(collection_record, 'discovery collection', run))
    expected = _collection_input_records(preparation)
    if (collection.get('role') not in {'single_reflection_complete_mother_collection',
            'single_reflection_recorded_pre_pulse_continuation_collection'}
            or collection.get('phase') != 'discovery' or collection.get('native_complete') is not True
            or any(collection.get(key) != value for key, value in expected.items())):
        raise ValueError('pulse selection requires this run complete discovery collection and frozen inputs')
    request = _read(_verified(expected['request_record'], 'frozen scientific request', run))
    design = _read(_verified(expected['field_design_record'], 'frozen field design', run))
    requires_rf = any(point['kind'] == 'rf_reference' for point in design['working_points'])
    author = validate_native_flight(request['flight'], requires_rf=requires_rf, allow_discovery=True)
    if (author['pulse']['mode'] != 'discover' or collection['flight'] !=
            resolve_phase_flight(author, phase='discovery', requires_rf=requires_rf)):
        raise ValueError('discovery collection flight differs from the frozen candidate plan')
    geometry = _read(_verified(expected['geometry_record'], 'frozen geometry', run))
    births = {row['particle_id']: row['instrument_time_us'] for row in collection['canonical_events']
              if row['event'] == 'source_release'}
    terminals = {row['particle_id']: row['instrument_time_us'] for row in collection['native_terminals']}
    return select_discovery_pulse(births_us=births, terminal_times_us=terminals,
        snapshots=collection['native_shared_states'], candidate_times_us=author['pulse']['candidate_times_us'],
        frontend_geometry=geometry, pulse_width_us=author['pulse']['width_us'],
        input_records=dict(collection=collection_record, request=expected['request_record'],
                           frontend_geometry=expected['geometry_record']))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('preparation', 'workbench', 'run', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--log', type=Path)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--baseline-record', type=json.loads)
    parser.add_argument('--select-pulse', action='store_true')
    parser.add_argument('--collection-record', type=json.loads)
    args = parser.parse_args()
    preparation, workbench = _read(args.preparation), _read(args.workbench)
    if args.select_pulse:
        if args.collection_record is None or args.log is not None or args.baseline_record is not None:
            parser.error('pulse selection requires only collection-record, without log or baseline-record')
        result = select_pulse(preparation, args.run, args.collection_record)
        name = 'pulse_decision.json'
        passed = result['status'] == 'success'
    else:
        if (args.log is None and not workbench.get('batches')) or args.collection_record is not None:
            parser.error('native collection requires log, without collection-record')
        result = collect_log(preparation, workbench, args.run, args.log, replay=args.replay)
        name = 'collection.json'
        if args.baseline_record is not None:
            baseline = _read(_verified(args.baseline_record, 'baseline collection', args.run.resolve(strict=True)))
            if (baseline.get('schema_version') != 1 or baseline.get('role') not in {
                    'single_reflection_complete_mother_collection',
                    'single_reflection_recorded_pre_pulse_continuation_collection'}):
                raise ValueError('current baseline collection required')
            if baseline.get('role') != result.get('role'):
                raise ValueError('baseline collection source population role differs')
            result = compare_collections(baseline, result)
            name = 'replay_comparison.json'
        passed = result.get('passed', True)
    output = args.output.resolve()
    if not output.is_relative_to(args.run.resolve(strict=True)):
        raise ValueError('collection output must belong to the current run')
    output.mkdir(parents=True, exist_ok=True)
    target = output / name
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(dict(output_records={name: file_record(target)}, passed=passed)))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
