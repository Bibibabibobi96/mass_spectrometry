"""Joint RF-IP planner, gas, Program, and replay identity; no native solver."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.contracts import test_joint_ip_model as joint_ip_fixture
from tests.contracts.test_simion_rf_tracking import rf_tracking_case
from tests.contracts.test_simion_native_plans import LUA
from tests.components.ion_processor.test_functional import HS1_SOURCE_FIXTURE
from msplatform.assembly.factory import assemble
from msplatform.backends.simion import operations
from msplatform.backends.simion.model import compile_prepared_model, RF_IP_PHYSICS
from msplatform.backends.simion.rf_tracking_execution import prepare_rf_ip_hs1
from msplatform.backends.simion.rf_tracking_program import render_rf_controls
from msplatform.backends.simion.tracking_execution import plan_tracking_execution
from msplatform.backends.simion.tracking_units import tracking_applicability
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value
from msplatform.contracts.gas import BoxDomain
from tests.contracts.test_support.ip_hs1_author import environment_record
from msplatform.io.manifest_records import file_record


@unittest.skipUnless(LUA.is_file(), 'plain Lua unavailable')
class ComposedRfIpHs1Tests(unittest.TestCase):
    def test_translated_actual_plan_runtime_program_and_identity(self):
        fixture = joint_ip_fixture.JointIpModelTests(methodName='runTest'); fixture.setUp()
        recipe = fixture.compiled.frontend_geometry['composition_plan']['recipe']
        recipe = copy.deepcopy(recipe)
        for item in recipe['instances']:
            item['transform']['translation_mm'][0] += 5
        from tests.assembly.rf_ip.test_ip_compiler import IpCompilerTests
        original = IpCompilerTests(methodName='runTest'); original.setUp()
        assembly = assemble(recipe, original.assembly.components)
        bounds = copy.deepcopy(original.numerics)
        bounds['parent_domain']['pa_bounds_mm']['x_min'] += 5
        bounds['parent_domain']['pa_bounds_mm']['x_max'] += 5
        compiled = operations.compile_geometry(assembly, numerics=bounds)
        model = compile_prepared_model(compiled, compiled.components_resolved, drive=fixture.drive, physics=RF_IP_PHYSICS)
        _, _, packet, clocks, propagation, numerics = rf_tracking_case()
        first=packet['rows'][0]
        packet['realization']['spec']['species']=dict(species_kind='ion',mass_amu=first['mass_amu'],charge_state=first['charge_state'])
        from msplatform.contracts.particle_physics import kinetic_energy_ev
        for row in packet['rows']:
            row.update(species_id=first['species_id'], mass_amu=first['mass_amu'], charge_state=first['charge_state'])
            row['kinetic_energy_eV']=kinetic_energy_ev(row['mass_amu'],*(row['velocity_'+axis+'_m_s'] for axis in 'xyz'))
            packet['mother']['records'][row['particle_id']].update(species_id=first['species_id'], mass_amu=first['mass_amu'], charge_state=first['charge_state'], kinetic_energy_eV=row['kinetic_energy_eV'])
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
        bath = box((0,-10,-10),(211,10,10))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); vendor=root/'original.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf-8')
            request=dict(bath_domain=bath,outer_domain=box((-200,-40,-40),(300,40,40)),vendor_record=file_record(vendor),numerics=dict(seed=40,hs1_steps_per_mfp=20),environment_record=environment_record(root,pressure_pa=4,temperature_k=300,bulk_velocity_m_s=[1,2,3]),environment_instance_id='ion_processor')
            prepared=prepare_rf_ip_hs1(model,request)
            plan=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=propagation,
                observations=dict(plane_observations=[]),numerics=numerics,hs1_request=request)
            self.assertEqual(plan['hs1_identity'],prepared['identity']); self.assertEqual(plan['flight']['tracking_kind'],'rf_ip')
            public_propagation=dict(propagation,publication_contract='original_birth_si_v1')
            public_plan=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=public_propagation,
                observations=dict(plane_observations=[],observation_times_us=[1.75]),numerics=numerics,hs1_request=request)
            self.assertTrue(public_plan['flight']['original_birth_si'])
            self.assertNotEqual(tracking_applicability(plan),tracking_applicability(public_plan))
            self.assertEqual(public_plan['hs1_identity'],prepared['identity'])
            with self.assertRaisesRegex(ValueError,'empty plane'):
                plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=public_propagation,
                    observations=dict(plane_observations=[{'observation_id':'unbound'}]),numerics=numerics,hs1_request=request)
            with self.assertRaisesRegex(ValueError,'continuous original-birth'):
                plan_tracking_execution(model,particles=packet,clock_records=clocks,
                    propagation=dict(public_propagation,scope='state_relaunch'),
                    observations=dict(plane_observations=[]),numerics=numerics,hs1_request=request)
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
            self.assertNotIn('local rf_committed_observations=true',controls['program'])
            # Exercise the actual emitted Program with a deliberately inert HS1
            # implementation. It observes the placed gas query, not collision physics.
            import re
            view=prepared['identity']['native_gas_view']
            expected=dict(gas_mass_amu=view['mass_amu'],temperature_k=view['temperature_k'],
                pressure_pa=0,sigma_m2=view['cross_section_m2'],mean_free_path_mm=view['mean_free_path_mm'],
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
            with self.assertRaises(ValueError): prepare_rf_ip_hs1(model,dict(request,outer_domain=None))
            self._g13_rendered_samples(root, model, packet, clocks, propagation, numerics, request, plan, stub, re)
            public_plan['hs1']=copy.deepcopy(plan['hs1'])
            self._public_rendered_si(root, model, public_plan, stub, re)
            self._actual_managed_consumer(root, model, compiled, packet, propagation, numerics, request)

    def _public_rendered_si(self, root, model, plan, stub, re):
        """Real emitted Program and callbacks with inert HS1; no vendor Fly."""
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.simion.terminal_evidence import append_terminal_recorder
        from msplatform.backends.simion.tracking_collection import collect_tracking_logs
        from msplatform.backends.simion.tracking_execution import _publish_split_particle_data
        from msplatform.results.particle_data import read_particle_data
        controls=render_rf_controls(model,plan,assets={},native_sources={})
        self.assertIn('local rf_committed_observations=true',controls['program'])
        body=re.sub(r'(?m)^(\s*)adjustable ',r'\1',controls['program'])
        body=append_terminal_recorder(body,recorder_source=native_resource_path('native_terminal_recording.lua').read_text(encoding='utf-8'),native_run='public-fixture')
        chunks=[stub,body,'\nion_run=1;ion_time_of_birth=0;ion_time_step=.1;sim_grouped=0;segment.initialize_run()\n']
        for ion,row in enumerate(plan['rows'],1):
            chunks.append('ion_number='+str(ion)+';ion_instance=1;ion_splat=0;ion_time_of_flight=0;ion_mass='+repr(row['mass_amu'])+';ion_charge='+str(row['charge_state'])+'\n')
            for axis in 'xyz':
                chunks.append('ion_p'+axis+'_mm='+repr(row['position_'+axis+'_mm'])+';ion_v'+axis+'_mm='+repr(row['velocity_'+axis+'_m_s']/1000)+'\n')
            chunks.append('segment.initialize();ion_time_of_flight=.5;ion_px_mm=ion_px_mm+.5;segment.other_actions();ion_time_of_flight=1;ion_px_mm=ion_px_mm+.5;segment.other_actions();segment.terminate()\n')
        chunks.append("print('status,Fly completed. 2 splats')\n")
        script=root/'public_rf_ip.lua';script.write_text(''.join(chunks),encoding='utf-8')
        child=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(child.returncode,0,child.stdout+child.stderr)
        log=root/'public_rf_ip.log';log.write_text(child.stdout,encoding='utf-8')
        metadata=copy.deepcopy(controls['build_metadata']);metadata['terminal_evidence']=dict(schema_version=1,native_run='public-fixture')
        batch=dict(source_row_range=[1,2],expected_particle_ids=[7,91],build_metadata=metadata)
        collection=collect_tracking_logs([log],source_rows={row['particle_id']:row for row in plan['rows']},
            source_provenance=plan['source_provenance'],flight=plan['flight'],batches=[batch])
        self.assertTrue(collection['observation_complete'])
        self.assertEqual([(row['particle_id'],row['instrument_time_us']) for row in collection['native_shared_states']],[(7,1.75),(91,1.75)])
        binary=root/'public_fixture.exe';binary.write_bytes(b'INERT_NOT_SIMION')
        binary_record=file_record(binary,'solver_native_binary');identity={key:binary_record[key] for key in ('bytes','sha256')}
        output=root/'public_si';output.mkdir()
        session=SimpleNamespace(result_dir=output,context=SimpleNamespace(tools={'simion':str(binary)}),
            declare_file=lambda path,role:path,canonical_path=lambda path:path)
        with patch('msplatform.backends.simion.tracking_execution.windows_binary_version',return_value='inert-fixture'):
            _publish_split_particle_data(session,plan,collection,dict(native_frame_id=model.document['native_frame_id']),
                model.document,identity,{})
        data=read_particle_data(output/'particle_data')
        self.assertEqual([row['particle_id'] for row in data['initial_states']],[7,91])
        self.assertEqual(data['trajectories']['particle_id'].tolist(),[7,91])
        self.assertEqual(data['trajectories']['time_s'].tolist(),[1.75e-6,1.75e-6])
        self.assertEqual(data['metadata']['clock']['clock_epoch_id'],model.document['drive']['clock']['clock_epoch_id'])
        self.assertTrue(all(row['physical_outcome']=='unknown' for row in data['terminal_states']))

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
        # Re-render each ordinal unit independently and observe the real HS1
        # wrapper's seed calls; the HS1 implementation itself remains inert.
        for part in reversed_units:
            control=render_rf_controls(model,part,assets={},native_sources={})
            unit_body=re.sub(r'(?m)^(\s*)adjustable ',r'\1',control['program'])
            row=part['rows'][0];pid=row['particle_id']
            unit=[traced,unit_body,'\nsegment.initialize_run()\n',
                'ion_number=1;ion_instance=1;ion_splat=0;ion_time_of_flight=0;ion_mass='+repr(row['mass_amu'])+';ion_charge='+str(row['charge_state'])+'\n']
            for axis in 'xyz':
                unit.append('ion_p'+axis+'_mm='+repr(row['position_'+axis+'_mm'])+';ion_v'+axis+'_mm='+repr(row['velocity_'+axis+'_m_s']/1000)+'\n')
            unit.append('segment.initialize();ion_time_of_flight=.5;segment.other_actions();segment.terminate()\n')
            unit.append('assert(seeds[#seeds]=='+str(40+pid-1)+', tostring(seeds[#seeds]))\n')
            unit_script=root/('partition_seed_'+str(pid)+'.lua');unit_script.write_text(''.join(unit),encoding='utf-8')
            unit_run=subprocess.run([str(LUA),str(unit_script)],cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(unit_run.returncode,0,unit_run.stdout+unit_run.stderr)
    def _actual_managed_consumer(self, root, model, compiled, packet, propagation, numerics, request):
        """Real public owner and leases; only the native leaf is an inert Python child."""
        import os
        from unittest.mock import patch
        from msplatform.execution import run_session

        from tests.contracts.test_support.rf_ip_inert_field import prepare_inert_field
        host_state=os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH') or str(root/'host.sqlite3')
        private=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
            MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='',MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=host_state)
        with patch.dict(os.environ,private):
            reference, originals, context, store = prepare_inert_field(root, model, compiled)
        from msplatform.execution.owner import standalone_native_store
        actual_process=run_session.run_observed_process; observed=[]
        from tests.contracts.test_support.rf_ip_inert_leaf import inert_native_leaf
        inert_native = inert_native_leaf(actual_process, observed)
        with patch.dict(os.environ,private),patch.object(run_session,'run_observed_process',side_effect=inert_native):
            with standalone_native_store(store, task_key='rf-ip-inert-tracking', budget=512*1024**2):
                result=operations.track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),
                    numerics=numerics,context=context,hs1_request=request)
                reused=operations.track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),
                    numerics=numerics,context=context,hs1_request=request,recovery_reference=result.reference['manifest'])
                self.assertEqual(len(observed),3)
                self.assertEqual(reused.metadata['reused_unit_count'],1)
                wrong_seed=dict(request,numerics=dict(request['numerics'],seed=request['numerics']['seed']+1))
                with self.assertRaisesRegex(ValueError,'scientific applicability or partition differs'):
                    operations.track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),
                        numerics=numerics,context=context,hs1_request=wrong_seed,recovery_reference=result.reference['manifest'])
                self.assertEqual(len(observed),3)
            frozen_bath=result.manifest_location.parent/'inputs/hs1/bath.lua'
            original_bath=frozen_bath.read_bytes()
            try:
                frozen_bath.write_bytes(bytes([original_bath[0]^1])+original_bath[1:])
                with standalone_native_store(store, task_key='rf-ip-inert-tracking-bath-tamper', budget=512*1024**2) as refused:
                    with self.assertRaisesRegex((AssertionError,ValueError),'(SHA-256 changed|immutable input)'):
                        operations.track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),
                            numerics=numerics,context=context,hs1_request=request,recovery_reference=result.reference['manifest'])
                    refused['reported_status']='failed'
            finally:
                frozen_bath.write_bytes(original_bath)
            self.assertEqual(len(observed),3)
            vendor_path=Path(request['vendor_record']['path']);vendor_bytes=vendor_path.read_bytes()
            try:
                vendor_path.write_bytes(bytes([vendor_bytes[0]^1])+vendor_bytes[1:])
                with standalone_native_store(store, task_key='rf-ip-inert-tracking-vendor-tamper', budget=512*1024**2) as refused:
                    with self.assertRaisesRegex(AssertionError,'SHA-256 changed'):
                        operations.track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),
                            numerics=numerics,context=context,hs1_request=request)
                    refused['reported_status']='failed'
            finally:
                vendor_path.write_bytes(vendor_bytes)
            # Keep the actual resolver but select a private resource package whose
            # one missing file cannot affect concurrent installed consumers.
            import shutil
            from msplatform.backends.simion import resources as simion_resources
            original_package = Path(simion_resources.files('msplatform.backends.simion'))
            isolated_package = root/'missing-resource-package'
            shutil.copytree(original_package/'resources', isolated_package/'resources',
                            ignore=shutil.ignore_patterns('rf_ip_gas_selection.lua'))
            missing = isolated_package/'resources/rf_ip_gas_selection.lua'
            self.assertFalse(missing.exists())
            self.assertTrue((original_package/'resources/rf_ip_gas_selection.lua').is_file())
            self.assertEqual((isolated_package/'resources/rf_ip_tracking_hs1.lua').read_bytes(),
                             (original_package/'resources/rf_ip_tracking_hs1.lua').read_bytes())
            before_missing = len(observed)
            with standalone_native_store(store, task_key='rf-ip-inert-tracking-missing-resource', budget=512*1024**2) as refused:
                with patch.object(simion_resources, 'files', return_value=isolated_package):
                    with self.assertRaisesRegex(FileNotFoundError, 'installed SIMION native resource is missing: rf_ip_gas_selection.lua'):
                        operations.track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),
                            numerics=numerics,context=context,hs1_request=request)
                refused['reported_status']='failed'
            self.assertEqual(len(observed), before_missing)
            self.assertTrue((original_package/'resources/rf_ip_gas_selection.lua').is_file())
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
