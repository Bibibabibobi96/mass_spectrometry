"""Software tests for the actual Assembly geometry stage; no COMSOL launch."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform import assembly, components, examples
from msplatform.backends.comsol import geometry_execution as subject


def real_assembly():
    case = examples.load_example('rf_oatof_functional_v1')
    parts = {key: components.resolve_component(value) for key, value in case.component_requests.items()}
    return assembly.assemble(case.recipe, parts)


class ComsolAssemblyGeometryExecutionTests(unittest.TestCase):
    def test_public_stage_freezes_complete_projection_and_uses_existing_owner(self):
        instrument = real_assembly()
        before = instrument.composition_plan
        with TemporaryDirectory() as folder:
            root = Path(folder)
            launcher = root / 'comsol.exe'
            launcher.write_bytes(b'fixture executable')
            context = SimpleNamespace(tools={'comsol_launcher': launcher, 'matlab_root': root})
            policy = {'limits': {'transient_run_directory_bytes': 1}, 'artifact_retention': {}}
            with patch.object(subject, 'read_stage_policy', return_value=(policy, {'identity': 'policy'})), \
                 patch.object(subject, 'run_managed_stage', return_value={'manifest': {'identity': 'manifest'}}) as owner, \
                 patch.object(subject, 'open_artifact', return_value='opened') as reader:
                output = subject.build_geometry(instrument, outer_box_mm={'min': [-1000]*3, 'max': [1000]*3},
                    geometry_validation={'position_mm': 1e-6, 'normal_abs': 1e-9}, context=context)
            self.assertEqual(output, 'opened')
            self.assertEqual(instrument.composition_plan, before)
            call = owner.call_args.kwargs
            self.assertEqual(call['expected_operation_ids'], ('build_geometry', 'reopen_geometry'))
            self.assertEqual(call['operation_dependencies'], {'reopen_geometry': ['build_geometry']})
            self.assertEqual(call['payload']['geometry_validation'], {'position_mm': 1e-6, 'normal_abs': 1e-9})
            projection = call['payload']['projection']
            self.assertEqual(len(projection['members']), 77)
            self.assertEqual(len(projection['electrode_groups']), 50)
            reader.assert_called_once_with({'manifest': {'identity': 'manifest'}, 'product_id': 'geometry'},
                                           expected_kind='geometry_artifact')

    def test_box_and_sanity_errors_precede_owner(self):
        instrument = real_assembly()
        with patch.object(subject, 'run_managed_stage') as owner:
            with self.assertRaises(ValueError):
                subject.build_geometry(instrument, outer_box_mm={'min': [0]*3, 'max': [1]*3},
                    geometry_validation={'position_mm': 0, 'normal_abs': 0}, context=None)
            with self.assertRaises(ValueError):
                subject.build_geometry(instrument, outer_box_mm={'min': [-1000]*3, 'max': [1000]*3},
                    geometry_validation={'position_mm': float('nan'), 'normal_abs': 0}, context=None)
            owner.assert_not_called()

    def test_report_identity_and_physics_fail_closed(self):
        projection = {'members': [{'member_id': 'a'}], 'electrode_groups': [
            {'instance_id': 'one', 'electrode_group_id': 'g', 'member_ids': ['a']}]}
        row = {'scope': 'geometry_only', 'operation': 'build', 'member_count': 1, 'group_count': 1,
               'group_keys': ['one/g'], 'model_path': str(Path.cwd() / 'model.mph'), 'geometry_domains': 1,
               'physics_count': 0, 'mesh_count': 0, 'study_count': 0, 'solver_count': 0,
               'group_faces': [[1, 2]], 'vacuum_domains': [1], 'outer_faces': [3]}
        subject._check_report(row, 'build', projection, Path(row['model_path']))
        for key, value in [('member_count', 2), ('group_keys', ['wrong/g']), ('mesh_count', 1),
                           ('group_faces', [[]]), ('outer_faces', [])]:
            bad = copy.deepcopy(row)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                subject._check_report(bad, 'build', projection, Path(row['model_path']))

    def test_native_launcher_failure_preserves_primary_error(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('inputs', 'results', 'logs'):
                (root / name).mkdir()
            launcher = root / 'native' / 'launcher' / 'run.ps1'
            launcher.parent.mkdir(parents=True)
            launcher.write_text('fixture', encoding='utf-8')
            comsol = root / 'comsol.exe'
            comsol.write_bytes(b'fixture')
            context = SimpleNamespace(workspace=root, python_executable=root / 'python.exe',
                host_state_path=root / 'host.sqlite', policy_path=root / 'policy.json',
                tools={'comsol_launcher': comsol, 'matlab_root': root}, powershell_executable=root / 'pwsh.exe')
            session = SimpleNamespace(expected_operation_ids=('build_geometry', 'reopen_geometry'),
                input_dir=root / 'inputs', result_dir=root / 'results', log_dir=root / 'logs', run_dir=root,
                context=context, run_id='fixture', declare_file=lambda path, role: path, add_input=lambda *args: None)
            calls = []
            def fail(operation, **kwargs):
                calls.append(operation)
                raise RuntimeError('actual launcher refusal')
            session.run_process = fail
            projection = {'members': [], 'electrode_groups': [], 'outer_box_mm': {'min': [0, 0, 0], 'max': [1, 1, 1]}}
            with patch.object(subject, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(subject, 'declare_runtime_files') as preserve, \
                 self.assertRaisesRegex(RuntimeError, 'actual launcher refusal'):
                subject.execute_geometry(session, projection=projection,
                    validation={'position_mm': 0, 'normal_abs': 0}, limits={})
            self.assertEqual(calls, ['build_geometry'])
            preserve.assert_called_once()

    def test_cold_selection_change_fails_closed(self):
        original = {'group_keys': ['rf/a'], 'group_faces': [[1, 2]], 'vacuum_domains': [1],
                    'outer_faces': [3], 'geometry_domains': 1}
        subject._check_cold_report(original, copy.deepcopy(original))
        for key, replacement in [('group_keys', ['other/a']), ('group_faces', [[1, 4]]),
                                 ('vacuum_domains', [2]), ('outer_faces', [4]), ('geometry_domains', 2)]:
            changed = copy.deepcopy(original)
            changed[key] = replacement
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                subject._check_cold_report(original, changed)

    def test_cold_operation_cannot_change_saved_geometry(self):
        import json
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('inputs', 'results', 'logs'):
                (root / name).mkdir()
            launcher = root / 'native' / 'launcher' / 'run.ps1'
            launcher.parent.mkdir(parents=True)
            launcher.write_text('fixture', encoding='utf-8')
            comsol = root / 'comsol.exe'
            comsol.write_bytes(b'fixture')
            context = SimpleNamespace(workspace=root, python_executable=root / 'python.exe',
                host_state_path=root / 'host.sqlite', policy_path=root / 'policy.json',
                tools={'comsol_launcher': comsol, 'matlab_root': root}, powershell_executable=root / 'pwsh.exe')
            session = SimpleNamespace(expected_operation_ids=('build_geometry', 'reopen_geometry'),
                input_dir=root / 'inputs', result_dir=root / 'results', log_dir=root / 'logs', run_dir=root,
                context=context, run_id='fixture', declare_file=lambda path, role: path, add_input=lambda *args: None)
            model = root / 'geometry-only.mph'
            descriptor = root / 'results' / 'geometry-descriptor.json'
            def simulate(operation, **kwargs):
                model.write_bytes(b'built' if operation == 'build_geometry' else b'modified')
                descriptor.write_bytes(b'descriptor')
                (root / 'logs' / (operation + '.bootstrap.log')).write_text('STATUS=PASS', encoding='utf-8')
                report = {'scope': 'geometry_only', 'operation': 'build', 'member_count': 1, 'group_count': 1,
                    'group_keys': ['one/g'], 'model_path': str(model), 'geometry_domains': 1,
                    'physics_count': 0, 'mesh_count': 0, 'study_count': 0, 'solver_count': 0,
                    'group_faces': [[1]], 'vacuum_domains': [1], 'outer_faces': [2]}
                (root / 'results' / (operation + '.json')).write_text(json.dumps(report), encoding='utf-8')
            session.run_process = simulate
            projection = {'members': [{'member_id': 'm'}], 'electrode_groups': [
                {'instance_id': 'one', 'electrode_group_id': 'g', 'member_ids': ['m']}],
                'outer_box_mm': {'min': [0, 0, 0], 'max': [1, 1, 1]}}
            with patch.object(subject, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(subject, 'declare_runtime_files'), patch.object(subject, 'require_launcher_completion'), \
                 self.assertRaisesRegex(AssertionError, 'byte count changed'):
                subject.execute_geometry(session, projection=projection,
                    validation={'position_mm': 0, 'normal_abs': 0}, limits={})

    def test_successful_inert_stage_binds_product_data(self):
        import json
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('inputs', 'results', 'logs'):
                (root / name).mkdir()
            launcher = root / 'native' / 'launcher' / 'run.ps1'
            launcher.parent.mkdir(parents=True)
            launcher.write_text('fixture', encoding='utf-8')
            comsol = root / 'comsol.exe'
            comsol.write_bytes(b'fixture')
            context = SimpleNamespace(workspace=root, python_executable=root / 'python.exe',
                host_state_path=root / 'host.sqlite', policy_path=root / 'policy.json',
                tools={'comsol_launcher': comsol, 'matlab_root': root}, powershell_executable=root / 'pwsh.exe')
            inputs = {}
            session = SimpleNamespace(expected_operation_ids=('build_geometry', 'reopen_geometry'),
                input_dir=root / 'inputs', result_dir=root / 'results', log_dir=root / 'logs', run_dir=root,
                context=context, run_id='fixture', declare_file=lambda path, role: path,
                add_input=lambda name, record: inputs.update({name: record}))
            model = root / 'geometry-only.mph'
            descriptor = root / 'results' / 'geometry-descriptor.json'
            def simulate(operation, **kwargs):
                if operation == 'build_geometry':
                    model.write_bytes(b'inert geometry bytes')
                    descriptor.write_bytes(b'inert descriptor')
                (root / 'logs' / (operation + '.bootstrap.log')).write_text('STATUS=PASS', encoding='utf-8')
                report = {'scope': 'geometry_only', 'operation': 'build' if operation == 'build_geometry' else 'reopen',
                    'member_count': 1, 'group_count': 1, 'group_keys': ['one/g'], 'model_path': str(model),
                    'geometry_domains': 1, 'physics_count': 0, 'mesh_count': 0, 'study_count': 0, 'solver_count': 0,
                    'group_faces': [[1]], 'vacuum_domains': [1], 'outer_faces': [2]}
                (root / 'results' / (operation + '.json')).write_text(json.dumps(report), encoding='utf-8')
            session.run_process = simulate
            projection = {'assembly_frame_id': 'world', 'members': [{'member_id': 'm'}], 'electrode_groups': [
                {'instance_id': 'one', 'electrode_group_id': 'g', 'member_ids': ['m']}],
                'outer_box_mm': {'min': [0, 0, 0], 'max': [1, 1, 1]}}
            with patch.object(subject, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(subject, 'declare_runtime_files'), patch.object(subject, 'require_launcher_completion'):
                result = subject.execute_geometry(session, projection=projection,
                    validation={'position_mm': 0, 'normal_abs': 0}, limits={})
            product = result['manifest_extra_fields']['products']['geometry']
            self.assertEqual(product['kind'], 'geometry_artifact')
            self.assertEqual(product['status'], 'complete')
            self.assertEqual(product['data']['projection'], inputs['projection'])
            self.assertEqual(product['data']['geometry_validation'], inputs['geometry_validation'])
            self.assertEqual(set(product['data']), {'projection', 'geometry_validation', 'model', 'descriptor',
                                                    'build_geometry', 'reopen_geometry'})
            self.assertEqual(len(result['required_output_paths']), 4)
