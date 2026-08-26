Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

if(-not('MultipoleMemoryStatus' -as[type])){
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MultipoleMemoryStatus {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)]
  public class Status {
    public uint length=(uint)Marshal.SizeOf(typeof(Status));
    public uint load; public ulong totalPhysical; public ulong availablePhysical;
    public ulong totalPage; public ulong availablePage; public ulong totalVirtual;
    public ulong availableVirtual; public ulong availableExtended;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Auto, SetLastError=true)]
  static extern bool GlobalMemoryStatusEx([In,Out] Status status);
  public static ulong AvailableBytes() {
    var status=new Status();
    if(!GlobalMemoryStatusEx(status)) throw new InvalidOperationException("GlobalMemoryStatusEx failed.");
    return status.availablePhysical;
  }
  public static ulong TotalBytes() {
    var status=new Status();
    if(!GlobalMemoryStatusEx(status)) throw new InvalidOperationException("GlobalMemoryStatusEx failed.");
    return status.totalPhysical;
  }
}
'@
}

function Get-RunDirectoryBytes {
  param([Parameter(Mandatory)][string]$RunDir)
  if(-not(Test-Path -LiteralPath $RunDir -PathType Container)){return [int64]0}
  $sum=(Get-ChildItem -LiteralPath $RunDir -Recurse -File -ErrorAction SilentlyContinue|
    Measure-Object -Property Length -Sum).Sum
  return $(if($null-eq$sum){[int64]0}else{[int64]$sum})
}

function Get-ProcessTreeWorkingSetBytes {
  param([Parameter(Mandatory)][int]$RootProcessId)
  $processes=@(Get-Process -ErrorAction SilentlyContinue)
  $ids=[Collections.Generic.HashSet[int]]::new()
  $null=$ids.Add($RootProcessId)
  $changed=$true
  while($changed){
    $changed=$false
    foreach($process in $processes){
      try{$parentId=[int]$process.Parent.Id}catch{continue}
      if($ids.Contains($parentId)-and$ids.Add([int]$process.Id)){$changed=$true}
    }
  }
  $sum=[int64]0
  foreach($processId in $ids){
    try{$sum+=[int64](Get-Process -Id $processId -ErrorAction Stop).WorkingSet64}catch{}
  }
  return $sum
}

function Get-ManagedSolverProcessSample {
  <#
    Return the unique live process family belonging to one scheduler launch.

    SIMION may use a short-lived launcher which starts another process and then
    exits. Keep the launched root and every descendant by Windows parent ID;
    executable-name discovery would mix concurrent runs of the same solver.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][int[]]$RootProcessIds,
    [int[]]$TrackedProcessIds=@()
  )
  $processes=@(Get-Process -ErrorAction SilentlyContinue)
  $known=[Collections.Generic.HashSet[int]]::new()
  foreach($processId in @($RootProcessIds)+@($TrackedProcessIds)){
    if($processId -gt 0){$null=$known.Add([int]$processId)}
  }
  $parentByChild=@{}
  # Get-Process.Parent fails once a short-lived launcher has exited, even
  # while its solver child is still active.  Win32_Process retains the child
  # record's ParentProcessId, so use it first to keep that child in this
  # launch family rather than prematurely declaring the formal batch done.
  try{
    foreach($process in @(Get-CimInstance Win32_Process -ErrorAction Stop)){
      $parentByChild[[int]$process.ProcessId]=[int]$process.ParentProcessId
    }
  }catch{
    foreach($process in $processes){
      try{$parentByChild[[int]$process.Id]=[int]$process.Parent.Id}catch{}
    }
  }
  $changed=$true
  while($changed){
    $changed=$false
    foreach($childId in @($parentByChild.Keys)){
      if($known.Contains([int]$parentByChild[$childId]) -and $known.Add([int]$childId)){$changed=$true}
    }
  }
  $byId=@{}
  foreach($process in $processes){$byId[[int]$process.Id]=$process}
  $active=@()
  $bytes=[int64]0
  $cpuTicks=[int64]0
  foreach($processId in $known){
    if($byId.ContainsKey([int]$processId)){
      $process=$byId[[int]$processId]
      $active+=[int]$processId
      $bytes+=[int64]$process.WorkingSet64
      try{$cpuTicks+=[int64]$process.TotalProcessorTime.Ticks}catch{}
    }
  }
  return [pscustomobject]@{
    tracked_process_ids=@($known|Sort-Object)
    active_process_ids=@($active|Sort-Object)
    working_set_bytes=$bytes
    total_processor_time_ticks=$cpuTicks
  }
}

function Stop-ManagedSolverProcesses {
  param([Parameter(Mandatory)][int[]]$ProcessIds)
  foreach($processId in $ProcessIds){
    if(Get-Process -Id $processId -ErrorAction SilentlyContinue){
      & taskkill.exe /PID $processId /T /F | Out-Null
    }
  }
}

function Write-ResourceUsage {
  param([Parameter(Mandatory)][hashtable]$Usage,[Parameter(Mandatory)][string]$Path)
  $temporary="$Path.tmp"
  $Usage|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $temporary -Encoding UTF8
  Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Invoke-ResourceBudgetedProcess {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ResolvedBudgetPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [Parameter(Mandatory)][string]$FilePath,
    [Parameter(Mandatory)][string[]]$ArgumentList,
    [string]$WorkingDirectory='',
    [string]$RedirectStandardOutput='',
    [string]$RedirectStandardError='',
    [hashtable]$Environment=@{}
  )
  $budget=Get-Content -LiteralPath $ResolvedBudgetPath -Raw -Encoding UTF8|ConvertFrom-Json
  $limits=$budget.limits
  $directorySampleProperty=$limits.PSObject.Properties[
    'transient_run_directory_sample_interval_seconds'
  ]
  $directorySampleIntervalSeconds=[double]0.5
  if($null-ne$directorySampleProperty){
    try{$directorySampleIntervalSeconds=[convert]::ToDouble(
      $directorySampleProperty.Value,[Globalization.CultureInfo]::InvariantCulture)}catch{
      throw 'Transient run-directory sample interval must be one positive integer.'
    }
    if($directorySampleProperty.Value-is[bool]-or
        $directorySampleIntervalSeconds-lt 1-or
        $directorySampleIntervalSeconds-ne[math]::Floor($directorySampleIntervalSeconds)){
      throw 'Transient run-directory sample interval must be one positive integer.'
    }
  }
  if(Test-Path -LiteralPath $UsagePath -PathType Leaf){
    $usage=Get-Content -LiteralPath $UsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $started=[datetimeoffset]::Parse([string]$usage.started_at_utc)
  }else{
    $started=[datetimeoffset]::UtcNow
    $usage=[ordered]@{
      schema_version=1;role='multipole_resource_usage';status='running'
      failure_class=$null;limit_name=$null;started_at_utc=$started.ToString('o')
      wall_clock_seconds=0.0;peak_process_tree_working_set_bytes=[int64]0
      minimum_system_available_memory_bytes=$null;warning_names=@();peak_run_directory_bytes=[int64]0
      final_retained_bytes=$null;limits=$limits
      final_retained_measurement_scope='run_directory_before_terminal_manifest'
    }
  }
  $startArguments=@{FilePath=$FilePath;ArgumentList=$ArgumentList;PassThru=$true;WindowStyle='Hidden'}
  if(-not[string]::IsNullOrWhiteSpace($WorkingDirectory)){$startArguments.WorkingDirectory=$WorkingDirectory}
  if(-not[string]::IsNullOrWhiteSpace($RedirectStandardOutput)){
    $startArguments.RedirectStandardOutput=$RedirectStandardOutput
  }
  if(-not[string]::IsNullOrWhiteSpace($RedirectStandardError)){
    $startArguments.RedirectStandardError=$RedirectStandardError
  }
  if($Environment.Count-gt 0){$startArguments.Environment=$Environment}
  $process=Start-Process @startArguments
  $lastDirectorySampleAt=$null
  $trackedProcessIds=@([int]$process.Id)
  $managedActive=$true
  while($managedActive){
    $now=[datetimeoffset]::UtcNow
    $elapsed=($now-$started).TotalSeconds
    $sample=Get-ManagedSolverProcessSample -RootProcessIds @([int]$process.Id) `
      -TrackedProcessIds $trackedProcessIds
    $trackedProcessIds=@($sample.tracked_process_ids)
    $managedActive=@($sample.active_process_ids).Count -gt 0
    $treeBytes=[int64]$sample.working_set_bytes
    $availableBytes=[int64][MultipoleMemoryStatus]::AvailableBytes()
    $sampleDirectory=$null-eq$lastDirectorySampleAt-or
      ($now-$lastDirectorySampleAt).TotalSeconds-ge$directorySampleIntervalSeconds
    if($sampleDirectory){
      $directoryBytes=Get-RunDirectoryBytes -RunDir $RunDir
      $lastDirectorySampleAt=$now
      $usage.peak_run_directory_bytes=[math]::Max(
        [int64]$usage.peak_run_directory_bytes,$directoryBytes)
    }
    $usage.wall_clock_seconds=[math]::Round($elapsed,3)
    $usage.peak_process_tree_working_set_bytes=[math]::Max(
      [int64]$usage.peak_process_tree_working_set_bytes,$treeBytes)
    $usage.minimum_system_available_memory_bytes=$(if($null-eq$usage.minimum_system_available_memory_bytes){
      $availableBytes
    }else{[math]::Min([int64]$usage.minimum_system_available_memory_bytes,$availableBytes)})
    Write-ResourceUsage -Usage $usage -Path $UsagePath
    if(-not$managedActive){break}
    Start-Sleep -Milliseconds 500
  }
  $usage.wall_clock_seconds=[math]::Round(
    ([datetimeoffset]::UtcNow-$started).TotalSeconds,3)
  $directoryBytes=Get-RunDirectoryBytes -RunDir $RunDir
  $usage.peak_run_directory_bytes=[math]::Max(
    [int64]$usage.peak_run_directory_bytes,$directoryBytes)
  $usage.status=$(if($process.ExitCode-eq 0){'running'}else{'process_failed'})
  Write-ResourceUsage -Usage $usage -Path $UsagePath
  return [pscustomobject]@{exit_code=$process.ExitCode;resource_budget_exceeded=$false;limit_name=$null;
    resource_calibration_complete=$false}
}

function Assert-RepositoryProcessSpecification {
  param([Parameter(Mandatory)]$Specification)
  foreach($required in @('name','file_path','argument_list','stdout','stderr','environment')){
    if(-not($Specification.PSObject.Properties.Name-contains$required)){
      throw "Scheduled process specification is missing $required."
    }
  }
}

function Start-RepositoryScheduledProcess {
  param([Parameter(Mandatory)]$Specification)
  Assert-RepositoryProcessSpecification -Specification $Specification
  $arguments=@{
    FilePath=[string]$Specification.file_path;ArgumentList=@($Specification.argument_list)
    PassThru=$true;WindowStyle='Hidden';RedirectStandardOutput=[string]$Specification.stdout
    RedirectStandardError=[string]$Specification.stderr;Environment=[hashtable]$Specification.environment
  }
  if($Specification.PSObject.Properties.Name-contains'working_directory'){
    $arguments.WorkingDirectory=[string]$Specification.working_directory
  }
  $started=[datetimeoffset]::UtcNow;$process=Start-Process @arguments
  return [pscustomobject]@{
    name=[string]$Specification.name;specification=$Specification;process=$process
    root_process_id=[int]$process.Id;started_at=$started
    tracked_process_ids=@([int]$process.Id);active=$true;completed=$false
    exit_code=$null;peak_working_set_bytes=[int64]0;pressure_terminated=$false
  }
}

function Get-SystemCpuPercent {
  try{
    $average=(Get-CimInstance Win32_Processor -ErrorAction Stop|
      Measure-Object -Property LoadPercentage -Average).Average
    return [double]$average
  }catch{return [double]0}
}

function Start-ObservedFormalProcess {
  <# Start the first formal batch and observe it without terminating it. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)]$ProcessSpecification
  )
  $plan=Get-Content -LiteralPath $DispatchPlanPath -Raw -Encoding UTF8|ConvertFrom-Json
  if([string]$plan.estimation.kind-ne'formal_first_batch_observation'){
    throw 'Formal observation requires an unknown-identity repository plan.'
  }
  $seconds=[int]$plan.limits.formal_observation_seconds
  if($seconds-ne 30){throw 'Repository formal observation duration must be 30 seconds.'}
  $record=Start-RepositoryScheduledProcess -Specification $ProcessSpecification
  $previousTicks=[int64]0;$previousAt=$record.started_at
  $peakCpu=[double]0;$peakBackground=[double]0;$systemCpu=[double]0;$lastSystemAt=$null
  while($record.active-and([datetimeoffset]::UtcNow-$record.started_at).TotalSeconds-lt$seconds){
    $now=[datetimeoffset]::UtcNow
    $sample=Get-ManagedSolverProcessSample -RootProcessIds @($record.root_process_id) `
      -TrackedProcessIds $record.tracked_process_ids
    $record.tracked_process_ids=@($sample.tracked_process_ids)
    $record.active=@($sample.active_process_ids).Count-gt 0
    $record.peak_working_set_bytes=[math]::Max(
      [int64]$record.peak_working_set_bytes,[int64]$sample.working_set_bytes)
    $elapsed=($now-$previousAt).TotalSeconds
    if($previousTicks-gt 0-and$elapsed-gt 0){
      $cpu=100.0*(([int64]$sample.total_processor_time_ticks-$previousTicks)/1.0e7)/
        ($elapsed*[Environment]::ProcessorCount)
      $peakCpu=[math]::Max($peakCpu,[math]::Max(0.0,$cpu))
      if($null-eq$lastSystemAt-or($now-$lastSystemAt).TotalSeconds-ge 2){
        $systemCpu=Get-SystemCpuPercent;$lastSystemAt=$now
      }
      $peakBackground=[math]::Max($peakBackground,[math]::Max(0.0,$systemCpu-$cpu))
    }
    $previousTicks=[int64]$sample.total_processor_time_ticks;$previousAt=$now
    if(-not$record.active){break}
    Start-Sleep -Milliseconds 500
  }
  if(-not$record.active){
    $record.process.WaitForExit()
    try{
      $record.process.Refresh()
      $record.peak_working_set_bytes=[math]::Max(
        [int64]$record.peak_working_set_bytes,[int64]$record.process.PeakWorkingSet64)
    }catch{}
    $record.completed=$true;$record.exit_code=[int]$record.process.ExitCode
    $record.process.Dispose()
  }
  $record|Add-Member -NotePropertyName completed_during_observation `
    -NotePropertyValue ([bool]$record.completed) -Force
  $record|Add-Member -NotePropertyName observed_process_cpu_percent `
    -NotePropertyValue ([math]::Round($peakCpu,3)) -Force
  $record|Add-Member -NotePropertyName observed_background_cpu_percent `
    -NotePropertyValue ([math]::Round($peakBackground,3)) -Force
  return [pscustomobject]@{
    process_record=$record;completed_naturally=[bool]$record.completed;exit_code=$record.exit_code
    observed_peak_process_tree_working_set_bytes=[int64]$record.peak_working_set_bytes
    observed_process_cpu_percent=[math]::Round($peakCpu,3)
    observed_background_cpu_percent=[math]::Round($peakBackground,3)
    available_memory_bytes=[int64][MultipoleMemoryStatus]::AvailableBytes()
    total_physical_memory_bytes=[int64][MultipoleMemoryStatus]::TotalBytes()
  }
}

function Invoke-ResourceBudgetedProcesses {
  <# Execute independent formal batches under the repository dispatch policy. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$DispatchPlanPath,
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,
    [object[]]$ProcessSpecifications=@(),
    [object[]]$ExistingProcessRecords=@()
  )
  $plan=Get-Content -LiteralPath $DispatchPlanPath -Raw -Encoding UTF8|ConvertFrom-Json
  if([string]$plan.role-ne'simion_repository_dispatch_plan'){
    throw 'Parallel execution requires a repository SIMION dispatch plan.'
  }
  $limits=$plan.limits;$maximumConcurrency=[int]$limits.maximum_concurrency
  if($maximumConcurrency-lt 1){throw 'Repository maximum concurrency must be positive.'}
  if([int]$limits.launch_stagger_seconds-ne 5-or[int]$limits.memory_critical_seconds-ne 15){
    throw 'Repository launch and memory-danger policy differs from the public invariant.'
  }
  $pending=[Collections.ArrayList]::new()
  foreach($spec in $ProcessSpecifications){Assert-RepositoryProcessSpecification $spec;$null=$pending.Add($spec)}
  $running=[Collections.ArrayList]::new();$completed=[Collections.ArrayList]::new()
  foreach($record in $ExistingProcessRecords){
    if($record.completed){$null=$completed.Add($record)}else{$null=$running.Add($record)}
  }
  if($pending.Count+$running.Count+$completed.Count-lt 1){throw 'No formal process was supplied.'}
  $started=[datetimeoffset]::UtcNow;$nextLaunch=$started
  $warningBytes=[int64]$limits.memory_admission_reserve_bytes
  $criticalBytes=[int64]$limits.memory_critical_reserve_bytes
  if($warningBytes-ne 2GB-or$criticalBytes-ne 1GB){
    throw 'Repository memory reserves must be 2 GiB admission and 1 GiB critical.'
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
  $criticalSince=$null;$lastCpuAt=$null;$systemCpu=[double]0
  $peakAggregate=[int64]0;$minimumAvailable=$null;$peakConcurrency=$running.Count
  $pauseEvents=[Collections.ArrayList]::new();$terminationEvents=[Collections.ArrayList]::new()
  $requeueCounts=@{};$unschedulable=$false
  while($pending.Count-gt 0-or$running.Count-gt 0){
    $now=[datetimeoffset]::UtcNow;$nextRunning=[Collections.ArrayList]::new();$aggregate=[int64]0
    foreach($record in @($running)){
      $sample=Get-ManagedSolverProcessSample -RootProcessIds @($record.root_process_id) `
        -TrackedProcessIds $record.tracked_process_ids
      $record.tracked_process_ids=@($sample.tracked_process_ids)
      $record.active=@($sample.active_process_ids).Count-gt 0
      $record.peak_working_set_bytes=[math]::Max(
        [int64]$record.peak_working_set_bytes,[int64]$sample.working_set_bytes)
      $aggregate+=[int64]$sample.working_set_bytes
      if($record.active){$null=$nextRunning.Add($record);continue}
      $record.process.WaitForExit()
      $record.completed=$true
      $record.exit_code=$(if($record.pressure_terminated){$null}else{[int]$record.process.ExitCode})
      $record.process.Dispose()
      if(-not$record.pressure_terminated){$null=$completed.Add($record)}
    }
    $running=$nextRunning;$peakAggregate=[math]::Max($peakAggregate,$aggregate)
    $available=[int64][MultipoleMemoryStatus]::AvailableBytes()
    $minimumAvailable=$(if($null-eq$minimumAvailable){$available}else{[math]::Min([int64]$minimumAvailable,$available)})
    if($null-eq$lastCpuAt-or($now-$lastCpuAt).TotalSeconds-ge 2){$systemCpu=Get-SystemCpuPercent;$lastCpuAt=$now}
    if($available-lt$criticalBytes){if($null-eq$criticalSince){$criticalSince=$now}}else{$criticalSince=$null}
    if($null-ne$criticalSince-and($now-$criticalSince).TotalSeconds-ge 15-and$running.Count-gt 0){
      $victim=@($running|Sort-Object started_at -Descending)[0];$name=[string]$victim.name
      $count=$(if($requeueCounts.ContainsKey($name)){[int]$requeueCounts[$name]}else{0})
      if($maximumConcurrency-eq 1-and$count-ge 1){$unschedulable=$true;break}
      Stop-ManagedSolverProcesses -ProcessIds @($victim.tracked_process_ids)
      $victim.pressure_terminated=$true;$requeueCounts[$name]=$count+1
      $null=$pending.Add($victim.specification)
      $maximumConcurrency=[math]::Max(1,$maximumConcurrency-1)
      $null=$terminationEvents.Add([ordered]@{
        process=$name;at_utc=$now.ToString('o')
        reason='available_memory_below_1_gib_for_15_seconds'
        requeued=$true;new_maximum_concurrency=$maximumConcurrency
      })
      $criticalSince=$null;$nextLaunch=$now.AddSeconds(5);Start-Sleep -Seconds 5;continue
    }
    # A dispatch plan limits lanes from the first formal peak.  Before every
    # later launch, also reserve one expected process footprint based on the
    # highest live peak seen so far.  This tightens admission immediately if
    # SIMION grows after the 30-second observation, without a project-local
    # RAM setting or an unnecessary calibration run.
    $livePeak=[int64]0
    foreach($record in @($running)){
      $livePeak=[math]::Max($livePeak,[int64]$record.peak_working_set_bytes)
    }
    $dynamicAdmissionBytes=[int64][math]::Max(
      $plannedMemoryBudget,[math]::Ceiling($livePeak*$memorySafetyFactor))
    $canLaunch=$pending.Count-gt 0-and$running.Count-lt$maximumConcurrency-and
      $now-ge$nextLaunch-and$available-ge($warningBytes+$dynamicAdmissionBytes)-and
      $systemCpu-lt[double]$limits.cpu_admission_percent
    if($canLaunch){
      $spec=$pending[0];$pending.RemoveAt(0)
      $null=$running.Add((Start-RepositoryScheduledProcess -Specification $spec))
      $peakConcurrency=[math]::Max($peakConcurrency,$running.Count)
      $nextLaunch=[datetimeoffset]::UtcNow.AddSeconds(5)
    }elseif($pending.Count-gt 0-and($available-lt$warningBytes-or$systemCpu-ge[double]$limits.cpu_admission_percent)){
      if($pauseEvents.Count-eq 0-or($now-[datetimeoffset]$pauseEvents[$pauseEvents.Count-1].at_utc).TotalSeconds-ge 5){
        $null=$pauseEvents.Add([ordered]@{at_utc=$now.ToString('o');available_memory_bytes=$available;system_cpu_percent=$systemCpu})
      }
    }
    if($pending.Count-gt 0-or$running.Count-gt 0){Start-Sleep -Milliseconds 500}
  }
  if($unschedulable){foreach($record in @($running)){Stop-ManagedSolverProcesses -ProcessIds @($record.tracked_process_ids)}}
  $failed=@($completed|Where-Object{$null-ne$_.exit_code-and[int]$_.exit_code-ne 0})
  $usage=[ordered]@{
    schema_version=2;role='multipole_resource_usage'
    status=$(if($unschedulable){'resource_pressure_failed'}elseif($failed.Count-gt 0){'process_failed'}else{'running'})
    failure_class=$(if($unschedulable){'sustained_critical_memory_at_single_concurrency'}else{$null})
    limit_name=$(if($unschedulable){'system_available_memory'}else{$null})
    started_at_utc=$started.ToString('o');wall_clock_seconds=[math]::Round(([datetimeoffset]::UtcNow-$started).TotalSeconds,3)
    peak_process_tree_working_set_bytes=$peakAggregate;minimum_system_available_memory_bytes=$minimumAvailable
    peak_run_directory_bytes=(Get-RunDirectoryBytes -RunDir $RunDir);final_retained_bytes=$null;limits=$plan.limits
    final_retained_measurement_scope='run_directory_before_terminal_manifest'
    execution_wave=[ordered]@{dispatch='repository_adaptive_staggered';process_count=$completed.Count;peak_concurrency=$peakConcurrency}
    scheduler_receipt=[ordered]@{
      resource_identity_source=[string]$plan.estimation.kind
      planned_maximum_concurrency=[int]$plan.limits.maximum_concurrency
      final_maximum_concurrency=$maximumConcurrency;peak_concurrency=$peakConcurrency
      minimum_available_memory_bytes=$minimumAvailable
      dynamic_admission_bytes_at_finish=$dynamicAdmissionBytes
      launch_pause_events=@($pauseEvents);termination_requeue_events=@($terminationEvents)
    }
  }
  if($ExistingProcessRecords.Count-gt 0){
    $first=$ExistingProcessRecords[0]
    $usage.first_formal_observation=[ordered]@{
      process=[string]$first.name;peak_working_set_bytes=[int64]$first.peak_working_set_bytes
      completed_naturally=[bool]$first.completed_during_observation
      process_cpu_percent=[double]$first.observed_process_cpu_percent
      background_cpu_percent=[double]$first.observed_background_cpu_percent
    }
  }
  Write-ResourceUsage -Usage $usage -Path $UsagePath
  return [pscustomobject]@{
    resource_budget_exceeded=$unschedulable;limit_name=$usage.limit_name
    processes=@($completed|ForEach-Object{[pscustomobject]@{name=$_.name;exit_code=$_.exit_code}})
  }
}

function Complete-ResourceUsage {
  [CmdletBinding()]
  param(
    [string]$ResolvedBudgetPath,
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
