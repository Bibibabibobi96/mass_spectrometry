"""Independent RF/OA Program projection using the existing model, pulse and source-clock owners."""
from __future__ import annotations
import copy
import math
from pathlib import Path
from typing import Any, Mapping
from .model import require_prepared_model,model_geometry,render_model_configuration
from .source import lua_value,canonical_clock_lua
from .resources import native_resource_path
from .tracking_program import _instrument_plane_observations,validate_program_trajectory_quality


def validate_rf_flight(flight,*,requires_rf):
    keys={'maximum_flight_us','maximum_step_us','trajectory_quality'}|({'rf_steps_per_period'} if requires_rf else set())
    if 'observation_times_us' in flight:keys.add('observation_times_us')
    if 'grouped' in flight:
        keys.add('grouped')
        if type(flight['grouped'])is not int or flight['grouped']not in (0,1):
            raise ValueError('RF grouped scheduling must be integer zero or one')
    if set(flight)!=keys:raise ValueError('RF flight requires explicit pulse-free step/quality controls')
    for key in ['maximum_flight_us','maximum_step_us']:
        value=flight[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('RF flight '+key+' must be positive finite')
    validate_program_trajectory_quality(flight['trajectory_quality'])
    if requires_rf:
        value=flight['rf_steps_per_period']
        if type(value)is not int or value<1:
            raise ValueError('RF flight rf_steps_per_period is outside the supported native range')
    if 'observation_times_us' in flight:
        times=flight['observation_times_us']
        if (not isinstance(times,list) or not times or any(type(t)not in (int,float) or not math.isfinite(t) for t in times)
                or any(a>=b for a,b in zip(times,times[1:]))):
            raise ValueError('RF observation times must be finite strictly increasing')
    return dict(copy.deepcopy(flight),tracking_kind='independent_rf')


def _ip_mr_bindings(document, admission):
    """Project an admitted basis into the existing scalar composer contract."""
    if (not isinstance(admission,dict) or admission.get('schema_version')!=1
            or admission.get('role')!='ip_mr_scalar_basis_binding'
            or admission.get('model_identity_sha256')!=document['model_identity_sha256']):
        raise ValueError('matching admitted IP–MR scalar basis required')
    bases=admission['bases']
    rows=[row for row in document['native_drive_rows'] if row['kind']=='ip_schedule']
    rf=[row for row in document['native_drive_rows'] if row['kind']=='rf']
    if len(rows)!=15 or {row['schedule_index'] for row in rows}!=set(range(1,16)):
        raise ValueError('complete explicit IP schedule group mapping required')
    groups=[dict(instance_id=row['instance_id'],electrode_group_id=row['electrode_group_id'],
        schedule_index=row['schedule_index'],coefficient='model_drive.evaluate_at.voltage_v') for row in rows]
    if admission.get('ip_groups')!=groups:
        raise ValueError('admitted IP group/index mapping differs from model')
    if rf:
        row=rf[0];rf_identity=dict(instance_id=row['instance_id'],waveform=row['waveform'],
            frequency_hz=row['frequency_hz'],phase_rad=row['phase_rad'],coefficient='dimensionless_rf_waveform')
        if admission.get('rf')!=rf_identity:
            raise ValueError('admitted RF signature differs from model')
    elif admission.get('rf') is not None:
        raise ValueError('admitted RF signature differs from model')
    expected={'carrier'}|{'ip_'+str(i) for i in range(1,16)}|({'rf_reference'} if rf else set())
    if set(bases)!=expected:
        raise ValueError('admitted scalar basis coverage differs from model')
    records=[]
    def binding(name):
        item=bases[name];grid=item['grid'];selected=item['records']
        records.extend(copy.deepcopy(list(selected.values())))
        projected = dict(mode='comsol_static_scalar_v',scalar_pa=selected['field_v']['path'],
            valid_pa=selected['field_valid']['path'],origin_mm=grid['origin_mm'],pitch_mm=grid['pitch_mm'],
            dimensions=grid['dimensions'],ideal_sheet_projection=item['ideal_sheet_projection'])
        if item.get('refinement_windows'):
            projected['refinement_windows'] = []
            for level in item['refinement_windows']:
                records.extend(copy.deepcopy(list(level['records'].values())))
                window_grid, window_records = level['grid'], level['records']
                projected['refinement_windows'].append(dict(
                    name=level['name'], active_box_mm=level['active_box_mm'], mode='comsol_static_scalar_v',
                    scalar_pa=window_records['field_v']['path'], valid_pa=window_records['field_valid']['path'],
                    origin_mm=window_grid['origin_mm'], pitch_mm=window_grid['pitch_mm'],
                    dimensions=window_grid['dimensions'], ideal_sheet_projection=level['ideal_sheet_projection']))
        return projected
    result=dict(carrier=binding('carrier'),ip_unit_volt=[dict(instance_id=row['instance_id'],
        electrode_group_id=row['electrode_group_id'],binding=binding('ip_'+str(row['schedule_index']))) for row in rows])
    if rf:
        row=rf[0];signature=dict(waveform=row['waveform'],frequency_hz=row['frequency_hz'],phase_rad=row['phase_rad'],
            phase_reference_instrument_time_us=document['drive']['clock']['phase_reference_instrument_time_us'])
        result['rf_reference']=dict(binding=binding('rf_reference'),signature=signature)
    return result,records

def render_rf_controls(model: Any, plan: Mapping[str, Any], *, assets: Mapping[str, Any],
                       native_sources: Mapping[str, str], scalar_bindings: dict[str, Any] | None = None,
                       slot_domains: list[str | None] | None = None) -> dict[str, Any]:
    """Render the existing Program with explicit scalar and native-slot bindings."""
    document=require_prepared_model(model)
    geometry=dict(model_geometry(model).frontend_geometry,native_frame_id=document['native_frame_id'])
    kind=plan['flight'].get('tracking_kind')
    ip_mr=kind=='ip_mr'
    joint=kind in {'rf_ip','ip_mr'}
    if ip_mr:
        if geometry.get('role')!='simion_ip_mr_complete_geometry':
            raise ValueError('IP–MR tracking requires complete selected geometry')
        expected=set(geometry['asset_components'])
        if (not isinstance(slot_domains,list) or len(slot_domains)!=len(expected)+1
                or sum(value is None for value in slot_domains)!=1
                or len(set(value for value in slot_domains if value is not None))!=len(expected)
                or set(value for value in slot_domains if value is not None)!=expected):
            raise ValueError('explicit workbench slot domains must cover each selected asset once')
        if not isinstance(scalar_bindings,dict):
            raise ValueError('explicit admitted IP–MR scalar bindings required')
        if not {'scalar_field_adapter.lua','ip_mr_scalar_field.lua'} <= native_sources.keys():
            raise ValueError('frozen IP–MR scalar resources required')
        if 'rf_steps_per_period' not in plan['flight']:
            raise ValueError('IP–MR HS1 requires explicit IP RF step resolution')
        composer_bindings,scalar_records=_ip_mr_bindings(document,scalar_bindings)
        names=copy.deepcopy(slot_domains)
    else:
        if scalar_bindings is not None or slot_domains is not None:
            raise ValueError('IP–MR inputs require IP–MR tracking')
        names=['parent'] if joint else geometry['composition_plan']['scope']['instance_ids']
    ids=[row['particle_id'] for row in plan['rows']]
    if not ids:raise ValueError('zero RF cohort has no Program')
    config=render_model_configuration(model)
    def resource(name):return native_sources[name] if name in native_sources else native_resource_path(name).read_text(encoding='utf-8')
    prefix='simion.workbench_program()\n'
    prefix+='local rf_model_config=(function()\n'+config+'\nend)()\n'
    prefix+='local rf_kernel=(function()\n'+resource('rf_drive.lua')+'\nend)()\n'
    oa=plan['flight'].get('tracking_kind')=='independent_oa'
    if oa or joint:
        prefix+='local oa_pulse_hook=(function()\n'+resource('single_flight_pulse_hook.lua')+'\nend)()\n'
        prefix+='local oa_waveforms=(function()\n'+resource('voltage_waveforms.lua')+'\nend)()\n'
        ip_native=",(function(...)\n"+resource('native_drive.lua')+"\nend)" if joint else ''
        prefix+='local rf_consumer=(function()\n'+resource('model_drive.lua')+'\nend)().new(rf_model_config,rf_kernel,oa_pulse_hook,oa_waveforms'+ip_native+')\n'
    else:
        prefix+='local rf_consumer=(function()\n'+resource('model_drive.lua')+'\nend)().new(rf_model_config,rf_kernel,nil,nil)\n'
    arrays=dict(single_flight_source_particle_id=ids,single_flight_time_origin_us=[r['instrument_time_us'] for r in plan['rows']],
        single_flight_absolute_deadline_us=[plan['absolute_deadlines_us_by_particle_id'][pid] for pid in ids],
        rf_initial_velocities=[[r['velocity_'+a+'_m_s']/1000 for a in 'xyz'] for r in plan['rows']],
        rf_instance_domains=names,rf_observation_times=plan['flight'].get('observation_times_us',[]))
    for name,value in arrays.items():prefix+='local '+name+'='+lua_value(value)+'\n'
    prefix+='local single_flight_particle_id_offset=0\n'+canonical_clock_lua()
    prefix+='local rf_step_cap_us='+lua_value(plan['flight']['maximum_step_us'])+'\n'
    if 'rf_steps_per_period' in plan['flight']:
        prefix+='for _,row in ipairs(rf_model_config.groups) do if row.kind=="rf" then local value=rf_kernel.new_differential{waveform=row.waveform,frequency_hz=row.frequency_hz,phase_rad=row.phase_rad,rf_amplitude_v=row.rf_amplitude_v,rf_scale=1,rf_steps_per_period='+lua_value(plan['flight']['rf_steps_per_period'])+'}; rf_step_cap_us=math.min(rf_step_cap_us,value.timestep_cap_us) end end\n'
    prefix+='local rf_trajectory_quality='+lua_value(plan['flight']['trajectory_quality'])+'\n'
    prefix+='local rf_grouped='+lua_value(plan['flight'].get('grouped'))+'\n'
    program=prefix+resource('rf_tracking.lua')
    if ip_mr:
        adapter=resource('scalar_field_adapter.lua')
        composer=resource('ip_mr_scalar_field.lua')
        program+='\nlocal ip_mr_scalar_adapter=(function()\n'+adapter+'\nend)()\n'
        program+='local ip_mr_scalar_module=(function()\n'+composer+'\nend)()\n'
        program+='local ip_mr_scalar=ip_mr_scalar_module.new(ip_mr_scalar_adapter,rf_consumer,rf_kernel,'+lua_value(composer_bindings)+')\n'
        program+="function segment.efield_adjust()\n  local instance=assert(simion.wb.instances[ion_instance],'selected instance required')\n"
        program+='  ion_dvoltsx_gu,ion_dvoltsy_gu,ion_dvoltsz_gu=ip_mr_scalar(instance,ion_px_mm,ion_py_mm,ion_pz_mm,single_flight_instrument_time_us())\nend\n'
    if joint:
        options=plan['hs1']
        if set(options)!={'vendor_path','bath_path','outer_path','query_frame_id','numerics'}:
            raise ValueError('RF-IP HS1 requires exact frozen runtime inputs')
        numerics=options['numerics']
        if (set(numerics)!={'seed','hs1_steps_per_mfp'} or type(numerics['seed']) is not int or numerics['seed']<0
                or type(numerics['hs1_steps_per_mfp']) is not int or numerics['hs1_steps_per_mfp']<1):
            raise ValueError('RF-IP HS1 requires positive explicit integer seed and steps')
        for key in ('vendor_path','bath_path','outer_path'):
            if not isinstance(options[key],str) or not Path(options[key]).is_absolute() or not options[key].isascii():
                raise ValueError('RF-IP HS1 frozen input paths must be absolute')
        from msplatform.contracts.rigid_transform import RigidTransform
        composition = document['geometry']['frontend_geometry']['composition_plan']
        ip_ids = [name for name, component in composition['components'].items()
                  if component['project_id'] == 'dual_pressure_rectilinear_ion_processor']
        if len(ip_ids) != 1:
            raise ValueError('RF-IP gas requires the selected IP component')
        poses = [row['transform'] for row in composition['recipe']['instances']
                 if row['instance_id'] == ip_ids[0]]
        if len(poses) != 1:
            raise ValueError('RF-IP gas requires the selected IP placement')
        pose = RigidTransform.from_contract(poses[0])
        if pose.to_frame_id != options['query_frame_id'] or pose.to_frame_id != document['native_frame_id']:
            raise ValueError('RF-IP gas frame differs from the selected IP placement')
        if plan['flight'].get('grouped') != 0:
            raise ValueError('RF-IP HS1 requires sequential particle processing')
        schedule=document['drive']['ip_schedule']
        baseline=schedule['baseline']; timing=schedule['native_timing']
        edges=sorted(set([baseline['schedule'][key] for key in ('capture_end_us','transfer_end_us','lift_end_us','terminal_us')]+[timing['primary_quench_us'],timing['pulse_start_us']]))
        config=dict(baseline=baseline,numerics=numerics,query_frame_id=options['query_frame_id'],schedule_edges_us=edges)
        program+='\nrf_step_cap_us=math.min(rf_step_cap_us,'+lua_value(1e6/baseline['electric']['rf_frequency_hz']/plan['flight']['rf_steps_per_period'])+')\n'
        program+='\nlocal joint_hs=simion.import('+lua_value(options['vendor_path'])+')\n'
        program+='local joint_bath=assert(loadfile('+lua_value(options['bath_path'])+'))()\n'
        program+='local joint_outer=assert(loadfile('+lua_value(options['outer_path'])+'))()\n'
        program+='local joint_selector=(function()\n'+resource('rf_ip_gas_selection.lua')+'\nend)().new(joint_bath,joint_outer)\n'
        program+='local joint_binder=(function()\n'+resource('collision_hs1_gas.lua')+'\nend)()\n'
        program+='local joint_hs1=(function()\n'+resource('rf_ip_tracking_hs1.lua')+'\nend)()\n'
        program+='joint_hs1.install(joint_hs,joint_selector,joint_binder,'+lua_value(config)+',single_flight_instrument_time_us,single_flight_canonical_particle_id,oa_waveforms)\n'
    if oa and document['drive'].get('pulse',{}).get('mode')=='timed':
        pulse=document['drive']['pulse']
        program+='\nlocal oa_step_pulse=oa_pulse_hook.compile_physical{voltage_waveforms=oa_waveforms,pulse_mode=function() return 1 end,pulse_time_us='+lua_value(pulse['time_us'])+',pulse_width_us='+lua_value(pulse['width_us'])+'}\n'
        program+='local oa_original_tstep=segment.tstep_adjust\nfunction segment.tstep_adjust() oa_original_tstep();ion_time_step=oa_step_pulse.cap_timestep_at(single_flight_instrument_time_us(),ion_time_step) end\n'
    definitions=plan['observations']['plane_observations']
    if definitions:
        program=_instrument_plane_observations(program,definitions,geometry,
            consumed_plane_events=plan['propagation']['consumed_plane_events'],particle_ids=ids,
            start_times_us=[r['instrument_time_us'] for r in plan['rows']],propagation_stop=plan['propagation']['stop'])
        if plan['propagation']['stop'] is not None:
            marker='  if cut then\n'
            if program.count(marker)!=1:raise ValueError('RF cut terminal hook differs')
            program=program.replace(marker,marker+"    rf_emit_current('terminal','accepted_cut')\n",1)
    metadata=dict(tracking_kind=plan['flight']['tracking_kind'],plane_observations=copy.deepcopy(definitions) if definitions else None,
        consumed_plane_events=copy.deepcopy(plan['propagation']['consumed_plane_events']),propagation_stop=copy.deepcopy(plan['propagation']['stop']),
        source_clock=dict(original_birth_times_us=[r['particle_birth_time_us'] for r in plan['rows']],
            absolute_deadlines_us=[plan['absolute_deadlines_us_by_particle_id'][pid] for pid in ids]))
    if oa:metadata.update(component_kind='orthogonal_accelerator',field_domain_coupling='independent_component_domains',native_state_wire_format='legacy_shared_RF_NATIVE_STATE_V1')
    return dict(program=program,build_metadata=metadata,carriers=assets,response_fields=[],
        immutable_input_records=[record for row in assets.values() for record in [*row['family_records'],row['witness_record']]]+(scalar_records if ip_mr else []),flight=plan['flight'])
