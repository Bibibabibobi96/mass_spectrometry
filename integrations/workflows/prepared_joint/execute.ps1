[CmdletBinding(DefaultParameterSetName='Flight')]
param(
  [Parameter(Mandatory,ParameterSetName='Flight')][string]$PreparedJointWorkbenchRunPath,
  [Parameter(Mandatory,ParameterSetName='Analysis')][string]$AnalyzeRunPath,
  [Parameter(Mandatory,ParameterSetName='Flight')][Parameter(Mandatory,ParameterSetName='Analysis')][string]$ContractPath,
  [Parameter(ParameterSetName='Flight')][string]$TrajectoryEquivalenceReferenceRunPath='',
  [Parameter(ParameterSetName='Flight')][ValidateSet('measured_population','centroid_probe')][string]$PreparedSourceMode='measured_population',
  [Parameter(ParameterSetName='Flight')][string]$FieldBindingPath='',
  [Parameter(ParameterSetName='Flight')][string]$ContinuationPredecessorManifestPath='',
  [Parameter(Mandatory,ParameterSetName='Resume')][switch]$ResumeFinalization,
  [string]$ResultPath='',
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
. (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
$pathContext=Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
. (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
if($ResumeFinalization){
  if(-not$RunId){throw 'Finalization recovery requires the existing RunId.'}
  $projectArtifacts=Join-Path $pathContext.artifact_root "projects/$projectId"
  if(-not$ResultPath){$ResultPath=Join-Path $projectArtifacts "scratch/workflow_results/$RunId/result.json"}
  $recoveryRun=Join-Path $projectArtifacts "runs/$RunId"
  if(Test-Path -LiteralPath $ResultPath -PathType Leaf){
    $transport=Get-Content -LiteralPath $ResultPath -Raw|ConvertFrom-Json -AsHashtable
    if($transport.role-ne'run_artifact_workflow_result'-or(Split-Path -Leaf ([string]$transport.run_directory))-cne$RunId){throw 'Prepared-joint recovery Result identity differs.'}
    $recoveryRun=[string]$transport.run_directory
  }
  $result=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $recoveryRun 'inputs/execution_request.json') -ResultPath $ResultPath -ResumeFinalization
  Write-Output $result
  if($result.status-ne'success'){throw 'Prepared-joint finalization remains incomplete; inspect Result recovery action.'}
  return
}
if($PSCmdlet.ParameterSetName-eq'Flight'){
  $simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
}

$script:preparedPackage=$null
function Invoke-ProjectPython {
  param([string[]]$Arguments)
  $root=$script:pythonRoot;$environment=@{}
  if($null-ne$script:preparedPackage){
    $execution=Get-RunNativeExecutionContext -Package $script:preparedPackage -Paths @($root) -Tool Python
    $root=[string]$execution.projected_paths[0];$environment=$execution.environment
  }
  Invoke-RunToolRootContext -RepoRoot $root -Environment $environment -Operation {
    & $python -B @Arguments
    if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}
  }
}

function Get-PreparedJointSourceReferences {
  param([string[]]$RunDirectories)
  # These are explicit run authorities from the request or verified trial,
  # never inferred ancestors of an arbitrary external file.
  $code='import json,sys;from pathlib import Path;from common.contracts.write_run_manifest import file_record;print(json.dumps([dict(manifest_record=file_record(Path(p)/"run_manifest.json"),protected_paths=[p],protected_cache_keys=[]) for p in json.loads(sys.argv[1])]))'
  $json=(@(Invoke-ProjectPython -Arguments @('-c',$code,(ConvertTo-Json -InputObject @($RunDirectories|Where-Object{$_}|Select-Object -Unique) -Compress)))-join"`n")
  return @($json|ConvertFrom-Json -AsHashtable -Depth 100)
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
  $parentManifest=$null;$parentRun=$null
  if($ContinuationPredecessorManifestPath){
    $parentManifest=(Resolve-Path -LiteralPath $ContinuationPredecessorManifestPath).Path
    if((Split-Path -Leaf $parentManifest)-ne'run_manifest.json'){throw 'Prepared-joint continuation requires an explicit predecessor run_manifest.json.'}
    $parentRun=Split-Path -Parent $parentManifest
  }
  $recording=(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial','recording-config','--contract',$observation))-join"`n")|ConvertFrom-Json
  if($null-eq$recording){throw 'Prepared joint flight requires retained trajectory observations.'}
  $jointRunId=if($RunId){$RunId}else{(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__ip-mr-joint-'+[guid]::NewGuid().ToString('N').Substring(0,8)}
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $pathContext.artifact_root "projects/$projectId") `
    -RunId $jointRunId -Project $projectId -Mode prepared_joint -Software @('SIMION 2020','Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $recording.reason -CapacityLedgerLifecycleEnabled -PathContext $pathContext
  $script:preparedPackage=$package
  $runDir=[string]$package.artifact_run_dir
  $resultDir=[string]$package.result_dir
  $logDir=[string]$package.log_dir
  $owner=$null;$finalizationAttempted=$false;$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
  $capacity=$null;$lease=$null;$terminalized=$false;$writerUnknown=$false;$waveInProgress=$false;$failureRecord=$null
  $runTimer=[Diagnostics.Stopwatch]::StartNew();$phaseTimings=[ordered]@{}
  $guards=[Collections.Generic.List[IDisposable]]::new()
  $pathEnvironmentNames=@('MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
  $savedPathEnvironment=Save-RunEnvironment -Names $pathEnvironmentNames
  $stage='capacity_startup'
  try {
 $parentEnvironment=(Get-RunNativeExecutionContext -Package $package -Paths @()).environment
 foreach($key in $parentEnvironment.Keys){[Environment]::SetEnvironmentVariable([string]$key,[string]$parentEnvironment[$key],'Process')}

    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
      -ArtifactRoot ([string]$pathContext.artifact_root) -RunDirectory $runDir `
      -CommittedNewBytes ([int64]$recording.output_budget_bytes) -ProtectedPaths @($runDir) `
      -SourceReferences @(Get-PreparedJointSourceReferences -RunDirectories @($prepared,$parentRun,$TrajectoryEquivalenceReferenceRunPath)) -Owner "run-artifact-workflow:${projectId}:$jointRunId"
    Write-RunJson -Path (Join-Path $resultDir 'artifact_capacity_gate_startup.json') -Depth 14 -Value $capacity
    $stage='freeze_executable_dependencies'
    $dependencyPath=Join-Path $repoRoot 'integrations/config/runtime_dependencies.json'
    $frozen=Freeze-ConsumerDependencies -RepoRoot $repoRoot -ContractPath $dependencyPath -InputDir (Join-Path $runDir 'inputs') -OwnerId $projectId -ConsumerId prepared_joint
    $script:pythonRoot=[string]$frozen.execution_root
    $entryIdentity=@($frozen.identities|Where-Object{$_.source_repo_path-ceq'integrations/workflows/prepared_joint/execute.ps1'})
    $frozenEntryRecord=if($entryIdentity.Count-eq1){@{path=$entryIdentity[0].snapshot_path;exists=$true;bytes=[long](Get-Item -LiteralPath $entryIdentity[0].snapshot_path).Length;sha256=$entryIdentity[0].sha256}}else{$null}
    if($parentRun){
      . (Join-Path $script:pythonRoot 'projects/parallel_mirror_dual_stripe_mr_tof/simion/native_corridor_runtime_support.ps1')
      $capacity=Protect-MrtofContinuationEvidence -Parent $parentRun -Session $capacity -Python $python -RepoRoot $script:pythonRoot -Guards $guards
    }
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    if($configuration.project-ne$projectId-or$configuration.mode-ne'prepared_joint'){throw 'Prepared joint run owner or mode differs.'}
    $configuration.inputs=[ordered]@{code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
    foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $stage='freeze_measured_joint_trial'
    if($TrajectoryEquivalenceReferenceRunPath){$guards.Add((Enter-RunTerminalConsumptionGuard -RunDirectory $TrajectoryEquivalenceReferenceRunPath))}
    $prepareArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial','prepare','--prepared-run',$prepared,'--contract',$observation,'--run-directory',$runDir,'--source-mode',$PreparedSourceMode)
    if($FieldBindingPath){$prepareArguments+=@('--field-binding',(Resolve-Path -LiteralPath $FieldBindingPath).Path)}
    if($TrajectoryEquivalenceReferenceRunPath){$prepareArguments+=@('--equivalence-reference-run',(Resolve-Path -LiteralPath $TrajectoryEquivalenceReferenceRunPath).Path)}
    if($parentManifest){$prepareArguments+=@('--continuation-predecessor-manifest',$parentManifest)}
    Invoke-ProjectPython -Arguments $prepareArguments
    $preparationPath=Join-Path $resultDir 'prepared_joint_trial.json'
    $trial=Get-Content -LiteralPath $preparationPath -Raw|ConvertFrom-Json -Depth 60
    $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity `
      -ProtectedPaths @($runDir) -SourceReferences @(Get-PreparedJointSourceReferences -RunDirectories @($trial.protected_paths)) -RemainingCommittedNewBytes ([int64]$recording.output_budget_bytes)
    $capacity=$renewal.session
    $stage='plan_measured_joint_dispatch'
    $request=Join-Path $resultDir 'simion_dispatch_request.json'
    $profiles=Join-Path $resultDir 'simion_resource_profiles.json'
    $dispatch=Join-Path $resultDir 'simion_repository_dispatch_plan.json'
    $plan=Join-Path $resultDir 'simion_execution_batch_plan.json'
    $usage=Join-Path $logDir 'simion_batch_resource_usage.json'
    $continuation=$null;$continuationPlanPath=$null
    if($ContinuationPredecessorManifestPath){
      $continuationRoot=Join-Path $package.input_dir 'mrtof_batch_continuation'
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation',
        '--predecessor-run-dir',$parentRun,'--current-run-config',$package.run_config,
        '--prepared-joint-current-preparation',$preparationPath,'--trusted-repo-root',$repoRoot,'--output-dir',$continuationRoot)
      $continuationPlanPath=Join-Path $continuationRoot 'simion_whole_unit_replay_plan.json'
      $continuation=Get-Content -LiteralPath $continuationPlanPath -Raw|ConvertFrom-Json -Depth 40
      $plan=[string]$continuation.batch_plan.path
      $dispatch=[string]$continuation.dispatch_plan.path
      $request=[string]$continuation.dispatch_request.path
      $profiles=[string]$continuation.resource_profiles.path
    }else{
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $pathContext.artifact_root "projects/$projectId/runs"),'--output',$profiles)
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_scheduler','--request',$request,'--profiles',$profiles,'--output',$dispatch)
      Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatch,'--output',$plan)
    }
    $batchRoot=Join-Path $resultDir 'batches'
    New-Item -ItemType Directory -Path $batchRoot|Out-Null
    $records=@{}
    function New-PreparedJointBatch {
      param($PlannedBatch)
      $batchDirectory=Join-Path $batchRoot ('batch_{0:D3}'-f[int]$PlannedBatch.index)
      $nativePaths=@([string]$trial.launcher,$batchDirectory,(Join-Path $batchDirectory 'joint.iob'),
        (Join-Path $batchDirectory 'joint.fly2'),(Join-Path $batchDirectory 'joint.lua'))+@($trial.guard_paths)
      $execution=Get-RunNativeExecutionContext -Package $package -Paths $nativePaths
      Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Environment $execution.environment -Operation {
        Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','materialize-joint','--preparation',$preparationPath,'--particle-id-min',([string]$PlannedBatch.particle_id_min),'--particle-id-max',([string]$PlannedBatch.particle_id_max),'--output',$batchDirectory)|Out-Host
      }
      return [pscustomobject]@{
        name=('mrtof_ip_measured_batch_{0:D3}'-f[int]$PlannedBatch.index);scheduler_batch=$PlannedBatch
        file_path=$simion;working_directory=$execution.projected_paths[1];environment=$execution.environment
        stdout=Join-Path $logDir ('joint_flight_batch_{0:D3}.log'-f[int]$PlannedBatch.index)
        stderr=Join-Path $logDir ('joint_flight_batch_{0:D3}.stderr.log'-f[int]$PlannedBatch.index)
        argument_list=[string[]]@('--nogui','--noprompt','lua',[string]$execution.projected_paths[0],[string]$execution.projected_paths[2],[string]$execution.projected_paths[3])
        batch_receipt=Join-Path $batchDirectory 'batch_receipt.json'
        owner_exit=Join-Path $batchDirectory 'owner_exit.json'
      }
    }
    $initial=Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json
    foreach($batch in @($initial.batches)){
      $reuse=$null;if($null-ne$continuation){$reuse=@($continuation.batches|Where-Object{[int]$_.index-eq[int]$batch.index})[0]}
      if($null-eq$reuse-or[string]$reuse.action-eq'replay'){$records[[int]$batch.index]=New-PreparedJointBatch $batch}
      else{
        $unit=@($continuation.units|Where-Object{[string]$_.key-eq('batch-{0:D3}'-f[int]$batch.index)})[0]
        $outputs=@($unit.terminal_outputs);$log=[string]$outputs[0].path;$receipt=[string]$outputs[1].path
        $records[[int]$batch.index]=[pscustomobject]@{name=('mrtof_ip_measured_batch_{0:D3}'-f[int]$batch.index);scheduler_batch=$batch;stdout=$log;stderr='';batch_receipt=$receipt;fly2=[string]$outputs[2].path;owner_exit=if($outputs.Count-gt3){[string]$outputs[3].path}else{''};owner_manifest=if($reuse.PSObject.Properties.Name-contains'exit_evidence_manifest'-and$reuse.exit_evidence_manifest){[string]$reuse.exit_evidence_manifest}else{''};reused=$true}
      }
    }
    if($null-ne$continuation){
      $missing=@($initial.batches|Where-Object{ $record=$records[[int]$_.index];-not($record.PSObject.Properties.Name-contains'reused') })
      if($missing.Count){
        $localDispatch=Join-Path $resultDir 'simion_repository_dispatch_plan.json'
        Copy-Item -LiteralPath $dispatch -Destination $localDispatch
        $dispatch=$localDispatch
        $fixedArgs=@('-m','common.simion.resource_scheduler','--prepare-fixed-recovery-plan',$dispatch,'--fixed-batch-plan',$plan,'--output',$dispatch)
        if($profiles){$fixedArgs+=@('--profiles',$profiles)}
        foreach($batch in $missing){$fixedArgs+=@('--replay-batch-index',([string]$batch.index))}
        Invoke-ProjectPython -Arguments $fixedArgs
      }
    }
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs.prepared_joint_trial=$preparationPath
    $configuration.inputs.parent_prepared_manifest=Join-Path $prepared 'run_manifest.json'
    if($TrajectoryEquivalenceReferenceRunPath){$configuration.inputs.trajectory_equivalence_source_manifest=Join-Path $TrajectoryEquivalenceReferenceRunPath 'run_manifest.json'}
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
          $batchScience=Get-Content -LiteralPath $record.batch_receipt -Raw|ConvertFrom-Json -AsHashtable
          if($batchScience.Contains('scientific_event_output')-and$null-ne$batchScience.scientific_event_output){
            foreach($pair in @(@('events_path','scientific_events'),@('trajectory_path','scientific_trajectory'))){
              if($batchScience.scientific_event_output.Contains($pair[0])){
                $configuration.inputs[($prefix+'_'+$pair[1])]=[string]$batchScience.scientific_event_output[$pair[0]]
              }
            }
          }
          if($record.owner_exit){$configuration.inputs[($prefix+'_owner_exit')]=[string]$record.owner_exit}
          if($record.owner_manifest){$configuration.inputs[($prefix+'_owner_manifest')]=[string]$record.owner_manifest}
        }
      }
    }
    $configuration.parameters=[ordered]@{parent_prepared_run=$prepared;trajectory_equivalence_reference_run=$TrajectoryEquivalenceReferenceRunPath;accelerator_provider='dual_pressure_rectilinear_ion_processor';particle_count=[int]$trial.launched_particle_count;mother_particle_count=[int]$trial.mother_particle_count;expected_particle_ids=@($trial.expected_particle_ids);trajectory_recording=$recording;source_mode=$PreparedSourceMode;prism_voltages_v=@($trial.prism_voltages_v);stripe_biases_v=@($trial.stripe_biases_v);energy_target_acceptance='not_declared';gui_executed=$false}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $owner=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity `
      -ResultPath $ResultPath -EntrypointPath (Join-Path $script:pythonRoot 'integrations/workflows/prepared_joint/execute.ps1') -EntrypointRecord $frozenEntryRecord `
      -CommitmentInputPaths @([string]$trial.trajectory_contract.path) -Software @('SIMION 2020','Python 3.11')
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status checkpoint `
      -Software @('SIMION 2020','Python 3.11') -Outputs @($preparationPath,$request,$profiles,$dispatch,$plan)|Out-Null
    $stage='measured_joint_flight'
    $phaseTimings.preparation_seconds=$runTimer.Elapsed.TotalSeconds
    $flightStarted=$runTimer.Elapsed.TotalSeconds
    $replay=@($initial.batches|Where-Object{ $b=$records[[int]$_.index];$null-eq$b.PSObject.Properties['reused'] -or -not[bool]$b.reused })
    if($replay.Count-gt0){
      if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
      foreach($path in @($trial.guard_paths)){
        $guards.Add([IO.File]::Open([string]$path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))
        $surface=[string]$path+'-surf'
        if(Test-Path -LiteralPath $surface -PathType Leaf){$guards.Add([IO.File]::Open($surface,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))}
      }
      $lease=Enter-HostResourceStage -StatePath $pathContext.host_resource_state_path -Role SIMION -Stage mrtof_flight -Budget (Get-HostResourceBudget -Role SIMION -Stage mrtof_flight) -RunId $jointRunId
      $stage='joint_asset_identity_before_flight'
      Invoke-ProjectPython -Arguments @('-c','import sys;from pathlib import Path;from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding,verify_joint_asset_records;verify_joint_asset_records(load_binding(Path(sys.argv[1])));print("JOINT_NATIVE_ASSETS=PASS")',[string]$trial.field_binding.path)
      $stage='measured_joint_flight'
    }
    $dispatchValue=Get-Content -LiteralPath $dispatch -Raw|ConvertFrom-Json
    $formalIndex=$null;$firstSpecification=$null;$replan=$null
    $recoverObservation=$null-ne$continuation-and$dispatchValue.estimation.PSObject.Properties['recovered_missing_observation']-and[bool]$dispatchValue.estimation.recovered_missing_observation
    if(([string]$dispatchValue.estimation.kind-eq'formal_first_batch_observation')-and($null-eq$continuation-or$recoverObservation)-and$replay.Count-gt0){
      $formalIndex=if($recoverObservation-and$dispatchValue.estimation.PSObject.Properties['observed_missing_batch_index']){[int]$dispatchValue.estimation.observed_missing_batch_index}elseif($recoverObservation){[int]$replay[0].index}else{[int]$initial.batches[0].index}
      $replan={
      param($formal)
      $completed=[bool]$formal.process_record.completed
      $adaptive=@('-m','common.simion.resource_scheduler')
      if($recoverObservation){$adaptive+=@('--recovered-missing-plan',$dispatch)}else{$adaptive+=@('--request',$request,'--profiles',$profiles)}
      $adaptive+=@('--output',$dispatch,'--observed-formal-peak-bytes',([string]$formal.observed_peak_process_tree_working_set_bytes),'--observed-formal-cpu-percent',([string]$formal.observed_process_cpu_percent),'--observed-background-cpu-percent',([string]$formal.observed_background_cpu_percent),'--available-memory-bytes',([string]$formal.available_memory_bytes),'--total-physical-memory-bytes',([string]$formal.total_physical_memory_bytes))
      if($completed){$adaptive+='--first-batch-completed'}
      Invoke-ProjectPython -Arguments $adaptive
      if($recoverObservation){return}
      Invoke-ProjectPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatch,'--output',$plan)
      $replanned=Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json
      foreach($batch in @($replanned.batches)){
        if($records.ContainsKey([int]$batch.index)){
          $prior=$records[[int]$batch.index].scheduler_batch
          if([int]$prior.particle_id_min-ne[int]$batch.particle_id_min-or[int]$prior.count-ne[int]$batch.count){throw 'Adaptive plan changed an existing measured batch.'}
        }else{$records[[int]$batch.index]=New-PreparedJointBatch $batch}
      }
      }
      $firstSpecification=$records[$formalIndex]
    }
    $prepareRemaining={
      param($formal)
      $final=Get-Content -LiteralPath $plan -Raw|ConvertFrom-Json
      $pending=@($final.batches|Where-Object{ $record=$records[[int]$_.index];($null-eq$formalIndex-or[int]$_.index-ne$formalIndex)-and(-not($record.PSObject.Properties.Name-contains'reused')) }|ForEach-Object{$records[[int]$_.index]})
      [pscustomobject]@{pending=$pending;final=$final}
    }
    $checkpoint={
      param($completedRecord)
      $index=[int]$completedRecord.specification.scheduler_batch.index
      $batch=$records[$index]
      $nativeOperations.Add(@{operation_id="simion.batch.$index";resource_release_id='simion';observation=@{
        exit_confirmed=[bool]$completedRecord.completed;returncode=[int]$completedRecord.exit_code;
        process_id=[int]$completedRecord.root_process_id;process_started_at_utc_ticks=[long]$completedRecord.root_process_started_at_utc_ticks}})
      Write-RunJson -Path $batch.owner_exit -Value ([ordered]@{schema_version=1;role='simion_batch_owner_exit';batch_index=$index;completed=$true;exit_code=[int]$completedRecord.exit_code})
    }
    $waveInProgress=$true
    $wave=Invoke-SimionBatchPhase -DispatchPlanPath $dispatch -RunDir $runDir -UsagePath $usage `
      -FirstSpecification $firstSpecification -Replan $replan -PrepareRemaining $prepareRemaining -OnProcessCompleted $checkpoint
    $waveInProgress=[bool]$wave.resource_budget_exceeded
    $final=$wave.prepared.final
    $pending=@($wave.prepared.pending)
    $existing=@(if($null-ne$wave.formal){$wave.formal.process_record})
    if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count-ne0){throw 'Measured joint flight failed or exceeded repository resource budget.'}
    $phaseTimings.flight_seconds=$runTimer.Elapsed.TotalSeconds-$flightStarted
    $analysisStarted=$runTimer.Elapsed.TotalSeconds
    if(Test-Path -LiteralPath $usage){Complete-ResourceUsage -RunDir $runDir -UsagePath $usage|Out-Null}
    if($null-ne$lease){
      $release=Exit-HostResourceStage -Lease $lease -PassThru
      if($nativeOperations.Count){
        $inherited=[bool]$lease.inherited
        if($inherited){$release=Invoke-HostResourceTransaction -Request @{operation='inherit';token=[string]$lease.token}}
        $resourceReleases.Add(@{release_id='simion';completion_receipt=@{host_release=@{inherited=$inherited;token=[string]$lease.token;result=@{status=[string]$release.status;token=[string]$release.token};error=$null}}})
      }
      $lease=$null
    }
    $stage='merge_measured_original_ids'
    $merged=Join-Path $logDir 'native_two_prism_flight.log'
    $mergeReceipt=Join-Path $resultDir 'batch_log_merge_receipt.json'
    $merge=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','merge-joint','--preparation',$preparationPath,'--output',$merged,'--receipt',$mergeReceipt)
    foreach($batch in @($final.batches)){$item=$records[[int]$batch.index];$merge+=@('--batch-log',$item.stdout,$item.batch_receipt)}
    Invoke-ProjectPython -Arguments $merge
    $stage='automatic_joint_diagnostics'
    if($PreparedSourceMode-eq'centroid_probe'){
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepared_joint_trial','analyze-probe','--preparation',$preparationPath,'--log',$merged,'--scientific-event-receipt',$mergeReceipt,'--output',(Join-Path $resultDir 'diagnostics'))
    }else{
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','analyze-joint','--preparation',$preparationPath,'--log',$merged,'--output',(Join-Path $resultDir 'diagnostics'))
    }
    if($trial.PSObject.Properties.Name-contains'trajectory_equivalence_reference'-and$null-ne$trial.trajectory_equivalence_reference){
      $stage='field_consumer_trajectory_equivalence'
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','compare-joint','--preparation',$preparationPath,'--log',$merged,'--scientific-event-receipt',$mergeReceipt,'--output',(Join-Path $resultDir 'trajectory_equivalence_receipt.json'))
    }
    $phaseTimings.analysis_seconds=$runTimer.Elapsed.TotalSeconds-$analysisStarted
    Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
      native_path_preparation=$package.native_path_preparation
      schema_version=1;role='mrtof_measured_joint_flight_summary';status='success';mother_particle_count=[int]$trial.mother_particle_count
      execution_status='completed';data_validity='valid';scientific_result='candidate_only';failure_stage=$null;failure_reason=$null
      recovery_action='none';result_path=$package.summary;phase_timings_seconds=$phaseTimings;elapsed_through_analysis_seconds=$runTimer.Elapsed.TotalSeconds
      launched_particle_count=[int]$trial.launched_particle_count;joint_simulation_executed=($pending.Count-gt0-or$existing.Count-gt0);gui_executed=$false
      actual_native_batch_count=($pending.Count+$existing.Count);reused_batch_count=@($final.batches|Where-Object{$records[[int]$_.index].PSObject.Properties.Name-contains'reused'}).Count
      qualification='candidate_joint_flight_only';energy_target_acceptance='not_declared';six_dimensional_match_qualified=$false;time_focus_qualified=$false
      diagnostics=Join-Path $resultDir 'diagnostics';all_upstream_and_downstream_losses_retained=$true
      dispatch_plan=$dispatch;resource_usage=$usage;batch_plan=$plan;merged_log=$merged
    })
    $stage='terminal_publication';$finalizationAttempted=$true
    $summaryDocument=Get-Content -LiteralPath $package.summary -Raw|ConvertFrom-Json -AsHashtable
    $summaryDocument.elapsed_before_finalization_seconds=$runTimer.Elapsed.TotalSeconds
    $outputs=@(Get-ChildItem -LiteralPath $resultDir,$logDir -Recurse -File|ForEach-Object{$_.FullName})
    $ownerResult=Complete-RunArtifactPowerShellOwner -Context $owner -Status success -Summary $summaryDocument -OutputPaths $outputs `
      -WritersStopped $true -WriterCompletion @{operations=@($nativeOperations|ForEach-Object{$_});resource_releases=@($resourceReleases|ForEach-Object{$_})}
    $capacity=$null;$terminalized=$true
    if($ownerResult.status-ne'success'){throw 'Prepared-joint finalization is incomplete; use ResumeFinalization.'}
    $nativeExecuted=($pending.Count-gt0-or$existing.Count-gt0)
    Write-Output "MEASURED_JOINT_TRIAL=PASS RUN_ID=$jointRunId JOINT_FLY=$nativeExecuted GUI=False RESULT=$($owner.result_path) SUMMARY=$($package.summary) TOTAL_SECONDS=$($runTimer.Elapsed.TotalSeconds)"
  }catch{
    $failureRecord=$_
    $drainError=$failureRecord.Exception.Data['simion_first_batch_drain_error']
    if($drainError-or($waveInProgress-and-not$failureRecord.Exception.Data['simion_wave_writer_completion_confirmed'])){
      $writerUnknown=$true
      try {
        Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
      native_path_preparation=$package.native_path_preparation
          schema_version=1;role='mrtof_measured_joint_flight_summary';status='writer_completion_unknown'
          reason=$failureRecord.Exception.Message;failure_stage=$stage;drain_error=[string]$drainError
          execution_status='unknown';data_validity='unknown';scientific_result='not_evaluated';failure_reason=$failureRecord.Exception.Message
          recovery_action='confirm_writer_completion_before_recovery';result_path=$package.summary;phase_timings_seconds=$phaseTimings;elapsed_seconds=$runTimer.Elapsed.TotalSeconds
          writer_confirmation=if($waveInProgress){'batch_runner_did_not_confirm_completion'}else{'first_batch_drain_failed'}
        })
      } catch { $failureRecord.Exception.Data['writer_unknown_result_error']=[string]$_ }
      if($null-ne$owner){try{
        $unknownSummary=Get-Content -LiteralPath $package.summary -Raw|ConvertFrom-Json -AsHashtable
        $null=Complete-RunArtifactPowerShellOwner -Context $owner -Status failed -Summary $unknownSummary -OutputPaths @() `
          -WritersStopped $false -WriterCompletion @{operations=@();resource_releases=@()} -OriginalFailure $failureRecord
      }catch{$failureRecord.Exception.Data['writer_unknown_finalization_error']=[string]$_}}
      throw $failureRecord
    }
    try{if(-not$terminalized-and-not$finalizationAttempted){
      $failure=$failureRecord.Exception.Message
      if($null-ne$lease){
      $release=Exit-HostResourceStage -Lease $lease -PassThru
      if($nativeOperations.Count){
        $inherited=[bool]$lease.inherited
        if($inherited){$release=Invoke-HostResourceTransaction -Request @{operation='inherit';token=[string]$lease.token}}
        $resourceReleases.Add(@{release_id='simion';completion_receipt=@{host_release=@{inherited=$inherited;token=[string]$lease.token;result=@{status=[string]$release.status;token=[string]$release.token};error=$null}}})
      }
      $lease=$null
    }
      Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
      native_path_preparation=$package.native_path_preparation
        schema_version=1;role='mrtof_measured_joint_flight_summary';status='failed';reason=$failure;failure_stage=$stage
        execution_status='failed';data_validity='unknown';scientific_result='not_evaluated';failure_reason=$failure
        recovery_action='new_run_with_explicit_predecessor';result_path=$package.summary;phase_timings_seconds=$phaseTimings;elapsed_seconds=$runTimer.Elapsed.TotalSeconds
        gui_executed=$false;qualification='failed_joint_trial_no_performance_qualification'
        drain_error=$failureRecord.Exception.Data['simion_first_batch_drain_error'];verification_error=$failureRecord.Exception.Data['simion_first_batch_verification_error']
      })
      if($null-ne$owner-and-not$finalizationAttempted){
        $finalizationAttempted=$true
        $summaryDocument=Get-Content -LiteralPath $package.summary -Raw|ConvertFrom-Json -AsHashtable
        $outputs=@(Get-ChildItem -LiteralPath $resultDir,$logDir -Recurse -File|ForEach-Object{$_.FullName})
        $null=Complete-RunArtifactPowerShellOwner -Context $owner -Status failed -Summary $summaryDocument -OutputPaths $outputs `
          -WritersStopped $true -WriterCompletion @{operations=@($nativeOperations|ForEach-Object{$_});resource_releases=@($resourceReleases|ForEach-Object{$_})} -OriginalFailure $failureRecord
        $capacity=$null
      }
    }}catch{
      $failureRecord.Exception.Data['prepared_joint_closeout_error']=[string]$_
      Write-Warning "Prepared joint closeout also failed: $_"
    }
    throw $failureRecord
  }finally{
    Restore-RunEnvironment -Names $pathEnvironmentNames -Snapshot $savedPathEnvironment
    if(-not$writerUnknown){
      $cleanupErrors=[Collections.Generic.List[string]]::new()
      if($null-ne$lease){try{Exit-HostResourceStage -Lease $lease}catch{$cleanupErrors.Add([string]$_)}}
      if($null-ne$package){try{Remove-RunPackageExecutionAlias -Package $package}catch{$cleanupErrors.Add([string]$_)}}
      foreach($guard in $guards){try{$guard.Dispose()}catch{$cleanupErrors.Add([string]$_)}}
      if($null-ne$capacity-and-not$finalizationAttempted){try{$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}catch{$cleanupErrors.Add([string]$_)}}
      if($cleanupErrors.Count){
        if($null-ne$failureRecord){$failureRecord.Exception.Data['prepared_joint_cleanup_errors']=@($cleanupErrors);Write-Warning "Prepared joint cleanup also failed: $($cleanupErrors -join '; ')"}
        else{throw "Prepared joint cleanup failed: $($cleanupErrors -join '; ')"}
      }
    }
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
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $pathContext.artifact_root "projects/$projectId") `
    -RunId $analysisRunId -Project $projectId -Mode prepared_joint_analysis -Software @('Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $recording.reason -CapacityLedgerLifecycleEnabled -PathContext $pathContext
  $script:preparedPackage=$package
  $runDir=[string]$package.artifact_run_dir
  $inputDir=Join-Path $runDir 'inputs'
  $analysisTimer=[Diagnostics.Stopwatch]::StartNew()
  $owner=$null;$capacity=$null;$failure=$null;$stage='capacity_startup'
  try {
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot ([string]$pathContext.artifact_root) `
      -RunDirectory $runDir -CommittedNewBytes ([int64]$recording.output_budget_bytes) -ProtectedPaths @($runDir) `
      -SourceReferences @(Get-PreparedJointSourceReferences -RunDirectories @($source)) -Owner "run-artifact-workflow:${projectId}:$analysisRunId"
    $stage='freeze_executable_dependencies'
    $dependencyPath=Join-Path $repoRoot 'integrations/config/runtime_dependencies.json'
    $frozen=Freeze-ConsumerDependencies -RepoRoot $repoRoot -ContractPath $dependencyPath -InputDir $inputDir -OwnerId $projectId -ConsumerId prepared_joint
    $script:pythonRoot=[string]$frozen.execution_root
    $entryIdentity=@($frozen.identities|Where-Object{$_.source_repo_path-ceq'integrations/workflows/prepared_joint/execute.ps1'})
    $frozenEntryRecord=if($entryIdentity.Count-eq1){@{path=$entryIdentity[0].snapshot_path;exists=$true;bytes=[long](Get-Item -LiteralPath $entryIdentity[0].snapshot_path).Length;sha256=$entryIdentity[0].sha256}}else{$null}
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs=[ordered]@{code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
    foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
    Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
    $frozenAnalysisContract=Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'analysis_contract.json')
    $owner=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity `
      -ResultPath $ResultPath -EntrypointPath (Join-Path $script:pythonRoot 'integrations/workflows/prepared_joint/execute.ps1') -EntrypointRecord $frozenEntryRecord `
      -CommitmentInputPaths @($frozenAnalysisContract) -Software @('Python 3.11')
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
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
      -ProtectedPaths @($runDir) -SourceReferences @(Get-PreparedJointSourceReferences -RunDirectories @($selection.protected_paths)) -RemainingCommittedNewBytes ([int64]$recording.output_budget_bytes)
    $capacity=$renewal.session
    $stage='joint_diagnostics'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight','analyze-joint',
      '--preparation',[string]$selection.preparation,'--log',[string]$selection.merged_log,'--output',(Join-Path $package.result_dir 'diagnostics'),'--analysis-contract',[string]$selection.analysis_contract)
  }catch{$failure=$_}
  $status=if($null-eq$failure){'success'}else{'failed'}
  $summary=[ordered]@{native_path_preparation=$package.native_path_preparation;schema_version=1;role='prepared_joint_analysis_summary';status=$status;source_run=$source;native_flight_executed=$false;qualification='post_hoc_analysis_only';elapsed_before_finalization_seconds=$analysisTimer.Elapsed.TotalSeconds}
  if($null-ne$failure){$summary.reason=$failure.Exception.Message;$summary.failure_stage=$stage}
  if($null-eq$owner){
    if($null-ne$capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
    if($null-ne$failure){throw $failure};throw 'Analysis finalization owner was not initialized.'
  }
  $outputs=@(Get-ChildItem -LiteralPath $package.result_dir -Recurse -File|ForEach-Object{$_.FullName})
  $ownerResult=Complete-RunArtifactPowerShellOwner -Context $owner -Status $status -Summary $summary -OutputPaths $outputs `
    -WritersStopped $true -WriterCompletion @{operations=@();resource_releases=@()} -OriginalFailure $failure
  if($null-ne$failure){throw $failure}
  if($ownerResult.status-ne'success'){throw 'Prepared-joint analysis finalization is incomplete; use ResumeFinalization.'}
  Write-Output "PREPARED_JOINT_ANALYSIS=PASS RUN_ID=$analysisRunId NATIVE_FLY=False"
}
if($PSCmdlet.ParameterSetName-eq'Analysis'){
  . (Join-Path $repoRoot 'common/host_execution_lease.ps1')
  $analysisLease=Enter-HostExecutionLease -StatePath $pathContext.host_resource_state_path -Role GATE -Stage unclassified -RunId $RunId
  $analysisOkay=$false
  try{Invoke-PreparedJointAnalysis;$analysisOkay=$true}
  finally{Exit-HostExecutionLease -Lease $analysisLease -Outcome $(if($analysisOkay){'success'}else{'failed'}) -RunId $RunId}
}else{Invoke-PreparedJointTrial}
