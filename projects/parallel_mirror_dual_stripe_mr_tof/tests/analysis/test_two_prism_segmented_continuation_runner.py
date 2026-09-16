from pathlib import Path
import re
import unittest


RUNNER = (
    Path(__file__).parents[2]
    / "analysis"
    / "run_two_prism_segmented_continuation.ps1"
)


class TwoPrismSegmentedContinuationRunnerTests(unittest.TestCase):
    def test_runner_consumes_only_the_parent_coverage_run_for_physical_inputs(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[Parameter(Mandatory)][string]$CoverageRunManifest", text)
        self.assertIn(
            "[ValidateSet('angle_then_y','y_then_angle_diagnostic')][string]$SolveMode",
            text,
        )
        self.assertNotIn("[Parameter(Mandatory)][string]$ExactKRunManifest", text)
        self.assertNotIn("[Parameter(Mandatory)][string]$StripeSeedRunManifest", text)
        self.assertNotIn("[Parameter(Mandatory)][string]$AcceleratorExitRunManifest", text)
        for record_name in (
            "downstream_contract",
            "parent_exact_k_run_manifest",
            "parent_stripe_seed_run_manifest",
            "accelerator_exit_observation",
            "accelerator_exit_source_receipt",
        ):
            self.assertIn(f"-Name '{record_name}'", text)
        self.assertIn("two_prism_segmented_voltage_branch_coverage", text)
        self.assertIn("coverage_manifest_verification.log", text)
        self.assertIn("parent_coverage_summary.json", text)

    def test_every_continuation_and_transport_control_is_mandatory(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        mandatory_names = (
            "ExpectedTopologySignatureSha256",
            "InitialP1V", "InitialP2LowerV", "InitialP2UpperV",
            "P1MinimumV", "P1MaximumV", "P2MinimumV", "P2MaximumV",
            "AngleToleranceDeg", "PositiveMirrorTurnYToleranceMm", "P2RootToleranceV",
            "InitialP1StepV", "MinimumP1StepV", "MaximumP1StepV",
            "P1StepGrowthFactor", "P2InitialHalfWidthV",
            "P2BracketExpansionFactor", "P2BracketMaximumExpansions",
            "MaximumInnerIterations", "MaximumOuterIterations",
            "MaximumTransportEvaluations", "MaximumNodesPerDirection",
            "RelativeTolerance", "AbsoluteTolerance", "MaximumStepMmPerSqrtV",
            "EventSamplesPerStep", "RootTimeToleranceMmPerSqrtV",
            "BoundaryRootToleranceMm", "MomentumToleranceSqrtV",
            "NormalEnergyToleranceV", "MaximumSteps",
            "StageAMaximumReducedTimeMmPerSqrtV",
            "StageBMaximumReducedTimeMmPerSqrtV",
        )
        for name in mandatory_names:
            self.assertRegex(
                text,
                rf"\[Parameter\(Mandatory\)\]\[[^]]+\]\${re.escape(name)}\b",
                msg=name,
            )
            self.assertIn(f"${name}", text)

    def test_runner_freezes_lineage_sources_and_uses_managed_facades(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "New-RunPackage",
            "Copy-VerifiedRunInput",
            "Assert-VerifiedRunRecordHash",
            "Test-RunFilesIdentical",
            "Enter-HostExecutionLease -Role GATE -Stage theory_compute",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "Complete-FailedRun",
            "two_prism_segmented_voltage_continuation.py",
            "two_prism_segmented_coverage.py",
            "two_prism_segmented_transport.py",
            "common\\host_resource_python.py",
            "common\\host_execution_lease.ps1",
        ):
            self.assertIn(token, text)
        self.assertNotIn("SIMION", text)
        self.assertIn("Split-Path -Parent $coverageManifest", text)

    def test_runner_forwards_all_controls_to_the_existing_python_cli(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        for argument in (
            "--coverage-summary",
            "--solve-mode",
            "--expected-topology-signature-sha256",
            "--initial-p1-v", "--initial-p2-lower-v", "--initial-p2-upper-v",
            "--p1-min-v", "--p1-max-v", "--p2-min-v", "--p2-max-v",
            "--angle-tolerance-deg", "--positive-turn-y-tolerance-mm", "--p2-root-tolerance-v",
            "--initial-p1-step-v", "--minimum-p1-step-v", "--maximum-p1-step-v",
            "--p1-step-growth-factor", "--p2-initial-half-width-v",
            "--p2-bracket-expansion-factor", "--p2-bracket-maximum-expansions",
            "--maximum-inner-iterations", "--maximum-outer-iterations",
            "--maximum-transport-evaluations", "--maximum-nodes-per-direction",
            "--relative-tolerance", "--absolute-tolerance", "--max-step",
            "--event-samples-per-step", "--root-time-tolerance",
            "--boundary-root-tolerance", "--momentum-tolerance",
            "--normal-energy-tolerance", "--maximum-steps",
            "--stage-a-maximum-reduced-time", "--stage-b-maximum-reduced-time",
        ):
            self.assertIn(f"'{argument}'", text)

    def test_python_entry_remains_the_only_heavy_scientific_operation(self) -> None:
        text = RUNNER.read_text(encoding="utf-8-sig")
        self.assertEqual(text.count("Enter-HostExecutionLease -Role GATE -Stage theory_compute"), 1)
        source = (RUNNER.parent / "two_prism_segmented_voltage_continuation.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("ensure_heavy_entry(", source)
        self.assertIn('role="GATE", stage="theory_compute"', source)
        self.assertIn("MRTOF_TWO_PRISM_SEGMENTED_CONTINUATION=PASS", source)
        self.assertIn(
            "stripe_biases, slow_energy, target_tangent_ratio, stripe_identity = _load_stripe_seed(",
            source,
        )
        self.assertIn('"target_tangent_ratio": target_tangent_ratio', source)


if __name__ == "__main__":
    unittest.main()
