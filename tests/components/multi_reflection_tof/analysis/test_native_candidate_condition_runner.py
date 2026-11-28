import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


RUNNER = (
    Path(__file__).resolve().parents[4]
    / "src/msplatform/workflows/resources/native_candidate_condition_action.ps1"
)
PROFILE = RUNNER.parents[2] / "components/multi_reflection_tof/config/execution_profiles.json"
STORE_OWNER = RUNNER.parents[1] / "mr_native_condition.py"
CONTINUATION_RUNNER = RUNNER.with_name("run_two_prism_segmented_continuation.ps1")
OA_RELEASE = RUNNER.parents[4] / "src/msplatform/components/multi_reflection_tof/config" / "accelerator_component_release_n100.json"


class NativeCandidateConditionRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8-sig")

    def test_physical_stages_delegate_to_existing_runners_in_order(self) -> None:
        stages = [
            "run_dual_stripe_operating_seed.ps1",
            "msplatform.workflows.oa_focus_component",
            "oa_mr.ps1",
            "run_two_prism_segmented_coverage.ps1",
            "run_two_prism_segmented_continuation.ps1",
            "run_downstream_workpoint_iteration.ps1",
            "run_native_candidate_chain.ps1",
        ]
        positions = [self.source.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("FixedGridRunManifest=$fixedMirrorManifest", self.source)
        self.assertIn("'--release-spec-path',$releaseSpec", self.source)
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
        end = self.source.index("$workpointArgs.PythonExe=$python", start)
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
        safe_exit = self.source.index("Join-Path $workflowResources 'oa_mr.ps1'")
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
            "WorkspaceRoot",
            "ArtifactRoot",
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
        self.assertIn("failure_stage=$failureStage", self.source)
        self.assertNotIn("Complete-FailedRun", self.source)
        self.assertIn("run_managed_stage", STORE_OWNER.read_text(encoding="utf-8"))

    def test_existing_native_runtime_checkpoint_is_reused_without_pa_materialization(self) -> None:
        self.assertIn("native_runtime_checkpoint_path", self.source)
        self.assertGreaterEqual(
            self.source.count("NativeRuntimeCheckpoint=$nativeRuntimeCheckpoint"), 3
        )

    def test_accelerator_runtime_checkpoint_is_passed_only_to_new_provider(self) -> None:
        self.assertIn("[string]$AcceleratorRuntimeCheckpoint=''", self.source)
        self.assertIn(
            "if($AcceleratorRuntimeCheckpoint){$providerArgv+=@('--runtime-checkpoint-path',$AcceleratorRuntimeCheckpoint)}",
            self.source,
        )

    def test_wrapper_does_not_duplicate_scheduler_or_hash_checks(self) -> None:
        self.assertNotIn("Get-FileHash", self.source)
        self.assertNotIn("Start-Job", self.source)
        self.assertNotIn("ForEach-Object -Parallel", self.source)
        self.assertNotIn("Enter-HostExecutionLease", self.source)

    def test_condition_uses_installed_resources_and_forwards_explicit_execution_roots(self) -> None:
        self.assertIn("[Parameter(Mandatory)][string]$WorkspaceRoot", self.source)
        self.assertIn("[Parameter(Mandatory)][string]$ArtifactRoot", self.source)
        self.assertIn("import msplatform;print(Path(msplatform.__file__).resolve().parent)", self.source)
        self.assertIn("$workflowResources=Join-Path $packageRoot 'workflows/resources'", self.source)
        self.assertIn("$simionResources=Join-Path $packageRoot 'backends/simion/resources'", self.source)
        self.assertIn("'--workspace-root',$workspaceRoot,'--store-root',$storeRoot", self.source)
        for name in ("stripeArgs", "safeExitArgs", "coverageArgs", "continuationArgs",
                     "workpointArgs", "candidateArgs"):
            self.assertIn(f"${name}.PythonExe=$python", self.source)
        for name in ("stripeArgs", "coverageArgs", "continuationArgs", "workpointArgs", "candidateArgs"):
            self.assertIn(f"${name}.WorkspaceRoot=$workspaceRoot", self.source)
            self.assertIn(f"${name}.ArtifactRoot=$artifactRoot", self.source)
        self.assertIn("RepoRoot=$workspaceRoot", self.source)
        self.assertIn("CompositionPlanPath=$CompositionPlanPath;LocalScopePath=$LocalScopePath", self.source)
        self.assertIn("'--store-root',$storeRoot", self.source)
        self.assertIn("oa_provider_result.json", self.source)
        self.assertNotIn("projects\\orthogonal_accelerator", self.source)
        self.assertIn("Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind assembly", self.source)
        self.assertIn("& $python -I -B -m msplatform.workflows.oa_mr.native_system_runtime", self.source)
        self.assertNotIn(".venv", self.source)
        self.assertNotIn("Join-Path $PSScriptRoot", self.source)
        self.assertNotIn("PYTHONPATH", self.source)

    def test_profile_registers_store_python_cli_directly(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))["profiles"][0]
        step = profile["steps"][0]
        owner = STORE_OWNER.read_text(encoding="utf-8")
        self.assertEqual(step["shell"], "python")
        self.assertEqual(step["entrypoint"], "src/msplatform/workflows/mr_native_condition.py")
        self.assertIn("condition", step["arguments"])
        self.assertIn("--store-root", step["arguments"])
        self.assertIn("--powershell-exe", step["arguments"])
        self.assertIn("standalone_native_store", owner)
        self.assertIn("recover_managed_native_store_stage", owner)
        self.assertIn("recover_run_publication", owner)

    def test_continuation_runner_supports_auto_and_legacy_explicit_selection(self) -> None:
        continuation = CONTINUATION_RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$automaticSelection=$explicitSelection.Count-eq0", continuation)
        self.assertIn("'--auto-select-initial-bracket'", continuation)
        self.assertIn("'--expected-topology-signature-sha256'", continuation)
        self.assertIn("Explicit continuation selection requires topology", continuation)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class NativeCandidateConditionPreparationTests(unittest.TestCase):
    def test_default_campaign_child_freezes_the_same_plan_and_optional_scope(self) -> None:
        # Execute both production scripts unchanged. Only lifecycle allocation
        # and the first physical stage are substituted: no solver is requested.
        for with_scope in (False, True):
            with self.subTest(with_scope=with_scope), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                repo = root / "repo"
                analysis = repo / "src/msplatform/workflows/resources"
                analysis.mkdir(parents=True)
                shutil.copyfile(RUNNER.with_name("native_candidate_campaign_action.ps1"),
                                analysis / "native_candidate_campaign_action.ps1")
                shutil.copyfile(RUNNER, analysis / RUNNER.name)
                support = repo / "src" / "msplatform" / "execution" / "resources" / "run_artifact_support.ps1"
                support.parent.mkdir(parents=True)
                real_support = RUNNER.parents[4] / "src" / "msplatform" / "execution" / "resources" / support.name
                support.write_text(
                    f". '{real_support.as_posix()}'\n" + r"""
function Resolve-RunArtifactRoot {
  param($ArtifactRoot,$OwnerKind,$OwnerId,$Python)
  return Join-Path $ArtifactRoot (Join-Path $OwnerKind's' $OwnerId)
}
function New-RunPackage {
  param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,
    [switch]$RetentionContractEnabled,$RetentionClass,[switch]$CapacityLedgerLifecycleEnabled)
  $run=Join-Path (Join-Path $ArtifactRoot 'runs') $RunId
  $inputs=Join-Path $run 'inputs'
  New-Item -ItemType Directory -Path $inputs -Force|Out-Null
  $config=Join-Path $run 'run_config.json'
  Write-RunJson -Path $config -Value @{run_id=$RunId;project=$Project;mode=$Mode}
  return [pscustomobject]@{input_dir=$inputs;run_config=$config;summary=(Join-Path $run 'summary.json')}
}
function Complete-FailedRun {
  param($Python,$RepoRoot,$RunConfig,$Summary,$SummaryRole,$Reason,$Software,$Status,$FailureStage)
  $config=Get-Content -LiteralPath $RunConfig -Raw|ConvertFrom-Json -AsHashtable
  Write-RunJson -Path (Join-Path (Split-Path -Parent $RunConfig) 'run_manifest.json') -Value @{
    schema_version=2;run_id=$config.run_id;project=$config.project;mode=$config.mode;status=$Status}
  Write-RunJson -Path $Summary -Value @{status=$Status;failure_stage=$FailureStage;reason=$Reason}
}
""",
                    encoding="utf-8",
                )
                (analysis / "run_dual_stripe_operating_seed.ps1").write_text(
                    "param([Parameter(Mandatory)]$AcceleratorComponentContractPath,"
                    "[Parameter(Mandatory)]$AcceleratorGeometryProfileId,"
                    "[Parameter(Mandatory)]$FixedGridRunManifest,[Parameter(Mandatory)]$ContractPath,"
                    "[Parameter(Mandatory)]$RunId,[Parameter(Mandatory)]$WorkspaceRoot,"
                    "[Parameter(Mandatory)]$ArtifactRoot,[Parameter(Mandatory)]$PythonExe)\n"
                    "throw 'PREPARE_BOUNDARY_BEFORE_PHYSICS'\n",
                    encoding="utf-8",
                )
                selected_python = root / "selected_python.cmd"
                selected_python.write_text(
                    f"@echo off\r\necho {(repo / 'src/msplatform').as_posix()}\r\n",
                    encoding="utf-8",
                )
                condition_entry = analysis / "condition_entry.ps1"
                condition_entry.write_text(
                    "param($ConditionPath,$ContextPath,$RunId,$CompositionPlanPath,$LocalScopePath='',$WorkspaceRoot,$ArtifactRoot,$PythonExe,$StoreRoot,$ResultPath)\n"
                    f"$arguments=@{{ConditionPath=$ConditionPath;ContextPath=$ContextPath;RunId=$RunId;"
                    f"CompositionPlanPath=$CompositionPlanPath;WorkspaceRoot='{repo.as_posix()}';"
                    f"ArtifactRoot='{(root / 'artifacts').as_posix()}';PythonExe='{selected_python.as_posix()}';StoreRoot=$StoreRoot}}\n"
                    "if($LocalScopePath){$arguments.LocalScopePath=$LocalScopePath}\n"
                    "$run=Join-Path $ArtifactRoot \"components/multi_reflection_tof/runs/$RunId\";$inputs=Join-Path $run 'inputs'\n"
                    "New-Item -ItemType Directory -Path $inputs -Force|Out-Null\n"
                    "$config=Join-Path $run 'run_config.json';$summary=Join-Path $run 'summary.json'\n"
                    "@{run_id=$RunId}|ConvertTo-Json|Set-Content -LiteralPath $config;@{status='checkpoint'}|ConvertTo-Json|Set-Content -LiteralPath $summary\n"
                    "$package=Join-Path $inputs 'package.json';@{run_dir=$run;input_dir=$inputs;run_config=$config;summary=$summary}|ConvertTo-Json|Set-Content -LiteralPath $package\n"
                    "$arguments.PackagePath=$package\n"
                    "try{"
                    f"& (Join-Path $PSScriptRoot '{RUNNER.name}') @arguments"
                    "}catch{"
                    "@{run_id=$RunId;project='multi_reflection_tof';mode='native_candidate_single_condition';status='failed'}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $run 'run_manifest.json');"
                    "@{manifest=@{path=(Join-Path $run 'run_manifest.json')}}|ConvertTo-Json|Set-Content -LiteralPath $ResultPath;throw}\n",
                    encoding="utf-8",
                )
                campaign = root / "campaign.json"
                campaign.write_text(json.dumps([{"K": 25.5, "accelerator_y": -55.0}]), encoding="utf-8")
                contract = root / "contract.json"
                contract.write_text(json.dumps({"nominal": {"target_drift_period_ratio": 1},
                    "accelerator": {"focus_y_anchor": {"project_y_mm": 0}}}), encoding="utf-8")
                mirror = root / "mirror"
                (mirror / "results").mkdir(parents=True)
                for path in (mirror / "run_manifest.json", mirror / "results" / "mirror_real_field_period_comparison.json"):
                    path.write_text("{}", encoding="utf-8")
                context = root / "context.json"
                context.write_text(json.dumps({
                    "schema_version": 2, "role": "mrtof_native_candidate_condition_context",
                    "accelerator_component_contract_path": str(RUNNER.parents[4] / "src/msplatform/components/orthogonal_accelerator/component_contract.json"),
                    "accelerator_geometry_profile_id": "closed_two_zone_compact_mr_axial_r3_gap1_4mm",
                    "contract_path": str(contract),
                    "fixed_grid_mirror_run_manifest": str(mirror / "run_manifest.json"),
                    "geometry_review_run_path": str(root), "native_corridor_bank_run_path": str(root),
                    "native_system_runtime_bundle_path": str(contract), "native_runtime_checkpoint_path": "",
                    "source_definition_path": str(contract), "oa_base_release_spec_path": str(contract),
                    "oa_request_path": str(contract),
                }), encoding="utf-8")
                plan, scope = root / "plan.json", root / "scope.json"
                plan.write_bytes(b'{"fixture": "explicit parent plan"}\n')
                scope.write_bytes(b'{"fixture": "explicit local scope"}\n')
                checkpoint = root / "checkpoint.json"
                campaign_package = root / "campaign_package.json"
                campaign_package.write_text("{}", encoding="utf-8")
                (root / "store").mkdir()
                command = ["pwsh", "-NoProfile", "-NonInteractive", "-File",
                    str(analysis / "native_candidate_campaign_action.ps1"),
                    "-StoreRoot", str(root / "store"), "-PackagePath", str(campaign_package),
                    "-CampaignPath", str(campaign), "-CheckpointPath", str(checkpoint),
                    "-ConditionContextPath", str(context), "-CompositionPlanPath", str(plan),
                    "-ConditionRunnerPath", str(condition_entry),
                    "-WorkspaceRoot", str(repo), "-ArtifactRoot", str(root / "artifacts"),
                    "-PythonExe", str(selected_python),
                    "-CampaignStamp", "20261028_000000"]
                if with_scope:
                    command.extend(["-LocalScopePath", str(scope)])
                result = subprocess.run(command, cwd=repo, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Condition run terminated with status failed", result.stdout + result.stderr)
                state = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
                self.assertEqual(state["conditions"][0]["terminal_state"], "failed")
                run = Path(state["conditions"][0]["run_manifest"]).parent
                config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
                summary = json.loads((run / "summary.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(summary["failure_stage"], "fixed_grid_stripe_seed")
                self.assertEqual(summary["reason"], "PREPARE_BOUNDARY_BEFORE_PHYSICS")
                for key, source in (("composition_plan", plan), ("local_scope", scope)):
                    if key == "local_scope" and not with_scope:
                        self.assertIsNone(state[key])
                        self.assertNotIn(key, config["inputs"])
                        continue
                    frozen = Path(config["inputs"][key])
                    self.assertEqual(frozen.parent, run / "inputs")
                    self.assertEqual(frozen.read_bytes(), source.read_bytes())
                    self.assertEqual(frozen.read_bytes(), Path(state[key]["path"]).read_bytes())
                frozen_contract = json.loads(Path(config["inputs"]["condition_contract"]).read_text(encoding="utf-8-sig"))
                self.assertEqual(frozen_contract["nominal"]["target_drift_period_ratio"], 25.5)
                self.assertEqual(frozen_contract["accelerator"]["focus_y_anchor"]["project_y_mm"], -55.0)

    def test_new_oa_provider_is_read_only_from_the_component_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            resources = repo / "src/msplatform/workflows/resources"
            provider_resources = repo / "src/msplatform/backends/simion/resources"
            resources.mkdir(parents=True)
            provider_resources.mkdir(parents=True)
            condition_runner = resources / RUNNER.name
            shutil.copyfile(RUNNER, condition_runner)
            real_support = RUNNER.parents[4] / "src/msplatform/execution/resources/run_artifact_support.ps1"
            support = repo / "src/msplatform/execution/resources" / real_support.name
            support.parent.mkdir(parents=True)
            support.write_text(
                f". '{real_support.as_posix()}'\n" + r"""
function Resolve-RunArtifactRoot {
  param($ArtifactRoot,$OwnerKind,$OwnerId,$Python)
  return Join-Path $ArtifactRoot (Join-Path $OwnerKind's' $OwnerId)
}
function New-RunPackage {
  param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,
    [switch]$RetentionContractEnabled,$RetentionClass,[switch]$CapacityLedgerLifecycleEnabled)
  $run=Join-Path (Join-Path $ArtifactRoot 'runs') $RunId
  $inputs=Join-Path $run 'inputs'
  New-Item -ItemType Directory -Path $inputs -Force|Out-Null
  $config=Join-Path $run 'run_config.json'
  Write-RunJson -Path $config -Value @{run_id=$RunId;project=$Project;mode=$Mode}
  return [pscustomobject]@{input_dir=$inputs;run_config=$config;summary=(Join-Path $run 'summary.json')}
}
function Complete-FailedRun {
  param($Python,$RepoRoot,$RunConfig,$Summary,$SummaryRole,$Reason,$Software,$Status,$FailureStage)
  Write-RunJson -Path $Summary -Value @{status=$Status;failure_stage=$FailureStage;reason=$Reason}
}
""",
                encoding="utf-8",
            )
            (resources / "run_dual_stripe_operating_seed.ps1").write_text(r"""
param([Parameter(Mandatory)]$AcceleratorComponentContractPath,[Parameter(Mandatory)]$AcceleratorGeometryProfileId,
  [Parameter(Mandatory)]$FixedGridRunManifest,[Parameter(Mandatory)]$ContractPath,[Parameter(Mandatory)]$RunId,
  [Parameter(Mandatory)]$WorkspaceRoot,[Parameter(Mandatory)]$ArtifactRoot,[Parameter(Mandatory)]$PythonExe)
$run=Join-Path $ArtifactRoot "components/multi_reflection_tof/runs/$RunId"
New-Item -ItemType Directory -Path $run -Force|Out-Null
@{run_id=$RunId}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $run 'run_manifest.json')
@{selected_seed=@{selected_exact_K_slow_energy_per_charge_v=5.0}}|ConvertTo-Json -Depth 5|
  Set-Content -LiteralPath (Join-Path $run 'summary.json')
""", encoding="utf-8")
            receipt = {
                "role": "orthogonal_accelerator_mrtof_runtime_receipt",
                "status": "published_standalone_response_bank",
                "mrtof_projection": {
                    "accepted_release": {
                        "slow_energy_center_per_charge_v": 5.0,
                        "slow_energy_full_width_per_charge_v": 0.2,
                        "mass_th": 524.0,
                        "charge_e": 1,
                        "nominal_direction": [0.0, 1.0, 0.0],
                        "angular_full_width_deg": 0.0,
                        "geometry": {
                            "shape": "cylinder", "axis": "y", "radius_mm": 0.5,
                            "height_mm": 1.0, "center_mm": [0.0, 0.0, 0.0],
                        },
                    },
                    "required_source_y_offset_from_accelerator_axis_mm": -1.0,
                    "provider_exit_energy_acceptance": {
                        "passed": True,
                        "tolerances": {
                            "maximum_exit_transverse_energy_error_per_charge_v": 0.0,
                            "maximum_exit_transverse_velocity_bias_mm_per_us": 0.0,
                        },
                        "center_particle": {
                            "transverse_energy_passed": True,
                            "transverse_velocity_bias_passed": True,
                        },
                        "cohort": {
                            "transverse_energy_passed": True,
                            "transverse_velocity_bias_passed": True,
                        },
                    },
                },
            }
            provider_driver = root / "provider_driver.py"
            provider_driver.write_text(
                "import json,sys\nfrom pathlib import Path\n"
                f"root=Path({str(root)!r});repo=Path({str(repo)!r});run_inputs=root/'artifacts/components/multi_reflection_tof/runs/20261125_000000__analysis__python__condition/inputs'\n"
                "args=sys.argv[1:]\n"
                "if '-c' in args:\n"
                "    if run_inputs.is_dir(): (run_inputs/'native_system_runtime_bundle.json').write_text('{}')\n"
                "    print((repo/'src/msplatform').as_posix());raise SystemExit(0)\n"
                "if 'msplatform.workflows.oa_mr.native_system_runtime' in args:\n"
                "    output=Path(args[args.index('--bundle-output')+1]);output.write_text('{}');raise SystemExit(0)\n"
                "assert 'msplatform.workflows.oa_focus_component' in args\n"
                "def option(name): return args[args.index(name)+1]\n"
                "run=root/'artifacts/components/orthogonal_accelerator/runs'/option('--run-id')\n"
                "(run/'results').mkdir(parents=True)\n"
                "(run/'run_manifest.json').write_text(json.dumps({'project':'orthogonal_accelerator','mode':'component_focus_workflow','status':'success','run_id':option('--run-id')}),encoding='utf8')\n"
                f"(run/'results/mrtof_runtime_receipt.json').write_text(json.dumps({receipt!r}),encoding='utf8')\n"
                "(run/'transport.json').write_text(json.dumps({'workspace':option('--workspace-root'),'store':option('--store-root'),'powershell':option('--powershell-exe')}),encoding='utf8')\n"
                "(Path(option('--receipt-path'))).write_text(json.dumps({'run_directory':str(run),'manifest':{'path':str(run/'run_manifest.json')}}),encoding='utf8')\n",
                encoding="utf-8",
            )
            run_id = "20261125_000000__analysis__python__condition"
            run = root / "artifacts/components/multi_reflection_tof/runs" / run_id
            run_inputs = run / "inputs"
            run_inputs.mkdir(parents=True)
            run_config = run / "run_config.json"
            run_config.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
            (run / "summary.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
            package = run_inputs / "package.json"
            package.write_text(json.dumps({"run_dir": str(run), "input_dir": str(run_inputs),
                "run_config": str(run_config), "summary": str(run / "summary.json")}), encoding="utf-8")
            (root / "store").mkdir()
            selected_python = root / "selected_python.cmd"
            selected_python.write_text(
                f"@echo off\r\n\"{sys.executable}\" \"{provider_driver}\" %*\r\nexit /b %errorlevel%\r\n",
                encoding="utf-8",
            )
            contract = root / "contract.json"
            contract.write_text(json.dumps({
                "nominal": {"target_drift_period_ratio": 1},
                "accelerator": {"focus_y_anchor": {"project_y_mm": 0}},
            }), encoding="utf-8")
            release = root / "release.json"
            release.write_text(json.dumps({'schema_version': 2,
                "role": 'repository_particle_release',
                "species": {'species_kind': 'ion', "charge_state": 1, "mass_amu": 524.0},
                "sampling": {
                    "kinetic_energy": {"center_ev": 1.0, "full_width_ev": 0.2},
                    "nominal_direction": [0.0, 1.0, 0.0], "angular_full_width_deg": 0.0,
                },
                "geometry": {
                    "shape": "cylinder", "axis": "y", "radius_mm": 0.5,
                    "height_mm": 1.0, "center_mm": [0.0, 0.0, 0.0],
                },
            }), encoding="utf-8")
            mirror = root / "mirror"
            (mirror / "results").mkdir(parents=True)
            (mirror / "run_manifest.json").write_text("{}", encoding="utf-8")
            (mirror / "results/mirror_real_field_period_comparison.json").write_text("{}", encoding="utf-8")
            context = root / "context.json"
            context.write_text(json.dumps({
                "schema_version": 2, "role": "mrtof_native_candidate_condition_context",
                "accelerator_component_contract_path": str(contract),
                "accelerator_geometry_profile_id": "closed_two_zone_compact_mr_axial_r3_gap1_4mm",
                "contract_path": str(contract),
                "fixed_grid_mirror_run_manifest": str(mirror / "run_manifest.json"),
                "geometry_review_run_path": str(root), "native_corridor_bank_run_path": str(root),
                "native_system_runtime_bundle_path": str(contract), "native_runtime_checkpoint_path": "",
                "source_definition_path": str(contract), "oa_base_release_spec_path": str(release),
                "oa_request_path": str(contract),
            }), encoding="utf-8")
            condition = root / "condition.json"
            condition.write_text(json.dumps({
                "schema_version": 1, "role": "mrtof_native_candidate_campaign_condition",
                "K": 25.5, "accelerator_y": -55.0,
            }), encoding="utf-8")
            plan = root / "plan.json"
            plan.write_text("{}", encoding="utf-8")
            (root / "results").mkdir()
            (root / "results/pa_family_cache_publication.json").write_text(json.dumps({
                "cache_key": "fixture-cache", "generation_sha256": "fixture-generation",
            }), encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(condition_runner),
                 "-ConditionPath", str(condition), "-ContextPath", str(context), "-RunId", run_id,
                 "-WorkspaceRoot", str(repo), "-ArtifactRoot", str(root / "artifacts"),
                 "-PythonExe", str(selected_python), "-CompositionPlanPath", str(plan),
                 "-StoreRoot", str(root / "store"), "-PackagePath", str(package)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=60, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            summary = json.loads((
                root / "artifacts/components/multi_reflection_tof/runs" / run_id / "summary.json"
            ).read_text(encoding="utf-8-sig"))
            self.assertEqual(summary["failure_stage"], "accelerator_safe_exit")
            self.assertTrue((run_inputs / "native_system_runtime_bundle.json").is_file())
            provider_run = root / "artifacts/components/orthogonal_accelerator/runs/20261125_000000__sim__simion__mrtof-condition-oa-provider"
            self.assertTrue((provider_run / "run_manifest.json").is_file())
            transport = json.loads((provider_run / "transport.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(transport, {
                "workspace": str(repo), "store": str(root / "store"),
                "powershell": str(Path(shutil.which("pwsh")).resolve()),
            })
            self.assertFalse((root / "artifacts/projects").exists())


class NativeConditionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        from dataclasses import replace
        from msplatform.execution.run_session import RunSession
        from msplatform.storage import ArtifactStore
        from tests.contracts.test_execution_runtime import NormalOwnerTests

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        helper = NormalOwnerTests()
        context = helper._context(self.root)
        capacity = self.root / "capacity.json"
        capacity.write_text(json.dumps(helper._policy()), encoding="utf-8")
        stage = dict(limits=dict(wall_clock_seconds=120, transient_run_directory_bytes=16*1024**2,
            process_tree_working_set_bytes=1024**3, minimum_system_available_memory_bytes=1,
            compact_final_retained_bytes=16*1024**2, automatic_retry_count=0),
            artifact_retention=dict(policy_version=1, **{"class": "compact"}))
        policy = self.root / "stages.json"
        policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
            stages={"mr_native_condition": stage})), encoding="utf-8")
        self.context = replace(context, capacity_policy_path=capacity, stage_policy_path=policy,
            tools={"simion": Path(sys.executable)})
        self.store = ArtifactStore(self.root / "store")
        self.condition = self.root / "condition.json"
        self.condition.write_text(json.dumps({"schema_version": 1,
            "role": "mrtof_native_candidate_campaign_condition", "K": 25.5, "accelerator_y": -55.0}), encoding="utf-8")
        self.context_path = self.root / "context.json"
        self.context_path.write_text(json.dumps({"schema_version": 2,
            "role": "mrtof_native_candidate_condition_context"}), encoding="utf-8")
        self.plan = self.root / "plan.json"
        self.plan.write_text('{"fixture":"plan"}', encoding="utf-8")
        self.original_process = RunSession.run_process

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, run_id: str, *, failed: bool = False, receipt: Path | None = None):
        from msplatform.workflows.mr_native_condition import run_native_condition

        def transport(session, operation_id, **kwargs):
            status = "failed" if failed else "success"
            summary = dict(schema_version=1, role="mrtof_native_candidate_single_condition_summary",
                status=status, workflow_outcome=None if failed else "within_tolerance", K=25.5,
                accelerator_y_mm=-55.0)
            if failed:
                summary.update(failure_stage="fixed_grid_stripe_seed", reason="INERT_FIRST_PHYSICAL_STAGE")
            code = "import json,pathlib,sys;pathlib.Path(sys.argv[1]).write_text(json.dumps(" + repr(summary) + "),encoding='utf8');sys.exit(" + ("7" if failed else "0") + ")"
            kwargs.update(executable=Path(sys.executable), arguments=["-c", code, str(session.artifact_run_dir/"summary.json")])
            return self.original_process(session, operation_id, **kwargs)

        environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="",
            MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID="", MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE="")
        with patch.dict(os.environ, environment), patch(
                "msplatform.execution.run_session.RunSession.run_process", new=transport):
            return run_native_condition(self.context, artifact_store=self.store,
                condition_path=self.condition, context_path=self.context_path, composition_plan_path=self.plan,
                run_id=run_id, artifact_root=self.root/"legacy", receipt_path=receipt)

    def test_store_success_cold_read_and_public_recovery(self) -> None:
        from msplatform.workflows.mr_native_condition import recover_native_condition_publication
        result = self.invoke("20261128_010000__test__python__store-condition")
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.store.run_status(result["store_run_id"])["execution_status"], "succeeded")
        self.assertTrue(self.store.inspect_run(result["store_run_id"]).is_dir())
        before = Path(result["manifest"]["path"]).read_bytes()
        recovery = recover_native_condition_publication(store=self.store,
            store_run_id=result["store_run_id"], context=self.context)
        self.assertFalse(recovery["run_recovered"])
        self.assertEqual(Path(result["manifest"]["path"]).read_bytes(), before)

    def test_store_failure_preserves_stage_and_result_receipt(self) -> None:
        receipt = self.root / "condition-result.json"
        result = self.invoke("20261128_010001__test__python__store-condition-failure", failed=True, receipt=receipt)
        self.assertEqual(result["status"], "failed")
        summary = json.loads(Path(result["run_directory"], "summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["failure_stage"], "fixed_grid_stripe_seed")
        published = json.loads(receipt.read_text(encoding="utf-8-sig"))
        self.assertTrue(Path(published["manifest"]["path"]).is_file())
        self.assertEqual(self.store.run_status(result["store_run_id"])["execution_status"], "failed")

    def test_python_cli_requires_legacy_root_before_store_registration(self) -> None:
        result = subprocess.run([sys.executable, "-m", "msplatform.workflows.mr_native_condition", "condition",
            "--condition-path", str(self.condition), "--context-path", str(self.context_path),
            "--composition-plan-path", str(self.plan), "--run-id", "20261128_010003__test__python__store-condition-legacy",
            "--workspace-root", str(self.root), "--store-root", str(self.store.root),
            "--powershell-exe", shutil.which("pwsh")], cwd=self.root,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy_artifact_root", result.stdout + result.stderr)
        with self.store._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_missing_plan_is_rejected_before_store_registration(self) -> None:
        from msplatform.workflows.mr_native_condition import run_native_condition
        with self.assertRaises(FileNotFoundError):
            run_native_condition(self.context, artifact_store=self.store, condition_path=self.condition,
                context_path=self.context_path, composition_plan_path=self.root/"missing.json",
                run_id="20261128_010002__test__python__store-condition-missing", artifact_root=self.root/"legacy")
        with self.store._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
