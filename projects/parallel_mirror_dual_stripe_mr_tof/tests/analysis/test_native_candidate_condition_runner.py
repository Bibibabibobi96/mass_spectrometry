import json
from pathlib import Path
import unittest


RUNNER = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "run_native_candidate_condition.ps1"
)
CONTINUATION_RUNNER = RUNNER.with_name("run_two_prism_segmented_continuation.ps1")
OA_RELEASE = RUNNER.parents[1] / "config" / "accelerator_component_release_n100.json"


class NativeCandidateConditionRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8-sig")

    def test_physical_stages_delegate_to_existing_runners_in_order(self) -> None:
        stages = [
            "run_dual_stripe_operating_seed.ps1",
            "run_component_focus_workflow.ps1",
            "run_two_prism_trial.ps1",
            "run_two_prism_segmented_coverage.ps1",
            "run_two_prism_segmented_continuation.ps1",
            "run_downstream_workpoint_iteration.ps1",
            "run_native_candidate_chain.ps1",
        ]
        positions = [self.source.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("FixedGridRunManifest=$fixedMirrorManifest", self.source)
        self.assertIn("ReleaseSpecPath=$releaseSpec", self.source)
        self.assertIn("AcceleratorSafeExitOnly=$true", self.source)
        self.assertNotIn("ContinuationRunManifest=$context", self.source)

    def test_condition_contract_changes_only_k_and_accelerator_y(self) -> None:
        self.assertIn("$contract.nominal.target_drift_period_ratio=$k", self.source)
        self.assertIn("$contract.accelerator.focus_y_anchor.project_y_mm=$acceleratorY", self.source)
        self.assertIn("condition_contract.json", self.source)
        self.assertNotIn("Set-Content -LiteralPath $baseContract", self.source)

    def test_exact_k_oa_provider_uses_repository_release_and_published_offset(self) -> None:
        self.assertIn("selected_exact_K_slow_energy_per_charge_v", self.source)
        self.assertIn("oa_base_release_spec_path", self.source)
        self.assertIn("$release.sampling.kinetic_energy.center_ev=$slowEnergy*[math]::Abs($charge)", self.source)
        self.assertIn("$release.sampling.nominal_direction=@(0.0,1.0,0.0)", self.source)
        self.assertIn("$release.sampling.angular_full_width_deg=0.0", self.source)
        self.assertIn("accepted_release", self.source)
        self.assertIn("provider_exit_energy_acceptance", self.source)
        self.assertIn("$energyAcceptance.passed-ne$true", self.source)
        self.assertIn("maximum_exit_transverse_energy_error_per_charge_v", self.source)
        self.assertIn("maximum_exit_transverse_velocity_bias_mm_per_us", self.source)
        self.assertIn("transverse_velocity_bias_passed", self.source)
        self.assertIn("center_particle.transverse_energy_passed-ne$true", self.source)
        self.assertIn("cohort.transverse_energy_passed-ne$true", self.source)
        self.assertIn("required_source_y_offset_from_accelerator_axis_mm", self.source)
        self.assertIn("$sourceDefinitionData.source_y_offset_mm=$sourceYOffset", self.source)
        self.assertIn(
            "$sourceDefinitionData.kinetic_energy_center_ev=$slowEnergy*[math]::Abs($charge)",
            self.source,
        )
        self.assertIn("$sourceDefinitionData.nominal_direction_workbench=@(0.0,1.0,0.0)", self.source)
        self.assertIn("$sourceDefinitionData.angular_full_width_deg=0.0", self.source)
        self.assertIn("SourceDefinitionPath=$conditionSourceDefinition", self.source)

    def test_oa_release_geometry_matches_the_mr_source_cylinder(self) -> None:
        release = json.loads(OA_RELEASE.read_text(encoding="utf-8"))
        self.assertEqual(release["geometry"]["shape"], "cylinder")
        self.assertEqual(release["geometry"]["axis"], "y")
        self.assertEqual(release["geometry"]["radius_mm"], 0.5)
        self.assertEqual(release["geometry"]["height_mm"], 1.0)
        self.assertEqual(release["sampling"]["nominal_direction"], [0.0, 1.0, 0.0])
        self.assertEqual(release["sampling"]["angular_full_width_deg"], 0.0)
        self.assertIn("OA base release must be the shared y-height 1 mm", self.source)
        self.assertIn("$acceptedGeometry.axis-ne'y'", self.source)
        self.assertIn("OA provider geometry differs from the run-local release spec", self.source)

    def test_provider_reuse_is_explicit_and_k_scoped(self) -> None:
        self.assertIn("[string]$ProviderReusePath=''", self.source)
        self.assertIn("$reuse.K-ne$k", self.source)
        self.assertIn("provider_run_manifest=$providerManifest", self.source)
        self.assertIn("provider_runtime_receipt=$acceleratorReceipt", self.source)

    def test_existing_stripe_and_continuation_reuse_is_optional_and_paired(self) -> None:
        self.assertIn("[string]$StripeReuseRunManifest=''", self.source)
        self.assertIn("[string]$ContinuationReuseRunManifest=''", self.source)
        self.assertIn(
            "StripeReuseRunManifest and ContinuationReuseRunManifest must be supplied together.",
            self.source,
        )
        self.assertIn("function Assert-ReusedStripeAndContinuation", self.source)
        self.assertIn("joint_root_tolerance_reached-ne$true", self.source)
        self.assertIn("target_drift_period_ratio-ne$ExpectedK", self.source)
        self.assertIn("accelerator_y_anchor_mm-ne$ExpectedAcceleratorY", self.source)
        self.assertIn("source_stripe_run_id-ne[string]$stripe.run_id", self.source)
        self.assertIn("if($null-ne$reusedPair)", self.source)
        self.assertIn("$safeExitManifest=$null;$coverageManifest=$null", self.source)

    def test_completed_candidate_reuse_is_minimal_and_condition_scoped(self) -> None:
        self.assertIn("[string]$CandidateReuseRunManifest=''", self.source)
        self.assertIn("function Assert-ReusedCandidate", self.source)
        self.assertIn(
            "CandidateReuseRunManifest requires Stripe/Continuation reuse and ProviderReusePath.",
            self.source,
        )
        self.assertIn("native_candidate_end_to_end_chain", self.source)
        self.assertIn("mrtof_native_candidate_end_to_end_chain_summary", self.source)
        self.assertIn("downstream_fixed_grid_workpoint_iteration", self.source)
        self.assertIn("target_drift_period_ratio-ne$ExpectedK", self.source)
        self.assertIn("project_y_mm-ne$ExpectedAcceleratorY", self.source)
        self.assertIn("accelerator_provider_receipt", self.source)
        self.assertIn("source_y_offset_mm-$ExpectedSourceYOffset", self.source)
        self.assertIn("$failureStage='reuse_native_candidate'", self.source)
        self.assertIn("if($CandidateReuseRunManifest)", self.source)

    def test_n1_resume_is_explicit_and_uses_the_existing_workpoint_interface(self) -> None:
        for name in (
            "WorkpointResumeInitialManifest",
            "WorkpointResumeParentCheckpoint",
            "WorkpointResumeSuccessfulChildManifest",
        ):
            self.assertIn(f"[string]${name}=''", self.source)
        self.assertIn(
            "Workpoint resume requires initial manifest, parent checkpoint, and successful child together.",
            self.source,
        )
        self.assertIn(
            "Workpoint resume requires Stripe/Continuation reuse and cannot reuse a completed Candidate.",
            self.source,
        )
        start = self.source.index("if($workpointResumeArguments.Count-eq3){")
        end = self.source.index("if($PythonExe){$workpointArgs.PythonExe", start)
        resume_branch = self.source[start:end]
        self.assertIn("$workpointArgs.InitialWorkpointManifest=", resume_branch)
        self.assertIn("$workpointArgs.ResumeParentCheckpoint=", resume_branch)
        self.assertIn("$workpointArgs.ResumeSuccessfulChildManifest=", resume_branch)
        resume_only, normal_only = resume_branch.split("}else{", 1)
        self.assertNotIn("NativeRuntimeCheckpoint", resume_only)
        self.assertIn("$workpointArgs.ContinuationRunManifest=$continuationManifest", normal_only)
        self.assertIn("$workpointArgs.NativeRuntimeCheckpoint=$nativeRuntimeCheckpoint", normal_only)

    def test_qualified_n1_reuse_skips_workpoint_iteration_and_enters_candidate(self) -> None:
        self.assertIn("[string]$QualifiedWorkpointRunPath=''", self.source)
        self.assertIn(
            "Qualified workpoint reuse requires Stripe/Continuation reuse and excludes Candidate or checkpoint resume.",
            self.source,
        )
        self.assertIn("$failureStage='reuse_n1_workpoint'", self.source)
        self.assertIn("$workpointRun=(Resolve-Path -LiteralPath $QualifiedWorkpointRunPath).Path", self.source)
        self.assertIn("$workpointHandoff.status-ne'within_tolerance'", self.source)
        self.assertIn("$workpointHandoff.qualification-ne'candidate_bunch_screening_authorized'", self.source)
        self.assertIn("QualifiedWorkpointRunPath=$workpointRun", self.source)

    def test_new_provider_rebinds_only_the_accelerator_before_any_mr_flight(self) -> None:
        rebind = self.source.index("native_system_runtime rebind-accelerator")
        safe_exit = self.source.index("run_two_prism_trial.ps1")
        workpoint = self.source.index("run_downstream_workpoint_iteration.ps1")
        candidate = self.source.index("run_native_candidate_chain.ps1")
        self.assertLess(rebind, safe_exit)
        self.assertLess(rebind, workpoint)
        self.assertLess(rebind, candidate)
        self.assertIn("$nativeBundle=$providerBoundBundle", self.source)
        self.assertIn("response_refine_performed=$false", self.source)
        self.assertNotIn("Copy-Item -LiteralPath $accelerator", self.source)

    def test_provider_owns_source_y_offset_without_legacy_offset_gate(self) -> None:
        self.assertIn("$sourceYOffset=[double]$provider.source_y_offset", self.source)
        self.assertNotIn("$legacySourceYOffset", self.source)
        self.assertNotIn("Source-definition y offset differs", self.source)
        self.assertIn("$sourceDefinitionData.source_y_offset_mm=$sourceYOffset", self.source)
        self.assertIn("AcceleratorSourceYOffsetMm=$sourceYOffset", self.source)

    def test_r130_authority_remains_the_mirror_run(self) -> None:
        self.assertIn("fixed_grid_mirror_run_manifest must name run_manifest.json", self.source)
        self.assertIn("mirror_real_field_period_comparison.json", self.source)
        self.assertIn("MirrorRunPath=$mirrorRun;StripeRunPath=$stripeRun", self.source)
        self.assertNotIn("MirrorRunPath=$stripeRun", self.source)

    def test_pair_specific_prism_seed_selection_belongs_to_continuation(self) -> None:
        self.assertNotIn("function Select-ContinuationSeed", self.source)
        self.assertNotIn("both_residual_ranges_enclose_zero", self.source)
        self.assertNotIn("prism_continuation_selection.json", self.source)
        self.assertIn("$continuationArgs.CoverageRunManifest=$coverageManifest", self.source)
        self.assertNotIn("$continuationArgs.ExpectedTopologySignatureSha256", self.source)
        self.assertNotIn("$continuationArgs.InitialP1V", self.source)

    def test_context_cannot_override_pair_identity_or_selected_bracket(self) -> None:
        self.assertIn("Condition context may not override orchestrator argument", self.source)
        for name in (
            "FixedMirrorStripeRunManifest",
            "AcceleratorExitRunManifest",
            "ExpectedTopologySignatureSha256",
            "InitialP1V",
            "InitialP2LowerV",
            "InitialP2UpperV",
        ):
            self.assertIn(f"'{name}'", self.source)

    def test_n1_is_qualified_before_candidate_and_parent_publishes_child_lineage(self) -> None:
        self.assertIn("best_physical_workpoint_handoff.json", self.source)
        self.assertIn("QualifiedWorkpointRunPath=$workpointRun", self.source)
        self.assertIn("RetainBaselineGuiWorkbench=$true", self.source)
        self.assertIn("candidate_run_manifest=$candidateManifest", self.source)
        self.assertIn("workflow_outcome=[string]$candidateSummary.workflow_outcome", self.source)

    def test_structured_physical_nonqualification_is_a_campaign_warning(self) -> None:
        self.assertIn("function Complete-PhysicalConditionWarning", self.source)
        self.assertIn(
            "warning_prism_continuation_not_qualified__continue_parameter_scan",
            self.source,
        )
        self.assertIn(
            "warning_n1_workpoint_not_qualified__continue_parameter_scan",
            self.source,
        )
        self.assertIn("workpoint_incomplete_downstream_blocked", self.source)
        self.assertIn("$workpointSummary.external_interruption-eq$false", self.source)
        self.assertIn("Complete-FailedRun", self.source)

    def test_existing_native_runtime_checkpoint_is_reused_without_pa_materialization(self) -> None:
        self.assertIn("native_runtime_checkpoint_path", self.source)
        self.assertGreaterEqual(
            self.source.count("NativeRuntimeCheckpoint=$nativeRuntimeCheckpoint"), 3
        )

    def test_accelerator_runtime_checkpoint_is_passed_only_to_new_provider(self) -> None:
        self.assertIn("[string]$AcceleratorRuntimeCheckpoint=''", self.source)
        self.assertIn(
            'if($AcceleratorRuntimeCheckpoint){$providerArgs.RuntimeCheckpointPath=',
            self.source,
        )

    def test_wrapper_does_not_duplicate_scheduler_or_hash_checks(self) -> None:
        self.assertNotIn("Get-FileHash", self.source)
        self.assertNotIn("Start-Job", self.source)
        self.assertNotIn("ForEach-Object -Parallel", self.source)
        self.assertNotIn("Enter-HostExecutionLease", self.source)

    def test_continuation_runner_supports_auto_and_legacy_explicit_selection(self) -> None:
        continuation = CONTINUATION_RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$automaticSelection=$explicitSelection.Count-eq0", continuation)
        self.assertIn("'--auto-select-initial-bracket'", continuation)
        self.assertIn("'--expected-topology-signature-sha256'", continuation)
        self.assertIn("Explicit continuation selection requires topology", continuation)


if __name__ == "__main__":
    unittest.main()
