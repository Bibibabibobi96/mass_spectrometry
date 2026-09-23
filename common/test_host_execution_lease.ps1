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
  . (Join-Path $PSScriptRoot 'contracts/run_artifact_support.ps1')
  $realTransaction=${function:Invoke-HostResourceTransaction}
  try {
    function Invoke-HostResourceTransaction {
      param([hashtable]$Request,[string]$StatePath)
      return [pscustomobject]@{processes=@(
        [pscustomobject]@{pid=4242;started='0000000000000000001'},
        [pscustomobject]@{pid=4242;started='0000000000000000001'}
      )}
    }
    $duplicateLease=[pscustomobject]@{
      state_path=$statePath;token='duplicate-registration-test';registered_work_processes=@{}
    }
    $duplicateLease=Register-HostResourceProcess -Lease $duplicateLease -ProcessId 4242
    Assert-True ($duplicateLease.registered_work_processes['4242']-eq'0000000000000000001') `
      'Duplicate scheduler observations of one process identity must register once.'
  } finally {
    Set-Item -Path function:Invoke-HostResourceTransaction -Value $realTransaction
  }
  $nativeTicks = Get-HostResourceNativeProcessCreationTicks -ProcessId $PID
  $managedTicks = (Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks.ToString('D19')
  Assert-True ($nativeTicks -eq $managedTicks) 'Native limited process query did not preserve the current creation identity.'
  $ordinary = Get-HostResourceBudget -Role GATE -Stage unlisted-ordinary-check
  Assert-True (-not $ordinary.heavy_stage -and -not $ordinary.unknown_peak -and $ordinary.memory_bytes -eq 2GB) `
    'Ordinary unclassified GATE work must default to its declared light budget.'
  Assert-True ($ordinary.cpu_cores -le 2 -and $ordinary.cpu_cores -gt 0) 'Ordinary CPU declaration is invalid.'
  foreach ($vendorRole in @('GATE','SIMION','COMSOL')) {
    Assert-True (-not (Get-HostResourceBudget -Role $vendorRole -Stage unlisted-solver).heavy_stage) `
      'An unlisted stage must remain light regardless of software role.'
  }
  $comsolPostprocess = Get-HostResourceBudget -Role COMSOL -Stage postprocess
  Assert-True (-not $comsolPostprocess.heavy_stage -and -not $comsolPostprocess.unknown_peak -and
    $comsolPostprocess.memory_bytes -eq $ordinary.memory_bytes) 'COMSOL postprocess must use ordinary-light.'
  Assert-True ((Get-HostResourceBudget -Role COMSOL -Stage solver).heavy_stage) 'COMSOL solver lost its heavy permission.'
  foreach ($stageCase in @(@('SIMION','pa_refine'), @('SIMION','flight'), @('GATE','theory_compute'))) {
    Assert-True ((Get-HostResourceBudget -Role $stageCase[0] -Stage $stageCase[1]).heavy_stage) 'Listed stage lost heavy classification.'
  }
  foreach ($flightStage in @('flight','mrtof_flight')) {
    $flight=Get-HostResourceBudget -Role SIMION -Stage $flightStage
    Assert-True ($flight.heavy_stage-and$flight.io_slots-eq1) `
      'SIMION flight must retain heavy exclusion without reserving every I/O stream.'
  }
  $dirichletResponse=Get-HostResourceBudget -Role SIMION -Stage dirichlet_response_refine
  Assert-True (-not$dirichletResponse.heavy_stage-and$dirichletResponse.io_slots-eq1-and
    $dirichletResponse.memory_bytes-eq6GB-and$dirichletResponse.cpu_cores-eq2) `
    'Measured Dirichlet-response admission profile is invalid.'
  foreach ($prepareStage in @('prepare','pa_prepare','mrtof_pa_prepare','analyzer_local_pa_prepare','accelerator_pa_prepare')) {
    Assert-True (-not (Get-HostResourceBudget -Role SIMION -Stage $prepareStage).heavy_stage) `
      'An unlisted PA preparation stage must remain light.'
  }
  Assert-True ((Get-HostResourceBudget -Profile unknown).unknown_peak) 'Explicit conservative unknown profile was lost.'
  Assert-True (Test-HostResourceConsoleProcess -ImagePath (Join-Path ([Environment]::SystemDirectory) 'conhost.exe')) `
    'The OS console image was not recognized.'
  Assert-True (-not (Test-HostResourceConsoleProcess -ImagePath (Join-Path $testRoot 'conhost.exe'))) `
    'A same-name executable outside the Windows system directory was incorrectly exempted.'
  Assert-True (-not (Test-HostResourceConsoleProcess -ImagePath $null)) `
    'An unknown executable image was incorrectly exempted.'
  $diskFixture=@(
    [pscustomobject]@{Name='0';CurrentDiskQueueLength=3},
    [pscustomobject]@{Name='2 C:';CurrentDiskQueueLength=0}
  )
  Assert-True (-not (Get-HostResourceIoPressure -Disks $diskFixture -TargetPath 'C:\repo')) `
    'An unrelated physical-disk queue incorrectly blocked the repository volume.'
  $diskFixture[1].CurrentDiskQueueLength=2
  Assert-True (Get-HostResourceIoPressure -Disks $diskFixture -TargetPath 'C:\repo') `
    'A queue on the repository volume was not observed.'
  Assert-True (Get-HostResourceIoPressure -Disks @($diskFixture[0]) -TargetPath 'C:\repo') `
    'Missing repository-volume telemetry did not fail closed.'
  $realSnapshot = ${function:Get-HostResourceSnapshot}
  function Get-HostResourceSnapshot {
    $value = & $realSnapshot
    $value.cpu_percent = 0; $value.available_memory_bytes = 32GB
    $value.total_memory_bytes = 64GB; $value.logical_processors = 4; $value.io_pressure = $false
    return $value
  }
  $light = Get-HostResourceBudget -Profile measured-small-check
  $override = Get-HostResourceBudget -Profile heavy-compute
  $override.cpu_cores = $light.cpu_cores; $override.memory_bytes = $light.memory_bytes; $override.io_slots = 0
  $lease = Enter-HostResourceStage -Role GATE -Stage 'test-prepare' -Budget $override
  Assert-True ($lease.status -eq 'acquired') 'A valid stage did not acquire.'
  $rejectedLight = $false
  try { Assert-HostResourceHeavyStage } catch { $rejectedLight = $true }
  Assert-True $rejectedLight 'Light admission incorrectly authorized whole-host worker scheduling.'
  $inherited = Enter-HostResourceStage -Role GATE -Stage 'nested-known' -Budget $light
  Assert-True ($inherited.inherited -and $inherited.token -eq $lease.token) 'Nested entry allocated a second reservation.'
  Exit-HostExecutionLease -Lease $inherited
  $lease = Update-HostResourceStage -Lease $lease -Stage 'test-analyze' -Budget $light -RetainedMemoryBytes 0
  Assert-True ($lease.stage -eq 'test-analyze' -and $lease.status -eq 'acquired') 'Stage transition failed.'
  $lease = Update-HostResourceStage -Lease $lease -Stage 'theory_compute' `
    -Budget $light -RetainedMemoryBytes 0
  Assert-HostResourceHeavyStage -Lease $lease
  Assert-HostResourceHeavyStage
  Exit-HostResourceStage -Lease $lease
  $lease = $null
  Assert-True (@((Get-HostResourceStatus -StatePath $statePath).records).Count -eq 0) 'Normal release leaked a reservation.'

  # Run the real postprocess -> artifact-capacity entry chain against an empty
  # temporary artifact root and this private ledger, never production storage.
  $capacityRoot = Join-Path $testRoot 'artifacts'
  New-Item -ItemType Directory -Path $capacityRoot | Out-Null
  $lease = Enter-HostExecutionLease -Role SIMION -Stage mrtof_postprocess
  try {
    $capacity = Invoke-ArtifactCapacityGate -Python $PythonExe -RepoRoot (Split-Path -Parent $PSScriptRoot) `
      -ArtifactRoot $capacityRoot
    Assert-True $capacity.satisfied_after_apply 'Nested capacity gate did not complete.'
    $records = @((Get-HostResourceStatus -StatePath $statePath).records)
    Assert-True ($records.Count -eq 1 -and $records[0].token -eq $lease.token) 'Capacity child changed its parent grant.'
  } finally { Exit-HostExecutionLease -Lease $lease; $lease = $null }
  Assert-True (@((Get-HostResourceStatus -StatePath $statePath).records).Count -eq 0) 'Postprocess capacity chain leaked a grant.'

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
  $lease = Enter-HostExecutionLease -Role COMSOL -Stage solver -RunId 'test-listed-heavy'
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
`$childLease = Enter-HostResourceStage -Role GATE -Stage test-child -StatePath '$quotedState' -Budget (Get-HostResourceBudget -Role GATE -Stage test-child) -NoWait -NoEnvironment
if (`$childLease.status -ne 'acquired') { throw 'Ordinary light work could not share idle heavy capacity.' }
Exit-HostResourceStage -Lease `$childLease
`$childLease = Enter-HostResourceStage -Role SIMION -Stage flight -StatePath '$quotedState' -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -NoWait -NoEnvironment
if (`$childLease.status -ne 'waiting') { throw 'An unknown heavy stage did not exclude a second heavy stage.' }
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
