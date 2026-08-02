from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_GATE = REPO_ROOT / "integrations" / Path(__file__).resolve().parents[1].name / "verify_integration.ps1"


class IntegrationGateFailureTests(unittest.TestCase):
    def test_failing_unittest_never_prints_pass(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        with tempfile.TemporaryDirectory(dir=REPO_ROOT.parent) as directory:
            root = Path(directory)
            integration = root / "integrations" / "fixture_integration"
            tests = integration / "tests"
            common_integration = root / "common" / "integration"
            tests.mkdir(parents=True)
            common_integration.mkdir(parents=True)
            shutil.copy2(SOURCE_GATE, integration / "verify_integration.ps1")
            (common_integration / "fixture.py").write_text(
                "VALUE = 1\n", encoding="utf-8"
            )
            (tests / "test_failure.py").write_text(
                "import unittest\n\n"
                "class FailureTest(unittest.TestCase):\n"
                "    def test_failure(self):\n"
                "        self.fail('intentional gate failure')\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(integration / "verify_integration.ps1"),
                    "-PythonExe",
                    sys.executable,
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=60,
            )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0, output)
        self.assertNotIn("INTEGRATION_GATE=PASS", output)
        self.assertIn("integration tests failed", output)


if __name__ == "__main__":
    unittest.main()
