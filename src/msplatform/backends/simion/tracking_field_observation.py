"""Bounded parsing of native callback observations; no accepted-state claim."""
from __future__ import annotations
import json, math
from pathlib import Path
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


def _validate_field_observation_row(row: dict, spec: dict, context: dict, previous: dict, counts: dict) -> None:
    required = {'schema_version','role','basis','record_seq','callback_seq','bucket_id','instrument_time_us',
        'solver_elapsed_us','particle_id','ion_number','instance_index','domain_id','world_frame_id','world_position_mm',
        'grid_spacing_mm','instance_scale','instance_rotation_deg','entry_gradient_gu','rf_members','pulse_active_used',
        'pulse_basis','pa_gu','after_dynamic_gradient_gu','region_override','after_region_gradient_gu','final_gradient_gu',
        'actual_rf_phase_rad','rf_phase_basis','carrier_native_path','carrier_native_field_gu'}
    scalar = 'scalar_sources' in context
    static = context.get('observation_basis') == 'native_entry_gradient_no_extra_query'
    if (context.get('observation_basis') not in (None, 'native_entry_gradient_no_extra_query')
            or static != (spec['domain_id'] in {'flight_tube','reflectron','detector'})):
        raise ValueError('applied-field context basis differs from domain')
    if static:
        required -= {'rf_members','pa_gu','carrier_native_field_gu'}
    if scalar:
        required.update(('scalar_sources','scalar_rf_coefficient','scalar_pulse_coefficient','legacy_fields_intermediate_only'))
    active = row.get('pulse_active_used')
    if active is True: required.update(('pulse_scale_used','pulse_native_field_gu','pulse_native_path'))
    if set(row) != required or type(active) is not bool:
        raise ValueError('applied-field query fields differ')
    if (type(row['schema_version']) is not int or row['schema_version'] != 1
            or row['role'] != 'single_reflection_applied_field_query' or row['basis'] != ('common_scalar_query_v1' if scalar else 'native_entry_gradient_no_extra_query' if static else 'efield_adjust_query_only')):
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
    vector_keys = ['world_position_mm','grid_spacing_mm','instance_rotation_deg','entry_gradient_gu',
                   'after_dynamic_gradient_gu','after_region_gradient_gu','final_gradient_gu']
    if not static: vector_keys += ['pa_gu','carrier_native_field_gu']
    for key in vector_keys:
        if not vector(row[key]): raise ValueError('invalid applied-field query vector')
    if row['instance_scale'] <= 0 or min(row['grid_spacing_mm']) <= 0:
        raise ValueError('invalid applied-field native spacing/scale')
    if not scalar and row['after_region_gradient_gu'] != row['final_gradient_gu']:
        raise ValueError('applied-field final capture is not after all region overrides')
    if scalar:
        sources = context['scalar_sources']
        if (set(sources) != {'carrier','rf_reference','pulse_delta'}
                or row['scalar_sources'] != {name: record['field_v']['path'] for name,record in sources.items()}
                or not finite(row['scalar_rf_coefficient']) or type(row['scalar_pulse_coefficient']) is not int
                or row['scalar_pulse_coefficient'] not in (0,1)
                or row['legacy_fields_intermediate_only'] is not True):
            raise ValueError('common scalar observation identity or coefficients differ')
    buckets = {item['bucket_id']:item for item in spec['buckets']}
    bucket = buckets.get(row['bucket_id'])
    t = row['instrument_time_us']
    if (bucket is None or not bucket['time_min_us'] <= t < bucket['time_max_us']
            or t >= spec['deadline_us'] or counts[row['bucket_id']] >= 2):
        raise ValueError('applied-field query is outside its declared window/cap')
    def loaded_path(actual,expected):
        return isinstance(actual,str) and bool(actual) and Path(actual).name.casefold()==Path(expected['path']).name.casefold()
    if static:
        if (active or row['pulse_basis'] != 'not_applied_not_queried'
                or spec['domain_id'] not in {'flight_tube','reflectron','detector'}
                or context['instance_index'] != {'flight_tube':1,'reflectron':2,'detector':4}[spec['domain_id']]
                or not loaded_path(row['carrier_native_path'],context['static_carrier_record'])):
            raise ValueError('static applied-field carrier, slot or local-query basis differs')
    else:
        members = row['rf_members']
        if (not isinstance(members,list) or len(members) != len(context['rf_sources'])
                or any(not isinstance(item,dict) or set(item) != {'coefficient_used','native_field_gu','native_path'}
                       or not finite(item['coefficient_used']) or not vector(item['native_field_gu']) for item in members)):
            raise ValueError('applied-field actual RF basis/coefficient coverage differs')
        records = context['field_records'][spec['domain_id']]
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


def collect_native_field_observations(logs, cases, source_rows, spec, expected_context_for_case):
    """Parse declared unit logs against caller-verified spec, context and source."""
    if len(logs)!=len(cases): raise ValueError('observation unit logs differ')
    header=summary=None; rows=[]; candidates=[]; candidate_header=None
    counts={} if spec is None else {r['bucket_id']:0 for r in spec['buckets']}
    previous=dict(record_seq=0,callback_seq=0); observed_bytes=0; candidate_bytes=0; seen_pairs=set()
    for case,path in zip(cases,logs,strict=True):
        ids=case['expected_particle_ids'];eligible=spec is not None and spec['eligible_batch_anchor_particle_id'] in ids
        with Path(path).open(encoding='utf-8-sig') as stream:
            for line in stream:
                if ('PLANE_OBSERVATION' in line or 'PLANE_BOUNDARY_RETURN' in line) and case.get('build_metadata',{}).get('plane_observations') is None:
                    raise ValueError('undeclared plane observation evidence')
                if 'TRACE: applied_field_observation' not in line and 'TRACE: instance_adjust_observation' not in line: continue
                if not eligible: raise ValueError('undeclared or non-anchor-batch observation evidence')
                prefix,payload=line.strip().split(' ',2)[1:];value=_observation_json(payload)
                if prefix.startswith('applied_field_observation'):
                    observed_bytes+=len(line.encode('utf-8'))
                    if observed_bytes>spec['max_output_bytes']//2: raise ValueError('applied-field phase evidence exceeds its byte cap')
                else:
                    candidate_bytes+=len(line.encode('utf-8'))
                    if candidate_bytes>65536: raise ValueError('instance candidate evidence byte cap exceeded')
                if prefix=='applied_field_observation_header':
                    if header is not None or rows or summary is not None: raise ValueError('duplicate applied-field header')
                    if (set(value)!={'schema_version','role','specification','context'} or type(value['schema_version']) is not int or value['schema_version']!=1 or value['role']!='single_reflection_applied_field_observation_header' or value['specification']!=spec): raise ValueError('applied-field header declaration differs')
                    expected=expected_context_for_case(case)
                    if json.dumps(value['context'],sort_keys=True)!=json.dumps(expected,sort_keys=True): raise ValueError('applied-field header differs from verified source/provider/PA context')
                    header=value
                elif prefix=='applied_field_observation':
                    if header is None or summary is not None or len(rows)>=16: raise ValueError('applied-field query order/cap differs')
                    _validate_field_observation_row(value,spec,header['context'],previous,counts)
                    origin=float(source_rows[value['particle_id']]['instrument_time_us'])
                    if not _close(value['instrument_time_us'],origin+value['solver_elapsed_us']): raise ValueError('observation instrument clock differs from source origin plus solver elapsed')
                    rows.append(value)
                elif prefix=='applied_field_observation_summary':
                    if header is None or summary is not None: raise ValueError('duplicate or unbound applied-field summary')
                    if (set(value)!={'schema_version','role','rows','counts','coverage_complete','stopped_by','deadline_seen'} or type(value['schema_version']) is not int or value['schema_version']!=1 or value['role']!='single_reflection_applied_field_observation_summary' or type(value['rows']) is not int or value['rows']!=len(rows) or value['counts']!=counts or any(type(n) is not int for n in value['counts'].values()) or type(value['coverage_complete']) is not bool or value['coverage_complete']!=all(n==2 for n in counts.values()) or type(value['deadline_seen']) is not bool or value['stopped_by'] not in ('native_end','row_cap')): raise ValueError('applied-field summary differs from actual query rows')
                    summary=value
                elif prefix=='instance_adjust_observation_header':
                    expected={'schema_version':1,'role':'single_reflection_instance_candidate_observation','semantics':'candidate_callback_not_accepted_field_selection','particle_id':spec['eligible_batch_anchor_particle_id'],'max_rows':16,'max_output_bytes':65536,'policy':'first_observation_per_candidate_output_pair_before_deadline'}
                    if candidate_header is not None or candidates or type(value.get('schema_version')) is not int or type(value.get('particle_id')) is not int or type(value.get('max_rows')) is not int or type(value.get('max_output_bytes')) is not int or value!=expected: raise ValueError('instance candidate header differs')
                    candidate_header=value
                elif prefix=='instance_adjust_observation':
                    required={'schema_version','role','semantics','record_seq','particle_id','ion_number','instrument_time_us','solver_elapsed_us','world_position_mm','candidate_instance','output_instance'}
                    if candidate_header is None or set(value)!=required or value['schema_version']!=1 or value['role']!='single_reflection_instance_candidate' or value['semantics']!='candidate_callback_not_accepted_field_selection' or type(value['schema_version']) is not int or type(value['record_seq']) is not int or type(value['particle_id']) is not int or value['record_seq']!=len(candidates)+1 or len(candidates)>=16: raise ValueError('instance candidate record differs')
                    if any(type(value[k]) is not int or value[k]<0 for k in ('candidate_instance','output_instance')) or type(value['ion_number']) is not int or value['ion_number']<1 or value['ion_number']>len(ids) or value['particle_id']!=ids[value['ion_number']-1] or value['particle_id']!=spec['eligible_batch_anchor_particle_id']: raise ValueError('instance candidate identity differs')
                    if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) for k in ('instrument_time_us','solver_elapsed_us')) or not isinstance(value['world_position_mm'],list) or len(value['world_position_mm'])!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in value['world_position_mm']): raise ValueError('instance candidate numeric data differs')
                    if value['instrument_time_us']>=spec['deadline_us'] or not _close(value['instrument_time_us'],float(source_rows[value['particle_id']]['instrument_time_us'])+value['solver_elapsed_us']): raise ValueError('instance candidate clock differs')
                    pair=(value['candidate_instance'],value['output_instance'])
                    if pair in seen_pairs: raise ValueError('duplicate instance candidate pair')
                    seen_pairs.add(pair);candidates.append(value)
                else: raise ValueError('unknown native field observation trace protocol')
    if spec is None:return None
    missing=[k for k,v in counts.items() if v<2]
    return dict(schema_version=1,role='simion_native_field_observation',status='RECORDED' if header is not None and summary is not None and not missing else 'INCONCLUSIVE',coverage_status='complete' if header is not None and summary is not None and not missing else 'coverage_incomplete',missing_buckets=missing,header=header,summary=summary,queries=rows,observed_bytes=observed_bytes,candidate_observations=dict(status='RECORDED' if candidate_header is not None and candidates else 'INCONCLUSIVE',header=candidate_header,rows=candidates,observed_bytes=candidate_bytes,semantics='candidate_callback_not_accepted_field_selection'),claim='bounded native callback query evidence only; not accepted states, world E, plane potentials or scientific qualification')
