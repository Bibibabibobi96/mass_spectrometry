"""Table-driven source contracts for the bounded two-prism workflows."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
ANALYSIS = PROJECT / "analysis"


PRISM_CASES = {
    "segmented_coverage": {
        "runner": "run_two_prism_segmented_coverage.ps1",
        "required": (
            "Copy-VerifiedRunInput",
            "Test-RunFilesIdentical",
            "Enter-HostExecutionLease -Role GATE -Stage theory_compute",
            "Apply-RunArtifactRetention",
            "Complete-FailedRun",
            "two_prism_segmented_coverage.py",
            "common\\host_resource_python.py",
            "common\\host_resource_python.ps1",
            "common\\host_resource_scheduler.py",
            "common\\host_resource_policy.json",
            "FixedMirrorStripeRunManifest",
            "--fixed-mirror-stripe-manifest",
            "contract_current_initial_search_window",
            "Supply all four P1/P2 bound overrides, or omit all four",
            '"--local-p1-values-v=$localP1"',
            '"--local-p2-values-v=$localP2"',
        ),
        "mandatory": (
            "SobolSampleCount", "WorkerCount", "RelativeTolerance",
            "MaximumStepMmPerSqrtV", "StageAMaximumReducedTimeMmPerSqrtV",
            "StageBMaximumReducedTimeMmPerSqrtV",
        ),
        "forbidden": ("SIMION", "'--local-p2-values-v',$localP2"),
    },
    "parallel_angle_discovery": {
        "runner": "run_two_prism_parallel_angle_discovery.ps1",
        "required": (
            "[Parameter(Mandatory)][string]$CoverageRunManifest",
            "Get-VerifiedRunManifestInputRecord",
            "Assert-VerifiedRunRecordHash",
            "Copy-VerifiedRunInput",
            "two_prism_segmented_voltage_branch_coverage",
            "--coverage-summary", "--p1-min-v", "--p1-max-v",
            "--anchor-count", "--worker-count", "--angle-ratio-root-tolerance",
            "--p2-root-tolerance-v", "--topology-boundary-tolerance-v",
            "--maximum-slice-evaluations", "--normal-energy-tolerance",
            "--stage-a-maximum-reduced-time", "--stage-b-maximum-reduced-time",
        ),
        "mandatory": (
            "P1MinimumV", "P1MaximumV", "AnchorCount", "WorkerCount",
            "AngleRatioRootTolerance", "P2RootToleranceV",
            "TopologyBoundaryToleranceV", "MaximumSliceEvaluations",
            "RelativeTolerance", "AbsoluteTolerance", "MaximumStepMmPerSqrtV",
            "EventSamplesPerStep", "RootTimeToleranceMmPerSqrtV",
            "BoundaryRootToleranceMm", "MomentumToleranceSqrtV",
            "NormalEnergyToleranceV", "MaximumSteps",
            "StageAMaximumReducedTimeMmPerSqrtV", "StageBMaximumReducedTimeMmPerSqrtV",
        ),
        "forbidden": ("$ExactKRunManifest", "$StripeSeedRunManifest", "$AcceleratorExitRunManifest", "SIMION"),
    },
    "segmented_continuation": {
        "runner": "run_two_prism_segmented_continuation.ps1",
        "required": (
            "[Parameter(Mandatory)][string]$CoverageRunManifest",
            "[ValidateSet('angle_then_y','y_then_angle_diagnostic')][string]$SolveMode",
            "downstream_contract", "accelerator_exit_observation",
            "accelerator_exit_source_receipt", "parent_fixed_mirror_stripe_run_manifest",
            "parent_exact_k_run_manifest", "parent_stripe_seed_run_manifest",
            "two_prism_segmented_voltage_branch_coverage",
            "coverage_manifest_verification.log", "parent_coverage_summary.json",
            "Copy-VerifiedRunInput", "Assert-VerifiedRunRecordHash",
            "two_prism_segmented_voltage_continuation.py",
            "two_prism_segmented_coverage.py", "two_prism_segmented_transport.py",
            "--coverage-summary", "--solve-mode", "--expected-topology-signature-sha256",
            "--initial-p1-v", "--initial-p2-lower-v", "--initial-p2-upper-v",
            "--p1-min-v", "--p1-max-v", "--p2-min-v", "--p2-max-v",
            "--angle-tolerance-deg", "--positive-turn-y-tolerance-mm",
            "--p2-root-tolerance-v", "--maximum-inner-iterations",
            "--maximum-outer-iterations", "--maximum-transport-evaluations",
            "--normal-energy-tolerance", "--stage-a-maximum-reduced-time",
            "--stage-b-maximum-reduced-time",
        ),
        "mandatory": (
            "ExpectedTopologySignatureSha256", "InitialP1V", "InitialP2LowerV",
            "InitialP2UpperV", "P1MinimumV", "P1MaximumV", "P2MinimumV",
            "P2MaximumV", "AngleToleranceDeg", "PositiveMirrorTurnYToleranceMm",
            "P2RootToleranceV", "InitialP1StepV", "MinimumP1StepV", "MaximumP1StepV",
            "P1StepGrowthFactor", "P2InitialHalfWidthV", "P2BracketExpansionFactor",
            "P2BracketMaximumExpansions", "MaximumInnerIterations", "MaximumOuterIterations",
            "MaximumTransportEvaluations", "MaximumNodesPerDirection", "RelativeTolerance",
            "AbsoluteTolerance", "MaximumStepMmPerSqrtV", "EventSamplesPerStep",
            "RootTimeToleranceMmPerSqrtV", "BoundaryRootToleranceMm",
            "MomentumToleranceSqrtV", "NormalEnergyToleranceV", "MaximumSteps",
            "StageAMaximumReducedTimeMmPerSqrtV", "StageBMaximumReducedTimeMmPerSqrtV",
        ),
        "forbidden": (
            "[Parameter(Mandatory)][string]$ExactKRunManifest",
            "[Parameter(Mandatory)][string]$StripeSeedRunManifest",
            "[Parameter(Mandatory)][string]$AcceleratorExitRunManifest",
            "SIMION",
        ),
    },
}


class PrismRunnerContractMatrixTests(unittest.TestCase):
    def test_segmented_runner_parameters_and_forwarding(self) -> None:
        for name, case in PRISM_CASES.items():
            with self.subTest(case=name):
                source = (ANALYSIS / case["runner"]).read_text(encoding="utf-8-sig")
                for token in case["required"]:
                    self.assertIn(token, source, token)
                for parameter in case["mandatory"]:
                    self.assertRegex(
                        source,
                        rf"\[Parameter\(Mandatory\)\]\[[^]]+\]\${re.escape(parameter)}\b",
                        parameter,
                    )
                for token in case.get("forbidden", ()):
                    self.assertNotIn(token, source, token)
                self.assertEqual(source.count("Enter-HostExecutionLease -Role GATE -Stage theory_compute"), 1)

    def test_all_declared_controls_reach_the_python_cli(self) -> None:
        common_transport = (
            "--relative-tolerance", "--absolute-tolerance", "--max-step",
            "--event-samples-per-step", "--root-time-tolerance",
            "--boundary-root-tolerance", "--momentum-tolerance",
            "--normal-energy-tolerance", "--maximum-steps",
            "--stage-a-maximum-reduced-time", "--stage-b-maximum-reduced-time",
        )
        cases = {
            "run_two_prism_parallel_angle_discovery.ps1": (
                "--coverage-summary", "--p1-min-v", "--p1-max-v", "--anchor-count",
                "--worker-count", "--angle-ratio-root-tolerance", "--p2-root-tolerance-v",
                "--topology-boundary-tolerance-v", "--maximum-slice-evaluations",
            ) + common_transport,
            "run_two_prism_segmented_continuation.ps1": (
                "--coverage-summary", "--solve-mode", "--expected-topology-signature-sha256",
                "--initial-p1-v", "--initial-p2-lower-v", "--initial-p2-upper-v",
                "--p1-min-v", "--p1-max-v", "--p2-min-v", "--p2-max-v",
                "--angle-tolerance-deg", "--positive-turn-y-tolerance-mm",
                "--p2-root-tolerance-v", "--initial-p1-step-v", "--minimum-p1-step-v",
                "--maximum-p1-step-v", "--p1-step-growth-factor", "--p2-initial-half-width-v",
                "--p2-bracket-expansion-factor", "--p2-bracket-maximum-expansions",
                "--maximum-inner-iterations", "--maximum-outer-iterations",
                "--maximum-transport-evaluations", "--maximum-nodes-per-direction",
            ) + common_transport,
        }
        for script, options in cases.items():
            source = (ANALYSIS / script).read_text(encoding="utf-8-sig")
            for option in options:
                with self.subTest(script=script, option=option):
                    self.assertIn(f"'{option}'", source)

    def test_heavy_python_entries_enforce_the_same_resource_stage(self) -> None:
        cases = (
            ("two_prism_segmented_coverage.py", "MRTOF_TWO_PRISM_SEGMENTED_COVERAGE_ANALYSIS=PASS"),
            ("two_prism_segmented_voltage_continuation.py", "MRTOF_TWO_PRISM_SEGMENTED_CONTINUATION=PASS"),
            ("two_prism_parallel_angle_discovery.py", None),
        )
        for script, marker in cases:
            with self.subTest(script=script):
                source = (ANALYSIS / script).read_text(encoding="utf-8-sig")
                self.assertIn("ensure_heavy_entry(", source)
                self.assertIn('role="GATE", stage="theory_compute"', source)
                if marker is not None:
                    self.assertIn(marker, source)
        continuation = (ANALYSIS / "two_prism_segmented_voltage_continuation.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("load_segmented_operating_authority(", continuation)
        self.assertIn('"target_tangent_ratio": target_tangent_ratio', continuation)

    def test_downstream_iteration_is_bounded_resumable_and_reuses_one_session(self) -> None:
        source = (ANALYSIS / "run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        for token in (
            "run_two_prism_trial.ps1", "NativeCorridorBankRunPath is required",
            "NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.",
            "NativeCorridorRuntimeSession=$nativeRuntimeSession",
            "Stripe1VoltageV=$Voltages[0]", "Prism1VoltageV=$Voltages[2]",
            "native_corridor_private_fast_adjust_family__four_instances__n1", "maximumIterations",
            "iteration_lineage.json", "parent_manifest=$previousManifest",
            "child_manifest_sha256", "iteration_{0:D2}_decision.json",
            "__sim__simion__mrtof-downstream-auto-workpoint",
            "$childRunId = '{0}-iter-{1:D2}'", "terminal_reason='solver_failure'",
            "Enter-ArtifactWorkflowCapacitySession", "CapacityWorkflowSession=$capacitySession",
            "Update-ArtifactWorkflowCapacitySession", "Exit-ArtifactWorkflowCapacitySession",
            "native_corridor_protection_renewal.json", "--cache-protection-renewal",
            "$operatingCacheKey = [string]$cacheBinding.cache_key",
            "ResumeSuccessfulChildManifest", "if (-not $resumeThisIteration)",
            "Child materialization does not match the controller's requested voltage vector",
            "ResumeParentCheckpoint", "$startIteration = [int]$checkpoint.next_iteration",
            "-RemainingCommittedNewBytes 0", "Write-VerifiedRunManifest",
        ):
            self.assertIn(token, source, token)
        for token in (
            "Refine-", "while ($true)", "__workflow__simion__",
            "Invoke-CapacityProtectionLease", "CapacityProtectionLeaseId=",
            "CapacityTargetGiB", "CapacityMinimumFreeGiB", "CapacityBaselineReceipt",
            "SupersededCacheAuthorization", "LocalWorkbenchRunPath",
            "LocalResponseFamilyRunPath", "LocalRegionOverrideWorkbenchRunPath",
            "LocalRegionOverrideRegions", "LocalHandoffSelectionRunPath",
            "RuntimeCentralStripeResponse", "BootstrapGlobalOperatingPa",
            "standalone_response_linear_composition__no_refine",
        ):
            self.assertNotIn(token, source, token)
        argument_binding = source.index("CapacityWorkflowSession=$capacitySession")
        loop = source.index("for ($iteration = $startIteration;")
        self.assertLess(argument_binding, loop)
        native_checkpoint = source.index("Save-NativeWorkflowCheckpoint -Reason", loop)
        native_release = source.index("Exit-ArtifactWorkflowCapacitySession", native_checkpoint)
        self.assertLess(native_checkpoint, native_release)
        terminal = source.index("$capacityTerminal = Update-ArtifactWorkflowCapacitySession")
        manifest = source.index("Write-VerifiedRunManifest", terminal)
        final_release = source.index("Exit-ArtifactWorkflowCapacitySession", manifest)
        self.assertLess(terminal, manifest)
        self.assertLess(manifest, final_release)


if __name__ == "__main__":
    unittest.main()
