"""Collect shared independent RF/OA native states without TOF reflectron taxonomy."""
from __future__ import annotations
import copy
import json
import math
from pathlib import Path
from msplatform.contracts.particle_state import binary64_serialization_close
from .native_completion import require_one_fly_completion



def collect_rf_tracking_logs(log_paths,*,source_rows,source_provenance,flight,batches):
    from .tracking_collection import read_plane_observations,read_cut_stop_events
    if len(log_paths)!=len(batches) or not batches:raise ValueError('RF log/unit binding differs')
    ordered=list(source_rows);seen=[];births={};terminals={};shared=[];events=[];ends={};contacts={};incomplete={};counts=[];logs=[];deadlines={};dynamics=[]
    definitions=batches[0]['build_metadata'].get('plane_observations')
    policy=batches[0]['build_metadata'].get('propagation_stop')
    consumed=[]
    fields={'event','reason','particle_id','ion','instrument_time_us','x_mm','y_mm','z_mm',
        'vx_mm_per_us','vy_mm_per_us','vz_mm_per_us','mass_amu','charge_state','instance'}
    mothers={r['particle_id']:r for r in source_provenance['mother_records']}
    ip_mr=flight.get('tracking_kind')=='ip_mr'
    if ip_mr:
        mother_ids=source_provenance.get('mother_particle_ids')
        records=source_provenance.get('mother_records')
        if (source_provenance.get('state_kind')!='source_birth' or
                source_provenance.get('execution_particle_ids')!=ordered or mother_ids!=ordered or
                not isinstance(records,list) or [row.get('particle_id') for row in records]!=ordered or
                len(set(ordered))!=len(ordered) or policy is not None):
            raise ValueError('IP–MR continuous tracking requires its complete original birth cohort')
        if any(source_rows[pid]['instrument_time_us']!=mothers[pid]['particle_birth_time_us'] for pid in ordered):
            raise ValueError('IP–MR actual source differs from original particle birth')
    for file,case in zip(log_paths,batches,strict=True):
        low,high=case['source_row_range'];ids=ordered[low-1:high]
        if ids!=case['expected_particle_ids'] or not 1<=low<=high<=len(ordered):raise ValueError('RF unit ordinal/ID map differs')
        metadata=case['build_metadata']
        if metadata.get('plane_observations')!=definitions or metadata.get('propagation_stop')!=policy:
            raise ValueError('RF units disagree on observations/stop')
        clock=metadata['source_clock'];birth_values=clock['original_birth_times_us'];deadline_values=clock['absolute_deadlines_us']
        if birth_values!=[mothers[pid]['particle_birth_time_us'] for pid in ids] or len(deadline_values)!=len(ids):
            raise ValueError('RF unit lost its original births/deadlines')
        deadlines.update(zip(ids,deadline_values,strict=True));consumed.extend(metadata.get('consumed_plane_events',[]))
        if ip_mr and metadata.get('consumed_plane_events'):
            raise ValueError('IP–MR continuous tracking cannot consume a prior plane state')
        seen.extend(ids);path=Path(file).resolve(strict=True);logs.append(path);counts.append(len(ids))
        with path.open(encoding='utf-8-sig') as stream:require_one_fly_completion(stream)
        if ip_mr and 'MR_OBSERVATION_' in path.read_text(encoding='utf-8-sig'):
            raise ValueError('IP–MR MR observations are not supported by this terminal-only consumer')
        controls=[]
        for number,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
            if 'RF_DYNAMICS_V1:' in line:
                control=json.loads(line.split('RF_DYNAMICS_V1:',1)[1])
                if (set(control)!={'grouped','repulsion','relativity','segment_global'} or type(control['grouped'])is not int
                        or control['grouped']not in (0,1) or control['repulsion']!='none'
                        or type(control['relativity'])is not int or control['relativity']!=0
                        or type(control['segment_global'])is not int or control['segment_global']!=1
                        or 'grouped' in flight and control['grouped']!=flight['grouped']):
                    raise ValueError('RF native dynamics differ from explicit collision-free policy')
                controls.append(control)
            if ip_mr and 'RF_OBSERVATION_INCOMPLETE_V1:' in line:
                import re
                marker_pairs=re.findall(r'(\w+)=([^\s]+)',line.split('RF_OBSERVATION_INCOMPLETE_V1:',1)[1]);fields_in=dict(marker_pairs)
                if len(marker_pairs)!=len(fields_in) or set(fields_in)!={'ion','particle_id','reason'} or fields_in['reason'] not in {'callback_before_pending','equal_time_conflict','terminal_before_retained_history'}:
                    raise ValueError('IP–MR incomplete observation marker differs')
                native=int(fields_in['ion']);pid=int(fields_in['particle_id'])
                if not 1<=native<=len(ids) or ids[native-1]!=pid or str(native)!=fields_in['ion'] or str(pid)!=fields_in['particle_id'] or pid in incomplete:raise ValueError('IP–MR incomplete observation identity differs')
                incomplete[pid]=fields_in['reason']
            if 'RF_NATIVE_STATE_V1:' not in line:continue
            row=json.loads(line.split('RF_NATIVE_STATE_V1:',1)[1])
            if set(row)!=fields:raise ValueError('RF native state wire fields differ')
            if (type(row['ion'])is not int or not 1<=row['ion']<=len(ids) or row['particle_id']!=ids[row['ion']-1]
                    or type(row['particle_id'])is not int or type(row['instance'])is not int or row['instance']<0
                    or any(type(v)not in (int,float) or not math.isfinite(v) for k,v in row.items() if k not in {'event','reason'})):
                raise ValueError('RF native identity/numerical state differs')
            pid=row['particle_id'];original=source_rows[pid]
            if row['mass_amu']!=original['mass_amu'] or row['charge_state']!=original['charge_state']:
                raise ValueError('RF native particle changes physical mass or signed charge')
            row.update(raw_line_number=number,log=str(path))
            event=row['event']
            if event=='source_release':
                if pid in births:raise ValueError('RF particle has duplicate actual birth')
                if row['instrument_time_us']!=original['instrument_time_us']:raise ValueError('RF native start clock differs')
                for axis in 'xyz':
                    if (not binary64_serialization_close(row[axis+'_mm'],original['position_'+axis+'_mm'])
                            or not binary64_serialization_close(row['v'+axis+'_mm_per_us'],original['velocity_'+axis+'_m_s']/1000)):
                        raise ValueError('RF native birth 6D differs from frozen source')
                births[pid]=row
            elif event=='terminal':
                if pid in terminals:raise ValueError('RF particle has duplicate raw terminal')
                if row['reason']not in {'unknown','deadline','accepted_cut'}:raise ValueError('RF terminal reason is undeclared')
                terminals[pid]=row
            elif event=='shared':
                if row['instrument_time_us']not in flight.get('observation_times_us',[]):raise ValueError('RF shared time is undeclared')
                if any(r['particle_id']==pid and r['instrument_time_us']==row['instrument_time_us'] for r in shared):raise ValueError('RF shared state duplicated')
                shared.append(row)
            elif event=='preaction_contact' and ip_mr:
                if pid in contacts or row['reason']!='native_splat_minus_one':raise ValueError('IP–MR contact provenance differs')
                contacts[pid]=row
            elif event=='deadline_endpoint':
                if pid in ends:raise ValueError('RF deadline endpoint duplicated')
                ends[pid]=row
            else:raise ValueError('unsupported RF native event')
            events.append(row)
        if len(controls)!=1:raise ValueError('RF log requires one actual dynamics readback')
        dynamics.append(controls[0])
    if seen!=ordered or len(set(seen))!=len(seen) or set(births)!=set(ordered) or set(terminals)!=set(ordered):
        raise ValueError('RF logs omit/duplicate source cohort actual births or native terminals')
    observation=(read_plane_observations(logs,ordered,counts,definitions,consumed_plane_events=consumed) if definitions else None)
    cuts=read_cut_stop_events(logs,ordered,counts,policy,observation,terminals)
    if ip_mr:
        diagnostic_shared=[row for row in shared if row['particle_id'] in incomplete]
        shared=[row for row in shared if row['particle_id'] not in incomplete]
        events=[row for row in events if not (row['event']=='shared' and row['particle_id'] in incomplete)]
        diagnostic_planes=[]
        if observation is not None:
            diagnostic_planes=[row for row in observation['rows'] if row['particle_id'] in incomplete]
            observation['rows']=[row for row in observation['rows'] if row['particle_id'] not in incomplete]
            if incomplete:observation['status']='incomplete'
        for row in shared:
            pid=row['particle_id']
            if row['reason']!='accepted_step_linear_interpolation' or not births[pid]['instrument_time_us']<=row['instrument_time_us']<=terminals[pid]['instrument_time_us']:
                raise ValueError('IP–MR shared observation exceeds native lifetime or method')
        if observation is not None:
            for row in observation['rows']:
                pid=row['particle_id']
                if (row['step_start_instrument_time_us']<births[pid]['instrument_time_us'] or
                        row['step_end_instrument_time_us']>terminals[pid]['instrument_time_us']):
                    raise ValueError('IP–MR plane observation exceeds native lifetime')
    outcomes=[]
    for pid in ordered:
        terminal=terminals[pid]
        if terminal['instrument_time_us']<births[pid]['instrument_time_us']:raise ValueError('RF terminal precedes actual start')
        if terminal['reason']=='deadline':
            if pid not in ends or ends[pid]['instrument_time_us']<deadlines[pid]:raise ValueError('RF deadline stop lacks request boundary evidence')
            category='unknown_native_terminal' if ip_mr and pid in contacts else 'programmatic_deadline_stop'
        elif terminal['reason']=='accepted_cut':
            if pid not in cuts:raise ValueError('RF cut terminal lacks actual accepted-step plane evidence')
            if cuts[pid]['event_instrument_time_us']>deadlines[pid]:raise ValueError('RF accepted cut exceeds original deadline')
            category='handoff_cut_stop'
        else:
            if pid in cuts or pid in ends:raise ValueError('RF unknown terminal conflicts with explicit stopped endpoint')
            category='unknown_native_terminal'
        outcome=dict(particle_id=pid,category=category,instance_id=terminal['instance'],
            terminal_instrument_time_us=terminal['instrument_time_us'])
        if terminal['reason']=='deadline':outcome['request_boundary']=copy.deepcopy(ends[pid])
        else:outcome['accepted_endpoint']=copy.deepcopy(cuts.get(pid))
        outcomes.append(outcome)
    result=dict(native_complete=True,native_dynamics=dynamics,canonical_events=events,native_terminals=[terminals[pid] for pid in ordered],
        native_shared_states=shared,native_pulse_states=[],
        census=dict(role='rf_full_mother_census',execution_particle_ids=ordered,mother_particle_ids=copy.deepcopy(source_provenance['mother_particle_ids']),
            terminal_taxonomy=dict(role='rf_raw_terminal_taxonomy',particle_outcomes=outcomes,
                classification_is_mutually_exclusive_and_exhaustive=True),unknown_is_loss=False),
        original_mother={key:copy.deepcopy(source_provenance[key]) for key in
            ('mother_particle_ids','mother_records','mother_fates','clock_authority_sha256','clock_records')})
    if flight.get('tracking_kind')=='independent_oa':
        result.update(component_kind='orthogonal_accelerator',native_state_wire_format='legacy_shared_RF_NATIVE_STATE_V1',native_pulse_state_recording='not_requested')
        result['census']['role']='oa_full_mother_census'
        result['census']['terminal_taxonomy']['role']='oa_raw_terminal_taxonomy'
    if flight.get('tracking_kind')=='rf_ip':
        result.update(tracking_kind='rf_ip',native_state_wire_format='legacy_shared_RF_NATIVE_STATE_V1')
        result['census']['role']='rf_ip_full_mother_census'
        result['census']['terminal_taxonomy']['role']='rf_ip_raw_terminal_taxonomy'
    if ip_mr:
        result.update(observation_complete=not incomplete and (observation is None or observation['status']=='complete'),observation_incomplete=incomplete,uncommitted_observations=dict(shared=diagnostic_shared,planes=diagnostic_planes))
        result.update(tracking_kind='ip_mr',native_state_wire_format='legacy_shared_RF_NATIVE_STATE_V1',
                      propagation_scope='original_birth_to_native_terminal',
                      mr_observations=dict(status='not_recorded',events=[]))
        result['census']['role']='ip_mr_full_mother_census'
        result['census']['terminal_taxonomy']['role']='ip_mr_raw_terminal_taxonomy'
        for row in result['census']['terminal_taxonomy']['particle_outcomes']:
            row['terminal_splat']=None
            row['terminal_splat_availability']='not_read'
            row['native_preaction_contact']=contacts.get(row['particle_id'])
    if observation is not None:result['plane_observations']=observation
    if policy is not None:result.update(propagation_stop=policy,propagation_scope='segmented_upstream',observation_complete=observation['status']=='complete')
    return result
