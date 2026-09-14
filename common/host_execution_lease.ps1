Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:HostResourcePolicyPath = Join-Path $PSScriptRoot 'host_resource_policy.json'
$script:HostResourceStatePath = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'MassSpectrometry/host_resources.sqlite3'

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

function Get-HostResourceSnapshot {
  <# Fresh OS observations; a missing snapshot blocks admission, never releases leases. #>
  $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
  $cpu = @(Get-CimInstance Win32_Processor -ErrorAction Stop)
  $load = ($cpu | Measure-Object LoadPercentage -Average).Average
  $unknownProcessIds = [Collections.Generic.List[int]]::new()
  $processes = @(foreach ($process in Get-CimInstance Win32_Process -ErrorAction Stop) {
    if ($null -eq $process.CreationDate) {
      $unknownProcessIds.Add([int]$process.ProcessId)
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
  # I/O slots serialize uncalibrated bulk writers. Observe an actual queue,
  # rather than treating low CPU usage as evidence that a disk is idle.
  $ioPressure = $true
  try {
    $disks = @(Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -ErrorAction Stop |
      Where-Object Name -ne '_Total')
    $ioPressure = $disks.Count -eq 0 -or @($disks | Where-Object CurrentDiskQueueLength -gt 0).Count -gt 0
  } catch { Write-Verbose "Disk telemetry unavailable: $($_.Exception.Message)" }
  return @{
    complete = $true; processes = $processes; unknown_process_ids = $unknownProcessIds.ToArray()
    logical_processors = [Environment]::ProcessorCount
    cpu_percent = $load
    total_memory_bytes = [int64]$os.TotalVisibleMemorySize * 1KB
    available_memory_bytes = [int64]$os.FreePhysicalMemory * 1KB
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
  $record = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request @{
    operation='transition';token=$Lease.token;stage=$Stage;budget=$Budget;retained_memory_bytes=$RetainedMemoryBytes
  }
  $Lease.stage=$Stage; $Lease.status=[string]$record.status; $Lease.reason=[string]$record.reason
  return Wait-HostResourceStage -Lease $Lease
}

function Register-HostResourceProcess {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease, [Parameter(Mandatory)][int]$ProcessId)
  $null = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request @{
    operation='register';token=$Lease.token;process_id=$ProcessId
  }
}

function Exit-HostResourceStage {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease)
  try {
    if (-not $Lease.inherited) {
      $result = Invoke-HostResourceTransaction -StatePath $Lease.state_path -Request @{operation='release';token=$Lease.token}
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
