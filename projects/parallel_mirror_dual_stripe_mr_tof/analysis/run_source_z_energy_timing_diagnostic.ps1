[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$FlightRunPath,
  [string]$RunId='',
  [string]$PythonExe='',
  [Nullable[long]]$CapacityKnownMeasuredBytes=$null,
  [Nullable[double]]$CapacityTargetGiB=$null,
  [Nullable[double]]$CapacityMinimumFreeGiB=$null
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$sourceRun=(Resolve-Path -LiteralPath $FlightRunPath).Path
$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
if(-not(Test-Path -LiteralPath $sourceManifest -PathType Leaf)){throw 'FlightRunPath has no run_manifest.json.'}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-source-z-energy-timing'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'source_z_energy_timing_diagnostic' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight'
try{
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $sourceManifest `
    --require-status success --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
  if($LASTEXITCODE-ne 0){throw 'Flight source manifest failed full verification.'}
  $sourceObservation=Get-Content -LiteralPath (Join-Path $sourceRun 'results\two_prism_trial_observation.json') `
    -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $particleCount=[int]$sourceObservation.cohort_analysis.expected_particle_count
  if($particleCount-le 1){throw 'Flight source must contain N>1 particles.'}

  $failureStage='capacity_startup'
  $capacityStartupParameters=@{
    Python=$python
    RepoRoot=$repoRoot
    ArtifactRoot=(Join-Path $workspaceRoot 'artifacts')
    ProtectedPaths=@($package.artifact_run_dir,$sourceRun)
    RequiredHeadroomBytes=[int64]4194304
  }
  if($null-ne$CapacityKnownMeasuredBytes){
    $capacityStartupParameters.KnownMeasuredBytes=[int64]$CapacityKnownMeasuredBytes
    $capacityStartupParameters.MaximumNewArtifactBytes=[int64]4194304
  }
  if($null-ne$CapacityTargetGiB){$capacityStartupParameters.TargetGiB=[double]$CapacityTargetGiB}
  if($null-ne$CapacityMinimumFreeGiB){$capacityStartupParameters.MinimumFreeGiB=[double]$CapacityMinimumFreeGiB}
  $startup=Invoke-ArtifactCapacityGate @capacityStartupParameters
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage='freeze_inputs'
  $frozenManifest=Copy-VerifiedRunInput -Source $sourceManifest `
    -Destination (Join-Path $package.input_dir 'flight_run_manifest.json')
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{flight_run_manifest=$frozenManifest}
  $configuration.parameters=[ordered]@{
    lifecycle_stage='frozen_source_z_energy_timing_diagnostic'
    source_run_directory=$sourceRun
    particle_count=$particleCount
    solver_execution='none'
    safe_exit_scope='all_expected_particles'
    downstream_scope='all_detector_hits_with_complete_event_chain'
    source_or_peak_filtering='none'
    statistical_scope='descriptive_transfer_diagnostic_only__not_causal'
    acceptance_threshold=$null
    capacity_target_gib=if($null-ne$CapacityTargetGiB){[double]$CapacityTargetGiB}else{$null}
    capacity_minimum_free_gib=if($null-ne$CapacityMinimumFreeGiB){[double]$CapacityMinimumFreeGiB}else{$null}
  }
  Write-RunJson -Path $runConfig -Depth 12 -Value $configuration

  $failureStage='analyze'
  $result=Join-Path $resultDir 'source_z_energy_timing_diagnostic.json'
  $log=Join-Path $logDir 'source_z_energy_timing_diagnostic.log'
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic `
      --run-dir $sourceRun --output $result 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne 0){throw 'Source-z energy/timing analysis failed.'}
    if(-not(Test-Path -LiteralPath $log -PathType Leaf)){
      [IO.File]::WriteAllText($log,'',[Text.UTF8Encoding]::new($false))
    }
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  $data=Get-Content -LiteralPath $result -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($data.status-ne'candidate_diagnostic'-or$data.cohort.particle_count-ne$particleCount){
    throw 'Source-z energy/timing result is incomplete.'
  }
  Write-RunJson -Path $summary -Depth 30 -Value ([ordered]@{
    schema_version=1
    role='mrtof_source_z_energy_timing_diagnostic_run_summary'
    status='success'
    qualification=[string]$data.qualification
    acceptance_threshold=$null
    cohort=$data.cohort
    safe_exit=$data.safe_exit
    stages=$data.stages
    derived_transfer=$data.derived_transfer
    terminal_plane_diagnostic=$data.terminal_plane_diagnostic
    state_dispersion=$data.state_dispersion
    event_coverage=$data.event_coverage
    interpretation=[string]$data.interpretation
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $capacityTerminalParameters=@{
    Python=$python
    RepoRoot=$repoRoot
    ArtifactRoot=(Join-Path $workspaceRoot 'artifacts')
    ProtectedPaths=@($package.artifact_run_dir,$sourceRun)
    KnownMeasuredBytes=[int64]$startup.measured_after_bytes
    MaximumNewArtifactBytes=$maximum
  }
  if($null-ne$CapacityTargetGiB){$capacityTerminalParameters.TargetGiB=[double]$CapacityTargetGiB}
  if($null-ne$CapacityMinimumFreeGiB){$capacityTerminalParameters.MinimumFreeGiB=[double]$CapacityMinimumFreeGiB}
  $terminal=Invoke-ArtifactCapacityGate @capacityTerminalParameters
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $failureStage='publish_success_manifest'
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11') -Outputs @($summary,$result,$startupPath,$terminalPath,$retention,$log)
  $terminalized=$true
  Write-Host "MRTOF_SOURCE_Z_ENERGY_TIMING_DIAGNOSTIC=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_source_z_energy_timing_diagnostic_run_summary' -Reason $_.Exception.Message `
      -Software @('Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_source_z_energy_timing_diagnostic_run_summary' `
      -Reason 'Source-z energy/timing analysis stopped before terminal publication.' `
      -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage
  }
}
