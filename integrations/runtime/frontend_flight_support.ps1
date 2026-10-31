Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Add-FrontendNativeOperation {
  <# Transport the public process owner's facts before scientific callbacks. #>
  [CmdletBinding(DefaultParameterSetName='Record')]
  param([Parameter(Mandatory)]$NativeOperations,[Parameter(Mandatory)][string]$NativeResourceReleaseId,
    [Parameter(Mandatory)][string]$OperationId,
    [Parameter(Mandatory,ParameterSetName='Record')]$ProcessRecord,
    [Parameter(Mandatory,ParameterSetName='Exception')][Collections.IDictionary]$ExceptionData)
  if($null-eq$NativeOperations){return}
  if($PSCmdlet.ParameterSetName-eq'Exception'){
    if(-not$ExceptionData.Contains('observed_process_exit_confirmed')){return}
    $confirmed=$ExceptionData['observed_process_exit_confirmed'];$code=$ExceptionData['observed_process_returncode']
    $id=$ExceptionData['observed_process_id'];$birth=$ExceptionData['observed_process_started_at_utc_ticks']
  }else{
    $code=$ProcessRecord.exit_code;$id=$ProcessRecord.root_process_id;$birth=$ProcessRecord.root_process_started_at_utc_ticks
    $confirmed=$null-ne$code
    if(($ProcessRecord-is[Collections.IDictionary]-and$ProcessRecord.Contains('completed'))-or
       $ProcessRecord.PSObject.Properties.Name-contains'completed'){$confirmed=[bool]$ProcessRecord.completed}
  }
  if($confirmed-and(($id-isnot[int]-and$id-isnot[long])-or[long]$id-le0-or
      ($birth-isnot[int]-and$birth-isnot[long])-or[long]$birth-le0-or
      ($code-isnot[int]-and$code-isnot[long]))){throw 'Frontend native completion lacks actual process identity/exit evidence.'}
  if($null-ne$id-and$null-ne$birth-and[long]$id-gt0-and[long]$birth-gt0){
    foreach($operation in $NativeOperations){
      if($operation.observation.process_id-eq$id-and$operation.observation.process_started_at_utc_ticks-eq$birth){return}
    }
  }
  $NativeOperations.Add(@{operation_id=($OperationId+'.'+[string]$id+'.'+[string]$birth);
    observation=@{exit_confirmed=[bool]$confirmed;returncode=$code;process_id=$id;process_started_at_utc_ticks=$birth};
    resource_release_id=$NativeResourceReleaseId})|Out-Null
}

function Invoke-FrontendRuntimePython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string[]]$Arguments,
    [switch]$Json
  )
  $stdout=Join-Path $RunDirectory ('logs/'+$Name+'.stdout.log')
  $stderr=Join-Path $RunDirectory ('logs/'+$Name+'.stderr.log')
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python -B @Arguments 1>$stdout 2>$stderr
    if($LASTEXITCODE-ne0){throw "Frontend runtime failed: $Name; see $stderr"}
  }
  if($Json){return Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json -Depth 100}
  Get-Content -LiteralPath $stdout|Write-Host
}

function New-FrontendFlightSpecification {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Case,[Parameter(Mandatory)][string]$SimionExe)
  if([int]$Case.count-lt1-or[int]$Case.simion_particle_id_offset-ne0-or[int]$Case.merge_offset-ne0){
    throw 'Frontend case must retain original particle IDs without rebasing.'
  }
  $range=if(($Case-is[Collections.IDictionary]-and$Case.Contains('source_row_range'))-or
      $Case.PSObject.Properties.Name-contains'source_row_range'){@($Case.source_row_range)}
    else{@($Case.expected_particle_ids[0],$Case.expected_particle_ids[-1])}
  return [pscustomobject]@{
    name=[string]$Case.case_id
    scheduler_batch=[pscustomobject]@{index=[int]$Case.index;count=[int]$Case.count;particle_id_min=[int]$range[0];particle_id_max=[int]$range[-1]}
    file_path=$SimionExe;working_directory=[string]$Case.working_directory
    environment=$Case.environment|ConvertTo-Json -Compress|ConvertFrom-Json -AsHashtable
    stdout=[string]$Case.stdout;stderr=[string]$Case.stderr;argument_list=[string[]]$Case.fly_arguments
  }
}

function Write-FrontendBatchCheckpoint {
  <# Retain a small natural-exit fact; the stopped owner binds it once at terminal publication. #>
  param([Parameter(Mandatory)]$Record,[Parameter(Mandatory)][string]$Phase,
    [Parameter(Mandatory)][string]$RunDirectory,[Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][string]$WorkbenchReceiptPath,[Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot)
  if($null-eq$Record.exit_code-or[int]$Record.exit_code-ne0){return}
  if(-not(Test-Path -LiteralPath $WorkbenchReceiptPath -PathType Leaf)-or
     -not(Test-Path -LiteralPath $DispatchPlanPath -PathType Leaf)){return}
  $workbench=Get-Content -LiteralPath $WorkbenchReceiptPath -Raw|ConvertFrom-Json -Depth 100
  $cases=@($workbench.batches|Where-Object{[string]$_.case_id-ceq[string]$Record.name})
  if($cases.Count-ne1){return} # Replanning may have failed before the final case existed.
  $case=$cases[0]
  if([string]$Record.name-cnotmatch'^[A-Za-z0-9_-]+$'-or$Phase-cnotmatch'^[a-z][a-z0-9_]*$'){throw 'Invalid frontend checkpoint identity.'}
  $stdout=[string]$Record.specification.stdout
  if(-not(Test-Path -LiteralPath $stdout -PathType Leaf)){throw 'Completed frontend batch has no stdout.'}
  $directory=Join-Path $RunDirectory "results/frontend_batch_completion/$Phase"
  New-Item -ItemType Directory -Path $directory -Force|Out-Null
  $receipt=Join-Path $directory ($Record.name+'.json')
  $range=@($case.source_row_range)
  if($range.Count-ne2){throw 'Completed frontend batch lacks its source row range.'}
  $fact=[ordered]@{schema_version=1;role='frontend_batch_natural_completion';
    phase=$Phase;case_id=[string]$Record.name;exit_code=0;natural_exit=$true;
    stdout_relative_path=[IO.Path]::GetRelativePath($RunDirectory,$stdout);
    count=[int]$case.count;source_row_range=@([int]$range[0],[int]$range[1])}
  if($Record.PSObject.Properties.Name-contains'observed_process_cpu_percent'){
    $fact.resource_observation=@{peak_bytes=[long]$Record.peak_managed_memory_bytes;
      process_cpu_percent=[double]$Record.observed_process_cpu_percent;
      background_cpu_percent=[double]$Record.observed_background_cpu_percent}
  }
  if($case.PSObject.Properties.Name-contains'control_records'){
    $controls=@($case.control_records|ForEach-Object{[string]$_.path})+@([string]$case.iob_path,[string]$case.iob_reopen_record.path)
  }else{
    $controls=@(foreach($kind in @('program','particles','build_spec','iob')){
      $item=$case.outputs.$kind
      if($null-eq$item){throw "Completed frontend batch lacks $kind."}
      [string]$item.path
    })
  }
  foreach($path in $controls){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Completed frontend batch lacks control $path."}
  }
  Write-RunJson -Path $receipt -Value $fact -Atomic
}

function Invoke-FrontendIobBuild {
  [CmdletBinding()]
  param(
    $NativeOperations=$null,[string]$NativeResourceReleaseId='simion',
    [Parameter(Mandatory)]$Case,[Parameter(Mandatory)][string]$Phase,
    [Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][string]$SimionExe,[Parameter(Mandatory)]$Limits,
    [string]$Python='', [string]$RepoRoot='', [scriptblock]$IobVerification=$null
  )
  $name=[string]$Case.case_id
  $nativeReturned=$false
  try {
  $result=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $RunDirectory -FilePath $SimionExe `
    -ArgumentList ([string[]]$Case.iob_builder_arguments) -WorkingDirectory ([string]$Case.working_directory) `
    -UsagePath (Join-Path $RunDirectory "logs/$Phase.$name.assembly.resource_usage.json") `
    -RedirectStandardOutput (Join-Path $RunDirectory "logs/$Phase.$name.assembly.stdout.log") `
    -RedirectStandardError (Join-Path $RunDirectory "logs/$Phase.$name.assembly.stderr.log")
  $nativeReturned=$true
  if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId -OperationId ($Phase+'.iob.'+$name) -ProcessRecord $result}
  if($result.resource_budget_exceeded-or[int]$result.exit_code-ne0-or-not(Test-Path -LiteralPath ([string]$Case.iob_path))){
    throw "Frontend IOB assembly failed: $Phase/$name"
  }
  if($IobVerification){
    & $IobVerification -Operation after_build -Case $Case -BuildResult $result -Phase $Phase -RunDirectory $RunDirectory `
      -SimionExe $SimionExe -Limits $Limits -Python $Python -RepoRoot $RepoRoot
  }
  } catch {
    if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId -OperationId ($Phase+'.iob.'+$name) -ExceptionData $_.Exception.Data}
    # This helper also builds the first IOB before a batch wave exists. Carry
    # an unknown native builder/inspector to the same owner release boundary.
    if((-not$nativeReturned-and(-not$_.Exception.Data.Contains('observed_process_exit_confirmed')-or
         $_.Exception.Data['observed_process_exit_confirmed']-isnot[bool]-or-not[bool]$_.Exception.Data['observed_process_exit_confirmed']))-or
       ($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])){
      $_.Exception.Data['simion_wave_writer_completion_confirmed']=$false
    }
    throw
  }
}

function Invoke-FrontendFlightPhase {
  <# Scientific state/source/phase compilation stays in the explicitly supplied
     runtime module. This mechanism owns only the existing automatic dispatch,
     first-formal observation and remaining work; the GUI case is assembled. #>
  [CmdletBinding()]
  param(
    $NativeOperations=$null,[string]$NativeResourceReleaseId='simion',
    [Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][string]$ProjectRunsRoot,
    [Parameter(Mandatory)][string]$RepoRoot,[Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RuntimeModule,
    [Parameter(Mandatory)][string]$SimionExe,[Parameter(Mandatory)]$Limits,
    [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9_]*$')][string]$Phase,
    [Nullable[double]]$PulseTimeUs=$null,
    [string]$SharedTimesPath='',
    [string[]]$RuntimeInputArguments=@(),
    [string]$FixedDispatchPlanPath='',
    [string]$ContinuationPlanPath='',
    $ContinuationWorkbench=$null,
    [string]$WorkbenchReceiptPath='',
    $Prepared=$null,
    [scriptblock]$IobVerification=$null,
    [scriptblock]$OnProcessCompleted=$null
  )
  $context=@{Python=$Python;RepoRoot=$RepoRoot;RunDirectory=$RunDirectory}
  $native=@{NativeOperations=$NativeOperations;NativeResourceReleaseId=$NativeResourceReleaseId;RunDirectory=$RunDirectory;SimionExe=$SimionExe;Limits=$Limits;Phase=$Phase;Python=$Python;RepoRoot=$RepoRoot}
  if($IobVerification){$native.IobVerification=$IobVerification}
  $phaseArgs=@('--run',$RunDirectory,'--phase',$Phase)+$RuntimeInputArguments
  if($SharedTimesPath){$phaseArgs+=@('--shared-times-json',$SharedTimesPath)}
  if($null-ne$PulseTimeUs){$phaseArgs+=@('--pulse-time-us',([double]$PulseTimeUs).ToString('G17',[Globalization.CultureInfo]::InvariantCulture))}
  if($null-eq$Prepared){
    $Prepared=Invoke-FrontendRuntimePython @context -Name "$Phase.prepare-dispatch" `
      -Arguments (@('-m',$RuntimeModule,'prepare-dispatch')+$phaseArgs) -Json
  }
  $recovery=([bool]$FixedDispatchPlanPath -or [bool]$ContinuationPlanPath)
  if($recovery-and((-not$FixedDispatchPlanPath)-or(-not$ContinuationPlanPath))){throw 'Recovery requires both fixed dispatch and continuation plan paths.'}
  $profiles=Join-Path $RunDirectory "results/$Phase.resource_profiles.json"
  $dispatch=Join-Path $RunDirectory "results/$Phase.dispatch_plan.json"
  $usage=Join-Path $RunDirectory "results/$Phase.resource_usage.json"
  if($recovery){
    $dispatch=[IO.Path]::GetFullPath($FixedDispatchPlanPath)
    if(-not(Test-Path -LiteralPath $dispatch -PathType Leaf)){throw 'Frozen recovery dispatch plan is missing.'}
    if(-not(Test-Path -LiteralPath $ContinuationPlanPath -PathType Leaf)){throw 'Frozen whole-unit continuation plan is missing.'}
    $scheduler=@()
  }else{
    Invoke-FrontendRuntimePython @context -Name "$Phase.resource-profile-discover" `
      -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',$ProjectRunsRoot,'--output',$profiles)
    $scheduler=@('-m','common.simion.resource_scheduler','--request',[string]$Prepared.dispatch_request_path,'--profiles',$profiles,'--output',$dispatch)
    Invoke-FrontendRuntimePython @context -Name "$Phase.dispatch-plan" -Arguments $scheduler
  }
  $plan=Get-Content -LiteralPath $dispatch -Raw|ConvertFrom-Json -Depth 100
  $initial=if($null-ne$ContinuationWorkbench){$ContinuationWorkbench}else{Invoke-FrontendRuntimePython @context -Name "$Phase.materialize-initial" `
    -Arguments (@('-m',$RuntimeModule,'materialize-batches')+$phaseArgs+@('--batch-plan',$dispatch)) -Json}
  $formalIndex=$null;$firstSpecification=$null;$replan=$null;$afterDrain=$null
  if((-not$recovery)-and$plan.estimation.kind-eq'formal_first_batch_observation'){
    $provisional=Join-Path $RunDirectory "results/$Phase.provisional_dispatch_plan.json"
    Copy-Item -LiteralPath $dispatch -Destination $provisional
    $first=@($initial.batches)[0]
    $null=Invoke-FrontendIobBuild @native -Case $first
    # Publish the original formal interval and its built controls before it can
    # start. A later replan failure must retain the actual first-batch identity.
    if($WorkbenchReceiptPath){Write-RunJson -Path $WorkbenchReceiptPath -Value $initial -Depth 100}
    $formalIndex=[int]$first.index
    $afterDrain={
      if($IobVerification){
        & $IobVerification -Operation after_first_fly -Case $first -BuildResult $null -Phase $Phase -RunDirectory $RunDirectory `
          -SimionExe $SimionExe -Limits $Limits -Python $Python -RepoRoot $RepoRoot
      }
    }
    $replan={
      param($formal)
      $firstBatchCompleted=[bool]$formal.process_record.completed
      $adaptive=$scheduler+@('--observed-formal-peak-bytes',"$($formal.observed_peak_process_tree_working_set_bytes)",
        '--observed-formal-cpu-percent',"$($formal.observed_process_cpu_percent)",
        '--observed-background-cpu-percent',"$($formal.observed_background_cpu_percent)",
        '--available-memory-bytes',"$($formal.available_memory_bytes)",'--total-physical-memory-bytes',"$($formal.total_physical_memory_bytes)")
      if($firstBatchCompleted){$adaptive+='--first-batch-completed'}
      Invoke-FrontendRuntimePython @context -Name "$Phase.dispatch-followup" -Arguments $adaptive
    }
    $firstSpecification=New-FrontendFlightSpecification -Case $first -SimionExe $SimionExe
  }
  if($recovery-and$plan.PSObject.Properties['estimation']-and$plan.estimation.PSObject.Properties['recovered_missing_observation']-and
      [bool]$plan.estimation.recovered_missing_observation){
    $replayPlan=Get-Content -LiteralPath $ContinuationPlanPath -Raw|ConvertFrom-Json -Depth 100
    $replayKeys=@($replayPlan.units|Where-Object{$_.action-eq'replay'}|ForEach-Object{[string]$_.key})
    if($replayKeys.Count-gt0){
      $missing=@($initial.batches|Where-Object{[string]$_.case_id-ceq$replayKeys[0]})
      if($missing.Count-ne1){throw 'Unobserved recovered dispatch lacks its unique missing unit.'}
      $first=$missing[0];$formalIndex=[int]$first.index
      $null=Invoke-FrontendIobBuild @native -Case $first
      if($WorkbenchReceiptPath){Write-RunJson -Path $WorkbenchReceiptPath -Value $initial -Depth 100}
      $firstSpecification=New-FrontendFlightSpecification -Case $first -SimionExe $SimionExe
      $replan={param($formal)
        $arguments=@('-m','common.simion.resource_scheduler','--recovered-missing-plan',$dispatch,'--output',$dispatch,
          '--observed-formal-peak-bytes',[string]$formal.observed_peak_process_tree_working_set_bytes,
          '--observed-formal-cpu-percent',[string]$formal.observed_process_cpu_percent,
          '--observed-background-cpu-percent',[string]$formal.observed_background_cpu_percent,
          '--available-memory-bytes',[string]$formal.available_memory_bytes,
          '--total-physical-memory-bytes',[string]$formal.total_physical_memory_bytes)
        if($formal.process_record.completed){$arguments+='--first-batch-completed'}
        Invoke-FrontendRuntimePython @context -Name "$Phase.recovered-missing-dispatch" -Arguments $arguments
      }
      $afterDrain={if($IobVerification){& $IobVerification -Operation after_first_fly -Case $first -BuildResult $null -Phase $Phase -RunDirectory $RunDirectory -SimionExe $SimionExe -Limits $Limits -Python $Python -RepoRoot $RepoRoot}}
    }
  }
  $prepareRemaining={
    param($formal)
    $materialized=if($recovery){$initial}else{Invoke-FrontendRuntimePython @context -Name "$Phase.materialize-complete" `
      -Arguments (@('-m',$RuntimeModule,'materialize-batches')+$phaseArgs+@('--batch-plan',$dispatch)) -Json}
    if($materialized.coverage-ne'complete_population'-or@($materialized.pending_particle_ids).Count){throw 'Final frontend dispatch does not cover the complete mother source.'}
    $pending=@($materialized.batches|Where-Object{$null-eq$formalIndex-or[int]$_.index-ne$formalIndex})
    if($recovery){
      $continuation=Get-Content -LiteralPath $ContinuationPlanPath -Raw|ConvertFrom-Json -Depth 100
      $units=@{};foreach($unit in @($continuation.units)){$units[[string]$unit.key]=$unit}
      $reused=@()
      $pending=@($pending|Where-Object{
        $unit=$units[[string]$_.case_id]
        if($null-eq$unit){throw "Recovery plan lacks current batch $($_.case_id)."}
        if($unit.action-eq'reuse'){
          $_|Add-Member -NotePropertyName continuation_source -NotePropertyValue $unit -Force
          $reused+=$_
          return $false
        }
        if($unit.action-cne'replay'){throw "Recovery action differs for $($_.case_id)."}
        return $true
      })
      $materialized|Add-Member -NotePropertyName reused_batches -NotePropertyValue @($reused) -Force
    }
    # Publish small prepared controls before workers start so a managed failed
    # run can retain already complete batches through its normal manifest.
    if($WorkbenchReceiptPath){Write-RunJson -Path $WorkbenchReceiptPath -Value $materialized -Depth 100}
    foreach($case in $pending){
      $null=Invoke-FrontendIobBuild @native -Case $case
      if($WorkbenchReceiptPath){Write-RunJson -Path $WorkbenchReceiptPath -Value $materialized -Depth 100}
    }
    if((-not$recovery)-and$null-ne$materialized.gui_case){$null=Invoke-FrontendIobBuild @native -Case $materialized.gui_case}
    $specifications=@($pending|ForEach-Object{New-FrontendFlightSpecification -Case $_ -SimionExe $SimionExe})
    [pscustomobject]@{pending=$specifications;materialized=$materialized}
  }
  # Capture the caller's callback and function implementation before the public
  # batch owner introduces its own OnProcessCompleted dynamic parameter scope.
  $completionWriter=${function:Add-FrontendNativeOperation}
  $scientificCompletion=$OnProcessCompleted
  $completionOperations=$NativeOperations
  $completionReleaseId=$NativeResourceReleaseId
  $completionPhase=$Phase
  $completion={param($record)
    if($null-ne$completionOperations){& $completionWriter -NativeOperations $completionOperations -NativeResourceReleaseId $completionReleaseId -OperationId ($completionPhase+'.fly.'+[string]$record.name) -ProcessRecord $record}
    if($scientificCompletion){& $scientificCompletion $record}
  }.GetNewClosure()
  $wave=Invoke-SimionBatchPhase -DispatchPlanPath $dispatch -RunDir $RunDirectory -UsagePath $usage `
    -FirstSpecification $firstSpecification -Replan $replan -PrepareRemaining $prepareRemaining -AfterDrain $afterDrain `
    -OnProcessCompleted $completion
  $materialized=$wave.prepared.materialized
  if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count){
    try{throw "Frontend $Phase batch flight failed."}catch{
      $_.Exception.Data['simion_wave_writer_completion_confirmed']=-not[bool]$wave.resource_budget_exceeded
      throw
    }
  }
  if($recovery-and@($wave.prepared.pending).Count-eq0-and@($wave.processes).Count-eq0){
    $materialized|Add-Member -NotePropertyName native_process_records -NotePropertyValue @() -Force
    return $materialized
  }
  $materialized|Add-Member -NotePropertyName native_process_records -NotePropertyValue @($wave.processes) -Force
  Complete-ResourceUsage -RunDir $RunDirectory -UsagePath $usage|Out-Null
  if($null-ne$formalIndex-and-not$recovery){
    $profileName=if($Phase-eq'extraction'){'simion_resource_profile.json'}else{"$Phase.simion_resource_profile.json"}
    Invoke-FrontendRuntimePython @context -Name "$Phase.resource-profile-publish" -Arguments @(
      '-m','common.simion.resource_profile','publish','--run-id',([IO.Path]::GetFileName($RunDirectory)),
      '--resource-usage',$usage,'--dispatch-plan',$dispatch,'--resource-usage-relative-path',"results/$Phase.resource_usage.json",
      '--dispatch-plan-relative-path',"results/$Phase.dispatch_plan.json",'--output',(Join-Path $RunDirectory "results/$profileName"))
  }
  return $materialized
}

function Invoke-FrontendDefaultReplay {
 [CmdletBinding()]
 param(
  [Parameter(Mandatory)]$Materialized,[Parameter(Mandatory)][ref]$HostLease,
  [Parameter(Mandatory)][string]$RunDirectory,[Parameter(Mandatory)][string]$RepoRoot,
  [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$SimionExe,
  [Parameter(Mandatory)]$Limits,
  $NativeOperations=$null,[string]$NativeResourceReleaseId='simion'
 )
 $policy=$Materialized.default_replay_policy
 if($policy.scope-eq'not_requested'){
  return @{status='not_requested';requested=$false;native_fly_performed=$false;scope='not_requested'}
 }
 $casePath=Join-Path $RunDirectory 'inputs/default_replay_gui_case.json'
 Write-RunJson -Path $casePath -Value $Materialized.gui_case -Depth 100
 if($policy.comparison_policy-eq'independent_stochastic_collisions'-and$policy.scope-eq'saved_controls_only'){
  $verify=@'
import json,sys
from pathlib import Path
from integrations.workflows.local_frontend.replay import verify_saved_controls
run=Path(sys.argv[1])
receipt=verify_saved_controls(run,json.loads(Path(sys.argv[2]).read_text()))
receipt['default_replay_policy']=json.loads(Path(sys.argv[3]).read_text())['default_replay_policy']
receipt['requested']=receipt['default_replay_policy']['requested']
path=run/'results/saved_controls_verification.json'
if path.exists():
    raise ValueError('refuse to overwrite saved controls verification')
path.write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n',encoding='utf-8')
print(json.dumps(receipt,allow_nan=False))
'@
  return Invoke-FrontendRuntimePython -Python $Python -RepoRoot $RepoRoot -RunDirectory $RunDirectory -Name saved_controls_verify `
   -Arguments @('-c',$verify,$RunDirectory,$casePath,([string]$Materialized.receipt_path)) -Json
 }
 if($policy.comparison_policy-ne'deterministic_trajectory_parity'-or$policy.scope-ne'fresh_process'){
  throw 'Saved-default replay requires an explicit supported materialization policy.'
 }
 $logsPath=Join-Path $RunDirectory 'inputs/default_replay_scheduled_logs.json'
 Write-RunJson -Path $logsPath -Value @($Materialized.batches|ForEach-Object{[string]$_.stdout})
 $prepare=@'
import json,sys
from pathlib import Path
from integrations.workflows.local_frontend.replay import prepare_default_replay
print(json.dumps(prepare_default_replay(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text())),allow_nan=False))
'@
 $spec=Invoke-FrontendRuntimePython -Python $Python -RepoRoot $RepoRoot -RunDirectory $RunDirectory -Name default_replay_prepare -Arguments @('-c',$prepare,$RunDirectory,$casePath) -Json
 $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
 # A new process consumes the saved IOB defaults. No Program, Q, particles,
 # retention, preload Lua, or other flight setting is supplied on the CLI.
 try{
 $result=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $RunDirectory -FilePath $SimionExe `
  -ArgumentList ([string[]]$spec.argument_list) -WorkingDirectory ([string]$spec.working_directory) `
  -Environment ($spec.environment|ConvertTo-Json -Compress|ConvertFrom-Json -AsHashtable) `
  -UsagePath ([string]$spec.usage_path) -RedirectStandardOutput ([string]$spec.stdout) -RedirectStandardError ([string]$spec.stderr)
  if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId -OperationId 'default_replay.fly' -ProcessRecord $result}
 }catch{
  if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId -OperationId 'default_replay.fly' -ExceptionData $_.Exception.Data}
  throw
 }
 if($result.resource_budget_exceeded-or[int]$result.exit_code-ne0){throw 'Saved-default fresh-process Fly failed; original and replay logs retained.'}
 $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 $compare=@'
import json,sys
from pathlib import Path
from integrations.workflows.local_frontend.replay import compare_default_replay
run,logs,replay=map(Path,sys.argv[1:4])
print(json.dumps(compare_default_replay(run,[Path(p) for p in json.loads(logs.read_text())],replay),allow_nan=False))
'@
 $comparison=Invoke-FrontendRuntimePython -Python $Python -RepoRoot $RepoRoot -RunDirectory $RunDirectory -Name default_replay_compare -Arguments @('-c',$compare,$RunDirectory,$logsPath,([string]$spec.stdout)) -Json
 if(-not$comparison.passed){throw 'Saved-default replay differs from scheduled mother evidence; complete comparison retained.'}
 $comparison|Add-Member -NotePropertyName requested -NotePropertyValue $true -Force
 $comparison|Add-Member -NotePropertyName native_fly_performed -NotePropertyValue $true -Force
 $comparison|Add-Member -NotePropertyName status -NotePropertyValue completed -Force
 return $comparison
}
