"""Owner's explicit stopped failure recovery never invokes a native action."""
import json
import sqlite3
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.execution import owner
from msplatform.io.manifest_records import file_record


class FailedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.root = self.workspace / 'artifacts/assemblies/instrument_assembly/runs/test-run'
        for name in ('inputs/owner', 'logs', 'results'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.result_path = self.workspace / 'result.json'
        self.context = SimpleNamespace(workspace=self.workspace, host_state_path=self.workspace/'host.sqlite',
                                       execution_root=self.root.parent)
        with sqlite3.connect(self.context.host_state_path) as db:
            db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY, document TEXT)')
            db.execute('INSERT INTO state VALUES (1, ?)', (json.dumps({'schema_version': 1, 'records': []}),))
        self.action = self.root/'inputs/owner/action.py'
        self.action.write_text('frozen', encoding='utf-8')
        self.source = self.workspace/'source.py'
        self.source.write_text('frozen', encoding='utf-8')
        action = file_record(self.action, 'required_evidence')
        live = file_record(self.source, 'required_evidence')
        self.source.write_text('changed', encoding='utf-8')
        self.capacity = {'status': 'active', 'owner': 'run-artifact-workflow:instrument_assembly:test-run',
                         'artifact_root': str(self.workspace/'artifacts'), 'lease_id': 'lease'}
        self.request = {'role': 'run_artifact_workflow_request', 'package': {'run_id': 'test-run',
            'project': 'instrument_assembly', 'mode': 'pulse_basis_recovery'},
            'payload': {'action': 'recover_assembly_pulse_basis'}, 'expected_operation_ids': ['reopen_pulse_basis'],
            'operation_dependencies': {}, 'prepared': {'entrypoint': action, 'source_entrypoint': live},
            'capacity': {'commitment_inputs': []}, 'paths': {'artifact_root': str(self.workspace/'artifacts'),
                'host_resource_state_path': str(self.context.host_state_path), 'execution_root': str(self.context.execution_root)}}
        self.result = {'role': 'run_artifact_workflow_result', 'status': 'failed', 'stage': 'finalization',
            'writers_confirmed': True, 'resume_action': 'inspect_writer_completion', 'run_directory': str(self.root),
            'execution_request': str(self.root/'inputs/execution_request.json'), 'capacity_session': self.capacity,
            'exception': {'type': 'ProcessExecutionError', 'message': 'exit 1',
                          'notes': ['original action source after action changed']}}
        self.process = {'error': None, 'observation': {'exit_code': 1, 'root_process_id': 21,
            'root_process_started_at_utc_ticks': 123}, 'host_release': {'inherited': False, 'token': 'token',
            'error': None, 'result': {'status': 'released', 'token': 'token'}}}
        self.launcher = {'role': 'comsol_launcher_completion', 'run_id': 'test-run',
            'host_release': {'inherited': True, 'token': 'token', 'error': None},
            'runtime_storage': {'run_directory': str(self.root/'comsol_runtime/reopen_pulse_basis')},
            'operations': [{'operation_id': 'launcher-attempt-1', 'observation': {'exit_confirmed': True,
                'returncode': 0, 'process_id': 22, 'process_started_at_utc_ticks': 124}}]}
        self._write(self.root/'inputs/execution_request.json', self.request)
        self._write(self.root/'run_config.json', {'run_id': 'test-run', 'inputs': {'execution_request': str(self.root/'inputs/execution_request.json'),
                                                                                     'owner_authority_0': str(self.action)}})
        self._write(self.root/'logs/capacity_session.json', self.capacity)
        self._write(self.root/'logs/operation_0001.process.json', self.process)
        self._write(self.root/'logs/reopen_pulse_basis.launcher.json', self.launcher)
        self._write(self.result_path, self.result)

    @staticmethod
    def _write(path, data):
        path.write_text(json.dumps(data), encoding='utf-8')

    def arguments(self):
        paths = {'result': self.result_path, 'request': self.root/'inputs/execution_request.json',
                 'run_config': self.root/'run_config.json', 'frozen_action': self.action,
                 'process': self.root/'logs/operation_0001.process.json', 'launcher': self.root/'logs/reopen_pulse_basis.launcher.json'}
        evidence = {name: file_record(path, 'required_evidence') for name, path in paths.items()}
        evidence['role_authority'] = {'version': 1, 'frozen_action_sha256': self.request['prepared']['entrypoint']['sha256'],
                                      'basis': 'reviewed_frozen_action_declarations_and_run_config'}
        roles = {str(path.resolve()): 'required_evidence' for path in self.root.rglob('*') if path.is_file()}
        return dict(explicit_file_roles=roles, role_evidence=evidence)

    def invoke(self, **arguments):
        with patch.object(owner, '_require_capacity_accounted'), patch.object(owner, '_finalize', side_effect=lambda s, r, c, **k: c):
            return owner.recover_failed_finalization(self.context, self.result_path, **arguments)

    def test_observed_failed_exit_becomes_failed_completion_without_action(self):
        result = self.invoke(**self.arguments())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['manifest_extra_fields'], {})
        self.assertEqual(result['writer_completion']['operations'][0]['observation']['returncode'], 1)
        self.assertIn('original action source', result['exception']['notes'][0])

    def test_missing_forged_and_unclassified_evidence_fails_closed(self):
        for case in ('missing', 'forged', 'unknown', 'role', 'duplicate_process', 'bad_token', 'unknown_pid'):
            with self.subTest(case=case):
                args = self.arguments()
                if case == 'missing': del args['role_evidence']['process']
                if case == 'forged': args['role_evidence']['process']['sha256'] = '0'*64
                if case == 'unknown': (self.root/'unknown.dat').write_text('unknown', encoding='utf-8')
                if case == 'role': args['explicit_file_roles'].pop(str(self.action.resolve()))
                if case == 'duplicate_process': (self.root/'logs/operation_0002.process.json').write_text('{}', encoding='utf-8')
                if case in ('bad_token', 'unknown_pid'):
                    path = self.root/'logs/operation_0001.process.json'
                    altered = json.loads(path.read_text(encoding='utf-8'))
                    if case == 'bad_token': altered['host_release']['token'] = 'wrong'
                    else: altered['observation']['root_process_id'] = 0
                    self._write(path, altered)
                    args['role_evidence']['process'] = file_record(path, 'required_evidence')
                with self.assertRaises((ValueError, AssertionError)):
                    self.invoke(**args)
                if case == 'unknown': (self.root/'unknown.dat').unlink()
                if case == 'duplicate_process': (self.root/'logs/operation_0002.process.json').unlink()
                if case in ('bad_token', 'unknown_pid'): self._write(self.root/'logs/operation_0001.process.json', self.process)


if __name__ == '__main__':
    unittest.main()
