"""Native-only contract tests for the MR-TOF flight runner."""
from pathlib import Path
import unittest

RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"

class TwoPrismTrialRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = RUNNER.read_text(encoding="utf-8")

    def test_requires_native_bank_and_system_bundle(self):
        self.assertIn("NativeCorridorBankRunPath is required for the native-only flight runner.", self.source)
        self.assertIn("NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.", self.source)

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

    def test_retained_gui_workbench_is_run_local_and_lifecycle_managed(self):
        for token in (
            "[switch]$RetainGuiWorkbench",
            "'solver_review'",
            "Retained SIMION GUI workbench with private run-local IOB companions.",
            "Join-Path $artifactSolverDir 'gui_workbench'",
            "Join-Path $temporarySolverDir 'pa_inputs'",
            "Retained GUI workbench native checkpoint controller is missing.",
            "PA payloads have already been bound through the runtime and published",
            "pa_dependencies=$guiPaDependencies",
        ):
            self.assertIn(token, self.source)
        self.assertIn(
            "if($null-ne$iobInputCopyDir-and-not$RetainGuiWorkbench)", self.source
        )

    def test_retained_gui_rebinds_shared_runtime_to_persistent_checkpoint(self):
        self.assertIn(
            "Join-Path ([string]$NativeCorridorRuntimeSession.directory) 'mrtof_analyzer_corridor.pa0'",
            self.source,
        )
        self.assertIn("-Stage 'rebind_retained_gui_iob'", self.source)
        self.assertIn("$nativeRuntime.controller_path=$stableNativeController", self.source)
        self.assertIn(
            "$privateIobSeed,$globalFallbackAnalyzer,$guiNativeController,$sourceAccelerator,$sourceDetector",
            self.source,
        )
        self.assertIn(
            "foreach($projectedPa in @($iobAnalyzerInput,$iobDetectorInput)){Remove-ShortPaCopy -Path $projectedPa}",
            self.source,
        )
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
        self.assertIn("accelerator_overlay_pa0_sha256=[string]$nativeSystemRuntimeRecords['accelerator'].sha256", self.source)
        self.assertIn("reflectron_pa0_sha256=[string]$nativeSystemRuntimeRecords['detector'].sha256", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceAccelerator", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceDetector", self.source)

    def test_capacity_counts_only_materialized_iob_projections(self):
        self.assertIn("$requiredBytes+=$nativeFamilyPeakBytes+$iobProjectionBytes", self.source)
        self.assertNotIn("$iobProjectionBytes+=[int64](Get-Item -LiteralPath $sourceAccelerator).Length", self.source)

    def test_first_batch_observation_keeps_repository_scheduler_contract(self):
        self.assertIn("Start-ObservedFormalProcess -DispatchPlanPath", self.source)
        self.assertNotIn("WaitForNaturalCompletionAfterObservation", self.source)

    def test_compact_postprocess_does_not_transition_a_finished_solver_lease(self):
        self.assertNotIn("-Stage 'mrtof_postprocess'", self.source)

    def test_provider_runtime_receipt_is_the_only_accelerator_input(self):
        self.assertIn("AcceleratorProviderReceiptPath", self.source)
        self.assertNotIn("AcceleratorRunPath", self.source)
        self.assertIn("orthogonal_accelerator_mrtof_runtime_receipt", self.source)
        self.assertIn("published_read_only", self.source)
        self.assertIn("Provider consumed input byte count differs from its declared receipt.", self.source)
        self.assertIn("$acceleratorConsumerProjectionId='mrtof_accelerator_provider_receipt_v1'", self.source)
        self.assertIn("--consumer-projection-id $acceleratorConsumerProjectionId --consumed-output $acceleratorProviderReceipt", self.source)
        self.assertIn("@($providerAccelerator.read_only_controller_pa0,$providerAccelerator.provider_plan)", self.source)
        self.assertNotIn("$providerAccelerator.pa_child_manifest", self.source)
        self.assertIn("$iobAcceleratorInput=$sourceAccelerator", self.source)
        self.assertNotIn("Copy-IobPaInput -Source $sourceAccelerator", self.source)
        self.assertIn(
            "@('-c',$poseCode,$reviewed,$acceleratorLocal,$trajectoryContract,$posePath)",
            self.source,
        )
        self.assertNotIn(
            "@('-c',$poseCode,$reviewed,$acceleratorGeometry,$trajectoryContract,$posePath)",
            self.source,
        )

    def test_trajectory_contract_authority_precedes_its_derived_inputs(self):
        authority = "$trajectoryContractSource=Join-Path $repoRoot"
        self.assertLess(
            self.source.index(authority),
            self.source.index("$selectedContract=$trajectoryContractSource"),
        )
        self.assertLess(
            self.source.index(authority),
            self.source.index("$acceleratorGeometryContract=$trajectoryContractSource"),
        )

if __name__ == "__main__":
    unittest.main()
