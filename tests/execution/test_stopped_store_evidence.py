"""Stopped Store evidence guards actual short-process owner results."""
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from msplatform.execution.native_source_guard import guard_stopped_store_evidence, guard_failed_store_evidence
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore
from tests.contracts import test_execution_runtime as owner_fixture


def interrupted_action(session):
    session.run_process('unit',executable=Path(sys.executable),arguments=['-c','print("inert unit")'],
                        role='GATE',stage='software_tests',limits=None)
    index=session.declare_file(session.result_dir/'unit_index.json','required_evidence')
    unit=session.declare_file(session.result_dir/'unit.csv','required_evidence')
    unit.write_text('particle_id\n1\n',encoding='utf-8')
    index.write_text(json.dumps({'unit':file_record(unit,'required_evidence')}),encoding='utf-8')
    return dict(status='interrupted',summary={'fixture':'INERT_ONLY'},output_paths=[str(index),str(unit)],
        required_output_paths=[str(index),str(unit)],retention_preserve_paths=[],manifest_extra_fields={})


def failed_action(session):
    result=interrupted_action(session)
    failure=RuntimeError('inert observed failure')
    failure.failure_output_paths=result['output_paths']
    raise failure


@unittest.skipUnless(os.name=='nt' and os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'),'shared Windows host ledger required')
class StoppedStoreEvidenceTests(unittest.TestCase):
    def test_group_attempt_set_rejects_missing_and_duplicate_records(self):
        from msplatform.execution.native_artifact_controls import validate_native_group_completion
        members=[('a',1,2),('b',3,4)]
        attempts=[('a',1,1,2),('b',1,3,4)]
        incomplete={'writers_stopped':True,'operations':[{'operation_id':'a','attempt':1}],
                    'not_started':[],'resource_releases':[]}
        for proof in (incomplete,dict(incomplete,operations=incomplete['operations']*2)):
            with self.assertRaisesRegex(ValueError,'exact declared attempts'):
                validate_native_group_completion(host_token='host',host_state_path='unused',host_file_id=[],
                    members=members,attempts=attempts,completion=proof)
    def test_actual_failed_worker_keeps_legacy_single_output_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);helper=owner_fixture.NormalOwnerTests();policy=root/'capacity.json'
            policy.write_text(json.dumps(helper._policy()),encoding='utf-8')
            context=replace(helper._context(root),capacity_policy_path=policy,
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']))
            context.workspace.mkdir(parents=True)
            args=helper._arguments(root,failed_action)
            args.update(run_id='20261127_150001__test__python__failed',expected_operation_ids=('unit',),
                operation_dependencies={},action_record=file_record(Path(__file__),'required_evidence'),
                completion_api=no_particle_batch_completion_api)
            store=ArtifactStore(root/'store')
            with self.assertRaisesRegex(RuntimeError,'inert observed failure'):
                run_managed_stage(context,artifact_store=store,**args)
            manifest_path=next(store.root.glob('assets/native_stage/*/*/runs/*/run_manifest.json'))
            record=file_record(manifest_path,'required_evidence')
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['status'],'failed')
            outputs={Path(row['path']).name:row for row in manifest['outputs']}
            with guard_failed_store_evidence(store,record,outputs['unit_index.json']): pass
            with guard_stopped_store_evidence(store,record) as (guarded,hold):
                self.assertEqual(guarded['status'],'failed')
                hold([outputs['unit_index.json'],outputs['unit.csv']])
    def test_actual_interrupted_worker_proofs_and_selected_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);helper=owner_fixture.NormalOwnerTests();policy=root/'capacity.json'
            policy.write_text(json.dumps(helper._policy()),encoding='utf-8')
            context=replace(helper._context(root),capacity_policy_path=policy,
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']))
            context.workspace.mkdir(parents=True)
            args=helper._arguments(root,interrupted_action)
            args.update(run_id='20261127_150000__test__python__interrupted',
                expected_operation_ids=('unit',),operation_dependencies={},
                action_record=file_record(Path(__file__),'required_evidence'),completion_api=no_particle_batch_completion_api)
            store=ArtifactStore(root/'store')
            result=run_managed_stage(context,artifact_store=store,**args)
            record=result['manifest'];manifest_path=Path(record['path'])
            manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['status'],'interrupted')
            outputs={Path(row['path']).name:row for row in manifest['outputs']}
            index,unit=outputs['unit_index.json'],outputs['unit.csv']
            with store._db() as db:
                identity,work,state=db.execute("SELECT id,work,state FROM assets WHERE path LIKE 'assets/native_stage/%'").fetchone()
                binding=db.execute('SELECT b.id FROM native_bindings b JOIN native_binding_controls c ON c.binding_id=b.id WHERE c.control_id=?',(work[8:],)).fetchone()[0]
            self.assertEqual(state,'failed')
            with guard_stopped_store_evidence(store,record) as (guarded,hold):
                self.assertEqual(guarded['status'],'interrupted')
                hold([index]); self.assertEqual(json.loads(Path(index['path']).read_text())['unit'],unit)
                hold([unit])
                with self.assertRaises(PermissionError): Path(unit['path']).unlink()
                with self.assertRaisesRegex(ValueError,'uniquely bound'):
                    hold([dict(unit,sha256='0'*64)])
            with self.assertRaises(ValueError):
                with guard_failed_store_evidence(store,record,index): pass
            with store._transaction() as db: db.execute("UPDATE native_bindings SET state='active' WHERE id=?",(binding,))
            try:
                with self.assertRaises(ValueError):
                    with guard_stopped_store_evidence(store,record): pass
            finally:
                with store._transaction() as db: db.execute("UPDATE native_bindings SET state='complete' WHERE id=?",(binding,))
            Path(unit['path']).unlink()
            with self.assertRaises((OSError,ValueError)):
                with guard_stopped_store_evidence(store,record) as (_,hold): hold([unit])
            self.assertEqual(store.asset_status(identity)['state'],'failed')
            with store.inplace_asset('native_stage','active-checkpoint',run_id='20261127_150002__test__python__checkpoint') as (_,asset,_,_seal):
                pending=asset/'runs'/'20261127_150002__test__python__checkpoint'
                pending.mkdir(parents=True)
                checkpoint=pending/'run_manifest.json'
                checkpoint.write_text(json.dumps({'status':'checkpoint'}),encoding='utf-8')
                with self.assertRaises(ValueError):
                    with guard_stopped_store_evidence(store,file_record(checkpoint,'required_evidence')): pass
