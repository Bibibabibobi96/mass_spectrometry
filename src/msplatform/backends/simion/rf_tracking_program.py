"""Independent RF/OA Program projection using the existing model, pulse and source-clock owners."""
from __future__ import annotations
import copy
import math
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


def render_rf_controls(model,plan,*,assets,native_sources):
    document=require_prepared_model(model)
    geometry=dict(model_geometry(model).frontend_geometry,native_frame_id=document['native_frame_id'])
    names=geometry['composition_plan']['scope']['instance_ids']
    ids=[row['particle_id'] for row in plan['rows']]
    if not ids:raise ValueError('zero RF cohort has no Program')
    config=render_model_configuration(model)
    def resource(name):return native_sources[name] if name in native_sources else native_resource_path(name).read_text(encoding='utf-8')
    prefix='simion.workbench_program()\n'
    prefix+='local rf_model_config=(function()\n'+config+'\nend)()\n'
    prefix+='local rf_kernel=(function()\n'+resource('rf_drive.lua')+'\nend)()\n'
    oa=plan['flight'].get('tracking_kind')=='independent_oa'
    if oa:
        prefix+='local oa_pulse_hook=(function()\n'+resource('single_flight_pulse_hook.lua')+'\nend)()\n'
        prefix+='local oa_waveforms=(function()\n'+resource('voltage_waveforms.lua')+'\nend)()\n'
        prefix+='local rf_consumer=(function()\n'+resource('model_drive.lua')+'\nend)().new(rf_model_config,rf_kernel,oa_pulse_hook,oa_waveforms)\n'
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
        immutable_input_records=[record for row in assets.values() for record in [*row['family_records'],row['witness_record']]],flight=plan['flight'])
