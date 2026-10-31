Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-CooledReferenceCalibration {
 [CmdletBinding()]
 param(
  [Parameter(Mandatory)]$Package,[Parameter(Mandatory)][string]$RepoRoot,
  [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$SimionExe,
  [Parameter(Mandatory)]$Limits,[Parameter(Mandatory)][string]$ProjectRunsRoot,
  [Parameter(Mandatory)][ref]$HostLease,
  $NativeOperations=$null,[string]$NativeResourceReleaseId='simion'
 )
 $module='integrations.workflows.cooled_frontend.reference'
 $context=@{Python=$Python;RepoRoot=$RepoRoot;RunDirectory=[string]$Package.artifact_run_dir}
 $metadata=Invoke-FrontendRuntimePython @context -Name reference_prepare `
  -Arguments @('-m',$module,'prepare-reference','--run',[string]$Package.artifact_run_dir) -Json
 $guards=[Collections.Generic.List[string]]::new()
 $trials=[Collections.Generic.List[object]]::new()
 $referenceFailure=$null;$referenceWriterUnknown=$false
 try{
  foreach($record in $metadata.working_points){
   $null=Protect-ImmutablePaSource -Source ([string]$record.path) -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
   $guards.Add([string]$record.path)
  }
  $trialPath=Join-Path $Package.input_dir 'reference_observed_trials.json'
  $verifiedTrial=$null
  $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
  $null=Invoke-FrontendFlightPhase -RunDirectory $Package.artifact_run_dir -ProjectRunsRoot $ProjectRunsRoot `
   -RepoRoot $RepoRoot -Python $Python -RuntimeModule $module -SimionExe $SimionExe -Limits $Limits `
   -Phase held_off -SharedTimesPath ([string]$metadata.shared_times_path) `
   -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId
  $discovery=Invoke-FrontendRuntimePython @context -Name reference_collect_held_off `
   -Arguments @('-m',$module,'collect-trial','--run',[string]$Package.artifact_run_dir,'--phase','held_off') -Json
  if($discovery.status-ne'window_observed'){throw "Reference calibration stopped: held-OFF discovery status=$($discovery.status); native evidence retained."}
  $scheduled=@($discovery.arrival_window.initial_trials)
  if($scheduled.Count-ne2){throw 'Reference discovery requires two native-supported candidate pulse times.'}
  foreach($step in 0..2){
   if($step-lt2){$phase=[string]$scheduled[$step].phase;$pulse=[double]$scheduled[$step].pulse_time_us}
   else{
    $iterationTrialPath=Join-Path $Package.input_dir ("reference_observed_trials_before_$step.json")
    Write-RunJson -Path $iterationTrialPath -Value $trials.ToArray() -Depth 100
    $code=@'
import json,sys
from pathlib import Path
from integrations.workflows.cooled_frontend.pulse import propose_common_pulse
metadata=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
trials=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig'))
print(json.dumps(propose_common_pulse(trials,target_y_mm=metadata['target_y_mm'],release_start_us=metadata['release_start_us']),allow_nan=False))
'@
    $proposal=Invoke-FrontendRuntimePython @context -Name "reference_proposal_$step" `
     -Arguments @('-c',$code,[string]$metadata.metadata_path,$iterationTrialPath) -Json
    if(-not$proposal.native_check_required){$verifiedTrial=@($proposal.reference_trials)[0];break}
    $phase='secant'
    $pulse=[double]$proposal.proposal_time_us
   }
   $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
   $null=Invoke-FrontendFlightPhase -RunDirectory $Package.artifact_run_dir -ProjectRunsRoot $ProjectRunsRoot `
    -RepoRoot $RepoRoot -Python $Python -RuntimeModule $module -SimionExe $SimionExe -Limits $Limits `
    -Phase $phase -PulseTimeUs $pulse -SharedTimesPath ([string]$metadata.shared_times_path) `
    -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId
   $trial=Invoke-FrontendRuntimePython @context -Name ("reference_collect_"+$phase) `
    -Arguments @('-m',$module,'collect-trial','--run',[string]$Package.artifact_run_dir,'--phase',$phase) -Json
   $trials.Add($trial)
   Write-RunJson -Path $trialPath -Value $trials.ToArray() -Depth 100
   if($trial.status-ne'exit_observed'){
    throw "Reference calibration stopped: phase=$phase pulse_time_us=$($trial.pulse_time_us) status=$($trial.status); no unique measured exit, native trial evidence retained."
   }
   $verifiedTrial=$trial
  }
  $verifiedPath=Join-Path $Package.input_dir 'reference_verified_trial.json'
  Write-RunJson -Path $verifiedPath -Value $verifiedTrial -Depth 100
  $freeze=@'
import json,sys
from pathlib import Path
from common.contracts.write_run_manifest import file_record
from integrations.workflows.cooled_frontend.pulse import freeze_common_pulse_decision
metadata=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'));trials_path=Path(sys.argv[2]);verified=json.loads(Path(sys.argv[4]).read_text(encoding='utf-8-sig'))
decision=freeze_common_pulse_decision(verified,target_y_mm=metadata['target_y_mm'],release_start_us=metadata['release_start_us'],field_identity=metadata['field_identity'],voltage_calibration=metadata['voltage_calibration'])
decision['all_reference_trials_record']=file_record(trials_path.resolve())
output=Path(sys.argv[3]);output.parent.mkdir(parents=True,exist_ok=True)
if output.exists():raise ValueError('Refuse to overwrite a frozen pulse decision')
output.write_text(json.dumps(decision,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(decision=decision,decision_record=file_record(output.resolve())),allow_nan=False))
'@
  $decision=Invoke-FrontendRuntimePython @context -Name reference_freeze_decision `
   -Arguments @('-c',$freeze,[string]$metadata.metadata_path,$trialPath,(Join-Path $Package.result_dir 'reference/common_pulse_decision.json'),$verifiedPath) -Json
  return [pscustomobject]@{discovery=$discovery;reference_trials=$trials.ToArray();common_pulse_decision=$decision;mother_count=[int]$metadata.mother_count;
   simulated_reference_count=1;mother_population_flight=$false;qualification='Native cold-reference centering only; original-mother capture and population focusing remain unverified.'}
 }catch{
  $referenceFailure=$_
  if(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
     ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed'])){$referenceWriterUnknown=$true}
  throw
 }finally{
  if($null-ne$NativeOperations-and@($NativeOperations|Where-Object{-not$_.observation.exit_confirmed}).Count){$referenceWriterUnknown=$true}
  if(-not$referenceWriterUnknown){
   try{foreach($path in $guards){$null=Unprotect-ImmutablePaSource -Source $path}}catch{
    if($referenceFailure){$referenceFailure.Exception.Data['reference_guard_release_error']=$_}else{throw}
   }
  }
 }
}
