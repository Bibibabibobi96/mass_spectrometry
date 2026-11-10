"""Table-driven source contracts for the bounded two-prism workflows."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
ANALYSIS = PROJECT / "analysis"


PRISM_CASES = {
    "segmented_coverage": {
        "runner": "run_two_prism_segmented_coverage.ps1",
        "required": (
            "Copy-VerifiedRunInput",
            "Assert-VerifiedRunRecordHash",
            "Test-RunFilesIdentical",
            "Enter-HostExecutionLease -Role GATE -Stage theory_compute",
            "Register-HostResourceProcess", "Wait-HostResourceProcess",
            "-ResourceLease $lease",
            "Apply-RunArtifactRetention",
            "Complete-FailedRun",
            "two_prism_segmented_coverage.py",
            "common\\host_resource_python.py",
            "common\\host_resource_python.ps1",
            "common\\host_resource_scheduler.py",
            "src\\msplatform\\execution\\resources\\host_resource_policy.json",
            "FixedMirrorStripeRunManifest",
            "--fixed-mirror-stripe-manifest",
            "contract_current_initial_search_window",
            "Supply all four P1/P2 bound overrides, or omit all four",
            '"--local-p1-values-v=$localP1"',
            '"--local-p2-values-v=$localP2"',
            "unconsumed_records_not_asserted",
        ),
        "mandatory": (
            "SobolSampleCount", "WorkerCount", "RelativeTolerance",
            "MaximumStepMmPerSqrtV", "StageAMaximumReducedTimeMmPerSqrtV",
            "StageBMaximumReducedTimeMmPerSqrtV",
        ),
        "forbidden": (
            "SIMION", "'--local-p2-values-v',$localP2",
            "msplatform.execution.manifest_verification',$exitManifest",
        ),
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
            "Register-HostResourceProcess", "Wait-HostResourceProcess",
            "-ResourceLease $lease",
            "two_prism_segmented_voltage_continuation.py",
            "two_prism_segmented_coverage.py", "two_prism_segmented_transport.py",
            "--coverage-summary", "--solve-mode", "--expected-topology-signature-sha256",
            "--auto-select-initial-bracket",
            "--initial-p1-v", "--initial-p2-lower-v", "--initial-p2-upper-v",
            "--p1-min-v", "--p1-max-v", "--p2-min-v", "--p2-max-v",
            "--angle-tolerance-deg", "--positive-turn-y-tolerance-mm",
            "--p2-root-tolerance-v", "--maximum-inner-iterations",
            "--maximum-outer-iterations", "--maximum-transport-evaluations",
            "--normal-energy-tolerance", "--stage-a-maximum-reduced-time",
            "--stage-b-maximum-reduced-time",
        ),
        "mandatory": (
            "AngleToleranceDeg", "PositiveMirrorTurnYToleranceMm",
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
            "integrations/workflows/oa_mr/execute.ps1", "NativeCorridorBankRunPath is required",
            "NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.",
            "NativeCorridorRuntimeSession=$nativeRuntimeSession",
            "Stripe1VoltageV=$Voltages[0]", "Prism1VoltageV=$prisms[0]",
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


    def test_segmented_declared_sources_copy_the_exact_prism_triad(self) -> None:
        """Exercise actual source-list/Copy-VerifiedRunInput transport, not a solver."""
        powershell = shutil.which("pwsh")
        if not powershell:
            self.skipTest("PowerShell 7 required")
        expected_runner_names = ("run_two_prism_segmented_coverage.ps1",
                                 "run_two_prism_segmented_continuation.ps1")
        repository = PROJECT.parents[1]
        harness = r"""param($Repository,$Output)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$support=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repository 'common/contracts/run_artifact_support.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Public input-copy source parse failed'}
$copy=@($support.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Copy-VerifiedRunInput'},$true))
if($copy.Count-ne1){throw 'Public input-copy function must be unique'}
. ([scriptblock]::Create($copy[0].Extent.Text))
$reports=@()
foreach($name in @('run_two_prism_segmented_coverage.ps1','run_two_prism_segmented_continuation.ps1')){
 $tokens=$null;$errors=$null
 $tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repository ('projects/parallel_mirror_dual_stripe_mr_tof/analysis/'+$name)),[ref]$tokens,[ref]$errors)
 if($errors.Count){throw 'Actual runner parse failed'}
 $lists=@($tree.FindAll({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$sourcePaths'},$true))
 $copies=@($tree.FindAll({param($n)$n-is[Management.Automation.Language.ForStatementAst]-and$n.Extent.Text.Contains('Copy-VerifiedRunInput -Source $source -Destination $destination')},$true))
 if($lists.Count-ne1-or$copies.Count-ne1){throw 'Actual source declaration/copy boundary must be unique'}
 . ([scriptblock]::Create($lists[0].Extent.Text))
 $repoRoot=$Repository;$sourceDir=Join-Path $Output $name
 New-Item -ItemType Directory -Path $sourceDir|Out-Null
 $sourceInputs=[ordered]@{};$sourceChecks=@()
 . ([scriptblock]::Create($copies[0].Extent.Text))
 $rows=@()
 for($index=0;$index-lt$sourcePaths.Count;$index++){
  $key='analytic_source_{0:D2}'-f($index+1)
  $rows+=@{relative=$sourcePaths[$index];key=$key;frozen=$sourceInputs[$key];source=$sourceChecks[$index].source;checked_frozen=$sourceChecks[$index].frozen;sha256=(Get-FileHash -LiteralPath $sourceInputs[$key] -Algorithm SHA256).Hash}
 }
 $reports+=@{runner=$name;paths=@($sourcePaths);input_count=$sourceInputs.Count;check_count=$sourceChecks.Count;rows=$rows}
}
ConvertTo-Json -InputObject @($reports) -Depth 8 -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "actual-source-copy.ps1"
            script.write_text(harness, encoding="utf-8")
            completed = subprocess.run([powershell, "-NoProfile", "-File", str(script),
                str(repository), str(root)], cwd=repository, capture_output=True,
                text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            reports = json.loads(completed.stdout)
            self.assertEqual({row["runner"] for row in reports}, set(expected_runner_names))
            for report in reports:
                with self.subTest(runner=report["runner"]):
                    paths = report["paths"]
                    self.assertEqual(paths[-2:], [
                        "src\\msplatform\\components\\parallel_mirror_dual_stripe_mr_tof\\prism_analytic.py",
                        "src\\msplatform\\components\\parallel_mirror_dual_stripe_mr_tof\\prism_l0.py"])
                    self.assertEqual(report["input_count"], len(paths))
                    self.assertEqual(report["check_count"], len(paths))
                    self.assertEqual(len(report["rows"]), len(paths))
                    for index, row in enumerate(report["rows"], 1):
                        source = repository / row["relative"]
                        frozen = Path(row["frozen"])
                        self.assertEqual(row["key"], f"analytic_source_{index:02d}")
                        self.assertEqual(Path(row["source"]), source)
                        self.assertEqual(row["checked_frozen"], row["frozen"])
                        self.assertEqual(frozen.name, f"source_{index:02d}" + source.suffix)
                        self.assertEqual(frozen.read_bytes(), source.read_bytes())
                        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), row["sha256"].lower())
                    for name in ("prism_l0", "prism_analytic", "drift_phase_contract"):
                        selected = "src\\msplatform\\components\\parallel_mirror_dual_stripe_mr_tof\\" + name + ".py"
                        self.assertEqual(paths.count(selected), 1)



if __name__ == "__main__":
    unittest.main()
