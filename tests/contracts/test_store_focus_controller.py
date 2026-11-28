"""Inert process-owner checks for Store focus controller family."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import patch

from msplatform.backends.simion.oa_focus_controller_store import run_focus_controller
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution import owner
from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore

INERT = r'''
from pathlib import Path
from msplatform.backends.simion import oa_focus_controller_store as w
original=w._run_native
def inert(context,*,name,arguments,directory,run_directory,limits,records,marker):
    outputs=[]
    if name=='focus_build':
        raw=Path(arguments[5]); count=int(arguments[6]); outputs=[str(raw)]+[str(raw.with_suffix('.pa'+str(i))) for i in range(count+1)]
    elif name.startswith('focus_export_'):
        outputs=[arguments[-1]]
    code="from pathlib import Path; outputs="+repr(outputs)+"\nfor p in outputs: Path(p).write_bytes(b'INERT_NOT_PA')\nprint("+repr(marker)+")"
    return original(context,name=name,arguments=['-c',code],directory=directory,
        run_directory=run_directory,limits=limits,records=records,marker=marker)
w._run_native=inert
w.main()
'''

@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process owner required')
class StoreFocusControllerTests(unittest.TestCase):
    def test_focus_worker_rejects_unsafe_receipt_before_writing(self):
        from msplatform.backends.simion import oa_focus_controller_store as subject
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run = root/'run'; (run/'inputs').mkdir(parents=True)
            outside = root/'outside.json'; outside.write_text('{"sentinel":true}', encoding='utf8')
            request = run/'inputs/request.json'
            request.write_text(json.dumps(dict(schema_version=1, context={}, inputs=[], parameters=dict(
                run_directory=str(run), log_directory=str(run/'logs/controller'),
                execution_directory=str(run/'logs/controller/native'), receipt_path=str(outside)))), encoding='utf8')
            with patch.object(sys, 'argv', ['focus', str(request)]):
                with self.assertRaisesRegex(ValueError, 'paths escape'):
                    subject.main()
            self.assertEqual(outside.read_text(encoding='utf8'), '{"sentinel":true}')

    def test_public_campaign_api_executes_managed_inert_controller(self):
        from msplatform.workflows.oa_focus_controller import run_focus_controller_campaign
        with tempfile.TemporaryDirectory(prefix='focus-campaign-store-') as directory:
            root = Path(directory)
            plan = dict(role='orthogonal_accelerator_component_focus_pa_plan', electrode_count=4,
                layout=dict(ring_count=0), gem='INERT_GEM', numerical_domain=dict(
                    mesh_mm_per_gu=[1.,1.,1.], span_mm=[2.,2.,2.], stored_span_mm=[2.,2.,2.],
                    mirror_axes=['x'], iob_origin_mm=[0.,0.,0.]))
            campaign = Path(__file__).resolve().parents[2]/'src/msplatform/components/orthogonal_accelerator/config/two_zone_component_focus_campaign.json'
            before = campaign.read_bytes()
            script = root/'inert.py'; script.write_text(INERT, encoding='utf8')
            stage = root/'stage.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=16*1024*1024,
                process_tree_working_set_bytes=2*1024**3, minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=16*1024*1024, automatic_retry_count=0)
            stage.write_text(json.dumps(dict(schema_version=1, role='execution_stage_policy',
                stages={'oa_focus_controller':dict(limits=limits,artifact_retention={
                    'policy_version':1,'class':'solver_review','reason':'inert focus fixture'})})), encoding='utf8')
            context = ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3',policy_path=resource_path('host_resource_policy.json'))
            context = replace(context, stage_policy_path=stage)
            store = ArtifactStore(root/'store')
            actual = RunSession.run_process
            def transport(session, operation_id, **kwargs):
                kwargs['arguments']=['-I','-B',str(script),kwargs['arguments'][-1]]
                return actual(session,operation_id,**kwargs)
            env=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                     MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,env), patch.object(RunSession,'run_process',new=transport), \
                 patch('msplatform.backends.simion.oa_focus_plan.derive',return_value=plan):
                result = run_focus_controller_campaign(context, artifact_store=store, campaign_path=campaign,
                    mesh_mm_per_gu=[1.,1.,1.], run_id='20261127_130100__test__python__focus-public',
                    committed_new_bytes=16*1024*1024)
            self.assertEqual(result['status'],'success')
            run = Path(result['run_directory'])
            summary = json.loads((run/'results/focus_controller_result.json').read_text(encoding='utf8'))
            self.assertEqual((summary['cache_disposition'], summary['native_count']), ('miss',6))
            self.assertEqual((run/'inputs/campaign.json').read_bytes(),before)
            self.assertEqual(campaign.read_bytes(),before)
            self.assertEqual(ArtifactStore(root/'store').inspect_run(result['store_run_id']),Path(result['store_run_path']))
            with patch.dict(os.environ,env), patch.object(RunSession,'run_process',new=transport), \
                 patch('msplatform.backends.simion.oa_focus_plan.derive',return_value=plan):
                legacy = run_focus_controller_campaign(context, artifact_store=store, campaign_path=campaign,
                    mesh_mm_per_gu=[1.,1.,1.], run_id='20261127_130101__test__python__focus-legacy-store',
                    committed_new_bytes=16*1024*1024, legacy_pa_output=True)
            legacy_run = Path(legacy['run_directory'])
            pa_result = json.loads((legacy_run/'results/component_focus_pa_result.json').read_text(encoding='utf8'))
            self.assertEqual(pa_result['disposition'],'hit')
            self.assertEqual(pa_result['store_asset_id'],summary['asset_id'])
            checkpoint = json.loads((legacy_run/'results/accelerator_runtime_checkpoint.json').read_text(encoding='utf8'))
            self.assertEqual(checkpoint['cache_key'],pa_result['cache_key'])
            self.assertEqual(len(checkpoint['members']),5)
            self.assertTrue(all((Path(checkpoint['directory'])/row['name']).is_file() for row in checkpoint['members']))
            self.assertEqual(json.loads((legacy_run/'run_manifest.json').read_text(encoding='utf8'))['mode'],'component_focus_pa_build')

    def test_family_miss_hit_and_missing_rebuild_with_native_evidence(self):
        with tempfile.TemporaryDirectory(prefix='store-focus-') as directory:
            root=Path(directory)
            plan=dict(role='orthogonal_accelerator_component_focus_pa_plan', electrode_count=4,
                layout=dict(ring_count=0), gem='INERT_GEM', numerical_domain=dict(
                    mesh_mm_per_gu=[1.,1.,1.], span_mm=[2.,2.,2.], stored_span_mm=[2.,2.,2.],
                    mirror_axes=['x'], iob_origin_mm=[0.,0.,0.]))
            resources=dict(builder=native_resource_path('build_component_focus_pa.lua'),
                exporter=native_resource_path('export_standalone_pa.lua'),
                verifier=native_resource_path('verify_component_focus_pa.lua'))
            script=root/'inert.py';script.write_text(INERT,encoding='utf8')
            budget=root/'budget.json';budget.write_text('{}',encoding='utf8')
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3',policy_path=resource_path('host_resource_policy.json'))
            store=ArtifactStore(root/'store');reports=[]
            def action(session):
                reports.append(run_focus_controller(session,operation_id='focus',plan=plan,resources=resources,limits={}))
                return dict(status='success',summary={},output_paths=[],required_output_paths=[],
                    retention_preserve_paths=[],manifest_extra_fields={})
            actual=RunSession.run_process
            def transport(session,operation_id,**kwargs):
                kwargs['arguments']=['-I','-B',str(script),kwargs['arguments'][-1]]
                return actual(session,operation_id,**kwargs)
            env=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                     MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,env),patch.object(RunSession,'run_process',new=transport):
                for i,(disposition,count) in enumerate((('miss',6),('hit',0),('miss',6))):
                    result=owner.run_managed_stage(context,descriptor=dict(project='orthogonal_accelerator',mode='focus',software=[]),
                        run_id=f'20261127_13000{i}__test__python__focus-store',payload={},committed_new_bytes=16*1024*1024,
                        commitment_inputs=[file_record(budget,'required_evidence')],
                        retention=dict(policy_version=1,**{'class':'solver_review'},reason='inert focus controller'),
                        expected_operation_ids=['focus'],operation_dependencies={},action=action,
                        action_record=file_record(Path(__file__),'required_evidence'),artifact_store=store,
                        completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
                    self.assertEqual(result['status'],'success')
                    self.assertEqual((reports[-1]['cache_disposition'],reports[-1]['native_count']),(disposition,count))
                    if i==1:
                        (Path(reports[-1]['asset_directory'])/'orthogonal_accelerator_focus.response3.pa').unlink()
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0],0)

    def test_focus_controller_supplies_no_particle_retention_completion(self):
        from msplatform.execution.completion import no_particle_batch_completion_api
        from msplatform.workflows.oa_focus_controller import run_focus_controller_campaign
        from types import SimpleNamespace
        campaign=Path(__file__).resolve().parents[2]/'src/msplatform/components/orthogonal_accelerator/config/two_zone_component_focus_campaign.json'
        stage={'artifact_retention':{},'limits':{}}
        def owner(context,**kwargs):
            self.assertIs(kwargs['completion_api'],no_particle_batch_completion_api)
            return {'status':'fixture'}
        with patch('msplatform.workflows.oa_focus_controller.read_stage_policy',return_value=(stage,{})), \
             patch('msplatform.backends.simion.oa_focus_plan.derive',return_value={'role':'inert'}), \
             patch('msplatform.workflows.oa_focus_controller.run_managed_stage',side_effect=owner):
            result=run_focus_controller_campaign(SimpleNamespace(),artifact_store=object(),campaign_path=campaign,
                mesh_mm_per_gu=[1.,1.,1.],run_id='inert',committed_new_bytes=1)
        self.assertEqual(result['status'],'fixture')

    def test_verified_store_controller_materializes_claimed_private_family(self):
        from types import SimpleNamespace
        from msplatform.backends.simion.oa_focus_controller_store import materialize_focus_runtime
        from msplatform.backends.simion.oa_focus_identity import expected_files, identity
        from msplatform.execution.native_artifact_controls import current_native_artifact_scope
        from msplatform.execution.owner import standalone_native_store
        from msplatform.io.file_identity import canonical_json_sha256, file_sha256
        from msplatform.storage.store import ArtifactStore
        with tempfile.TemporaryDirectory(prefix='focus-runtime-store-') as directory:
            root=Path(directory);store=ArtifactStore(root/'store')
            plan=dict(role='orthogonal_accelerator_component_focus_pa_plan',electrode_count=4,layout={'ring_count':0},
                gem='INERT',numerical_domain=dict(mesh_mm_per_gu=[1.,1.,1.],span_mm=[2.,2.,2.],
                stored_span_mm=[1.,2.,2.],mirror_axes=['x'],iob_origin_mm=[0.,-1.,0.]))
            resources={name:root/(name+'.lua') for name in ('builder','exporter','verifier')}
            for name,path in resources.items():path.write_text('INERT '+name,encoding='utf8')
            exe=Path(sys.executable);science=identity(plan,resources['builder'],exe)
            key=canonical_json_sha256(dict(schema_version=1,science=science,
                exporter_sha256=file_sha256(resources['exporter']),verifier_sha256=file_sha256(resources['verifier'])))
            work=store.new_work()
            for name in expected_files(plan):(work/name).write_bytes(('INERT '+name).encode())
            (work/'focus_identity.json').write_text(json.dumps(dict(cache_key=key,identity=science)),encoding='utf8')
            (work/'focus_verify.process.json').write_text(json.dumps(dict(observation=dict(exit_code=0))),encoding='utf8')
            (work/'focus_verify.stdout.log').write_text('ACCELERATOR_COMPONENT_FOCUS_PA_VERIFY=PASS',encoding='utf8')
            asset=store.put_asset('simion_focus_controller','simion-focus-controller-v1:'+key,work)
            with standalone_native_store(store,task_key='focus-runtime-fixture',budget=1024*1024) as scope:
                workdir=current_native_artifact_scope()['work_directory'];inputs=workdir/'inputs';inputs.mkdir()
                inputs_added={}
                class Session:
                    input_dir=inputs
                    _store_stage_directory=workdir
                    context=SimpleNamespace(tools={'simion':exe})
                    def declare_file(self,path,role):return path
                    def add_input(self,name,record):inputs_added[name]=record
                with materialize_focus_runtime(Session(),asset_id=asset,plan=plan,resources=resources) as runtime:
                    self.assertEqual(len(runtime['members']),5)
                    self.assertEqual(Path(runtime['controller']['path']).read_bytes(),b'INERT orthogonal_accelerator_focus.pa0')
                    self.assertEqual(current_native_artifact_scope()['claim_ids'][-1] != '',True)
                    self.assertEqual(store.collect(100000)['released_bytes'],0)
                self.assertEqual(len(inputs_added),5)
                context=ExecutionContext(workspace=root/'study',python_executable=exe,
                    powershell_executable=Path(shutil.which('pwsh')),tools={'simion':exe},
                    host_state_path=root/'host.sqlite3',policy_path=resource_path('host_resource_policy.json'))
                def consume(session):
                    with materialize_focus_runtime(session,asset_id=asset,plan=plan,resources=resources) as runtime:
                        token=current_native_artifact_scope()['claim_ids'][-1]
                        program="from pathlib import Path;import sys;assert all(Path(x).read_bytes().startswith(b'INERT') for x in sys.argv[1:]);print('PRIVATE_FOCUS_FAMILY=PASS')"
                        session.run_process('consume_focus',executable=exe,
                            arguments=['-I','-c',program,*[row['path'] for row in runtime['members']]],
                            role='GATE',stage='inert_focus_consumer',limits={},immutable_input_records=runtime['members'])
                        with store._db() as db:
                            bound=db.execute('''SELECT b.state FROM native_bindings b JOIN native_binding_controls c
                                ON c.binding_id=b.id WHERE c.control_id=? AND b.operation_id='consume_focus' ''',(token,)).fetchall()
                        self.assertEqual(bound,[('complete',)])
                    output=session.declare_file(session.result_dir/'result.json','required_evidence')
                    output.write_text('{}',encoding='utf8')
                    return dict(status='success',summary={},output_paths=[output],required_output_paths=[output],
                                retention_preserve_paths=[],manifest_extra_fields={})
                result=owner.run_managed_stage(context,descriptor=dict(project='orthogonal_accelerator',
                    mode='focus_runtime_fixture',software=[]),run_id='20261127_153000__test__python__focus-runtime',
                    payload={},committed_new_bytes=1024*1024,commitment_inputs=[file_record(resources['builder'],'required_evidence')],
                    retention=dict(policy_version=1,**{'class':'solver_review'},reason='inert focus runtime'),
                    expected_operation_ids=['consume_focus'],operation_dependencies={},action=consume,
                    action_record=file_record(Path(__file__),'required_evidence'),artifact_store=store)
                self.assertEqual(result['status'],'success')
            with store._db() as db:
                self.assertEqual(db.execute('SELECT required FROM refs WHERE run_id=? AND asset_id=?',
                    (scope['parent_run_id'],asset)).fetchone(),(1,))
            with self.assertRaises(ValueError):
                with standalone_native_store(store,task_key='focus-runtime-wrong',budget=1024*1024):
                    wrong=dict(plan,gem='CHANGED')
                    with materialize_focus_runtime(Session(),asset_id=asset,plan=wrong,resources=resources):pass
            (store.asset_status(asset)['path']/'orthogonal_accelerator_focus.pa1').write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                with standalone_native_store(store,task_key='focus-runtime-tampered',budget=1024*1024):
                    with materialize_focus_runtime(Session(),asset_id=asset,plan=plan,resources=resources):pass
