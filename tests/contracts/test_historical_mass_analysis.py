"""Actual Store/process-owner regression for sealed v1 mass analysis."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from msplatform.execution import processes
from msplatform.results.historical_mass_spectrum import OUTPUT_NAMES
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.historical_mass_analysis import analyze_recorded_mass_spectrum
from tests.contracts import test_execution_runtime as runtime_fixture
from tests.contracts.test_support.historical_mass_fixture import sealed_mass_source


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows OS source guard required')
class HistoricalMassAnalysisTests(unittest.TestCase):
    def test_history_guard_rejects_tampering_and_preserves_source(self):
        from msplatform.execution.native_source_guard import guard_historical_run
        from msplatform.io.manifest_records import file_record
        from msplatform.results.historical_mass_spectrum import read_historical_mass_selection
        with tempfile.TemporaryDirectory() as directory:
            _, source, _, _ = sealed_mass_source(Path(directory))
            before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            manifest = file_record(source/'run_manifest.json')
            with patch('msplatform.execution.capacity_ledger.load_capacity_ledger',
                       side_effect=AssertionError('old owner must not be accessed')):
                with guard_historical_run(manifest, expected_project='single_reflection_oa_tof_mass_analyzer',
                                          expected_mode='mass_spectrum_candidate') as guard:
                    selected = read_historical_mass_selection(guard, manifest)
                    self.assertEqual(len(selected['exports']), 11)
                    with self.assertRaises(PermissionError):
                        (source/'comsol/m100.csv').unlink()
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            (source/'comsol/m100.csv').write_text('changed', encoding='utf8')
            with guard_historical_run(manifest, expected_project='single_reflection_oa_tof_mass_analyzer',
                                      expected_mode='mass_spectrum_candidate') as guard:
                with self.assertRaises(ValueError):
                    read_historical_mass_selection(guard, manifest)

    def test_history_rejects_incomplete_summary_and_reports(self):
        from msplatform.execution.manifest_publication import publish_run_manifest
        from msplatform.execution.native_source_guard import guard_historical_run
        from msplatform.io.manifest_records import file_record
        from msplatform.results.historical_mass_spectrum import read_historical_mass_selection
        from msplatform.backends.simion.native_completion import retention_api
        for relative, payload, expected in (
                ('results/simion_summary.json', '{"Hit":11}', 'full-mother'),
                ('logs/m100.report.txt', 'DETECTED=3/4', 'DETECTED')):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                _, source, _, outputs = sealed_mass_source(Path(directory))
                (source/relative).write_text(payload, encoding='utf8')
                (source/'run_manifest.json').unlink()
                publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=retention_api)
                manifest = file_record(source/'run_manifest.json')
                with guard_historical_run(manifest, expected_project='single_reflection_oa_tof_mass_analyzer',
                                          expected_mode='mass_spectrum_candidate') as guard:
                    with self.assertRaisesRegex(ValueError, expected):
                        read_historical_mass_selection(guard, manifest)

    def test_history_rejects_nonterminal_or_failed_manifest(self):
        from msplatform.execution.native_source_guard import guard_historical_run
        from msplatform.io.manifest_records import file_record
        with tempfile.TemporaryDirectory() as directory:
            _, source, _, _ = sealed_mass_source(Path(directory))
            path = source/'run_manifest.json'
            original = json.loads(path.read_text(encoding='utf8'))
            for status in ('checkpoint', 'failed'):
                with self.subTest(status=status):
                    path.write_text(json.dumps(dict(original, status=status)), encoding='utf8')
                    with self.assertRaises(ValueError):
                        with guard_historical_run(file_record(path), expected_project='single_reflection_oa_tof_mass_analyzer',
                                                  expected_mode='mass_spectrum_candidate'):
                            pass

    def test_frozen_worker_rejects_modified_source_or_geometry(self):
        import hashlib
        from msplatform.execution.historical_mass_spectrum_worker import _verify_required_sources
        required = ('msplatform/execution/historical_mass_spectrum_worker.py',
            'msplatform/results/historical_mass_spectrum.py', 'msplatform/analysis/mass_spectrum.py',
            'msplatform/results/single_reflection_particle_table.py',
            'src/msplatform/components/single_reflection_oa_tof/config/resolved_geometry.json')
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent/'code'
            files = []
            for name in required:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode('ascii'))
                files.append({'relative_path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            (parent/'code_inventory.json').write_text(json.dumps({'files': files}), encoding='utf8')
            selected = {'inputs': {'resolved_geometry': {'sha256': files[-1]['sha256']}}}
            _verify_required_sources(root, selected)
            (root/required[1]).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'source identity differs'):
                _verify_required_sources(root, selected)
            (root/required[1]).write_bytes(required[1].encode('ascii'))
            selected['inputs']['resolved_geometry']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'geometry identity differs'):
                _verify_required_sources(root, selected)

    def test_failed_stage_does_not_publish_store_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, source, _, _ = sealed_mass_source(root)
            context = runtime_fixture.NormalOwnerTests()._context(root)
            store = ArtifactStore(root/'store')
            with patch('msplatform.workflows.historical_mass_analysis.read_stage_policy',
                       return_value=({'artifact_retention': {}, 'limits': {}}, {})), \
                 patch('msplatform.workflows.historical_mass_analysis.run_managed_stage',
                       return_value={'status': 'failed'}):
                with self.assertRaisesRegex(RuntimeError, 'stage failed'):
                    analyze_recorded_mass_spectrum(context, source_manifest=source/'run_manifest.json',
                        run_id='20261127_100000__analysis__python__failed', artifact_store=store,
                        committed_new_bytes=1024*1024)
            with store._db() as db:
                self.assertEqual(db.execute('SELECT status FROM run_execution').fetchone()[0], 'failed')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)

    def test_store_reanalysis_deep_path_observes_real_process_and_reopens(self):
        with tempfile.TemporaryDirectory(prefix='mass-history-') as directory:
            root = Path(directory)
            deep = root
            while len(str(deep)) < 260:
                deep /= 'historical input and artifact segment'
            _, source, _, _ = sealed_mass_source(deep)
            before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            context = runtime_fixture.NormalOwnerTests()._context(root)
            context.workspace.mkdir(parents=True, exist_ok=True)
            stage_path = root / 'stages.json'
            limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=268435456,
                process_tree_working_set_bytes=2147483648, minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=67108864, automatic_retry_count=0)
            stage_path.write_text(json.dumps(dict(schema_version=1, role='execution_stage_policy',
                stages={'oa_tof_mass_spectrum': dict(limits=limits,
                    artifact_retention={'policy_version': 1, 'class': 'solver_review', 'reason': 'historical test'})})), encoding='utf8')
            context = replace(context, stage_policy_path=stage_path, host_state_path=root/'host.sqlite3',
                              execution_root=root/'aliases')
            store = ArtifactStore(deep/'new-store')
            requests = []
            original = processes._invoke_process_owner
            def observe(context, request, resource_name, interpret):
                requests.append(dict(request))
                return original(context, request, resource_name, interpret)
            with patch.object(processes, '_invoke_process_owner', side_effect=observe):
                result = analyze_recorded_mass_spectrum(context, source_manifest=source/'run_manifest.json',
                    run_id='20261127_100000__analysis__python__history', artifact_store=store,
                    committed_new_bytes=268435456)
            self.assertEqual((result['status'], result['stage'], result['writers_confirmed']), ('success', 'complete', True))
            self.assertEqual(len(requests), 1)
            request = requests[0]
            self.assertLessEqual(len(request['working_directory']), 259)
            self.assertGreater(len(request['run_directory']), 259)
            self.assertNotEqual(request['working_directory'], request['run_directory'])
            self.assertIn(request['working_directory'], request['stdout_path'])
            self.assertIn(request['working_directory'], request['stderr_path'])
            self.assertFalse(Path(request['working_directory']).exists())
            run = Path(result['run_directory'])
            for name in OUTPUT_NAMES:
                self.assertTrue((run/'results'/name).is_file(), name)
            completion = json.loads((run/'results/execution_completion.json').read_text(encoding='utf8'))
            self.assertEqual(completion['summary']['solver_native_calls'], 0)
            self.assertEqual(completion['summary']['pa_materializations'], 0)
            receipt = json.loads((run/'logs/operation_0001.process.json').read_text(encoding='utf8'))
            self.assertEqual(receipt['observation']['exit_code'], 0)
            self.assertEqual(receipt['host_release']['result']['status'], 'released')
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM native_bindings WHERE state='active'").fetchone()[0], 0)
            self.assertEqual(ArtifactStore(deep/'new-store').inspect_run(result['store_run_id']), Path(result['store_run_path']))
            self.assertEqual(before, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
