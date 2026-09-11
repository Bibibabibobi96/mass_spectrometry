from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"


class TwoPrismTrialRunnerTest(unittest.TestCase):
    def test_downstream_trials_reuse_pa_and_protect_the_fly2(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "Stripe1VoltageV",
            "Stripe2VoltageV",
            "ContinueMainDrift",
            "RetainGuiWorkbench",
            "PulseAcceleratorUntilInitialExit",
            "AcceleratorPulseSchedulePath",
            "$acceleratorPulseRequested",
            "AcceleratorFamilyRunPath",
            "read_only_voltageized",
            "temporary_voltageized_analyzer__immutable_family",
            "downstream_trial_source.input.fly2",
            "Test-RunFilesIdentical",
            "build_three_component_iob.lua",
            "local_operating_pa_cache",
            "content_addressed_local_operating_pa0",
            "solver_review",
            "gui_workbench_receipt.json",
            "gui_workbench_iob",
            "extraction must use the unchanged static prism voltages",
            "elseif($cacheProbe.disposition-eq'miss')",
            "transient_miss_not_published",
            "independently_constructed_standalone_response",
            "project_iob_pa_inputs",
            "iob_input_analyzer.pa",
            "iob_input_accelerator.pa",
            "iob_input_detector.pa",
            "$observedExtraction.status-eq'detector_hit'",
            "materialize_writable_accelerator_family",
            "writable_accelerator_family_materialization.json",
            "--pulse-accelerator-until-initial-exit",
            "--accelerator-pulse-schedule",
            "1..9|ForEach-Object",
            "$acceleratorFamilySimion",
            "source_accelerator_family_run_manifest",
            "iob_seed=if($null-eq$localWorkbenchRun)",
            "local_refinement_sidecar=if($null-eq$localWorkbenchRun)",
            "flight_program=Join-Path $solverDir 'mrtof_three_component_candidate.lua'",
            "mirror_cycle_counter=Join-Path $solverDir",
            "voltage_map=Join-Path $solverDir",
            "flight_launcher=Join-Path $solverDir 'run_iob_flight.lua'",
            "trial_materializer=Join-Path $solverDir 'two_prism_simion_trial.py'",
            "analyzer_voltageizer=Join-Path $solverDir 'voltageize_analyzer_pa0.lua'",
            "basis_adjuster=if($null-eq$localWorkbenchRun)",
            "basis_voltage_measurement=if($null-eq$localWorkbenchRun)",
        ):
            self.assertIn(token, source)
        self.assertIn("voltageize_analyzer_pa0.lua", source)
        self.assertIn("Remove-TemporarySolverDirectory", source)
        self.assertIn("short_pa_path_support.ps1", source)
        self.assertNotIn("New-ShortPaCopy -Source $basisSource", source)
        self.assertIn("standalone_response_filename", source)
        self.assertIn("native_family_member_opened=$false", source)
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
        self.assertNotIn("$temporaryAnalyzer,$sourceAccelerator,$sourceDetector,$temporaryIob", source)
        self.assertNotIn("$temporaryAnalyzer)+$temporaryLocalPaths+@($sourceAccelerator,$sourceDetector", source)
        self.assertNotIn("$observed.status-eq'detector_observed'", source)
        self.assertNotIn("AcceleratorPulseOffTimeUs", source)
        self.assertIn("if(-not$acceleratorPulseRequested)", source)
        self.assertIn("run_local_family_disposable", source)
        self.assertLess(
            source.index("$cacheProbe.disposition-eq'hit'"),
            source.index('Invoke-SimionStage -Stage ("adjust_local_'),
        )


if __name__ == "__main__":
    unittest.main()
