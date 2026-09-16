from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "run_single_center_timestep_convergence.ps1"
)


class SingleCenterTimestepConvergenceRunnerTest(unittest.TestCase):
    def test_managed_runner_freezes_and_verifies_three_source_runs(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "[ValidateCount(3,3)]",
            "verify_run_manifest.py",
            "--require-mode finite_3d_two_prism_voltage_trial",
            "Copy-VerifiedRunInput",
            "single_center_timestep_convergence",
            "acceptance_threshold=$null",
            "Apply-RunArtifactRetention",
            "Invoke-ArtifactCapacityGate",
            "Write-VerifiedRunManifest",
        ):
            self.assertIn(token, source)
        self.assertNotIn("SIMION.exe", source)
        self.assertNotIn("refine", source.lower())


if __name__ == "__main__":
    unittest.main()
