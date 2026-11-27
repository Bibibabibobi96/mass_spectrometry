"""The dependency contract must reject ambiguous JSON before freezing inputs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 required')
class DependencyJsonKeysTests(unittest.TestCase):
    def test_current_contract_has_one_unambiguous_effective_closure(self):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate JSON key: ' + key)
                result[key] = value
            return result
        path = ROOT / 'src/msplatform/workflows/config/runtime_dependencies.json'
        document = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
        self.assertNotIn('single_reflection_flight', document['consumer_ids'])
        for group in document['providers']:
            for kind in ('python_packages', 'python_modules', 'files'):
                for row in group[kind]:
                    self.assertNotIn('single_reflection_flight', row['consumers'])
                    self.assertTrue(row['consumers'])
        packages = document['providers'][0]['python_packages']
        self.assertEqual([row['source_repo_path'] for row in packages], ['src/msplatform'])

    def test_named_loader_rejects_duplicate_before_any_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = root / 'contract.json'
            output = root / 'frozen'
            script = root / 'probe.ps1'
            script.write_text(r'''
. $env:DEP_SCRIPT
$doc = [System.Text.Json.JsonDocument]::Parse('{"a":{"same":1},"b":{"same":2}}')
try { Assert-WorkflowDependencyJsonUniqueKeys -Value $doc.RootElement } finally { $doc.Dispose() }
try {
  Freeze-ConsumerDependencies -Python $env:DEP_PYTHON -RepoRoot $env:DEP_REPO -ContractPath $env:DEP_CONTRACT `
    -InputDir $env:DEP_OUTPUT -OwnerId instrument_assembly -ConsumerId oa_mr
  throw 'duplicate was accepted'
} catch {
  if ($_.Exception.Message -notlike '*duplicate JSON key: python_packages*') { throw }
}
Write-Output 'DEPENDENCY_DUPLICATE_REJECTED=PASS'
''', encoding='utf-8')
            contract.write_text('{"providers":[{"python_packages":[],"python_packages":[]}]}', encoding='utf-8')
            environment = dict(os.environ, DEP_SCRIPT=str(ROOT / 'src/msplatform/execution/resources/dependencies.ps1'),
                DEP_PYTHON=sys.executable, DEP_REPO=str(ROOT), DEP_CONTRACT=str(contract), DEP_OUTPUT=str(output))
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-File', str(script)],
                cwd=root, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('DEPENDENCY_DUPLICATE_REJECTED=PASS', result.stdout)
            self.assertFalse(output.exists())
