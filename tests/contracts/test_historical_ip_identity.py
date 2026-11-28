"""Historical identities are read as recorded, never enabled for new runs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.assembly.ip_mr_connection import validate_component_exit_binding
from msplatform.results.ip_continuation import continuation_ancestry, continuation_protection_paths


class HistoricalIpIdentityTests(unittest.TestCase):
    def test_component_exit_accepts_exact_historical_and_current_identity(self):
        record = dict(schema_version=2, role='ion_processor_component_exit_export', status='prepared',
                      source_project='dual_pressure_rectilinear_ion_processor',
                      source_instance_id='ip-1', target_instance_id='mr-1')
        before = copy.deepcopy(record)
        self.assertEqual(validate_component_exit_binding(record), ('ip-1', 'mr-1'))
        self.assertEqual(record, before)
        current = dict(record, source_project='ion_processor')
        self.assertEqual(validate_component_exit_binding(current), ('ip-1', 'mr-1'))
        for bad in (dict(record, source_project='unknown'), dict(record, schema_version=1),
                    dict(record, role='other'), dict(record, schema_version=2.0),
                    dict(record, target_instance_id='ip-1')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_component_exit_binding(bad)

    def test_ancestry_requires_explicit_history_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run-old'
            run.mkdir()
            manifest = run / 'run_manifest.json'
            original = json.dumps(dict(schema_version=2, role='simulation_run_manifest',
                                       project='dual_pressure_rectilinear_ion_processor',
                                       mode='native_electrode_functional', run_id=run.name,
                                       status='success', inputs={})).encode()
            manifest.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                continuation_ancestry(run)
            self.assertEqual(continuation_ancestry(run, historical=True), [run.resolve()])
            self.assertEqual(continuation_protection_paths(run, historical=True), [run.resolve()])
            self.assertEqual(manifest.read_bytes(), original)
            invalid = json.loads(original)
            for field, value in (('schema_version', 2.0), ('role', 'other'), ('mode', 'other')):
                tampered = dict(invalid, **{field: value})
                manifest.write_text(json.dumps(tampered), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'identity differs'):
                    continuation_ancestry(run, historical=True)
            current = json.loads(original)
            current['project'] = 'ion_processor'
            manifest.write_text(json.dumps(current), encoding='utf-8')
            self.assertEqual(continuation_ancestry(run), [run.resolve()])
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                continuation_ancestry(run, historical=True)
