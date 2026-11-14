"""Exercise recovery with real owner/receipts and an inert external launcher."""
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from common.contracts import test_execution_runtime as execution_fixture
from common.contracts import test_comsol_stationary_managed_failure as failure_fixture
from msplatform.backends.comsol import assembly_field_solution, native_execution
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.processes import ProcessExecutionError
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.artifacts import open_artifact


class StationaryRecoveryManagedTests(unittest.TestCase):
    @patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': ''})
    def test_failed_owner_output_recovers_and_tamper_refuses(self):
        with tempfile.TemporaryDirectory(prefix='stationary-recovery-owner-') as directory:
            root = Path(directory)
            helper = execution_fixture.NormalOwnerTests()
            capacity = root / 'capacity.json'
            capacity.write_text(json.dumps(helper._policy()), encoding='utf-8')
            context = replace(helper._context(root), capacity_policy_path=capacity,
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                tools={'comsol_launcher': Path(sys.executable), 'matlab_root': root})
            context.workspace.mkdir(parents=True)
            limits = {'wall_clock_seconds': 120, 'transient_run_directory_bytes': 64 * 1024**2,
                'process_tree_working_set_bytes': 1024**3, 'minimum_system_available_memory_bytes': 1,
                'compact_final_retained_bytes': 64 * 1024**2, 'automatic_retry_count': 0}
            retention = {'policy_version': 1, 'class': 'solver_review', 'reason': 'inert stationary recovery test'}
            policy = root / 'stages.json'
            stage = {'limits': limits, 'artifact_retention': retention}
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy',
                'stages': {'solve_assembly_stationary': stage, 'recover_assembly_stationary': stage}}), encoding='utf-8')
            context = replace(context, stage_policy_path=policy)
            args = helper._arguments(root, failure_fixture.source_action)
            args.update(retention=retention, run_id='20261114_130000__build__python__prepared-model',
                action_record=file_record(Path(failure_fixture.__file__), 'required_evidence'), completion_api=no_particle_batch_completion_api)
            made = run_managed_stage(context, **args)
            source = open_artifact({'manifest': made['manifest'], 'product_id': 'model'}, expected_kind='prepared_model')
            source_bytes = {key: source.data_path(key).read_bytes() for key in source.data_records}
            control = context.workspace / 'inert-control.json'
            control.write_text(json.dumps({'case': 'reopen_failure'}), encoding='utf-8')
            original = native_execution.freeze_native_sources
            def sources(session, names):
                _, records = original(session, names)
                target = session.declare_file(session.input_dir / 'native_sources/inert_stationary_launcher.ps1', 'required_evidence')
                freeze_file(Path(__file__).parent / 'test_support/assembly_stationary_recovery_launcher.ps1', target)
                record = file_record(target, 'required_evidence')
                session.add_input('inert_launcher', record)
                return target, [*records, record]
            original_run_process = RunSession.run_process
            def inert_transport(session, operation_id, **kwargs):
                self.assertEqual((kwargs['role'], kwargs['stage']), ('COMSOL', 'solver'))
                self.assertIn('inert_stationary_launcher.ps1', ' '.join(kwargs['arguments']))
                kwargs.update(role='GATE', stage='stationary_inert_transport')
                return original_run_process(session, operation_id, **kwargs)
            with (patch.object(native_execution, 'freeze_native_sources', side_effect=sources),
                  patch.object(RunSession, 'run_process', new=inert_transport)):
                with self.assertRaises(ProcessExecutionError):
                    assembly_field_solution.solve_stationary(source, solver_numerics={'kind': 'comsol_stationary_default'}, context=context)
                manifests = list((context.workspace / 'artifacts/projects/instrument_assembly/runs').glob('*assembly-field*/run_manifest.json'))
                self.assertEqual(len(manifests), 1)
                failed_path = manifests[0]
                failed_bytes = failed_path.read_bytes()
                failed = json.loads(failed_bytes)
                self.assertEqual(failed['status'], 'failed')
                outputs = {Path(record['path']).name: record for record in failed['outputs']}
                selected = outputs['assembly-stationary-field.mph']
                verify_record('actual failed output', selected)
                selected_path = Path(selected['path'])
                selected_bytes = selected_path.read_bytes()
                failed_record = file_record(failed_path, 'required_evidence')
                control.write_text(json.dumps({'case': 'recovery', 'borrowed_model': str(selected_path)}), encoding='utf-8')
                recovered = assembly_field_solution.recover_stationary(failed_record, selected_output=selected, context=context)
                self.assertEqual(recovered.kind, 'field_solution')
                self.assertEqual(recovered.data_path('model'), selected_path.resolve())
                self.assertEqual(recovered.data_path('model').read_bytes(), selected_bytes)
                recovered_manifest = json.loads(recovered.manifest_location.read_text(encoding='utf-8-sig'))
                row = json.loads(recovered.data_path('reopen_solution').read_text(encoding='utf-8-sig'))
                self.assertEqual((row['operation'], row['compute_calls']), ('recover', 0))
                self.assertEqual(recovered_manifest['status'], 'success')
                self.assertEqual(recovered_manifest['inputs']['borrowed_solution'], selected)
                completion = json.loads((recovered.manifest_location.parent / 'results/execution_completion.json').read_text(encoding='utf-8-sig'))
                self.assertEqual([v['operation_id'] for v in completion['writer_completion']['operations']], ['reopen_solution'])
                self.assertTrue(completion['writer_completion']['operations'][0]['observation']['exit_confirmed'])
                self.assertEqual(completion['writer_completion']['operations'][0]['observation']['returncode'], 0)
                self.assertIsNone(completion['writer_completion']['resource_releases'][0]['completion_receipt']['host_release']['error'])
                self.assertEqual(failed_path.read_bytes(), failed_bytes)
                self.assertEqual({key: source.data_path(key).read_bytes() for key in source.data_records}, source_bytes)
                selected_path.write_bytes(selected_bytes + b'tampered')
                try:
                    with patch.object(RunSession, 'run_process', side_effect=AssertionError('must not launch')) as launch:
                        with self.assertRaises(AssertionError):
                            assembly_field_solution.recover_stationary(failed_record, selected_output=selected, context=context)
                        launch.assert_not_called()
                finally:
                    selected_path.write_bytes(selected_bytes)

    @patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': ''})
    def test_reused_workpoint_failure_recovers_with_exact_mesh_and_voltages(self):
        with tempfile.TemporaryDirectory(prefix='stationary-recovery-owner-') as directory:
            root = Path(directory)
            helper = execution_fixture.NormalOwnerTests()
            capacity = root / 'capacity.json'
            capacity.write_text(json.dumps(helper._policy()), encoding='utf-8')
            context = replace(helper._context(root), capacity_policy_path=capacity,
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                tools={'comsol_launcher': Path(sys.executable), 'matlab_root': root})
            context.workspace.mkdir(parents=True)
            limits = {'wall_clock_seconds': 120, 'transient_run_directory_bytes': 64 * 1024**2,
                'process_tree_working_set_bytes': 1024**3, 'minimum_system_available_memory_bytes': 1,
                'compact_final_retained_bytes': 64 * 1024**2, 'automatic_retry_count': 0}
            retention = {'policy_version': 1, 'class': 'solver_review', 'reason': 'inert stationary recovery test'}
            policy = root / 'stages.json'
            stage = {'limits': limits, 'artifact_retention': retention}
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy',
                'stages': {'solve_assembly_stationary': stage, 'recover_assembly_stationary': stage}}), encoding='utf-8')
            context = replace(context, stage_policy_path=policy)
            args = helper._arguments(root, failure_fixture.source_action)
            args.update(retention=retention, run_id='20261114_130000__build__python__prepared-model',
                action_record=file_record(Path(failure_fixture.__file__), 'required_evidence'), completion_api=no_particle_batch_completion_api)
            made = run_managed_stage(context, **args)
            source = open_artifact({'manifest': made['manifest'], 'product_id': 'model'}, expected_kind='prepared_model')
            source_bytes = {key: source.data_path(key).read_bytes() for key in source.data_records}
            control = context.workspace / 'inert-control.json'
            control.write_text(json.dumps({'case': 'parent_success'}), encoding='utf-8')
            original = native_execution.freeze_native_sources
            def sources(session, names):
                _, records = original(session, names)
                target = session.declare_file(session.input_dir / 'native_sources/inert_stationary_launcher.ps1', 'required_evidence')
                freeze_file(Path(__file__).parent / 'test_support/assembly_stationary_recovery_launcher.ps1', target)
                record = file_record(target, 'required_evidence')
                session.add_input('inert_launcher', record)
                return target, [*records, record]
            original_run_process = RunSession.run_process
            def inert_transport(session, operation_id, **kwargs):
                self.assertEqual((kwargs['role'], kwargs['stage']), ('COMSOL', 'solver'))
                self.assertIn('inert_stationary_launcher.ps1', ' '.join(kwargs['arguments']))
                kwargs.update(role='GATE', stage='stationary_inert_transport')
                return original_run_process(session, operation_id, **kwargs)
            with (patch.object(native_execution, 'freeze_native_sources', side_effect=sources),
                  patch.object(RunSession, 'run_process', new=inert_transport)):
                parent = assembly_field_solution.solve_stationary(source, solver_numerics={'kind':'comsol_stationary_default'}, context=context)
                old_request = json.loads(parent.data_path('request').read_text(encoding='utf-8-sig'))
                new_request = json.loads(json.dumps(old_request))
                new_request['group_voltages'][0]['voltage_v'] = 18.0
                parent_bytes = parent.data_path('model').read_bytes()
                control.write_text(json.dumps({'case':'reuse_success'}),encoding='utf-8')
                normal=assembly_field_solution.solve_stationary(parent,solver_numerics={'kind':'comsol_stationary_default'},request=new_request,context=context)
                self.assertEqual(normal.data_path('prepared_manifest'),source.manifest_location)
                normal_manifest=json.loads(normal.manifest_location.read_text(encoding='utf-8-sig'))
                bound=normal_manifest['inputs']['upstream_prepared_manifest']
                self.assertTrue(Path(bound['path']).is_absolute())
                self.assertEqual(normal_manifest['products']['solution']['data']['prepared_manifest'],bound)
                self.assertEqual(parent.data_path('model').read_bytes(),parent_bytes)
                control.write_text(json.dumps({'case':'reuse_reopen_failure'}),encoding='utf-8')
                with self.assertRaises(ProcessExecutionError):
                    assembly_field_solution.solve_stationary(parent,solver_numerics={'kind':'comsol_stationary_default'},request=new_request,context=context)
                manifests=list((context.workspace/'artifacts/projects/instrument_assembly/runs').glob('*assembly-field*/run_manifest.json'))
                failed_paths=[path for path in manifests if json.loads(path.read_text(encoding='utf-8-sig'))['status']=='failed']
                self.assertEqual(len(failed_paths),1);failed_path=failed_paths[0];failed_bytes=failed_path.read_bytes()
                failed=json.loads(failed_bytes);outputs={Path(record['path']).name:record for record in failed['outputs']}
                self.assertIn('solve_stationary.json',outputs)
                failed_record=file_record(failed_path,'required_evidence')
                for name in ('assembly-stationary-field.mph','assembly-stationary-computed-raw.mph'):
                    selected=outputs[name];verify_record('failed selected output',selected);selected_path=Path(selected['path']);selected_bytes=selected_path.read_bytes()
                    control.write_text(json.dumps({'case':'reuse_recovery','borrowed_model':str(selected_path)}),encoding='utf-8')
                    recovered=assembly_field_solution.recover_stationary(failed_record,selected_output=selected,context=context)
                    self.assertEqual(recovered.data_path('model'),selected_path.resolve())
                    self.assertEqual(json.loads(recovered.data_path('request').read_text(encoding='utf-8-sig')),new_request)
                    self.assertEqual(recovered.data_path('prepared_manifest'),source.manifest_location)
                    self.assertEqual(selected_path.read_bytes(),selected_bytes)
                for case in ('reuse_recovery_bad_mesh','reuse_recovery_bad_voltage'):
                    selected=outputs['assembly-stationary-field.mph'];control.write_text(json.dumps({'case':case,'borrowed_model':selected['path']}),encoding='utf-8')
                    with self.subTest(case=case),self.assertRaises(ValueError):
                        assembly_field_solution.recover_stationary(failed_record,selected_output=selected,context=context)
                self.assertEqual(failed_path.read_bytes(),failed_bytes)
                self.assertEqual(parent.data_path('model').read_bytes(),parent_bytes)
                self.assertEqual({key:source.data_path(key).read_bytes() for key in source.data_records},source_bytes)
