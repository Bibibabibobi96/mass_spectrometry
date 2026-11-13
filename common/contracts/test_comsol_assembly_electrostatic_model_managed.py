"""Queued managed-owner fixture. Synthetic native child; never a field qualification."""
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from common.contracts import test_execution_runtime as execution_fixture
from msplatform.backends.comsol import assembly_electrostatic_model as subject
from msplatform.backends.comsol import native_execution
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.run_session import RunSession
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.inputs import freeze_file
from msplatform.execution.processes import ProcessExecutionError
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact

PROJECTION = {'electrode_groups': [{'instance_id': 'rf', 'electrode_group_id': 'drive'}]}
BASELINE = {'group_keys': ['rf/drive'], 'group_faces': [[2, 3]], 'vacuum_domains': [1], 'outer_faces': [4, 5]}
REQUEST = {'group_voltages': [{'instance_id': 'rf', 'electrode_group_id': 'drive', 'voltage_v': 17.0}], 'relative_permittivity': 1.0, 'exterior': {'kind': 'potential', 'voltage_v': 0.0}, 'mesh': {'global_automatic_level': 5, 'electrode_hmax_mm': 4.0}, 'study': {'kind': 'stationary'}}

def source_action(session):
    values = {'projection': PROJECTION, 'geometry_validation': {}, 'model': 'synthetic source MPH', 'descriptor': {}, 'build_geometry': BASELINE, 'reopen_geometry': BASELINE}
    records = {}
    for name, value in values.items():
        target = session.declare_file(session.result_dir / (name + ('.mph' if name == 'model' else '.json')), 'solver_native_binary' if name == 'model' else 'required_evidence')
        target.write_text(value if name == 'model' else json.dumps(value), encoding='utf-8')
        records[name] = file_record(target, 'solver_native_binary' if name == 'model' else 'required_evidence')
    paths = [str(session.result_dir / (name + ('.mph' if name == 'model' else '.json'))) for name in values]
    return dict(status='success', summary={'synthetic': True}, output_paths=paths, required_output_paths=paths, retention_preserve_paths=[], manifest_extra_fields={'products': {'geometry': {'schema_version': 1, 'kind': 'geometry_artifact', 'status': 'complete', 'metadata': {'backend': 'comsol', 'scope': 'geometry_only', 'native_reopen_verified': True}, 'data': records}}})

class ManagedSyntheticModelTests(unittest.TestCase):
    @patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': ''})
    def test_managed_owner_and_failure_order(self):
        for case in ('success', 'source_tamper', 'model_tamper', 'process_failure'):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix='assembly-model-managed-') as directory:
                root = Path(directory)
                helper = execution_fixture.NormalOwnerTests()
                cap = root / 'capacity.json'
                cap.write_text(json.dumps(helper._policy()), encoding='utf-8')
                context = replace(helper._context(root), capacity_policy_path=cap, host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']), tools={'comsol_launcher': Path(sys.executable), 'matlab_root': root})
                context.workspace.mkdir(parents=True)
                policy = root / 'stages.json'
                limits = {'wall_clock_seconds': 120, 'transient_run_directory_bytes': 64 * 1024**2, 'process_tree_working_set_bytes': 1024**3, 'minimum_system_available_memory_bytes': 1, 'compact_final_retained_bytes': 64 * 1024**2, 'automatic_retry_count': 0}
                retention = {'policy_version': 1, 'class': 'solver_review', 'reason': 'synthetic managed COMSOL transport test'}
                policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy', 'stages': {'prepare_assembly_electrostatic_model': {'limits': limits, 'artifact_retention': retention}}}), encoding='utf-8')
                context = replace(context, stage_policy_path=policy)
                args = helper._arguments(root, source_action)
                args.update(retention=retention, run_id='20261114_120000__build__python__synthetic-geometry', action_record=file_record(Path(__file__), 'required_evidence'), completion_api=no_particle_batch_completion_api)
                source_result = run_managed_stage(context, **args)
                geometry = open_artifact({'manifest': source_result['manifest'], 'product_id': 'geometry'}, expected_kind='geometry_artifact')
                original_model = geometry.data_path('model').read_bytes()
                control = {'case': case, 'source_path': str(geometry.data_path('model'))}
                (context.workspace / 'inert-control.json').write_text(json.dumps(control), encoding='utf-8')
                def sources(session, names):
                    launcher, records = native_execution.freeze_native_sources(session, names)
                    target = session.declare_file(session.input_dir / 'native_sources/inert_model_launcher.ps1', 'required_evidence')
                    freeze_file(Path(__file__).parent / 'test_support/assembly_electrostatic_model_launcher.ps1', target)
                    record = file_record(target, 'required_evidence')
                    session.add_input('inert_launcher', record)
                    return target, [*records, record]
                original_run_process = RunSession.run_process
                def inert_transport(session, operation_id, **kwargs):
                    self.assertIn(operation_id, ('build_model', 'reopen_model'))
                    self.assertEqual((kwargs['role'], kwargs['stage']), ('COMSOL', 'solver'))
                    self.assertEqual(Path(kwargs['executable']), session.context.powershell_executable)
                    arguments = kwargs['arguments']
                    self.assertEqual(arguments[:2], ['-NoProfile', '-File'])
                    launcher = Path(arguments[2])
                    self.assertEqual(launcher.resolve(), (session.input_dir / 'native_sources/inert_model_launcher.ps1').resolve())
                    self.assertEqual(launcher.read_bytes(), (Path(__file__).parent / 'test_support/assembly_electrostatic_model_launcher.ps1').read_bytes())
                    kwargs.update(role='GATE', stage='assembly_model_inert_transport')
                    return original_run_process(session, operation_id, **kwargs)
                with (patch.object(subject, 'freeze_native_sources', side_effect=sources),
                      patch.object(RunSession, 'run_process', new=inert_transport)):
                    if case == 'success':
                        product = subject.prepare_model(geometry, request=REQUEST, context=context)
                        self.assertEqual(product.metadata['field_status'], 'not_solved')
                        self.assertIn('geometry_validation', product.data_records)
                        self.assertIn('reopen_geometry', product.data_records)
                        self.assertEqual(json.loads(product.data_path('reopen_geometry').read_text(encoding='utf-8')), BASELINE)
                        self.assertEqual(product.data_path('geometry_validation').read_text(encoding='utf-8'), '{}')
                        self.assertFalse((product.manifest_location.parent / 'inputs/geometry/model.mph').exists())
                        self.assertEqual(product.data_records['geometry_manifest'], geometry.reference['manifest'])
                        self.assertNotIn(geometry.data_path('model').resolve(), [p.resolve() for p in product.data_locations.values()])
                        self.assertEqual(product.data_path('model').read_bytes(), b'SYNTHETIC_NOT_A_COMSOL_MODEL')
                        manifest = json.loads(product.manifest_location.read_text(encoding='utf-8-sig'))
                        completion = json.loads((product.manifest_location.parent / 'results/execution_completion.json').read_text(encoding='utf-8-sig'))
                        self.assertEqual([x['operation_id'] for x in completion['writer_completion']['operations']], ['build_model', 'reopen_model'])
                    else:
                        with self.assertRaises(ProcessExecutionError if case == 'process_failure' else (AssertionError, ProcessExecutionError)) as caught:
                            subject.prepare_model(geometry, request=REQUEST, context=context)
                        self.assertRegex(str(caught.exception), '23' if case == 'process_failure' else '(?i)(changed|immutable|denied|access|exit)')
                        manifests = list((context.workspace / 'artifacts/projects/instrument_assembly/runs').glob('*assembly-model*/run_manifest.json'))
                        self.assertEqual(len(manifests), 1)
                        manifest = json.loads(manifests[0].read_text(encoding='utf-8-sig'))
                        self.assertEqual(manifest['status'], 'failed')
                        self.assertNotIn('model', manifest.get('products', {}))
                        completion = json.loads((manifests[0].parent / 'results/execution_completion.json').read_text(encoding='utf-8-sig'))
                        operations = [x['operation_id'] for x in completion['writer_completion']['operations']]
                        self.assertEqual(operations, ['build_model', 'reopen_model'] if case == 'model_tamper' else ['build_model'])
                self.assertEqual(geometry.data_path('model').read_bytes(), original_model)

if __name__ == '__main__':
    unittest.main()
