from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_native_corridor_bunch_screening.ps1"


class NativeCorridorBunchScreeningRunnerTest(unittest.TestCase):
    def test_screening_runs_one_static_cohort_from_checkpointed_family(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "Open-NativeCorridorRuntimeCheckpoint -Session $nativeRuntimeSession",
            "NativeCorridorRuntimeSession=$nativeRuntimeSession",
            "NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath",
            "[string]$InitialCohortRunPath=''",
            "[ValidateSet(3,13,100,1000)][int]$CohortParticleCount=1000",
            "$cohortRunId=New-CohortRunId",
            "BunchParticleIdMax=$CohortParticleCount",
            "RetainGuiWorkbench=$true",
            "[string]$MirrorVoltageVariationPath=''",
            "$cohortArguments.MirrorVoltageVariationPath=$mirrorVoltageVariation",
            "one_checkpointed_native_fast_adjust_family__no_pa_copy_or_refine",
            "accelerator_field_mode='static'",
            "Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession",
        ):
            self.assertIn(token, source)
        self.assertNotIn("New-NativeCorridorRuntimeFamily", source)
        self.assertEqual(source.count("RetainGuiWorkbench=$true"), 1)
        self.assertNotIn("AcceleratorPulseSchedulePath", source)
        self.assertNotIn("run_freeze_bunch_pulse_schedule.ps1", source)

    def test_workpoint_mirror_variation_is_inherited_when_not_explicit(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn(
            "$workpointConfig.inputs.terminal_time_mirror_voltage_variation",
            source,
        )
        self.assertIn(
            "$cohortArguments.MirrorVoltageVariationPath=$mirrorVoltageVariation",
            source,
        )

    def test_controlled_diagnostic_sizes_are_explicit(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[switch]$FocusDiagnosticOnly", source)
        self.assertIn(
            "[ValidateSet('','focus_z','slow_energy','controlled_aberration')]",
            source,
        )
        self.assertIn(
            "$requiredDiagnosticCount = if($DiagnosticPurpose -eq 'controlled_aberration'){13}",
            source,
        )
        self.assertIn(
            "focus_z/slow_energy use N=3 and controlled_aberration uses N=13.",
            source,
        )

    def test_numerical_probe_can_override_only_the_trajectory_step_scale(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[Nullable[double]]$TrajectoryStepScaleOverride=$null", source)
        self.assertIn("TrajectoryStepScaleOverride must be in (0,1].", source)
        self.assertIn(
            "TrajectoryStepScale=$(if($null-eq$trajectoryStepScale){[double]$problem.trajectory_step_scale}else{$trajectoryStepScale})",
            source,
        )

    def test_source_center_y_must_match_workpoint_accelerator_pose(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$contractData.accelerator.focus_y_anchor.project_y_mm", source)
        self.assertIn("$sourceData.nominal_center_state.position_workbench_mm[1]", source)
        self.assertIn("source centre does not match the workpoint accelerator y pose", source)

    def test_native_bunch_flights_forward_only_the_bound_system_bundle(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("Workpoint has no native system runtime bundle identity.", source)
        self.assertIn("NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath", source)
        self.assertIn("Workpoint must bind an OA accelerator provider receipt.", source)
        self.assertIn("$cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt", source)
        self.assertNotIn("AcceleratorRunPath", source)
        self.assertNotIn("accelerator_run", source)
        self.assertNotIn("LocalWorkbenchRunPath=[string]$problem.local_workbench", source)

    def test_bunch_flights_reuse_the_workpoint_frozen_contract(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$workpointContract=(Resolve-Path -LiteralPath (Join-Path $workpointRun 'inputs\\contract.json')).Path", source)
        self.assertIn("Workpoint frozen contract identity differs from its physical-problem identity.", source)
        self.assertEqual(source.count("ContractPath=$workpointContract"), 1)

    def test_legacy_warning_handoff_is_reselected_from_verified_history(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("if($handoffData.status-ne'within_tolerance')", source)
        self.assertIn("Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'iteration_history.json'", source)
        self.assertIn("--select-best-physical-workpoint','--history',$history", source)
        self.assertIn("$handoffData.status-ne'within_tolerance'", source)

    def test_verified_initial_static_cohort_can_resume_without_reflight(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("if($null-ne$initialCohortRun)", source)
        self.assertIn(
            "$cohortSummary.source_cohort.mother_particle_count-ne[int]$sourceData.mother_particle_count",
            source,
        )
        self.assertNotIn(
            "$cohortSummary.source_cohort.mother_particle_count-ne[int]$sourceData.particle_count",
            source,
        )
        self.assertIn("source_cohort.selection.parent_particle_states_sha256", source)
        self.assertIn("$cohortVoltages=@($cohortSummary.stripe_biases_v)+@($cohortSummary.prism_voltages_v)", source)
        self.assertIn("Cohort run does not bind the requested source, workpoint voltages, and static accelerator mode.", source)
        self.assertLess(source.index("if($null-ne$initialCohortRun)"), source.index("& $trialRunner @cohortArguments"))
        self.assertNotIn("New-ShortPaCopy", source)

    def test_incomplete_cohort_can_use_common_batch_continuation(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "[string]$CohortBatchContinuationRunPath=''",
            "$cohortArguments.BatchContinuationRunPath=$CohortBatchContinuationRunPath",
        ):
            self.assertIn(token, source)

    def test_static_cohort_collection_gate_is_the_only_downstream_gate(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("stop_below_collection_hard_minimum", source)
        self.assertIn("[bool]$cohortGateData.hard_stop", source)
        self.assertNotIn("pilotGate", source)

    def test_cohort_run_id_keeps_revision_at_the_end(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function New-CohortRunId", source)
        self.assertIn("$cohortRunId=New-CohortRunId", source)
        self.assertNotIn('$RunId+"__n$CohortParticleCount-static"', source)

if __name__ == "__main__":
    unittest.main()
