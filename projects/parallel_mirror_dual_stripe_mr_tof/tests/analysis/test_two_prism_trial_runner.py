from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"
PROGRAM = Path(__file__).resolve().parents[2] / "simion" / "mrtof_candidate.lua"
MATERIALIZER = Path(__file__).resolve().parents[2] / "analysis" / "two_prism_simion_trial.py"
COMPOSER = Path(__file__).resolve().parents[4] / "common" / "simion" / "compose_standalone_pa.lua"
IOB_BUILDER = Path(__file__).resolve().parents[2] / "simion" / "build_local_refinement_iob.lua"


class TwoPrismTrialRunnerTest(unittest.TestCase):
    def test_solver_processes_use_named_resource_stages(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "Enter-HostResourceStage -Role SIMION -Stage 'mrtof_prepare'",
            "Get-HostResourceBudget -Role SIMION -Stage 'mrtof_prepare'",
            "Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight'",
            "Get-HostResourceBudget -Role SIMION -Stage 'mrtof_flight'",
            "Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_postprocess'",
            "Get-HostResourceBudget -Role SIMION -Stage 'mrtof_postprocess'",
            "Register-HostResourceProcess -Lease $ResourceLease -ProcessId $process.Id",
            "if(-not$process.HasExited)",
            "HOST_RESOURCE_PROCESS=COMPLETED_BEFORE_REGISTRATION",
            "Exit-HostResourceStage -Lease $resourceLease",
        ):
            self.assertIn(token, source)
        self.assertNotIn("Enter-HostExecutionLease", source)
        self.assertNotIn("Exit-HostExecutionLease", source)
        self.assertLess(
            source.index("-Stage 'mrtof_prepare'"),
            source.index("-Stage 'mrtof_flight'"),
        )
        self.assertLess(
            source.index("Invoke-SimionStage -Stage 'build_temporary_iob'"),
            source.index("-Stage 'mrtof_flight'"),
        )
        self.assertLess(
            source.index("-Stage 'mrtof_flight'"),
            source.index("Invoke-SimionStage -Stage 'native_two_prism_flight'"),
        )
        self.assertLess(
            source.index("-Stage 'mrtof_flight'"),
            source.index("-Stage 'mrtof_postprocess'"),
        )

    def test_prepare_stage_only_composes_existing_solutions(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8-sig")
        composer = COMPOSER.read_text(encoding="utf-8-sig")
        iob_builder = IOB_BUILDER.read_text(encoding="utf-8-sig")
        for source in (runner, composer, iob_builder):
            self.assertNotIn(":refine", source)
        self.assertNotIn("gem2pa", runner)
        self.assertNotIn("build_component_pa.lua", runner)
        self.assertIn("standalone_linear_response_composition", runner)
        self.assertIn("refine_performed=$false", runner)

    def test_temporary_pa_cleanup_retries_only_the_verified_temp_target(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function Remove-TemporarySolverDirectory", source)
        self.assertIn("for($attempt=1;$attempt-le8;$attempt++)", source)
        self.assertIn("Start-Sleep -Milliseconds (250*$attempt)", source)
        self.assertIn("if($attempt-eq8){throw}", source)
        self.assertIn("Refusing to remove non-temporary solver directory", source)

    def test_batch_clone_inspection_has_invariant_number_formatter(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function Format-InvariantNumber", source)
        self.assertIn("[Globalization.CultureInfo]::InvariantCulture", source)
        self.assertIn("$inspectionArguments+=Format-InvariantNumber", source)

    def test_pulsed_accelerator_uses_one_standalone_pa_field_gate(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8-sig")
        program = PROGRAM.read_text(encoding="utf-8-sig")
        materializer = MATERIALIZER.read_text(encoding="utf-8-sig")
        self.assertIn("runtime_accelerator_field_gate_enable", materializer)
        self.assertIn("function segment.efield_adjust()", program)
        self.assertIn("ion_dvoltsx_gu, ion_dvoltsy_gu, ion_dvoltsz_gu = 0, 0, 0", program)
        self.assertNotIn("accelerator:fast_adjust", program)
        self.assertIn("$localWorkbenchConfig.inputs.accelerator_pa", runner)
        self.assertNotIn("$acceleratorFamilySources", runner)

    def test_downstream_trials_reuse_pa_and_protect_the_fly2(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "Stripe1VoltageV",
            "Stripe2VoltageV",
            "RetainGuiWorkbench",
            "PulseAcceleratorUntilInitialExit",
            "AcceleratorPulseSchedulePath",
            "BunchSourceReceiptPath",
            "$acceleratorPulseRequested",
            "AcceleratorFamilyRunPath is obsolete",
            "BootstrapGlobalOperatingPa",
            "standalone_accelerator_pa",
            "verified standalone local workbench or explicit BootstrapGlobalOperatingPa",
            "read_only_analyzer_pa=$workbenchAnalyzer",
            "downstream_trial_source.input.fly2",
            "Test-RunFilesIdentical",
            "build_three_component_iob.lua",
            "local_operating_pa_cache",
            "compose_standalone_pa.lua",
            "content_addressed_local_operating_pa",
            "solver_review",
            "gui_workbench_receipt.json",
            "gui_workbench_iob",
            "manifest_bound_standalone_operating_pa__efield_gate_to_zero",
            "mrtof_two_prism_geometry_contract_v1",
            "--consumer-projection-id $geometryConsumerProjectionId",
            "--consumed-input resolved_prototype_contract $geometryReviewedContract",
            "unconsumed_records_not_asserted=$true",
            "all_other_upstream_manifests='full'",
            "unchanged static prism voltages",
            "elseif($cacheProbe.disposition-eq'miss')",
            "transient_miss_not_published",
            "standalone_linear_response_composition",
            "project_iob_pa_inputs",
            "iob_input_analyzer.pa",
            "iob_input_accelerator.pa",
            "iob_input_detector.pa",
            "$observedExtraction.status-eq'detector_hit'",
            "--pulse-accelerator-until-initial-exit",
            "--accelerator-pulse-schedule",
            "--bunch-source-receipt",
            "iob_seed=if($reuseFrozenWorkbenchAnalyzer)",
            "local_refinement_sidecar=if(-not$reuseFrozenWorkbenchAnalyzer){$null}",
            "flight_program=Join-Path $flightArtifactRoot 'mrtof_three_component_candidate.lua'",
            "mirror_cycle_counter=Join-Path $flightArtifactRoot",
            "voltage_map=Join-Path $flightArtifactRoot",
            "flight_launcher=Join-Path $artifactSolverDir 'run_iob_flight.lua'",
            "trial_materializer=Join-Path $artifactSolverDir 'two_prism_simion_trial.py'",
            "analyzer_voltageizer=if($reuseFrozenWorkbenchAnalyzer)",
            "basis_adjuster=Join-Path $artifactSolverDir",
            "basis_voltage_measurement=$null",
        ):
            self.assertIn(token, source)
        self.assertNotIn("ContinueMainDrift", source)
        self.assertNotIn("ConstrainXSymmetryPlane", source)
        self.assertIn("complete_three_dimensional_static_return", source)
        self.assertIn("$reuseFrozenWorkbenchAnalyzer=$null-ne$localWorkbenchRun", source)
        self.assertIn("$localWorkbenchConfig.inputs.local_operating_pas", source)
        self.assertIn("$localWorkbenchConfig.inputs.accelerator_pa", source)
        self.assertIn("$localWorkbenchConfig.inputs.detector_pa", source)
        self.assertIn("$localWorkbenchConfig.inputs.operating_run_manifest", source)
        self.assertIn("$localWorkbenchConfig.inputs.operating_iob", source)
        self.assertIn("[IO.Path]::GetFileNameWithoutExtension($declaredWorkbenchIob)", source)
        self.assertIn("Assert-FrozenWorkbenchOutput -Path $localConfigSource", source)
        self.assertNotIn("simion\\mrtof_local_replacement.local_refinement.lua", source)
        self.assertIn("Test-RunFilesIdentical -Left $declared -Right", source)
        self.assertIn("Local-workbench operating provenance differs", source)
        self.assertIn("$temporaryLocalPaths=@($localWorkbenchOperatingPaths)", source)
        self.assertIn("$startupProtectedCacheKeys=if($null-eq$localWorkbenchRun){@()}else{@($localFamilies.cache_key)}", source)
        self.assertIn("if($earlyOperatingCacheHit){$startupProtectedCacheKeys+=@($operatingCacheKey)}", source)
        self.assertIn("$startupProtectedCacheKeys=@($startupProtectedCacheKeys|Select-Object -Unique)", source)
        self.assertIn("New-ShortPaCopy -Source $localWorkbenchOperatingPaths[$index]", source)
        self.assertNotIn("Join-Path $localWorkbenchRun \"simion\\$($localNames[$index])\"", source)
        self.assertIn("Invoke-SimionStage -Stage 'voltageize_temporary_analyzer'", source)
        self.assertIn("bootstrap_global_family_read_only", source)
        self.assertIn("[IO.FileShare]::Read", source)
        self.assertIn("if($null-eq$localWorkbenchRun){@()}", source)
        self.assertIn("Remove-TemporarySolverDirectory", source)
        self.assertIn("short_pa_path_support.ps1", source)
        self.assertNotIn("New-ShortPaCopy -Source $basisSource", source)
        self.assertIn("standalone_response_filename", source)
        self.assertIn("Resolve-AnalyzerLocalStandaloneResponseSubset", source)
        self.assertNotIn("Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family", source)
        self.assertIn("native_family_member_opened=$false", source)
        self.assertNotIn("adjust_operating_pa_from_basis.lua", source)
        self.assertIn("$coefficient=[double]$deltaVoltages[$changedIndex]/$basisVoltage", source)
        self.assertIn("foreach($changedIndex in $changedIndices)", source)
        self.assertNotIn("measure_global_basis_voltage", source)

    def test_legacy_prism_switch_and_extraction_inputs_are_not_public(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for obsolete in (
            "Prism1ExtractionVoltageV", "Prism2ExtractionVoltageV",
            "PrismSwitchTimeUs", "ReferenceTransportRunPath",
        ):
            self.assertNotIn(obsolete, source)
        self.assertNotIn("[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2')", source)
        self.assertIn("New-ShortPaCopy -Source $Source -Destination $destination", source)
        self.assertIn("$iobAnalyzerInput,$iobAcceleratorInput,$iobDetectorInput", source)
        self.assertIn("$iobAnalyzerInput)+$iobLocalInputs", source)
        self.assertIn("if($RetainGuiWorkbench){", source)
        self.assertIn("$transientBytes+=$localOperatingBytes+$perRegionProjectionBytes", source)
        self.assertNotIn("$largestLocalFamilyBytes", source)
        self.assertNotIn("--materialize-manifest", source)
        self.assertIn("-MinimumFreeGiB $minimumFreeGiB", source)
        self.assertLess(
            source.index("[int64]$requiredBytes=0;[int64]$transientBytes=0"),
            source.index("[int64]$iobProjectionBytes="),
        )
        self.assertIn("foreach($path in $temporaryLocalPaths)", source)
        self.assertIn("source_sha256=$voltageSourceHash", source)
        self.assertIn("Get-FileHash -LiteralPath $workbenchAnalyzer", source)
        self.assertNotIn("$voltageSourceHash=if($reuseFrozenWorkbenchAnalyzer){$upstreamHashes[3]}", source)
        self.assertNotIn("$requiredBytes+=3*$localOperatingBytes", source)
        self.assertNotIn("Copy-RequiredInput $sourceAnalyzer", source)
        self.assertNotIn("Copy-RequiredInput $sourceAccelerator", source)
        self.assertNotIn("$sourceAccelerator=Join-Path $localWorkbenchRun", source)
        self.assertNotIn("$sourceDetector=Join-Path $localWorkbenchRun", source)
        self.assertNotIn("Join-Path $geometrySimion 'mrtof_accelerator.pa#'", source)
        self.assertNotIn("mrtof_accelerator.pa1", source)
        self.assertNotIn("$acceleratorFamilySources", source)
        self.assertNotIn("materialize_writable_accelerator_family", source)
        self.assertNotIn("$temporaryAnalyzer,$sourceAccelerator,$sourceDetector,$temporaryIob", source)
        self.assertNotIn("$temporaryAnalyzer)+$temporaryLocalPaths+@($sourceAccelerator,$sourceDetector", source)
        self.assertNotIn("$observed.status-eq'detector_observed'", source)
        self.assertNotIn("AcceleratorPulseOffTimeUs", source)
        self.assertIn("if(-not$acceleratorPulseRequested)", source)
        self.assertIn("N>1 forbids initial_exit_triggered_single_center", source)
        self.assertIn("schema-2 fixed_global_time schedule", source)
        self.assertIn("Materialized trial Fly2 identity differs", source)
        self.assertLess(
            source.index("$cacheProbe.disposition-eq'hit'"),
            source.index('Invoke-SimionStage -Stage ("compose_local_'),
        )

    def test_n_greater_than_one_uses_repository_dynamic_dispatch(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn(
            "trajectory_quality_profile_id=[string]$trial.trajectory_profile.profile_id",
            source,
        )
        self.assertNotIn("$trial.trajectory_profile.id", source)
        for token in (
            "common\\multipole\\resource_budget_support.ps1",
            "common.simion.resource_profile','discover",
            'projects\\$projectId\\runs',
            "common.simion.resource_scheduler",
            "common.simion.particle_batching",
            "Start-ObservedFormalProcess",
            "-WaitForNaturalCompletionAfterObservation",
            "Invoke-ResourceBudgetedProcesses",
            "simion_particle_id_offset",
            "Formal-first replan changed an already completed batch interval",
            "Assert-MrtofBatchTransientCapacity",
            "New-ShortPaCopy -Source $temporaryAnalyzer",
            "-MarkDestinationReadOnly",
            "Protect-ShortPaCopyDestination -Path $paPath",
            "Get-ShortPaCopyIdentity -Path $_",
            "private PA lost its no-write guard",
            "eight_private_read_only_standalone_pas_per_batch",
            "parent_held_no_write_handles_during_flight",
            "iob_input_analyzer.pa",
            "iob_input_accelerator.pa",
            "iob_input_detector.pa",
            "iob_input_local_{0}.pa",
            "$script:batchPaCopyDirectories+=@($batchPaDir)",
            "mrtof_batch_flight','materialize'",
            ") | Out-Host",
            "Remove-ShortPaCopiesUnderDirectory -Path $path -ExpectedNamePrefix 'batch_'",
            "batch_log_merge_receipt",
            "bunch_source_run_manifest",
            "managed batch dispatch requires common tob=0",
            "peak_active_workers",
            "bottleneck=$bottleneck",
        ):
            self.assertIn(token, source)
        self.assertNotIn("maximum_parallel_batches", source)
        self.assertNotIn("maximum_parallel_workers", source)
        self.assertLess(
            source.index("$script:batchPaCopyDirectories+=@($batchPaDir)"),
            source.index("New-ShortPaCopy -Source $temporaryAnalyzer"),
        )
        self.assertLess(
            source.index("Remove-ShortPaCopiesUnderDirectory -Path $path -ExpectedNamePrefix 'batch_'"),
            source.index("Remove-TemporarySolverDirectory -Path $batchRuntimeRoot"),
        )

    def test_n_greater_than_one_builds_one_portable_iob_template(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "$batchPaDir=$batchDir",
            "build_batch_iob_template_once",
            "Copy-MrtofBatchTemplateToRecord",
            "Assert-MrtofBatchClonePortability",
            "inspect_batch_iob_without_template_directory",
            "template_directory_hidden_during_clone_reload",
            "Distinct batch intervals unexpectedly materialized identical Fly2 companions",
            "eight_private_read_only_standalone_pas_per_batch",
            "flight changed its private standalone PA set",
            "batch_iob_bundle_portability_receipt.json",
        ):
            self.assertIn(token, source)
        self.assertEqual(source.count("Invoke-SimionStage -Stage 'build_batch_iob_template_once'"), 1)
        self.assertEqual(source.count("Assert-MrtofBatchClonePortability -Records"), 1)
        replan_clone = (
            "Copy-MrtofBatchTemplateToRecord -Template $batchTemplateRecord "
            "-Record $batchRecords[$plannedIndex]"
        )
        self.assertIn(replan_clone, source)
        self.assertLess(
            source.index(replan_clone),
            source.index("Assert-MrtofBatchClonePortability -Records"),
        )
        self.assertLess(
            source.index("Assert-MrtofBatchClonePortability -Records"),
            source.index("$pendingSpecs=@("),
        )
        self.assertLess(
            source.index("Move-Item -LiteralPath $template.runtime_dir -Destination $hidden"),
            source.index("inspect_batch_iob_without_template_directory"),
        )
        self.assertLess(
            source.index("inspect_batch_iob_without_template_directory"),
            source.index("Move-Item -LiteralPath $hidden -Destination $template.runtime_dir"),
        )

    def test_contiguous_frozen_source_diagnostic_uses_the_same_runner(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        materializer = MATERIALIZER.read_text(encoding="utf-8-sig")
        for token in (
            "BunchParticleIdMin", "BunchParticleIdMax",
            "TrajectoryStepScale", "--trajectory-step-scale",
            "--bunch-particle-id-min", "--bunch-particle-id-max",
            "candidate_bunch_selection_diagnostic__not_formal",
            "source_selection=$trial.source_selection",
            "frozen bunch interval diagnostic requires the static accelerator mode",
        ):
            self.assertIn(token, source)
        self.assertIn("resolve_bunch_source_interval", materializer)
        self.assertIn("contiguous_frozen_bunch_diagnostic__not_formal", materializer)
        self.assertIn("trajectory step scale must be in (0, 1]", materializer)
        self.assertIn("BunchParticleIdMax-lt$BunchParticleIdMin", source)
        self.assertIn("one or more contiguous IDs", source)
        self.assertNotIn("BunchParticleIdMax-le$BunchParticleIdMin", source)
        self.assertIn("bunch_particle_id_max < bunch_particle_id_min", materializer)
        self.assertIn("one or more contiguous particles", materializer)
        self.assertNotIn("bunch_particle_id_max <= bunch_particle_id_min", materializer)


if __name__ == "__main__":
    unittest.main()
