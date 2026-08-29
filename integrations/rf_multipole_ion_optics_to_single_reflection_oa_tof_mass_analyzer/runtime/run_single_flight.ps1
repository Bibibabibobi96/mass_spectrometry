[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [Parameter(Mandatory)][string]$RuntimeBinding,
  [Parameter(Mandatory)][ValidateSet('simion')][string]$SourceBranchId,
  [Parameter(Mandatory)][string]$ResolvedSourceContract,
  [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256,
  [string]$RequiredPaCacheGenerationBinding = '',
  [string]$RequiredPaCacheGenerationBindingSha256 = '',
  [string]$OatofResolvedGeometry = '',
  [string]$PulseSchedule = '',
  [Parameter(Mandatory)][string]$ResolvedPopulationContract,
  [Parameter(Mandatory)][string]$ResolvedPopulationContractSha256,
  [string]$LayoutProfileId = '',
  [string]$ArchitectureGenerationId = '',
  [string]$ThreeZoneCandidate = '',
  [string]$ThreeZoneCandidateSha256 = '',
  [string]$TheoryWorkingPoint = '',
  [string]$TheoryWorkingPointSha256 = '',
  [double]$ExpectedBoreRadiusMm = 0,
  [double]$ExpectedRingOuterRadiusMm = 0,
  [double]$ExpectedShieldInnerRadiusMm = 0,
  [string]$TimeIntegrationProfileId = '',
  [string]$ResolvedExecutionProfile = '',
  [string]$ResolvedExecutionProfileSha256 = '',
  [Parameter(Mandatory)][string]$ResolvedRegionFieldContract,
  [Parameter(Mandatory)][string]$ResolvedRegionFieldContractSha256,
  [Parameter(Mandatory)][string]$ResolvedRegionFieldSemanticSha256,
  [string]$SourceProfileId = '',
  [string]$PrePulseSourceState = '',
  [string]$PrePulseSourceStateSha256 = '',
  [int]$PrePulseSourceStateCount = 0,
  [double]$PrePulseRestartPositionToleranceMm = 0,
  [double]$PrePulseRestartVelocityToleranceMPerS = 0,
  [double]$PrePulseRestartClockToleranceUs = 0,
  [double]$PrePulseRestartEnergyToleranceEv = 0,
  [string]$PrePulseRestartValidation = '',
  [string]$PrePulseRestartValidationSha256 = '',
  [string]$MotherParticleSource = '',
  [string]$MotherParticleSourceSha256 = '',
  [int]$MotherParticleCount = 0,
  [string]$MotherParticleSourceRunRoot = '',
  [string]$MotherParticleSourceReceipt = '',
  [string]$MotherParticleSourceReceiptSha256 = '',
  [string]$TerminalHandoffState = '',
  [string]$TerminalHandoffStateSha256 = '',
  [int]$TerminalHandoffMotherParticleCount = 0,
  [int]$TerminalHandoffContinuedParticleCount = 0,
  [double]$TerminalHandoffMassAmu = 0,
  [int]$TerminalHandoffChargeState = 0,
  [int]$TerminalHandoffSmokeSourceParticleId = 0,
  [int]$TerminalHandoffExecutionParticleCount = 0,
  [int]$TerminalHandoffUpstreamLossCount = -1,
  [string]$PrePulseTimeSeriesContract = '',
  [string]$PrePulseTimeSeriesContractSha256 = '',
  [string]$ResumePrePulseFromRun = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = '',
  [switch]$BuildOnly,
  [switch]$ProgramAxisFieldExport,
  [ValidateSet('strict','exploration')][string]$RuntimeImplementationBindingMode = 'strict'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$frozenPaCacheGenerationBindingPath = [string]$RequiredPaCacheGenerationBinding
$frozenPaCacheGenerationBindingSha256 = [string]$RequiredPaCacheGenerationBindingSha256
$hasRequiredPaCacheGenerationBinding = -not [string]::IsNullOrWhiteSpace(
  $frozenPaCacheGenerationBindingPath
)
if ($hasRequiredPaCacheGenerationBinding -ne (-not [string]::IsNullOrWhiteSpace(
    $frozenPaCacheGenerationBindingSha256))) {
  throw 'PA cache generation binding path/hash identity is incomplete.'
}
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
. (Join-Path $PSScriptRoot 'runtime_binding.ps1')
. (Join-Path $PSScriptRoot 'single_flight_assets.ps1')
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repoRoot `
  -ResolvedConnection $ResolvedConnection -RuntimeBinding $RuntimeBinding `
  -ExpectedConnectionProfileId $ConnectionProfileId -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256 `
  -AllowImplementationContentShaMismatch:($RuntimeImplementationBindingMode -eq 'exploration')
. $runtime.run_artifact_support
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')

function Invoke-SingleFlightPython {
  param(
    [Parameter(Mandatory)][object[]]$Arguments,
    [Parameter(Mandatory)][string]$Failure,
    [string]$StdoutPath = '',
    [string]$StderrPath = ''
  )
  $saved = Save-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE')
  try {
    $env:PYTHONPATH = $repoRoot; $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $repoRoot
    try {
      if ($StdoutPath -and $StderrPath) {
        & $python @Arguments 1> $StdoutPath 2> $StderrPath
      } else {
        & $python @Arguments
      }
      if ($LASTEXITCODE -ne 0) { throw "$Failure (exit_code=$LASTEXITCODE)" }
    } finally { Pop-Location }
  } finally { Restore-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE') -Snapshot $saved }
}

function Get-RfSingleFlightParticleLines {
  param(
    [Parameter(Mandatory)][string]$ParticleInput,
    [Parameter(Mandatory)][bool]$RestartFly2
  )
  $lines = @(Get-Content -LiteralPath $ParticleInput -Encoding UTF8)
  if ($RestartFly2) {
    $lines = @($lines | Where-Object { $_ -match '^  standard_beam ' })
  }
  return $lines
}

function Read-RfFrozenResolvedBudgetDocument {
  param([Parameter(Mandatory)]$StageBudgetReceipt)
  if (-not ($StageBudgetReceipt.PSObject.Properties.Name -contains
      'frozen_budget') -or
      [string]::IsNullOrWhiteSpace([string]$StageBudgetReceipt.frozen_budget) -or
      -not (Test-Path -LiteralPath $StageBudgetReceipt.frozen_budget -PathType Leaf)) {
    throw 'Run-local frozen resolved engineering budget is missing.'
  }
  return Get-Content -LiteralPath $StageBudgetReceipt.frozen_budget `
    -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Test-RfFrozenCacheGeneration {
  <#
  Confirm that the immutable generation selected and fully verified before
  construction is still the one frozen into this run.  Do not re-hash every
  PA here: the cache reuse resolver already performed that full check,
  and this runner only reads a run-local materialized copy thereafter.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$ProjectId,
    [Parameter(Mandatory)][string]$CacheEntry,
    [Parameter(Mandatory)][string]$CacheRole,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$FrozenManifest,
    [Parameter(Mandatory)][string]$LogDirectory
  )
  $currentManifest = Join-Path $CacheEntry 'cache_manifest.json'
  $manifestMatches = (Test-Path -LiteralPath $currentManifest -PathType Leaf) -and
    ((Get-FileHash -LiteralPath $currentManifest -Algorithm SHA256).Hash -eq
      (Get-FileHash -LiteralPath $FrozenManifest -Algorithm SHA256).Hash)
  return [pscustomobject]@{
    passed = $manifestMatches
    verifier_exit_code = $(if ($manifestMatches) {0} else {1})
    frozen_manifest_matches = $manifestMatches
    cache_entry = $CacheEntry
    stdout_log = $null
    stderr_log = $null
  }
}

function Assert-RfThreeZoneArgumentSet {
  param(
    [string]$Candidate = '',
    [string]$CandidateSha256 = ''
  )
  $values = @($Candidate,$CandidateSha256)
  $hasAny = @($values | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_)
  }).Count -gt 0
  $hasAll = @($values | Where-Object {
    [string]::IsNullOrWhiteSpace([string]$_)
  }).Count -eq 0
  if ($hasAny -ne $hasAll) {
    throw 'Three-zone runner Candidate arguments are incomplete.'
  }
  return $hasAll
}

function Resolve-RfPositiveGapDomainSplit {
  <#
  The long connector is the only governed reason to use a split PA family.
  Each fine PA extends 10 mm inward from its own physical end.  The remaining
  middle sleeve is coarse bridge only; fine domains must never overlap.
  #>
  param([Parameter(Mandatory)]$ResolvedConnection)
  if ($null -eq $ResolvedConnection.connector -or
      $null -eq $ResolvedConnection.connector.length_mm) {
    throw 'Resolved connection is missing connector.length_mm.'
  }
  $gapMm = [double]$ResolvedConnection.connector.length_mm
  if ([double]::IsNaN($gapMm) -or [double]::IsInfinity($gapMm) -or $gapMm -lt 0) {
    throw 'Resolved connector.length_mm must be finite and nonnegative.'
  }
  $bufferMm = 10.0
  $minimumSplitGapMm = 50.0
  if ($gapMm -le 0.0) {
    return [ordered]@{
      mode='integrated_frontend'; reason='direct_mating_gap_zero'
      connector_length_mm=$gapMm; endpoint_buffer_mm=$null; coarse_sleeve_length_mm=$null
    }
  }
  if ($gapMm -lt $minimumSplitGapMm) {
    return [ordered]@{
      mode='integrated_frontend'; reason='positive_gap_below_split_threshold'
      connector_length_mm=$gapMm; endpoint_buffer_mm=$null; coarse_sleeve_length_mm=$null
    }
  }
  return [ordered]@{
    mode='domain_split'; reason='positive_gap_meets_split_threshold'
    connector_length_mm=$gapMm; minimum_split_gap_mm=$minimumSplitGapMm
    endpoint_buffer_mm=$bufferMm; coarse_sleeve_length_mm=($gapMm - 2.0*$bufferMm)
    required_pa_roles=@('full_coarse_bridge','fine_upstream','accelerator_main','accelerator_intermediate2_overlay')
    fine_domain_overlap_prohibited=$true
    field_superposition_prohibited=$true
  }
}

$hasThreeZoneCandidate = Assert-RfThreeZoneArgumentSet -Candidate $ThreeZoneCandidate -CandidateSha256 $ThreeZoneCandidateSha256
if ($ProgramAxisFieldExport -and -not $BuildOnly) {
  throw 'Program axis-field export requires BuildOnly because it is not a particle flight.'
}

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) { throw "SIMION is missing: $SimionExe" }
$runProjectId = 'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
$simionSolverCacheIdentity = Get-RfSimionSolverCacheIdentity -SimionExe $SimionExe
$isPrePulseTimeSeriesScreening = -not [string]::IsNullOrWhiteSpace(
  $PrePulseTimeSeriesContract
)
if (-not [string]::IsNullOrWhiteSpace($ResumePrePulseFromRun) -and
    -not $isPrePulseTimeSeriesScreening) {
  throw 'Pre-pulse batch continuation requires pre-pulse time-series screening mode.'
}
# The current public single-flight contract does not expose a restart context.
# Keep this explicit optional value initialized under StrictMode so the Program
# builder may remain forward-compatible without making ordinary or pre-pulse
# runs depend on an undeclared variable.
$restartContext = $null
if ($isPrePulseTimeSeriesScreening -ne (-not [string]::IsNullOrWhiteSpace(
      $PrePulseTimeSeriesContractSha256))) {
  throw 'Pre-pulse time-series contract path/hash identity is incomplete.'
}
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId"
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $runProjectId -Mode 'rf_to_oatof_simion_single_flight' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') -UseShortExecutionPath `
  -ExpectedExecutionRelativePaths @(
    'inputs/simion_five_instance_container/mag_quad_2dp.iob',
    'inputs/single_flight_mother_sample__batch999.fly2',
    'logs/overlay_interface_verify_resource_usage.json',
    'results/pre_pulse_time_series_screening_receipt.json',
    'results/single_flight_accelerator_checkpoint_evolution_metadata.json',
    'simion/frontend_cache_copy/frontend.pa0',
    'simion/overlay_iob_stage/mag_quad_2dp.iob'
  )
$requiredPaCacheGenerationBindingDocument = $null
$requiredPaCacheGenerationEntries = @()
if ($hasRequiredPaCacheGenerationBinding) {
  # The adapter has already verified the frozen file and SHA before dispatch.
  # The authoritative runtime check below validates the resolved cache
  # manifests (role, cache key, generation and payload) before SIMION.
  $requiredPaCacheGenerationBindingDocument = Get-Content `
    -LiteralPath $frozenPaCacheGenerationBindingPath -Raw -Encoding UTF8 |
    ConvertFrom-Json -AsHashtable
  if ($null -eq $requiredPaCacheGenerationBindingDocument -or
      $requiredPaCacheGenerationBindingDocument -isnot
        [System.Collections.IDictionary] -or
      -not $requiredPaCacheGenerationBindingDocument.Contains('binding_mode') -or
      -not $requiredPaCacheGenerationBindingDocument.Contains('cache_generations')) {
    $parsedType = if ($null -eq $requiredPaCacheGenerationBindingDocument) {
      '<null>'
    } else {
      $requiredPaCacheGenerationBindingDocument.GetType().FullName
    }
    $parsedKeys = if ($requiredPaCacheGenerationBindingDocument -isnot
        [System.Collections.IDictionary]) {
      '<none>'
    } else {
      @($requiredPaCacheGenerationBindingDocument.Keys) -join ','
    }
    throw "PA cache generation binding parser output is invalid: type=$parsedType keys=$parsedKeys path=$frozenPaCacheGenerationBindingPath"
  }
  $requiredPaCacheGenerationEntries = @(
    $requiredPaCacheGenerationBindingDocument['cache_generations']
  )
  if ([string]$requiredPaCacheGenerationBindingDocument['binding_mode'] -ne
      'require_exact_schema_v3_generations_v1' -or
      $requiredPaCacheGenerationEntries.Count -lt 1 -or
      @($requiredPaCacheGenerationEntries | Where-Object {
        $_ -isnot [System.Collections.IDictionary]
      }).Count -ne 0) {
    throw 'PA cache generation binding is invalid.'
  }
  $roles = @($requiredPaCacheGenerationEntries | ForEach-Object {
    [string]$_['role']
  })
  if ($roles.Count -ne @($roles | Select-Object -Unique).Count) {
    throw 'PA cache generation binding roles are not unique.'
  }
  Copy-Item -LiteralPath $frozenPaCacheGenerationBindingPath -Destination (
    Join-Path $package.input_dir 'single_flight_pa_cache_generation_binding.json'
  )
}
$resourceBudgetExceeded = $false
$snapshotReady = $false
$summaryRole = 'rf_oatof_simion_single_flight_summary'
$resourceUsage = Join-Path $package.log_dir 'resource_usage.json'
$paCacheDispositions = [ordered]@{
  frontend = [ordered]@{
    role='simion_single_flight_frontend_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  # Domain-split calls the same immutable coarse frontend generation by its
  # physical role.  This is an alias in the receipt, not a duplicate PA cache.
  full_coarse_bridge = [ordered]@{
    role='simion_single_flight_frontend_pa_cache';key=$null
    disposition='not_applicable'
  }
  fine_upstream = [ordered]@{
    role='simion_single_flight_upstream_bridge_pa_cache';key=$null
    disposition='not_applicable'
  }
  accelerator_main = [ordered]@{
    role='simion_single_flight_accelerator_main_pa_cache';key=$null
    disposition='not_applicable'
  }
  accelerator_overlay = [ordered]@{
    role='simion_accelerator_overlay_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  accelerator_entrance_overlay = [ordered]@{
    role='simion_accelerator_entrance_overlay_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  accelerator_intermediate_overlay = [ordered]@{
    role='simion_accelerator_intermediate_overlay_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  accelerator_intermediate2_overlay = [ordered]@{
    role='simion_accelerator_intermediate_overlay_pa_cache';key=$null
    disposition='not_applicable'
  }
  flight_tube = [ordered]@{
    role='simion_oatof_flight_tube_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  reflectron = [ordered]@{
    role='simion_oatof_reflectron_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
}
function Assert-RfExactPaCacheGenerationBinding {
  param([Parameter(Mandatory)][object[]]$ActiveCaches)
  if (-not $hasRequiredPaCacheGenerationBinding) { return }
  $expected = @($requiredPaCacheGenerationEntries)
  if ($expected.Count -ne $ActiveCaches.Count) {
    throw 'PA cache generation binding does not cover exactly the active PA roles.'
  }
  foreach ($active in $ActiveCaches) {
    if ($active -isnot [System.Collections.IDictionary]) {
      throw 'Active PA cache identity has an unsupported representation.'
    }
    $activeRole = [string]$active['role']
    $matches = @($expected | Where-Object {
      [string]$_['role'] -eq $activeRole
    })
    if ($matches.Count -ne 1) {
      throw "PA cache generation binding lacks exactly one active role: $activeRole"
    }
    $requirement = $matches[0]
    $manifestPath = Join-Path ([string]$active['cache_directory']) `
      'cache_manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
      throw "PA cache generation manifest is missing: $activeRole"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
      ConvertFrom-Json -AsHashtable
    if ($manifest -isnot [System.Collections.IDictionary] -or
        [int]$manifest['schema_version'] -ne 3 -or
        [string]$manifest['role'] -ne $activeRole -or
        [string]$manifest['cache_key'] -ne [string]$active['cache_key'] -or
        [string]$manifest['cache_key'] -ne [string]$requirement['cache_key'] -or
        [string]$manifest['generation_sha256'] -ne
          [string]$requirement['generation_sha256'] -or
        ([string]$manifest['payload_sha256']).ToUpperInvariant() -ne
          ([string]$requirement['payload_sha256']).ToUpperInvariant()) {
      throw ("PA cache generation identity differs: role={0}; cache_directory={1}; " +
        "expected_key={2}; actual_key={3}; expected_generation={4}; " +
        "actual_generation={5}; expected_payload={6}; actual_payload={7}; " +
        "actual_schema={8}" -f $activeRole,[string]$active['cache_directory'],
        [string]$requirement['cache_key'],[string]$manifest['cache_key'],
        [string]$requirement['generation_sha256'],[string]$manifest['generation_sha256'],
        [string]$requirement['payload_sha256'],[string]$manifest['payload_sha256'],
        [string]$manifest['schema_version'])
    }
  }
}
function Resolve-RfBoundGenerationDirectory {
  param(
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$Role,
    [AllowNull()][string]$ReusableDirectory
  )
  if ($null -eq $ReusableDirectory -or -not $hasRequiredPaCacheGenerationBinding) {
    return $ReusableDirectory
  }
  # A generation-bound contract must never silently fall back to a schema-v2
  # key root nor consult its mutable current-generation pointer.  Its frozen
  # binding names the exact immutable generation to materialize.
  $matches = @($requiredPaCacheGenerationEntries | Where-Object {
    [string]$_['role'] -eq $Role -and [string]$_['cache_key'] -eq $CacheKey
  })
  if ($matches.Count -eq 0) {
    return $ReusableDirectory
  }
  if ($matches.Count -ne 1) {
    throw "PA cache generation binding repeats role/key: $Role"
  }
  $generationDirectory = Join-Path (Join-Path (Join-Path $CacheRoot $CacheKey) `
    'generations') ([string]$matches[0]['generation_sha256'])
  if (-not (Test-Path -LiteralPath $generationDirectory -PathType Container)) {
    throw "Bound PA cache generation is missing: $Role"
  }
  return $generationDirectory
}
$prePulseTimeSeriesContractFrozen = $null
$prePulseTimeSeries = $null
if ($isPrePulseTimeSeriesScreening) {
  $prePulseTimeSeriesContractFrozen = Join-Path $package.input_dir `
    'pre_pulse_time_series_screening_contract.json'
  Copy-RfStableFile -SourceRunRoot $workspaceRoot `
    -SourcePath $PrePulseTimeSeriesContract `
    -Destination $prePulseTimeSeriesContractFrozen `
    -Role 'pre-pulse time-series screening contract' | Out-Null
  if ((Get-FileHash -LiteralPath $prePulseTimeSeriesContractFrozen -Algorithm SHA256).Hash -ne
      $PrePulseTimeSeriesContractSha256) {
    throw 'Pre-pulse time-series screening contract SHA differs.'
  }
  $prePulseTimeSeries = Get-Content -LiteralPath $prePulseTimeSeriesContractFrozen `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  # The family workflow materializes the immutable, identity-bearing screening
  # receipt as schema v3/v4.  Its execution semantics are unchanged from v1/v2;
  # the added identity fields must not make a valid screen unreachable.
  if ([int]$prePulseTimeSeries.schema_version -notin @(1, 2, 3, 4) -or
      [string]$prePulseTimeSeries.role -ne
        'rf_oatof_pre_pulse_time_series_screening_contract' -or
      [string]$prePulseTimeSeries.mode -ne 'real_pa_rf_pre_pulse_time_series' -or
      [string]$prePulseTimeSeries.active_scope -ne
        'pre_pulse_frontend_accelerator' -or
      -not [bool]$prePulseTimeSeries.pulse_disabled -or
      -not [bool]$prePulseTimeSeries.terminate_at_window_end -or
      [bool]$prePulseTimeSeries.resolution_claim_allowed -or
      (@($prePulseTimeSeries.prohibited_outputs) -join ',') -ne
        'detector_crossing,resolution_metrics,single_flight_spatial_six_panel' -or
      @($prePulseTimeSeries.sample_times_us).Count -lt 1) {
    throw 'Pre-pulse time-series screening contract mode/output policy differs.'
  }
}
$preCacheRunConfiguration = [ordered]@{
  schema_version=2;run_id=$RunId;project=$runProjectId
  mode='rf_to_oatof_simion_single_flight';project_root=$repoRoot
  inputs=[ordered]@{}
  parameters=[ordered]@{
    lifecycle_stage='pa_cache_policy_pending_budget_validation'
    connection_profile_id=$ConnectionProfileId
    source_branch_id=$SourceBranchId
    single_flight_pa_cache_policy=$null
    single_flight_pa_cache_policy_provenance=$null
    pa_cache_dispositions=$paCacheDispositions
  }
  formal_gate_passed=$false
  artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
}
function Write-RfPreCacheRunConfiguration {
  param([Parameter(Mandatory)][string]$LifecycleStage)
  $preCacheRunConfiguration.parameters.lifecycle_stage = $LifecycleStage
  Write-RunJson -Path $package.run_config -Depth 10 -Value $preCacheRunConfiguration
}
Write-RfPreCacheRunConfiguration `
  -LifecycleStage 'pa_cache_policy_pending_budget_validation'

$hostExecutionLease = Enter-HostExecutionLease -Role SIMION -RunId $RunId
$hostExecutionOutcome = 'failed'
try {
  # Repository-wide waterline: automatic cleanup is constrained to L1/L2/L3
  # reconstructible material and is fail-closed if 500 GiB cannot be reached.
  # The receipt is frozen with this run, making every automatic removal auditible.
  $artifactCapacityStartup = Invoke-SingleFlightPython -Arguments @(
    '-m','common.contracts.reconcile_artifact_capacity',
    '--artifact-root',(Join-Path $workspaceRoot 'artifacts'),'--target-gib','500','--apply'
  ) -Failure 'Artifact capacity gate failed at SIMION startup.'
  $artifactCapacityStartupReceipt = @($artifactCapacityStartup) -join "`n" |
    ConvertFrom-Json
  if (-not [bool]$artifactCapacityStartupReceipt.satisfied_after_apply) {
    throw 'Artifact capacity gate did not reach the 500 GiB repository watermark.'
  }
  $artifactCapacityStartupReceiptPath = Join-Path $package.input_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $artifactCapacityStartupReceiptPath -Depth 14 -Value $artifactCapacityStartupReceipt
  Write-Output ((
    'ARTIFACT_CAPACITY_GATE=PASS MEASURED_GIB={0:N2} REMOVED_GIB={1:N2} TARGET_GIB=500.00'
  ) -f ($artifactCapacityStartupReceipt.measured_bytes / 1GB),
    ($artifactCapacityStartupReceipt.removed_bytes / 1GB))
  # External stops can bypass a compact run's terminal cleanup.  This small,
  # local metadata scan is intentionally performed before every new SIMION
  # launch, while the shared host lease proves no other SIMION process runs.
  # It only removes unrecorded files forbidden by a *verified* interrupted
  # compact manifest.  Historical manifest drift remains reportable by the
  # explicit maintenance command, never silently removed at startup.
  $interruptedReconciliation = Invoke-SingleFlightPython -Arguments @(
    '-m','common.contracts.reconcile_interrupted_compact_runs',
    '--run-root',(Join-Path $artifactRoot 'runs'),'--apply','--summary-only'
  ) -Failure 'Interrupted compact-run reconciliation failed.'
  $interruptedReconciliationReceipt = @($interruptedReconciliation) -join "`n" |
    ConvertFrom-Json
  Write-Output ((
    'INTERRUPTED_COMPACT_RECONCILIATION=PASS SCANNED={0} ELIGIBLE={1} ' +
    'REMAINING_BYTES={2} APPLIED={3} REMOVED_BYTES={4}'
  ) -f
    $interruptedReconciliationReceipt.scanned_run_count,
    $interruptedReconciliationReceipt.eligible_runs,
    $interruptedReconciliationReceipt.removable_bytes,
    $interruptedReconciliationReceipt.applied_runs,
    $interruptedReconciliationReceipt.removed_bytes
  )
  $budget = Initialize-RfIntegrationStageBudget -ResolvedBudget $ResolvedEngineeringBudget `
    -InputDir $package.input_dir -ExpectedIntegrationId `
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $ConnectionProfileId -StageId 'single_flight_transport' -Solver simion
  $resolvedBudgetDocument = Read-RfFrozenResolvedBudgetDocument `
    -StageBudgetReceipt $budget
  $stageBudgetDocument = Get-Content -Raw -LiteralPath $budget.stage_budget `
    -Encoding UTF8 | ConvertFrom-Json
  $minimumSystemAvailableMemoryBytes =
    [int64]$stageBudgetDocument.limits.minimum_system_available_memory_bytes
  try {
    $diskCapacity = Test-RepositoryDiskCapacity -TargetPath $package.run_dir `
      -TransientRunDirectoryBytes ([int64]$stageBudgetDocument.limits.transient_run_directory_bytes)
  } catch {
    $diskFailure = $_.TargetObject
    if ($diskFailure -is [pscustomobject] -and
        [string]$diskFailure.role -eq 'repository_disk_capacity_check') {
      Write-Output ((
        'SIMION_STARTUP_STORAGE=FAIL VOLUME={0} FREE_GIB={1:N2} REQUIRED_GIB={2:N2} ' +
        'RESERVE_GIB={3:N2} REASON=insufficient_disk_capacity'
      ) -f
        $diskFailure.volume_root, ($diskFailure.free_bytes / 1GB),
        ($diskFailure.required_available_bytes / 1GB),
        ($diskFailure.system_disk_reserve_bytes / 1GB)
      )
    }
    throw
  }
  Write-Output ((
    'SIMION_STARTUP_STORAGE=PASS VOLUME={0} FREE_GIB={1:N2} REQUIRED_GIB={2:N2} ' +
    'RESERVE_GIB={3:N2}'
  ) -f $diskCapacity.volume_root,
    ($diskCapacity.free_bytes / 1GB),
    ($diskCapacity.required_available_bytes / 1GB),
    ($diskCapacity.system_disk_reserve_bytes / 1GB)
  )
  $PaCachePolicy = [string]$resolvedBudgetDocument.single_flight_pa_cache_policy
  $PaCachePolicyProvenance = [string](
    $resolvedBudgetDocument.single_flight_pa_cache_policy_provenance
  )
  if ($isPrePulseTimeSeriesScreening -and
      $PaCachePolicy -notin @('require_existing','build_and_publish_if_missing')) {
    throw 'Pre-pulse time-series screening requires FUNCTIONAL_ONLY cache-governed execution.'
  }
  $preCacheRunConfiguration.parameters.single_flight_pa_cache_policy =
    [string]$resolvedBudgetDocument.single_flight_pa_cache_policy
  $preCacheRunConfiguration.parameters.single_flight_pa_cache_policy_provenance =
    [string]$resolvedBudgetDocument.single_flight_pa_cache_policy_provenance
  Write-RfPreCacheRunConfiguration `
    -LifecycleStage 'pa_cache_policy_frozen_post_budget_validation'
  $configurationSource = Join-Path $integrationRoot 'config\simion_single_flight.json'
  $configuration = Join-Path $package.input_dir 'simion_single_flight.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $configurationSource -Destination $configuration -Role 'single-flight configuration' | Out-Null
  $executionProfilePath = Join-Path $package.input_dir 'resolved_single_flight_execution_profile.json'
  $hasResolvedExecutionProfile = -not [string]::IsNullOrWhiteSpace($ResolvedExecutionProfile)
  if ($hasResolvedExecutionProfile -ne (-not [string]::IsNullOrWhiteSpace(
      $ResolvedExecutionProfileSha256))) {
    throw 'Prepared single-flight execution profile path/hash identity is incomplete.'
  }
  if ($hasResolvedExecutionProfile) {
    Copy-Item -LiteralPath $ResolvedExecutionProfile -Destination $executionProfilePath -Force
    if ((Get-FileHash -LiteralPath $executionProfilePath -Algorithm SHA256).Hash -ne
        $ResolvedExecutionProfileSha256) {
      throw 'Prepared single-flight execution profile identity differs.'
    }
  } else {
    $executionProfileArguments = @('-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_execution_profile',
      '--configuration',$configuration,'--output',$executionProfilePath)
    if ($TimeIntegrationProfileId) { $executionProfileArguments += @('--time-integration-profile-id',$TimeIntegrationProfileId) }
    if (-not $isPrePulseTimeSeriesScreening) { $executionProfileArguments += '--include-source-region-diagnostic' }
    Invoke-SingleFlightPython -Arguments $executionProfileArguments `
      -Failure 'Single-flight numerical configuration is invalid.'
  }
  $executionProfile = Get-Content -LiteralPath $executionProfilePath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $selectedGridProfileId = [string]$executionProfile.frontend_grid_profile_id
  $frontendCellMmX = [double]$executionProfile.frontend_cell_mm_xyz.x
  $frontendCellMmY = [double]$executionProfile.frontend_cell_mm_xyz.y
  $frontendCellMmZ = [double]$executionProfile.frontend_cell_mm_xyz.z
  $overlayEnabled = [bool]$executionProfile.accelerator_overlay_enabled
  $resolvedFieldOverlayId = [string]$executionProfile.field_overlay_id
  $overlayLayout = if ($overlayEnabled -and $null -ne $executionProfile.PSObject.Properties['accelerator_overlay_layout']) {
    [string]$executionProfile.accelerator_overlay_layout
  } else { 'whole_accelerator_v1' }
  $overlaySpecs = @($executionProfile.accelerator_overlay_specs | Where-Object { $_ })
  if ($overlayEnabled -and $overlaySpecs.Count -eq 0) {
    $overlaySpecs = @([pscustomobject]@{
      overlay_id='accelerator_overlay'; region_id='whole_accelerator'
      cell_mm_xyz=$executionProfile.accelerator_overlay_cell_mm_xyz
      half_span_mm=$null
    })
  }
  if ($overlayEnabled) {
    $overlaySpecs = @($overlaySpecs | ForEach-Object {
      $overlayId = switch ([string]$_.region_id) {
        'whole_accelerator' { 'accelerator_overlay' }
        'entrance' { 'accelerator_entrance_overlay' }
        'intermediate2' { 'accelerator_intermediate_overlay' }
        default { throw "Unsupported accelerator overlay region: $($_.region_id)" }
      }
      [pscustomobject]@{
        overlay_id=$overlayId; region_id=[string]$_.region_id
        cell_mm_xyz=$_.cell_mm_xyz
        half_span_mm=$(if ($null -ne $_.PSObject.Properties['intermediate_half_span_mm']) {
          $_.intermediate_half_span_mm
        } else { $null })
      }
    })
  }
  if ($overlayEnabled -and $overlayLayout -eq 'two_local_v1' -and
      (@($overlaySpecs.overlay_id) -join ',') -ne
      'accelerator_entrance_overlay,accelerator_intermediate_overlay') {
    throw 'Two-local accelerator overlay profile must define entrance then intermediate overlay specs.'
  }
  if ($overlayEnabled -and $overlayLayout -notin @('whole_accelerator_v1','two_local_v1')) {
    throw "Unsupported accelerator overlay layout: $overlayLayout"
  }
  $overlayCellMmX = if ($overlayEnabled) { [double]$overlaySpecs[0].cell_mm_xyz.x } else { $null }
  $overlayCellMmY = if ($overlayEnabled) { [double]$overlaySpecs[0].cell_mm_xyz.y } else { $null }
  $overlayCellMmZ = if ($overlayEnabled) { [double]$overlaySpecs[0].cell_mm_xyz.z } else { $null }
  $selectedOatofNumericalProfileId = [string]$executionProfile.oatof_numerical_profile_id
  $reflectronCellMmAxial = [double]$executionProfile.reflectron_cell_mm.axial
  $reflectronCellMmRadial = [double]$executionProfile.reflectron_cell_mm.radial
  $selectedTrajectoryQualityProfileId = [string]$executionProfile.trajectory_quality_profile_id
  $trajectoryQuality = [int]$executionProfile.trajectory_quality
  $selectedTimeIntegrationProfileId = [string]$executionProfile.time_integration_profile_id
  $rfStepsPerPeriod = [int]$executionProfile.rf_steps_per_period
  $maximumTimeOfFlightUs = [double]$executionProfile.maximum_time_of_flight_us
  $spatialWindowProfiles = @($executionProfile.spatial_window_profile_id | Where-Object { $_ })
  $resolvedRegionFieldContractFrozen = Join-Path $package.input_dir 'resolved_region_field_contract.json'
  Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $ResolvedRegionFieldContract `
    -Destination $resolvedRegionFieldContractFrozen -Role 'resolved region field contract' | Out-Null
  if ((Get-FileHash -LiteralPath $resolvedRegionFieldContractFrozen -Algorithm SHA256).Hash -ne
      $ResolvedRegionFieldContractSha256) {
    throw 'Resolved region field contract SHA differs.'
  }
  $resolvedRegionField = Get-Content -LiteralPath $resolvedRegionFieldContractFrozen -Raw |
    ConvertFrom-Json
  if ($resolvedRegionField.role -ne 'rf_oatof_resolved_region_field_contract' -or
      [string]$resolvedRegionField.semantic_sha256 -ne $ResolvedRegionFieldSemanticSha256 -or
      [bool]$resolvedRegionField.semantic.real_pa_field_blending_allowed) {
    throw 'Resolved region field semantic authority differs.'
  }
  $selectedFieldProfileId = [string]$resolvedRegionField.semantic.canonical_profile_id
  $threeZoneCandidateFrozen = $null
  if ($hasThreeZoneCandidate) {
    $threeZoneCandidateFrozen = Join-Path $package.input_dir 'three_zone_t5_candidate_resolved.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $ThreeZoneCandidate -Destination $threeZoneCandidateFrozen -Role 'three-zone T5 Candidate resolved input' | Out-Null
    if ((Get-FileHash -LiteralPath $threeZoneCandidateFrozen -Algorithm SHA256).Hash -ne
        $ThreeZoneCandidateSha256) {
      throw 'Three-zone T5 Candidate SHA differs.'
    }
  }
  $hasGovernedLayout = -not [string]::IsNullOrWhiteSpace($LayoutProfileId)
  $hasGeometry = -not [string]::IsNullOrWhiteSpace($OatofResolvedGeometry)
  $hasPulseSchedule = -not [string]::IsNullOrWhiteSpace($PulseSchedule)
  $resolvedFrozen = Join-Path $package.input_dir 'resolved_connection.json'
  $upstreamFrozen = Join-Path $package.input_dir 'upstream_resolved_design.json'
  $sourceContractFrozen = Join-Path $package.input_dir 'resolved_source_contract.json'
  $populationContractFrozen = Join-Path $package.input_dir 'resolved_population_contract.json'
  $runtimeBindingFrozen = Join-Path $package.input_dir 'runtime_binding.json'
  $oatofGeometry = Join-Path $package.input_dir 'oatof_resolved_geometry.json'
  Copy-Item -LiteralPath $runtime.resolved_connection_path -Destination $resolvedFrozen
  $resolvedConnectionDocument = Get-Content -LiteralPath $resolvedFrozen -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $domainSplitPlan = Resolve-RfPositiveGapDomainSplit -ResolvedConnection $resolvedConnectionDocument
  $domainSplitEnabled = [string]$domainSplitPlan.mode -eq 'domain_split'
  $coarseBridgeCellMmX = $null
  $coarseBridgeCellMmY = $null
  $coarseBridgeCellMmZ = $null
  if ($domainSplitEnabled) {
    $coarseBridgeCells = $executionProfile.coarse_bridge_cell_mm_xyz
    if ($null -eq $coarseBridgeCells) {
      throw 'Positive-gap domain split requires a coarse-bridge grid declaration.'
    }
    $coarseBridgeCellMmX = [double]$coarseBridgeCells.x
    $coarseBridgeCellMmY = [double]$coarseBridgeCells.y
    $coarseBridgeCellMmZ = [double]$coarseBridgeCells.z
    if ($coarseBridgeCellMmX -le 0.0 -or $coarseBridgeCellMmY -le 0.0 -or
        $coarseBridgeCellMmZ -le 0.0) {
      throw 'Positive-gap domain split coarse-bridge grid is invalid.'
    }
  }
  $domainSplitContract = Join-Path $package.input_dir 'domain_split_runtime_contract.json'
  Write-RunJson -Path $domainSplitContract -Depth 6 -Value ([ordered]@{
    schema_version=1; role='rf_oatof_domain_split_runtime_contract'
    status=[string]$domainSplitPlan.mode
    plan=$domainSplitPlan
  })
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design -Destination $upstreamFrozen
  Copy-Item -LiteralPath $runtime.contracts.resolved_source_contract -Destination $sourceContractFrozen
  Copy-RfStableFile -SourceRunRoot $workspaceRoot `
    -SourcePath $ResolvedPopulationContract -Destination $populationContractFrozen `
    -Role 'resolved single-flight population contract' | Out-Null
  if ((Get-FileHash -LiteralPath $populationContractFrozen -Algorithm SHA256).Hash -ne
      $ResolvedPopulationContractSha256) {
    throw 'Resolved population contract hash differs.'
  }
  $runtimePopulationPath = Join-Path $package.input_dir 'resolved_single_flight_population.json'
  Invoke-SingleFlightPython -Arguments @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_population',
    '--contract',$populationContractFrozen,'--output',$runtimePopulationPath
  ) -Failure 'Resolved population contract identity differs.'
  $runtimePopulation = Get-Content -LiteralPath $runtimePopulationPath -Raw `
    -Encoding UTF8 | ConvertFrom-Json
  $launched = [int]$runtimePopulation.launched_particle_count
  $PopulationDenominatorCount = [int]$runtimePopulation.population_denominator_count
  $EligiblePopulationCount = $runtimePopulation.eligible_population_count
  $BootstrapResamples = [int]$runtimePopulation.bootstrap_resample_count
  $BootstrapSeed = [int]$runtimePopulation.bootstrap_seed
  $sourceReleaseMode = [string]$runtimePopulation.source_release_mode
  if ($runtime.resolved_source_contract.PSObject.Properties.Name -contains
      'authority_scope') {
    throw 'Resolved source contract contains a retired source-authority scope.'
  }
  if (-not $hasGovernedLayout -or -not $hasGeometry -or -not $hasPulseSchedule) {
    throw 'Governed layout, geometry, and pulse schedule are required.'
  }
  $populationBasis = [string]$runtimePopulation.population_basis
  $requiresEligiblePopulation = [bool]$runtimePopulation.requires_eligible_population
  $isPrePulseRestart = [bool]$runtimePopulation.is_pre_pulse_restart
  $sourceRegionDiagnosticProfileId = [string]$executionProfile.source_region_diagnostic_profile_id
  $sourceRegionDiagnosticProfiles = @($sourceRegionDiagnosticProfileId | Where-Object { $_ })
  Copy-Item -LiteralPath $runtime.binding_path -Destination $runtimeBindingFrozen
  $oatofGeometrySource = if ($hasGovernedLayout) {
    [IO.Path]::GetFullPath($OatofResolvedGeometry)
  } else {
    Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\config\resolved_geometry.json'
  }
  Copy-RfStableFile -SourceRunRoot $(if ($hasGovernedLayout) {$workspaceRoot} else {$repoRoot}) `
    -SourcePath $oatofGeometrySource `
    -Destination $oatofGeometry -Role 'oaTOF resolved geometry' | Out-Null
  $oatofGeometryDocument = Get-Content -LiteralPath $oatofGeometry -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ([double]$oatofGeometryDocument.simion_geometry_build.reflectron.cell_axial_mm -ne
      $reflectronCellMmAxial -or
      [double]$oatofGeometryDocument.simion_geometry_build.reflectron.cell_radial_mm -ne
      $reflectronCellMmRadial) {
    throw 'Frozen oaTOF geometry differs from the selected numerical profile.'
  }
  $layoutDerivation = if ($hasGovernedLayout) {
    $oatofGeometryDocument.single_flight_layout_derivation
  } else { $null }
  if ($hasGovernedLayout -and (
      [string]$layoutDerivation.architecture_generation_id -ne $ArchitectureGenerationId -or
      [double]$oatofGeometryDocument.geometry_mm.bore_r -ne $ExpectedBoreRadiusMm -or
      [double]$oatofGeometryDocument.geometry_mm.ring_outer_r -ne $ExpectedRingOuterRadiusMm -or
      [double]$oatofGeometryDocument.geometry_mm.flight_tube_r -ne $ExpectedShieldInnerRadiusMm)) {
    throw 'Frozen oaTOF architecture generation or radius identity differs.'
  }
  $hasReflectronRebuild = (
    -not $isPrePulseTimeSeriesScreening -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.reflectron_pa
  )
  $hasFlightTubeRebuild = (
    -not $isPrePulseTimeSeriesScreening -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.flight_tube_pa
  )
  if (-not $overlayEnabled) {
    $paCacheDispositions.accelerator_overlay.disposition = 'not_applicable'
    $paCacheDispositions.accelerator_entrance_overlay.disposition = 'not_applicable'
    $paCacheDispositions.accelerator_intermediate_overlay.disposition = 'not_applicable'
  } elseif ($overlayLayout -eq 'whole_accelerator_v1') {
    $paCacheDispositions.accelerator_entrance_overlay.disposition = 'not_applicable'
    $paCacheDispositions.accelerator_intermediate_overlay.disposition = 'not_applicable'
  } else {
    $paCacheDispositions.accelerator_overlay.disposition = 'not_applicable'
  }
  if (-not $hasFlightTubeRebuild) {
    $paCacheDispositions.flight_tube.disposition = 'formal'
  }
  if (-not $hasReflectronRebuild) {
    $paCacheDispositions.reflectron.disposition = 'formal'
  }
  Write-RfPreCacheRunConfiguration -LifecycleStage 'pa_cache_policy_frozen_pre_cache'
  $pulseScheduleFrozen = $null
  $pulseTimeUs = $null
  $pulseWidthUs = $null
  if ($hasPulseSchedule) {
    $pulseScheduleFrozen = Join-Path $package.input_dir 'resolved_single_flight_pulse_schedule.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $PulseSchedule `
      -Destination $pulseScheduleFrozen -Role 'single-flight pulse schedule' | Out-Null
    $pulseScheduleDocument = Get-Content -LiteralPath $pulseScheduleFrozen -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ($pulseScheduleDocument.role -ne 'rf_oatof_resolved_single_flight_pulse_schedule' -or
        $pulseScheduleDocument.layout_profile_id -ne $LayoutProfileId -or
        $pulseScheduleDocument.population_declaration_sha256 -ne
          $runtimePopulation.population_declaration_sha256 -or
        [double]$pulseScheduleDocument.pulse_effective_time_us -le 0 -or
        [double]$pulseScheduleDocument.pulse_width_us -le 0) {
      throw 'Governed single-flight pulse schedule identity differs.'
    }
    $pulseTimeUs = [double]$pulseScheduleDocument.pulse_effective_time_us
    $pulseWidthUs = [double]$pulseScheduleDocument.pulse_width_us
  }

  if ($isPrePulseRestart -ne ($sourceReleaseMode -eq 'pre_pulse_restart')) {
    throw 'Resolved population source-release mode changed during initialization.'
  }
  if ($isPrePulseRestart -ne (-not [string]::IsNullOrWhiteSpace($PrePulseSourceState) -and
      -not [string]::IsNullOrWhiteSpace($PrePulseSourceStateSha256) -and
      $PrePulseSourceStateCount -gt 0)) {
    throw 'Pre-pulse restart source-state identity is incomplete.'
  }
  $hasRestartValidation = -not [string]::IsNullOrWhiteSpace($PrePulseRestartValidation)
  if ($isPrePulseRestart -and $hasRestartValidation -ne (
      -not [string]::IsNullOrWhiteSpace($PrePulseRestartValidationSha256) -and
      $PrePulseRestartPositionToleranceMm -gt 0 -and
      $PrePulseRestartVelocityToleranceMPerS -gt 0 -and
      $PrePulseRestartClockToleranceUs -gt 0 -and
      $PrePulseRestartEnergyToleranceEv -gt 0)) {
    throw 'Pre-pulse restart validation-contract identity is incomplete.'
  }
  $prePulseValidationFrozen = $null
  if ($hasRestartValidation) {
    $prePulseValidationFrozen = Join-Path $package.input_dir `
      'canonical_pulse_restart_target_state_validation.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $PrePulseRestartValidation -Destination $prePulseValidationFrozen `
      -Role 'pre-pulse restart validation contract' | Out-Null
    if ((Get-FileHash -LiteralPath $prePulseValidationFrozen -Algorithm SHA256).Hash -ne
        $PrePulseRestartValidationSha256) {
      throw 'Pre-pulse restart validation-contract hash differs.'
    }
  }
  $motherSource = Join-Path $package.input_dir 'mother_particle_source.csv'
  $isTerminalHandoffContinuation = $sourceReleaseMode -eq 'continuous_frontend_handoff'
  $hasTerminalHandoffState = -not [string]::IsNullOrWhiteSpace($TerminalHandoffState)
  if ($isTerminalHandoffContinuation -ne ($hasTerminalHandoffState -and
      -not [string]::IsNullOrWhiteSpace($TerminalHandoffStateSha256) -and
      $TerminalHandoffMotherParticleCount -gt 0 -and
      $TerminalHandoffContinuedParticleCount -gt 0 -and
      $TerminalHandoffMassAmu -gt 0 -and $TerminalHandoffChargeState -gt 0)) {
    throw 'Terminal-handoff continuation identity is incomplete.'
  }
  $hasMotherOverride = -not [string]::IsNullOrWhiteSpace($MotherParticleSource)
  if ($hasMotherOverride -ne (-not [string]::IsNullOrWhiteSpace($MotherParticleSourceSha256) -and $MotherParticleCount -gt 0)) {
    throw 'Single-flight mother-source override identity is incomplete.'
  }
  $hasMaterializedMotherReceipt = -not [string]::IsNullOrWhiteSpace(
    $MotherParticleSourceReceipt
  )
  if ($hasMaterializedMotherReceipt -ne (-not [string]::IsNullOrWhiteSpace(
        $MotherParticleSourceReceiptSha256))) {
    throw 'Materialized mother-source receipt identity is incomplete.'
  }
  if ($isPrePulseRestart -and
      ($hasMotherOverride -or $hasMaterializedMotherReceipt)) {
    throw 'Restart source modes prohibit an unused mother-source override.'
  }
  $hasMotherSourceRunRoot = -not [string]::IsNullOrWhiteSpace(
    $MotherParticleSourceRunRoot
  )
  if ($hasMotherSourceRunRoot -and (-not $hasMotherOverride -or $hasMaterializedMotherReceipt)) {
    throw 'Explicit mother-source run root requires one non-materialized mother-source override.'
  }
  $sourceToCopy = if ($isPrePulseRestart) {
    [IO.Path]::GetFullPath($PrePulseSourceState)
  } elseif ($isTerminalHandoffContinuation) {
    [IO.Path]::GetFullPath($TerminalHandoffState)
  } elseif ($hasMotherOverride) { [IO.Path]::GetFullPath($MotherParticleSource) } else { $runtime.source_particle_source }
  $motherSourceRoot = if ($hasMotherSourceRunRoot) {
    [IO.Path]::GetFullPath($MotherParticleSourceRunRoot)
  } elseif ($isPrePulseRestart -or $isTerminalHandoffContinuation) { $workspaceRoot } elseif ($hasMaterializedMotherReceipt) {
    Resolve-RfMaterializedMotherSourceRunRoot `
      -WorkspaceRoot $workspaceRoot `
      -SourcePath $sourceToCopy `
      -ReceiptPath $MotherParticleSourceReceipt
  } elseif ($hasMotherOverride) { $repoRoot } else { $workspaceRoot }
  Copy-RfStableFile -SourceRunRoot $motherSourceRoot -SourcePath $sourceToCopy `
    -Destination $motherSource -Role 'single-flight mother particle source' | Out-Null
  $motherSourceReceiptFrozen = $null
  if ($hasMaterializedMotherReceipt) {
    $motherSourceReceiptFrozen = Join-Path $package.input_dir (
      'single_flight_source_materialization_receipt.json'
    )
    Copy-RfStableFile -SourceRunRoot $motherSourceRoot `
      -SourcePath $MotherParticleSourceReceipt `
      -Destination $motherSourceReceiptFrozen `
      -Role 'single-flight source materialization receipt' | Out-Null
    if ((Get-FileHash -LiteralPath $motherSourceReceiptFrozen -Algorithm SHA256).Hash -ne
        $MotherParticleSourceReceiptSha256) {
      throw 'Single-flight source materialization receipt hash differs.'
    }
  }
  if ($isPrePulseRestart -and (Get-FileHash -LiteralPath $motherSource -Algorithm SHA256).Hash -ne $PrePulseSourceStateSha256) {
    throw 'Pre-pulse restart source-state hash differs.'
  }
  if ($hasMotherOverride -and -not $isPrePulseRestart -and (Get-FileHash -LiteralPath $motherSource -Algorithm SHA256).Hash -ne $MotherParticleSourceSha256) {
    throw 'Single-flight mother-source override hash differs.'
  }
  if ($isTerminalHandoffContinuation -and (Get-FileHash -LiteralPath $motherSource -Algorithm SHA256).Hash -ne $TerminalHandoffStateSha256) {
    throw 'Terminal-handoff source-state hash differs.'
  }
  if (($isPrePulseRestart -and $PrePulseSourceStateCount -ne $launched) -or
      ($isTerminalHandoffContinuation -and ($TerminalHandoffContinuedParticleCount -ne $launched -or $TerminalHandoffMotherParticleCount -ne $PopulationDenominatorCount)) -or
      ($hasMotherOverride -and -not $isTerminalHandoffContinuation -and
       $MotherParticleCount -ne $launched) -or
      (-not $isPrePulseRestart -and -not $isTerminalHandoffContinuation -and
       -not $hasMotherOverride -and
       [int]$runtime.source_record.launched_particle_count -ne $launched)) {
    throw 'Single-flight source count differs from the resolved population authority.'
  }
  if ($requiresEligiblePopulation -and
      ($PopulationDenominatorCount -lt $EligiblePopulationCount -or
       $EligiblePopulationCount -lt $launched)) {
    throw 'Conditional-source population counts are inconsistent.'
  }
  if (-not $isTerminalHandoffContinuation -and @(Import-Csv -LiteralPath $motherSource).Count -ne $launched) {
    throw 'Single-flight mother sample count differs from source authority.'
  }
  $frontendGem = Join-Path $package.input_dir 'single_flight_frontend.gem'
  $frontendContract = Join-Path $package.input_dir 'single_flight_frontend_contract.json'
  $upstreamBridgeGem = if ($domainSplitEnabled) { Join-Path $package.input_dir 'upstream_bridge.gem' } else { $null }
  $upstreamBridgeContract = if ($domainSplitEnabled) { Join-Path $package.input_dir 'upstream_bridge_contract.json' } else { $null }
  $acceleratorMainGem = if ($domainSplitEnabled) { Join-Path $package.input_dir 'accelerator_main.gem' } else { $null }
  $acceleratorMainContract = if ($domainSplitEnabled) { Join-Path $package.input_dir 'accelerator_main_contract.json' } else { $null }
  $overlayGem = if ($overlayEnabled) { Join-Path $package.input_dir 'accelerator_overlay.gem' } else { $null }
  $overlayContract = if ($overlayEnabled) { Join-Path $package.input_dir 'accelerator_overlay_contract.json' } else { $null }
  $overlayArtifacts = @()
  if ($overlayEnabled) {
    foreach ($spec in $overlaySpecs) {
      $overlayArtifacts += [pscustomobject]@{
        overlay_id=[string]$spec.overlay_id; region_id=[string]$spec.region_id
        half_span_mm=$spec.half_span_mm; cell_mm_xyz=$spec.cell_mm_xyz
        gem=(Join-Path $package.input_dir (([string]$spec.overlay_id) + '.gem'))
        contract=(Join-Path $package.input_dir (([string]$spec.overlay_id) + '_contract.json'))
      }
    }
    if ($overlayLayout -eq 'whole_accelerator_v1') {
      $overlayArtifacts[0].gem = $overlayGem
      $overlayArtifacts[0].contract = $overlayContract
    }
  }
  # Keep the coarse bridge arguments physically adjacent to the domain-split
  # branch.  The full frontend PA is its Dirichlet boundary provider, never a
  # hidden reuse of the fine accelerator grid.
  $frontendCompileArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend',
    '--upstream',$upstreamFrozen,'--oatof',$oatofGeometry,
    '--connection',$resolvedFrozen,'--gem',$frontendGem,'--contract',$frontendContract)
  if ($domainSplitEnabled) {
    $frontendCompileArguments += @(
      '--cell-mm-x',([string]$coarseBridgeCellMmX),
      '--cell-mm-y',([string]$coarseBridgeCellMmY),
      '--cell-mm-z',([string]$coarseBridgeCellMmZ)
    )
  } else {
    $frontendCompileArguments += @(
      '--cell-mm-x',([string]$frontendCellMmX),
      '--cell-mm-y',([string]$frontendCellMmY),
      '--cell-mm-z',([string]$frontendCellMmZ)
    )
  }
  if ($domainSplitEnabled) {
    $frontendCompileArguments += @(
      '--upstream-bridge-gem',$upstreamBridgeGem,
      '--upstream-bridge-contract',$upstreamBridgeContract,
      '--accelerator-main-gem',$acceleratorMainGem,
      '--accelerator-main-contract',$acceleratorMainContract,
      '--partition-cell-mm-x',([string]$frontendCellMmX),
      '--partition-cell-mm-y',([string]$frontendCellMmY),
      '--partition-cell-mm-z',([string]$frontendCellMmZ)
    )
  }
  if ($overlayEnabled) {
    $firstOverlay = $overlayArtifacts[0]
    $frontendCompileArguments += @(
      '--overlay-gem',$firstOverlay.gem,'--overlay-contract',$firstOverlay.contract,
      '--overlay-cell-mm-x',([string]$firstOverlay.cell_mm_xyz.x),
      '--overlay-cell-mm-y',([string]$firstOverlay.cell_mm_xyz.y),
      '--overlay-cell-mm-z',([string]$firstOverlay.cell_mm_xyz.z),
      '--overlay-region-id',$firstOverlay.region_id)
    if ($null -ne $firstOverlay.half_span_mm) {
      $frontendCompileArguments += @('--overlay-intermediate-half-span-mm',([string]$firstOverlay.half_span_mm))
    }
  }
  Invoke-SingleFlightPython -Arguments $frontendCompileArguments `
    -Failure 'Single-flight frontend compilation failed.'
  if ($overlayEnabled -and $overlayArtifacts.Count -gt 1) {
    foreach ($additionalOverlay in @($overlayArtifacts | Select-Object -Skip 1)) {
      # The overlay compiler also emits a frontend base.  It must never reuse
      # the authoritative coarse frontend paths, otherwise this second local
      # overlay silently overwrites the coarse Dirichlet boundary family.
      $additionalFrontendGem = Join-Path $package.input_dir (
        ([string]$additionalOverlay.overlay_id) + '_compile_base.gem'
      )
      $additionalFrontendContract = Join-Path $package.input_dir (
        ([string]$additionalOverlay.overlay_id) + '_compile_base_contract.json'
      )
      $additionalBaseCellMmX = if ($domainSplitEnabled) { $coarseBridgeCellMmX } else { $frontendCellMmX }
      $additionalBaseCellMmY = if ($domainSplitEnabled) { $coarseBridgeCellMmY } else { $frontendCellMmY }
      $additionalBaseCellMmZ = if ($domainSplitEnabled) { $coarseBridgeCellMmZ } else { $frontendCellMmZ }
      $additionalCompileArguments = @('-m',
        'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend',
        '--upstream',$upstreamFrozen,'--oatof',$oatofGeometry,
        '--connection',$resolvedFrozen,'--gem',$additionalFrontendGem,'--contract',$additionalFrontendContract,
        '--cell-mm-x',([string]$additionalBaseCellMmX),
        '--cell-mm-y',([string]$additionalBaseCellMmY),
        '--cell-mm-z',([string]$additionalBaseCellMmZ),
        '--overlay-gem',$additionalOverlay.gem,'--overlay-contract',$additionalOverlay.contract,
        '--overlay-cell-mm-x',([string]$additionalOverlay.cell_mm_xyz.x),
        '--overlay-cell-mm-y',([string]$additionalOverlay.cell_mm_xyz.y),
        '--overlay-cell-mm-z',([string]$additionalOverlay.cell_mm_xyz.z),
        '--overlay-region-id',$additionalOverlay.region_id)
      if ($null -ne $additionalOverlay.half_span_mm) {
        $additionalCompileArguments += @('--overlay-intermediate-half-span-mm',([string]$additionalOverlay.half_span_mm))
      }
      Invoke-SingleFlightPython -Arguments $additionalCompileArguments `
        -Failure "Single-flight $($additionalOverlay.overlay_id) compilation failed."
    }
  }
  # Preserve the existing scalar aliases for the legacy five-instance path;
  # the two-local profile is represented by the ordered artifact collection.
  if ($overlayEnabled) {
    $overlayGem = $overlayArtifacts[0].gem
    $overlayContract = $overlayArtifacts[0].contract
  }
  $frontendGeometry = Get-Content -LiteralPath $frontendContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($domainSplitEnabled -and (
      [double]$frontendGeometry.cell_mm_xyz.x -ne $coarseBridgeCellMmX -or
      [double]$frontendGeometry.cell_mm_xyz.y -ne $coarseBridgeCellMmY -or
      [double]$frontendGeometry.cell_mm_xyz.z -ne $coarseBridgeCellMmZ
    )) {
    throw 'Domain-split coarse frontend PA grid differs from the declared coarse-bridge grid.'
  }
  $frontendElectrodeTopologyContract = Join-Path $package.input_dir 'frontend_electrode_topology.json'
  Invoke-SingleFlightPython -Arguments @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract',
    '--frontend-contract',$frontendContract,
    '--output',$frontendElectrodeTopologyContract
  ) -Failure 'Single-flight frontend electrode topology resolution failed.'
  $frontendElectrodeTopology = Get-Content -LiteralPath $frontendElectrodeTopologyContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $frontendBasisElectrodeIds = @(
    $frontendElectrodeTopology.basis_electrode_ids | ForEach-Object { [int]$_ }
  )
  $maximumFrontendElectrodeId = [int]$frontendElectrodeTopology.maximum_electrode_id
  $expectedFrontendBasisElectrodeIds = @(0..$maximumFrontendElectrodeId)
  if ([string]$frontendElectrodeTopology.role -ne
      'rf_oatof_single_flight_electrode_topology' -or
      [string]::IsNullOrWhiteSpace([string]$frontendElectrodeTopology.topology_id) -or
      [int]$frontendElectrodeTopology.basis_count -ne
      $frontendBasisElectrodeIds.Count -or
      ($frontendBasisElectrodeIds -join ',') -ne
      ($expectedFrontendBasisElectrodeIds -join ',')) {
    throw 'Resolved frontend electrode topology is invalid or non-contiguous.'
  }
  if ($hasThreeZoneCandidate) {
    if (-not [string]::IsNullOrWhiteSpace($TheoryWorkingPoint)) {
      if ([string]::IsNullOrWhiteSpace($TheoryWorkingPointSha256) -or
          -not (Test-Path -LiteralPath $TheoryWorkingPoint -PathType Leaf) -or
          (Get-FileHash -LiteralPath $TheoryWorkingPoint -Algorithm SHA256).Hash -ne
          $TheoryWorkingPointSha256) {
        throw 'Theory working point is missing or stale.'
      }
    }
    $threeZoneRuntimeIdentity = Join-Path $package.input_dir `
      'three_zone_runtime_identity.json'
    $threeZoneRuntimeIdentityArguments = @(
      '-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.three_zone_runtime_identity',
      '--candidate',$threeZoneCandidateFrozen,
      '--candidate-sha256',$ThreeZoneCandidateSha256,
      '--geometry',$oatofGeometry,
      '--geometry-sha256',(Get-FileHash -LiteralPath $oatofGeometry -Algorithm SHA256).Hash,
      '--frontend-contract',$frontendContract,
      '--frontend-electrode-topology',$frontendElectrodeTopologyContract,
      '--region-field',$resolvedRegionFieldContractFrozen,
      '--configuration',$configuration,
      '--layout-profile-id',$LayoutProfileId,
      '--architecture-generation-id',$ArchitectureGenerationId,
      '--output',$threeZoneRuntimeIdentity
    )
    if (-not [string]::IsNullOrWhiteSpace($TheoryWorkingPoint)) {
      $threeZoneRuntimeIdentityArguments += @('--theory-working-point',$TheoryWorkingPoint)
    }
    Invoke-SingleFlightPython -Arguments $threeZoneRuntimeIdentityArguments `
      -Failure 'Frozen three-zone Candidate/runtime identity differs.'
    $threeZoneRuntimeProjection =
      Get-Content -LiteralPath $threeZoneRuntimeIdentity -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ([int]$threeZoneRuntimeProjection.schema_version -ne 1 -or
        [string]$threeZoneRuntimeProjection.role -ne
          'rf_oatof_three_zone_runtime_identity') {
      throw 'Frozen three-zone Candidate/runtime identity differs.'
    }
    $threeZoneTopologyId = [string]$threeZoneRuntimeProjection.topology_id
    $threeZoneGeometryId = [string]$threeZoneRuntimeProjection.geometry_id
    $threeZoneFrontendElectrodeTopologyId =
      [string]$threeZoneRuntimeProjection.frontend_electrode_topology_id
    $selectedFieldProfileId = [string]$threeZoneRuntimeProjection.field_profile_id
    $threeZoneFieldId = [string]$threeZoneRuntimeProjection.field_id
    $threeZoneRuntimeIdentityValues = @(
      $threeZoneTopologyId,$threeZoneGeometryId,
      $threeZoneFrontendElectrodeTopologyId,$selectedFieldProfileId,$threeZoneFieldId
    )
    if (@($threeZoneRuntimeIdentityValues |
        Where-Object { [string]::IsNullOrWhiteSpace([string]$_) }
      ).Count -gt 0) {
      throw 'Frozen three-zone Candidate/runtime identity differs.'
    }
  }
  $apertureWidthMm = [double]$frontendGeometry.aperture.width_mm
  $apertureHeightMm = [double]$frontendGeometry.aperture.height_mm
  $apertureDiscretization =
    $frontendGeometry.accelerator_local_region.accelerator_port_aperture_discretization
  if (-not $apertureDiscretization.compiled_pa_open_column_check_required -or
      [double]$apertureDiscretization.mechanical_width_mm -ne $apertureWidthMm -or
      [double]$apertureDiscretization.mechanical_height_mm -ne $apertureHeightMm) {
    throw 'Single-flight aperture discretization contract is incomplete or inconsistent.'
  }
  $apertureGridWarnings = @($apertureDiscretization.grid_alignment.warnings)
  foreach ($warningCode in $apertureGridWarnings) {
    Write-Warning "SIMION aperture discretization warning: $warningCode"
  }
  $apertureVerifier = Join-Path $package.input_dir 'verify_simion_aperture_topology.lua'
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'common\simion\verify_aperture_topology.lua') `
    -Destination $apertureVerifier -Role 'compiled PA aperture topology verifier' | Out-Null
  $apertureTopologySupport = Join-Path $package.input_dir 'simion_aperture_topology_support.ps1'
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'common\simion\aperture_topology_support.ps1') `
    -Destination $apertureTopologySupport -Role 'shared SIMION aperture topology entry' | Out-Null
  . $apertureTopologySupport
  $apertureTopologyReport = Join-Path $package.result_dir 'frontend_aperture_topology_check.json'
  $frontendHash = (Get-FileHash -LiteralPath $frontendGem -Algorithm SHA256).Hash
  $frontendBasisInitializerSource = Join-Path $PSScriptRoot 'initialize_fast_adjust_pa_basis.lua'
  $frontendSinglePaRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
  if (-not (Test-Path -LiteralPath $frontendBasisInitializerSource -PathType Leaf) -or
      -not (Test-Path -LiteralPath $frontendSinglePaRefinerSource -PathType Leaf)) {
    throw 'Frontend PA basis initializer or single-PA refiner is missing.'
  }
  $frontendBasisInitializerFrozen = Join-Path $package.input_dir 'initialize_fast_adjust_pa_basis.lua'
  $frontendSinglePaRefinerFrozen = Join-Path $package.input_dir 'refine_single_pa.lua'
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $frontendBasisInitializerSource `
    -Destination $frontendBasisInitializerFrozen -Role 'frontend fast-adjust PA basis initializer' | Out-Null
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $frontendSinglePaRefinerSource `
    -Destination $frontendSinglePaRefinerFrozen -Role 'frontend single-PA refiner' | Out-Null
  $frontendCacheRole = 'simion_single_flight_frontend_pa_cache'
  $frontendCacheIdentity = [ordered]@{
    schema_version=2; role=$frontendCacheRole
    project_id=$runProjectId; solver=$simionSolverCacheIdentity
    inputs=[ordered]@{
      frontend_gem_sha256=$frontendHash
      basis_initializer_sha256=(Get-FileHash -LiteralPath $frontendBasisInitializerFrozen -Algorithm SHA256).Hash
      single_pa_refiner_sha256=(Get-FileHash -LiteralPath $frontendSinglePaRefinerFrozen -Algorithm SHA256).Hash
    }
    critical_options=[ordered]@{
      gem2pa=@('--nogui','--noprompt','gem2pa','frontend.gem','frontend.pa#')
      basis_initialization=@('lua','initialize_fast_adjust_pa_basis.lua','frontend.pa#')
      refine_mode='per_basis_lua_explicit_v2'
      refinement_convergence='simion_official_default'
    }
  }
  $frontendCacheKey = Get-RfContentIdentitySha256 -Identity $frontendCacheIdentity
  $paCacheDispositions.frontend.key = $frontendCacheKey
  if ($domainSplitEnabled) {
    $paCacheDispositions.full_coarse_bridge.key = $frontendCacheKey
  }
  $cacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\simion_single_flight_frontend"
  $cacheDir = Join-Path $cacheRoot $frontendCacheKey
  $frontendCacheLock = Enter-RfCacheKeyLock -CacheRoot $cacheRoot `
    -CacheKey $frontendCacheKey
  try {
  $cacheDir = Resolve-RfReusableCacheDirectory -Python $python `
    -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
    -CacheRoot $cacheRoot -CacheKey $frontendCacheKey -Role $frontendCacheRole `
    -Identity $frontendCacheIdentity `
    -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'})
  $cacheDir = Resolve-RfBoundGenerationDirectory -CacheRoot $cacheRoot `
    -CacheKey $frontendCacheKey -Role $frontendCacheRole `
    -ReusableDirectory $cacheDir
  # A coarse PA family is a basis family, not merely a summed .pa0.  Fine
  # domains read every electrode basis to impose their outer Dirichlet
  # boundary.  A detached publisher or capacity action must therefore never
  # make a partial family reusable.
  $requiredFrontendBasisFiles = @()
  if (-not [string]::IsNullOrWhiteSpace($cacheDir)) {
    $requiredFrontendBasisFiles = @(0..$maximumFrontendElectrodeId |
      ForEach-Object { Join-Path $cacheDir ("frontend.pa{0}" -f $_) })
  }
  if (-not [string]::IsNullOrWhiteSpace($cacheDir) -and @($requiredFrontendBasisFiles | Where-Object {
        -not (Test-Path -LiteralPath $_ -PathType Leaf)
      }).Count -gt 0) {
    $cacheDir = $null
  }
  $frontendCacheHit = -not [string]::IsNullOrWhiteSpace($cacheDir)
  $frontendRefineRequired = -not $frontendCacheHit
  if ($frontendRefineRequired -and $PaCachePolicy -eq 'require_existing') {
    $paCacheDispositions.frontend.disposition = 'cache_miss_required_existing'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_miss'
    throw "Required PA cache MISS or damage: role=$frontendCacheRole key=$frontendCacheKey"
  }
  if ($frontendRefineRequired) {
    $paCacheDispositions.frontend.disposition = 'cache_miss_build_authorized'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_build_authorized'
    $frontendBuildDir = New-RfCacheStagingDirectory -CacheRoot $cacheRoot
    try {
    $cacheGem = Join-Path $frontendBuildDir 'frontend.gem'
    $cachePaSharp = Join-Path $frontendBuildDir 'frontend.pa#'
    $cacheBasisInitializer = Join-Path $frontendBuildDir 'initialize_fast_adjust_pa_basis.lua'
    $cacheSinglePaRefiner = Join-Path $frontendBuildDir 'refine_single_pa.lua'
    Copy-Item -LiteralPath $frontendGem -Destination $cacheGem
    Copy-Item -LiteralPath $frontendBasisInitializerFrozen -Destination $cacheBasisInitializer
    Copy-Item -LiteralPath $frontendSinglePaRefinerFrozen -Destination $cacheSinglePaRefiner
    $gem2pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_gem2pa_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $frontendBuildDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_gem2pa.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_gem2pa.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','gem2pa',$cacheGem,$cachePaSharp)
    if ($gem2pa.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend GEM conversion exceeded its resource budget.' }
    if ($gem2pa.exit_code -ne 0) { throw 'Frontend GEM conversion failed.' }
    $basisInitialization = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_basis_initialization_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $frontendBuildDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_basis_initialization.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_basis_initialization.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','lua',$cacheBasisInitializer,$cachePaSharp)
    if ($basisInitialization.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend basis initialization exceeded its resource budget.' }
    if ($basisInitialization.exit_code -ne 0) { throw 'Frontend basis initialization failed.' }
    foreach ($electrode in 0..$maximumFrontendElectrodeId) {
      $singleFrontendPa = Join-Path $frontendBuildDir ("frontend.pa{0}" -f $electrode)
      $singleRefine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir ("frontend_refine_pa{0}_resource_usage.json" -f $electrode)) -FilePath $SimionExe `
        -WorkingDirectory $frontendBuildDir -RedirectStandardOutput (Join-Path $package.log_dir ("frontend_refine_pa{0}.stdout.log" -f $electrode)) `
        -RedirectStandardError (Join-Path $package.log_dir ("frontend_refine_pa{0}.stderr.log" -f $electrode)) `
        -ArgumentList @('--nogui','--noprompt','lua',$cacheSinglePaRefiner,$singleFrontendPa)
      if ($singleRefine.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw "Frontend pa$electrode refinement exceeded its resource budget." }
      if ($singleRefine.exit_code -ne 0) { throw "Frontend pa$electrode refinement failed." }
    }
    $missingFrontendBasisFiles = @(0..$maximumFrontendElectrodeId | ForEach-Object {
      Join-Path $frontendBuildDir ("frontend.pa{0}" -f $_)
    } | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
    if ($missingFrontendBasisFiles.Count -gt 0) {
      throw ('Frontend PA refinement produced an incomplete basis family: ' +
        ($missingFrontendBasisFiles -join ','))
    }
    $cacheDir = Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot `
      -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId -CacheRoot $cacheRoot `
      -CacheKey $frontendCacheKey -Role $frontendCacheRole -Identity $frontendCacheIdentity `
      -StagingDirectory $frontendBuildDir -ProviderRunId $RunId
    $paCacheDispositions.frontend.disposition = 'built_and_published'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_published'
    } catch {
      $frontendBuildFailure = $_
      if (Test-Path -LiteralPath $frontendBuildDir) {
        # A metering or process-launch failure means this build cannot be
        # published.  Stop only SIMION writers explicitly bound to this
        # staging directory, then preserve the original failure rather than
        # masking it with a locked-directory cleanup exception.
        $frontendWriters = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
          $_.Name -ieq 'simion.exe' -and -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
          $_.CommandLine.ToLowerInvariant().Contains($frontendBuildDir.ToLowerInvariant())
        })
        foreach ($frontendWriter in $frontendWriters) {
          Stop-Process -Id ([int]$frontendWriter.ProcessId) -ErrorAction SilentlyContinue
        }
        try { Wait-RfCacheStagingWriterExit -StagingDirectory $frontendBuildDir -TimeoutSeconds 15 } catch {
          Write-Warning "Could not confirm frontend staging writer exit: $($_.Exception.Message)"
        }
        try { Remove-Item -LiteralPath $frontendBuildDir -Recurse -Force -ErrorAction Stop } catch {
          Write-Warning "Could not remove failed frontend staging: $($_.Exception.Message)"
        }
      }
      throw $frontendBuildFailure
    }
  }
  if (-not $frontendRefineRequired) {
    $paCacheDispositions.frontend.disposition = 'cache_hit'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_hit'
  }
  if ($domainSplitEnabled) {
    $paCacheDispositions.full_coarse_bridge.disposition = $paCacheDispositions.frontend.disposition
  }
  } finally {
    Exit-RfCacheKeyLock -Mutex $frontendCacheLock
  }
  $cacheGem = Join-Path $cacheDir 'frontend.gem'; $cachePaSharp = Join-Path $cacheDir 'frontend.pa#'; $cachePa0 = Join-Path $cacheDir 'frontend.pa0'
  # Freeze the selected immutable generation before any construction work.  A
  # later cache publication may advance current_generation, but cannot change
  # which exact PA generation this run consumed.
  $frontendCacheManifestInput = Copy-RfCacheManifestInput -CacheEntry $cacheDir `
    -Destination (Join-Path $package.input_dir 'frontend_pa_cache_manifest.json')
  $frontendWorkingDir = Join-Path $package.run_dir 'simion\frontend_cache_copy'
  New-Item -ItemType Directory -Path $frontendWorkingDir -Force | Out-Null
  foreach ($source in Get-ChildItem -LiteralPath $cacheDir -Filter 'frontend.pa*' -File) {
    $target = Join-Path $frontendWorkingDir $source.Name
    Copy-Item -LiteralPath $source.FullName -Destination $target -Force
    Set-RfMaterializedCacheFileWritable -Path $target
  }
  $frontendWorkingPa0 = Join-Path $frontendWorkingDir 'frontend.pa0'

  # A positive long gap retains the coarse frontend PA as the common outer
  # Dirichlet source.  The two fine domains are independently initialized from
  # every coarse electrode basis before their per-basis Refine, so neither
  # domain can silently substitute a zero outer boundary or a field sum.
  $domainSplitFineBuilds = @()
  if ($domainSplitEnabled) {
    $basisBuilderSource = Join-Path $PSScriptRoot 'build_accelerator_overlay_basis.lua'
    $acceleratorMainBasisBuilderSource = Join-Path $PSScriptRoot 'build_accelerator_main_basis_fast.lua'
    $refinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
    foreach ($fineDefinition in @(
      [pscustomobject]@{ name='upstream_bridge'; disposition_key='fine_upstream'; role='simion_single_flight_upstream_bridge_pa_cache'; cache_leaf='simion_single_flight_upstream_bridge'; gem=$upstreamBridgeGem; contract=$upstreamBridgeContract },
      [pscustomobject]@{ name='accelerator_main'; disposition_key='accelerator_main'; role='simion_single_flight_accelerator_main_pa_cache'; cache_leaf='simion_single_flight_accelerator_main'; gem=$acceleratorMainGem; contract=$acceleratorMainContract }
    )) {
      # Accelerator main is the only large fine domain.  Its specialized
      # builder preserves every coarse-basis Dirichlet value while avoiding
      # repeated edge/corner writes; upstream retains its cache identity.
      $fineBasisBuilderSource = if ($fineDefinition.name -eq 'accelerator_main') {
        $acceleratorMainBasisBuilderSource
      } else {
        $basisBuilderSource
      }
      $fineGeometry = Get-Content -LiteralPath $fineDefinition.contract -Raw -Encoding UTF8 | ConvertFrom-Json
      if ([string]::IsNullOrWhiteSpace([string]$fineGeometry.instance_origin_mm.x) -or
          [string]::IsNullOrWhiteSpace([string]$fineGeometry.instance_origin_mm.y) -or
          [string]::IsNullOrWhiteSpace([string]$fineGeometry.instance_origin_mm.z)) {
        throw "Domain-split $($fineDefinition.name) contract is missing its workbench origin."
      }
      $fineIdentity = [ordered]@{
        schema_version=2; role=$fineDefinition.role; project_id=$runProjectId; solver=$simionSolverCacheIdentity
        inputs=[ordered]@{
          fine_gem_sha256=(Get-FileHash -LiteralPath $fineDefinition.gem -Algorithm SHA256).Hash
          coarse_frontend_cache_key=$frontendCacheKey
          basis_builder_sha256=(Get-FileHash -LiteralPath $fineBasisBuilderSource -Algorithm SHA256).Hash
          refiner_sha256=(Get-FileHash -LiteralPath $refinerSource -Algorithm SHA256).Hash
        }
        critical_options=[ordered]@{
          domain_split_role=$fineDefinition.name; boundary_mode='coarse_electrode_basis_dirichlet_v1'
          basis_electrode_ids=$frontendBasisElectrodeIds; refinement_convergence='simion_official_default'
        }
      }
      $fineKey = Get-RfContentIdentitySha256 -Identity $fineIdentity
      $fineCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\$($fineDefinition.cache_leaf)"
      $paCacheDispositions[$fineDefinition.disposition_key].key = $fineKey
      $fineCacheDir = Resolve-RfReusableCacheDirectory -Python $python -RepoRoot $repoRoot `
        -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId -CacheRoot $fineCacheRoot `
        -CacheKey $fineKey -Role $fineDefinition.role -Identity $fineIdentity `
        -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'})
      $fineCacheDir = Resolve-RfBoundGenerationDirectory -CacheRoot $fineCacheRoot -CacheKey $fineKey `
        -Role $fineDefinition.role -ReusableDirectory $fineCacheDir
      if ([string]::IsNullOrWhiteSpace($fineCacheDir) -and $PaCachePolicy -eq 'require_existing') {
        $paCacheDispositions[$fineDefinition.disposition_key].disposition = 'cache_miss_required_existing'
        throw "Required domain-split PA cache MISS or damage: role=$($fineDefinition.name) key=$fineKey"
      }
      if ([string]::IsNullOrWhiteSpace($fineCacheDir)) {
        $paCacheDispositions[$fineDefinition.disposition_key].disposition = 'cache_miss_build_authorized'
        $fineBuildDir = New-RfCacheStagingDirectory -CacheRoot $fineCacheRoot
        try {
          $fineBuildGem = Join-Path $fineBuildDir ($fineDefinition.name + '.gem')
          $fineBuildSharp = Join-Path $fineBuildDir ($fineDefinition.name + '.pa#')
          $fineBasisReport = Join-Path $fineBuildDir 'basis_build.json'
          Copy-Item -LiteralPath $fineDefinition.gem -Destination $fineBuildGem
          $gem2pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
            -UsagePath (Join-Path $package.log_dir ($fineDefinition.name + '_gem2pa_resource_usage.json')) `
            -FilePath $SimionExe -WorkingDirectory $fineBuildDir `
            -RedirectStandardOutput (Join-Path $package.log_dir ($fineDefinition.name + '_gem2pa.stdout.log')) `
            -RedirectStandardError (Join-Path $package.log_dir ($fineDefinition.name + '_gem2pa.stderr.log')) `
            -ArgumentList @('--nogui','--noprompt','gem2pa',$fineBuildGem,$fineBuildSharp)
          if ($gem2pa.resource_budget_exceeded -or $gem2pa.exit_code -ne 0) { throw "$($fineDefinition.name) GEM conversion failed." }
          $basis = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
            -UsagePath (Join-Path $package.log_dir ($fineDefinition.name + '_basis_resource_usage.json')) `
            -FilePath $SimionExe -WorkingDirectory $fineBuildDir `
            -RedirectStandardOutput (Join-Path $package.log_dir ($fineDefinition.name + '_basis.stdout.log')) `
            -RedirectStandardError (Join-Path $package.log_dir ($fineDefinition.name + '_basis.stderr.log')) `
            -ArgumentList @('--nogui','--noprompt','lua',$fineBasisBuilderSource,$frontendWorkingPa0,$fineBuildSharp,
              ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
              ([string]$fineGeometry.instance_origin_mm.x),([string]$fineGeometry.instance_origin_mm.y),([string]$fineGeometry.instance_origin_mm.z),
              ([string]$maximumFrontendElectrodeId),$fineBasisReport)
          if ($basis.resource_budget_exceeded -or $basis.exit_code -ne 0) { throw "$($fineDefinition.name) basis transfer failed." }
          foreach ($electrode in $frontendBasisElectrodeIds) {
            $refine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
              -UsagePath (Join-Path $package.log_dir ("{0}_refine_pa{1}_resource_usage.json" -f $fineDefinition.name,$electrode)) `
              -FilePath $SimionExe -WorkingDirectory $fineBuildDir `
              -RedirectStandardOutput (Join-Path $package.log_dir ("{0}_refine_pa{1}.stdout.log" -f $fineDefinition.name,$electrode)) `
              -RedirectStandardError (Join-Path $package.log_dir ("{0}_refine_pa{1}.stderr.log" -f $fineDefinition.name,$electrode)) `
              -ArgumentList @('--nogui','--noprompt','lua',$refinerSource,(Join-Path $fineBuildDir ("{0}.pa{1}" -f $fineDefinition.name,$electrode)))
            if ($refine.resource_budget_exceeded -or $refine.exit_code -ne 0) { throw "$($fineDefinition.name) PA refinement failed for basis $electrode." }
          }
          $fineCacheDir = Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot `
            -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId -CacheRoot $fineCacheRoot `
            -CacheKey $fineKey -Role $fineDefinition.role -Identity $fineIdentity `
            -StagingDirectory $fineBuildDir -ProviderRunId $RunId
          $paCacheDispositions[$fineDefinition.disposition_key].disposition = 'built_and_published'
        } catch {
          if (Test-Path -LiteralPath $fineBuildDir) { Remove-Item -LiteralPath $fineBuildDir -Recurse -Force }
          throw
        }
      } else { $paCacheDispositions[$fineDefinition.disposition_key].disposition = 'cache_hit' }
      $domainSplitFineBuilds += [pscustomobject]@{
        name=$fineDefinition.name; gem=$fineDefinition.gem; contract=$fineDefinition.contract; geometry=$fineGeometry
        cache_role=$fineDefinition.role; disposition_key=$fineDefinition.disposition_key; cache_key=$fineKey; cache_dir=$fineCacheDir; pa0=$null
        basis_builder=$fineBasisBuilderSource; refiner=$refinerSource
        basis_report=(Join-Path $fineCacheDir 'basis_build.json')
      }
    }
  }

  $overlayGeometry = $null
  $overlayCacheDir = $null
  $overlayCachePa0 = $null
  $overlayBasisBuilderFrozen = $null
  $overlayRefinerFrozen = $null
  $overlayKey = $null
  $overlayBasisReport = $null
  $overlayInterfaceVerifierFrozen = $null
  $overlayInterfaceReport = $null
  $overlayRefineDispatchRequest = $null
  $overlayRefineDispatchPlan = $null
  $overlayRefineResourceUsage = $null
  if ($overlayEnabled -and $overlayLayout -eq 'whole_accelerator_v1') {
    $overlayGeometry = Get-Content -LiteralPath $overlayContract -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($overlayGeometry.role -ne 'rf_oatof_simion_accelerator_overlay_contract' -or
        [string]$overlayGeometry.boundary_condition.mode -ne
        'coarse_electrode_basis_dirichlet_v1' -or
        (@($overlayGeometry.boundary_condition.basis_electrode_ids |
          ForEach-Object { [int]$_ }) -join ',') -ne
        ($frontendBasisElectrodeIds -join ',')) {
      throw 'Compiled accelerator overlay contract is invalid.'
    }
    $overlayBasisBuilderSource = Join-Path $PSScriptRoot 'build_accelerator_overlay_basis.lua'
    $overlayRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
    $overlayInterfaceVerifierSource = Join-Path $PSScriptRoot 'verify_accelerator_overlay_interface.lua'
    $overlayCacheRole = 'simion_accelerator_overlay_pa_cache'
    $overlayIdentity = [ordered]@{
      schema_version=2; role=$overlayCacheRole
      project_id=$runProjectId; solver=$simionSolverCacheIdentity
      inputs=[ordered]@{
        overlay_gem_sha256=(Get-FileHash -LiteralPath $overlayGem -Algorithm SHA256).Hash
        frontend_pa_cache_key=$frontendCacheKey
        basis_builder_sha256=(Get-FileHash -LiteralPath $overlayBasisBuilderSource -Algorithm SHA256).Hash
        refiner_sha256=(Get-FileHash -LiteralPath $overlayRefinerSource -Algorithm SHA256).Hash
        interface_verifier_sha256=(Get-FileHash -LiteralPath $overlayInterfaceVerifierSource -Algorithm SHA256).Hash
      }
      critical_options=[ordered]@{
        boundary_mode='coarse_electrode_basis_dirichlet_v1'
        electrode_topology_id=[string]$frontendElectrodeTopology.topology_id
        basis_count=$frontendBasisElectrodeIds.Count
        gem2pa=@('--nogui','--noprompt','gem2pa','accelerator_overlay.gem','accelerator_overlay.pa#')
        refinement_convergence='simion_official_default'
        maximum_electrode_id=$maximumFrontendElectrodeId
      }
    }
    $overlayKey = Get-RfContentIdentitySha256 -Identity $overlayIdentity
    $paCacheDispositions.accelerator_overlay.key = $overlayKey
    $overlayCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\simion_accelerator_overlay"
    $overlayCacheDir = Join-Path $overlayCacheRoot $overlayKey
    $overlayCachePaSharp = Join-Path $overlayCacheDir 'accelerator_overlay.pa#'
    $overlayCachePa0 = Join-Path $overlayCacheDir 'accelerator_overlay.pa0'
    $overlayCacheManifest = Join-Path $overlayCacheDir 'cache_manifest.json'
    $overlayCacheBasisReport = Join-Path $overlayCacheDir 'basis_build.json'
    $overlayCacheDir = Resolve-RfReusableCacheDirectory -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayCacheRole `
      -Identity $overlayIdentity `
      -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'})
    $overlayCacheDir = Resolve-RfBoundGenerationDirectory -CacheRoot $overlayCacheRoot `
      -CacheKey $overlayKey -Role $overlayCacheRole `
      -ReusableDirectory $overlayCacheDir
    $overlayFamilyComplete = -not [string]::IsNullOrWhiteSpace($overlayCacheDir)
    if (-not $overlayFamilyComplete -and $PaCachePolicy -eq 'require_existing') {
      $paCacheDispositions.accelerator_overlay.disposition = 'cache_miss_required_existing'
      Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_miss'
      throw "Required PA cache MISS or damage: role=$overlayCacheRole key=$overlayKey"
    }
    New-Item -ItemType Directory -Path $overlayCacheRoot -Force | Out-Null
    $overlayBasisBuilderFrozen = Join-Path $package.input_dir 'build_accelerator_overlay_basis.lua'
    $overlayRefinerFrozen = Join-Path $package.input_dir 'refine_accelerator_overlay_pa.lua'
    $overlayInterfaceVerifierFrozen = Join-Path $package.input_dir 'verify_accelerator_overlay_interface.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayBasisBuilderSource `
      -Destination $overlayBasisBuilderFrozen -Role 'accelerator overlay basis builder' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayRefinerSource `
      -Destination $overlayRefinerFrozen -Role 'accelerator overlay segmented refiner' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayInterfaceVerifierSource `
      -Destination $overlayInterfaceVerifierFrozen -Role 'accelerator overlay interface verifier' | Out-Null
    $overlayBasisReport = Join-Path $package.result_dir 'accelerator_overlay_basis_build.json'
    if (-not $overlayFamilyComplete) {
      $paCacheDispositions.accelerator_overlay.disposition = 'cache_miss_build_authorized'
      Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_build_authorized'
      # SIMION 2020's GEM compiler on Windows has a legacy path-length limit.
      # Keep staging non-hidden and short; the completed family is still
      # atomically renamed to the full content-hash cache key.
      $overlayBuildDir = Join-Path $overlayCacheRoot (
        'b-' + [guid]::NewGuid().ToString('N').Substring(0,12)
      )
      if ([IO.Path]::GetFullPath((Split-Path -Parent $overlayBuildDir)) -ne [IO.Path]::GetFullPath($overlayCacheRoot)) {
        throw 'Overlay cache staging directory escaped the governed cache root.'
      }
      New-Item -ItemType Directory -Path $overlayBuildDir | Out-Null
      try {
        $overlayBuildPaSharp = Join-Path $overlayBuildDir 'accelerator_overlay.pa#'
        $overlayBuildBasisReport = Join-Path $overlayBuildDir 'basis_build.json'
        $overlayCacheGem = Join-Path $overlayBuildDir 'accelerator_overlay.gem'
        Copy-Item -LiteralPath $overlayGem -Destination $overlayCacheGem
        $overlayGem2Pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
          -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_gem2pa_resource_usage.json') `
          -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
          -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_gem2pa.stdout.log') `
          -RedirectStandardError (Join-Path $package.log_dir 'overlay_gem2pa.stderr.log') `
          -ArgumentList @('--nogui','--noprompt','gem2pa',$overlayCacheGem,$overlayBuildPaSharp)
        if ($overlayGem2Pa.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay GEM conversion exceeded its resource budget.' }
        if ($overlayGem2Pa.exit_code -ne 0) { throw 'Overlay GEM conversion failed.' }
        $overlayBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
          -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_basis_resource_usage.json') `
          -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
          -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_basis.stdout.log') `
          -RedirectStandardError (Join-Path $package.log_dir 'overlay_basis.stderr.log') `
          -ArgumentList @('--nogui','--noprompt','lua',$overlayBasisBuilderFrozen,$frontendWorkingPa0,$overlayBuildPaSharp,
            ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
            ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),
            ([string]$maximumFrontendElectrodeId),$overlayBuildBasisReport)
        if ($overlayBuild.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay basis transfer exceeded its resource budget.' }
        if ($overlayBuild.exit_code -ne 0) { throw 'Overlay basis transfer failed.' }
        # The basis transfer above writes all boundary-conditioned PA arrays
        # and must finish before any individual refine.  After that point each
        # electrode PA is an independent, immutable numerical job.  Delegate
        # only this independent wave to the repository scheduler; no campaign
        # CPU/memory control is permitted here.
        $overlayRefineDispatchRequest = Join-Path $package.input_dir `
          'accelerator_overlay_refine_dispatch_request.json'
        $overlayRefineDispatchPlan = Join-Path $package.input_dir `
          'accelerator_overlay_refine_dispatch_plan.json'
        $overlayRefineResourceUsage = Join-Path $package.log_dir `
          'accelerator_overlay_refine_resource_usage.json'
        $overlayRefineIdentity = [ordered]@{
          solver='SIMION';field_kind='electrostatic'
          work_item_count=$frontendBasisElectrodeIds.Count
          independent_work_items=$true
          frontend_grid_profile_id=$selectedGridProfileId
          oatof_numerical_profile_id=$selectedOatofNumericalProfileId
          trajectory_quality_profile_id=$selectedTrajectoryQualityProfileId
          time_integration_profile_id=$selectedTimeIntegrationProfileId
          frontend_cell_mm_xyz=[ordered]@{x=$frontendCellMmX;y=$frontendCellMmY;z=$frontendCellMmZ}
          accelerator_overlay_cell_mm_xyz=[ordered]@{x=$overlayCellMmX;y=$overlayCellMmY;z=$overlayCellMmZ}
          reflectron_cell_mm=$null;trajectory_quality=$null;rf_steps_per_period=$null
          accelerator_field_profile_id=$selectedFieldProfileId
          frontend_pa0_sha256=(Get-FileHash -LiteralPath $frontendWorkingPa0 -Algorithm SHA256).Hash
          accelerator_overlay_pa0_sha256=$null;reflectron_pa0_sha256=$null
          case_input_sha256=$overlayKey
        }
        Write-RunJson -Path $overlayRefineDispatchRequest -Depth 8 -Value $overlayRefineIdentity
        Invoke-SingleFlightPython -Arguments @(
          '-m','common.simion.resource_scheduler','--request',$overlayRefineDispatchRequest,
          '--output',$overlayRefineDispatchPlan
        ) -Failure 'Accelerator overlay refinement resource planning failed.'
        $overlayRefineRuntimePlan = Get-Content -LiteralPath $overlayRefineDispatchPlan `
          -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$overlayRefineRuntimePlan.dispatch_unit -ne 'independent_work_items' -or
            [int]$overlayRefineRuntimePlan.work_item_count -ne $frontendBasisElectrodeIds.Count -or
            [int]$overlayRefineRuntimePlan.limits.maximum_concurrency -lt 1) {
          throw 'Accelerator overlay refinement dispatch plan is invalid.'
        }
        $overlayRefineSpecifications = @($frontendBasisElectrodeIds | ForEach-Object {
          $electrode = [int]$_
          [pscustomobject]@{
            name=('accelerator_overlay_refine_pa{0}' -f $electrode)
            file_path=$SimionExe;working_directory=$overlayBuildDir
            stdout=(Join-Path $package.log_dir "overlay_refine_pa${electrode}.stdout.log")
            stderr=(Join-Path $package.log_dir "overlay_refine_pa${electrode}.stderr.log")
            environment=@{}
            argument_list=[string[]]@('--nogui','--noprompt','lua',$overlayRefinerFrozen,
              (Join-Path $overlayBuildDir "accelerator_overlay.pa$electrode"))
            scheduler_batch=[pscustomobject]@{index=$electrode+1;total_batches=$frontendBasisElectrodeIds.Count;work_item_id_min=$electrode+1;work_item_id_max=$electrode+1;count=1;execution_unit='independent_work_items'}
          }
        })
        $overlayExistingProcessRecords = @()
        if ([string]$overlayRefineRuntimePlan.estimation.kind -eq 'formal_first_batch_observation') {
          $overlayObservation = Start-ObservedFormalProcess `
            -DispatchPlanPath $overlayRefineDispatchPlan `
            -ProcessSpecification $overlayRefineSpecifications[0]
          if ([int64]$overlayObservation.observed_peak_process_tree_working_set_bytes -lt 1) {
            throw 'First accelerator-overlay refinement did not produce a usable resource observation.'
          }
          $overlayReplanArguments = @(
            '-m','common.simion.resource_scheduler','--request',$overlayRefineDispatchRequest,
            '--output',$overlayRefineDispatchPlan,
            '--available-memory-bytes',([string]$overlayObservation.available_memory_bytes),
            '--total-physical-memory-bytes',([string]$overlayObservation.total_physical_memory_bytes),
            '--observed-formal-peak-bytes',([string]$overlayObservation.observed_peak_process_tree_working_set_bytes),
            '--observed-formal-cpu-percent',([string]$overlayObservation.observed_process_cpu_percent),
            '--observed-background-cpu-percent',([string]$overlayObservation.observed_background_cpu_percent)
          )
          if ($overlayObservation.completed_naturally) { $overlayReplanArguments += '--first-batch-completed' }
          Invoke-SingleFlightPython -Arguments $overlayReplanArguments `
            -Failure 'Accelerator overlay formal-first resource replanning failed.'
          $overlayRefineRuntimePlan = Get-Content -LiteralPath $overlayRefineDispatchPlan `
            -Raw -Encoding UTF8 | ConvertFrom-Json
          if ([string]$overlayRefineRuntimePlan.estimation.kind -ne 'observed_formal_batch') {
            throw 'Accelerator overlay refinement formal-first dispatch replan is invalid.'
          }
          $overlayExistingProcessRecords = @($overlayObservation.process_record)
          $overlayRefineSpecifications = @($overlayRefineSpecifications | Select-Object -Skip 1)
        }
        $overlayRefineWave = Invoke-ResourceBudgetedProcesses `
          -DispatchPlanPath $overlayRefineDispatchPlan -RunDir $package.run_dir `
          -UsagePath $overlayRefineResourceUsage `
          -ProcessSpecifications $overlayRefineSpecifications `
          -ExistingProcessRecords $overlayExistingProcessRecords
        if ($overlayRefineWave.resource_budget_exceeded) {
          $resourceBudgetExceeded=$true
          throw 'Accelerator overlay refinement wave exceeded the repository resource budget.'
        }
        if (@($overlayRefineWave.processes | Where-Object { [int]$_.exit_code -ne 0 }).Count -ne 0) {
          throw 'Accelerator overlay PA refinement failed.'
        }
        $overlayCacheDir = Publish-RfVerifiedCacheEntry -Python $python `
          -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
          -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayCacheRole `
          -Identity $overlayIdentity -StagingDirectory $overlayBuildDir -ProviderRunId $RunId
        $paCacheDispositions.accelerator_overlay.disposition = 'built_and_published'
        Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_published'
      } catch {
        if (Test-Path -LiteralPath $overlayBuildDir) {
          if ([IO.Path]::GetFullPath((Split-Path -Parent $overlayBuildDir)) -ne [IO.Path]::GetFullPath($overlayCacheRoot)) {
            throw 'Refusing to clean an overlay cache staging directory outside the governed cache root.'
          }
          Remove-Item -LiteralPath $overlayBuildDir -Recurse -Force
        }
        throw
      }
    }
    if ($overlayFamilyComplete) {
      $paCacheDispositions.accelerator_overlay.disposition = 'cache_hit'
      Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_hit'
    }
    $overlayCacheBasisReport = Join-Path $overlayCacheDir 'basis_build.json'
    Copy-Item -LiteralPath $overlayCacheBasisReport -Destination $overlayBasisReport
    $overlayInterfaceReport = Join-Path $package.result_dir 'accelerator_overlay_interface_verification.json'
  }

  $twoLocalOverlayBuilds = @()
  if ($overlayEnabled -and $overlayLayout -eq 'two_local_v1') {
    $domainMain = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'accelerator_main' })
    if ($domainSplitEnabled -and $domainMain.Count -ne 1) { throw 'Domain-split intermediate overlay requires accelerator-main PA.' }
    $basisSourcePa0 = if ($domainSplitEnabled) { Join-Path $domainMain[0].cache_dir 'accelerator_main.pa0' } else { $frontendWorkingPa0 }
    $basisSourceKey = if ($domainSplitEnabled) { $domainMain[0].cache_key } else { $frontendCacheKey }
    $basisSourceOrigin = if ($domainSplitEnabled) { $domainMain[0].geometry.instance_origin_mm } else { $frontendGeometry.instance_origin_mm }
    $overlayBasisBuilderSource = Join-Path $PSScriptRoot 'build_accelerator_overlay_basis.lua'
    $overlayRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
    $overlayInterfaceVerifierSource = Join-Path $PSScriptRoot 'verify_accelerator_overlay_interface.lua'
    $overlayCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\simion_accelerator_overlay"
    $twoLocalOverlayInputs = if ($domainSplitEnabled) { @($overlayArtifacts | Where-Object { $_.overlay_id -eq 'accelerator_intermediate_overlay' }) } else { $overlayArtifacts }
    foreach ($twoLocalOverlay in $twoLocalOverlayInputs) {
      $overlayId = [string]$twoLocalOverlay.overlay_id
      $overlayDisposition = $paCacheDispositions[$overlayId]
      $overlayRole = [string]$overlayDisposition.role
      $overlayGeometry = Get-Content -LiteralPath $twoLocalOverlay.contract -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($overlayGeometry.role -ne 'rf_oatof_simion_accelerator_overlay_contract' -or
          [string]$overlayGeometry.region_id -ne [string]$twoLocalOverlay.region_id -or
          [string]$overlayGeometry.boundary_condition.mode -ne 'coarse_electrode_basis_dirichlet_v1' -or
          (@($overlayGeometry.boundary_condition.basis_electrode_ids | ForEach-Object { [int]$_ }) -join ',') -ne
          ($frontendBasisElectrodeIds -join ',')) {
        throw "Compiled $overlayId contract is invalid."
      }
      $overlayIdentity = [ordered]@{
        schema_version=2; role=$overlayRole; project_id=$runProjectId; solver=$simionSolverCacheIdentity
        inputs=[ordered]@{
          overlay_gem_sha256=(Get-FileHash -LiteralPath $twoLocalOverlay.gem -Algorithm SHA256).Hash
          coarse_pa_cache_key=$basisSourceKey
          basis_builder_sha256=(Get-FileHash -LiteralPath $overlayBasisBuilderSource -Algorithm SHA256).Hash
          refiner_sha256=(Get-FileHash -LiteralPath $overlayRefinerSource -Algorithm SHA256).Hash
          interface_verifier_sha256=(Get-FileHash -LiteralPath $overlayInterfaceVerifierSource -Algorithm SHA256).Hash
        }
        critical_options=[ordered]@{
          overlay_id=$overlayId; region_id=[string]$twoLocalOverlay.region_id
          half_span_mm=$twoLocalOverlay.half_span_mm
          boundary_mode='coarse_electrode_basis_dirichlet_v1'
          electrode_topology_id=[string]$frontendElectrodeTopology.topology_id
          basis_count=$frontendBasisElectrodeIds.Count
          gem2pa=@('--nogui','--noprompt','gem2pa',($overlayId + '.gem'),($overlayId + '.pa#'))
          refinement_convergence='simion_official_default'; maximum_electrode_id=$maximumFrontendElectrodeId
        }
      }
      $overlayKey = Get-RfContentIdentitySha256 -Identity $overlayIdentity
      $overlayDisposition.key = $overlayKey
      if ($domainSplitEnabled -and $overlayId -eq 'accelerator_intermediate_overlay') {
        $paCacheDispositions.accelerator_intermediate2_overlay.key = $overlayKey
      }
      $overlayCacheDir = Resolve-RfReusableCacheDirectory -Python $python `
        -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
        -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayRole -Identity $overlayIdentity `
        -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'})
      $overlayCacheDir = Resolve-RfBoundGenerationDirectory -CacheRoot $overlayCacheRoot `
        -CacheKey $overlayKey -Role $overlayRole -ReusableDirectory $overlayCacheDir
      $overlayFamilyComplete = -not [string]::IsNullOrWhiteSpace($overlayCacheDir)
      if (-not $overlayFamilyComplete -and $PaCachePolicy -eq 'require_existing') {
        $overlayDisposition.disposition = 'cache_miss_required_existing'
        throw "Required PA cache MISS or damage: role=$overlayRole key=$overlayKey"
      }
      $basisBuilderFrozen = Join-Path $package.input_dir ("build_${overlayId}_basis.lua")
      $refinerFrozen = Join-Path $package.input_dir ("refine_${overlayId}_pa.lua")
      $interfaceVerifierFrozen = Join-Path $package.input_dir ("verify_${overlayId}_interface.lua")
      Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayBasisBuilderSource -Destination $basisBuilderFrozen -Role "$overlayId basis builder" | Out-Null
      Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayRefinerSource -Destination $refinerFrozen -Role "$overlayId segmented refiner" | Out-Null
      Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayInterfaceVerifierSource -Destination $interfaceVerifierFrozen -Role "$overlayId interface verifier" | Out-Null
      $basisReport = Join-Path $package.result_dir ("${overlayId}_basis_build.json")
      $refineDispatchRequest = $null
      $refineDispatchPlan = $null
      $refineResourceUsage = $null
      if (-not $overlayFamilyComplete) {
        $overlayDisposition.disposition = 'cache_miss_build_authorized'
        New-Item -ItemType Directory -Path $overlayCacheRoot -Force | Out-Null
        $overlayBuildDir = Join-Path $overlayCacheRoot ('b-' + [guid]::NewGuid().ToString('N').Substring(0,12))
        New-Item -ItemType Directory -Path $overlayBuildDir | Out-Null
        try {
          $buildGem = Join-Path $overlayBuildDir ($overlayId + '.gem')
          $buildPaSharp = Join-Path $overlayBuildDir ($overlayId + '.pa#')
          $buildBasisReport = Join-Path $overlayBuildDir 'basis_build.json'
          Copy-Item -LiteralPath $twoLocalOverlay.gem -Destination $buildGem
          # Published cache generations are deliberately read-only.  SIMION's
          # Lua PA loader opens an array with a writable handle even when this
          # boundary-transfer operation only reads its potentials.  Materialize
          # the main fine-basis family beneath this disposable overlay staging
          # directory, never relax the cache generation's immutability, and
          # remove the copy immediately after all Dirichlet faces are written.
          $basisSourceForBuildPa0 = $basisSourcePa0
          $basisSourceWorkingDirectory = $null
          if ($domainSplitEnabled) {
            $basisSourceWorkingDirectory = Join-Path $overlayBuildDir 'basis_source'
            New-Item -ItemType Directory -Path $basisSourceWorkingDirectory | Out-Null
            foreach ($source in Get-ChildItem -LiteralPath $domainMain[0].cache_dir `
                -Filter 'accelerator_main.pa*' -File) {
              $target = Join-Path $basisSourceWorkingDirectory $source.Name
              Copy-Item -LiteralPath $source.FullName -Destination $target -Force
              Set-RfMaterializedCacheFileWritable -Path $target
            }
            $basisSourceForBuildPa0 = Join-Path $basisSourceWorkingDirectory 'accelerator_main.pa0'
            if (-not (Test-Path -LiteralPath $basisSourceForBuildPa0 -PathType Leaf)) {
              throw 'Domain-split intermediate overlay basis-source materialization is incomplete.'
            }
          }
          $gem2pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
            -UsagePath (Join-Path $package.log_dir "${overlayId}_gem2pa_resource_usage.json") -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
            -RedirectStandardOutput (Join-Path $package.log_dir "${overlayId}_gem2pa.stdout.log") -RedirectStandardError (Join-Path $package.log_dir "${overlayId}_gem2pa.stderr.log") `
            -ArgumentList @('--nogui','--noprompt','gem2pa',$buildGem,$buildPaSharp)
          if ($gem2pa.resource_budget_exceeded -or $gem2pa.exit_code -ne 0) { throw "$overlayId GEM conversion failed." }
          $basis = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
            -UsagePath (Join-Path $package.log_dir "${overlayId}_basis_resource_usage.json") -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
            -RedirectStandardOutput (Join-Path $package.log_dir "${overlayId}_basis.stdout.log") -RedirectStandardError (Join-Path $package.log_dir "${overlayId}_basis.stderr.log") `
            -ArgumentList @('--nogui','--noprompt','lua',$basisBuilderFrozen,$basisSourceForBuildPa0,$buildPaSharp,
              ([string]$basisSourceOrigin.x),([string]$basisSourceOrigin.y),([string]$basisSourceOrigin.z),
              ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),
              ([string]$maximumFrontendElectrodeId),$buildBasisReport)
          if ($basis.resource_budget_exceeded -or $basis.exit_code -ne 0) { throw "$overlayId basis transfer failed." }
          if ($null -ne $basisSourceWorkingDirectory) {
            Remove-Item -LiteralPath $basisSourceWorkingDirectory -Recurse -Force
            $basisSourceWorkingDirectory = $null
          }
          $refineDispatchRequest = Join-Path $package.input_dir ("${overlayId}_refine_dispatch_request.json")
          $refineDispatchPlan = Join-Path $package.input_dir ("${overlayId}_refine_dispatch_plan.json")
          $refineResourceUsage = Join-Path $package.log_dir ("${overlayId}_refine_resource_usage.json")
          $refineIdentity = [ordered]@{
            solver='SIMION';field_kind='electrostatic';work_item_count=$frontendBasisElectrodeIds.Count
            independent_work_items=$true;frontend_grid_profile_id=$selectedGridProfileId
            oatof_numerical_profile_id=$selectedOatofNumericalProfileId
            trajectory_quality_profile_id=$selectedTrajectoryQualityProfileId
            time_integration_profile_id=$selectedTimeIntegrationProfileId
            frontend_cell_mm_xyz=[ordered]@{x=$frontendCellMmX;y=$frontendCellMmY;z=$frontendCellMmZ}
            accelerator_overlay_cell_mm_xyz=$twoLocalOverlay.cell_mm_xyz
            accelerator_field_profile_id=$selectedFieldProfileId
            coarse_pa0_sha256=(Get-FileHash -LiteralPath $basisSourcePa0 -Algorithm SHA256).Hash
            case_input_sha256=$overlayKey
          }
          Write-RunJson -Path $refineDispatchRequest -Depth 8 -Value $refineIdentity
          Invoke-SingleFlightPython -Arguments @('-m','common.simion.resource_scheduler','--request',$refineDispatchRequest,'--output',$refineDispatchPlan) `
            -Failure "$overlayId refinement resource planning failed."
          $refineSpecifications = @($frontendBasisElectrodeIds | ForEach-Object {
            $electrode = [int]$_
            [pscustomobject]@{
              name=("${overlayId}_refine_pa$electrode");file_path=$SimionExe;working_directory=$overlayBuildDir
              stdout=(Join-Path $package.log_dir "${overlayId}_refine_pa${electrode}.stdout.log")
              stderr=(Join-Path $package.log_dir "${overlayId}_refine_pa${electrode}.stderr.log")
              environment=@{};argument_list=[string[]]@('--nogui','--noprompt','lua',$refinerFrozen,(Join-Path $overlayBuildDir ("${overlayId}.pa$electrode")))
              scheduler_batch=[pscustomobject]@{index=$electrode+1;total_batches=$frontendBasisElectrodeIds.Count;work_item_id_min=$electrode+1;work_item_id_max=$electrode+1;count=1;execution_unit='independent_work_items'}
            }
          })
          $refineWave = Invoke-ResourceBudgetedProcesses -DispatchPlanPath $refineDispatchPlan -RunDir $package.run_dir `
            -UsagePath $refineResourceUsage -ProcessSpecifications $refineSpecifications -ExistingProcessRecords @()
          if ($refineWave.resource_budget_exceeded -or @($refineWave.processes | Where-Object { [int]$_.exit_code -ne 0 }).Count -ne 0) { throw "$overlayId PA refinement failed." }
          $overlayCacheDir = Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot `
            -ProjectId $runProjectId -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayRole `
            -Identity $overlayIdentity -StagingDirectory $overlayBuildDir -ProviderRunId $RunId
          $overlayDisposition.disposition = 'built_and_published'
        } catch {
          if (Test-Path -LiteralPath $overlayBuildDir) { Remove-Item -LiteralPath $overlayBuildDir -Recurse -Force }
          throw
        }
      } else { $overlayDisposition.disposition = 'cache_hit' }
      if ($domainSplitEnabled -and $overlayId -eq 'accelerator_intermediate_overlay') {
        $paCacheDispositions.accelerator_intermediate2_overlay.disposition = $overlayDisposition.disposition
      }
      Copy-Item -LiteralPath (Join-Path $overlayCacheDir 'basis_build.json') -Destination $basisReport
      $twoLocalOverlayBuilds += [pscustomobject]@{
        overlay_id=$overlayId; geometry=$overlayGeometry; cache_role=$overlayRole; cache_key=$overlayKey; cache_dir=$overlayCacheDir
        cache_pa0=(Join-Path $overlayCacheDir ($overlayId + '.pa0')); gem=$twoLocalOverlay.gem; contract=$twoLocalOverlay.contract
        basis_builder=$basisBuilderFrozen; refiner=$refinerFrozen; interface_verifier=$interfaceVerifierFrozen; basis_report=$basisReport
        interface_report=(Join-Path $package.result_dir ("${overlayId}_interface_verification.json"))
        refine_dispatch_request=$refineDispatchRequest; refine_dispatch_plan=$refineDispatchPlan; refine_resource_usage=$refineResourceUsage
      }
    }
  }
  $isRestartFly2 = $isPrePulseRestart
  $particleInput = Join-Path $package.input_dir $(if ($isRestartFly2) {
      'single_flight_mother_sample.fly2'
    } else {
      'single_flight_mother_sample.ion'
    })
  $globalSource = Join-Path $package.input_dir 'single_flight_initial_global_state.csv'
  $particleRowMap = Join-Path $package.input_dir 'single_flight_particle_row_map.csv'
  $terminalHandoffReceiptFrozen = $null
  $sourceArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source',
    '--source',$motherSource,'--connection',$resolvedFrozen,'--particle-input',$particleInput,'--global-state',$globalSource,
    '--row-map',$particleRowMap,
    '--source-release-mode',$sourceReleaseMode)
  if ($isTerminalHandoffContinuation) {
    $terminalHandoffReceiptFrozen = Join-Path $package.input_dir 'terminal_handoff_continuation_receipt.json'
    $sourceArguments += @('--handoff-mass-amu',([string]$TerminalHandoffMassAmu),
      '--handoff-charge-state',([string]$TerminalHandoffChargeState),
      '--handoff-receipt',$terminalHandoffReceiptFrozen)
    if ($TerminalHandoffSmokeSourceParticleId -gt 0) {
      $sourceArguments += @('--handoff-smoke-source-particle-id',
        ([string]$TerminalHandoffSmokeSourceParticleId))
    }
    if ($TerminalHandoffExecutionParticleCount -gt 0) {
      $sourceArguments += @('--handoff-execution-particle-count',
        ([string]$TerminalHandoffExecutionParticleCount))
    }
  }
  if ($isPrePulseRestart) {
    $sourceArguments += @('--pulse-time-us',([string]$pulseTimeUs))
  }
  Invoke-SingleFlightPython -Arguments $sourceArguments `
    -Failure 'Single-flight source materialization failed.'
  if ($isTerminalHandoffContinuation) {
    $terminalHandoffReceipt = Get-Content -LiteralPath $terminalHandoffReceiptFrozen `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedTerminalLossCount = if ($TerminalHandoffUpstreamLossCount -ge 0) {
      $TerminalHandoffUpstreamLossCount
    } else { $PopulationDenominatorCount - $launched }
    if ($terminalHandoffReceipt.role -ne 'rf_oatof_terminal_handoff_continuation_receipt' -or
        [int]$terminalHandoffReceipt.mother_particle_count -ne $TerminalHandoffMotherParticleCount -or
        [int]$terminalHandoffReceipt.continued_particle_count -ne $launched -or
        [int]$terminalHandoffReceipt.upstream_loss_count -ne $expectedTerminalLossCount) {
      throw 'Terminal-handoff continuation materialization receipt differs from population authority.'
    }
    if ($TerminalHandoffSmokeSourceParticleId -gt 0 -and
        [int]$terminalHandoffReceipt.smoke_source_particle_id -ne $TerminalHandoffSmokeSourceParticleId) {
      throw 'Terminal-handoff smoke particle identity differs from the frozen request.'
    }
    if ($TerminalHandoffExecutionParticleCount -gt 0 -and
        [int]$terminalHandoffReceipt.execution_particle_count -ne $TerminalHandoffExecutionParticleCount) {
      throw 'Terminal-handoff execution population differs from the frozen request.'
    }
  }

  $runtimeDir = Join-Path $package.run_dir 'simion'
  function Copy-RfPaCacheFamilyToRuntime {
    param([Parameter(Mandatory)][string]$CacheDirectory,[Parameter(Mandatory)][string]$Pattern)
    foreach ($source in Get-ChildItem -LiteralPath $CacheDirectory -Filter $Pattern -File) {
      $target = Join-Path $runtimeDir $source.Name
      Copy-Item -LiteralPath $source.FullName -Destination $target -Force
      Set-RfMaterializedCacheFileWritable -Path $target
    }
  }
  $formalDir = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer\formal\simion'
  Copy-RfOatofFormalPaSet -FormalDir $formalDir -Destination $runtimeDir
  foreach ($domainSplitFineBuild in $domainSplitFineBuilds) {
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $domainSplitFineBuild.cache_dir `
      -Pattern ($domainSplitFineBuild.name + '.pa*')
    $domainSplitFineBuild.pa0 = Join-Path $runtimeDir ($domainSplitFineBuild.name + '.pa0')
  }
  $reflectronBuilderFrozen = $null
  $reflectronGemFrozen = $null
  $reflectronRefinerFrozen = $null
  $reflectronPa0 = Join-Path $runtimeDir 'reflectron.pa0'
  $reflectronBuildStdout = $null
  $reflectronBuildStderr = $null
  $flightTubeBuilderFrozen = $null
  $flightTubeGemFrozen = $null
  $flightTubeBuildStdout = $null
  $flightTubeBuildStderr = $null
  $downstreamCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\simion_oatof_downstream_pa"
  $flightTubeBuilderSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\build_flight_tube_variant.lua'
  $flightTubeGemSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\oatof_flight_tube_ground.gem'
  $reflectronBuilderSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\build_reflectron_variant.lua'
  $reflectronGemSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\oatof_reflectron_ideal_10_5.gem'
  $reflectronRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
  function Get-DownstreamCachePlan {
    param(
      [Parameter(Mandatory)][string]$Kind,
      [Parameter(Mandatory)][string]$Role,
      [Parameter(Mandatory)][string]$Builder,
      [Parameter(Mandatory)][string]$Gem,
      [Parameter(Mandatory)]$CriticalOptions,
      [Parameter(Mandatory)][string]$GeometryIdentitySha256,
      [string]$Additional=''
    )
    $additionalHash = if ([string]::IsNullOrWhiteSpace($Additional)) { '' } else { (Get-FileHash -LiteralPath $Additional -Algorithm SHA256).Hash }
    $identity = [ordered]@{
      schema_version=2; role=$Role
      project_id=$runProjectId; solver=$simionSolverCacheIdentity
      inputs=[ordered]@{
        pa_build_geometry_sha256=$GeometryIdentitySha256
        builder_sha256=(Get-FileHash -LiteralPath $Builder -Algorithm SHA256).Hash
        gem_sha256=(Get-FileHash -LiteralPath $Gem -Algorithm SHA256).Hash
        additional_builder_sha256=$additionalHash
      }
      critical_options=$CriticalOptions
    }
    $key = Get-RfContentIdentitySha256 -Identity $identity
    return [pscustomobject]@{
      kind=$Kind;role=$Role;identity=$identity;key=$key
      directory=(Join-Path $downstreamCacheRoot $key)
      pa0=(Join-Path (Join-Path $downstreamCacheRoot $key) "$Kind.pa0")
    }
  }
  $geometry = $oatofGeometryDocument.geometry_mm
  $flightBuild = $oatofGeometryDocument.simion_geometry_build.flight_tube
  $reflectronBuild = $oatofGeometryDocument.simion_geometry_build.reflectron
  $rings = $oatofGeometryDocument.rings
  $voltage = $oatofGeometryDocument.electrodes_V
  # The flight-tube PA is a single grounded shield.  Its builder consumes only
  # these mesh and geometry values; electrode potentials are applied by the
  # runtime field contract and must not create a duplicate PA-cache identity.
  $flightTubeGeometryIdentity = Get-RfFlightTubePaBuildGeometryIdentity `
    -Geometry $geometry -Build $flightBuild
  $flightTubeGeometryIdentitySha256 = Get-RfContentIdentitySha256 `
    -Identity $flightTubeGeometryIdentity
  $reflectronGeometryIdentitySha256 = (Get-FileHash -LiteralPath $oatofGeometry `
    -Algorithm SHA256).Hash
  $flightTubeCachePlan = Get-DownstreamCachePlan -Kind 'flight_tube_ground' `
    -Role 'simion_oatof_flight_tube_pa_cache' -Builder $flightTubeBuilderSource `
    -GeometryIdentitySha256 $flightTubeGeometryIdentitySha256 `
    -Gem $flightTubeGemSource -CriticalOptions ([ordered]@{
      builder_mode='flight_tube_variant';cell_axial_mm=[double]$flightBuild.cell_axial_mm
      cell_radial_mm=[double]$flightBuild.cell_radial_mm;max_gib=[double]$flightBuild.max_gib
      flight_tube_radius_mm=[double]$geometry.flight_tube_r
      flight_tube_wall_mm=[double]$geometry.flight_tube_wall
      shield_endcap_thickness_mm=[double]$geometry.shield_endcap_thickness
      shield_outer_z_min_mm=[double]$geometry.shield_outer_z_min
      flight_length_mm=[double]$geometry.L_flight
      invocation=@('--nogui','--noprompt','lua','build_flight_tube_variant.lua')
    })
  $reflectronCachePlan = Get-DownstreamCachePlan -Kind 'reflectron' `
    -Role 'simion_oatof_reflectron_pa_cache' -Builder $reflectronBuilderSource `
    -GeometryIdentitySha256 $reflectronGeometryIdentitySha256 `
    -Gem $reflectronGemSource -Additional $reflectronRefinerSource `
    -CriticalOptions ([ordered]@{
      builder_mode='initialize-only';cell_axial_mm=[double]$reflectronBuild.cell_axial_mm
      cell_radial_mm=[double]$reflectronBuild.cell_radial_mm;max_gib=[double]$reflectronBuild.max_gib
      stage1_count=[int]$rings.stage1_count;stage2_count=[int]$rings.stage2_count
      refinement_convergence='simion_official_default';midgrid_voltage_V=[double]$voltage.midgrid
      backplate_voltage_V=[double]$voltage.backplate
      invocation=@('--nogui','--noprompt','lua','build_reflectron_variant.lua')
      fast_adjust_mode='explicit_ring_voltage_assignments'
    })
  $flightTubeCachePa0 = $flightTubeCachePlan.pa0
  $reflectronCachePa0 = $reflectronCachePlan.pa0
  $flightTubeCacheDir = $flightTubeCachePlan.directory
  $reflectronCacheDir = $reflectronCachePlan.directory
  if ($isPrePulseTimeSeriesScreening) {
    $identity = $prePulseTimeSeries.identities
    # v2 introduced runtime-verified cache identities; v3 adds two local
    # overlays and v4 records the four disjoint long-gap PA roles.
    $cacheKeys = if ([int]$prePulseTimeSeries.schema_version -in @(2, 3, 4)) {
      $roles = $prePulseTimeSeries.pa_cache_roles
      $expectedPrePulseRoles = if ($domainSplitEnabled) {
        'full_coarse_bridge,fine_upstream,accelerator_main,accelerator_intermediate2_overlay'
      } elseif ($overlayLayout -eq 'two_local_v1') {
        'frontend,accelerator_entrance_overlay,accelerator_intermediate_overlay'
      } else { 'frontend,accelerator_overlay' }
      if ([string]$roles.identity_source -ne
          'runner_materialized_verified_pa_cache_receipt' -or
          (@($roles.required) -join ',') -ne $expectedPrePulseRoles -or
          (@($roles.prohibited) -join ',') -ne 'flight_tube,reflectron') {
        throw 'Pre-pulse time-series PA cache role policy differs.'
      }
      $resolvedCacheKeys = [ordered]@{flight_tube=$null;reflectron=$null}
      if ($domainSplitEnabled) {
        $domainProgramOverlay = @($twoLocalOverlayBuilds | Where-Object { $_.overlay_id -eq 'accelerator_intermediate_overlay' })
        $domainFineUpstream = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'upstream_bridge' })
        $domainFineMain = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'accelerator_main' })
        if ($domainProgramOverlay.Count -ne 1 -or $domainFineUpstream.Count -ne 1 -or $domainFineMain.Count -ne 1) {
          throw 'Pre-pulse domain-split PA cache family is incomplete.'
        }
        $resolvedCacheKeys.full_coarse_bridge = $frontendCacheKey
        $resolvedCacheKeys.fine_upstream = $domainFineUpstream[0].cache_key
        $resolvedCacheKeys.accelerator_main = $domainFineMain[0].cache_key
        $resolvedCacheKeys.accelerator_intermediate2_overlay = $domainProgramOverlay[0].cache_key
      } elseif ($overlayLayout -eq 'two_local_v1') {
        $resolvedCacheKeys.frontend = $frontendCacheKey
        foreach ($twoLocalOverlayBuild in $twoLocalOverlayBuilds) {
          $resolvedCacheKeys[$twoLocalOverlayBuild.overlay_id] = $twoLocalOverlayBuild.cache_key
        }
      } else {
        $resolvedCacheKeys.frontend = $frontendCacheKey
        $resolvedCacheKeys.accelerator_overlay = $overlayKey
      }
      $resolvedCacheKeys
    } else {
      $prePulseTimeSeries.pa_cache_keys
    }
    $rfGrid = $prePulseTimeSeries.rf_time_grid
    $upstreamDocument = Get-Content -LiteralPath $upstreamFrozen -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $motherSourceActualSha256 = (Get-FileHash -LiteralPath $(if (
        $isTerminalHandoffContinuation) { $globalSource } else { $motherSource }) `
      -Algorithm SHA256).Hash
    $identityChecks = @(
      @([string]$identity.campaign_id,[string]$runtimePopulation.campaign_id),
      @([string]$identity.experiment_id,[string]$runtimePopulation.experiment_id),
      @([string]$identity.connection_profile_id,$ConnectionProfileId),
      @([string]$identity.source_profile_id,$SourceProfileId),
      @([string]$identity.resolved_source_contract_sha256,$ResolvedSourceContractSha256),
      @([string]$identity.resolved_population_contract_sha256,$ResolvedPopulationContractSha256),
      @([string]$identity.mother_particle_source_sha256,$motherSourceActualSha256),
      @([string]$identity.layout_profile_id,$LayoutProfileId),
      @([string]$identity.architecture_generation_id,$ArchitectureGenerationId),
      @([string]$identity.candidate_sha256,$ThreeZoneCandidateSha256),
      @([string]$identity.topology_id,$threeZoneTopologyId),
      @([string]$identity.geometry_id,$threeZoneGeometryId),
      @([string]$identity.frontend_electrode_topology_id,$threeZoneFrontendElectrodeTopologyId),
      @([string]$identity.field_id,$threeZoneFieldId),
      @([string]$identity.field_profile_id,$selectedFieldProfileId),
      @([string]$identity.region_field_semantic_sha256,$ResolvedRegionFieldSemanticSha256),
      @([string]$identity.frontend_grid_profile_id,$selectedGridProfileId),
      @([string]$identity.field_overlay_id,$resolvedFieldOverlayId),
      @([string]$identity.oatof_numerical_profile_id,$selectedOatofNumericalProfileId),
      @([string]$identity.trajectory_quality_profile_id,$selectedTrajectoryQualityProfileId),
      @([string]$identity.time_integration_profile_id,$selectedTimeIntegrationProfileId)
    )
    $prePulseCacheIdentityMatches = $null -eq $cacheKeys.flight_tube -and $null -eq $cacheKeys.reflectron
    if ($null -ne $cacheKeys.flight_tube -or $null -ne $cacheKeys.reflectron) {
      $prePulseCacheIdentityMatches = $false
    }
    if ($domainSplitEnabled) {
      $domainProgramOverlay = @($twoLocalOverlayBuilds | Where-Object { $_.overlay_id -eq 'accelerator_intermediate_overlay' })
      $domainFineUpstream = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'upstream_bridge' })
      $domainFineMain = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'accelerator_main' })
      $prePulseCacheIdentityMatches = $prePulseCacheIdentityMatches -and
        ([string]$cacheKeys.full_coarse_bridge -eq $frontendCacheKey) -and
        ($domainFineUpstream.Count -eq 1 -and [string]$cacheKeys.fine_upstream -eq [string]$domainFineUpstream[0].cache_key) -and
        ($domainFineMain.Count -eq 1 -and [string]$cacheKeys.accelerator_main -eq [string]$domainFineMain[0].cache_key) -and
        ($domainProgramOverlay.Count -eq 1 -and [string]$cacheKeys.accelerator_intermediate2_overlay -eq [string]$domainProgramOverlay[0].cache_key)
    } elseif ($overlayLayout -eq 'two_local_v1') {
      $prePulseCacheIdentityMatches = $prePulseCacheIdentityMatches -and ([string]$cacheKeys.frontend -eq $frontendCacheKey)
      foreach ($twoLocalOverlayBuild in $twoLocalOverlayBuilds) {
        $prePulseCacheIdentityMatches = $prePulseCacheIdentityMatches -and
          ([string]$cacheKeys.($twoLocalOverlayBuild.overlay_id) -eq [string]$twoLocalOverlayBuild.cache_key)
      }
    } else {
      $prePulseCacheIdentityMatches = $prePulseCacheIdentityMatches -and ([string]$cacheKeys.frontend -eq $frontendCacheKey) -and
        ([string]$cacheKeys.accelerator_overlay -eq [string]$overlayKey)
    }
    if (@($identityChecks | Where-Object { $_[0] -ne $_[1] }).Count -ne 0 -or -not $prePulseCacheIdentityMatches) {
      throw 'Pre-pulse time-series source/layout/field/PA identity differs.'
    }
    $sampleTimes = @($prePulseTimeSeries.sample_times_us | ForEach-Object {
      [double]$_
    })
    $frequencyHz = [double]$upstreamDocument.drive.frequency_Hz
    $periodUs = 1000000.0 / $frequencyHz
    $gridRfStepsPerPeriod = [int]$rfGrid.rf_steps_per_period
    if ($gridRfStepsPerPeriod -le 0) {
      throw 'Pre-pulse time-series RF step count must be positive.'
    }
    $stepUs = $periodUs / [double]$gridRfStepsPerPeriod
    $startIndex = [int]$rfGrid.start_index
    $endIndex = [int]$rfGrid.end_index
    if ([string]$rfGrid.waveform -ne [string]$upstreamDocument.drive.waveform -or
        [double]$rfGrid.frequency_hz -ne $frequencyHz -or
        [double]$rfGrid.phase_rad -ne [double]$upstreamDocument.drive.phase_rad -or
        $rfStepsPerPeriod -ne $gridRfStepsPerPeriod -or
        [Math]::Abs([double]$rfGrid.period_us - $periodUs) -gt 1e-12 -or
        [Math]::Abs([double]$rfGrid.step_us - $stepUs) -gt 1e-12 -or
        $startIndex -lt 0 -or $endIndex -lt $startIndex -or
        $sampleTimes.Count -ne ($endIndex - $startIndex + 1)) {
      throw 'Pre-pulse time-series native solver time-grid identity differs.'
    }
    for ($index = 0; $index -lt $sampleTimes.Count; $index++) {
      $expectedTime = [double]$rfGrid.grid_origin_us +
        ($startIndex + $index) * $stepUs
      if ([Math]::Abs($sampleTimes[$index] - $expectedTime) -gt
          (1e-12 * [Math]::Max(1.0,[Math]::Abs($expectedTime)))) {
        throw 'Pre-pulse time-series sample time differs from the frozen native solver grid.'
      }
      if ($index -gt 0 -and $sampleTimes[$index] -le $sampleTimes[$index - 1]) {
        throw 'Pre-pulse time-series sample times are not strictly increasing.'
      }
    }
  }
  function Copy-RfPaFamilyAliasInRuntime {
    param(
      [Parameter(Mandatory)][string]$SourcePrefix,
      [Parameter(Mandatory)][string]$DestinationPrefix,
      [string]$SourceDirectory=$runtimeDir
    )
    $members = @(Get-ChildItem -LiteralPath $SourceDirectory -Filter ($SourcePrefix + '.pa*') -File)
    if ($members.Count -eq 0) {
      throw "PA family alias source is missing: $SourcePrefix"
    }
    foreach ($member in $members) {
      $suffix = $member.Name.Substring($SourcePrefix.Length)
      $destination = Join-Path $runtimeDir ($DestinationPrefix + $suffix)
      Copy-Item -LiteralPath $member.FullName -Destination $destination -Force
      Set-RfMaterializedCacheFileWritable -Path $destination
    }
  }
  function Publish-DownstreamPaCacheFamily {
    param([Parameter(Mandatory)]$Plan,[Parameter(Mandatory)][string]$Pattern)
    $staging = New-RfCacheStagingDirectory -CacheRoot $downstreamCacheRoot
    try {
      foreach ($source in Get-ChildItem -LiteralPath $runtimeDir -Filter $Pattern -File) {
        $destination = Join-Path $staging $source.Name
        Copy-Item -LiteralPath $source.FullName -Destination $destination
      }
      return Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot `
        -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
        -CacheRoot $downstreamCacheRoot -CacheKey $Plan.key -Role $Plan.role `
        -Identity $Plan.identity -StagingDirectory $staging -ProviderRunId $RunId
    } catch {
      if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
      throw
    }
  }
  $flightTubeCacheUsed = $false
  $reflectronCacheUsed = $false
  if ($hasFlightTubeRebuild) {
    $paCacheDispositions.flight_tube.key = $flightTubeCachePlan.key
  }
  if ($hasReflectronRebuild) {
    $paCacheDispositions.reflectron.key = $reflectronCachePlan.key
  }
  $flightTubeCacheDir = if ($hasFlightTubeRebuild) { Resolve-RfReusableCacheDirectory -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $downstreamCacheRoot -CacheKey $flightTubeCachePlan.key `
      -Role $flightTubeCachePlan.role `
      -Identity $flightTubeCachePlan.identity `
      -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'}) }
  $flightTubeCacheDir = Resolve-RfBoundGenerationDirectory -CacheRoot $downstreamCacheRoot `
    -CacheKey $flightTubeCachePlan.key -Role $flightTubeCachePlan.role `
    -ReusableDirectory $flightTubeCacheDir
  $flightTubeCacheHit = -not [string]::IsNullOrWhiteSpace($flightTubeCacheDir)
  if ($hasFlightTubeRebuild -and -not $flightTubeCacheHit -and
      $PaCachePolicy -eq 'require_existing') {
    $paCacheDispositions.flight_tube.disposition = 'cache_miss_required_existing'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_miss'
    throw "Required PA cache MISS or damage: role=$($flightTubeCachePlan.role) key=$($flightTubeCachePlan.key)"
  }
  if ($flightTubeCacheHit) {
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $flightTubeCacheDir -Pattern 'flight_tube_ground.pa*'
    $flightTubeCacheUsed = $true
    $hasFlightTubeRebuild = $false
    $paCacheDispositions.flight_tube.disposition = 'cache_hit'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_hit'
  }
  $reflectronCacheDir = if ($hasReflectronRebuild) { Resolve-RfReusableCacheDirectory -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $downstreamCacheRoot -CacheKey $reflectronCachePlan.key `
      -Role $reflectronCachePlan.role `
      -Identity $reflectronCachePlan.identity `
      -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'}) }
  $reflectronCacheDir = Resolve-RfBoundGenerationDirectory -CacheRoot $downstreamCacheRoot `
    -CacheKey $reflectronCachePlan.key -Role $reflectronCachePlan.role `
    -ReusableDirectory $reflectronCacheDir
  $reflectronCacheHit = -not [string]::IsNullOrWhiteSpace($reflectronCacheDir)
  if ($hasReflectronRebuild -and -not $reflectronCacheHit -and
      $PaCachePolicy -eq 'require_existing') {
    $paCacheDispositions.reflectron.disposition = 'cache_miss_required_existing'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_miss'
    throw "Required PA cache MISS or damage: role=$($reflectronCachePlan.role) key=$($reflectronCachePlan.key)"
  }
  if ($reflectronCacheHit) {
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $reflectronCacheDir -Pattern 'reflectron.pa*'
    $reflectronCacheUsed = $true
    $hasReflectronRebuild = $false
    $paCacheDispositions.reflectron.disposition = 'cache_hit'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_hit'
  }
  if ($overlayEnabled -and $overlayLayout -eq 'whole_accelerator_v1') {
    $overlayCachePaSharp = Join-Path $overlayCacheDir 'accelerator_overlay.pa#'
    $overlayCachePa0 = Join-Path $overlayCacheDir 'accelerator_overlay.pa0'
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $overlayCacheDir `
      -Pattern 'accelerator_overlay.pa*'
    $activePaCaches = @(
      [ordered]@{role=$frontendCacheRole;cache_key=$frontendCacheKey;cache_directory=$cacheDir}
    )
    $activePaCaches += [ordered]@{
      role=$overlayCacheRole;cache_key=$overlayKey;cache_directory=$overlayCacheDir
    }
    if ($flightTubeCacheUsed) {
      $activePaCaches += [ordered]@{
        role=$flightTubeCachePlan.role;cache_key=$flightTubeCachePlan.key;cache_directory=$flightTubeCacheDir
      }
    }
    if ($reflectronCacheUsed) {
      $activePaCaches += [ordered]@{
        role=$reflectronCachePlan.role;cache_key=$reflectronCachePlan.key;cache_directory=$reflectronCacheDir
      }
    }
    Assert-RfExactPaCacheGenerationBinding -ActiveCaches $activePaCaches
    $overlayRuntimePa0 = Join-Path $runtimeDir 'accelerator_overlay.pa0'
    $overlayVerify = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
      -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_interface_verify_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_interface_verify.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'overlay_interface_verify.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','lua',$overlayInterfaceVerifierFrozen,$frontendWorkingPa0,$overlayRuntimePa0,
        ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
        ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),'19',$overlayInterfaceReport)
    if ($overlayVerify.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay interface verification exceeded its resource budget.' }
    if ($overlayVerify.exit_code -ne 0) { throw 'Overlay interface verification failed.' }
  }
  if ($domainSplitEnabled) {
    $domainProgramOverlay = @($twoLocalOverlayBuilds | Where-Object { $_.overlay_id -eq 'accelerator_intermediate_overlay' })
    if ($domainProgramOverlay.Count -ne 1) { throw 'Domain-split Program intermediate overlay is missing.' }
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $domainProgramOverlay[0].cache_dir -Pattern 'accelerator_intermediate_overlay.pa*'
  } elseif ($overlayEnabled -and $overlayLayout -eq 'two_local_v1') {
    $activePaCaches = @([ordered]@{role=$frontendCacheRole;cache_key=$frontendCacheKey;cache_directory=$cacheDir})
    foreach ($twoLocalOverlayBuild in $twoLocalOverlayBuilds) {
      Copy-RfPaCacheFamilyToRuntime -CacheDirectory $twoLocalOverlayBuild.cache_dir `
        -Pattern ($twoLocalOverlayBuild.overlay_id + '.pa*')
      $activePaCaches += [ordered]@{role=$twoLocalOverlayBuild.cache_role;cache_key=$twoLocalOverlayBuild.cache_key;cache_directory=$twoLocalOverlayBuild.cache_dir}
      $overlayRuntimePa0 = Join-Path $runtimeDir ($twoLocalOverlayBuild.overlay_id + '.pa0')
      $overlayVerify = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir ($twoLocalOverlayBuild.overlay_id + '_interface_verify_resource_usage.json')) `
        -FilePath $SimionExe -WorkingDirectory $runtimeDir `
        -RedirectStandardOutput (Join-Path $package.log_dir ($twoLocalOverlayBuild.overlay_id + '_interface_verify.stdout.log')) `
        -RedirectStandardError (Join-Path $package.log_dir ($twoLocalOverlayBuild.overlay_id + '_interface_verify.stderr.log')) `
        -ArgumentList @('--nogui','--noprompt','lua',$twoLocalOverlayBuild.interface_verifier,$frontendWorkingPa0,$overlayRuntimePa0,
          ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
          ([string]$twoLocalOverlayBuild.geometry.instance_origin_mm.x),([string]$twoLocalOverlayBuild.geometry.instance_origin_mm.y),([string]$twoLocalOverlayBuild.geometry.instance_origin_mm.z),
          '19',$twoLocalOverlayBuild.interface_report)
      if ($overlayVerify.resource_budget_exceeded -or $overlayVerify.exit_code -ne 0) { throw "$($twoLocalOverlayBuild.overlay_id) interface verification failed." }
    }
    if ($flightTubeCacheUsed) { $activePaCaches += [ordered]@{role=$flightTubeCachePlan.role;cache_key=$flightTubeCachePlan.key;cache_directory=$flightTubeCacheDir} }
    if ($reflectronCacheUsed) { $activePaCaches += [ordered]@{role=$reflectronCachePlan.role;cache_key=$reflectronCachePlan.key;cache_directory=$reflectronCacheDir} }
    Assert-RfExactPaCacheGenerationBinding -ActiveCaches $activePaCaches
  }
  if (-not $overlayEnabled) {
    $activePaCaches = @(
      [ordered]@{role=$frontendCacheRole;cache_key=$frontendCacheKey;cache_directory=$cacheDir}
    )
    if ($flightTubeCacheUsed) {
      $activePaCaches += [ordered]@{
        role=$flightTubeCachePlan.role;cache_key=$flightTubeCachePlan.key;cache_directory=$flightTubeCacheDir
      }
    }
    if ($reflectronCacheUsed) {
      $activePaCaches += [ordered]@{
        role=$reflectronCachePlan.role;cache_key=$reflectronCachePlan.key;cache_directory=$reflectronCacheDir
      }
    }
    Assert-RfExactPaCacheGenerationBinding -ActiveCaches $activePaCaches
  }
  # In a long-gap domain split the coarse frontend aperture is expressly
  # non-authoritative.  The mechanical aperture and its local edge field are
  # realized only by accelerator_main, so inspect that materialized fine PA.
  $apertureTopologyPa = $frontendWorkingPa0
  $apertureTopologyGeometry = $frontendGeometry
  $apertureTopologyDiscretization = $apertureDiscretization
  if ($domainSplitEnabled) {
    $domainApertureMain = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'accelerator_main' })
    if ($domainApertureMain.Count -ne 1 -or [string]::IsNullOrWhiteSpace($domainApertureMain[0].pa0)) {
      throw 'Domain-split aperture topology check requires accelerator-main PA.'
    }
    $apertureTopologyPa = [string]$domainApertureMain[0].pa0
    $apertureTopologyGeometry = $domainApertureMain[0].geometry
    $apertureTopologyDiscretization =
      $apertureTopologyGeometry.accelerator_port_aperture.discretization
    if ($null -eq $apertureTopologyDiscretization) {
      throw 'Domain-split accelerator-main aperture discretization is missing.'
    }
  }
  $topologyResult = Invoke-SimionCompiledApertureTopologyCheck `
    -PaPath $apertureTopologyPa -ReportPath $apertureTopologyReport -VerifierPath $apertureVerifier `
    -OriginXmm ([double]$apertureTopologyGeometry.instance_origin_mm.x) `
    -OriginYmm ([double]$apertureTopologyGeometry.instance_origin_mm.y) `
    -OriginZmm ([double]$apertureTopologyGeometry.instance_origin_mm.z) `
    -CellMmX ([double]$apertureTopologyGeometry.cell_mm_xyz.x) `
    -CellMmY ([double]$apertureTopologyGeometry.cell_mm_xyz.y) `
    -CellMmZ ([double]$apertureTopologyGeometry.cell_mm_xyz.z) `
    -FlangeXMinMm ([double]$apertureTopologyDiscretization.flange_x_min_mm) `
    -FlangeXMaxMm ([double]$apertureTopologyDiscretization.flange_x_max_mm) `
    -CenterYmm ([double]$frontendGeometry.source_exit_center_mm.y) `
    -CenterZmm ([double]$frontendGeometry.source_exit_center_mm.z) `
    -MechanicalWidthMm $apertureWidthMm -MechanicalHeightMm $apertureHeightMm `
    -BooleanBoundaryPolicy ([string]$apertureTopologyDiscretization.boolean_boundary_policy) `
    -InvokeVerifier {
      param($verifierPath)
      Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir 'frontend_aperture_topology_resource_usage.json') -FilePath $SimionExe `
        -WorkingDirectory (Split-Path -Parent $apertureTopologyPa) -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_aperture_topology.stdout.log') `
        -RedirectStandardError (Join-Path $package.log_dir 'frontend_aperture_topology.stderr.log') `
        -ArgumentList @('--nogui','--noprompt','lua',$verifierPath)
    }
  $apertureTopology = $topologyResult.audit
  if ($hasFlightTubeRebuild) {
    $paCacheDispositions.flight_tube.disposition = 'cache_miss_build_authorized'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_build_authorized'
    $flightTubeBuilderFrozen = Join-Path $package.input_dir 'build_flight_tube_variant.lua'
    $flightTubeGemFrozen = Join-Path $package.input_dir 'oatof_flight_tube_ground.gem'
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $flightTubeBuilderSource `
      -Destination $flightTubeBuilderFrozen -Role 'candidate flight-tube SIMION builder' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $flightTubeGemSource `
      -Destination $flightTubeGemFrozen -Role 'candidate flight-tube SIMION GEM' | Out-Null
    $flightTubeBuildStdout = Join-Path $package.log_dir 'flight_tube_build.stdout.log'
    $flightTubeBuildStderr = Join-Path $package.log_dir 'flight_tube_build.stderr.log'
    $geometry = $oatofGeometryDocument.geometry_mm
    $build = $oatofGeometryDocument.simion_geometry_build.flight_tube
    $flightTubeBuild = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'flight_tube_build_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput $flightTubeBuildStdout `
      -RedirectStandardError $flightTubeBuildStderr -ArgumentList @(
        '--nogui','--noprompt','lua',$flightTubeBuilderFrozen,$flightTubeGemFrozen,
        (Join-Path $runtimeDir 'flight_tube_ground.pa#'),
        ([string]$build.cell_axial_mm),([string]$build.cell_radial_mm),
        ([string]$build.max_gib),([string]$geometry.flight_tube_r),
        ([string]$geometry.flight_tube_wall),
        ([string]$geometry.shield_endcap_thickness),
        ([string]$geometry.shield_outer_z_min),([string]$geometry.L_flight))
    if ($flightTubeBuild.resource_budget_exceeded) {
      $resourceBudgetExceeded=$true
      throw 'Candidate flight-tube PA build exceeded its resource budget.'
    }
    if ($flightTubeBuild.exit_code -ne 0 -or
        -not (Test-Path -LiteralPath (Join-Path $runtimeDir 'flight_tube_ground.pa0') -PathType Leaf)) {
      throw 'Candidate flight-tube PA build failed.'
    }
    $flightTubeCacheDir = Publish-DownstreamPaCacheFamily `
      -Plan $flightTubeCachePlan -Pattern 'flight_tube_ground.pa*'
    $flightTubeCacheUsed = $true
    $paCacheDispositions.flight_tube.disposition = 'built_and_published'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_published'
  }
  if ($hasReflectronRebuild) {
    $paCacheDispositions.reflectron.disposition = 'cache_miss_build_authorized'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_build_authorized'
    $reflectronBuilderFrozen = Join-Path $package.input_dir 'build_reflectron_variant.lua'
    $reflectronGemFrozen = Join-Path $package.input_dir 'oatof_reflectron_ideal_10_5.gem'
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $reflectronBuilderSource `
      -Destination $reflectronBuilderFrozen -Role 'candidate reflectron SIMION builder' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $reflectronGemSource `
      -Destination $reflectronGemFrozen -Role 'candidate reflectron SIMION GEM' | Out-Null
    $reflectronRefinerFrozen = Join-Path $package.input_dir 'refine_single_pa.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $reflectronRefinerSource `
      -Destination $reflectronRefinerFrozen -Role 'candidate reflectron segmented refiner' | Out-Null
    $reflectronBuildStdout = Join-Path $package.log_dir 'reflectron_build.stdout.log'
    $reflectronBuildStderr = Join-Path $package.log_dir 'reflectron_build.stderr.log'
    $geometry = $oatofGeometryDocument.geometry_mm
    $build = $oatofGeometryDocument.simion_geometry_build.reflectron
    $rings = $oatofGeometryDocument.rings
    $voltage = $oatofGeometryDocument.electrodes_V
    $reflectronBuild = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'reflectron_build_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput $reflectronBuildStdout `
      -RedirectStandardError $reflectronBuildStderr -ArgumentList @(
        '--nogui','--noprompt','lua',$reflectronBuilderFrozen,$reflectronGemFrozen,
        (Join-Path $runtimeDir 'reflectron.pa#'),
        ([string]$build.cell_axial_mm),([string]$build.cell_radial_mm),
        ([string]$build.max_gib),([string]$geometry.flight_tube_r),
        ([string]$geometry.flight_tube_wall),([string]$geometry.L_reflectron),
        ([string]$geometry.ring_thickness),([string]$geometry.shield_axial_gap),
        ([string]$geometry.shield_endcap_thickness),([string]$geometry.L_stage1),
        ([string]$geometry.L_stage2),([string]$geometry.bore_r),
        ([string]$geometry.ring_outer_r),([string]$rings.stage1_count),
        ([string]$rings.stage2_count),([string]$voltage.midgrid),
        ([string]$voltage.backplate),'initialize-only')
    if ($reflectronBuild.resource_budget_exceeded) {
      $resourceBudgetExceeded=$true
      throw 'Candidate reflectron PA build exceeded its resource budget.'
    }
    if ($reflectronBuild.exit_code -ne 0) {
      throw 'Candidate reflectron PA initialization failed.'
    }
    $maximumReflectronElectrode = 4 + [int]$rings.stage1_count + [int]$rings.stage2_count
    foreach ($electrode in 0..$maximumReflectronElectrode) {
      $singlePa = Join-Path $runtimeDir "reflectron.pa$electrode"
      $singleRefine = Invoke-ResourceBudgetedProcess `
        -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir "reflectron_refine_pa${electrode}_resource_usage.json") `
        -FilePath $SimionExe -WorkingDirectory $runtimeDir `
        -RedirectStandardOutput (Join-Path $package.log_dir "reflectron_refine_pa${electrode}.stdout.log") `
        -RedirectStandardError (Join-Path $package.log_dir "reflectron_refine_pa${electrode}.stderr.log") `
        -ArgumentList @('--nogui','--noprompt','lua',$reflectronRefinerFrozen,$singlePa)
      if ($singleRefine.resource_budget_exceeded) {
        $resourceBudgetExceeded=$true
        throw "Candidate reflectron pa$electrode refine exceeded its resource budget."
      }
      if ($singleRefine.exit_code -ne 0) {
        throw "Candidate reflectron pa$electrode segmented refine failed."
      }
    }
    $reflectronAssignmentsPath = Join-Path $package.input_dir `
      'reflectron_fast_adjust_assignments.json'
    Invoke-SingleFlightPython -Arguments @(
      '-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
      '--reflectron-fast-adjust-oatof',$oatofGeometry,
      '--reflectron-fast-adjust-output',$reflectronAssignmentsPath
    ) -Failure 'Reflectron fast-adjust assignment compilation failed.'
    $assignmentsDocument = Get-Content -LiteralPath $reflectronAssignmentsPath `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($assignmentsDocument.role -ne
        'rf_oatof_reflectron_fast_adjust_assignments' -or
        @($assignmentsDocument.assignments).Count -ne
        ($maximumReflectronElectrode + 1)) {
      throw 'Reflectron fast-adjust assignments are incomplete.'
    }
    $assignments = @($assignmentsDocument.assignments | ForEach-Object { [string]$_ })
    $fastAdjust = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'reflectron_fast_adjust_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput (Join-Path $package.log_dir 'reflectron_fast_adjust.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'reflectron_fast_adjust.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','fastadj',$reflectronPa0,($assignments -join ','))
    if ($fastAdjust.resource_budget_exceeded) {
      $resourceBudgetExceeded=$true
      throw 'Candidate reflectron fast-adjust exceeded its resource budget.'
    }
    if ($fastAdjust.exit_code -ne 0 -or
        -not (Test-Path -LiteralPath $reflectronPa0 -PathType Leaf)) {
      throw 'Candidate reflectron fast-adjust failed.'
    }
    $reflectronCacheDir = Publish-DownstreamPaCacheFamily `
      -Plan $reflectronCachePlan -Pattern 'reflectron.pa*'
    $reflectronCacheUsed = $true
    $paCacheDispositions.reflectron.disposition = 'built_and_published'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_published'
  }
  $overlayIobBuilderFrozen = $null
  $overlayIobContainerFrozen = $null
  $overlayIobContainerGemFrozen = @()
  $totalAxisFieldIob = $null
  if ($overlayEnabled -and $overlayLayout -eq 'whole_accelerator_v1') {
    $overlayIobBuilderSource = Join-Path $PSScriptRoot 'build_single_flight_overlay_iob.lua'
    $overlayIobBuilderFrozen = Join-Path $package.input_dir 'build_single_flight_overlay_iob.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayIobBuilderSource `
      -Destination $overlayIobBuilderFrozen -Role 'single-flight overlay IOB builder' | Out-Null
    $overlayIobContainerSourceDir = Join-Path (Split-Path -Parent $SimionExe) 'examples\magnetic_potential'
    $overlayIobContainerSource = Join-Path $overlayIobContainerSourceDir 'mag_quad_2dp.iob'
    if (-not (Test-Path -LiteralPath $overlayIobContainerSource -PathType Leaf)) {
      throw 'SIMION-distributed five-instance IOB container is missing.'
    }
    $overlayContainerFrozenDir = Join-Path $package.input_dir 'simion_five_instance_container'
    New-Item -ItemType Directory -Path $overlayContainerFrozenDir -Force | Out-Null
    $overlayIobContainerFrozen = Join-Path $overlayContainerFrozenDir 'mag_quad_2dp.iob'
    Copy-Item -LiteralPath $overlayIobContainerSource -Destination $overlayIobContainerFrozen
    foreach ($seedName in @('mag_quad_2dp.gem','mag_quad_2dp-Mx.gem','mag_quad_2dp-My.gem','mag_quad_2dp-j.gem','mag_quad_2dp-mu.gem')) {
      $seedFrozen = Join-Path $overlayContainerFrozenDir $seedName
      Copy-Item -LiteralPath (Join-Path $overlayIobContainerSourceDir $seedName) -Destination $seedFrozen
      $overlayIobContainerGemFrozen += $seedFrozen
    }
    # SIMION 2020's bundled GEM preprocessor cannot create its intermediate
    # *.processed.gem beside a container whose absolute path is too long.
    # Keep the governed evidence in the run and use a short, disposable copy
    # only while replacing the five placeholder instances.
    $overlayIobStageRoot = Join-Path $workspaceRoot 'scratch\simion_iob'
    $overlayIobStageDir = New-RfCacheStagingDirectory -CacheRoot $overlayIobStageRoot
    try {
      Get-ChildItem -LiteralPath $overlayContainerFrozenDir -File |
        Copy-Item -Destination $overlayIobStageDir
      $overlayIobContainerRuntime = Join-Path $overlayIobStageDir 'mag_quad_2dp.iob'
      $overlayIobBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
        -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_iob_build_resource_usage.json') `
        -FilePath $SimionExe -WorkingDirectory $runtimeDir `
        -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_iob_build.stdout.log') `
        -RedirectStandardError (Join-Path $package.log_dir 'overlay_iob_build.stderr.log') `
        -ArgumentList @('--nogui','--noprompt','lua',$overlayIobBuilderFrozen,
          (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),$overlayIobContainerRuntime,
          (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),
          (Join-Path $runtimeDir 'flight_tube_ground.pa0'),(Join-Path $runtimeDir 'reflectron.pa0'),
          (Join-Path $runtimeDir 'accelerator.pa0'),(Join-Path $runtimeDir 'detector_ground.pa0'),
          (Join-Path $runtimeDir 'accelerator_overlay.pa0'),
          ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),
          (Join-Path $runtimeDir 'oatof_ideal_grounded.lua'),(Join-Path $runtimeDir 'oatof_ideal_grounded.fly2'))
      if ($overlayIobBuild.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay IOB build exceeded its resource budget.' }
      if ($overlayIobBuild.exit_code -ne 0) { throw 'Overlay IOB build failed.' }
      if ($ProgramAxisFieldExport) {
        # Same five PA files and transforms as the runnable IOB, but no
        # same-basename Program/Fly2 for SIMION to auto-run during top-level Lua.
        $totalAxisFieldIob = Join-Path $runtimeDir 'total_axis_field.iob'
        $axisFieldIobBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
          -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'total_axis_field_iob_build_resource_usage.json') `
          -FilePath $SimionExe -WorkingDirectory $runtimeDir `
          -RedirectStandardOutput (Join-Path $package.log_dir 'total_axis_field_iob_build.stdout.log') `
          -RedirectStandardError (Join-Path $package.log_dir 'total_axis_field_iob_build.stderr.log') `
          -ArgumentList @('--nogui','--noprompt','lua',$overlayIobBuilderFrozen,
            (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),$overlayIobContainerRuntime,$totalAxisFieldIob,
            (Join-Path $runtimeDir 'flight_tube_ground.pa0'),(Join-Path $runtimeDir 'reflectron.pa0'),
            (Join-Path $runtimeDir 'accelerator.pa0'),(Join-Path $runtimeDir 'detector_ground.pa0'),
            (Join-Path $runtimeDir 'accelerator_overlay.pa0'),
            ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z))
        if ($axisFieldIobBuild.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Total-axis-field IOB build exceeded its resource budget.' }
        if ($axisFieldIobBuild.exit_code -ne 0 -or -not (Test-Path -LiteralPath $totalAxisFieldIob -PathType Leaf)) { throw 'Total-axis-field IOB build failed.' }
      }
    } finally {
      if (Test-Path -LiteralPath $overlayIobStageDir) {
        Remove-Item -LiteralPath $overlayIobStageDir -Recurse -Force
      }
    }
  }
  if ($overlayEnabled -and $overlayLayout -eq 'two_local_v1' -and -not $domainSplitEnabled) {
    $overlayIobBuilderSource = Join-Path $PSScriptRoot 'build_single_flight_two_overlay_iob.lua'
    $overlayIobBuilderFrozen = Join-Path $package.input_dir 'build_single_flight_two_overlay_iob.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayIobBuilderSource `
      -Destination $overlayIobBuilderFrozen -Role 'single-flight two-overlay IOB builder' | Out-Null
    $overlayContainerSourceDir = Join-Path (Split-Path -Parent $SimionExe) 'examples\magnetic_potential'
    $overlayIobContainerSource = Join-Path $overlayContainerSourceDir 'current_sphere_3dp.iob'
    # The distributed six-instance IOB references all three magnetic-vector
    # potential components.  The IOB alone is therefore not a self-contained
    # runtime container once it is copied out of the examples directory.
    $overlayIobContainerCompanionGems = @(
      'current_sphere_3dp-Ax.gem',
      'current_sphere_3dp-Ay.gem',
      'current_sphere_3dp-Az.gem',
      'current_sphere_3dp-jx.gem',
      'current_sphere_3dp-jy.gem',
      'current_sphere_3dp-jz.gem'
    ) | ForEach-Object { Join-Path $overlayContainerSourceDir $_ }
    if (-not (Test-Path -LiteralPath $overlayIobContainerSource -PathType Leaf)) {
      throw 'SIMION-distributed six-instance IOB container is missing.'
    }
    foreach ($overlayIobContainerCompanionGem in $overlayIobContainerCompanionGems) {
      if (-not (Test-Path -LiteralPath $overlayIobContainerCompanionGem -PathType Leaf)) {
        throw "SIMION-distributed six-instance IOB companion GEM is missing: $overlayIobContainerCompanionGem"
      }
    }
    $overlayContainerFrozenDir = Join-Path $package.input_dir 'simion_six_instance_container'
    New-Item -ItemType Directory -Path $overlayContainerFrozenDir -Force | Out-Null
    Copy-Item -LiteralPath $overlayIobContainerSource -Destination $overlayContainerFrozenDir
    foreach ($overlayIobContainerCompanionGem in $overlayIobContainerCompanionGems) {
      Copy-Item -LiteralPath $overlayIobContainerCompanionGem -Destination $overlayContainerFrozenDir
    }
    $overlayIobContainerFrozen = Join-Path $overlayContainerFrozenDir 'current_sphere_3dp.iob'
    $overlayIobContainerGemFrozen = @(Get-ChildItem -LiteralPath $overlayContainerFrozenDir -Filter '*.gem' -File | ForEach-Object { $_.FullName })
    $overlayIobStageDir = New-RfCacheStagingDirectory -CacheRoot (Join-Path $workspaceRoot 'scratch\simion_iob')
    try {
      Get-ChildItem -LiteralPath $overlayContainerFrozenDir -File | Copy-Item -Destination $overlayIobStageDir
      $entranceOverlay = @($twoLocalOverlayBuilds | Where-Object { $_.overlay_id -eq 'accelerator_entrance_overlay' })
      $intermediateOverlay = @($twoLocalOverlayBuilds | Where-Object { $_.overlay_id -eq 'accelerator_intermediate_overlay' })
      if ($entranceOverlay.Count -ne 1 -or $intermediateOverlay.Count -ne 1) { throw 'Two-local overlay build set is incomplete.' }
      $twoOverlayArguments = @('--nogui','--noprompt','lua',$overlayIobBuilderFrozen,
        (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),(Join-Path $overlayIobStageDir 'current_sphere_3dp.iob'),(Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),
        (Join-Path $runtimeDir 'flight_tube_ground.pa0'),(Join-Path $runtimeDir 'reflectron.pa0'),(Join-Path $runtimeDir 'accelerator.pa0'),(Join-Path $runtimeDir 'detector_ground.pa0'),
        (Join-Path $runtimeDir 'accelerator_entrance_overlay.pa0'),(Join-Path $runtimeDir 'accelerator_intermediate_overlay.pa0'),
        ([string]$entranceOverlay[0].geometry.instance_origin_mm.x),([string]$entranceOverlay[0].geometry.instance_origin_mm.y),([string]$entranceOverlay[0].geometry.instance_origin_mm.z),
        ([string]$intermediateOverlay[0].geometry.instance_origin_mm.x),([string]$intermediateOverlay[0].geometry.instance_origin_mm.y),([string]$intermediateOverlay[0].geometry.instance_origin_mm.z))
      $overlayIobBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir 'two_overlay_iob_build_resource_usage.json') -FilePath $SimionExe -WorkingDirectory $runtimeDir `
        -RedirectStandardOutput (Join-Path $package.log_dir 'two_overlay_iob_build.stdout.log') -RedirectStandardError (Join-Path $package.log_dir 'two_overlay_iob_build.stderr.log') `
        -ArgumentList ($twoOverlayArguments + @((Join-Path $runtimeDir 'oatof_ideal_grounded.lua'),(Join-Path $runtimeDir 'oatof_ideal_grounded.fly2')))
      if ($overlayIobBuild.resource_budget_exceeded -or $overlayIobBuild.exit_code -ne 0) { throw 'Two-overlay IOB build failed.' }
      if ($ProgramAxisFieldExport) {
        $totalAxisFieldIob = Join-Path $runtimeDir 'total_axis_field.iob'
        $twoOverlayAxisFieldArguments = @($twoOverlayArguments[0..5]) + @($totalAxisFieldIob) + @($twoOverlayArguments[7..18])
        $axisFieldIobBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
          -UsagePath (Join-Path $package.log_dir 'two_overlay_total_axis_field_iob_build_resource_usage.json') -FilePath $SimionExe -WorkingDirectory $runtimeDir `
          -RedirectStandardOutput (Join-Path $package.log_dir 'two_overlay_total_axis_field_iob_build.stdout.log') -RedirectStandardError (Join-Path $package.log_dir 'two_overlay_total_axis_field_iob_build.stderr.log') `
          -ArgumentList $twoOverlayAxisFieldArguments
        if ($axisFieldIobBuild.resource_budget_exceeded -or $axisFieldIobBuild.exit_code -ne 0 -or -not (Test-Path -LiteralPath $totalAxisFieldIob -PathType Leaf)) { throw 'Two-overlay total-axis-field IOB build failed.' }
      }
    } finally {
      if (Test-Path -LiteralPath $overlayIobStageDir) { Remove-Item -LiteralPath $overlayIobStageDir -Recurse -Force }
    }
  }
  if ($domainSplitEnabled) {
    $domainSplitIobBuilder = Join-Path $package.input_dir 'build_single_flight_domain_split_iob.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath (Join-Path $PSScriptRoot 'build_single_flight_domain_split_iob.lua') -Destination $domainSplitIobBuilder -Role 'single-flight domain-split IOB builder' | Out-Null
    $intermediateOverlay = @($twoLocalOverlayBuilds | Where-Object { $_.overlay_id -eq 'accelerator_intermediate_overlay' })
    $domainMain = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'accelerator_main' }); $domainUpstream = @($domainSplitFineBuilds | Where-Object { $_.name -eq 'upstream_bridge' })
    if ($intermediateOverlay.Count -ne 1 -or $domainMain.Count -ne 1 -or $domainUpstream.Count -ne 1) { throw 'Domain-split PA family is incomplete.' }
    # The formal Program validates the PA basenames recorded in the IOB.  Keep
    # cache families immutable and create run-local aliases with the governed
    # six-slot names before constructing that IOB (including every basis PA).
    Copy-RfPaFamilyAliasInRuntime -SourcePrefix 'frontend' -DestinationPrefix 'coarse_frontend' `
      -SourceDirectory $frontendWorkingDir
    Copy-RfPaFamilyAliasInRuntime -SourcePrefix 'accelerator_main' -DestinationPrefix 'accelerator'
    $coarseFrontendRuntimePa0 = Join-Path $runtimeDir 'coarse_frontend.pa0'
    $acceleratorMainRuntimePa0 = Join-Path $runtimeDir 'accelerator.pa0'
    $containerDir = Join-Path (Split-Path -Parent $SimionExe) 'examples\magnetic_potential'; $container = Join-Path $containerDir 'current_sphere_3dp.iob'
    if (-not (Test-Path -LiteralPath $container -PathType Leaf)) { throw 'SIMION-distributed six-instance IOB container is missing.' }
    $stage = New-RfCacheStagingDirectory -CacheRoot (Join-Path $workspaceRoot 'scratch\simion_iob')
    try {
      Copy-Item -LiteralPath $container -Destination $stage; Get-ChildItem -LiteralPath $containerDir -Filter 'current_sphere_3dp-*.gem' -File | Copy-Item -Destination $stage
      $domainSplitIobArguments = @('--nogui','--noprompt','lua',$domainSplitIobBuilder,(Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),(Join-Path $stage 'current_sphere_3dp.iob'),(Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),$coarseFrontendRuntimePa0,(Join-Path $runtimeDir 'reflectron.pa0'),$acceleratorMainRuntimePa0,(Join-Path $runtimeDir 'detector_ground.pa0'),$domainUpstream[0].pa0,(Join-Path $runtimeDir 'accelerator_intermediate_overlay.pa0'),([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),([string]$domainMain[0].geometry.instance_origin_mm.x),([string]$domainMain[0].geometry.instance_origin_mm.y),([string]$domainMain[0].geometry.instance_origin_mm.z),([string]$domainUpstream[0].geometry.instance_origin_mm.x),([string]$domainUpstream[0].geometry.instance_origin_mm.y),([string]$domainUpstream[0].geometry.instance_origin_mm.z),([string]$intermediateOverlay[0].geometry.instance_origin_mm.x),([string]$intermediateOverlay[0].geometry.instance_origin_mm.y),([string]$intermediateOverlay[0].geometry.instance_origin_mm.z))
      if ($ProgramAxisFieldExport) {
        # The standalone field exporter must load a same-transform IOB without
        # a same-basename Program/Fly2 auto-running during top-level Lua.  The
        # regular build below intentionally replaces its Formal IOB in place,
        # so this export IOB must be built first from the unmodified Formal one.
        $totalAxisFieldIob = Join-Path $runtimeDir 'total_axis_field.iob'
        $domainSplitAxisFieldArguments = @($domainSplitIobArguments[0..5]) + @($totalAxisFieldIob) + @($domainSplitIobArguments[7..24])
        $axisFieldIobBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'domain_split_total_axis_field_iob_build_resource_usage.json') -FilePath $SimionExe -WorkingDirectory $runtimeDir -RedirectStandardOutput (Join-Path $package.log_dir 'domain_split_total_axis_field_iob_build.stdout.log') -RedirectStandardError (Join-Path $package.log_dir 'domain_split_total_axis_field_iob_build.stderr.log') -ArgumentList $domainSplitAxisFieldArguments
        if ($axisFieldIobBuild.resource_budget_exceeded -or $axisFieldIobBuild.exit_code -ne 0 -or -not (Test-Path -LiteralPath $totalAxisFieldIob -PathType Leaf)) { throw 'Domain-split total-axis-field IOB build failed.' }
      }
      $built = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'domain_split_iob_build_resource_usage.json') -FilePath $SimionExe -WorkingDirectory $runtimeDir -RedirectStandardOutput (Join-Path $package.log_dir 'domain_split_iob_build.stdout.log') -RedirectStandardError (Join-Path $package.log_dir 'domain_split_iob_build.stderr.log') -ArgumentList $domainSplitIobArguments
      if ($built.resource_budget_exceeded -or $built.exit_code -ne 0) { throw 'Domain-split IOB build failed.' }
    } finally { if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force } }
  }
  $frontendCacheRecheck = Test-RfFrozenCacheGeneration -Python $python `
    -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
    -CacheEntry $cacheDir -CacheRole $frontendCacheRole -CacheKey $frontendCacheKey `
    -FrozenManifest $frontendCacheManifestInput -LogDirectory $package.log_dir
  if (-not $frontendCacheRecheck.passed) {
    throw ('Frontend PA cache generation verification failed after construction: ' +
      "exit_code=$($frontendCacheRecheck.verifier_exit_code); " +
      "frozen_manifest_matches=$($frontendCacheRecheck.frozen_manifest_matches); " +
      "cache_entry=$($frontendCacheRecheck.cache_entry); " +
      "stdout=$($frontendCacheRecheck.stdout_log); stderr=$($frontendCacheRecheck.stderr_log)")
  }
  $flightTubeCacheManifestInput = if ($flightTubeCacheUsed) {
    Copy-RfCacheManifestInput -CacheEntry $flightTubeCacheDir `
      -Destination (Join-Path $package.input_dir 'flight_tube_pa_cache_manifest.json')
  } else { $null }
  $reflectronCacheManifestInput = if ($reflectronCacheUsed) {
    Copy-RfCacheManifestInput -CacheEntry $reflectronCacheDir `
      -Destination (Join-Path $package.input_dir 'reflectron_pa_cache_manifest.json')
  } else { $null }
  $overlayCacheManifestInput = if ($overlayEnabled -and $overlayLayout -eq 'whole_accelerator_v1') {
    Copy-RfCacheManifestInput -CacheEntry $overlayCacheDir `
      -Destination (Join-Path $package.input_dir 'accelerator_overlay_pa_cache_manifest.json')
  } else { $null }
  $domainSplitFineCacheManifestInputs = @()
  if ($domainSplitEnabled) {
    foreach ($domainSplitFineBuild in $domainSplitFineBuilds) {
      $domainSplitFineCacheManifestInputs += [pscustomobject]@{
        disposition=$paCacheDispositions[$domainSplitFineBuild.disposition_key]
        path=(Copy-RfCacheManifestInput -CacheEntry $domainSplitFineBuild.cache_dir `
          -Destination (Join-Path $package.input_dir ($domainSplitFineBuild.name + '_pa_cache_manifest.json')))
      }
    }
  }
  $twoLocalOverlayCacheManifestInputs = @()
  if ($overlayEnabled -and $overlayLayout -eq 'two_local_v1') {
    foreach ($twoLocalOverlayBuild in $twoLocalOverlayBuilds) {
      $twoLocalOverlayCacheManifestInputs += [pscustomobject]@{
        overlay_id=$twoLocalOverlayBuild.overlay_id
        disposition=$paCacheDispositions[$twoLocalOverlayBuild.overlay_id]
        path=(Copy-RfCacheManifestInput -CacheEntry $twoLocalOverlayBuild.cache_dir `
          -Destination (Join-Path $package.input_dir ($twoLocalOverlayBuild.overlay_id + '_pa_cache_manifest.json')))
      }
    }
  }
  $cacheManifestBindings = @(
    [ordered]@{disposition=$paCacheDispositions.frontend; path=$frontendCacheManifestInput}
  )
  if ($domainSplitEnabled) {
    $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.full_coarse_bridge;path=$frontendCacheManifestInput}
    foreach ($domainSplitFineCacheManifestInput in $domainSplitFineCacheManifestInputs) {
      $cacheManifestBindings += [ordered]@{disposition=$domainSplitFineCacheManifestInput.disposition;path=$domainSplitFineCacheManifestInput.path}
    }
  }
  if ($null -ne $flightTubeCacheManifestInput) {
    $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.flight_tube;path=$flightTubeCacheManifestInput}
  }
  if ($null -ne $reflectronCacheManifestInput) {
    $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.reflectron;path=$reflectronCacheManifestInput}
  }
  if ($null -ne $overlayCacheManifestInput) {
    $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.accelerator_overlay;path=$overlayCacheManifestInput}
  }
  foreach ($twoLocalOverlayCacheManifestInput in $twoLocalOverlayCacheManifestInputs) {
    $cacheManifestBindings += [ordered]@{disposition=$twoLocalOverlayCacheManifestInput.disposition;path=$twoLocalOverlayCacheManifestInput.path}
    if ($domainSplitEnabled -and $twoLocalOverlayCacheManifestInput.overlay_id -eq 'accelerator_intermediate_overlay') {
      $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.accelerator_intermediate2_overlay;path=$twoLocalOverlayCacheManifestInput.path}
    }
  }
  foreach ($binding in $cacheManifestBindings) {
    $manifest = Get-Content -LiteralPath $binding.path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($hasRequiredPaCacheGenerationBinding) {
      if ([int]$manifest.schema_version -ne 3 -or
          [string]$manifest.generation_sha256 -notmatch '^[a-f0-9]{64}$' -or
          [string]$manifest.payload_sha256 -notmatch '^[A-Fa-f0-9]{64}$') {
        throw 'Frozen PA cache manifest lacks immutable generation identity.'
      }
      $binding.disposition.generation_sha256 = [string]$manifest.generation_sha256
      $binding.disposition.payload_sha256 = [string]$manifest.payload_sha256.ToUpperInvariant()
    } elseif ([int]$manifest.schema_version -notin @(2,3)) {
      throw 'Frozen PA cache manifest schema is unsupported.'
    }
  }
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'single_flight_program_build.json'
  $totalAxisFieldExporter = Join-Path $package.input_dir 'total_axis_field_exporter.lua'
  $analyzerComponent = Join-Path $package.input_dir 'oatof_analyzer_component.lua'
  $pulseHook = Join-Path $package.input_dir 'single_flight_pulse_hook.lua'
  $frontendHook = Join-Path $package.input_dir 'single_flight_frontend_hook.lua'
  $rfDriveKernel = Join-Path $package.input_dir 'simion_rf_drive.lua'
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_analyzer_component.lua') `
    -Destination $analyzerComponent -Role 'single-flight oaTOF analyzer component' | Out-Null
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $PSScriptRoot 'single_flight_pulse_hook.lua') `
    -Destination $pulseHook -Role 'single-flight pulse hook' | Out-Null
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $PSScriptRoot 'single_flight_frontend_hook.lua') `
    -Destination $frontendHook -Role 'single-flight frontend hook' | Out-Null
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'common\multipole\simion_rf_drive.lua') `
    -Destination $rfDriveKernel -Role 'single-flight RF drive kernel' | Out-Null
  $programArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
    '--analyzer-component',$analyzerComponent,
    '--pulse-hook',$pulseHook,
    '--frontend-hook',$frontendHook,
    '--upstream',$upstreamFrozen,
    '--frontend-contract',$frontendContract,'--oatof',$oatofGeometry,
    '--initial-global-state',$globalSource,
    '--particle-row-map',$particleRowMap,
    '--resolved-region-field-contract',$resolvedRegionFieldContractFrozen,
    '--rf-drive-kernel',$rfDriveKernel,
    '--rf-steps-per-period',([string]$rfStepsPerPeriod),
    '--source-release-mode',$sourceReleaseMode,
    '--output',$program,'--metadata',$programMetadata)
  if ($domainSplitEnabled) {
    $domainProgramOverlay = @($twoLocalOverlayBuilds | Where-Object { $_.overlay_id -eq 'accelerator_intermediate_overlay' })
    if ($domainProgramOverlay.Count -ne 1) { throw 'Domain-split Program intermediate overlay is missing.' }
    $programArguments += @('--upstream-bridge-contract',$upstreamBridgeContract,'--accelerator-main-contract',$acceleratorMainContract,'--intermediate-accelerator-overlay-contract',$domainProgramOverlay[0].contract)
  }
  if ($ProgramAxisFieldExport) {
    $programArguments += '--total-axis-field-exporter-output',$totalAxisFieldExporter
  }
  if ($null -ne $restartContext) {
    $programArguments += @('--restart-context',$restartContext)
  }
  if ($isPrePulseTimeSeriesScreening) {
    $programArguments += @(
      '--pre-pulse-time-series-contract',$prePulseTimeSeriesContractFrozen
    )
  }
  if ($null -ne $prePulseValidationFrozen) { $programArguments += '--global-segments' }
  if ($overlayEnabled -and $overlayLayout -eq 'whole_accelerator_v1') {
    $programArguments += @('--accelerator-overlay-contract',$overlayContract)
  } elseif ($overlayEnabled -and -not $domainSplitEnabled) {
    $entranceProgramOverlay = @($twoLocalOverlayBuilds | Where-Object {
      $_.overlay_id -eq 'accelerator_entrance_overlay'
    })
    $intermediateProgramOverlay = @($twoLocalOverlayBuilds | Where-Object {
      $_.overlay_id -eq 'accelerator_intermediate_overlay'
    })
    if ($entranceProgramOverlay.Count -ne 1 -or $intermediateProgramOverlay.Count -ne 1) {
      throw 'Two-local Program overlay contracts are incomplete.'
    }
    $programArguments += @(
      '--accelerator-overlay-contract',$entranceProgramOverlay[0].contract,
      '--intermediate-accelerator-overlay-contract',$intermediateProgramOverlay[0].contract
    )
  }
  Invoke-SingleFlightPython -Arguments $programArguments `
    -Failure 'Single-flight Program build failed.' `
    -StdoutPath (Join-Path $package.log_dir 'single_flight_program_build.stdout.log') `
    -StderrPath (Join-Path $package.log_dir 'single_flight_program_build.stderr.log')

  $preparedDispatchPlan = $resolvedBudgetDocument.single_flight_dispatch_plan
  $preparedDispatchPlanPath = Join-Path $package.input_dir 'simion_prepared_dispatch_plan.json'
  $runtimeDispatchPlanPath = Join-Path $package.input_dir 'simion_repository_dispatch_plan.json'
  $preparedDispatchPlan | ConvertTo-Json -Depth 8 | Set-Content `
    -LiteralPath $preparedDispatchPlanPath -Encoding UTF8
  Invoke-SingleFlightPython -Arguments @(
    '-m','common.simion.resource_scheduler','--prepared-plan',$preparedDispatchPlanPath,
    '--output',$runtimeDispatchPlanPath
  ) -Failure 'SIMION runtime resource scheduling failed.'
  $runtimeDispatchPlan = Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath |
    ConvertFrom-Json
  if ($runtimeDispatchPlan.role -ne 'simion_repository_dispatch_plan' -or
      [int]$runtimeDispatchPlan.particle_count -ne $launched -or
      @($runtimeDispatchPlan.waves).Count -ne 1 -or
      [int]$runtimeDispatchPlan.waves[0].batch_count -lt 1 -or
      [int]$runtimeDispatchPlan.waves[0].batch_count -gt $launched) {
    throw 'SIMION runtime resource scheduler returned an invalid dispatch plan.'
  }
  $executionBatchCount = [int]$runtimeDispatchPlan.waves[0].batch_count

  $runConfiguration = [ordered]@{
    schema_version=2; run_id=$RunId; project=$runProjectId; mode='rf_to_oatof_simion_single_flight'; project_root=$repoRoot
    upstream_project_id=$runtime.upstream_project_id
    inputs=[ordered]@{ configuration=$configuration; resolved_single_flight_execution_profile=$executionProfilePath; runtime_binding=$runtimeBindingFrozen; resolved_connection=$resolvedFrozen; resolved_source_contract=$sourceContractFrozen; resolved_population_contract=$populationContractFrozen; resolved_single_flight_population=$runtimePopulationPath; upstream_resolved_design=$upstreamFrozen; oatof_resolved_geometry=$oatofGeometry; pulse_schedule=$pulseScheduleFrozen; resolved_region_field_contract=$resolvedRegionFieldContractFrozen; analyzer_component=$analyzerComponent; pulse_hook=$pulseHook; frontend_hook=$frontendHook; rf_drive_kernel=$rfDriveKernel; resolved_integration_engineering_budget=$budget.frozen_budget; resolved_stage_resource_budget=$budget.stage_budget; mother_particle_source=$motherSource; mother_particle_source_materialization_receipt=$motherSourceReceiptFrozen; initial_global_state=$globalSource; particle_row_map=$particleRowMap; pre_pulse_restart_validation=$prePulseValidationFrozen; particle_input=$particleInput; frontend_gem=$frontendGem; frontend_basis_initializer=$frontendBasisInitializerFrozen; frontend_single_pa_refiner=$frontendSinglePaRefinerFrozen; frontend_contract=$frontendContract; frontend_electrode_topology=$frontendElectrodeTopologyContract; frontend_pa_cache_manifest=$frontendCacheManifestInput; accelerator_overlay_gem=$overlayGem; accelerator_overlay_contract=$overlayContract; accelerator_overlay_basis_builder=$overlayBasisBuilderFrozen; accelerator_overlay_refiner=$overlayRefinerFrozen; accelerator_overlay_interface_verifier=$overlayInterfaceVerifierFrozen; accelerator_overlay_pa_cache_manifest=$overlayCacheManifestInput; accelerator_overlay_iob_builder=$overlayIobBuilderFrozen; accelerator_overlay_iob_container=$overlayIobContainerFrozen; accelerator_overlay_iob_container_gems=$overlayIobContainerGemFrozen; accelerator_overlay_basis_report=$overlayBasisReport; accelerator_overlay_interface_report=$overlayInterfaceReport; accelerator_overlay_refine_dispatch_request=$overlayRefineDispatchRequest; accelerator_overlay_refine_dispatch_plan=$overlayRefineDispatchPlan; accelerator_overlay_refine_resource_usage=$overlayRefineResourceUsage; flight_tube_pa_cache_manifest=$flightTubeCacheManifestInput; reflectron_pa_cache_manifest=$reflectronCacheManifestInput; frontend_aperture_topology_support=$apertureTopologySupport; frontend_aperture_topology_verifier=$apertureVerifier; program_metadata=$programMetadata; candidate_flight_tube_builder=$flightTubeBuilderFrozen; candidate_flight_tube_gem=$flightTubeGemFrozen; candidate_reflectron_builder=$reflectronBuilderFrozen; candidate_reflectron_gem=$reflectronGemFrozen; candidate_reflectron_refiner=$reflectronRefinerFrozen }
    upstream_source_identity=$resolvedBudgetDocument.source_identity
    parameters=[ordered]@{ connection_profile_id=$ConnectionProfileId; source_branch_id=$SourceBranchId; single_flight_pa_cache_policy=$PaCachePolicy; single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance; pa_cache_dispositions=$paCacheDispositions; layout_profile_id=$(if($hasGovernedLayout){$LayoutProfileId}else{$null}); architecture_generation_id=$(if($hasGovernedLayout){$ArchitectureGenerationId}else{$null}); source_profile_id=$(if($SourceProfileId){$SourceProfileId}else{$null}); field_overlay_id=$resolvedFieldOverlayId; bore_radius_mm=[double]$oatofGeometryDocument.geometry_mm.bore_r; ring_outer_radius_mm=[double]$oatofGeometryDocument.geometry_mm.ring_outer_r; shield_inner_radius_mm=[double]$oatofGeometryDocument.geometry_mm.flight_tube_r; frontend_grid_profile_id=$selectedGridProfileId; frontend_cell_mm_xyz=[ordered]@{x=$frontendCellMmX;y=$frontendCellMmY;z=$frontendCellMmZ}; accelerator_overlay_enabled=$overlayEnabled; accelerator_overlay_cell_mm_xyz=$(if($overlayEnabled){[ordered]@{x=$overlayCellMmX;y=$overlayCellMmY;z=$overlayCellMmZ}}else{$null}); accelerator_overlay_boundary_mode=$(if($overlayEnabled){'coarse_electrode_basis_dirichlet_v1'}else{$null}); oatof_numerical_profile_id=$selectedOatofNumericalProfileId; trajectory_quality_profile_id=$selectedTrajectoryQualityProfileId; trajectory_quality=$trajectoryQuality; time_integration_profile_id=$selectedTimeIntegrationProfileId; rf_steps_per_period=$rfStepsPerPeriod; spatial_window_profile_id=$executionProfile.spatial_window_profile_id; source_region_diagnostic_profile_id=$(if($sourceRegionDiagnosticProfiles.Count -eq 1){$sourceRegionDiagnosticProfileId}else{$null}); accelerator_field_profile_id=$selectedFieldProfileId; resolved_region_field_contract_sha256=$ResolvedRegionFieldContractSha256; resolved_region_field_semantic_sha256=$ResolvedRegionFieldSemanticSha256; resolved_population_contract_sha256=$ResolvedPopulationContractSha256; clock_basis=[string]$executionProfile.clock_basis; launched_particle_count=$launched; particle_count=$launched; population_denominator_count=$PopulationDenominatorCount; eligible_population_count=$EligiblePopulationCount; population_basis=$populationBasis; execution_batch_count=$executionBatchCount; execution_batches_parallel=[bool]($executionBatchCount -gt 1); aperture_width_mm=$apertureWidthMm; aperture_height_mm=$apertureHeightMm; aperture_boolean_boundary_policy=[string]$apertureDiscretization.boolean_boundary_policy; aperture_grid_warnings=$apertureGridWarnings; frontend_open_aperture_column_count=[int]$apertureTopology.open_column_count; frontend_aperture_guard_electrode_check_passed=[bool]$apertureTopology.guard_electrode_check_passed; frontend_aperture_topology_report_sha256=(Get-FileHash -LiteralPath $apertureTopologyReport -Algorithm SHA256).Hash; rod_end_to_accelerator_shield_mm=[double]$frontendGeometry.junction_enclosure.rod_end_to_accelerator_shield_mm; surrounded_transition=$true; accelerator_axis_x_mm=[double]$oatofGeometryDocument.coordinate_convention.accelerator_axis_x; pulse_time_us=$pulseTimeUs; pulse_width_us=$pulseWidthUs; design_compilation=$(if($null -ne $layoutDerivation){$layoutDerivation.design_compilation}else{$null}); source_release_full_width_mm=[double]$oatofGeometryDocument.particle_source.size_z_mm; reflectron_stage2_length_mm=[double]$oatofGeometryDocument.geometry_mm.L_stage2; reflectron_midgrid_voltage_V=[double]$oatofGeometryDocument.electrodes_V.midgrid; reflectron_backplate_voltage_V=[double]$oatofGeometryDocument.electrodes_V.backplate; reflectron_pa0_sha256=(Get-FileHash -LiteralPath $reflectronPa0 -Algorithm SHA256).Hash; frontend_gem_sha256=$frontendHash; frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash; accelerator_overlay_pa0_sha256=$(if($overlayEnabled -and $overlayLayout -eq 'whole_accelerator_v1'){(Get-FileHash -LiteralPath $overlayCachePa0 -Algorithm SHA256).Hash}else{$null}) }
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}; formal_gate_passed=$false
  }
  $runConfiguration.parameters.maximum_time_of_flight_us = $maximumTimeOfFlightUs
  $runConfiguration.parameters.accelerator_overlay_layout = $overlayLayout
  if ($overlayEnabled -and $overlayLayout -eq 'two_local_v1') {
    $runConfiguration.inputs.accelerator_local_overlays = @($twoLocalOverlayBuilds | ForEach-Object {
      $localOverlay = $_
      $matchingManifest = @($twoLocalOverlayCacheManifestInputs | Where-Object {
        $_.overlay_id -eq $localOverlay.overlay_id
      })
      if ($matchingManifest.Count -ne 1) { throw 'Two-local overlay cache manifest binding is incomplete.' }
      [ordered]@{
        overlay_id=$localOverlay.overlay_id; gem=$localOverlay.gem; contract=$localOverlay.contract; cache_role=$localOverlay.cache_role; cache_key=$localOverlay.cache_key
        basis_builder=$localOverlay.basis_builder; refiner=$localOverlay.refiner; interface_verifier=$localOverlay.interface_verifier
        pa_cache_manifest=$matchingManifest[0].path; basis_report=$localOverlay.basis_report; interface_report=$localOverlay.interface_report
      }
    })
    $runConfiguration.parameters.accelerator_overlay_cell_mm_xyz = $null
    $runConfiguration.parameters.accelerator_overlay_pa0_sha256 = $null
    $runConfiguration.parameters.accelerator_local_overlay_pa0_sha256 = @($twoLocalOverlayBuilds | ForEach-Object {
      [ordered]@{overlay_id=$_.overlay_id;sha256=(Get-FileHash -LiteralPath $_.cache_pa0 -Algorithm SHA256).Hash}
    })
  }
  $runConfiguration.parameters.bootstrap_resample_count = $BootstrapResamples
  $runConfiguration.parameters.bootstrap_seed = $BootstrapSeed
  $runConfiguration.parameters.program_axis_field_export_requested = [bool]$ProgramAxisFieldExport
  if ($isPrePulseTimeSeriesScreening) {
    $runConfiguration.inputs.pre_pulse_time_series_contract =
      $prePulseTimeSeriesContractFrozen
    # The materializer validates this identity after the short execution
    # directory is retired.  Preserve the supplied hash in the immutable run
    # configuration instead of relying on the process-local argument.
    $runConfiguration.parameters.pre_pulse_time_series_contract_sha256 =
      $PrePulseTimeSeriesContractSha256
    $runConfiguration.parameters.execution_mode =
      'real_pa_rf_pre_pulse_time_series'
    $runConfiguration.parameters.resolution_claim_allowed = $false
  }
  if ($hasThreeZoneCandidate) {
    $runConfiguration.inputs.three_zone_t5_candidate =
      $threeZoneCandidateFrozen
    $runConfiguration.inputs.three_zone_runtime_identity =
      $threeZoneRuntimeIdentity
    $runConfiguration.parameters.three_zone_topology_id =
      $threeZoneTopologyId
    $runConfiguration.parameters.three_zone_geometry_id =
      $threeZoneGeometryId
    $runConfiguration.parameters.three_zone_frontend_electrode_topology_id =
      $threeZoneFrontendElectrodeTopologyId
    $runConfiguration.parameters.three_zone_field_id = $threeZoneFieldId
    $runConfiguration.parameters.three_zone_candidate_sha256 =
      $ThreeZoneCandidateSha256
    $runConfiguration.parameters.accelerator_intermediate2_forward_launched_upper_bound =
      $launched
  }
  $batchPlanPath = Join-Path $package.input_dir 'simion_execution_batch_plan.json'
  Invoke-SingleFlightPython -Arguments @(
    '-m','common.simion.particle_batching','--from-dispatch-plan',$runtimeDispatchPlanPath,
    '--output',$batchPlanPath
  ) -Failure 'Shared SIMION single-wave batch planning failed.'
  $batchPlan = Get-Content -Raw -LiteralPath $batchPlanPath | ConvertFrom-Json
  if ($batchPlan.dispatch -ne 'single_wave_parallel' -or
      [int]$batchPlan.particle_count -ne [int]$launched) {
    throw 'Shared SIMION batch plan differs from the frozen launched population.'
  }
  $runConfiguration.inputs.simion_execution_batch_plan = $batchPlanPath
  $runConfiguration.inputs.simion_prepared_dispatch_plan = $preparedDispatchPlanPath
  $runConfiguration.inputs.simion_repository_dispatch_plan = $runtimeDispatchPlanPath
  $runConfiguration.parameters.simion_single_wave_batch_plan_sha256 =
    (Get-FileHash -Algorithm SHA256 -LiteralPath $batchPlanPath).Hash
  $runConfiguration.parameters.simion_repository_dispatch_plan_sha256 =
    (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeDispatchPlanPath).Hash
  $runConfiguration.parameters.runtime_implementation_binding_mode =
    $RuntimeImplementationBindingMode
  $runConfiguration.parameters.runtime_implementation_identity =
    $runtime.implementation_identity
  Write-RunJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RunJson -Path $package.summary -Depth 10 -Value ([ordered]@{schema_version=1;role=$summaryRole;status='interrupted';reason='Frozen inputs recorded; SIMION flight not complete.';single_flight_pa_cache_policy=$PaCachePolicy;single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance;pa_cache_dispositions=$paCacheDispositions})
  Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status interrupted -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  if ($BuildOnly) {
    $axisFieldOutput = $null
    $axisFieldUsage = $null
    if ($ProgramAxisFieldExport) {
      if (-not $hasThreeZoneCandidate -or -not $overlayEnabled) {
        throw 'Program axis-field export requires a three-zone Candidate with overlay PA.'
      }
      if ([string]::IsNullOrWhiteSpace($totalAxisFieldIob) -or -not (Test-Path -LiteralPath $totalAxisFieldIob -PathType Leaf)) {
        throw 'Program axis-field export requires the field-only five-instance IOB.'
      }
      $axisFieldOutput = Join-Path $package.result_dir 'total_axis_field.csv'
      if (-not (Test-Path -LiteralPath $totalAxisFieldExporter -PathType Leaf)) {
        throw 'Top-level total-axis field exporter was not generated.'
      }
      $axisFieldUsage = Join-Path $package.log_dir 'total_axis_field_resource_usage.json'
      $axisFieldResult = Invoke-ResourceBudgetedProcess `
        -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath $axisFieldUsage -FilePath $SimionExe -WorkingDirectory $runtimeDir `
        -RedirectStandardOutput (Join-Path $package.log_dir 'total_axis_field.stdout.log') `
        -RedirectStandardError (Join-Path $package.log_dir 'total_axis_field.stderr.log') `
        -Environment @{
          OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0
          OATOF_TOTAL_AXIS_FIELD_CSV = $axisFieldOutput
          OATOF_TOTAL_AXIS_FIELD_IOB = $totalAxisFieldIob
          OATOF_TOTAL_AXIS_FIELD_PULSE_TIME_US = ([string]$pulseTimeUs)
          OATOF_TOTAL_AXIS_FIELD_PULSE_WIDTH_US = ([string]$pulseWidthUs)
        } -ArgumentList ([string[]](@(
          '--nogui','--noprompt','lua',$totalAxisFieldExporter
        )))
      if ($axisFieldResult.resource_budget_exceeded -or $axisFieldResult.exit_code -ne 0 -or
          -not (Test-Path -LiteralPath $axisFieldOutput -PathType Leaf)) {
        throw 'Top-level total-axis field export failed.'
      }
    }
    # BuildOnly may still materialize large PA families before the top-level
    # diagnostic.  Apply the same compact retention contract as a particle
    # flight before publishing its immutable manifest.
    $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot `
      -RunConfig $package.run_config
    if ($axisFieldUsage -and -not (Complete-ResourceUsage `
          -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
          -UsagePath $axisFieldUsage)) {
      $resourceBudgetExceeded = $true
      throw 'BuildOnly total-axis-field compact retained-byte budget exceeded.'
    }
    $axisFieldOutputArtifact = if ($axisFieldOutput) {
      Join-Path $package.artifact_run_dir 'results\total_axis_field.csv'
    } else { $null }
    $axisFieldUsageArtifact = if ($axisFieldUsage) {
      Join-Path $package.artifact_run_dir 'logs\total_axis_field_resource_usage.json'
    } else { $null }
    Write-RunJson -Path $package.summary -Depth 10 -Value ([ordered]@{
      schema_version=1; role=$summaryRole; status='success'
      execution_mode=$(if($ProgramAxisFieldExport){'program_axis_field_export'}else{'build_only'})
      claim_limit='PA/IOB construction and optional static field export only; no particle flight or physics result.'
      single_flight_pa_cache_policy=$PaCachePolicy
      pa_cache_dispositions=$paCacheDispositions
      total_axis_field_csv=$axisFieldOutputArtifact
      total_axis_field_iob_status='TOP_LEVEL_FIVE_INSTANCE_EXPORT'
      total_axis_field_resource_usage=$axisFieldUsageArtifact
    })
    $buildOnlyOutputs = @(
      $axisFieldOutput,$axisFieldUsage,$retentionActions,
      (Join-Path $package.log_dir 'total_axis_field.stdout.log'),
      (Join-Path $package.log_dir 'total_axis_field.stderr.log'),$package.summary
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $buildOnlyOutputs
    $hostExecutionOutcome = 'success'
    return
  }

  $batchCount = [int]$batchPlan.batch_count
  $particleLines = @(Get-RfSingleFlightParticleLines `
    -ParticleInput $particleInput -RestartFly2 $isRestartFly2)
  if ($particleLines.Count -ne $launched) {
    throw 'Single-flight particle-input row count differs from the launched mother sample.'
  }
  $prePulseContinuationPlan = $null
  $importedCompletedTraceFiles = @()
  if (-not [string]::IsNullOrWhiteSpace($ResumePrePulseFromRun)) {
    $continuationRoot = Join-Path $package.input_dir 'pre_pulse_batch_continuation'
    Invoke-SingleFlightPython -Arguments @(
      '-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pre_pulse_batch_continuation',
      '--predecessor-run-dir',$ResumePrePulseFromRun,
      '--particle-row-map',$particleRowMap,
      '--mother-particle-source',$motherSource,
      '--initial-global-state',$globalSource,
      '--contract-sha256',$PrePulseTimeSeriesContractSha256,
      '--output-dir',$continuationRoot
    ) -Failure 'Pre-pulse batch continuation planning failed.'
    $prePulseContinuationPlan = Get-Content -LiteralPath (
      Join-Path $continuationRoot 'simion_batch_continuation_plan.json'
    ) -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($prePulseContinuationPlan.role -ne 'simion_batch_continuation_plan' -or
        [int]$prePulseContinuationPlan.batch_plan.particle_count -ne $launched -or
        [int]$prePulseContinuationPlan.completed_particle_count +
          [int]$prePulseContinuationPlan.replay_particle_count -ne $launched) {
      throw 'Pre-pulse batch continuation plan differs from the frozen cohort.'
    }
    if ([int]$prePulseContinuationPlan.replay_particle_count -eq 0) {
      throw 'All pre-pulse batches are complete; use the zero-SIMION completed-screening recovery path.'
    }
    $batchPlanPath = [string]$prePulseContinuationPlan.batch_plan.path
    $batchPlan = Get-Content -LiteralPath $batchPlanPath -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ((Get-FileHash -LiteralPath $batchPlanPath -Algorithm SHA256).Hash -ne
        [string]$prePulseContinuationPlan.batch_plan.sha256) {
      throw 'Pre-pulse continuation canonical batch plan hash differs.'
    }
    $importedCompletedTraceFiles = @($prePulseContinuationPlan.batches |
      Where-Object { $null -ne $_.imported_completed_trace } |
      ForEach-Object { [string]$_.imported_completed_trace.path })
    $runConfiguration.inputs.simion_batch_continuation_plan = Join-Path `
      $continuationRoot 'simion_batch_continuation_plan.json'
    $runConfiguration.inputs.simion_execution_batch_plan = $batchPlanPath
    $runConfiguration.parameters.pre_pulse_continuation_completed_particle_count =
      [int]$prePulseContinuationPlan.completed_particle_count
    $runConfiguration.parameters.pre_pulse_continuation_replay_particle_count =
      [int]$prePulseContinuationPlan.replay_particle_count
    Write-RunJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  }
  function New-SingleFlightBatchRecords($Plan) {
    $records = @()
    foreach ($plannedBatch in @($Plan.batches)) {
      $batchIndex = [int]$plannedBatch.index
      $count = [int]$plannedBatch.count
      $offset = [int]$plannedBatch.simion_particle_id_offset
      $batchParticleInput = Join-Path $package.input_dir (
        'single_flight_mother_sample__batch{0:D2}.{1}' -f $batchIndex,$(if ($isRestartFly2) {'fly2'} else {'ion'})
      )
      $batchParticleLines = [string[]]$particleLines[$offset..($offset + $count - 1)]
      if ($isRestartFly2) {
        $batchParticleLines = [string[]](@('particles {','  coordinates = 0,') + $batchParticleLines + @('}'))
      }
      if (-not (Test-Path -LiteralPath $batchParticleInput -PathType Leaf)) {
        [IO.File]::WriteAllLines(
          $batchParticleInput,
          $batchParticleLines,
          [Text.UTF8Encoding]::new($false)
        )
      }
      $records += [pscustomobject]@{
        index = $batchIndex; count = $count; offset = $offset
        particle_input = $batchParticleInput
        stdout = Join-Path $package.log_dir ('simion__batch{0:D2}.stdout.log' -f $batchIndex)
        stderr = Join-Path $package.log_dir ('simion__batch{0:D2}.stderr.log' -f $batchIndex)
      }
    }
    return @($records)
  }
  $batchRecords = @(New-SingleFlightBatchRecords $batchPlan)
  if ($null -ne $prePulseContinuationPlan) {
    $replayRecords = @()
    foreach ($continuationBatch in @($prePulseContinuationPlan.batches)) {
      $replayCount = [int]$continuationBatch.replay_particle_count
      if ($replayCount -eq 0) { continue }
      $batchIndex = [int]$continuationBatch.index
      $replayOffset = [int]$continuationBatch.replay_particle_id_min - 1
      $batchParticleInput = Join-Path $package.input_dir (
        'single_flight_mother_sample__batch{0:D2}__continuation.{1}' -f
          $batchIndex,$(if ($isRestartFly2) {'fly2'} else {'ion'})
      )
      $batchParticleLines = [string[]]$particleLines[$replayOffset..($replayOffset + $replayCount - 1)]
      if ($isRestartFly2) {
        $batchParticleLines = [string[]](@('particles {','  coordinates = 0,') +
          $batchParticleLines + @('}'))
      }
      [IO.File]::WriteAllLines($batchParticleInput,$batchParticleLines,[Text.UTF8Encoding]::new($false))
      $replayRecords += [pscustomobject]@{
        index=$batchIndex;count=$replayCount;offset=$replayOffset
        particle_input=$batchParticleInput
        stdout=Join-Path $package.log_dir ('simion__batch{0:D2}__continuation.stdout.log' -f $batchIndex)
        stderr=Join-Path $package.log_dir ('simion__batch{0:D2}__continuation.stderr.log' -f $batchIndex)
      }
    }
    $batchRecords = @($replayRecords)
  }
  $stdoutFiles = @($batchRecords | ForEach-Object { $_.stdout })
  $stdoutFiles += $importedCompletedTraceFiles
  $stderrFiles = @($batchRecords | ForEach-Object { $_.stderr })
  # The whole batch set is one dispatch wave.  The shared aggregate helper owns
  # process-tree and available-memory accounting; per-batch helpers would make
  # the frozen process-tree limit apply independently to every SIMION child.
  $resourceUsageFiles = @($resourceUsage)
  if ($null -ne $overlayRefineResourceUsage) { $resourceUsageFiles += $overlayRefineResourceUsage }
  foreach ($twoLocalOverlayBuild in $twoLocalOverlayBuilds) {
    if ($null -ne $twoLocalOverlayBuild.refine_resource_usage) {
      $resourceUsageFiles += $twoLocalOverlayBuild.refine_resource_usage
    }
  }
  function New-SingleFlightProcessSpecifications($Records) {
    $specifications = @()
    $largestPlannedBatchCount = [int](($Records | Measure-Object -Property count -Maximum).Maximum)
    if ($largestPlannedBatchCount -lt 1) {
      throw 'SIMION ion-list capacity requires at least one particle in the execution batch plan.'
    }
    # SIMION sizes the IOB ion list before reading an external ION table and
    # rejects a capacity below 100.  This is preallocation only: external particle tables still determine the exact physical batch population.
    $ionListCapacity = [Math]::Max(100,$largestPlannedBatchCount)
    # Size the list to the largest planned batch above the SIMION minimum, not
    # to a repository-wide cap.
    # Batches above 10,000 remain valid; this is visibility only.
    if ($ionListCapacity -gt 10000) {
      Write-Warning (
        'SIMION ion-list capacity is {0} particles (>10000 operational warning threshold); ' +
        'continuing without a batch-size limit.' -f $ionListCapacity
      )
    }
    foreach ($batch in $Records) {
      $specifications += [pscustomobject]@{
      name = 'simion_batch_{0:D2}' -f [int]$batch.index
      simion_ion_list_capacity = $ionListCapacity
      file_path = $SimionExe
      working_directory = $runtimeDir
      stdout = $batch.stdout
      stderr = $batch.stderr
      environment = $(if ($domainSplitEnabled) {
        @{ OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET = [string]$batch.offset }
      } else {
        @{ OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0; OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET = [string]$batch.offset }
      })
      argument_list = [string[]](@(
        '--default-num-particles',([string]$ionListCapacity),'--nogui','--noprompt','fly',
        '--trajectory-quality',([string]$trajectoryQuality),
        '--retain-trajectories','0','--particles',$batch.particle_input,'--programs','1',
        '--adjustable',("trajectory_quality={0}" -f $trajectoryQuality),
        '--adjustable','trajectory_log_enable=1',
        '--adjustable',("diagnostic_max_tof_us={0:R}" -f $maximumTimeOfFlightUs)
      ) + $(if ($isPrePulseTimeSeriesScreening) { @(
        '--adjustable','handoff_pulse_mode=2'
      ) } else { @(
        '--adjustable','handoff_pulse_mode=1',
        '--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
        '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs)
      ) }) + @(
        $(if (-not $isPrePulseRestart) {
          @('--adjustable',("single_flight_rf_steps={0}" -f $rfStepsPerPeriod))
        } else { @() }),
        (Join-Path $runtimeDir 'oatof_ideal_grounded.iob')
      ))
      }
    }
    return @($specifications)
  }
  $processSpecifications = @(New-SingleFlightProcessSpecifications $batchRecords)
  $resourceIdentityWasUnknown =
    [string]$runtimeDispatchPlan.estimation.kind -eq 'formal_first_batch_observation'
  $existingProcessRecords = @()
  if ($resourceIdentityWasUnknown) {
    if ($null -eq $prePulseContinuationPlan -and $processSpecifications.Count -ne 1) {
      throw 'Unknown resource identity must start from one formal first batch.'
    }
    $formalObservation = Start-ObservedFormalProcess `
      -DispatchPlanPath $runtimeDispatchPlanPath `
      -ProcessSpecification $processSpecifications[0]
    if ($formalObservation.resource_budget_exceeded) {
      $resourceBudgetExceeded = $true
      throw 'The first formal SIMION batch exceeded the repository memory-danger policy.'
    }
    if ($formalObservation.completed_naturally -and
        ($null -eq $formalObservation.exit_code -or [int]$formalObservation.exit_code -ne 0)) {
      throw 'The first formal SIMION batch failed before adaptive replanning.'
    }
    if ([int64]$formalObservation.observed_peak_process_tree_working_set_bytes -lt 1) {
      throw 'The first formal SIMION batch did not produce a usable resource observation.'
    }
    $replanArguments = @(
      '-m','common.simion.resource_scheduler','--prepared-plan',$preparedDispatchPlanPath,
      '--output',$runtimeDispatchPlanPath,
      '--available-memory-bytes',([string]$formalObservation.available_memory_bytes),
      '--total-physical-memory-bytes',([string]$formalObservation.total_physical_memory_bytes),
      '--observed-formal-peak-bytes',([string]$formalObservation.observed_peak_process_tree_working_set_bytes),
      '--observed-formal-cpu-percent',([string]$formalObservation.observed_process_cpu_percent),
      '--observed-background-cpu-percent',([string]$formalObservation.observed_background_cpu_percent)
    )
    if ($formalObservation.completed_naturally) {
      $replanArguments += '--first-batch-completed'
    }
    Invoke-SingleFlightPython -Arguments $replanArguments `
      -Failure 'Single-flight formal-first resource replanning failed.'
    $runtimeDispatchPlan = Get-Content -Raw -LiteralPath $runtimeDispatchPlanPath |
      ConvertFrom-Json
    if ([string]$runtimeDispatchPlan.estimation.kind -ne 'observed_formal_batch' -or
        @($runtimeDispatchPlan.waves).Count -ne 1 -or
        [int]$runtimeDispatchPlan.waves[0].batch_count -lt 1 -or
        [int]$runtimeDispatchPlan.waves[0].batch_count -gt $launched) {
      throw 'Single-flight formal-first dispatch plan is invalid.'
    }
    $executionBatchCount = [int]$runtimeDispatchPlan.waves[0].batch_count
    if ($null -eq $prePulseContinuationPlan) {
      Invoke-SingleFlightPython -Arguments @(
        '-m','common.simion.particle_batching','--from-dispatch-plan',$runtimeDispatchPlanPath,
        '--output',$batchPlanPath
      ) -Failure 'Single-flight formal-first batch planning failed.'
      $batchPlan = Get-Content -Raw -LiteralPath $batchPlanPath | ConvertFrom-Json
      $batchRecords = @(New-SingleFlightBatchRecords $batchPlan)
      $stdoutFiles = @($batchRecords | ForEach-Object { $_.stdout })
      $stderrFiles = @($batchRecords | ForEach-Object { $_.stderr })
      $processSpecifications = @(New-SingleFlightProcessSpecifications $batchRecords)
    }
    $existingProcessRecords = @($formalObservation.process_record)
    $processSpecifications = @($processSpecifications | Select-Object -Skip 1)
    $runConfiguration.parameters.execution_batch_count = $executionBatchCount
    $runConfiguration.parameters.execution_batches_parallel = [bool]($executionBatchCount -gt 1)
    $runConfiguration.parameters.simion_single_wave_batch_plan_sha256 =
      (Get-FileHash -Algorithm SHA256 -LiteralPath $batchPlanPath).Hash
    $runConfiguration.parameters.simion_repository_dispatch_plan_sha256 =
      (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeDispatchPlanPath).Hash
    Write-RunJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  }
  $prePulseCheckpointOutputs = [System.Collections.Generic.List[string]]::new()
  $prePulseCheckpointAction = $null
  if ($isPrePulseTimeSeriesScreening) {
    # A batch becomes a reusable checkpoint only after SIMION exits naturally.
    # The shared scheduler invokes this action after each such completion;
    # publishing the manifest atomically binds the current frozen run config
    # and every completed raw log before another batch may fail or be stopped.
    $prePulseCheckpointAction = {
      param($completedRecord)
      foreach ($path in @(
          [string]$completedRecord.specification.stdout,
          [string]$completedRecord.specification.stderr
      )) {
        if (-not [string]::IsNullOrWhiteSpace($path) -and
            (Test-Path -LiteralPath $path -PathType Leaf) -and
            -not $prePulseCheckpointOutputs.Contains($path)) {
          $prePulseCheckpointOutputs.Add($path)
        }
      }
      Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
        -RunConfig $package.run_config -Manifest $package.run_manifest `
        -Status interrupted -Software @('SIMION 2020','Python 3.11') `
        -Outputs @($prePulseCheckpointOutputs)
    }
  }
  $waveResult = Invoke-ResourceBudgetedProcesses `
    -DispatchPlanPath $runtimeDispatchPlanPath `
    -RunDir $package.run_dir -UsagePath $resourceUsage `
    -ProcessSpecifications $processSpecifications `
    -ExistingProcessRecords $existingProcessRecords `
    -OnProcessCompleted $prePulseCheckpointAction
  if ($waveResult.resource_budget_exceeded) {
    $resourceBudgetExceeded = $true
    throw 'Single-flight SIMION batch wave exceeded its aggregate resource budget.'
  }
  if (@($waveResult.processes | Where-Object { [int]$_.exit_code -ne 0 }).Count -ne 0) {
    throw 'Single-flight SIMION batch wave failed.'
  }

  if ($isPrePulseTimeSeriesScreening) {
    $statesCsv = Join-Path $package.result_dir 'pre_pulse_time_series_states.csv'
    $screeningReceipt = Join-Path $package.result_dir `
      'pre_pulse_time_series_screening_receipt.json'
    $materializerArguments = @(
      '-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_pre_pulse_time_series',
      '--run-config',$package.run_config,
      '--pre-pulse-time-series-contract-sha256',$PrePulseTimeSeriesContractSha256,
      '--states-output',$statesCsv,
      '--receipt-output',$screeningReceipt,
      '--summary-output',$package.summary
    )
    foreach ($stdoutFile in $stdoutFiles) {
      $materializerArguments += @('--stdout-log',$stdoutFile)
    }
    Invoke-SingleFlightPython -Arguments $materializerArguments `
      -Failure 'Pre-pulse time-series materialization failed.'
    $materializedSummary = Get-Content -Raw -LiteralPath $package.summary `
      -Encoding UTF8 | ConvertFrom-Json
    $stateRowCount = [int]$materializedSummary.census.observed_state_rows
    $runConfiguration.parameters.pre_pulse_time_series_state_row_count = $stateRowCount
    Write-RunJson -Path $package.run_config -Depth 10 -Value $runConfiguration
    $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot `
      -RunConfig $package.run_config
    foreach ($usage in $resourceUsageFiles) {
      if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget `
            -RunDir $package.run_dir -UsagePath $usage)) {
        $resourceBudgetExceeded = $true
        throw 'Pre-pulse time-series compact retained-byte budget exceeded.'
      }
    }
  $outputs = @($statesCsv,$screeningReceipt,$package.summary,$retentionActions) +
      $stdoutFiles + $stderrFiles + $resourceUsageFiles |
      Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    Write-RunManifest -Python $python -RepoRoot $repoRoot `
      -RunConfig $package.run_config -Status success `
      -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
    $hostExecutionOutcome = 'success'
    Write-Output "SIMION_PRE_PULSE_TIME_SERIES=PASS RUN_ID=$RunId ROWS=$stateRowCount"
    return
  }

  $checkpoints = Join-Path $package.result_dir 'single_flight_particle_checkpoints.csv'
  $analysisArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight',
    '--resolved-population-contract',$populationContractFrozen,
    '--resolved-population-contract-sha256',$ResolvedPopulationContractSha256,
    '--geometry',$oatofGeometry,
    '--clock-basis',([string]$executionProfile.clock_basis),
    '--initial-global-state',$globalSource,
    '--particle-row-map',$particleRowMap,
    '--initial-global-state-sha256',((Get-FileHash -LiteralPath $globalSource -Algorithm SHA256).Hash),
    '--checkpoints',$checkpoints,'--summary',$package.summary)
  $analysisArguments += '--require-terminal-taxonomy'
  $analysisArguments += @('--pulse-time-us',([string]$pulseTimeUs))
  if ($sourceReleaseMode -eq 'pre_pulse_restart') {
    if ($PrePulseRestartPositionToleranceMm -le 0 -or
        $PrePulseRestartVelocityToleranceMPerS -le 0 -or
        $PrePulseRestartClockToleranceUs -le 0 -or
        $PrePulseRestartEnergyToleranceEv -le 0) {
      throw 'Pre-pulse restart requires positive frozen source-release tolerances.'
    }
    $analysisArguments += @(
      '--restart-position-tolerance-mm',([string]$PrePulseRestartPositionToleranceMm),
      '--restart-velocity-tolerance-m-per-s',([string]$PrePulseRestartVelocityToleranceMPerS),
      '--restart-clock-tolerance-us',([string]$PrePulseRestartClockToleranceUs),
      '--restart-energy-tolerance-eV',([string]$PrePulseRestartEnergyToleranceEv),
      '--restart-validation-contract-sha256',$PrePulseRestartValidationSha256
    )
  }
  if ($spatialWindowProfiles.Count -eq 1 -or
      $sourceRegionDiagnosticProfiles.Count -eq 1) {
    $analysisArguments += @('--configuration',$configuration)
  }
  if ($spatialWindowProfiles.Count -eq 1) {
    $analysisArguments += @(
      '--spatial-window-profile-id',
      [string]$executionProfile.spatial_window_profile_id
    )
  }
  if ($sourceRegionDiagnosticProfiles.Count -eq 1) {
    $analysisArguments += @(
      '--source-region-diagnostic-profile-id',$sourceRegionDiagnosticProfileId
    )
  }
  if ($hasThreeZoneCandidate) {
    $analysisArguments += '--require-three-zone-checkpoint-census'
  }
  foreach ($batch in $batchRecords) {
    $analysisArguments += @(
      '--log',$batch.stdout,
      '--batch-particle-count',([string]$batch.count)
    )
  }
  Invoke-SingleFlightPython -Arguments $analysisArguments `
    -Failure 'Single-flight log analysis failed.'
  $sixPanel = Join-Path $package.result_dir 'single_flight_spatial_six_panel.png'
  $sixPanelMetadata = Join-Path $package.result_dir 'single_flight_spatial_six_panel_metadata.json'
  $phaseSpace = Join-Path $package.result_dir 'single_flight_accelerator_pre_pulse_phase_space.png'
  $phaseSpaceMetadata = Join-Path $package.result_dir 'single_flight_accelerator_pre_pulse_phase_space_metadata.json'
  $phaseSpaceData = Join-Path $package.result_dir 'single_flight_accelerator_pre_pulse_phase_space.csv'
  $evolution = Join-Path $package.result_dir 'single_flight_accelerator_checkpoint_evolution.png'
  $evolutionMetadata = Join-Path $package.result_dir 'single_flight_accelerator_checkpoint_evolution_metadata.json'
  $evolutionData = Join-Path $package.result_dir 'single_flight_accelerator_checkpoint_evolution.csv'
  $hasStatisticalDiagnostics = $launched -gt 1
  if ($hasStatisticalDiagnostics) {
    Invoke-SingleFlightPython -Arguments @('-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel',
      '--initial',$globalSource,'--checkpoints',$checkpoints,'--upstream',$upstreamFrozen,
      '--frontend',$frontendContract,'--oatof',$oatofGeometry,'--output',$sixPanel,
      '--metadata',$sixPanelMetadata,'--phase-space-output',$phaseSpace,
      '--phase-space-metadata',$phaseSpaceMetadata,'--phase-space-data',$phaseSpaceData,
      '--evolution-output',$evolution,'--evolution-metadata',$evolutionMetadata,
      '--evolution-data',$evolutionData
    ) -Failure 'Single-flight spatial and phase-space diagnostics failed.'
  }
  $result = Get-Content -LiteralPath $package.summary -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($hasThreeZoneCandidate) {
    $runConfiguration.parameters.accelerator_intermediate2_forward_count =
      [int]$result.census.accelerator_intermediate2_forward
  }
  $result | Add-Member -NotePropertyName single_flight_pa_cache_policy `
    -NotePropertyValue $PaCachePolicy -Force
  $result | Add-Member -NotePropertyName single_flight_pa_cache_policy_provenance `
    -NotePropertyValue $PaCachePolicyProvenance -Force
  $result | Add-Member -NotePropertyName pa_cache_dispositions `
    -NotePropertyValue $paCacheDispositions -Force
  $result | Add-Member -NotePropertyName accelerator_pre_pulse_phase_space `
    -NotePropertyValue $(if ($hasStatisticalDiagnostics) { [ordered]@{
      figure='results/single_flight_accelerator_pre_pulse_phase_space.png'
      metadata='results/single_flight_accelerator_pre_pulse_phase_space_metadata.json'
      data='results/single_flight_accelerator_pre_pulse_phase_space.csv'
      claim_status='DIAGNOSTIC_ONLY'
      selection_uses_detector_outcome=$false
    }} else { [ordered]@{
      status='NOT_RUN';reason='one_ion_functional_smoke_has_no_statistical_phase_space_diagnostic'
      claim_status='PROHIBITED';selection_uses_detector_outcome=$false
    }}) -Force
  $result | Add-Member -NotePropertyName accelerator_checkpoint_evolution `
    -NotePropertyValue $(if ($hasStatisticalDiagnostics) { [ordered]@{
      figure='results/single_flight_accelerator_checkpoint_evolution.png'
      metadata='results/single_flight_accelerator_checkpoint_evolution_metadata.json'
      data='results/single_flight_accelerator_checkpoint_evolution.csv'
      claim_status='DIAGNOSTIC_ONLY'
      selection_uses_detector_outcome=$false
    }} else { [ordered]@{
      status='NOT_RUN';reason='one_ion_functional_smoke_has_no_statistical_checkpoint_evolution'
      claim_status='PROHIBITED';selection_uses_detector_outcome=$false
    }}) -Force
  Write-RunJson -Path $package.summary -Depth 10 -Value $result
  $runConfiguration.parameters.multipole_handoff_count = [int]$result.census.multipole_handoff
  $runConfiguration.parameters.local_accelerator_exit_count = [int]$result.census.local_accelerator_exit
  $runConfiguration.parameters.detector_crossing_count = [int]$result.census.detector_crossing
  Write-RunJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $diagnosticOutputs = if ($hasStatisticalDiagnostics) {
    @($sixPanel,$sixPanelMetadata,$phaseSpace,$phaseSpaceMetadata,$phaseSpaceData,$evolution,$evolutionMetadata,$evolutionData)
  } else { @() }
  $outputs = @($checkpoints) + $diagnosticOutputs + $stdoutFiles + $stderrFiles + $resourceUsageFiles + @($flightTubeBuildStdout,$flightTubeBuildStderr,$reflectronBuildStdout,$reflectronBuildStderr,$package.summary,$retentionActions) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
  foreach ($usage in $resourceUsageFiles) {
    if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath $usage)) { $resourceBudgetExceeded=$true; throw 'Single-flight compact retained-byte budget exceeded.' }
  }
  $resourceProfile = $null
  if ($resourceIdentityWasUnknown) {
    $resourceProfile = Join-Path $package.result_dir 'simion_resource_profile.json'
    Invoke-SingleFlightPython -Arguments @(
      '-m','common.simion.resource_profile','publish','--run-id',$RunId,
      '--resource-usage',$resourceUsage,'--resource-usage-relative-path','logs/resource_usage.json',
      '--dispatch-plan',$runtimeDispatchPlanPath,'--output',$resourceProfile
    ) -Failure 'Single-flight SIMION resource profile publication failed.'
  }
  if ($resourceProfile) { $outputs += $resourceProfile }
  Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $hostExecutionOutcome = 'success'
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after successful run: $($_.Exception.Message)"
  }
  Write-Output "SIMION_SINGLE_FLIGHT=PASS RUN_ID=$RunId DETECTOR=$($result.census.detector_crossing)/$launched"
} catch {
  $hostExecutionOutcome = if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}
  Complete-FailedRun -Python $python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Summary $package.summary `
    -SummaryRole $summaryRole -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11') `
    -Status $(if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}) `
    -FailureClass $(if ($resourceBudgetExceeded) {'resource_budget_exceeded'} else {''}) `
    -AdditionalSummaryProperties ([ordered]@{
      single_flight_pa_cache_policy=$PaCachePolicy
      single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance
      pa_cache_dispositions=$paCacheDispositions
      frozen_input_snapshot_completed=[bool]$snapshotReady
      failure_exception_type=$_.Exception.GetType().FullName
      failure_script_stack_trace=[string]$_.ScriptStackTrace
    }) `
    -ResourceUsagePath $(if ($resourceBudgetExceeded) {$resourceUsage} else {''})
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after failed run: $($_.Exception.Message)"
  }
  throw
} finally {
  Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId
}
