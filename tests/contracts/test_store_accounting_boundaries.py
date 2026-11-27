"""Store reservation accounting at real execution and alias boundaries."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.context import ExecutionContext
from msplatform.execution.owner import run_managed_stage, store_growth_accountant
from msplatform.execution.resources import resource_path
from msplatform.execution.run_paths import create_execution_alias, remove_execution_alias
from msplatform.io.manifest_records import file_record
from msplatform.storage.store import ArtifactStore


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows execution alias required')
class StoreAccountingBoundaryTests(unittest.TestCase):
    def test_status_and_control_cleanup_never_replace_original_error(self):
        from contextlib import contextmanager
        from msplatform.execution.owner import standalone_native_store
        with tempfile.TemporaryDirectory(prefix='store-owner-errors-') as directory:
            store = ArtifactStore(Path(directory) / 'store')
            original = OSError('original action failure')
            with patch.object(store, 'finish_run', side_effect=OSError('status write failed')):
                with self.assertRaises(OSError) as caught:
                    with standalone_native_store(store, task_key='failure', budget=1000):
                        raise original
            self.assertIs(caught.exception, original)
            self.assertTrue(any('status write failed' in note for note in original.__notes__))
            original = OSError('another action failure')
            reserve = store.reserve
            @contextmanager
            def faulty_reservation(size):
                with reserve(size) as token:
                    try:
                        yield token
                    finally:
                        raise OSError('reservation close failed')
            with patch.object(store, 'reserve', side_effect=faulty_reservation):
                with self.assertRaises(OSError) as caught:
                    with standalone_native_store(store, task_key='cleanup', budget=1000):
                        raise original
            self.assertIs(caught.exception, original)
            self.assertTrue(any('reservation close failed' in note for note in original.__notes__))

    def test_accounting_failure_does_not_replace_action_failure(self):
        from types import SimpleNamespace
        from msplatform.execution.run_session import RunSession
        original = OSError('original action failure')
        accounting = OSError('accounting failure')
        def fail(_path):
            raise accounting
        session = SimpleNamespace(_store_managed=True, _store_stage_directory=Path.cwd(), _store_account=fail)
        RunSession._account_store_growth(session, original)
        self.assertIn('accounting failure', original.__notes__[0])
        with self.assertRaises(OSError) as caught:
            RunSession._account_store_growth(session, None)
        self.assertIs(caught.exception, accounting)

    def context(self, root):
        return ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh')), tools={}, execution_root=root / 'aliases',
            host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
            policy_path=resource_path('host_resource_policy.json'))

    def test_real_execution_alias_is_charged_once(self):
        with tempfile.TemporaryDirectory(prefix='store-account-alias-') as directory:
            root = Path(directory)
            store = ArtifactStore(root / 'store')
            work = store.new_work()
            run = work / 'run'; run.mkdir()
            context = self.context(root)
            alias = Path(create_execution_alias(context, run)['execution_alias'])
            try:
                with store.reserve(1024) as reservation:
                    account = store_growth_accountant(store, reservation, 1024, work)
                    (alias / 'data').write_bytes(b'x' * 73)
                    account(alias)
                    account(run)
                    with store._db() as db:
                        self.assertEqual(db.execute('SELECT remaining FROM reservations WHERE id=?', (reservation,)).fetchone()[0], 951)
                    with (run / 'data').open('ab') as stream:
                        stream.write(b'y' * 5)
                    account(alias)
                    with store._db() as db:
                        self.assertEqual(db.execute('SELECT remaining FROM reservations WHERE id=?', (reservation,)).fetchone()[0], 946)
            finally:
                remove_execution_alias(context, alias, run)

    def test_two_process_boundaries_preserve_other_reservation(self):
        from msplatform.backends.simion import native_completion
        from msplatform.execution.processes import ProcessExecutionError
        with tempfile.TemporaryDirectory(prefix='store-account-worker-') as directory:
            root = Path(directory)
            store = ArtifactStore(root / 'store')
            context = self.context(root)
            authority = root / 'budget.json'; authority.write_text('{}', encoding='utf-8')
            observations = []
            with store.reserve(100000) as other:
                def action(session):
                    token = session.capacity_session['lease_id']
                    with store._db() as db:
                        initial = db.execute('SELECT remaining FROM reservations WHERE id=?', (token,)).fetchone()[0]
                    for index, amount in enumerate((8000, 12000), start=1):
                        output = session.declare_file(session.result_dir / f'output{index}.bin', 'solver_native_binary')
                        script = 'from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b"x"*int(sys.argv[2])); sys.exit(int(sys.argv[3]))'
                        arguments = ['-c', script, str(output), str(amount), str(7 if index == 2 else 0)]
                        if index == 2:
                            with self.assertRaises(ProcessExecutionError):
                                session.run_process(f'write{index}', executable=Path(sys.executable),
                                    arguments=arguments, role='GATE', stage='store_fixture', limits=None)
                        else:
                            session.run_process(f'write{index}', executable=Path(sys.executable),
                                arguments=arguments, role='GATE', stage='store_fixture', limits=None)
                        with store._db() as db:
                            observations.append((db.execute('SELECT remaining FROM reservations WHERE id=?', (token,)).fetchone()[0],
                                db.execute('SELECT remaining FROM reservations WHERE id=?', (other,)).fetchone()[0]))
                    self.assertGreater(initial, observations[0][0])
                    self.assertGreater(observations[0][0], observations[1][0])
                    self.assertEqual([value[1] for value in observations], [100000, 100000])
                    outputs = [str(session.result_dir / f'output{i}.bin') for i in (1, 2)]
                    return dict(status='failed', summary={}, output_paths=outputs, required_output_paths=outputs,
                                retention_preserve_paths=[], manifest_extra_fields={})
                with patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': ''}):
                    result = run_managed_stage(context, descriptor={'project': 'instrument_assembly', 'mode': 'test', 'software': []},
                        run_id='20261127_170000__test__python__account', payload={}, committed_new_bytes=1000000,
                        commitment_inputs=[file_record(authority, 'required_evidence')],
                        retention={'policy_version': 1, 'class': 'solver_review', 'reason': 'inert worker fixture'},
                        expected_operation_ids=['write1', 'write2'], operation_dependencies={'write2': ['write1']},
                        action=action, action_record=file_record(Path(__file__), 'required_evidence'),
                        completion_api=lambda: native_completion, artifact_store=store)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(store.run_status(result['store_run_id'])['execution_status'], 'failed')
