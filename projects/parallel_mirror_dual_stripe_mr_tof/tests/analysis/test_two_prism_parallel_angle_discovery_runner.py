from pathlib import Path
import re
import unittest


RUNNER = (
    Path(__file__).parents[2]
    / "analysis"
    / "run_two_prism_parallel_angle_discovery.ps1"
)


class TwoPrismParallelAngleDiscoveryRunnerTests(unittest.TestCase):
    def test_runner_derives_physical_inputs_only_from_parent_coverage(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[Parameter(Mandatory)][string]$CoverageRunManifest", text)
        for forbidden in (
            "$ExactKRunManifest",
            "$StripeSeedRunManifest",
            "$AcceleratorExitRunManifest",
        ):
            self.assertNotIn(forbidden, text)
        for record_name in (
            "downstream_contract",
            "parent_exact_k_run_manifest",
            "parent_stripe_seed_run_manifest",
            "accelerator_exit_observation",
            "accelerator_exit_source_receipt",
        ):
            self.assertIn(f"-Name '{record_name}'", text)
        self.assertIn("two_prism_segmented_voltage_branch_coverage", text)

    def test_discovery_and_transport_controls_are_explicit(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        for name in (
            "P1MinimumV", "P1MaximumV", "AnchorCount", "WorkerCount",
            "AngleRatioRootTolerance", "P2RootToleranceV",
            "TopologyBoundaryToleranceV", "MaximumSliceEvaluations",
            "RelativeTolerance", "AbsoluteTolerance", "MaximumStepMmPerSqrtV",
            "EventSamplesPerStep", "RootTimeToleranceMmPerSqrtV",
            "BoundaryRootToleranceMm", "MomentumToleranceSqrtV",
            "NormalEnergyToleranceV", "MaximumSteps",
            "StageAMaximumReducedTimeMmPerSqrtV",
            "StageBMaximumReducedTimeMmPerSqrtV",
        ):
            self.assertRegex(
                text,
                rf"\[Parameter\(Mandatory\)\]\[[^]]+\]\${re.escape(name)}\b",
                msg=name,
            )

    def test_runner_uses_managed_lineage_resource_and_artifact_facades(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "New-RunPackage",
            "Get-VerifiedRunManifestInputRecord",
            "Assert-VerifiedRunRecordHash",
            "Copy-VerifiedRunInput",
            "Test-RunFilesIdentical",
            "Enter-HostExecutionLease -Role GATE -Stage theory_compute",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "Complete-FailedRun",
        ):
            self.assertIn(token, text)
        self.assertNotIn("SIMION", text)

    def test_runner_forwards_parallel_slice_controls(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        for argument in (
            "--coverage-summary", "--p1-min-v", "--p1-max-v",
            "--anchor-count", "--worker-count",
            "--angle-ratio-root-tolerance", "--p2-root-tolerance-v",
            "--topology-boundary-tolerance-v", "--maximum-slice-evaluations",
            "--relative-tolerance", "--absolute-tolerance", "--max-step",
            "--event-samples-per-step", "--root-time-tolerance",
            "--boundary-root-tolerance", "--momentum-tolerance",
            "--normal-energy-tolerance", "--maximum-steps",
            "--stage-a-maximum-reduced-time", "--stage-b-maximum-reduced-time",
        ):
            self.assertIn(f"'{argument}'", text)

    def test_python_entry_is_the_only_heavy_scientific_operation(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        self.assertEqual(
            text.count("Enter-HostExecutionLease -Role GATE -Stage theory_compute"),
            1,
        )
        source = (RUNNER.parent / "two_prism_parallel_angle_discovery.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("ensure_heavy_entry(", source)
        self.assertIn('role="GATE", stage="theory_compute"', source)


if __name__ == "__main__":
    unittest.main()
