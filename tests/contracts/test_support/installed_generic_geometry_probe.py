"""Installed public generic geometry compilation with an explicit test provider."""
import copy
import importlib.util
import sys
import sysconfig
from pathlib import Path


def run_dynamic(root, product, compiled, packet, clocks, propagation, lua_provider):
    """Exercise installed neutral RF/pulse basis and Program with inert Lua APIs."""
    import subprocess
    import sysconfig
    from msplatform.backends.comsol import assembly_geometry, assembly_electrostatic_model
    from msplatform.backends.simion import (model, generic_scalar_binding, neutral_sampled_field,
        rf_tracking_program, tracking_execution, tracking_units, tracking_collection, resources)
    from msplatform.backends.simion.source import lua_value

    from msplatform.io.manifest_records import verify_record
    assert isinstance(lua_provider, dict), 'pinned Lua provider record required'
    verify_record('installed generic Lua provider before execution', lua_provider)
    lua = Path(lua_provider['path']).resolve(strict=True)

    purelib = Path(sysconfig.get_paths()['purelib']).resolve()
    for module in (assembly_geometry, assembly_electrostatic_model, model, generic_scalar_binding,
                   neutral_sampled_field, rf_tracking_program, tracking_execution, tracking_units,
                   tracking_collection, resources):
        assert Path(module.__file__).resolve().is_relative_to(purelib), module.__file__
    names = ('model_drive.lua', 'rf_drive.lua', 'rf_tracking.lua', 'single_flight_pulse_hook.lua',
             'voltage_waveforms.lua', 'scalar_field_adapter.lua', 'generic_scalar_field.lua')
    paths = {name: resources.native_resource_path(name).resolve(strict=True) for name in names}
    assert all(path.is_relative_to(purelib) for path in paths.values())
    native_sources = {name: path.read_text(encoding='utf8') for name, path in paths.items()}
    snapshot = dict(composition_plan=product.composition_plan, components_resolved=product.components_resolved,
                    components_source=product.components_source)
    projection = assembly_geometry.project_assembly_geometry(snapshot,
        outer_box_mm={'min': [-100.0]*3, 'max': [100.0]*3})
    start = float(packet['rows'][0]['instrument_time_us'])
    drive = dict(clock=dict(packet['clock'], phase_reference_instrument_time_us=0.0),
        pulse=dict(mode='timed', time_us=start+0.2, width_us=0.5), groups={
            'first': {'body': dict(kind='rf', waveform='sine', frequency_hz=1e6, phase_rad=0.0,
                rf_amplitude_v=3.0, polarity=1, common_mode_v=2.0, dc_v=0.0)},
            'second': {'body': dict(kind='pulse', off_voltage_v=-2.0, on_voltage_v=5.0)}})
    dynamic = model.compile_prepared_model(compiled, product.components_resolved, drive=drive, physics=model.RF_PHYSICS)
    document = model.require_prepared_model(dynamic)
    vectors = {'one': {'first': 1.0, 'second': 0.0}, 'two': {'first': 0.0, 'second': 1.0}}
    samples = {}
    weights = {}
    bases = {}
    grid = dict(origin_mm=[-1.0]*3, pitch_mm=[1.0]*3, dimensions=[3]*3)
    for name, vector in vectors.items():
        request = dict(group_voltages=[dict(instance_id=row['instance_id'],
            electrode_group_id=row['electrode_group_id'], voltage_v=vector[row['instance_id']])
            for row in projection['electrode_groups']], relative_permittivity=1.0,
            exterior=dict(kind='potential', voltage_v=0.0),
            mesh=dict(global_automatic_level=9, electrode_hmax_mm=5.0), study=dict(kind='stationary'))
        request = assembly_electrostatic_model.validate_request(projection, request)
        rows = [dict(instance_id=instance, electrode_group_id='body', weight=value)
                for instance, value in vector.items()]
        samples[name] = dict(request=request, weights=rows)
        weights[name] = rows
        bases[name] = dict(grid=grid, records={
            'field_v': {'path': str(Path(root)/('generic_'+name+'_v.pa'))},
            'field_valid': {'path': str(Path(root)/('generic_'+name+'_mask.pa'))}},
            ideal_sheet_projection=[])
    terms = generic_scalar_binding.compile_linear_terms(projection, drive, samples)
    assert set(terms['terms']) == {'carrier', 'pulse', 'rf_0'}
    missing = {'two': samples['two']}
    try:
        generic_scalar_binding.compile_linear_terms(projection, drive, missing)
    except ValueError as error:
        assert 'span' in str(error), error
    else:
        raise AssertionError('incomplete generic basis was accepted')
    admission = dict(role='generic_linear_scalar_admission', schema_version=1,
        model_identity_sha256=document['model_identity_sha256'], bases=bases, weights=weights)
    numerics = dict(maximum_step_us=.01, trajectory_quality=5, grouped=0, rf_steps_per_period=20)
    plan = tracking_execution.plan_tracking_execution(dynamic, particles=packet, clock_records=clocks,
        propagation=propagation, observations=dict(plane_observations=[]), numerics=numerics)
    # The real public sampled FieldBundle admission is deliberately not fabricated here.
    plan['flight']['tracking_kind'] = 'neutral_sampled'
    rendered = rf_tracking_program.render_rf_controls(dynamic, plan, assets={}, native_sources=native_sources,
        scalar_bindings=admission, slot_domains=[None, 'world'])
    changed = copy.deepcopy(admission)
    changed['model_identity_sha256'] = '0'*64
    try:
        rf_tracking_program.render_rf_controls(dynamic, plan, assets={}, native_sources=native_sources,
            scalar_bindings=changed, slot_domains=[None, 'world'])
    except ValueError as error:
        assert 'matching admitted' in str(error), error
    else:
        raise AssertionError('mismatched sampled model was accepted')
    prefix = r"""
segment={};simion={pas={},experimental={},wb={instances={}}}
function simion.workbench_program() end
function simion.early_access() end
local calls=0;local invalid=false
function simion.pas:open(path)
 local mask=path:find('_mask',1,true)~=nil
 return {path=path,symmetry='3dplanar',nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,
 potential=function()if mask and invalid and path:find('_one_',1,true) then return 0 end return 1 end}
end
simion.experimental.field_array=function(args)return {efield=function()
 calls=calls+1;return args.V.path:find('_one_',1,true) and 1 or 2,0,0 end} end
ion_number=1;ion_time_of_flight=0;ion_instance=1;ion_px_mm=0;ion_py_mm=0;ion_pz_mm=0
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0;ion_mass=100;ion_charge=1;ion_splat=0;ion_time_step=.001
local inst={scale=1,pa={dx_mm=1,dy_mm=1,dz_mm=1},wb_to_pa_orient=function(self,x,y,z)return x,y,z end}
simion.wb.instances[1]=inst;simion.wb.instances[2]=inst
"""
    suffix = r"""
assert(segment.fast_adjust==nil,'raw collision PA must not be fast-adjusted')
local start=START
for _,dt in ipairs({0,.25,.75}) do
 ion_time_of_flight=dt
 local t=start+dt; local pulse=(dt>=.2 and dt<.7) and 5 or -2
 local expected=-((2+3*math.sin(2*math.pi*t))+2*pulse)
 for slot=1,2 do ion_instance=slot;calls=0;segment.efield_adjust()
  assert(calls==2 and math.abs(ion_dvoltsx_gu-expected)<1e-9,'sampled RF/pulse value differs') end
end
local phase=(2*math.pi+math.asin(-2/3))/(2*math.pi)
local zero=phase+math.ceil(start-phase)
ion_time_of_flight=zero-start;invalid=true
local ok,err=pcall(segment.efield_adjust)
assert(not ok and err:find('V_SUPPORT_UNKNOWN',1,true),'zero coefficient hid missing support')
print('INSTALLED_GENERIC_RF_PULSE_LUA=PASS slots=2 invalid_mask=refused fast_adjust=none native=none')
""".replace('START', lua_value(start))
    script = Path(root)/'installed_generic_dynamic_program.lua'
    script.write_text(prefix+rendered['program']+suffix, encoding='utf8', newline='\n')
    result = subprocess.run([str(lua), str(script)], cwd=Path(root), capture_output=True,
                            text=True, encoding='utf8', timeout=30, check=False)
    verify_record('installed generic Lua provider after execution', lua_provider)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'INSTALLED_GENERIC_RF_PULSE_LUA=PASS' in result.stdout, result.stdout
    resource = paths['generic_scalar_field.lua']
    original = resource.read_bytes()
    hidden = resource.with_name(resource.name+'.probe-hidden')
    assert not hidden.exists()
    resource.rename(hidden)
    try:
        try:
            resources.native_resource_path('generic_scalar_field.lua')
        except FileNotFoundError:
            pass
        else:
            raise AssertionError('missing installed scalar resource was accepted')
    finally:
        hidden.rename(resource)
    assert resource.read_bytes() == original
    print('INSTALLED_GENERIC_DYNAMIC=PASS model=rf_pulse basis=compiled lua=api_stub missing_resource=refused restored=1 native=none', flush=True)


def run(root, lua_provider):
    from msplatform import assembly, components
    from msplatform.backends import simion
    from msplatform.backends.simion import generic_geometry
    import msplatform.capabilities as capability_module
    import msplatform.components.geometry_members as geometry_members_module
    from msplatform.capabilities import capabilities
    from msplatform.components.geometry_members import assembly_geometry_members
    purelib=Path(sysconfig.get_paths()['purelib']).resolve()
    for module in (assembly,components,simion,generic_geometry,capability_module,geometry_members_module):
        assert Path(module.__file__).resolve().is_relative_to(purelib),module.__file__
    provider=Path(root)/'installed_registered_component.py'
    spec=importlib.util.spec_from_file_location('installed_registered_component',provider)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    module.ensure_registered()
    a=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':2}})
    b=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':3}})
    def pose(x):return dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[x,0,0])
    recipe=dict(schema_version=1,role='assembly_recipe',integration_id='unlisted_fixture',recipe_id='two_instances',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='second',project_id='toy_registered',transform=pose(10)),dict(instance_id='first',project_id='toy_registered',transform=pose(0))],connections=[])
    product=assembly.assemble(recipe,{'first':a,'second':b})
    numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-20,-20,-20],maximum_mm=[20,20,20]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='first',electrode_group_id='body',gu=[20,20,20]),dict(instance_id='second',electrode_group_id='body',gu=[30,20,20])],void_witnesses=[[0,0,0]])
    compiled=simion.compile_geometry(product,numerics=numerics)
    assert len(compiled.frontend_geometry['physical_samples'])==3
    renamed=copy.deepcopy(recipe);renamed['instances']=[dict(instance_id='alpha',project_id='toy_registered',transform=pose(0)),dict(instance_id='beta',project_id='toy_registered',transform=pose(10))]
    second=assembly.assemble(renamed,{'alpha':a,'beta':b})
    renamed_numerics=copy.deepcopy(numerics);renamed_numerics['metal_witnesses'][0]['instance_id']='alpha';renamed_numerics['metal_witnesses'][1]['instance_id']='beta'
    renamed_compiled=simion.compile_geometry(second,numerics=renamed_numerics)
    assert len(renamed_compiled.frontend_geometry['physical_samples'])==3
    def geometry(assembly_value):
        snapshot=dict(composition_plan=assembly_value.composition_plan,components_resolved=assembly_value.components_resolved,components_source=assembly_value.components_source)
        return sorted((tuple(row['shape']['parts'][0]['size_mm']),tuple(row['transform']['translation_mm'])) for row in assembly_geometry_members(snapshot))
    assert geometry(product)==geometry(second)
    bad=copy.deepcopy(numerics);bad['boundary']='grounded_faces'
    capability=capabilities(dict(schema_version=1,operation='compile_geometry',arguments=dict(assembly=product,numerics=bad)))
    assert capability['contract_status']=='rejected',capability
    # Exercise the installed static scientific and tracking planners; no solver or Fly.
    from msplatform import examples, ion_release
    from msplatform.backends.simion import model, field_execution, tracking_execution, rf_tracking_program
    from msplatform.backends.simion.resources import native_resource_path
    from msplatform.io.manifest_records import file_record
    from importlib.resources import files
    for selected_module in (model,field_execution,tracking_execution,rf_tracking_program,examples,ion_release):
        assert Path(selected_module.__file__).resolve().is_relative_to(purelib), selected_module.__file__
    for name in ('model_drive.lua','rf_drive.lua','rf_tracking.lua','export_detached_standalone_pa.lua','audit_static_operating_pa.lua'):
        assert native_resource_path(name).resolve().is_relative_to(purelib), name
    release=copy.deepcopy(examples.load_example('rf_oatof_functional_v1').release)
    release['source_component_id']='first'
    release['release_spec']['frame_id']='toy_local'
    release['release_spec']['particle_count']=release['release_spec']['mother_particle_count']=2
    release['particle_ids']=release['particle_ids'][:2]
    packet=ion_release.sample_release(release).to_dict()
    clock=dict(packet['clock'],phase_reference_instrument_time_us=0.)
    drive=dict(clock=clock,groups={'first':{'body':dict(kind='static',voltage_v=1.25)},
                                  'second':{'body':dict(kind='static',voltage_v=0.)}})
    prepared=model.compile_prepared_model(compiled,product.components_resolved,drive=drive,physics=model.RF_PHYSICS)
    doc=model.require_prepared_model(prepared)
    assert doc['field_status']=='not_solved' and doc['drive']==drive
    mapped={(row['instance_id'],row['electrode_group_id']):row['native_targets'][0]['electrode_id'] for row in doc['native_drive_rows']}
    assert mapped=={(row['instance_id'],row['electrode_group_id']):row['native_id'] for row in compiled.frontend_geometry['electrode_mapping']}
    graph=field_execution.plan_fields_execution(prepared,numerics=dict(refine_policy='vendor_default'))
    assert graph['expected_operation_ids']==['materialize_geometry','refine_world','audit_family','export_operating','audit_fields']
    epoch=Path(str(files('msplatform.examples').joinpath('instrument_epoch_v1.json')))
    authority=Path(str(files('msplatform.examples').joinpath('instrument_clock_authority_v1.json')))
    assert epoch.resolve().is_relative_to(purelib) and authority.resolve().is_relative_to(purelib)
    clocks={'instrument_epoch':file_record(epoch),'clock_authority':file_record(authority)}
    propagation=dict(schema_version=1,scope='continuous_assembly',end_policy=dict(maximum_particle_age_us=200.),
        consumed_plane_events=[],stop=None,dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none'))
    tracking_numerics=dict(maximum_step_us=.01,trajectory_quality=5,grouped=0)
    options=dict(particles=packet,clock_records=clocks,propagation=propagation,
                 observations=dict(plane_observations=[]),numerics=tracking_numerics)
    tracking=tracking_execution.plan_tracking_execution(prepared,**options)
    assert tracking['flight']['tracking_kind']=='static_world' and len(tracking['rows'])==2
    controls=rf_tracking_program.render_rf_controls(prepared,tracking,assets={},native_sources={})
    assert 'local rf_static_operating=true' in controls['program']
    assert controls['build_metadata']['static_operating_voltages']==sorted(
        [dict(electrode_id=row['native_targets'][0]['electrode_id'],voltage_v=row['voltage_v'])
         for row in doc['native_drive_rows']],key=lambda row:row['electrode_id'])
    outside=copy.deepcopy(packet)
    outside['rows'][0]['position_x_mm']=1000.
    try: tracking_execution.plan_tracking_execution(prepared,**dict(options,particles=outside))
    except ValueError as exc: assert 'outside' in str(exc),exc
    else: raise AssertionError('outside-domain original birth was accepted')
    run_dynamic(root, product, compiled, packet, clocks, propagation, lua_provider)
    print('INSTALLED_GENERIC_STATIC_PLANNING=PASS groups=2 births=2 outside_refused=1 native=none',flush=True)
    print('INSTALLED_GENERIC_REGISTERED_GEOMETRY=PASS instances=2 renamed=1 capability_rejected=1 pure_compile=1',flush=True)

def run_neutral_ip(root, lua_provider):
    """Exercise the installed canonical scheduled-IP consumer with portable Lua APIs."""
    import json
    import subprocess
    from msplatform import assembly, components
    from msplatform.backends.comsol import assembly_geometry, assembly_electrostatic_model
    from msplatform.backends.simion import model, generic_scalar_binding, rf_tracking_program, resources

    from msplatform.io.manifest_records import verify_record

    purelib = Path(sysconfig.get_paths()['purelib']).resolve()
    for module in (assembly, components, assembly_geometry, assembly_electrostatic_model, model,
                   generic_scalar_binding, rf_tracking_program, resources):
        assert Path(module.__file__).resolve().is_relative_to(purelib), module.__file__
    fixture = json.loads((Path(root) / 'installed_neutral_ip_fixture.json').read_text(encoding='utf8'))
    component = components.resolve_component(fixture['request'])
    product = assembly.assemble(fixture['recipe'], {'ion_processor': component})
    from msplatform.backends.simion.operations import compile_geometry
    compiled = compile_geometry(product, numerics=fixture['numerics'])
    electrodes = product.components_resolved['ion_processor']['projection']['electrodes']
    assert len(electrodes) == 15
    clock = fixture['clock']
    drive = dict(clock=dict(clock, phase_reference_instrument_time_us=0.),
        ip_schedule=dict(baseline=product.components_source['ion_processor']['baseline'],
                         native_operating_point=fixture['operating_point'], clock=clock),
        groups={'ion_processor': {e['name']: dict(kind='ip_schedule', schedule_index=e['electrode_id']) for e in electrodes}})
    prepared = model.compile_prepared_model(compiled, product.components_resolved, drive=drive, physics=model.RF_PHYSICS)
    document = model.require_prepared_model(prepared)
    snapshot = dict(composition_plan=product.composition_plan, components_resolved=product.components_resolved,
                    components_source=product.components_source)
    projection = assembly_geometry.project_assembly_geometry(snapshot, outer_box_mm={'min': [-1000]*3, 'max': [1000]*3})
    groups = [(g['instance_id'], g['electrode_group_id']) for g in projection['electrode_groups']]
    samples = {}; bases = {}; weights = {}
    for index, key in enumerate(groups):
        name = str(index)
        rows = [dict(instance_id=i, electrode_group_id=g, weight=float((i, g) == key)) for i, g in groups]
        request = assembly_electrostatic_model.validate_request(projection, dict(
            group_voltages=[dict(instance_id=r['instance_id'], electrode_group_id=r['electrode_group_id'], voltage_v=r['weight']) for r in rows],
            relative_permittivity=1., exterior={'kind': 'potential', 'voltage_v': 0.},
            mesh={'global_automatic_level': 5, 'electrode_hmax_mm': 4.}, study={'kind': 'stationary'}))
        samples[name] = {'request': request, 'weights': rows}; weights[name] = rows
        bases[name] = dict(grid=dict(frame_id='world', origin_mm=[0,0,0], pitch_mm=[1,1,1], dimensions=[3,3,3]),
            records={'field_v': {'path': 'basis_'+name}, 'field_valid': {'path': 'basis_'+name+'_field_valid'}}, ideal_sheet_projection=[])
    terms = generic_scalar_binding.compile_linear_terms(projection, document['drive'], samples)
    assert sum(name.startswith('schedule_') for name in terms['terms']) == len(electrodes)
    try: generic_scalar_binding.compile_linear_terms(projection, document['drive'], dict(list(samples.items())[1:]))
    except ValueError: pass
    else: raise AssertionError('incomplete IP basis accepted')
    names = ('scalar_field_adapter.lua','generic_scalar_field.lua','model_drive.lua','rf_drive.lua','rf_tracking.lua',
             'single_flight_pulse_hook.lua','voltage_waveforms.lua','native_drive.lua')
    paths = {name: resources.native_resource_path(name).resolve(strict=True) for name in names}
    assert all(path.is_relative_to(purelib) for path in paths.values())
    native_sources = {name: path.read_text(encoding='utf8') for name, path in paths.items()}
    admission = dict(role='generic_linear_scalar_admission', model_identity_sha256=document['model_identity_sha256'], bases=bases, weights=weights)
    row = dict(particle_id=7,instrument_time_us=0.,particle_birth_time_us=0.,velocity_x_m_s=1.,velocity_y_m_s=2.,velocity_z_m_s=3.)
    plan = dict(flight=dict(tracking_kind='neutral_sampled',has_ip_schedule=True,maximum_step_us=1.,rf_steps_per_period=80,trajectory_quality=17,grouped=0),
        rows=[row], absolute_deadlines_us_by_particle_id={7:200.}, observations=dict(plane_observations=[]), propagation=dict(consumed_plane_events=[],stop=None))
    program = rf_tracking_program.render_rf_controls(prepared, plan, assets={}, native_sources=native_sources,
        scalar_bindings=admission, slot_domains=[None,'world'])['program']
    # Renderer falls back to its installed resource loader when a frozen entry is absent.
    # Simulate a missing installed resource without mutating either installation or checkout.
    from unittest.mock import patch
    missing_sources = dict(native_sources); missing_sources.pop('native_drive.lua')
    with patch.object(rf_tracking_program, 'native_resource_path', side_effect=FileNotFoundError('native_drive.lua')):
        try:
            rf_tracking_program.render_rf_controls(prepared, plan, assets={}, native_sources=missing_sources,
                scalar_bindings=admission, slot_domains=[None,'world'])
        except FileNotFoundError as error:
            assert 'native_drive.lua' in str(error), error
        else:
            raise AssertionError('missing native_drive.lua was accepted')
    baseline=document['drive']['ip_schedule']['baseline']; timing=document['drive']['ip_schedule']['native_timing']
    edges=sorted(set([baseline['schedule'][k] for k in ('capture_end_us','transfer_end_us','lift_end_us','terminal_us')]+[timing['primary_quench_us'],timing['pulse_start_us']]))
    cap=1e6/baseline['electric']['rf_frequency_hz']/80; edge=next(x for x in edges if x>cap); epsilon=cap/4
    suffix=("\nsegment.initialize_run();segment.initialize();ion_time_step=1;segment.tstep_adjust();assert(math.abs(ion_time_step-%.17g)<1e-12);" % cap
        + "ion_time_of_flight=%.17g;ion_time_step=1;segment.tstep_adjust();assert(math.abs(ion_time_step-%.17g)<1e-12);" % (edge-epsilon,epsilon)
        + "ion_instance=2;calls=0;segment.efield_adjust();local total=0;for _,r in ipairs(rf_consumer.evaluate_at(single_flight_instrument_time_us())) do total=total+r.voltage_v end;assert(calls==%d and math.abs(ion_dvoltsx_gu+total)<1e-8);print('INSTALLED_NEUTRAL_IP_LUA=PASS')\n" % len(electrodes))
    script=Path(root)/'installed_neutral_ip.lua';script.write_text(fixture['lua_prefix']+'\n'+program.replace('adjustable ','')+suffix,encoding='utf8')
    verify_record('installed IP Lua before',lua_provider)
    result=subprocess.run([str(Path(lua_provider['path']).resolve(strict=True)),str(script)],cwd=root,capture_output=True,text=True,encoding='utf8',timeout=30,check=False)
    verify_record('installed IP Lua after',lua_provider)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'INSTALLED_NEUTRAL_IP_LUA=PASS' in result.stdout
    print('INSTALLED_NEUTRAL_IP=PASS groups=15 basis=complete lua=api_stub native=none',flush=True)
