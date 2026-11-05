Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

if (-not (Get-Command Assert-HostResourceHeavyStage -ErrorAction SilentlyContinue) -or
    -not (Get-Command Test-HostResourceConsoleProcess -ErrorAction SilentlyContinue)) {
  throw 'Load the installed host resource with an explicit execution context first.'
}

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

function Get-RepositoryProcessSnapshot {
  <# Share whole-host enumeration within one scheduler poll, never across polls.
     Process scalar properties are still read by each family sampler. #>
  [CmdletBinding()]
  param([object[]]$Processes)
  if(-not $PSBoundParameters.ContainsKey('Processes')){
    $Processes=@(Get-Process -ErrorAction SilentlyContinue)
  }
  $cimProcesses=@()
  $parentSnapshot=$null
  try{$cimProcesses=@(Get-CimInstance Win32_Process -ErrorAction Stop)}catch{
    $parentSnapshot=Get-HostResourceProcessParents
  }
  return [pscustomobject]@{
    processes=$Processes
    cim_processes=$cimProcesses
    parent_snapshot=$parentSnapshot
  }
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
    [hashtable]$TrackedProcessStartedAtUtcTicks=@{},
    [psobject]$ProcessSnapshot
  )
  $processes=if($null-ne$ProcessSnapshot){@($ProcessSnapshot.processes)}else{@(Get-Process -ErrorAction SilentlyContinue)}
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
  $unknownAncestryProcessIds=[Collections.Generic.HashSet[int]]::new()
  $observedStartTicks=@{}
  $readStarted={
    param([int]$Identity)
    $key=[string]$Identity
    if($observedStartTicks.ContainsKey($key)){return $observedStartTicks[$key]}
    $ticks=$null
    if($byId.ContainsKey($Identity)){
      try{$ticks=$byId[$Identity].StartTime.ToUniversalTime().Ticks}catch{
        $ticks=Get-HostResourceNativeProcessCreationTicks -ProcessId $Identity
      }
    }
    $observedStartTicks[$key]=$ticks
    return $ticks
  }
  foreach($key in $expectedStartTicks.Keys){
    $processId=[int]$key
    if($byId.ContainsKey($processId)){
      $actualStarted=& $readStarted $processId
      if($null-eq$actualStarted){$null=$unknownAncestryProcessIds.Add($processId)}
      if($null-eq$actualStarted-or[int64]$actualStarted-ne[int64]$expectedStartTicks[$key]){
        $null=$staleProcessIds.Add($processId)
      }
    }
  }
  $known=[Collections.Generic.HashSet[int]]::new()
  foreach($processId in @($RootProcessIds)+@($TrackedProcessIds)){
    if($processId -gt 0 -and -not $staleProcessIds.Contains([int]$processId)){
      $null=$known.Add([int]$processId)
    }
  }
  $parentByChild=@{}
  $ancestryComplete=$true
  $systemConsoleHostProcessIds=[Collections.Generic.HashSet[int]]::new()
  # Get-Process.Parent fails once a short-lived launcher has exited, even
  # while its solver child is still active.  Win32_Process retains the child
  # record's ParentProcessId, so use it first to keep that child in this
  # launch family rather than prematurely declaring the formal batch done.
  # Standalone calls keep Get-Process -> birth checks -> parent enumeration.
  if($null-eq$ProcessSnapshot){$ProcessSnapshot=Get-RepositoryProcessSnapshot -Processes $processes}
  if($null-eq$ProcessSnapshot.parent_snapshot){
    foreach($process in $ProcessSnapshot.cim_processes){
      $parentByChild[[int]$process.ProcessId]=[int]$process.ParentProcessId
      if($process.PSObject.Properties.Name -contains 'ExecutablePath' -and
          (Test-HostResourceConsoleProcess -ImagePath ([string]$process.ExecutablePath))){
        $null=$systemConsoleHostProcessIds.Add([int]$process.ProcessId)
      }
    }
  }else{
    $parentSnapshot=$ProcessSnapshot.parent_snapshot
    $ancestryComplete=[bool]$parentSnapshot.complete
    # Unknown identity matters only along a possible owned ancestry chain.
    # Keep descendants behind an unresolved intermediate node as candidates;
    # unrelated protected Windows processes do not describe this solver tree.
    $candidates=[Collections.Generic.HashSet[int]]::new()
    foreach($processId in @($known)+@($unknownAncestryProcessIds)){$null=$candidates.Add($processId)}
    $changed=$true
    while($changed){
      $changed=$false
      foreach($childId in $parentSnapshot.parents.Keys){
        if($candidates.Contains($parentSnapshot.parents[$childId])-and$candidates.Add($childId)){$changed=$true}
      }
    }
    foreach($process in $processes){
      if(-not$candidates.Contains([int]$process.Id)){continue}
      $started=$null
      try{$started=$process.StartTime.ToUniversalTime().Ticks.ToString('D19')}catch{
        $started=Get-HostResourceNativeProcessCreationTicks -ProcessId ([int]$process.Id)
      }
      if($null-eq$started){
        $null=$unknownAncestryProcessIds.Add([int]$process.Id)
        # Retain the possible live family while identity is unresolved. The
        # existing unknown-scope/drain contract must not drop these writers.
        $parentByChild[[int]$process.Id]=[int]$parentSnapshot.parents[[int]$process.Id]
        continue
      }
      $parent=Get-HostResourceSnapshotParent -Parents $parentSnapshot.parents `
        -ProcessId ([int]$process.Id) -Started $started `
        -SnapshotStartedUtcTicks $parentSnapshot.started_at_utc_ticks
      if($null-ne$parent){$parentByChild[[int]$process.Id]=[int]$parent}
      else{
        $null=$unknownAncestryProcessIds.Add([int]$process.Id)
        $parentByChild[[int]$process.Id]=[int]$parentSnapshot.parents[[int]$process.Id]
      }
    }
  }
  $changed=$true
  while($changed){
    $changed=$false
    foreach($childId in @($parentByChild.Keys)){
      $parentId=[int]$parentByChild[$childId]
      if(-not$known.Contains($parentId)-or$known.Contains([int]$childId)){continue}
      $parentKey=[string]$parentId
      $parentBorn=if($expectedStartTicks.ContainsKey($parentKey)){$expectedStartTicks[$parentKey]}else{& $readStarted $parentId}
      $childBorn=& $readStarted ([int]$childId)
      # A retained PPID number is not proof of ancestry: a child cannot
      # predate the known parent identity, even after that parent has exited.
      if($null-ne$parentBorn-and$null-ne$childBorn-and[int64]$childBorn-lt[int64]$parentBorn){continue}
      if($null-eq$parentBorn-or$null-eq$childBorn){$null=$unknownAncestryProcessIds.Add([int]$childId)}
      if($null-ne$childBorn){$expectedStartTicks[[string]$childId]=[int64]$childBorn}
      if($known.Add([int]$childId)){$changed=$true}
    }
  }
  $active=@()
  $bytes=[int64]0
  $privateBytes=[int64]0
  $managedBytes=[int64]0
  $cpuTicks=[int64]0
  $cpuTicksByProcessId=@{}
  $trackedStartTicks=@{}
  # Retain known births with historical tracked IDs across empty polls. A PID
  # reused later must not become an unbound member of the original family.
  foreach($key in $expectedStartTicks.Keys){$trackedStartTicks[$key]=$expectedStartTicks[$key]}
  $activeSystemConsoleHostProcessIds=@()
  foreach($processId in $known){
    if($byId.ContainsKey([int]$processId)){
      $process=$byId[[int]$processId]
      $active+=[int]$processId
      # CIM may omit ExecutablePath; compensate only for this owned live row.
      # Keep the exact system-image classifier and the existing failure handling.
      try{
        if(Test-HostResourceConsoleProcess -ImagePath ([string]$process.Path)){
          $null=$systemConsoleHostProcessIds.Add([int]$processId)
        }
      }catch{}
      if($systemConsoleHostProcessIds.Contains([int]$processId)){
        $activeSystemConsoleHostProcessIds+=[int]$processId
      }
      $started=& $readStarted ([int]$processId)
      if($null-eq$started){$null=$unknownAncestryProcessIds.Add([int]$processId)}
      else{$trackedStartTicks[[string]$processId]=[int64]$started}
      $workingSet=[int64]$process.WorkingSet64
      # Windows may trim a SIMION process's resident working set while its
      # private committed allocation remains large.  For admission, taking the
      # larger value avoids treating a temporarily paged-out 10 GiB solver as a
      # 500 MiB solver and launching an unsafe additional worker.
      $private=[int64]$process.PrivateMemorySize64
      $bytes+=$workingSet
      $privateBytes+=$private
      $managedBytes+=[math]::Max($workingSet,$private)
      try{
        $processCpuTicks=[int64]$process.TotalProcessorTime.Ticks
        $cpuTicks+=$processCpuTicks
        $cpuTicksByProcessId[[string]$processId]=$processCpuTicks
      }catch{}
    }
  }
  return [pscustomobject]@{
    ancestry_complete=($ancestryComplete-and$unknownAncestryProcessIds.Count-eq0)
    process_parent_ids=$parentByChild
    unknown_ancestry_process_ids=@($unknownAncestryProcessIds|Sort-Object)
    tracked_process_ids=@($known|Sort-Object)
    tracked_process_started_at_utc_ticks=$trackedStartTicks
    active_process_ids=@($active|Sort-Object)
    system_console_host_process_ids=@($activeSystemConsoleHostProcessIds|Sort-Object)
    working_set_bytes=$bytes
    private_bytes=$privateBytes
    managed_memory_bytes=$managedBytes
    total_processor_time_ticks=$cpuTicks
    processor_time_ticks_by_process_id=$cpuTicksByProcessId
  }
}

function Test-ManagedProcessLaunchAncestry {
  <# Prove only the selected READY worker's chain; unrelated unknown branches
     remain unknown in the full family observation used by other consumers. #>
  param([Parameter(Mandatory)]$Sample,[Parameter(Mandatory)][int]$RootProcessId,
    [Parameter(Mandatory)][long]$RootStartedAtUtcTicks,[Parameter(Mandatory)][int]$ProcessId,
    [Parameter(Mandatory)][long]$StartedAtUtcTicks)
  $births=$Sample.tracked_process_started_at_utc_ticks
  if($Sample.active_process_ids-notcontains$ProcessId-or-not$births.ContainsKey([string]$ProcessId)-or
     [long]$births[[string]$ProcessId]-ne$StartedAtUtcTicks){return $false}
  if($null-eq$Sample.PSObject.Properties['process_parent_ids']){return $false}
  $visited=[Collections.Generic.HashSet[int]]::new()
  $current=$ProcessId
  while($true){
    if(-not$visited.Add($current)-or-not$births.ContainsKey([string]$current)){return $false}
    if($current-eq$RootProcessId){return [long]$births[[string]$current]-eq$RootStartedAtUtcTicks}
    if(-not$Sample.process_parent_ids.ContainsKey($current)){return $false}
    $parent=[int]$Sample.process_parent_ids[$current]
    if(-not$births.ContainsKey([string]$parent)-or
       [long]$births[[string]$parent]-gt[long]$births[[string]$current]){return $false}
    $current=$parent
  }
}

function Invoke-RepositoryManagedPythonProcess {
  <# Controlled Python workers identify their actual process before any work.
     Waiting that handle and draining both pipes also covers output written
     after a completion file. No grant, deadline, kill or tree-wide claim. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string[]]$ArgumentList,
    [Parameter(Mandatory)][string]$WorkingDirectory,[Parameter(Mandatory)][string]$StandardOutputPath,
    [Parameter(Mandatory)][string]$StandardErrorPath,[hashtable]$Environment=@{})
  $nonce=[guid]::NewGuid().ToString('N')
  $start=[Diagnostics.ProcessStartInfo]::new()
  $start.FileName=$Python;$start.WorkingDirectory=$WorkingDirectory;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
  $start.StandardInputEncoding=[Text.UTF8Encoding]::new($false);$start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
  foreach($argument in $ArgumentList){$start.ArgumentList.Add($argument)}
  foreach($key in $Environment.Keys){$start.Environment[$key]=[string]$Environment[$key]}
  $start.Environment['MASS_SPECTROMETRY_MANAGED_PROCESS_NONCE']=$nonce
  $start.Environment['PYTHONIOENCODING']='utf-8'
  $launcher=$null;$worker=$null;$outStream=$null;$errStream=$null;$outTask=$null;$errTask=$null;$failure=$null
  $readyBuffer=[IO.MemoryStream]::new();$readyAccepted=$false
  $receipt=[ordered]@{schema_version=1;role='repository_managed_python_completion';nonce=$nonce;
    launcher_process_id=$null;worker_process_id=$null;worker_started_at_utc_ticks=$null;
    ownership_confirmed=$false;worker_exit_confirmed=$false;launcher_exit_confirmed=$false;
    exit_code=$null;stdout_drained=$false;stderr_drained=$false;ack_attempted=$false}
  try{
    $outStream=[IO.File]::Open($StandardOutputPath,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $errStream=[IO.File]::Open($StandardErrorPath,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $launcher=[Diagnostics.Process]::Start($start);$receipt.launcher_process_id=[int]$launcher.Id
    $launcherBirth=[int64]$launcher.StartTime.ToUniversalTime().Ticks
    $errTask=$launcher.StandardError.BaseStream.CopyToAsync($errStream)
    # Read only the bounded ASCII JSON frame, then stream raw remaining bytes
    # directly to disk. StreamReader read-ahead would hide buffered log bytes.
    while($true){
      $next=$launcher.StandardOutput.BaseStream.ReadByte()
      if($next-lt0){throw 'Managed worker exited before READY.'}
      $readyBuffer.WriteByte([byte]$next)
      if($readyBuffer.Length-gt1024){throw 'Managed READY frame exceeds its bounded identity format.'}
      if($next-eq10){break}
    }
    $line=[Text.Encoding]::UTF8.GetString($readyBuffer.ToArray())
    $ready=$line|ConvertFrom-Json -AsHashtable
    if($ready-isnot[Collections.IDictionary]){throw 'Managed READY must be an object.'}
    $readyFields=($ready.Keys|Sort-Object)-join','
    if($readyFields-cne'nonce,pid,role,schema_version,started'-or
       $ready.schema_version-ne1-or$ready.role-cne'repository_managed_process_ready'-or$ready.nonce-cne$nonce-or
       ($ready.schema_version-isnot[long]-and$ready.schema_version-isnot[int])-or
       ($ready.pid-isnot[long]-and$ready.pid-isnot[int])-or[int]$ready.pid-le0-or
       $ready.started-isnot[string]-or$ready.started-notmatch'^[0-9]{19}$'){
      throw 'Managed worker did not provide this launch identity as its first output.'
    }
    $readyAccepted=$true;$outTask=$launcher.StandardOutput.BaseStream.CopyToAsync($outStream)
    $sample=Get-ManagedSolverProcessSample -RootProcessIds @([int]$launcher.Id) `
      -RootProcessStartedAtUtcTicks @{([string]$launcher.Id)=$launcherBirth}
    $workerId=[int]$ready.pid;$workerBirth=[int64]$ready.started
    if(-not(Test-ManagedProcessLaunchAncestry -Sample $sample -RootProcessId ([int]$launcher.Id) `
        -RootStartedAtUtcTicks $launcherBirth -ProcessId $workerId -StartedAtUtcTicks $workerBirth)){
      throw 'Managed worker ancestry or creation identity is unconfirmed; work was not acknowledged.'
    }
    $candidate=[Diagnostics.Process]::GetProcessById($workerId)
    try{
      $null=$candidate.Handle
      if([int64]$candidate.StartTime.ToUniversalTime().Ticks-ne$workerBirth){throw 'Managed worker changed before ACK.'}
      $worker=$candidate
    }finally{if($null-eq$worker){$candidate.Dispose()}}
    $receipt.worker_process_id=$workerId;$receipt.worker_started_at_utc_ticks=$workerBirth;$receipt.ownership_confirmed=$true
    $ready.role='repository_managed_process_ack'
    # A write error may occur after the worker received ACK; do not report it
    # as an unattempted start. The same owned handles are settled in finally.
    $receipt.ack_attempted=$true
    $launcher.StandardInput.WriteLine(($ready|ConvertTo-Json -Compress));$launcher.StandardInput.Close()
  }catch{
    $failure=$_
  }finally{
    # EOF also cancels an unacknowledged worker without starting its work.
    if($null-ne$launcher){try{$launcher.StandardInput.Close()}catch{
      if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['managed_stdin_close_error']=$_.Exception.Message}
    }}
    if($null-ne$launcher-and$null-eq$outTask){try{
      if(-not$readyAccepted){$prefix=$readyBuffer.ToArray();$outStream.Write($prefix,0,$prefix.Length)}
      $outTask=$launcher.StandardOutput.BaseStream.CopyToAsync($outStream)
    }catch{if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['managed_stdout_start_error']=$_.Exception.Message}}}
    foreach($entry in @(@{process=$worker;field='worker_exit_confirmed'},@{process=$launcher;field='launcher_exit_confirmed'})){
      if($null-eq$entry.process){continue}
      try{
        $entry.process.WaitForExit();$receipt[$entry.field]=$entry.process.HasExited
        if($entry.field-eq'worker_exit_confirmed'){$receipt.exit_code=[int]$entry.process.ExitCode}
      }catch{if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['managed_root_wait_error']=$_.Exception.Message}}
    }
    try{
      if($null-ne$outTask){
        $null=$outTask.GetAwaiter().GetResult();$outStream.Flush();$receipt.stdout_drained=$true
      }
    }catch{if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['managed_stdout_drain_error']=$_.Exception.Message}}
    try{if($null-ne$errTask){$null=$errTask.GetAwaiter().GetResult();$errStream.Flush();$receipt.stderr_drained=$true}}
    catch{if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['managed_stderr_drain_error']=$_.Exception.Message}}
    foreach($resource in @($worker,$launcher,$outStream,$errStream,$readyBuffer)){
      if($null-ne$resource){try{$resource.Dispose()}catch{
        if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['managed_close_error']=$_.Exception.Message}
      }}
    }
  }
  if($null-ne$failure){$failure.Exception.Data['managed_python_completion']=[pscustomobject]$receipt;throw $failure}
  return [pscustomobject]$receipt
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

function Test-RepositorySimionProcessSpecification {
  <# A scheduled SIMION executable is the solver itself, not a launcher.
     Once that exact root process has exited, a lingering console/helper is
     not permitted to keep the batch alive.  Other executable types retain
     descendant tracking for short-lived launcher workflows. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Specification)
  if (-not ($Specification.PSObject.Properties.Name -contains 'file_path')) {
    return $false
  }
  return [IO.Path]::GetFileName([string]$Specification.file_path).Equals(
    'simion.exe', [StringComparison]::OrdinalIgnoreCase
  )
}

function Test-RepositoryManagedProcessIsActive {
  <# Direct SIMION launches end with the exact root process identity.  Other
     executables may be launchers, so their non-console process-tree sample
     remains the completion authority.  A verified Windows system conhost is
     retained in process and memory accounting but cannot keep completed work
     alive by itself. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]$Specification,
    [Parameter(Mandatory)][int]$RootProcessId,
    [Parameter(Mandatory)][int64]$RootProcessStartedAtUtcTicks,
    [Parameter(Mandatory)]$Sample
  )
  if (Test-RepositorySimionProcessSpecification -Specification $Specification) {
    return Test-ManagedRootProcessIsLive -ProcessId $RootProcessId `
      -ExpectedStartedAtUtcTicks $RootProcessStartedAtUtcTicks
  }
  $activeProcessIds=@($Sample.active_process_ids)
  if(-not($Sample.PSObject.Properties.Name -contains 'system_console_host_process_ids')){
    # Preserve the older sample contract for live upgrades and test seams.
    return $activeProcessIds.Count -gt 0
  }
  $systemConsoleHostProcessIds=[Collections.Generic.HashSet[int]]::new()
  foreach($processId in @($Sample.system_console_host_process_ids)){
    $null=$systemConsoleHostProcessIds.Add([int]$processId)
  }
  return @($activeProcessIds|Where-Object{
    -not $systemConsoleHostProcessIds.Contains([int]$_)
  }).Count -gt 0
}

function Stop-ManagedSolverProcesses {
  param([Parameter(Mandatory)][int[]]$ProcessIds,[hashtable]$ExpectedStartedAtUtcTicks=@{})
  foreach($processId in $ProcessIds){
    if($ExpectedStartedAtUtcTicks.Count-gt0){
      $key=[string]$processId
      if(-not$ExpectedStartedAtUtcTicks.ContainsKey($key)-or
         -not(Test-ManagedRootProcessIsLive -ProcessId $processId -ExpectedStartedAtUtcTicks ([int64]$ExpectedStartedAtUtcTicks[$key]))){continue}
    }
    $process=Get-Process -Id $processId -ErrorAction SilentlyContinue
    if($null-eq$process){continue}
    try{
      & taskkill.exe /PID $processId /T /F | Out-Null
      $terminationExitCode=$LASTEXITCODE
      $process.Refresh()
      if($terminationExitCode-ne0-and-not$process.HasExited){
        throw "MANAGED_PROCESS_TERMINATION_FAILED PID=$processId EXIT_CODE=$terminationExitCode"
      }
    }finally{$process.Dispose()}
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

function New-RepositoryProcessObservation {
  param([pscustomobject]$Limits=$null,[string]$RunDir='',[string]$UsagePath='')
  $policy=Get-Content -LiteralPath $script:HostResourcePolicyPath -Raw|ConvertFrom-Json
  $observation=@{
    usage=$null;started=(Get-RepositoryUtcNow);run_dir=$RunDir;usage_path=$UsagePath
    directory_interval_seconds=30;last_directory_sample_at=$null
    critical_since=$null;critical_bytes=[int64]$policy.memory_critical_reserve_bytes
    critical_seconds=[int]$policy.memory_critical_seconds;observation_warning_sent=$false
    metrics_warning_sent=$false;physical_danger=$false
  }
  if($null-eq$Limits){return $observation}
  if($null-ne$Limits-and(-not$RunDir-or-not$UsagePath)){throw 'Budget observation requires RunDir and UsagePath.'}
  if($Limits -is [Collections.IDictionary]){$Limits=[pscustomobject]$Limits}
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
  if($UsagePath-and(Test-Path -LiteralPath $UsagePath -PathType Leaf)){
    $usage=Get-Content -LiteralPath $UsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $started=[datetimeoffset]::Parse([string]$usage.started_at_utc)
  }else{
    $started=(Get-RepositoryUtcNow)
    $usage=[ordered]@{
      schema_version=1;role='multipole_resource_usage';status='running'
      failure_class=$null;limit_name=$null;started_at_utc=$started.ToString('o')
      wall_clock_seconds=0.0;peak_process_tree_working_set_bytes=[int64]0
      minimum_system_available_memory_bytes=$null;warning_names=@();peak_run_directory_bytes=[int64]0
      final_retained_bytes=$null;limits=$limits
      final_retained_measurement_scope='run_directory_before_terminal_manifest'
    }
  }
  $observation.usage=$usage;$observation.started=$started
  $observation.directory_interval_seconds=$directorySampleIntervalSeconds
  return $observation
}

function Update-RepositoryProcessObservation {
  param([Parameter(Mandatory)][hashtable]$Observation,[Parameter(Mandatory)]$Sample,[switch]$Final)
  $now=Get-RepositoryUtcNow
  $scopeKnown=-not($Sample.PSObject.Properties.Name-contains'ancestry_complete')-or[bool]$Sample.ancestry_complete
  $availableBytes=$null
  try{$availableBytes=Get-RepositoryAvailableMemoryBytes}catch{$scopeKnown=$false}
  if(-not$scopeKnown-and-not$Observation.observation_warning_sent){
    Write-Warning 'RESOURCE_OBSERVATION_WARNING=owned_scope_unknown' -WarningAction Continue
    $Observation.observation_warning_sent=$true
  }
  if($scopeKnown-and$null-ne$availableBytes-and$availableBytes-lt$Observation.critical_bytes){
    if($null-eq$Observation.critical_since){$Observation.critical_since=$now}
  }else{$Observation.critical_since=$null}
  $danger=$null-ne$Observation.critical_since-and($now-$Observation.critical_since).TotalSeconds-ge$Observation.critical_seconds
  $Observation.physical_danger=$danger
  $usage=$Observation.usage
  if($null-ne$usage){
    if($danger){$usage.status='physical_danger';$usage.failure_class='sustained_physical_memory_danger';$usage.limit_name='system_available_memory'}
    try{
    $limits=$usage.limits
    $usage.wall_clock_seconds=[math]::Round(($now-$Observation.started).TotalSeconds,3)
    $usage.observation_status=$(if($scopeKnown){'known'}else{'unknown'})
    $treeBytes=[int64]$Sample.working_set_bytes
    $usage.peak_process_tree_working_set_bytes=[math]::Max([int64]$usage.peak_process_tree_working_set_bytes,$treeBytes)
    $measurements=[ordered]@{wall_clock_seconds=$usage.wall_clock_seconds;process_tree_working_set_bytes=$treeBytes}
    if($null-ne$availableBytes){
      $usage.minimum_system_available_memory_bytes=$(if($null-eq$usage.minimum_system_available_memory_bytes){$availableBytes}else{[math]::Min([int64]$usage.minimum_system_available_memory_bytes,$availableBytes)})
      $measurements.minimum_system_available_memory_bytes=$availableBytes
    }
    if($Final-or$null-eq$Observation.last_directory_sample_at-or($now-$Observation.last_directory_sample_at).TotalSeconds-ge$Observation.directory_interval_seconds){
      $directoryBytes=Get-RunDirectoryBytes -RunDir $Observation.run_dir
      $Observation.last_directory_sample_at=$now
      $usage.peak_run_directory_bytes=[math]::Max([int64]$usage.peak_run_directory_bytes,$directoryBytes)
      $measurements.transient_run_directory_bytes=$directoryBytes
    }
    foreach($name in $measurements.Keys){
      $exceeded=$(if($name-eq'minimum_system_available_memory_bytes'){$measurements[$name]-lt$limits.$name}else{$measurements[$name]-gt$limits.$name})
      if($exceeded-and@($usage.warning_names)-notcontains$name){
        $usage.warning_names=@($usage.warning_names)+$name
        Write-Warning "RESOURCE_BUDGET_WARNING=$name MEASURED=$($measurements[$name]) LIMIT=$($limits.$name)" -WarningAction Continue
      }
    }
    Write-ResourceUsage -Usage $usage -Path $Observation.usage_path
    }catch{
      if(-not$Observation.metrics_warning_sent){
        Write-Warning "RESOURCE_OBSERVATION_WARNING=metrics_failed ERROR=$($_.Exception.Message)" -WarningAction Continue
        $Observation.metrics_warning_sent=$true
      }
    }
  }
  return [pscustomobject]@{physical_danger=$danger;observation_known=$scopeKnown}
}

function Write-RepositoryLastProcessObservation {
  <# Persist already computed facts only; no sampling, readiness or exit inference. #>
  param([hashtable]$Observation,$Sample=$null,$SampledAt=$null,
    [string]$Phase,[string]$Reason,[AllowNull()]$ManagedActive=$null,
    [bool]$RootExitConfirmed=$false,[switch]$DeferWrite,[switch]$Force)
  if($null-eq$Observation){return}
  $target=$Observation.usage
  if($null-eq$target-and$Observation.ContainsKey('start_receipt')){$target=$Observation.start_receipt}
  if($null-eq$target){return}
  try{
    if($null-ne$Sample){
      $facts=[ordered]@{}
      foreach($name in @('active_process_ids','tracked_process_ids','tracked_process_started_at_utc_ticks',
          'unknown_ancestry_process_ids','ancestry_complete','system_console_host_process_ids','process_parent_ids')){
        $property=$Sample.PSObject.Properties[$name]
        if($null-eq$property){$facts[$name]=$null}
        elseif($name-eq'process_parent_ids'){
          # The existing CIM sample may contain unrelated machine-wide edges.
          # Persist only direct edges for the already observed owned candidates.
          $ownedIds=@()
          foreach($idsName in @('active_process_ids','tracked_process_ids','unknown_ancestry_process_ids')){
            $idsProperty=$Sample.PSObject.Properties[$idsName]
            if($null-ne$idsProperty){$ownedIds+=@($idsProperty.Value)}
          }
          $copy=[ordered]@{}
          foreach($childId in @($ownedIds|Sort-Object -Unique)){
            $key=$(if($property.Value.Contains([int]$childId)){[int]$childId}else{[string]$childId})
            if($property.Value.Contains($key)){$copy[[string]$childId]=$property.Value[$key]}
          }
          $facts[$name]=$copy
        }elseif($name-eq'tracked_process_started_at_utc_ticks'){
          $copy=[ordered]@{};foreach($key in @($property.Value.Keys|Sort-Object)){$copy[[string]$key]=$property.Value[$key]}
          $facts[$name]=$copy
        }elseif($name-eq'ancestry_complete'){$facts[$name]=$property.Value}
        else{$facts[$name]=@($property.Value)}
      }
      $Observation.last_process_sample=$facts
      $Observation.last_process_sampled_at_utc=$SampledAt.ToString('o')
    }
    if($null-ne$ManagedActive){
      $Observation.last_managed_active_decision=@{active=$ManagedActive;
        branch=$(if($Observation.ContainsKey('process_decision_branch')){$Observation.process_decision_branch}else{$null});
        sampled_at_utc=$(if($Observation.ContainsKey('last_process_sampled_at_utc')){$Observation.last_process_sampled_at_utc}else{$null})}
    }
    $recordedAt=Get-RepositoryUtcNow
    $target.last_process_observation=[ordered]@{
      sample=$(if($Observation.ContainsKey('last_process_sample')){$Observation.last_process_sample}else{$null})
      sampled_at_utc=$(if($Observation.ContainsKey('last_process_sampled_at_utc')){$Observation.last_process_sampled_at_utc}else{$null})
      recorded_at_utc=$recordedAt.ToString('o')
      root_process_id=$Observation.root_process_id
      root_process_started_at_utc_ticks=$Observation.root_process_started_at_utc_ticks
      root_exit_confirmed=$RootExitConfirmed;managed_active=$ManagedActive
      last_managed_active_decision=$(if($Observation.ContainsKey('last_managed_active_decision')){$Observation.last_managed_active_decision}else{$null})
      wait_phase=$Phase;wait_reason=$Reason
    }
    $signature=[ordered]@{sample=$target.last_process_observation.sample;
      root_exit_confirmed=$RootExitConfirmed;managed_active=$ManagedActive;phase=$Phase;reason=$Reason}|ConvertTo-Json -Depth 12 -Compress
    $changed=-not$Observation.ContainsKey('last_fact_write_signature')-or$signature-cne$Observation.last_fact_write_signature
    $due=-not$Observation.ContainsKey('last_fact_write_at')-or($recordedAt-$Observation.last_fact_write_at).TotalSeconds-ge30
    if(-not$DeferWrite-and($Force-or$changed-or$due)){
      $Observation.last_fact_write_signature=$signature;$Observation.last_fact_write_at=$recordedAt
      Write-ResourceUsage -Usage $target -Path $Observation.usage_path
    }
  }catch{
    # Diagnostic publication cannot replace the primary failure or release a guard.
    $Observation.last_process_observation_error=$_.Exception.Message
    Write-Warning "RESOURCE_OBSERVATION_WARNING=last_process_fact_failed ERROR=$($_.Exception.Message)" -WarningAction Continue
  }
}

function Wait-RepositoryImmutableProcessDrain {
  <# Keep the caller's guards while the same real root/known family is unresolved. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Process,[Parameter(Mandatory)][int]$RootProcessId,
    $RootProcessStartedAtUtcTicks=$null,[bool]$RootExitConfirmed=$false,$RootReturnCode=$null,
    [int[]]$TrackedProcessIds=@(),[hashtable]$TrackedProcessStartedAtUtcTicks=@{},$Failure=$null,
    [hashtable]$Observation=$null)
      # FileShare.Read guards belong to our caller. Do not unwind that caller
      # while the same launched handle or an unresolved owned family may live.
      # .NET WaitForExit waits only this associated process, not descendants.
      $lastDrainWarning=[datetime]::MinValue
      while($true){
        try{
          if(-not$rootExitConfirmed){
            Write-RepositoryLastProcessObservation -Observation $Observation -Phase immutable_drain_root_wait `
              -Reason await_original_handle_exit -RootExitConfirmed $false -Force
            $process.WaitForExit();$rootExitConfirmed=$process.HasExited
            $rootReturnCode=[int]$process.ExitCode
          }
          if($null-eq$rootProcessStartedAtUtcTicks){$rootProcessStartedAtUtcTicks=[int64]$process.StartTime.ToUniversalTime().Ticks}
          if($null-ne$Observation){$Observation.root_process_started_at_utc_ticks=$rootProcessStartedAtUtcTicks}
          $drain=Get-ManagedSolverProcessSample -RootProcessIds @([int]$RootProcessId) `
            -TrackedProcessIds $trackedProcessIds -RootProcessStartedAtUtcTicks @{
              ([string]$RootProcessId)=$rootProcessStartedAtUtcTicks
            } -TrackedProcessStartedAtUtcTicks $trackedProcessStartedAtUtcTicks
          $drainSampledAt=Get-RepositoryUtcNow
          $trackedProcessIds=@(@($trackedProcessIds)+@($drain.tracked_process_ids)|Sort-Object -Unique)
          foreach($key in $drain.tracked_process_started_at_utc_ticks.Keys){
            if(-not$trackedProcessStartedAtUtcTicks.ContainsKey($key)){$trackedProcessStartedAtUtcTicks[$key]=$drain.tracked_process_started_at_utc_ticks[$key]}
          }
          $drainComplete=$rootExitConfirmed-and$drain.ancestry_complete-and@($drain.active_process_ids).Count-eq0
          $drainReason=$(if($drainComplete){'confirmed_empty'}else{'owned_family_or_identity_unconfirmed'})
          Write-RepositoryLastProcessObservation -Observation $Observation -Sample $drain -SampledAt $drainSampledAt `
            -Phase $(if($drainComplete){'immutable_drain_confirmed_empty'}else{'immutable_drain_wait'}) `
            -Reason $drainReason -RootExitConfirmed $rootExitConfirmed
          if($drainComplete){break}
        }catch{
          $drainReason=$_.Exception.Message
          if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['immutable_input_drain_error']=$_.Exception.Message}
          Write-RepositoryLastProcessObservation -Observation $Observation -Phase immutable_drain_observation_unknown `
            -Reason $drainReason -RootExitConfirmed $rootExitConfirmed
        }
        if(([datetime]::UtcNow-$lastDrainWarning).TotalSeconds-ge30){
          Write-Warning "IMMUTABLE_INPUT_DRAIN=waiting ROOT=$($RootProcessId) REASON=$drainReason" -WarningAction Continue
          $lastDrainWarning=[datetime]::UtcNow
        }
        Start-Sleep -Milliseconds 500
      }
  return [pscustomobject]@{root_exit_confirmed=$rootExitConfirmed;root_returncode=$rootReturnCode;
    root_started_at_utc_ticks=$rootProcessStartedAtUtcTicks;tracked_process_ids=$trackedProcessIds;
    tracked_process_started_at_utc_ticks=$trackedProcessStartedAtUtcTicks;failure=$failure}
}

function Assert-RepositoryProcessObservationMetadata {
  param($Metadata,[string]$UsagePath)
  if($null-eq$Metadata){return}
  if($Metadata-isnot[Collections.IDictionary]-or(($Metadata.Keys|Sort-Object)-join',')-cne'role,run_id,stage'){
    throw 'Process observation metadata requires exactly run_id, role and stage.'
  }
  foreach($name in @('run_id','role','stage')){
    if($Metadata[$name]-isnot[string]-or[string]::IsNullOrWhiteSpace($Metadata[$name])){
      throw 'Process observation metadata values must be nonempty strings.'
    }
  }
  if([string]::IsNullOrWhiteSpace($UsagePath)-or-not[IO.Path]::IsPathFullyQualified($UsagePath)){
    throw 'Process observation metadata requires its original absolute usage path.'
  }
}

function Write-RepositoryProcessStartObservation {
  <# Facts from the original launched handle, not GUI-ready or current liveness. #>
  param([hashtable]$Observation,$Process,$RootProcessStartedAtUtcTicks,
    [string]$FilePath,[string]$WindowStyle,$Metadata)
  if($null-eq$Metadata){return}
  $rootId=[int]$Process.Id
  if($rootId-le0){throw 'Started process has no valid original process ID.'}
  $actualImage=$null;$imageStatus='unknown';$imageError=$null
  try{
    $candidate=$Process.MainModule.FileName
    if(-not[string]::IsNullOrWhiteSpace($candidate)){$actualImage=[string]$candidate;$imageStatus='known'}
  }catch{$imageError=$_.Exception.Message}
  $facts=[ordered]@{
    root_process_id=$rootId;root_process_started_at_utc_ticks=$RootProcessStartedAtUtcTicks
    identity_status=$(if($null-ne$RootProcessStartedAtUtcTicks){'known'}else{'unknown'})
    requested_executable=$FilePath;requested_window_style=$WindowStyle
    actual_image_status=$imageStatus;actual_image_path=$actualImage;actual_image_error=$imageError
    observed_at_utc=(Get-RepositoryUtcNow).ToString('o');usage_path=$Observation.usage_path
    operation=@{run_id=$Metadata.run_id;role=$Metadata.role;stage=$Metadata.stage}
  }
  # Without limits, keep the original no-budget observer unchanged. Only this
  # explicitly requested start fact is written, never invented budget metrics.
  $usage=$Observation.usage
  if($null-eq$usage){$usage=@{schema_version=1;role='execution_process_start_observation';budget_observation='not_requested'}}
  if($null-eq$Observation.usage){$Observation.start_receipt=$usage}
  $usage.process_start=$facts
  Write-ResourceUsage -Usage $usage -Path $Observation.usage_path
}

function Invoke-ResourceBudgetedProcess {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][AllowNull()][pscustomobject]$Limits,[Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$UsagePath,[Parameter(Mandatory)][string]$FilePath,
    [Parameter(Mandatory)][string[]]$ArgumentList,[string]$WorkingDirectory='',
    [string]$RedirectStandardOutput='',[string]$RedirectStandardError='',[hashtable]$Environment=@{},
    [switch]$RequireImmutableInputDrain,
    [string]$WindowStyle='Hidden',
    $ProcessObservationMetadata=$null
  )
  Assert-RepositoryProcessObservationMetadata -Metadata $ProcessObservationMetadata -UsagePath $UsagePath
  if(@('Hidden','Normal')-cnotcontains$WindowStyle){throw 'window_style requires exactly Hidden or Normal'}
  $observation=New-RepositoryProcessObservation -Limits $Limits -RunDir $RunDir -UsagePath $UsagePath
  $startArguments=@{FilePath=$FilePath;ArgumentList=$ArgumentList;PassThru=$true;WindowStyle=$WindowStyle}
  if(-not[string]::IsNullOrWhiteSpace($WorkingDirectory)){$startArguments.WorkingDirectory=$WorkingDirectory}
  if(-not[string]::IsNullOrWhiteSpace($RedirectStandardOutput)){
    $startArguments.RedirectStandardOutput=$RedirectStandardOutput
  }
  if(-not[string]::IsNullOrWhiteSpace($RedirectStandardError)){
    $startArguments.RedirectStandardError=$RedirectStandardError
  }
  if($Environment.Count-gt 0){$startArguments.Environment=$Environment}
  # Callers supply the native argument array: only explicit refine/fly verbs
  # require heavy permission. GEM conversion and construction-only Lua do not.
  $requiresHeavySimionCommand=@($ArgumentList|Where-Object{$_ -in @('refine','fly')}).Count-gt 0
  if ($requiresHeavySimionCommand -and
      (Test-RepositorySimionProcessSpecification -Specification ([pscustomobject]@{file_path=$FilePath}))) {
    Assert-HostResourceHeavyStage
  }
  $process=Start-Process @startArguments
  $failure=$null;$rootExitConfirmed=$false;$rootReturnCode=$null;$rootProcessStartedAtUtcTicks=$null
  $trackedProcessIds=@([int]$process.Id);$trackedProcessStartedAtUtcTicks=@{}
  $observation.root_process_id=[int]$process.Id;$observation.root_process_started_at_utc_ticks=$null
  try{
    try{$rootProcessStartedAtUtcTicks=[int64]$process.StartTime.ToUniversalTime().Ticks}
    catch{
      $identityFailure=$_
      try{Write-RepositoryProcessStartObservation -Observation $observation -Process $process `
        -RootProcessStartedAtUtcTicks $null -FilePath $FilePath -WindowStyle $WindowStyle -Metadata $ProcessObservationMetadata}
      catch{$identityFailure.Exception.Data['process_start_snapshot_error']=$_.Exception.Message}
      throw $identityFailure
    }
    $observation.root_process_started_at_utc_ticks=$rootProcessStartedAtUtcTicks
    Write-RepositoryProcessStartObservation -Observation $observation -Process $process `
      -RootProcessStartedAtUtcTicks $rootProcessStartedAtUtcTicks -FilePath $FilePath -WindowStyle $WindowStyle -Metadata $ProcessObservationMetadata
    $trackedProcessIds=@([int]$process.Id)
    $trackedProcessStartedAtUtcTicks=@{([string]$process.Id)=$rootProcessStartedAtUtcTicks}
    $processSpecification=[pscustomobject]@{file_path=$FilePath}
    $danger=$false;$managedActive=$true
    while($managedActive){
      $sample=Get-ManagedSolverProcessSample -RootProcessIds @([int]$process.Id) `
        -TrackedProcessIds $trackedProcessIds -RootProcessStartedAtUtcTicks @{
          ([string]$process.Id)=$rootProcessStartedAtUtcTicks
        } -TrackedProcessStartedAtUtcTicks $trackedProcessStartedAtUtcTicks
      $sampledAt=Get-RepositoryUtcNow
      $trackedProcessIds=@($sample.tracked_process_ids)
      if($sample.PSObject.Properties.Name-contains'tracked_process_started_at_utc_ticks'){$trackedProcessStartedAtUtcTicks=$sample.tracked_process_started_at_utc_ticks}
      $isSimion=Test-RepositorySimionProcessSpecification -Specification $processSpecification
      $decisionBranch=$(if($isSimion){'simion_exact_root'}else{'non_simion_family'})
      $managedActive=Test-RepositoryManagedProcessIsActive -Specification $processSpecification `
        -RootProcessId ([int]$process.Id) -RootProcessStartedAtUtcTicks $rootProcessStartedAtUtcTicks -Sample $sample
      if(-not$managedActive-and-not$isSimion){
        $decisionBranch='non_simion_root_identity_fallback'
        $managedActive=Test-ManagedRootProcessIsLive -ProcessId ([int]$process.Id) -ExpectedStartedAtUtcTicks $rootProcessStartedAtUtcTicks
      }
      $observation.process_decision_branch=$decisionBranch
      Write-RepositoryLastProcessObservation -Observation $observation -Sample $sample -SampledAt $sampledAt `
        -Phase process_observation -Reason ($decisionBranch+$(if($managedActive){'_active'}else{'_not_active'})) `
        -ManagedActive $managedActive -RootExitConfirmed $rootExitConfirmed -DeferWrite
      $observed=Update-RepositoryProcessObservation -Observation $observation -Sample $sample
      if($observed.physical_danger-and$managedActive){
        $danger=$true
        Stop-ManagedSolverProcesses -ProcessIds $trackedProcessIds -ExpectedStartedAtUtcTicks $trackedProcessStartedAtUtcTicks
        break
      }
      if($null-eq$observation.usage){
        Write-RepositoryLastProcessObservation -Observation $observation -Phase process_observation `
          -Reason ($decisionBranch+$(if($managedActive){'_active'}else{'_not_active'})) `
          -ManagedActive $managedActive -RootExitConfirmed $rootExitConfirmed
      }
      if($managedActive){Start-Sleep -Milliseconds 500}
    }
    Write-RepositoryLastProcessObservation -Observation $observation -Phase root_handle_wait `
      -Reason await_original_handle_exit -ManagedActive $managedActive -RootExitConfirmed $rootExitConfirmed -Force
    $process.WaitForExit();$rootExitConfirmed=$process.HasExited
    $rootReturnCode=[int]$process.ExitCode
    Write-RepositoryLastProcessObservation -Observation $observation -Phase root_handle_exited `
      -Reason original_handle_exit_confirmed -ManagedActive $managedActive -RootExitConfirmed $rootExitConfirmed
    $null=Update-RepositoryProcessObservation -Observation $observation -Sample $sample -Final
    $usage=$observation.usage
    if($null-ne$usage){
      if(-not$danger){$usage.status=$(if($process.ExitCode-eq0){'running'}else{'process_failed'})}
      try{Write-ResourceUsage -Usage $usage -Path $UsagePath}catch{
        Write-Warning "RESOURCE_OBSERVATION_WARNING=finalization_failed ERROR=$($_.Exception.Message)" -WarningAction Continue
      }
    }
  }catch{$failure=$_}finally{
    # Observation failure must not return the caller's input guards while this
    # directly owned root still writes. This handle does not attest descendants.
    if(-not$rootExitConfirmed){
      try{
        Write-RepositoryLastProcessObservation -Observation $observation -Phase failure_root_handle_wait `
          -Reason await_original_handle_exit_after_failure -RootExitConfirmed $rootExitConfirmed -Force
        $process.WaitForExit();$rootExitConfirmed=$process.HasExited
        $rootReturnCode=[int]$process.ExitCode
      }catch{
        if($null-eq$failure){$failure=$_}
        else{$failure.Exception.Data['observed_process_wait_error']=$_}
      }
    }
    if($RequireImmutableInputDrain){
      $drained=Wait-RepositoryImmutableProcessDrain -Process $process -RootProcessId ([int]$process.Id) `
        -RootProcessStartedAtUtcTicks $rootProcessStartedAtUtcTicks -RootExitConfirmed $rootExitConfirmed `
        -RootReturnCode $rootReturnCode -TrackedProcessIds $trackedProcessIds `
        -TrackedProcessStartedAtUtcTicks $trackedProcessStartedAtUtcTicks -Failure $failure -Observation $observation
      $rootExitConfirmed=$drained.root_exit_confirmed;$rootReturnCode=$drained.root_returncode
      $rootProcessStartedAtUtcTicks=$drained.root_started_at_utc_ticks;$failure=$drained.failure
    }
  }
  if($null-ne$failure){
    $failure.Exception.Data['observed_process_exit_confirmed']=[bool]$rootExitConfirmed
    $failure.Exception.Data['observed_process_returncode']=$rootReturnCode
    $failure.Exception.Data['observed_process_id']=[int]$process.Id
    $failure.Exception.Data['observed_process_started_at_utc_ticks']=$rootProcessStartedAtUtcTicks
    throw $failure
  }
  return [pscustomobject]@{exit_code=$process.ExitCode;resource_budget_exceeded=$danger;
    limit_name=$(if($danger){'system_available_memory'}elseif($null-ne$usage){$usage.limit_name}else{$null});
    usage_path=$(if($null-ne$usage){$UsagePath}else{$null});
    root_process_id=[int]$process.Id;root_process_started_at_utc_ticks=$rootProcessStartedAtUtcTicks}
}
