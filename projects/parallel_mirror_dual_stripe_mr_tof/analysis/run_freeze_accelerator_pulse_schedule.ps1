[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CenterRunManifest,
  [string]$RunId='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$centerManifest=(Resolve-Path -LiteralPath $CenterRunManifest).Path
$centerRun=Split-Path -Parent $centerManifest
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-accelerator-pulse-schedule'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'accelerator_global_pulse_schedule_freeze' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight';$capacitySession=$null
try{
  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 1048576 -ProtectedPaths @($package.artifact_run_dir,$centerRun) `
    -Owner "mrtof-freeze-accelerator-pulse-schedule:$RunId"
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession
  $failureStage='verify_source'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $centerManifest `
    --require-status success --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
  if($LASTEXITCODE-ne 0){throw 'Centre trial run manifest failed verification.'}
  $failureStage='freeze_inputs'
  $frozenManifest=Copy-VerifiedRunInput -Source $centerManifest -Destination (Join-Path $package.input_dir 'center_run_manifest.json')
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{center_run_manifest=$frozenManifest}
  $configuration.parameters=[ordered]@{
    lifecycle_stage='single_center_diagnostic_pulse_schedule_freeze'
    bunch_qualification='pending_multi_particle_safe_exit_envelope'
    time_basis='ion_time_of_flight_us_from_common_tob_zero_release'
  }
  Write-RunJson -Path $runConfig -Value $configuration
  $failureStage='freeze_pulse_schedule'
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial `
      freeze-pulse-schedule --center-run $centerRun --output $summary 2>&1|Tee-Object -FilePath (Join-Path $logDir 'freeze_accelerator_pulse_schedule.log')
    if($LASTEXITCODE-ne 0){throw 'Accelerator pulse-schedule freeze failed'}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('Python 3.11') `
    -Outputs @($summary,$startupPath,$terminalPath,$retention,(Join-Path $logDir 'freeze_accelerator_pulse_schedule.log'))
  $terminalized=$true;Write-Host "MRTOF_ACCELERATOR_PULSE_SCHEDULE_FREEZE=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_accelerator_global_pulse_schedule' -Reason $_.Exception.Message -Software @('Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true};throw
}finally{
  try{
    if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_accelerator_global_pulse_schedule' -Reason 'Schedule freeze stopped before terminal publication.' -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage}
  }finally{
    if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
  }
}
