from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
ENTRIES = {
    "candidate": "backends/simion/resources/register_candidate_layout_template.ps1",
    "multipole_template": "workflows/resources/register_simion_layout_template.ps1",
    "cross_solver": "workflows/resources/compare_cross_solver.ps1",
    "responses": "workflows/resources/compare_responses.ps1",
}


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class InstalledResourceEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.venv = cls.root / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(cls.venv)],
            cwd=cls.root,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        cls.python = cls.venv / "Scripts/python.exe"
        cls.package = cls.venv / "Lib/site-packages/msplatform"
        shutil.copytree(
            REPO / "src/msplatform",
            cls.package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        cls.workspace = cls.root / "workspace"
        cls.workspace.mkdir()
        cls.artifacts = cls.root / "artifacts"
        cls.caller = cls.root / "unrelated-caller"
        cls.caller.mkdir()
        poison = cls.root / "poison/msplatform"
        poison.mkdir(parents=True)
        (poison / "__init__.py").write_text(
            "raise RuntimeError('external PYTHONPATH was consumed')\n",
            encoding="utf-8",
        )
        cls.environment = {
            **os.environ,
            "PYTHONPATH": str(poison.parent),
            "SIMULATION_PYTHON_EXE": "",
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def invoke(self, name: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                shutil.which("pwsh") or "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(self.package / ENTRIES[name]),
                "-WorkspaceRoot",
                str(self.workspace),
                "-PythonExe",
                str(self.python),
                *arguments,
            ],
            cwd=self.caller,
            env=self.environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def assert_boundary(self, result: subprocess.CompletedProcess[str], sentinel: str) -> None:
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn(sentinel, output)
        self.assertNotIn("external PYTHONPATH was consumed", output)

    def test_comparison_entries_load_installed_support(self) -> None:
        support = self.package / "execution/resources/run_artifact_support.ps1"
        support.write_text("throw 'INSTALLED_COMPARISON_SUPPORT'\n", encoding="utf-8")
        cases = {
            "cross_solver": [
                "-Mode", "transport_interface_readiness",
                "-ComsolRunId", "unused", "-SimionRunId", "unused",
            ],
            "responses": [
                "-ComsolRunId", "unused", "-SimionRunId", "unused", "-L1RunId", "unused",
            ],
        }
        for name, arguments in cases.items():
            with self.subTest(entry=name):
                result = self.invoke(
                    name,
                    [*arguments, "-ArtifactRootPath", str(self.artifacts)],
                )
                self.assert_boundary(result, "INSTALLED_COMPARISON_SUPPORT")

    def test_compensation_uses_public_workflow_without_retired_powershell_entry(self) -> None:
        self.assertFalse((self.package / "workflows/resources/execute_oatof_compensation.ps1").exists())
        self.assertTrue((self.package / "workflows/reflectron_compensation.py").is_file())
        self.assertTrue((self.package / "analysis/reflectron_voltage_fit.py").is_file())

    def test_freezer_copies_actual_installed_sources(self) -> None:
        code_root = self.root / "frozen-installed"
        script = self.root / "freeze-installed.ps1"
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        script.write_text(
            "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n"
            f". {quote(self.package / 'execution/resources/frozen_python_package.ps1')}\n"
            f"$package=New-FrozenPythonPackage -Python {quote(self.python)} "
            f"-SourceRoot {quote(self.package.parent)} -CodeRoot {quote(code_root)} "
            "-PythonModules @('src/msplatform/workflows/rf_transport_comparison.py') "
            "-RelativePaths @('src/msplatform/contracts/particle_count_policy.json')\n"
            "Assert-FrozenPythonPackage -Package $package\n"
            "$module=Get-FrozenPythonPackageFile -Package $package "
            "-RelativePath 'src/msplatform/workflows/rf_transport_comparison.py'\n"
            "if(-not(Test-Path -LiteralPath $module -PathType Leaf)){throw 'Installed module was not frozen'}\n"
            "Write-Output 'INSTALLED_FREEZE_PASS'\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [shutil.which("pwsh") or "pwsh", "-NoProfile", "-NonInteractive", "-File", str(script)],
            cwd=self.caller,
            env=self.environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INSTALLED_FREEZE_PASS", result.stdout)
        self.assertTrue(
            (code_root / "src/msplatform/workflows/rf_transport_comparison.py").is_file()
        )

    def test_candidate_registration_reaches_installed_structure_verifier(self) -> None:
        verifier = self.package / "backends/simion/resources/verify_iob_runtime_contract.ps1"
        verifier.write_text("throw 'INSTALLED_CANDIDATE_VERIFIER'\n", encoding="utf-8")
        source = self.root / "candidate-source"
        source.mkdir()
        (source / "layout.iob").write_bytes(b"software fixture, not an IOB")
        (source / "layout.con").write_bytes(b"software fixture, not a CON")
        result = self.invoke(
            "candidate",
            [
                "-SourceIobPath", str(source / "layout.iob"),
                "-SourceConPath", str(source / "layout.con"),
                "-RunId", "20261124_120000__build__simion__template-registration",
                "-ArtifactProjectRoot", str(self.artifacts / "candidate"),
            ],
        )
        self.assert_boundary(result, "INSTALLED_CANDIDATE_VERIFIER")

    def test_multipole_registration_uses_isolated_installed_python(self) -> None:
        result = self.invoke(
            "multipole_template",
            [
                "-ConfirmGuiCreatedAndReopened",
                "-SourceIobPath", "unused.iob", "-SourceConPath", "unused.con",
                "-RunId", "20261124_120001__build__simion__template-registration",
                "-SimionExe", str(self.root / "missing-simion.exe"),
                "-ArtifactProjectRoot", str(self.artifacts / "multipole"),
            ],
        )
        self.assert_boundary(result, "SIMION executable is missing")


if __name__ == "__main__":
    unittest.main()
