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
    # Capture both consumers without opening even the default live database.
    $script:pathSelections = [Collections.Generic.List[string]]::new()
    function Invoke-HostResourceTransaction {
      param([hashtable]$Request, [string]$StatePath)
      $script:pathSelections.Add($StatePath)
      return [pscustomobject]@{token='path-selection-test';status='acquired';reason='fixture';owner=@{pid=$PID}}
    }
    $pathBudget = Get-HostResourceBudget -Role GATE -Stage path-selection
    $explicitState = Join-Path $testRoot 'explicit.sqlite3'
    $environmentState = Join-Path $testRoot 'environment.sqlite3'
    foreach ($case in @(
      @{explicit=$explicitState;environment='relative-env.sqlite3';expected=$explicitState},
      @{explicit='';environment=$environmentState;expected=$environmentState},
      @{explicit='';environment='';expected=$script:HostResourceStatePath}
    )) {
      $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = $case.environment
      $stateArguments = @{}
      if ($case.explicit) { $stateArguments.StatePath = $case.explicit }
      $selected = Enter-HostResourceStage -Role GATE -Stage path-selection -Budget $pathBudget `
        @stateArguments -NoEnvironment -NoWait
      $null = Get-HostResourceStatus @stateArguments
      $expected = [IO.Path]::GetFullPath($case.expected)
      Assert-True ($selected.state_path -eq $expected -and
        $script:pathSelections[-2] -eq $expected -and $script:pathSelections[-1] -eq $expected) `
        'Admission and status selected different explicit/environment/default state paths.'
    }
    foreach ($relative in @('relative.sqlite3', 'C:relative.sqlite3', '\relative.sqlite3')) {
      foreach ($case in @(
        @{explicit=$relative;environment=$environmentState},
        @{explicit='';environment=$relative}
      )) {
        $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = $case.environment
        $stateArguments = @{}
        if ($case.explicit) { $stateArguments.StatePath = $case.explicit }
        $before = $script:pathSelections.Count
        foreach ($consumer in @('admission', 'status')) {
          $rejected = $false
          try {
            if ($consumer -eq 'admission') {
              $null = Enter-HostResourceStage -Role GATE -Stage path-selection -Budget $pathBudget `
                @stateArguments -NoEnvironment -NoWait
            } else { $null = Get-HostResourceStatus @stateArguments }
          } catch { $rejected = $_.Exception.Message -match 'must be absolute' }
          Assert-True $rejected 'Relative deployment paths must fail before a scheduler transaction.'
        }
        Assert-True ($script:pathSelections.Count -eq $before) 'Rejected paths reached the scheduler.'
      }
    }
    Write-Output 'HOST_RESOURCE_PATH_SELECTION_TEST=PASS TRANSACTIONS=MOCKED'
  } finally {
    Set-Item -Path function:Invoke-HostResourceTransaction -Value $realTransaction
    $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = $statePath
    Remove-Variable pathSelections -Scope Script
  }
  try {
    function Invoke-HostResourceTransaction {
      param([hashtable]$Request,[string]$StatePath)
      return [pscustomobject]@{processes=@([pscustomobject]@{pid=4242;started='0000000000000000001'})}
    }
    $duplicateLease=[pscustomobject]@{
      state_path=$statePath;token='duplicate-registration-test';registered_work_processes=@{}
    }
    $duplicateLease=Register-HostResourceProcess -Lease $duplicateLease -ProcessId 4242
    Assert-True ($duplicateLease.registered_work_processes['4242']-eq'0000000000000000001') `
      'One canonical scheduler process identity must register.'
  } finally {
    Set-Item -Path function:Invoke-HostResourceTransaction -Value $realTransaction
  }
  try {
    function Invoke-HostResourceTransaction {
      param([hashtable]$Request,[string]$StatePath)
      return [pscustomobject]@{processes=@(
        [pscustomobject]@{pid=4243;started='0639590650123456700'},
        [pscustomobject]@{pid=4243;started='0639590650123456703'}
      )}
    }
    $precisionLease=[pscustomobject]@{
      state_path=$statePath;token='precision-registration-test';registered_work_processes=@{}
    }
    $rejected=$false
    try { $null=Register-HostResourceProcess -Lease $precisionLease -ProcessId 4243 } catch { $rejected=$_.Exception.Message -match 'one exact registered' }
    Assert-True $rejected 'Lease adapter must reject a noncanonical duplicate scheduler response.'
  } finally {
    Set-Item -Path function:Invoke-HostResourceTransaction -Value $realTransaction
  }
  $emptyParents = [Collections.Generic.Dictionary[int,int]]::new()
  $snapshotParents = [Collections.Generic.Dictionary[int,int]]::new()
  $snapshotParents[11] = 3; $snapshotParents[12] = 7; $snapshotParents[13] = 0
  $parentCases = @(
    @{parents=$emptyParents;pid=11;started='99';expected=0;name='empty-table'},
    @{parents=$snapshotParents;pid=99;started='101';expected=0;name='missing-pid'},
    @{parents=$snapshotParents;pid=11;started='98';expected=3;name='first-pid'},
    @{parents=$snapshotParents;pid=12;started='98';expected=7;name='second-pid'},
    @{parents=$snapshotParents;pid=13;started='98';expected=0;name='parent-zero'},
    @{parents=$snapshotParents;pid=11;started='100';expected=3;name='same-tick'},
    @{parents=$snapshotParents;pid=11;started='99';expected=3;name='earlier-identity'},
    @{parents=$snapshotParents;pid=11;started='101';expected=$null;name='newer-identity'}
  )
  foreach ($case in $parentCases) {
    $actual = Get-HostResourceSnapshotParent -Parents $case.parents -ProcessId $case.pid `
      -Started $case.started -SnapshotStartedUtcTicks 100
    Assert-True ($actual -eq $case.expected) "Snapshot parent lookup failed: $($case.name)"
  }
  Write-Output "HOST_RESOURCE_SNAPSHOT_PARENT_TEST=PASS CASES=$($parentCases.Count)"
  $nativeParents=Get-HostResourceProcessParents
  $nextNativeParents=Get-HostResourceProcessParents
  Assert-True ($nativeParents.complete -and $nativeParents.parents.ContainsKey($PID)) 'Native parent table omitted the actual test process.'
  Assert-True (-not [object]::ReferenceEquals($nativeParents.parents,$nextNativeParents.parents)) 'Native parent table was cached across observations.'
  Assert-True ($nextNativeParents.started_at_utc_ticks -ge $nativeParents.started_at_utc_ticks) 'Native parent observations reversed their capture times.'
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
  Invoke-RunToolRootContext -RepoRoot (Split-Path -Parent $PSScriptRoot) -Operation {
    & $PythonExe -c "from pathlib import Path; from common.contracts import capacity_ledger; import sys; capacity_ledger.initialize_capacity_ledger(Path(sys.argv[1]), objects=[])" $capacityRoot
    if ($LASTEXITCODE -ne 0) { throw 'Host lease capacity ledger fixture initialization failed.' }
    & $PythonExe -m common.contracts.reconcile_artifact_capacity `
      --artifact-root $capacityRoot --create-protection-lease host-lease-capacity `
      --lease-owner host-lease-test --lease-ttl-seconds 3600 --protect-path projects
    if ($LASTEXITCODE -ne 0) { throw 'Host lease capacity protection fixture creation failed.' }
  } | Out-Null
  $lease = Enter-HostExecutionLease -Role SIMION -Stage mrtof_postprocess
  try {
    try {
      $capacity = Invoke-ArtifactCapacityGate -Python $PythonExe -RepoRoot (Split-Path -Parent $PSScriptRoot) `
        -ArtifactRoot $capacityRoot -CapacityProtectionLeaseId host-lease-capacity
      Assert-True ($capacity.satisfied_after_apply-eq$true) 'Capacity wrapper returned an unsatisfied decision.'
    } catch {
      # The isolated empty ledger still shares the host volume's free space.
      if($_.Exception.Message-notlike 'Artifact capacity gate blocked startup: MINIMUM_FREE_CAPACITY_UNAVAILABLE;*'){throw}
    }
    $records = @((Get-HostResourceStatus -StatePath $statePath).records)
    Assert-True ($records.Count -eq 1 -and $records[0].token -eq $lease.token) 'Capacity child changed its parent grant.'
  } finally { Exit-HostExecutionLease -Lease $lease; $lease = $null }
  Assert-True (@((Get-HostResourceStatus -StatePath $statePath).records).Count -eq 0) 'Postprocess capacity chain leaked a grant.'

  # A hidden Windows console owns a real conhost child for its entire life.
  # Process identities and image paths are real; CIM is forced unavailable and
  # only host pressure is fixed to exercise the native snapshot release path.
  $quotedSource = $leaseSource.Replace("'", "''")
  $quotedState = (Join-Path $testRoot 'hidden.sqlite3').Replace("'", "''")
  $hiddenError = Join-Path $testRoot 'hidden-error.txt'
  $quotedHiddenError = $hiddenError.Replace("'", "''")
  $hiddenProgress = Join-Path $testRoot 'hidden-progress.txt'
  $quotedHiddenProgress = $hiddenProgress.Replace("'", "''")
  $hiddenCode = @"
trap { [IO.File]::WriteAllText('$quotedHiddenError', `$_.Exception.ToString()); exit 1 }
. '$quotedSource'
`$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = '$quotedState'
Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue
`$realTransaction = `${function:Invoke-HostResourceTransaction}
function Invoke-HostResourceTransaction {
  param([hashtable]`$Request,[string]`$StatePath)
  `$watch = [Diagnostics.Stopwatch]::StartNew()
  [IO.File]::AppendAllText('$quotedHiddenProgress', ([DateTime]::UtcNow.ToString('O') + ' transaction-start ' + `$Request.operation + "`n"))
  try { & `$realTransaction -Request `$Request -StatePath `$StatePath }
  finally {
    [IO.File]::AppendAllText('$quotedHiddenProgress', ([DateTime]::UtcNow.ToString('O') + ' transaction-end ' + `$Request.operation + ' elapsed_ms=' + `$watch.ElapsedMilliseconds + "`n"))
  }
}
`$real = `${function:Get-HostResourceSnapshot}
`$script:hiddenFixtureSnapshot = `$null
function Get-CimInstance { throw 'Forced CIM unavailability for native console snapshot regression.' }
function Get-HostResourceSnapshot {
  if (`$null -eq `$script:hiddenFixtureSnapshot) {
    [IO.File]::AppendAllText('$quotedHiddenProgress', ([DateTime]::UtcNow.ToString('O') + " native-snapshot-start`n"))
    `$s = & `$real
    `$owners = @(`$s.processes | Where-Object pid -eq `$PID)
    `$consoles = @(`$s.processes | Where-Object { `$_.parent_pid -eq `$PID -and `$_.is_system_console_host })
    if (`$owners.Count -ne 1 -or `$consoles.Count -eq 0) { throw 'Native fallback did not discover the hidden owner and system conhost.' }
    # Keep the real native-discovered fixture tree. Repeated whole-host process
    # and performance-counter enumeration is outside this console-release test.
    `$s.processes = @(`$owners) + @(`$consoles)
    `$s.unknown_process_ids = @(); `$s.definitely_exited_process_ids = @()
    `$script:hiddenFixtureSnapshot = `$s
    [IO.File]::AppendAllText('$quotedHiddenProgress', ([DateTime]::UtcNow.ToString('O') + " native-snapshot-complete`n"))
  }
  `$s = `$script:hiddenFixtureSnapshot.Clone()
  foreach (`$row in `$s.processes) {
    if ((Get-HostResourceNativeProcessCreationTicks -ProcessId `$row.pid) -ne `$row.started) {
      throw 'The native-discovered hidden fixture process changed identity or exited.'
    }
    `$live = [Diagnostics.Process]::GetProcessById(`$row.pid)
    try { if (`$live.HasExited) { throw 'The hidden fixture process is no longer alive.' } }
    finally { `$live.Dispose() }
  }
  `$s.cpu_percent=0; `$s.available_memory_bytes=32GB; `$s.total_memory_bytes=64GB; `$s.logical_processors=4; `$s.io_pressure=`$false
  `$script:hiddenSnapshot = `$s
  [IO.File]::AppendAllText('$quotedHiddenProgress', ([DateTime]::UtcNow.ToString('O') + " snapshot-return`n"))
  return `$s
}
`$budget = Get-HostResourceBudget -Profile measured-small-check
`$hiddenLease = Enter-HostResourceStage -Role GATE -Stage prepare -Budget `$budget
[IO.File]::AppendAllText('$quotedHiddenProgress', "acquired`n")
try {
  `$console = @(`$script:hiddenSnapshot.processes | Where-Object { `$_.parent_pid -eq `$PID -and `$_.is_system_console_host })
  if (`$console.Count -eq 0) { throw 'Hidden-console fixture did not create a conhost child.' }
  `$hiddenLease = Update-HostResourceStage -Lease `$hiddenLease -Stage analyze -Budget `$budget -RetainedMemoryBytes 0
  if (`$hiddenLease.stage -ne 'analyze') { throw 'Hidden process did not transition.' }
} finally { Exit-HostResourceStage -Lease `$hiddenLease }
[IO.File]::AppendAllText('$quotedHiddenProgress', "released`n")
if (@((Get-HostResourceStatus -StatePath '$quotedState').records).Count -ne 0) {
  throw 'Console-only task kept its budget after explicit release while the owner remained alive.'
}
if (@(`$script:hiddenSnapshot.processes | Where-Object { `$_.parent_pid -eq `$PID -and `$_.is_system_console_host }).Count -eq 0) {
  throw 'The console fixture exited before the release assertion.'
}
`$nextLease = Enter-HostResourceStage -Role GATE -Stage next-request -Budget (Get-HostResourceBudget -Profile unknown) -NoWait -NoEnvironment
try {
  if (`$nextLease.status -ne 'acquired') { throw 'A new request remained blocked after console-only release.' }
} finally { Exit-HostResourceStage -Lease `$nextLease }
[IO.File]::AppendAllText('$quotedHiddenProgress', "next-request-released`n")
"@
  $hiddenEncoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($hiddenCode))
  $hidden = Start-Process -FilePath (Get-Command pwsh).Source -WindowStyle Hidden -PassThru `
    -WorkingDirectory $testRoot -ArgumentList @('-NoProfile','-EncodedCommand',$hiddenEncoded)
  try {
    # Measured native-fallback cold snapshot took 42 s on this shared host;
    # allow it plus the existing 45 s transaction boundary, without changing admission.
    $hiddenFinished = $hidden.WaitForExit(90000)
    $hiddenFailure = if (Test-Path -LiteralPath $hiddenError) { Get-Content -LiteralPath $hiddenError -Raw } else { '' }
    $hiddenStages = if (Test-Path -LiteralPath $hiddenProgress) { Get-Content -LiteralPath $hiddenProgress -Raw } else { 'not-started' }
    Write-Output "HIDDEN_FIXTURE_STAGES=$hiddenStages"
    Assert-True $hiddenFinished "Hidden stage fixture did not finish. Stages: $hiddenStages Error: $hiddenFailure"
    Assert-True ($hidden.ExitCode -eq 0) "Hidden stage could not transition with its own conhost child: $hiddenFailure Stages: $hiddenStages"
  } finally {
    # Reap only this fixture's process tree before deleting its private ledger.
    if (-not $hidden.HasExited) { $hidden.Kill($true); $hidden.WaitForExit() }
    $hidden.Dispose()
  }

  # Independent contender, not a child claiming the same budget.
  $lease = Enter-HostExecutionLease -Role COMSOL -Stage solver -RunId 'test-listed-heavy'
  $quotedSource = $leaseSource.Replace("'", "''")
  $quotedState = $statePath.Replace("'", "''")
  $childProgress = Join-Path $testRoot 'contender-progress.txt'
  $quotedChildProgress = $childProgress.Replace("'", "''")
  $childError = Join-Path $testRoot 'contender-error.txt'
  $quotedChildError = $childError.Replace("'", "''")
  $childCode = @"
trap { [IO.File]::WriteAllText('$quotedChildError', `$_.Exception.ToString()); exit 1 }
. '$quotedSource'
`$realTransaction = `${function:Invoke-HostResourceTransaction}
function Invoke-HostResourceTransaction {
  param([hashtable]`$Request,[string]`$StatePath)
  `$watch = [Diagnostics.Stopwatch]::StartNew()
  [IO.File]::AppendAllText('$quotedChildProgress', ([DateTime]::UtcNow.ToString('O') + ' transaction-start ' + `$Request.operation + "`n"))
  try { & `$realTransaction -Request `$Request -StatePath `$StatePath }
  finally {
    [IO.File]::AppendAllText('$quotedChildProgress', ([DateTime]::UtcNow.ToString('O') + ' transaction-end ' + `$Request.operation + ' elapsed_ms=' + `$watch.ElapsedMilliseconds + "`n"))
  }
}
Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID -ErrorAction SilentlyContinue
`$real = `${function:Get-HostResourceSnapshot}
`$script:contenderSnapshot = `$null
function Get-HostResourceSnapshot {
  if (`$null -eq `$script:contenderSnapshot) {
    [IO.File]::AppendAllText('$quotedChildProgress', ([DateTime]::UtcNow.ToString('O') + " process-snapshot-start`n"))
    `$s = & `$real
    [IO.File]::AppendAllText('$quotedChildProgress', ([DateTime]::UtcNow.ToString('O') + " process-snapshot-complete`n"))
    # This exclusion test needs the two actual owners, not four repeated CIM
    # scans of unrelated host processes. Keep their real console descendants.
    `$owners = @(`$s.processes | Where-Object { `$_.pid -in @($PID, `$PID) })
    if (`$owners.Count -ne 2) { throw 'Contender snapshot did not discover both real fixture owners.' }
    `$s.processes = @(`$owners) + @(`$s.processes | Where-Object {
      `$_.parent_pid -in @($PID, `$PID) -and `$_.is_system_console_host
    })
    `$s.unknown_process_ids = @(); `$s.definitely_exited_process_ids = @()
    `$script:contenderSnapshot = `$s
  }
  `$s = `$script:contenderSnapshot.Clone()
  foreach (`$row in `$s.processes) {
    `$nativeStarted = Get-HostResourceNativeProcessCreationTicks -ProcessId `$row.pid
    # CIM creation dates truncate to microseconds; use the same one-quantum
    # identity boundary as Wait-HostResourceProcess, preserving the ledger identity.
    if ([string]::IsNullOrWhiteSpace([string]`$nativeStarted) -or
        [Math]::Abs([int64]`$nativeStarted - [int64]`$row.started) -ge 10) {
      throw ("A real contender fixture process changed identity or exited: pid=" + `$row.pid +
        ' snapshot_started=' + `$row.started + ' native_started=' + `$nativeStarted)
    }
  }
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
  try {
    $childFinished = $child.WaitForExit(30000)
    $childFailure = if (Test-Path -LiteralPath $childError) { Get-Content -LiteralPath $childError -Raw } else { '' }
    $childStages = if (Test-Path -LiteralPath $childProgress) { Get-Content -LiteralPath $childProgress -Raw } else { 'not-started' }
    Write-Output "CONTENDER_FIXTURE_STAGES=$childStages"
    Assert-True $childFinished "Isolated contender did not finish. Stages: $childStages Error: $childFailure"
    Assert-True ($child.ExitCode -eq 0) "Isolated contender failed: $childFailure Stages: $childStages"
  } finally {
    # Reap this exact fixture tree before the outer cleanup removes its ledger.
    if (-not $child.HasExited) { $child.Kill($true) }
    $child.WaitForExit()
    $child.Dispose()
  }
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
