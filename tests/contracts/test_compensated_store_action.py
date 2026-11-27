"""Inert real-owner integration of standalone reflectron rebias and audit."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.simion.field_execution import _run_rebias_operations
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution import owner
from msplatform.execution.context import ExecutionContext
from msplatform.execution.inputs import freeze_file
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process owner required')
class CompensatedStoreActionTests(unittest.TestCase):
    def test_real_store_owner_composition_then_audit_with_inert_processes(self):
        with tempfile.TemporaryDirectory(prefix='store-rebias-') as directory:
            root = Path(directory)
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={'simion':Path(sys.executable)},
                host_state_path=root/'host.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            store = ArtifactStore(root/'store')
            budget = root/'budget.json'; budget.write_text('{}', encoding='utf-8')
            calls = []
            fail_marker = [False]
            def action(session):
                work = session.run_dir/'simion/rebias'; work.mkdir(parents=True)
                records = {}
                resources = {}
                for name in ('compose_standalone_pa.lua', 'audit_downstream_fields.lua'):
                    path = session.declare_file(session.input_dir/name, 'required_evidence')
                    freeze_file(native_resource_path(name), path, retention_role='required_evidence')
                    records['resource_'+name] = file_record(path, 'required_evidence')
                    session.add_input(name, records['resource_'+name]); resources[name] = path
                paths = [work/name for name in ('base.pa', 'one.pa', 'two.pa')]
                source_records = []
                for index, path in enumerate(paths):
                    path = session.declare_file(path, 'solver_native_binary')
                    path.write_bytes(b'INERT_NOT_PA')
                    record = file_record(path, 'solver_native_binary')
                    session.add_input('fixture_'+str(index), record); source_records.append(record)
                target = work/'composed.pa'; audit_spec = work/'audit.lua'; audit_output = work/'audit.json'
                plan = SimpleNamespace(operations=[{'arguments':['--nogui','--noprompt','lua',
                    str(resources['audit_downstream_fields.lua']),str(audit_spec)], 'outputs':[str(audit_output)]}],
                    materializations={str(audit_spec):'return {}\n'})
                by_path = {row['path']:row for row in source_records}
                audit = _run_rebias_operations(session, reflectron_plan={'carrier_path':str(target),
                    'response_paths':[str(paths[1]),str(paths[2])]}, rebias_plan={'responses':[
                    {'coefficient':0.1},{'coefficient':-0.2}]}, rebias_base=paths[0], by_path=by_path,
                    copied=list(source_records), resources=resources, records=records, downstream_plan=plan,
                    limits={}, allow_asynchronous_io=None)
                return dict(status='success', summary={'fixture':'INERT_NOT_NATIVE_QUALIFICATION'},
                    output_paths=[str(target), audit['path']], required_output_paths=[str(target), audit['path']],
                    retention_preserve_paths=[], manifest_extra_fields={})
            original = RunSession.run_process
            def transport(session, operation_id, **kwargs):
                calls.append(operation_id)
                work = session.run_dir/'simion/rebias'
                if operation_id == 'compose_reflectron':
                    marker = 'MISSING' if fail_marker[0] else 'STANDALONE_PA_COMPOSITION=PASS'
                    code = f"from pathlib import Path;Path({str(work/'composed.pa')!r}).write_bytes(b'INERT_COMPOSED');print({marker!r})"
                else:
                    code = f"from pathlib import Path;Path({str(work/'audit.json')!r}).write_text('{{\"status\":\"success\"}}');print('DOWNSTREAM_NATIVE_AUDIT=PASS')"
                kwargs['arguments'] = ['-c', code]
                return original(session, operation_id, **kwargs)
            env = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                       MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ, env), patch.object(RunSession, 'run_process', new=transport):
                result = owner.run_managed_stage(context, descriptor=dict(project='instrument_assembly', mode='field', software=[]),
                    run_id='20261127_121010__test__python__store-rebias', payload={}, committed_new_bytes=8*1024*1024,
                    commitment_inputs=[file_record(budget,'required_evidence')],
                    retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert rebias integration'),
                    expected_operation_ids=['compose_reflectron','audit_rebiased_downstream'],
                    operation_dependencies={'audit_rebiased_downstream':['compose_reflectron']}, action=action,
                    action_record=file_record(Path(__file__),'required_evidence'), artifact_store=store,
                    completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
            self.assertEqual(result['status'], 'success')
            self.assertEqual(calls, ['compose_reflectron','audit_rebiased_downstream'])
            completion = json.loads((Path(result['run_directory'])/'results/execution_completion.json').read_text())
            self.assertEqual(len(completion['writer_completion']['resource_releases']), 2)
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0], 0)
            fail_marker[0] = True
            calls.clear()
            with patch.dict(os.environ, env), patch.object(RunSession, 'run_process', new=transport):
                with self.assertRaisesRegex(ValueError, 'composition completion marker'):
                    owner.run_managed_stage(context, descriptor=dict(project='instrument_assembly', mode='field', software=[]),
                        run_id='20261127_121011__test__python__store-rebias-failure', payload={},
                        committed_new_bytes=8*1024*1024, commitment_inputs=[file_record(budget,'required_evidence')],
                        retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert rebias failure'),
                        expected_operation_ids=['compose_reflectron','audit_rebiased_downstream'],
                        operation_dependencies={'audit_rebiased_downstream':['compose_reflectron']}, action=action,
                        action_record=file_record(Path(__file__),'required_evidence'), artifact_store=store,
                        completion_api=lambda:SimpleNamespace(recoverable_batch_logs=lambda _root:set()))
            self.assertEqual(calls, ['compose_reflectron'])
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0], 0)
