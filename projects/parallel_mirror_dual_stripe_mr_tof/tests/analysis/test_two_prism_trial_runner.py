"""Native-only contract tests for the MR-TOF flight runner."""
from pathlib import Path
import json
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"

class TwoPrismTrialRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = RUNNER.read_text(encoding="utf-8")

    def test_requires_native_bank_and_system_bundle(self):
        self.assertIn("NativeCorridorBankRunPath is required for the native-only flight runner.", self.source)
        self.assertIn("NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_summary_preserves_nested_phase_space_acceptance_objects(self):
        acceptance = {
            "status": "evaluated__center_particle_only",
            "absolute_tolerance_per_charge_v": 0.05,
            "reference_provider_tolerance_per_charge_v": None,
            "within_tolerance": False,
        }
        value = {"cohort_analysis": {"prism_phase_space_diagnostic": {"surfaces": {
            "accelerator_safe_exit": {"kinetic_energy_per_charge": {
                "component_target_diagnostic": {"components": {
                    "Ex": {"acceptance": acceptance},
                    "Ey": {"acceptance": {**acceptance, "within_tolerance": True}},
                }}
            }}
        }}}}
        publication = next(
            line.strip() for line in self.source.splitlines()
            if line.strip().startswith("Write-RunJson -Path $summary ")
        )
        writer = RUNNER.parents[3] / "common/contracts/run_artifact_support.ps1"
        with TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            target = Path(directory) / "summary.json"
            source.write_text(json.dumps(value), encoding="utf-8")
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            command = (
                f". {quote(writer)}\n"
                f"$summaryValue=Get-Content -Raw -LiteralPath {quote(source)}|ConvertFrom-Json\n"
                f"$summary={quote(target)}\n{publication}"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=RUNNER.parent,
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8-sig")), value)

    def test_no_legacy_five_region_public_inputs_remain(self):
        for name in ("LocalWorkbenchRunPath", "LocalResponseFamilyRunPath",
                     "LocalRegionOverrideWorkbenchRunPath", "LocalRegionOverrideRegions",
                     "LocalHandoffSelectionRunPath", "RuntimeCentralStripeResponse",
                     "BootstrapGlobalOperatingPa", "localWorkbenchRun",
                     "useNativeCorridor", "hybridFixedResponseScreening",
                     "localOperatingCacheReceipt", "batchTemplateRecord"):
            self.assertNotIn(name, self.source)
        self.assertNotIn("basisLinkDir", self.source)

    def test_native_runtime_preserves_four_instance_and_bundle_identity(self):
        for token in ("build_native_corridor_iob.lua", "4_instance_seed.iob",
                      "native_system_runtime", "NativeCorridorRuntimeSession",
                      "native_corridor_private_fast_adjust_family"):
            self.assertIn(token, self.source)
        self.assertIn("$privateIobSeed=Join-Path $temporarySolverDir '4_instance_seed.iob'", self.source)
        self.assertIn("foreach($seedIndex in 2..4)", self.source)
        self.assertIn("New-Item -ItemType HardLink", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $privateSeedPlaceholder", self.source)
        self.assertIn("$nativeControllerForIob=[IO.Path]::GetFullPath([string]$nativeRuntime.receipt.controller_path)", self.source)
        self.assertIn("$privateIobSeed,$iobAnalyzerInput,$nativeControllerForIob", self.source)

    def test_standalone_n1_can_open_one_existing_native_checkpoint(self):
        self.assertIn("[string]$NativeRuntimeCheckpoint=''", self.source)
        self.assertIn(
            "Supply NativeCorridorRuntimeSession or NativeRuntimeCheckpoint, not both.",
            self.source,
        )
        self.assertIn("directory=[IO.Path]::GetFullPath([string]$checkpoint.directory)", self.source)
        self.assertIn("checkpoint_path=$nativeRuntimeCheckpointPath", self.source)

    def test_checkpoint_is_opened_before_capacity_peak_is_computed(self):
        opened = self.source.index("Open-NativeCorridorRuntimeCheckpoint")
        peak = self.source.index("$nativeFamilyPeakBytes=10*")
        self.assertLess(opened, peak)
        self.assertIn("$NativeCorridorRuntimeSession.resident_bytes-gt0", self.source)

    def test_global_fallback_identity_is_reused_without_an_extra_full_hash(self):
        self.assertIn(
            "$voltageSourceHash=[string]$globalFallbackRecord.sha256", self.source
        )
        self.assertNotIn(
            "Get-FileHash -LiteralPath $globalFallbackAnalyzer", self.source
        )

    def test_shared_runtime_retains_small_gui_workbench_under_compact_policy(self):
        for token in (
            "[switch]$RetainGuiWorkbench",
            "-RetentionContractEnabled -RetentionClass compact",
            "$retainGuiWorkbenchFiles=$null-ne$NativeCorridorRuntimeSession",
            "Join-Path $artifactSolverDir 'gui_workbench'",
            "Retained GUI workbench native checkpoint controller is missing.",
            "PA payloads have already been bound through the runtime and published",
            "pa_dependencies=$guiPaDependencies",
            "Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp'",
        ):
            self.assertIn(token, self.source)
        self.assertNotIn("-RetentionClass solver_review", self.source)
        self.assertIn("if($retainGuiWorkbenchFiles){", self.source)
        self.assertNotIn("Join-Path $temporarySolverDir 'pa_inputs'", self.source)
        self.assertNotIn("simion_pa_links_", self.source)
        self.assertNotIn("iobInputCopyDir", self.source)
        self.assertIn("$privateIobSeed,", self.source)
        self.assertIn(
            "if($RetainGuiWorkbench-and$null-eq$NativeCorridorRuntimeSession)",
            self.source,
        )
        self.assertIn(
            "standalone retention would duplicate the complete PA family",
            self.source,
        )

    def test_retained_gui_rebinds_shared_runtime_to_persistent_checkpoint(self):
        self.assertIn(
            "Join-Path ([string]$NativeCorridorRuntimeSession.directory) 'mrtof_analyzer_corridor.pa0'",
            self.source,
        )
        self.assertIn("-Stage 'rebind_retained_gui_iob'", self.source)
        self.assertIn("$nativeRuntime.controller_path=$stableNativeController", self.source)
        self.assertIn(
            "$privateIobSeed,$globalFallbackAnalyzer,$guiNativeController,$persistentAcceleratorController,$sourceDetector",
            self.source,
        )
        self.assertIn("persistent_controller_path", self.source)
        self.assertIn("$iobAcceleratorInput=$persistentAcceleratorController", self.source)
        self.assertIn("private_accelerator_controller_pa=$persistentAcceleratorController", self.source)
        accelerator_block = self.source.split("$failureStage='prepare_accelerator_runtime_family'", 1)[1].split(
            "$nativeOrigins=", 1,
        )[0]
        self.assertNotIn("New-NativeFastAdjustRuntimeFamily", accelerator_block)
        self.assertNotIn("Remove-ShortPaCopy -Path $projectedPa", self.source)
        self.assertIn(
            "Remove-IobSeedPlaceholderCompanions -Directory $temporarySolverDir -Count 4",
            self.source,
        )
        self.assertNotIn(
            "shared runtime sessions are not portable GUI dependencies", self.source
        )
        self.assertNotIn(
            "Get-ChildItem -LiteralPath $temporarySolverDir -Recurse -File", self.source
        )

    def test_bunch_batches_use_official_shared_iob_particle_override(self):
        self.assertIn("official_shared_iob__per_process_particles_override", self.source)
        self.assertIn("$batchIob=$temporaryIob", self.source)
        self.assertIn("$Record.iob,$Record.source_fly2", self.source)
        self.assertNotIn("build_native_batch_iob_", self.source)
        self.assertNotIn("batch_iob_bundle_portability_receipt", self.source)
        self.assertNotIn("batchPaCopyDirectories", self.source)
        self.assertIn("shared_native_corridor_runtime__four_instances__no_refine", self.source)
        self.assertNotIn("build_local_refinement_iob.lua", self.source)
        self.assertNotIn("build_three_component_iob.lua", self.source)

    def test_dispatch_identity_reuses_verified_component_and_bank_receipts(self):
        self.assertIn("frontend_pa0_sha256=[string]$nativeBankCache.generation_sha256", self.source)
        self.assertIn("accelerator_overlay_generation_sha256=[string]$providerAccelerator.pa_family.generation_sha256", self.source)
        self.assertIn("reflectron_pa0_sha256=[string]$nativeSystemRuntimeRecords['detector'].sha256", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceAccelerator", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceDetector", self.source)

    def test_static_pa_assets_are_guarded_once_and_not_materialized_per_trial(self):
        self.assertIn("$requiredBytes+=$nativeFamilyPeakBytes", self.source)
        self.assertNotIn("iobProjectionBytes", self.source)
        self.assertIn(
            "Protect-ImmutablePaSource -Source $globalFallbackAnalyzer", self.source
        )
        self.assertIn("Protect-ImmutablePaSource -Source $sourceDetector", self.source)
        self.assertIn("$iobAnalyzerInput=$globalFallbackAnalyzer", self.source)
        self.assertIn("$iobDetectorInput=$sourceDetector", self.source)
        self.assertNotIn("function Copy-IobPaInput", self.source)
        self.assertNotIn("New-ShortPaCopy -Source $sourceDetector", self.source)

    def test_first_batch_observation_keeps_repository_scheduler_contract(self):
        self.assertIn("Start-ObservedFormalProcess -DispatchPlanPath", self.source)
        self.assertNotIn("WaitForNaturalCompletionAfterObservation", self.source)

    def test_first_completed_batch_publishes_existing_controlled_aberration_report(self):
        self.assertIn("function Publish-MrtofFirstBatchAberration", self.source)
        self.assertIn("--first-batch-log',$Record.stdout", self.source)
        self.assertIn("--source-receipt',$bunchSourceLocal", self.source)
        self.assertIn("Publish-MrtofFirstBatchAberration -Record", self.source)
        self.assertIn("$manifestOutputs+=$earlyAberrationReport", self.source)

    def test_bunch_batches_publish_common_whole_batch_checkpoints(self):
        for token in (
            "[string]$BatchContinuationRunPath=''",
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation",
            "simion_batch_continuation_plan",
            "continuation accepts only whole completed batches",
            "-OnProcessCompleted $checkpointAction",
            "-Status checkpoint",
        ):
            self.assertIn(token, self.source)
        self.assertIn("$replayBatchIndexes-contains$index", self.source)
        self.assertIn("$replayBatchIndexes=@(", self.source)
        self.assertIn(
            "$replayBatchIndexes=@($replanned.batches|ForEach-Object{[int]$_.index})",
            self.source,
        )

    def test_failure_removes_only_disposable_trajectory_cache_before_publication(self):
        catch = self.source.index("}catch{")
        failed = self.source.index("Complete-FailedRun", catch)
        cache_cleanup = self.source.index(
            "Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp'",
            catch,
        )
        self.assertLess(cache_cleanup, failed)

    def test_compact_postprocess_does_not_transition_a_finished_solver_lease(self):
        self.assertNotIn("-Stage 'mrtof_postprocess'", self.source)

    def test_inherited_host_lease_is_reused_and_not_released_by_child(self):
        self.assertIn("[pscustomobject]$InheritedHostResourceLease=$null", self.source)
        self.assertIn("$resourceLease=$InheritedHostResourceLease", self.source)
        self.assertIn("$ownsHostResourceLease=$null-eq$InheritedHostResourceLease", self.source)
        self.assertIn("if($ownsHostResourceLease){", self.source)
        self.assertNotIn("Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_prepare'", self.source)
        self.assertEqual(
            self.source.count("Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight'"),
            2,
        )
        self.assertIn("if($ownsHostResourceLease-and$null-ne$resourceLease)", self.source)

    def test_shared_host_lease_does_not_accumulate_transient_work_roots(self):
        self.assertIn("[bool]$RegisterHostProcess=$true", self.source)
        self.assertIn(
            "if($RegisterHostProcess-and-not$process.HasExited)", self.source
        )
        self.assertEqual(
            self.source.count("-RegisterHostProcess $ownsHostResourceLease"), 4
        )
        self.assertNotIn(
            "a reserved process creation identity is unavailable", self.source
        )

    def test_provider_runtime_receipt_is_the_only_accelerator_input(self):
        self.assertIn("AcceleratorProviderReceiptPath", self.source)
        self.assertNotIn("AcceleratorRunPath", self.source)
        self.assertIn("orthogonal_accelerator_mrtof_runtime_receipt", self.source)
        self.assertIn("published_standalone_response_bank", self.source)
        self.assertIn("Provider consumed input byte count differs from its declared receipt.", self.source)
        self.assertIn("$acceleratorConsumerProjectionId='mrtof_accelerator_provider_receipt_v1'", self.source)
        self.assertIn("--consumer-projection-id $acceleratorConsumerProjectionId --consumed-output $acceleratorProviderReceipt", self.source)
        self.assertIn("@($providerAccelerator.provider_plan,$providerAccelerator.resolved_campaign)", self.source)
        self.assertNotIn("$providerAccelerator.pa_child_manifest", self.source)
        self.assertIn("$iobAcceleratorInput=$sourceAccelerator", self.source)
        self.assertNotIn("Copy-IobPaInput -Source $sourceAccelerator", self.source)
        self.assertIn(
            "@('-c',$poseCode,$reviewed,$acceleratorLocal,$trajectoryContract,$posePath,$acceleratorProviderPlanLocal)",
            self.source,
        )
        self.assertNotIn(
            "@('-c',$poseCode,$reviewed,$acceleratorGeometry,$trajectoryContract,$posePath)",
            self.source,
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is required")
    def test_exit_only_skips_detector_gate_but_full_flight_calls_it(self):
        start = self.source.index("  $collectionGatePath=$null;$collectionGate=$null")
        end = self.source.index("  $observedResiduals=", start)
        block = self.source[start:end]
        with TemporaryDirectory() as directory:
            quoted = "'" + directory.replace("'", "''") + "'"
            for scope, expected_calls in (
                ("accelerator_safe_exit_envelope_only", 0),
                ("complete_three_dimensional_static_return", 1),
            ):
                with self.subTest(scope=scope):
                    command = (
                        "$ErrorActionPreference='Stop'; $isBunchFlight=$true; $calls=0\n"
                        f"$trial=@{{execution_scope='{scope}'}}; $resultDir={quoted}\n"
                        "$observation='unused'; function Invoke-ProjectPython { param($Arguments) "
                        "$script:calls++; '{}' | Set-Content -LiteralPath $Arguments[-1] }\n"
                        + block
                        + "\n@{calls=$calls; gate_is_null=($null-eq$collectionGate)}|ConvertTo-Json -Compress"
                    )
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-Command", command],
                        cwd=RUNNER.parent,
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads(result.stdout)
                    self.assertEqual(actual["calls"], expected_calls)
                    self.assertEqual(actual["gate_is_null"], expected_calls == 0)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is required")
    def test_flight_scope_follows_execution_scope(self):
        scope_start = self.source.index("$isSafeExitOnly=")
        scope_end = self.source.index("\n", scope_start)
        label_start = self.source.index("$config.parameters.flight_scope=")
        label_end = self.source.index(";$config.parameters.execution_scope=", label_start)
        for scope in (
            "accelerator_safe_exit_envelope_only",
            "complete_three_dimensional_static_return",
        ):
            with self.subTest(scope=scope):
                command = (
                    "$ErrorActionPreference='Stop'; $config=@{parameters=@{}}; "
                    f"$trial=@{{execution_scope='{scope}'}}\n"
                    + self.source[scope_start:scope_end] + "\n"
                    + self.source[label_start:label_end] + "\n"
                    + "$config.parameters | ConvertTo-Json -Compress"
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", command],
                    cwd=RUNNER.parent,
                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["flight_scope"], scope)

    def test_provider_small_inputs_are_frozen_and_consumed_locally(self):
        for variable, filename, option in (
            ("acceleratorProviderPlan", "accelerator_provider_plan.json", "--accelerator-provider-plan"),
            ("acceleratorResolvedCampaign", "accelerator_resolved_campaign.json", "--accelerator-resolved-campaign"),
        ):
            self.assertIn(f"${variable}Local=Copy-RequiredInput ${variable}", self.source)
            self.assertIn(f"'{option}',${variable}Local", self.source)
            self.assertIn(f"Join-Path $artifactSolverDir '{filename}'", self.source)
            capacity_line = next(line for line in self.source.splitlines() if "$requiredBytes+=[int64]" in line and "foreach" in line)
            self.assertIn(f"${variable}", capacity_line)
        pose = next(line for line in self.source.splitlines() if line.strip().startswith('$poseCode='))
        self.assertIn("plan=json.loads(Path(sys.argv[5]).read_text", pose)
        self.assertNotIn("receipt['provider_plan']['path']", pose)

    def test_trajectory_contract_authority_precedes_its_derived_inputs(self):
        authority = "$trajectoryContractSource=$trajectoryContractInput"
        self.assertLess(
            self.source.index(authority),
            self.source.index("$selectedContract=$trajectoryContractSource"),
        )
        self.assertLess(
            self.source.index(authority),
            self.source.index("$acceleratorGeometryContract=$trajectoryContractSource"),
        )

    def test_optional_contract_controls_pose_and_trajectory_without_rebuilding_pa(self):
        self.assertIn("[string]$ContractPath=''", self.source)
        self.assertIn("$trajectoryContractInput=if([string]::IsNullOrWhiteSpace($ContractPath))", self.source)
        self.assertIn("$trajectoryContractSource=$trajectoryContractInput", self.source)

    def test_direct_trial_accepts_run_input_accelerator_y_pose(self):
        self.assertIn("[Nullable[double]]$AcceleratorYAnchorMm=$null", self.source)
        self.assertIn(
            "$resolvedContract.accelerator.focus_y_anchor.project_y_mm=[double]$AcceleratorYAnchorMm",
            self.source,
        )
        self.assertIn(
            "foreach($resolvedContractPath in @($contract,$acceleratorGeometry,$trajectoryContract))",
            self.source,
        )
        self.assertIn("$config.parameters.accelerator_y_anchor_mm", self.source)

if __name__ == "__main__":
    unittest.main()
