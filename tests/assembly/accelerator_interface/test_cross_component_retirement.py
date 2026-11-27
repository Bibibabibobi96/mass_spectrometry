"""Retired cross-component re-release fails before any native owner."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
RESOURCES = ROOT / 'src/msplatform/workflows/resources'


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 required')
class CrossComponentRetirementTests(unittest.TestCase):
    def test_measured_and_centroid_flights_refuse_before_owner(self):
        entry = RESOURCES / 'prepared_joint_execute.ps1'
        self.assertNotIn('PreparedSourceMode', entry.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source_mode in ('measured_population', 'centroid_probe'):
                result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(entry),
                    '-PreparedJointWorkbenchRunPath', str(root/'missing'), '-ContractPath', str(root/'contract'),
                    '-PreparedSourceMode', source_mode, '-RepoRoot', str(root)], cwd=root,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'artifacts').exists())
            for args in (('-AnalyzeRunPath', 'missing', '-ContractPath', 'missing'),
                         ('-ResumeFinalization', '-RunId', 'historical')):
                result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(entry),
                    *args, '-RepoRoot', str(root), '-PythonExe', str(root/'missing-python')], cwd=root,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('measured-population re-release is retired', result.stdout+result.stderr)

    def test_full_joint_option_is_absent_before_any_owner(self):
        entry = RESOURCES / 'accelerator_interface.ps1'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(entry),
                '-FullJoint', '-RepoRoot', str(root)], cwd=root, capture_output=True,
                text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FullJoint', result.stdout + result.stderr)
            self.assertFalse((root/'artifacts').exists())


if __name__ == '__main__':
    unittest.main()
