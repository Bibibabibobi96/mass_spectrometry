<# JSON transport to the unique installed batch dispatcher, not a new scheduler. #>
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=[Console]::In.ReadToEnd()|ConvertFrom-Json -AsHashtable
. (Join-Path $PSScriptRoot 'host_execution_lease.ps1') -HostContext $request.context
. (Join-Path $PSScriptRoot 'simion_dispatch_support.ps1')
$lease=$null;$failure=$null;$release=$null;$wave=$null
$guards=[Collections.Generic.List[string]]::new()
$started=[Collections.Generic.List[object]]::new();$observations=@{};$attempts=[Collections.Generic.List[object]]::new()
function ConvertTo-BatchObservation($record){
  return @{exit_code=[int]$record.exit_code;root_process_id=[int]$record.root_process_id;
    root_process_started_at_utc_ticks=[int64]$record.root_process_started_at_utc_ticks}
}
try{
  $lease=Enter-HostExecutionLease -Role $request.role -Stage $request.stage -RunId $request.run_id
  if(@($request.immutable_input_records).Count){
    . (Join-Path $PSScriptRoot 'payload_file_support.ps1') -UnbufferedIdentityReader {
      param([string]$Source,[int64]$Length)
      $digest=& $request.context.python_executable -I -B -c 'from msplatform.execution.file_identity import file_sha256_unbuffered;import sys;print(file_sha256_unbuffered(sys.argv[1]))' $Source
      if($LASTEXITCODE-ne0){throw 'Immutable batch input verification failed.'};$digest
    }
    foreach($record in $request.immutable_input_records){
      if(-not[IO.Path]::IsPathFullyQualified([string]$record.path)-or$record.exists-isnot[bool]-or-not$record.exists-or
         $record.bytes-is[bool]-or$record.bytes-isnot[long]-and$record.bytes-isnot[int]-or$record.bytes-lt0-or
         [string]$record.sha256-cnotmatch'^[A-Fa-f0-9]{64}$'){throw 'Invalid immutable batch input record.'}
      $guard=Protect-ImmutablePaSource -Source $record.path -ExpectedBytes $record.bytes -ExpectedSha256 $record.sha256
      if(-not$guard.already_protected){$guards.Add([string]$guard.path)}
    }
  }
  $onStarted={param($record) $started.Add($record)}.GetNewClosure()
  $convertObservation=${function:ConvertTo-BatchObservation}
  $onCompleted={param($record)
    $observation=& $convertObservation $record
    $observations[[string]$record.name]=$observation
    $attempts.Add(@{operation_id=[string]$record.name;observation=$observation;pressure_terminated=[bool]$record.pressure_terminated})
    $payload=@{operation_id=[string]$record.name;observation=$observation;host_release=$null}
    $payload|ConvertTo-Json -Depth 12 -Compress|& $request.context.python_executable -I -B -c 'import json,sys;from pathlib import Path;from msplatform.execution.recorded_file_removal import write_json_atomic;write_json_atomic(Path(sys.argv[1]),json.load(sys.stdin))' $record.specification.receipt_path
    if($LASTEXITCODE-ne0){throw 'Batch process completion evidence could not be preserved.'}
  }.GetNewClosure()
  $specifications=@(foreach($row in $request.specifications){
    [pscustomobject]@{name=$row.operation_id;file_path=$row.executable;argument_list=@($row.argument_line);
      stdout=$row.stdout_path;stderr=$row.stderr_path;working_directory=$row.working_directory;
      environment=$row.environment;scheduler_batch=[pscustomobject]$row.scheduler_batch;
      receipt_path=$row.receipt_path;retain_process_handle=$true;on_started=$onStarted}
  })
  $prepare={param($formal) [pscustomobject]@{pending=@($specifications|Where-Object{
    $null-eq$formal-or[string]$_.name-cne[string]$formal.process_record.name})}}.GetNewClosure()
  $arguments=@{DispatchPlanPath=$request.dispatch_plan_path;RunDir=$request.run_directory;
    UsagePath=$request.usage_path;PrepareRemaining=$prepare;OnProcessCompleted=$onCompleted}
  if($null-ne$request.formal_operation_id){
    $first=@($specifications|Where-Object{$_.name-ceq$request.formal_operation_id})
    if($first.Count-ne1){throw 'Formal batch does not uniquely match a declared operation.'}
    $arguments.FirstSpecification=$first[0]
    $arguments.Replan={param($formal)
      $args=@('-I','-B','-m','msplatform.execution.simion_dispatch','--recovered-missing-plan',$request.dispatch_plan_path,
        '--output',$request.dispatch_plan_path,'--observed-formal-peak-bytes',[string]$formal.observed_peak_process_tree_managed_memory_bytes,
        '--observed-formal-cpu-percent',[string]$formal.observed_process_cpu_percent,
        '--observed-background-cpu-percent',[string]$formal.observed_background_cpu_percent,
        '--available-memory-bytes',[string]$formal.available_memory_bytes,'--total-physical-memory-bytes',[string]$formal.total_physical_memory_bytes)
      if($formal.completed_naturally){$args+='--first-batch-completed'}
      & $request.context.python_executable @args
      if($LASTEXITCODE-ne0){throw 'Actual formal observation could not replan the frozen missing partition.'}
    }.GetNewClosure()
  }
  $wave=Invoke-SimionBatchPhase @arguments
  if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count){throw 'Observed batch wave failed.'}
}catch{
  $failure=$_
  # Start-Process may have returned before its identity metadata could be built.
  # Retain that original handle in this same holder; never rebind by PID.
  if($_.Exception.Data.Contains('simion_started_process')){
    $process=$_.Exception.Data['simion_started_process'];$spec=$_.Exception.Data['simion_started_specification']
    if(-not@($started|Where-Object{[object]::ReferenceEquals($_.process,$process)}).Count){
      $started.Add([pscustomobject]@{process=$process;name=$spec.name;specification=$spec;root_process_id=[int]$process.Id;
        root_process_started_at_utc_ticks=$null;tracked_process_ids=@([int]$process.Id);
        tracked_process_started_at_utc_ticks=@{};completed=$false;exit_code=$null;pressure_terminated=$false})
    }
  }
}finally{
  # All paths, including observation/checkpoint failure, retain the original
  # handles and the same public single-root/family drain before input release.
  foreach($record in $started){
    $drain=Wait-RepositoryImmutableProcessDrain -Process $record.process -RootProcessId $record.root_process_id `
      -RootProcessStartedAtUtcTicks $record.root_process_started_at_utc_ticks `
      -RootExitConfirmed ([bool]$record.completed-and$null-ne$record.exit_code) -RootReturnCode $record.exit_code `
      -TrackedProcessIds $record.tracked_process_ids -TrackedProcessStartedAtUtcTicks $record.tracked_process_started_at_utc_ticks `
      -Failure $failure
    $failure=$drain.failure
    if(-not$observations.ContainsKey([string]$record.name)){
      $observations[[string]$record.name]=@{exit_code=$drain.root_returncode;root_process_id=$record.root_process_id;
        root_process_started_at_utc_ticks=$drain.root_started_at_utc_ticks}
    }
    if(-not@($attempts|Where-Object{$_.observation.root_process_id-eq$record.root_process_id-and
      $_.observation.root_process_started_at_utc_ticks-eq$drain.root_started_at_utc_ticks}).Count){
      $attempts.Add(@{operation_id=[string]$record.name;pressure_terminated=[bool]$record.pressure_terminated;
        observation=@{exit_code=$drain.root_returncode;root_process_id=$record.root_process_id;
          root_process_started_at_utc_ticks=$drain.root_started_at_utc_ticks}})
    }
    try{$record.process.Dispose()}catch{if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['batch_dispose_error']=$_.Exception.Message}}
  }
  foreach($path in $guards){
    try{$null=Unprotect-ImmutablePaSource -Source $path}catch{
      if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['immutable_input_release_error']=$_.Exception.Message}
    }
  }
  if($null-ne$lease){
    $release=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$null;error=$null}
    try{$release.result=Exit-HostResourceStage -Lease $lease -PassThru}catch{$release.error=$_.Exception.Message}
  }
}
$errorRecord=$null
if($null-ne$failure){
  $errorRecord=@{type=$failure.Exception.GetType().FullName;message=$failure.Exception.Message;data=@{}}
  # Keep original/secondary diagnostic text without serializing live handles.
  foreach($key in $failure.Exception.Data.Keys){$errorRecord.data[[string]$key]=[string]$failure.Exception.Data[$key]}
}
$notStarted=@($request.specifications|Where-Object{-not$observations.ContainsKey([string]$_.operation_id)}|ForEach-Object{$_.operation_id})
$envelope=@{observations=$observations;attempts=$attempts.ToArray();not_started=$notStarted;error=$errorRecord;host_release=$release}
[Console]::Out.WriteLine('EXECUTION_BATCH_RESULT='+($envelope|ConvertTo-Json -Depth 24 -Compress))
if($null-ne$failure-or$null-eq$release-or$release.error-or
  (-not$release.inherited-and($null-eq$release.result-or$release.result.status-ne'released'))){exit 1}
exit 0
