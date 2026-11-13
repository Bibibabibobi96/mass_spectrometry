"""Managed owner action-source freezing and stopped finalization."""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts import test_execution_runtime as fixture
from msplatform.execution import owner
from msplatform.io.manifest_records import file_record


def make_action(root, mutate=False):
    path = root / 'original_action.py'
    path.write_text("""from pathlib import Path
calls = []
def action(session):
    calls.append(session.run_id)
    MUTATION
    output = session.declare_file(session.result_dir / 'value.txt', 'required_evidence')
    output.write_text('result', encoding='utf-8')
    return dict(status='success', summary={}, output_paths=[str(output)], required_output_paths=[str(output)], retention_preserve_paths=[], manifest_extra_fields={})
""".replace('MUTATION', "Path(__file__).write_text('changed', encoding='utf-8')" if mutate else 'pass'), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('owned_test_action', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return path, module


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell execution required')
class OwnerActionFreezeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.helper = fixture.NormalOwnerTests()
        self.context = self.helper._context(self.root)
        self.policy = patch('msplatform.execution.capacity_admission._capacity_policy', return_value=self.helper._policy())
        self.policy.start()
        self.addCleanup(self.policy.stop)

    def prepared(self, mutate=False):
        source, module = make_action(self.root, mutate)
        args = self.helper._arguments(self.root, module.action)
        args['action_record'] = file_record(source, 'required_evidence')
        return source, module, args

    def test_frozen_entry_and_original_provenance(self):
        source, module, args = self.prepared()
        outcome = owner.run_managed_stage(self.context, **args)
        run = Path(outcome['run_directory'])
        request = json.loads((run / 'inputs/execution_request.json').read_text(encoding='utf-8'))
        frozen = request['prepared']['entrypoint']
        self.assertEqual(request['prepared']['source_entrypoint'], args['action_record'])
        self.assertEqual(Path(frozen['path']), run / 'inputs/owner/action.py')
        self.assertEqual(Path(frozen['path']).read_bytes(), source.read_bytes())
        manifest = json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['inputs']['owner_authority_0'], frozen)
        self.assertEqual(module.calls, [args['run_id']])

    def test_original_mutation_during_action_refuses_completion(self):
        _, module, args = self.prepared(mutate=True)
        with self.assertRaisesRegex(AssertionError, 'original action source after action'):
            owner.run_managed_stage(self.context, **args)
        self.assertEqual(module.calls, [args['run_id']])
        self.assertFalse(list((self.context.workspace / 'artifacts').rglob('execution_completion.json')))

    def test_resume_after_original_removed_and_copy_tamper_or_missing_refuses(self):
        for defect in ('none', 'tamper', 'missing'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                context = self.helper._context(root)
                source, module = make_action(root)
                args = self.helper._arguments(root, module.action)
                args['action_record'] = file_record(source, 'required_evidence')
                with patch('msplatform.execution.workflow_publication.publish_terminal_state', side_effect=OSError('PUBLICATION_FAULT')):
                    with self.assertRaisesRegex(OSError, 'PUBLICATION_FAULT'):
                        owner.run_managed_stage(context, **args)
                result_path = next((context.workspace / 'artifacts').rglob('result.json'))
                result = json.loads(result_path.read_text(encoding='utf-8'))
                self.assertTrue(result['writers_confirmed'])
                frozen = Path(result['run_directory']) / 'inputs/owner/action.py'
                source.unlink()
                if defect == 'tamper': frozen.write_text('tampered', encoding='utf-8')
                if defect == 'missing': frozen.unlink()
                if defect == 'none':
                    recovered = owner.resume_finalization(context, result_path)
                    self.assertEqual(recovered['status'], 'success')
                else:
                    with self.assertRaises(AssertionError): owner.resume_finalization(context, result_path)
                self.assertEqual(module.calls, [args['run_id']])

    def test_legacy_request_keeps_original_entrypoint_strict(self):
        from types import SimpleNamespace
        entry = self.root / 'legacy_action.py'
        entry.write_text('original', encoding='utf-8')
        record = file_record(entry, 'required_evidence')
        config = self.root / 'legacy_config.json'
        request_path = self.root / 'legacy_request.json'
        config.write_text('{}', encoding='utf-8')
        request_path.write_text('{}', encoding='utf-8')
        completion = {'execution_request': file_record(request_path, 'required_evidence'),
                      'run_config': file_record(config, 'required_evidence')}
        request = {'prepared': {'entrypoint': record}, 'capacity': {'commitment_inputs': []}}
        entry.write_text('changed', encoding='utf-8')
        with patch.object(owner, '_writer_completion'):
            with self.assertRaisesRegex(AssertionError, 'owner authority 0'):
                owner._publish(SimpleNamespace(artifact_run_dir=self.root), request, completion, None)

    def test_copy_failure_preserves_original_error_before_action(self):
        from msplatform.execution.completion import no_particle_batch_completion_api
        _, module, args = self.prepared()
        args['completion_api'] = no_particle_batch_completion_api
        with patch('msplatform.execution.inputs.freeze_file', side_effect=OSError('ACTION_COPY_FAILURE')):
            with self.assertRaisesRegex(OSError, 'ACTION_COPY_FAILURE') as caught:
                owner.run_managed_stage(self.context, **args)
        print('COPY_ERROR_NOTES', getattr(caught.exception, '__notes__', []))
        self.assertEqual(module.calls, [])
        result_path = next((self.context.workspace / 'artifacts').rglob('result.json'))
        result = json.loads(result_path.read_text(encoding='utf-8'))
        self.assertEqual((result['status'], result['stage']), ('failed', 'complete'))
        manifest = json.loads(Path(result['manifest']['path']).read_text(encoding='utf-8'))
        request = json.loads((Path(result['run_directory']) / 'inputs/execution_request.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['inputs']['owner_authority_0'], args['action_record'])
        self.assertEqual(request['prepared']['entrypoint'], args['action_record'])
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        self.assertEqual(load_capacity_protection_leases(self.context.workspace / 'artifacts')['audit'], [])

    def test_request_update_failure_preserves_original_and_releases(self):
        from msplatform.execution.completion import no_particle_batch_completion_api
        _, module, args = self.prepared()
        args['completion_api'] = no_particle_batch_completion_api
        write = owner.write_json_atomic
        def fail_update(path, value):
            if isinstance(value, dict) and 'source_entrypoint' in value.get('prepared', {}):
                raise OSError('ACTION_REQUEST_UPDATE_FAILURE')
            return write(path, value)
        with patch.object(owner, 'write_json_atomic', side_effect=fail_update):
            with self.assertRaisesRegex(OSError, 'ACTION_REQUEST_UPDATE_FAILURE') as caught:
                owner.run_managed_stage(self.context, **args)
        print('REQUEST_ERROR_NOTES', getattr(caught.exception, '__notes__', []))
        self.assertEqual(module.calls, [])
        result_path = next((self.context.workspace / 'artifacts').rglob('result.json'))
        result = json.loads(result_path.read_text(encoding='utf-8'))
        self.assertEqual((result['status'], result['stage']), ('failed', 'complete'))
        manifest = json.loads(Path(result['manifest']['path']).read_text(encoding='utf-8'))
        self.assertEqual(manifest['inputs']['owner_authority_0'], args['action_record'])
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        self.assertEqual(load_capacity_protection_leases(self.context.workspace / 'artifacts')['audit'], [])

    def test_request_update_after_replace_failure_binds_persisted_copy(self):
        from msplatform.execution.completion import no_particle_batch_completion_api
        _, module, args = self.prepared()
        args['completion_api'] = no_particle_batch_completion_api
        write = owner.write_json_atomic
        def fail_after_update(path, value):
            result = write(path, value)
            if isinstance(value, dict) and 'source_entrypoint' in value.get('prepared', {}):
                raise OSError('AFTER_REQUEST_REPLACE')
            return result
        with patch.object(owner, 'write_json_atomic', side_effect=fail_after_update):
            with self.assertRaisesRegex(OSError, 'AFTER_REQUEST_REPLACE'):
                owner.run_managed_stage(self.context, **args)
        self.assertEqual(module.calls, [])
        result_path = next((self.context.workspace / 'artifacts').rglob('result.json'))
        result = json.loads(result_path.read_text(encoding='utf-8'))
        self.assertEqual((result['status'], result['stage']), ('failed', 'complete'))
        run = Path(result['run_directory'])
        request = json.loads((run / 'inputs/execution_request.json').read_text(encoding='utf-8'))
        manifest = json.loads(Path(result['manifest']['path']).read_text(encoding='utf-8'))
        self.assertEqual(manifest['inputs']['owner_authority_0'], request['prepared']['entrypoint'])
        self.assertEqual(Path(request['prepared']['entrypoint']['path']), run / 'inputs/owner/action.py')
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        self.assertEqual(load_capacity_protection_leases(self.context.workspace / 'artifacts')['audit'], [])

    def test_callable_mismatch_remains_refused(self):
        _, module, args = self.prepared()
        other = self.root / 'other.py'
        other.write_text('unrelated', encoding='utf-8')
        args['action_record'] = file_record(other, 'required_evidence')
        with self.assertRaisesRegex(ValueError, 'callable source differs'):
            owner.run_managed_stage(self.context, **args)
        self.assertEqual(module.calls, [])
