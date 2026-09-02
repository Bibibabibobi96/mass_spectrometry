Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# The mutex, rather than the receipt file, is the authority.  The receipt is
# deliberately only human-readable contention metadata: Windows releases the
# mutex when a holder crashes, even if its receipt survives in TEMP.
$script:HostExecutionLeaseMutexName =
  'Global\MassSpectrometry.HostExecutionLease.v1'
$script:HostExecutionLeaseReceiptPath = Join-Path `
  ([IO.Path]::GetTempPath()) 'mass_spectrometry_host_execution_lease_v1.json'

function Get-HostExecutionLeaseReceipt {
  param([Parameter(Mandatory)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
  try {
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 |
      ConvertFrom-Json -Depth 4
  } catch {
    return $null
  }
}

function Set-HostExecutionLeaseReceipt {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][ValidateSet('SIMION', 'COMSOL', 'GATE')][string]$Role,
    [Parameter(Mandatory)][int]$OwnerProcessId,
    [string]$RunId = ''
  )
  $parent = Split-Path -Parent $Path
  if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }
  $receipt = [ordered]@{
    schema_version = 1
    role = $Role
    owner_pid = $OwnerProcessId
    run_id = $RunId
    acquired_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
  }
  $temporary = "$Path.$OwnerProcessId.tmp"
  [IO.File]::WriteAllText(
    $temporary,
    ($receipt | ConvertTo-Json -Depth 4),
    [Text.UTF8Encoding]::new($false)
  )
  Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Enter-HostExecutionLease {
  <#
    Serialize real SIMION/COMSOL execution and repository gates on this Windows host.
    A child gate inherits the environment marker from its owning gate and must
    not attempt a second, cross-process mutex acquisition.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][ValidateSet('SIMION', 'COMSOL', 'GATE')][string]$Role,
    [string]$RunId = '',
    [string]$MutexName = $script:HostExecutionLeaseMutexName,
    [string]$ReceiptPath = $script:HostExecutionLeaseReceiptPath,
    [ValidateRange(100, 10000)][int]$PollMilliseconds = 1000,
    [ValidateRange(1, 3600)][int]$StatusIntervalSeconds = 30
  )
  $ownerProcessId = [Diagnostics.Process]::GetCurrentProcess().Id
  if ($env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID) {
    $holder = $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID
    Write-Host (
      "HOST_EXECUTION_LEASE=ACQUIRED ROLE=$Role MODE=INHERITED " +
      "HOLDER_PID=$holder WAIT_SECONDS=0"
    )
    return [pscustomobject]@{
      role = $Role; owner_pid = $ownerProcessId; inherited = $true
      mutex = $null; receipt_path = $ReceiptPath
      run_id = $RunId
      previous_role = $null; previous_owner_pid = $null
    }
  }

  $mutex = [Threading.Mutex]::new($false, $MutexName)
  $timer = [Diagnostics.Stopwatch]::StartNew()
  $lastReportedSecond = $null
  $acquired = $false
  try {
    while (-not $acquired) {
      try {
        $acquired = $mutex.WaitOne($PollMilliseconds)
      } catch [Threading.AbandonedMutexException] {
        # The previous holder crashed.  The OS has transferred ownership to us.
        $acquired = $true
      }
      if ($acquired) { break }
      $elapsedSeconds = [int][Math]::Floor($timer.Elapsed.TotalSeconds)
      # Announce contention immediately, then periodically.  Per-poll output
      # makes a long, normal wait unreadable without conveying new state.
      if ($null -eq $lastReportedSecond -or
          $elapsedSeconds - $lastReportedSecond -ge $StatusIntervalSeconds) {
        $receipt = Get-HostExecutionLeaseReceipt -Path $ReceiptPath
        $holder = if ($null -ne $receipt -and $receipt.PSObject.Properties.Name -contains 'owner_pid') {
          [string]$receipt.owner_pid
        } else { 'UNKNOWN' }
        Write-Host (
          "HOST_EXECUTION_LEASE=WAIT ROLE=$Role HOLDER_PID=$holder " +
          "WAIT_SECONDS=$elapsedSeconds"
        )
        $lastReportedSecond = $elapsedSeconds
      }
    }
    Set-HostExecutionLeaseReceipt -Path $ReceiptPath -Role $Role `
      -OwnerProcessId $ownerProcessId -RunId $RunId
    $previousRole = $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE
    $previousOwnerPid = $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID
    $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE = $Role
    $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID = [string]$ownerProcessId
    Write-Host (
      "HOST_EXECUTION_LEASE=ACQUIRED ROLE=$Role HOLDER_PID=$ownerProcessId " +
      "WAIT_SECONDS=$([Math]::Round($timer.Elapsed.TotalSeconds, 3))"
    )
    return [pscustomobject]@{
      role = $Role; owner_pid = $ownerProcessId; inherited = $false
      mutex = $mutex; receipt_path = $ReceiptPath
      run_id = $RunId
      previous_role = $previousRole; previous_owner_pid = $previousOwnerPid
    }
  } catch {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    throw
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

function Exit-HostExecutionLease {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]$Lease,
    [ValidateSet('', 'success', 'failed', 'interrupted')]
    [string]$Outcome = '',
    [string]$RunId = ''
  )
  if ([bool]$Lease.inherited) { return }
  try {
    $receipt = Get-HostExecutionLeaseReceipt -Path ([string]$Lease.receipt_path)
    if ($null -ne $receipt -and [string]$receipt.owner_pid -eq [string]$Lease.owner_pid) {
      Remove-Item -LiteralPath ([string]$Lease.receipt_path) -Force -ErrorAction SilentlyContinue
    }
  } finally {
    if ($null -eq $Lease.previous_role) {
      Remove-Item Env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE -ErrorAction SilentlyContinue
    } else {
      $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE = [string]$Lease.previous_role
    }
    if ($null -eq $Lease.previous_owner_pid) {
      Remove-Item Env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID -ErrorAction SilentlyContinue
    } else {
      $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID = [string]$Lease.previous_owner_pid
    }
    try { $Lease.mutex.ReleaseMutex() } finally { $Lease.mutex.Dispose() }
    Write-Host "HOST_EXECUTION_LEASE=RELEASED ROLE=$($Lease.role) PID=$($Lease.owner_pid)"
    if ($Lease.role -in @('SIMION', 'COMSOL') -and -not [string]::IsNullOrWhiteSpace($Outcome)) {
      $notificationRunId = if ([string]::IsNullOrWhiteSpace($RunId)) { "pid-$($Lease.owner_pid)" } else { $RunId }
      Invoke-HostExecutionCompletionNotification -Outcome $Outcome -RunId $notificationRunId
    }
  }
}
