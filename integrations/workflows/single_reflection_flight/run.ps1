<#
.SYNOPSIS
Run the supported single-reflection assembly over its declared propagation range.
.DESCRIPTION
The request declares the physical assembly, source, clock, fields and numerics.
Preparation, new or reusable fields, workbench, flight and analysis are connected
by this owner. Simulation path selection, input sources and complete examples:
integrations/README.md (simulation path selection).
propagation_scope defaults to declared_source_to_terminal: a recorded-state
source starts a continuous segment at its snapshot time. original_birth_to_terminal
also includes the earlier propagation and state re-release in that source's history.
No intermediate geometric handoff plane is implied by a volume snapshot.
#>
[CmdletBinding(DefaultParameterSetName="Run")]
param(
  [Parameter(Mandatory,ParameterSetName="Run")][string]$Request,
  [Parameter(Mandatory,ParameterSetName="Run")][string]$ExecutionBudgetPath,
  [Parameter(Mandatory,ParameterSetName="Resume")][switch]$ResumeFinalization,
  [string]$ResultPath='',
  [string]$RunId='',
  [Parameter(ParameterSetName='Run')][switch]$FieldDesignOnly,
  [Parameter(ParameterSetName='Run')][switch]$WorkbenchOnly,
  [Parameter(ParameterSetName='Run')][switch]$Fly,
  [string]$Python='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)

# This is the public run owner.  execute.ps1 owns scientific preparation,
# frozen executable dependencies, and updates the owner's capacity reservation;
# this wrapper owns the one run package, capacity session and terminal seal.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(-not$ResumeFinalization-and([int][bool]$FieldDesignOnly+[int][bool]$WorkbenchOnly+[int][bool]$Fly)-gt1){
  throw 'Select at most one of FieldDesignOnly, WorkbenchOnly or Fly.'
}
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $RepoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
if($ResumeFinalization){
  if(-not$ResultPath){throw 'ResumeFinalization requires the original ResultPath.'}
  $prior=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($RunId-and(Split-Path -Leaf $prior.run_directory)-ne$RunId){throw 'Result belongs to a different run.'}
  $outcome=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $prior.run_directory 'inputs/execution_request.json') -ResultPath $ResultPath -ResumeFinalization
  Write-Output $outcome
  if($outcome.status-ne'success'){throw 'Single-reflection finalization remains incomplete; inspect Result recovery_action.'}
  return
}
$stage=if($FieldDesignOnly){'field_design'}elseif($WorkbenchOnly){'workbench'}else{'fly'}
$runClock=[Diagnostics.Stopwatch]::StartNew()
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$Request=(Resolve-Path -LiteralPath $Request).Path
$ExecutionBudgetPath=(Resolve-Path -LiteralPath $ExecutionBudgetPath).Path
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
$Python=(Resolve-Path -LiteralPath $Python).Path
. (Join-Path $RepoRoot 'common/paths/workspace_paths.ps1')
$pathContext=Resolve-WorkspacePaths -SourceRoot $RepoRoot -Python $Python
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__single-reflection-flight'}

$project='instrument_assembly'
$workspace=Split-Path -Parent $RepoRoot
$artifacts=[string]$pathContext.artifact_root
$package=$null
$capacity=$null
$writerUnknown=$false;$failure=$null;$ownerContext=$null;$scientificSummary=$null
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
$phaseTimings=[ordered]@{};$summaryClock=$null
$stageName='create_run_package'
$retentionReason='Retain native single-reflection fields, saved workbench, frozen source-cohort flight evidence, and requested saved-workbench checks for solver review.'
$pathEnvironmentNames=@('MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY','SIMULATION_PYTHON_EXE')
$savedPathEnvironment=Save-RunEnvironment -Names $pathEnvironmentNames
try {
  $env:SIMULATION_PYTHON_EXE=$Python
  $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot `
    -ArtifactRoot (Join-Path $artifacts "projects/$project") -RunId $RunId -Project $project `
    -Mode ("single_reflection_{0}" -f $stage) -Software @('SIMION 2020','Python 3.11','PowerShell 7') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $retentionReason -CapacityLedgerLifecycleEnabled -PathContext $pathContext `
    -AdditionalDirectories @('simion') `
    -ExpectedExecutionRelativePaths @(
      'inputs/runtime_snapshot/projects/single_reflection_oa_tof_mass_analyzer/simion/reflectron/oatof_reflectron_ideal_10_5.gem'
    )
 $parentEnvironment=(Get-RunNativeExecutionContext -Package $package -Paths @()).environment
 foreach($key in $parentEnvironment.Keys){[Environment]::SetEnvironmentVariable([string]$key,[string]$parentEnvironment[$key],'Process')}
  # Preparation initially needs no payload commitment. The delegated native
  # stage renews this same session from its frozen engineering budget.
  $ownerProtectedPaths=@($package.artifact_run_dir)
  $sourceProtectionCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.continuation import source_capacity_projection
print(json.dumps(source_capacity_projection(artifact_root=Path(sys.argv[1]),request_path=Path(sys.argv[2]))))
'@
  $sourceProtection=Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    $output=& $Python -B -c $sourceProtectionCode $artifacts $Request
    if($LASTEXITCODE-ne0){throw 'Single-reflection explicit source protection projection failed.'}
    return ($output-join"`n")|ConvertFrom-Json -AsHashtable -Depth 100
  }
  $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $artifacts `
    -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -ProtectedPaths $ownerProtectedPaths `
    -SourceReferences @($sourceProtection.source_references) `
    -Owner ("run-artifact-workflow:{0}:{1}"-f$project,$RunId)
  Write-RunJson -Path (Join-Path $package.result_dir 'artifact_capacity_gate_startup.json') -Depth 20 -Value $capacity
  # The public owner is part of the executable decision path.  Freeze this
  # small script once; execute.ps1 then freezes its own runtime closure.
  $runnerInput=Join-Path $package.input_dir 'run_single_reflection_flight.ps1'
  Copy-VerifiedRunInput -Source $PSCommandPath -Destination $runnerInput|Out-Null
  $initialConfig=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $initialConfig.inputs.public_runner=$runnerInput
  Write-RunJson -Path $package.run_config -Depth 100 -Value $initialConfig
  $ownerBudget=Copy-VerifiedRunInput -Source $ExecutionBudgetPath -Destination (Join-Path $package.input_dir 'owner_execution_budget.json')
  $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $Python -RepoRoot $RepoRoot -Package $package -CapacitySession $capacity `
    -EntrypointPath $runnerInput -CommitmentInputPaths @($ownerBudget) -ResultPath $ResultPath -Software @('SIMION 2020','Python 3.11','PowerShell 7')
  $ResultPath=[string]$ownerContext.result_path
  $phaseTimings.owner_preparation=[double]$runClock.Elapsed.TotalSeconds

  $stageName='execute_frozen_workflow'
  $executeArguments=@{
    RunPackage=$package;Request=$Request;ExecutionBudgetPath=$ownerBudget;OutputDirectory=[string]$package.artifact_run_dir
    RepoRoot=$RepoRoot;Python=$Python;WorkflowCapacitySession=$capacity;NativeOperations=$nativeOperations;ResourceReleases=$resourceReleases;PhaseTimings=$phaseTimings
  }
  if($stage-eq'field_design'){$executeArguments.FieldDesignOnly=$true}
  elseif($stage-eq'workbench'){$executeArguments.WorkbenchOnly=$true}
  else{$executeArguments.Fly=$true}
  & (Join-Path $RepoRoot 'integrations/workflows/single_reflection_flight/execute.ps1') @executeArguments
  $summaryClock=[Diagnostics.Stopwatch]::StartNew()

  $preparationReceipt=Get-Content -LiteralPath (Join-Path $package.result_dir 'single_reflection/preparation_receipt.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $replayRequested=[bool]$preparationReceipt.default_replay_requested
  $defaultReplaySummary=@{requested=$replayRequested;status=$(if($replayRequested){'not_executed'}else{'not_requested'});native_fly_performed=$false}
  if($stage-eq'fly'){
    $finalWorkbench=Get-Content -LiteralPath (Join-Path $package.result_dir 'single_reflection/workbench_preparation.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    $defaultReplaySummary=$finalWorkbench.default_replay_verification
  }
  $stageName='terminal_publication'
  $sourceProvenancePath=Join-Path $package.artifact_run_dir 'inputs/source_provenance.json'
  $sourceProvenance=Get-Content -LiteralPath $sourceProvenancePath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $stateRestart=$sourceProvenance.source_kind-eq'recorded_pre_pulse_state'
  $propagationScope=[string]$sourceProvenance.propagation_scope
  if($propagationScope-notin@('declared_source_to_terminal','original_birth_to_terminal')){throw 'Frozen source provenance has an unsupported propagation_scope.'}
  $birthHistoryPath=if($stateRestart){'segmented_handoff'}else{'continuous_assembly'}
  $simulationPath=if($propagationScope-eq'original_birth_to_terminal'){$birthHistoryPath}else{'continuous_assembly'}
  $validationContractPath=$null
  if($sourceProvenance.ContainsKey('input_records')-and$sourceProvenance.input_records.ContainsKey('validation_contract')){
    $validationContractPath=Join-Path $package.artifact_run_dir 'inputs/functional_validation.json'
  }
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $config.parameters=[ordered]@{
    workflow='single_reflection_flight';requested_stage=$stage;verify_saved_workbench_replay=$replayRequested;scientific_request=(Join-Path $package.input_dir 'request.json')
    execution_budget=(Join-Path $package.input_dir 'resolved_integration_engineering_budget.json');gui_executed=$false
    propagation_scope=$propagationScope
    validation_contract=$validationContractPath
  }
  Write-RunJson -Path $package.run_config -Depth 100 -Value $config
  $nativeFlightCount=0;$reusedFlightCount=0;$nativeWorkbenchCount=0
  $flightRecords=Join-Path $package.result_dir 'single_reflection/flight_execution_records.json'
  if(Test-Path -LiteralPath $flightRecords){$nativeFlightCount=@(Get-Content -LiteralPath $flightRecords -Raw|ConvertFrom-Json).Count}
  foreach($receiptName in @('discovery_workbench_preparation.json','workbench_preparation.json')){
    $receiptPath=Join-Path $package.result_dir "single_reflection/$receiptName"
    if(Test-Path -LiteralPath $receiptPath){
      $wb=Get-Content -LiteralPath $receiptPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
      $cases=if($wb.ContainsKey('batches')){@($wb.batches)}else{@($wb)}
      foreach($case in $cases){
        if($case.ContainsKey('continuation_source')){$reusedFlightCount++}
        elseif($case.ContainsKey('native_workbench_execution')){$nativeWorkbenchCount+=@($case.native_workbench_execution).Count}
        if($case.ContainsKey('replay_continuation_source')){$reusedFlightCount++}
      }
    }
  }
  $scientificSummary=[ordered]@{
    native_path_preparation=$package.native_path_preparation
    schema_version=1;role='single_reflection_flight_run_summary';status='success';requested_stage=$stage
    default_replay=$defaultReplaySummary
    simulation_path=$simulationPath;trajectory_execution=$(if($nativeFlightCount-gt0){if($stateRestart){'continuous_after_recorded_state_restart'}else{'continuous_from_declared_source'}}elseif($reusedFlightCount-gt0){'reused_complete_batches'}else{'not_executed'})
    propagation_scope=$propagationScope;original_birth_to_terminal_path=$birthHistoryPath
    propagation_start=$(if($propagationScope-eq'original_birth_to_terminal'){'original_birth_population'}elseif($stateRestart){'recorded_pre_pulse_volume_state'}else{'declared_source_population'})
    propagation_end='declared_detector_observation_or_actual_terminal'
    continuous_segment_start=$(if($stateRestart){'recorded_pre_pulse_volume_state'}else{'declared_source_population'})
    continuous_segment_executed=($nativeFlightCount-gt0)
    composition_plan_path=Join-Path $package.artifact_run_dir 'inputs/composition_plan.json'
    actual_scope_path=Join-Path $package.artifact_run_dir 'inputs/frontend_geometry.json'
    source_provenance_path=$sourceProvenancePath
    validation_contract_path=$validationContractPath
    source_kind=$sourceProvenance.source_kind;source_instance_id=$sourceProvenance.source_instance_id
    state_restart=$stateRestart
    state_restart_executed=($stateRestart-and$nativeFlightCount-gt0)
    upstream_history_recomputed=$false
    restart_state_time_us=$(if($stateRestart){$sourceProvenance.restart_state_time_us}else{$null})
    restart_plane=$null
    state_time_semantics=$sourceProvenance.state_time_semantics
    source_frame_id=$sourceProvenance.source_frame_id;target_frame_id=$sourceProvenance.target_frame_id
    clock_epoch_id=$sourceProvenance.clock_epoch_id
    continued_particle_ids=$(if($stateRestart){,@($sourceProvenance.continued_particle_ids)}else{$null})
    original_mother_particle_ids=$(if($stateRestart){,@($sourceProvenance.original_mother_particle_ids)}else{$null})
    original_mother_particle_count=$(if($stateRestart){$sourceProvenance.original_mother_particle_count}else{$sourceProvenance.particle_count})
    uncontinued_mother_particle_ids=@(if($stateRestart){$sourceProvenance.uncontinued_mother_particle_ids})
    execution_status='completed';scientific_result='not_qualified__see_frozen_stage_receipts'
    elapsed_before_finalization_seconds=$runClock.Elapsed.TotalSeconds
    field_design_executed=$true;workbench_executed=($stage-eq'workbench'-or$nativeWorkbenchCount-gt0);fly_executed=($nativeFlightCount-gt0)
    native_flight_batch_count=$nativeFlightCount;reused_flight_batch_count=$reusedFlightCount
    gui_executed=$false;qualification='workflow_execution_only__physical_qualification_is_defined_by_frozen_stage_receipts'
  }
  $phaseTimings.owner_summary=[double]$summaryClock.Elapsed.TotalSeconds
}catch{
  $failure=$_;$data=$failure.Exception.Data
  if($null-eq$capacity-and$data.Contains('capacity_session')){
    $capacity=$data['capacity_session']
    try{if($package){Write-RunJson -Path (Join-Path $package.log_dir 'capacity_session.json') -Value $capacity -Depth 100}}
    catch{$failure.Exception.Data['capacity_session_persistence_error']=$_}
  }
  if($data.Contains('single_reflection_failure_stage')){$stageName=[string]$data['single_reflection_failure_stage']}
  $writerUnknown=([bool]$data['simion_first_batch_writer_unknown']-or[bool]$data['simion_first_batch_drain_error']-or
    ($data.Contains('observed_process_exit_confirmed')-and-not[bool]$data['observed_process_exit_confirmed'])-or
    ($data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$data['simion_wave_writer_completion_confirmed']))
}finally{
  try{
    if(@($nativeOperations|Where-Object{-not$_.observation.exit_confirmed}).Count){$writerUnknown=$true}
    if(-not$ownerContext-and-not$writerUnknown){
      try{if($capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity};if($package){Remove-RunPackageExecutionAlias -Package $package}}
      catch{if($failure){$failure.Exception.Data['bootstrap_cleanup_error']=$_}else{$failure=$_}}
    }
    if($ownerContext-and-not$ownerContext.completion_written){
      $summary=if($null-ne$scientificSummary){$scientificSummary}else{[ordered]@{schema_version=1;role='single_reflection_flight_run_summary';requested_stage=$stage;gui_executed=$false}}
      $summary.execution_status=if($writerUnknown){'writer_completion_unknown'}elseif($failure){'failed'}else{'completed'}
      $summary.data_validity=if($failure){'incomplete'}else{'valid'}
      $summary.scientific_result=if($failure){'NOT_EVALUATED'}else{'not_qualified__see_frozen_stage_receipts'}
      $summary.failure_stage=if($failure){$stageName}else{$null};$summary.failure_reason=if($failure){$failure.Exception.Message}else{$null}
      $summary.recovery_action=if($writerUnknown){'inspect_writer_completion'}elseif($failure){'inspect_preserved_stage_evidence_or_resume_finalization'}else{'none'}
      $summary.secondary_errors=@(if($failure){foreach($key in @('scientific_evidence_binding_error','host_release_error','asset_release_error','capacity_release_error','capacity_session_persistence_error','bootstrap_cleanup_error')){if($failure.Exception.Data.Contains($key)){[string]$failure.Exception.Data[$key]}}})
      $summary.result_path=$ResultPath;$summary.phase_timings_seconds=$phaseTimings;$summary.total_elapsed_seconds=$runClock.Elapsed.TotalSeconds
      $inputPrefix=(Join-Path $package.artifact_run_dir 'inputs')+[IO.Path]::DirectorySeparatorChar
      $outputs=@(Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Where-Object{
        $_.Name-notin@('run_config.json','run_manifest.json')-and-not$_.FullName.StartsWith($inputPrefix,[StringComparison]::OrdinalIgnoreCase)
      }|ForEach-Object FullName)
      $ownerContext.session=$capacity
      try{$outcome=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $(if($failure){'failed'}else{'success'}) -Summary $summary -OutputPaths $outputs `
        -WriterCompletion @{operations=@($nativeOperations.ToArray());resource_releases=@($resourceReleases.ToArray())} -WritersStopped (-not$writerUnknown) -OriginalFailure $failure;Write-Output $outcome}
      catch{if($failure){$failure.Exception.Data['finalization_error']=$_}else{$failure=$_}}
    }
  }finally{Restore-RunEnvironment -Names $pathEnvironmentNames -Snapshot $savedPathEnvironment}
}
if($failure){throw $failure}
Write-Output ("SINGLE_REFLECTION_RUN=PASS RUN_ID={0} STAGE={1} RESULT={2} TOTAL_SECONDS={3:F3} GUI=False"-f$RunId,$stage,$ResultPath,$runClock.Elapsed.TotalSeconds)
