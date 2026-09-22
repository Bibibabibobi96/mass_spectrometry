[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$BunchSourceRunManifest,
  [Parameter(Mandatory)][string]$StaticPilotRunManifest,
  [Parameter(Mandatory)][string]$PilotTrialReceiptPath,
  [Parameter(Mandatory)][string]$PilotLogPath,
  [Parameter(Mandatory)][ValidateRange(0.0,[double]::MaxValue)][double]$GuardUs,
  [Nullable[double]]$PulseOffTimeUs=$null,
  [string]$RunId='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$sourceManifest=(Resolve-Path -LiteralPath $BunchSourceRunManifest).Path
$pilotManifest=(Resolve-Path -LiteralPath $StaticPilotRunManifest).Path
$pilotReceipt=(Resolve-Path -LiteralPath $PilotTrialReceiptPath).Path
$pilotLog=(Resolve-Path -LiteralPath $PilotLogPath).Path
$sourceRun=Split-Path -Parent $sourceManifest
$pilotRun=Split-Path -Parent $pilotManifest
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-bunch-pulse-schedule'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

function Get-VerifiedOutputRecord {
  param(
    [Parameter(Mandatory)][object[]]$Records,
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Label
  )
  $resolved=[IO.Path]::GetFullPath($Path)
  $matches=@($Records|Where-Object{
    $_.exists -and -not[string]::IsNullOrWhiteSpace([string]$_.path) -and
    [IO.Path]::GetFullPath([string]$_.path)-eq$resolved
  })
  if($matches.Count-ne 1){throw "Verified run manifest must bind exactly one $Label output."}
  $record=$matches[0]
  if((Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash-ne([string]$record.sha256).ToUpperInvariant()){
    throw "$Label differs from its verified run manifest."
  }
  return $record
}

$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'bunch_global_pulse_schedule_freeze' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight';$capacitySession=$null
try{
  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 1048576 -ProtectedPaths @($package.artifact_run_dir,$sourceRun,$pilotRun) `
    -Owner "mrtof-freeze-bunch-pulse-schedule:$RunId"
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession
  $failureStage='verify_sources'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $sourceManifest `
    --require-status success --require-project $projectId --require-mode deterministic_bunch_source_materialization
  if($LASTEXITCODE-ne 0){throw 'Bunch source run manifest failed verification.'}
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $pilotManifest `
    --require-status success --require-project $projectId
  if($LASTEXITCODE-ne 0){throw 'Static pilot run manifest failed verification.'}
  $sourceData=Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8|ConvertFrom-Json
  $pilotData=Get-Content -LiteralPath $pilotManifest -Raw -Encoding UTF8|ConvertFrom-Json
  if($pilotData.mode-notin@('finite_3d_two_prism_voltage_trial','finite_3d_bunch_static_pilot')){
    throw "Unsupported static bunch pilot run mode: $($pilotData.mode)"
  }
  $sourceReceiptPath=Join-Path $sourceRun 'results\bunch_source_receipt.json'
  Get-VerifiedOutputRecord -Records @($sourceData.outputs) -Path $sourceReceiptPath -Label 'bunch source receipt'|Out-Null
  Get-VerifiedOutputRecord -Records @($pilotData.outputs) -Path $pilotReceipt -Label 'static pilot trial receipt'|Out-Null
  Get-VerifiedOutputRecord -Records @($pilotData.outputs) -Path $pilotLog -Label 'static pilot log'|Out-Null

  $failureStage='freeze_inputs'
  $frozenSourceManifest=Copy-VerifiedRunInput -Source $sourceManifest -Destination (Join-Path $package.input_dir 'bunch_source_run_manifest.json')
  $frozenSourceReceipt=Copy-VerifiedRunInput -Source $sourceReceiptPath -Destination (Join-Path $package.input_dir 'bunch_source_receipt.json')
  $frozenPilotManifest=Copy-VerifiedRunInput -Source $pilotManifest -Destination (Join-Path $package.input_dir 'static_pilot_run_manifest.json')
  $frozenPilotReceipt=Copy-VerifiedRunInput -Source $pilotReceipt -Destination (Join-Path $package.input_dir 'static_pilot_trial_receipt.json')
  $frozenPilotLog=Copy-VerifiedRunInput -Source $pilotLog -Destination (Join-Path $package.input_dir 'static_pilot.log')
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    bunch_source_run_manifest=$frozenSourceManifest
    bunch_source_receipt=$frozenSourceReceipt
    static_pilot_run_manifest=$frozenPilotManifest
    static_pilot_trial_receipt=$frozenPilotReceipt
    static_pilot_log=$frozenPilotLog
  }
  $configuration.parameters=[ordered]@{
    lifecycle_stage='complete_bunch_safe_exit_schedule_freeze'
    guard_us=$GuardUs
    pulse_off_time_us=$PulseOffTimeUs
    pulse_off_time_authority=$(if($null-eq$PulseOffTimeUs){'cohort_last_safe_exit_plus_guard'}else{'caller_common_envelope_verified_against_this_cohort'})
    guard_authority='mandatory_cli_value_recorded_in_run_config_and_schedule'
    solver_execution='none'
  }
  Write-RunJson -Path $runConfig -Value $configuration

  $failureStage='freeze_schedule'
  $schedule=Join-Path $resultDir 'bunch_global_pulse_schedule.json'
  $log=Join-Path $logDir 'freeze_bunch_pulse_schedule.log'
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    $freezeArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule',
      'freeze-schedule','--source-receipt',$frozenSourceReceipt,'--pilot-log',$frozenPilotLog,
      '--pilot-trial-receipt',$frozenPilotReceipt,'--guard-us',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$GuardUs)),'--output',$schedule)
    if($null-ne$PulseOffTimeUs){$freezeArguments+=@('--pulse-off-time-us',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$PulseOffTimeUs)))}
    & $python @freezeArguments 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne 0){throw 'Bunch pulse schedule freeze failed.'}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  $scheduleData=Get-Content -LiteralPath $schedule -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  Write-RunJson -Path $summary -Depth 16 -Value ([ordered]@{
    schema_version=1;role='mrtof_bunch_global_pulse_schedule_run_summary';status='success'
    qualification='complete_static_pilot_cohort_schedule__no_fixed_time_flight'
    schedule=$scheduleData
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11') -Outputs @($summary,$schedule,$startupPath,$terminalPath,$retention,$log)
  $terminalized=$true
  Write-Host "MRTOF_BUNCH_PULSE_SCHEDULE_RUN=PASS RUN_ID=$RunId TIME_US=$($scheduleData.pulse_off_time_us)"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_bunch_global_pulse_schedule_run_summary' -Reason $_.Exception.Message -Software @('Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  try{
    if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_bunch_global_pulse_schedule_run_summary' -Reason 'Bunch pulse schedule freeze stopped before terminal publication.' -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage}
  }finally{
    if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
  }
}
