param([string]$PythonExe = (Join-Path (Split-Path -Parent $PSScriptRoot) '.venv/Scripts/python.exe'))

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw $Message }
}

# Long-term behavior tests create only isolated temporary state; never use the
# live host ledger and never launch a commercial solver.
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('host_stage_test_' + [guid]::NewGuid().ToString('N'))
$statePath = Join-Path $testRoot 'state.sqlite3'
$leaseSource = Join-Path $PSScriptRoot 'host_execution_lease.ps1'
$savedEnvironment = @{}
foreach ($name in @('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH',
    'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID','MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE','SIMULATION_PYTHON_EXE')) {
  $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
$lease = $null
try {
  New-Item -ItemType Directory -Path $testRoot | Out-Null
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = $statePath
  $env:SIMULATION_PYTHON_EXE = $PythonExe
  . $leaseSource
  Assert-True (Test-HostResourceConsoleProcess -ImagePath (Join-Path ([Environment]::SystemDirectory) 'conhost.exe')) `
    'The OS console image was not recognized.'
  Assert-True (-not (Test-HostResourceConsoleProcess -ImagePath (Join-Path $testRoot 'conhost.exe'))) `
    'A same-name executable outside the Windows system directory was incorrectly exempted.'
  Assert-True (-not (Test-HostResourceConsoleProcess -ImagePath $null)) `
    'An unknown executable image was incorrectly exempted.'
  $realSnapshot = ${function:Get-HostResourceSnapshot}
  function Get-HostResourceSnapshot {
    $value = & $realSnapshot
    $value.cpu_percent = 0; $value.available_memory_bytes = 32GB
    $value.total_memory_bytes = 64GB; $value.logical_processors = 4; $value.io_pressure = $false
    return $value
  }
  $light = Get-HostResourceBudget -Profile measured-small-check
  $lease = Enter-HostResourceStage -Role GATE -Stage 'test-prepare' -Budget $light
  Assert-True ($lease.status -eq 'acquired') 'A valid stage did not acquire.'
  $inherited = Enter-HostResourceStage -Role GATE -Stage 'nested-known' -Budget $light
  Assert-True ($inherited.inherited -and $inherited.token -eq $lease.token) 'Nested entry allocated a second reservation.'
  Exit-HostExecutionLease -Lease $inherited
  $lease = Update-HostResourceStage -Lease $lease -Stage 'test-analyze' -Budget $light -RetainedMemoryBytes 0
  Assert-True ($lease.stage -eq 'test-analyze' -and $lease.status -eq 'acquired') 'Stage transition failed.'
  Exit-HostResourceStage -Lease $lease
  $lease = $null
  Assert-True (@((Get-HostResourceStatus -StatePath $statePath).records).Count -eq 0) 'Normal release leaked a reservation.'

  # A hidden Windows console owns a real conhost child for its entire life.
  # Process identities and image paths are real; only host pressure is fixed.
  $quotedSource = $leaseSource.Replace("'", "''")
  $quotedState = (Join-Path $testRoot 'hidden.sqlite3').Replace("'", "''")
  $hiddenError = Join-Path $testRoot 'hidden-error.txt'
  $quotedHiddenError = $hiddenError.Replace("'", "''")
  $hiddenCode = @"
trap { [IO.File]::WriteAllText('$quotedHiddenError', `$_.Exception.ToString()); exit 1 }
. '$quotedSource'
`$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = '$quotedState'
Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue
`$real = `${function:Get-HostResourceSnapshot}
function Get-HostResourceSnapshot {
  `$s = & `$real
  `$s.cpu_percent=0; `$s.available_memory_bytes=32GB; `$s.total_memory_bytes=64GB; `$s.logical_processors=4; `$s.io_pressure=`$false
  return `$s
}
`$console = @(Get-CimInstance Win32_Process | Where-Object { `$_.ParentProcessId -eq `$PID -and `$_.Name -eq 'conhost.exe' })
if (`$console.Count -eq 0) { throw 'Hidden-console fixture did not create a conhost child.' }
`$budget = Get-HostResourceBudget -Profile measured-small-check
`$hiddenLease = Enter-HostResourceStage -Role GATE -Stage prepare -Budget `$budget
try {
  `$hiddenLease = Update-HostResourceStage -Lease `$hiddenLease -Stage analyze -Budget `$budget -RetainedMemoryBytes 0
  if (`$hiddenLease.stage -ne 'analyze') { throw 'Hidden process did not transition.' }
} finally { Exit-HostResourceStage -Lease `$hiddenLease }
if (@((Get-HostResourceStatus -StatePath '$quotedState').records).Count -ne 0) {
  throw 'Console-only task kept its budget after explicit release while the owner remained alive.'
}
if (@(Get-CimInstance Win32_Process | Where-Object { `$_.ParentProcessId -eq `$PID -and `$_.Name -eq 'conhost.exe' }).Count -eq 0) {
  throw 'The console fixture exited before the release assertion.'
}
`$nextLease = Enter-HostResourceStage -Role GATE -Stage next-request -Budget (Get-HostResourceBudget -Profile unknown) -NoWait -NoEnvironment
try {
  if (`$nextLease.status -ne 'acquired') { throw 'A new request remained blocked after console-only release.' }
} finally { Exit-HostResourceStage -Lease `$nextLease }
"@
  $hiddenEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($hiddenCode))
  $hidden = Start-Process -FilePath (Get-Command pwsh).Source -WindowStyle Hidden -PassThru `
    -ArgumentList @('-NoProfile','-EncodedCommand',$hiddenEncoded)
  Assert-True ($hidden.WaitForExit(45000)) 'Hidden stage fixture did not finish.'
  $hiddenFailure = if (Test-Path -LiteralPath $hiddenError) { Get-Content -LiteralPath $hiddenError -Raw } else { '' }
  Assert-True ($hidden.ExitCode -eq 0) "Hidden stage could not transition with its own conhost child: $hiddenFailure"

  # Independent contender, not a child claiming the same budget.
  $lease = Enter-HostExecutionLease -Role COMSOL -RunId 'test-unknown'
  $quotedSource = $leaseSource.Replace("'", "''")
  $quotedState = $statePath.Replace("'", "''")
  $childCode = @"
. '$quotedSource'
Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID -ErrorAction SilentlyContinue
`$real = `${function:Get-HostResourceSnapshot}
function Get-HostResourceSnapshot {
  `$s = & `$real
  `$s.cpu_percent=0; `$s.available_memory_bytes=32GB; `$s.total_memory_bytes=64GB; `$s.logical_processors=4; `$s.io_pressure=`$false
  return `$s
}
`$childLease = Enter-HostResourceStage -Role GATE -Stage test-child -StatePath '$quotedState' -Budget (Get-HostResourceBudget -Profile measured-small-check) -NoWait -NoEnvironment
if (`$childLease.status -ne 'waiting') { throw 'Unknown peak did not exclude a second stage.' }
Exit-HostResourceStage -Lease `$childLease
"@
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($childCode))
  $child = Start-Process -FilePath (Get-Command pwsh).Source -WindowStyle Hidden -PassThru `
    -ArgumentList @('-NoProfile','-EncodedCommand',$encoded)
  Assert-True ($child.WaitForExit(30000)) 'Isolated contender did not finish.'
  Assert-True ($child.ExitCode -eq 0) 'Isolated contender failed.'
  Exit-HostExecutionLease -Lease $lease
  $lease = $null
  Assert-True (@((Get-HostResourceStatus -StatePath $statePath).records).Count -eq 0) 'Unknown stage leaked a reservation.'
  Write-Output 'HOST_EXECUTION_LEASE_TEST=PASS MODE=ISOLATED_STAGE_LEDGER'
} finally {
  if ($null -ne $lease) { Exit-HostExecutionLease -Lease $lease }
  foreach ($name in $savedEnvironment.Keys) {
    [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
  }
  $resolved = [IO.Path]::GetFullPath($testRoot)
  $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
  if (-not $resolved.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -or
      -not (Split-Path -Leaf $resolved).StartsWith('host_stage_test_')) {
    throw 'Refusing cleanup outside isolated scheduler test directory.'
  }
  if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
