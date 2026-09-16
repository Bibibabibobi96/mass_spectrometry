from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


RUNNER = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "run_r27_source_return_correlation.ps1"
)


class R27SourceReturnCorrelationRunnerTests(unittest.TestCase):
    def test_managed_runner_is_analysis_only_and_complete(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "[Parameter(Mandatory)][string]$R27RunPath",
            "common\\contracts\\run_artifact_support.ps1",
            "verify_run_manifest.py",
            "--require-mode finite_3d_two_prism_voltage_trial",
            "Copy-VerifiedRunInput",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "r27_source_return_correlation",
            "acceptance_threshold=$null",
            "source_filtering='forbidden'",
            "solver_execution='none'",
            "[IO.File]::WriteAllText($log,'',",
            "$failureStage='publish_success_manifest'",
        ):
            self.assertIn(token, source)
        self.assertNotIn("SIMION.exe", source)
        self.assertNotIn("refine", source.lower())

    def test_runner_has_valid_powershell_syntax(self) -> None:
        command = (
            "$errors=$null;$tokens=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{RUNNER}',[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count){$errors|ForEach-Object{$_.Message};exit 1}"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            cwd=RUNNER.parents[4],
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
