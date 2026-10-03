import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


RUNNER = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "run_native_candidate_campaign.ps1"
)
CAMPAIGN = RUNNER.parents[1] / "config" / "native_candidate_campaign_k_y_scan.json"


class NativeCandidateCampaignRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8-sig")

    def test_campaign_delegates_one_complete_condition_without_physics(self) -> None:
        self.assertIn("[string]$ConditionRunnerPath=''", self.source)
        self.assertIn("[Parameter(Mandatory)][string]$ConditionContextPath", self.source)
        self.assertIn("ConditionRunnerPath must be a file.", self.source)
        self.assertIn("run_native_candidate_condition.ps1", self.source)
        self.assertIn("& $conditionRunner @arguments|Out-Host", self.source)
        self.assertNotIn("run_target_operating_point_chain.ps1", self.source)
        self.assertNotIn("run_two_prism_segmented_coverage.ps1", self.source)
        self.assertNotIn("run_native_candidate_chain.ps1", self.source)

    def test_input_is_an_explicit_ordered_k_and_accelerator_y_list(self) -> None:
        self.assertIn("Campaign JSON must be an ordered array.", self.source)
        self.assertIn("-ne'accelerator_y,K'", self.source)
        self.assertIn("must contain exactly K and accelerator_y", self.source)
        self.assertIn("K=[double]$Condition.K;accelerator_y=[double]$Condition.accelerator_y", self.source)

    def test_checkpoint_is_condition_level_only(self) -> None:
        self.assertIn("terminal_state='pending';attempt_count=0", self.source)
        self.assertIn("run_manifest=$null;workflow_outcome=$null", self.source)
        self.assertNotIn("coverage_run_manifest", self.source)
        self.assertIn("continuation_reuse_run_manifest", self.source)
        self.assertNotIn("Get-FileHash", self.source)
        self.assertNotIn("SHA256", self.source)

    def test_provider_cache_is_k_scoped_and_passed_explicitly(self) -> None:
        self.assertIn("[string]$InitialProviderReuseMapPath=''", self.source)
        self.assertIn("Read-InitialProviderReuseMap", self.source)
        self.assertIn("provider_cache=$providerCache", self.source)
        self.assertIn("Get-KCacheKey", self.source)
        self.assertIn("$arguments.ProviderReusePath=$reusePath", self.source)
        self.assertIn("orthogonal_accelerator_mrtof_runtime_receipt", self.source)

    def test_condition_reuse_map_is_pair_scoped_and_passed_explicitly(self) -> None:
        self.assertIn("[string]$ConditionReuseMapPath=''", self.source)
        self.assertIn("Get-ConditionReuseKey", self.source)
        self.assertIn("Read-ConditionReuseMap", self.source)
        self.assertIn("stripe_reuse_run_manifest", self.source)
        self.assertIn("continuation_reuse_run_manifest", self.source)
        self.assertIn("$arguments.StripeReuseRunManifest", self.source)
        self.assertIn("$arguments.ContinuationReuseRunManifest", self.source)
        self.assertIn("candidate_reuse_run_manifest", self.source)
        self.assertIn("$arguments.CandidateReuseRunManifest", self.source)

    def test_terminal_success_and_warning_advance_in_order(self) -> None:
        self.assertIn("if($condition.terminal_state-in@('success','warning'))", self.source)
        self.assertIn("$terminal.workflow_outcome-eq'within_tolerance'", self.source)
        self.assertIn("$outcome-notlike'warning_*'", self.source)
        self.assertIn("{'success'}else{'warning'}", self.source)
        self.assertIn("$state.status='success'", self.source)

    def test_failure_stops_and_incomplete_attempt_gets_new_identity(self) -> None:
        self.assertIn("if($condition.terminal_state-eq'failed')", self.source)
        self.assertIn("$attempt=[int]$condition.attempt_count+1", self.source)
        self.assertIn("(($Attempt-1)*$ConditionCount)", self.source)
        self.assertIn("$terminal.status-in@('checkpoint','interrupted')", self.source)
        self.assertIn("will receive a new identity on restart", self.source)
        self.assertIn("$condition.terminal_state='failed';Write-Checkpoint", self.source)
        self.assertNotIn("Start-Job", self.source)
        self.assertNotIn("ForEach-Object -Parallel", self.source)

    def test_nonterminal_workpoint_resume_is_forwarded_explicitly(self) -> None:
        self.assertIn("Get-NonterminalWorkpointResume", self.source)
        self.assertIn("$arguments.WorkpointResumeInitialManifest", self.source)
        self.assertIn("$arguments.WorkpointResumeParentCheckpoint", self.source)
        self.assertIn("$arguments.WorkpointResumeSuccessfulChildManifest", self.source)
        self.assertIn("$arguments.QualifiedWorkpointRunPath", self.source)
        self.assertIn("condition_runner_resume_wiring_version=2", self.source)
        self.assertNotIn("Get-FileHash", self.source)
        self.assertNotIn("SHA256", self.source)

    def test_completed_conditions_require_their_existing_manifest(self) -> None:
        self.assertIn("Condition manifest identity is invalid", self.source)
        self.assertIn("Condition summary identity or outcome is invalid", self.source)
        self.assertIn("Condition runner did not publish a run manifest", self.source)

    def test_context_and_runner_are_frozen_without_payload_hashing(self) -> None:
        self.assertIn("context_source_path=$conditionContext;frozen_context=$frozenContext", self.source)
        self.assertIn("ConditionContextPath differs from the campaign checkpoint", self.source)
        self.assertIn("Condition runner identity differs from the campaign checkpoint", self.source)
        self.assertIn("last_write_time_utc_ticks", self.source)
        self.assertNotIn("Get-FileHash", self.source)

    def test_condition_is_reconciled_and_atomically_rewritten(self) -> None:
        self.assertIn("Assert-ConditionInput -Condition $condition", self.source)
        self.assertIn("Condition input differs from checkpoint K/y", self.source)
        self.assertIn("Write-ConditionInput -Condition $Condition -Path $path", self.source)

    def test_authoritative_campaign_has_the_requested_order(self) -> None:
        self.assertEqual(
            json.loads(CAMPAIGN.read_text(encoding="utf-8")),
            [
                {"K": 25.5, "accelerator_y": -50.0},
                {"K": 24.5, "accelerator_y": -50.0},
                {"K": 23.5, "accelerator_y": -50.0},
                {"K": 25.5, "accelerator_y": -55.0},
                {"K": 24.5, "accelerator_y": -55.0},
                {"K": 23.5, "accelerator_y": -55.0},
            ],
        )


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class NativeCandidateCampaignBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifact_runs = self.root / "artifacts" / "runs"
        self.artifact_runs.mkdir(parents=True)
        source = RUNNER.read_text(encoding="utf-8-sig")
        source = source.replace(
            '$artifactRuns=Join-Path $workspaceRoot "artifacts\\projects\\$project\\runs"',
            f"$artifactRuns='{self.artifact_runs.as_posix()}'",
        )
        self.runner = self.root / "campaign.ps1"
        self.runner.write_text(source, encoding="utf-8")
        self.fake_runner = self.root / "condition_runner.ps1"
        self.fake_runner.write_text(
            """[CmdletBinding()] param(
  [Parameter(Mandatory)][string]$ConditionPath,
  [Parameter(Mandatory)][string]$ContextPath,
  [Parameter(Mandatory)][string]$RunId,
  [string]$ProviderReusePath='',
  [string]$StripeReuseRunManifest='',
  [string]$ContinuationReuseRunManifest='',
  [string]$CandidateReuseRunManifest='',
  [string]$QualifiedWorkpointRunPath='',
  [string]$WorkpointResumeInitialManifest='',
  [string]$WorkpointResumeParentCheckpoint='',
  [string]$WorkpointResumeSuccessfulChildManifest='',
  [string]$PythonExe='', [string]$SimionExe='')
$condition=Get-Content -LiteralPath $ConditionPath -Raw|ConvertFrom-Json
$context=Get-Content -LiteralPath $ContextPath -Raw|ConvertFrom-Json
$attempt=1
if(Test-Path -LiteralPath $context.counter_path){$attempt=1+[int](Get-Content -LiteralPath $context.counter_path -Raw)}
Set-Content -LiteralPath $context.counter_path -Value $attempt -Encoding UTF8
$status=if($context.behavior-eq'interrupted_then_success'-and$attempt-eq1){'interrupted'}else{'success'}
$outcome=if(($context.behavior-eq'warning_then_success'-and$attempt-eq1)-or$context.behavior-eq'upstream_warning'){'warning_physical_nonqualification__continue_parameter_scan'}else{'within_tolerance'}
$project=if($context.behavior-eq'wrong_manifest'){'wrong_project'}else{'parallel_mirror_dual_stripe_mr_tof'}
$run=Join-Path $context.artifact_runs $RunId
New-Item -ItemType Directory -Path $run -Force|Out-Null
[ordered]@{stripe=$StripeReuseRunManifest;continuation=$ContinuationReuseRunManifest;candidate=$CandidateReuseRunManifest;qualified_workpoint=$QualifiedWorkpointRunPath;workpoint_initial=$WorkpointResumeInitialManifest;workpoint_parent=$WorkpointResumeParentCheckpoint;workpoint_child=$WorkpointResumeSuccessfulChildManifest}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $run 'reuse_arguments.json') -Encoding UTF8
[ordered]@{inputs=[ordered]@{condition=$ConditionPath}}|ConvertTo-Json -Depth 3|Set-Content -LiteralPath (Join-Path $run 'run_config.json') -Encoding UTF8
$provider=$null
if($ProviderReusePath){
  $provider=Get-Content -LiteralPath $ProviderReusePath -Raw|ConvertFrom-Json
}else{
  $providerAttempt=1
  if(Test-Path -LiteralPath $context.provider_counter_path){$providerAttempt=1+[int](Get-Content -LiteralPath $context.provider_counter_path -Raw)}
  Set-Content -LiteralPath $context.provider_counter_path -Value $providerAttempt -Encoding UTF8
  $providerRun=Join-Path $context.artifact_runs ('oa-'+$RunId)
  New-Item -ItemType Directory -Path (Join-Path $providerRun 'results') -Force|Out-Null
  $providerManifest=Join-Path $providerRun 'run_manifest.json'
  $providerReceipt=Join-Path $providerRun 'results/mrtof_runtime_receipt.json'
  [ordered]@{schema_version=2;run_id=('oa-'+$RunId);project='orthogonal_accelerator';mode='component_focus_workflow';status='success'}|ConvertTo-Json|Set-Content -LiteralPath $providerManifest -Encoding UTF8
  [ordered]@{schema_version=1;role='orthogonal_accelerator_mrtof_runtime_receipt';status='published_standalone_response_bank';mrtof_projection=[ordered]@{required_source_y_offset_from_accelerator_axis_mm=-1.5;accepted_release=[ordered]@{slow_energy_center_per_charge_v=4.9;slow_energy_full_width_per_charge_v=0.1;mass_th=524;charge_e=1;nominal_direction=@(0,1,0);angular_full_width_deg=0.0;geometry=[ordered]@{shape='cylinder';center_mm=@(0,0,32);axis='y';radius_mm=0.5;height_mm=1.0}};provider_exit_energy_acceptance=[ordered]@{passed=$true;tolerances=[ordered]@{maximum_exit_transverse_energy_error_per_charge_v=0.05;maximum_exit_transverse_velocity_bias_mm_per_us=0.0001};center_particle=[ordered]@{transverse_energy_passed=$true;transverse_velocity_bias_passed=$true};cohort=[ordered]@{transverse_energy_passed=$true;transverse_velocity_bias_passed=$true}}}}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $providerReceipt -Encoding UTF8
  $provider=[ordered]@{run_manifest=$providerManifest;runtime_receipt=$providerReceipt;release_slow_energy_per_charge_v=4.9;required_source_y_offset_mm=-1.5}
}
[ordered]@{schema_version=2;run_id=$RunId;project=$project;mode='native_candidate_single_condition';status=$status}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $run 'run_manifest.json') -Encoding UTF8
if($status-eq'success'){
  $summary=[ordered]@{schema_version=1;status='success';workflow_outcome=$outcome;K=[double]$condition.K;accelerator_y_mm=[double]$condition.accelerator_y;provider_run_manifest=[string]$provider.run_manifest;provider_runtime_receipt=[string]$provider.runtime_receipt;provider_release_slow_energy_per_charge_v=[double]$provider.release_slow_energy_per_charge_v;provider_required_source_y_offset_mm=[double]$provider.required_source_y_offset_mm}
  if($context.behavior-eq'complete_candidate'){
    $candidateRun=Join-Path $run 'candidate'
    New-Item -ItemType Directory -Path $candidateRun -Force|Out-Null
    $candidateManifest=Join-Path $candidateRun 'run_manifest.json'
    $baselineDiagnostic=Join-Path $candidateRun 'baseline_diagnostic.json'
    $focusedDiagnostic=Join-Path $candidateRun 'focused_diagnostic.json'
    [ordered]@{schema_version=2;run_id='candidate';project='parallel_mirror_dual_stripe_mr_tof';mode='native_candidate_end_to_end_chain';status='success'}|ConvertTo-Json|Set-Content -LiteralPath $candidateManifest -Encoding UTF8
    [ordered]@{controlled_detector_focus=[ordered]@{status='observed';scope='same_energy_direction_x_y_mass_charge_birth_time__z_only_pair'};central_plane_focus_history=[ordered]@{plane_z_mm=0.0;target_return_crossing=[ordered]@{status='observed';crossing_index=51;direction_z=-1;scope='all_source_cohort_particles_reaching_this_z0_crossing__no_detector_hit_filter';controlled_z_only_focus=[ordered]@{status='observed';particle_ids=@(2,1,3);crossing_index=51;direction_z=-1;dt_d_initial_z_us_per_mm=0.012;second_order_center_deviation_us=0.0007;coordinate_unit='mm';time_unit='us';scope='same_energy_direction_x_y_mass_charge_birth_time__z_only_triplet__same_target_return_crossing';qualification='controlled_z_only_three_point_diagnostic_only__not_a_focus_gate'}}}}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $baselineDiagnostic -Encoding UTF8
    [ordered]@{controlled_detector_focus=[ordered]@{status='observed';scope='same_energy_direction_x_y_mass_charge_birth_time__z_only_pair'};central_plane_focus_history=[ordered]@{plane_z_mm=0.0;target_return_crossing=[ordered]@{status='observed';crossing_index=51;direction_z=-1;scope='all_source_cohort_particles_reaching_this_z0_crossing__no_detector_hit_filter'}}}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $focusedDiagnostic -Encoding UTF8
    [ordered]@{schema_version=1;role='mrtof_native_candidate_end_to_end_chain_summary';status='success';workflow_outcome='within_tolerance';comparison=[ordered]@{samples=@([ordered]@{label='baseline';peak_method_id='common_gaussian_kde_time_v1';peak_analysis_contract=[ordered]@{method_id='common_gaussian_kde_time_v1';settings=[ordered]@{bandwidth_multiplier=1.06}};particle_count=100;detector_hit_count=81;collection_rate=0.81;detector_dt_d_initial_z_us_per_mm=0.02;detector_tof_median_us=800.0;detector_tof_fwhm_us=0.004878;mass_resolution_t_over_2fwhm=82000.0;focus_particle_count=3;focus_diagnostic_path=$baselineDiagnostic;z0_reached_particle_count=100;z0_reached_fraction=1.0;z0_dt_d_initial_z_us_per_mm=-0.01;z0_tof_median_us=770.0;z0_tof_fwhm_us=0.01;z0_mass_resolution_t_over_2fwhm=38500.0;diagnostic_path=$baselineDiagnostic;te1_coordinate=0.0},[ordered]@{label='root';peak_method_id='common_gaussian_kde_time_v1';peak_analysis_contract=[ordered]@{method_id='common_gaussian_kde_time_v1';settings=[ordered]@{bandwidth_multiplier=1.06}};particle_count=100;detector_hit_count=84;collection_rate=0.84;detector_dt_d_initial_z_us_per_mm=0.001;detector_tof_median_us=801.0;detector_tof_fwhm_us=0.0033375;mass_resolution_t_over_2fwhm=120000.0;focus_particle_count=3;focus_diagnostic_path=$focusedDiagnostic;z0_reached_particle_count=100;z0_reached_fraction=1.0;z0_dt_d_initial_z_us_per_mm=-0.03;z0_tof_median_us=771.0;z0_tof_fwhm_us=0.02;z0_mass_resolution_t_over_2fwhm=19275.0;diagnostic_path=$focusedDiagnostic;te1_coordinate=-0.75})};collection=[ordered]@{baseline=[ordered]@{detection_rate=0.81};focused=[ordered]@{detection_rate=0.84};satisfied=$true};detector_plane_focus=[ordered]@{status='converged'};center_workpoint=[ordered]@{baseline=[ordered]@{passed=$true};focused=[ordered]@{passed=$true};satisfied=$true}}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $candidateRun 'summary.json') -Encoding UTF8
    $summary.candidate_run_manifest=$candidateManifest
  }elseif($context.behavior-eq'upstream_warning'){
    $summary.physical_nonqualification=[ordered]@{stage='prism_coverage';reason='fixture warning'}
  }
  $summary|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $run 'summary.json') -Encoding UTF8
}
""",
            encoding="utf-8",
        )
        self.campaign = self.root / "conditions.json"
        self.campaign.write_text(
            json.dumps([{"K": 25.5, "accelerator_y": -55.0}]), encoding="utf-8"
        )
        self.checkpoint = self.root / "checkpoint.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_context(self, name: str, behavior: str) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(
                {
                    "artifact_runs": str(self.artifact_runs),
                    "behavior": behavior,
                    "counter_path": str(self.root / f"{name}.counter"),
                    "provider_counter_path": str(self.root / f"{name}.provider_counter"),
                }
            ),
            encoding="utf-8",
        )
        return path

    def invoke(
        self,
        context: Path,
        provider_reuse_map: Path | None = None,
        condition_reuse_map: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
                "pwsh",
                "-NoProfile",
                "-File",
                str(self.runner),
                "-CampaignPath",
                str(self.campaign),
                "-CheckpointPath",
                str(self.checkpoint),
                "-ConditionRunnerPath",
                str(self.fake_runner),
                "-ConditionContextPath",
                str(context),
                "-CampaignStamp",
                "20260924_010000",
            ]
        if provider_reuse_map is not None:
            command.extend(["-InitialProviderReuseMapPath", str(provider_reuse_map)])
        if condition_reuse_map is not None:
            command.extend(["-ConditionReuseMapPath", str(condition_reuse_map)])
        return subprocess.run(
            command,
            cwd=RUNNER.parent,
            timeout=120,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def write_provider_reuse_map(self, k: float = 25.5) -> Path:
        provider_run = self.artifact_runs / "imported-provider"
        receipt_dir = provider_run / "results"
        receipt_dir.mkdir(parents=True)
        manifest = provider_run / "run_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "run_id": "imported-provider",
                    "project": "orthogonal_accelerator",
                    "mode": "component_focus_workflow",
                    "status": "success",
                }
            ),
            encoding="utf-8",
        )
        receipt = receipt_dir / "mrtof_runtime_receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "orthogonal_accelerator_mrtof_runtime_receipt",
                    "status": "published_standalone_response_bank",
                    "mrtof_projection": {
                        "required_source_y_offset_from_accelerator_axis_mm": -1.5,
                        "accepted_release": {
                            "slow_energy_center_per_charge_v": 4.9,
                            "slow_energy_full_width_per_charge_v": 0.1,
                            "mass_th": 524,
                            "charge_e": 1,
                            "nominal_direction": [0, 1, 0],
                            "angular_full_width_deg": 0.0,
                            "geometry": {
                                "shape": "cylinder",
                                "center_mm": [0, 0, 32],
                                "axis": "y",
                                "radius_mm": 0.5,
                                "height_mm": 1.0,
                            },
                        },
                        "provider_exit_energy_acceptance": {
                            "passed": True,
                            "tolerances": {
                                "maximum_exit_transverse_energy_error_per_charge_v": 0.05,
                                "maximum_exit_transverse_velocity_bias_mm_per_us": 0.0001,
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
            ),
            encoding="utf-8",
        )
        mapping = self.root / "provider_reuse_map.json"
        mapping.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "mrtof_native_candidate_provider_reuse_map",
                    "providers": [{"K": k, "runtime_receipt": str(receipt)}],
                }
            ),
            encoding="utf-8",
        )
        return mapping

    def test_context_switch_is_rejected_after_completion(self) -> None:
        first = self.write_context("context_a.json", "success")
        second = self.write_context("context_b.json", "success")
        self.assertEqual(self.invoke(first).returncode, 0)
        result = self.invoke(second)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ConditionContextPath differs", result.stderr)

    def test_condition_tampering_is_rejected(self) -> None:
        context = self.write_context("context.json", "success")
        self.assertEqual(self.invoke(context).returncode, 0)
        condition = self.root / "checkpoint.d" / "condition_001.json"
        payload = json.loads(condition.read_text(encoding="utf-8-sig"))
        payload["K"] = 23.5
        condition.write_text(json.dumps(payload), encoding="utf-8")
        result = self.invoke(context)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Condition input differs from checkpoint K/y", result.stderr)

    def test_runner_identity_change_is_rejected(self) -> None:
        context = self.write_context("context.json", "success")
        self.assertEqual(self.invoke(context).returncode, 0)
        self.fake_runner.write_text(
            self.fake_runner.read_text(encoding="utf-8") + "\n# changed\n",
            encoding="utf-8",
        )
        result = self.invoke(context)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Condition runner identity differs", result.stderr)

    def test_wrong_manifest_identity_is_rejected_and_not_terminalized(self) -> None:
        context = self.write_context("context.json", "wrong_manifest")
        result = self.invoke(context)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Condition manifest identity is invalid", result.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(state["conditions"][0]["terminal_state"], "pending")

    def test_interrupted_attempt_restarts_with_new_identity(self) -> None:
        context = self.write_context("context.json", "interrupted_then_success")
        first = self.invoke(context)
        self.assertNotEqual(first.returncode, 0)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(state["conditions"][0]["terminal_state"], "pending")
        first_manifest = state["conditions"][0]["run_manifest"]
        second = self.invoke(context)
        self.assertEqual(second.returncode, 0, second.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(state["conditions"][0]["attempt_count"], 2)
        self.assertEqual(state["conditions"][0]["terminal_state"], "success")
        self.assertNotEqual(first_manifest, state["conditions"][0]["run_manifest"])

    def test_interrupted_workpoint_resumes_through_new_condition_identity(self) -> None:
        context = self.write_context("context.json", "interrupted_then_success")
        first = self.invoke(context)
        self.assertNotEqual(first.returncode, 0)

        stamp = "20260924_010000"
        workpoint = self.artifact_runs / f"{stamp}__sim__simion__mrtof-condition-n1-workpoint"
        results = workpoint / "results"
        results.mkdir(parents=True)
        root = self.artifact_runs / f"{stamp}__sim__simion__mrtof-condition-n1-workpoint-jacobian" / "run_manifest.json"
        child = self.artifact_runs / f"{stamp}__sim__simion__mrtof-condition-n1-workpoint-iter-04" / "run_manifest.json"
        interrupted_child = self.artifact_runs / f"{stamp}__sim__simion__mrtof-condition-n1-workpoint-iter-05" / "run_manifest.json"
        stripe = self.artifact_runs / "stripe-authority" / "run_manifest.json"
        continuation = self.artifact_runs / "continuation-authority" / "run_manifest.json"
        for manifest in (root, child, stripe, continuation):
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "run_id": manifest.parent.name,
                        "project": "parallel_mirror_dual_stripe_mr_tof",
                        "mode": "fixture",
                        "status": "success",
                    }
                ),
                encoding="utf-8",
            )
        interrupted_child.parent.mkdir(parents=True, exist_ok=True)
        interrupted_child.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "run_id": interrupted_child.parent.name,
                    "project": "parallel_mirror_dual_stripe_mr_tof",
                    "mode": "fixture",
                    "status": "interrupted",
                }
            ),
            encoding="utf-8",
        )
        contract = workpoint / "contract.json"
        contract.write_text(
            json.dumps(
                {
                    "nominal": {"target_drift_period_ratio": 25.5},
                    "accelerator": {"focus_y_anchor": {"project_y_mm": -55.0}},
                }
            ),
            encoding="utf-8",
        )
        (workpoint / "run_config.json").write_text(
            json.dumps(
                {
                    "inputs": {"contract": str(contract)},
                    "parameters": {
                        "native_recovery_problem": {"stripe": str(stripe.parent)},
                        "voltage_seed_consumer_projection": {"manifest": str(continuation)},
                    },
                }
            ),
            encoding="utf-8",
        )
        (workpoint / "run_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "run_id": workpoint.name,
                    "project": "parallel_mirror_dual_stripe_mr_tof",
                    "mode": "downstream_fixed_grid_workpoint_iteration",
                    "status": "checkpoint",
                }
            ),
            encoding="utf-8",
        )
        (results / "iteration_lineage.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "mrtof_downstream_workpoint_iteration_lineage",
                    "root_workpoint_manifest": {"path": str(root)},
                    "children": [
                        {"iteration": 4, "child_manifest": str(child)},
                        {"iteration": 5, "child_manifest": str(interrupted_child)},
                    ],
                }
            ),
            encoding="utf-8",
        )

        self.fake_runner.write_text(
            self.fake_runner.read_text(encoding="utf-8") + "\n# resume wiring v1\n",
            encoding="utf-8",
        )
        second = self.invoke(context)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(state["condition_runner_resume_wiring_version"], 2)
        self.assertEqual(state["conditions"][0]["attempt_count"], 2)
        second_run = self.artifact_runs / "20260924_010001__sim__simion__mrtof-native-condition"
        arguments = json.loads((second_run / "reuse_arguments.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(Path(arguments["workpoint_initial"]), root)
        self.assertEqual(Path(arguments["workpoint_parent"]), workpoint / "run_manifest.json")
        self.assertEqual(Path(arguments["workpoint_child"]), child)
        self.assertEqual(Path(arguments["stripe"]), stripe)
        self.assertEqual(Path(arguments["continuation"]), continuation)

    def test_failed_attempt_with_qualified_n1_skips_checkpoint_resume(self) -> None:
        context = self.write_context("context.json", "interrupted_then_success")
        first = self.invoke(context)
        self.assertNotEqual(first.returncode, 0)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        state["condition_runner_resume_wiring_version"] = 1
        state["conditions"][0]["terminal_state"] = "failed"
        state["conditions"][0]["stripe_reuse_run_manifest"] = "stripe.json"
        state["conditions"][0]["continuation_reuse_run_manifest"] = "continuation.json"
        stamp = "20260924_010000"
        workpoint = self.artifact_runs / f"{stamp}__sim__simion__mrtof-condition-n1-workpoint"
        state["conditions"][0]["workpoint_qualified_run_path"] = str(workpoint)
        state["conditions"][0]["workpoint_resume_initial_manifest"] = None
        state["conditions"][0]["workpoint_resume_parent_checkpoint"] = None
        state["conditions"][0]["workpoint_resume_successful_child_manifest"] = None
        self.checkpoint.write_text(json.dumps(state), encoding="utf-8")
        self.fake_runner.write_text(
            self.fake_runner.read_text(encoding="utf-8") + "\n# terminal N1 reuse v2\n",
            encoding="utf-8",
        )

        second = self.invoke(context)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(state["condition_runner_resume_wiring_version"], 2)
        self.assertEqual(state["conditions"][0]["attempt_count"], 2)
        arguments = json.loads(
            (
                self.artifact_runs
                / "20260924_010001__sim__simion__mrtof-native-condition"
                / "reuse_arguments.json"
            ).read_text(encoding="utf-8-sig")
        )
        self.assertEqual(Path(arguments["qualified_workpoint"]), workpoint)
        self.assertFalse(arguments["workpoint_parent"])
        self.assertFalse(arguments["workpoint_child"])

    def test_same_k_different_y_reuses_one_provider(self) -> None:
        self.campaign.write_text(
            json.dumps(
                [
                    {"K": 25.5, "accelerator_y": -55.0},
                    {"K": 25.5, "accelerator_y": -60.0},
                ]
            ),
            encoding="utf-8",
        )
        context = self.write_context("context.json", "success")
        result = self.invoke(context)
        self.assertEqual(result.returncode, 0, result.stderr)
        provider_counter = self.root / "context.json.provider_counter"
        self.assertEqual(provider_counter.read_text(encoding="utf-8-sig").strip(), "1")
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(state["provider_cache"]), 1)

    def test_initial_provider_map_avoids_a_redundant_provider_run(self) -> None:
        context = self.write_context("context.json", "success")
        provider_map = self.write_provider_reuse_map()
        result = self.invoke(context, provider_reuse_map=provider_map)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "context.json.provider_counter").exists())
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(state["provider_cache"]), 1)
        self.assertEqual(
            Path(state["provider_cache"]["25.5"]["runtime_receipt"]).name,
            "mrtof_runtime_receipt.json",
        )

    def test_condition_reuse_map_is_selected_by_exact_k_and_y(self) -> None:
        context = self.write_context("context.json", "success")
        stripe = self.root / "stripe_manifest.json"
        continuation = self.root / "continuation_manifest.json"
        stripe.write_text("{}", encoding="utf-8")
        continuation.write_text("{}", encoding="utf-8")
        mapping = self.root / "condition_reuse_map.json"
        mapping.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "mrtof_native_candidate_condition_reuse_map",
                    "conditions": [
                        {
                            "K": 25.5,
                            "accelerator_y": -55.0,
                            "stripe_run_manifest": str(stripe),
                            "continuation_run_manifest": str(continuation),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = self.invoke(context, condition_reuse_map=mapping)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        run = Path(state["conditions"][0]["run_manifest"]).parent
        received = json.loads(
            (run / "reuse_arguments.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual(Path(received["stripe"]), stripe.resolve())
        self.assertEqual(Path(received["continuation"]), continuation.resolve())
        self.assertEqual(received["candidate"], "")

    def test_completed_candidate_is_passed_only_for_its_exact_condition(self) -> None:
        self.campaign.write_text(
            json.dumps(
                [
                    {"K": 25.5, "accelerator_y": -55.0},
                    {"K": 24.5, "accelerator_y": -55.0},
                ]
            ),
            encoding="utf-8",
        )
        context = self.write_context("context.json", "warning_then_success")
        stripe = self.root / "stripe_manifest.json"
        continuation = self.root / "continuation_manifest.json"
        candidate = self.root / "candidate_manifest.json"
        for path in (stripe, continuation, candidate):
            path.write_text("{}", encoding="utf-8")
        mapping = self.root / "condition_reuse_map.json"
        mapping.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "mrtof_native_candidate_condition_reuse_map",
                    "conditions": [
                        {
                            "K": 25.5,
                            "accelerator_y": -55.0,
                            "stripe_run_manifest": str(stripe),
                            "continuation_run_manifest": str(continuation),
                            "candidate_run_manifest": str(candidate),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = self.invoke(
            context,
            provider_reuse_map=self.write_provider_reuse_map(),
            condition_reuse_map=mapping,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        first_run = Path(state["conditions"][0]["run_manifest"]).parent
        second_run = Path(state["conditions"][1]["run_manifest"]).parent
        first = json.loads(
            (first_run / "reuse_arguments.json").read_text(encoding="utf-8-sig")
        )
        second = json.loads(
            (second_run / "reuse_arguments.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual(Path(first["candidate"]), candidate.resolve())
        self.assertEqual(second["candidate"], "")

    def test_warning_condition_advances_to_the_next_condition(self) -> None:
        self.campaign.write_text(
            json.dumps(
                [
                    {"K": 25.5, "accelerator_y": -50.0},
                    {"K": 24.5, "accelerator_y": -50.0},
                ]
            ),
            encoding="utf-8",
        )
        context = self.write_context("context.json", "warning_then_success")
        result = self.invoke(context)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.root / "context.json.counter").read_text(encoding="utf-8-sig").strip(),
            "2",
        )
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        self.assertEqual(state["status"], "success")
        self.assertEqual(
            [item["terminal_state"] for item in state["conditions"]],
            ["warning", "success"],
        )
        self.assertEqual(
            state["conditions"][0]["workflow_outcome"],
            "warning_physical_nonqualification__continue_parameter_scan",
        )

    def test_comparison_projects_complete_candidate_metrics_and_best(self) -> None:
        context = self.write_context("context.json", "complete_candidate")
        result = self.invoke(context)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        comparison = json.loads(
            Path(state["comparison_path"]).read_text(encoding="utf-8-sig")
        )
        row = comparison["conditions"][0]
        self.assertEqual(comparison["schema_version"], 2)
        self.assertEqual(row["terminal_stage"], "native_candidate")
        self.assertEqual(row["baseline"]["detection_rate"], 0.81)
        self.assertEqual(row["baseline"]["detector_hit_count"], 81)
        self.assertEqual(row["baseline"]["tof_fwhm_us"], 0.004878)
        self.assertEqual(row["baseline"]["mass_resolution_t_over_2fwhm"], 82000.0)
        self.assertEqual(
            row["baseline"]["initial_z_time_slope"]["measurement_basis"],
            "controlled_symmetric_initial_z_pair",
        )
        baseline_z0 = row["baseline"]["z0_target_return"]
        self.assertEqual(baseline_z0["crossing_index"], 51)
        self.assertEqual(baseline_z0["direction_z"], -1)
        self.assertEqual(baseline_z0["reached_particle_count"], 100)
        self.assertEqual(baseline_z0["tof_fwhm_us"], 0.01)
        self.assertEqual(baseline_z0["mass_resolution_t_over_2fwhm"], 38500.0)
        self.assertEqual(
            baseline_z0["initial_z_time_slope"]["measurement_basis"],
            "descriptive_linear_regression_over_all_particles_reaching_target_return_z0",
        )
        self.assertEqual(
            baseline_z0["qualification"],
            "diagnostic_only__not_a_z0_resolution_gate",
        )
        controlled_z0 = baseline_z0["controlled_z_only_focus"]
        self.assertEqual(controlled_z0["status"], "observed")
        self.assertEqual(controlled_z0["particle_ids"], [2, 1, 3])
        self.assertEqual(controlled_z0["crossing_index"], 51)
        self.assertEqual(controlled_z0["direction_z"], -1)
        self.assertEqual(controlled_z0["dt_d_initial_z_us_per_mm"], 0.012)
        self.assertEqual(controlled_z0["second_order_center_deviation_us"], 0.0007)
        self.assertEqual(row["focused"]["detection_rate"], 0.84)
        self.assertEqual(row["focused"]["mass_resolution_t_over_2fwhm"], 120000.0)
        self.assertEqual(row["focused"]["z0_target_return"]["tof_fwhm_us"], 0.02)
        self.assertIsNone(
            row["focused"]["z0_target_return"]["controlled_z_only_focus"]
        )
        self.assertEqual(row["detector_plane_focus"]["convergence_status"], "converged")
        self.assertEqual(row["detector_plane_focus"]["te1_coordinate"], -0.75)
        self.assertTrue(row["center_gate"]["satisfied"])
        self.assertFalse(comparison["metric_scope"]["z0_is_qualification_gate"])
        self.assertIn(
            "do not by themselves attribute downstream causal broadening",
            comparison["metric_scope"]["cross_plane_comparison"],
        )
        self.assertEqual(
            comparison["selection"]["best_qualified_condition"]["ordinal"], 1
        )

    def test_comparison_retains_rows_but_does_not_rank_mixed_peak_settings(self) -> None:
        self.fake_runner.write_text(
            self.fake_runner.read_text().replace("bandwidth_multiplier=1.06", "bandwidth_multiplier=$condition.K"),
            encoding="utf-8",
        )
        self.campaign.write_text(json.dumps([
            {"K": 25.5, "accelerator_y": -50.0},
            {"K": 24.5, "accelerator_y": -50.0},
        ]), encoding="utf-8")
        result = self.invoke(self.write_context("context.json", "complete_candidate"))
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        comparison = json.loads(Path(state["comparison_path"]).read_text(encoding="utf-8-sig"))
        self.assertEqual(len(comparison["conditions"]), 2)
        self.assertEqual(comparison["selection"]["status"], "unavailable_mixed_peak_settings")
        self.assertIsNone(comparison["selection"]["best_qualified_condition"])

    def test_comparison_keeps_candidate_fields_null_for_upstream_warning(self) -> None:
        context = self.write_context("context.json", "upstream_warning")
        result = self.invoke(context)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.checkpoint.read_text(encoding="utf-8-sig"))
        comparison = json.loads(
            Path(state["comparison_path"]).read_text(encoding="utf-8-sig")
        )
        row = comparison["conditions"][0]
        self.assertEqual(row["terminal_stage"], "prism_coverage")
        self.assertIsNone(row["candidate_run_manifest"])
        for phase in ("baseline", "focused"):
            self.assertTrue(all(value is None for value in row[phase].values()))
        self.assertEqual(
            row["detector_plane_focus"],
            {"convergence_status": None, "te1_coordinate": None},
        )
        self.assertEqual(
            row["center_gate"],
            {"baseline_passed": None, "focused_passed": None, "satisfied": None},
        )
        self.assertIsNone(comparison["selection"]["best_qualified_condition"])

    def test_campaign_carries_provider_runtime_checkpoint_between_conditions(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function Get-ProviderRuntimeCheckpoint", source)
        self.assertIn("$record.checkpoint.path", source)
        self.assertIn("$arguments.AcceleratorRuntimeCheckpoint=", source)
        self.assertIn(
            "$state.accelerator_runtime_checkpoint=Get-ProviderRuntimeCheckpoint",
            source,
        )


if __name__ == "__main__":
    unittest.main()
