# Unique installed SIMION dispatch; scientific inputs remain caller-owned.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'resource_process_support.ps1')

function Assert-RepositoryProcessSpecification {
  param([Parameter(Mandatory)]$Specification)
  foreach($required in @('name','file_path','argument_list','stdout','stderr','environment')){
    if(-not($Specification.PSObject.Properties.Name-contains$required)){
      throw "Scheduled process specification is missing $required."
    }
  }
  if($Specification.PSObject.Properties.Name-contains'exclusive_resource_key'){
    $key=$Specification.exclusive_resource_key
    if($null-ne$key-and(-not($key -is [string])-or[string]::IsNullOrWhiteSpace([string]$key))){
      throw 'Scheduled process exclusive_resource_key must be a non-empty string when supplied.'
    }
  }
  if($Specification.PSObject.Properties.Name-contains'prepare' -and
      $null-ne$Specification.prepare -and -not ($Specification.prepare -is [scriptblock])){
    throw 'Scheduled process prepare must be a script block when supplied.'
  }
}

function Start-RepositoryScheduledProcess {
  param([Parameter(Mandatory)]$Specification)
  Assert-RepositoryProcessSpecification -Specification $Specification
  # A prepared batch may need small Workbench-local assets immediately before
  # launch.  Do not materialize those while an earlier SIMION process still
  # scans the same runtime directory after its frozen observation window.
  if($Specification.PSObject.Properties.Name-contains'prepare'-and
      $null-ne$Specification.prepare){
    try{$null=& $Specification.prepare $Specification}
    catch{$_.Exception.Data['simion_native_launch_not_attempted']=$true;throw}
  }
  $arguments=@{
    FilePath=[string]$Specification.file_path;ArgumentList=@($Specification.argument_list)
    PassThru=$true;WindowStyle='Hidden';RedirectStandardOutput=[string]$Specification.stdout
    RedirectStandardError=[string]$Specification.stderr;Environment=[hashtable]$Specification.environment
  }
  if($Specification.PSObject.Properties.Name-contains'working_directory'){
    $arguments.WorkingDirectory=[string]$Specification.working_directory
  }
  $started=Get-RepositoryUtcNow;$process=Start-Process @arguments
  try{$record=[pscustomobject]@{
    name=[string]$Specification.name;specification=$Specification;process=$process
    root_process_id=[int]$process.Id;root_process_started_at_utc_ticks=[int64]$process.StartTime.ToUniversalTime().Ticks;started_at=$started
    tracked_process_ids=@([int]$process.Id)
    tracked_process_started_at_utc_ticks=@{([string]$process.Id)=[int64]$process.StartTime.ToUniversalTime().Ticks}
    active=$true;completed=$false
    exit_code=$null;peak_working_set_bytes=[int64]0;peak_managed_memory_bytes=[int64]0;pressure_terminated=$false
  }
    if($Specification.PSObject.Properties.Name-contains'on_started'){$null=& $Specification.on_started $record}
    return $record
  }catch{
    # Start-Process returned, but the immutable identity could not be built.
    # The caller must not infer that this writer has stopped.
    $_.Exception.Data['simion_first_batch_writer_unknown']=$true
    $_.Exception.Data['simion_started_process']=$process
    $_.Exception.Data['simion_started_specification']=$Specification
    throw
  }
}

function Write-RepositorySchedulerEvent {
  <# Emit one concise, factual lifecycle event from the public executor. #>
  param(
    [Parameter(Mandatory)][string]$Event,
    $Record=$null,
    [int]$ActiveCount=-1,
    [int]$PendingCount=-1,
    [hashtable]$Details=@{}
  )
  $fields=[Collections.Generic.List[string]]::new()
  $fields.Add("SIMION_RESOURCE_EVENT=$Event")
  if($null-ne$Record){
    $fields.Add("PROCESS=$([string]$Record.name)")
    $batch=$null
    if($Record.PSObject.Properties.Name-contains'specification'-and
       $Record.specification.PSObject.Properties.Name-contains'scheduler_batch'){
      $batch=$Record.specification.scheduler_batch
    }
    if($null-ne$batch){
      $workItem=$batch.PSObject.Properties.Name-contains'execution_unit'-and
        [string]$batch.execution_unit-eq'independent_work_items'
      $properties=$(if($workItem){@('index','total_batches','work_item_id_min','work_item_id_max','count')}else{@('index','total_batches','particle_id_min','particle_id_max','count')})
      foreach($property in $properties){
        if($batch.PSObject.Properties.Name-contains$property){
          $name=@{index='BATCH';total_batches='TOTAL_BATCHES';particle_id_min='PARTICLE_ID_MIN';particle_id_max='PARTICLE_ID_MAX';work_item_id_min='WORK_ITEM_ID_MIN';work_item_id_max='WORK_ITEM_ID_MAX';count=$(if($workItem){'WORK_ITEM_COUNT'}else{'PARTICLE_COUNT'})}[$property]
          $fields.Add("$name=$([string]$batch.$property)")
        }
      }
    }
  }
  if($ActiveCount-ge0){$fields.Add("ACTIVE=$ActiveCount")}
  if($PendingCount-ge0){$fields.Add("PENDING=$PendingCount")}
  foreach($key in @($Details.Keys|Sort-Object)){$fields.Add("$key=$([string]$Details[$key])")}
  # Lifecycle events are diagnostic output, not the function's returned
  # process record.  Write-Output would be captured into callers such as
  # `$wave = Invoke-ResourceBudgetedProcesses`, hiding the event from the
  # terminal and corrupting the typed return collection.  Write-Host keeps
  # the event visible while leaving the success stream exclusively for data.
  Write-Host ($fields-join' ')
}

function Get-SystemCpuPercent {
  try{
    $average=(Get-CimInstance Win32_Processor -ErrorAction Stop|
      Measure-Object -Property LoadPercentage -Average).Average
    $value=[double]$average
    # Win32_Processor.LoadPercentage is a whole-system 0--100 value.  A
    # transient WMI value outside that range is not safe evidence of pressure:
    # discard it and retain the last valid sample instead of turning a
    # one-core-scale artifact into a permanent single-worker decision.
    if([double]::IsNaN($value)-or[double]::IsInfinity($value)-or$value-lt0-or$value-gt100){
      return $null
    }
    return $value
  }catch{return $null}
}

function Assert-RepositoryDispatchLimits {
  param([Parameter(Mandatory)]$Limits, [Parameter(Mandatory)][string[]]$PositiveIntegers)
  foreach($name in $PositiveIntegers){
    $value=$Limits.$name
    if($value-is[bool]-or$value-is[string]-or$null-eq$value-or
       [double]::IsNaN([double]$value)-or[double]::IsInfinity([double]$value)-or
       [double]$value-lt 1-or[math]::Truncate([double]$value)-ne[double]$value){
      throw "Repository dispatch limit $name must be a positive integer."
    }
  }
}

function Start-ObservedFormalProcess {
  <# Start the first formal batch, retain it, and observe the fixed first window. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)]$ProcessSpecification,
    [switch]$WaitForNaturalCompletionAfterObservation
  )
  Assert-HostResourceHeavyStage
  $plan=Get-Content -LiteralPath $DispatchPlanPath -Raw -Encoding UTF8|ConvertFrom-Json
  if([string]$plan.estimation.kind-ne'formal_first_batch_observation'){
    throw 'Formal observation requires an unknown-identity repository plan.'
  }
  $seconds=[int]$plan.limits.formal_observation_seconds
  Assert-RepositoryDispatchLimits -Limits $plan.limits -PositiveIntegers @(
    'formal_observation_seconds','memory_critical_reserve_bytes','memory_critical_seconds')
  $memoryWarningOnly=($plan.limits.PSObject.Properties.Name-contains'memory_policy'-and
    [string]$plan.limits.memory_policy-eq'warn_single_worker')
  $criticalBytes=[int64]$plan.limits.memory_critical_reserve_bytes
  $criticalSeconds=[int]$plan.limits.memory_critical_seconds
  $logicalProcessors=[int][Environment]::ProcessorCount
  if($plan.PSObject.Properties.Name-contains'host'-and
      $plan.host.PSObject.Properties.Name-contains'logical_processors'-and
      [int]$plan.host.logical_processors-gt0){
    $logicalProcessors=[int]$plan.host.logical_processors
  }
  $record=Start-RepositoryScheduledProcess -Specification $ProcessSpecification
  try {
  Write-RepositorySchedulerEvent -Event 'BATCH_STARTED' -Record $record -ActiveCount 1 `
    -Details @{OBSERVATION_SECONDS=$seconds;MEASUREMENT='FIRST_FORMAL_BATCH'}
  $previousTicks=[int64]0;$previousTicksByProcessId=@{};$previousAt=$record.started_at
  $peakCpu=[double]0;$peakBackground=[double]0;$systemCpu=[double]0;$lastSystemAt=$null
  $cpuSamples=[Collections.Generic.List[object]]::new()
  $criticalSince=$null;$resourceBudgetExceeded=$false
  $observationMemoryWarnings=[Collections.ArrayList]::new()
  $observationComplete=$false;$completedDuringObservation=$false
  # The formal first batch remains alive after the frozen observation window.  Its
  # measured peak determines the initial lane count; subsequent live admission
  # and the existing memory-danger state machine protect against later growth.
  # Waiting for natural completion here would serialize every otherwise
  # parallel run and would make the observation window meaningless.
  while($record.active){
    $now=Get-RepositoryUtcNow
    $sampleArgs=@{RootProcessIds=@($record.root_process_id);TrackedProcessIds=$record.tracked_process_ids}
    $recordRootStartedAtUtcTicks=[int64]0
    if($record.PSObject.Properties.Name -contains 'root_process_started_at_utc_ticks'){
      $recordRootStartedAtUtcTicks=[int64]$record.root_process_started_at_utc_ticks
      $sampleArgs.RootProcessStartedAtUtcTicks=@{([string]$record.root_process_id)=$recordRootStartedAtUtcTicks}
    }
    if($record.PSObject.Properties.Name -contains 'tracked_process_started_at_utc_ticks'){
      $sampleArgs.TrackedProcessStartedAtUtcTicks=$record.tracked_process_started_at_utc_ticks
    }
    $sample=Get-ManagedSolverProcessSample @sampleArgs
    $record.tracked_process_ids=@($sample.tracked_process_ids)
    if(-not ($record.PSObject.Properties.Name -contains 'tracked_process_started_at_utc_ticks')){
      $record|Add-Member -NotePropertyName tracked_process_started_at_utc_ticks -NotePropertyValue @{} -Force
    }
    # Older test seams and in-memory records return the original sample shape.
    # Preserve compatibility while production samples retain start identities.
    if($sample.PSObject.Properties.Name -contains 'tracked_process_started_at_utc_ticks'){
      $record.tracked_process_started_at_utc_ticks=$sample.tracked_process_started_at_utc_ticks
    }
    $record.active=Test-RepositoryManagedProcessIsActive `
      -Specification $record.specification -RootProcessId ([int]$record.root_process_id) `
      -RootProcessStartedAtUtcTicks $recordRootStartedAtUtcTicks `
      -Sample $sample
    $record.peak_working_set_bytes=[math]::Max(
      [int64]$record.peak_working_set_bytes,[int64]$sample.working_set_bytes)
    $record.peak_managed_memory_bytes=[math]::Max(
      [int64]$record.peak_managed_memory_bytes,[int64]$sample.managed_memory_bytes)
    $available=Get-RepositoryAvailableMemoryBytes
    # Ordinary admission pressure only warns. Sustained measured host danger
    # uses the same frozen critical threshold under either admission policy.
    if($available-lt$criticalBytes){
      if($null-eq$criticalSince){
        $criticalSince=$now
        if($memoryWarningOnly){
          $null=$observationMemoryWarnings.Add([ordered]@{
            at_utc=$now.ToString('o');available_memory_bytes=$available
            action='warn_continue_observation';memory_policy='warn_single_worker'
          })
          Write-RepositorySchedulerEvent -Event 'MEMORY_PRESSURE_WARNING' -Record $record `
            -ActiveCount 1 -Details @{AVAILABLE_MEMORY_BYTES=$available;MEMORY_POLICY='warn_single_worker';ACTION='CONTINUE'}
        }
      }elseif($record.active-and($now-$criticalSince).TotalSeconds-ge$criticalSeconds){
        Stop-ManagedSolverProcesses -ProcessIds @($record.tracked_process_ids)
        $record.pressure_terminated=$true;$resourceBudgetExceeded=$true
        Write-RepositorySchedulerEvent -Event 'MEMORY_DANGER_TERMINATION' -Record $record `
          -ActiveCount 1 -Details @{AVAILABLE_MEMORY_BYTES=$available;CRITICAL_SECONDS=$criticalSeconds;CRITICAL_THRESHOLD_BYTES=$criticalBytes;ACTION='STOP_ONLY_FORMAL_BATCH'}
      }
    }else{$criticalSince=$null}
    $elapsed=($now-$previousAt).TotalSeconds
    if($elapsed-gt 0){
      $cpuDeltaTicks=[int64]0
      if($sample.PSObject.Properties.Name-contains'processor_time_ticks_by_process_id'){
        foreach($entry in $sample.processor_time_ticks_by_process_id.GetEnumerator()){
          $key=[string]$entry.Key
          if($previousTicksByProcessId.ContainsKey($key)){
            $cpuDeltaTicks+=[math]::Max([int64]0,[int64]$entry.Value-[int64]$previousTicksByProcessId[$key])
          }
        }
      }elseif($previousTicks-gt 0){
        # Compatibility seam for older tests and an in-memory caller loaded
        # before per-process CPU accounting was added.
        $cpuDeltaTicks=[math]::Max([int64]0,[int64]$sample.total_processor_time_ticks-$previousTicks)
      }
      $cpu=100.0*($cpuDeltaTicks/1.0e7)/($elapsed*$logicalProcessors)
      $peakCpu=[math]::Max($peakCpu,[math]::Max(0.0,$cpu))
      if($null-eq$lastSystemAt-or($now-$lastSystemAt).TotalSeconds-ge 2){
        $observedSystemCpu=Get-SystemCpuPercent
        if($null-ne$observedSystemCpu){$systemCpu=[double]$observedSystemCpu}
        $lastSystemAt=$now
      }
      $peakBackground=[math]::Max($peakBackground,[math]::Max(0.0,$systemCpu-$cpu))
      $cpuSamples.Add([pscustomobject]@{at=$now;percent=[math]::Max(0.0,$cpu)})
    }
    $previousTicks=[int64]$sample.total_processor_time_ticks
    if($sample.PSObject.Properties.Name-contains'processor_time_ticks_by_process_id'){
      $previousTicksByProcessId=@{}
      foreach($entry in $sample.processor_time_ticks_by_process_id.GetEnumerator()){
        $previousTicksByProcessId[[string]$entry.Key]=[int64]$entry.Value
      }
    }
    $previousAt=$now
    if($record.pressure_terminated){
      $record.process.WaitForExit();$record.active=$false;break
    }
    if(-not$record.active){
      $completedDuringObservation=-not$observationComplete
      break
    }
    if(($now-$record.started_at).TotalSeconds-ge$seconds){
      if(-not$observationComplete){
        Write-RepositorySchedulerEvent -Event 'FORMAL_OBSERVATION_COMPLETE' -Record $record -ActiveCount 1 `
          -Details @{OBSERVATION_SECONDS=$seconds;MEASUREMENT='FIRST_FORMAL_BATCH';PROCESS_CONTINUES='true'}
        $observationComplete=$true
      }
      if(-not$WaitForNaturalCompletionAfterObservation){break}
    }
    Start-Sleep -Milliseconds 500
  }
  if(-not$record.active){
    $record.process.WaitForExit()
    try{
      $record.process.Refresh()
      $record.peak_working_set_bytes=[math]::Max(
        [int64]$record.peak_working_set_bytes,[int64]$record.process.PeakWorkingSet64)
      $record.peak_managed_memory_bytes=[math]::Max(
        [int64]$record.peak_managed_memory_bytes,[int64]$record.process.PeakWorkingSet64)
    }catch{}
    $record.completed=$true
    $record.exit_code=$(if($record.pressure_terminated){$null}else{[int]$record.process.ExitCode})
    Write-RepositorySchedulerEvent -Event 'BATCH_COMPLETED' -Record $record -ActiveCount 0 `
      -Details @{EXIT_CODE=$record.exit_code;NATURAL=$(if($record.pressure_terminated){'false'}else{'true'});MEASUREMENT='FIRST_FORMAL_BATCH';WALL_CLOCK_SECONDS=([math]::Round(((Get-RepositoryUtcNow)-$record.started_at).TotalSeconds,3));MORE_PENDING='UNKNOWN'}
    if(-not($record.specification.PSObject.Properties.Name-contains'retain_process_handle')-or-not$record.specification.retain_process_handle){$record.process.Dispose()}
  }
  # Fast Adjust and PA loading can briefly use many cores even though the
  # independent-particle flight that follows is single-core.  Memory remains
  # peak-based, but lane planning uses the median of the final observation
  # window so a short startup burst cannot serialize a long formal cohort.
  # A batch that finishes inside the observation window has no established
  # steady phase, so it conservatively keeps the observed peak.
  $sustainedCpu=$peakCpu
  $cpuMeasurement='peak_completed_inside_observation'
  if($observationComplete-and-not$completedDuringObservation){
    $tailSeconds=[math]::Min(10.0,[math]::Max(3.0,[math]::Floor($seconds/4.0)))
    $tailStart=$record.started_at.AddSeconds([math]::Max(0.0,$seconds-$tailSeconds))
    [double[]]$tailCpu=@($cpuSamples|Where-Object{$_.at-ge$tailStart}|ForEach-Object{[double]$_.percent}|Sort-Object)
    if($tailCpu.Count-gt0){
      $middle=[int][math]::Floor($tailCpu.Count/2)
      $sustainedCpu=if(($tailCpu.Count%2)-eq1){$tailCpu[$middle]}else{($tailCpu[$middle-1]+$tailCpu[$middle])/2.0}
      $cpuMeasurement='median_final_observation_window'
    }
  }
  $record|Add-Member -NotePropertyName completed_during_observation `
    -NotePropertyValue ([bool]$completedDuringObservation) -Force
  $record|Add-Member -NotePropertyName memory_warning_events `
    -NotePropertyValue @($observationMemoryWarnings) -Force
  $record|Add-Member -NotePropertyName observed_process_cpu_percent `
    -NotePropertyValue ([math]::Round($sustainedCpu,3)) -Force
  $record|Add-Member -NotePropertyName observed_process_cpu_peak_percent `
    -NotePropertyValue ([math]::Round($peakCpu,3)) -Force
  $record|Add-Member -NotePropertyName observed_process_cpu_measurement `
    -NotePropertyValue $cpuMeasurement -Force
  $record|Add-Member -NotePropertyName observed_background_cpu_percent `
    -NotePropertyValue ([math]::Round($peakBackground,3)) -Force
  return [pscustomobject]@{
    process_record=$record;completed_naturally=([bool]$record.completed -and -not [bool]$record.pressure_terminated);exit_code=$record.exit_code
    resource_budget_exceeded=[bool]$resourceBudgetExceeded
    # The legacy working-set key remains the active runner input.  Its value is
    # deliberately upgraded to the conservative managed peak so existing
    # callers immediately use max(working set, private bytes) for admission.
    observed_peak_process_tree_working_set_bytes=[int64]$record.peak_managed_memory_bytes
    observed_peak_process_tree_managed_memory_bytes=[int64]$record.peak_managed_memory_bytes
    observed_peak_process_tree_resident_working_set_bytes=[int64]$record.peak_working_set_bytes
    observed_process_cpu_percent=[math]::Round($sustainedCpu,3)
    observed_process_cpu_peak_percent=[math]::Round($peakCpu,3)
    observed_process_cpu_measurement=$cpuMeasurement
    observed_background_cpu_percent=[math]::Round($peakBackground,3)
    available_memory_bytes=Get-RepositoryAvailableMemoryBytes
    total_physical_memory_bytes=[int64][MultipoleMemoryStatus]::TotalBytes()
  }
  } catch {
    $failure=$_
    $failure.Exception.Data['simion_first_batch_process_record']=$record
    if(-not$record.completed){
      $failure.Exception.Data['simion_first_batch_writer_unknown']=$true
    }else{
      try{if(-not($record.specification.PSObject.Properties.Name-contains'retain_process_handle')-or-not$record.specification.retain_process_handle){$record.process.Dispose()}}catch{$failure.Exception.Data['simion_first_batch_dispose_error']=[string]$_}
    }
    throw $failure
  }
}

function Invoke-SimionFormalObservation {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [Parameter(Mandatory)]$ProcessSpecification,
    [Parameter(Mandatory)][scriptblock]$Replan,
    [scriptblock]$OnStarted=$null,
    [scriptblock]$OnDrained=$null,
    [scriptblock]$AfterDrain=$null,
    [scriptblock]$OnProcessCompleted=$null
  )
  $formal=$null
  try {
    $formal=Start-ObservedFormalProcess -DispatchPlanPath $DispatchPlanPath -ProcessSpecification $ProcessSpecification
    if($OnStarted){$null=& $OnStarted $formal.process_record}
    if($formal.resource_budget_exceeded-or($formal.process_record.completed-and
        (-not$formal.completed_naturally-or[int]$formal.exit_code-ne0))){throw 'Formal first batch did not continue or complete safely.'}
    $null=& $Replan $formal
  } catch {
    $failure=$_
    $processRecord=if($null-ne$formal){$formal.process_record}else{$failure.Exception.Data['simion_first_batch_process_record']}
    if($null-ne$processRecord){
      Invoke-ObservedPreparationFailureDrain -Failure $failure -DispatchPlanPath $DispatchPlanPath -RunDir $RunDir `
        -UsagePath $UsagePath -ProcessRecords @($processRecord) -OnDrained $OnDrained -AfterDrain $AfterDrain -OnProcessCompleted $OnProcessCompleted
    }
    if($failure.Exception.Data['simion_first_batch_writer_unknown']){
      $failure.Exception.Data['simion_first_batch_drain_error']='First-batch process identity or completion is unconfirmed.'
    }elseif($failure.Exception.Data['simion_native_launch_not_attempted']){
      $failure.Exception.Data['simion_wave_writer_completion_confirmed']=$true
    }
    throw $failure
  }
  return $formal
}

function Invoke-ObservedPreparationFailureDrain {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]$Failure,
    [Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [Parameter(Mandatory)][object[]]$ProcessRecords,
    [scriptblock]$AfterDrain=$null,
    [scriptblock]$OnDrained=$null,
    [scriptblock]$OnProcessCompleted=$null
  )
  # Draining these records proves only their writers stopped. A preparation
  # callback may have launched a different IOB writer whose observer failed.
  $preparationWriterUnknown=(($Failure.Exception.Data.Contains('observed_process_exit_confirmed')-and
    -not[bool]$Failure.Exception.Data['observed_process_exit_confirmed'])-or
    ($Failure.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and
    -not[bool]$Failure.Exception.Data['simion_wave_writer_completion_confirmed']))
  $stopped=$false
  try {
    $drainArgs=@{DispatchPlanPath=$DispatchPlanPath;RunDir=$RunDir;UsagePath=$UsagePath;
      ProcessSpecifications=@();ExistingProcessRecords=$ProcessRecords}
    if($OnProcessCompleted){$drainArgs.OnProcessCompleted=$OnProcessCompleted}
    $drainResult=Invoke-ResourceBudgetedProcesses @drainArgs
    if($drainResult.resource_budget_exceeded){throw 'First-batch drain did not confirm writer completion.'}
    $Failure.Exception.Data['simion_first_batch_writer_unknown']=$false
    $Failure.Exception.Data['simion_wave_writer_completion_confirmed']=-not$preparationWriterUnknown
    $stopped=$true
    if($OnDrained-and-not$preparationWriterUnknown){ $null=& $OnDrained $drainResult }
  } catch {
    $Failure.Exception.Data['simion_first_batch_drain_error']=[string]$_
    # A checkpoint can reject scientific completion after the native writer
    # has already stopped. Preserve that proof, but never another writer's unknown.
    $stopped=(-not$preparationWriterUnknown-and
      $_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and
      [bool]$_.Exception.Data['simion_wave_writer_completion_confirmed']-and
      -not($_.Exception.Data.Contains('observed_process_exit_confirmed')-and
        -not[bool]$_.Exception.Data['observed_process_exit_confirmed']))
    $Failure.Exception.Data['simion_wave_writer_completion_confirmed']=$stopped
    if($stopped){$Failure.Exception.Data['simion_first_batch_writer_unknown']=$false}
    Write-Warning "First-batch drain failed: $_"
  }
  if($AfterDrain-and$stopped-and-not$preparationWriterUnknown){try { $null=& $AfterDrain } catch {
    if(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
       ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed'])){
      $Failure.Exception.Data['simion_wave_writer_completion_confirmed']=$false
    }
    $Failure.Exception.Data['simion_first_batch_verification_error']=[string]$_
    Write-Warning "First-batch verification failed: $_"
  }}
  throw $Failure
}

function Invoke-SimionBatchPhase {
  <# Coordinate one owner-prepared batch wave; scientific inputs stay with its owner. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [Parameter(Mandatory)][scriptblock]$PrepareRemaining,
    $FirstSpecification=$null,
    [scriptblock]$Replan=$null,
    [scriptblock]$OnStarted=$null,
    [scriptblock]$OnDrained=$null,
    [scriptblock]$AfterDrain=$null,
    [scriptblock]$OnProcessCompleted=$null
  )
  $formal=$null;$existing=@()
  if($null-ne$FirstSpecification){
    if($null-eq$Replan){throw 'Formal first batch requires a replan callback.'}
    $formal=Invoke-SimionFormalObservation -DispatchPlanPath $DispatchPlanPath -RunDir $RunDir -UsagePath $UsagePath `
      -ProcessSpecification $FirstSpecification -Replan $Replan -OnStarted $OnStarted -OnDrained $OnDrained `
      -AfterDrain $AfterDrain -OnProcessCompleted $OnProcessCompleted
    $existing=@($formal.process_record)
  }
  try {
    $prepared=& $PrepareRemaining $formal
    if($null-eq$prepared-or-not($prepared.PSObject.Properties.Name-contains'pending')){
      throw 'Batch preparation must return an object with a pending specification array.'
    }
    $pending=@($prepared.pending)
  } catch {
    if($existing.Count){
      Invoke-ObservedPreparationFailureDrain -Failure $_ -DispatchPlanPath $DispatchPlanPath -RunDir $RunDir `
        -UsagePath $UsagePath -ProcessRecords $existing -OnDrained $OnDrained -AfterDrain $AfterDrain `
        -OnProcessCompleted $OnProcessCompleted
    }
    $_.Exception.Data['simion_wave_writer_completion_confirmed']=-not(
      ($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
      ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed']))
    throw
  }
  if($pending.Count-eq0-and$existing.Count-eq0){
    return [pscustomobject]@{resource_budget_exceeded=$false;processes=@();formal=$formal;prepared=$prepared}
  }
  try {
    $wave=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $DispatchPlanPath -RunDir $RunDir -UsagePath $UsagePath `
      -ProcessSpecifications $pending -ExistingProcessRecords $existing -OnProcessCompleted $OnProcessCompleted
  } catch {
    $failure=$_
    if($AfterDrain-and$failure.Exception.Data['simion_wave_writer_completion_confirmed']){
      try{$null=& $AfterDrain}catch{
        if(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
           ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed'])){
          $failure.Exception.Data['simion_wave_writer_completion_confirmed']=$false
        }
        $failure.Exception.Data['simion_wave_verification_error']=[string]$_
        Write-Warning "Batch verification failed: $_"
      }
    }
    throw $failure
  }
  if($AfterDrain-and-not$wave.resource_budget_exceeded){
    try{$null=& $AfterDrain}catch{
      $verificationWriterUnknown=(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
        ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed']))
      if(@($wave.processes|Where-Object{$null-ne$_.exit_code-and[int]$_.exit_code-ne0}).Count){
        $verificationFailure=$_
        try{throw 'Native batch wave failed.'}catch{
          $_.Exception.Data['simion_wave_verification_error']=[string]$verificationFailure
          $_.Exception.Data['simion_wave_writer_completion_confirmed']=-not$verificationWriterUnknown
          throw
        }
      }
      $_.Exception.Data['simion_wave_writer_completion_confirmed']=-not$verificationWriterUnknown
      throw
    }
  }
  return [pscustomobject]@{resource_budget_exceeded=[bool]$wave.resource_budget_exceeded;
    processes=@($wave.processes);formal=$formal;prepared=$prepared}
}

function Invoke-ResourceBudgetedProcesses {
  <# Execute independent formal batches under the repository dispatch policy. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [object[]]$ProcessSpecifications=@(),
    [object[]]$ExistingProcessRecords=@(),
    # Optional caller-owned durable checkpoint publication.  It is invoked
    # only after a worker has exited naturally with a record available; the
    # callback must fail closed if its immutable receipt cannot be published.
    [scriptblock]$OnProcessCompleted=$null,
    [switch]$NoFailureDrain
  )
  # Keep admitted records visible to the error path even if plan validation or
  # a later batch's preparation fails after the formal worker has started.
  $running=[Collections.ArrayList]::new()
  foreach($record in $ExistingProcessRecords){if(-not$record.completed){$null=$running.Add($record)}}
  $launchInProgress=$false;$checkpointFailure=$null;$checkpointWriterUnknown=$false
  try {
  # A completed first batch needs only receipt publication; pending or live
  # workers still require the original heavy permission before dispatch.
  if($ProcessSpecifications.Count-gt0-or@($ExistingProcessRecords|Where-Object{-not$_.completed}).Count-gt0){
    Assert-HostResourceHeavyStage
  }
  $plan=Get-Content -LiteralPath $DispatchPlanPath -Raw -Encoding UTF8|ConvertFrom-Json
  if([string]$plan.role-ne'simion_repository_dispatch_plan'){
    throw 'Parallel execution requires a repository SIMION dispatch plan.'
  }
  $limits=$plan.limits;$maximumConcurrency=[int]$limits.maximum_concurrency
  $memoryWarningOnly=($limits.PSObject.Properties.Name-contains'memory_policy'-and
    [string]$limits.memory_policy-eq'warn_single_worker')
  if($maximumConcurrency-lt 1){throw 'Repository maximum concurrency must be positive.'}
  Assert-RepositoryDispatchLimits -Limits $limits -PositiveIntegers @(
    'maximum_concurrency','launch_stagger_seconds','memory_critical_seconds',
    'memory_recovery_stable_seconds','maximum_memory_recovery_attempts',
    'maximum_memory_danger_termination_attempts',
    'memory_critical_reserve_bytes')
  if([int]$limits.maximum_memory_recovery_attempts-lt[int]$limits.maximum_memory_danger_termination_attempts){
    throw 'Every permitted memory-danger interruption requires a recovery attempt.'
  }
  $pending=[Collections.ArrayList]::new()
  foreach($spec in $ProcessSpecifications){Assert-RepositoryProcessSpecification $spec;$null=$pending.Add($spec)}
  $completed=[Collections.ArrayList]::new()
  foreach($record in $ExistingProcessRecords){
    if(-not($record.PSObject.Properties.Name-contains'peak_managed_memory_bytes')){
      # A first formal worker can be handed from an older in-memory runner
      # during a repository upgrade.  Preserve safe admission rather than
      # failing on the absent additive receipt field.
      $record|Add-Member -NotePropertyName peak_managed_memory_bytes `
        -NotePropertyValue ([int64]$record.peak_working_set_bytes) -Force
    }
    if($record.completed){$null=$completed.Add($record)}
  }
  if($null-ne$OnProcessCompleted){
    foreach($record in @($completed)){
      # Checkpoint callbacks may publish a manifest, whose helper deliberately
      # writes a receipt object to the pipeline.  The scheduler's contract is
      # a single result object, so callback output must not leak into callers
      # such as $waveResult (where it would turn the result into an array).
      try{$null = & $OnProcessCompleted $record}
      catch{
        if(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
           ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed'])){$checkpointWriterUnknown=$true}
        if($null-eq$checkpointFailure){$checkpointFailure=$_}
        else{$checkpointFailure.Exception.Data['simion_additional_checkpoint_error']=[string]$_}
        $pending.Clear()
      }
    }
  }
  if($pending.Count+$running.Count+$completed.Count-lt 1){throw 'No formal process was supplied.'}
  $started=Get-RepositoryUtcNow;$nextLaunch=$started
  $warningBytes=[int64]$limits.memory_admission_reserve_bytes
  $criticalBytes=[int64]$limits.memory_critical_reserve_bytes
  $recoveryStableSeconds=[int]$limits.memory_recovery_stable_seconds
  $maximumRecoveryAttempts=[int]$limits.maximum_memory_recovery_attempts
  $maximumDangerTerminations=[int]$limits.maximum_memory_danger_termination_attempts
  if($memoryWarningOnly){
    if($warningBytes-ne0){throw 'SIMION warning memory policy requires zero admission reserve.'}
  }else{
    Assert-RepositoryDispatchLimits -Limits $limits -PositiveIntegers memory_admission_reserve_bytes
  }
  if(-not$memoryWarningOnly-and$warningBytes-le$criticalBytes){
    throw 'Repository admission memory reserve must exceed the critical reserve.'
  }
  $estimation=$plan.estimation
  $plannedMemoryBudget=[int64]0
  $memorySafetyFactor=[double]1.0
  if($null-ne$estimation){
    if($estimation.PSObject.Properties.Name-contains'per_process_memory_budget_bytes'){
      $plannedMemoryBudget=[int64]$estimation.per_process_memory_budget_bytes
    }
    if($estimation.PSObject.Properties.Name-contains'memory_safety_factor'){
      $memorySafetyFactor=[double]$estimation.memory_safety_factor
    }
  }
  # A first formal observation can complete before dispatch begins.  In that
  # valid one-batch path the scheduler loop is skipped, but the final receipt
  # still records the admission basis.
  $dynamicAdmissionBytes=[int64]$plannedMemoryBudget
  $launchAdmissionBytes=$dynamicAdmissionBytes
  $criticalSince=$null;$recoverySafeSince=$null;$dangerRecoveryPending=$false
  $lastCpuAt=$null;$systemCpu=[double]0
  $peakWorkingSetAggregate=[int64]0;$peakManagedMemoryAggregate=[int64]0
  # Retain the largest per-process footprint observed for the whole wave.
  # When all live workers finish after a pressure intervention, recomputing
  # admission from the now-empty live set would otherwise fall back to a
  # stale profile and immediately over-admit the requeued work.
  $observedPerProcessManagedPeak=[int64]0
  $minimumAvailable=$null;$peakConcurrency=$running.Count
  $memoryWarningEvents=[Collections.ArrayList]::new();$memoryWarningActive=$false
  foreach($record in $ExistingProcessRecords){
    if($record.PSObject.Properties.Name-contains'memory_warning_events'){
      foreach($warningEvent in $record.memory_warning_events){$null=$memoryWarningEvents.Add($warningEvent)}
    }
  }
  $pauseEvents=[Collections.ArrayList]::new();$terminationEvents=[Collections.ArrayList]::new()
  $recoveryEvents=[Collections.ArrayList]::new();$requeueCounts=@{};$recoveryAttempts=0
  $batchFailureEvents=[Collections.ArrayList]::new();$batchFailureDetected=$false
  $dangerTerminationAttempts=0;$unschedulable=$false
  $resourcePauseActive=$false;$resourcePauseReason=$null
  if(-not($limits.PSObject.Properties.Name-contains'minimum_process_cpu_percent')){
    throw 'Repository dispatch limits require minimum_process_cpu_percent.'
  }
  $estimatedProcessCpu=[double]$limits.minimum_process_cpu_percent
  if([double]::IsNaN($estimatedProcessCpu)-or[double]::IsInfinity($estimatedProcessCpu)-or
     $estimatedProcessCpu-le0-or$estimatedProcessCpu-gt100){
    throw 'Repository minimum process CPU percent must be finite and in (0,100].'
  }
  if($null-ne$estimation-and$estimation.PSObject.Properties.Name-contains'per_process_cpu_percent'){
    $estimatedProcessCpu=[math]::Max($estimatedProcessCpu,[double]$estimation.per_process_cpu_percent)
  }
  # New plans carry the centrally compiled effective demand. Never multiply a
  # raw observation here: this preserves old frozen plans and prevents applying
  # the margin again during live admission, recovery or resource publication.
  if($limits.PSObject.Properties.Name-contains'minimum_process_cpu_budget_percent'){
    $minimumCpuBudget=[double]$limits.minimum_process_cpu_budget_percent
    if([double]::IsNaN($minimumCpuBudget)-or[double]::IsInfinity($minimumCpuBudget)-or$minimumCpuBudget-le0){
      throw 'Repository minimum CPU demand budget must be finite and positive.'
    }
    $estimatedProcessCpu=[math]::Max($estimatedProcessCpu,$minimumCpuBudget)
  }
  if($null-ne$estimation-and$estimation.PSObject.Properties.Name-contains'per_process_cpu_budget_percent'){
    $cpuBudget=[double]$estimation.per_process_cpu_budget_percent
    if([double]::IsNaN($cpuBudget)-or[double]::IsInfinity($cpuBudget)-or$cpuBudget-le0){
      throw 'Repository effective CPU demand must be finite and positive.'
    }
    $estimatedProcessCpu=[math]::Max($estimatedProcessCpu,$cpuBudget)
  }
  while($pending.Count-gt 0-or$running.Count-gt 0){
    $now=Get-RepositoryUtcNow;$nextRunning=[Collections.ArrayList]::new()
    $completedThisCycle=[Collections.ArrayList]::new()
    $aggregateWorkingSet=[int64]0;$aggregateManagedMemory=[int64]0
    $processSnapshot=$null
    if($running.Count-gt0){$processSnapshot=Get-RepositoryProcessSnapshot}
    foreach($record in @($running)){
      $sampleArgs=@{RootProcessIds=@($record.root_process_id);TrackedProcessIds=$record.tracked_process_ids;ProcessSnapshot=$processSnapshot}
      $recordRootStartedAtUtcTicks=[int64]0
      if($record.PSObject.Properties.Name -contains 'root_process_started_at_utc_ticks'){
        $recordRootStartedAtUtcTicks=[int64]$record.root_process_started_at_utc_ticks
        $sampleArgs.RootProcessStartedAtUtcTicks=@{([string]$record.root_process_id)=$recordRootStartedAtUtcTicks}
      }
      if($record.PSObject.Properties.Name -contains 'tracked_process_started_at_utc_ticks'){
        $sampleArgs.TrackedProcessStartedAtUtcTicks=$record.tracked_process_started_at_utc_ticks
      }
      $sample=Get-ManagedSolverProcessSample @sampleArgs
      $record.tracked_process_ids=@($sample.tracked_process_ids)
      if(-not ($record.PSObject.Properties.Name -contains 'tracked_process_started_at_utc_ticks')){
        $record|Add-Member -NotePropertyName tracked_process_started_at_utc_ticks -NotePropertyValue @{} -Force
      }
      # The scheduler accepts an older sample shape during a live upgrade;
      # start-time identity is additive, not a requirement for that seam.
      if($sample.PSObject.Properties.Name -contains 'tracked_process_started_at_utc_ticks'){
        $record.tracked_process_started_at_utc_ticks=$sample.tracked_process_started_at_utc_ticks
      }
      $record.active=Test-RepositoryManagedProcessIsActive `
        -Specification $record.specification -RootProcessId ([int]$record.root_process_id) `
        -RootProcessStartedAtUtcTicks $recordRootStartedAtUtcTicks `
        -Sample $sample
      # Direct SIMION uses its exact root identity.  Launchers retain ordinary
      # descendants as completion authorities, while a verified Windows
      # system conhost remains accounted but cannot strand a completed batch.
      $record.peak_working_set_bytes=[math]::Max(
        [int64]$record.peak_working_set_bytes,[int64]$sample.working_set_bytes)
      $record.peak_managed_memory_bytes=[math]::Max(
        [int64]$record.peak_managed_memory_bytes,[int64]$sample.managed_memory_bytes)
      $observedPerProcessManagedPeak=[math]::Max(
        $observedPerProcessManagedPeak,[int64]$record.peak_managed_memory_bytes)
      $aggregateWorkingSet+=[int64]$sample.working_set_bytes
      $aggregateManagedMemory+=[int64]$sample.managed_memory_bytes
      if($record.active){$null=$nextRunning.Add($record);continue}
      $record.process.WaitForExit()
      $exitCode=$(if($record.pressure_terminated){$null}else{[int]$record.process.ExitCode})
      if(-not($record.specification.PSObject.Properties.Name-contains'retain_process_handle')-or-not$record.specification.retain_process_handle){$record.process.Dispose()}
      $record.exit_code=$exitCode
      $record.completed=$true
      if(-not$record.pressure_terminated){
        $null=$completed.Add($record)
        $null=$completedThisCycle.Add($record)
        if($null-ne$OnProcessCompleted){
          try{$null = & $OnProcessCompleted $record}
          catch{
            if(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
               ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed'])){$checkpointWriterUnknown=$true}
            if($null-eq$checkpointFailure){$checkpointFailure=$_}
            else{$checkpointFailure.Exception.Data['simion_additional_checkpoint_error']=[string]$_}
            $pending.Clear()
          }
        }
      }
    }
    $running=$nextRunning
    # Report after the whole running set has been sampled.  Reporting inside
    # the loop would make simultaneous completions look as though no sibling
    # workers remained, because later live records had not yet been counted.
    foreach($record in @($completedThisCycle)){
      Write-RepositorySchedulerEvent -Event 'BATCH_COMPLETED' -Record $record `
        -ActiveCount $running.Count -PendingCount $pending.Count `
        -Details @{EXIT_CODE=$record.exit_code;NATURAL='true';WALL_CLOCK_SECONDS=([math]::Round(((Get-RepositoryUtcNow)-$record.started_at).TotalSeconds,3));MORE_PENDING=($(if($pending.Count-gt0){'true'}else{'false'}))}
    }
    $failedThisCycle=@($completedThisCycle|Where-Object{
      $null-ne$_.exit_code-and[int]$_.exit_code-ne0
    })
    if($failedThisCycle.Count -gt 0 -and -not $batchFailureDetected){
      # A non-zero exit invalidates the complete cohort, so do not launch new
      # work. Already-running siblings retain their natural evidence instead
      # of being force-stopped because a peer failed.
      $cancelledPending=$pending.Count
      $pending.Clear()
      $null=$batchFailureEvents.Add([ordered]@{
        at_utc=$now.ToString('o');failed_batch_count=$failedThisCycle.Count
        cancelled_pending_batch_count=$cancelledPending;stopped_active_batch_count=0
      })
      $batchFailureDetected=$true
      Write-RepositorySchedulerEvent -Event 'BATCH_FAILURE_HALT_NEW_LAUNCHES' `
        -ActiveCount $running.Count -PendingCount $cancelledPending `
        -Details @{FAILED_BATCH_COUNT=$failedThisCycle.Count;ACTION='WAIT_FOR_HEALTHY_ACTIVE_BATCHES'}
    }
    $peakWorkingSetAggregate=[math]::Max($peakWorkingSetAggregate,$aggregateWorkingSet)
    $peakManagedMemoryAggregate=[math]::Max($peakManagedMemoryAggregate,$aggregateManagedMemory)
    $available=Get-RepositoryAvailableMemoryBytes
    $minimumAvailable=$(if($null-eq$minimumAvailable){$available}else{[math]::Min([int64]$minimumAvailable,$available)})
    if($null-eq$lastCpuAt-or($now-$lastCpuAt).TotalSeconds-ge 2){
      $observedSystemCpu=Get-SystemCpuPercent
      if($null-ne$observedSystemCpu){$systemCpu=[double]$observedSystemCpu}
      $lastCpuAt=$now
    }
    # A dispatch plan limits lanes from the first formal peak.  Before every
    # later launch, also reserve one expected process footprint based on the
    # highest live peak seen so far.  This tightens admission immediately if
    # SIMION grows after the frozen observation window, without a project-local
    # RAM setting or an unnecessary calibration run.
    $livePeak=[int64]0
    foreach($record in @($running)){
      $livePeak=[math]::Max($livePeak,[int64]$record.peak_managed_memory_bytes)
    }
    $dynamicAdmissionBytes=[int64][math]::Max(
      $plannedMemoryBudget,[math]::Ceiling(
        [math]::Max($livePeak,$observedPerProcessManagedPeak)*$memorySafetyFactor))
    # Predicted memory shortage warns at zero active workers; sibling starts
    # still require their measured footprint to avoid oversubscribing RAM.
    $launchAdmissionBytes=$dynamicAdmissionBytes
    $memoryShortage=$available-lt$dynamicAdmissionBytes-or$available-lt$criticalBytes
    if($memoryWarningOnly-and$memoryShortage-and-not$memoryWarningActive){
      $null=$memoryWarningEvents.Add([ordered]@{
        at_utc=$now.ToString('o');available_memory_bytes=$available
        expected_process_memory_bytes=$dynamicAdmissionBytes;active_count=$running.Count
        action='warn_continue_single_worker';memory_policy='warn_single_worker'
      })
      Write-RepositorySchedulerEvent -Event 'MEMORY_PRESSURE_WARNING' `
        -ActiveCount $running.Count -PendingCount $pending.Count `
        -Details @{AVAILABLE_MEMORY_BYTES=$available;EXPECTED_PROCESS_MEMORY_BYTES=$dynamicAdmissionBytes;MEMORY_POLICY='warn_single_worker';ACTION='CONTINUE_SINGLE_WORKER'}
      $memoryWarningActive=$true
    }elseif(-not$memoryShortage){$memoryWarningActive=$false}
    if($available-lt$criticalBytes){if($null-eq$criticalSince){$criticalSince=$now}}else{$criticalSince=$null}
    if($null-ne$criticalSince-and($now-$criticalSince).TotalSeconds-ge[int]$limits.memory_critical_seconds-and$running.Count-gt 0){
      if($dangerTerminationAttempts-ge$maximumDangerTerminations){
        # The permitted newest-worker interventions are exhausted.
        # Another critical window means the run cannot be made safe
        # by another incremental reduction: terminate its remaining managed
        # workers and preserve a failed receipt rather than letting Windows
        # thrash indefinitely.
        foreach($record in @($running)){
          Stop-ManagedSolverProcesses -ProcessIds @($record.tracked_process_ids)
        }
        $unschedulable=$true
        Write-RepositorySchedulerEvent -Event 'MEMORY_DANGER_UNRECOVERABLE' `
          -ActiveCount $running.Count -PendingCount $pending.Count `
          -Details @{AVAILABLE_MEMORY_BYTES=$available;CRITICAL_SECONDS=$limits.memory_critical_seconds;CRITICAL_THRESHOLD_BYTES=$criticalBytes;TERMINATION_ATTEMPTS=$dangerTerminationAttempts}
        break
      }
      $victim=@($running|Sort-Object started_at -Descending)[0];$name=[string]$victim.name
      $count=$(if($requeueCounts.ContainsKey($name)){[int]$requeueCounts[$name]}else{0})
      Stop-ManagedSolverProcesses -ProcessIds @($victim.tracked_process_ids)
      $victim.pressure_terminated=$true;$requeueCounts[$name]=$count+1
      # Preserve balanced lane completion.  A pressure-interrupted worker has
      # already consumed part of its lane's wall time; placing it behind an
      # optional balancing remainder would leave one lane idle at the end of
      # the wave.  It must be the next eligible launch after the required
      # recovery observation.
      $pending.Insert(0,$victim.specification)
      $maximumConcurrency=[math]::Max(1,$maximumConcurrency-1)
      $dangerTerminationAttempts+=1
      Write-RepositorySchedulerEvent -Event 'MEMORY_DANGER_TERMINATION' -Record $victim `
        -ActiveCount $running.Count -PendingCount $pending.Count `
        -Details @{AVAILABLE_MEMORY_BYTES=$available;CRITICAL_SECONDS=$limits.memory_critical_seconds;CRITICAL_THRESHOLD_BYTES=$criticalBytes;REMAINING_TERMINATION_ATTEMPTS=($maximumDangerTerminations-$dangerTerminationAttempts)}
      $null=$terminationEvents.Add([ordered]@{
        process=$name;at_utc=$now.ToString('o')
        reason='available_memory_below_critical_reserve'
        critical_reserve_bytes=$criticalBytes; critical_seconds=[int]$limits.memory_critical_seconds
        requeued=$true;requeue_priority='front';new_maximum_concurrency=$maximumConcurrency
      })
      # A requeued worker must not immediately restart after a danger kill,
      # including at one lane where reducing maximumConcurrency has no effect.
      # It receives the same policy-defined stable-admission observation as a
      # restored multi-lane worker.
      $criticalSince=$null;$recoverySafeSince=$null;$dangerRecoveryPending=$true
      $nextLaunch=$now.AddSeconds([int]$limits.launch_stagger_seconds);Start-Sleep -Milliseconds 500;continue
    }
    $recoveryAdmissionSafe=$available-ge($warningBytes+$dynamicAdmissionBytes)-and
      ($systemCpu+$estimatedProcessCpu-lt[double]$limits.cpu_admission_percent)
    $recoveryEligible=$dangerRecoveryPending-and$pending.Count-gt 0-and
      $recoveryAttempts-lt$maximumRecoveryAttempts
    if($recoveryEligible){
      if($recoveryAdmissionSafe){
        if($null-eq$recoverySafeSince){$recoverySafeSince=$now}
        elseif(($now-$recoverySafeSince).TotalSeconds-ge$recoveryStableSeconds){
          $recoveryAttempts+=1
          $null=$recoveryEvents.Add([ordered]@{
            at_utc=$now.ToString('o');attempt=$recoveryAttempts
            effective_maximum_concurrency=$maximumConcurrency
            available_memory_bytes=$available;dynamic_admission_bytes=$dynamicAdmissionBytes
            system_cpu_percent=$systemCpu
          })
          $recoverySafeSince=$null;$dangerRecoveryPending=$false;$nextLaunch=$now
          Write-RepositorySchedulerEvent -Event 'MEMORY_RECOVERY_RELAUNCH_ALLOWED' `
            -ActiveCount $running.Count -PendingCount $pending.Count `
            -Details @{ATTEMPT=$recoveryAttempts;AVAILABLE_MEMORY_BYTES=$available;DYNAMIC_ADMISSION_BYTES=$dynamicAdmissionBytes;MAXIMUM_CONCURRENCY=$maximumConcurrency}
        }
      }else{$recoverySafeSince=$null}
    }else{$recoverySafeSince=$null}
    $memoryLaunchAllowed=$available-ge($warningBytes+$launchAdmissionBytes)-or
      ($memoryWarningOnly-and$running.Count-eq0)
    $canLaunch=$pending.Count-gt 0-and$running.Count-lt$maximumConcurrency-and
      -not$dangerRecoveryPending-and$now-ge$nextLaunch-and$memoryLaunchAllowed-and
      ($systemCpu+$estimatedProcessCpu-lt[double]$limits.cpu_admission_percent)
    $exclusiveResourceBlocked=$false;$nextSpecification=$null
    if($canLaunch){
      $activeExclusiveResourceKeys=@{}
      foreach($activeRecord in @($running)){
        $activeSpecification=$activeRecord.specification
        if($activeSpecification.PSObject.Properties.Name-contains'exclusive_resource_key'-and
            -not[string]::IsNullOrWhiteSpace([string]$activeSpecification.exclusive_resource_key)){
          $activeExclusiveResourceKeys[[string]$activeSpecification.exclusive_resource_key]=$true
        }
      }
      foreach($candidate in @($pending)){
        $candidateKey=$(if($candidate.PSObject.Properties.Name-contains'exclusive_resource_key'){
          [string]$candidate.exclusive_resource_key
        }else{''})
        if([string]::IsNullOrWhiteSpace($candidateKey) -or -not $activeExclusiveResourceKeys.ContainsKey($candidateKey)){
          $nextSpecification=$candidate;break
        }
      }
      if($null-eq$nextSpecification){$canLaunch=$false;$exclusiveResourceBlocked=$true}
    }
    if($canLaunch){
      if($resourcePauseActive){
        Write-RepositorySchedulerEvent -Event 'RESOURCE_ADMISSION_RESUMED' `
          -ActiveCount $running.Count -PendingCount $pending.Count `
          -Details @{AVAILABLE_MEMORY_BYTES=$available;PREVIOUS_REASON=$resourcePauseReason;REQUIRED_AVAILABLE_MEMORY_BYTES=($warningBytes+$dynamicAdmissionBytes)}
        $resourcePauseActive=$false;$resourcePauseReason=$null
      }
      $spec=$nextSpecification;$null=$pending.Remove($spec)
      $launchInProgress=$true
      $launched=Start-RepositoryScheduledProcess -Specification $spec
      $null=$running.Add($launched)
      $launchInProgress=$false
      $peakConcurrency=[math]::Max($peakConcurrency,$running.Count)
      Write-RepositorySchedulerEvent -Event 'BATCH_STARTED' -Record $launched `
        -ActiveCount $running.Count -PendingCount $pending.Count `
        -Details @{MAXIMUM_CONCURRENCY=$maximumConcurrency}
      $nextLaunch=(Get-RepositoryUtcNow).AddSeconds([int]$limits.launch_stagger_seconds)
    }elseif($pending.Count-gt 0-and$running.Count-lt$maximumConcurrency){
      if($pauseEvents.Count-eq 0-or($now-[datetimeoffset]$pauseEvents[$pauseEvents.Count-1].at_utc).TotalSeconds-ge 5){
        $reason=$(if($exclusiveResourceBlocked){'exclusive_resource_in_use'}elseif($dangerRecoveryPending){'post_danger_recovery_observation'}elseif(
          -not$memoryLaunchAllowed){'available_memory_below_dynamic_admission'}elseif(
          ($systemCpu+$estimatedProcessCpu)-ge[double]$limits.cpu_admission_percent){'cpu_admission_exceeded'}else{'launch_stagger_pending'})
        $null=$pauseEvents.Add([ordered]@{
          at_utc=$now.ToString('o');reason=$reason;available_memory_bytes=$available
          required_available_memory_bytes=($warningBytes+$launchAdmissionBytes)
          dynamic_admission_bytes=$dynamicAdmissionBytes;launch_admission_bytes=$launchAdmissionBytes;system_cpu_percent=$systemCpu
        })
        if($reason-ne'launch_stagger_pending'){
          Write-RepositorySchedulerEvent -Event 'RESOURCE_ADMISSION_PAUSED' `
            -ActiveCount $running.Count -PendingCount $pending.Count `
          -Details @{AVAILABLE_MEMORY_BYTES=$available;DYNAMIC_ADMISSION_BYTES=$dynamicAdmissionBytes;LAUNCH_ADMISSION_BYTES=$launchAdmissionBytes;REASON=$reason;REQUIRED_AVAILABLE_MEMORY_BYTES=($warningBytes+$launchAdmissionBytes);SYSTEM_CPU_PERCENT=$systemCpu}
          $resourcePauseActive=$true;$resourcePauseReason=$reason
        }
      }
    }
    if($pending.Count-gt 0-or$running.Count-gt 0){Start-Sleep -Milliseconds 500}
  }
  if($unschedulable){foreach($record in @($running)){Stop-ManagedSolverProcesses -ProcessIds @($record.tracked_process_ids)}}
  $failed=@($completed|Where-Object{$null-ne$_.exit_code-and[int]$_.exit_code-ne 0})
  $completedWorkUnits=[int64]0
  foreach($record in @($completed)){
    if($record.PSObject.Properties.Name-contains'specification'-and
       $record.specification.PSObject.Properties.Name-contains'scheduler_batch'-and
       $record.specification.scheduler_batch.PSObject.Properties.Name-contains'count'){
      $completedWorkUnits+=[int64]$record.specification.scheduler_batch.count
    }
  }
  $isWorkItemDispatch=$plan.PSObject.Properties.Name-contains'dispatch_unit'-and
    [string]$plan.dispatch_unit-eq'independent_work_items'
  $expectedWorkUnits=$(if($isWorkItemDispatch){[string]$plan.work_item_count}elseif(
    $plan.PSObject.Properties.Name-contains'particle_count'){[string]$plan.particle_count}else{'UNKNOWN'})
  $completedLabel=$(if($isWorkItemDispatch){'COMPLETED_WORK_ITEMS'}else{'COMPLETED_PARTICLES'})
  $expectedLabel=$(if($isWorkItemDispatch){'EXPECTED_WORK_ITEMS'}else{'EXPECTED_PARTICLES'})
  Write-RepositorySchedulerEvent -Event $(if($unschedulable){'BATCH_WAVE_TERMINATED'}else{'BATCH_WAVE_COMPLETED'}) `
    -ActiveCount $running.Count -PendingCount $pending.Count `
    -Details @{COMPLETED_BATCHES=$completed.Count;$completedLabel=$completedWorkUnits;$expectedLabel=$expectedWorkUnits;FAILED_BATCHES=$failed.Count;STATUS=$(if($unschedulable){'RESOURCE_PRESSURE_FAILED'}elseif($failed.Count-gt0){'PROCESS_FAILED'}else{'COMPLETED'});TOTAL_WALL_CLOCK_SECONDS=([math]::Round(((Get-RepositoryUtcNow)-$started).TotalSeconds,3))}
  $usage=[ordered]@{
    schema_version=2;role='multipole_resource_usage'
    status=$(if($unschedulable){'resource_pressure_failed'}elseif($failed.Count-gt 0){'process_failed'}else{'running'})
    failure_class=$(if($unschedulable){'memory_danger_recovery_attempts_exhausted'}else{$null})
    limit_name=$(if($unschedulable){'system_available_memory'}else{$null})
    started_at_utc=$started.ToString('o');wall_clock_seconds=[math]::Round(((Get-RepositoryUtcNow)-$started).TotalSeconds,3)
    peak_process_tree_working_set_bytes=$peakWorkingSetAggregate
    peak_process_tree_managed_memory_bytes=$peakManagedMemoryAggregate
    minimum_system_available_memory_bytes=$minimumAvailable
    peak_run_directory_bytes=(Get-RunDirectoryBytes -RunDir $RunDir);final_retained_bytes=$null;limits=$plan.limits
    final_retained_measurement_scope='run_directory_before_terminal_manifest'
    execution_wave=[ordered]@{dispatch='repository_adaptive_staggered';process_count=$completed.Count;peak_concurrency=$peakConcurrency}
    scheduler_receipt=[ordered]@{
      resource_identity_source=[string]$plan.estimation.kind
      memory_policy=$(if($memoryWarningOnly){'warn_single_worker'}else{'reserve_and_terminate'})
      memory_warning_events=@($memoryWarningEvents)
      planned_maximum_concurrency=[int]$plan.limits.maximum_concurrency
      final_maximum_concurrency=$maximumConcurrency;peak_concurrency=$peakConcurrency
      minimum_available_memory_bytes=$minimumAvailable
      dynamic_admission_bytes_at_finish=$dynamicAdmissionBytes
      per_process_cpu_budget_percent=$estimatedProcessCpu
      launch_pause_events=@($pauseEvents);termination_requeue_events=@($terminationEvents)
      recovery_relaunch_events=@($recoveryEvents);recovery_attempt_count=$recoveryAttempts
      danger_termination_attempt_count=$dangerTerminationAttempts
      batch_failure_cancellation_events=@($batchFailureEvents)
    }
  }
  # Keep the measured worker identity and its own work count together. Wave
  # aggregate memory is not a per-worker observation when workers overlap.
  $memoryObservation=$null
  foreach($record in @($completed)){
    if(-not($record.specification.PSObject.Properties.Name-contains'scheduler_batch')-or
       -not($record.PSObject.Properties.Name-contains'root_process_id')-or
       -not($record.PSObject.Properties.Name-contains'root_process_started_at_utc_ticks')){continue}
    $count=[int]$record.specification.scheduler_batch.count
    $peak=[int64]$record.peak_managed_memory_bytes
    if($count-lt1-or$peak-lt1){continue}
    if($null-eq$memoryObservation-or$peak-gt$memoryObservation.peak_managed_memory_bytes){
      $memoryObservation=[ordered]@{
        process=[string]$record.name;work_units=$count;peak_managed_memory_bytes=$peak
        root_process_id=[int]$record.root_process_id
        root_process_started_at_utc_ticks=[int64]$record.root_process_started_at_utc_ticks
      }
    }
  }
  if($null-ne$memoryObservation){$usage.per_process_memory_observation=$memoryObservation}
  if($ExistingProcessRecords.Count-gt 0-and
      $ExistingProcessRecords[0].PSObject.Properties.Name-contains'completed_during_observation'){
    $first=$ExistingProcessRecords[0]
    $usage.first_formal_observation=[ordered]@{
      process=[string]$first.name;peak_working_set_bytes=[int64]$first.peak_working_set_bytes
      peak_managed_memory_bytes=[int64]$first.peak_managed_memory_bytes
      completed_naturally=[bool]$first.completed_during_observation
      process_cpu_percent=[double]$first.observed_process_cpu_percent
      process_cpu_peak_percent=$(if($first.PSObject.Properties.Name-contains'observed_process_cpu_peak_percent'){[double]$first.observed_process_cpu_peak_percent}else{[double]$first.observed_process_cpu_percent})
      process_cpu_measurement=$(if($first.PSObject.Properties.Name-contains'observed_process_cpu_measurement'){[string]$first.observed_process_cpu_measurement}else{'legacy_peak'})
      background_cpu_percent=[double]$first.observed_background_cpu_percent
    }
  }
  Write-ResourceUsage -Usage $usage -Path $UsagePath
  if($null-ne$checkpointFailure){
    $checkpointFailure.Exception.Data['simion_wave_writer_completion_confirmed']=(-not$unschedulable-and-not$checkpointWriterUnknown)
    throw $checkpointFailure
  }
  return [pscustomobject]@{
    resource_budget_exceeded=$unschedulable;limit_name=$usage.limit_name
    processes=@($completed|ForEach-Object{[pscustomobject]@{name=$_.name;exit_code=$_.exit_code}})
  }
  } catch {
    $failure=$_
    $failureWriterUnknown=(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
      ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed']))
    if($null-ne$checkpointFailure-and-not[object]::ReferenceEquals($failure.Exception,$checkpointFailure.Exception)){
      $checkpointFailure.Exception.Data['simion_wave_followup_error']=[string]$failure
      $failure=$checkpointFailure
    }
    if($launchInProgress-and$failure.Exception.Data['simion_native_launch_not_attempted']){$launchInProgress=$false}
    $active=@($running|Where-Object{-not$_.completed})
    if(-not$NoFailureDrain-and$active.Count){
      try {
        # No pending sibling or checkpoint callback is retried here. The
        # existing owner observes the already-started processes to completion.
        $drainArgs=@{DispatchPlanPath=$DispatchPlanPath;RunDir=$RunDir;UsagePath=$UsagePath;
          ProcessSpecifications=@();ExistingProcessRecords=$active;NoFailureDrain=$true}
        if($null-ne$OnProcessCompleted){$drainArgs.OnProcessCompleted=$OnProcessCompleted}
        $drained=Invoke-ResourceBudgetedProcesses @drainArgs
        if(-not$drained.resource_budget_exceeded-and-not$launchInProgress){
          $failure.Exception.Data['simion_wave_writer_completion_confirmed']=-not($failureWriterUnknown-or$checkpointWriterUnknown)
        }
      } catch {
        $failure.Exception.Data['simion_wave_drain_error']=[string]$_
        if($_.Exception.Data['simion_wave_writer_completion_confirmed']-and-not$launchInProgress){
          $failure.Exception.Data['simion_wave_writer_completion_confirmed']=-not($failureWriterUnknown-or$checkpointWriterUnknown)
        }
        Write-Warning "SIMION batch drain failed: $_"
      }
    } elseif(-not$launchInProgress-and$active.Count-eq0-and
        -not$failure.Exception.Data.Contains('simion_wave_writer_completion_confirmed')) {
      $failure.Exception.Data['simion_wave_writer_completion_confirmed']=-not($failureWriterUnknown-or$checkpointWriterUnknown)
    }
    if($failureWriterUnknown-or$checkpointWriterUnknown){$failure.Exception.Data['simion_wave_writer_completion_confirmed']=$false}
    if(-not$failure.Exception.Data.Contains('simion_wave_writer_completion_confirmed')){
      $failure.Exception.Data['simion_wave_writer_completion_confirmed']=$false
    }
    throw $failure
  }
}

function Complete-ResourceUsage {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath
  )
  $usage=Get-Content -LiteralPath $UsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $finalBytes=Get-RunDirectoryBytes -RunDir $RunDir
  $usage.final_retained_bytes=$finalBytes
  $usage.peak_run_directory_bytes=[math]::Max([int64]$usage.peak_run_directory_bytes,$finalBytes)
  if($usage.status-eq'running'){$usage.status='completed'}
  Write-ResourceUsage -Usage $usage -Path $UsagePath
  return $true
}
