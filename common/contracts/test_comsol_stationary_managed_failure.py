"""Inert native process; exercise real managed failure evidence publication."""
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from common.contracts import test_execution_runtime as execution_fixture
from common.contracts import test_comsol_assembly_electrostatic_model_managed as model_fixture
from msplatform.backends.comsol import assembly_field_solution, native_execution
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.inputs import freeze_file
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.processes import ProcessExecutionError
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record, verify_record
from msplatform.results.artifacts import open_artifact


def source_action(session):
    values = dict(model='inert prepared model', request=model_fixture.REQUEST,
                  projection=model_fixture.PROJECTION, descriptor={}, geometry_validation={},
                  reopen_geometry=model_fixture.BASELINE, build_model={}, reopen_model={})
    records = {}
    for name, value in values.items():
        role = 'solver_native_binary' if name == 'model' else 'required_evidence'
        path = session.declare_file(session.result_dir / (name + ('.mph' if name == 'model' else '.json')), role)
        path.write_text(value if name == 'model' else json.dumps(value), encoding='utf-8')
        records[name] = file_record(path, role)
    paths = [record['path'] for record in records.values()]
    product = dict(schema_version=1, kind='prepared_model', status='complete',
                   metadata=dict(backend='comsol', scope='assembly_electrostatic_unsolved',
                                 field_status='not_solved', native_reopen_verified=True), data=records)
    return dict(status='success', summary={'synthetic': True}, output_paths=paths,
                required_output_paths=paths, retention_preserve_paths=[],
                manifest_extra_fields={'products': {'model': product}})


class StationaryManagedFailureTests(unittest.TestCase):
    @patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': ''})
    def test_failed_compute_and_cold_reopen_preserve_actual_outputs(self):
        for case in ('compute_failure', 'reopen_failure'):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix='stationary-owner-') as directory:
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
                retention = {'policy_version': 1, 'class': 'solver_review', 'reason': 'inert stationary failure test'}
                policy = root / 'stages.json'
                policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy',
                    'stages': {'solve_assembly_stationary': {'limits': limits, 'artifact_retention': retention}}}), encoding='utf-8')
                context = replace(context, stage_policy_path=policy)
                args = helper._arguments(root, source_action)
                args.update(retention=retention, run_id='20261114_130000__build__python__prepared-model',
                    action_record=file_record(Path(__file__), 'required_evidence'), completion_api=no_particle_batch_completion_api)
                made = run_managed_stage(context, **args)
                source = open_artifact({'manifest': made['manifest'], 'product_id': 'model'}, expected_kind='prepared_model')
                source_bytes = {key: source.data_path(key).read_bytes() for key in source.data_records}
                (context.workspace / 'inert-control.json').write_text(json.dumps({'case': case}), encoding='utf-8')
                original = native_execution.freeze_native_sources
                def sources(session, names):
                    _, records = original(session, names)
                    target = session.declare_file(session.input_dir / 'native_sources/inert_stationary_launcher.ps1', 'required_evidence')
                    freeze_file(Path(__file__).parent / 'test_support/assembly_stationary_failure_launcher.ps1', target)
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
                    with self.assertRaises(ProcessExecutionError) as caught:
                        assembly_field_solution.solve_stationary(source, solver_numerics={'kind': 'comsol_stationary_default'}, context=context)
                self.assertIn('23', str(caught.exception))
                manifests = list((context.workspace / 'artifacts/projects/instrument_assembly/runs').glob('*assembly-field*/run_manifest.json'))
                self.assertEqual(len(manifests), 1)
                manifest = json.loads(manifests[0].read_text(encoding='utf-8-sig'))
                self.assertEqual(manifest['status'], 'failed')
                self.assertNotIn('solution', manifest.get('products', {}))
                completion = json.loads((manifests[0].parent / 'results/execution_completion.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(completion['status'], 'failed')
                self.assertEqual(completion['exception']['message'], str(caught.exception))
                names = {Path(value).name for value in completion['output_paths']}
                expected = {'assembly-stationary-computed-raw.mph'}
                if case == 'reopen_failure':
                    expected.add('assembly-stationary-field.mph')
                    expected.add('solve_stationary.json')
                self.assertEqual(names, expected)
                outputs = {Path(record['path']).name: record for record in manifest['outputs']}
                for name in expected:
                    verify_record(name, outputs[name], base_dir=manifests[0].parent)
                operations = completion['writer_completion']['operations']
                self.assertEqual([item['operation_id'] for item in operations],
                    ['solve_stationary'] if case == 'compute_failure' else ['solve_stationary', 'reopen_solution'])
                self.assertTrue(all(item['observation']['exit_confirmed'] for item in operations))
                releases = completion['writer_completion']['resource_releases']
                self.assertEqual(len(releases), len(operations))
                self.assertEqual(operations[-1]['observation']['returncode'], 23)
                for item in releases:
                    self.assertIsNone(item['completion_receipt']['host_release']['error'])
                self.assertEqual({key: source.data_path(key).read_bytes() for key in source.data_records}, source_bytes)
