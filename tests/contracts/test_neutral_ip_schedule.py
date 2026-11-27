"""Canonical registered IP schedule through neutral pure compilation; no native owner."""
import copy
import json
import unittest
from pathlib import Path
from tests.contracts import test_neutral_ip_primitives as primitive_fixture
from msplatform.backends.simion.model import RF_PHYSICS, compile_prepared_model, require_prepared_model
from msplatform.backends.simion.generic_scalar_binding import compile_linear_terms
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.io.file_identity import file_sha256

V=Path(__file__).resolve().parents[2]

class CanonicalNeutralScheduleTests(unittest.TestCase):
    def test_canonical_model_span_and_rename_order(self):
        primitive_fixture.CanonicalIpNeutralTests.setUpClass()
        fixture=primitive_fixture.CanonicalIpNeutralTests(methodName='runTest')
        assembly=fixture.assembly
        geometry=fixture.compile_complete(assembly);print('REAL_PUBLIC_GEOMETRY',len(geometry.frontend_geometry['members']),len(geometry.frontend_geometry['electrode_mapping']),flush=True)
        identity={'clock_epoch_id':'instrument_clock_epoch_v1','authority_sha256':file_sha256(V/'src/msplatform/examples/instrument_epoch_v1.json')};point=json.loads((V/'src/msplatform/components/ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
        electrodes=assembly.components_resolved['ion_processor']['projection']['electrodes'];drive={'clock':dict(identity,phase_reference_instrument_time_us=0.),'ip_schedule':{'baseline':assembly.components_source['ion_processor']['baseline'],'native_operating_point':point,'clock':identity},'groups':{'ion_processor':{e['name']:{'kind':'ip_schedule','schedule_index':e['electrode_id']} for e in electrodes}}}
        model=compile_prepared_model(geometry,assembly.components_resolved,drive=drive,physics=RF_PHYSICS);doc=require_prepared_model(model);assert len(doc['native_drive_rows'])==len(electrodes);print('REAL_MODEL',len(electrodes),flush=True)
        recompiled=compile_prepared_model(geometry,assembly.components_resolved,drive=doc['drive'],physics=RF_PHYSICS);assert require_prepared_model(recompiled)==doc
        for change in ('missing','misbound','clock'):
         bad=copy.deepcopy(drive)
         if change=='missing':bad['groups']['ion_processor'].pop(electrodes[0]['name'])
         if change=='misbound':bad['groups']['ion_processor'][electrodes[0]['name']]['schedule_index']=999
         if change=='clock':bad['ip_schedule']['clock']['authority_sha256']='0'*64
         try:compile_prepared_model(geometry,assembly.components_resolved,drive=bad,physics=RF_PHYSICS)
         except (ValueError,KeyError):pass
         else:raise AssertionError('invalid model accepted '+change)
        snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
        proj=project_assembly_geometry(snapshot,outer_box_mm={'min':[-1000]*3,'max':[1000]*3});groups=[(g['instance_id'],g['electrode_group_id']) for g in proj['electrode_groups']];operator=dict(relative_permittivity=1.,exterior={'kind':'potential','voltage_v':0.},mesh={'global_automatic_level':5,'electrode_hmax_mm':4.},study={'kind':'stationary'});samples={}
        for index,key in enumerate(groups):
         request=validate_request(proj,dict(group_voltages=[dict(instance_id=i,electrode_group_id=g,voltage_v=float((i,g)==key)) for i,g in groups],**operator))
         samples[str(index)]={'request':request,'weights':[dict(instance_id=i,electrode_group_id=g,weight=float((i,g)==key)) for i,g in groups]}
        plan=compile_linear_terms(proj,doc['drive'],samples);assert sum(x.startswith('schedule_') for x in plan['terms'])==len(electrodes)
        try:compile_linear_terms(proj,doc['drive'],dict(list(samples.items())[1:]))
        except ValueError:pass
        else:raise AssertionError('incomplete basis accepted')
        print('REAL_CANONICAL_IP_MODEL_AND_SPAN=PASS',flush=True)

        # A real RF + IP assembly, then reverse declaration order and rename both instances.
        from importlib.resources import files
        from msplatform.components.catalog import resolve_component
        from msplatform.assembly.factory import assemble
        from msplatform.backends.simion.operations import compile_geometry
        example=json.loads(files('msplatform').joinpath('examples/rf_oatof_functional_v1.json').read_text(encoding='utf8'));rf=resolve_component(example['component_requests']['multipole'])
        recipe=copy.deepcopy(assembly.composition_plan['recipe']);recipe['instances'].insert(0,dict(instance_id='multipole',project_id='rf_multipole_ion_optics',transform=dict(schema_version=1,role='rigid_transform',from_frame_id=rf.assembly_interface['local_frame_id'],to_frame_id=recipe['assembly_frame_id'],rotation=[[0,-1,0],[0,0,1],[-1,0,0]],translation_mm=[0,-305.6,3])))
        recipe['connections']=[dict(connection_id='rf_to_ip',upstream=dict(instance_id='multipole',port_id='mechanical_exit'),downstream=dict(instance_id='ion_processor',port_id='guide_inlet'),gap_mm=1.,coupling_mode='monolithic_joint_solve')]
        joined=assemble(recipe,{'ion_processor':fixture.component,'multipole':rf});joined_geometry=fixture.compile_complete(joined)
        rename={'ion_processor':'z_ip','multipole':'a_rf'}
        renamed_recipe=copy.deepcopy(recipe);renamed_recipe['instances'].reverse()
        for row in renamed_recipe['instances']:row['instance_id']=rename[row['instance_id']]
        for row in renamed_recipe['connections']:
         for end in ('upstream','downstream'):row[end]['instance_id']=rename[row[end]['instance_id']]
        renamed=assemble(renamed_recipe,{'z_ip':fixture.component,'a_rf':rf});g=joined_geometry.frontend_geometry
        numerics={k:copy.deepcopy(g[k]) for k in ('domain','pitch_mm','boundary','metal_witnesses','void_witnesses')};numerics['representation']='neutral_world_collision'
        for row in numerics['metal_witnesses']:row['instance_id']=rename[row['instance_id']]
        renamed_geometry=compile_geometry(renamed,numerics=numerics)
        for candidate,name in ((joined_geometry,'ion_processor'),(renamed_geometry,'z_ip')):
         groups={}
         for row in candidate.frontend_geometry['electrode_mapping']:
          groups.setdefault(row['instance_id'],{})[row['electrode_group_id']]=({'kind':'ip_schedule','schedule_index':next(e['electrode_id'] for e in electrodes if e['name']==row['electrode_group_id'])} if row['instance_id']==name else {'kind':'static','voltage_v':0.})
         from msplatform.backends.simion.electrode_contract import scientific_multipole_drive
         rf_id=next(instance for instance in groups if instance!=name)
         rf_map={row['electrode_group_id']:row['native_id'] for row in candidate.frontend_geometry['electrode_mapping'] if row['instance_id']==rf_id}
         groups[rf_id]=scientific_multipole_drive(candidate.components_resolved[rf_id],rf_map)
         candidate_drive=copy.deepcopy(drive);candidate_drive['groups']=groups
         candidate_model=compile_prepared_model(candidate,candidate.components_resolved,drive=candidate_drive,physics=RF_PHYSICS)
         if name=='ion_processor':joined_model=candidate_model
         assert len(require_prepared_model(candidate_model)['native_drive_rows'])==len(candidate.frontend_geometry['electrode_mapping'])
        print('REAL_RF_IP_RENAME_REORDER_MODEL=PASS',flush=True)


        # Actual neutral Program with real canonical schedule/model and inert Lua PA API.
        import ast,subprocess,tempfile
        from msplatform.backends.simion.rf_tracking_program import render_rf_controls
        from msplatform.backends.simion.resources import native_resource_path
        names=('scalar_field_adapter.lua','generic_scalar_field.lua','model_drive.lua','rf_drive.lua','rf_tracking.lua','single_flight_pulse_hook.lua','voltage_waveforms.lua','native_drive.lua')
        resources={n:native_resource_path(n).read_text(encoding='utf8') for n in names}
        items={};weights={}
        for name,item in samples.items():
         items[name]=dict(grid=dict(frame_id='world',origin_mm=[0,0,0],pitch_mm=[1,1,1],dimensions=[3,3,3]),records={'field_v':{'path':'basis_'+name},'field_valid':{'path':'basis_'+name+'_field_valid'}},ideal_sheet_projection=[])
         weights[name]=item['weights']
        admission=dict(role='generic_linear_scalar_admission',model_identity_sha256=doc['model_identity_sha256'],bases=items,weights=weights)
        row=dict(particle_id=7,instrument_time_us=0.,particle_birth_time_us=0.,velocity_x_m_s=1.,velocity_y_m_s=2.,velocity_z_m_s=3.)
        plan=dict(flight=dict(tracking_kind='neutral_sampled',has_ip_schedule=True,maximum_step_us=1.,rf_steps_per_period=80,trajectory_quality=17,grouped=0),rows=[row],absolute_deadlines_us_by_particle_id={7:200.},observations=dict(plane_observations=[]),propagation=dict(consumed_plane_events=[],stop=None))
        rendered=render_rf_controls(model,plan,assets={},native_sources=resources,scalar_bindings=admission,slot_domains=[None,'world'])
        tree=ast.parse((V/'tests/contracts/test_ip_mr_tracking_program.py').read_text(encoding='utf8'));prefix=next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prefix' for t in n.targets)).replace('BG_INDEX','2')
        baseline=doc['drive']['ip_schedule']['baseline'];timing=doc['drive']['ip_schedule']['native_timing'];edges=sorted(set([baseline['schedule'][k] for k in ('capture_end_us','transfer_end_us','lift_end_us','terminal_us')]+[timing['primary_quench_us'],timing['pulse_start_us']]))
        cap=1e6/baseline['electric']['rf_frequency_hz']/80;edge=next(x for x in edges if x>cap);epsilon=cap/4
        suffix=("\nsegment.initialize_run();segment.initialize();ion_time_step=1;segment.tstep_adjust();assert(math.abs(ion_time_step-%.17g)<1e-12);" % cap
         + "ion_time_of_flight=%.17g;ion_time_step=1;segment.tstep_adjust();assert(math.abs(ion_time_step-%.17g)<1e-12);" % (edge-epsilon,epsilon)
         + "ion_instance=2;calls=0;segment.efield_adjust();local total=0;for _,r in ipairs(rf_consumer.evaluate_at(single_flight_instrument_time_us())) do total=total+r.voltage_v end;assert(calls==15 and math.abs(ion_dvoltsx_gu+total)<1e-8 and math.abs(ion_dvoltsy_gu+2*total)<1e-8 and math.abs(ion_dvoltsz_gu+3*total)<1e-8);print('NEUTRAL_SCHEDULE_PROGRAM=PASS')\n")
        import os,shutil
        lua=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1') or 'C:/Program Files/SIMION-2020/lua.exe'
        if not lua:raise FileNotFoundError('standalone Lua provider required')
        with tempfile.TemporaryDirectory() as temp:
         path=Path(temp)/'probe.lua';path.write_text(prefix+'\n'+rendered['program'].replace('adjustable ','')+suffix,encoding='utf8');run=subprocess.run([lua,str(path)],cwd=temp,capture_output=True,text=True,encoding='utf8',timeout=30);print(run.stdout,run.stderr,flush=True);assert run.returncode==0

        # Real original release and public planning, no field read or owner.
        from msplatform import examples as example_api,ion_release as release_api
        from msplatform.io.manifest_records import file_record
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        packet=release_api.sample_release(example_api.load_example('rf_oatof_functional_v1').release).to_dict()
        clock_records={name:file_record(V/'src/msplatform/examples'/filename) for name,filename in [('clock_authority','instrument_clock_authority_v1.json'),('instrument_epoch','instrument_epoch_v1.json')]}
        prop=dict(schema_version=1,scope='continuous_assembly',dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none'),end_policy=dict(maximum_particle_age_us=200.),consumed_plane_events=[],stop=None)
        common=dict(model=joined_model,particles=packet,clock_records=clock_records,propagation=prop,observations={'plane_observations':[]})
        from unittest.mock import patch
        try:plan_tracking_execution(**common,numerics=dict(maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80))
        except ValueError as exc:assert 'requires published sampled field' in str(exc)
        else:raise AssertionError('unpublished sampled field accepted')
        # Test-only admission double: actual sampled product publication is still open.
        with patch('msplatform.backends.simion.rf_tracking_execution.admit_neutral_sampled_tracking_fields',return_value={'model':joined_model,'basis':{},'code_records':{}}):
         try:plan_tracking_execution(**common,numerics=dict(maximum_step_us=.001,trajectory_quality=17),neutral_sampled_field_reference={'test_only':True})
         except ValueError as exc:assert 'numerics' in str(exc)
         else:raise AssertionError('IP schedule accepted missing RF steps')
         actual_plan=plan_tracking_execution(**common,numerics=dict(maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80),neutral_sampled_field_reference={'test_only':True})
         assert actual_plan['flight']['has_ip_schedule'] and actual_plan['flight']['rf_steps_per_period']==80
         from msplatform.backends.simion import tracking_units
         with tempfile.TemporaryDirectory() as directory:
          changed=Path(directory)/'native_drive.lua';changed.write_bytes(native_resource_path('native_drive.lua').read_bytes())
          def resource_for_identity(name):return changed if name=='native_drive.lua' else native_resource_path(name)
          with patch('msplatform.backends.simion.resources.native_resource_path',side_effect=resource_for_identity):
           first=tracking_units.tracking_applicability(actual_plan)
           changed.write_bytes(changed.read_bytes()+b'-- altered identity\n')
           self.assertNotEqual(first,tracking_units.tracking_applicability(actual_plan))
        print('REAL_SOURCE_SCHEDULE_PLAN_WITH_ADMISSION_DOUBLE=PASS',flush=True)
