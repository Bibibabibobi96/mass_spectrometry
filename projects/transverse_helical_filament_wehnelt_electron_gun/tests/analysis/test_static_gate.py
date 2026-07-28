"""Static integration checks for the public Wehnelt project gate."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]


class StaticGateTests(unittest.TestCase):
    """Keep the project gate on the repository runtime and CI path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.project_gate = (PROJECT_ROOT / "verify_project.ps1").read_text(
            encoding="utf-8"
        )
        cls.integration_gate = (
            REPO_ROOT / "common" / "verify_repository_integration.ps1"
        ).read_text(encoding="utf-8")

    def test_public_gate_requires_powershell_core_7(self) -> None:
        self.assertIn(
            ". (Join-Path $repoRoot 'common\\require_powershell7.ps1')",
            self.project_gate,
        )

    def test_public_gate_resolves_and_validates_one_python_311_runtime(self) -> None:
        resolve_index = self.project_gate.index(
            "$PythonExe = [IO.Path]::GetFullPath($PythonExe)"
        )
        location_index = self.project_gate.index("Push-Location $repoRoot")
        self.assertLess(resolve_index, location_index)
        self.assertIn(
            "Test-Path -LiteralPath $PythonExe -PathType Leaf",
            self.project_gate,
        )
        self.assertIn("$pythonVersion -ne '3.11'", self.project_gate)
        self.assertNotIn("Get-Command python", self.project_gate)
        self.assertIn(
            "-m projects.transverse_helical_filament_wehnelt_electron_gun.analysis.resolve_contract",
            self.project_gate,
        )

    def test_repository_integration_gate_runs_wehnelt_static_once(self) -> None:
        invocation = (
            "& (Join-Path $repoRoot "
            "'projects\\transverse_helical_filament_wehnelt_electron_gun"
            "\\verify_project.ps1') "
            "-PythonExe $PythonExe"
        )
        self.assertEqual(self.integration_gate.count(invocation), 1)


if __name__ == "__main__":
    unittest.main()
