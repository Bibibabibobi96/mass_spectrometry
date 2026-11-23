"""Real canonical IP and typed HS1 preparation, no solver or native Fly."""
import json
import tempfile
import unittest
from pathlib import Path

from tests.contracts import test_neutral_ip_primitives as fixture
from tests.components.dual_pressure_rectilinear_ion_processor.test_functional import HS1_SOURCE_FIXTURE
from msplatform.backends.simion.model import RF_PHYSICS, compile_prepared_model
from msplatform.backends.simion.rf_tracking_execution import prepare_neutral_ip_hs1
from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasSource, GasSpecies, GasState
from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import file_record

SOURCE = Path(fixture.__file__).resolve().parents[2]
def box(lo, hi):
    return BoxDomain(lo, hi, (True, True, True), (True, True, True))

class NeutralCanonicalHs1Tests(unittest.TestCase):
    def test_real_schedule_vendor_and_outer_coverage(self):
        fixture.CanonicalIpNeutralTests.setUpClass()
        case=fixture.CanonicalIpNeutralTests(methodName='runTest')
        assembly=case.assembly
        geometry=case.compile_complete(assembly)
        epoch={'clock_epoch_id':'instrument_clock_epoch_v1','authority_sha256':file_sha256(SOURCE/'src/msplatform/examples/instrument_epoch_v1.json')}
        point=json.loads((SOURCE/'src/msplatform/components/dual_pressure_rectilinear_ion_processor/config/native_operating_point.json').read_text(encoding='utf8'))
        electrodes=assembly.components_resolved['ion_processor']['projection']['electrodes']
        drive={'clock':dict(epoch,phase_reference_instrument_time_us=0.),'ip_schedule':{'baseline':assembly.components_source['ion_processor']['baseline'],'native_operating_point':point,'clock':epoch},'groups':{'ion_processor':{e['name']:{'kind':'ip_schedule','schedule_index':e['electrode_id']} for e in electrodes}}}
        model=compile_prepared_model(geometry,assembly.components_resolved,drive=drive,physics=RF_PHYSICS)
        import copy
        keyed_drive=copy.deepcopy(drive)
        keyed_drive['ip_schedules']={'ion_processor':keyed_drive.pop('ip_schedule')}
        keyed_model=compile_prepared_model(geometry,assembly.components_resolved,drive=keyed_drive,physics=RF_PHYSICS)
        baseline=model.document['drive']['ip_schedule']['baseline']
        outer=GasFieldSpec(field_id='outer',frame_id=baseline['clock']['frame_id'],representation='uniform',composition_id='ion_processor_explicit_single_gas',composition=(GasSpecies('ion_processor_model_gas',baseline['gas']['mass_amu'],1),),domain=box((-10000,-10000,-10000),(10000,10000,10000)),source=GasSource('prescribed','test',()),uniform_state=GasState('vacuum',0,baseline['gas']['temperature_k'],(0,0,0)))
        domain=geometry.frontend_geometry['domain']
        grid={'frame_id':domain['frame_id'],'origin_mm':domain['minimum_mm'],'pitch_mm':[b-a for a,b in zip(domain['minimum_mm'],domain['maximum_mm'],strict=True)],'dimensions':[2,2,2]}
        with tempfile.TemporaryDirectory() as directory:
            vendor=Path(directory)/'vendor.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf8')
            request={'bath_domain':box((0,-10,-10),(211,10,10)),'outer':outer,'vendor_record':file_record(vendor),'numerics':{'seed':42,'hs1_steps_per_mfp':20}}
            result=prepare_neutral_ip_hs1(model,request,basis={'grid':grid})
            self.assertEqual(result['identity']['numerics'],request['numerics'])
            keyed_result=prepare_neutral_ip_hs1(keyed_model,request,basis={'grid':grid})
            self.assertEqual(keyed_result['identity'],result['identity'])
            self.assertEqual(keyed_result['bath_runtime'],result['bath_runtime'])
            self.assertEqual(keyed_result['outer_runtime'],result['outer_runtime'])
            # An admitted active window beyond the base still needs explicit outer gas.
            from dataclasses import replace
            base_grid={'frame_id':domain['frame_id'],'origin_mm':[-1,-1,-1],'pitch_mm':[1,1,1],'dimensions':[3,3,3]}
            level={'grid':{'frame_id':domain['frame_id']},'active_box_mm':[[4,6],[-1,1],[-1,1]]}
            routed={'grid':base_grid,'bases':{'sample':{'refinement_windows':[level]}}}
            expanded=prepare_neutral_ip_hs1(model,request,basis=routed)
            self.assertEqual(expanded['identity']['common_world_domain']['maximum_mm'][0],6)
            too_small=dict(request,outer=replace(outer,domain=box((-1,-1,-1),(1,1,1))))
            with self.assertRaisesRegex(ValueError,'complete parent box'):
                prepare_neutral_ip_hs1(model,too_small,basis=routed)
            from unittest.mock import patch
            from msplatform import examples, ion_release
            from msplatform.backends.simion.tracking_execution import plan_tracking_execution
            packet=ion_release.sample_release(examples.load_example('rf_oatof_functional_v1').release).to_dict()
            for source_row in packet['rows']:
                source_row['source_component_id']=source_row['target_component_id']='ion_processor'
                source_row['frame_id']='dual_pressure_ion_processor_local_v1'
                mother=packet['mother']['records'][source_row['particle_id']]
                mother['source_component_id']=mother['target_component_id']='ion_processor';mother['frame_id']=source_row['frame_id']
            clocks={name:file_record(SOURCE/'src/msplatform/examples'/filename) for name,filename in [('clock_authority','instrument_clock_authority_v1.json'),('instrument_epoch','instrument_epoch_v1.json')]}
            propagation={'schema_version':1,'scope':'continuous_assembly','dynamics':{'kinematics':'nonrelativistic','collisions':'hs1','space_charge':'none'},'end_policy':{'maximum_particle_age_us':200.},'consumed_plane_events':[],'stop':None}
            with patch('msplatform.backends.simion.rf_tracking_execution.admit_neutral_sampled_tracking_fields',return_value={'model':model,'basis':{'grid':grid},'code_records':{}}):
                planned=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=propagation,observations={'plane_observations':[]},numerics={'maximum_step_us':.001,'trajectory_quality':17,'rf_steps_per_period':80,'grouped':0},hs1_request=request,neutral_sampled_field_reference={'test_only':True})
                self.assertTrue(planned['flight']['has_hs1'])
                self.assertEqual(planned['hs1_identity'],result['identity'])
                self.assertEqual(planned['propagation']['dynamics']['collisions'],'hs1')
                no_collision=dict(propagation,dynamics=dict(propagation['dynamics'],collisions='none'))
                plain=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=no_collision,observations={'plane_observations':[]},numerics={'maximum_step_us':.001,'trajectory_quality':17,'rf_steps_per_period':80,'grouped':0},neutral_sampled_field_reference={'test_only':True})
                self.assertNotIn('has_hs1',plain['flight'])
                with self.assertRaises(ValueError):
                    plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=propagation,observations={'plane_observations':[]},numerics={'maximum_step_us':.001,'trajectory_quality':17,'rf_steps_per_period':80,'grouped':0},neutral_sampled_field_reference={'test_only':True})
            self.assertEqual(result['query_frame_id'],domain['frame_id'])
            self.assertEqual(result['identity']['common_world_domain']['minimum_mm'],tuple(domain['minimum_mm']))
            self.assertIn('pressure',result['bath_runtime'])
            from msplatform.backends.simion.rf_tracking_program import render_rf_controls
            from msplatform.backends.simion.resources import native_resource_path
            names=('scalar_field_adapter.lua','generic_scalar_field.lua','rf_ip_tracking_hs1.lua',
                   'collision_hs1_gas.lua','rf_ip_gas_selection.lua','model_drive.lua','rf_drive.lua',
                   'rf_tracking.lua','native_drive.lua','single_flight_pulse_hook.lua','voltage_waveforms.lua')
            resources={name:native_resource_path(name).read_text(encoding='utf8') for name in names}
            group_keys=[(row['instance_id'],row['electrode_group_id']) for row in model.document['native_drive_rows']]
            bases={};weights={}
            for index,key in enumerate(group_keys):
                name=str(index)
                bases[name]={'grid':{'frame_id':domain['frame_id'],'origin_mm':[0,0,0],'pitch_mm':[1,1,1],'dimensions':[3,3,3]},'records':{'field_v':{'path':'C:/inert/'+name},'field_valid':{'path':'C:/inert/'+name+'_mask'}},'ideal_sheet_projection':[]}
                weights[name]=[{'instance_id':i,'electrode_group_id':g,'weight':float((i,g)==key)} for i,g in group_keys]
            binding={'role':'generic_linear_scalar_admission','model_identity_sha256':model.document['model_identity_sha256'],'bases':bases,'weights':weights}
            row={'particle_id':7,'instrument_time_us':0.,'particle_birth_time_us':0.,'velocity_x_m_s':1.,'velocity_y_m_s':2.,'velocity_z_m_s':3.}
            row2=dict(row,particle_id=91)
            plan={'flight':{'tracking_kind':'neutral_sampled','has_ip_schedule':True,'has_hs1':True,'maximum_step_us':1.,'rf_steps_per_period':80,'trajectory_quality':17,'grouped':0},'rows':[row,row2],'absolute_deadlines_us_by_particle_id':{7:200.,91:200.},'hs1':{'vendor_path':str(vendor),'bath_path':str(Path(directory)/'bath.lua'),'outer_path':str(Path(directory)/'outer.lua'),'query_frame_id':domain['frame_id'],'numerics':request['numerics']},'observations':{'plane_observations':[]},'propagation':{'consumed_plane_events':[],'stop':None}}
            rendered=render_rf_controls(model,plan,assets={},native_sources=resources,scalar_bindings=binding,slot_domains=[None,'world'])
            self.assertIn('joint_hs1.install(',rendered['program'])
            self.assertIn('single_flight_canonical_particle_id',rendered['program'])
            self.assertIn('joint_saved_segments.initialize',rendered['program'])
            # Execute the generated callbacks with the existing SIMION API double.
            import ast, os, shutil, subprocess
            tree=ast.parse((SOURCE/'tests/contracts/test_ip_mr_tracking_program.py').read_text(encoding='utf8'))
            prefix=next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prefix' for t in n.targets)).replace('BG_INDEX','2')
            prefix=prefix.replace('function hs.segment.other_actions() end','local collisions=0; function hs.segment.other_actions() collisions=collisions+1 end')
            Path(plan['hs1']['bath_path']).write_text(result['bath_runtime'],encoding='utf8')
            Path(plan['hs1']['outer_path']).write_text(result['outer_runtime'],encoding='utf8')
            prefix += '\nlocal joint_hs1_frame=' + __import__('msplatform.backends.simion.source',fromlist=['lua_value']).lua_value(domain['frame_id']) + '\n'
            suffix="\nsegment.initialize_run(); assert(seeds[#seeds]==42); segment.initialize(); segment.tstep_adjust(); segment.other_actions(); assert(seeds[#seeds]==48 and collisions==1); segment.terminate(); ion_number=2; segment.initialize(); segment.tstep_adjust(); segment.other_actions(); assert(seeds[#seeds]==132 and collisions==2); segment.terminate(); ion_number=1; assert(not pcall(segment.tstep_adjust)); ion_px_mm=1000000; assert(not pcall(hs.pressure)); ion_px_mm=1; assert(joint_selector.sample(9000,9000,9000,joint_hs1_frame).pressure_pa==0); assert(joint_selector.sample(1000000,1000000,1000000,joint_hs1_frame).status=='outside_domain'); ion_number=1; segment.initialize_run(); assert(seeds[#seeds]==42); segment.initialize(); segment.tstep_adjust(); assert(seeds[#seeds]==48); print('NEUTRAL_HS1_CALLBACK=PASS')\n"
            lua=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1') or 'C:/Program Files/SIMION-2020/lua.exe'
            if not lua: raise FileNotFoundError('portable Lua required')
            script=Path(directory)/'check.lua';script.write_text(prefix+'\n'+rendered['program'].replace('adjustable ','')+suffix,encoding='utf8')
            run=subprocess.run([lua,str(script)],cwd=directory,capture_output=True,text=True,encoding='utf8',timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('NEUTRAL_HS1_CALLBACK=PASS',run.stdout)
            bad=dict(request);bad['vendor_record']=dict(request['vendor_record'],sha256='0'*64)
            with self.assertRaises(AssertionError):prepare_neutral_ip_hs1(model,bad,basis={'grid':grid})
