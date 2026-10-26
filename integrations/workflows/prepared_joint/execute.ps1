[CmdletBinding(DefaultParameterSetName='Flight')]
param(
  [Parameter(Mandatory,ParameterSetName='Flight')][string]$PreparedJointWorkbenchRunPath,
  [Parameter(Mandatory,ParameterSetName='Analysis')][string]$AnalyzeRunPath,
  [Parameter(Mandatory)][string]$ContractPath,
  [Parameter(ParameterSetName='Flight')][string]$TrajectoryEquivalenceReferenceRunPath='',
  [Parameter(ParameterSetName='Flight')][ValidateSet('measured_population','centroid_probe')][string]$PreparedSourceMode='measured_population',
  [Parameter(ParameterSetName='Flight')][string]$FieldBindingPath='',
  [Parameter(ParameterSetName='Flight')][string]$ContinuationPredecessorManifestPath='',
  [string]$RunId='',
  [Parameter(ParameterSetName='Flight')][string]$SimionExe='',
  [string]$PythonExe='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
$projectId='instrument_assembly'
$workspaceRoot=Split-Path -Parent $repoRoot
$script:pythonRoot=$repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv/Scripts/python.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if($PSCmdlet.ParameterSetName-eq'Flight'){
  $simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
  if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
}

function Invoke-ProjectPython {
  param([string[]]$Arguments)
  Push-Location -LiteralPath $script:pythonRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$script:pythonRoot;& $python -B @Arguments;if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}

function Invoke-PreparedJointTrial {
  # One public trial entry; common run/lease/capacity and batch executors own
  # lifecycle and admission. The compiler only freezes scientific inputs.
  . (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
  . (Join-Path $repoRoot 'common/resource_budget_support.ps1')
  . (Join-Path $repoRoot 'integrations/runtime/dependencies.ps1')
  if(-not$ContractPath){throw 'Prepared joint flight requires an explicit observation ContractPath.'}
  $prepared=(Resolve-Path -LiteralPath $PreparedJointWorkbenchRunPath).Path
  $observation=(Resolve-Path -LiteralPath $ContractPath).Path
  $recording=(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','recording-config','--contract',$observation))-join"`n")|ConvertFrom-Json
  if($null-eq$recording){throw 'Prepared joint flight requires retained trajectory observations.'}
  $jointRunId=if($RunId){$RunId}else{(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__ip-mr-joint-'+[guid]::NewGuid().ToString('N').Substring(0,8)}
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts/projects/$projectId") `
    -RunId $jointRunId -Project $projectId -Mode prepared_joint -Software @('SIMION 2020','Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $recording.reason -CapacityLedgerLifecycleEnabled
  $runDir=[string]$package.artifact_run_dir
  $resultDir=[string]$package.result_dir
  $logDir=[string]$package.log_dir
  $capacity=$null;$lease=$null;$terminalized=$false
  $guards=[Collections.Generic.List[IO.FileStream]]::new()
  $stage='capacity_startup'
  try {
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
      -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $runDir `
      -CommittedNewBytes ([int64]$recording.output_budget_bytes) -ProtectedPaths @($runDir,$prepared) -Owner "instrument-assembly-prepared-joint:$jointRunId"
    Write-RunJson -Path (Join-Path $resultDir 'artifact_capacity_gate_startup.json') -Depth 14 -Value $capacity
    $stage='freeze_executable_dependencies'
    $dependencyPath=Join-Path $repoRoot 'integrations/config/runtime_dependencies.json'
    $frozen=Freeze-ConsumerDependencies -RepoRoot $repoRoot -ContractPath $dependencyPath -InputDir (Join-Path $runDir 'inputs') -OwnerId $projectId -ConsumerId prepared_joint
    $script:pythonRoot=[string]$frozen.execution_root
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    if($configuration.project-ne$projectId-or$configuration.mode-ne'prepared_joint'){throw 'Prepared joint run owner or mode differs.'}
    $configuration.inputs=[ordered]@{code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
    foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $stage='freeze_measured_joint_trial'
    $prepareArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial','prepare','--prepared-run',$prepared,'--contract',$observation,'--run-directory',$runDir,'--source-mode',$PreparedSourceMode)
    if($FieldBindingPath){$prepareArguments+=@('--field-binding',(Resolve-Path -LiteralPath $FieldBindingPath).Path)}
    if($TrajectoryEquivalenceReferenceRunPath){$prepareArguments+=@('--equivalence-reference-run',(Resolve-Path -LiteralPath $TrajectoryEquivalenceReferenceRunPath).Path)}
    Invoke-ProjectPython -Arguments $prepareArguments
    $preparationPath=Join-Path $resultDir 'prepared_joint_trial.json'
    $trial=Get-Content -LiteralPath $preparationPath -Raw|ConvertFrom-Json -Depth 60
    $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity `
      -ProtectedPaths (@($runDir)+@($trial.protected_paths)) -RemainingCommittedNewBytes ([int64]$recording.output_budget_bytes)
    $capacity=$renewal.session
    $stage='plan_measured_joint_dispatch'
    $request=Join-Path $resultDir 'simion_dispatch_request.json'
    $profiles=Join-Path $resultDir 'simion_resource_profiles.json'
    $dispatch=Join-Path $resultDir 'simion_repository_dispatch_plan.json'
    $plan=Join-Path $resultDir 'simion_execution_batch_plan.json'
    $usage=Join-Path $logDir 'simion_batch_resource_usage.json'
    $continuation=$null;$continuationPlanPath=$null
    if($ContinuationPredecessorManifestPath){
      $parentManifest=(Resolve-Path -LiteralPath $ContinuationPredecessorManifestPath).Path
      if((Split-Path -Leaf $parentManifest)-ne'run_manifest.json'){throw 'Prepared-joint continuation requires an explicit predecessor run_manifest.json.'}
      $parentRun=Split-Path -Parent $parentManifest
      $continuationRoot=Join-Path $package.input_dir 'mrtof_batch_continuation'
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation',
        '--predecessor-run-dir',$parentRun,'--current-run-config',$package.run_config,
        '--prepared-joint-current-preparation',$preparationPath,'--output-dir',$continuationRoot)
      $continuationPlanPath=Join-Path $continuationRoot 'simion_whole_unit_replay_plan.json'
      $continuation=Get-Content -LiteralPath $continuationPlanPath -Raw|ConvertFrom-Json -Depth 40
      $plan=[string]$continuation.batch_plan.path
      $dispatch=[string]$continuation.dispatch_plan.path
      $request=[string]$continuation.dispatch_request.path
      $profiles=[string]$continuation.resource_profiles.path
    }else{
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $workspaceRoot "artifacts/projects/$projectId/runs"),'--output',$profiles)
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_scheduler','--request',$request,'--profiles',$profiles,'--output',$dispatch)
      Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatch,'--output',$plan)
    }
    $batchRoot=Join-Path $resultDir 'batches'
    New-Item -ItemType Directory -Path $batchRoot|Out-Null
    $records=@{}
    function New-PreparedJointBatch {
      param($PlannedBatch)
      $batchDirectory=Join-Path $batchRoot ('batch_{0:D3}'-f[int]$PlannedBatch.index)
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','materialize-joint','--preparation',$preparationPath,'--particle-id-min',([string]$PlannedBatch.particle_id_min),'--particle-id-max',([string]$PlannedBatch.particle_id_max),'--output',$batchDirectory)|Out-Host
      return [pscustomobject]@{
        name=('mrtof_ip_measured_batch_{0:D3}'-f[int]$PlannedBatch.index);scheduler_batch=$PlannedBatch
        file_path=$simion;working_directory=$batchDirectory;environment=@{}
        stdout=Join-Path $logDir ('joint_flight_batch_{0:D3}.log'-f[int]$PlannedBatch.index)
        stderr=Join-Path $logDir ('joint_flight_batch_{0:D3}.stderr.log'-f[int]$PlannedBatch.index)
        argument_list=[string[]]@('--nogui','--noprompt','lua',[string]$trial.launcher,(Join-Path $batchDirectory 'joint.iob'),(Join-Path $batchDirectory 'joint.fly2'))
        batch_receipt=Join-Path $batchDirectory 'batch_receipt.json'
      }
    }
    $initial=Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json
    foreach($batch in @($initial.batches)){
      $reuse=$null;if($null-ne$continuation){$reuse=@($continuation.batches|Where-Object{[int]$_.index-eq[int]$batch.index})[0]}
      if($null-eq$reuse-or[string]$reuse.action-eq'replay'){$records[[int]$batch.index]=New-PreparedJointBatch $batch}
      else{
        $unit=@($continuation.units|Where-Object{[string]$_.key-eq('batch-{0:D3}'-f[int]$batch.index)})[0]
        $outputs=@($unit.terminal_outputs);$log=[string]$outputs[0].path;$receipt=[string]$outputs[1].path
        $records[[int]$batch.index]=[pscustomobject]@{name=('mrtof_ip_measured_batch_{0:D3}'-f[int]$batch.index);scheduler_batch=$batch;stdout=$log;stderr='';batch_receipt=$receipt;fly2=[string]$outputs[2].path;reused=$true}
      }
    }
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs.prepared_joint_trial=$preparationPath
    $configuration.inputs.parent_prepared_manifest=Join-Path $prepared 'run_manifest.json'
    $configuration.inputs.observation_contract=[string]$trial.trajectory_contract.path
    $configuration.inputs.simion_execution_batch_plan=$plan
    $configuration.inputs.simion_dispatch_request=$request
    $configuration.inputs.simion_resource_profiles=$profiles
    $configuration.inputs.simion_repository_dispatch_plan=$dispatch
    if($null-ne$continuation){
      $configuration.inputs.continuation_parent_manifest=$parentManifest
      $configuration.inputs.simion_whole_unit_replay_plan=$continuationPlanPath
      foreach($batch in @($initial.batches)){
        $record=$records[[int]$batch.index]
        if(($record.PSObject.Properties.Name-contains'reused')-and[bool]$record.reused){
          $prefix=('reused_batch_{0:D3}'-f[int]$batch.index)
          $configuration.inputs[($prefix+'_log')]=[string]$record.stdout
          $configuration.inputs[($prefix+'_receipt')]=[string]$record.batch_receipt
          $configuration.inputs[($prefix+'_fly2')]=[string]$record.fly2
        }
      }
    }
    $configuration.parameters=[ordered]@{parent_prepared_run=$prepared;trajectory_equivalence_reference_run=$TrajectoryEquivalenceReferenceRunPath;accelerator_provider='dual_pressure_rectilinear_ion_processor';particle_count=[int]$trial.launched_particle_count;mother_particle_count=[int]$trial.mother_particle_count;expected_particle_ids=@($trial.expected_particle_ids);trajectory_recording=$recording;source_mode=$PreparedSourceMode;prism_voltages_v=@($trial.prism_voltages_v);stripe_biases_v=@($trial.stripe_biases_v);energy_target_acceptance='not_declared';gui_executed=$false}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status checkpoint `
      -Software @('SIMION 2020','Python 3.11') -Outputs @($preparationPath,$request,$profiles,$dispatch,$plan)|Out-Null
    $stage='measured_joint_flight'
    $replay=@($initial.batches|Where-Object{ $b=$records[[int]$_.index];$null-eq$b.PSObject.Properties['reused'] -or -not[bool]$b.reused })
    if($replay.Count-gt0){
      foreach($path in @($trial.guard_paths)){
        $guards.Add([IO.File]::Open([string]$path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))
        $surface=[string]$path+'-surf'
        if(Test-Path -LiteralPath $surface -PathType Leaf){$guards.Add([IO.File]::Open($surface,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))}
      }
      $lease=Enter-HostResourceStage -Role SIMION -Stage mrtof_flight -Budget (Get-HostResourceBudget -Role SIMION -Stage mrtof_flight) -RunId $jointRunId
      $stage='joint_asset_identity_before_flight'
      Invoke-ProjectPython -Arguments @('-c','import sys;from pathlib import Path;from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding,verify_joint_asset_records;verify_joint_asset_records(load_binding(Path(sys.argv[1])));print("JOINT_NATIVE_ASSETS=PASS")',[string]$trial.field_binding.path)
      $stage='measured_joint_flight'
    }
    $dispatchValue=Get-Content -LiteralPath $dispatch -Raw|ConvertFrom-Json
    $existing=@();$formalIndex=$null
    if($null-eq$continuation-and[string]$dispatchValue.estimation.kind-eq'formal_first_batch_observation'){
      $formalIndex=[int]$initial.batches[0].index
      $formal=Start-ObservedFormalProcess -DispatchPlanPath $dispatch -ProcessSpecification $records[$formalIndex]
      $completed=[bool]$formal.process_record.completed
      if($formal.resource_budget_exceeded-or($completed-and(-not$formal.completed_naturally-or[int]$formal.exit_code-ne0))){throw 'Measured formal first batch failed or exceeded the resource budget.'}
      $adaptive=@('-m','common.simion.resource_scheduler','--request',$request,'--profiles',$profiles,'--output',$dispatch,'--observed-formal-peak-bytes',([string]$formal.observed_peak_process_tree_working_set_bytes),'--observed-formal-cpu-percent',([string]$formal.observed_process_cpu_percent),'--observed-background-cpu-percent',([string]$formal.observed_background_cpu_percent),'--available-memory-bytes',([string]$formal.available_memory_bytes),'--total-physical-memory-bytes',([string]$formal.total_physical_memory_bytes))
      if($completed){$adaptive+='--first-batch-completed'}
      Invoke-ProjectPython -Arguments $adaptive
      $existing=@($formal.process_record)
      Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatch,'--output',$plan)
      $replanned=Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json
      foreach($batch in @($replanned.batches)){
        if($records.ContainsKey([int]$batch.index)){
          $prior=$records[[int]$batch.index].scheduler_batch
          if([int]$prior.particle_id_min-ne[int]$batch.particle_id_min-or[int]$prior.count-ne[int]$batch.count){throw 'Adaptive plan changed an existing measured batch.'}
        }else{$records[[int]$batch.index]=New-PreparedJointBatch $batch}
      }
    }
    $final=Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json
    $pending=@($final.batches|Where-Object{ $record=$records[[int]$_.index];($null-eq$formalIndex-or[int]$_.index-ne$formalIndex)-and(-not($record.PSObject.Properties.Name-contains'reused')) }|ForEach-Object{$records[[int]$_.index]})
    if($pending.Count-eq0-and$existing.Count-eq0){$wave=[pscustomobject]@{resource_budget_exceeded=$false;processes=@()}}
    else{$wave=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatch -RunDir $runDir -UsagePath $usage `
      -ProcessSpecifications $pending -ExistingProcessRecords $existing}
    if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count-ne0){throw 'Measured joint flight failed or exceeded repository resource budget.'}
    if(Test-Path -LiteralPath $usage){Complete-ResourceUsage -RunDir $runDir -UsagePath $usage|Out-Null}
    Exit-HostResourceStage -Lease $lease;$lease=$null
    $stage='merge_measured_original_ids'
    $merged=Join-Path $logDir 'native_two_prism_flight.log'
    $mergeReceipt=Join-Path $resultDir 'batch_log_merge_receipt.json'
    $merge=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','merge-joint','--preparation',$preparationPath,'--output',$merged,'--receipt',$mergeReceipt)
    foreach($batch in @($final.batches)){$item=$records[[int]$batch.index];$merge+=@('--batch-log',$item.stdout,$item.batch_receipt)}
    Invoke-ProjectPython -Arguments $merge
    $stage='automatic_joint_diagnostics'
    if($PreparedSourceMode-eq'centroid_probe'){
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial','analyze-probe','--preparation',$preparationPath,'--log',$merged,'--output',(Join-Path $resultDir 'diagnostics'))
    }else{
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','analyze-joint','--preparation',$preparationPath,'--log',$merged,'--output',(Join-Path $resultDir 'diagnostics'))
    }
    if($trial.PSObject.Properties.Name-contains'trajectory_equivalence_reference'-and$null-ne$trial.trajectory_equivalence_reference){
      $stage='field_consumer_trajectory_equivalence'
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','compare-joint','--preparation',$preparationPath,'--log',$merged,'--output',(Join-Path $resultDir 'trajectory_equivalence_receipt.json'))
    }
    Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
      schema_version=1;role='mrtof_measured_joint_flight_summary';status='success';mother_particle_count=[int]$trial.mother_particle_count
      launched_particle_count=[int]$trial.launched_particle_count;joint_simulation_executed=($pending.Count-gt0-or$existing.Count-gt0);gui_executed=$false
      actual_native_batch_count=($pending.Count+$existing.Count);reused_batch_count=@($final.batches|Where-Object{$records[[int]$_.index].PSObject.Properties.Name-contains'reused'}).Count
      qualification='candidate_joint_flight_only';energy_target_acceptance='not_declared';six_dimensional_match_qualified=$false;time_focus_qualified=$false
      diagnostics=Join-Path $resultDir 'diagnostics';all_upstream_and_downstream_losses_retained=$true
      dispatch_plan=$dispatch;resource_usage=$usage;batch_plan=$plan;merged_log=$merged
    })
    $stage='terminal_publication'
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
    $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity -RemainingCommittedNewBytes 0
    $capacity=$terminal.session
    Write-RunJson -Path (Join-Path $resultDir 'artifact_capacity_gate_terminal.json') -Depth 14 -Value $terminal
    $outputs=@(Get-ChildItem -LiteralPath $resultDir -Recurse -File|ForEach-Object{$_.FullName})+@(Get-ChildItem -LiteralPath $logDir -File|ForEach-Object{$_.FullName})+@($package.summary,$retention)
    # Retained trajectory payload is deliberately larger than the light-evidence
    # finalize-ready contract. Publish scientific identity first, then use the
    # same stopped-payload owner seal as the native field producer.
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs -DeferCapacityFinalization
    $terminalized=$true
    $stage='stopped_payload_seal'
    $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity
    $capacity=$null
    Invoke-ProjectPython -Arguments @('-m','common.contracts.run_capacity_lifecycle','--action','seal-stopped-payload','--artifact-root',(Join-Path $workspaceRoot 'artifacts'),'--run-config',$package.run_config,'--owner',$projectId,'--confirm-writing-stopped','--retention-reason',[string]$recording.reason)
    Write-Output "MEASURED_JOINT_TRIAL=PASS RUN_ID=$jointRunId JOINT_FLY=True GUI=False"
  }catch{
    if(-not$terminalized){
      $failure=$_.Exception.Message
      if($null-ne$lease){Exit-HostResourceStage -Lease $lease;$lease=$null}
      Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
        schema_version=1;role='mrtof_measured_joint_flight_summary';status='failed';reason=$failure;failure_stage=$stage
        gui_executed=$false;qualification='failed_joint_trial_no_performance_qualification'
      })
      $retention=Join-Path $runDir 'retention_actions.json'
      if(-not(Test-Path -LiteralPath $retention -PathType Leaf)){
        $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
      }
      $outputs=@(Get-ChildItem -LiteralPath $runDir -Recurse -File|Where-Object{$_.Name-notin@('run_config.json','run_manifest.json')}|ForEach-Object{$_.FullName})
      Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status failed -Software @('SIMION 2020','Python 3.11') -Outputs $outputs -DeferCapacityFinalization
      $terminalized=$true
      if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity;$capacity=$null}
      Invoke-ProjectPython -Arguments @('-m','common.contracts.run_capacity_lifecycle','--action','seal-stopped-payload','--artifact-root',(Join-Path $workspaceRoot 'artifacts'),'--run-config',$package.run_config,'--owner',$projectId,'--confirm-writing-stopped','--retention-reason',[string]$recording.reason)
    }else{
      Write-Warning "Scientific manifest remains verified; stopped-payload sealing failed at $stage and requires the public owner recovery command."
    }
    throw
  }finally{
    if($null-ne$lease){Exit-HostResourceStage -Lease $lease}
    foreach($guard in $guards){$guard.Dispose()}
    if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
  }
}
function Invoke-PreparedJointAnalysis {
  . (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
  . (Join-Path $repoRoot 'integrations/runtime/dependencies.ps1')
  $source=(Resolve-Path -LiteralPath $AnalyzeRunPath).Path
  $contract=(Resolve-Path -LiteralPath $ContractPath).Path
  $recording=(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','recording-config','--contract',$contract))-join"`n")|ConvertFrom-Json
  if($null-eq$recording){throw 'Joint analysis requires the original retained-observation budget.'}
  $analysisRunId=if($RunId){$RunId}else{(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__ip-mr-joint-'+[guid]::NewGuid().ToString('N').Substring(0,8)}
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts/projects/$projectId") `
    -RunId $analysisRunId -Project $projectId -Mode prepared_joint_analysis -Software @('Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $recording.reason -CapacityLedgerLifecycleEnabled
  $runDir=[string]$package.artifact_run_dir
  $inputDir=Join-Path $runDir 'inputs'
  $capacity=$null;$failure=$null;$stage='capacity_startup'
  try {
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
      -RunDirectory $runDir -CommittedNewBytes ([int64]$recording.output_budget_bytes) -ProtectedPaths @($runDir,$source) -Owner "instrument-assembly-joint-analysis:$analysisRunId"
    $stage='freeze_executable_dependencies'
    $dependencyPath=Join-Path $repoRoot 'integrations/config/runtime_dependencies.json'
    $frozen=Freeze-ConsumerDependencies -RepoRoot $repoRoot -ContractPath $dependencyPath -InputDir $inputDir -OwnerId $projectId -ConsumerId prepared_joint
    $script:pythonRoot=[string]$frozen.execution_root
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs=[ordered]@{code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
    foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $stage='admit_completed_native_source'
    $selection=(@(Invoke-ProjectPython -Arguments @('-m','integrations.workflows.prepared_joint.analysis','--source-run',$source,'--contract',$contract,'--output-inputs',$inputDir))-join"`n")|ConvertFrom-Json -Depth 50
    if(($selection.recording|ConvertTo-Json -Compress)-cne($recording|ConvertTo-Json -Compress)){throw 'Analysis observation budget changed during input freezing.'}
    $configuration.inputs.source_manifest=$selection.source_manifest
    $configuration.inputs.analysis_contract=$selection.analysis_contract
    $configuration.inputs.source_preparation=$selection.preparation
    $configuration.inputs.source_merge_receipt=$selection.merge_receipt
    $configuration.parameters=[ordered]@{source_run=$source;mother_particle_count=$selection.mother_particle_count;launched_particle_count=$selection.launched_particle_count;native_flight_executed=$false;qualification='post_hoc_analysis_only'}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity `
      -ProtectedPaths (@($runDir)+@($selection.protected_paths)) -RemainingCommittedNewBytes ([int64]$recording.output_budget_bytes)
    $capacity=$renewal.session
    $stage='joint_diagnostics'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','analyze-joint',
      '--preparation',[string]$selection.preparation,'--log',[string]$selection.merged_log,'--output',(Join-Path $package.result_dir 'diagnostics'),'--analysis-contract',[string]$selection.analysis_contract)
  }catch{$failure=$_}
  # Scientific terminal publication is independent of capacity sealing. A seal
  # failure must not replace a successful analysis manifest with solver failure.
  try {
    $status=if($null-eq$failure){'success'}else{'failed'}
    $summary=[ordered]@{schema_version=1;role='prepared_joint_analysis_summary';status=$status;source_run=$source;native_flight_executed=$false;qualification='post_hoc_analysis_only'}
    if($null-ne$failure){$summary.reason=$failure.Exception.Message;$summary.failure_stage=$stage}
    Write-RunJson -Path $package.summary -Depth 20 -Value $summary
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $script:pythonRoot -RunConfig $package.run_config
    if($null-ne$capacity){
      $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity -RemainingCommittedNewBytes 0
      $capacity=$terminal.session
    }
    $outputs=@(Get-ChildItem -LiteralPath $package.result_dir -Recurse -File|ForEach-Object{$_.FullName})+@($package.summary,$retention)
    Write-VerifiedRunManifest -Python $python -RepoRoot $script:pythonRoot -RunConfig $package.run_config -Status $status -Software @('Python 3.11') -Outputs $outputs -DeferCapacityFinalization
    if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity;$capacity=$null}
    Invoke-ProjectPython -Arguments @('-m','common.contracts.run_capacity_lifecycle','--action','seal-stopped-payload','--artifact-root',(Join-Path $workspaceRoot 'artifacts'),
      '--run-config',$package.run_config,'--owner',$projectId,'--confirm-writing-stopped','--retention-reason',[string]$recording.reason)
  }finally{
    if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
  }
  if($null-ne$failure){throw $failure}
  Write-Output "PREPARED_JOINT_ANALYSIS=PASS RUN_ID=$analysisRunId NATIVE_FLY=False"
}
if($PSCmdlet.ParameterSetName-eq'Analysis'){
  . (Join-Path $repoRoot 'common/host_execution_lease.ps1')
  $analysisLease=Enter-HostExecutionLease -Role GATE -Stage unclassified -RunId $RunId
  $analysisOkay=$false
  try{Invoke-PreparedJointAnalysis;$analysisOkay=$true}
  finally{Exit-HostExecutionLease -Lease $analysisLease -Outcome $(if($analysisOkay){'success'}else{'failed'}) -RunId $RunId}
}else{Invoke-PreparedJointTrial}
