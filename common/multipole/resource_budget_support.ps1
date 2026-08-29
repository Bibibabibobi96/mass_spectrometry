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

function Get-RepositoryUtcNow {
  <# Small seam for deterministic scheduler tests; production always uses UTC. #>
  return [datetimeoffset]::UtcNow
}

function Get-RepositoryAvailableMemoryBytes {
  <# Return immediately reusable physical RAM, not a process working-set proxy. #>
  return [int64][MultipoleMemoryStatus]::AvailableBytes()
}

function Test-RepositoryDiskCapacity {
  <#
    Fail closed before a transient solver run can exhaust its target volume.
    Callers supply a post-launch free-space floor together with the frozen
    run-directory budget.  The required free space is their sum, so a solver
    cannot start at the floor and then consume its way below it.
  #>
  [OutputType([pscustomobject])]
  param(
    [Parameter(Mandatory)][string]$TargetPath,
    [Parameter(Mandatory)][int64]$TransientRunDirectoryBytes,
    [int64]$MinimumFreeBytes = [int64](10GB)
  )
  if($TransientRunDirectoryBytes -lt 0){
    throw 'Transient run-directory bytes must be non-negative.'
  }
  if($MinimumFreeBytes -lt 0){
    throw 'Minimum free bytes must be non-negative.'
  }
  if($TransientRunDirectoryBytes -gt ([int64]::MaxValue-$MinimumFreeBytes)){
    throw 'Transient run-directory bytes exceed the representable disk-capacity limit.'
  }
  $resolvedTargetPath=[IO.Path]::GetFullPath($TargetPath)
  $drive=@(Get-PSDrive -PSProvider FileSystem|Where-Object{
    $resolvedTargetPath.StartsWith([string]$_.Root,[StringComparison]::OrdinalIgnoreCase)
  }|Sort-Object {$_.Root.Length} -Descending|Select-Object -First 1)
  if($drive.Count-ne1){
    throw "Target path is not on a mounted FileSystem volume: $resolvedTargetPath"
  }
  $requiredAvailableBytes=[int64]($TransientRunDirectoryBytes+$MinimumFreeBytes)
  $freeBytes=[int64]$drive[0].Free
  $check=[pscustomobject][ordered]@{
    role='repository_disk_capacity_check'
    target_path=$resolvedTargetPath
    volume_root=[string]$drive[0].Root
    transient_run_directory_bytes=$TransientRunDirectoryBytes
    system_disk_reserve_bytes=$MinimumFreeBytes
    minimum_free_bytes=$MinimumFreeBytes
    required_available_bytes=$requiredAvailableBytes
    free_bytes=$freeBytes
    passed=($freeBytes-ge$requiredAvailableBytes)
  }
  if(-not $check.passed){throw $check}
  return $check
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
    [int[]]$TrackedProcessIds=@(),
    [hashtable]$RootProcessStartedAtUtcTicks=@{},
    [hashtable]$TrackedProcessStartedAtUtcTicks=@{}
  )
  $processes=@(Get-Process -ErrorAction SilentlyContinue)
  $byId=@{}
  foreach($process in $processes){$byId[[int]$process.Id]=$process}
  $expectedStartTicks=@{}
  foreach($rootProcessId in $RootProcessIds){
    $key=[string]$rootProcessId
    if($RootProcessStartedAtUtcTicks.ContainsKey($key)){
      $expectedStartTicks[$key]=[int64]$RootProcessStartedAtUtcTicks[$key]
    }
  }
  foreach($trackedProcessId in $TrackedProcessIds){
    $key=[string]$trackedProcessId
    if($TrackedProcessStartedAtUtcTicks.ContainsKey($key)){
      $expectedStartTicks[$key]=[int64]$TrackedProcessStartedAtUtcTicks[$key]
    }
  }
  $staleProcessIds=[Collections.Generic.HashSet[int]]::new()
  foreach($key in $expectedStartTicks.Keys){
    $processId=[int]$key
    if($byId.ContainsKey($processId)){
      try{
        if([int64]$byId[$processId].StartTime.ToUniversalTime().Ticks -ne
           [int64]$expectedStartTicks[$key]){
          $null=$staleProcessIds.Add($processId)
        }
      }catch{$null=$staleProcessIds.Add($processId)}
    }
  }
  $known=[Collections.Generic.HashSet[int]]::new()
  foreach($processId in @($RootProcessIds)+@($TrackedProcessIds)){
    if($processId -gt 0 -and -not $staleProcessIds.Contains([int]$processId)){
      $null=$known.Add([int]$processId)
    }
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
  $active=@()
  $bytes=[int64]0
  $privateBytes=[int64]0
  $managedBytes=[int64]0
  $cpuTicks=[int64]0
  $trackedStartTicks=@{}
  foreach($processId in $known){
    if($byId.ContainsKey([int]$processId)){
      $process=$byId[[int]$processId]
      $active+=[int]$processId
      try{$trackedStartTicks[[string]$processId]=[int64]$process.StartTime.ToUniversalTime().Ticks}catch{}
      $workingSet=[int64]$process.WorkingSet64
      # Windows may trim a SIMION process's resident working set while its
      # private committed allocation remains large.  For admission, taking the
      # larger value avoids treating a temporarily paged-out 10 GiB solver as a
      # 500 MiB solver and launching an unsafe additional worker.
      $private=[int64]$process.PrivateMemorySize64
      $bytes+=$workingSet
      $privateBytes+=$private
      $managedBytes+=[math]::Max($workingSet,$private)
      try{$cpuTicks+=[int64]$process.TotalProcessorTime.Ticks}catch{}
    }
  }
  return [pscustomobject]@{
    tracked_process_ids=@($known|Sort-Object)
    tracked_process_started_at_utc_ticks=$trackedStartTicks
    active_process_ids=@($active|Sort-Object)
    working_set_bytes=$bytes
    private_bytes=$privateBytes
    managed_memory_bytes=$managedBytes
    total_processor_time_ticks=$cpuTicks
  }
}

function Test-ManagedRootProcessIsLive {
  <#
    A process-tree sample is observational: a transient failure to enumerate
    the root must not authorize its caller to treat a still-running solver as
    complete.  Only the originally launched PID with its recorded start
    identity can keep the single-process watchdog alive; a reused PID cannot.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][int]$ProcessId,
    [Parameter(Mandatory)][int64]$ExpectedStartedAtUtcTicks
  )
  try {
    $process = Get-Process -Id $ProcessId -ErrorAction Stop
    return [int64]$process.StartTime.ToUniversalTime().Ticks -eq $ExpectedStartedAtUtcTicks
  } catch {
    return $false
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
  # Antivirus/indexing and a concurrent read may briefly hold the previous
  # receipt open on Windows.  A metering publication failure must not abandon
  # a still-running solver and leave its PA staging directory orphaned.
  $lastMoveError=$null
  foreach($attempt in 1..20){
    try {
      Move-Item -LiteralPath $temporary -Destination $Path -Force -ErrorAction Stop
      return
    } catch {
      $lastMoveError=$_.Exception
      Start-Sleep -Milliseconds 250
    }
  }
  throw "Could not publish resource usage after 20 attempts: $($lastMoveError.Message)"
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
  # Capacity accounting is not a safety signal.  Keep its full recursive scan
  # off the 500 ms process/memory safety loop; a missing legacy field inherits
  # the repository-wide 30 s cadence.
  $directorySampleIntervalSeconds=[double]30
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
  $rootProcessStartedAtUtcTicks=[int64]$process.StartTime.ToUniversalTime().Ticks
  $lastDirectorySampleAt=$null
  $trackedProcessIds=@([int]$process.Id)
  # Retain birth identities for descendants as well as the launcher.  A
  # completed SIMION helper PID can be reused by an unrelated long-lived
  # process before the next 500 ms poll; treating that PID as the old helper
  # would otherwise leave this metered stage waiting indefinitely.
  $trackedProcessStartedAtUtcTicks=@{
    ([string]$process.Id)=$rootProcessStartedAtUtcTicks
  }
  $managedActive=$true
  while($managedActive){
    $now=[datetimeoffset]::UtcNow
    $elapsed=($now-$started).TotalSeconds
    $sample=Get-ManagedSolverProcessSample -RootProcessIds @([int]$process.Id) `
      -TrackedProcessIds $trackedProcessIds -RootProcessStartedAtUtcTicks @{
        ([string]$process.Id)=$rootProcessStartedAtUtcTicks
      } -TrackedProcessStartedAtUtcTicks $trackedProcessStartedAtUtcTicks
    $trackedProcessIds=@($sample.tracked_process_ids)
    if($sample.PSObject.Properties.Name -contains 'tracked_process_started_at_utc_ticks'){
      $trackedProcessStartedAtUtcTicks=$sample.tracked_process_started_at_utc_ticks
    }
    $managedActive=@($sample.active_process_ids).Count -gt 0
    # Do not let a transient process-tree enumeration gap tear down a staging
    # directory while the exact root process is still refining it.  Descendant
    # tracking remains responsible after the root exits; this guard only adds
    # the verified live root as a minimum completion condition.
    if (-not $managedActive) {
      $managedActive = Test-ManagedRootProcessIsLive -ProcessId ([int]$process.Id) `
        -ExpectedStartedAtUtcTicks $rootProcessStartedAtUtcTicks
    }
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
  # A process-tree sample is advisory.  It must never let a cache publisher or
  # its catch-cleanup run while the directly launched solver is still alive.
  # This is especially important for SIMION refinement: a transient WMI/sample
  # gap would otherwise make the runner remove a staging cache that SIMION is
  # actively writing.  Waiting here retains the normal child-tree monitoring
  # above, but makes the root process's actual exit the final completion fact.
  if (-not $process.HasExited) {
    $process.WaitForExit()
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
  $started=Get-RepositoryUtcNow;$process=Start-Process @arguments
  return [pscustomobject]@{
    name=[string]$Specification.name;specification=$Specification;process=$process
    root_process_id=[int]$process.Id;root_process_started_at_utc_ticks=[int64]$process.StartTime.ToUniversalTime().Ticks;started_at=$started
    tracked_process_ids=@([int]$process.Id)
    tracked_process_started_at_utc_ticks=@{([string]$process.Id)=[int64]$process.StartTime.ToUniversalTime().Ticks}
    active=$true;completed=$false
    exit_code=$null;peak_working_set_bytes=[int64]0;peak_managed_memory_bytes=[int64]0;pressure_terminated=$false
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

function Start-ObservedFormalProcess {
  <# Start the first formal batch, retain it, and observe the fixed first window. #>
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
  if($seconds-ne 45){throw 'Repository formal observation duration must be 45 seconds.'}
  $record=Start-RepositoryScheduledProcess -Specification $ProcessSpecification
  Write-RepositorySchedulerEvent -Event 'BATCH_STARTED' -Record $record -ActiveCount 1 `
    -Details @{OBSERVATION_SECONDS=$seconds;MEASUREMENT='FIRST_FORMAL_BATCH'}
  $previousTicks=[int64]0;$previousAt=$record.started_at
  $peakCpu=[double]0;$peakBackground=[double]0;$systemCpu=[double]0;$lastSystemAt=$null
  $criticalBytes=[int64]$plan.limits.memory_critical_reserve_bytes
  $criticalSeconds=[int]$plan.limits.memory_critical_seconds
  if($criticalBytes-ne512MB-or$criticalSeconds-ne15){
    throw 'Repository first-formal memory-danger policy differs from the public invariant.'
  }
  $criticalSince=$null;$resourceBudgetExceeded=$false
  # The formal first batch remains alive after the fixed 45 s observation.  Its
  # measured peak determines the initial lane count; subsequent live admission
  # and the existing memory-danger state machine protect against later growth.
  # Waiting for natural completion here would serialize every otherwise
  # parallel run and would make the 45 s observation meaningless.
  while($record.active){
    $now=Get-RepositoryUtcNow
    $sampleArgs=@{RootProcessIds=@($record.root_process_id);TrackedProcessIds=$record.tracked_process_ids}
    if($record.PSObject.Properties.Name -contains 'root_process_started_at_utc_ticks'){
      $sampleArgs.RootProcessStartedAtUtcTicks=@{([string]$record.root_process_id)=[int64]$record.root_process_started_at_utc_ticks}
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
    $record.active=@($sample.active_process_ids).Count-gt 0
    $record.peak_working_set_bytes=[math]::Max(
      [int64]$record.peak_working_set_bytes,[int64]$sample.working_set_bytes)
    $record.peak_managed_memory_bytes=[math]::Max(
      [int64]$record.peak_managed_memory_bytes,[int64]$sample.managed_memory_bytes)
    $available=Get-RepositoryAvailableMemoryBytes
    if($available-lt$criticalBytes){
      if($null-eq$criticalSince){$criticalSince=$now}
      elseif(($now-$criticalSince).TotalSeconds-ge$criticalSeconds){
        Stop-ManagedSolverProcesses -ProcessIds @($record.tracked_process_ids)
        $record.pressure_terminated=$true;$resourceBudgetExceeded=$true
        Write-RepositorySchedulerEvent -Event 'MEMORY_DANGER_TERMINATION' -Record $record `
          -ActiveCount 1 -Details @{AVAILABLE_MEMORY_BYTES=$available;CRITICAL_SECONDS=$criticalSeconds;CRITICAL_THRESHOLD_BYTES=$criticalBytes;ACTION='STOP_ONLY_FORMAL_BATCH'}
      }
    }else{$criticalSince=$null}
    $elapsed=($now-$previousAt).TotalSeconds
    if($previousTicks-gt 0-and$elapsed-gt 0){
      $cpu=100.0*(([int64]$sample.total_processor_time_ticks-$previousTicks)/1.0e7)/
        ($elapsed*[Environment]::ProcessorCount)
      $peakCpu=[math]::Max($peakCpu,[math]::Max(0.0,$cpu))
      if($null-eq$lastSystemAt-or($now-$lastSystemAt).TotalSeconds-ge 2){
        $observedSystemCpu=Get-SystemCpuPercent
        if($null-ne$observedSystemCpu){$systemCpu=[double]$observedSystemCpu}
        $lastSystemAt=$now
      }
      $peakBackground=[math]::Max($peakBackground,[math]::Max(0.0,$systemCpu-$cpu))
    }
    $previousTicks=[int64]$sample.total_processor_time_ticks;$previousAt=$now
    if($record.pressure_terminated){
      $record.process.WaitForExit();$record.active=$false;break
    }
    if(-not$record.active){break}
    if(($now-$record.started_at).TotalSeconds-ge$seconds){
      Write-RepositorySchedulerEvent -Event 'FORMAL_OBSERVATION_COMPLETE' -Record $record -ActiveCount 1 `
        -Details @{OBSERVATION_SECONDS=$seconds;MEASUREMENT='FIRST_FORMAL_BATCH';PROCESS_CONTINUES='true'}
      break
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
    $record.process.Dispose()
  }
  $record|Add-Member -NotePropertyName completed_during_observation `
    -NotePropertyValue ([bool]$record.completed) -Force
  $record|Add-Member -NotePropertyName observed_process_cpu_percent `
    -NotePropertyValue ([math]::Round($peakCpu,3)) -Force
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
    observed_process_cpu_percent=[math]::Round($peakCpu,3)
    observed_background_cpu_percent=[math]::Round($peakBackground,3)
    available_memory_bytes=Get-RepositoryAvailableMemoryBytes
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
    [object[]]$ExistingProcessRecords=@(),
    # Optional caller-owned durable checkpoint publication.  It is invoked
    # only after a worker has exited naturally with a record available; the
    # callback must fail closed if its immutable receipt cannot be published.
    [scriptblock]$OnProcessCompleted=$null
  )
  $plan=Get-Content -LiteralPath $DispatchPlanPath -Raw -Encoding UTF8|ConvertFrom-Json
  if([string]$plan.role-ne'simion_repository_dispatch_plan'){
    throw 'Parallel execution requires a repository SIMION dispatch plan.'
  }
  $limits=$plan.limits;$maximumConcurrency=[int]$limits.maximum_concurrency
  if($maximumConcurrency-lt 1){throw 'Repository maximum concurrency must be positive.'}
  if([int]$limits.launch_stagger_seconds-ne 5-or[int]$limits.memory_critical_seconds-ne 15-or
     [int]$limits.memory_recovery_stable_seconds-ne 45-or
     [int]$limits.maximum_memory_recovery_attempts-ne 2-or
     [int]$limits.maximum_memory_danger_termination_attempts-ne 2){
    throw 'Repository launch and memory-danger policy differs from the public invariant.'
  }
  $pending=[Collections.ArrayList]::new()
  foreach($spec in $ProcessSpecifications){Assert-RepositoryProcessSpecification $spec;$null=$pending.Add($spec)}
  $running=[Collections.ArrayList]::new();$completed=[Collections.ArrayList]::new()
  foreach($record in $ExistingProcessRecords){
    if(-not($record.PSObject.Properties.Name-contains'peak_managed_memory_bytes')){
      # A first formal worker can be handed from an older in-memory runner
      # during a repository upgrade.  Preserve safe admission rather than
      # failing on the absent additive receipt field.
      $record|Add-Member -NotePropertyName peak_managed_memory_bytes `
        -NotePropertyValue ([int64]$record.peak_working_set_bytes) -Force
    }
    if($record.completed){$null=$completed.Add($record)}else{$null=$running.Add($record)}
  }
  if($null-ne$OnProcessCompleted){
    foreach($record in @($completed)){
      # Checkpoint callbacks may publish a manifest, whose helper deliberately
      # writes a receipt object to the pipeline.  The scheduler's contract is
      # a single result object, so callback output must not leak into callers
      # such as $waveResult (where it would turn the result into an array).
      $null = & $OnProcessCompleted $record
    }
  }
  if($pending.Count+$running.Count+$completed.Count-lt 1){throw 'No formal process was supplied.'}
  $started=Get-RepositoryUtcNow;$nextLaunch=$started
  $warningBytes=[int64]$limits.memory_admission_reserve_bytes
  $criticalBytes=[int64]$limits.memory_critical_reserve_bytes
  $plannedMaximumConcurrency=$maximumConcurrency
  $recoveryStableSeconds=[int]$limits.memory_recovery_stable_seconds
  $maximumRecoveryAttempts=[int]$limits.maximum_memory_recovery_attempts
  $maximumDangerTerminations=[int]$limits.maximum_memory_danger_termination_attempts
  if($warningBytes-ne 1GB-or$criticalBytes-ne 512MB){
    throw 'Repository memory reserves must be 1 GiB admission and 0.5 GiB critical.'
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
  $minimumAvailable=$null;$peakConcurrency=$running.Count
  $pauseEvents=[Collections.ArrayList]::new();$terminationEvents=[Collections.ArrayList]::new()
  $recoveryEvents=[Collections.ArrayList]::new();$requeueCounts=@{};$recoveryAttempts=0
  $batchFailureEvents=[Collections.ArrayList]::new();$batchFailureDetected=$false
  $dangerTerminationAttempts=0;$unschedulable=$false
  $resourcePauseActive=$false;$resourcePauseReason=$null
  $estimatedProcessCpu=[double]10.0
  if($limits.PSObject.Properties.Name-contains'minimum_process_cpu_percent'){
    $estimatedProcessCpu=[math]::Max($estimatedProcessCpu,[double]$limits.minimum_process_cpu_percent)
  }
  if($null-ne$estimation-and$estimation.PSObject.Properties.Name-contains'per_process_cpu_percent'){
    $estimatedProcessCpu=[math]::Max($estimatedProcessCpu,[double]$estimation.per_process_cpu_percent)
  }
  while($pending.Count-gt 0-or$running.Count-gt 0){
    $now=Get-RepositoryUtcNow;$nextRunning=[Collections.ArrayList]::new()
    $completedThisCycle=[Collections.ArrayList]::new()
    $aggregateWorkingSet=[int64]0;$aggregateManagedMemory=[int64]0
    foreach($record in @($running)){
      $sampleArgs=@{RootProcessIds=@($record.root_process_id);TrackedProcessIds=$record.tracked_process_ids}
      if($record.PSObject.Properties.Name -contains 'root_process_started_at_utc_ticks'){
        $sampleArgs.RootProcessStartedAtUtcTicks=@{([string]$record.root_process_id)=[int64]$record.root_process_started_at_utc_ticks}
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
      $record.active=@($sample.active_process_ids).Count-gt 0
      $record.peak_working_set_bytes=[math]::Max(
        [int64]$record.peak_working_set_bytes,[int64]$sample.working_set_bytes)
      $record.peak_managed_memory_bytes=[math]::Max(
        [int64]$record.peak_managed_memory_bytes,[int64]$sample.managed_memory_bytes)
      $aggregateWorkingSet+=[int64]$sample.working_set_bytes
      $aggregateManagedMemory+=[int64]$sample.managed_memory_bytes
      if($record.active){$null=$nextRunning.Add($record);continue}
      $record.process.WaitForExit()
      $record.completed=$true
      $record.exit_code=$(if($record.pressure_terminated){$null}else{[int]$record.process.ExitCode})
      $record.process.Dispose()
      if(-not$record.pressure_terminated){
        $null=$completed.Add($record)
        $null=$completedThisCycle.Add($record)
        if($null-ne$OnProcessCompleted){
          $null = & $OnProcessCompleted $record
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
      # A non-zero SIMION exit makes this wave unusable as a complete-cohort
      # result.  Do not spend hours completing siblings or start queued work;
      # stop only workers belonging to this same wave and leave their logs for
      # the parent lifecycle to publish as the causal failure record.
      foreach($record in @($running)){
        Stop-ManagedSolverProcesses -ProcessIds @($record.tracked_process_ids)
      }
      $cancelledPending=$pending.Count
      $pending.Clear()
      $null=$batchFailureEvents.Add([ordered]@{
        at_utc=$now.ToString('o');failed_batch_count=$failedThisCycle.Count
        cancelled_pending_batch_count=$cancelledPending
        stopped_active_batch_count=$running.Count
      })
      $batchFailureDetected=$true
      Write-RepositorySchedulerEvent -Event 'BATCH_FAILURE_CANCELLATION' `
        -ActiveCount $running.Count -PendingCount $cancelledPending `
        -Details @{FAILED_BATCH_COUNT=$failedThisCycle.Count;ACTION='STOP_CURRENT_WAVE'}
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
    # SIMION grows after the 45-second observation, without a project-local
    # RAM setting or an unnecessary calibration run.
    $livePeak=[int64]0
    foreach($record in @($running)){
      $livePeak=[math]::Max($livePeak,[int64]$record.peak_managed_memory_bytes)
    }
    $dynamicAdmissionBytes=[int64][math]::Max(
      $plannedMemoryBudget,[math]::Ceiling($livePeak*$memorySafetyFactor))
    # A one-lane plan has no additional worker to protect.  Its next batch may
    # start only after the retained formal batch exits, so admit it against the
    # measured single-process peak plus the repository reserve.  Keep the
    # inflated budget for every multi-lane launch and all live-growth checks.
    $launchAdmissionBytes=$dynamicAdmissionBytes
    if($running.Count-eq 0-and$maximumConcurrency-eq 1-and
       $null-ne$estimation-and[string]$estimation.kind-in@('exact_resource_profile','observed_formal_batch')-and
       $estimation.PSObject.Properties.Name-contains'observed_peak_bytes' -and
       [int64]$estimation.observed_peak_bytes -gt 0){
      $launchAdmissionBytes=[int64]$estimation.observed_peak_bytes
    }
    if($available-lt$criticalBytes){if($null-eq$criticalSince){$criticalSince=$now}}else{$criticalSince=$null}
    if($null-ne$criticalSince-and($now-$criticalSince).TotalSeconds-ge 15-and$running.Count-gt 0){
      if($dangerTerminationAttempts-ge$maximumDangerTerminations){
        # Two individual newest-worker interventions have already been
        # measured.  A third critical window means the run cannot be made safe
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
        reason='available_memory_below_0p5_gib_for_15_seconds'
        requeued=$true;requeue_priority='front';new_maximum_concurrency=$maximumConcurrency
      })
      # A requeued worker must not immediately restart after a danger kill,
      # including at one lane where reducing maximumConcurrency has no effect.
      # It receives the same 45-second stable-admission observation as a
      # restored multi-lane worker.
      $criticalSince=$null;$recoverySafeSince=$null;$dangerRecoveryPending=$true
      $nextLaunch=$now.AddSeconds(5);Start-Sleep -Seconds 5;continue
    }
    $recoveryAdmissionSafe=$available-ge($warningBytes+$dynamicAdmissionBytes)-and
      ($systemCpu+$estimatedProcessCpu-lt[double]$limits.cpu_admission_percent)
    $recoveryEligible=$dangerRecoveryPending-and$pending.Count-gt 0-and
      $recoveryAttempts-lt$maximumRecoveryAttempts
    if($recoveryEligible){
      if($recoveryAdmissionSafe){
        if($null-eq$recoverySafeSince){$recoverySafeSince=$now}
        elseif(($now-$recoverySafeSince).TotalSeconds-ge$recoveryStableSeconds){
          if($maximumConcurrency-lt$plannedMaximumConcurrency){$maximumConcurrency+=1}
          $recoveryAttempts+=1
          $null=$recoveryEvents.Add([ordered]@{
            at_utc=$now.ToString('o');attempt=$recoveryAttempts
            restored_maximum_concurrency=$maximumConcurrency
            available_memory_bytes=$available;dynamic_admission_bytes=$dynamicAdmissionBytes
            system_cpu_percent=$systemCpu
          })
          $recoverySafeSince=$null;$dangerRecoveryPending=$false;$nextLaunch=$now
          Write-RepositorySchedulerEvent -Event 'MEMORY_RECOVERY_RELAUNCH_ALLOWED' `
            -ActiveCount $running.Count -PendingCount $pending.Count `
            -Details @{ATTEMPT=$recoveryAttempts;AVAILABLE_MEMORY_BYTES=$available;DYNAMIC_ADMISSION_BYTES=$dynamicAdmissionBytes;RESTORED_MAXIMUM_CONCURRENCY=$maximumConcurrency}
        }
      }else{$recoverySafeSince=$null}
    }else{$recoverySafeSince=$null}
    $canLaunch=$pending.Count-gt 0-and$running.Count-lt$maximumConcurrency-and
      -not$dangerRecoveryPending-and$now-ge$nextLaunch-and$available-ge($warningBytes+$launchAdmissionBytes)-and
      ($systemCpu+$estimatedProcessCpu-lt[double]$limits.cpu_admission_percent)
    if($canLaunch){
      if($resourcePauseActive){
        Write-RepositorySchedulerEvent -Event 'RESOURCE_ADMISSION_RESUMED' `
          -ActiveCount $running.Count -PendingCount $pending.Count `
          -Details @{AVAILABLE_MEMORY_BYTES=$available;PREVIOUS_REASON=$resourcePauseReason;REQUIRED_AVAILABLE_MEMORY_BYTES=($warningBytes+$dynamicAdmissionBytes)}
        $resourcePauseActive=$false;$resourcePauseReason=$null
      }
      $spec=$pending[0];$pending.RemoveAt(0)
      $launched=Start-RepositoryScheduledProcess -Specification $spec
      $null=$running.Add($launched)
      $peakConcurrency=[math]::Max($peakConcurrency,$running.Count)
      Write-RepositorySchedulerEvent -Event 'BATCH_STARTED' -Record $launched `
        -ActiveCount $running.Count -PendingCount $pending.Count `
        -Details @{MAXIMUM_CONCURRENCY=$maximumConcurrency}
      $nextLaunch=(Get-RepositoryUtcNow).AddSeconds(5)
    }elseif($pending.Count-gt 0-and$running.Count-lt$maximumConcurrency){
      if($pauseEvents.Count-eq 0-or($now-[datetimeoffset]$pauseEvents[$pauseEvents.Count-1].at_utc).TotalSeconds-ge 5){
        $reason=$(if($dangerRecoveryPending){'post_danger_recovery_observation'}elseif(
          $available-lt($warningBytes+$launchAdmissionBytes)){'available_memory_below_dynamic_admission'}elseif(
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
      planned_maximum_concurrency=[int]$plan.limits.maximum_concurrency
      final_maximum_concurrency=$maximumConcurrency;peak_concurrency=$peakConcurrency
      minimum_available_memory_bytes=$minimumAvailable
      dynamic_admission_bytes_at_finish=$dynamicAdmissionBytes
      launch_pause_events=@($pauseEvents);termination_requeue_events=@($terminationEvents)
      recovery_relaunch_events=@($recoveryEvents);recovery_attempt_count=$recoveryAttempts
      danger_termination_attempt_count=$dangerTerminationAttempts
      batch_failure_cancellation_events=@($batchFailureEvents)
    }
  }
  if($ExistingProcessRecords.Count-gt 0){
    $first=$ExistingProcessRecords[0]
    $usage.first_formal_observation=[ordered]@{
      process=[string]$first.name;peak_working_set_bytes=[int64]$first.peak_working_set_bytes
      peak_managed_memory_bytes=[int64]$first.peak_managed_memory_bytes
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
