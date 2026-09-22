[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$SourceRunPath,
  [string]$RunId='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$sourceRun=(Resolve-Path -LiteralPath $SourceRunPath).Path
$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-completed-bunch-flight-recovery'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

function Get-VerifiedSourceOutput {
  param([Parameter(Mandatory)]$Manifest,[Parameter(Mandatory)][string]$Path)
  $resolved=[IO.Path]::GetFullPath($Path)
  $records=@($Manifest.outputs|Where-Object{
    $_.exists-and-not[string]::IsNullOrWhiteSpace([string]$_.path)-and
    [IO.Path]::GetFullPath([string]$_.path)-eq$resolved
  })
  if($records.Count-ne1){throw "Source manifest does not bind exactly one output: $resolved"}
  if((Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash-ne([string]$records[0].sha256).ToUpperInvariant()){
    throw "Source output differs from its manifest: $resolved"
  }
}

$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'completed_bunch_flight_postprocess_recovery' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir;$logDir=$package.log_dir
$terminalized=$false;$failureStage='preflight';$capacitySession=$null
try{
  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 33554432 -ProtectedPaths @($sourceRun) `
    -Owner "mrtof-completed-bunch-flight-recovery:$RunId"
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession

  $failureStage='verify_source'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $sourceManifest `
    --require-status failed --require-project $projectId
  if($LASTEXITCODE-ne0){throw 'Source run manifest failed verification.'}
  $sourceData=Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8|ConvertFrom-Json
  if($sourceData.status-ne'failed'-or$sourceData.mode-ne'finite_3d_two_prism_voltage_trial'){
    throw 'Recovery input must be one failed finite 3D two-prism run.'
  }
  $sourceSummaryPath=Join-Path $sourceRun 'summary.json'
  $sourceSummary=Get-Content -LiteralPath $sourceSummaryPath -Raw -Encoding UTF8|ConvertFrom-Json
  if($sourceSummary.failure_stage-ne'plan_bunch_dispatch'){
    throw 'Recovery is restricted to completed batch flights that failed during dispatch finalization.'
  }
  $batchPlanPath=Join-Path $sourceRun 'results\simion_execution_batch_plan.json'
  $trialReceiptPath=Join-Path $sourceRun 'results\two_prism_trial_materialization.json'
  foreach($path in @($sourceSummaryPath,$batchPlanPath,$trialReceiptPath)){
    Get-VerifiedSourceOutput -Manifest $sourceData -Path $path
  }
  $batchPlan=Get-Content -LiteralPath $batchPlanPath -Raw -Encoding UTF8|ConvertFrom-Json
  if($batchPlan.coverage-ne'complete_population'-or[int]$batchPlan.particle_count-lt2){
    throw 'Source batch plan is not one complete N>1 population.'
  }
  $sourceBatchLogs=@()
  foreach($batch in @($batchPlan.batches)){
    $path=Join-Path $sourceRun ('logs\native_two_prism_flight__batch{0:D2}.log'-f[int]$batch.index)
    Get-VerifiedSourceOutput -Manifest $sourceData -Path $path
    $sourceBatchLogs+=,$path
  }

  $failureStage='freeze_inputs'
  $frozenManifest=Copy-VerifiedRunInput -Source $sourceManifest -Destination (Join-Path $package.input_dir 'source_failed_run_manifest.json')
  $frozenSummary=Copy-VerifiedRunInput -Source $sourceSummaryPath -Destination (Join-Path $package.input_dir 'source_failed_summary.json')
  $frozenPlan=Copy-VerifiedRunInput -Source $batchPlanPath -Destination (Join-Path $package.input_dir 'simion_execution_batch_plan.json')
  $frozenTrial=Copy-VerifiedRunInput -Source $trialReceiptPath -Destination (Join-Path $package.input_dir 'two_prism_trial_materialization.json')
  $frozenLogs=@()
  foreach($path in $sourceBatchLogs){
    $frozenLogs+=, (Copy-VerifiedRunInput -Source $path -Destination (Join-Path $package.input_dir (Split-Path $path -Leaf)))
  }
  $configuration=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    source_failed_run_manifest=$frozenManifest;source_failed_summary=$frozenSummary
    simion_execution_batch_plan=$frozenPlan;two_prism_trial_materialization=$frozenTrial
    batch_logs=$frozenLogs
  }
  $configuration.parameters=[ordered]@{
    lifecycle_stage='postprocess_only__no_solver_execution'
    particle_count=[int]$batchPlan.particle_count;batch_count=[int]$batchPlan.batch_count
    source_failure_stage=[string]$sourceSummary.failure_stage
  }
  Write-RunJson -Path $runConfig -Value $configuration

  $failureStage='merge_batches'
  $mergedLog=Join-Path $logDir 'native_two_prism_flight.log'
  $mergeReceipt=Join-Path $resultDir 'batch_log_merge_receipt.json'
  $mergeArgs=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','merge',
    '--particle-count',([string]$batchPlan.particle_count),'--particle-id-min','1',
    '--output',$mergedLog,'--receipt',$mergeReceipt)
  for($index=0;$index-lt@($batchPlan.batches).Count;$index++){
    $batch=@($batchPlan.batches)[$index]
    $mergeArgs+=@('--batch-log',$frozenLogs[$index],([string]$batch.simion_particle_id_offset),([string]$batch.count))
  }
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @mergeArgs;if($LASTEXITCODE-ne0){throw 'Batch log merge failed.'}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}

  $failureStage='analyze_trial'
  $observation=Join-Path $resultDir 'two_prism_trial_observation.json'
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial analyze `
      --log $mergedLog --trial-receipt $frozenTrial --output $observation
    if($LASTEXITCODE-ne0){throw 'Recovered trial analysis failed.'}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  $observed=Get-Content -LiteralPath $observation -Raw -Encoding UTF8|ConvertFrom-Json
  $cohort=$observed.cohort_analysis
  Write-RunJson -Path $summary -Depth 10 -Value ([ordered]@{
    schema_version=1;role='mrtof_completed_bunch_flight_recovery_summary';status='success'
    qualification='candidate_postprocess_recovery__source_solver_batches_completed__no_solver_rerun'
    source_run_id=[string]$sourceData.run_id
    metrics=[ordered]@{
      particle_count=[int]$cohort.expected_particle_count;event_integrity_passed=[bool]$cohort.event_integrity_passed
      detector_hit_count=[int]$cohort.detector_hit_count;detection_rate=[double]$cohort.detection_rate
      electrode_collision_count=[int]$cohort.electrode_collision_count
      target_k=[double]$cohort.target_k;target_k_count=[int]$cohort.target_k_count
      target_k_fraction=[double]$cohort.target_k_fraction;overtone_histogram=$cohort.overtone_histogram
      detector_tof_median_us=[double]$cohort.detector_tof_median_us
      detector_tof_fwhm_us=[double]$cohort.detector_tof_fwhm_us
      mass_resolution_t_over_2fwhm=[double]$cohort.mass_resolution_t_over_2fwhm
      accelerator_safe_exit_fraction=[double]$cohort.accelerator_safe_exit_fraction
    }
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11') `
    -Outputs @($summary,$observation,$mergeReceipt,$mergedLog,$startupPath,$terminalPath,$retention)
  $terminalized=$true
  Write-Host "MRTOF_COMPLETED_BUNCH_FLIGHT_RECOVERY=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_completed_bunch_flight_recovery_summary' -Reason $_.Exception.Message -Software @('Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_completed_bunch_flight_recovery_summary' -Reason 'Recovery stopped before terminal publication.' -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage}
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}
