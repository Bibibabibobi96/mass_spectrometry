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
    def test_old_joint_execution_owner_and_admission_are_absent(self):
        import importlib.util
        from msplatform.workflows.historical_joint_analysis import publish_joint_analysis

        self.assertFalse((RESOURCES / 'prepared_joint_execute.ps1').exists())
        self.assertIsNone(importlib.util.find_spec('msplatform.workflows.prepared_joint'))
        self.assertTrue(callable(publish_joint_analysis))

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
