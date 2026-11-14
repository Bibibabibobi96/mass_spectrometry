"""Static neutral-world source-level model contract; no native qualification."""
import copy
import unittest
from msplatform import assembly, components
from msplatform.backends.simion.generic_geometry import compile_generic_collision_geometry
from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS
from common.contracts.test_support.registered_component import ensure_registered

class StaticWorldModelTests(unittest.TestCase):
    def setUp(self):
        ensure_registered()
        a=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':2}})
        b=components.resolve_component({'provider_id':'toy_registered','design':{'width_mm':3}})
        def pose(x):return dict(schema_version=1,role='rigid_transform',from_frame_id='toy_local',to_frame_id='world',rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[x,0,0])
        recipe=dict(schema_version=1,role='assembly_recipe',integration_id='toy_integration',recipe_id='toy_recipe',assembly_frame_id='world',position_tolerance_mm=1e-6,angular_tolerance_rad=1e-6,instances=[dict(instance_id='first',project_id='toy_registered',transform=pose(0)),dict(instance_id='second',project_id='toy_registered',transform=pose(10))],connections=[])
        self.assembly=assembly.assemble(recipe,{'first':a,'second':b})
        self.numerics=dict(representation='neutral_world_collision',domain=dict(frame_id='world',minimum_mm=[-5,-5,-5],maximum_mm=[20,5,5]),pitch_mm=1,boundary='native_zero_neumann',metal_witnesses=[dict(instance_id='first',electrode_group_id='body',gu=[5,5,5]),dict(instance_id='second',electrode_group_id='body',gu=[15,5,5])],void_witnesses=[[0,0,0]])
        self.compiled=compile_generic_collision_geometry(self.assembly,numerics=self.numerics)
        self.drive=dict(groups={'first':{'body':dict(kind='static',voltage_v=1.25)},'second':{'body':dict(kind='static',voltage_v=0)}},clock=dict(clock_epoch_id='test',authority_sha256='0'*64,phase_reference_instrument_time_us=0))
    def test_voltage_mapping_and_refusals(self):
        def compile_(drive=None,physics=RF_PHYSICS,compiled=None):return compile_prepared_model(compiled or self.compiled,self.assembly.components_resolved,drive=drive or self.drive,physics=physics).document
        shifted=copy.deepcopy(self.drive);shifted['clock']['phase_reference_instrument_time_us']=12.5
        self.assertEqual(compile_(shifted)['drive']['clock']['phase_reference_instrument_time_us'],12.5)
        from msplatform.backends.simion.model import _validate_timing
        with self.assertRaises(ValueError):_validate_timing(shifted,requires_pulse=False)
        for value in (float('nan'),float('inf')):
            invalid=copy.deepcopy(self.drive);invalid['clock']['phase_reference_instrument_time_us']=value
            with self.subTest(phase=value),self.assertRaises(ValueError):compile_(invalid)
        result=compile_();mapping={(r['instance_id'],r['electrode_group_id']):r['native_targets'][0] for r in result['native_drive_rows']}
        self.assertEqual(mapping,{(r['instance_id'],r['electrode_group_id']):dict(domain='world',electrode_id=r['native_id']) for r in self.compiled.frontend_geometry['electrode_mapping']})
        for bad in (True,float('nan'),float('inf')):
            drive=copy.deepcopy(self.drive);drive['groups']['first']['body']['voltage_v']=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):compile_(drive)
        drive=copy.deepcopy(self.drive);del drive['groups']['second']
        with self.assertRaises(ValueError):compile_(drive)
        drive=copy.deepcopy(self.drive);drive['groups']['first']['body']['kind']='rf'
        with self.assertRaises(ValueError):compile_(drive)
        with self.assertRaises(ValueError):compile_(physics=dict(RF_PHYSICS,boundary_policy='grounded_pa_faces'))
        damaged=copy.deepcopy(self.compiled);damaged.frontend_gems['world']+='--tamper'
        with self.assertRaises(ValueError):compile_(compiled=damaged)

    def test_static_field_graph_is_explicit(self):
        from msplatform.backends.simion.field_execution import plan_fields_execution
        model=compile_prepared_model(self.compiled,self.assembly.components_resolved,drive=self.drive,physics=RF_PHYSICS)
        graph=plan_fields_execution(model,numerics=dict(refine_policy='explicit_convergence',convergence_v={'world':1e-5}))
        self.assertEqual(graph['expected_operation_ids'],['materialize_geometry','refine_world','audit_fields'])
        for value in (True,0,-1,float('nan')):
            with self.subTest(value=value),self.assertRaises(ValueError):
                plan_fields_execution(model,numerics=dict(refine_policy='explicit_convergence',convergence_v={'world':value}))
        with self.assertRaises(ValueError):plan_fields_execution(model,numerics=dict(refine_policy='vendor_default',convergence_v=1))

    def test_public_model_plan_binds_world_assets(self):
        from pathlib import Path
        from msplatform.backends.simion.native_plans import plan_model_preparation
        from msplatform.backends.simion.resources import STRUCTURAL_SEEDS
        model=compile_prepared_model(self.compiled,self.assembly.components_resolved,drive=self.drive,physics=RF_PHYSICS)
        base=Path.cwd()/'world-plan-only'
        seed=dict(path=str(base/'seed.iob'),bytes=STRUCTURAL_SEEDS[1][0],sha256=STRUCTURAL_SEEDS[1][1])
        def rec(name):return dict(path=str(base/name),bytes=1,sha256='a'*64)
        assets={'world':dict(raw_record=rec('world.pa#'),surface_records=[rec('world.pa-surf')],witness_record=rec('world.csv'))}
        plan=plan_model_preparation(model,geometry_assets=assets,run_directory=base,seed_record=seed,native_path_resource=base/'native.lua')
        self.assertEqual([r['operation_id'] for r in plan.operations],['materialize_geometry','build_model','verify_model'])
        self.assertIn('neutral_world_model_iob_build',plan.materializations[str(base/'inputs/geometry_iob.lua')])
        self.assertIn('NEUTRAL_WORLD_MODEL_BUILD=PASS',plan.operations[1]['success_marker'])
        with self.assertRaises(ValueError):plan_model_preparation(model,geometry_assets={},run_directory=base,seed_record=seed,native_path_resource=base/'native.lua')

    def test_original_birth_tracking_plan_and_program(self):
        from pathlib import Path
        from common.contracts.test_simion_rf_tracking import rf_tracking_case
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        from msplatform.backends.simion.rf_tracking_program import render_rf_controls
        _,rf_model,packet,clocks,policy,numerics=rf_tracking_case()
        drive=copy.deepcopy(self.drive);drive['clock']=rf_model.document['drive']['clock'];drive['clock']['phase_reference_instrument_time_us']=12.5
        model=compile_prepared_model(self.compiled,self.assembly.components_resolved,drive=drive,physics=RF_PHYSICS)
        for row in packet['rows']:row['frame_id']='toy_local'
        for row in packet['mother']['records'].values():row['frame_id']='toy_local'
        numerics.pop('rf_steps_per_period')
        plan=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=policy,observations=dict(plane_observations=[]),numerics=numerics)
        self.assertEqual([row['particle_id'] for row in plan['rows']],[7,91])
        self.assertEqual(plan['flight']['tracking_kind'],'static_world')
        on_face=copy.deepcopy(packet);on_face['rows'][0]['position_x_mm']=-5
        on_face['mother']['records'][7]['position_x_mm']=-5
        face_plan=plan_tracking_execution(model,particles=on_face,clock_records=clocks,propagation=policy,observations=dict(plane_observations=[]),numerics=numerics)
        self.assertEqual(face_plan['rows'][0]['position_x_mm'],-5)
        outside=copy.deepcopy(packet);outside['rows'][0]['position_x_mm']=-5.01
        outside['mother']['records'][7]['position_x_mm']=-5.01
        with self.assertRaisesRegex(ValueError,'outside the explicit field domain'):
            plan_tracking_execution(model,particles=outside,clock_records=clocks,propagation=policy,observations=dict(plane_observations=[]),numerics=numerics)
        controls=render_rf_controls(model,plan,assets={},native_sources={})
        program=controls['program']
        self.assertIn('world',program);self.assertIn('1.25',program);self.assertIn('12.5',program)
        from msplatform.backends.simion.rf_tracking_execution import plan_rf_tracking_workbench
        base=Path.cwd()/'static-tracking-plan-only'
        carrier=dict(path=str(base/'world.pa0'))
        assets={'world':dict(carrier_record=carrier,family_records=[carrier,dict(path=str(base/'world.pa-surf'))],witness_record=dict(path=str(base/'witness.csv')))}
        workbench=plan_rf_tracking_workbench(self.compiled,carriers=assets,run_directory=base,program=program,native_source_rows=plan['native_source_rows'],native_path_resource=base/'native.lua')
        spec=workbench.materializations[str(base/'inputs/tracking_iob.lua')]
        self.assertIn('static_world_tracking_iob',spec);self.assertIn('world.pa0',spec)
        self.assertEqual(workbench.operations[0]['success_marker'],'STATIC_WORLD_TRACKING_IOB=PASS')
        with self.assertRaises(ValueError):plan_rf_tracking_workbench(self.compiled,carriers={},run_directory=base,program=program,native_source_rows=plan['native_source_rows'],native_path_resource=base/'native.lua')
        import subprocess, tempfile
        from common.contracts.test_simion_prepared_model import LUA as lua
        if not lua.is_file(): self.skipTest('verified Lua interpreter unavailable')
        ids={(r['instance_id'],r['electrode_group_id']):r['native_id'] for r in self.compiled.frontend_geometry['electrode_mapping']}
        script="simion={workbench_program=function() segment={} end};ion_number=1;ion_instance=1;ion_time_of_flight=0;adj_elect={}\n"+program+"\nsegment.fast_adjust();assert(adj_elect["+str(ids[('first','body')])+"]==1.25);assert(adj_elect["+str(ids[('second','body')])+"]==0);print('STATIC_VALUES_PASS')\n"
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'static.lua';path.write_text(script,encoding='utf-8')
            child=subprocess.run([str(lua),str(path)],cwd=directory,capture_output=True,text=True,timeout=30)
            self.assertEqual(child.returncode,0,child.stderr);self.assertIn('STATIC_VALUES_PASS',child.stdout)
            coverage="simion={workbench_program=function() segment={} end};ion_number=1;ion_instance=1;ion_time_of_flight=0;ion_px_mm=0;ion_py_mm=0;ion_pz_mm=0;ion_vx_mm=1;ion_vy_mm=1;ion_vz_mm=1;ion_mass=100;ion_charge=1;ion_splat=0;adj_elect={};sim_grouped=1\n"+program+"\nsegment.initialize_run();ion_instance=0;local ok,msg=pcall(segment.initialize);assert(not ok and msg:find('STATIC_WORLD_FIELD_COVERAGE_MISSING') and msg:find('slot=0'));ion_instance=1;segment.initialize();ion_px_mm=-5;segment.other_actions();local original=segment.fast_adjust;ion_instance=0;ok,msg=pcall(segment.other_actions);assert(not ok and msg:find('STATIC_WORLD_FIELD_COVERAGE_MISSING') and msg:find('particle=7') and msg:find('slot=0'));assert(segment.fast_adjust==original);ion_instance=1;ion_px_mm=21;ok,msg=pcall(segment.terminate);assert(not ok and msg:find('STATIC_WORLD_FIELD_COVERAGE_MISSING') and msg:find('x_mm=21'));print('COVERAGE_PASS')\n"
            path.write_text(coverage,encoding='utf-8');child=subprocess.run([str(lua),str(path)],cwd=directory,capture_output=True,text=True,timeout=30)
            self.assertEqual(child.returncode,0,child.stderr);self.assertIn('COVERAGE_PASS',child.stdout)
        import json
        from msplatform.backends.simion.tracking_collection import collect_tracking_logs
        lines=['RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}']
        for ion,state in enumerate(plan['rows'],1):
            row=dict(event='source_release',reason='none',particle_id=state['particle_id'],ion=ion,instrument_time_us=state['instrument_time_us'],mass_amu=state['mass_amu'],charge_state=state['charge_state'],instance=1)
            row.update({axis+'_mm':state['position_'+axis+'_mm'] for axis in 'xyz'})
            row.update({'v'+axis+'_mm_per_us':state['velocity_'+axis+'_m_s']/1000 for axis in 'xyz'})
            lines.append('RF_NATIVE_STATE_V1: '+json.dumps(row))
            lines.append('RF_NATIVE_STATE_V1: '+json.dumps(dict(row,event='terminal',reason='unknown',instrument_time_us=2.)))
        lines.append('status,Fly completed. 2 splats')
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'inert.log';log.write_text('\n'.join(lines)+'\n')
            result=collect_tracking_logs([log],source_rows={r['particle_id']:r for r in plan['rows']},source_provenance=plan['source_provenance'],flight=plan['flight'],batches=[dict(source_row_range=[1,2],expected_particle_ids=[7,91],build_metadata=controls['build_metadata'])])
            self.assertEqual([row['particle_id'] for row in result['native_terminals']],[7,91])
            self.assertEqual(result['original_mother']['mother_records'],plan['source_provenance']['mother_records'])
        wrong_scope=copy.deepcopy(policy);wrong_scope['scope']='segmented_upstream'
        with self.assertRaises(ValueError):plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=wrong_scope,observations=dict(plane_observations=[]),numerics=numerics)
        policy=copy.deepcopy(policy);policy['dynamics']['collisions']='hs1'
        with self.assertRaises(ValueError):plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=policy,observations=dict(plane_observations=[]),numerics=numerics)
