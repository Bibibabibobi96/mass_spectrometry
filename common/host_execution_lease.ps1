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
    [Parameter(Mandatory)][ValidateSet('SIMION', 'GATE')][string]$Role,
    [Parameter(Mandatory)][int]$OwnerProcessId
  )
  $parent = Split-Path -Parent $Path
  if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }
  $receipt = [ordered]@{
    schema_version = 1
    role = $Role
    owner_pid = $OwnerProcessId
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
    Serialize real SIMION execution and repository gates on this Windows host.
    A child gate inherits the environment marker from its owning gate and must
    not attempt a second, cross-process mutex acquisition.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][ValidateSet('SIMION', 'GATE')][string]$Role,
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
      -OwnerProcessId $ownerProcessId
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
      previous_role = $previousRole; previous_owner_pid = $previousOwnerPid
    }
  } catch {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    throw
  }
}

function Exit-HostExecutionLease {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Lease)
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
  }
}
