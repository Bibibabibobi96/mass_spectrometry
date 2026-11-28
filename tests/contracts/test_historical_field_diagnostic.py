"""Historical field sweep Store analysis from authenticated inert records."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.backends.simion.native_completion import retention_api
from msplatform.execution.manifest_publication import publish_run_manifest
from msplatform.storage.store import ArtifactStore
from msplatform.workflows.historical_field_diagnostic import analyze_recorded_field_sweep
from tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_ideal_field_diagnostic_runner import sweep_source_fixture


def sealed_sweep(root):
    source, _ = sweep_source_fixture(root)
    def event(index, radius):
        return f'TRACE: detector_crossing ion={index} t={index + 1} x=1 y=2 z=3 r={radius} zmax=4\n'
    (source/'logs/actual.log').write_text(event(1, 1) + event(2, 45), encoding='utf8')
    (source/'logs/ideal.log').write_text(event(1, 42) + event(2, 45), encoding='utf8')
    (source/'run_manifest.json').unlink()
    outputs = [source/'logs/actual.log', source/'logs/ideal.log', source/'simion/oatof_N2.ion']
    publish_run_manifest(source/'run_config.json', 'success', output_paths=outputs, retention_api=retention_api)
    return source


@unittest.skipUnless(__import__('os').name == 'nt', 'Windows historical OS guard required')
class HistoricalFieldDiagnosticTests(unittest.TestCase):
    def test_store_cold_read_same_cohort_zero_hit_and_source_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = sealed_sweep(root)
            before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            store = ArtifactStore(root/'new-store')
            import shutil
            original = shutil.copyfile
            blocked = []
            def copy_while_guarded(origin, target, *args, **kwargs):
                if Path(origin).name == 'actual.log':
                    with self.assertRaises(PermissionError):
                        Path(origin).unlink()
                    blocked.append(True)
                return original(origin, target, *args, **kwargs)
            with patch('msplatform.workflows.historical_field_diagnostic.shutil.copyfile', side_effect=copy_while_guarded):
                result = analyze_recorded_field_sweep(source_manifest=source/'run_manifest.json',
                                                      artifact_store=store, budget_bytes=4*1024*1024)
            self.assertEqual(blocked, [True])
            run = ArtifactStore(root/'new-store').inspect_run(result['store_run_id'])
            summary = json.loads((run/'summary.json').read_text(encoding='utf8'))
            self.assertNotIn('formal_eligible', summary)
            self.assertEqual([(x['case_id'], x['detected']) for x in summary['cases']], [('actual', 1), ('ideal', 0)])
            self.assertIsNone(summary['cases'][1]['mean_tof_us'])
            self.assertIsNone(summary['cases'][1]['tof_std_ns'])
            self.assertIsNone(summary['cases'][1]['solve_seconds'])
            self.assertEqual((run/'inputs/source.ion').read_bytes(), (source/'simion/oatof_N2.ion').read_bytes())
            self.assertEqual((run/'inputs/source_run_manifest.json').read_bytes(), (source/'run_manifest.json').read_bytes())
            self.assertEqual((run/'inputs/source_run_config.json').read_bytes(), (source/'run_config.json').read_bytes())
            self.assertEqual(before, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
            with store._db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)

    def test_source_count_mismatch_is_rejected_without_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = sealed_sweep(root)
            ion = source/'simion/oatof_N2.ion'
            ion.write_text('0,524,1,0,0,0,0,0,5,1,0\n', encoding='utf8')
            for case in ('actual', 'ideal'):
                log = source/'logs'/f'{case}.log'
                log.write_text('TRACE: detector_crossing ion=1 t=2 x=1 y=2 z=3 r=1 zmax=4\n', encoding='utf8')
            (source/'run_manifest.json').unlink()
            publish_run_manifest(source/'run_config.json', 'success',
                output_paths=[source/'logs/actual.log', source/'logs/ideal.log', ion], retention_api=retention_api)
            store = ArtifactStore(root/'new-store')
            with self.assertRaisesRegex(ValueError, 'particle count differs'):
                analyze_recorded_field_sweep(source_manifest=source/'run_manifest.json',
                                             artifact_store=store, budget_bytes=4*1024*1024)
            with store._db() as db:
                self.assertEqual(db.execute('SELECT status FROM run_execution').fetchone()[0], 'failed')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)

    def test_budget_exhaustion_is_failed_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = sealed_sweep(root)
            before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
            store = ArtifactStore(root/'new-store')
            with self.assertRaisesRegex(ValueError, 'growth exceeds reserved budget'):
                analyze_recorded_field_sweep(source_manifest=source/'run_manifest.json',
                                             artifact_store=store, budget_bytes=1)
            with store._db() as db:
                self.assertEqual(db.execute('SELECT status FROM run_execution').fetchone()[0], 'failed')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0], 0)
            self.assertEqual(before, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})

    def test_unsealed_or_tampered_input_never_publishes(self):
        for condition in ('failed', 'interrupted', 'tampered', 'missing'):
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = sealed_sweep(root)
                manifest = source/'run_manifest.json'
                if condition in ('failed', 'interrupted'):
                    payload = json.loads(manifest.read_text(encoding='utf8'))
                    payload['status'] = condition
                    manifest.write_text(json.dumps(payload), encoding='utf8')
                elif condition == 'tampered':
                    (source/'logs/actual.log').write_text('tampered', encoding='utf8')
                else:
                    (source/'logs/actual.log').unlink()
                before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
                store = ArtifactStore(root/'new-store')
                with self.assertRaises((ValueError, FileNotFoundError)):
                    analyze_recorded_field_sweep(source_manifest=manifest, artifact_store=store, budget_bytes=4*1024*1024)
                self.assertEqual(before, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
                with store._db() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 0)
