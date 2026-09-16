[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$R27RunPath,
  [string]$RunId='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$sourceRun=(Resolve-Path -LiteralPath $R27RunPath).Path
$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
if(-not(Test-Path -LiteralPath $sourceManifest -PathType Leaf)){throw 'R27RunPath has no run_manifest.json.'}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-r27-source-return-correlation'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'r27_source_return_correlation' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight'
try{
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $sourceManifest `
    --require-status success --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
  if($LASTEXITCODE-ne 0){throw 'R27 source manifest failed full verification.'}

  $failureStage='capacity_startup'
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -ProtectedPaths @($package.artifact_run_dir,$sourceRun) -RequiredHeadroomBytes 2097152
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage='freeze_inputs'
  $frozenManifest=Copy-VerifiedRunInput -Source $sourceManifest `
    -Destination (Join-Path $package.input_dir 'r27_run_manifest.json')
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{r27_run_manifest=$frozenManifest}
  $configuration.parameters=[ordered]@{
    lifecycle_stage='frozen_r27_source_return_terminal_association'
    source_run_directory=$sourceRun
    particle_count=100
    solver_execution='none'
    statistical_scope='descriptive_association_only__not_causal'
    acceptance_threshold=$null
    source_filtering='forbidden'
  }
  Write-RunJson -Path $runConfig -Depth 12 -Value $configuration

  $failureStage='analyze'
  $result=Join-Path $resultDir 'r27_source_return_correlation.json'
  $log=Join-Path $logDir 'r27_source_return_correlation.log'
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.r27_source_return_correlation `
      --run-dir $sourceRun --output $result 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne 0){throw 'R27 source-return correlation analysis failed.'}
    if(-not(Test-Path -LiteralPath $log -PathType Leaf)){
      [IO.File]::WriteAllText($log,'',[Text.UTF8Encoding]::new($false))
    }
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  $data=Get-Content -LiteralPath $result -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($data.status-ne'candidate_diagnostic'-or$data.cohort.particle_count-ne 100){
    throw 'R27 source-return correlation result is incomplete.'
  }
  Write-RunJson -Path $summary -Depth 24 -Value ([ordered]@{
    schema_version=1
    role='mrtof_r27_source_return_correlation_run_summary'
    status='success'
    qualification=[string]$data.qualification
    acceptance_threshold=$null
    cohort=$data.cohort
    associations=$data.associations
    interpretation=[string]$data.interpretation
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -ProtectedPaths @($package.artifact_run_dir,$sourceRun) `
    -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $failureStage='publish_success_manifest'
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11') -Outputs @($summary,$result,$startupPath,$terminalPath,$retention,$log)
  $terminalized=$true
  Write-Host "MRTOF_R27_SOURCE_RETURN_CORRELATION=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_r27_source_return_correlation_run_summary' -Reason $_.Exception.Message `
      -Software @('Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_r27_source_return_correlation_run_summary' `
      -Reason 'R27 source-return correlation stopped before terminal publication.' `
      -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage
  }
}
