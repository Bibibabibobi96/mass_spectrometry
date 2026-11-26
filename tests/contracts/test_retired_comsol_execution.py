"""Retired OA–TOF execution rejects before acquiring native resources."""
import inspect
import subprocess
import unittest
from pathlib import Path

from msplatform.backends.comsol.oatof_retrace import run_species_retrace

ROOT = Path(__file__).resolve().parents[2]


class RetiredComsolExecutionTests(unittest.TestCase):
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
