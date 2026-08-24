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
  [Parameter(Mandatory)]
  [ValidateSet('require_existing','build_and_publish_if_missing')]
  [string]$PaCachePolicy,
  [Parameter(Mandatory)]
  [ValidateSet('explicit_campaign_row')]
  [string]$PaCachePolicyProvenance,
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
  [switch]$ResolutionQualification,
  [string]$PrePulseTimeSeriesContract = '',
  [string]$PrePulseTimeSeriesContractSha256 = '',
  [ValidateScript({ $_ -ge 1 })][int]$ExecutionBatchCount = 1,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
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
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256
. $runtime.run_artifact_support
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')

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

$hasThreeZoneCandidate = Assert-RfThreeZoneArgumentSet -Candidate $ThreeZoneCandidate -CandidateSha256 $ThreeZoneCandidateSha256

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) { throw "SIMION is missing: $SimionExe" }
$runProjectId = 'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
$simionSolverCacheIdentity = Get-RfSimionSolverCacheIdentity -SimionExe $SimionExe
$isPrePulseTimeSeriesScreening = -not [string]::IsNullOrWhiteSpace(
  $PrePulseTimeSeriesContract
)
if ($isPrePulseTimeSeriesScreening -ne (-not [string]::IsNullOrWhiteSpace(
      $PrePulseTimeSeriesContractSha256))) {
  throw 'Pre-pulse time-series contract path/hash identity is incomplete.'
}
if ($isPrePulseTimeSeriesScreening -and (
    $ResolutionQualification -or
    $PaCachePolicy -notin @('require_existing','build_and_publish_if_missing'))) {
  throw 'Pre-pulse time-series screening requires FUNCTIONAL_ONLY cache-governed execution.'
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
  accelerator_overlay = [ordered]@{
    role='simion_accelerator_overlay_pa_cache';key=$null
    disposition='pending_cache_decision'
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
  if ([int]$prePulseTimeSeries.schema_version -notin @(1, 2) -or
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
    single_flight_pa_cache_policy=$PaCachePolicy
    single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance
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

try {
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
  if ([string]$resolvedBudgetDocument.single_flight_pa_cache_policy -ne
      $PaCachePolicy -or
      [string]$resolvedBudgetDocument.single_flight_pa_cache_policy_provenance -ne
      $PaCachePolicyProvenance) {
    throw 'Runner PA cache policy differs from the frozen resolved engineering budget.'
  }
  $PaCachePolicy = [string]$resolvedBudgetDocument.single_flight_pa_cache_policy
  $PaCachePolicyProvenance = [string](
    $resolvedBudgetDocument.single_flight_pa_cache_policy_provenance
  )
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
  $requiredQualificationBootstrapResamples = [int]$executionProfile.required_qualification_bootstrap_resamples
  $overlayEnabled = [bool]$executionProfile.accelerator_overlay_enabled
  $resolvedFieldOverlayId = [string]$executionProfile.field_overlay_id
  $overlayCellMmX = if ($overlayEnabled) { [double]$executionProfile.accelerator_overlay_cell_mm_xyz.x } else { $null }
  $overlayCellMmY = if ($overlayEnabled) { [double]$executionProfile.accelerator_overlay_cell_mm_xyz.y } else { $null }
  $overlayCellMmZ = if ($overlayEnabled) { [double]$executionProfile.accelerator_overlay_cell_mm_xyz.z } else { $null }
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
  $threeZoneCandidateDocument = $null
  if ($hasThreeZoneCandidate) {
    $threeZoneCandidateFrozen = Join-Path $package.input_dir 'three_zone_t5_candidate_resolved.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $ThreeZoneCandidate -Destination $threeZoneCandidateFrozen -Role 'three-zone T5 Candidate resolved input' | Out-Null
    if ((Get-FileHash -LiteralPath $threeZoneCandidateFrozen -Algorithm SHA256).Hash -ne
        $ThreeZoneCandidateSha256) {
      throw 'Three-zone T5 Candidate SHA differs.'
    }
    $threeZoneCandidateDocument = Get-Content -LiteralPath $threeZoneCandidateFrozen -Raw -Encoding UTF8 | ConvertFrom-Json
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
  if ($ExecutionBatchCount -gt $launched) {
    throw 'Single-flight execution batch count exceeds launched particle count.'
  }
  $sourceRegionDiagnosticProfileId = [string]$executionProfile.source_region_diagnostic_profile_id
  $sourceRegionDiagnosticProfiles = @($sourceRegionDiagnosticProfileId | Where-Object { $_ })
  if ($ResolutionQualification -and
      $BootstrapResamples -ne $requiredQualificationBootstrapResamples) {
    throw 'Resolution qualification bootstrap resamples differ from the frozen policy.'
  }
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
  } elseif ($hasMotherOverride) { [IO.Path]::GetFullPath($MotherParticleSource) } else { $runtime.source_particle_source }
  $motherSourceRoot = if ($hasMotherSourceRunRoot) {
    [IO.Path]::GetFullPath($MotherParticleSourceRunRoot)
  } elseif ($isPrePulseRestart) { $workspaceRoot } elseif ($hasMaterializedMotherReceipt) {
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
  if (($isPrePulseRestart -and $PrePulseSourceStateCount -ne $launched) -or
      ($hasMotherOverride -and $MotherParticleCount -ne $launched) -or
      (-not $isPrePulseRestart -and
       -not $hasMotherOverride -and
       [int]$runtime.source_record.launched_particle_count -ne $launched)) {
    throw 'Single-flight source count differs from the resolved population authority.'
  }
  if ($requiresEligiblePopulation -and
      ($PopulationDenominatorCount -lt $EligiblePopulationCount -or
       $EligiblePopulationCount -lt $launched)) {
    throw 'Conditional-source population counts are inconsistent.'
  }
  if (@(Import-Csv -LiteralPath $motherSource).Count -ne $launched) {
    throw 'Single-flight mother sample count differs from source authority.'
  }
  $frontendGem = Join-Path $package.input_dir 'single_flight_frontend.gem'
  $frontendContract = Join-Path $package.input_dir 'single_flight_frontend_contract.json'
  $overlayGem = if ($overlayEnabled) { Join-Path $package.input_dir 'accelerator_overlay.gem' } else { $null }
  $overlayContract = if ($overlayEnabled) { Join-Path $package.input_dir 'accelerator_overlay_contract.json' } else { $null }
  $frontendCompileArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend',
    '--upstream',$upstreamFrozen,'--oatof',$oatofGeometry,
    '--connection',$resolvedFrozen,'--gem',$frontendGem,'--contract',$frontendContract,
    '--cell-mm-x',([string]$frontendCellMmX),
    '--cell-mm-y',([string]$frontendCellMmY),
    '--cell-mm-z',([string]$frontendCellMmZ))
  if ($overlayEnabled) {
    $frontendCompileArguments += @(
      '--overlay-gem',$overlayGem,'--overlay-contract',$overlayContract,
      '--overlay-cell-mm-x',([string]$overlayCellMmX),
      '--overlay-cell-mm-y',([string]$overlayCellMmY),
      '--overlay-cell-mm-z',([string]$overlayCellMmZ))
  }
  Invoke-SingleFlightPython -Arguments $frontendCompileArguments `
    -Failure 'Single-flight frontend compilation failed.'
  $frontendGeometry = Get-Content -LiteralPath $frontendContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
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
    $threeZoneTopologyId = [string]$threeZoneCandidateDocument.identities.topology_id
    $threeZoneGeometryId = [string]$threeZoneCandidateDocument.identities.geometry_id
    $threeZoneFrontendElectrodeTopologyId = [string]$frontendElectrodeTopology.topology_id
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
    $threeZoneFieldId = [string](
      Get-Content -LiteralPath $threeZoneRuntimeIdentity -Raw -Encoding UTF8 |
      ConvertFrom-Json
    ).field_id
    if ([string]::IsNullOrWhiteSpace($threeZoneFieldId)) {
      throw 'Frozen three-zone Candidate/runtime identity differs.'
    }
  }
  $apertureWidthMm = [double]$frontendGeometry.aperture.width_mm
  $apertureHeightMm = [double]$frontendGeometry.aperture.height_mm
  $apertureDiscretization = $frontendGeometry.junction_enclosure.aperture_discretization
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
  $frontendCacheRole = 'simion_single_flight_frontend_pa_cache'
  $frontendCacheIdentity = [ordered]@{
    schema_version=2; role=$frontendCacheRole
    project_id=$runProjectId; solver=$simionSolverCacheIdentity
    inputs=[ordered]@{frontend_gem_sha256=$frontendHash}
    critical_options=[ordered]@{
      gem2pa=@('--nogui','--noprompt','gem2pa','frontend.gem','frontend.pa#')
      refine=@('--nogui','--noprompt','refine','frontend.pa#')
    }
  }
  $frontendCacheKey = Get-RfContentIdentitySha256 -Identity $frontendCacheIdentity
  $paCacheDispositions.frontend.key = $frontendCacheKey
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
    Copy-Item -LiteralPath $frontendGem -Destination $cacheGem
    $gem2pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_gem2pa_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $frontendBuildDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_gem2pa.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_gem2pa.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','gem2pa',$cacheGem,$cachePaSharp)
    if ($gem2pa.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend GEM conversion exceeded its resource budget.' }
    if ($gem2pa.exit_code -ne 0) { throw 'Frontend GEM conversion failed.' }
    $refine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_refine_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $frontendBuildDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_refine.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_refine.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','refine',$cachePaSharp)
    if ($refine.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend refinement exceeded its resource budget.' }
    if ($refine.exit_code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $frontendBuildDir 'frontend.pa0') -PathType Leaf)) { throw 'Frontend PA refinement failed.' }
    $cacheDir = Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot `
      -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId -CacheRoot $cacheRoot `
      -CacheKey $frontendCacheKey -Role $frontendCacheRole -Identity $frontendCacheIdentity `
      -StagingDirectory $frontendBuildDir -ProviderRunId $RunId
    $paCacheDispositions.frontend.disposition = 'built_and_published'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_published'
    } catch {
      if (Test-Path -LiteralPath $frontendBuildDir) {
        Remove-Item -LiteralPath $frontendBuildDir -Recurse -Force
      }
      throw
    }
  }
  if (-not $frontendRefineRequired) {
    $paCacheDispositions.frontend.disposition = 'cache_hit'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_hit'
  }
  } finally {
    Exit-RfCacheKeyLock -Mutex $frontendCacheLock
  }
  $cacheGem = Join-Path $cacheDir 'frontend.gem'; $cachePaSharp = Join-Path $cacheDir 'frontend.pa#'; $cachePa0 = Join-Path $cacheDir 'frontend.pa0'
  $frontendWorkingDir = Join-Path $package.run_dir 'simion\frontend_cache_copy'
  New-Item -ItemType Directory -Path $frontendWorkingDir -Force | Out-Null
  foreach ($source in Get-ChildItem -LiteralPath $cacheDir -Filter 'frontend.pa*' -File) {
    $target = Join-Path $frontendWorkingDir $source.Name
    Copy-Item -LiteralPath $source.FullName -Destination $target -Force
    Set-RfMaterializedCacheFileWritable -Path $target
  }
  $frontendWorkingPa0 = Join-Path $frontendWorkingDir 'frontend.pa0'

  $overlayGeometry = $null
  $overlayCacheDir = $null
  $overlayCachePa0 = $null
  $overlayBasisBuilderFrozen = $null
  $overlayRefinerFrozen = $null
  $overlayKey = $null
  $overlayBasisReport = $null
  $overlayInterfaceVerifierFrozen = $null
  $overlayInterfaceReport = $null
  if ($overlayEnabled) {
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
        refinement_convergence='5e-7'
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
        foreach ($electrode in $frontendBasisElectrodeIds) {
          $singleOverlayPa = Join-Path $overlayBuildDir "accelerator_overlay.pa$electrode"
          $singleOverlayRefine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
            -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir "overlay_refine_pa${electrode}_resource_usage.json") `
            -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
            -RedirectStandardOutput (Join-Path $package.log_dir "overlay_refine_pa${electrode}.stdout.log") `
            -RedirectStandardError (Join-Path $package.log_dir "overlay_refine_pa${electrode}.stderr.log") `
            -ArgumentList @('--nogui','--noprompt','lua',$overlayRefinerFrozen,$singleOverlayPa,'5e-7')
          if ($singleOverlayRefine.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw "Overlay pa$electrode refine exceeded its resource budget." }
          if ($singleOverlayRefine.exit_code -ne 0) { throw "Overlay pa$electrode refine failed." }
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

  $isRestartFly2 = $isPrePulseRestart
  $particleInput = Join-Path $package.input_dir $(if ($isRestartFly2) {
      'single_flight_mother_sample.fly2'
    } else {
      'single_flight_mother_sample.ion'
    })
  $globalSource = Join-Path $package.input_dir 'single_flight_initial_global_state.csv'
  $particleRowMap = Join-Path $package.input_dir 'single_flight_particle_row_map.csv'
  $sourceArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source',
    '--source',$motherSource,'--connection',$resolvedFrozen,'--particle-input',$particleInput,'--global-state',$globalSource,
    '--row-map',$particleRowMap,
    '--source-release-mode',$sourceReleaseMode)
  if ($isPrePulseRestart) {
    $sourceArguments += @('--pulse-time-us',([string]$pulseTimeUs))
  }
  Invoke-SingleFlightPython -Arguments $sourceArguments `
    -Failure 'Single-flight source materialization failed.'

  $runtimeDir = Join-Path $package.run_dir 'simion'
  $formalDir = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer\formal\simion'
  Copy-RfOatofFormalPaSet -FormalDir $formalDir -Destination $runtimeDir
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
      refinement_convergence='5e-7';midgrid_voltage_V=[double]$voltage.midgrid
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
    $cacheKeys = if ([int]$prePulseTimeSeries.schema_version -eq 2) {
      $roles = $prePulseTimeSeries.pa_cache_roles
      if ([string]$roles.identity_source -ne
          'runner_materialized_verified_pa_cache_receipt' -or
          (@($roles.required) -join ',') -ne 'frontend,accelerator_overlay' -or
          (@($roles.prohibited) -join ',') -ne 'flight_tube,reflectron') {
        throw 'Pre-pulse time-series PA cache role policy differs.'
      }
      [ordered]@{
        frontend = $frontendCacheKey
        accelerator_overlay = $overlayKey
        flight_tube = $null
        reflectron = $null
      }
    } else {
      $prePulseTimeSeries.pa_cache_keys
    }
    $rfGrid = $prePulseTimeSeries.rf_time_grid
    $upstreamDocument = Get-Content -LiteralPath $upstreamFrozen -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $motherSourceActualSha256 = (Get-FileHash -LiteralPath $motherSource `
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
    if (@($identityChecks | Where-Object { $_[0] -ne $_[1] }).Count -ne 0 -or
        [string]$cacheKeys.frontend -ne $frontendCacheKey -or
        [string]$cacheKeys.accelerator_overlay -ne [string]$overlayKey -or
        $null -ne $cacheKeys.flight_tube -or
        $null -ne $cacheKeys.reflectron) {
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
  function Copy-RfPaCacheFamilyToRuntime {
    param([Parameter(Mandatory)][string]$CacheDirectory,[Parameter(Mandatory)][string]$Pattern)
    foreach ($source in Get-ChildItem -LiteralPath $CacheDirectory -Filter $Pattern -File) {
      $target = Join-Path $runtimeDir $source.Name
      Copy-Item -LiteralPath $source.FullName -Destination $target -Force
      Set-RfMaterializedCacheFileWritable -Path $target
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
  if ($overlayEnabled) {
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
  $topologyResult = Invoke-SimionCompiledApertureTopologyCheck `
    -PaPath $frontendWorkingPa0 -ReportPath $apertureTopologyReport -VerifierPath $apertureVerifier `
    -OriginXmm ([double]$frontendGeometry.instance_origin_mm.x) `
    -OriginYmm ([double]$frontendGeometry.instance_origin_mm.y) `
    -OriginZmm ([double]$frontendGeometry.instance_origin_mm.z) `
    -CellMmX ([double]$frontendGeometry.cell_mm_xyz.x) `
    -CellMmY ([double]$frontendGeometry.cell_mm_xyz.y) `
    -CellMmZ ([double]$frontendGeometry.cell_mm_xyz.z) `
    -FlangeXMinMm ([double]$apertureDiscretization.flange_x_min_mm) `
    -FlangeXMaxMm ([double]$apertureDiscretization.flange_x_max_mm) `
    -CenterYmm ([double]$frontendGeometry.source_exit_center_mm.y) `
    -CenterZmm ([double]$frontendGeometry.source_exit_center_mm.z) `
    -MechanicalWidthMm $apertureWidthMm -MechanicalHeightMm $apertureHeightMm `
    -BooleanBoundaryPolicy ([string]$apertureDiscretization.boolean_boundary_policy) `
    -InvokeVerifier {
      param($verifierPath)
      Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir 'frontend_aperture_topology_resource_usage.json') -FilePath $SimionExe `
        -WorkingDirectory $frontendWorkingDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_aperture_topology.stdout.log') `
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
        -ArgumentList @('--nogui','--noprompt','lua',$reflectronRefinerFrozen,$singlePa,'5e-7')
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
  if ($overlayEnabled) {
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
    } finally {
      if (Test-Path -LiteralPath $overlayIobStageDir) {
        Remove-Item -LiteralPath $overlayIobStageDir -Recurse -Force
      }
    }
    if ($overlayIobBuild.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay IOB build exceeded its resource budget.' }
    if ($overlayIobBuild.exit_code -ne 0) { throw 'Overlay IOB build failed.' }
  }
  if ($null -eq (Resolve-RfReusableCacheDirectory -Python $python -RepoRoot $repoRoot `
      -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $cacheRoot -CacheKey $frontendCacheKey -Role $frontendCacheRole `
      -Identity $frontendCacheIdentity -InvalidEntryAction 'preserve')) {
    throw 'Frontend PA cache changed during construction-time SIMION access.'
  }
  $frontendCacheManifestInput = Copy-RfCacheManifestInput -CacheEntry $cacheDir `
    -Destination (Join-Path $package.input_dir 'frontend_pa_cache_manifest.json')
  $flightTubeCacheManifestInput = if ($flightTubeCacheUsed) {
    Copy-RfCacheManifestInput -CacheEntry $flightTubeCacheDir `
      -Destination (Join-Path $package.input_dir 'flight_tube_pa_cache_manifest.json')
  } else { $null }
  $reflectronCacheManifestInput = if ($reflectronCacheUsed) {
    Copy-RfCacheManifestInput -CacheEntry $reflectronCacheDir `
      -Destination (Join-Path $package.input_dir 'reflectron_pa_cache_manifest.json')
  } else { $null }
  $overlayCacheManifestInput = if ($overlayEnabled) {
    Copy-RfCacheManifestInput -CacheEntry $overlayCacheDir `
      -Destination (Join-Path $package.input_dir 'accelerator_overlay_pa_cache_manifest.json')
  } else { $null }
  $cacheManifestBindings = @(
    [ordered]@{disposition=$paCacheDispositions.frontend; path=$frontendCacheManifestInput}
  )
  if ($null -ne $flightTubeCacheManifestInput) {
    $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.flight_tube;path=$flightTubeCacheManifestInput}
  }
  if ($null -ne $reflectronCacheManifestInput) {
    $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.reflectron;path=$reflectronCacheManifestInput}
  }
  if ($null -ne $overlayCacheManifestInput) {
    $cacheManifestBindings += [ordered]@{disposition=$paCacheDispositions.accelerator_overlay;path=$overlayCacheManifestInput}
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
  if ($null -ne $restartContext) {
    $programArguments += @('--restart-context',$restartContext)
  }
  if ($isPrePulseTimeSeriesScreening) {
    $programArguments += @(
      '--pre-pulse-time-series-contract',$prePulseTimeSeriesContractFrozen
    )
  }
  if ($null -ne $prePulseValidationFrozen) { $programArguments += '--global-segments' }
  if ($overlayEnabled) { $programArguments += @('--accelerator-overlay-contract',$overlayContract) }
  Invoke-SingleFlightPython -Arguments $programArguments `
    -Failure 'Single-flight Program build failed.' `
    -StdoutPath (Join-Path $package.log_dir 'single_flight_program_build.stdout.log') `
    -StderrPath (Join-Path $package.log_dir 'single_flight_program_build.stderr.log')

  $runConfiguration = [ordered]@{
    schema_version=2; run_id=$RunId; project=$runProjectId; mode='rf_to_oatof_simion_single_flight'; project_root=$repoRoot
    upstream_project_id=$runtime.upstream_project_id
    inputs=[ordered]@{ configuration=$configuration; resolved_single_flight_execution_profile=$executionProfilePath; runtime_binding=$runtimeBindingFrozen; resolved_connection=$resolvedFrozen; resolved_source_contract=$sourceContractFrozen; resolved_population_contract=$populationContractFrozen; resolved_single_flight_population=$runtimePopulationPath; upstream_resolved_design=$upstreamFrozen; oatof_resolved_geometry=$oatofGeometry; pulse_schedule=$pulseScheduleFrozen; resolved_region_field_contract=$resolvedRegionFieldContractFrozen; analyzer_component=$analyzerComponent; pulse_hook=$pulseHook; frontend_hook=$frontendHook; rf_drive_kernel=$rfDriveKernel; resolved_integration_engineering_budget=$budget.frozen_budget; resolved_stage_resource_budget=$budget.stage_budget; mother_particle_source=$motherSource; mother_particle_source_materialization_receipt=$motherSourceReceiptFrozen; initial_global_state=$globalSource; particle_row_map=$particleRowMap; pre_pulse_restart_validation=$prePulseValidationFrozen; particle_input=$particleInput; frontend_gem=$frontendGem; frontend_contract=$frontendContract; frontend_electrode_topology=$frontendElectrodeTopologyContract; frontend_pa_cache_manifest=$frontendCacheManifestInput; accelerator_overlay_gem=$overlayGem; accelerator_overlay_contract=$overlayContract; accelerator_overlay_basis_builder=$overlayBasisBuilderFrozen; accelerator_overlay_refiner=$overlayRefinerFrozen; accelerator_overlay_interface_verifier=$overlayInterfaceVerifierFrozen; accelerator_overlay_pa_cache_manifest=$overlayCacheManifestInput; accelerator_overlay_iob_builder=$overlayIobBuilderFrozen; accelerator_overlay_iob_container=$overlayIobContainerFrozen; accelerator_overlay_iob_container_gems=$overlayIobContainerGemFrozen; accelerator_overlay_basis_report=$overlayBasisReport; accelerator_overlay_interface_report=$overlayInterfaceReport; flight_tube_pa_cache_manifest=$flightTubeCacheManifestInput; reflectron_pa_cache_manifest=$reflectronCacheManifestInput; frontend_aperture_topology_support=$apertureTopologySupport; frontend_aperture_topology_verifier=$apertureVerifier; program_metadata=$programMetadata; candidate_flight_tube_builder=$flightTubeBuilderFrozen; candidate_flight_tube_gem=$flightTubeGemFrozen; candidate_reflectron_builder=$reflectronBuilderFrozen; candidate_reflectron_gem=$reflectronGemFrozen; candidate_reflectron_refiner=$reflectronRefinerFrozen }
    upstream_source_identity=$resolvedBudgetDocument.source_identity
    parameters=[ordered]@{ connection_profile_id=$ConnectionProfileId; source_branch_id=$SourceBranchId; single_flight_pa_cache_policy=$PaCachePolicy; single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance; pa_cache_dispositions=$paCacheDispositions; layout_profile_id=$(if($hasGovernedLayout){$LayoutProfileId}else{$null}); architecture_generation_id=$(if($hasGovernedLayout){$ArchitectureGenerationId}else{$null}); source_profile_id=$(if($SourceProfileId){$SourceProfileId}else{$null}); field_overlay_id=$resolvedFieldOverlayId; bore_radius_mm=[double]$oatofGeometryDocument.geometry_mm.bore_r; ring_outer_radius_mm=[double]$oatofGeometryDocument.geometry_mm.ring_outer_r; shield_inner_radius_mm=[double]$oatofGeometryDocument.geometry_mm.flight_tube_r; frontend_grid_profile_id=$selectedGridProfileId; frontend_cell_mm_xyz=[ordered]@{x=$frontendCellMmX;y=$frontendCellMmY;z=$frontendCellMmZ}; accelerator_overlay_enabled=$overlayEnabled; accelerator_overlay_cell_mm_xyz=$(if($overlayEnabled){[ordered]@{x=$overlayCellMmX;y=$overlayCellMmY;z=$overlayCellMmZ}}else{$null}); accelerator_overlay_boundary_mode=$(if($overlayEnabled){'coarse_electrode_basis_dirichlet_v1'}else{$null}); oatof_numerical_profile_id=$selectedOatofNumericalProfileId; trajectory_quality_profile_id=$selectedTrajectoryQualityProfileId; trajectory_quality=$trajectoryQuality; time_integration_profile_id=$selectedTimeIntegrationProfileId; rf_steps_per_period=$rfStepsPerPeriod; spatial_window_profile_id=$executionProfile.spatial_window_profile_id; source_region_diagnostic_profile_id=$(if($sourceRegionDiagnosticProfiles.Count -eq 1){$sourceRegionDiagnosticProfileId}else{$null}); accelerator_field_profile_id=$selectedFieldProfileId; resolved_region_field_contract_sha256=$ResolvedRegionFieldContractSha256; resolved_region_field_semantic_sha256=$ResolvedRegionFieldSemanticSha256; resolved_population_contract_sha256=$ResolvedPopulationContractSha256; clock_basis=[string]$executionProfile.clock_basis; launched_particle_count=$launched; particle_count=$launched; population_denominator_count=$PopulationDenominatorCount; eligible_population_count=$EligiblePopulationCount; population_basis=$populationBasis; execution_batch_count=$ExecutionBatchCount; execution_batches_parallel=[bool]($ExecutionBatchCount -gt 1); aperture_width_mm=$apertureWidthMm; aperture_height_mm=$apertureHeightMm; aperture_boolean_boundary_policy=[string]$apertureDiscretization.boolean_boundary_policy; aperture_grid_warnings=$apertureGridWarnings; frontend_open_aperture_column_count=[int]$apertureTopology.open_column_count; frontend_aperture_guard_electrode_check_passed=[bool]$apertureTopology.guard_electrode_check_passed; frontend_aperture_topology_report_sha256=(Get-FileHash -LiteralPath $apertureTopologyReport -Algorithm SHA256).Hash; rod_end_to_accelerator_shield_mm=[double]$frontendGeometry.junction_enclosure.rod_end_to_accelerator_shield_mm; surrounded_transition=$true; accelerator_axis_x_mm=[double]$oatofGeometryDocument.coordinate_convention.accelerator_axis_x; pulse_time_us=$pulseTimeUs; pulse_width_us=$pulseWidthUs; design_compilation=$(if($null -ne $layoutDerivation){$layoutDerivation.design_compilation}else{$null}); source_release_full_width_mm=[double]$oatofGeometryDocument.particle_source.size_z_mm; reflectron_stage2_length_mm=[double]$oatofGeometryDocument.geometry_mm.L_stage2; reflectron_midgrid_voltage_V=[double]$oatofGeometryDocument.electrodes_V.midgrid; reflectron_backplate_voltage_V=[double]$oatofGeometryDocument.electrodes_V.backplate; reflectron_pa0_sha256=(Get-FileHash -LiteralPath $reflectronPa0 -Algorithm SHA256).Hash; frontend_gem_sha256=$frontendHash; frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash; accelerator_overlay_pa0_sha256=$(if($overlayEnabled){(Get-FileHash -LiteralPath $overlayCachePa0 -Algorithm SHA256).Hash}else{$null}) }
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}; formal_gate_passed=$false
  }
  $runConfiguration.parameters.maximum_time_of_flight_us = $maximumTimeOfFlightUs
  $runConfiguration.parameters.bootstrap_resample_count = $BootstrapResamples
  $runConfiguration.parameters.bootstrap_seed = $BootstrapSeed
  $runConfiguration.parameters.resolution_qualification_required_bootstrap_resample_count =
    $requiredQualificationBootstrapResamples
  if ($isPrePulseTimeSeriesScreening) {
    $runConfiguration.inputs.pre_pulse_time_series_contract =
      $prePulseTimeSeriesContractFrozen
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
  $dispatchPlanPath = Join-Path $package.input_dir 'simion_repository_dispatch_plan.json'
  $resolvedBudgetDocument.single_flight_dispatch_plan | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $dispatchPlanPath -Encoding UTF8
  Invoke-SingleFlightPython -Arguments @(
    '-m','common.simion.particle_batching','--particle-count',([string]$launched),
    '--batch-count',([string]$runConfiguration.parameters.execution_batch_count),
    '--output',$batchPlanPath
  ) -Failure 'Shared SIMION single-wave batch planning failed.'
  $batchPlan = Get-Content -Raw -LiteralPath $batchPlanPath | ConvertFrom-Json
  if ($batchPlan.dispatch -ne 'single_wave_parallel' -or
      [int]$batchPlan.particle_count -ne [int]$launched) {
    throw 'Shared SIMION batch plan differs from the frozen launched population.'
  }
  $runConfiguration.inputs.simion_execution_batch_plan = $batchPlanPath
  $runConfiguration.inputs.simion_repository_dispatch_plan = $dispatchPlanPath
  $runConfiguration.parameters.simion_single_wave_batch_plan_sha256 =
    (Get-FileHash -Algorithm SHA256 -LiteralPath $batchPlanPath).Hash
  Write-RunJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RunJson -Path $package.summary -Depth 10 -Value ([ordered]@{schema_version=1;role=$summaryRole;status='interrupted';reason='Frozen inputs recorded; SIMION flight not complete.';single_flight_pa_cache_policy=$PaCachePolicy;single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance;pa_cache_dispositions=$paCacheDispositions})
  Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status interrupted -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $batchCount = [int]$batchPlan.batch_count
  $particleLines = @(Get-RfSingleFlightParticleLines `
    -ParticleInput $particleInput -RestartFly2 $isRestartFly2)
  if ($particleLines.Count -ne $launched) {
    throw 'Single-flight particle-input row count differs from the launched mother sample.'
  }
  $batchRecords = @()
  foreach ($plannedBatch in @($batchPlan.batches)) {
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
    [IO.File]::WriteAllLines(
      $batchParticleInput,
      $batchParticleLines,
      [Text.UTF8Encoding]::new($false)
    )
    $batchRecords += [pscustomobject]@{
      index = $batchIndex
      count = $count
      offset = $offset
      particle_input = $batchParticleInput
      stdout = Join-Path $package.log_dir (
        'simion__batch{0:D2}.stdout.log' -f $batchIndex
      )
      stderr = Join-Path $package.log_dir (
        'simion__batch{0:D2}.stderr.log' -f $batchIndex
      )
    }
  }
  $stdoutFiles = @($batchRecords | ForEach-Object { $_.stdout })
  $stderrFiles = @($batchRecords | ForEach-Object { $_.stderr })
  # The whole batch set is one dispatch wave.  The shared aggregate helper owns
  # process-tree and available-memory accounting; per-batch helpers would make
  # the frozen process-tree limit apply independently to every SIMION child.
  $resourceUsageFiles = @($resourceUsage)
  $processSpecifications = @()
  foreach ($batch in $batchRecords) {
    $processSpecifications += [pscustomobject]@{
      name = 'simion_batch_{0:D2}' -f [int]$batch.index
      file_path = $SimionExe
      working_directory = $runtimeDir
      stdout = $batch.stdout
      stderr = $batch.stderr
      environment = @{
        OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0
        OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET = [string]$batch.offset
      }
      argument_list = [string[]](@(
        '--default-num-particles',([string][Math]::Max(100,[int]$batch.count)),
        '--nogui','--noprompt','fly',
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
  $waveResult = Invoke-ResourceBudgetedProcesses `
    -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
    -UsagePath $resourceUsage -ProcessSpecifications $processSpecifications
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
      $sourceRegionDiagnosticProfiles.Count -eq 1 -or
      $ResolutionQualification) {
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
  if ($ResolutionQualification) {
    $analysisArguments += '--require-resolution-qualification'
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
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel',
    '--initial',$globalSource,'--checkpoints',$checkpoints,'--upstream',$upstreamFrozen,
    '--frontend',$frontendContract,'--oatof',$oatofGeometry,'--output',$sixPanel,
    '--metadata',$sixPanelMetadata,'--phase-space-output',$phaseSpace,
    '--phase-space-metadata',$phaseSpaceMetadata,'--phase-space-data',$phaseSpaceData,
    '--evolution-output',$evolution,'--evolution-metadata',$evolutionMetadata,
    '--evolution-data',$evolutionData
  ) -Failure 'Single-flight spatial and phase-space diagnostics failed.'
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
    -NotePropertyValue ([ordered]@{
      figure='results/single_flight_accelerator_pre_pulse_phase_space.png'
      metadata='results/single_flight_accelerator_pre_pulse_phase_space_metadata.json'
      data='results/single_flight_accelerator_pre_pulse_phase_space.csv'
      claim_status='DIAGNOSTIC_ONLY'
      selection_uses_detector_outcome=$false
    }) -Force
  $result | Add-Member -NotePropertyName accelerator_checkpoint_evolution `
    -NotePropertyValue ([ordered]@{
      figure='results/single_flight_accelerator_checkpoint_evolution.png'
      metadata='results/single_flight_accelerator_checkpoint_evolution_metadata.json'
      data='results/single_flight_accelerator_checkpoint_evolution.csv'
      claim_status='DIAGNOSTIC_ONLY'
      selection_uses_detector_outcome=$false
    }) -Force
  Write-RunJson -Path $package.summary -Depth 10 -Value $result
  $runConfiguration.parameters.multipole_handoff_count = [int]$result.census.multipole_handoff
  $runConfiguration.parameters.local_accelerator_exit_count = [int]$result.census.local_accelerator_exit
  $runConfiguration.parameters.detector_crossing_count = [int]$result.census.detector_crossing
  Write-RunJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $outputs = @($checkpoints,$sixPanel,$sixPanelMetadata,$phaseSpace,$phaseSpaceMetadata,$phaseSpaceData,$evolution,$evolutionMetadata,$evolutionData) + $stdoutFiles + $stderrFiles + $resourceUsageFiles + @($flightTubeBuildStdout,$flightTubeBuildStderr,$reflectronBuildStdout,$reflectronBuildStderr,$package.summary,$retentionActions) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
  foreach ($usage in $resourceUsageFiles) {
    if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath $usage)) { $resourceBudgetExceeded=$true; throw 'Single-flight compact retained-byte budget exceeded.' }
  }
  $resourceProfile = $null
  if ([string]$resolvedBudgetDocument.single_flight_dispatch_plan.estimation.kind -eq 'unknown_resource_profile_bootstrap') {
    $resourceProfile = Join-Path $package.result_dir 'simion_resource_profile.json'
    Invoke-SingleFlightPython -Arguments @(
      '-m','common.simion.resource_profile','publish','--run-id',$RunId,
      '--resource-usage',$resourceUsage,'--resource-usage-relative-path','logs/resource_usage.json',
      '--dispatch-plan',$dispatchPlanPath,'--output',$resourceProfile
    ) -Failure 'Single-flight SIMION resource profile publication failed.'
  }
  if ($resourceProfile) { $outputs += $resourceProfile }
  Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after successful run: $($_.Exception.Message)"
  }
  Write-Output "SIMION_SINGLE_FLIGHT=PASS RUN_ID=$RunId DETECTOR=$($result.census.detector_crossing)/$launched"
} catch {
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
    }) `
    -ResourceUsagePath $(if ($resourceBudgetExceeded) {$resourceUsage} else {''})
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after failed run: $($_.Exception.Message)"
  }
  throw
}
