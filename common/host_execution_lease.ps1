Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:HostResourcePolicyPath = Join-Path $PSScriptRoot 'host_resource_policy.json'
# Keep one scheduler alongside the shared artifact ledger.  Desktop child
# processes may be denied both ProgramData and LocalApplicationData, whereas
# this repository's artifact root is the common writable control plane for
# every project workflow in the workspace.
$script:HostResourceStatePath = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'artifacts\common\host_resources.sqlite3'

function Get-HostResourceBudget {
  [CmdletBinding()]
  param([string]$Role = 'GATE', [string]$Stage = '', [string]$Profile = '')
  $policy = Get-Content -LiteralPath $script:HostResourcePolicyPath -Raw | ConvertFrom-Json -AsHashtable
  if (-not $Profile) {
    $key = "$Role/$Stage"
    $Profile = if ($policy.ContainsKey('stages') -and $policy.stages.ContainsKey($key)) {
      [string]$policy.stages[$key]
    } elseif ($policy.default_profiles.ContainsKey($Role)) {
      [string]$policy.default_profiles[$Role]
    } else { throw "Unknown host resource role: $Role" }
  }
  if (-not $policy.profiles.ContainsKey($Profile)) { throw "Unknown host resource profile: $Profile" }
  $budget = $policy.profiles[$Profile]
  if ($Profile -eq 'ordinary-light') {
    $budget.cpu_cores = [math]::Min([double]$budget.cpu_cores,
      [Environment]::ProcessorCount * [double]$policy.cpu_admission_percent / 100)
  }
  return $budget
}

function Test-HostResourceConsoleProcess {
  <# Only the protected Windows image is console infrastructure, not a name match. #>
  param([AllowNull()][string]$ImagePath)
  if ([string]::IsNullOrWhiteSpace($ImagePath)) { return $false }
  $consoleImage = Join-Path ([Environment]::SystemDirectory) 'conhost.exe'
  return [string]::Equals($ImagePath, $consoleImage, [StringComparison]::OrdinalIgnoreCase)
}

function Get-HostResourceIoPressure {
  <# Scope physical-disk telemetry to the volume that contains this repository.

     A queue on an unrelated, unmounted, or secondary disk must not serialize
     solver work whose inputs and outputs are on another volume.  Missing or
     unmappable target-volume telemetry still fails closed.
  #>
  param(
    [Parameter(Mandatory)][object[]]$Disks,
    [string]$TargetPath = $PSScriptRoot
  )
  $policy=Get-Content -LiteralPath $script:HostResourcePolicyPath -Raw|ConvertFrom-Json -AsHashtable
  [double]$threshold=$policy.io_pressure_queue_length_threshold
  if([double]::IsNaN($threshold)-or[double]::IsInfinity($threshold)-or$threshold-lt1){
    throw 'Host resource policy has an invalid I/O pressure queue threshold.'
  }
  if($Disks.Count-eq0){return $true}
  $root=[IO.Path]::GetPathRoot([IO.Path]::GetFullPath($TargetPath))
  if($root-match'^[A-Za-z]:\\$'){
    $volume=$root.TrimEnd([IO.Path]::DirectorySeparatorChar)
    $targetDisks=@($Disks|Where-Object{
      @(([string]$_.Name)-split'\s+') -contains $volume
    })
    if($targetDisks.Count-eq0){return $true}
  }else{$targetDisks=@($Disks)}
  return @($targetDisks|Where-Object{[double]$_.CurrentDiskQueueLength-ge$threshold}).Count-gt0
}

function Get-HostResourceNativeProcessCreationTicks {
  <# Query creation time with PROCESS_QUERY_LIMITED_INFORMATION when .NET/CIM is denied. #>
  param([Parameter(Mandatory)][int]$ProcessId)
  if ($null -eq ('MassSpectrometry.NativeProcessIdentity' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace MassSpectrometry {
  public static class NativeProcessIdentity {
    const uint PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint processId);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessTimes(IntPtr handle, out long creation, out long exit, out long kernel, out long user);
    public static bool TryGetCreationTicks(int processId, out long ticks) {
      ticks=0; IntPtr handle=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, (uint)processId);
      if (handle==IntPtr.Zero) return false;
      try { long exit, kernel, user; return GetProcessTimes(handle, out ticks, out exit, out kernel, out user); }
      finally { CloseHandle(handle); }
    }
  }
}
'@
  }
  [int64]$ticks=0
  if ([MassSpectrometry.NativeProcessIdentity]::TryGetCreationTicks($ProcessId, [ref]$ticks)) {
    return [DateTime]::FromFileTimeUtc($ticks).Ticks.ToString('D19')
  }
  return $null
}

function Get-HostResourceSnapshot {
  <# Fresh OS observations; a missing snapshot blocks admission, never releases leases. #>
  try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $cpu = @(Get-CimInstance Win32_Processor -ErrorAction Stop)
    $load = ($cpu | Measure-Object LoadPercentage -Average).Average
    $unknownProcessIds = [Collections.Generic.List[int]]::new()
    $definitelyExitedProcessIds = [Collections.Generic.List[int]]::new()
    $processes = @(foreach ($process in Get-CimInstance Win32_Process -ErrorAction Stop) {
      if ($null -eq $process.CreationDate) {
        # CIM can deny CreationDate for a live process. A native limited query
        # still identifies it without treating an unreadable PID as dead.
        $started = Get-HostResourceNativeProcessCreationTicks -ProcessId ([int]$process.ProcessId)
        if ($null -ne $started) {
          @{ pid = [int]$process.ProcessId; parent_pid = [int]$process.ParentProcessId; started = $started
             memory_bytes = [int64][Math]::Max([int64]$process.WorkingSetSize, [int64]$process.PrivatePageCount)
             is_system_console_host = Test-HostResourceConsoleProcess -ImagePath $process.ExecutablePath }
          continue
        }
        # A CIM row can outlive a short-lived process. Only an explicit native
        # no-such-process result authorizes scheduler recovery; all access or
        # metadata failures remain unknown and therefore fail closed.
        $exited = $false
        try {
          $probe = [Diagnostics.Process]::GetProcessById([int]$process.ProcessId)
          try { $exited = $probe.HasExited } finally { $probe.Dispose() }
        } catch [ArgumentException] { $exited = $true }
        catch { $exited = $false }
        if ($exited) { $definitelyExitedProcessIds.Add([int]$process.ProcessId) }
        else { $unknownProcessIds.Add([int]$process.ProcessId) }
        continue
      }
      @{
        pid = [int]$process.ProcessId
        parent_pid = [int]$process.ParentProcessId
        started = $process.CreationDate.ToUniversalTime().Ticks.ToString('D19')
        memory_bytes = [int64][Math]::Max([int64]$process.WorkingSetSize, [int64]$process.PrivatePageCount)
        is_system_console_host = Test-HostResourceConsoleProcess -ImagePath $process.ExecutablePath
      }
    })
    $totalMemoryBytes = [int64]$os.TotalVisibleMemorySize * 1KB
    $availableMemoryBytes = [int64]$os.FreePhysicalMemory * 1KB
  } catch {
    # Sandboxed child processes can be denied WMI/CIM while retaining ordinary
    # process and performance-counter access.  Use independent Win32/.NET
    # telemetry here; failure of either source still closes admission.
    Write-Verbose "CIM telemetry unavailable; using native fallback: $($_.Exception.Message)"
    if ($null -eq ('MassSpectrometry.NativeMemoryStatus' -as [type])) {
      Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace MassSpectrometry {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)] public class NativeMemoryStatus {
    public uint dwLength = (uint)Marshal.SizeOf(typeof(NativeMemoryStatus));
    public uint dwMemoryLoad; public ulong ullTotalPhys; public ulong ullAvailPhys;
    public ulong ullTotalPageFile; public ulong ullAvailPageFile; public ulong ullTotalVirtual;
    public ulong ullAvailVirtual; public ulong ullAvailExtendedVirtual;
    [DllImport("kernel32.dll", SetLastError=true)] public static extern bool GlobalMemoryStatusEx([In, Out] NativeMemoryStatus status);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct ProcessEntry {
      public uint dwSize; public uint cntUsage; public uint th32ProcessID; public IntPtr th32DefaultHeapID;
      public uint th32ModuleID; public uint cntThreads; public uint th32ParentProcessID;
      public int pcPriClassBase; public uint dwFlags;
      [MarshalAs(UnmanagedType.ByValTStr, SizeConst=260)] public string szExeFile;
    }
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool Process32First(IntPtr snapshot, ref ProcessEntry entry);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool Process32Next(IntPtr snapshot, ref ProcessEntry entry);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
    public static int ParentProcessId(int processId) {
      IntPtr snapshot=CreateToolhelp32Snapshot(0x00000002, 0);
      if (snapshot == IntPtr.Zero || snapshot == new IntPtr(-1)) return -1;
      try {
        ProcessEntry entry=new ProcessEntry(); entry.dwSize=(uint)Marshal.SizeOf(typeof(ProcessEntry));
        if (!Process32First(snapshot, ref entry)) return -1;
        do { if (entry.th32ProcessID == (uint)processId) return (int)entry.th32ParentProcessID; }
        while (Process32Next(snapshot, ref entry));
        return -1;
      } finally { CloseHandle(snapshot); }
    }
  }
}
'@
    }
    $memory = [MassSpectrometry.NativeMemoryStatus]::new()
    if (-not [MassSpectrometry.NativeMemoryStatus]::GlobalMemoryStatusEx($memory)) {
      throw 'Native memory telemetry is unavailable.'
    }
    $sample = Get-Counter '\Processor Information(_Total)\% Processor Time' -ErrorAction Stop
    $load = [double](@($sample.CounterSamples | Select-Object -First 1)[0].CookedValue)
    if (-not [double]::IsFinite($load) -or $load -lt 0 -or $load -gt 100) { throw 'Native CPU telemetry is invalid.' }
    $unknownProcessIds = [Collections.Generic.List[int]]::new()
    $definitelyExitedProcessIds = [Collections.Generic.List[int]]::new()
    $processes = @(foreach ($process in [Diagnostics.Process]::GetProcesses()) {
      try {
        $started = $process.StartTime.ToUniversalTime().Ticks.ToString('D19')
        $parent=[MassSpectrometry.NativeMemoryStatus]::ParentProcessId([int]$process.Id)
        if($parent-lt0){$parent=0}
        @{ pid=[int]$process.Id; parent_pid=$parent; started=$started
           memory_bytes=[int64]$process.WorkingSet64; is_system_console_host=$false }
      } catch {
        $started=Get-HostResourceNativeProcessCreationTicks -ProcessId ([int]$process.Id)
        if($null-ne$started){
          $parent=[MassSpectrometry.NativeMemoryStatus]::ParentProcessId([int]$process.Id)
          if($parent-lt0){$parent=0}
          @{ pid=[int]$process.Id; parent_pid=$parent; started=$started
             memory_bytes=[int64]$process.WorkingSet64; is_system_console_host=$false }
          continue
        }
        # An exited process is neither a live descendant nor an unavailable
        # identity. Preserve fail-closed handling only when both OS paths
        # cannot read a live process creation identity.
        if($process.HasExited){$definitelyExitedProcessIds.Add([int]$process.Id)}else{$unknownProcessIds.Add([int]$process.Id)}
      }
      finally { $process.Dispose() }
    })
    $totalMemoryBytes = [int64]$memory.ullTotalPhys
    $availableMemoryBytes = [int64]$memory.ullAvailPhys
  }
  # I/O slots consult the configured target-volume queue threshold. A single
  # queued request is normal bulk I/O, not proof that the disk is saturated.
  $ioPressure = $true
  try {
    $disks = @(Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -ErrorAction Stop |
      Where-Object Name -ne '_Total')
    $ioPressure = Get-HostResourceIoPressure -Disks $disks -TargetPath $PSScriptRoot
  } catch {
    # WMI disk telemetry may be denied to a desktop child even though the
    # standard Windows performance counter remains available.  Use the total
    # physical-disk queue as a conservative fallback; an unavailable counter
    # still leaves admission closed.
    try {
      $sample = Get-Counter '\PhysicalDisk(_Total)\Current Disk Queue Length' -ErrorAction Stop
      $queue = [double](@($sample.CounterSamples | Select-Object -First 1)[0].CookedValue)
      if (-not [double]::IsFinite($queue) -or $queue -lt 0) { throw 'Disk queue telemetry is invalid.' }
      $policy = Get-Content -LiteralPath $script:HostResourcePolicyPath -Raw | ConvertFrom-Json -AsHashtable
      $ioPressure = $queue -ge [double]$policy.io_pressure_queue_length_threshold
      Write-Verbose "CIM disk telemetry unavailable; used physical-disk queue fallback: $queue"
    } catch {
      Write-Verbose "Disk telemetry unavailable: $($_.Exception.Message)"
    }
  }
  return @{
    complete = $true; processes = $processes; unknown_process_ids = $unknownProcessIds.ToArray(); definitely_exited_process_ids = $definitelyExitedProcessIds.ToArray()
    logical_processors = [Environment]::ProcessorCount
    cpu_percent = $load
    total_memory_bytes = $totalMemoryBytes
    available_memory_bytes = $availableMemoryBytes
    io_pressure = $ioPressure
  }
}

function Invoke-HostResourceTransaction {
  [CmdletBinding()]
  param([Parameter(Mandatory)][hashtable]$Request, [Parameter(Mandatory)][string]$StatePath)
  $policy = Get-Content -LiteralPath $script:HostResourcePolicyPath -Raw | ConvertFrom-Json
  $backoffMilliseconds = [int]$policy.poll_milliseconds
  $timer = [Diagnostics.Stopwatch]::StartNew()
  $lastReport = -[double]$policy.status_interval_seconds
  $repo = Split-Path -Parent $PSScriptRoot
  $python = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else {
    Join-Path $repo '.venv/Scripts/python.exe'
  }
  if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Host scheduler requires the repository Python runtime: $python"
  }
  while ($true) {
    $snapshotStarted = [DateTime]::UtcNow.Ticks
    $snapshot = Get-HostResourceSnapshot
    $snapshot.observed_at_ticks = $snapshotStarted
    $owner = @($snapshot.processes | Where-Object pid -eq $PID)
    if ($owner.Count -ne 1) { throw 'Cannot establish the current process creation identity.' }
    $Request.owner = @{pid=$PID; started=[string]$owner[0].started}
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $python; $start.WorkingDirectory = $repo
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true; $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    foreach ($arg in @('-m','common.host_resource_scheduler','--state',$StatePath)) { $start.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::Start($start)
    try {
      $outputTask = $process.StandardOutput.ReadToEndAsync()
      $errorTask = $process.StandardError.ReadToEndAsync()
      $process.StandardInput.WriteLine((@{request=$Request;snapshot=$snapshot} | ConvertTo-Json -Depth 12 -Compress))
      $process.StandardInput.Close()
      if (-not $process.WaitForExit(45000)) {
        $process.Kill($true); $process.WaitForExit()
        throw 'Host scheduler transaction timed out; existing reservations are retained.'
      }
      $output = $outputTask.GetAwaiter().GetResult()
      $errorText = $errorTask.GetAwaiter().GetResult()
      if ($process.ExitCode -eq 0) { return $output | ConvertFrom-Json -Depth 12 }
      if ($process.ExitCode -ne 75) { throw "Host scheduler transaction failed: $errorText" }
    } finally { $process.Dispose() }
    # Another transaction committed a newer observation. This is ordinary
    # queue contention, not a workload failure. Never reuse the rejected
    # snapshot, and never retain subprocess handles or recursive stack frames.
    if ($timer.Elapsed.TotalSeconds - $lastReport -ge $policy.status_interval_seconds) {
      Write-Host "HOST_RESOURCE=WAIT REASON=snapshot_contention OPERATION=$($Request.operation) WAIT_SECONDS=$([int]$timer.Elapsed.TotalSeconds)"
      $lastReport = $timer.Elapsed.TotalSeconds
    }
    $delay = Get-Random -Minimum ([int]$policy.poll_milliseconds) -Maximum ($backoffMilliseconds + 1)
    Start-Sleep -Milliseconds $delay
    $backoffMilliseconds = [int][Math]::Min(
      [int]$policy.snapshot_backoff_max_milliseconds, [int64]$backoffMilliseconds * 2)
  }
}

function Receive-HostResourceStage {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease)
  if ($Lease.inherited) { return $Lease }
  $record = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request @{
    operation='poll';token=$Lease.token
  }
  $Lease.status = [string]$record.status
  $Lease.reason = [string]$record.reason
  return $Lease
}

function Assert-HostResourceHeavyStage {
  <# Verify permission once at the internal worker scheduler boundary. #>
  [CmdletBinding()]
  param($Lease = $null)
  $token = if ($null -ne $Lease) { $Lease.token } else { $env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN }
  $statePath = if ($null -ne $Lease) { $Lease.state_path } else { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH }
  if (-not $token) { throw 'An acquired heavy stage resource token is required.' }
  if (-not $statePath) { $statePath = $script:HostResourceStatePath }
  $null = Invoke-HostResourceTransaction -StatePath $statePath -Request @{
    operation='inherit';token=$token;require_heavy_stage=$true
  }
}

function Wait-HostResourceStage {
  param([Parameter(Mandatory)]$Lease)
  $policy = Get-Content -LiteralPath $script:HostResourcePolicyPath -Raw | ConvertFrom-Json
  $timer = [Diagnostics.Stopwatch]::StartNew()
  $lastReport = -[double]$policy.status_interval_seconds
  while ($Lease.status -ne 'acquired') {
    if ($timer.Elapsed.TotalSeconds - $lastReport -ge $policy.status_interval_seconds) {
      Write-Host "HOST_RESOURCE=WAIT ROLE=$($Lease.role) STAGE=$($Lease.stage) REASON=$($Lease.reason) WAIT_SECONDS=$([int]$timer.Elapsed.TotalSeconds)"
      $lastReport = $timer.Elapsed.TotalSeconds
    }
    Start-Sleep -Milliseconds $policy.poll_milliseconds
    $Lease = Receive-HostResourceStage -Lease $Lease
  }
  Write-Host "HOST_RESOURCE=ACQUIRED ROLE=$($Lease.role) STAGE=$($Lease.stage) PID=$PID INHERITED=$($Lease.inherited)"
  return $Lease
}

function Enter-HostResourceStage {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][ValidateSet('GATE','SIMION','COMSOL')][string]$Role,
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][hashtable]$Budget,
    [string]$RunId = '', [string]$StatePath = '',
    [switch]$NoEnvironment, [switch]$NoWait
  )
  $Budget = $Budget.Clone()
  $Budget.heavy_stage = (Get-HostResourceBudget -Role $Role -Stage $Stage).heavy_stage
  if (-not $StatePath) {
    $StatePath = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) {
      $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH
    } else { $script:HostResourceStatePath }
  }
  $inherited = -not [string]::IsNullOrWhiteSpace($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN)
  $request = if ($inherited) {
    @{operation='inherit'; token=$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN;role=$Role;budget=$Budget}
  } else {
    @{operation='request';token=[guid]::NewGuid().ToString('N');role=$Role;stage=$Stage;budget=$Budget;run_id=$RunId}
  }
  $record = Invoke-HostResourceTransaction -Request $request -StatePath $StatePath
  $previous = @{}
  foreach ($name in @('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH',
      'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  }
  $lease = [pscustomobject]@{
    token=[string]$record.token;status=[string]$record.status;reason=[string]$record.reason
    inherited=$inherited;state_path=$StatePath;role=$Role;stage=$Stage;run_id=$RunId
    owner_pid=$PID;previous_environment=$previous;environment_set=(-not $NoEnvironment)
    registered_work_processes=@{};completed_work_processes=[Collections.Generic.List[object]]::new()
  }
  try {
    if (-not $NoWait) { $lease = Wait-HostResourceStage -Lease $lease }
    if (-not $NoEnvironment) {
      if ($lease.status -ne 'acquired') { throw 'NoWait requires NoEnvironment until the stage is acquired.' }
      $env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN = $lease.token
      $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = $StatePath
      $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID = [string]$record.owner.pid
      $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE = $Role
    }
    return $lease
  } catch {
    if (-not $inherited) {
      $null = Invoke-HostResourceTransaction -StatePath $StatePath -Request @{operation='release';token=$lease.token}
    }
    throw
  }
}

function Update-HostResourceStage {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease, [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][hashtable]$Budget, [Parameter(Mandatory)][int64]$RetainedMemoryBytes)
  $Budget = $Budget.Clone()
  $Budget.heavy_stage = (Get-HostResourceBudget -Role $Lease.role -Stage $Stage).heavy_stage
  if ($Lease.inherited) {
    $null = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request @{
      operation='inherit';token=$Lease.token;role=$Lease.role;budget=$Budget
    }
    return $Lease
  }
  # A completed child can remain visible for one process-snapshot interval.
  # Do not turn that normal hand-off into a failed physics run: refresh until
  # the scheduler sees the terminal child disappear, while retaining the
  # existing lease and its admission promise throughout.
  $deadline = [DateTime]::UtcNow.AddSeconds(30)
  while ($true) {
    try {
      $record = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request @{
        operation='transition';token=$Lease.token;stage=$Stage;budget=$Budget;retained_memory_bytes=$RetainedMemoryBytes
      }
      break
    } catch {
      if ($_.Exception.Message -notmatch 'live descendants still own this stage' -or [DateTime]::UtcNow -ge $deadline) {
        throw
      }
      Start-Sleep -Milliseconds 100
    }
  }
  $Lease.stage=$Stage; $Lease.status=[string]$record.status; $Lease.reason=[string]$record.reason
  return Wait-HostResourceStage -Lease $Lease
}

function Register-HostResourceProcess {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease, [Parameter(Mandatory)][int]$ProcessId)
  $record = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request @{
    operation='register';token=$Lease.token;process_id=$ProcessId
  }
  $registered=@($record.processes|Where-Object{[int]$_.pid-eq$ProcessId})
  if($registered.Count-ne1){throw 'Scheduler did not return one exact registered work-process identity.'}
  $Lease.registered_work_processes[[string]$ProcessId]=[string]$registered[0].started
  return $Lease
}

function Wait-HostResourceProcess {
  <# Synchronously wait one registered child and retain its exact completion proof. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease,[Parameter(Mandatory)]$Process)
  if($Lease.inherited){throw 'An inherited lease cannot attest work-process completion.'}
  $pid=[int]$Process.Id;$key=[string]$pid
  if(-not $Lease.registered_work_processes.ContainsKey($key)){throw 'Completion requires a process registered by this lease.'}
  $expected=[string]$Lease.registered_work_processes[$key]
  try{$actual=$Process.StartTime.ToUniversalTime().Ticks.ToString('D19')}catch{throw 'Completion requires a readable registered process creation identity.'}
  if($actual-ne$expected){throw 'Completion process identity differs from the registered work process.'}
  $Process.WaitForExit()
  if(-not $Process.HasExited){throw 'Synchronous work-process wait did not reach terminal state.'}
  foreach($completed in @($Lease.completed_work_processes)){
    if([int]$completed.pid-eq$pid-and[string]$completed.started-eq$expected){return $Lease}
  }
  $Lease.completed_work_processes.Add([pscustomobject]@{pid=$pid;started=$expected})
  return $Lease
}

function Exit-HostResourceStage {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease)
  try {
    if (-not $Lease.inherited) {
      $request=@{operation='release';token=$Lease.token}
      if($Lease.completed_work_processes.Count-gt0){$request.completed_work_processes=@($Lease.completed_work_processes)}
      $result = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request $request
      Write-Host "HOST_RESOURCE=RELEASE ROLE=$($Lease.role) STAGE=$($Lease.stage) STATUS=$($result.status)"
    }
  } finally {
    if ($Lease.environment_set) {
      foreach ($name in $Lease.previous_environment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $Lease.previous_environment[$name], 'Process')
      }
    }
  }
}

function Get-HostResourceStatus {
  param([string]$StatePath = $script:HostResourceStatePath)
  return Invoke-HostResourceTransaction -StatePath $StatePath -Request @{operation='status'}
}

function Enter-HostExecutionLease {
  <# Only centrally listed stages request heavy permission; unlisted work is light. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][ValidateSet('SIMION','COMSOL','GATE')][string]$Role,
    [string]$RunId = '', [string]$Stage = 'unclassified')
  return Enter-HostResourceStage -Role $Role -RunId $RunId -Stage $Stage -Budget (Get-HostResourceBudget -Role $Role -Stage $Stage)
}

function Exit-HostExecutionLease {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease,
    [ValidateSet('','success','failed','interrupted')][string]$Outcome = '', [string]$RunId = '')
  Exit-HostResourceStage -Lease $Lease
  if (-not $Lease.inherited -and $Lease.role -in @('SIMION','COMSOL') -and $Outcome) {
    Invoke-HostExecutionCompletionNotification -Outcome $Outcome -RunId $(if ($RunId) {$RunId} else {$Lease.run_id})
  }
}

function Invoke-HostExecutionCompletionNotification {
  <# Best-effort local notification for a terminal solver run. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [ValidateSet('success', 'failed', 'interrupted')]
    [string]$Outcome,
    [Parameter(Mandatory)]
    [string]$RunId
  )
  $setting = [Environment]::GetEnvironmentVariable('SIMULATION_COMPLETION_SOUND')
  if ([string]::Equals($setting, 'off', [StringComparison]::OrdinalIgnoreCase)) {
    Write-Verbose "Solver completion sound is disabled for run $RunId."
    return
  }
  try {
    if ($Outcome -eq 'success') {
      # A short major-triad ascent is deliberately reserved for one successful
      # top-level solver completion; it is distinct from Windows' warning cue.
      foreach ($tone in @(@(523, 120), @(659, 120), @(784, 120))) {
        [Console]::Beep([int]$tone[0], [int]$tone[1])
      }
    } else {
      [System.Media.SystemSounds]::Hand.Play()
    }
    Write-Host "HOST_EXECUTION_NOTIFICATION=PLAYED OUTCOME=$Outcome RUN_ID=$RunId"
  } catch {
    # Audio cannot alter a scientific run's terminal status.
    Write-Warning "HOST_EXECUTION_NOTIFICATION=UNAVAILABLE OUTCOME=$Outcome RUN_ID=$RunId REASON=$($_.Exception.Message)"
  }
}
