[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Equal {
  param(
    [Parameter(Mandatory)][object]$Actual,
    [Parameter(Mandatory)][object]$Expected,
    [Parameter(Mandatory)][string]$Message
  )
  if ($Actual -ne $Expected) {
    throw "$Message Expected='$Expected' Actual='$Actual'"
  }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$projectRoot = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("run_artifact_support_" + [guid]::NewGuid().ToString('N'))
$executionRoot = Join-Path 'C:\tmp\ms' ("run_artifact_support_" + [guid]::NewGuid().ToString('N'))
$originalPythonPath=[Environment]::GetEnvironmentVariable('PYTHONPATH')
$originalNoUserSite=[Environment]::GetEnvironmentVariable('PYTHONNOUSERSITE')

$hostEnvironment=@{}
foreach($name in @('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','SIMULATION_PYTHON_EXE')) {
  $hostEnvironment[$name]=[Environment]::GetEnvironmentVariable($name,'Process')
}
try {
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN=''
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $testRoot 'host.sqlite3'
  $env:SIMULATION_PYTHON_EXE=$python
  . (Join-Path $PSScriptRoot 'run_artifact_support.ps1')
  & {
    # Exercise native Python streams/exit status, with capacity mutation stubbed.
    function Invoke-RunToolRootContext { param($RepoRoot,$Operation) & $Operation }
    function Invoke-ArtifactCapacityGate { return [pscustomobject]@{satisfied_after_apply=$true} }
    $leaseFixturePythonExe=$python
    $script:leaseFixtureCode='import json;print(json.dumps({"lease_id":"fixture"}))'
    function Invoke-LeaseFixturePython {
      param([Parameter(ValueFromRemainingArguments)]$NativeArguments)
      if('--delete-protection-lease'-in$NativeArguments){$global:LASTEXITCODE=0;return}
      if('--output-list-json'-in$NativeArguments){
        $script:writerListPath=$NativeArguments[([array]::IndexOf($NativeArguments,'--output-list-json')+1)]
        if(-not(Test-Path -LiteralPath $script:writerListPath)){throw 'Writer list missing before launch.'}
        $script:writerList=ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($script:writerListPath)) -NoEnumerate
      }
      & $leaseFixturePythonExe -c $script:leaseFixtureCode
      $global:LASTEXITCODE=$LASTEXITCODE
    }
    $session=Enter-ArtifactWorkflowCapacitySession -Python Invoke-LeaseFixturePython -RepoRoot $repoRoot `
      -ArtifactRoot $testRoot -RunDirectory $testRoot -CommittedNewBytes 0
    Assert-Equal $session.lease.lease_id 'fixture' 'Successful lease JSON protocol must remain separate from diagnostics.'
    $script:leaseFixtureCode='import sys;print("diagnostic stdout");print("specific native stderr",file=sys.stderr);sys.exit(23)'
    $message=$null
    try{Enter-ArtifactWorkflowCapacitySession -Python Invoke-LeaseFixturePython -RepoRoot $repoRoot `
      -ArtifactRoot $testRoot -RunDirectory $testRoot -CommittedNewBytes 0|Out-Null}catch{$message=$_.Exception.Message}
    foreach($part in @('exit_code=23','stdout=diagnostic stdout','stderr=specific native stderr')){
      if(-not$message.Contains($part)){throw "Native lease failure lost its actual diagnostic: $part; got=$message"}
    }
    $script:leaseFixtureCode='import sys;print("x"*10000);print("y"*10000,file=sys.stderr);sys.exit(24)'
    try{Enter-ArtifactWorkflowCapacitySession -Python Invoke-LeaseFixturePython -RepoRoot $repoRoot `
      -ArtifactRoot $testRoot -RunDirectory $testRoot -CommittedNewBytes 0|Out-Null}catch{$message=$_.Exception.Message}
    if(-not$message.Contains('exit_code=24')-or-not$message.Contains('[truncated tail]')-or$message.Length-gt8400){
      throw 'Native lease failure must retain its exit status with bounded stream diagnostics.'
    }
    $script:leaseFixtureCode='print("RUN_MANIFEST=PASS PATH=fixture.json")'
    $writerResult=@(Write-RunManifest -Python Invoke-LeaseFixturePython -RepoRoot $repoRoot -RunConfig unused.json -Status checkpoint -PassThru)
    Assert-Equal $writerResult.Count 1 'Successful manifest writer stdout shape changed.'
    Assert-Equal $writerResult[0] 'RUN_MANIFEST=PASS PATH=fixture.json' 'Successful manifest writer protocol changed.'
    Assert-Equal $script:writerList.Count 0 'Empty outputs must be a JSON array.'
    Assert-Equal (Test-Path -LiteralPath $script:writerListPath) $false 'Successful writer must remove its temporary list.'
    $script:leaseFixtureCode='import sys;print("writer diagnostic stdout");print("specific writer stderr",file=sys.stderr);sys.exit(31)'
    try{Write-RunManifest -Python Invoke-LeaseFixturePython -RepoRoot $repoRoot -RunConfig unused.json -Status checkpoint|Out-Null}catch{$message=$_.Exception.Message}
    foreach($part in @('status checkpoint','exit_code=31','stdout=writer diagnostic stdout','stderr=specific writer stderr')){
      if(-not$message.Contains($part)){throw "Manifest failure lost its native diagnostic: $part; got=$message"}
    }
    Assert-Equal (Test-Path -LiteralPath $script:writerListPath) $false 'Failed writer must remove its temporary list.'
    $script:leaseFixtureCode='import sys;print("x"*10000);print("y"*10000,file=sys.stderr);sys.exit(32)'
    try{Write-RunManifest -Python Invoke-LeaseFixturePython -RepoRoot $repoRoot -RunConfig unused.json -Status checkpoint|Out-Null}catch{$message=$_.Exception.Message}
    if(-not$message.Contains('exit_code=32')-or-not$message.Contains('[truncated tail]')-or$message.Length-gt8400){
      throw 'Manifest writer failure must retain exit status and bounded native diagnostics.'
    }
  }
  & {
    # Exercise the real wrapper under StrictMode without any capacity mutation.
    function Enter-HostExecutionLease { return [pscustomobject]@{} }
    function Exit-HostExecutionLease { param($Lease) }
    $maintenanceSatisfied=$false
    function Invoke-RunToolRootContext {
      return (@{satisfied_after_apply=$maintenanceSatisfied;execution_mode='maintenance';
        resident_bytes=700;free_bytes=200;capacity_gap_bytes=100;target_bytes=600;
        removed=@{object_count=1;bytes=28}}|ConvertTo-Json)
    }
    $message=$null
    try {
      Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot -ExecutionMode maintenance
    } catch { $message=$_.Exception.Message }
    Assert-Equal $message 'Artifact capacity gate blocked maintenance: CAPACITY_TARGET_NOT_MET; resident_bytes=700; free_bytes=200; capacity_gap_bytes=100; target_bytes=600; removed_bytes=28' `
      'Maintenance must consume its compact CLI receipt, not missing detailed/startup fields.'
    $maintenanceSatisfied=$true
    $maintenanceReceipt=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
      -ArtifactRoot $testRoot -ExecutionMode maintenance
    Assert-Equal $maintenanceReceipt.satisfied_after_apply $true 'Satisfied compact maintenance receipt must pass.'
    Assert-Equal $maintenanceReceipt.removed.bytes 28 'Maintenance must retain the aggregate removal count.'
  }
  $originalLocation=(Get-Location).Path
  & {
    # Real renewal/gate functions with only external I/O stubbed; no live lease mutation.
    function Enter-HostExecutionLease { return [pscustomobject]@{} }
    function Exit-HostExecutionLease { param($Lease) }
    $satisfied=$true
    function Invoke-RunToolRootContext {
      $script:renewalFixtureCalls++
      return (@{satisfied_after_apply=$satisfied;blocking_reason='TARGET_CAPACITY_EXCEEDED';
        resident_bytes=700;total_active_lease_committed_new_bytes=11;projected_bytes=711;
        target_bytes=600;required_free_bytes=300;free_bytes_before=200}|ConvertTo-Json)
    }
    $cases=@(@{keys=@();paths=@()},@{keys=@(('a'*64));paths=@('one')},
      @{keys=@(('a'*64),('b'*64));paths=@('one','two')})
    foreach($case in $cases){
      $session=[pscustomobject]@{status='active';artifact_root=$testRoot;lease_id='fixture';owner='fixture';
        lease_ttl_seconds=60;committed_new_bytes=10;protected_paths=@($case.paths);protected_cache_keys=@($case.keys)}
      $script:renewalFixtureCalls=0
      $first=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $session `
        -ProtectedPaths $case.paths -ProtectedCacheKeys $case.keys
      $second=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $first.session
      $raised=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $second.session `
        -RemainingCommittedNewBytes 11
      foreach($name in @('protected_paths','protected_cache_keys')){
        Assert-Equal ($raised.session.$name-is[Array]) $true 'Renewal must preserve an array, including empty/singleton.'
      }
      Assert-Equal $raised.session.protected_cache_keys.Count $case.keys.Count 'Renewal must not manufacture null keys or retain duplicates.'
      Assert-Equal $raised.session.protected_paths.Count $case.paths.Count 'Renewal must not manufacture null paths or retain duplicates.'
      Assert-Equal ($raised.session.protected_cache_keys-join',') ($case.keys-join',') 'Renewal cache identities changed.'
      Assert-Equal $raised.session.committed_new_bytes 11 'Raised reservation was not retained.'
      Assert-Equal $script:renewalFixtureCalls 4 'Two renewals and raised commitment must call the real re-admission gate.'
      Assert-Equal $raised.admission_gate.satisfied_after_apply $true 'Raised commitment did not reach admission.'
    }
    $satisfied=$false
    $session=[pscustomobject]@{status='active';artifact_root=$testRoot;lease_id='fixture';owner='fixture';
      lease_ttl_seconds=60;committed_new_bytes=10;protected_paths=@();protected_cache_keys=@();capacity_threshold_action='warn'}
    $message=$null
    try{Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $session `
      -RemainingCommittedNewBytes 11|Out-Null}catch{$message=$_.Exception.Message}
    if($message-notlike 'Artifact capacity gate blocked startup: TARGET_CAPACITY_EXCEEDED;*'){
      throw 'An old warning session must not bypass hard re-admission.'
    }
    Assert-Equal $session.committed_new_bytes 11 'Failed re-admission must retain the increased reservation.'
    $session.PSObject.Properties.Remove('capacity_threshold_action')
    $message=$null
    try{Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $session `
      -RemainingCommittedNewBytes 12|Out-Null}catch{$message=$_.Exception.Message}
    if($message-notlike 'Artifact capacity gate blocked startup: TARGET_CAPACITY_EXCEEDED;*'){
      throw 'Capacity re-admission must reject the unsatisfied receipt.'
    }
    $session.protected_cache_keys=@('not-a-sha256-key')
    $message=$null
    try{Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $session `
      -RemainingCommittedNewBytes 13|Out-Null}catch{$message=$_.Exception.Message}
    Assert-Equal $message 'Protected cache key must be one SHA-256 key.' 'Array preservation must not accept malformed cache keys.'
  }
  & {
    # Exercise only wrapper decisions: no reconciler, disk mutation or host admission.
    function Enter-HostExecutionLease { return [pscustomobject]@{} }
    function Exit-HostExecutionLease { param($Lease) }
    $fakeReceipt=[ordered]@{satisfied_after_apply=$false;blocking_reason='TARGET_CAPACITY_EXCEEDED';
      resident_bytes=700;total_active_lease_committed_new_bytes=4;projected_bytes=704;
      target_bytes=600;required_free_bytes=299;free_bytes_before=200}
    function Invoke-RunToolRootContext { return ($fakeReceipt|ConvertTo-Json) }
    foreach($reason in @('TARGET_CAPACITY_EXCEEDED','MINIMUM_FREE_CAPACITY_UNAVAILABLE')){
      $fakeReceipt.blocking_reason=$reason
      $message=$null
      try { Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
        -CapacityProtectionLeaseId fixture|Out-Null } catch {$message=$_.Exception.Message}
      if($message-notlike "Artifact capacity gate blocked startup: $reason;*"){throw 'Capacity thresholds must block startup.'}
      $rejected=$false
      try{Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
        -CapacityProtectionLeaseId fixture -CapacityThresholdAction warn|Out-Null}catch{$rejected=$true}
      Assert-Equal $rejected $true 'Removed warning override must be rejected, not reopen unsafe admission.'
    }
    foreach($reason in @('CAPACITY_LEDGER_REQUIRED','CURRENT_LEASE_REQUIRED','ACTIVE_LEASE_COMMITMENT_UNKNOWN',
      'WRITING_RECOVERY_REVIEW_OVERDUE','CURRENT_LEASE_SCOPE_INCOMPLETE','SAFETY_DECISION_UNAVAILABLE','UNSPECIFIED')){
      $fakeReceipt.blocking_reason=$reason
      $message=$null
      try { Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
        -CapacityProtectionLeaseId fixture|Out-Null } catch {$message=$_.Exception.Message}
      if($message-notlike "Artifact capacity gate blocked startup: $reason;*"){throw 'Capacity gate must reject invalid safety decisions.'}
    }
    $fakeReceipt.blocking_reason='MINIMUM_FREE_CAPACITY_UNAVAILABLE'
    function Invoke-RunToolRootContext {
      $script:capacityStartupTestCalls++
      if($script:capacityStartupTestCalls-eq1){return '{"lease_id":"fixture"}'}
      if($script:capacityStartupTestCalls-eq2){return ($fakeReceipt|ConvertTo-Json)}
      return '{"deleted":true}'
    }
    $script:capacityStartupTestCalls=0
    $message=$null
    try{Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
      -RunDirectory $testRoot -CommittedNewBytes 4|Out-Null}catch{$message=$_.Exception.Message}
    if($message-notlike 'Artifact capacity gate blocked startup: MINIMUM_FREE_CAPACITY_UNAVAILABLE;*'){
      throw 'Unsatisfied startup must not publish an active workflow session.'
    }
    Assert-Equal $script:capacityStartupTestCalls 3 'Rejected startup must release its provisional capacity lease.'
    $fakeReceipt.satisfied_after_apply=$true
    $script:capacityStartupTestCalls=0
    $session=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
      -RunDirectory $testRoot -CommittedNewBytes 4
    Assert-Equal $session.startup_gate.satisfied_after_apply $true 'Satisfied startup must publish its actual successful gate.'
    Assert-Equal ($null-eq$session.PSObject.Properties['capacity_threshold_action']) $true 'New session must not record a retired warning policy.'
    $released=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $session
    Assert-Equal $released.deleted $true 'Satisfied session must use normal lease release.'
    function Invoke-RunToolRootContext { throw 'fixture Python failure' }
    $message=$null
    try { Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
      -CapacityProtectionLeaseId fixture|Out-Null } catch {$message=$_.Exception.Message}
    Assert-Equal $message 'fixture Python failure' 'Capacity gate must not swallow command failure.'
    function Invoke-RunToolRootContext { return 'invalid JSON' }
    $failed=$false
    try { Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
      -CapacityProtectionLeaseId fixture|Out-Null } catch {$failed=$true}
    Assert-Equal $failed $true 'Capacity gate must reject damaged receipt.'
  }
  [Environment]::SetEnvironmentVariable('PYTHONPATH','run-artifact-test-pythonpath')
  [Environment]::SetEnvironmentVariable('PYTHONNOUSERSITE','run-artifact-test-nousersite')
  $context=Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    [pscustomobject]@{
      location=(Get-Location).Path
      python_path=$env:PYTHONPATH
      no_user_site=$env:PYTHONNOUSERSITE
    }
  }
  Assert-Equal $context.location $repoRoot 'Tool context did not use RepoRoot.'
  Assert-Equal $context.python_path $repoRoot 'Tool context did not bind PYTHONPATH.'
  Assert-Equal $context.no_user_site '1' 'Tool context did not disable user site.'
  Assert-Equal (Get-Location).Path $originalLocation 'Tool context did not restore location.'
  Assert-Equal ([Environment]::GetEnvironmentVariable('PYTHONPATH')) 'run-artifact-test-pythonpath' `
    'Tool context did not restore PYTHONPATH.'
  Assert-Equal ([Environment]::GetEnvironmentVariable('PYTHONNOUSERSITE')) 'run-artifact-test-nousersite' `
    'Tool context did not restore PYTHONNOUSERSITE.'

  $governedRoot=Join-Path $testRoot 'artifacts'
  $governedProjectRoot=Join-Path $governedRoot 'projects\fixture_project'
  foreach($badArtifactRoot in @((Join-Path $governedProjectRoot 'runs'),(Join-Path $governedRoot 'projects\wrong_project'),$governedRoot)){
    $badRunId='20260723_165956__test__cross__wrong-artifact-root__n1'
    $message=$null
    try{
      New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $badArtifactRoot `
        -RunId $badRunId -Project fixture_project -Mode contract_test -Software @('contract test') `
        -RetentionContractEnabled -CapacityLedgerLifecycleEnabled|Out-Null
    }catch{$message=$_.Exception.Message}
    if(-not$message-or-not$message.Contains('ArtifactRoot must be the canonical artifacts/projects/<Project>')){
      throw "Wrong ArtifactRoot was not rejected before creation: $badArtifactRoot; $message"
    }
    if(Test-Path -LiteralPath (Join-Path $badArtifactRoot ('runs/'+$badRunId))){
      throw 'Rejected ArtifactRoot created an ungoverned nested run.'
    }
  }
  $prewriteRun=Join-Path $governedProjectRoot 'runs\20260723_165959__test__cross__prewrite-rejected__n1'
  try {
    New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $governedProjectRoot `
      -RunId '20260723_165959__test__cross__prewrite-rejected__n1' -Project fixture_project `
      -Mode contract_test -Software @('contract test') | Out-Null
    throw 'Expected governed pre-write lifecycle rejection did not occur.'
  } catch {
    if ($_.Exception.Message -notmatch 'require retention and capacity-ledger lifecycle') { throw }
  }
  if(Test-Path -LiteralPath $prewriteRun){throw 'Governed pre-write rejection created an unmanaged run range.'}
  New-Item -ItemType Directory -Path $governedProjectRoot -Force|Out-Null
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -c "from pathlib import Path; from common.contracts import capacity_ledger; import sys; capacity_ledger.initialize_capacity_ledger(Path(sys.argv[1]), objects=[])" $governedRoot
    if($LASTEXITCODE-ne0){throw 'Governed pre-write ledger fixture initialization failed.'}
  } | Out-Null
  $governedPackage=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $governedProjectRoot `
    -RunId '20260723_165958__test__cross__prewrite-registered__n1' -Project fixture_project `
    -Mode contract_test -Software @('contract test') -RetentionContractEnabled -RetentionClass compact `
    -CapacityLedgerLifecycleEnabled
  $governedLedger=Get-Content -LiteralPath (Join-Path $governedRoot 'common\capacity_ledger.json') -Raw|ConvertFrom-Json
  $governedEntry=@($governedLedger.objects|Where-Object {$_.path -eq 'projects/fixture_project/runs/20260723_165958__test__cross__prewrite-registered__n1'})
  Assert-Equal $governedEntry.Count 1 'Governed package must retain exactly one registered run range.'
  Assert-Equal $governedEntry[0].status 'writing' 'Governed package range must remain writing after initialization.'
  Assert-Equal $governedEntry[0].recovery_reason 'run_manifest_not_terminal' 'Initialization must replace the pre-write recovery reason.'
  $legacyGovernedDir=Join-Path $governedProjectRoot 'runs\20260723_165957__test__cross__legacy-initialize-rejected__n1'
  New-Item -ItemType Directory -Path $legacyGovernedDir -Force|Out-Null
  try {
    Initialize-RunRecord -RunDir $legacyGovernedDir `
      -RunId (Split-Path -Leaf $legacyGovernedDir) -Project fixture_project -Mode contract_test `
      -ProjectRoot $projectRoot -RepoRoot $repoRoot -Python $python `
      -ProvisionalSummaryRole 'fixture_provisional_summary' -TerminalSummaryRole 'fixture_terminal_summary'
    throw 'Expected direct governed Initialize-RunRecord rejection did not occur.'
  } catch {
    if ($_.Exception.Message -notmatch 'cannot create a run beneath artifacts') { throw }
  }
  if(Test-Path -LiteralPath (Join-Path $legacyGovernedDir 'run_config.json')){
    throw 'Rejected governed Initialize-RunRecord wrote a config before lifecycle registration.'
  }

  $capacityRoot=Join-Path $testRoot 'capacity_artifacts'
  New-Item -ItemType Directory -Path $capacityRoot -Force|Out-Null
  New-Item -ItemType Directory -Path (Join-Path $capacityRoot 'projects') -Force|Out-Null
  New-Item -ItemType Directory -Path (Join-Path $capacityRoot 'common') -Force|Out-Null
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -c "from pathlib import Path; from common.contracts import capacity_ledger; import sys; capacity_ledger.initialize_capacity_ledger(Path(sys.argv[1]), objects=[])" $capacityRoot
    if($LASTEXITCODE-ne0){throw 'Capacity ledger fixture initialization failed.'}
  } | Out-Null
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -m common.contracts.reconcile_artifact_capacity `
      --artifact-root $capacityRoot --create-protection-lease test-capacity `
      --lease-owner run-artifact-support --lease-ttl-seconds 3600 --protect-path projects
    if($LASTEXITCODE-ne 0){throw 'Capacity protection lease fixture creation failed.'}
  } | Out-Null
  # Read the actual CLI decision even when this host has less free space than
  # policy requires, then prove the production wrapper enforces that decision.
  $capacityTestLease=Enter-HostExecutionLease -Role GATE
  try{
    $capacityOutput=@(Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -m common.contracts.reconcile_artifact_capacity --artifact-root $capacityRoot `
        --execution-mode startup --capacity-protection-lease-id test-capacity --apply
      if($LASTEXITCODE-ne0){throw 'Capacity CLI fixture failed.'}
    })
  }finally{Exit-HostExecutionLease -Lease $capacityTestLease}
  $capacityReceipt=($capacityOutput-join"`n")|ConvertFrom-Json
  Assert-Equal $capacityReceipt.role 'artifact_capacity_gate' 'Capacity gate role changed.'
  # Temporary empty ledger does not imply the real volume has enough free space.
  $expectedSatisfied=($capacityReceipt.free_bytes_before-ge$capacityReceipt.required_free_bytes-and
    $capacityReceipt.projected_bytes-le$capacityReceipt.target_bytes)
  Assert-Equal $capacityReceipt.satisfied_after_apply $expectedSatisfied `
    'Capacity gate must report the actual volume decision, not assume fixture free space.'
  $policy=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'artifact_capacity_policy.json') -Raw |
    ConvertFrom-Json
  Assert-Equal $capacityReceipt.target_bytes ([int64]$policy.target_gib * 1GB) `
    'Omitted target must use the shared capacity policy.'
  Assert-Equal $capacityReceipt.minimum_free_bytes ([int64]$policy.minimum_free_gib * 1GB) `
    'Minimum-free watermark must come from the shared capacity policy.'
  Assert-Equal $capacityReceipt.measurement_mode 'STARTUP_LEDGER' `
    'Capacity gate startup did not use the ledger path.'
  $capacityRejected=$false
  try{Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $capacityRoot -CapacityProtectionLeaseId test-capacity|Out-Null}catch{
    if($_.Exception.Message-notlike 'Artifact capacity gate blocked startup:*'){throw}
    $capacityRejected=$true
  }
  Assert-Equal $capacityRejected (-not$expectedSatisfied) 'Wrapper must block the real unsatisfied CLI capacity decision.'

  $interruptedDir = Join-Path $testRoot '20260723_170001__test__cross__lifecycle-interrupted__n100'
  New-Item -ItemType Directory -Path $interruptedDir -Force | Out-Null
  Initialize-RunRecord -RunDir $interruptedDir `
    -RunId (Split-Path -Leaf $interruptedDir) -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
    -ProjectRoot $projectRoot -RepoRoot $repoRoot -Python $python `
    -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
    -TerminalSummaryRole 'oa_tof_terminal_run_summary'

  $config = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_config.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $summary = Get-Content -LiteralPath (Join-Path $interruptedDir 'summary.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $manifest = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $config.project_root $projectRoot 'Initialize-RunRecord changed project_root.'
  Assert-Equal $summary.role 'oa_tof_provisional_run_summary' 'Initialization summary role changed.'
  Assert-Equal $summary.status 'checkpoint' 'Initialization summary status changed.'
  Assert-Equal $summary.reason 'Run package initialized; task-specific inputs are not frozen yet.' 'Initialization reason changed.'
  Assert-Equal $manifest.status 'checkpoint' 'Initialization manifest status changed.'
  Assert-Equal @($manifest.outputs).Count 1 'Initialization manifest must record summary.json.'
  Assert-Equal (Split-Path -Leaf $manifest.outputs[0].path) 'summary.json' `
    'Initialization manifest output path changed.'

  Write-TerminalRunRecord -RunDir $interruptedDir -Status failed `
    -Reason 'synthetic failure' -RepoRoot $repoRoot -Python $python `
    -SummaryRole 'oa_tof_terminal_run_summary'
  $failedSummary = Get-Content -LiteralPath (Join-Path $interruptedDir 'summary.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $failedManifest = Get-Content -LiteralPath (Join-Path $interruptedDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $failedSummary.status 'failed' 'Failed summary status changed.'
  Assert-Equal $failedSummary.reason 'synthetic failure' 'Failed summary reason changed.'
  Assert-Equal $failedManifest.status 'failed' 'Failed manifest status changed.'

  $v2FailedDir = Join-Path (Join-Path $testRoot 'runs') '20260723_170004__test__cross__native-grid-failure__n1'
  New-Item -ItemType Directory -Path (Join-Path $v2FailedDir 'simion') -Force | Out-Null
  $v2Config = Join-Path $v2FailedDir 'run_config.json'
  $v2Summary = Join-Path $v2FailedDir 'summary.json'
  Write-RunJson -Path $v2Config -Value ([ordered]@{
    schema_version=2;run_id=(Split-Path -Leaf $v2FailedDir);project='single_reflection_oa_tof_mass_analyzer'
    mode='native_ideal_grid_smoke';project_root=$repoRoot;inputs=[ordered]@{}
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
  })
  'synthetic builder failure' | Set-Content -LiteralPath (Join-Path $v2FailedDir 'simion\accelerator_builder.stderr.log') -Encoding UTF8
  Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $v2Config -Summary $v2Summary `
    -SummaryRole 'oa_tof_native_ideal_grid_smoke_summary' -SummarySchemaVersion 2 `
    -Reason 'grid2 electrode has zero raw PA points' -FailureClass 'native_ideal_grid_smoke_failed' `
    -FailureStage 'accelerator_raw_pa_family_or_grid_row_audit' -ThresholdResultEligible $false `
    -AdditionalSummaryProperties ([ordered]@{cache_policy='require_existing';snapshot_completed=$false}) `
    -Software @('synthetic SIMION')
  $v2FailedSummary = Get-Content -LiteralPath $v2Summary -Raw -Encoding UTF8 | ConvertFrom-Json
  $v2FailedManifest = Get-Content -LiteralPath (Join-Path $v2FailedDir 'run_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $v2FailedSummary.schema_version 2 'Failed native-grid summary schema changed.'
  Assert-Equal $v2FailedSummary.failure_stage 'accelerator_raw_pa_family_or_grid_row_audit' 'Failed native-grid stage changed.'
  Assert-Equal $v2FailedSummary.threshold_result_eligible $false 'Failed native-grid result became threshold eligible.'
  Assert-Equal $v2FailedSummary.cache_policy 'require_existing' 'Additional failed summary property changed.'
  Assert-Equal $v2FailedSummary.snapshot_completed $false 'Pre-snapshot failure flag changed.'
  Assert-Equal $v2FailedManifest.status 'failed' 'Failed native-grid manifest status changed.'
  Assert-Equal $v2FailedManifest.artifact_retention.class 'compact' 'Failed native-grid retention changed.'
  $v2SummaryOutput = @($v2FailedManifest.outputs | Where-Object {
    [IO.Path]::GetFullPath([string]$_.path).Equals(
      [IO.Path]::GetFullPath($v2Summary), [StringComparison]::OrdinalIgnoreCase
    )
  })
  Assert-Equal $v2SummaryOutput.Count 1 'Failed summary manifest output changed.'
  Assert-Equal $v2SummaryOutput[0].sha256 `
    (Get-FileHash -LiteralPath $v2Summary -Algorithm SHA256).Hash `
    'Failed summary manifest SHA differs from final summary.'
  Assert-Equal ([int64]$v2SummaryOutput[0].bytes) `
    ([int64](Get-Item -LiteralPath $v2Summary).Length) `
    'Failed summary manifest bytes differ from final summary.'

  $preservedDir = Join-Path (Join-Path $testRoot 'runs') '20260723_170005__test__cross__natural-trace-failure__n1'
  New-Item -ItemType Directory -Path (Join-Path $preservedDir 'logs') -Force | Out-Null
  $preservedConfig = Join-Path $preservedDir 'run_config.json'
  $preservedSummary = Join-Path $preservedDir 'summary.json'
  $preservedTrace = Join-Path $preservedDir 'logs\simion__batch01.trace.log'
  $incompleteTrace = Join-Path $preservedDir 'logs\simion__batch02.trace.log'
  New-Item -ItemType Directory -Path (Join-Path $preservedDir 'simion') -Force | Out-Null
  Write-RunJson -Path $preservedConfig -Value ([ordered]@{
    schema_version=2;run_id=(Split-Path -Leaf $preservedDir);project='single_reflection_oa_tof_mass_analyzer'
    mode='natural_trace_fixture';project_root=$repoRoot;inputs=[ordered]@{}
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
  })
  @('native RF trace fixture','status,Fly completed.') | Set-Content -LiteralPath $preservedTrace -Encoding UTF8
  'incomplete native RF trace fixture' | Set-Content -LiteralPath $incompleteTrace -Encoding UTF8
  'solver-native PA fixture' | Set-Content -LiteralPath (Join-Path $preservedDir 'simion\frontend.pa0') -Encoding UTF8
  Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $preservedConfig -Summary $preservedSummary `
    -SummaryRole 'natural_trace_fixture_summary' -Reason 'materializer fixture failure' `
    -Software @('contract test') -AdditionalOutputs @($preservedTrace) -PreserveRawOutputs `
    -PreserveRawOutputPaths @($preservedTrace)
  Assert-Equal (Test-Path -LiteralPath $preservedTrace -PathType Leaf) $true `
    'Failed natural-trajectory materialization must preserve its raw trace for recovery.'
  Assert-Equal (Test-Path -LiteralPath $incompleteTrace -PathType Leaf) $false `
    'Failed natural-trajectory retention must remove an incomplete raw trace.'
  $preservedManifest = Get-Content -LiteralPath (Join-Path $preservedDir 'run_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal @($preservedManifest.outputs | Where-Object { $_.path -eq $preservedTrace }).Count 1 `
    'Failed natural-trajectory manifest must retain the recoverable trace.'
  Assert-Equal (Test-Path -LiteralPath (Join-Path $preservedDir 'simion\frontend.pa0')) $false `
    'Failed natural-trajectory retention must remove solver-native PA files.'
  Assert-Equal (Test-Path -LiteralPath (Join-Path $preservedDir 'retention_actions.json')) $true `
    'Failed natural-trajectory retention must record its removal action.'

  $fullFlightDir = Join-Path (Join-Path $testRoot 'runs') `
    '20260723_170006__test__cross__full-flight-stdout-failure__n1'
  New-Item -ItemType Directory -Path (Join-Path $fullFlightDir 'logs') -Force | Out-Null
  $fullFlightConfig = Join-Path $fullFlightDir 'run_config.json'
  $fullFlightSummary = Join-Path $fullFlightDir 'summary.json'
  $fullFlightStdout = Join-Path $fullFlightDir 'logs\simion__batch01.stdout.log'
  Write-RunJson -Path $fullFlightConfig -Value ([ordered]@{
    schema_version=2;run_id=(Split-Path -Leaf $fullFlightDir);project='single_reflection_oa_tof_mass_analyzer'
    mode='full_flight_stdout_fixture';project_root=$repoRoot;inputs=[ordered]@{}
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
  })
  @('TRACE: source_release ion=1 particle_id=1 fixture=1',
    'TRACE: handoff_terminal_raw ion=1 fixture=1',
    'status,Fly completed. 1 splats, 1 seconds') |
    Set-Content -LiteralPath $fullFlightStdout -Encoding UTF8
  Complete-FailedRun -Python $python -RepoRoot $repoRoot `
    -RunConfig $fullFlightConfig -Summary $fullFlightSummary `
    -SummaryRole 'full_flight_stdout_fixture_summary' -Reason 'analysis fixture failure' `
    -Software @('contract test') -AdditionalOutputs @($fullFlightStdout) `
    -PreserveRawOutputs -PreserveRawOutputPaths @($fullFlightStdout)
  Assert-Equal (Test-Path -LiteralPath $fullFlightStdout -PathType Leaf) $true `
    'Failed full-flight analysis must preserve completed native stdout.'
  $fullFlightManifest = Get-Content -LiteralPath (Join-Path $fullFlightDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $fullFlightManifest.status 'failed' `
    'Completed full-flight stdout failed publication status differs.'
  Assert-Equal @($fullFlightManifest.outputs | Where-Object {
    $_.path -eq $fullFlightStdout
  }).Count 1 'Failed full-flight manifest must retain completed stdout.'

  $successDir = Join-Path $testRoot '20260723_170002__test__cross__lifecycle-success__n100'
  New-Item -ItemType Directory -Path $successDir -Force | Out-Null
  $successConfig = Join-Path $successDir 'run_config.json'
  $successSummary = Join-Path $successDir 'summary.json'
  Write-RunJson -Path $successConfig -Value ([ordered]@{
    schema_version=1;run_id=(Split-Path -Leaf $successDir);project='single_reflection_oa_tof_mass_analyzer'
    mode='contract_test';project_root=$projectRoot;inputs=[ordered]@{}
  })
  Write-RunJson -Path $successSummary -Value ([ordered]@{
    schema_version=1;role='oa_tof_contract_test_summary';status='success'
  })
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
    -RunConfig $successConfig -Status success -Outputs @($successSummary)
  $successManifest = Get-Content -LiteralPath (Join-Path $successDir 'run_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal $successManifest.status 'success' 'Success manifest status changed.'

  $budgetPackage=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
    -RunId '20260723_170003__test__cross__resource-budget__n100' `
    -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
    -Software @('contract test') -RetentionContractEnabled -RetentionClass compact
  $usagePath=Join-Path $budgetPackage.result_dir 'resource_usage.json'
  Write-RunJson -Path $usagePath -Value ([ordered]@{
    schema_version=1;role='multipole_resource_usage';status='running'
    failure_class=$null;limit_name='wall_clock_seconds'
    peak_run_directory_bytes=0;final_retained_bytes=$null
    limits=[ordered]@{compact_final_retained_bytes=26214400}
  })
  Complete-FailedRun -Python $python -RepoRoot $repoRoot `
    -RunConfig $budgetPackage.run_config -Summary $budgetPackage.summary `
    -SummaryRole 'resource_budget_test_summary' -Reason 'wall clock exceeded' `
    -Software @('contract test') -Status interrupted `
    -FailureClass resource_budget_exceeded -ResourceUsagePath $usagePath
  $budgetSummary=Get-Content -LiteralPath $budgetPackage.summary -Raw|ConvertFrom-Json
  $budgetManifest=Get-Content -LiteralPath (Join-Path $budgetPackage.run_dir 'run_manifest.json') -Raw|ConvertFrom-Json
  $budgetUsage=Get-Content -LiteralPath $usagePath -Raw|ConvertFrom-Json
  Assert-Equal $budgetSummary.status 'interrupted' 'Resource budget summary must be interrupted.'
  Assert-Equal $budgetSummary.failure_class 'resource_budget_exceeded' 'Resource budget failure class changed.'
  Assert-Equal $budgetManifest.status 'interrupted' 'Resource budget manifest must be interrupted.'
  Assert-Equal $budgetUsage.status 'interrupted' 'Resource usage must leave running state on failure.'
  Assert-Equal $budgetUsage.failure_class 'resource_budget_exceeded' `
    'Resource usage failure class changed.'

  $schedulerPackage=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
    -RunId '20260723_170004__test__cross__scheduler-usage__n100' `
    -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
    -Software @('contract test') -RetentionContractEnabled -RetentionClass compact
  $schedulerUsagePath=Join-Path $schedulerPackage.result_dir 'resource_usage.json'
  Write-RunJson -Path $schedulerUsagePath -Value ([ordered]@{
    schema_version=2;role='multipole_resource_usage';status='running'
    failure_class='memory_danger_recovery_attempts_exhausted';limit_name='system_available_memory'
    peak_run_directory_bytes=0;final_retained_bytes=$null
    limits=[ordered]@{maximum_concurrency=2;memory_critical_reserve_bytes=536870912}
  })
  Complete-FailedRun -Python $python -RepoRoot $repoRoot `
    -RunConfig $schedulerPackage.run_config -Summary $schedulerPackage.summary `
    -SummaryRole 'scheduler_usage_test_summary' -Reason 'memory pressure' `
    -Software @('contract test') -Status interrupted `
    -FailureClass resource_budget_exceeded -ResourceUsagePath $schedulerUsagePath
  $schedulerUsage=Get-Content -LiteralPath $schedulerUsagePath -Raw|ConvertFrom-Json
  Assert-Equal $schedulerUsage.status 'interrupted' `
    'Scheduler-only usage without a compact byte limit must still publish.'
  Assert-Equal ($schedulerUsage.final_retained_bytes -ge 0) $true `
    'Scheduler-only usage must record final retained bytes.'

  $shortPackage=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
    -RunId '20260723_170005__test__cross__short-execution-path__n1' `
    -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
    -Software @('contract test') -UseShortExecutionPath -ExecutionRoot $executionRoot
  Assert-Equal ([IO.Path]::GetFullPath($shortPackage.artifact_run_dir)) `
    ([IO.Path]::GetFullPath((Join-Path $testRoot 'runs\20260723_170005__test__cross__short-execution-path__n1'))) `
    'Short package artifact run path changed.'
  if (-not $shortPackage.execution_alias -or
      -not ([IO.Path]::GetFullPath($shortPackage.run_dir).StartsWith(
        [IO.Path]::GetFullPath($executionRoot) + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      ))) {
    throw 'Short package did not return an execution-root alias.'
  }
  $shortManifest = Join-Path $shortPackage.run_dir 'run_manifest.json'
  $shortInput = Join-Path $shortPackage.input_dir 'short_execution_input.json'
  Set-Content -LiteralPath $shortInput -Value '{"role":"short_execution_probe"}' -Encoding UTF8
  $shortConfig = Get-Content -LiteralPath $shortPackage.run_config -Raw -Encoding UTF8 |
    ConvertFrom-Json -AsHashtable
  $shortConfig.inputs = [ordered]@{ short_execution_probe = $shortInput }
  Write-RunJson -Path $shortPackage.run_config -Value $shortConfig
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
    -RunConfig $shortPackage.run_config -Status interrupted -Software @('contract test') `
    -Outputs @($shortPackage.summary)
  $shortManifestDocument = Get-Content -LiteralPath $shortManifest -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-Equal ([IO.Path]::GetFullPath([string]$shortManifestDocument.run_config.path)) `
    ([IO.Path]::GetFullPath((Join-Path $shortPackage.artifact_run_dir 'run_config.json'))) `
    'Manifest must resolve the short execution alias to the artifact run.'
  Assert-Equal ([IO.Path]::GetFullPath([string]$shortManifestDocument.inputs.short_execution_probe.path)) `
    ([IO.Path]::GetFullPath((Join-Path $shortPackage.artifact_run_dir 'inputs\short_execution_input.json'))) `
    'Manifest must resolve short execution input paths to the artifact run.'
  Remove-RunPackageExecutionAlias -Package $shortPackage
  if (Test-Path -LiteralPath $shortPackage.execution_alias) {
    throw 'Short execution alias remained after cleanup.'
  }
  if (-not (Test-Path -LiteralPath $shortPackage.artifact_run_dir -PathType Container)) {
    throw 'Short execution alias cleanup removed the artifact run.'
  }
  Assert-Equal $shortPackage.execution_path_capacity.role 'run_package_execution_path_capacity' `
    'Short package path capacity role changed.'
  if (-not $shortPackage.execution_path_capacity.legacy_windows_compatible) {
    throw 'Short execution alias did not satisfy legacy Windows path capacity.'
  }

  $directTarget=Join-Path $testRoot 'direct_execution_target'
  New-Item -ItemType Directory -Path $directTarget -Force|Out-Null
  $directAlias=New-RunExecutionAlias -TargetDirectory $directTarget `
    -ExecutionRoot $executionRoot -ExpectedExecutionRelativePaths @('simion\nested\result.json')
  if(-not(Test-Path -LiteralPath $directAlias.execution_alias -PathType Container)){
    throw 'Generic short execution alias was not created.'
  }
  Remove-RunExecutionAlias -ExecutionAlias $directAlias.execution_alias -TargetDirectory $directTarget
  if(Test-Path -LiteralPath $directAlias.execution_alias){
    throw 'Generic short execution alias remained after cleanup.'
  }
  if(-not(Test-Path -LiteralPath $directTarget -PathType Container)){
    throw 'Generic short execution alias cleanup removed its target.'
  }
  try {
    $tooLongRelativePath = ('x' * 260) + '.json'
    New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $testRoot `
      -RunId '20260723_170006__test__cross__short-path-capacity__n1' `
      -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'contract_test' `
      -Software @('contract test') -UseShortExecutionPath -ExecutionRoot $executionRoot `
      -ExpectedExecutionRelativePaths $tooLongRelativePath | Out-Null
    throw 'Expected execution path capacity rejection did not occur.'
  } catch {
    if ($_.Exception.Message -notmatch 'EXECUTION_PATH_CAPACITY=FAIL') { throw }
  }
  if (Test-Path -LiteralPath (Join-Path $testRoot 'runs\20260723_170006__test__cross__short-path-capacity__n1')) {
    throw 'Path-capacity rejection created an artifact run directory.'
  }

  $writeError = ''
  try {
    Write-VerifiedRunManifest -Python (Join-Path $testRoot 'missing-python.exe') `
      -RepoRoot $repoRoot -RunConfig $successConfig -Status failed
  } catch {
    $writeError = $_.Exception.Message
  }
  if ($writeError -notlike 'Could not publish verified failed run manifest:*') {
    throw "Manifest write failure message changed. Actual='$writeError'"
  }

  $timeoutRejected = $false
  try {
    Write-RunManifest -Python $python -RepoRoot $repoRoot `
      -RunConfig $successConfig -Status timeout
  } catch {
    $timeoutRejected = $true
  }
  Assert-Equal $timeoutRejected $true `
    'PowerShell manifest support must not reinterpret candidate-workflow timeout.'

  Write-Output 'RUN_ARTIFACT_SUPPORT=PASS'
} finally {
  foreach($name in $hostEnvironment.Keys) {
    [Environment]::SetEnvironmentVariable($name,$hostEnvironment[$name],'Process')
  }
  [Environment]::SetEnvironmentVariable('PYTHONPATH',$originalPythonPath)
  [Environment]::SetEnvironmentVariable('PYTHONNOUSERSITE',$originalNoUserSite)
  if (Test-Path -LiteralPath $testRoot) {
    [IO.Directory]::Delete($testRoot, $true)
  }
  if (Test-Path -LiteralPath $executionRoot) {
    [IO.Directory]::Delete($executionRoot, $true)
  }
}
