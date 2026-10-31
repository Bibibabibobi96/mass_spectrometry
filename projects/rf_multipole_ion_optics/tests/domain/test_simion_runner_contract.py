import csv
import ctypes
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from projects.rf_multipole_ion_optics.runtime.particle_source_preflight import COLUMNS
from projects.rf_multipole_ion_optics.runtime.simion_particle_source import render_canonical_source
from common.simion.resource_profile import publish_resource_profile


RUNNER = Path(__file__).resolve().parents[2] / "runtime/run_simion_finite_3d_transport.ps1"
REPO_ROOT = Path(__file__).parents[4]


def _short_windows_path(path: Path) -> Path:
    """Return an existing path's 8.3 spelling when Windows exposes one."""
    if sys.platform != "win32":
        return path
    get_short_path = ctypes.windll.kernel32.GetShortPathNameW
    required = get_short_path(str(path), None, 0)
    if required == 0:
        return path
    buffer = ctypes.create_unicode_buffer(required)
    if get_short_path(str(path), buffer, required) == 0:
        return path
    return Path(buffer.value)


class SimionRunnerContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_finite_public_owner_uses_actual_host_facts_and_never_double_releases(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("Initialize-RunArtifactPowerShellOwner -Python $python", source)
        self.assertIn("$ownerContext.completion_written", source)
        for removed in ("function Complete-RfWorkflowOwner", "function Get-RfOwnerFileRecord", "function Convert-RfOwnerPath"):
            self.assertNotIn(removed, source)
        script = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $env:RF_TEST_REPO 'common/contracts/run_artifact_workflow.ps1')
. (Join-Path $env:RF_TEST_REPO 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
function Exit-HostResourceStage {param($Lease,[switch]$PassThru);$script:exits++;if($Lease.inherited){return $null};return @{status=$(if($scenario-eq'mismatch'){'retained'}else{'released'});token=$Lease.token}}
function Invoke-HostResourceTransaction {param($StatePath,$Request);$script:inherits++;if($Request.operation-ne'inherit'-or$Request.token-cne'actual-token'){throw 'Actual inheritance identity changed'};return @{status=$(if($scenario-eq'inherited_unknown'){'unknown'}else{'acquired'});token=$Request.token}}
foreach($scenario in @('owned','inherited','mismatch','inherited_unknown')){
 $script:exits=0;$script:inherits=0;$hostReleaseState=@{released=$false;completion=$null}
 $hostExecutionLease=@{token='actual-token';inherited=($scenario-in@('inherited','inherited_unknown'));state_path='fixture'}
 $nativeOperations=@(@{operation_id='fly';observation=@{exit_confirmed=$true;returncode=0;process_id=12;process_started_at_utc_ticks=123};resource_release_id='simion'})
 if($scenario-in@('mismatch','inherited_unknown')){
  $blocked=$false;try{Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativeOperations -State $hostReleaseState|Out-Null}catch{$blocked=[bool]$_.Exception.Data['rf_host_release_unconfirmed']}
  if(-not$blocked-or$hostReleaseState.released-or($scenario-eq'inherited_unknown'-and$script:exits-ne0)){throw 'Unconfirmed host release lost its protection'}
 }else{
  $facts=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativeOperations -State $hostReleaseState;Assert-WorkflowWriterCompletion $facts -PowerShellOwner
  $receipt=$facts.resource_releases[0].completion_receipt.host_release
  if($receipt.token-cne'actual-token'-or($scenario-eq'inherited'-and($null-ne$receipt.result-or$script:inherits-ne1))){throw 'Actual inherited null release or grant identity changed'}
  $again=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativeOperations -State $hostReleaseState
  if($script:exits-ne1-or$again.resource_releases[0].completion_receipt.host_release.inherited-ne($scenario-eq'inherited')){throw 'Host release repeated or identity changed'}
 }
}
'''
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO_ROOT,
            env={**os.environ, "RF_TEST_REPO": str(REPO_ROOT), "RF_TEST_RUNNER": str(RUNNER)},
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_direct_native_step_records_actual_exit_and_guards_unknown_descendants(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("  function Invoke-SimionStep("):source.index("  Set-RfRunPhase 'field_and_layout'", source.index("  function Invoke-SimionStep("))]
        script = r"""
$ErrorActionPreference='Stop';$logDir='.';$runDir='.';$resourceUsage='unused';$simion='unused';$solverDir='.'
$resolvedBudgetPreflight=@{limits=@{}};$nativeOperations=[Collections.ArrayList]::new();$script:resourceBudgetExceeded=$false
function Invoke-ResourceBudgetedProcess {
 if($scenario-eq'observation'){$error=[Exception]::new('observation-failure');$error.Data['observed_process_exit_confirmed']=$true;throw $error}
 return @{exit_code=0;resource_budget_exceeded=($scenario-eq'pressure');root_process_id=123;root_process_started_at_utc_ticks=456}
}
""" + block + r"""
$scenario='success';Invoke-SimionStep 'gem2pa' @('fixture')
if($nativeOperations.Count-ne1-or$nativeOperations[0].observation.returncode-ne0-or
   $nativeOperations[0].observation.process_id-ne123-or$nativeOperations[0].observation.process_started_at_utc_ticks-ne456){throw 'actual exit was not recorded'}
foreach($scenario in @('observation','pressure')){
 $caught=$false;try{Invoke-SimionStep 'refine' @('fixture')}catch{
  $caught=$true;if($_.Exception.Data['simion_wave_writer_completion_confirmed']-ne$false){throw 'unknown descendants were not protected'}
 }
 if(-not$caught-or$nativeOperations.Count-ne1){throw 'unknown exit was falsely recorded'}
}
exit 0
"""
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_frozen_fly_projection_preserves_prior_native_configuration(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        projection = source[source.index("  $flyPhysics=[ordered]@{"):source.index("  $flyPhysicsPath=Join-Path")]
        with tempfile.TemporaryDirectory() as directory:
            script = r"""
$ErrorActionPreference='Stop';$inputDir=$env:RF_TEST_ROOT;$resultDir=$inputDir;$solverDir=$inputDir
$flightIobPath=Join-Path $solverDir 'quad_monolithic.iob'
$TrajectoryQuality=10;$RfStepsPerPeriod=80;$MaximumTimeUs=80;$resolvedCellMmZ=2
$drive=@{waveform='cosine';rf_amplitude_V_zero_to_peak_per_group=20;dc_amplitude_V_per_group=3;frequency_Hz=100;phase_rad=1}
$geometry=@{rod_z_min=1;rod_z_max=9};$rodLua='rod_electrodes={fixture},';$staticLua='static_electrodes={fixture},'
$handoffPlaneMm=11;$censusPlaneMm=12;$censusRadius=4;$workingRadius=8;$zShift=5;$origin=6;$backwardEscape=-1
$mechanicalExitEnabled=$true;$exitObservation=@{mechanical_exit_z_mm=10;numerical_guard_z_mm=11;aperture_radius_mm=3}
""" + projection + r"""
$name='rf_on';$rfScale=1;$axialScale=0;$resolvedHash='fixture';$casePhysics=$flyPhysics.cases[$name]
$caseState=Join-Path $resultDir 'particle_states__rf_on.csv';$caseTrajectory=Join-Path $resultDir 'trajectory_samples__rf_on.csv'
$caseMechanical=Join-Path $resultDir 'mechanical_exit_states__rf_on.csv';$caseSummary=Join-Path $resultDir 'simion_summary__rf_on.json'
$simionBatches=@([pscustomobject]@{index=1;fly2='particles.fly2';states='states.lua'})
$continuationUnits=@{}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_TEST_RUNNER,[ref]$tokens,[ref]$errors)
$function=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'New-TransportBatchRuns'},$true))
if($function.Count-ne1){throw 'missing batch configuration builder'}
. ([scriptblock]::Create($function[0].Extent.Text))
$runs=@(New-TransportBatchRuns)
$actual=Get-Content -LiteralPath $runs[0].lua_config -Raw -Encoding ASCII
$mechanicalLua="mechanical_exit_csv=[[$caseMechanical]],mechanical_exit_plane_mm=10,mechanical_exit_aperture_radius_mm=3,mechanical_exit_guard_mm=11,"
$old=@"
return {iob=[[$(Join-Path $solverDir 'quad_monolithic.iob')]], fly2=[[particles.fly2]], source_states=dofile([[states.lua]]),
trajectory_csv=[[$caseTrajectory]], particle_state_csv=[[$caseState]], summary_json=[[$caseSummary]],
$mechanicalLua
mode="resolved_design_transport", operating_point="rf_on", parent_resolved_design_sha256="fixture",
trajectory_quality=10, rf_steps_per_period=80, waveform="cosine",
rf_peak_v=20, rf_scale=1, axial_scale=0,
dc_amplitude_v=3, frequency_hz=100, phase_rad=1,
$rodLua $staticLua
maximum_time_us=80, trajectory_plane_step_mm=2,
rod_z_min_mm=1, rod_z_max_mm=9,
rod_exit_plane_mm=9, handoff_plane_mm=11,
    census_plane_mm=12,
census_radius_mm=4, radial_escape_radius_mm=8,
axial_axis="x", origin_x_mm=5, origin_y_mm=-6,
origin_z_mm=6, backward_escape_plane_mm=-1}
"@
if($actual.Trim()-cne$old.Trim()){throw "frozen projection changed native Lua:`n$actual`nEXPECTED:`n$old"}
$expected=@('--nogui','--noprompt','fly','--remove-pas=3','--trajectory-quality','10','--programs','1','--retain-trajectories','0','--adjustable','transport_rf_steps_per_period=80')
if((@($flyPhysics.fly_args)-join '|')-cne($expected-join '|')){throw 'native Fly arguments changed'}
if((@($flyPhysics.gem2pa_args)-join '|')-cne'--nogui|--noprompt|gem2pa|quad_monolithic.gem|quad_monolithic.pa#'){throw 'gem2pa arguments changed'}
if((@($flyPhysics.refine_args)-join '|')-cne'--nogui|--noprompt|refine|quad_monolithic.pa#'){throw 'refine arguments changed'}
if((@($flyPhysics.iob_args)-join '|')-cne'--nogui|--noprompt|lua|build_simion_runtime_iob.lua|quad_monolithic.iob|multipole_runtime_program.lua|quad_monolithic.fly2'){throw 'IOB arguments changed'}
foreach($entry in @('rf_on:1:0','zero_rf_control:0:0','axial_acceleration_rf_on:1:1','zero_axial_drop_rf_on:1:0','axial_acceleration_rf_off:0:1')){
 $parts=$entry.Split(':');$case=$flyPhysics.cases[$parts[0]]
 if([int]$case.rf-ne[int]$parts[1]-or[int]$case.axial-ne[int]$parts[2]){throw 'case drive scales changed'}
}
$parent=Join-Path $inputDir 'parent'
$parentState=Join-Path $parent 'particle_states__rf_on.csv';$parentSummary=Join-Path $parent 'simion_summary__rf_on.json'
$parentMechanical=Join-Path $parent 'mechanical_exit_states__rf_on.csv'
$continuationUnits['rf_on.batch_01']=@{terminal_outputs=@(@{path=$parentState},@{path=$parentSummary},@{path=$parentMechanical})}
$RetentionClass='compact'
$runs=@(New-TransportBatchRuns)
if($runs[0].state-cne$parentState-or$runs[0].summary-cne$parentSummary-or$runs[0].mechanical-cne$parentMechanical){throw 'reused batch did not retain original owner paths'}
exit 0
"""
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT, env={**os.environ, "RF_TEST_RUNNER": str(RUNNER), "RF_TEST_ROOT": directory},
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_scientific_evidence_failure_publishes_complete_negative_result(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        evaluation = source[source.index("  $scientificStatus='success'"):
                            source.index("  # Invoke-TransportCase performs")]
        summary = source[source.index("  $summaryDocument=[ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary'"):
                         source.index("  $resourceProfile=$null", source.index("  $scientificStatus="))]
        publication = source[source.index("  $writerCompletion=Get-RfSimionStoppedWriterCompletion", source.index("  $requiredPaths=")):
                             source.index("  $resultMarker=")]
        terminal = source[source.rindex("\nif($hostExecutionOutcome-eq'failed')"):]
        for scenario in ("pass", "scientific_fail", "evaluation_error"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                metrics = dict(primary_case_id="rf_on", control_case_id="rf_off",
                               cases=dict(rf_on=dict(transmission_fraction=.95 if scenario=="pass" else .5),
                                          rf_off=dict(transmission_fraction=.1)))
                contract = dict(schema_version=1, role="multipole_transport_evidence_contract",
                    project_id="wrong" if scenario=="evaluation_error" else "rf_multipole_ion_optics",
                    design_profile_id="fixture", evaluation="rf_vs_zero_rf",
                    thresholds=dict(minimum_primary_transmission=.9, minimum_transmission_improvement=.2))
                (root / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
                (root / "evidence.json").write_text(json.dumps(contract), encoding="utf-8")
                (root / "mechanical.csv").write_text("INERT_ALREADY_VALIDATED_STATE_FIXTURE", encoding="utf-8")
                script = root / "scientific_publication.ps1"
                escaped_repo = str(REPO_ROOT.resolve()).replace("'", "''")
                escaped_python = sys.executable.replace("'", "''")
                script.write_text(f"""$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$codeRoot='{escaped_repo}';$python='{escaped_python}';$manifestRepoRoot=$codeRoot
$tokens=$null;$parseErrors=$null
$runnerAst=[Management.Automation.Language.Parser]::ParseFile(
 (Join-Path $codeRoot 'projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1'),[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){{throw 'Production runner does not parse'}}
$scientificTry=@($runnerAst.EndBlock.Statements|Where-Object {{
 $_-is[Management.Automation.Language.TryStatementAst]-and$_.Body.Extent.Text.Contains("`$scientificStatus='success'")
}})
if($scientificTry.Count-ne1){{throw 'Scientific publication owner is ambiguous'}}
$failureBody=[scriptblock]::Create(($scientificTry[0].CatchClauses[-1].Body.Statements|ForEach-Object {{$_.Extent.Text}})-join"`n")
$resultDir=$PWD.Path;$runConfig='unused';$resourceBudgetExceeded=$false;$hostExecutionOutcome='failed'
$ProjectId='rf_multipole_ion_optics';$DesignProfileId='fixture';$RunId='fixture'
$resolvedHash='fixture';$primaryTransmission=0.5;$controlTransmission=0.1;$CaseSet='paired'
$continuationPredecessor=$null
$phaseTimings=@{{}};$runTimer=[Diagnostics.Stopwatch]::StartNew()
$metrics=Join-Path $resultDir 'metrics.json';$evidence=Join-Path $resultDir 'evidence.json'
$summary=Join-Path $resultDir 'summary.json'
$physicalRunDir=$resultDir;$ownerContext=@{{}};$ResultPath=Join-Path $resultDir 'result.json'
$requiredPaths=@();$resourceItems=@();$profileRequest=$null;$nativeOperations=@();$hostExecutionLease=$null;$hostReleaseState=@{{released=$false;completion=$null}}
$outputs=@($summary,$metrics,(Join-Path $resultDir 'mechanical.csv'),(Join-Path $resultDir 'evidence_evaluation.json'))
function Convert-WorkflowOwnerPath($Context,$Path) {{ return $Path }}
function Get-RfSimionStoppedWriterCompletion {{return @{{operations=@();resource_releases=@()}}}}
function Complete-RunArtifactPowerShellOwner {{
 param($Context,$Status,$Summary,$OutputPaths,$RequiredOutputPaths,$WriterCompletion,$WritersStopped,$ResourceUsagePaths,$ResourceProfile,$OriginalFailure)
 if(-not$WritersStopped-or$null-ne$OriginalFailure){{throw 'Scientific result changed writer completion facts'}}
 $Summary|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $script:summary -Encoding utf8
 @{{status=$Status;outputs=@($OutputPaths)}}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $resultDir 'publication.json') -Encoding utf8
}}
function Complete-FailedRun {{
 param($Python,$RepoRoot,$RunConfig,$Summary,$SummaryRole,$Reason,$Software,$Status,$FailureClass,$ResourceUsagePath)
 @{{schema_version=1;role=$SummaryRole;status=$Status;reason=$Reason}}|ConvertTo-Json|Set-Content -LiteralPath $Summary -Encoding utf8
}}
try {{
""" + evaluation + summary + publication + """
 $published=Get-Content (Join-Path $resultDir 'publication.json') -Raw|ConvertFrom-Json
 $result=Get-Content $summary -Raw|ConvertFrom-Json
 @{published=$true;manifest=$published;summary=$result;outcome=$hostExecutionOutcome}|ConvertTo-Json -Depth 10 -Compress
}catch{
 Complete-FailedRun -Summary $summary -SummaryRole 'multipole_simion_finite_3d_transport_summary' -Status 'failed' -Reason $_.Exception.Message
}finally{
 Set-Content -LiteralPath (Join-Path $resultDir 'grant_released.txt') -Value 'released'
}
""" + terminal, encoding="utf-8", newline="\n")
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(script)],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", check=False, timeout=60)
                self.assertEqual(result.returncode, 0 if scenario=="pass" else 1, result.stderr)
                self.assertTrue((root / "grant_released.txt").is_file())
                if scenario == "evaluation_error":
                    self.assertFalse((root / "publication.json").exists())
                    interrupted = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
                    self.assertEqual(interrupted["status"], "failed")
                    self.assertNotIn("native_execution_complete", interrupted)
                else:
                    decision = json.loads(result.stdout.splitlines()[-1])
                    expected = "success" if scenario=="pass" else "failed"
                    self.assertTrue(decision["published"])
                    self.assertEqual(decision["manifest"]["status"], expected)
                    self.assertEqual(decision["summary"]["status"], expected)
                    self.assertEqual(decision["outcome"], expected)
                    self.assertTrue(decision["summary"]["native_execution_complete"])
                    self.assertEqual(decision["summary"]["checks"]["minimum_primary_transmission"], scenario=="pass")
                    self.assertEqual(set(decision["manifest"]["outputs"]), {str(p) for p in (
                        root/"summary.json",root/"metrics.json",root/"mechanical.csv",root/"evidence_evaluation.json")})

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_control_receipt_cannot_replace_primary_observation(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    $resourceUsage=if($name-eq$primaryName)"):
                       source.index("    if($batchRuns.Count-gt 1-or($continuationPredecessor-and-not$caseRunsNative[$name])){")]
        support = (REPO_ROOT / "common/resource_budget_support.ps1").read_text(encoding="utf-8-sig")
        observation = support[support.index("  if($ExistingProcessRecords.Count-gt 0-and\n      $ExistingProcessRecords[0].PSObject.Properties.Name-contains'completed_during_observation'){"):
                              support.index("  Write-ResourceUsage -Usage $usage -Path $UsagePath", support.index("    $usage.first_formal_observation="))]
        terminal = source[source.index("  $caseResourceUsage=[ordered]@{}"):
                          source.index("  if($null-ne$dispatchPlan-and$resourceIdentityWasUnknown){", source.index("  $caseResourceUsage=[ordered]@{}"))]
        owner = (REPO_ROOT / "common/contracts/run_artifact_workflow.ps1").read_text(encoding="utf-8-sig")
        finish_usage = owner[owner.index("      foreach($item in $completion.resource_usage_paths){", owner.index("Set-WorkflowStage resource_finalization")):
                             owner.index("      if($null-ne$completion.resource_profile)", owner.index("Set-WorkflowStage resource_finalization"))]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            support_path = str(REPO_ROOT / "common/resource_budget_support.ps1").replace("'", "''")
            script = f". '{support_path}'\n" + """
$ErrorActionPreference='Stop'
$resultDir=$PWD.Path;$runDir=$resultDir;$primaryName='primary'
$ownerContext=@{}
function Convert-WorkflowOwnerPath($Context,$Path) { return $Path }
$script:calls=@()
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
 $usage=@{role='multipole_resource_usage';status='running';peak_run_directory_bytes=0;peak_process_tree_working_set_bytes=999999}
""" + observation + """
 $usage|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $UsagePath
 $script:calls+=@{launched=@($ProcessSpecifications|ForEach-Object{$_.scheduler_batch.index});retained=@($ExistingProcessRecords).Count}
 return @{resource_budget_exceeded=$false;processes=@(@{exit_code=0})}
}
function Invoke-SimionBatchPhase {
 param($DispatchPlanPath,$RunDir,$UsagePath,$PrepareRemaining,$FirstSpecification)
 $formal=if($null-ne$FirstSpecification){@{process_record=$script:observedRecord}}else{$null}
 $prepared=& $PrepareRemaining $formal
 $existing=@(if($null-ne$formal){$script:observedRecord})
 $wave=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $DispatchPlanPath -RunDir $RunDir -UsagePath $UsagePath -ProcessSpecifications $prepared.pending -ExistingProcessRecords $existing
 $wave.prepared=$prepared
 return $wave
}
$simion='unused';$solverDir='.';$logDir='.';$dispatchPlan='unused';$rfDriveKernelLua='unused';$continuationUnits=@{};$continuationPredecessor=$null
$flyArguments=@('a','b','c','d','e','f','g')
$batchRuns=@(1,2|ForEach-Object{@{batch=@{index=$_;particle_id_min=$_;particle_id_max=$_};lua_config='unused';fly2='unused'}})
# Explicit fixture observation differs from the aggregate peak above.
$script:observedRecord=[pscustomobject]@{name='primary-first';specification=@{scheduler_batch=@{index=1}};peak_working_set_bytes=12345;
 peak_managed_memory_bytes=12345;completed_during_observation=$true;
 observed_process_cpu_percent=12;observed_background_cpu_percent=3}
function New-TransportBatchRuns {return $batchRuns}
function Run-Case($name) {
$batchState=[pscustomobject]@{runs=$batchRuns};$replanAction=$null
$firstSpecification=if($name-eq'primary'){@{name='first'}}else{$null}
""" + block + """
}
Run-Case primary
$before=[IO.File]::ReadAllText((Join-Path $resultDir 'resource_usage.json'))
Run-Case control
if([IO.File]::ReadAllText((Join-Path $resultDir 'resource_usage.json')) -ne $before){throw 'Control overwrote primary'}
$resourceUsage=Join-Path $resultDir 'resource_usage.json'
$resolvedResourceBudget=$null;$control=@{};$controlName='control';$caseRunsNative=@{primary=$true;control=$true}
$null=Complete-ResourceUsage -RunDir $runDir -UsagePath $resourceUsage
""" + terminal + """
$completion=@{resource_usage_paths=$resourceItems};$runRoot=$runDir
""" + finish_usage + """
ConvertTo-Json -InputObject $script:calls -Depth 6
"""
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-Command", script],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [
                {"launched": [2], "retained": 1}, {"launched": [1, 2], "retained": 0},
            ])
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan", "resource_identity": {"solver": "SIMION"},
                "waves": [{"kind": "observed_formal_batch", "batches": [{"count": 1}]}],
            }), encoding="utf-8")
            profile = publish_resource_profile(
                run_id="fixture", resource_usage_path=root / "resource_usage.json", dispatch_plan_path=plan,
            )
            self.assertEqual(profile["per_batch_peak_working_set_bytes"], 12345)
            for name, filename in (("primary", "resource_usage.json"), ("control", "resource_usage__control.json")):
                receipt = json.loads((root / filename).read_text(encoding="utf-8-sig"))
                self.assertEqual(receipt["case_name"], name)
                self.assertEqual(receipt["status"], "completed")
                self.assertEqual(receipt["measurement_scope"], "single_transport_case_not_all_run_cases")
            with self.assertRaisesRegex(ValueError, "explicit first formal observation"):
                publish_resource_profile(
                    run_id="fixture", resource_usage_path=root / "resource_usage__control.json", dispatch_plan_path=plan,
                )
        self.assertIn("$outputs+=@($caseResourceUsage.Values|Where-Object{$_-ne$resourceUsage})", source)
        self.assertIn("single_transport_case_not_all_run_cases", owner)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is required")
    def test_transport_snapshots_include_host_runtime_dependency_closure(self) -> None:
        expected = {
            "common/host_execution_lease.ps1", "common/host_resource_scheduler.py",
            "common/host_resource_policy.json", "common/require_powershell7.ps1",
            "common/analysis/particle_census.py",
        }
        for runner_name in ("run_finite_3d_transport.ps1", RUNNER.name):
            with self.subTest(runner=runner_name), tempfile.TemporaryDirectory() as directory:
                root = _short_windows_path(Path(directory))
                def quoted(path: Path) -> str:
                    return "'" + str(path).replace("'", "''") + "'"
                entry = RUNNER.parent / runner_name
                script = r"""$ErrorActionPreference='Stop'
$repoRoot=@@REPO@@;$inputDir=@@INPUT@@
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile(@@ENTRY@@,[ref]$null,[ref]$null)
$declarations=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.AssignmentStatementAst]-and
 $n.Left.Extent.Text-in@('$hostRuntimeSourcePaths','$analysisSourcePaths','$executionCapacityPaths')},$true)|Sort-Object {$_.Extent.StartOffset})
if($declarations.Count-lt4){throw 'Declared copy/capacity inputs missing'}
foreach($declaration in $declarations){Invoke-Expression $declaration.Extent.Text}
if('@@NAME@@'-eq'run_finite_3d_transport.ps1'){
 $function=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Copy-FiniteComsolRuntime'},$true))
 if($function.Count-ne1){throw 'Actual shared finite runtime copier missing'}
 Invoke-Expression $function[0].Extent.Text
 $call=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Copy-FiniteComsolRuntime'},$true))[-1]
 $copied=Invoke-Expression $call.Extent.Text;$codeRoot=$copied.code_root
}else{
 $begin=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$codeRoot'},$true))[0]
 $finish=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$ownerSource'},$true))[0]
 $source=[IO.File]::ReadAllText(@@ENTRY@@)
 Invoke-Expression $source.Substring($begin.Extent.StartOffset,$finish.Extent.StartOffset-$begin.Extent.StartOffset)
}
$executionCapacityPaths|ConvertTo-Json|Set-Content @@CAPACITY@@
. (Join-Path $codeRoot 'common/host_execution_lease.ps1')
$null=Get-HostResourceBudget -Role GATE -Stage snapshot-probe
""".replace('@@REPO@@', quoted(REPO_ROOT)).replace('@@INPUT@@', quoted(root)).replace('@@ENTRY@@', quoted(entry)).replace('@@NAME@@', runner_name).replace('@@CAPACITY@@', quoted(root / 'capacity.json'))
                completed = subprocess.run(
                    [shutil.which("pwsh"), "-NoProfile", "-Command", script],
                    cwd=root, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=45, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                records = json.loads((root / "code_inventory.json").read_text(encoding="utf-8-sig"))["files"]
                by_path = {record["path"]: record for record in records}
                capacities = json.loads((root / "capacity.json").read_text(encoding="utf-8-sig"))
                for relative in expected:
                    payload = root / "code" / relative
                    self.assertIn("inputs/code/" + relative, capacities)
                    self.assertEqual(payload.read_bytes(), (REPO_ROOT / relative).read_bytes())
                    self.assertEqual(hashlib.sha256(payload.read_bytes()).hexdigest().upper(), by_path[relative]["sha256"])
                imports = "from common.host_resource_scheduler import load_policy; assert load_policy()"
                if "simion" in runner_name:
                    imports += "; from common.simion import resource_scheduler; assert resource_scheduler.CPU_ADMISSION_PERCENT > 0"
                probe = subprocess.run(
                    [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(root / 'code')!r}); " + imports],
                    cwd=root, capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(probe.returncode, 0, probe.stderr)
                census_program = """
import csv, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from common.analysis import particle_census as c
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from projects.rf_multipole_ion_optics.core.component_port import validate_exit_observations
assert pathlib.Path(c.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
source, state = pathlib.Path("mother.csv"), pathlib.Path("terminal.csv")
source.write_text("particle_id,birth_time_s\\n31,0\\n7,0\\n")
rows = []
for pid in (7, 31):
    row = dict.fromkeys(PARTICLE_STATE_COLUMNS, 0.)
    row.update(particle_id=pid, event="terminal", status="lost", terminal_reason="unknown",
               time_us=2., elapsed_time_us=2.)
    rows.append(row)
with state.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
result = validate_exit_observations(state, source, dict(mechanical_exit_z_mm=85., aperture_radius_mm=None))
print(json.dumps(dict(mother=result["mother_particle_ids"], non_exit=result["non_exit_particle_ids"])))
"""
                command = [sys.executable, "-B", "-I", "-c", census_program, str(root / "code")]
                census_probe = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                              timeout=30, check=False)
                self.assertEqual(census_probe.returncode, 0, census_probe.stderr)
                self.assertEqual(json.loads(census_probe.stdout), dict(mother=[7, 31], non_exit=[7, 31]))
                (root / "code/common/analysis/particle_census.py").unlink()
                refused = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30, check=False)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn("particle_census", refused.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_frozen_comsol_runner_receives_resolved_python_environment(self) -> None:
        entry = REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"
        script = r"""$ErrorActionPreference='Stop'
. '@@SUPPORT@@'
$ast=[Management.Automation.Language.Parser]::ParseFile('@@ENTRY@@',[ref]$null,[ref]$null)
$assignments=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.AssignmentStatementAst]},$true))
$names=@($assignments|Where-Object {$_.Left.Extent.Text-eq'$environmentNames'})
$save=@($assignments|Where-Object {$_.Left.Extent.Text-eq'$oldEnvironment'})
$sets=@($assignments|Where-Object {$_.Left.Extent.Text-in@('$env:SIMULATION_PYTHON_EXE','$env:PYTHONPATH')-and$_.Right.Extent.Text-in@('$python','$codeRoot')})
$restore=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Restore-RunEnvironment'},$true))[-1]
$launch=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Invoke-ResourceBudgetedProcess'},$true))[-1]
if($names.Count-ne1-or$save.Count-ne1-or$sets.Count-lt2-or$null-eq$restore-or$null-eq$launch){throw 'Actual environment/launch boundary missing'}
$python='selected-python';$codeRoot='selected-frozen-code';$resolvedBudget=@{limits=@{}};$runDir='.';$resourceUsage='unused';$pwsh='unused';$task='unused';$report='unused';$RunId='fixture';$ownerState=@{launcher_receipt='unused'}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$ArgumentList)
 if($env:SIMULATION_PYTHON_EXE-cne$python-or$env:PYTHONPATH-cne$codeRoot){throw 'Native child did not inherit selected interpreter/frozen source'}
 $script:calls++
 if($fail){throw 'CHILD_ENV_SENTINEL'}
 return @{}
}
foreach($fail in @($false,$true)){
 $env:SIMULATION_PYTHON_EXE='prior-python';$env:PYTHONPATH='prior-source';$script:calls=0
 Invoke-Expression $names[0].Extent.Text;Invoke-Expression $save[0].Extent.Text
 try{
  foreach($set in $sets){Invoke-Expression $set.Extent.Text}
  $null=Invoke-Expression $launch.Extent.Text
 }catch{if($_.Exception.Message-cne'CHILD_ENV_SENTINEL'){throw}}
 finally{Invoke-Expression $restore.Extent.Text}
 if($script:calls-ne1-or$env:SIMULATION_PYTHON_EXE-cne'prior-python'-or$env:PYTHONPATH-cne'prior-source'){throw 'Original environment was not restored'}
}
""".replace('@@ENTRY@@', str(entry)).replace('@@SUPPORT@@', str(REPO_ROOT / 'common/contracts/run_artifact_support.ps1'))
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runner_freezes_resolved_campaign_selection_before_solver_launch(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$ResolvedRuntimeProfilePath=''", source)
        self.assertIn(
            "Campaign transport requires the resolved runtime-profile snapshot.",
            source,
        )
        self.assertIn("resolved_runtime_profile.json", source)
        self.assertIn("campaign_sha256=[string]$campaignSelection.sha256", source)
        self.assertLess(
            source.index("Campaign authority changed before it was frozen."),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_unsupported_fractional_cache_policy_fails_before_native_work(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("simion_pa_basis_policy", source)
        self.assertIn("SIMION_PA_BASIS_POLICY_UNSUPPORTED", source)
        self.assertLess(
            source.index("SIMION_PA_BASIS_POLICY_UNSUPPORTED"),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_runner_consumes_frozen_snapshot_without_private_terminal_composition(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        for token in ("downstream_terminal_profiles.json","core.downstream_terminal","$hasDownstreamTerminal"):
            self.assertNotIn(token,runner)
        self.assertIn("$snapshotDesign=$resolvedRuntimeDocument.design_profile_resolution.resolved_design",runner)
        self.assertIn("$geometry.observations",runner)
        self.assertIn("$observations.handoff_plane_z_mm",runner)

    def test_default_run_ids_delimit_the_design_profile_variable(self) -> None:
        for name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (RUNNER.parent / name).read_text(encoding="utf-8-sig")
            self.assertIn("$($DesignProfileId.Replace('_','-'))__resolved-l3", source)
            self.assertNotIn("$DesignProfileId__resolved-l3", source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_shared_host_lease_reports_one_manifest_bound_terminal_outcome(self) -> None:
        entry = REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"
        script = r"""$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile('@@ENTRY@@',[ref]$null,[ref]$null)
$ast.FindAll({param($n) $n-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object{Invoke-Expression $_.Extent.Text}
$script:calls=0
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$RequiredOutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure,$ResourceUsagePaths)
 $script:calls++
 if($Context.result_path-cne'fixture-result'-or$Status-cne'success'-or-not$WritersStopped-or$Summary.scientific_result-cne'functional_fail'-or
    $OutputPaths[0]-cne'actual-output'-or$RequiredOutputPaths[0]-cne'actual-output'-or$WriterCompletion.operations.Count-ne0-or
    $WriterCompletion.resource_releases.Count-ne0-or$Summary.total_elapsed_seconds-lt0){throw 'Original public terminal arguments changed'}
 return @{stage='complete'}
}
$state=@{native_attempted=$false;host_lease=$null;writer_unknown=$false;usage_path=$null;phase_timings=@{prepare=0.1};timer=[Diagnostics.Stopwatch]::StartNew();finalization_started=$false}
$context=@{result_path='fixture-result'};$summary=@{scientific_result='functional_fail'}
$null=Complete-FiniteComsolOwner -Context $context -State $state -RunId fixture -Status success -Summary $summary -Outputs @('actual-output') -Required @('actual-output')
if($script:calls-ne1-or$state.finalization_started){throw 'Terminal outcome was duplicated or left unfinished'}
""".replace('@@ENTRY@@', str(entry))
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_dispatch_request_does_not_replace_design_manifest_input(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("      $dispatchRequestDocument=[ordered]@"):
                       source.index("      $dispatchRequestDocument|ConvertTo-Json")]
        script = (
            "$ErrorActionPreference='Stop'; $request='design.json'; "
            "$automaticDispatch=@{field_kind='rf'}; $sourceMeta=@{particle_count=17}; "
            "$TrajectoryQuality=0; $RuntimeProfileId='fixture'; $RfStepsPerPeriod=32; "
            + block + "\n@{design_request=$request; dispatch=$dispatchRequestDocument}|ConvertTo-Json -Depth 5"
        )
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["design_request"], "design.json")
        self.assertEqual(payload["dispatch"]["particle_count"], 17)
        self.assertIn("design_request=$request", source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_continuation_observes_largest_missing_batch_without_repartition(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    $pendingRuns=@($batchRuns|"):source.index("    # Keep each case's receipt independent:")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dispatch.json").write_text(json.dumps({"estimation": {"kind": "observed_formal_batch"}, "limits": {"maximum_concurrency": 3},
                "waves": [{"batch_count": 2}]}), encoding="utf-8")
            (root / "batch.json").write_text("original-partition", encoding="utf-8")
            script = r"""
$ErrorActionPreference='Stop';$codeRoot=$env:RF_TEST_ROOT;$runDir=$codeRoot;$logDir=$codeRoot;$solverDir=$codeRoot
$dispatchPlan=Join-Path $codeRoot 'dispatch.json';$batchPlan=Join-Path $codeRoot 'batch.json'
$dispatchRequest='request';$resourceProfiles='profiles';$python='Invoke-FixturePython';$simion='unused';$name='primary'
$rfDriveKernelLua='kernel';$flyArguments=@('a','b','c','d','e','f','g');$continuationPredecessor='parent'
$script:resourceCalibrationRequired=$true;$script:resourceIdentityWasUnknown=$true
$continuationLargestMissing=4
$continuationUnits=@{'primary.batch_01'=@{}}
$batchRuns=@(
 @{batch=@{index=1;particle_id_min=1;particle_id_max=2};fly2='one';lua_config='one'},
 @{batch=@{index=2;particle_id_min=3;particle_id_max=6};fly2='two';lua_config='two'},
 @{batch=@{index=3;particle_id_min=7;particle_id_max=8};fly2='three';lua_config='three'})
function Invoke-FixturePython {$global:LASTEXITCODE=0}
function Set-SimionBatchesFromPlan {throw 'continuation repartitioned the source'}
function Write-RunJson {param($Path,$Value,$Depth) $Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path}
""" + block + r"""
if($firstSpecification.scheduler_batch.index-ne2-or$firstSpecification.scheduler_batch.count-ne4){throw 'did not observe largest missing batch'}
$observation=[pscustomobject]@{observed_peak_process_tree_working_set_bytes=100;available_memory_bytes=1000;
 total_physical_memory_bytes=2000;observed_process_cpu_percent=1;observed_background_cpu_percent=2;completed_naturally=$false;
 process_record=[pscustomobject]@{specification=[pscustomobject]@{scheduler_batch=$null}}}
& $replanAction $observation
if((Get-Content -LiteralPath $batchPlan -Raw)-cne'original-partition'){throw 'frozen partition changed'}
if($script:resourceCalibrationRequired-or$script:resourceIdentityWasUnknown){throw 'continuation published an inexact profile'}
if($observation.process_record.specification.scheduler_batch.index-ne2){throw 'wrong observed unit'}
$continuationLargestMissing=6;$script:resourceCalibrationRequired=$true;$script:resourceIdentityWasUnknown=$true
& $replanAction $observation
if((Get-Content -LiteralPath $dispatchPlan -Raw|ConvertFrom-Json).limits.maximum_concurrency-ne1){throw 'larger later batch was not admitted conservatively'}
exit 0
"""
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT, env={**os.environ, "RF_TEST_ROOT": str(root)}, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_full_continuation_skips_field_and_iob_native_work(self) -> None:
        script = r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_TEST_RUNNER,[ref]$tokens,[ref]$errors)
$guard=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.IfStatementAst] -and
 $node.Extent.Text.StartsWith('if(-not$continuationAllReuse)') -and $node.Extent.Text.Contains("Invoke-SimionStep 'gem2pa'")},$true))
if($guard.Count-ne1){throw 'missing native field guard'}
$continuationAllReuse=$true
function Invoke-SimionStep {throw 'unexpected native field or IOB start'}
function Read-RfSimionFieldCheckpoint {throw 'unexpected field loading'}
function Protect-RfSimionFieldCheckpoint {throw 'unexpected PA verification'}
function Write-RfSimionFieldCheckpoint {throw 'unexpected field producer'}
. ([scriptblock]::Create($guard[0].Extent.Text))
exit 0
"""
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
                                cwd=REPO_ROOT, env={**os.environ, "RF_TEST_RUNNER": str(RUNNER)},
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_continuation_dispatches_only_missing_batches(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    if($null-eq$dispatchPlan-and$batchRuns.Count-eq 1-and$null-eq$firstSpecification)"):
                       source.index("    if($batchRuns.Count-gt 1-or($continuationPredecessor-and-not$caseRunsNative[$name])){")]
        script = r"""
$ErrorActionPreference='Stop';$simion='unused';$solverDir='.';$logDir='.';$resourceUsage='unused'
$runDir='.';$dispatchPlan='unused';$rfDriveKernelLua='unused';$name='primary';$firstSpecification=$null;$replanAction=$null
$flyArguments=@('a','b','c','d','e','f','g')
$batchRuns=@(1,2|ForEach-Object{@{batch=@{index=$_;particle_id_min=$_;particle_id_max=$_};lua_config='unused';fly2='unused'}})
$batchState=[pscustomobject]@{runs=$batchRuns}
function Invoke-SimionStep {throw 'unexpected native start'}
function New-TransportBatchRuns {throw 'continuation rewrote a live batch input'}
function Invoke-SimionBatchPhase {
 param($PrepareRemaining,$FirstSpecification)
 $formal=if($FirstSpecification){@{process_record=@{specification=@{scheduler_batch=@{index=2}}}}}else{$null}
 $prepared=& $PrepareRemaining $formal
 $actual=@($prepared.pending|ForEach-Object{$_.scheduler_batch.index})
 if(($actual -join ',')-ne$expected){throw "wrong pending batches: $actual"}
 return @{resource_budget_exceeded=$false;processes=@();prepared=$prepared}
}
foreach($expected in @('2','')) {
 $continuationUnits=@{'primary.batch_01'=@{}}
 if($expected-eq''){$continuationUnits['primary.batch_02']=@{}}
""" + block + "\n}"
        script += "\n$expected='';$continuationPredecessor='parent';$firstSpecification=@{name='first-missing'};$continuationUnits=@{'primary.batch_01'=@{}}\n" + block
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_control_launches_all_batches_after_retaining_primary_first_worker(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    if($null-eq$dispatchPlan-and$batchRuns.Count-eq 1-and$null-eq$firstSpecification)"):
                       source.index("    if($batchRuns.Count-gt 1-or($continuationPredecessor-and-not$caseRunsNative[$name])){")]
        script = """
$ErrorActionPreference='Stop'
$script:calls=@()
function Invoke-SimionBatchPhase {
 param($PrepareRemaining,$FirstSpecification)
 $formal=if($null-ne$FirstSpecification){@{process_record=@{name='primary-first';specification=@{scheduler_batch=@{index=1}}}}}else{$null}
 $prepared=& $PrepareRemaining $formal
 $script:calls+=@{launched=@($prepared.pending|ForEach-Object{$_.scheduler_batch.index}); retained=[int]($null-ne$formal)}
 return @{resource_budget_exceeded=$false;processes=@(@{exit_code=0});prepared=$prepared}
}
$simion='unused';$solverDir='.';$logDir='.';$resourceUsage='unused';$runDir='.';$dispatchPlan='unused';$rfDriveKernelLua='unused';$continuationUnits=@{};$continuationPredecessor=$null
$flyArguments=@('a','b','c','d','e','f','g')
$batchRuns=@(1,2|ForEach-Object{@{batch=@{index=$_;particle_id_min=$_;particle_id_max=$_};lua_config='unused';fly2='unused'}})
$batchState=[pscustomobject]@{runs=$batchRuns};$replanAction=$null
function New-TransportBatchRuns {return $batchRuns}
""" + "\nforeach($name in @('primary','control')){\n$firstSpecification=if($name-eq'primary'){@{name='first'}}else{$null}\n" + block + "\n}\nConvertTo-Json -InputObject $script:calls -Depth 6"
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [
            {"launched": [2], "retained": 1}, {"launched": [1, 2], "retained": 0},
        ])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_single_dispatch_waits_in_shared_executor_before_start(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        block = source[source.index("    if($null-eq$dispatchPlan-and$batchRuns.Count-eq 1"):
                       source.index("    if($batchRuns.Count-gt 1-or($continuationPredecessor-and-not$caseRunsNative[$name])){")]
        # This fixture isolates admission and lifecycle; separate tests exercise
        # the production completion callback with actual evidence files.
        block = block.replace("-OnProcessCompleted $checkpointAction", "")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan",
                "estimation": {"kind": "exact_resource_profile",
                               "per_process_memory_budget_bytes": 64 * 1024**2,
                               "memory_safety_factor": 1.1},
                "limits": {"maximum_concurrency": 1, "launch_stagger_seconds": 5,
                           "memory_critical_seconds": 15, "memory_recovery_stable_seconds": 45,
                           "maximum_memory_recovery_attempts": 2,
                           "maximum_memory_danger_termination_attempts": 2,
                           "memory_admission_reserve_bytes": 1024**3,
                           "memory_critical_reserve_bytes": 512 * 1024**2,
                           "cpu_admission_percent": 95,
                           "minimum_process_cpu_percent": 6.25},
            }), encoding="utf-8")
            def quoted(path: Path) -> str:
                return "'" + str(path).replace("'", "''") + "'"
            script = (
                f". {quoted(REPO_ROOT / 'common/resource_budget_support.ps1')}\n"
                f"$runDir={quoted(root)};$logDir=$runDir;$solverDir=$runDir;"
                f"$resourceUsage={quoted(root / 'usage.json')};$dispatchPlan={quoted(dispatch)};"
                + """
function Assert-HostResourceHeavyStage {}
function Invoke-SimionStep {throw 'single-dispatch-bypassed-wave'}
function Get-SystemCpuPercent {return [double]0}
# This contract tests dispatch/admission, not OS process discovery or startup.
# Keep the real executor, with deterministic host observations and completion.
$script:now=[datetimeoffset]'2026-10-16T00:00:00Z'
function Get-RepositoryUtcNow {return $script:now}
function Start-Sleep {
 param([int]$Seconds=0,[int]$Milliseconds=0)
 $script:now=$script:now.AddSeconds($Seconds+$Milliseconds/1000.0)
}
function Start-Process {throw 'dispatch-contract-fixture-must-not-spawn'}
$script:memorySamples=0
$script:workerLaunchCount=0;$script:processSamples=0
$script:waitCalls=0;$script:disposeCalls=0
function Get-RepositoryAvailableMemoryBytes {
 $script:memorySamples++
 if($script:memorySamples-le2){return [int64](1GB)}
 return [int64](4GB)
}
function Start-RepositoryScheduledProcess {
 param($Specification)
 if($script:memorySamples-lt3){throw 'worker-started-before-memory-recovery'}
 $script:workerLaunchCount++
 $script:launchedOnMemorySample=$script:memorySamples
 $process=[pscustomobject]@{ExitCode=0}
 $process|Add-Member ScriptMethod WaitForExit {$script:waitCalls++}
 $process|Add-Member ScriptMethod Dispose {$script:disposeCalls++}
 [pscustomobject]@{name=$Specification.name;specification=$Specification;process=$process;
  root_process_id=101;started_at=(Get-RepositoryUtcNow);tracked_process_ids=@(101);
  active=$true;completed=$false;exit_code=$null;peak_working_set_bytes=[int64]0;
  peak_managed_memory_bytes=[int64]0;pressure_terminated=$false}
}
function Get-ManagedSolverProcessSample {
 param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds)
 $script:processSamples++
 if($RootProcessIds.Count-ne1-or$RootProcessIds[0]-ne101){throw 'wrong-worker-sampled'}
 [pscustomobject]@{tracked_process_ids=@(101);active_process_ids=@();
  working_set_bytes=[int64](16MB);managed_memory_bytes=[int64](16MB)}
}
$simion='fixture-launcher.exe';$name='primary';$rfDriveKernelLua='unused';$continuationUnits=@{};$continuationPredecessor=$null
$flyArguments=@('a','b','c','d','e','f','g')
$batchRuns=@(@{batch=@{index=1;particle_id_min=1;particle_id_max=1};lua_config='unused';fly2='unused'})
$batchState=[pscustomobject]@{runs=$batchRuns};$firstSpecification=$null;$replanAction=$null
""" + block + """
$receipt=Get-Content -Raw $resourceUsage|ConvertFrom-Json
$pauses=@($receipt.scheduler_receipt.launch_pause_events|Where-Object {$_.reason-eq'available_memory_below_dynamic_admission'})
if($pauses.Count-lt1-or$wave.processes.Count-ne1-or$wave.processes[0].exit_code-ne0){throw 'missing-wait-or-completion'}
if($script:workerLaunchCount-ne1-or$script:launchedOnMemorySample-ne3-or$script:processSamples-ne1-or
   $script:waitCalls-ne1-or$script:disposeCalls-ne1){throw 'dispatch-or-completion-contract-changed'}
"""
            )
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                    cwd=REPO_ROOT, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_refine_returns_same_facade_grant_to_light_after_terminal_step(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("    $hostExecutionLease=Update-HostResourceStage -Lease $hostExecutionLease -Stage pa_refine")
        end = source.index("    if($RetentionClass-ne'compact'){", start)
        block = source[start:end]
        facade = REPO_ROOT / "common/host_execution_lease.ps1"
        for scenario in ("success", "failure", "inherited_light"):
            with self.subTest(scenario=scenario):
                script = f". '{facade}'\n$scenario='{scenario}'\n" + r'''
$script:events=@();$script:heavy=$false;$script:terminal=$false
$flyPhysics=@{refine_args=@('--nogui','--noprompt','refine','quad_monolithic.pa#')}
$hostExecutionLease=@{token='same-token';role='SIMION';stage='prepare';state_path='unused';
    inherited=($scenario-eq'inherited_light');status='acquired';reason=''}
function Invoke-HostResourceTransaction {
 param($StatePath,$Request)
 if($Request.token-ne'same-token'){throw 'token-changed'}
 if($Request.operation-eq'inherit'){
   if($Request.ContainsKey('budget')-and$Request.budget.heavy_stage-and-not$script:heavy){throw 'inherited-light-cannot-upgrade'}
   if($Request.ContainsKey('require_heavy_stage')-and-not$script:heavy){throw 'solver-without-heavy'}
   return @{}
 }
 if($Request.operation-ne'transition'){throw 'unexpected-operation'}
 if($Request.stage-eq'prepare'-and-not$script:terminal){throw 'released-before-terminal'}
 $script:heavy=[bool]$Request.budget.heavy_stage
 $script:events+="transition:$($Request.stage):$($script:heavy)"
 return @{status='acquired';reason=''}
}
function Invoke-SimionStep($name,$arguments){
 Assert-HostResourceHeavyStage -Lease $hostExecutionLease
 $script:events+="solver:$name"
 $script:terminal=$true
 if($scenario-eq'failure'){throw 'refine-fixture-failure'}
}
$caught=''
try {
''' + block + r'''
} catch {$caught=$_.Exception.Message}
if($scenario-eq'inherited_light'){
 if($caught-ne'inherited-light-cannot-upgrade'-or$script:events.Count-ne0){throw 'inherited-upgrade-bypassed'}
}else{
 if(($script:events-join',')-ne'transition:pa_refine:True,solver:refine,transition:prepare:False'){throw 'wrong-boundaries'}
 if($script:heavy-or$hostExecutionLease.stage-ne'prepare'){throw 'heavy-permission-not-returned'}
 if($scenario-eq'failure'-and$caught-ne'refine-fixture-failure'){throw 'failure-swallowed'}
 if($scenario-eq'success'-and$caught){throw $caught}
}
'''
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                        cwd=REPO_ROOT, capture_output=True, timeout=20, check=False)
                self.assertEqual(result.returncode, 0, repr(result.stdout) + repr(result.stderr))

    def test_simion_refine_and_flight_are_the_explicit_heavy_stages(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertEqual(source.count("Enter-HostResourceStage -Role SIMION"), 1)
        self.assertEqual(source.count("Update-HostResourceStage -Lease $hostExecutionLease"), 4)
        self.assertLess(source.index("-Stage prepare -RunId"), source.index("  $codeRoot=Join-Path"))
        self.assertLess(source.index("-Stage flight `"), source.index("$primary=Invoke-TransportCase"))
        self.assertLess(source.rindex("$control=Invoke-TransportCase"), source.index("-Stage postprocess `"))
        policy = json.loads((REPO_ROOT / "common/host_resource_policy.json").read_text(encoding="utf-8"))
        for stage in ("pa_refine", "flight"):
            self.assertTrue(policy["profiles"][policy["stages"]["SIMION/" + stage]]["heavy_stage"])
        self.assertNotIn("SIMION/prepare", policy["stages"])
        self.assertFalse(policy["profiles"][policy["stages"]["SIMION/postprocess"]]["heavy_stage"])

    def test_segmented_voltage_binding_uses_resolved_dynamic_electrodes(self) -> None:
        lua = (REPO_ROOT / "projects/rf_multipole_ion_optics/simion/simion_transport.lua").read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("adj_elect[electrode_id] = voltage", lua)
        self.assertIn("electrode_id <= 1000", lua)
        self.assertIn("$design.segmentation.segmented_rod_array", runner)
        self.assertIn("zero_axial_drop_rf_on", runner)
        self.assertNotIn("--segmented-rods", runner)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_bare_and_shell_bind_only_the_actual_native_electrodes(self) -> None:
        from projects.rf_multipole_ion_optics.tests.domain.test_simion_geometry import resolved_design,shell
        runner=RUNNER.read_text(encoding="utf-8")
        block=runner[runner.index("  $electrodesById=[ordered]@{}"):runner.index("  $normalizedGem=")]
        for enclosure in (None,shell()):
            for segmented in (False,True):
                design=resolved_design(enclosure,segmented=segmented)
                document=json.dumps(design)
                script="$ErrorActionPreference='Stop'\n$design='"+document+"'|ConvertFrom-Json -Depth 50\n"+"""
$geometry=$design.geometry_mm;$drive=$design.drive;$static=$design.static_electrodes_V
$rectangular=$false;$segmentedRodGeometry=($null-ne$design.segmentation.segmented_rod_array)
"""+block+"""
@{basis=$paBasisElectrodeIds;rod_lua=$rodLua;static_lua=$staticLua;static_count=@($staticRows).Count}|ConvertTo-Json -Compress
"""
                result=subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],cwd=REPO_ROOT,capture_output=True,text=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                binding=json.loads(result.stdout)
                expected=list(range(1,(5 if segmented else 3)+(1 if enclosure else 0)))
                self.assertEqual(binding["basis"],expected)
                self.assertEqual(binding["static_count"],1 if enclosure else 0)
                self.assertIn("rod_electrodes={",binding["rod_lua"])
                self.assertNotIn("output_electrode",binding["static_lua"])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_open_mechanical_exit_serializes_no_physical_aperture(self) -> None:
        runner=RUNNER.read_text(encoding="utf-8")
        start=runner.index("mechanical_exit_aperture_radius_lua=")+len("mechanical_exit_aperture_radius_lua=")
        block="$mechanicalRadiusLua="+runner[start:runner.index(";\n",start)]+"\n"
        self.assertIn("$flyPhysics.mechanical_exit_aperture_radius_lua",runner)
        for enabled,radius,expected in ((True,None,"nil"),(True,3.6,"3.6"),(False,None,"nil")):
            document=json.dumps({"aperture_radius_mm":radius} if enabled else {})
            script="$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest;\n$mechanicalExitEnabled=$"+str(enabled).lower()+"\n$exitObservation='"+document+"'|ConvertFrom-Json\n"+block+"Write-Output $mechanicalRadiusLua"
            result=subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],cwd=REPO_ROOT,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.strip(),expected)

    def test_segmented_rf_program_collapses_shared_pa_electrodes(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$electrodesById=[ordered]@{}", runner)
        self.assertIn("$electrodesById.Contains($electrodeId)", runner)
        self.assertIn("$electrodesById[[object]$electrodeId]", runner)
        self.assertIn(
            "RF electrode $electrodeId has inconsistent group or common-mode voltage.",
            runner,
        )
        self.assertIn("$electrodesById.Values|Sort-Object electrode_id", runner)

    def test_fractional_field_uses_original_checkpoint_and_rejects_old_cache_protocol(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        for token in (
            "simion_field_checkpoint_support.ps1",
            "Read-RfSimionFieldCheckpoint",
            "Protect-RfSimionFieldCheckpoint",
            "Write-RfSimionFieldCheckpoint",
            "SIMION_PA_BASIS_POLICY_UNSUPPORTED",
            "SIMION GEM must declare exactly one PA surface mode.",
        ):
            self.assertIn(token, runner)
        self.assertNotIn("function Get-VerifiedPaBasisFiles", runner)
        self.assertNotIn("function Get-TextSha256", runner)
        self.assertNotIn("Remove-Item -LiteralPath $paBasisCacheDir", runner)
        self.assertNotIn("-ItemType HardLink", runner)
        self.assertNotIn("Invoke-CommonPaFamilyCache", runner)
        self.assertLess(
            runner.index("Protect-RfSimionFieldCheckpoint -Checkpoint"),
            runner.index("Invoke-SimionStep 'build_runtime_iob'"),
        )

    def test_volume_source_skips_planar_phase_reserialization(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$hasVolumeSnapshotReceipt=", runner)
        self.assertEqual(
            runner.count("-not$hasVolumeSnapshotReceipt-and$resolvedRuntimeDocument"),
            2,
        )
        self.assertIn("Re-serializing it through the planar phase matcher", runner)

    def test_build_and_fly_are_serialized_without_nested_reentry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        watchdog = (REPO_ROOT / "common/resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Invoke-ResourceBudgetedProcess", source)
        self.assertIn("Start-Process @startArguments", watchdog)
        self.assertIn("$record.process.WaitForExit", watchdog)
        self.assertIn("Start-Sleep -Milliseconds 500", source)
        self.assertIn("'--nogui','--noprompt','fly'", source)
        self.assertNotIn("simion_run_fly.lua", source)

    def test_unknown_formal_writer_keeps_owner_protection(self):
        command = r"""
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
$owner=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$_.CatchClauses.Count-and$_.CatchClauses[0].Extent.Text.Contains('$simionRunFailure=$_')})[-1]
$tail=$owner.CatchClauses[0].Extent.Text+'finally'+$owner.Finally.Extent.Text
$script:writerCompletionUnknown=$false;$resourceBudgetExceeded=$false;$summary='inert';$hostExecutionOutcome='failed'
$ResultPath='external';$physicalRunDir='run';$phaseName='flight';$phaseTimings=@{};$runTimer=[Diagnostics.Stopwatch]::StartNew()
function Set-RfRunPhase($Next) {}
$script:events=[Collections.Generic.List[string]]::new()
function Write-RunJson {param($Path,$Value,[switch]$Atomic,$Depth) if($Path-eq'inert'){if($Value.status-ne'writer_completion_unknown'-or$Value.drain_error-ne'drain failed'){throw 'missing summary'}}elseif($Value.execution_status-ne'writer_completion_unknown'){throw 'missing result'};$script:events.Add('result')}
function Complete-FailedRun {throw 'published terminal'}
function Remove-RunPackageExecutionAlias {$script:events.Add('alias')}
function Exit-HostExecutionLease {$script:events.Add('host')}
foreach($data in @("`$e.Data['simion_first_batch_drain_error']='drain failed'", "`$e.Data['simion_wave_writer_completion_confirmed']=`$false;`$e.Data['simion_wave_drain_error']='drain failed'")){
 $script:events.Clear();$script:writerCompletionUnknown=$false
 try{. ([scriptblock]::Create("try{`$e=[Exception]::new('primary');$data;throw `$e}"+$tail))}catch{if($_.Exception.Message-ne'primary'){throw}}
 if(($script:events-join',')-ne'result,result'){throw 'unknown writer protection released'}
}
exit 0
"""
        command = command.replace("$args[0]", "'" + str(RUNNER).replace("'", "''") + "'")
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", command], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_dispatch_retains_first_formal_batch_before_parallel_replan(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        discover = "common.simion.resource_profile discover"
        schedule = "common.simion.resource_scheduler"
        publish = "common.simion.resource_profile publish"
        self.assertIn(discover, source)
        self.assertIn("--profiles $resourceProfiles", source)
        owner = (REPO_ROOT / "common/contracts/run_artifact_workflow.ps1").read_text(encoding="utf-8-sig")
        self.assertIn(publish, owner)
        self.assertLess(source.index(discover), source.index(schedule))
        self.assertLess(owner.index("Complete-ResourceUsage"), owner.index(publish))
        self.assertIn("formal_first_batch_observation", source)
        self.assertIn("$automaticDispatch=[pscustomobject]@{kind='automatic';field_kind='rf';independent_particles=$true}", source)
        self.assertIn("Invoke-SimionBatchPhase", source)
        self.assertIn("--observed-formal-peak-bytes", source)
        self.assertIn("--first-batch-completed", source)
        self.assertIn("$retainedFormalBatchOutputs", source)
        self.assertIn("retained first formal", source)
        self.assertIn("shared $($merge.property) CSV is incomplete", source)
        self.assertNotIn("RESOURCE_CALIBRATION_ONLY", source)
        self.assertIn("& $python @batchArguments | Out-Null", source)
        self.assertNotIn("maximum_process_tree_working_set_bytes=[int64]", source)
        self.assertNotIn("$request[$name]=[int]$automaticDispatch.$name", source)

    def test_scheduler_rejects_reused_process_ids(self) -> None:
        support = (REPO_ROOT / "common/resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("TrackedProcessStartedAtUtcTicks", support)
        self.assertIn("tracked_process_started_at_utc_ticks", support)
        self.assertIn("$staleProcessIds", support)

    def test_governed_profile_is_the_only_physical_entry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in ("ProjectId", "DesignProfileId", "ParticleSourcePath"):
            self.assertIn(token, source)
        for legacy in (
            "ProjectRoot",
            "ResolvedDesignPath",
            "ParticleMassAmu",
            "Adapter",
            "FieldScreenRunId",
            "AxialAccelerationContractPath",
            "EntranceConnectorLengthMm",
            "ExitConnectorLengthMm",
            "EndplateAcceleration",
        ):
            self.assertNotIn(legacy, source)
        self.assertIn("projects.rf_multipole_ion_optics.runtime.design_profile", source)
        self.assertIn("projects.rf_multipole_ion_optics.core.compile_design_request", source)
        self.assertIn("projects.rf_multipole_ion_optics.runtime.particle_source_preflight", source)

    def test_typed_mode_is_forwarded_to_both_solver_compilers(self) -> None:
        for runner_name in (
            "run_finite_3d_transport.ps1",
            "run_simion_finite_3d_transport.ps1",
        ):
            source = (RUNNER.parent / runner_name).read_text(encoding="utf-8")
            self.assertIn("$profile.profile.mode_id", source)
            self.assertIn("$profile.paths.operating_mode_registry", source)
            self.assertIn("--operating-mode-registry", source)
            self.assertIn("--mode-id", source)
            self.assertIn("operating_mode_registry=$modeRegistry", source)
            self.assertIn("operating_mode_id=$modeId", source)

    def test_tool_paths_are_numerical_runtime_parameters(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        template_support = (
            REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/simion_layout_template_support.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[string]$SimionExe", source)
        self.assertNotIn("[string]$TemplateIob", source)
        self.assertIn(
            "projects\\rf_multipole_ion_optics\\runtime\\simion_layout_template_support.ps1", source
        )
        self.assertIn("Resolve-MultipoleSimionLayoutTemplate", source)
        self.assertIn("projects.rf_multipole_ion_optics.runtime.simion_layout_template", template_support)
        self.assertIn("build_simion_runtime_iob.lua", source)
        self.assertIn("simion_layout_template_registry", source)
        self.assertIn("simion_layout_template_con", source)
        self.assertNotIn("C:\\Program Files\\SIMION-2020", source)

    def test_manifest_lifecycle_preserves_partial_outputs(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        support = (
            REPO_ROOT / "common/contracts/run_artifact_support.ps1"
        ).read_text(encoding="utf-8")
        self.assertEqual(source.count("Complete-FailedRun"), 1)
        self.assertIn("Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $hostExecutionOutcome", source)
        self.assertIn("Get-ChildItem -LiteralPath $directory -Recurse -File", support)
        self.assertIn("Write-VerifiedRunManifest", support)
        for output in (
            'simion_summary__$primaryName.json',
            'simion_summary__$controlName.json',
            'particle_states__$primaryName.csv',
            'particle_states__$controlName.csv',
            'trajectory_samples__$primaryName.csv',
            'trajectory_samples__$controlName.csv',
        ):
            self.assertIn(output, source)

    def test_census_and_handoff_are_exact_resolved_projections(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$interfaces.exit.handoff_plane_z_mm", source)
        self.assertIn("$interfaces.exit.census_plane_z_mm", source)
        self.assertIn("handoff_plane_mm=$handoffPlaneMm", source)
        self.assertIn("census_plane_mm=$censusPlaneMm", source)

    def test_gem_z_spacing_maps_to_the_flight_axis_controls(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("DefaultParameterSetName='IsotropicCell'", source)
        for axis in ("X", "Y", "Z"):
            self.assertIn(
                f"ParameterSetName='AnisotropicCell')]\n"
                f"  [ValidateScript({{[double]::IsFinite($_) -and $_ -gt 0}})][double]$CellMm{axis}",
                source,
            )
            self.assertIn(f"--cell-mm-{axis.lower()} $resolvedCellMm{axis}", source)
        self.assertIn("trajectory_plane_step_mm=$resolvedCellMmZ", source)
        self.assertIn("axial_axis='x'", source)
        self.assertIn('axial_axis="$($flyPhysics.axial_axis)"', source)
        self.assertIn("maps GEM +z to flight +x", source)

    def test_runner_accepts_small_positive_and_large_exploration_numerics(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        parameter_block = source[: source.index(")\n\nSet-StrictMode")] + ")\n'BOUND'\n"
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "parameter_probe.ps1"
            probe.write_text(parameter_block, encoding="utf-8")
            result = subprocess.run(
                [
                    "pwsh", "-NoProfile", "-NonInteractive", "-File", str(probe),
                    "-ProjectId", "probe", "-RuntimeProfileId", "probe",
                    "-DesignProfileId", "probe", "-ParticleSourcePath", "probe",
                    "-EngineeringBudgetPath", "probe", "-CellMm", "0.000001",
                    "-MaximumTimeUs", "0.000001", "-TrajectoryQuality", "10001",
                ],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BOUND", result.stdout)

    def test_solver_numerics_artifact_excludes_dispatch_control(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("simion_execution_batch_plan.json", source)
        self.assertNotIn("solverNumericsDocument.execution_batching", source)

    def test_final_run_id_is_always_forwarded_to_budget_authorization(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("$runIdWasExplicit", source)
        self.assertIn("$budgetArguments+=@('--run-id',$RunId)", source)
        self.assertIn("authorized_run_id", source)
        self.assertLess(
            source.index("authorized_run_id"),
            source.index("New-RunPackage"),
        )

    def test_pa_grid_budget_is_audited_before_simion_starts(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "Get-SimionPaGridAudit",
            "maximum_pa_grid_points",
            "simion_grid_audit.json",
            "multipole_simion_pa_grid_audit",
            "SIMION PA grid point budget exceeded",
        ):
            self.assertIn(token, source)
        audit = source.index(
            "$gridAuditDocument=Get-SimionPaGridAudit -GemPath $gem"
        )
        persisted = source.index(
            "Set-Content -LiteralPath $gridAudit -Encoding UTF8",
            audit,
        )
        rejected = source.index("if($gridAuditDocument.status-eq'FAIL')", persisted)
        simion_start = source.index("Invoke-SimionStep 'gem2pa'")
        self.assertLess(audit, persisted)
        self.assertLess(persisted, rejected)
        self.assertLess(rejected, simion_start)
        self.assertIn("simion_grid_audit=$gridAudit", source)

    def test_pa_grid_budget_accepts_below_cap_and_rejects_over_cap(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        start = source.index("function Get-SimionPaGridAudit")
        end = source.index("\n$repoRoot=", start)
        audit_function = source[start:end]
        with tempfile.TemporaryDirectory() as directory:
            gem = Path(directory) / "anisotropic.gem"
            gem.write_text(
                "pa_define(101, 41, 51, planar, non-mirrored)\n",
                encoding="ascii",
            )

            def audit(maximum: int | None) -> dict:
                maximum_argument = "$null" if maximum is None else str(maximum)
                command = (
                    f"{audit_function}\n"
                    f"Get-SimionPaGridAudit -GemPath '{gem}' "
                    f"-MaximumPaGridPoints {maximum_argument} | "
                    "ConvertTo-Json -Compress"
                )
                result = subprocess.run(
                    [
                        "pwsh",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        command,
                    ],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            grid_points = 101 * 41 * 51
            below_cap = audit(grid_points + 1)
            self.assertEqual(below_cap["status"], "PASS")
            self.assertEqual(below_cap["grid_points"], grid_points)
            self.assertEqual(
                below_cap["maximum_pa_grid_points"],
                grid_points + 1,
            )
            over_cap = audit(grid_points - 1)
            self.assertEqual(over_cap["status"], "FAIL")
            self.assertEqual(over_cap["grid_points"], grid_points)
            unconfigured = audit(None)
            self.assertEqual(unconfigured["status"], "NOT_CONFIGURED")
            self.assertIsNone(unconfigured["maximum_pa_grid_points"])

    def test_rejected_handoff_writes_a_unique_terminal_event(self) -> None:
        program = (REPO_ROOT / "projects/rf_multipole_ion_optics/simion/simion_transport.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "write_particle_state(ion_number, 'terminal', 'lost', "
            "'acceptance_aperture', handoff)",
            program,
        )
        self.assertIn("inside_handoff_aperture(handoff)", program)
        self.assertIn("handoff_aperture.radius_mm", program)
        self.assertIn("terminal_written[ion_number] = true", program)
        self.assertIn("if terminal_written[particle] then return end", program)
        self.assertIn(
            "if previous_state[particle] then "
            "finalize_particle(particle, previous_state[particle]) end",
            program,
        )

    def test_raw_and_paired_transmission_cannot_diverge(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        metrics = (REPO_ROOT / "projects/rf_multipole_ion_optics/analysis/analyze_simion_transport_metrics.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("projects.rf_multipole_ion_optics.analysis.analyze_simion_transport_metrics", source)
        self.assertIn("def _handoff_transmission", metrics)
        self.assertIn('row["event"] == "handoff"', metrics)
        self.assertNotIn("Import-Csv", source)

    def test_waveform_and_all_drive_scalars_come_from_resolved_design(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        lua = (REPO_ROOT / "projects/rf_multipole_ion_optics/simion/simion_transport.lua").read_text(encoding="utf-8")
        for field in (
            "waveform",
            "rf_amplitude_V_zero_to_peak_per_group",
            "dc_amplitude_V_per_group",
            "common_mode_offset_V",
            "frequency_Hz",
            "phase_rad",
        ):
            self.assertIn(field, source)
        self.assertIn("transport_waveform == 'sine'", lua)
        self.assertIn("transport_waveform == 'cosine'", lua)
        kernel = (REPO_ROOT / "common/simion/rf_drive.lua").read_text(encoding="utf-8")
        self.assertIn("RF drive waveform must be sine or cosine", kernel)
        self.assertIn("config.waveform == 'sine' and math.sin or math.cos", kernel)

    def test_mechanically_segmented_rods_always_receive_full_length_rf(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        comsol = (REPO_ROOT / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "$segmentedRodGeometry=($null-ne$design.segmentation.segmented_rod_array)",
            source,
        )
        self.assertIn("if($segmentedRodGeometry){", source)
        self.assertIn(
            "$segmented=($axialTopology-eq'segmented_rod_axial_acceleration')",
            source,
        )
        self.assertIn(
            "segmentedRodGeometry = isfield(design.segmentation,'segmented_rod_array')",
            comsol,
        )
        self.assertIn("if segmentedRodGeometry", comsol)
        self.assertIn(
            "segmentedAccelerationEnabled = strcmp("
            "axialTopology,'segmented_rod_axial_acceleration');",
            comsol,
        )

    def test_comsol_uses_the_single_frozen_enclosure_projector(self) -> None:
        comsol=(REPO_ROOT/"projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m").read_text(encoding="utf-8")
        helper=(REPO_ROOT/"projects/rf_multipole_ion_optics/comsol/build_multipole_enclosure.m").read_text(encoding="utf-8")
        self.assertIn("build_multipole_enclosure(geom,enclosureLayout.bodies,'enclosure')",comsol)
        self.assertIn("create_comsol_cylindrical_shell",helper)
        for field in ("inner_radius_mm","outer_radius_mm","z_max_mm","z_min_mm"):
            self.assertIn("body."+field,helper)
        self.assertNotIn("cylindrical_grounded_shield_through",comsol)
        self.assertIn("domain.radius_mm",comsol)
        self.assertIn("contract.ground_V==0",comsol)
        self.assertNotIn("exit_outer_endcap_aperture_plate_connector_V",comsol)

    def test_metrics_are_unqualified_without_explicit_evidence(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$qualification='UNQUALIFIED'", source)
        self.assertIn("evaluate_transport_evidence", source)
        self.assertIn("analyze_simion_axial_acceleration", source)
        self.assertIn("projects.rf_multipole_ion_optics.analysis.analyze_simion_transport_metrics", source)
        self.assertNotIn("function ConvertTo-TransportMetricCase", source)
        self.assertNotIn("MinimumRfTransmission", source)
        self.assertNotIn("MinimumImprovementOverZeroRf", source)

    def test_validator_output_is_not_returned_as_case_data(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("--output $stateReport|Out-Null", source)
        self.assertIn("return Get-Content -LiteralPath $caseSummary", source)

    def test_reference_comsol_run_is_verified_before_simion(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "common.contracts.verify_run_manifest",
            "--require-status success",
            "--require-local-run-config",
            "--require-run-id $ReferenceComsolRunId",
            "--require-project $ProjectId",
            "--require-mode resolved_design_transport",
            "--require-design-profile-id $DesignProfileId",
            "--require-parent-resolved-design-sha256 $resolvedHash",
            "--require-particle-source-sha256",
            "reference_comsol_run_manifest.json",
            "reference_comsol_run_manifest_sha256",
            "reference_comsol_source_run_id",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("common.contracts.verify_run_manifest"),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_project_wrappers_are_thin_profile_consumers(self) -> None:
        wrapper_path = (REPO_ROOT / "projects/rf_multipole_ion_optics/workflows"
                        / "no_collision_transport/run_simion.ps1")
        wrapper = wrapper_path.read_text(encoding="utf-8-sig")
        self.assertIn("RuntimeProfileId", wrapper)
        self.assertIn("project_transport_launcher_support.ps1", wrapper)
        for forbidden in ("DesignProfileId", "ParticleSourcePath", "FieldScreenRunId",
                          "AxialAccelerationContractPath"):
            self.assertNotIn(forbidden, wrapper)

    def test_5ev_projection_requires_and_consumes_explicit_operating_point(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$sourceProjectionArguments", runner)
        self.assertIn("--expected-source-family-sha256", runner)
        self.assertGreaterEqual(runner.count("--source-family"), 2)
        self.assertGreaterEqual(runner.count("--operating-point"), 2)
        project = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole"
        resolved_path = project / "config" / "resolved_design_official.json"
        family_path = project / "config" / "interface_readiness_particle_source.json"
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        speed = math.sqrt(
            2.0 * 5.0 * ELEMENTARY_CHARGE_C / (100.0 * AMU_KG)
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=COLUMNS, lineterminator="\n"
                )
                writer.writeheader()
                for particle_id in range(1, 101):
                    writer.writerow(
                        {
                            "particle_id": particle_id,
                            "birth_time_s": "0",
                            "x_mm": "0",
                            "y_mm": "0",
                            "z_mm": resolved["interfaces_mm"]["entrance"][
                                "release_plane_z_mm"
                            ],
                            "vx_m_s": "0",
                            "vy_m_s": "0",
                            "vz_m_s": format(speed, ".17g"),
                            "mass_amu": "100",
                            "charge_state": "1",
                        }
                    )
            with self.assertRaisesRegex(
                ValueError, "resolved closed interval"
            ):
                render_canonical_source(source, resolved_path)
            fly, states, count = render_canonical_source(
                source,
                resolved_path,
                source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(
                    family_path.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(count, 100)
            self.assertIn("ke=5", fly)
            self.assertIn("ke=5", states)
            with self.assertRaisesRegex(ValueError, "requires both"):
                render_canonical_source(
                    source,
                    resolved_path,
                    source_family_path=family_path,
                )
            with self.assertRaisesRegex(ValueError, "differs from the frozen"):
                render_canonical_source(
                    source,
                    resolved_path,
                    source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256="0" * 64,
                )

            class DriftingSourceFamily:
                def __init__(self) -> None:
                    self.read_count = 0

                def read_bytes(self) -> bytes:
                    self.read_count += 1
                    return (
                        family_path.read_bytes()
                        if self.read_count == 1
                        else b'{"schema_version":1,"operating_points":{}}'
                    )

            drifting_family = DriftingSourceFamily()
            _, _, drift_count = render_canonical_source(
                source,
                resolved_path,
                source_family_path=drifting_family,  # type: ignore[arg-type]
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(
                    family_path.read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(drift_count, 100)
            self.assertEqual(drifting_family.read_count, 1)

            fly, states, count = render_canonical_source(
                source, resolved_path, source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                particle_id_min=21, particle_id_max=40,
            )
            self.assertEqual(count, 20)
            self.assertIn("[21]", states)
            self.assertIn("[40]", states)
            self.assertNotIn("[20]", states)
            self.assertEqual(fly.count("standard_beam"), 20)
            _, local_states, _ = render_canonical_source(
                source, resolved_path, source_family_path=family_path,
                operating_point_id="rf_to_oatof_100amu_5eV",
                expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                particle_id_min=21, particle_id_max=40, simion_particle_id_offset=20,
            )
            self.assertIn("[1]", local_states)
            self.assertIn("[20]", local_states)
            self.assertNotIn("[21]", local_states)
            with self.assertRaisesRegex(ValueError, "offset exceeds"):
                render_canonical_source(
                    source, resolved_path, source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                    particle_id_min=21, particle_id_max=40, simion_particle_id_offset=21,
                )
            with self.assertRaisesRegex(ValueError, "batch interval"):
                render_canonical_source(
                    source, resolved_path, source_family_path=family_path,
                    operating_point_id="rf_to_oatof_100amu_5eV",
                    expected_source_family_sha256=hashlib.sha256(family_path.read_bytes()).hexdigest(),
                    particle_id_min=1,
                )

    def test_primary_only_case_set_skips_control_and_records_null_control(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "[ValidateSet('primary_and_zero_axial_control','primary_and_rf_off_energy_control','primary_only')]",
            runner,
        )
        self.assertIn("if($CaseSet-eq'primary_and_zero_axial_control')", runner)
        self.assertIn("elseif($CaseSet-eq'primary_and_rf_off_energy_control')", runner)
        self.assertIn("$control=Invoke-TransportCase $controlName 0 1", runner)
        self.assertIn("--metric-kind rf_off_energy_control", runner)
        self.assertIn("case_set=$CaseSet", runner)

    def test_parallel_batching_is_single_wave_and_revalidates_the_merged_state(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        support = (REPO_ROOT / "common/resource_budget_support.ps1").read_text(encoding="utf-8")
        self.assertIn("common.simion.particle_batching", runner)
        self.assertIn("SIMION shared single-wave batch plan differs from the canonical source.", runner)
        self.assertIn("--particle-id-min", runner)
        self.assertIn("Invoke-SimionBatchPhase", runner)
        self.assertIn("SIMION shared single-wave batch plan", runner)
        self.assertIn("SIMION $name particle-state contract failed.", runner)
        self.assertIn("--merge-rebase-csv", runner)
        self.assertIn("--merge-summaries", runner)
        self.assertIn(
            "'--observed-formal-peak-bytes',([string]$formalObservation.observed_peak_process_tree_working_set_bytes)",
            runner,
        )
        self.assertIn(
            "--from-dispatch-plan $dispatchPlan",
            runner,
        )
        self.assertNotIn("Add-Content -LiteralPath $caseState", runner)
        self.assertIn("execution_wave", support)
        self.assertIn("$control=$null;$controlName=$null", runner)
        self.assertIn(
            "Primary-only SIMION runs cannot consume a paired-case evidence contract.",
            runner,
        )
        self.assertIn("--metric-kind primary", runner)
        self.assertIn("$controlTransmission=$null", runner)
        self.assertIn('"simion_summary__$primaryName.json"', runner)
        self.assertIn("Primary SIMION case did not produce a transmission.", runner)
        self.assertIn("if($CaseSet-ne'primary_only')", runner)
        self.assertIn(
            "Paired SIMION case set did not produce a control transmission.", runner
        )


if __name__ == "__main__":
    unittest.main()
