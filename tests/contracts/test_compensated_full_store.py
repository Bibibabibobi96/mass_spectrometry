"""Full split field action through Store; all native payloads are inert fixtures."""
import csv
import json
import numpy as np
import math
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.simion.field_closure import downstream_identity, load_field_model
from msplatform.backends import simion
from msplatform.backends.simion import operations
from msplatform.backends.simion.downstream_fields_worker import DOWNSTREAM_RESOURCES
from msplatform.backends.simion.model import model_geometry
from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.execution import owner
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.native_source_guard import guard_native_source
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from msplatform.results.model import TraceResult
from msplatform.results.detector_observation import detector_observation
from msplatform.results.particle_data import write_particle_data
from msplatform.workflows.tracing import run_recipe
from msplatform.storage import ArtifactStore
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import compile_simion_model
from msplatform.backends.simion.reflectron_response_binding import compile_response_fit
from msplatform.workflows.reflectron_compensation import prepare_compensated_author
from tests.contracts.test_simion_field_worker import INERT_WORKER
from tests.contracts.test_static_world_managed import retained_on_failure
from tests.contracts.test_simion_fields_execution import inert_downstream_source


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process owner required')
class CompensatedFullStoreTests(unittest.TestCase):
    def test_full_field_action_with_inert_native_and_real_store_owners(self):
        with retained_on_failure() as root:
            examples = Path(__file__).resolve().parents[2]/'src/msplatform/examples'
            for name in ('rf_split_oatof_native_small_v1.toml','rf_split_oatof_native_small_v1.json'):
                (root/name).write_bytes((examples/name).read_bytes())
            author = root/'rf_split_oatof_native_small_v1.toml'
            original_recipe = load_recipe(author).to_dict()
            model = compile_simion_model(original_recipe)
            numerics = original_recipe['study']['document']['numerics']['fields']
            clock_path = examples/'instrument_clock_authority_v1.json'; clock_root = examples
            stage_policy = root/'stage-policy.json'
            stage_policy.write_text(json.dumps({'schema_version':1, 'role':'execution_stage_policy', 'stages':{
                'solve_fields':{'limits':{'wall_clock_seconds':600,'transient_run_directory_bytes':128*1024*1024,
                    'process_tree_working_set_bytes':4*1024**3,'minimum_system_available_memory_bytes':1024**3,
                    'compact_final_retained_bytes':128*1024*1024,'automatic_retry_count':0,
                    'reserved_run_payload_bytes':1024*1024},'artifact_retention':{'policy_version':1,
                    'class':'solver_review','reason':'inert public compensation field'}}}}), encoding='utf-8')
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3', policy_path=resource_path('host_resource_policy.json'),
                stage_policy_path=stage_policy)
            store = ArtifactStore(root/'store'); budget = root/'budget.json'; budget.write_text('{}',encoding='utf-8')
            scripts = {'member':root/'member.py', 'downstream':root/'downstream.py'}
            scripts['member'].write_text(INERT_WORKER,encoding='utf-8')
            scripts['downstream'].write_text(inert_downstream_source(),encoding='utf-8')
            base = dict(descriptor={'project':'instrument_assembly','mode':'inert_field','software':[]},payload={},
                committed_new_bytes=128*1024*1024,commitment_inputs=[file_record(budget,'required_evidence')],
                retention={'policy_version':1,'class':'solver_review','reason':'inert field action integration'},
                action_record=file_record(Path(__file__),'required_evidence'),
                completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
            def model_action(selected_model):
                def action(session):
                    records={}
                    def put(key,path,data=None,source=None,role='required_evidence'):
                        path=session.declare_file(path,role);path.parent.mkdir(parents=True,exist_ok=True)
                        if source is not None: freeze_file(source,path,retention_role=role)
                        else: path.write_bytes(data)
                        records[key]=file_record(path,role);return records[key]
                    put('compiled_model',session.input_dir/'compiled_model.json',json.dumps(selected_model.document).encode())
                    put('clock_authority',session.input_dir/'clock/clock_authority.json',source=clock_path)
                    epoch=json.loads(clock_path.read_text(encoding='utf-8'))['authority']['path']
                    put('instrument_epoch',session.input_dir/'clock'/epoch,source=clock_root/epoch)
                    put('structural_seed',session.input_dir/'seed.iob',source=structural_seed_path(4))
                    assets={}
                    for domain in ('parent','flight_tube','reflectron','detector'):
                        key=domain+'_raw';put(key,session.result_dir/(domain+'.pa#'),b'INERT_RAW',role='solver_native_binary')
                        assets[domain]={'raw_geometry':key}
                        if domain in ('flight_tube','detector'):
                            key=domain+'_surface';put(key,session.result_dir/(domain+'.pa-surf'),b'INERT_SURFACE',role='solver_native_binary')
                            assets[domain]['fractional_surface']=key
                    metadata={'backend':'simion','drive_configured':True,'geometry_materialized':True,
                        'field_status':'not_solved','source_status':'not_requested','native_assets':assets,'fixture':'INERT_ONLY'}
                    outputs=[row['path'] for row in records.values()]
                    return dict(status='success',summary=metadata,output_paths=outputs,required_output_paths=outputs,
                        retention_preserve_paths=[],manifest_extra_fields={'products':{'model':{'schema_version':1,
                            'kind':'prepared_model','status':'complete','metadata':metadata,'data':records}}})
                return action
            original=model.document
            published=owner.run_managed_stage(context,**base,run_id='20261127_121100__test__python__fixture-model',
                expected_operation_ids=[],operation_dependencies={},action=model_action(model),artifact_store=store)
            old_model=open_artifact({'manifest':published['manifest'],'product_id':'model'},expected_kind='prepared_model')
            old_source=load_field_model(old_model)
            tool={'release':'SIMION 2020','executable_bytes':Path(sys.executable).stat().st_size,
                  'executable_sha256':file_sha256(sys.executable)}
            raw={name:old_source.native_assets[name] for name in ('flight_tube','reflectron','detector')}
            identity=downstream_identity(model,raw_assets=raw,convergence_v=numerics['downstream_convergence_v'],
                tool_identity=tool,builder_identities={name:file_sha256(native_resource_path(name)) for name in DOWNSTREAM_RESOURCES})
            projection=model_geometry(model,downstream_drive=True)
            reflectron=next(row for row in projection.downstream_specs if row['role']=='reflectron')
            variable=reflectron['template_variables']; instance=reflectron['native_instance']
            grid={**{key:instance[key] for key in ('nx','ny','nz')},'dx_mm':variable['mmgu_axial'],
                  'dy_mm':variable['mmgu_radial'],'dz_mm':variable['mmgu_radial']}
            def old_field_action(session):
                records={}
                def put(key,path,data,role='solver_native_binary'):
                    path=session.declare_file(path,role);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                    records[key]=file_record(path,role);return records[key]
                put('compiled_model',session.input_dir/'compiled_model.json',json.dumps(model.document).encode(),'required_evidence')
                put('downstream_audit',session.result_dir/'old_audit.json',json.dumps({'status':'success','checked_assets':[
                    {'role':name} for name in ('flight_tube','reflectron','detector')]}).encode(),'required_evidence')
                assets={}
                for name in ('flight_tube','detector'):
                    keys=[]
                    for suffix in ('.pa#','.pa0','.pa1','.pa-surf'):
                        key=name+suffix.replace('.','_').replace('#','raw').replace('-','_')
                        put(key,session.result_dir/(name+suffix),b'INERT_FAMILY');keys.append(key)
                    assets[name]={'carrier':keys[1],'family':keys}
                put('reflectron_carrier',session.result_dir/'reflectron.pa',b'INERT_BASE')
                assets['reflectron']={'carrier':'reflectron_carrier','family':[]}
                responses=[]
                for index in range(1,len(variable['component']['electrodes'])+1):
                    key='response_'+str(index);put(key,session.result_dir/f'reflectron_response_{index}.pa',b'INERT_RESPONSE')
                    responses.append({'response_id':index,'data_key':key})
                metadata={'backend':'simion','field_status':'available','model_identity_sha256':original['model_identity_sha256'],
                    'downstream_identity':identity,'native_assets':assets,'reflectron_response_basis':{'schema_version':2,
                    'model_identity_sha256':original['model_identity_sha256'],'downstream_identity':identity,'grid':grid,
                    'symmetry':'2dcylindrical','responses':responses},'fixture':'INERT_ONLY'}
                outputs=[row['path'] for row in records.values()]
                return dict(status='success',summary=metadata,output_paths=outputs,required_output_paths=outputs,
                    retention_preserve_paths=[],manifest_extra_fields={'products':{'fields':{'schema_version':1,
                        'kind':'field_bundle','status':'complete','metadata':metadata,'data':records}}})
            source=owner.run_managed_stage(context,**base,run_id='20261127_121110__test__python__fixture-fields',
                expected_operation_ids=[],operation_dependencies={},action=old_field_action,artifact_store=store)
            source_ref={'manifest':source['manifest'],'product_id':'fields'}
            with guard_native_source(source_ref,expected_kind='field_bundle',
                    expected_artifact_root=context.workspace/'artifacts',artifact_store=store) as original_field:
                binding=compile_response_fit(original_field,expected_model=model,expected_downstream_identity=identity,
                    expected_grid=grid,expected_frame_id='oatof_global',regularization=0.001)
                def axis_action(session):
                    path=session.declare_file(session.result_dir/'synthetic_axis.csv','required_evidence')
                    path.parent.mkdir(parents=True,exist_ok=True)
                    count=len(binding['responses']); length=(binding['fit_parameters']['stage1_length_mm']+
                        binding['fit_parameters']['stage2_length_mm'])
                    with path.open('w',encoding='utf-8',newline='') as stream:
                        writer=csv.writer(stream);writer.writerow(['x_mm',*[f'basis_{i}_V' for i in range(1,count+1)]])
                        params=binding['fit_parameters']; l1=params['stage1_length_mm']; l2=params['stage2_length_mm']
                        mid=params['midgrid_voltage_v']; back=params['backplate_voltage_v']
                        initial=original['drive']['groups']['tof']['reflectron_stage1_ring_1']['voltage_v']
                        mid_id=2+params['stage1_count']; back_id=3+params['stage1_count']+params['stage2_count']
                        for step in range(81):
                            x=length*step/80; q=math.sin(math.pi*x/length)
                            desired=mid*x/l1 if x<=l1 else mid+(back-mid)*(x-l1)/l2
                            back_basis=0.0 if x<=l1 else (x-l1)/l2
                            mid_basis=(desired-back*back_basis-(initial-10.0)*q)/mid
                            columns=[0.0]*count; columns[1]=q; columns[mid_id-1]=mid_basis; columns[back_id-1]=back_basis
                            writer.writerow([x,*[10000*value for value in columns]])
                    record=file_record(path,'required_evidence')
                    metadata={'binding':binding,'maximum_x_mm':length,'samples_unit':'V','position_unit':'mm',
                              'basis_normalization_v':10000.0,'fixture':'SYNTHETIC_NOT_NATIVE'}
                    return dict(status='success',summary={'fixture':'SYNTHETIC_NOT_NATIVE'},output_paths=[str(path)],
                        required_output_paths=[str(path)],retention_preserve_paths=[],manifest_extra_fields={
                        'products':{'axis':{'schema_version':1,'kind':'axis_response_samples','status':'complete',
                                            'metadata':metadata,'data':{'axis_csv':record}}}})
                source_asset=Path(source_ref['manifest']['path']).relative_to(store.root).parts[3]
                with owner.standalone_native_store(store,task_key='inert_axis',budget=128*1024*1024,
                                                   required_assets=(source_asset,)):
                    axis_run=owner.run_managed_stage(context,**base,run_id='20261127_121111__test__python__synthetic-axis',
                        expected_operation_ids=[],operation_dependencies={},source_references=[{'manifest_record':source_ref['manifest']}],
                        action=axis_action,artifact_store=store)
            axis=open_artifact({'manifest':axis_run['manifest'],'product_id':'axis'},expected_kind='axis_response_samples')
            authored=prepare_compensated_author(author,axis,instance_id='tof',recipe_name='fitted.toml',
                                                 study_name='fitted.json',context=context,artifact_store=store)
            fitted_recipe=load_recipe(authored['recipe_path']).to_dict()
            from msplatform.workflows.native_tracing import preflight_native
            preflight=preflight_native(fitted_recipe,context=context,artifact_store=store)
            self.assertTrue(preflight['implemented'])
            self.assertFalse(preflight['native_verified'])
            fit=authored['fit']
            new_model=compile_simion_model(fitted_recipe)
            self.assertEqual(new_model.document['drive']['groups']['tof']['reflectron_stage1_ring_1']['voltage_v'],
                             fit['stage1_ring_voltages_V'][0])
            self.assertNotEqual(new_model.document['model_identity_sha256'],model.document['model_identity_sha256'])
            published=owner.run_managed_stage(context,**base,run_id='20261127_121101__test__python__fixture-model',
                expected_operation_ids=[],operation_dependencies={},action=model_action(new_model),artifact_store=store)
            new_model_product=open_artifact({'manifest':published['manifest'],'product_id':'model'},expected_kind='prepared_model')
            basis={'reference':source_ref,'fit':fit,'regularization':fit['fit']['regularization']}
            def geometry_action(session):
                path=session.declare_file(session.result_dir/'geometry-fixture.json','required_evidence')
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{"fixture":"INERT_ONLY"}',encoding='utf-8')
                record=file_record(path,'required_evidence')
                return dict(status='success',summary={'fixture':'INERT_ONLY'},output_paths=[str(path)],
                    required_output_paths=[str(path)],retention_preserve_paths=[],manifest_extra_fields={'products':{
                    'geometry':{'schema_version':1,'kind':'geometry_artifact','status':'complete',
                                'metadata':{'fixture':'INERT_ONLY'},'data':{'fixture':record}}}})
            geometry_run=owner.run_managed_stage(context,**base,run_id='20261127_121112__test__python__fixture-geometry',
                expected_operation_ids=[],operation_dependencies={},action=geometry_action,artifact_store=store)
            geometry_product=open_artifact({'manifest':geometry_run['manifest'],'product_id':'geometry'},expected_kind='geometry_artifact')
            trace_count=[0]
            def inert_trace(field, particles, **_kwargs):
                trace_count[0]+=1
                from msplatform.workflows.native_tracing import _particle_document
                packet=_particle_document(particles)
                selected={row['species_id']:row for row in fitted_recipe['species']}
                initial=[]; terminal=[]
                for row in packet['rows']:
                    species=selected[row['species_id']]
                    position=[row['position_'+axis+'_mm']/1000 for axis in 'xyz']
                    velocity=[row['velocity_'+axis+'_m_s'] for axis in 'xyz']; time=row['instrument_time_us']/1e6
                    initial.append(dict(particle_id=row['particle_id'],species_id=row['species_id'],position_m=position,
                        velocity_m_s=velocity,time_s=time,mass_kg=species['mass_kg'],charge_state=species['charge_state'],
                        charge_c=species['charge_c'],weight=row['particle_weight'],parent_particle_id=None,lineage_status='primary_birth'))
                    terminal.append(dict(particle_id=row['particle_id'],species_id=row['species_id'],position_m=position,
                        velocity_m_s=velocity,time_s=time,physical_outcome='unknown',stop_reason='time_limit',
                        component_id=None,electrode_id=None,surface_id=None,attribution_method='unavailable',
                        attribution_status='unavailable',started=True,backend_version='inert-software',
                        native_termination_code=None,native_entity_id=None,detail=None))
                arrays={'particle_id':np.empty(0,dtype='int64'),'time_s':np.empty(0),
                        'position_m':np.empty((0,3)),'velocity_m_s':np.empty((0,3))}
                result=TraceResult(initial,terminal,[],arrays,'succeeded',{'status':'complete',
                    'detector_observation':detector_observation('complete',[row['particle_id'] for row in initial])})
                def emit(session):
                    output=session.result_dir/'particle_data';output.mkdir(parents=True)
                    names=('initial_states.parquet','terminal_states.parquet','events.parquet','trajectories.h5','execution.json')
                    for name in names:session.declare_file(output/name,'required_evidence')
                    write_particle_data(output,result,metadata={'schema_version':2,'initial_state_basis':'native_birth_verified',
                        'frame_id':new_model.document['geometry']['frontend_geometry']['native_frame_id'],
                        'clock':{'basis':'experiment_relative','unit':'s',**packet['clock']},'species':fitted_recipe['species']})
                    records={'particle_data_'+name.replace('.','_'):file_record(output/name,'required_evidence') for name in names}
                    paths=[row['path'] for row in records.values()]
                    return dict(status='success',summary={'fixture':'INERT_TRACKING'},output_paths=paths,required_output_paths=paths,
                        retention_preserve_paths=[],manifest_extra_fields={'products':{'trajectory':{'schema_version':1,
                            'kind':'trajectory_result','status':'complete','metadata':{'fixture':'INERT_TRACKING'},'data':records}}})
                produced=owner.run_managed_stage(context,**base,run_id=f'20261127_12111{2+trace_count[0]}__test__python__inert-trajectory',
                    expected_operation_ids=[],operation_dependencies={},action=emit)
                return open_artifact({'manifest':produced['manifest'],'product_id':'trajectory'},expected_kind='trajectory_result')
            with self.assertRaisesRegex(ValueError, 'without other reuse'):
                operations.solve_fields(new_model_product, numerics=numerics, context=context,
                                        compensated_basis=basis, reuse_fields=source_ref)
            with self.assertRaisesRegex(ValueError, 'managed native Store scope'):
                operations.solve_fields(new_model_product, numerics=numerics, context=context, compensated_basis=basis)
            real=RunSession.run_process
            def transport(session,operation_id,**kwargs):
                if operation_id.startswith('frontend_') or operation_id=='downstream_fields':
                    script=scripts['downstream' if operation_id=='downstream_fields' else 'member']
                    kwargs['arguments']=['-I','-B','-X','utf8',str(script),kwargs['arguments'][-1]]
                elif operation_id=='compose_reflectron':
                    path=session.run_dir/'simion/fields/downstream/reflectron.pa'
                    code=f"from pathlib import Path;Path({str(path)!r}).write_bytes(b'INERT_COMPOSED');print('STANDALONE_PA_COMPOSITION=PASS')"
                    kwargs['arguments']=['-c',code]
                elif operation_id=='audit_rebiased_downstream':
                    path=session.run_dir/'simion/fields/downstream/audit.json'
                    code=f"from pathlib import Path;Path({str(path)!r}).write_text('{{\"status\":\"success\",\"checked_assets\":[{{\"role\":\"flight_tube\"}},{{\"role\":\"reflectron\"}},{{\"role\":\"detector\"}}]}}');print('DOWNSTREAM_NATIVE_AUDIT=PASS')"
                    kwargs['arguments']=['-c',code]
                elif operation_id in ('build_fields','verify_fields'):
                    path=session.run_dir/'simion/fields/fields.iob'
                    marker='SINGLE_REFLECTION_FIELD_IOB'+('_REOPEN' if operation_id=='verify_fields' else '')+'=PASS'
                    code=f"from pathlib import Path;p=Path({str(path)!r});p.parent.mkdir(parents=True,exist_ok=True);"
                    code+=("p.write_bytes(b'INERT_IOB');p.with_suffix('.fly2').write_text('particles { coordinates = 0 }');" if operation_id=='build_fields' else "assert p.is_file();")
                    kwargs['arguments']=['-c',code+'print('+repr(marker)+')']
                return real(session,operation_id,**kwargs)
            environment={'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'',
                         'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}
            captured=[]
            actual_solve=simion.solve_fields
            def solve(*args,**kwargs):
                result=actual_solve(*args,**kwargs);captured.append(result);return result
            from msplatform.backends.simion import grounded_runtime
            with patch.dict(os.environ,environment),patch.object(RunSession,'run_process',new=transport), \
                 patch.object(simion,'build_geometry',return_value=geometry_product), \
                 patch.object(simion,'prepare_model',return_value=new_model_product), \
                 patch.object(simion,'solve_fields',side_effect=solve), \
                 patch.object(grounded_runtime,'prepare_grounded_runtime_fields',side_effect=lambda field,**_kwargs:field), \
                 patch.object(simion,'track',side_effect=inert_trace):
                public=run_recipe(authored['recipe_path'],artifact_root=store.root,context=context,
                                  reserve_bytes=128*1024*1024)
            self.assertEqual(public['run_state']['execution_status'],'succeeded')
            self.assertEqual([case['id'] for case in public['summary']['cases']],['compensated','ideal_reflectron'])
            self.assertTrue(all(case['summary']['detector_observation']['status']=='complete' for case in public['summary']['cases']))
            self.assertEqual(trace_count[0],2)
            product=captured[0]
            self.assertEqual(product.kind,'field_bundle')
            self.assertEqual(product.metadata['model_identity_sha256'],new_model.document['model_identity_sha256'])
            self.assertEqual(product.metadata['rebias_native_operations'],2)
            self.assertEqual(product.metadata['downstream_native_operations'],0)
            self.assertTrue(product.metadata['downstream_reused'])
            self.assertEqual(product.data_path('reflectron_carrier').read_bytes(),b'INERT_COMPOSED')
            expected_assets={Path(ref['manifest']['path']).relative_to(store.root).parts[3] for ref in (source_ref,axis.reference)}
            with store._db() as db:
                retained={row[0] for row in db.execute('SELECT asset_id FROM refs WHERE run_id=?',(public['run_id'],))}
            self.assertTrue(expected_assets <= retained)
            store.collect(target_bytes=128*1024*1024)
            for ref, kind in ((source_ref,'field_bundle'),(axis.reference,'axis_response_samples')):
                with guard_native_source(ref,expected_kind=kind,expected_artifact_root=context.workspace/'artifacts',
                                         artifact_store=store) as reopened:
                    self.assertEqual(reopened.kind,kind)
            from msplatform.workflows.tracing import inspect_results
            self.assertEqual([case['id'] for case in inspect_results(public['run_id'],artifact_root=store.root)['summary']['cases']],
                             ['compensated','ideal_reflectron'])
            with store._db() as db:
                remaining={row[0] for row in db.execute('SELECT asset_id FROM refs WHERE run_id=?',(public['run_id'],))}
            self.assertTrue(expected_assets <= remaining)
