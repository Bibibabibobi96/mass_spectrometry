"""Small Store-owned RF L1 lifecycle; synthetic kernel, no scientific qualification."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.rf_mass_filter import finite_length, research
from tests.components.rf_multipole_ion_optics.analysis import test_mass_filter_l1 as l1_fixture


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows process ownership required')
class RfL1StoreLifecycleTests(unittest.TestCase):
    def test_functional_failure_is_not_published_as_success(self):
        with tempfile.TemporaryDirectory(prefix='rf-l1-functional-failure-') as directory:
            root = Path(directory)
            store = ArtifactStore(root / 'store')
            provider = l1_fixture.MassFilterL1Tests._controlled_provider(root / 'artifacts/components/rf_multipole_ion_optics', passed=False)
            policy = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy', 'stages': {
                'rf_mass_filter_l1': {'limits': limits, 'artifact_retention': {
                    'policy_version': 1, 'class': 'solver_review', 'reason': 'inert fixture'}}}}), encoding='utf-8')
            context = ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'), stage_policy_path=policy)
            run_id = '20261127_160011__test__python__rf-functional-fail'
            with patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': ''}), \
                 patch.object(finite_length, '_source_package_root', return_value=provider):
                with self.assertRaisesRegex(RuntimeError, 'functional gate failed'):
                    finite_length.run(context, baseline_path=research.DEFAULT_BASELINE,
                        resolved_path=research.DEFAULT_RESOLVED, mode_path=research.DEFAULT_MODE,
                        source_path=research.DEFAULT_SOURCE, run_id=run_id, artifact_store=store)
            with store._db() as db:
                asset = db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (run_id,)).fetchone()[0]
            run = store.asset_status(asset)['path'] / 'runs' / run_id
            self.assertEqual(store.asset_status(asset)['state'], 'failed')
            self.assertEqual(json.loads((run / 'run_manifest.json').read_text(encoding='utf-8'))['status'], 'failed')
            summary = json.loads((run / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['functional_gate'], 'FAIL')
            self.assertNotIn('formal_eligible', json.loads((run / 'run_manifest.json').read_text(encoding='utf-8')))

    def test_input_freezing_failure_retains_original_error_and_failed_evidence(self):
        from msplatform.execution import inputs
        with tempfile.TemporaryDirectory(prefix='rf-l1-freeze-failure-') as directory:
            root = Path(directory)
            store = ArtifactStore(root / 'store')
            policy = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy', 'stages': {
                'rf_mass_filter_l1': {'limits': limits, 'artifact_retention': {
                    'policy_version': 1, 'class': 'solver_review', 'reason': 'inert fixture'}}}}), encoding='utf-8')
            context = ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'), stage_policy_path=policy)
            original = OSError('injected input freeze failure')
            freeze = inputs.freeze_file
            def fail_selected(source, target, **kwargs):
                if Path(target).name == 'resolved_design_mass_filter.json':
                    raise original
                return freeze(source, target, **kwargs)
            run_id = '20261127_160007__test__python__rf-input-fail'
            with patch.object(inputs, 'freeze_file', side_effect=fail_selected):
                with self.assertRaises(OSError) as caught:
                    finite_length.run(context, baseline_path=research.DEFAULT_BASELINE,
                        resolved_path=research.DEFAULT_RESOLVED, mode_path=research.DEFAULT_MODE,
                        source_path=research.DEFAULT_SOURCE, run_id=run_id, artifact_store=store)
            self.assertIs(caught.exception, original)
            with store._db() as db:
                asset = db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (run_id,)).fetchone()[0]
            run = store.asset_status(asset)['path'] / 'runs' / run_id
            evidence = json.loads((run / 'results/failure_context.json').read_text(encoding='utf-8'))
            self.assertEqual((evidence['status'], evidence['failure_stage']), ('failed', 'input_freezing'))
            self.assertEqual(store.asset_status(asset)['state'], 'failed')

    def test_real_frozen_simulation_failure_keeps_stdout_and_worker_proof(self):
        from msplatform.execution.processes import ProcessExecutionError
        with tempfile.TemporaryDirectory(prefix='rf-l1-os-failure-') as directory:
            root = Path(directory)
            store = ArtifactStore(root / 'store')
            provider = l1_fixture.MassFilterL1Tests._controlled_provider(root / 'artifacts/components/rf_multipole_ion_optics')
            kernel = provider / 'components/rf_multipole/finite_length_transport.py'
            kernel.write_text('def simulate_mass(*args):\n    print("FROZEN_RF_FAILURE", flush=True)\n    raise OSError("INERT_KERNEL_FAILURE")\n', encoding='utf-8')
            policy = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy', 'stages': {
                'rf_mass_filter_l1': {'limits': limits, 'artifact_retention': {
                    'policy_version': 1, 'class': 'solver_review', 'reason': 'inert fixture'}}}}), encoding='utf-8')
            context = ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'), stage_policy_path=policy)
            run_id = '20261127_160010__test__python__rf-worker-fail'
            with patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': ''}), \
                 patch.object(finite_length, '_source_package_root', return_value=provider):
                with self.assertRaises(ProcessExecutionError) as caught:
                    finite_length.run(context, baseline_path=research.DEFAULT_BASELINE,
                        resolved_path=research.DEFAULT_RESOLVED, mode_path=research.DEFAULT_MODE,
                        source_path=research.DEFAULT_SOURCE, run_id=run_id, artifact_store=store)
            error = caught.exception
            self.assertTrue(error.observed_process_exit_confirmed)
            self.assertNotEqual(error.observed_process_returncode, 0)
            self.assertEqual(error.host_release['result']['status'], 'released')
            with store._db() as db:
                asset = db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (run_id,)).fetchone()[0]
            run = store.asset_status(asset)['path'] / 'runs' / run_id
            self.assertEqual(store.asset_status(asset)['state'], 'failed')
            self.assertEqual(json.loads((run / 'results/failure_context.json').read_text(encoding='utf-8'))['failure_stage'], 'simulation')
            self.assertIn('FROZEN_RF_FAILURE', (run / 'logs/simulation_module.stdout.log').read_text(encoding='utf-8'))
            self.assertIn('INERT_KERNEL_FAILURE', (run / 'logs/operation_0002.stderr.log').read_text(encoding='utf-8'))
            self.assertFalse((run / 'results/analysis_execution.json').exists())

    def test_author_guards_and_failed_run_identity_are_preserved(self):
        with tempfile.TemporaryDirectory(prefix='rf-l1-failure-') as directory:
            root = Path(directory)
            store = ArtifactStore(root / 'store')
            authors = []
            for index, source in enumerate((research.DEFAULT_BASELINE, research.DEFAULT_RESOLVED,
                                            research.DEFAULT_MODE, research.DEFAULT_SOURCE)):
                target = root / f'author{index}.json'
                target.write_bytes(source.read_bytes())
                authors.append(target)
            before = [path.read_bytes() for path in authors]
            policy = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy', 'stages': {
                'rf_mass_filter_l1': {'limits': limits, 'artifact_retention': {
                    'policy_version': 1, 'class': 'solver_review', 'reason': 'inert fixture'}}}}), encoding='utf-8')
            context = ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'), stage_policy_path=policy)
            run_id = '20261127_160004__test__python__rf-failed'
            failure = OSError('injected input preparation failure')
            def fail_after_inputs(*_args, **_kwargs):
                for path in authors:
                    with self.assertRaises(PermissionError):
                        path.unlink()
                raise failure
            arguments = dict(baseline_path=authors[0], resolved_path=authors[1], mode_path=authors[2],
                             source_path=authors[3], run_id=run_id, artifact_store=store)
            with patch.object(finite_length, '_prepare_frozen_request', side_effect=fail_after_inputs):
                with self.assertRaises(OSError) as caught:
                    finite_length.run(context, **arguments)
            self.assertIs(caught.exception, failure)
            self.assertEqual([path.read_bytes() for path in authors], before)
            with store._db() as db:
                asset_id = db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (run_id,)).fetchone()[0]
            self.assertEqual(store.asset_status(asset_id)['state'], 'failed')
            manifest = store.asset_status(asset_id)['path'] / 'runs' / run_id / 'run_manifest.json'
            self.assertEqual(json.loads(manifest.read_text(encoding='utf-8'))['status'], 'failed')
            with self.assertRaises(FileExistsError):
                finite_length.run(context, **arguments)

    def test_failed_stage_publication_can_resume_without_new_action(self):
        from contextlib import contextmanager
        with tempfile.TemporaryDirectory(prefix='rf-l1-resume-failure-') as directory:
            root = Path(directory)
            store = ArtifactStore(root / 'store')
            policy = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy', 'stages': {
                'rf_mass_filter_l1': {'limits': limits, 'artifact_retention': {
                    'policy_version': 1, 'class': 'solver_review', 'reason': 'inert fixture'}}}}), encoding='utf-8')
            context = ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'), stage_policy_path=policy)
            run_id = '20261127_160006__test__python__rf-recover'
            real_inplace = store.inplace_asset
            @contextmanager
            def interrupted(*args, **kwargs):
                with real_inplace(*args, **kwargs) as (asset, path, claim, _seal):
                    def fail_seal(**_kwargs):
                        raise OSError('injected seal interruption')
                    yield asset, path, claim, fail_seal
            original = OSError('original preparation failure')
            with patch.object(store, 'inplace_asset', side_effect=interrupted), \
                 patch.object(finite_length, '_prepare_frozen_request', side_effect=original):
                with self.assertRaises(OSError) as caught:
                    finite_length.run(context, baseline_path=research.DEFAULT_BASELINE,
                        resolved_path=research.DEFAULT_RESOLVED, mode_path=research.DEFAULT_MODE,
                        source_path=research.DEFAULT_SOURCE, run_id=run_id, artifact_store=store)
            self.assertIs(caught.exception, original)
            with store._db() as db:
                asset = db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (run_id,)).fetchone()[0]
            self.assertEqual(store.asset_status(asset)['state'], 'publishing')
            recovered = research.resume(run_id, asset, context=context, artifact_store=store)
            self.assertEqual((recovered['status'], recovered['replayed']), ('failed', True))
            repeated = research.resume(run_id, asset, context=context, artifact_store=store)
            self.assertEqual((repeated['status'], repeated['replayed']), ('failed', False))


    def test_ready_resume_revalidates_store_payload_without_republication(self):
        with tempfile.TemporaryDirectory(prefix='rf-l1-resume-') as directory:
            store = ArtifactStore(Path(directory) / 'store')
            run_id = '20261127_160003__test__python__rf-resume'
            with store.inplace_asset('native_stage', 'resume-test') as (asset, path, _claim, seal):
                run = path / 'runs' / run_id
                run.mkdir(parents=True)
                (run / 'run_manifest.json').write_text('{}', encoding='utf-8')
                (run / 'data').write_bytes(b'sealed')
                seal()
            result = research.resume(run_id, asset, context=None, artifact_store=store)
            self.assertEqual((result['status'], result['replayed']), ('ready', False))
            (run / 'data').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                research.resume(run_id, asset, context=None, artifact_store=store)

    def test_historical_parent_handles_remain_held(self):
        from msplatform.execution.manifest_publication import build_run_manifest
        with tempfile.TemporaryDirectory(prefix='rf-l1-history-') as directory:
            root = Path(directory)
            run = root / 'historical' / '20261127_160002__test__python__rf-history'
            (run / 'inputs').mkdir(parents=True)
            (run / 'results').mkdir()
            inputs = {}
            for name in ('baseline', 'resolved_design', 'mode', 'source', 'response_for_analysis'):
                path = run / 'inputs' / (name + '.json')
                path.write_bytes(b'response' if name == 'response_for_analysis' else b'{}')
                inputs[name] = str(path)
            response = run / 'results/mass-response__finite-length.csv'
            response.write_bytes(b'response')
            summary = run / 'summary.json'
            summary.write_text(json.dumps({'functional_gate': 'PASS'}), encoding='utf-8')
            config = run / 'run_config.json'
            config.write_text(json.dumps({'schema_version': 1, 'run_id': run.name,
                'project': 'rf_multipole_ion_optics', 'mode': 'mass_filter_reference', 'inputs': inputs,
                'parameters': {'lifecycle_stage': 'complete'}, 'capacity_ledger_lifecycle': {
                    'schema_version': 1, 'enabled': True, 'artifact_root': str(root / 'historical'),
                    'light_evidence_budget_bytes': 1024}}), encoding='utf-8')
            document = build_run_manifest(config, 'success', output_paths=[response, summary])
            manifest = run / 'run_manifest.json'
            manifest.write_text(json.dumps(document), encoding='utf-8')
            store = ArtifactStore(root / 'store')
            with finite_length._guard_analysis_parent(store, manifest) as (parent, required):
                self.assertEqual(parent['parent_run_id'], run.name)
                self.assertEqual(required, ())
                with self.assertRaises(PermissionError):
                    response.unlink()
            response.unlink()
            with self.assertRaises((OSError, ValueError)):
                with finite_length._guard_analysis_parent(store, manifest):
                    self.fail('missing historical response was accepted')

    def test_store_parent_claim_prevents_collection_while_reading(self):
        from msplatform.execution.manifest_publication import build_run_manifest
        with tempfile.TemporaryDirectory(prefix='rf-l1-parent-') as directory:
            store = ArtifactStore(Path(directory) / 'store')
            run_id = '20261127_160005__test__python__rf-parent'
            with store.inplace_asset('native_stage', 'parent', run_id=run_id) as (asset, path, _claim, seal):
                run = path / 'runs' / run_id
                (run / 'inputs').mkdir(parents=True)
                (run / 'results').mkdir()
                inputs = {}
                for name in ('baseline', 'resolved_design', 'mode', 'source', 'response_for_analysis'):
                    target = run / 'inputs' / (name + '.json')
                    target.write_bytes(b'response' if name == 'response_for_analysis' else b'{}')
                    inputs[name] = str(target)
                response = run / 'results/mass-response__finite-length.csv'
                response.write_bytes(b'response')
                summary = run / 'summary.json'
                summary.write_text(json.dumps({'functional_gate': 'PASS'}), encoding='utf-8')
                config = run / 'run_config.json'
                config.write_text(json.dumps({'schema_version': 1, 'run_id': run_id,
                    'project': 'rf_multipole_ion_optics', 'mode': 'mass_filter_reference', 'inputs': inputs,
                    'parameters': {'lifecycle_stage': 'complete'}, 'capacity_ledger_lifecycle': {
                        'schema_version': 1, 'enabled': False, 'artifact_root': str(store.root),
                        'light_evidence_budget_bytes': 1024}}), encoding='utf-8')
                manifest = run / 'run_manifest.json'
                manifest.write_text(json.dumps(build_run_manifest(config, 'success', output_paths=[response, summary])), encoding='utf-8')
                seal()
            with finite_length._guard_analysis_parent(store, manifest) as (parent, required):
                self.assertEqual((parent['parent_run_id'], required), (run_id, (asset,)))
                self.assertEqual(store.collect(1_000_000)['released_bytes'], 0)
                with self.assertRaises(PermissionError):
                    response.unlink()

    def test_analysis_failure_preserves_parent_and_original_error(self):
        from msplatform.execution.manifest_publication import build_run_manifest
        with tempfile.TemporaryDirectory(prefix='rf-l1-analysis-failure-') as directory:
            root = Path(directory)
            run = root / 'historical' / '20261127_160008__test__python__rf-parent'
            (run / 'inputs').mkdir(parents=True)
            (run / 'results').mkdir()
            paths = {}
            for name, source in zip(('baseline', 'resolved_design', 'mode', 'source'),
                                    (research.DEFAULT_BASELINE, research.DEFAULT_RESOLVED,
                                     research.DEFAULT_MODE, research.DEFAULT_SOURCE), strict=True):
                target = run / 'inputs' / (name + '.json')
                target.write_bytes(source.read_bytes())
                paths[name] = str(target)
            response = run / 'results/mass-response__finite-length.csv'
            response.write_bytes(b'inert response')
            copied = run / 'inputs/response.csv'
            copied.write_bytes(response.read_bytes())
            paths['response_for_analysis'] = str(copied)
            summary = run / 'summary.json'
            summary.write_text(json.dumps({'functional_gate': 'PASS'}), encoding='utf-8')
            config = run / 'run_config.json'
            config.write_text(json.dumps({'schema_version': 1, 'run_id': run.name,
                'project': 'rf_multipole_ion_optics', 'mode': 'mass_filter_reference', 'inputs': paths,
                'parameters': {'lifecycle_stage': 'complete'}, 'capacity_ledger_lifecycle': {
                    'schema_version': 1, 'enabled': True, 'artifact_root': str(root / 'historical'),
                    'light_evidence_budget_bytes': 1024}}), encoding='utf-8')
            manifest = run / 'run_manifest.json'
            document = build_run_manifest(config, 'success', output_paths=[response, summary])
            for row in document['outputs']:
                if Path(row['path']) == response:
                    row['retention_role'] = 'required_evidence'
            manifest.write_text(json.dumps(document), encoding='utf-8')
            before = {path: path.read_bytes() for path in run.rglob('*') if path.is_file()}
            policy = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy', 'stages': {
                'rf_mass_filter_l1': {'limits': limits, 'artifact_retention': {
                    'policy_version': 1, 'class': 'solver_review', 'reason': 'inert fixture'}}}}), encoding='utf-8')
            context = ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'), stage_policy_path=policy)
            store = ArtifactStore(root / 'store')
            failure = OSError('injected analysis failure')
            run_id = '20261127_160009__analysis__python__rf-failed'
            with patch.object(finite_length, '_prepare_frozen_request', return_value=(root / 'unused', [])), \
                 patch.object(finite_length, '_invoke_frozen_stage', side_effect=failure):
                with self.assertRaises(OSError) as caught:
                    finite_length.analyze(context, parent_manifest_path=manifest, run_id=run_id, artifact_store=store)
            self.assertIs(caught.exception, failure)
            self.assertEqual({path: path.read_bytes() for path in before}, before)
            with store._db() as db:
                asset = db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (run_id,)).fetchone()[0]
            failed_run = store.asset_status(asset)['path'] / 'runs' / run_id
            evidence = json.loads((failed_run / 'results/failure_context.json').read_text(encoding='utf-8'))
            self.assertEqual((evidence['failure_stage'], evidence['simulation_calls']), ('analysis_execution', 0))
            self.assertFalse((failed_run / 'results/simulation_execution.json').exists())

    def test_run_analyze_and_missing_parent_reject(self):
        with tempfile.TemporaryDirectory(prefix='rf-l1-store-') as directory:
            root = Path(directory)
            old_hint = root / 'artifacts/components/rf_multipole_ion_optics'
            provider = l1_fixture.MassFilterL1Tests._controlled_provider(old_hint)
            policy = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1048576,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            stage = dict(limits=limits, artifact_retention={'policy_version': 1, 'class': 'solver_review', 'reason': 'inert fixture'})
            policy.write_text(json.dumps({'schema_version': 1, 'role': 'execution_stage_policy',
                                          'stages': {'rf_mass_filter_l1': stage}}), encoding='utf-8')
            context = ExecutionContext(workspace=root / 'workspace', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'), stage_policy_path=policy)
            store = ArtifactStore(root / 'l1-store')
            inherited = {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': '', 'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID': '',
                         'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE': ''}
            with patch.dict(os.environ, inherited), patch.object(finite_length, '_source_package_root', return_value=provider):
                parent = finite_length.run(context, baseline_path=research.DEFAULT_BASELINE,
                    resolved_path=research.DEFAULT_RESOLVED, mode_path=research.DEFAULT_MODE, source_path=research.DEFAULT_SOURCE,
                    run_id='20261127_160000__test__python__rf-parent', artifact_store=store)
                parent_manifest = Path(parent['manifest']['path'])
                child = finite_length.analyze(context, parent_manifest_path=parent_manifest,
                    run_id='20261127_160001__analysis__python__rf-child', artifact_store=store)
            self.assertEqual((parent['status'], child['status']), ('success', 'success'))
            parent_path = Path(parent['run_directory'])
            child_path = Path(child['run_directory'])
            self.assertEqual((parent_path / 'results/mass-response__finite-length.csv').read_bytes(),
                             (child_path / 'results/mass-response__finite-length.csv').read_bytes())
            metrics = json.loads((parent_path / 'results/mass-filter__functional-metrics.json').read_text(encoding='utf-8'))
            self.assertEqual(metrics['sampled_response_analysis']['interpolated_main_peak_fwhm_Th'], 4.5)
            completion = json.loads((child_path / 'results/execution_completion.json').read_text(encoding='utf-8'))
            self.assertEqual([row['operation_id'] for row in completion['writer_completion']['operations']], ['analysis'])
            self.assertFalse((root / 'workspace/artifacts/capacity_ledger.json').exists())
            source = parent_path / 'results/mass-response__finite-length.csv'
            source.unlink()
            with self.assertRaises((OSError, ValueError)):
                with finite_length._guard_analysis_parent(store, parent_manifest):
                    self.fail('missing parent response was accepted')
