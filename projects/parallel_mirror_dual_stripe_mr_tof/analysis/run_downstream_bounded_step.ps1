[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$DefinitionRunManifest,
  [Parameter(Mandatory)][string]$CandidateRunManifest,
  [string]$RunId='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$definition=(Resolve-Path -LiteralPath $DefinitionRunManifest).Path
$candidate=(Resolve-Path -LiteralPath $CandidateRunManifest).Path
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__downstream-bounded-step'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'finite_3d_downstream_bounded_step_audit' `
  -Software @('Python 3.11','NumPy') -RetentionContractEnabled -RetentionClass compact
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight'
try{
  $definitionMode=(Get-Content -Raw -LiteralPath $definition|ConvertFrom-Json).mode
  if($definitionMode-notin@('finite_3d_downstream_voltage_definition_audit','finite_3d_downstream_central_difference_audit')){throw "Unsupported definition mode: $definitionMode"}
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $definition --require-status success --require-project $projectId --require-mode $definitionMode
  if($LASTEXITCODE-ne 0){throw 'Definition run manifest failed verification.'}
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $candidate --require-status success --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
  if($LASTEXITCODE-ne 0){throw 'Candidate trial manifest failed verification.'}
  $failureStage='capacity_startup'
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir) -RequiredHeadroomBytes 1048576
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_inputs'
  $frozenDefinition=Copy-VerifiedRunInput -Source $definition -Destination (Join-Path $package.input_dir 'definition_run_manifest.json')
  $frozenCandidate=Copy-VerifiedRunInput -Source $candidate -Destination (Join-Path $package.input_dir 'candidate_run_manifest.json')
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{definition_run_manifest=$frozenDefinition;candidate_run_manifest=$frozenCandidate}
  $configuration.parameters=[ordered]@{lifecycle_stage='single_center_downstream_bounded_step_audit';iteration_execution='none';physical_acceptance='not_defined'}
  Write-RunJson -Path $runConfig -Value $configuration
  $failureStage='bounded_step_audit'
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_bounded_step --definition-manifest $frozenDefinition --candidate-manifest $frozenCandidate --output $summary 2>&1|Tee-Object -FilePath (Join-Path $logDir 'downstream_bounded_step.log');if($LASTEXITCODE-ne 0){throw 'Bounded-step audit failed'}}finally{$env:PYTHONPATH=$saved;Pop-Location}
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('Python 3.11','NumPy') -Outputs @($summary,$startupPath,$terminalPath,$retention,(Join-Path $logDir 'downstream_bounded_step.log'))
  $terminalized=$true;Write-Host "MRTOF_DOWNSTREAM_BOUNDED_STEP_AUDIT=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_downstream_bounded_step_audit' -Reason $_.Exception.Message -Software @('Python 3.11','NumPy') -Status failed -FailureStage $failureStage;$terminalized=$true};throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_downstream_bounded_step_audit' -Reason 'Audit stopped before terminal publication.' -Software @('Python 3.11','NumPy') -Status interrupted -FailureStage $failureStage}
}
