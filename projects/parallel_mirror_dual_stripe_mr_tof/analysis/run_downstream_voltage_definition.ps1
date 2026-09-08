[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$BaselineRunManifest,
  [Parameter(Mandatory)][string]$Stripe1AxisRunManifest,
  [Parameter(Mandatory)][string]$Stripe2AxisRunManifest,
  [Parameter(Mandatory)][string]$Prism1AxisRunManifest,
  [Parameter(Mandatory)][string]$Prism2AxisRunManifest,
  [string]$ContractPath='',
  [string]$RunId='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$contract=if($ContractPath){(Resolve-Path -LiteralPath $ContractPath).Path}else{Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json'}
$manifests=@($BaselineRunManifest,$Stripe1AxisRunManifest,$Stripe2AxisRunManifest,$Prism1AxisRunManifest,$Prism2AxisRunManifest)|ForEach-Object{(Resolve-Path -LiteralPath $_).Path}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__downstream-voltage-definition'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'finite_3d_downstream_voltage_definition_audit' `
  -Software @('Python 3.11','NumPy') -RetentionContractEnabled -RetentionClass compact
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight'
try{
  foreach($manifest in $manifests){
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
    if($LASTEXITCODE-ne 0){throw "Upstream downstream-voltage trial failed verification: $manifest"}
  }
  $failureStage='capacity_startup'
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir) -RequiredHeadroomBytes 2097152
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_inputs'
  $frozenContract=Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $package.input_dir 'simion_candidate_two_zone.json')
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{candidate_contract=$frozenContract;baseline_trial_manifest=$manifests[0];stripe_1_axis_manifest=$manifests[1];stripe_2_axis_manifest=$manifests[2];prism_1_axis_manifest=$manifests[3];prism_2_axis_manifest=$manifests[4]}
  $configuration.parameters=[ordered]@{lifecycle_stage='single_center_downstream_local_definition';unknown_order=@('stripe_1_voltage_v','stripe_2_voltage_v','prism_1_voltage_v','prism_2_voltage_v');solver_execution='none__consume_verified_SIMION_trials';iteration_execution='forbidden'}
  Write-RunJson -Path $runConfig -Value $configuration
  $failureStage='definition_audit'
  $arguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_voltage_definition','--contract',$frozenContract,'--baseline-manifest',$manifests[0])
  foreach($manifest in $manifests[1..4]){$arguments+=@('--axis-manifest',$manifest)}
  $arguments+=@('--output',$summary)
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir 'downstream_voltage_definition.log');if($LASTEXITCODE-ne 0){throw 'Downstream voltage definition audit failed'}}finally{$env:PYTHONPATH=$saved;Pop-Location}
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal'
  $maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('Python 3.11','NumPy') -Outputs @($summary,$startupPath,$terminalPath,$retention,(Join-Path $logDir 'downstream_voltage_definition.log'))
  $terminalized=$true;Write-Host "MRTOF_DOWNSTREAM_VOLTAGE_DEFINITION_AUDIT=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_downstream_voltage_definition_audit' -Reason $_.Exception.Message -Software @('Python 3.11','NumPy') -Status failed -FailureStage $failureStage;$terminalized=$true};throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_finite_3d_downstream_voltage_definition_audit' -Reason 'Audit stopped before terminal publication.' -Software @('Python 3.11','NumPy') -Status interrupted -FailureStage $failureStage}
}
