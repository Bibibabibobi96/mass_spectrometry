"""Retired OA–TOF execution rejects before acquiring native resources."""
import inspect
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from msplatform.backends.comsol.oatof_retrace import run_species_retrace, verify_completed_species

ROOT = Path(__file__).resolve().parents[2]


class RetiredComsolExecutionTests(unittest.TestCase):
    def test_historical_species_authentication_survives_retirement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            completion = root / 'completion.json'
            report = root / 'report.txt'
            csv = root / 'particles.csv'
            completion.write_text(json.dumps({
                'schema_version': 1, 'role': 'comsol_launcher_completion', 'run_id': 'old-run',
                'operations': [{'observation': {'exit_confirmed': True, 'process_id': 123,
                                                'process_started_at_utc_ticks': 456, 'returncode': 0}}],
                'host_release': {'inherited': False, 'error': None, 'token': 't',
                                 'result': {'status': 'released', 'token': 't'}},
            }), encoding='utf-8')
            report.write_text('DETECTED=2/2\n', encoding='utf-8')
            csv.write_text('particle_id\n1\n2\n', encoding='utf-8')
            args = dict(run_id='old-run', particle_count=2, csv_path=csv,
                        report_path=report, completion_path=completion)
            self.assertEqual(verify_completed_species(**args)['receipt']['run_id'], 'old-run')
            report.write_text('DETECTED=1/2\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'lacks DETECTED=2/2'):
                verify_completed_species(**args)
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                verify_completed_species(**{**args, 'run_id': 'different'})
            receipt = json.loads(completion.read_text(encoding='utf-8'))
            receipt['host_release']['error'] = 'unknown'
            completion.write_text(json.dumps(receipt), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'release remains unknown'):
                verify_completed_species(**args)

    def test_python_retrace_rejects_before_accessing_owner(self):
        kwargs = {name: None for name, param in inspect.signature(run_species_retrace).parameters.items()
                  if param.kind == inspect.Parameter.KEYWORD_ONLY}
        with self.assertRaisesRegex(ValueError, 'retired.*msplatform run'):
            run_species_retrace(None, **kwargs)

    def test_formal_validate_rejects_before_resolving_paths(self):
        script = ROOT / 'src/msplatform/workflows/resources/run_formal_validation.ps1'
        result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(script),
                                 '-WorkspaceRoot', 'missing-workspace', '-ArtifactRootPath', 'missing-artifacts',
                                 '-ScienceRoot', 'missing-science', '-Phase', 'Validate'],
                                cwd=ROOT, timeout=15, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('retired', result.stderr)
        self.assertIn('msplatform run', result.stderr)
        self.assertNotIn('Cannot find path', result.stderr)


if __name__ == '__main__':
    unittest.main()
