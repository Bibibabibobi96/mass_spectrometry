"""V1 COMSOL receipts remain authenticated after old execution is removed."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from msplatform.results.historical_mass_spectrum import _historical_comsol_completion


class RetiredComsolExecutionTests(unittest.TestCase):
    def test_historical_completion_authentication_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            completion = Path(temp) / 'completion.json'
            receipt = {'schema_version': 1, 'role': 'comsol_launcher_completion', 'run_id': 'old-run',
                'operations': [{'observation': {'exit_confirmed': True, 'process_id': 123,
                                                'process_started_at_utc_ticks': 456, 'returncode': 0}}],
                'host_release': {'inherited': False, 'error': None, 'token': 't',
                                 'result': {'status': 'released', 'token': 't'}}}
            completion.write_text(json.dumps(receipt), encoding='utf8')
            self.assertEqual(_historical_comsol_completion(completion, run_id='old-run')['run_id'], 'old-run')
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                _historical_comsol_completion(completion, run_id='other')
            receipt['host_release']['error'] = 'unknown'
            completion.write_text(json.dumps(receipt), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'release remains unknown'):
                _historical_comsol_completion(completion, run_id='old-run')
            del receipt['host_release']['inherited']
            receipt['host_release']['error'] = None
            completion.write_text(json.dumps(receipt), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'release remains unknown'):
                _historical_comsol_completion(completion, run_id='old-run')

    def test_old_execution_module_is_absent(self):
        self.assertIsNone(importlib.util.find_spec('msplatform.backends.comsol.oatof_retrace'))
