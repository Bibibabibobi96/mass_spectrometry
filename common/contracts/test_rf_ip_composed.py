"""Joint RF-IP planner, gas, Program, and replay identity; no native solver."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.contracts import test_joint_ip_model as joint_ip_fixture
from common.contracts.test_simion_rf_tracking import rf_tracking_case
from common.contracts.test_simion_native_plans import LUA
from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import HS1_SOURCE_FIXTURE
from msplatform.assembly.factory import assemble
from msplatform.backends.simion import operations
from msplatform.workflows.multipole_ip import continuous
from msplatform.backends.simion.model import compile_prepared_model, RF_IP_PHYSICS
from msplatform.backends.simion.rf_tracking_execution import prepare_rf_ip_hs1
from msplatform.backends.simion.rf_tracking_program import render_rf_controls
from msplatform.backends.simion.tracking_execution import plan_tracking_execution
from msplatform.backends.simion.tracking_units import tracking_applicability
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value
from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasSource, GasSpecies, GasState
from msplatform.io.manifest_records import file_record


@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class ComposedRfIpHs1Tests(unittest.TestCase):
    def test_translated_actual_plan_runtime_program_and_identity(self):
        fixture = joint_ip_fixture.JointIpModelTests(methodName='runTest'); fixture.setUp()
        recipe = fixture.compiled.frontend_geometry['composition_plan']['recipe']
        recipe = copy.deepcopy(recipe)
        for item in recipe['instances']:
            item['transform']['translation_mm'][0] += 5
        from integrations.tests.test_ip_compiler import IpCompilerTests
        original = IpCompilerTests(methodName='runTest'); original.setUp()
        assembly = assemble(recipe, original.assembly.components)
        bounds = copy.deepcopy(original.numerics)
        bounds['parent_domain']['pa_bounds_mm']['x_min'] += 5
        bounds['parent_domain']['pa_bounds_mm']['x_max'] += 5
        compiled = operations.compile_geometry(assembly, numerics=bounds)
        model = compile_prepared_model(compiled, compiled.components_resolved, drive=fixture.drive, physics=RF_IP_PHYSICS)
        _, _, packet, clocks, propagation, numerics = rf_tracking_case()
        frame = compiled.frontend_geometry['composition_plan']['components']['multipole']['local_frame_id']
        for row in packet['rows']:
            row['source_component_id'] = 'multipole'; row['target_component_id'] = 'multipole'; row['frame_id'] = frame
            row['clock_epoch_id'] = model.document['drive']['clock']['clock_epoch_id']
        for row in packet['mother']['records'].values():
            row['source_component_id'] = 'multipole'; row['target_component_id'] = 'multipole'; row['frame_id'] = frame
            row['clock_epoch_id'] = model.document['drive']['clock']['clock_epoch_id']
        packet['clock'] = {k:model.document['drive']['clock'][k] for k in ('clock_epoch_id','authority_sha256')}
        clocks['instrument_epoch']['sha256'] = packet['clock']['authority_sha256']
        propagation['dynamics']['collisions'] = 'hs1'; numerics['grouped'] = 0
        box = lambda lo, hi: BoxDomain(lo, hi, (True,True,True), (True,True,True))
        baseline = model.document['drive']['ip_schedule']['baseline']
        bath = box((0,-10,-10),(211,10,10))
        outer = GasFieldSpec(field_id='explicit_outer',frame_id=baseline['clock']['frame_id'],representation='uniform',
            composition_id='ion_processor_explicit_single_gas',composition=(GasSpecies('ion_processor_model_gas',baseline['gas']['mass_amu'],1),),
            domain=box((-200,-40,-40),(300,40,40)),source=GasSource('prescribed','test_outer',()),
            uniform_state=GasState('gas',4,baseline['gas']['temperature_k'],(1,2,3)))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); vendor=root/'original.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf-8')
            request=dict(bath_domain=bath,outer=outer,vendor_record=file_record(vendor),numerics=dict(seed=40,hs1_steps_per_mfp=20))
            prepared=prepare_rf_ip_hs1(model,request)
            plan=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=propagation,
                observations=dict(plane_observations=[]),numerics=numerics,hs1_request=request)
            self.assertEqual(plan['hs1_identity'],prepared['identity']); self.assertEqual(plan['flight']['tracking_kind'],'rf_ip')
            with self.assertRaisesRegex(ValueError,'sequential'):
                plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=propagation,
                    observations=dict(plane_observations=[]),numerics={k:v for k,v in numerics.items() if k!='grouped'},hs1_request=request)
            identity=tracking_applicability(plan);changed=copy.deepcopy(plan);changed['hs1_identity']['numerics']['seed']+=1
            self.assertNotEqual(identity,tracking_applicability(changed))
            files={}
            for key in ('bath_runtime','outer_runtime','vendor_adapted'):
                files[key]=root/(key+'.lua');files[key].write_text(prepared[key],encoding='utf-8')
            plan['hs1']=dict(vendor_path=str(files['vendor_adapted']),bath_path=str(files['bath_runtime']),outer_path=str(files['outer_runtime']),
                query_frame_id=prepared['query_frame_id'],numerics=request['numerics'])
            controls=render_rf_controls(model,plan,assets={},native_sources={})
            self.assertIn('joint_hs1.install',controls['program']);self.assertNotIn('upstream_exit_x_mm',controls['program'])
            # Exercise the actual emitted Program with a deliberately inert HS1
            # implementation. It observes the placed gas query, not collision physics.
            import re
            expected=dict(gas_mass_amu=baseline['gas']['mass_amu'],temperature_k=baseline['gas']['temperature_k'],
                pressure_pa=0,sigma_m2=baseline['gas']['cross_section_m2'],mean_free_path_mm=baseline['gas']['mean_free_path_mm'],
                steps_per_mfp=20,random_seed=41,mark_collisions=0,trace_level=0)
            stub='''
local observed={};local hs={segment={}}
function hs.reset_run_state() end
function hs.bound_parameters() return EXPECTED end
function hs.segment.initialize() end
function hs.segment.tstep_adjust() end
function hs.segment.other_actions() observed[#observed+1]=hs.pressure() end
simion={workbench_program=function() segment={} end,import=function() return hs end}
seed=function() end
ion_number=1;ion_instance=1;ion_mass=100;ion_charge=1;ion_time_of_flight=0;ion_time_step=.01;ion_splat=0
ion_px_mm=35;ion_py_mm=0;ion_pz_mm=0;ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0
sim_rerun_flym=1;sim_grouped=1;sim_repulsion='none';sim_relativity=0;sim_trajectory_quality=5;sim_segment_global=0
'''.replace('EXPECTED',lua_value(expected))
            actual_program=re.sub(r'(?m)^(\s*)adjustable ',r'\1',controls['program'])
            callback=root/'callback.lua';callback.write_text(stub+actual_program+'''
segment.initialize_run();assert(sim_rerun_flym==0);segment.initialize();segment.other_actions()
ion_px_mm=4;ion_time_of_flight=.1;segment.other_actions()
assert(observed[1]==1 and observed[2]==4, tostring(observed[1])..','..tostring(observed[2]))
print('ACTUAL_PROGRAM_PLACED_GAS=PASS')
''',encoding='utf-8')
            callback_result=subprocess.run([str(LUA),str(callback)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(callback_result.returncode,0,callback_result.stderr)
            self.assertIn('ACTUAL_PROGRAM_PLACED_GAS=PASS',callback_result.stdout)
            self.assertIn('"grouped":0',callback_result.stdout)
            for name in ('rf_ip_gas_selection.lua','rf_ip_tracking_hs1.lua'):
                self.assertTrue(native_resource_path(name).is_file())
            script=root/'sample.lua';script.write_text('local b=assert(loadfile('+lua_value(str(files['bath_runtime']))+'))()\n'
                +'local o=assert(loadfile('+lua_value(str(files['outer_runtime']))+'))()\n'
                +'local s=assert(loadfile('+lua_value(str(native_resource_path('rf_ip_gas_selection.lua')))+'))().new(b,o)\n'
                +'local q=s.sample(35,0,0,'+lua_value(prepared['query_frame_id'])+')\n'
                +'assert(q.pressure_pa==1, tostring(q.pressure_pa)); print("TRANSLATED_GAS=PASS")\n',encoding='utf-8')
            child=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(child.returncode,0,child.stderr);self.assertIn('TRANSLATED_GAS=PASS',child.stdout)
            bad=dict(request,vendor_record=dict(request['vendor_record'],sha256='0'*64))
            with self.assertRaises(AssertionError): prepare_rf_ip_hs1(model,bad)
            with self.assertRaisesRegex(ValueError,'complete existing file record'):
                prepare_rf_ip_hs1(model,dict(request,vendor_record=dict(request['vendor_record'],exists=False)))
            with self.assertRaises(ValueError): prepare_rf_ip_hs1(model,dict(request,outer=None))
            self._g13_rendered_samples(root, model, packet, clocks, propagation, numerics, request, plan, stub, re)
            self._actual_managed_consumer(root, model, compiled, packet, propagation, numerics, request)

    def _g13_rendered_samples(self, root, model, packet, clocks, propagation, numerics, request, base_plan, stub, re):
        from msplatform.backends.simion.tracking_units import partition_tracking_units, slice_tracking_plan
        from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
        unit_plan=copy.deepcopy(base_plan);unit_plan.update(partition_tracking_units(unit_plan,unit_size=1))
        reversed_units=[slice_tracking_plan(unit_plan,unit) for unit in reversed(unit_plan['units'])]
        self.assertEqual([[row['particle_id'] for row in part['rows']] for part in reversed_units],[[91],[7]])
        self.assertEqual([part['source_provenance']['mother_particle_ids'] for part in reversed_units],[[7,91],[7,91]])
        plane=dict(schema_version=1,observation_id='rf_exit',source_instance_id='multipole',port_id='mechanical_exit',max_records=1)
        observations=dict(plane_observations=[plane],observation_times_us=[1.5,2.5])
        sampled=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=propagation,
            observations=observations,numerics=numerics,hs1_request=request)
        sampled['hs1']=copy.deepcopy(base_plan['hs1'])
        controls=render_rf_controls(model,sampled,assets={},native_sources={})
        body=re.sub(r'(?m)^(\s*)adjustable ',r'\1',controls['program'])
        traced=stub.replace('function hs.segment.initialize() end','function hs.segment.initialize() seed(41) end')
        traced=traced.replace('seed=function() end','seeds={};seed=function(x) seeds[#seeds+1]=x end')
        chunks=[traced,body,'\nsegment.initialize_run()\n']
        for ion,row in enumerate(sampled['rows'],1):
            chunks.append('ion_number='+str(ion)+';ion_instance=1;ion_splat=0;ion_time_of_flight=0;ion_mass='+repr(row['mass_amu'])+';ion_charge='+str(row['charge_state'])+'\n')
            for axis in 'xyz':
                chunks.append('ion_p'+axis+'_mm='+repr(row['position_'+axis+'_mm'])+';ion_v'+axis+'_mm='+repr(row['velocity_'+axis+'_m_s']/1000)+'\n')
            chunks.append('segment.initialize();ion_time_of_flight=.5;ion_px_mm=4;ion_py_mm=0;ion_pz_mm=0;segment.other_actions()\n')
            if ion==1:
                chunks.append('ion_time_of_flight=1.5;ion_px_mm=35;segment.other_actions()\n')
            chunks.append('segment.terminate()\n')
        chunks.append('assert(#seeds==6 and seeds[1]==41 and seeds[2]==40 and seeds[3]==41 and seeds[4]==46 and seeds[5]==41 and seeds[6]==130)\n')
        chunks.append("print('status,Fly completed. 2 splats')\n")
        script=root/'g13.lua';script.write_text(''.join(chunks),encoding='utf-8')
        process=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(process.returncode,0,process.stderr)
        log=root/'g13.log';log.write_text(process.stdout,encoding='utf-8')
        result=collect_rf_tracking_logs([log],source_rows={row['particle_id']:row for row in sampled['rows']},
            source_provenance=sampled['source_provenance'],flight=sampled['flight'],
            batches=[dict(source_row_range=[1,2],expected_particle_ids=[7,91],build_metadata=controls['build_metadata'])])
        self.assertEqual([(row['particle_id'],row['instrument_time_us']) for row in result['native_shared_states']],[(7,1.5),(7,2.5),(91,1.5)])
        self.assertTrue(result['plane_observations']['rows'])
        self.assertTrue(any(row['category']=='unknown_native_terminal' for row in result['census']['terminal_taxonomy']['particle_outcomes']))
        self.assertFalse(result['census']['unknown_is_loss'])
        self.assertEqual([(row['particle_id'],row['species_id'],row['particle_weight'],row['clock_epoch_id'],row['phase_reference_id'],row['phase_rad'])
                          for row in result['original_mother']['mother_records']],
                         [(row['particle_id'],row['species_id'],row['particle_weight'],row['clock_epoch_id'],row['phase_reference_id'],row['phase_rad']) for row in sampled['source_provenance']['mother_records']])
    def _actual_managed_consumer(self, root, model, compiled, packet, propagation, numerics, request):
        """Real public owner and leases; only the native leaf is an inert Python child."""
        import os
        import shutil
        import sys
        from unittest.mock import patch
        from common.contracts.test_simion_rf_prepared_model import assets_at, clock_reference
        from common.contracts.test_simion_rf_fields import InertFieldSession, execute
        from msplatform.backends.simion import field_closure
        from msplatform.backends.simion.rf_field_execution import _domain_labels, plan_rf_fields
        from msplatform.execution import owner, run_session, capacity_admission
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.resources import resource_path
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.results.artifacts import open_artifact

        source_root=root/'producer'; assets=assets_at(source_root,compiled); clock=clock_reference()
        records=dict(clock_authority=clock['contract'],instrument_epoch=clock['authority'])
        model_path=source_root/'model.json'; model_path.write_text(json.dumps(model.document),encoding='utf-8')
        records['compiled_model']=file_record(model_path,'required_evidence'); bindings={}
        for name,row in assets.items():
            bindings[name]={}
            for label,record in (('raw_geometry',row['raw_record']),('fractional_surface',row['surface_records'][0]),('surface_witnesses',row['witness_record'])):
                key=name+'_'+label;records[key]=record;bindings[name][label]=key
        manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-joint-model',project='software_fixture',
            mode='inert_joint_model',status='success',inputs={},outputs=list(records.values()),
            products=dict(model=dict(schema_version=1,kind='prepared_model',status='complete',data=records,
                metadata=dict(backend='simion',drive_configured=True,geometry_materialized=True,field_status='not_solved',
                    source_status='not_requested',native_assets=bindings))))
        publish_terminal_state(source_root,{'status':'success'},manifest)
        source=field_closure.load_field_model(dict(manifest=file_record(source_root/'run_manifest.json'),product_id='model'))
        graph=plan_rf_fields(model,numerics={'refine_policy':'vendor_default'})
        fields=InertFieldSession(root/'inert_fields',source_root,graph)
        fields.labels={'parent':_domain_labels(model.document['geometry']['frontend_geometry'],'parent')}
        with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(source_root))):
            result=execute(fields,source,{'refine_policy':'vendor_default'})
        product=result['manifest_extra_fields']['products']['fields']['metadata']
        self.assertEqual(product['field_representation'],'producer_owned_rf_ip_fractional_family')
        field_product=result['manifest_extra_fields']['products']['fields']
        policy=root/'capacity.json';policy.write_text(json.dumps(dict(capacity_admission._capacity_policy(),target_gib=1,minimum_free_gib=0)))
        budget=root/'budget.json';budget.write_text('{"bytes":16777216}')
        retention=dict(policy_version=1,**{'class':'solver_review'},reason='Inert joint tracking owner, not native science')
        stage=root/'stage.json';stage.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages=dict(track=dict(
            limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=16777216,process_tree_working_set_bytes=536870912,
                minimum_system_available_memory_bytes=1073741824,compact_final_retained_bytes=16777216,automatic_retry_count=0),artifact_retention=retention)))))
        context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),powershell_executable=Path(shutil.which('pwsh')),
            tools=dict(simion=Path(sys.executable)),host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
            policy_path=resource_path('host_resource_policy.json'),capacity_policy_path=policy,stage_policy_path=stage)
        def source_action(session):
            result_records={}
            for name,record in field_product['data'].items():
                relative=Path('clock')/Path(record['path']).name if name in {'clock_authority','instrument_epoch'} else Path(record['path']).relative_to(fields.run_dir)
                target=session.declare_file(session.input_dir/relative,record['retention_role']);target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(Path(record['path']).read_bytes())
                result_records[name]=file_record(session.canonical_path(target),record['retention_role']);session.add_input(name,result_records[name])
            paths=[Path(r['path']) for r in result_records.values()]
            return dict(status='success',summary=dict(fixture='INERT_ONLY'),output_paths=paths,required_output_paths=paths,
                retention_preserve_paths=[],manifest_extra_fields=dict(products=dict(fields=dict(field_product,data=result_records))))
        published=owner.run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='inert_joint_fields',software=[]),
            run_id='20261113_000001__test__python__inert-joint-fields',payload={},committed_new_bytes=16777216,
            commitment_inputs=[file_record(budget,'required_evidence')],retention=retention,expected_operation_ids=(),operation_dependencies={},
            action=source_action,action_record=file_record(Path(__file__),'required_evidence'))
        reference=dict(manifest=published['manifest'],product_id='fields');artifact=open_artifact(reference,expected_kind='field_bundle')
        originals={r['path']:Path(r['path']).read_bytes() for key,r in artifact.data_records.items() if '_family_' in key}
        actual_process=run_session.run_observed_process; observed=[]
        def inert_native(actual_context,**options):
            if options['role']!='SIMION':return actual_process(actual_context,**options)
            run=Path(options['working_directory']);args=options['arguments']
            paths={Path(r['path']).resolve() for r in options['immutable_input_records']}
            expected={*(run/'inputs/hs1'/name for name in ('original.lua','vendor.lua','bath.lua','outer.lua','identity.json')),
                      *(run/'inputs/native_sources'/name for name in ('rf_ip_gas_selection.lua','rf_ip_tracking_hs1.lua','collision_hs1_gas.lua'))}
            observed.append((options, paths, {path.resolve() for path in expected}))
            if 'fly' not in args:
                mode=args[-2];iob=run/'simion/tracking/instrument.iob'
                code='from pathlib import Path\n'+('Path('+repr(str(iob))+').write_bytes(b"INERT_IOB")\n' if mode=='build' else '')
                if mode=='build':
                    neutral=run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0'
                    code+='Path('+repr(str(neutral))+').write_bytes(b"INERT_BOOTSTRAP")\n'
                code+='print('+repr('RF_IP_TRACKING_IOB=PASS' if mode=='build' else 'RF_IP_TRACKING_IOB_REOPEN=PASS')+')'
            else:
                rows=json.loads((run/'inputs/canonical_source_states.json').read_text());lines=['RF_DYNAMICS_V1: {"grouped":0,"repulsion":"none","relativity":0,"segment_global":1}']
                for ion,row in enumerate(rows,1):
                    state=dict(event='source_release',reason='none',particle_id=row['particle_id'],ion=ion,instrument_time_us=row['instrument_time_us'],
                        mass_amu=row['mass_amu'],charge_state=row['charge_state'],instance=1)
                    state.update({a+'_mm':row['position_'+a+'_mm'] for a in 'xyz'});state.update({'v'+a+'_mm_per_us':row['velocity_'+a+'_m_s']/1000 for a in 'xyz'})
                    lines.extend(['RF_NATIVE_STATE_V1: '+json.dumps(state),'RF_NATIVE_STATE_V1: '+json.dumps(dict(state,event='terminal',reason='unknown',instrument_time_us=2.))])
                lines.append('status,Fly completed. 2 splats');code='print('+repr('\n'.join(lines))+')'
            guarded = [str(path) for path in expected]
            protection = ('for p in '+repr(guarded)+':\n'
                ' try:\n  f=open(p,"ab");f.close()\n'
                ' except PermissionError: pass\n'
                ' else: raise AssertionError("frozen collision input is writable")\n')
            return actual_process(actual_context,**dict(options,executable=Path(sys.executable),arguments=['-I','-c',protection+code],role='GATE',stage='inert_rf_ip_tracking'))
        private=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
        with patch.dict(os.environ,private),patch.object(run_session,'run_observed_process',side_effect=inert_native):
            result=continuous.track_existing_fields(fields=reference,particles=packet,propagation=propagation,observations=dict(plane_observations=[]),
                tracking_numerics=numerics,context=context,hs1_request=request)
            reused=continuous.track_existing_fields(fields=reference,particles=packet,propagation=propagation,observations=dict(plane_observations=[]),
                tracking_numerics=numerics,context=context,hs1_request=request,recovery_reference=result.reference['manifest'])
            self.assertEqual(len(observed),3)
            self.assertEqual(reused.metadata['reused_unit_count'],1)
            wrong_seed=dict(request,numerics=dict(request['numerics'],seed=request['numerics']['seed']+1))
            with self.assertRaisesRegex(ValueError,'scientific applicability or partition differs'):
                continuous.track_existing_fields(fields=reference,particles=packet,propagation=propagation,observations=dict(plane_observations=[]),
                    tracking_numerics=numerics,context=context,hs1_request=wrong_seed,recovery_reference=result.reference['manifest'])
            self.assertEqual(len(observed),3)
            frozen_bath=result.manifest_location.parent/'inputs/hs1/bath.lua'
            original_bath=frozen_bath.read_bytes()
            try:
                frozen_bath.write_bytes(bytes([original_bath[0]^1])+original_bath[1:])
                with self.assertRaisesRegex((AssertionError,ValueError),'(SHA-256 changed|immutable input)'):
                    continuous.track_existing_fields(fields=reference,particles=packet,propagation=propagation,observations=dict(plane_observations=[]),
                        tracking_numerics=numerics,context=context,hs1_request=request,recovery_reference=result.reference['manifest'])
            finally:
                frozen_bath.write_bytes(original_bath)
            self.assertEqual(len(observed),3)
            vendor_path=Path(request['vendor_record']['path']);vendor_bytes=vendor_path.read_bytes()
            try:
                vendor_path.write_bytes(bytes([vendor_bytes[0]^1])+vendor_bytes[1:])
                with self.assertRaisesRegex(AssertionError,'SHA-256 changed'):
                    continuous.track_existing_fields(fields=reference,particles=packet,propagation=propagation,observations=dict(plane_observations=[]),
                        tracking_numerics=numerics,context=context,hs1_request=request)
            finally:
                vendor_path.write_bytes(vendor_bytes)
            missing=native_resource_path('rf_ip_gas_selection.lua');held=missing.with_suffix('.lua.held')
            missing.rename(held)
            try:
                with self.assertRaisesRegex(FileNotFoundError,'installed SIMION native resource is missing'):
                    continuous.track_existing_fields(fields=reference,particles=packet,propagation=propagation,observations=dict(plane_observations=[]),
                        tracking_numerics=numerics,context=context,hs1_request=request)
            finally:
                held.rename(missing)
        collection=json.loads(result.data_path('collection').read_text());self.assertEqual(collection['native_calls'],3)
        self.assertEqual(result.metadata['tracking_kind'],'rf_ip');self.assertEqual(result.metadata['collision_model'],'hs1')
        self.assertEqual([row['particle_id'] for row in collection['native_terminals']],[7,91]);self.assertEqual(len(observed),3)
        self.assertEqual(collection['census']['role'],'rf_ip_full_mother_census')
        actual_program=(result.manifest_location.parent/'simion/tracking/instrument.lua').read_text(encoding='utf-8')
        execution_root=Path(observed[0][0]['working_directory'])
        for name in ('vendor.lua','bath.lua','outer.lua'):
            self.assertIn(lua_value(str(execution_root/'inputs/hs1'/name)),actual_program)
        for _,paths,expected in observed:
            self.assertTrue(expected <= paths, 'missing immutable collision inputs')
        for path,before in originals.items():self.assertEqual(Path(path).read_bytes(),before)