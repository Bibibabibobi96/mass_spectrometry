"""Public paired owner integration with explicitly inert vendor processes."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.paired_accelerator_static_field.store_workflow import run_paired_static_comparison
from tests.contracts.test_paired_static_store import INERT
from tests.components.single_reflection_oa_tof_mass_analyzer.analysis import test_paired_accelerator_static_field_prepare as preparation

COMSOL_STUB = r'''
import csv,json,sys
from pathlib import Path
run=Path(sys.argv[1]);out=run/'comsol';points=list(csv.DictReader((run/'inputs/bvp/paired_accelerator_field_points.csv').read_text(encoding='utf8').splitlines()))
fields=['point_id','x_mm','y_mm','z_mm','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m']
with (out/'comsol_field_samples.csv').open('w',newline='',encoding='utf8') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for row in points:w.writerow(dict(row,Ex_V_per_m=1,Ey_V_per_m=2,Ez_V_per_m=3))
saved=sys.argv[2] if len(sys.argv)>2 else ''
model=Path(saved) if saved else out/'paired_accelerator_static.mph'
if not saved:model.write_text('INERT NOT COMSOL',encoding='utf8')
(out/'comsol_field_native_facts.json').write_text(json.dumps(dict(backend='COMSOL',coordinate_unit='mm',field_unit=['V/m']*3,point_count=len(points),plan_path=str(run/'inputs/bvp/paired_accelerator_static_field_plan.json'),model_path=str(model),sample_path=str(out/'comsol_field_samples.csv'))),encoding='utf8')
if not saved:(out/'comsol_field_solution.json').write_text(json.dumps(dict(role='oatof_paired_accelerator_static_field_solution',schema_version=1,solution_tag='sol1',study_tag='std1',plan_path=str(run/'inputs/bvp/paired_accelerator_static_field_plan.json'),model_path=str(model),status='solved_saved',solution_present=True,mesh_complete=True,tetrahedra=1)),encoding='utf8')
(run/'logs/paired_comsol.bootstrap.log').write_text('STATUS=PASS',encoding='utf8')
'''

@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process owner required')
class PairedStaticPublicStoreTests(unittest.TestCase):
    def test_managed_store_with_inert_simion_and_stub_comsol(self):
        with tempfile.TemporaryDirectory(prefix='paired-public-') as directory:
            root=Path(directory); author=root/'author';author.mkdir()
            fixture=preparation.PairedAcceleratorStaticFieldPrepareTests();request=fixture._request(author)
            request_path=fixture._write_request(author,request)
            stage=root/'stage.json';limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=32*1024*1024,
                process_tree_working_set_bytes=2*1024**3,minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=32*1024*1024,automatic_retry_count=0)
            stage.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages={
                'paired_accelerator_static_field':dict(limits=limits,artifact_retention=dict(policy_version=1,
                **{'class':'solver_review'},reason='inert paired public fixture'))})),encoding='utf8')
            simion=root/'simion_stub.py';simion.write_text(INERT,encoding='utf8')
            comsol=root/'comsol_stub.py';comsol.write_text(COMSOL_STUB,encoding='utf8')
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable),
                'comsol_launcher':Path(sys.executable),'matlab_root':root},host_state_path=root/'host.sqlite3',
                policy_path=resource_path('host_resource_policy.json'),stage_policy_path=stage)
            store=ArtifactStore(root/'store');actual=RunSession.run_process;model_source=[]
            def transport(session,operation_id,**kwargs):
                if operation_id=='paired_simion':
                    kwargs['arguments']=['-I','-B',str(simion),kwargs['arguments'][-1]]
                elif operation_id=='paired_comsol':
                    kwargs['executable']=Path(sys.executable)
                    kwargs['arguments']=['-I','-B',str(comsol),str(session.run_dir),*model_source]
                return actual(session,operation_id,**kwargs)
            env=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                     MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,env),patch.object(RunSession,'run_process',new=transport), \
                 patch('msplatform.workflows.paired_accelerator_static_field.store_workflow.require_launcher_completion'):
                result=run_paired_static_comparison(context,artifact_store=store,request_path=request_path,
                    run_id='20261127_145000__test__python__paired-public',committed_new_bytes=32*1024*1024)
                self.assertEqual(result['status'],'success')
                run=Path(result['run_directory'])
                model=run/'comsol/paired_accelerator_static.mph'; original=model.read_bytes()
                model_source.append(str(model))
                reused=run_paired_static_comparison(context,artifact_store=store,request_path=request_path,
                    run_id='20261127_145001__test__python__paired-public-saved',committed_new_bytes=32*1024*1024,
                    saved_model_manifest=run/'run_manifest.json')
                self.assertEqual(reused['status'],'success')
                self.assertEqual(model.read_bytes(),original)
                self.assertFalse((Path(reused['run_directory'])/'comsol/paired_accelerator_static.mph').exists())
            metrics=json.loads((run/'results/comparison/accelerator_vector_field_metrics.json').read_text(encoding='utf8'))
            self.assertEqual(metrics['sample_points'],2)
            self.assertEqual(metrics['status'],'COMPARISON_COMPLETE')


    def test_completed_samples_enter_store_without_comsol_process(self):
        import csv
        from msplatform.backends.comsol.paired_static_field import prepare
        from msplatform.io.manifest_records import file_record
        with tempfile.TemporaryDirectory(prefix='paired-samples-store-') as directory:
            root=Path(directory);author=root/'author';author.mkdir()
            fixture=preparation.PairedAcceleratorStaticFieldPrepareTests();request=fixture._request(author)
            request_path=fixture._write_request(author,request)
            store=ArtifactStore(root/'store')
            with store.inplace_asset('native_stage','published-sample-fixture') as (asset,asset_path,_claim,seal):
                run=asset_path/'runs'/'source';(run/'inputs/bvp').mkdir(parents=True);(run/'comsol').mkdir()
                plan=prepare(request_path,run/'inputs/bvp')
                plan_path=run/'inputs/bvp/paired_accelerator_static_field_plan.json'
                points=list(csv.DictReader(Path(plan['sample_points']['path']).read_text(encoding='utf8').splitlines()))
                samples=run/'comsol/comsol_field_samples.csv'
                fields=['point_id','x_mm','y_mm','z_mm','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m']
                with samples.open('w',newline='',encoding='utf8') as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                    for row in points:writer.writerow(dict(row,Ex_V_per_m=1,Ey_V_per_m=2,Ez_V_per_m=3))
                facts=run/'comsol/comsol_field_native_facts.json'
                model=run/'comsol/paired_accelerator_static.mph';model.write_text('INERT NOT COMSOL',encoding='utf8')
                facts.write_text(json.dumps(dict(backend='COMSOL',coordinate_unit='mm',field_unit=['V/m']*3,
                    point_count=len(points),plan_path=str(plan_path),sample_path=str(samples),model_path=str(model))),encoding='utf8')
                completion=run/'results/execution_completion.json';completion.parent.mkdir()
                completion.write_text(json.dumps(dict(run_id='source',package={'execution_alias':None})),encoding='utf8')
                manifest=run/'run_manifest.json'
                manifest.write_text(json.dumps(dict(role='simulation_run_manifest',status='success',project='instrument_assembly',
                    mode='paired_accelerator_static_field',run_id='source',inputs={'plan':file_record(plan_path,'required_evidence')},
                    outputs=[file_record(samples,'required_evidence'),file_record(facts,'required_evidence'),file_record(model,'required_evidence'),
                             file_record(completion,'required_evidence')])),encoding='utf8');seal()
            stage=root/'stage.json';limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=32*1024*1024,
                process_tree_working_set_bytes=2*1024**3,minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=32*1024*1024,automatic_retry_count=0)
            stage.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages={
                'paired_accelerator_static_field':dict(limits=limits,artifact_retention=dict(policy_version=1,
                **{'class':'solver_review'},reason='inert completed samples fixture'))})),encoding='utf8')
            simion=root/'simion_stub.py';simion.write_text(INERT,encoding='utf8')
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3',policy_path=resource_path('host_resource_policy.json'),stage_policy_path=stage)
            actual=RunSession.run_process;operations=[]
            def transport(session,operation_id,**kwargs):
                operations.append(operation_id)
                if operation_id=='paired_simion':kwargs['arguments']=['-I','-B',str(simion),kwargs['arguments'][-1]]
                return actual(session,operation_id,**kwargs)
            env=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                     MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,env),patch.object(RunSession,'run_process',new=transport):
                result=run_paired_static_comparison(context,artifact_store=store,request_path=request_path,
                    run_id='20261127_145002__test__python__paired-public-samples',committed_new_bytes=32*1024*1024,
                    saved_samples_manifest=manifest)
            self.assertEqual(result['status'],'success')
            self.assertEqual(operations,['paired_simion','paired_analysis'])
            with store._db() as db:
                required=db.execute('SELECT required FROM refs WHERE run_id=? AND asset_id=?',(result['store_run_id'],asset)).fetchone()
            self.assertEqual(required,(1,))

PREPARED_FAILURE = r'''
import json,sys
from pathlib import Path
run=Path(sys.argv[1]);out=run/'comsol';plan=run/'inputs/bvp/paired_accelerator_static_field_plan.json'
model=out/'paired_accelerator_static.mph';model.write_bytes(b'INERT PREPARED NOT COMSOL')
(out/'comsol_field_solution.json').write_text(json.dumps(dict(schema_version=1,role='oatof_paired_accelerator_static_field_solution',status='prepared_saved',solution_present=False,solution_tag='sol1',study_tag='std1',mesh_complete=True,tetrahedra=1,plan_path=str(plan),model_path=str(model))),encoding='utf8')
sys.exit(7)
'''
PREPARED_REOPEN = r'''
import csv,json,sys
from pathlib import Path
run=Path(sys.argv[1]);source=Path(sys.argv[2]);assert source.read_bytes()==b'INERT PREPARED NOT COMSOL'
out=run/'comsol';plan=run/'inputs/bvp/paired_accelerator_static_field_plan.json'
points=list(csv.DictReader((run/'inputs/bvp/paired_accelerator_field_points.csv').read_text(encoding='utf8').splitlines()))
fields=['point_id','x_mm','y_mm','z_mm','Ex_V_per_m','Ey_V_per_m','Ez_V_per_m']
with (out/'comsol_field_samples.csv').open('w',newline='',encoding='utf8') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
 for row in points:w.writerow(dict(row,Ex_V_per_m=1,Ey_V_per_m=2,Ez_V_per_m=3))
model=out/'paired_accelerator_static.mph';model.write_bytes(b'INERT SOLVED NOT COMSOL')
(out/'comsol_field_native_facts.json').write_text(json.dumps(dict(backend='COMSOL',coordinate_unit='mm',field_unit=['V/m']*3,point_count=len(points),plan_path=str(plan),model_path=str(model),sample_path=str(out/'comsol_field_samples.csv'))),encoding='utf8')
(out/'comsol_field_solution.json').write_text(json.dumps(dict(schema_version=1,role='oatof_paired_accelerator_static_field_solution',status='solved_saved',solution_present=True,solution_tag='sol1',study_tag='std1',mesh_complete=True,tetrahedra=1,plan_path=str(plan),model_path=str(model))),encoding='utf8')
(run/'logs/paired_comsol.bootstrap.log').write_text('STATUS=PASS',encoding='utf8')
'''

@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process owner required')
class PairedPreparedRecoveryTests(unittest.TestCase):
    def test_failed_prepared_store_proof_and_new_run(self):
        from msplatform.backends.comsol.paired_static_model_source import guard_paired_failed_prepared_model
        with tempfile.TemporaryDirectory(prefix='paired-prepared-') as directory:
            root=Path(directory);author=root/'author';author.mkdir()
            fixture=preparation.PairedAcceleratorStaticFieldPrepareTests();request=fixture._request(author)
            request_path=fixture._write_request(author,request)
            stage=root/'stage.json';limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=32*1024*1024,
                process_tree_working_set_bytes=2*1024**3,minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=32*1024*1024,automatic_retry_count=0)
            stage.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages={
                'paired_accelerator_static_field':dict(limits=limits,artifact_retention=dict(policy_version=1,
                **{'class':'solver_review'},reason='inert prepared recovery fixture'))})),encoding='utf8')
            simion=root/'simion_stub.py';simion.write_text(INERT,encoding='utf8')
            failure=root/'failure_stub.py';failure.write_text(PREPARED_FAILURE,encoding='utf8')
            reopen=root/'reopen_stub.py';reopen.write_text(PREPARED_REOPEN,encoding='utf8')
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable),
                'comsol_launcher':Path(sys.executable),'matlab_root':root},host_state_path=root/'host.sqlite3',
                policy_path=resource_path('host_resource_policy.json'),stage_policy_path=stage)
            store=ArtifactStore(root/'store');actual=RunSession.run_process;source=[]
            def transport(session,operation_id,**kwargs):
                if operation_id=='paired_simion':kwargs['arguments']=['-I','-B',str(simion),kwargs['arguments'][-1]]
                elif operation_id=='paired_comsol':
                    kwargs['executable']=Path(sys.executable)
                    kwargs['arguments']=(['-I','-B',str(reopen),str(session.run_dir),source[0]] if source
                                         else ['-I','-B',str(failure),str(session.run_dir)])
                return actual(session,operation_id,**kwargs)
            env=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                     MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,env),patch.object(RunSession,'run_process',new=transport), \
                 patch('msplatform.workflows.paired_accelerator_static_field.store_workflow.require_launcher_completion'):
                with self.assertRaises(Exception) as first_failure:
                    run_paired_static_comparison(context,artifact_store=store,request_path=request_path,
                        run_id='20261127_145010__test__python__paired-failed',committed_new_bytes=32*1024*1024)
                manifests=list(store.root.glob('assets/native_stage/*/*/runs/*paired-failed/run_manifest.json'))
                self.assertEqual(len(manifests),1);manifest=manifests[0]
                outputs=json.loads(manifest.read_text(encoding='utf8'))['outputs']
                self.assertTrue(any(Path(item['path']).name=='comsol_field_solution.json' for item in outputs),
                    f'original failure: {first_failure.exception!r}; attrs: {vars(first_failure.exception)!r}; outputs: {[Path(item["path"]).name for item in outputs]}')
                with guard_paired_failed_prepared_model(store,manifest) as guarded:
                    self.assertEqual(guarded['source_stage'],'prepared_saved')
                    source.append(guarded['model']['path']);before=Path(source[0]).read_bytes()
                with store._db() as db:
                    failed_id=db.execute("SELECT id FROM assets WHERE state='failed'").fetchone()[0]
                result=run_paired_static_comparison(context,artifact_store=store,request_path=request_path,
                    run_id='20261127_145011__test__python__paired-prepared',committed_new_bytes=32*1024*1024,
                    prepared_model_manifest=manifest)
                self.assertEqual(result['status'],'success')
                self.assertEqual(Path(source[0]).read_bytes(),before)
                self.assertEqual(store.asset_status(failed_id)['state'],'failed')
                self.assertEqual((Path(result['run_directory'])/'comsol/paired_accelerator_static.mph').read_bytes(),b'INERT SOLVED NOT COMSOL')
