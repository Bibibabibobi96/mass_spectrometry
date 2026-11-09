"""Collect complete-mother native evidence; compare an override-free replay.

The caller owns native execution, admission and publication. This adapter uses
the shared canonical census, without statistical or legacy publication code.
No PA is opened, copied or hashed here.
"""
from __future__ import annotations

from msplatform.backends.simion.source import execution_particle_ids, validate_consumed_plane_events
from msplatform.backends.simion.tracking_collection import collect_tracking_logs

import argparse
import csv
import json
import math
from pathlib import Path

from common.analysis.particle_events import group_particle_events
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from integrations.runtime.build_single_flight_program import validate_native_flight, validate_native_field_observation
from msplatform.workflows.single_reflection_flight.pulse import resolve_phase_flight, select_discovery_pulse
from msplatform.backends.simion.source import GLOBAL_COLUMNS
from msplatform.contracts.particle_state import binary64_serialization_close as _close



def _observation_json(text: str) -> dict:
    def unique(pairs):
        result = {}
        for key,value in pairs:
            if key in result: raise ValueError('duplicate applied-field evidence field')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite applied-field evidence: '+value)
    result = json.loads(text,object_pairs_hook=unique,parse_constant=invalid)
    if not isinstance(result,dict): raise ValueError('applied-field evidence must be an object')
    return result


def _field_observation_definition(preparation: dict, source: dict, provenance: dict,
                                  flight: dict, run: Path) -> tuple[dict, dict] | None:
    record = preparation['input_records'].get('validation_contract')
    if record is None: return None
    document = _read(_verified(record,'field observation validation contract',run))
    if 'native_field_observation' not in document: return None
    request = _read(_verified(preparation['input_records']['request'],'field observation request',run))
    if type(request.get('schema_version')) is not int or request['schema_version'] != 10:
        raise ValueError('applied-field evidence requires an explicit request10 declaration')
    geometry = _read(_verified(preparation['outputs']['frontend_geometry'],'observation geometry',run))
    from integrations.runtime.single_flight_frontend import native_frontend_instances
    instances,_ = native_frontend_instances(geometry['composition_plan'])
    spec = validate_native_field_observation(document['native_field_observation'],particle_ids=list(source),
        source_instances=instances,domain_ids=list(geometry['numerical_domains']),
        clock_epoch_id=provenance['clock_epoch_id'],flight=flight)
    if spec['source_instance_id'] != request['source']['instance_id'] or spec['source_instance_id'] != provenance['source_instance_id']:
        raise ValueError('applied-field evidence source differs from the actual frozen RF particle source')
    return spec,geometry


def _validate_field_observation_row(row: dict, spec: dict, context: dict, previous: dict, counts: dict) -> None:
    required = {'schema_version','role','basis','record_seq','callback_seq','bucket_id','instrument_time_us',
        'solver_elapsed_us','particle_id','ion_number','instance_index','domain_id','world_frame_id','world_position_mm',
        'grid_spacing_mm','instance_scale','instance_rotation_deg','entry_gradient_gu','rf_members','pulse_active_used',
        'pulse_basis','pa_gu','after_dynamic_gradient_gu','region_override','after_region_gradient_gu','final_gradient_gu',
        'actual_rf_phase_rad','rf_phase_basis','carrier_native_path','carrier_native_field_gu'}
    active = row.get('pulse_active_used')
    if active is True: required.update(('pulse_scale_used','pulse_native_field_gu','pulse_native_path'))
    if set(row) != required or type(active) is not bool:
        raise ValueError('applied-field query fields differ')
    if (type(row['schema_version']) is not int or row['schema_version'] != 1
            or row['role'] != 'single_reflection_applied_field_query' or row['basis'] != 'efield_adjust_query_only'):
        raise ValueError('applied-field query version/role/basis differs')
    if row['rf_phase_basis'] != 'unwrapped_kernel_phase_at':
        raise ValueError('applied-field RF phase is not the original unwrapped kernel phase')
    for key in ('record_seq','callback_seq','particle_id','ion_number','instance_index'):
        if type(row[key]) is not int or row[key] < 1: raise ValueError('invalid applied-field query integer')
    ids = context['eligible_batch_particle_ids']
    if (row['record_seq'] != previous['record_seq']+1 or row['callback_seq'] <= previous['callback_seq']
            or row['ion_number'] > len(ids) or row['particle_id'] != ids[row['ion_number']-1]
            or row['instance_index'] != context['instance_index'] or row['domain_id'] != spec['domain_id']
            or row['world_frame_id'] != context['world_frame_id']):
        raise ValueError('applied-field query sequence/source/domain identity differs')
    def finite(value): return type(value) in (int,float) and math.isfinite(value)
    def vector(value): return isinstance(value,list) and len(value)==3 and all(finite(item) for item in value)
    for key in ('instrument_time_us','solver_elapsed_us','instance_scale','actual_rf_phase_rad'):
        if not finite(row[key]): raise ValueError('nonfinite applied-field query scalar')
    for key in ('world_position_mm','grid_spacing_mm','instance_rotation_deg','entry_gradient_gu','pa_gu',
                'carrier_native_field_gu','after_dynamic_gradient_gu','after_region_gradient_gu','final_gradient_gu'):
        if not vector(row[key]): raise ValueError('invalid applied-field query vector')
    if row['instance_scale'] <= 0 or min(row['grid_spacing_mm']) <= 0:
        raise ValueError('invalid applied-field native spacing/scale')
    if row['after_region_gradient_gu'] != row['final_gradient_gu']:
        raise ValueError('applied-field final capture is not after all region overrides')
    buckets = {item['bucket_id']:item for item in spec['buckets']}
    bucket = buckets.get(row['bucket_id'])
    t = row['instrument_time_us']
    if (bucket is None or not bucket['time_min_us'] <= t < bucket['time_max_us']
            or t >= spec['deadline_us'] or counts[row['bucket_id']] >= 2):
        raise ValueError('applied-field query is outside its declared window/cap')
    members = row['rf_members']
    if (not isinstance(members,list) or len(members) != len(context['rf_sources'])
            or any(not isinstance(item,dict) or set(item) != {'coefficient_used','native_field_gu','native_path'}
                   or not finite(item['coefficient_used']) or not vector(item['native_field_gu']) for item in members)):
        raise ValueError('applied-field actual RF basis/coefficient coverage differs')
    records = context['field_records'][spec['domain_id']]
    def loaded_path(actual,expected):
        return isinstance(actual,str) and bool(actual) and Path(actual).name.casefold()==Path(expected['path']).name.casefold()
    rf_records = [value for key,value in sorted(records.items()) if key.startswith('rf_reference')]
    if (not loaded_path(row['carrier_native_path'],records['carrier_off']) or
            any(not loaded_path(member['native_path'],record) for member,record in zip(members,rf_records,strict=True))):
        raise ValueError('applied-field actual loaded native member name differs from its frozen record')
    if active:
        if (row['pulse_basis'] != 'actual_field_vc_used' or not finite(row['pulse_scale_used'])
                or not vector(row['pulse_native_field_gu']) or not loaded_path(row['pulse_native_path'],records['pulse_delta'])):
            raise ValueError('applied-field pulse evidence differs')
    elif row['pulse_basis'] != 'not_applied_not_queried':
        raise ValueError('inactive pulse cannot claim a native query')
    region = row['region_override']
    if (not isinstance(region,dict) or not {'replace_all'} <= set(region) <=
            {'replace_all','dvoltsx_gu','dvoltsy_gu','dvoltsz_gu'} or type(region['replace_all']) is not bool
            or any(not finite(value) for key,value in region.items() if key != 'replace_all')):
        raise ValueError('applied-field region override evidence differs')
    previous.update(record_seq=row['record_seq'],callback_seq=row['callback_seq'])
    counts[row['bucket_id']] += 1


def _collect_field_observations(preparation: dict, workbench: dict, run: Path, source: dict,
                                provenance: dict, flight: dict, cases: list[dict], logs: list[Path]) -> dict | None:
    definition = _field_observation_definition(preparation,source,provenance,flight,run)
    header,summary,rows,observed_bytes = None,None,[],0
    spec,geometry = definition if definition is not None else (None,None)
    counts = {} if spec is None else {row['bucket_id']:0 for row in spec['buckets']}
    previous = dict(record_seq=0,callback_seq=0)
    for case,log in zip(cases,logs,strict=True):
        eligible_ids = case.get('expected_particle_ids',list(source))
        eligible = spec is not None and spec['eligible_batch_anchor_particle_id'] in eligible_ids
        with log.open(encoding='utf-8-sig') as observation_stream:
            for line in observation_stream:
                if ('PLANE_OBSERVATION' in line or 'PLANE_BOUNDARY_RETURN' in line) and case.get('build_metadata', {}).get('plane_observations') is None:
                    raise ValueError('undeclared plane observation evidence')
                if 'TRACE: applied_field_observation' not in line: continue
                if not eligible: raise ValueError('undeclared or non-anchor-batch applied-field evidence')
                observed_bytes += len(line.encode('utf-8'))
                if observed_bytes > spec['max_output_bytes']//2: raise ValueError('applied-field phase evidence exceeds its byte cap')
                prefix,payload = line.strip().split(' ',2)[1:]
                value = _observation_json(payload)
                if prefix == 'applied_field_observation_header':
                    if header is not None or rows or summary is not None: raise ValueError('duplicate applied-field header')
                    if (set(value) != {'schema_version','role','specification','context'} or value['schema_version'] != 1
                            or type(value['schema_version']) is not int
                            or value['role'] != 'single_reflection_applied_field_observation_header' or value['specification'] != spec):
                        raise ValueError('applied-field header declaration differs')
                    from integrations.workflows.single_reflection_flight.runtime import _field_observation, _frontend_fields
                    from integrations.runtime.single_flight_frontend import native_frontend_instances, instance_design_record
                    receipt = _verified(case['field_receipt_record'],'observation field receipt',run)
                    design = _read(_verified(preparation['outputs']['frontend_field_design'],'observation design',run))
                    fields,_ = _frontend_fields(receipt,design)
                    expected = _field_observation(preparation,list(source.values()),provenance,geometry,fields,flight,workbench['phase'])['evidence_context']
                    instances,_ = native_frontend_instances(geometry['composition_plan'])
                    order = sorted(instances,key=lambda key:tuple(sorted(geometry['electrode_bindings'][key].values())))
                    rf = [dict(instance_id=key,drive=_read(_verified(instance_design_record(preparation,key),'observation RF provider',run))['drive'],
                               electrode_group_native_ids=geometry['electrode_bindings'][key]) for key in order]
                    expected.update(eligible_batch_particle_ids=eligible_ids,instance_index=3 if spec['domain_id']=='parent' else 5,
                        world_frame_id=geometry['native_frame_id'],gradient_unit='V/gu_positive_grad_V',
                        basis_unit='field_vc_native_E_opposite_grad_V',query_semantics='efield_adjust_query_only_not_accepted_particle_state',rf_sources=rf)
                    expected.update(phase_row_cap=16,phase_byte_cap=524288,maximum_recorded_phases=2)
                    if json.dumps(value['context'],sort_keys=True) != json.dumps(expected,sort_keys=True):
                        raise ValueError('applied-field header differs from verified source/provider/PA context')
                    header = value
                elif prefix == 'applied_field_observation':
                    if header is None or summary is not None or len(rows) >= 16: raise ValueError('applied-field query order/cap differs')
                    _validate_field_observation_row(value,spec,header['context'],previous,counts)
                    rows.append(value)
                elif prefix == 'applied_field_observation_summary':
                    if header is None or summary is not None: raise ValueError('duplicate or unbound applied-field summary')
                    if (set(value) != {'schema_version','role','rows','counts','coverage_complete','stopped_by','deadline_seen'}
                            or type(value['schema_version']) is not int or value['schema_version'] != 1
                            or value['role'] != 'single_reflection_applied_field_observation_summary'
                            or type(value['rows']) is not int or value['rows'] != len(rows) or value['counts'] != counts
                            or any(type(n) is not int for n in value['counts'].values())
                            or type(value['coverage_complete']) is not bool or value['coverage_complete'] != all(n==2 for n in counts.values())
                            or type(value['deadline_seen']) is not bool
                            or value['stopped_by'] not in ('native_end','row_cap')):
                        raise ValueError('applied-field summary differs from actual query rows')
                    summary = value
                else: raise ValueError('unknown applied-field trace protocol')
    if spec is None: return None
    missing = [key for key,value in counts.items() if value < 2]
    return dict(schema_version=1,role='single_reflection_applied_field_observation',
        status='RECORDED' if header is not None and summary is not None and not missing else 'INCONCLUSIVE',
        coverage_status='complete' if header is not None and summary is not None and not missing else 'coverage_incomplete',
        missing_buckets=missing,header=header,summary=summary,queries=rows,observed_bytes=observed_bytes,
        claim='bounded native callback query evidence only; not accepted states, world E, plane potentials or scientific qualification')


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
    if provenance.get("schema_version") == 2:
        for name in ("clock_authority", "instrument_epoch"):
            authority = preparation["input_records"][name]
            _verified(authority, "canonical source " + name, run)
            declared = provenance["clock_records"][name]
            if declared.get("bytes") != authority.get("bytes") or declared.get("sha256", "").upper() != authority["sha256"].upper():
                raise ValueError("canonical source original clock record differs")
        if authority["sha256"].upper() != provenance.get("clock_authority_sha256", "").upper():
            raise ValueError("canonical source original clock authority differs")
    expected_ids = execution_particle_ids(provenance, preparation['particle_count'])
    if (not isinstance(expected_ids, list) or ids != expected_ids
            or len(ids) != workbench['particle_count'] or len(ids) != provenance['particle_count']
            or workbench['clock_epoch_id'] != provenance['clock_epoch_id']):
        raise ValueError('frozen source IDs/count/clock differ from source provenance')
    if restart_source and (provenance.get('continued_particle_count') != len(ids)
            or not set(ids) <= set(provenance.get('original_mother_particle_ids', []))):
        raise ValueError('recorded pre-pulse continuation ledger differs from source')
    if provenance.get('schema_version') == 2:
        validate_consumed_plane_events(provenance['consumed_plane_events'], state_kind=provenance['state_kind'], source_rows=rows)
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



def collect_log(preparation: dict, workbench: dict, run: Path, log: Path | None = None, *, replay: bool = False) -> dict:
    """Collect one complete original-mother flight without reconstruction/statistics."""
    run = run.resolve(strict=True)
    source, flight, controls, provenance = _inputs(preparation, workbench, run)
    cases = workbench.get('batches')
    if cases is None:
        cases = [dict(workbench,expected_particle_ids=list(source), source_row_range=[1,len(source)], stdout=str(log))]
    logs = []
    for case in cases:
        path = Path(case['replay_stdout'] if replay else case['stdout']).resolve(strict=True)
        from integrations.workflows.single_reflection_flight.continuation import parent_case_records
        allowed = parent_case_records(preparation, workbench, case, replay=replay)
        if not path.is_relative_to(run) and path not in allowed:
            raise ValueError('native log must belong to this run')
        logs.append(path)
    collected = collect_tracking_logs(logs, source_rows=source, source_provenance=provenance,
                                      flight=flight, batches=cases)
    census, rows = collected['census'], collected['canonical_events']
    pulse_states, shared_states = collected['native_pulse_states'], collected['native_shared_states']
    terminals = {row['particle_id']: row for row in collected['native_terminals']}
    plane_observation, stop_policy = collected.get('plane_observations'), collected.get('propagation_stop')
    continuation = provenance.get('source_kind') == 'recorded_pre_pulse_state'
    observation = _collect_field_observations(preparation,workbench,run,source,provenance,flight,cases,logs)
    modern_source = provenance.get('schema_version') == 2
    mother = ({key: provenance[key] for key in ('mother_particle_ids', 'mother_records', 'mother_fates', 'clock_authority_sha256', 'clock_records')}
              if modern_source else None)
    return dict(schema_version=2 if modern_source else 1, role=('single_reflection_canonical_source_collection' if modern_source else
        'single_reflection_recorded_pre_pulse_continuation_collection' if continuation else 'single_reflection_complete_mother_collection'),
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
        **({'native_field_observation':observation} if observation is not None else {}),
        **({'plane_observations':plane_observation} if plane_observation is not None else {}),
        **({'propagation_stop':stop_policy,'propagation_scope':'segmented_upstream',
            'handoff_stop_basis':'interpolated crossing separate from actual accepted endpoint',
            'observation_complete':plane_observation['status']=='complete'} if stop_policy is not None else {}),
        **({'original_mother':mother, 'source_provenance_record':preparation['outputs']['source_provenance'],
            'source_start_semantics':provenance['state_time_semantics']} if modern_source else {}),
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
    if baseline.get('original_mother') != replay.get('original_mother'):
        differences.append('original_mother')
    def plane_content(collection):
        value = collection.get('plane_observations')
        if value is None:
            return None
        return {**value, 'rows': [{key: item for key, item in row.items() if key not in {'log', 'raw_line_number'}} for row in value['rows']],
                'incomplete': [{key: item for key, item in row.items() if key not in {'log', 'raw_line_number'}} for row in value['incomplete']],
                'unlocalized_boundary_returns': [{key: item for key, item in row.items() if key not in {'log', 'raw_line_number'}} for row in value.get('unlocalized_boundary_returns', [])]}
    compare(plane_content(baseline), plane_content(replay), 'plane_observations')
    compare(baseline.get('propagation_stop'),replay.get('propagation_stop'),'propagation_stop')
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
    observation = None
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
        observation = result.pop('native_field_observation',None)
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
    observation_records = {}
    if observation is not None:
        observation_path = output / ('replay_native_field_observation.json' if args.replay else 'native_field_observation.json')
        with observation_path.open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(json.dumps(observation,indent=2,allow_nan=False)+'\n')
        observation_records[observation_path.name] = file_record(observation_path)
        result['native_field_observation_record'] = observation_records[observation_path.name]
        result['native_field_observation_status'] = observation['status']
    target = output / name
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(dict(output_records={name: file_record(target),**observation_records}, passed=passed)))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
