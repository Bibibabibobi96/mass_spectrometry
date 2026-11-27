"""Historical saved model guard, using inert bytes and no vendor software."""
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.backends.comsol.paired_static_model_source import guard_paired_saved_model
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from tests.workflows.paired_accelerator.test_support import paired_fixtures as fixtures

class PairedSavedModelGuardTests(unittest.TestCase):
    def test_direct_published_model_is_held_and_failed_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            _,producer,model,_,_,_=fixtures.completed_comsol_source(root)
            config_path=producer/'run_config.json';config=json.loads(config_path.read_text(encoding='utf8'))
            config['run_id']=producer.name;config_path.write_text(json.dumps(config),encoding='utf8')
            manifest_path=producer/'run_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf8'))
            manifest['run_id']=producer.name;manifest['run_config']=file_record(config_path,'required_evidence')
            manifest_path.write_text(json.dumps(manifest),encoding='utf8')
            store=ArtifactStore(root/'store')
            with guard_paired_saved_model(store,manifest_path) as source:
                self.assertEqual(Path(source['model']['path']),model)
                self.assertEqual(source['source_stage'],'solved_saved')
                self.assertIsNone(source['asset_id'])
                if __import__('os').name=='nt':
                    with self.assertRaises(PermissionError):
                        model.unlink()
            original=model.read_bytes();model.write_bytes(b'tampered')
            with self.assertRaises((ValueError,AssertionError)):
                with guard_paired_saved_model(store,manifest_path): pass
            model.write_bytes(original)
            manifest['status']='failed';manifest_path.write_text(json.dumps(manifest),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'terminal identity'):
                with guard_paired_saved_model(store,manifest_path): pass

    def test_ready_store_source_claim_guards_model_and_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);author=root/'author';author.mkdir()
            from msplatform.backends.comsol.paired_static_field import prepare
            fixture=fixtures.preparation_tests.PairedAcceleratorStaticFieldPrepareTests()
            request=fixture._request(author);request_path=fixture._write_request(author,request)
            store=ArtifactStore(root/'store')
            with store.inplace_asset('native_stage','inert-paired-source') as (asset_id,asset,_claim,seal):
                run=asset/'runs'/'source';(run/'inputs/bvp').mkdir(parents=True);(run/'comsol').mkdir()
                prepare(request_path,run/'inputs/bvp')
                plan=run/'inputs/bvp/paired_accelerator_static_field_plan.json'
                model=run/'comsol/paired_accelerator_static.mph';model.write_bytes(b'INERT NOT COMSOL')
                solution=run/'comsol/comsol_field_solution.json'
                solution.write_text(json.dumps(dict(schema_version=1,role='oatof_paired_accelerator_static_field_solution',
                    status='solved_saved',solution_present=True,solution_tag='sol1',plan_path=str(plan),model_path=str(model))),encoding='utf8')
                completion=run/'results/execution_completion.json';completion.parent.mkdir()
                completion.write_text(json.dumps(dict(run_id='source',package={'execution_alias':None})),encoding='utf8')
                samples=run/'comsol/comsol_field_samples.csv';samples.write_text('INERT',encoding='utf8')
                facts=run/'comsol/comsol_field_native_facts.json'
                facts.write_text(json.dumps(dict(backend='COMSOL',coordinate_unit='mm',field_unit=['V/m']*3,
                    point_count=2,plan_path=str(plan),sample_path=str(samples),model_path=str(model))),encoding='utf8')
                manifest=run/'run_manifest.json'
                manifest.write_text(json.dumps(dict(role='simulation_run_manifest',status='success',project='instrument_assembly',
                    mode='paired_accelerator_static_field',run_id='source',inputs={'plan':file_record(plan,'required_evidence')},
                    outputs=[file_record(solution,'required_evidence'),file_record(model,'required_evidence'),
                             file_record(completion,'required_evidence'),file_record(samples,'required_evidence'),
                             file_record(facts,'required_evidence')])),encoding='utf8')
                seal()
            with guard_paired_saved_model(store,manifest) as source:
                self.assertEqual(source['asset_id'],asset_id)
                self.assertTrue(source['claim_token'])
                self.assertEqual(store.collect(100000)['released_bytes'],0)
            from msplatform.backends.comsol.paired_static_model_source import guard_paired_saved_samples
            with guard_paired_saved_samples(store,manifest) as source:
                self.assertEqual(source['asset_id'],asset_id)
            model.write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                with guard_paired_saved_model(store,manifest): pass

    def test_recovery_identifies_paired_ready_stage_and_run_without_solver(self):
        from msplatform.workflows.paired_accelerator_static_field.store_workflow import recover_paired_static_publication
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=ArtifactStore(root/'store')
            with store.inplace_asset('native_stage','paired-recovery-fixture') as (identity,asset,_claim,seal):
                run=asset/'runs'/'inert';run.mkdir(parents=True)
                manifest=run/'run_manifest.json'
                document=dict(role='simulation_run_manifest',project='instrument_assembly',
                    mode='paired_accelerator_static_field',run_id='inert',status='success')
                manifest.write_text(json.dumps(document),encoding='utf8');seal()
            run_id,work=store.begin_run()
            with store.run_writer(run_id):
                store.mark_running(run_id)
                (work/'evidence.json').write_text('{}',encoding='utf8')
                store.publish_run(work,required_assets=(identity,),run_id=run_id)
            for _ in range(2):
                result=recover_paired_static_publication(None,artifact_store=store,stage_asset_id=identity,store_run_id=run_id)
                self.assertFalse(result['stage_recovered']);self.assertFalse(result['run_recovered'])
                self.assertEqual(result['run']['publication_status'],'ready')
            document['mode']='other';manifest.write_text(json.dumps(document),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'not a paired'):
                recover_paired_static_publication(None,artifact_store=store,stage_asset_id=identity,store_run_id=run_id)

    def test_completed_historical_samples_need_no_model_and_reject_tamper(self):
        from msplatform.backends.comsol.paired_static_model_source import guard_paired_saved_samples
        from msplatform.analysis.paired_static_samples import validate_samples
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            _,producer,model,samples,_,_=fixtures.completed_comsol_source(root)
            config_path=producer/'run_config.json';config=json.loads(config_path.read_text(encoding='utf8'))
            config['run_id']=producer.name;config_path.write_text(json.dumps(config),encoding='utf8')
            manifest_path=producer/'run_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf8'))
            manifest['run_id']=producer.name;manifest['run_config']=file_record(config_path,'required_evidence')
            manifest_path.write_text(json.dumps(manifest),encoding='utf8')
            model.unlink()
            store=ArtifactStore(root/'store')
            with guard_paired_saved_samples(store,manifest_path) as source:
                plan=json.loads(Path(source['plan']['path']).read_text(encoding='utf8'))
                validate_samples(plan,Path(source['samples']['path']))
            samples.write_text('tampered',encoding='utf8')
            with self.assertRaises((ValueError,AssertionError)):
                with guard_paired_saved_samples(store,manifest_path): pass

    def test_failed_prepared_without_writer_proof_is_rejected(self):
        from msplatform.backends.comsol.paired_static_model_source import guard_paired_failed_prepared_model
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);store=ArtifactStore(root/'store')
            with store.inplace_asset('native_stage','fake-failed-prepared') as (_identity,asset,_claim,seal):
                run=asset/'runs'/'failed';(run/'comsol').mkdir(parents=True)
                model=run/'comsol/paired_accelerator_static.mph';model.write_bytes(b'INERT')
                solution=run/'comsol/comsol_field_solution.json';solution.write_text('{}',encoding='utf8')
                manifest=run/'run_manifest.json'
                manifest.write_text(json.dumps(dict(project='instrument_assembly',mode='paired_accelerator_static_field',
                    run_id='failed',status='failed',inputs={},outputs=[file_record(model,'solver_native_binary'),
                    file_record(solution,'required_evidence')])),encoding='utf8')
                seal(failure_reason='inert failure')
            with self.assertRaisesRegex(ValueError,'unique execution_completion.json'):
                with guard_paired_failed_prepared_model(store,manifest):pass

    def test_flat_borrowed_success_requires_protected_original_and_unchanged_receipt(self):
        import shutil
        from msplatform.backends.comsol.paired_static_model import load_paired_static_model_source
        from msplatform.backends.simion.native_completion import retention_api
        from msplatform.execution.manifest_publication import build_run_manifest
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,producer,model,_,_,_=fixtures.completed_comsol_source(root)
            config_path=producer/'run_config.json';config=json.loads(config_path.read_text(encoding='utf8'))
            config['run_id']=producer.name;config_path.write_text(json.dumps(config),encoding='utf8')
            manifest_path=producer/'run_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf8'))
            manifest['run_id']=producer.name;manifest['run_config']=file_record(config_path,'required_evidence')
            manifest_path.write_text(json.dumps(manifest),encoding='utf8')
            consumer=root/'20261127_150000__test__python__paired-borrow';inputs=consumer/'inputs';(inputs/'bvp').mkdir(parents=True)
            source_plan=producer/'inputs/bvp/paired_accelerator_static_field_plan.json'
            plan=inputs/'bvp/paired_accelerator_static_field_plan.json';shutil.copyfile(source_plan,plan)
            snapshot=inputs/'comsol_source_manifest.json';shutil.copyfile(manifest_path,snapshot)
            receipt=inputs/'comsol_source.json';receipt.write_text(json.dumps(load_paired_static_model_source(manifest_path,manifest_path)),encoding='utf8')
            config=consumer/'run_config.json';config.write_text(json.dumps(dict(schema_version=1,run_id=consumer.name,
                project='instrument_assembly',mode='paired_accelerator_static_field',inputs={'plan':str(plan),
                'source':str(receipt),'source_manifest':str(snapshot)})),encoding='utf8')
            own=consumer/'run_manifest.json';own.write_text(json.dumps(build_run_manifest(config,'success',retention_api=retention_api)),encoding='utf8')
            store=ArtifactStore(root/'store')
            with guard_paired_saved_model(store,own) as source:
                self.assertEqual(Path(source['model']['path']),model)
                self.assertEqual(len(source['source_chain']),4)
            receipt.write_text('{}',encoding='utf8')
            with self.assertRaises((ValueError,AssertionError)):
                with guard_paired_saved_model(store,own):pass


    def test_interrupted_store_prepared_proves_writer_and_holds_outputs(self):
        import os
        import shutil
        import sys
        from types import SimpleNamespace
        from msplatform.backends.comsol.paired_static_field import prepare
        from msplatform.backends.comsol.paired_static_model_source import guard_paired_failed_prepared_model
        from msplatform.execution import owner
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.resources import resource_path
        if os.name!='nt' or not shutil.which('pwsh'):
            self.skipTest('Windows process owner required')
        with tempfile.TemporaryDirectory(prefix='paired-interrupted-') as directory:
            root=Path(directory);author=root/'author';author.mkdir()
            fixture=fixtures.preparation_tests.PairedAcceleratorStaticFieldPrepareTests()
            request=fixture._request(author);request_path=fixture._write_request(author,request)
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={},host_state_path=root/'host.sqlite3',
                policy_path=resource_path('host_resource_policy.json'))
            store=ArtifactStore(root/'store')
            def action(session):
                target=session.input_dir/'bvp';target.mkdir(parents=True)
                for name in ('paired_accelerator.gem','paired_accelerator_geometry.json',
                    'paired_accelerator_field_points.csv','paired_accelerator_static_field_plan.json'):
                    session.declare_file(target/name,'required_evidence')
                prepare(request_path,target)
                plan=target/'paired_accelerator_static_field_plan.json'
                session.add_input('paired_plan',file_record(plan,'required_evidence'))
                model=session.declare_file(session.run_dir/'comsol/paired_accelerator_static.mph','solver_native_binary')
                solution=session.declare_file(session.run_dir/'comsol/comsol_field_solution.json','required_evidence')
                model.parent.mkdir(parents=True,exist_ok=True)
                code=("import json,sys;from pathlib import Path;p=Path(sys.argv[1]);m=Path(sys.argv[2]);s=Path(sys.argv[3]);"
                    "m.write_bytes(b'INERT INTERRUPTED MODEL');s.write_text(json.dumps(dict(schema_version=1,"
                    "role='oatof_paired_accelerator_static_field_solution',status='prepared_saved',solution_present=False,"
                    "solution_tag='sol1',study_tag='std1',mesh_complete=True,tetrahedra=1,plan_path=str(p),model_path=str(m))))")
                session.run_process('paired_comsol',executable=Path(sys.executable),arguments=['-I','-c',code,str(plan),str(model),str(solution)],
                    role='GATE',stage='inert_prepared',limits={})
                return dict(status='interrupted',summary={'fixture':'controlled interrupted state'},output_paths=[model,solution],
                    required_output_paths=[],retention_preserve_paths=[],manifest_extra_fields={})
            env={'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'',
                 'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}
            from unittest.mock import patch
            with patch.dict(os.environ,env):
                result=owner.run_managed_stage(context,descriptor=dict(project='instrument_assembly',
                    mode='paired_accelerator_static_field',software=[]),run_id='20261127_152000__test__python__paired-interrupted',
                    payload={},committed_new_bytes=16*1024*1024,commitment_inputs=[file_record(request_path,'required_evidence')],
                    retention=dict(policy_version=1,**{'class':'solver_review'},reason='inert interrupted fixture'),
                    expected_operation_ids=['paired_comsol'],operation_dependencies={},action=action,
                    action_record=file_record(Path(__file__),'required_evidence'),artifact_store=store,
                    completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
            self.assertEqual(result['status'],'interrupted')
            manifest=Path(result['run_directory'])/'run_manifest.json'
            with guard_paired_failed_prepared_model(store,manifest) as source:
                self.assertEqual(source['source_stage'],'prepared_saved')
                self.assertEqual(Path(source['model']['path']).read_bytes(),b'INERT INTERRUPTED MODEL')
            with store._db() as db:
                self.assertEqual(db.execute("SELECT state FROM assets WHERE path LIKE 'assets/native_stage/%'").fetchone()[0],'failed')
