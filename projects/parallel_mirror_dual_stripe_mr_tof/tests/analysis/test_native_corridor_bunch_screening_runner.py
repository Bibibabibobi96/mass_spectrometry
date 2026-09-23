from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_native_corridor_bunch_screening.ps1"


class NativeCorridorBunchScreeningRunnerTest(unittest.TestCase):
    def test_screening_reuses_one_checkpointed_family_for_both_cohorts(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "Open-NativeCorridorRuntimeCheckpoint -Session $nativeRuntimeSession",
            "NativeCorridorRuntimeSession=$nativeRuntimeSession",
            "NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath",
            "BunchParticleIdMin=1;BunchParticleIdMax=100",
            "[string]$InitialPilotRunPath=''",
            "[string]$RecoveryPlanPath=''",
            "$pilotRunId=$RunId+'__n100-static'",
            "$cohortRunId=$RunId+'__n1000-fixed-clock'",
            "RetainGuiWorkbench=$true",
            "run_freeze_bunch_pulse_schedule.ps1",
            "$guardUs=[double]$pilotData.trajectory_profile.maximum_step_us",
            "one_checkpointed_native_fast_adjust_family__no_pa_copy_or_refine",
            "Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession",
        ):
            self.assertIn(token, source)
        self.assertNotIn("New-NativeCorridorRuntimeFamily", source)
        self.assertEqual(source.count("RetainGuiWorkbench=$true"), 2)

    def test_native_bunch_flights_forward_only_the_bound_system_bundle(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("Workpoint has no native system runtime bundle identity.", source)
        self.assertIn("NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath", source)
        self.assertIn("Workpoint must bind an OA accelerator provider receipt.", source)
        self.assertIn("$pilotArguments.AcceleratorProviderReceiptPath=$providerReceipt", source)
        self.assertIn("$cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt", source)
        self.assertNotIn("AcceleratorRunPath", source)
        self.assertNotIn("accelerator_run", source)
        self.assertNotIn("LocalWorkbenchRunPath=[string]$problem.local_workbench", source)

    def test_verified_initial_pilot_can_resume_without_reflight(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("if($null-ne$initialPilotRun)", source)
        self.assertIn("source_cohort.selection.parent_particle_states_sha256", source)
        self.assertIn("Initial pilot does not bind the requested frozen N=1000 source prefix.", source)
        self.assertLess(source.index("if($null-ne$initialPilotRun)"), source.index("& $trialRunner @pilotArguments"))
        self.assertNotIn("New-ShortPaCopy", source)

    def test_n100_hard_stop_preserves_evidence_and_prevents_n1000(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        stop = source.index("if([bool]$pilotGateData.hard_stop)")
        cohort = source.index("$failureStage='cohort_n1000'")
        self.assertLess(stop, cohort)
        self.assertIn("stop_below_collection_hard_minimum", source[stop:cohort])
        self.assertIn("Write-VerifiedRunManifest", source[stop:cohort])

    def test_user_can_pause_cleanly_after_n100_pilot(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        stop = source.index("if($StopAfterPilot)")
        freeze = source.index("$failureStage='freeze_global_pulse'")
        self.assertLess(stop, freeze)
        self.assertIn("status='pilot_complete'", source[stop:freeze])
        self.assertIn("paused_before_global_pulse_freeze_and_n1000_at_user_request", source[stop:freeze])
        self.assertIn("Write-VerifiedRunManifest", source[stop:freeze])

    def test_recovery_uses_the_bound_theory_seed_and_one_open_runtime(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "[switch]$RecoverTransport",
            "'bunch_transport_recovery_plan.json'",
            "analysis.bunch_transport_recovery','plan'",
            "'run_bunch_transport_recovery_probes'",
            "NativeCorridorRuntimeSession=$nativeRuntimeSession",
            "MRTOF_BUNCH_TRANSPORT_RECOVERY=SELECTED",
            "bunch_transport_recovery_selection.json",
            "function Invoke-ProjectPython",
            "function New-RecoveryCandidateRunId",
            "$env:PYTHONPATH=$repoRoot",
            "$candidateRunId=New-RecoveryCandidateRunId",
            "if(-not(Test-Path -LiteralPath $candidateManifest -PathType Leaf)){& $trialRunner @candidateArguments}",
        ):
            self.assertIn(token, source)
        recovery = source[source.index("if([bool]$pilotGateData.hard_stop-and$RecoverTransport)"):]
        self.assertNotIn("New-NativeCorridorRuntimeFamily", recovery)

    def test_unrecoverable_theory_stage_automatically_refreshes_reverse_axes(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        recovery = source[source.index("if([bool]$pilotGateData.hard_stop-and$RecoverTransport)"):]
        for token in (
            "function Invoke-BunchTransportRecoveryStage",
            "-Stage theory",
            "if($selectedRecovery.status-ne'selected')",
            "-Stage reverse_axis",
            "bunch_transport_recovery_reverse_axis_plan.json",
            "bunch_transport_recovery_reverse_axis_selection.json",
            "recovery_stages=$recoveryStageEvidence",
        ):
            self.assertIn(token, source)
        self.assertEqual(source.count("foreach($candidate in @($planData.candidates))"), 1)
        self.assertLess(recovery.index("-Stage theory"), recovery.index("-Stage reverse_axis"))


if __name__ == "__main__":
    unittest.main()
