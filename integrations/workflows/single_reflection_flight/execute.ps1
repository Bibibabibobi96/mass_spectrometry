[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Request,
  [pscustomobject]$RunPackage=$null,
  [switch]$PrepareOnly,
  [switch]$FieldDesignOnly,
  [switch]$WorkbenchOnly,
  [switch]$Fly,
  [string]$ExecutionBudgetPath='',
  [Parameter(Mandatory)][string]$OutputDirectory,
  [string]$Python='',
  [pscustomobject]$WorkflowCapacitySession=$null,
  $NativeOperations=$null,$ResourceReleases=$null,[Collections.IDictionary]$PhaseTimings=$null,
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
# The caller owns the managed run, capacity reservation and terminal publication.
# FieldDesignOnly builds the declared working fields and downstream provider fields.
# Fly schedules original frozen source rows over the same complete assembly,
# Saved-workbench fresh-process replay is performed only when explicitly requested.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(([int][bool]$PrepareOnly+[int][bool]$FieldDesignOnly+[int][bool]$WorkbenchOnly+[int][bool]$Fly)-ne1){throw 'Select exactly one PrepareOnly, FieldDesignOnly, WorkbenchOnly or Fly stage.'}
if((-not$PrepareOnly)-and-not$ExecutionBudgetPath){throw 'Native execution requires ExecutionBudgetPath.'}
if((-not$PrepareOnly)-and$null-eq$RunPackage){throw 'Native single-reflection stages require the public run owner package; use run.ps1.'}
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$Request=(Resolve-Path -LiteralPath $Request).Path
# A managed runner may pass its execution junction here.  Preserve that lexical
# path for every SIMION argument; resolving it would silently restore the long
# artifact path that the junction exists to avoid.
if(-not(Test-Path -LiteralPath $OutputDirectory -PathType Container)){
  throw 'Single-reflection output directory is missing.'
}
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_workflow.ps1')
. (Join-Path $RepoRoot 'integrations/runtime/dependencies.ps1')
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
$Python=(Resolve-Path -LiteralPath $Python).Path
$configPath=Join-Path $OutputDirectory 'run_config.json'
if(-not(Test-Path -LiteralPath $configPath -PathType Leaf)){
  throw 'Single-reflection output must already be owned by a managed run.'
}
$config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
$pathContext=if($null-ne$RunPackage){$RunPackage.path_context}else{$config.paths}
if($config.project-cne'instrument_assembly'){
  throw 'Single-reflection managed run owner must be instrument_assembly.'
}
$validation=& $Python (Join-Path $RepoRoot 'common/contracts/artifact_naming.py') run ([string]$config.run_id)
if($LASTEXITCODE-ne0-or-not($validation-match'^ARTIFACT_ID=PASS ')){
  throw 'Managed run has an invalid run identity.'
}
$manifestPath=Join-Path $OutputDirectory 'run_manifest.json'
if(Test-Path -LiteralPath $manifestPath){
  $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
  if($manifest.status-cne'checkpoint'){throw 'Single-reflection execution cannot modify a terminal run.'}
}
$inputs=Join-Path $OutputDirectory 'inputs'
if(-not(Test-Path -LiteralPath $inputs -PathType Container)){
  throw 'Managed run inputs directory is missing.'
}
$frozen=Freeze-ConsumerDependencies -RepoRoot $RepoRoot `
  -ContractPath (Join-Path $RepoRoot 'integrations/config/runtime_dependencies.json') `
  -InputDir $inputs -OwnerId instrument_assembly -ConsumerId single_reflection_flight
$frozenExecutionRoot=Join-Path $OutputDirectory 'inputs/runtime_snapshot'
if(-not(Test-Path -LiteralPath $frozenExecutionRoot -PathType Container)){
  throw 'Frozen single-reflection runtime snapshot is missing.'
}
if(-not$config.ContainsKey('inputs')){$config.inputs=@{}}
$config.inputs.code_inventory=$frozen.code_inventory_path
$config.inputs.dependency_contract=$frozen.dependency_contract_path
foreach($identity in $frozen.identities){$config.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
Write-RunJson -Path $configPath -Depth 100 -Value $config
$prepareCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.prepare import FROZEN_NAMES,prepare
request,run=map(Path,sys.argv[1:3])
try:
    receipt=prepare(request,run)
finally:
    # Bind actual frozen evidence even when scientific validation fails. The
    # caller's normal failed publication will establish these byte identities.
    config_path=run/'run_config.json'
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    for name,filename in dict(request='request.json',**FROZEN_NAMES).items():
        path=run/'inputs'/filename
        if path.is_file():
            config['inputs'][name]=str(path)
    for path in (run/'inputs'/'components').glob('*/resolved_design.json'):
        config['inputs']['instance_design__'+path.parent.name]=str(path)
    config_path.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(receipt,allow_nan=False))
'@
$receipt=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
  $result=& $Python -B -c $prepareCode $Request $OutputDirectory
  if($LASTEXITCODE-ne0){throw 'Single-reflection geometry and source preparation failed.'}
  return $result|ConvertFrom-Json -AsHashtable -Depth 100
}
$config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
foreach($name in $receipt.input_records.Keys){$config.inputs[$name]=[string]$receipt.input_records[$name].path}
Write-RunJson -Path $configPath -Depth 100 -Value $config
$resultDirectory=Join-Path $OutputDirectory 'results/single_reflection'
New-Item -ItemType Directory -Path $resultDirectory -Force|Out-Null
Write-RunJson -Path (Join-Path $resultDirectory 'preparation_receipt.json') -Depth 100 -Value $receipt
$defaultReplayRequested=[bool]$receipt.default_replay_requested
$sourceProvenance=Get-Content -LiteralPath (Join-Path $OutputDirectory 'inputs/source_provenance.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
$continuationSource=($sourceProvenance.source_kind-eq'recorded_pre_pulse_state')
$hasFrozenFrontendFields=$receipt.input_records.ContainsKey('frontend_fields')
$batchContinuation=$receipt.input_records.ContainsKey('continuation_parent_manifest')
if($PrepareOnly){
  Write-Output 'SINGLE_REFLECTION_PREPARATION=PASS SOLVER_EXECUTED=False QUALIFICATION=geometry_preparation_only'
  return
}
. (Join-Path $RepoRoot 'integrations/runtime/engineering_budget.ps1')
. (Join-Path $RepoRoot 'common/resource_budget_support.ps1')
. (Join-Path $frozen.execution_root 'integrations/runtime/frontend_flight_support.ps1')
. (Join-Path $RepoRoot 'common/simion/short_pa_path_support.ps1')
. (Join-Path $frozen.execution_root 'integrations/workflows/single_reflection_flight/field_stage.ps1')
$artifacts=[string]$pathContext.artifact_root
$failure=$null;$lease=$null;$capacity=$WorkflowCapacitySession;$ownsCapacity=($null-eq$WorkflowCapacitySession);$okay=$false;$stageElapsed=$null;$writerUnknown=$false
$downstreamExecution=@()
$workbenchExecution=@()
$allWorkbenchExecution=@()
$flightExecution=@()
$workbench=$null
$workbenchOkay=$false
$flightCollection=@()
$phaseCollection=@()
$nativePhases=@()
$discoverPulse=$false
$decisionRecord=$null
$paGuards=[Collections.Generic.List[string]]::new()
$frontendIobRetentionVerified=$false
$workbenchReceiptPath=Join-Path $resultDirectory 'workbench_preparation.json'
$workbenchEvidencePath=Join-Path $resultDirectory 'workbench_execution_records.json'
$downstreamEvidencePath=Join-Path $resultDirectory 'downstream_execution_records.json'
$downstreamPlanPath=$null
$flightEvidencePath=Join-Path $resultDirectory 'flight_execution_records.json'
$wallClockWarningStages=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
function Get-InstrumentNativePriorityOccupancyEvidence {
  param([Parameter(Mandatory)][AllowEmptyString()][string]$OutputText,[Parameter(Mandatory)]$ExpectedCounts)
  $markers=[regex]::Matches($OutputText,'(?m)^SINGLE_REFLECTION_NATIVE_PRIORITY_OCCUPANCY=')
  $proof=[regex]::Match($OutputText,'(?m)^SINGLE_REFLECTION_NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=([0-9]+) OBSERVED=([0-9]+) SCOPE=declared_points_only\r?$')
  if($markers.Count-ne1-or-not$proof.Success-or[long]$proof.Groups[1].Value-lt1-or
      [long]$proof.Groups[1].Value-ne[long]$ExpectedCounts.checked_points-or
      [long]$proof.Groups[2].Value-ne[long]$ExpectedCounts.observation_only_points){
    throw 'Workbench native priority/occupancy point evidence missing, repeated, incomplete or differs from frozen point counts.'
  }
  return @{status='success';checked_points=[long]$proof.Groups[1].Value;
    observation_only_points=[long]$proof.Groups[2].Value}
}

function Confirm-InstrumentIobVerification {
  param([ValidateSet('after_build','after_first_fly')][string]$Operation,$Case,$BuildResult,[string]$Phase,[string]$RunDirectory,[string]$SimionExe,$Limits,[string]$Python,[string]$RepoRoot)
  $name=[string]$Case.case_id
  if($Operation-eq'after_first_fly'){
    $null=Invoke-FrontendRuntimePython -Python $Python -RepoRoot $RepoRoot -RunDirectory $RunDirectory `
      -Name "$Phase.first-batch.controls-after" -Arguments @('-m','integrations.workflows.single_reflection_flight.runtime',
      '--run',$RunDirectory,'--verify-controls',([string]$Case.receipt_path)) -Json
    return
  }
  $result=$BuildResult
    $Case|Add-Member -NotePropertyName native_workbench_execution -NotePropertyValue @(@{
      operation='build';argv=@($Case.iob_builder_arguments);exit_code=$result.exit_code;
      stdout_path=(Join-Path $RunDirectory "logs/$Phase.$name.assembly.stdout.log");
      stderr_path=(Join-Path $RunDirectory "logs/$Phase.$name.assembly.stderr.log");
      usage_path=(Join-Path $RunDirectory "logs/$Phase.$name.assembly.resource_usage.json")}) -Force
    Write-RunJson -Path ([string]$Case.receipt_path) -Value $Case -Depth 100
    if(-not(Get-Content -LiteralPath (Join-Path $RunDirectory "logs/$Phase.$name.assembly.stdout.log") -Raw).Contains('SINGLE_REFLECTION_IOB=PASS')){
      throw "Instrument IOB build completion marker missing: $name"
    }
    $verifyLog=Join-Path $RunDirectory "logs/$Phase.$name.reopen.stdout.log"
    $verificationContext=Get-RunNativeExecutionContext -Package $RunPackage -Paths (@([string]$Case.working_directory,[string]$Case.iob_path)+@($Case.iob_verify_arguments|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})) -Tool SIMION
    try{
    $verified=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $RunDirectory -FilePath $SimionExe `
      -ArgumentList (Project-RunPath -Paths ([string[]]$Case.iob_verify_arguments) -ArtifactRunDir $RunPackage.artifact_run_dir -RunDir $verificationContext.run_dir -Python $Python) -WorkingDirectory $verificationContext.projected_paths[0] -Environment $verificationContext.environment `
      -UsagePath (Join-Path $RunDirectory "logs/$Phase.$name.reopen.resource_usage.json") `
      -RedirectStandardOutput $verifyLog -RedirectStandardError (Join-Path $RunDirectory "logs/$Phase.$name.reopen.stderr.log")
      if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId "$Phase.$name.reopen" -ProcessRecord $verified}
    }catch{
      if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId "$Phase.$name.reopen" -ExceptionData $_.Exception.Data}
      throw
    }
    $Case.native_workbench_execution+=@(@{operation='verify';argv=@($Case.iob_verify_arguments);exit_code=$verified.exit_code;
      stdout_path=$verifyLog;stderr_path=(Join-Path $RunDirectory "logs/$Phase.$name.reopen.stderr.log");
      usage_path=(Join-Path $RunDirectory "logs/$Phase.$name.reopen.resource_usage.json")})
    Write-RunJson -Path ([string]$Case.receipt_path) -Value $Case -Depth 100
    $verifyOutput=Get-Content -LiteralPath $verifyLog -Raw
    if($verified.resource_budget_exceeded-or[int]$verified.exit_code-ne0-or
       -not$verifyOutput.Contains('SINGLE_REFLECTION_IOB_REOPEN=PASS')){
      throw "Instrument saved IOB reopen failed: $name"
    }
    $Case.native_workbench_execution[-1].native_priority_occupancy_validation=Get-InstrumentNativePriorityOccupancyEvidence `
      -OutputText $verifyOutput -ExpectedCounts $Case.native_priority_occupancy_expected_counts
    $bound=Invoke-FrontendRuntimePython -Python $Python -RepoRoot $RepoRoot -RunDirectory $RunDirectory `
      -Name "$Phase.$name.bind-controls" -Arguments @('-m','integrations.workflows.single_reflection_flight.runtime',
        '--run',$RunDirectory,'--verify-controls',([string]$Case.receipt_path)) -Json
    $Case.outputs|Add-Member -NotePropertyName iob -NotePropertyValue $bound.iob_record -Force
    Write-RunJson -Path ([string]$Case.receipt_path) -Value $Case -Depth 100
}

function Initialize-InstrumentIobPaCopies {
  param($Prepared)
  if(-not$Prepared.ContainsKey('iob_pa_copies')){return}
  $missing=@($Prepared.iob_pa_copies|Where-Object{-not(Test-Path -LiteralPath ([string]$_.destination) -PathType Leaf)})
  [long]$newBytes=0
  foreach($copy in $missing){$newBytes+=[long]$copy.source_record.bytes}
  if($newBytes){
    $updated=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
      -RemainingCommittedNewBytes ([long]$capacity.committed_new_bytes+$newBytes)
    $script:capacity=$updated.session
  }
  foreach($copy in $Prepared.iob_pa_copies){
    $source=$copy.source_record
    $destination=[string]$copy.destination
    if(-not(Test-Path -LiteralPath $destination -PathType Leaf)){
      $null=New-ShortPaCopy -Source ([string]$source.path) -Destination $destination `
        -ExpectedBytes ([long]$source.bytes) -ExpectedSha256 ([string]$source.sha256) -GuardDestinationReadOnly
      try {$null=Publish-ShortPaCopyDestination -Path $destination -KeepDestinationGuard}
      catch {Remove-ShortPaCopy -Path $destination;throw}
      # Track the transferred owner before any later capacity update can fail.
      $paGuards.Add($destination)
      $null=Protect-ImmutablePaSource -Source $destination -ExpectedBytes ([long]$source.bytes) -ExpectedSha256 ([string]$source.sha256)
      $updated=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
        -RemainingCommittedNewBytes ([long]$capacity.committed_new_bytes-[long]$source.bytes)
      $script:capacity=$updated.session
    }
    if($destination-notin$paGuards){
      $null=Protect-ImmutablePaSource -Source $destination -ExpectedBytes ([long]$source.bytes) -ExpectedSha256 ([string]$source.sha256)
      $paGuards.Add($destination)
    }
  }
}
function Confirm-InstrumentFrontendIobRetention {
  # Saving a persistent IOB requires common owner retention, beyond the
  # execution lease. Ordinary FieldDesignOnly consumption has no such demand.
  if($script:frontendIobRetentionVerified){return}
  $code=@'
import json,sys
from pathlib import Path
from common.simion.pa_family_cache import validate_pa_family_cache_generation
stage=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
seen=set()
for domain in stage['domains']:
    for member in domain['working_points']:
        generation=Path(member['generation_directory'])
        if str(generation) in seen: continue
        seen.add(str(generation))
        validate_pa_family_cache_generation(generation,
            expected_cache_key=member['cache_key'],
            expected_filenames=member['cache_filenames'],
            verify_payload=False, require_publication_pin=True)
'@
  Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
    & $Python -B -c $code ([string]$field.cache_receipt)
    if($LASTEXITCODE-ne0){throw 'Persistent frontend IOB requires its exact common generation publication pin.'}
  }
  $script:frontendIobRetentionVerified=$true
}
function Write-InstrumentWallClockWarning {
  param($Limits=$budget.limits,$Elapsed=$stageElapsed,[string]$Stage='Instrument field design')
  if($Elapsed.Elapsed.TotalSeconds -gt [double]$Limits.wall_clock_seconds -and $wallClockWarningStages.Add($Stage)){
    Write-Warning ('RESOURCE_BUDGET_WARNING=wall_clock_seconds STAGE={0} MEASURED_SECONDS={1:N3} LIMIT_SECONDS={2}' -f
      $Stage,$Elapsed.Elapsed.TotalSeconds,$Limits.wall_clock_seconds)
  }
}
$evidenceCode=@'
import json,sys
from pathlib import Path
from common.contracts.write_run_manifest import file_record
rows=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
for row in rows:
    for kind in ("stdout","stderr","usage"):
        path=Path(row.pop(kind+"_path"))
        row[kind+"_record"]=file_record(path) if path.is_file() else None
Path(sys.argv[2]).write_text(json.dumps(rows,indent=2)+"\n",encoding="utf-8",newline="\n")
'@
function Write-NativeExecutionEvidence {
  param([object[]]$Records,[string]$Path)
  # Batch records scale with the actual run; transport only this small-file
  # path across the Windows process command line, never the JSON payload.
  $inputPath=$Path+'.input.json'
  Write-RunJson -Path $inputPath -Value @($Records) -Depth 30
  Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
    & $Python -B -c $evidenceCode $inputPath $Path
    if($LASTEXITCODE-ne0){throw 'Native evidence projection failed.'}
  }
  Remove-Item -LiteralPath $inputPath
}
function Get-InstrumentSourceProtectionProjection {
  param([string[]]$BorrowedPaths=@())
  $code=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.continuation import source_capacity_projection
value=json.load(sys.stdin)
print(json.dumps(source_capacity_projection(artifact_root=Path(sys.argv[1]),preparation=value['preparation'],borrowed_paths=value['borrowed_paths'])))
'@
  $payload=@{preparation=$receipt;borrowed_paths=@($BorrowedPaths)}
  Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
    $result=($payload|ConvertTo-Json -Depth 100 -Compress)|& $Python -B -c $code $artifacts
    if($LASTEXITCODE-ne0){throw 'Single-reflection explicit source protection projection failed.'}
    return ($result-join"`n")|ConvertFrom-Json -AsHashtable -Depth 100
  }
}
function Register-InstrumentContinuationInputs {
  param($Workbench)
  $config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $borrowed=@()
  foreach($name in @('continuation','replay_continuation')){
    if(-not$Workbench.ContainsKey($name)){continue}
    $planned=$Workbench[$name]
    foreach($unit in $planned.plan.units){
      if($unit.action-ne'reuse'){continue}
      $index=0
      foreach($artifact in $unit.terminal_outputs){
        $role='continuation_artifact_'+$planned.phase+'_'+$unit.key+'_'+$index
        $config.inputs[$role]=[string]$artifact.path
        $borrowed+=[string]$artifact.path
        $index++
      }
    }
  }
  Write-RunJson -Path $configPath -Value $config -Depth 100
  if($borrowed.Count){
    $projection=Get-InstrumentSourceProtectionProjection -BorrowedPaths @($borrowed|Select-Object -Unique)
    $updated=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity -SourceReferences @($projection.source_references)
    $script:capacity=$updated.session
  }
}
function Write-InstrumentWorkbenchReceipt {
  param([bool]$PhaseOkay)
  if($workbench){
    $receiptContext=@{execution_run_directory=[string]$RunPackage.run_dir;run_directory=[string]$RunPackage.artifact_run_dir}
    $persistentWorkbenchEvidence=Convert-WorkflowOwnerPath $receiptContext $workbenchEvidencePath
    if(-not(Test-WorkflowPathWithin $persistentWorkbenchEvidence $receiptContext.run_directory)){
      throw 'Workbench execution evidence is outside its owning run.'
    }
    $persistentFlightEvidence=$null
    if($Fly){
      $persistentFlightEvidence=Convert-WorkflowOwnerPath $receiptContext $flightEvidencePath
      if(-not(Test-WorkflowPathWithin $persistentFlightEvidence $receiptContext.run_directory)){
        throw 'Flight execution evidence is outside its owning run.'
      }
    }
    $workbench.native_execution_performed=@($workbenchExecution|Where-Object{$null-ne$_.exit_code}).Count-gt0
    $priorityChecks=@($workbenchExecution|Where-Object{$_.operation-eq'verify'-and$_.ContainsKey('native_priority_occupancy_validation')}|ForEach-Object{$_.native_priority_occupancy_validation})
    $expectedPriorityChecks=if($workbench.ContainsKey('batches')){@($workbench.batches).Count}else{1}
    $priorityOkay=$workbenchOkay-and$priorityChecks.Count-eq$expectedPriorityChecks
    $workbench.native_validation=@{status=$(if($workbenchOkay){'success'}else{'failed'});execution_records_path=$persistentWorkbenchEvidence;
      scope='saved_component_slots_grids_provider_poses_declared_priority_order_and_prepared_controls';
      native_priority_occupancy_validation=@{status=$(if($priorityOkay){'success'}elseif($workbench.native_execution_performed-and-not$workbenchOkay){'failed'}else{'pending'});
        scope='declared_native_point_expectations_only__not_dynamic_fields_continuity_or_global_geometry';
        checked_points=$(if($priorityChecks.Count){($priorityChecks|Measure-Object -Property checked_points -Sum).Sum}else{0});
        observation_only_points=$(if($priorityChecks.Count){($priorityChecks|Measure-Object -Property observation_only_points -Sum).Sum}else{0})};fly_performed=$false}
    if($workbenchOkay){
      $workbench.pending_validation=@('real_full_population_flight_validation')
      if(-not$priorityOkay){$workbench.pending_validation+=@('native_priority_occupancy_points')}
    }
    if($Fly){
      $workbench.native_validation.fly_performed=@($flightExecution|Where-Object{$null-ne$_.exit_code-and$_.phase-in$nativePhases}).Count-gt0
      $workbench.flight_validation=@{status=$(if($PhaseOkay){'success'}else{'failed'});execution_records_path=$persistentFlightEvidence;
        completed_collection_count=$phaseCollection.Count;
        scope=$(if($workbench.phase-eq'discovery'){'complete_mother_population_actual_occupancy_discovery'}elseif($defaultReplayRequested){if($continuationSource){'recorded_pre_pulse_continued_cohort_and_saved_default_replay'}else{'complete_mother_population_and_saved_default_replay'}}elseif($continuationSource){'recorded_pre_pulse_continued_cohort'}else{'complete_mother_population'});
        }
      $phaseReplayRequested=($defaultReplayRequested-and$workbench.phase-ne'discovery')
      $workbench.default_replay_verification=@{requested=$phaseReplayRequested;
        status=$(if(-not$phaseReplayRequested){'not_requested'}elseif($PhaseOkay){'completed'}else{'failed'});
        native_fly_performed=(@($flightExecution|Where-Object{$_.phase-eq'default_replay'}).Count-gt0)}
      $workbench.saved_default_replay_verification=$workbench.default_replay_verification.status
      if($PhaseOkay){
        $workbench.pending_validation=@()
        if(-not$priorityOkay){$workbench.pending_validation+=@('native_priority_occupancy_points')}
      }
    }
    Write-RunJson -Path $workbenchReceiptPath -Depth 100 -Value $workbench
  }
}
$currentStage='engineering_budget';$phaseClock=[Diagnostics.Stopwatch]::StartNew()
function Set-InstrumentStage([string]$Name){
  if($null-ne$PhaseTimings){$PhaseTimings[$currentStage]=[double]$phaseClock.Elapsed.TotalSeconds}
  $script:currentStage=$Name;$phaseClock.Restart()
}
try {
  $budget=Initialize-IntegrationStageBudget -ResolvedBudget $ExecutionBudgetPath -InputDir $inputs `
    -ExpectedIntegrationId instrument_assembly -ExpectedWorkflowId single_reflection_flight `
    -StageId instrument_field_design -Solver simion -ExpectedRetentionClass solver_review
  $budgetDocument=Get-Content -LiteralPath $budget.frozen_budget -Raw|ConvertFrom-Json
  if([int]$budgetDocument.particle_count-ne[int]$receipt.particle_count){throw 'Field budget population differs from the frozen active source cohort.'}
  $runtimeArguments=@('-B','-m','integrations.workflows.single_reflection_flight.runtime',
    '--preparation',(Join-Path $resultDirectory 'preparation_receipt.json'),'--run',$OutputDirectory,'--snapshot-root',$frozenExecutionRoot)
  if($WorkbenchOnly-or$Fly){
    $workbenchLimits=Get-IntegrationStageBudget -Document $budgetDocument -ExpectedIntegrationId instrument_assembly `
      -ExpectedWorkflowId single_reflection_flight -StageId instrument_workbench_preparation -Solver simion -ExpectedRetentionClass solver_review
    $flightCheck=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
      $checked=& $Python @runtimeArguments --check-flight
      if($LASTEXITCODE-ne0){throw 'WorkbenchOnly requires valid explicit frozen flight inputs.'}
      return $checked|ConvertFrom-Json -AsHashtable
    }
    $discoverPulse=[bool]$flightCheck.requires_discovery
  }
  if($Fly){
    $flightLimits=@{}
    $flightStages=@('instrument_flight')
    if($defaultReplayRequested){$flightStages+=@('instrument_default_replay')}
    if($discoverPulse){$flightStages=@('instrument_pulse_discovery')+$flightStages}
    foreach($stage in $flightStages){
      $flightLimits[$stage]=Get-IntegrationStageBudget -Document $budgetDocument -ExpectedIntegrationId instrument_assembly `
        -ExpectedWorkflowId single_reflection_flight -StageId $stage -Solver simion -ExpectedRetentionClass solver_review
    }
  }
  $downstreamPlan=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
    $planned=& $Python -B -m integrations.workflows.single_reflection_flight.downstream_fields `
      --preparation (Join-Path $resultDirectory 'preparation_receipt.json') --run $OutputDirectory --snapshot-root $frozenExecutionRoot `
      --engineering-budget $budget.frozen_budget
    if($LASTEXITCODE-ne0){throw 'Downstream field planning failed.'}
    return $planned|ConvertFrom-Json -AsHashtable -Depth 100
  }
  $downstreamPlanPath=[string]$downstreamPlan.plan_record.path
  # Capacity admission reserves only payload newly materialized in this run.
  # Selected source members remain protected producer inputs; the plan reserves
  # only the remaining members plus construction scratch. Cold construction
  # covers common payload plus the raw geometry and working PA0 scratch. Engineering
  # directory budgets remain warning thresholds during execution.
  $commitment=[long]$downstreamPlan.reserved_run_array_payload_bytes
  $commitment+=[long]$downstreamPlan.frontend_resource_lower_bounds.cache_miss_new_disk_payload_bytes_lower_bound
  if($Fly){
    $flightFloor=[long]$downstreamPlan.frontend_resource_lower_bounds.flight_process_array_bytes_lower_bound
    foreach($stage in $flightStages){
      if([long]$flightLimits[$stage].process_tree_working_set_bytes-le$flightFloor){
        throw "$stage budget must exceed frontend working-field RAM lower bound $flightFloor; downstream arrays and process overhead are additional."
      }
    }
  }
  $protectedPaths=@($OutputDirectory)
  $sourceProtection=Get-InstrumentSourceProtectionProjection
  if($ownsCapacity){
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $artifacts `
      -RunDirectory $OutputDirectory -CommittedNewBytes $commitment -ProtectedPaths $protectedPaths -SourceReferences @($sourceProtection.source_references)
  }else{
    $renewal=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
      -RemainingCommittedNewBytes $commitment -ProtectedPaths $protectedPaths -SourceReferences @($sourceProtection.source_references)
    $capacity=$renewal.session
  }
  $downstreamNativeContext=$null
  if(-not$downstreamPlan.ContainsKey('publication')){
    $nativePaths=@(Split-Path -Parent $downstreamPlanPath)
    foreach($step in $downstreamPlan.steps){$nativePaths+=@($step.argv|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})}
    $downstreamNativeContext=Get-RunNativeExecutionContext -Package $RunPackage -Paths $nativePaths -Tool SIMION
  }
  $lease=Enter-HostExecutionLease -StatePath $pathContext.host_resource_state_path -Role SIMION -Stage prepare
  $stageElapsed=[Diagnostics.Stopwatch]::StartNew()
  $simion=(Resolve-Path -LiteralPath (Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe')).Path
  Set-InstrumentStage 'frontend_fields'
  $field=Invoke-SingleReflectionFrontendFieldStage -Package $RunPackage -Python $Python -RepoRoot $frozen.execution_root `
    -RunDirectory $OutputDirectory -PreparedDirectory $OutputDirectory -SimionExe $simion `
    -HostLease ([ref]$lease) -CapacitySession ([ref]$capacity) -Limits $budget.limits `
    -CacheRoot (Join-Path $artifacts 'common/simion/pa_family_cache') `
    -StageElapsed $stageElapsed -ReservedRunPayloadBytes ([long]$downstreamPlan.reserved_run_array_payload_bytes) `
    -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token)
  Write-InstrumentWallClockWarning
  Write-RunJson -Path (Join-Path $resultDirectory 'field_receipt.json') -Depth 100 -Value $field
  Set-InstrumentStage 'downstream_fields'
  if($downstreamPlan.ContainsKey('publication')){
    $published=$downstreamPlan.publication
  }else{
  foreach($step in $downstreamPlan.steps){
    Write-InstrumentWallClockWarning
    $lease=Update-HostResourceStage -Lease $lease -Stage ([string]$step.resource_stage) `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage ([string]$step.resource_stage)) -RetainedMemoryBytes 0
    Write-InstrumentWallClockWarning
    $name='downstream_{0:D2}_{1}' -f [int]$step.index,[string]$step.name
    $stdout=Join-Path $OutputDirectory ('logs/'+$name+'.stdout.log')
    $stderr=Join-Path $OutputDirectory ('logs/'+$name+'.stderr.log')
    $usage=Join-Path $OutputDirectory ('logs/'+$name+'.resource_usage.json')
    $native=$null
    try {
      $native=Invoke-ResourceBudgetedProcess -Limits $budget.limits -RunDir $OutputDirectory -UsagePath $usage `
        -FilePath $simion -WorkingDirectory $downstreamNativeContext.projected_paths[0] -ArgumentList (Project-RunPath -Paths ([string[]]$step.argv) -ArtifactRunDir $RunPackage.artifact_run_dir -RunDir $downstreamNativeContext.run_dir -Python $Python) -Environment $downstreamNativeContext.environment `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId $name -ProcessRecord $native}
    }catch{
      if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId $name -ExceptionData $_.Exception.Data}
      throw
    } finally {
      $downstreamExecution+=@{index=[int]$step.index;argv=@($step.argv);exit_code=$(if($null-ne$native){$native.exit_code}else{$null});stdout_path=$stdout;stderr_path=$stderr;usage_path=$usage}
    }
    if($native.resource_budget_exceeded-or$native.exit_code-ne0){throw "Downstream native field stage failed: $($step.name)"}
    if(-not(Test-Path -LiteralPath $stdout)-or-not(Get-Content -LiteralPath $stdout -Raw).Contains([string]$step.success_marker)){
      throw "Downstream native field completion marker missing: $($step.name)"
    }
  }
  Write-NativeExecutionEvidence -Records $downstreamExecution -Path $downstreamEvidencePath
  Write-InstrumentWallClockWarning
  $published=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
    $publication=& $Python -B -m integrations.workflows.single_reflection_flight.downstream_fields `
      --plan $downstreamPlanPath --execution-records $downstreamEvidencePath
    if($LASTEXITCODE-ne0){throw 'Downstream field publication failed.'}
    return $publication|ConvertFrom-Json -AsHashtable -Depth 100
  }
  }
  Write-RunJson -Path (Join-Path $resultDirectory 'downstream_receipt.json') -Depth 100 -Value $published
  Write-InstrumentWallClockWarning
  $workbenchPhases=if($WorkbenchOnly-or$Fly){@('full_instrument')}else{@()}
  if($discoverPulse){$workbenchPhases=if($Fly){@('discovery','full_instrument')}else{@('discovery')}}
  foreach($workbenchPhase in $workbenchPhases){
    Set-InstrumentStage ("workbench_"+$workbenchPhase)
    $workbench=$null;$workbenchOkay=$false;$workbenchExecution=@();$phaseCollection=@();$baselineRecord=$null
    $workbenchPrefix=if($workbenchPhase-eq'discovery'){'discovery_'}else{''}
    $workbenchReceiptPath=Join-Path $resultDirectory "${workbenchPrefix}workbench_preparation.json"
    $workbenchEvidencePath=Join-Path $resultDirectory "${workbenchPrefix}workbench_execution_records.json"
    $nativePhases=if($workbenchPhase-eq'discovery'){@('discovery')}elseif($defaultReplayRequested){@('baseline','default_replay')}else{@('baseline')}
    $phaseArguments=@('--phase',$workbenchPhase)
    if($decisionRecord){$phaseArguments+=@('--pulse-decision-record',(ConvertTo-Json -InputObject $decisionRecord -Compress))}
    if($WorkbenchOnly){
      $workbenchElapsed=[Diagnostics.Stopwatch]::StartNew()
      $activeWorkbenchLimits=$workbenchLimits
      $workbench=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
        $materialized=& $Python @runtimeArguments @phaseArguments --field-receipt ([string]$field.cache_receipt) `
          --downstream-publication (Join-Path $resultDirectory 'downstream_receipt.json')
        if($LASTEXITCODE-ne0){throw 'Single-reflection workbench materialization failed.'}
        return $materialized|ConvertFrom-Json -AsHashtable -Depth 100
      }
      Write-RunJson -Path $workbenchReceiptPath -Depth 100 -Value $workbench
      Confirm-InstrumentFrontendIobRetention
      Initialize-InstrumentIobPaCopies -Prepared $workbench
      foreach($record in $workbench.pa_guard_records){
        if([string]$record.path-notin$paGuards){
          $null=Protect-ImmutablePaSource -Source ([string]$record.path) -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
          $paGuards.Add([string]$record.path)
        }
      }
      $lease=Update-HostResourceStage -Lease $lease -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
      $nativePaths=@((Split-Path -Parent $workbench.iob_path),[string]$workbench.iob_path)+@($workbench.iob_builder_arguments|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})+@($workbench.iob_verify_arguments|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})
      $workbenchNativeContext=Get-RunNativeExecutionContext -Package $RunPackage -Paths $nativePaths -Tool SIMION
      foreach($operation in @('build','verify')){
        $argv=if($operation-eq'build'){@($workbench.iob_builder_arguments)}else{@($workbench.iob_verify_arguments)}
        $stdout=Join-Path $OutputDirectory "logs/${workbenchPrefix}workbench_$operation.stdout.log"
        $stderr=Join-Path $OutputDirectory "logs/${workbenchPrefix}workbench_$operation.stderr.log"
        $usage=Join-Path $OutputDirectory "logs/${workbenchPrefix}workbench_$operation.resource_usage.json"
        $native=$null
        try {
          Write-InstrumentWallClockWarning -Limits $activeWorkbenchLimits -Elapsed $workbenchElapsed -Stage 'Instrument workbench preparation'
          $native=Invoke-ResourceBudgetedProcess -Limits $activeWorkbenchLimits -RunDir $OutputDirectory -UsagePath $usage `
            -FilePath $simion -WorkingDirectory $workbenchNativeContext.projected_paths[0] -ArgumentList (Project-RunPath -Paths ([string[]]$argv) -ArtifactRunDir $RunPackage.artifact_run_dir -RunDir $workbenchNativeContext.run_dir -Python $Python) -Environment $workbenchNativeContext.environment `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId ("workbench."+$workbenchPhase+"."+$operation) -ProcessRecord $native}
        }catch{
          if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId ("workbench."+$workbenchPhase+"."+$operation) -ExceptionData $_.Exception.Data}
          throw
        } finally {
          $execution=@{operation=$operation;argv=$argv;exit_code=$(if($null-ne$native){$native.exit_code}else{$null});stdout_path=$stdout;stderr_path=$stderr;usage_path=$usage}
          $workbenchExecution+=@($execution);$allWorkbenchExecution+=@($execution)
        }
        if($native.resource_budget_exceeded-or$native.exit_code-ne0){throw "Workbench native $operation failed."}
        $marker=if($operation-eq'build'){'SINGLE_REFLECTION_IOB=PASS'}else{'SINGLE_REFLECTION_IOB_REOPEN=PASS'}
        if(-not(Test-Path -LiteralPath $stdout)){throw "Workbench native $operation output missing."}
        $nativeOutput=Get-Content -LiteralPath $stdout -Raw
        if(-not$nativeOutput.Contains($marker)){
          throw "Workbench native $operation completion marker missing."
        }
        if($operation-eq'verify'){
          $execution.native_priority_occupancy_validation=Get-InstrumentNativePriorityOccupancyEvidence `
            -OutputText $nativeOutput -ExpectedCounts $workbench.native_priority_occupancy_expected_counts
        }
      }
      $verified=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
        $checked=& $Python @runtimeArguments --verify-controls $workbenchReceiptPath
        if($LASTEXITCODE-ne0){throw 'Workbench native preparation changed frozen controls.'}
        return $checked|ConvertFrom-Json -AsHashtable -Depth 100
      }
      $workbench.outputs.iob=$verified.iob_record
      # Bind the saved IOB before either Fly. Subsequent checks compare this same
      # record rather than accepting a newly computed identity as the baseline.
      Write-RunJson -Path $workbenchReceiptPath -Depth 100 -Value $workbench
      Write-NativeExecutionEvidence -Records $workbenchExecution -Path $workbenchEvidencePath
      Write-InstrumentWallClockWarning -Limits $activeWorkbenchLimits -Elapsed $workbenchElapsed -Stage 'Instrument workbench preparation'
      $workbenchOkay=$true
    }
    if($Fly){
      Set-InstrumentStage ("flight_"+$workbenchPhase)
      $limits=if($workbenchPhase-eq'discovery'){$flightLimits.instrument_pulse_discovery}else{$flightLimits.instrument_flight}
      $flightElapsed=[Diagnostics.Stopwatch]::StartNew()
      $fullRuntimeInputs=@('--preparation',(Join-Path $resultDirectory 'preparation_receipt.json'),
        '--snapshot-root',$frozenExecutionRoot,'--field-receipt',([string]$field.cache_receipt),
        '--downstream-publication',(Join-Path $resultDirectory 'downstream_receipt.json'))
      if($decisionRecord){$fullRuntimeInputs+=@('--pulse-decision-record',(ConvertTo-Json -InputObject $decisionRecord -Compress))}
      $prepared=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
        $output=& $Python @runtimeArguments prepare-dispatch @phaseArguments --field-receipt ([string]$field.cache_receipt) `
          --downstream-publication (Join-Path $resultDirectory 'downstream_receipt.json')
        if($LASTEXITCODE-ne0){throw 'Instrument dispatch preparation failed.'}
        return $output|ConvertFrom-Json -AsHashtable -Depth 100
      }
      $continuationArguments=@{}
      if($batchContinuation){
        $recoveryPhase=if($workbenchPhase-eq'discovery'){'discovery'}else{'baseline'}
        $recovered=Invoke-FrontendRuntimePython -Python $Python -RepoRoot $frozen.execution_root -RunDirectory $OutputDirectory `
          -Name "$workbenchPhase.continuation" -Arguments (@('-m','integrations.workflows.single_reflection_flight.runtime',
          'materialize-continuation','--run',$OutputDirectory,'--phase',$workbenchPhase,'--continuation-phase',$recoveryPhase)+$fullRuntimeInputs) -Json
        if($null-ne$recovered){
          $recoveredMap=$recovered|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable -Depth 100
          Register-InstrumentContinuationInputs -Workbench $recoveredMap
          $fixedDispatch=Join-Path $OutputDirectory "results/$workbenchPhase.dispatch_plan.json"
          Copy-VerifiedRunInput -Source ([string]$recovered.continuation.frozen_inputs.dispatch_record.path) -Destination $fixedDispatch|Out-Null
          $continuationArguments=@{FixedDispatchPlanPath=$fixedDispatch;ContinuationPlanPath=[string]$recovered.continuation.plan_record.path;ContinuationWorkbench=$recovered}
        }
      }
      if(-not$continuationArguments.Count-or@($recovered.continuation.plan.units|Where-Object{$_.action-eq'replay'}).Count){
        Confirm-InstrumentFrontendIobRetention
        Initialize-InstrumentIobPaCopies -Prepared $prepared
        foreach($record in $prepared.pa_guard_records){
          if([string]$record.path-notin$paGuards){
            $null=Protect-ImmutablePaSource -Source ([string]$record.path) -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
            $paGuards.Add([string]$record.path)
          }
        }
        $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
      }
      $materialized=Invoke-FrontendFlightPhase -Package $RunPackage -RunDirectory $OutputDirectory -ProjectRunsRoot (Split-Path -Parent $OutputDirectory) `
        -RepoRoot $frozen.execution_root -Python $Python -RuntimeModule integrations.workflows.single_reflection_flight.runtime `
        -SimionExe $simion -Limits $limits -Phase $workbenchPhase -RuntimeInputArguments $fullRuntimeInputs -Prepared $prepared `
        -WorkbenchReceiptPath $workbenchReceiptPath -IobVerification ${function:Confirm-InstrumentIobVerification} `
        -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) `
        -OnProcessCompleted {param($record) Write-FrontendBatchCheckpoint -Record $record -Phase $workbenchPhase -RunDirectory $OutputDirectory `
          -RunConfig $configPath -WorkbenchReceiptPath $workbenchReceiptPath -DispatchPlanPath (Join-Path $OutputDirectory "results/$workbenchPhase.dispatch_plan.json") -Python $Python -RepoRoot $RepoRoot} @continuationArguments
      $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
      $workbench=$materialized|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable -Depth 100
      $workbenchExecution=@($workbench.batches|Where-Object{-not$_.ContainsKey('continuation_source')}|ForEach-Object{$_.native_workbench_execution})
      $allWorkbenchExecution+=@($workbenchExecution)
      Write-NativeExecutionEvidence -Records $workbenchExecution -Path $workbenchEvidencePath
      $workbenchOkay=$true
      Write-RunJson -Path $workbenchReceiptPath -Value $workbench -Depth 100
      foreach($phase in $nativePhases){
        Set-InstrumentStage ("analyze_or_replay_"+$phase)
        $phaseDirectory=Join-Path $resultDirectory $phase
        New-Item -ItemType Directory -Path $phaseDirectory -ErrorAction Stop|Out-Null
        if($phase-eq'default_replay'){
          if($batchContinuation){
            $recoveredReplay=Invoke-FrontendRuntimePython -Python $Python -RepoRoot $frozen.execution_root -RunDirectory $OutputDirectory `
              -Name 'default_replay.continuation' -Arguments (@('-m','integrations.workflows.single_reflection_flight.runtime',
              'materialize-continuation','--run',$OutputDirectory,'--phase',$workbenchPhase,'--continuation-phase','default_replay')+$fullRuntimeInputs) -Json
            if($null-ne$recoveredReplay){
              $workbench=$recoveredReplay|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable -Depth 100
              Register-InstrumentContinuationInputs -Workbench $workbench
            }
          }
          $specifications=@(foreach($case in $workbench.batches){
            if($case.ContainsKey('replay_continuation_source')){continue}
            if($case.ContainsKey('continuation_pa_guard_records')){
              $borrowedPa=@()
              foreach($record in $case.continuation_pa_guard_records){
                if([string]$record.path-notin$paGuards){
                  $null=Protect-ImmutablePaSource -Source ([string]$record.path) -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
                  $paGuards.Add([string]$record.path)
                }
                $borrowedPa+=[string]$record.path
              }
              $projection=Get-InstrumentSourceProtectionProjection -BorrowedPaths $borrowedPa
              $updated=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity -SourceReferences @($projection.source_references)
              $capacity=$updated.session
            }
            $case.replay_stdout=Join-Path $phaseDirectory ($case.case_id+'.stdout.log')
            $case.replay_stderr=Join-Path $phaseDirectory ($case.case_id+'.stderr.log')
            $replayCase=@{};foreach($key in $case.Keys){$replayCase[$key]=$case[$key]}
            $replayCase.stdout=$case.replay_stdout;$replayCase.stderr=$case.replay_stderr
            New-FrontendFlightSpecification -Package $RunPackage -Case $replayCase -SimionExe $simion
          })
          Write-RunJson -Path $workbenchReceiptPath -Value $workbench -Depth 100
          # Baseline post-check is the replay pre-check; only log destinations changed.
          if($specifications.Count){$lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0}
          $replay=if($specifications.Count){Invoke-ResourceBudgetedProcesses -DispatchPlanPath (Join-Path $OutputDirectory "results/$workbenchPhase.dispatch_plan.json") `
            -RunDir $OutputDirectory -UsagePath (Join-Path $phaseDirectory resource_usage.json) -ProcessSpecifications $specifications `
            -OnProcessCompleted {param($record) if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId 'default_replay.fly' -ProcessRecord $record};Write-FrontendBatchCheckpoint -Record $record -Phase 'default_replay' -RunDirectory $OutputDirectory `
              -RunConfig $configPath -WorkbenchReceiptPath $workbenchReceiptPath -DispatchPlanPath (Join-Path $OutputDirectory "results/$workbenchPhase.dispatch_plan.json") -Python $Python -RepoRoot $RepoRoot}}else{@{resource_budget_exceeded=$false;processes=@()}}
          if($replay.resource_budget_exceeded){
            try{throw 'Saved-default replay exceeded the resource budget; writer completion is unconfirmed.'}catch{
              $_.Exception.Data['simion_wave_writer_completion_confirmed']=$false;throw
            }
          }
          $replayFailed=($replay.resource_budget_exceeded-or@($replay.processes|Where-Object{[int]$_.exit_code-ne0}).Count)
          if(-not$replayFailed-and$specifications.Count){Complete-ResourceUsage -RunDir $OutputDirectory -UsagePath (Join-Path $phaseDirectory resource_usage.json)|Out-Null}
          if($specifications.Count){$lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0}
        }
        $phaseExecution=@()
        foreach($case in $workbench.batches){
          $reuseKey=if($phase-eq'default_replay'){'replay_continuation_source'}else{'continuation_source'}
          if($case.ContainsKey($reuseKey)){continue}
          $records=if($phase-eq'default_replay'){@($replay.processes)}else{@($workbench.native_process_records)}
          $record=@($records|Where-Object{$_.name-eq$case.case_id})
          if($record.Count-ne1){throw 'Native worker receipt does not identify exactly one source batch.'}
          $phaseExecution+=@(@{phase=$phase;argv=$case.fly_arguments;exit_code=$record[0].exit_code;controls_unchanged=$null;control_error=$null;
            stdout_path=$(if($phase-eq'default_replay'){$case.replay_stdout}else{$case.stdout});
            stderr_path=$(if($phase-eq'default_replay'){$case.replay_stderr}else{$case.stderr});
            usage_path=$(if($phase-eq'default_replay'){Join-Path $phaseDirectory resource_usage.json}else{Join-Path $OutputDirectory "results/$workbenchPhase.resource_usage.json"})})
        }
        $flightExecution+=@($phaseExecution)
        try {
          Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
            & $Python @runtimeArguments --verify-controls $workbenchReceiptPath
            if($LASTEXITCODE-ne0){throw "Saved batch controls changed during $phase."}
          }|Out-Null
          foreach($record in $phaseExecution){$record.controls_unchanged=$true}
        } catch {
          foreach($record in $phaseExecution){$record.controls_unchanged=$false;$record.control_error=[string]$_}
          throw
        }
        if($phase-eq'default_replay'-and$replayFailed){throw 'Instrument saved-batch replay failed.'}
        $collectArguments=@('-B','-m','integrations.workflows.single_reflection_flight.collect',
          '--preparation',(Join-Path $resultDirectory 'preparation_receipt.json'),'--workbench',$workbenchReceiptPath,
          '--run',$OutputDirectory,'--output',$phaseDirectory)
        if($phase-eq'default_replay'){$collectArguments+=@('--replay','--baseline-record',(ConvertTo-Json -InputObject $baselineRecord -Compress))}
        $collected=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
          $output=& $Python @collectArguments
          if($LASTEXITCODE-ne0){throw "Instrument $phase execution-cohort collection failed."}
          return $output|ConvertFrom-Json -AsHashtable -Depth 100
        }
        $flightCollection+=@($collected);$phaseCollection+=@($collected)
        if($phase-eq'baseline'){$baselineRecord=$collected.output_records.'collection.json'}
        Write-InstrumentWallClockWarning -Limits $limits -Elapsed $flightElapsed -Stage "Instrument $phase"
      }
    }
    if($Fly-and$workbenchPhase-eq'discovery'){
      Write-InstrumentWallClockWarning -Limits $flightLimits.instrument_pulse_discovery -Elapsed $flightElapsed -Stage 'Instrument discovery selection'
      $selectionArguments=@('-B','-m','integrations.workflows.single_reflection_flight.collect',
        '--preparation',(Join-Path $resultDirectory 'preparation_receipt.json'),'--workbench',$workbenchReceiptPath,
        '--run',$OutputDirectory,'--output',(Join-Path $resultDirectory 'discovery'),
        '--select-pulse','--collection-record',(ConvertTo-Json -InputObject $phaseCollection[0].output_records.'collection.json' -Compress))
      $selected=Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
        $output=& $Python @selectionArguments
        if($LASTEXITCODE-ne0){throw 'Actual discovery has no supported pulse candidate; retain discovery/pulse_decision.json and frozen source evidence.'}
        return $output|ConvertFrom-Json -AsHashtable -Depth 100
      }
      $decisionRecord=$selected.output_records.'pulse_decision.json'
      Write-InstrumentWallClockWarning -Limits $flightLimits.instrument_pulse_discovery -Elapsed $flightElapsed -Stage 'Instrument discovery selection'
    }
    Write-InstrumentWorkbenchReceipt -PhaseOkay $true
  }
  if($Fly){Write-NativeExecutionEvidence -Records $flightExecution -Path $flightEvidencePath}
  $okay=$true
} catch {
  $failure=$_
  $data=$failure.Exception.Data
  $data['single_reflection_failure_stage']=$currentStage
  $writerUnknown=([bool]$data['simion_first_batch_writer_unknown']-or[bool]$data['simion_first_batch_drain_error']-or
    ($data.Contains('observed_process_exit_confirmed')-and-not[bool]$data['observed_process_exit_confirmed'])-or
    ($data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$data['simion_wave_writer_completion_confirmed']))
  if($writerUnknown){
    try{Write-RunJson -Path (Join-Path $resultDirectory 'writer_completion_unknown.json') -Value @{
      schema_version=1;role='writer_completion_unknown';status='unknown';reason=$failure.Exception.Message
      drain_error=[string]$data['simion_first_batch_drain_error'];wave_drain_error=[string]$data['simion_wave_drain_error']
    }}catch{$failure.Exception.Data['writer_unknown_result_error']=[string]$_}
  }
} finally {
  if($null-ne$PhaseTimings){$PhaseTimings[$currentStage]=[double]$phaseClock.Elapsed.TotalSeconds}
  if($null-ne$NativeOperations-and@($NativeOperations|Where-Object{-not$_.observation.exit_confirmed}).Count){$writerUnknown=$true}
  if(-not$writerUnknown){
  # The caller still owns terminal publication. Bind actual evidence on both
  # success and failure, then release both public sessions even if binding fails.
  try {
    if($Fly-and-not$workbench-and(Test-Path -LiteralPath $workbenchReceiptPath)){
      $workbench=Get-Content -LiteralPath $workbenchReceiptPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
      $workbenchExecution=@()
      for($caseIndex=0;$caseIndex-lt$workbench.batches.Count;$caseIndex++){
        $case=$workbench.batches[$caseIndex]
        if($case.ContainsKey('continuation_source')){continue}
        if(Test-Path -LiteralPath ([string]$case.receipt_path)){
          $case=Get-Content -LiteralPath ([string]$case.receipt_path) -Raw|ConvertFrom-Json -AsHashtable -Depth 100
          $workbench.batches[$caseIndex]=$case
        }
        if($case.ContainsKey('native_workbench_execution')){$workbenchExecution+=@($case.native_workbench_execution)}
      }
      $allWorkbenchExecution+=@($workbenchExecution)
    }
    if($downstreamExecution.Count-and-not(Test-Path -LiteralPath $downstreamEvidencePath)){Write-NativeExecutionEvidence -Records $downstreamExecution -Path $downstreamEvidencePath}
    if($workbenchExecution.Count-and-not(Test-Path -LiteralPath $workbenchEvidencePath)){Write-NativeExecutionEvidence -Records $workbenchExecution -Path $workbenchEvidencePath}
    if($flightExecution.Count-and-not(Test-Path -LiteralPath $flightEvidencePath)){Write-NativeExecutionEvidence -Records $flightExecution -Path $flightEvidencePath}
    Write-InstrumentWorkbenchReceipt -PhaseOkay $okay
    $config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    foreach($file in Get-ChildItem -LiteralPath $inputs -File){
      if($file.FullName-notin@($config.inputs.Values)){$config.inputs['stage_'+$file.Name]=$file.FullName}
    }
    $continuationDirectory=Join-Path $inputs 'continuation'
    if(Test-Path -LiteralPath $continuationDirectory){
      foreach($file in Get-ChildItem -LiteralPath $continuationDirectory -Recurse -File){
        $name='continuation_'+[IO.Path]::GetRelativePath($continuationDirectory,$file.FullName).Replace('\','_').Replace('/','_')
        $config.inputs[$name]=$file.FullName
      }
    }
    $evidence=@($downstreamPlanPath,$downstreamEvidencePath,(Join-Path $resultDirectory 'field_receipt.json'),(Join-Path $resultDirectory 'downstream_receipt.json'))
    foreach($row in $downstreamExecution){$evidence+=@($row.stdout_path,$row.stderr_path,$row.usage_path)}
    $evidence+=@($workbenchReceiptPath,$workbenchEvidencePath)
    if($discoverPulse){$evidence+=@((Join-Path $resultDirectory 'discovery_workbench_preparation.json'),
      (Join-Path $resultDirectory 'discovery_workbench_execution_records.json'),
      (Join-Path $resultDirectory 'discovery/pulse_decision.json'))}
    foreach($row in $allWorkbenchExecution){$evidence+=@($row.stdout_path,$row.stderr_path,$row.usage_path)}
    $evidence+=@($flightEvidencePath)
    $evidence+=@(Get-ChildItem -LiteralPath (Join-Path $OutputDirectory 'logs') -File|ForEach-Object{$_.FullName})
    $evidence+=@(Get-ChildItem -LiteralPath (Join-Path $OutputDirectory 'results') -File|ForEach-Object{$_.FullName})
    if(Test-Path -LiteralPath (Join-Path $OutputDirectory 'simion')){
      foreach($caseReceipt in Get-ChildItem -LiteralPath (Join-Path $OutputDirectory 'simion') -Filter workbench.json -Recurse -File){
        $case=Get-Content -LiteralPath $caseReceipt.FullName -Raw|ConvertFrom-Json -AsHashtable -Depth 100
        $evidence+=@($caseReceipt.FullName)
        $evidence+=@($case.outputs.Values|ForEach-Object{$_.path})
      }
    }
    foreach($row in $flightExecution){$evidence+=@($row.stdout_path,$row.stderr_path,$row.usage_path)}
    foreach($phase in @('discovery','baseline','default_replay')){
      $phaseDirectory=Join-Path $resultDirectory $phase
      if(Test-Path -LiteralPath $phaseDirectory){
        $evidence+=@(Get-ChildItem -LiteralPath $phaseDirectory -File|Where-Object{$_.Extension-in@('.json','.csv','.log')}|ForEach-Object{$_.FullName})
      }
    }
    $downstreamDirectory=Join-Path $OutputDirectory 'simion/downstream_fields'
    if(Test-Path -LiteralPath $downstreamDirectory){
      $evidence+=@(Get-ChildItem -LiteralPath $downstreamDirectory -File|Where-Object{$_.Extension-in@('.json','.lua')}|ForEach-Object{$_.FullName})
    }
    $i=0
    foreach($path in $evidence){
      if($path-and(Test-Path -LiteralPath $path -PathType Leaf)-and$path-notin@($config.inputs.Values)){
        $config.inputs['field_evidence_'+$i]=$path;$i++
      }
    }
    Write-RunJson -Path $configPath -Depth 100 -Value $config
  }catch{
    if($failure){$failure.Exception.Data['scientific_evidence_binding_error']=$_}else{$failure=$_}
  }
  try{
    if($lease){
      $token=[string]$lease.token
      $released=Exit-HostResourceStage -Lease $lease -PassThru
      if(-not$lease.inherited-and($null-eq$released-or$released.status-ne'released'-or$released.token-ne$token)){throw 'Single-reflection host release is unconfirmed.'}
      if($null-ne$ResourceReleases-and$null-ne$NativeOperations-and@($NativeOperations|Where-Object resource_release_id -eq $token).Count){
        Add-RunArtifactResourceRelease -ResourceReleases $ResourceReleases -ReleaseId $token -Receipt @{host_release=@{inherited=[bool]$lease.inherited;token=$token;result=$released;error=$null}}
      }
      $lease=$null
    }
  }catch{
    $writerUnknown=$true
    if($failure){$failure.Exception.Data['host_release_error']=$_}else{$failure=$_}
  }
  if(-not$writerUnknown){
    try{foreach($path in $paGuards){$null=Unprotect-ImmutablePaSource -Source $path};$paGuards.Clear()}
    catch{if($failure){$failure.Exception.Data['asset_release_error']=$_}else{$failure=$_}}
    if($capacity){
      if($capacity.PSObject.Properties['defer_capacity_finalization']-and$capacity.defer_capacity_finalization){
        if($null-ne$WorkflowCapacitySession){$WorkflowCapacitySession|Add-Member -NotePropertyName defer_capacity_finalization -NotePropertyValue $capacity.defer_capacity_finalization -Force}
      }elseif($ownsCapacity){
        try{$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity}
        catch{if($failure){$failure.Exception.Data['capacity_release_error']=$_}else{$failure=$_}}
      }
    }
  }
  }
}
if($writerUnknown){
  if(-not$failure){try{throw 'Single-reflection writer or host release is unconfirmed.'}catch{$failure=$_}}
  $failure.Exception.Data['simion_wave_writer_completion_confirmed']=$false
}
if($failure){throw $failure}

if($Fly){
  if($defaultReplayRequested){Write-Output 'SINGLE_REFLECTION_FLIGHT=PASS DEFAULT_REPLAY=PASS QUALIFICATION=complete_population_and_saved_default_parity_only'}
  else{Write-Output 'SINGLE_REFLECTION_FLIGHT=PASS DEFAULT_REPLAY=NOT_REQUESTED QUALIFICATION=complete_population_only'}
}elseif($WorkbenchOnly){
  Write-Output 'SINGLE_REFLECTION_WORKBENCH=PASS FLY_EXECUTED=False QUALIFICATION=saved_workbench_reopen_only'
}else{
  Write-Output 'SINGLE_REFLECTION_FIELDS=PASS FLY_EXECUTED=False QUALIFICATION=physical_metal_and_downstream_native_audit_only'
}
