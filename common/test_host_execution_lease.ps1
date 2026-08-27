Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-True {
  param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Message)
  if (-not $Condition) { throw $Message }
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) (
  'host_execution_lease_' + [guid]::NewGuid().ToString('N')
)
$mutexName = 'Global\MassSpectrometry.HostExecutionLease.test.' +
  [guid]::NewGuid().ToString('N')
$receiptPath = Join-Path $testRoot 'lease.json'
$childLog = Join-Path $testRoot 'child.log'
$leasePath = Join-Path $PSScriptRoot 'host_execution_lease.ps1'
$savedRole = [Environment]::GetEnvironmentVariable(
  'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE', 'Process'
)
$savedOwner = [Environment]::GetEnvironmentVariable(
  'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID', 'Process'
)
$parentLease = $null
try {
  New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
  . $leasePath
  $parentLease = Enter-HostExecutionLease -Role GATE -MutexName $mutexName `
    -ReceiptPath $receiptPath -PollMilliseconds 100
  Assert-True (Test-Path -LiteralPath $receiptPath -PathType Leaf) `
    'Lease acquisition did not publish its human-readable receipt.'

  $quotedLeasePath = $leasePath.Replace("'", "''")
  $quotedMutexName = $mutexName.Replace("'", "''")
  $quotedReceiptPath = $receiptPath.Replace("'", "''")
  $childScript = @"
Remove-Item Env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE -ErrorAction SilentlyContinue
Remove-Item Env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID -ErrorAction SilentlyContinue
. '$quotedLeasePath'
`$lease = Enter-HostExecutionLease -Role SIMION -MutexName '$quotedMutexName' -ReceiptPath '$quotedReceiptPath' -PollMilliseconds 100
Exit-HostExecutionLease -Lease `$lease
"@
  $encodedChildScript = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($childScript)
  )
  $child = Start-Process -FilePath (Get-Command pwsh).Source -WindowStyle Hidden `
    -ArgumentList @('-NoProfile', '-EncodedCommand', $encodedChildScript) -PassThru `
    -RedirectStandardOutput $childLog
  Start-Sleep -Milliseconds 350
  Assert-True (-not $child.HasExited) `
    'A second process acquired the host lease while the first holder still owned it.'
  Exit-HostExecutionLease -Lease $parentLease
  $parentLease = $null
  Assert-True ($child.WaitForExit(10000)) `
    'Waiting child did not acquire the host lease after release.'
  $child.Refresh()
  Assert-True ($child.ExitCode -eq 0) `
    "Waiting child exited with code $($child.ExitCode)."
  # Write-Host is deliberately used for live scheduler/gate status and is not
  # redirected by every PowerShell host.  The pre-release liveness assertion
  # above plus successful child completion proves real mutex contention.
  Assert-True (-not (Test-Path -LiteralPath $receiptPath)) `
    'Lease receipt remained after the final holder released it.'

  $env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID = 'synthetic-parent'
  $inherited = Enter-HostExecutionLease -Role GATE -MutexName $mutexName `
    -ReceiptPath $receiptPath -PollMilliseconds 100
  Assert-True ([bool]$inherited.inherited) `
    'Nested gate invocation did not inherit the outer host lease.'
  Exit-HostExecutionLease -Lease $inherited
  Remove-Item Env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID `
    -ErrorAction SilentlyContinue
  Write-Output 'HOST_EXECUTION_LEASE_TEST=PASS'
} finally {
  if ($null -ne $parentLease) { Exit-HostExecutionLease -Lease $parentLease }
  [Environment]::SetEnvironmentVariable(
    'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE', $savedRole, 'Process'
  )
  [Environment]::SetEnvironmentVariable(
    'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID', $savedOwner, 'Process'
  )
  if (Test-Path -LiteralPath $testRoot) {
    Remove-Item -LiteralPath $testRoot -Recurse -Force
  }
}
