"""Checks stationary readback independently of nonzero field values."""
import copy
import unittest
from msplatform.backends.comsol.assembly_field_solution import _check_stationary_report, validate_solution_readback


class StationarySolutionReadbackTests(unittest.TestCase):
    def test_raw_checkpoint_precedes_readback_and_uses_a_distinct_destination(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / 'src/msplatform/backends/comsol/matlab/solve_assembly_stationary.m').read_text(encoding='utf-8')
        run = source.index("model.study('std1').run;")
        raw = source.index("mphsave(model,rawOutputPath,'copy','on');")
        sequences = source.index("getSolverSequences('SolverSequence')")
        dataset = source.index("model.result.dataset.create(datasetTag,'Solution')")
        readback = source.index('read_assembly_stationary_solution(model,')
        final = source.index('mphsave(model,outputPath);')
        self.assertLess(run, raw)
        self.assertLess(raw, sequences)
        self.assertLess(sequences, dataset)
        self.assertLess(dataset, readback)
        self.assertLess(readback, final)

    def test_zero_field_has_no_special_nonzero_requirement(self):
        record = {'study_tag': 'std1', 'solution_tag': 'sol1', 'dataset_tag': 'dset',
                  'dataset_solution': 'sol1', 'solution_empty': False, 'solution_dofs': 12,
                  'solution_count': 1, 'stored_main_solutions': 1}
        validate_solution_readback(record, study_tag='std1', solution_tag='sol1', dataset_tag='dset')

    def test_scientific_notation_integral_dofs_and_invalid_values(self):
        import json
        record = {'study_tag': 'std1', 'solution_tag': 'sol1', 'dataset_tag': 'dset',
                  'dataset_solution': 'sol1', 'solution_empty': False,
                  'solution_dofs': json.loads('5.830174E+6'),
                  'solution_count': 1, 'stored_main_solutions': 1}
        validate_solution_readback(record, study_tag='std1', solution_tag='sol1', dataset_tag='dset')
        for value in (True, 0, -1, 1.5, float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_solution_readback(dict(record, solution_dofs=value), study_tag='std1', solution_tag='sol1', dataset_tag='dset')
    def test_changed_or_missing_evidence_is_rejected(self):
        original = {'study_tag': 'std1', 'solution_tag': 'sol1', 'dataset_tag': 'dset',
                    'dataset_solution': 'sol1', 'solution_empty': False, 'solution_dofs': 12,
                    'solution_count': 1, 'stored_main_solutions': 1}
        for key, value in [('study_tag', 'other'), ('dataset_solution', 'other'), ('solution_empty', True),
                           ('solution_count', 0), ('stored_main_solutions', 2), ('solution_dofs', 0),
                           ('solution_dofs', True)]:
            changed = copy.deepcopy(original)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_solution_readback(changed, study_tag='std1', solution_tag='sol1', dataset_tag='dset')


    def test_recovery_report_requires_zero_compute_and_exact_model(self):
        from pathlib import Path
        model = Path.cwd() / 'saved.mph'
        solution = {'study_tag': 'std1', 'solution_tag': 's', 'dataset_tag': 'assembly_field_solution',
                    'dataset_solution': 's', 'solution_empty': False, 'solution_dofs': 5830174.0,
                    'solution_count': 1, 'stored_main_solutions': 1, 'solver_policy': 'comsol_stationary_default',
                    'solver_type': 'Stationary', 'solver_sequence_type': 'Stationary',
                    'solver_features': ['st1'], 'comsol_version': '6.4'}
        baseline = {'group_keys': ['one/g'], 'group_faces': [3], 'vacuum_domains': [1], 'outer_faces': [4]}
        projection = {'electrode_groups': [{'instance_id': 'one', 'electrode_group_id': 'g'}]}
        row = dict(baseline, operation='recover', scope='single_stationary_workpoint',
                   model_path=str(model), compute_calls=0, solution=solution)
        _check_stationary_report(row, mode='recover', projection=projection, baseline=baseline, model=model)
        for changed in (dict(row, compute_calls=1), dict(row, model_path=str(model) + '.other'),
                        dict(row, group_faces=[9])):
            with self.assertRaises(ValueError):
                _check_stationary_report(changed, mode='recover', projection=projection, baseline=baseline, model=model)
    def test_stationary_report_zero_workpoint_and_mutations(self):
        from pathlib import Path
        model = Path.cwd() / 'fixture.mph'
        solution = {'study_tag': 'std1', 'solution_tag': 'sol1', 'dataset_tag': 'assembly_field_solution',
            'dataset_solution': 'sol1', 'solution_empty': False, 'solution_dofs': 12, 'solution_count': 1,
            'stored_main_solutions': 1, 'solver_policy': 'comsol_stationary_default', 'solver_type': 'Stationary',
            'solver_sequence_type': 'Stationary', 'solver_features': ['st1'], 'comsol_version': '6.4'}
        baseline = {'group_keys': ['one/g'], 'group_faces': [3], 'vacuum_domains': [1, 2], 'outer_faces': [4]}
        projection = {'electrode_groups': [{'instance_id': 'one', 'electrode_group_id': 'g'}]}
        row = dict(baseline, operation='compute', scope='single_stationary_workpoint', model_path=str(model),
                   compute_calls=1, solution=solution)
        _check_stationary_report(row, mode='compute', projection=projection, baseline=baseline, model=model)
        for key, value in [('group_faces', [9]), ('vacuum_domains', [2]), ('compute_calls', 0)]:
            changed = copy.deepcopy(row)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                _check_stationary_report(changed, mode='compute', projection=projection, baseline=baseline, model=model)
        changed = copy.deepcopy(row)
        changed['solution']['dataset_solution'] = 'other'
        with self.assertRaises(ValueError):
            _check_stationary_report(changed, mode='compute', projection=projection, baseline=baseline, model=model)
    def test_borrowed_model_guards_and_failure_preservation(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.comsol import native_execution
        from msplatform.execution import inputs
        from msplatform.io.manifest_records import file_record, verify_record
        from msplatform.backends.comsol.assembly_field_solution import execute_stationary

        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('inputs', 'results', 'logs', 'native/launcher', 'original'):
                (root / name).mkdir(parents=True)
            launcher = root / 'native/launcher/run.ps1'
            launcher.write_bytes(b'launcher')
            comsol = root / 'comsol.exe'
            comsol.write_bytes(b'comsol')
            names = ('model', 'request', 'projection', 'descriptor', 'geometry_validation', 'reopen_geometry',
                     'build_model', 'reopen_model')
            baseline = {'group_keys': ['one/g'], 'group_faces': [3], 'vacuum_domains': [1, 2], 'outer_faces': [4]}
            originals = {}
            for name in names:
                original = root / 'original' / (name + ('.mph' if name == 'model' else '.json'))
                original.write_text(json.dumps(baseline) if name == 'reopen_geometry' else name, encoding='utf-8')
                originals[name] = file_record(original, 'solver_native_binary' if name == 'model' else 'required_evidence')
            manifest_path = root / 'prepared-manifest.json'
            manifest_path.write_text('{}', encoding='utf-8')
            manifest_record = file_record(manifest_path)
            reads = []
            def data_path(name):
                reads.append(name)
                verify_record(name, originals[name])
                return Path(originals[name]['path'])
            source = SimpleNamespace(data_path=data_path, data_records=originals)
            context = SimpleNamespace(workspace=root, python_executable=root / 'python.exe',
                host_state_path=root / 'host.sqlite', policy_path=root / 'policy.json',
                tools={'comsol_launcher': comsol, 'matlab_root': root}, powershell_executable=root / 'pwsh.exe')
            added, operations = {}, []
            session = SimpleNamespace(expected_operation_ids=('solve_stationary', 'reopen_solution'),
                input_dir=root / 'inputs', result_dir=root / 'results', log_dir=root / 'logs', run_dir=root,
                context=context, run_id='fixture', declare_file=lambda path, role: path,
                add_input=lambda name, record: added.update({name: record}))
            output = root / 'assembly-stationary-field.mph'
            solution = {'study_tag': 'std1', 'solution_tag': 'sol1', 'dataset_tag': 'assembly_field_solution',
                'dataset_solution': 'sol1', 'solution_empty': False, 'solution_dofs': 12, 'solution_count': 1,
                'stored_main_solutions': 1, 'solver_policy': 'comsol_stationary_default',
                'solver_type': 'Stationary', 'solver_sequence_type': 'Stationary', 'solver_features': ['st1'],
                'comsol_version': '6.4'}
            def simulate(operation, **kwargs):
                operations.append((operation, kwargs['immutable_input_records']))
                if operation == 'solve_stationary':
                    (root / 'assembly-stationary-computed-raw.mph').write_bytes(b'inert raw result')
                    output.write_bytes(b'inert result')
                (root / 'logs' / (operation + '.bootstrap.log')).write_text('STATUS=PASS', encoding='utf-8')
                report = dict(baseline, operation='compute' if operation == 'solve_stationary' else 'reopen',
                    scope='single_stationary_workpoint', model_path=str(output),
                    compute_calls=1 if operation == 'solve_stationary' else 0, solution=solution)
                (root / 'results' / (operation + '.json')).write_text(json.dumps(report), encoding='utf-8')
            session.run_process = simulate
            projection = {'electrode_groups': [{'instance_id': 'one', 'electrode_group_id': 'g'}]}
            with patch.object(native_execution, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(native_execution, 'declare_runtime_files'), \
                 patch.object(native_execution, 'require_launcher_completion'), \
                 patch.object(inputs, 'freeze_file', wraps=inputs.freeze_file) as freeze:
                result = execute_stationary(session, source=source, manifest_record=manifest_record,
                    names=names, projection=projection, request={},
                    solver_numerics={'kind': 'comsol_stationary_default'}, limits={})
            self.assertNotIn(Path(originals['model']['path']), [call.args[0] for call in freeze.call_args_list])
            self.assertEqual(len(freeze.call_args_list), len(names) - 1)
            self.assertIn(originals['model'], operations[0][1])
            self.assertNotIn(originals['model'], operations[1][1])
            self.assertEqual(added['prepared_model_model'], originals['model'])
            self.assertEqual(reads.count('model'), 3)
            self.assertTrue(all(any(r['path'].endswith('solver-numerics.json') for r in guards)
                                for _, guards in operations))
            from msplatform.execution.terminal_publication import publish_terminal_state
            from msplatform.results import artifacts
            product = result['manifest_extra_fields']['products']['solution']
            required = ('request', 'projection', 'descriptor', 'geometry_validation', 'reopen_geometry')
            self.assertTrue(all(product['data'][name] == added['prepared_' + name] for name in required))
            published = root / 'published'
            published.mkdir()
            output_records = [file_record(Path(path), 'solver_native_binary' if path.endswith('.mph') else 'required_evidence')
                              for path in result['output_paths']]
            document = dict(schema_version=2, role='simulation_run_manifest', run_id='reader-fixture',
                project='software_fixture', mode='stationary_workpoint', status='success', inputs=added,
                outputs=output_records, products={'solution': product})
            publish_terminal_state(published, {'status': 'success'}, document)
            reference = {'manifest': file_record(published / 'run_manifest.json'), 'product_id': 'solution'}
            with patch.object(artifacts, 'ARTIFACT_KINDS', artifacts.ARTIFACT_KINDS | {'field_solution'}):
                reopened = artifacts.open_artifact(reference, expected_kind='field_solution')
                self.assertEqual(set(required) - set(reopened.data_records), set())
                for name in required:
                    member = reopened.data_path(name)
                    original = member.read_bytes()
                    member.write_bytes(original + b'tamper')
                    with self.subTest(name=name, failure='tampered'), self.assertRaises(AssertionError):
                        artifacts.open_artifact(reference, expected_kind='field_solution')
                    member.unlink()
                    with self.subTest(name=name, failure='missing'), self.assertRaises(AssertionError):
                        artifacts.open_artifact(reference, expected_kind='field_solution')
                    member.write_bytes(original)
                artifacts.open_artifact(reference, expected_kind='field_solution')
            failure_root = root / 'failure'
            for name in ('inputs', 'results', 'logs'):
                (failure_root / name).mkdir(parents=True)
            session.input_dir = failure_root / 'inputs'
            session.result_dir = failure_root / 'results'
            session.log_dir = failure_root / 'logs'
            session.run_dir = failure_root
            marker = RuntimeError('primary launcher failure')
            def fail(operation, **kwargs):
                raise marker
            session.run_process = fail
            with patch.object(native_execution, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(native_execution, 'declare_runtime_files', side_effect=ValueError('cleanup failure')), \
                 self.assertRaises(RuntimeError) as caught:
                result = execute_stationary(session, source=source, manifest_record=manifest_record,
                    names=names, projection=projection, request={},
                    solver_numerics={'kind': 'comsol_stationary_default'}, limits={})
            self.assertIs(caught.exception, marker)
            self.assertTrue(any('cleanup failure' in note for note in marker.__notes__))
            self.assertFalse(hasattr(marker, 'failure_output_paths'))
            recovery_root = root / 'recovery'
            for name in ('inputs', 'results', 'logs'):
                (recovery_root / name).mkdir(parents=True)
            session.input_dir = recovery_root / 'inputs'
            session.result_dir = recovery_root / 'results'
            session.log_dir = recovery_root / 'logs'
            session.run_dir = recovery_root
            saved_failure = RuntimeError('original readback failure after raw save')
            def fail_after_save(operation, **kwargs):
                (recovery_root / 'assembly-stationary-computed-raw.mph').write_bytes(b'inert partial or raw checkpoint')
                raise saved_failure
            session.run_process = fail_after_save
            with patch.object(native_execution, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(native_execution, 'declare_runtime_files'), \
                 self.assertRaises(RuntimeError) as saved_caught:
                execute_stationary(session, source=source, manifest_record=manifest_record,
                    names=names, projection=projection, request={},
                    solver_numerics={'kind': 'comsol_stationary_default'}, limits={})
            self.assertIs(saved_caught.exception, saved_failure)
            self.assertEqual(saved_failure.failure_output_paths,
                             [recovery_root / 'assembly-stationary-computed-raw.mph'])
            self.assertEqual(saved_failure.failure_output_paths[0].read_bytes(), b'inert partial or raw checkpoint')
            cold_root = root / 'cold-failure'
            for name in ('inputs', 'results', 'logs'):
                (cold_root / name).mkdir(parents=True)
            session.input_dir = cold_root / 'inputs'
            session.result_dir = cold_root / 'results'
            session.log_dir = cold_root / 'logs'
            session.run_dir = cold_root
            cold_failure = RuntimeError('original cold reopen failure')
            def fail_on_reopen(operation, **kwargs):
                if operation == 'reopen_solution':
                    raise cold_failure
                (cold_root / 'assembly-stationary-computed-raw.mph').write_bytes(b'raw checkpoint')
                (cold_root / 'assembly-stationary-field.mph').write_bytes(b'inert final')
                (cold_root / 'logs/solve_stationary.bootstrap.log').write_text('STATUS=PASS', encoding='utf-8')
                report = dict(baseline, operation='compute', scope='single_stationary_workpoint',
                    model_path=str(cold_root / 'assembly-stationary-field.mph'), compute_calls=1, solution=solution)
                (cold_root / 'results/solve_stationary.json').write_text(json.dumps(report), encoding='utf-8')
            session.run_process = fail_on_reopen
            with patch.object(native_execution, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(native_execution, 'declare_runtime_files'), \
                 patch.object(native_execution, 'require_launcher_completion'), \
                 self.assertRaises(RuntimeError) as cold_caught:
                execute_stationary(session, source=source, manifest_record=manifest_record,
                    names=names, projection=projection, request={},
                    solver_numerics={'kind': 'comsol_stationary_default'}, limits={})
            self.assertIs(cold_caught.exception, cold_failure)
            self.assertEqual(cold_failure.failure_output_paths,
                             [cold_root / 'assembly-stationary-computed-raw.mph', cold_root / 'assembly-stationary-field.mph', cold_root / 'results/solve_stationary.json'])
            post_root = root / 'postprocess-failure'
            for name in ('inputs', 'results', 'logs'):
                (post_root / name).mkdir(parents=True)
            session.input_dir = post_root / 'inputs'
            session.result_dir = post_root / 'results'
            session.log_dir = post_root / 'logs'
            session.run_dir = post_root
            post_failure = ValueError('original launcher completion failure')
            def complete_then_fail(operation, **kwargs):
                (post_root / 'assembly-stationary-computed-raw.mph').write_bytes(b'raw checkpoint')
                (post_root / 'assembly-stationary-field.mph').write_bytes(b'inert final')
            session.run_process = complete_then_fail
            with patch.object(native_execution, 'freeze_native_sources', return_value=(launcher, [])), \
                 patch.object(native_execution, 'declare_runtime_files'), \
                 patch.object(native_execution, 'require_launcher_completion', side_effect=post_failure), \
                 self.assertRaises(ValueError) as post_caught:
                execute_stationary(session, source=source, manifest_record=manifest_record,
                    names=names, projection=projection, request={},
                    solver_numerics={'kind': 'comsol_stationary_default'}, limits={})
            self.assertIs(post_caught.exception, post_failure)
            self.assertEqual(post_failure.failure_output_paths,
                             [post_root / 'assembly-stationary-computed-raw.mph', post_root / 'assembly-stationary-field.mph'])
