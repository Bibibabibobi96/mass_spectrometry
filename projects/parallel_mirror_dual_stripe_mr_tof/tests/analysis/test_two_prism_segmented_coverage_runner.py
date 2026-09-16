from pathlib import Path
import unittest


RUNNER = Path(__file__).parents[2] / "analysis" / "run_two_prism_segmented_coverage.ps1"


class TwoPrismSegmentedCoverageRunnerTests(unittest.TestCase):
    def test_runner_uses_managed_resource_and_artifact_facades(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("New-RunPackage", text)
        self.assertIn("Enter-HostExecutionLease -Role GATE -Stage theory_compute", text)
        self.assertIn("Invoke-ArtifactCapacityGate", text)
        self.assertIn("Apply-RunArtifactRetention", text)
        self.assertIn("Write-VerifiedRunManifest", text)
        self.assertIn("Complete-FailedRun", text)
        self.assertIn("Test-RunFilesIdentical", text)
        self.assertIn("common\\host_resource_python.py", text)
        self.assertIn("common\\host_resource_python.ps1", text)
        self.assertIn("common\\host_resource_scheduler.py", text)
        self.assertIn("common\\host_resource_policy.json", text)
        self.assertNotIn("SIMION", text)

    def test_scientific_controls_are_explicit_parameters(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        for name in (
            "P1MinimumV", "P1MaximumV", "P2MinimumV", "P2MaximumV",
            "SobolSampleCount", "WorkerCount", "RelativeTolerance",
            "MaximumStepMmPerSqrtV", "StageAMaximumReducedTimeMmPerSqrtV",
            "StageBMaximumReducedTimeMmPerSqrtV",
        ):
            self.assertIn("[Parameter(Mandatory)]", text)
            self.assertIn(f"${name}", text)

    def test_python_entry_requires_theory_compute_grant(self) -> None:
        source = (RUNNER.parent / "two_prism_segmented_coverage.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("ensure_heavy_entry(", source)
        self.assertIn('role="GATE", stage="theory_compute"', source)
        self.assertIn("MRTOF_TWO_PRISM_SEGMENTED_COVERAGE_ANALYSIS=PASS", source)

    def test_signed_local_voltage_lists_use_attached_option_values(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn('"--local-p1-values-v=$localP1"', text)
        self.assertIn('"--local-p2-values-v=$localP2"', text)
        self.assertNotIn("'--local-p2-values-v',$localP2", text)


if __name__ == "__main__":
    unittest.main()
