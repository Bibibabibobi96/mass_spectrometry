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
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')

function Assert-CompletedBunchRecovery {
  param($SourceSummary,$BatchPlan,$Observation)
  if($SourceSummary.failure_stage-notin@('plan_bunch_dispatch','analyze_trial')){
    throw 'Recovery requires a completed-flight dispatch or post-analysis failure.'
  }
  if($BatchPlan.coverage-ne'complete_population'-or[int]$BatchPlan.particle_count-lt2){
    throw 'Source batch plan is not one complete N>1 population.'
  }
  if($SourceSummary.failure_stage-eq'analyze_trial'-and(
    $null-eq$Observation-or-not$Observation.cohort_analysis.event_integrity_passed-or
    [int]$Observation.cohort_analysis.expected_particle_count-ne[int]$BatchPlan.particle_count)){
    throw 'Post-analysis recovery requires complete observed event integrity.'
  }
}

function Restore-CompletedBunchGui {
  param([string]$SourceDirectory,[string]$DestinationDirectory,[string]$ResultDirectory,
    [string]$LogDirectory,[string]$RecoveryRunId,$Binding)
  # Reuse the original official Workbench builder and small companions only.
  # This operation does not run Fly, Refine, Fast Adjust, or save any PA.
  $sourceGui=Join-Path $SourceDirectory 'simion\gui_workbench'
  New-Item -ItemType Directory -Path $DestinationDirectory|Out-Null
  foreach($item in @(Get-ChildItem -LiteralPath $sourceGui -File)){
    if($item.Extension-in@('.iob','.lua','.fly2')){
      Copy-VerifiedRunInput -Source $item.FullName -Destination (Join-Path $DestinationDirectory $item.Name)|Out-Null
    }
  }
  $seed=Join-Path $DestinationDirectory '4_instance_seed.iob'
  $placeholder=Join-Path $DestinationDirectory 'iob_seed_placeholder_01.pa0'
  Copy-Item -LiteralPath (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_01.pa0') -Destination $placeholder
  foreach($index in 2..4){$null=New-Item -ItemType HardLink -Path (Join-Path $DestinationDirectory ('iob_seed_placeholder_{0:D2}.pa0'-f$index)) -Target $placeholder}
  $iob=Join-Path $DestinationDirectory 'mrtof_three_component_candidate.iob'
  $program=[IO.Path]::ChangeExtension($iob,'.lua')
  $builder=Join-Path $SourceDirectory 'simion\build_native_corridor_iob.lua'
  $arguments=@('--nogui','--noprompt','lua',$builder,'--',$seed)+@($Binding.instances|ForEach-Object{[string]$_.pa_path})+
    @($iob,$program,[IO.Path]::ChangeExtension($iob,'.fly2'),$iob.Replace('.iob','.operating_point.lua'),
      $iob.Replace('.iob','.voltage_map.lua'),$iob.Replace('.iob','.priority.lua'))
  foreach($instance in @($Binding.instances)){foreach($value in @($instance.origin_mm)){$arguments+=([double]$value).ToString('R',[Globalization.CultureInfo]::InvariantCulture)}}
  $lease=Enter-HostExecutionLease -Role SIMION -RunId $RecoveryRunId -Stage 'rebind_retained_gui_iob'
  $process=$null;$outcome='failed'
  try{
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName=Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'
    $start.WorkingDirectory=$DestinationDirectory;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
    $start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
    foreach($argument in $arguments){$start.ArgumentList.Add($argument)}
    $process=[Diagnostics.Process]::Start($start)
    $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
    Write-Host "SIMION_STAGE=START STAGE=rebind_retained_gui_iob PID=$($process.Id)"
    if(-not$process.HasExited){Register-HostResourceProcess -Lease $lease -ProcessId $process.Id|Out-Null}
    $process.WaitForExit()
    $text=$stdout.GetAwaiter().GetResult()+$stderr.GetAwaiter().GetResult()
    [IO.File]::WriteAllText((Join-Path $LogDirectory 'rebind_retained_gui_iob.log'),$text,[Text.UTF8Encoding]::new($false))
    if($process.ExitCode-ne0-or$text-notmatch'MRTOF_NATIVE_CORRIDOR_IOB_BUILD=PASS'){throw 'Recovered GUI builder did not complete its priority/save checks.'}
    $null=Remove-IobSeedPlaceholderCompanions -Directory $DestinationDirectory -Count 4
    $files=@(Get-ChildItem -LiteralPath $DestinationDirectory -File|ForEach-Object{
      [ordered]@{name=$_.Name;path=$_.FullName;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
    })
    $dependencies=@($Binding.instances)+@($Binding.records.scalar_pa)
    if($Binding.records.PSObject.Properties['surface']){$dependencies+=@($Binding.records.surface)}
    foreach($window in @($Binding.refinement_windows)){$dependencies+=@($window.records.scalar_pa);if($window.records.PSObject.Properties['surface']){$dependencies+=@($window.records.surface)}}
    Write-RunJson -Path (Join-Path $ResultDirectory 'gui_workbench_receipt.json') -Depth 30 -Value ([ordered]@{
      schema_version=1;role='simion_gui_review_workbench';status='success';qualification='candidate_postprocess_recovery__no_solver_rerun'
      directory=$DestinationDirectory;iob_path=$iob;iob_sha256=(Get-FileHash -LiteralPath $iob -Algorithm SHA256).Hash
      source_accelerator_pa=[string]$Binding.instances[2].pa_path;source_detector_pa=[string]$Binding.instances[3].pa_path
      files=$files;pa_dependencies=$dependencies;external_field_queries_equivalent=$false
      external_field_limitation='Fly callbacks consume the retained static binding; ordinary Workbench field queries show collision arrays.'
    })
    $outcome='success'
  }finally{
    if($null-ne$process){$process.WaitForExit();$process.Dispose()}
    Exit-HostExecutionLease -Lease $lease -Outcome $outcome -RunId $RecoveryRunId
  }
}

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


function Copy-PreparedRecoveryRecord {
  param($Record,[string]$Destination)
  $path=[string]$Record.path
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)-or
     (Get-Item -LiteralPath $path).Length-ne[int64]$Record.bytes-or
     (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ne[string]$Record.sha256){
    throw "Prepared recovery record changed: $path"
  }
  $frozen=Copy-VerifiedRunInput -Source $path -Destination $Destination
  return [ordered]@{path=$frozen;exists=$true;bytes=[int64]$Record.bytes;sha256=[string]$Record.sha256}
}

function Assert-PreparedJointRecovery {
  param($SourceSummary,$Prepared,$Plan,$Merge)
  if($SourceSummary.status-ne'failed'-or$SourceSummary.failure_stage-ne'automatic_joint_diagnostics'){
    throw 'Prepared joint recovery requires a completed-flight automatic diagnostic failure.'
  }
  if($Prepared.role-ne'mrtof_prepared_joint_trial'-or$Plan.coverage-ne'complete_population'-or
     [int]$Plan.particle_count-ne[int]$Prepared.launched_particle_count-or
     $Merge.role-ne'mrtof_measured_batch_log_merge'-or$Merge.status-ne'success'-or
     [int]$Merge.particle_count-ne[int]$Prepared.launched_particle_count-or
     [int]$Merge.mother_particle_count-ne[int]$Prepared.mother_particle_count-or
     @($Merge.original_particle_ids).Count-ne@($Prepared.expected_particle_ids).Count){
    throw 'Prepared joint source, complete batch plan and merge do not close.'
  }
  for($i=0;$i-lt@($Prepared.expected_particle_ids).Count;$i++){
    if([int]$Merge.original_particle_ids[$i]-ne[int]$Prepared.expected_particle_ids[$i]){throw 'Prepared joint original IDs differ.'}
  }
}

function Invoke-PreparedJointRecovery {
  # Same public recovery workflow; only analysis/diagnostics run. No OA GUI path.
  $sourceSummaryPath=Join-Path $sourceRun 'summary.json'
  $preparedPath=Join-Path $sourceRun 'results/prepared_joint_trial.json'
  $prepared=Get-Content -LiteralPath $preparedPath -Raw|ConvertFrom-Json -AsHashtable
  $policy=$prepared.trajectory_recording
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts/projects/$projectId") `
    -RunId $RunId -Project $projectId -Mode completed_bunch_flight_postprocess_recovery -Software @('Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $policy.reason -CapacityLedgerLifecycleEnabled
  $capacity=$null;$lease=$null;$published=$false;$stage='verify_completed_joint_source'
  try {
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
      -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
      -CommittedNewBytes ([int64]$policy.output_budget_bytes) -ProtectedPaths @($sourceRun,$package.artifact_run_dir) -Owner "mrtof-joint-postprocess:$RunId"
    $lease=Enter-HostExecutionLease -Role GATE
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -m common.contracts.verify_run_manifest $sourceManifest --require-status failed --require-project $projectId
      if($LASTEXITCODE-ne0){throw 'Completed joint source manifest failed full verification.'}
    }
    $manifest=Get-Content -LiteralPath $sourceManifest -Raw|ConvertFrom-Json
    $planPath=Join-Path $sourceRun 'results/simion_execution_batch_plan.json'
    $mergePath=Join-Path $sourceRun 'results/batch_log_merge_receipt.json'
    foreach($path in @($sourceSummaryPath,$preparedPath,$planPath,$mergePath)){Get-VerifiedSourceOutput $manifest $path}
    $sourceSummary=Get-Content -LiteralPath $sourceSummaryPath -Raw|ConvertFrom-Json
    $plan=Get-Content -LiteralPath $planPath -Raw|ConvertFrom-Json
    $merge=Get-Content -LiteralPath $mergePath -Raw|ConvertFrom-Json
    Assert-PreparedJointRecovery $sourceSummary ([pscustomobject]$prepared) $plan $merge
    $inputs=[string]$package.input_dir;$results=[string]$package.result_dir;$logs=[string]$package.log_dir
    Copy-VerifiedRunInput -Source $sourceManifest -Destination (Join-Path $inputs 'source_failed_run_manifest.json')|Out-Null
    Copy-VerifiedRunInput -Source $sourceSummaryPath -Destination (Join-Path $inputs 'source_failed_summary.json')|Out-Null
    Copy-VerifiedRunInput -Source $preparedPath -Destination (Join-Path $inputs 'source_prepared_joint_trial.json')|Out-Null
    Copy-VerifiedRunInput -Source $planPath -Destination (Join-Path $inputs 'simion_execution_batch_plan.json')|Out-Null
    Copy-VerifiedRunInput -Source $mergePath -Destination (Join-Path $inputs 'source_batch_log_merge_receipt.json')|Out-Null
    $sourceCopy=Join-Path $inputs 'measured_source';New-Item -ItemType Directory -Path $sourceCopy|Out-Null
    foreach($file in Get-ChildItem -LiteralPath ([string]$prepared.measured_source_directory) -File){
      Get-VerifiedSourceOutput $manifest $file.FullName
      Copy-VerifiedRunInput -Source $file.FullName -Destination (Join-Path $sourceCopy $file.Name)|Out-Null
    }
    $originalSourceReceipt=Copy-PreparedRecoveryRecord $prepared.source_receipt (Join-Path $inputs 'source_measured_source_receipt.json')
    $sourceReceipt=Get-Content -LiteralPath ([string]$originalSourceReceipt.path) -Raw|ConvertFrom-Json -AsHashtable
    $provenance=Join-Path $inputs 'source_provenance';New-Item -ItemType Directory -Path $provenance|Out-Null
    foreach($key in @($sourceReceipt.inputs.Keys)){
      $record=$sourceReceipt.inputs[$key]
      $sourceReceipt.inputs[$key]=Copy-PreparedRecoveryRecord $record (Join-Path $provenance ($key+[IO.Path]::GetExtension([string]$record.path)))
    }
    $sourceReceipt.inputs.recovery_source_receipt=$originalSourceReceipt
    foreach($key in @($sourceReceipt.outputs.Keys)){
      $record=$sourceReceipt.outputs[$key]
      $canonical=Join-Path $sourceCopy ([IO.Path]::GetFileName([string]$record.path))
      if(-not(Test-Path -LiteralPath $canonical -PathType Leaf)-or
         (Get-Item $canonical).Length-ne[int64]$record.bytes-or
         (Get-FileHash $canonical).Hash-ne[string]$record.sha256){throw 'Recovery canonical source bytes changed.'}
      $sourceReceipt.outputs[$key]=[ordered]@{path=$canonical;exists=$true;bytes=[int64]$record.bytes;sha256=[string]$record.sha256}
    }
    $rewrittenSource=Join-Path $sourceCopy 'source_receipt.json'
    Write-RunJson -Path $rewrittenSource -Depth 60 -Value $sourceReceipt
    $prepared.measured_source_directory=$sourceCopy
    $prepared.source_receipt=[ordered]@{path=$rewrittenSource;exists=$true;bytes=(Get-Item $rewrittenSource).Length;sha256=(Get-FileHash $rewrittenSource).Hash}
    $authorities=Join-Path $inputs 'authorities';New-Item -ItemType Directory -Path $authorities|Out-Null
    foreach($key in @('trajectory_contract','operating_point','reference_materialization','field_binding','parent_preparation','flight_program','field_consumer_adapter')){
      if($prepared.Contains($key)){
        $record=$prepared[$key]
        $prepared[$key]=Copy-PreparedRecoveryRecord $record (Join-Path $authorities ($key+[IO.Path]::GetExtension([string]$record.path)))
      }
    }
    if($null-eq$prepared.trajectory_equivalence_reference){throw 'Recovery requires the declared full-field trajectory reference.'}
    foreach($key in @('reference_log','reference_manifest')){
      $record=$prepared.trajectory_equivalence_reference[$key]
      $prepared.trajectory_equivalence_reference[$key]=Copy-PreparedRecoveryRecord $record (Join-Path $authorities ($key+[IO.Path]::GetExtension([string]$record.path)))
    }
    $completed=@();$mergeArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','merge-joint')
    $batchRoot=Join-Path $inputs 'completed_batches';New-Item -ItemType Directory -Path $batchRoot|Out-Null
    foreach($batch in @($plan.batches)){
      $label='batch_{0:D3}'-f[int]$batch.index
      $directory=Join-Path $batchRoot $label;New-Item -ItemType Directory -Path $directory|Out-Null
      $sourceBatch=Join-Path $sourceRun ('results/batches/'+$label)
      $batchReceipt=Join-Path $sourceBatch 'batch_receipt.json';$fly2=Join-Path $sourceBatch 'joint.fly2'
      $raw=Join-Path $sourceRun ('logs/joint_flight_batch_{0:D3}.log'-f[int]$batch.index)
      foreach($path in @($batchReceipt,$fly2,$raw)){Get-VerifiedSourceOutput $manifest $path}
      $records=@{}
      foreach($item in @(@('batch_receipt',$batchReceipt),@('fly2',$fly2),@('log',$raw))){
        $record=@($manifest.outputs|Where-Object{[IO.Path]::GetFullPath([string]$_.path)-eq[IO.Path]::GetFullPath([string]$item[1])})[0]
        $records[$item[0]]=Copy-PreparedRecoveryRecord $record (Join-Path $directory ([IO.Path]::GetFileName($item[1])))
      }
      $completed+=,$records
      $mergeArguments+=@('--batch-log',[string]$records.log.path,[string]$records.batch_receipt.path)
    }
    $prepared.completed_source_batches=$completed
    $prepared.source_failed_manifest=[ordered]@{path=(Join-Path $inputs 'source_failed_run_manifest.json');sha256=(Get-FileHash $sourceManifest).Hash;bytes=(Get-Item $sourceManifest).Length;exists=$true}
    $recoveryPreparation=Join-Path $results 'prepared_joint_trial.json'
    Write-RunJson -Path $recoveryPreparation -Depth 60 -Value $prepared
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs=[ordered]@{prepared_joint_trial=$recoveryPreparation}
    $index=0;foreach($file in Get-ChildItem -LiteralPath $inputs -Recurse -File|Sort-Object FullName){$index++;$configuration.inputs[('frozen_{0:D3}'-f$index)]=$file.FullName}
    $configuration.parameters=[ordered]@{source_run=$sourceRun;solver_execution='none';launched_particle_count=$prepared.launched_particle_count;mother_particle_count=$prepared.mother_particle_count;source_failure_stage=$sourceSummary.failure_stage}
    Write-RunJson -Path $package.run_config -Depth 60 -Value $configuration
    $stage='verify_completed_batch_merge'
    $merged=Join-Path $logs 'native_two_prism_flight.log'
    $mergeArguments+=@('--preparation',$recoveryPreparation,'--output',$merged,'--receipt',(Join-Path $results 'batch_log_merge_receipt.json'))
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python @mergeArguments
      if($LASTEXITCODE-ne0){throw 'Recovered measured batch closure failed.'}
    }
    if((Get-FileHash $merged).Hash-ne[string]$merge.merged_log.sha256){throw 'Reassembled raw joint log differs from the sealed complete source.'}
    $stage='automatic_joint_diagnostics'
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight analyze-joint --preparation $recoveryPreparation --log $merged --output (Join-Path $results 'diagnostics')
      if($LASTEXITCODE-ne0){throw 'Recovered measured joint diagnostics failed.'}
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight compare-joint --preparation $recoveryPreparation --log $merged --output (Join-Path $results 'trajectory_equivalence_receipt.json')
      if($LASTEXITCODE-ne0){throw 'Recovered trajectory equivalence failed.'}
    }
    Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
      schema_version=1;role='mrtof_completed_bunch_flight_recovery_summary';status='success';source_run=$sourceRun
      launched_particle_count=$prepared.launched_particle_count;mother_particle_count=$prepared.mother_particle_count
      qualification='completed_measured_joint_postprocess_only';solver_rerun=$false;gui_executed=$false
      diagnostics=(Join-Path $results 'diagnostics/diagnostics_receipt.json');trajectory_equivalence=(Join-Path $results 'trajectory_equivalence_receipt.json')
    })
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
    $outputs=@(Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Where-Object{$_.Name-notin@('run_config.json','run_manifest.json')}|ForEach-Object{$_.FullName})
    Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('Python 3.11') -Outputs $outputs
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -m common.contracts.verify_run_manifest (Join-Path $package.artifact_run_dir 'run_manifest.json') --require-status success
      if($LASTEXITCODE-ne0){throw 'Recovered joint manifest verification failed.'}
    }
    $published=$true
    $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity;$capacity=$null
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root (Join-Path $workspaceRoot 'artifacts') --run-config $package.run_config --owner $projectId --confirm-writing-stopped --retention-reason $policy.reason
      if($LASTEXITCODE-ne0){throw 'Recovered joint stopped-payload seal failed; verified scientific manifest retained.'}
    }
    Write-Host "MRTOF_COMPLETED_JOINT_POSTPROCESS_RECOVERY=PASS RUN_ID=$RunId SOLVER_RERUN=False GUI=False"
  }catch{
    if(-not$published){
      Write-RunJson -Path $package.summary -Value @{schema_version=1;role='mrtof_completed_bunch_flight_recovery_summary';status='failed';failure_stage=$stage;reason=$_.Exception.Message;solver_rerun=$false;gui_executed=$false}
      $retained=Join-Path $package.artifact_run_dir 'retention_actions.json'
      if(-not(Test-Path -LiteralPath $retained)){Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config|Out-Null}
      $outputs=@(Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Where-Object{$_.Name-notin@('run_config.json','run_manifest.json')}|ForEach-Object{$_.FullName})
      Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status failed -Software @('Python 3.11') -Outputs $outputs
      Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
        & $python -m common.contracts.verify_run_manifest (Join-Path $package.artifact_run_dir 'run_manifest.json') --require-status failed
        if($LASTEXITCODE-ne0){throw 'Failed joint recovery manifest verification failed.'}
      }
      $published=$true
      if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity;$capacity=$null}
      Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
        & $python -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root (Join-Path $workspaceRoot 'artifacts') --run-config $package.run_config --owner $projectId --confirm-writing-stopped --retention-reason $policy.reason
        if($LASTEXITCODE-ne0){throw 'Failed joint recovery stopped-payload seal failed; scientific failure manifest retained.'}
      }
    }
    throw
  }finally{
    if($null-ne$lease){Exit-HostExecutionLease -Lease $lease}
    if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
  }
}

if(Test-Path -LiteralPath (Join-Path $sourceRun 'results/prepared_joint_trial.json') -PathType Leaf){
  Invoke-PreparedJointRecovery
  return
}

$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'completed_bunch_flight_postprocess_recovery' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion')
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
  $batchPlanPath=Join-Path $sourceRun 'results\simion_execution_batch_plan.json'
  $trialReceiptPath=Join-Path $sourceRun 'results\two_prism_trial_materialization.json'
  foreach($path in @($sourceSummaryPath,$batchPlanPath,$trialReceiptPath)){
    Get-VerifiedSourceOutput -Manifest $sourceData -Path $path
  }
  $batchPlan=Get-Content -LiteralPath $batchPlanPath -Raw -Encoding UTF8|ConvertFrom-Json
  $sourceObservation=$null
  if($sourceSummary.failure_stage-eq'analyze_trial'){
    $sourceObservationPath=Join-Path $sourceRun 'results\two_prism_trial_observation.json'
    Get-VerifiedSourceOutput -Manifest $sourceData -Path $sourceObservationPath
    $sourceObservation=Get-Content -LiteralPath $sourceObservationPath -Raw -Encoding UTF8|ConvertFrom-Json
  }
  Assert-CompletedBunchRecovery -SourceSummary $sourceSummary -BatchPlan $batchPlan -Observation $sourceObservation
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
  $sourceReceiptPath=Join-Path $sourceRun 'simion\bunch_source_receipt.json'
  Get-VerifiedSourceOutput -Manifest $sourceData -Path $sourceReceiptPath
  $sourceReceipt=Get-Content -LiteralPath $sourceReceiptPath -Raw -Encoding UTF8|ConvertFrom-Json
  $sourceOwner=Split-Path -Parent (Split-Path -Parent ([string]$sourceReceipt.state_table.path))
  $configuration.inputs.bunch_source_receipt=Copy-VerifiedRunInput -Source $sourceReceiptPath -Destination (Join-Path $package.input_dir 'bunch_source_receipt.json')
  $configuration.inputs.bunch_source_run_manifest=Copy-VerifiedRunInput -Source (Join-Path $sourceOwner 'run_manifest.json') -Destination (Join-Path $package.input_dir 'bunch_source_run_manifest.json')
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
  $failureStage='source_z_energy_timing_diagnostic'
  $diagnostic=Join-Path $resultDir 'source_z_energy_timing_diagnostic.json'
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic `
      --completed-run-config $runConfig --observation $observation --batch-merge-receipt $mergeReceipt --output $diagnostic
    if($LASTEXITCODE-ne0){throw 'Recovered default source/timing diagnostic failed.'}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  $guiOutputs=@()
  if(Test-Path -LiteralPath (Join-Path $sourceRun 'simion\gui_workbench') -PathType Container){
    $failureStage='rebind_retained_gui_iob'
    $bindingPath=Join-Path $sourceRun 'simion\static_field_binding.json'
    Get-VerifiedSourceOutput -Manifest $sourceData -Path $bindingPath
    Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
    try{
      $env:PYTHONPATH=$repoRoot
      $bindingJson=& $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding --binding $bindingPath
      if($LASTEXITCODE-ne0){throw 'Recovered GUI static binding failed its existing loader.'}
      $binding=($bindingJson-join"`n")|ConvertFrom-Json -Depth 100
    }finally{$env:PYTHONPATH=$saved;Pop-Location}
    if($binding.mode-ne'native_static_pa'-or@($binding.instances).Count-ne4){throw 'Retained GUI recovery requires its original four-instance native static binding.'}
    $configuration.inputs.static_field_binding=Copy-VerifiedRunInput -Source $bindingPath -Destination (Join-Path $package.input_dir 'static_field_binding.json')
    $guiDirectory=Join-Path $package.artifact_run_dir 'simion\gui_workbench'
    Restore-CompletedBunchGui -SourceDirectory $sourceRun -DestinationDirectory $guiDirectory -ResultDirectory $resultDir -LogDirectory $logDir -RecoveryRunId $RunId -Binding $binding
    $configuration.inputs.gui_workbench_iob=Join-Path $guiDirectory 'mrtof_three_component_candidate.iob'
    $configuration.inputs.gui_workbench_receipt=Join-Path $resultDir 'gui_workbench_receipt.json'
    $guiOutputs=@(Get-ChildItem -LiteralPath $guiDirectory -File|ForEach-Object{$_.FullName})+@($configuration.inputs.gui_workbench_receipt,(Join-Path $logDir 'rebind_retained_gui_iob.log'))
    Write-RunJson -Path $runConfig -Value $configuration
  }
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
    -Outputs (@($summary,$observation,$mergeReceipt,$mergedLog,$diagnostic,$startupPath,$terminalPath,$retention)+$guiOutputs)
  $terminalized=$true
  Write-Host "MRTOF_COMPLETED_BUNCH_FLIGHT_RECOVERY=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_completed_bunch_flight_recovery_summary' -Reason $_.Exception.Message -Software @('Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_completed_bunch_flight_recovery_summary' -Reason 'Recovery stopped before terminal publication.' -Software @('Python 3.11') -Status interrupted -FailureStage $failureStage}
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}
