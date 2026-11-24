[CmdletBinding()]
param(
  [Parameter(Mandatory)][ValidateCount(3,3)][string[]]$RunManifestPaths,
  [string]$RunId='',
  [Parameter(Mandatory)][string]$WorkspaceRoot,
  [Parameter(Mandatory)][string]$ArtifactRoot,
  [Parameter(Mandatory)][string]$PythonExe
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$workspaceRoot=(Resolve-Path -LiteralPath $WorkspaceRoot).Path
$repoRoot=$workspaceRoot
$artifactRoot=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRoot)
$python=[IO.Path]::GetFullPath($PythonExe)
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python 3.11 environment is missing: $python"}
$packageRootText=& $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if($LASTEXITCODE-ne0){throw 'Installed msplatform package is unavailable.'}
$packageRoot=(Resolve-Path -LiteralPath $packageRootText).Path
$manifests=@($RunManifestPaths|ForEach-Object{(Resolve-Path -LiteralPath $_).Path})
$sourceRuns=@($manifests|ForEach-Object{Split-Path -Parent $_})
if(($sourceRuns|Select-Object -Unique).Count-ne 3){throw 'Three distinct source runs are required.'}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-single-center-timestep-convergence'
}

. (Join-Path $packageRoot 'execution/resources/run_artifact_support.ps1')

$artifactProjectRoot=Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind component -OwnerId $projectId -Python $python
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'single_center_timestep_convergence' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight';$capacitySession=$null
try{
  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot ($artifactRoot) -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 2097152 -ProtectedPaths (@($package.artifact_run_dir)+$sourceRuns) `
    -Owner "mrtof-single-center-timestep-convergence:$RunId"
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession
  $failureStage='verify_sources'
  foreach($manifest in $manifests){
    & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' $manifest `
      --require-status success --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
    if($LASTEXITCODE-ne 0){throw "Source flight manifest failed verification: $manifest"}
  }
  $failureStage='freeze_inputs'
  $frozen=@()
  for($index=0;$index-lt 3;$index++){
    $frozen+=Copy-VerifiedRunInput -Source $manifests[$index] `
      -Destination (Join-Path $package.input_dir ('source_run_manifest_{0}.json'-f($index+1)))
  }
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{source_run_manifests=$frozen}
  $configuration.parameters=[ordered]@{
    lifecycle_stage='three_level_single_center_timestep_comparison'
    source_run_directories=$sourceRuns
    acceptance_threshold=$null
    solver_execution='none'
  }
  Write-RunJson -Path $runConfig -Depth 12 -Value $configuration

  $failureStage='analyze'
  $result=Join-Path $resultDir 'single_center_timestep_convergence.json'
  $log=Join-Path $logDir 'single_center_timestep_convergence.log'
  $arguments=@('-m','msplatform.workflows.mr_design.single_center_timestep_convergence')
  foreach($run in $sourceRuns){$arguments+=@('--run',$run)}
  $arguments+=@('--output',$result)
  Push-Location -LiteralPath $workspaceRoot
  try{
    & $python -I -B @arguments 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne 0){throw 'Single-centre time-step convergence analysis failed.'}
  }finally{Pop-Location}
  $data=Get-Content -LiteralPath $result -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  Write-RunJson -Path $summary -Depth 16 -Value ([ordered]@{
    schema_version=1
    role='mrtof_single_center_timestep_convergence_run_summary'
    status='success'
    qualification=[string]$data.qualification
    maximum_step_us=@($data.levels|ForEach-Object{[double]$_.maximum_step_us})
    detector_tof_us=@($data.levels|ForEach-Object{[double]$_.events.detector.t_us})
    adjacent_detector_absolute_differences=@($data.adjacent_differences|ForEach-Object{$_.events.detector.absolute_difference})
    acceptance_threshold=$null
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11') -Outputs @($summary,$result,$startupPath,$terminalPath,$retention,$log)
  $terminalized=$true
  Write-Host "MRTOF_SINGLE_CENTER_TIMESTEP_RUN=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_single_center_timestep_convergence_run_summary' -Reason $_.Exception.Message `
      -Software @('Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  try{
    if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){
      Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
        -SummaryRole 'mrtof_single_center_timestep_convergence_run_summary' `
        -Reason 'Time-step convergence analysis stopped before terminal publication.' `
        -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage
    }
  }finally{
    if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
  }
}
