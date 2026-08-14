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
  [string]$OatofResolvedGeometry = '',
  [string]$PulseSchedule = '',
  [string]$LayoutProfileId = '',
  [string]$ArchitectureGenerationId = '',
  [double]$ExpectedBoreRadiusMm = 0,
  [double]$ExpectedRingOuterRadiusMm = 0,
  [double]$ExpectedShieldInnerRadiusMm = 0,
  [string]$FrontendGridProfileId = '',
  [string]$OatofNumericalProfileId = '',
  [string]$TrajectoryQualityProfileId = '',
  [string]$TimeIntegrationProfileId = '',
  [string]$SpatialWindowProfileId = '',
  [Parameter(Mandatory)][string]$ResolvedRegionFieldContract,
  [Parameter(Mandatory)][string]$ResolvedRegionFieldContractSha256,
  [Parameter(Mandatory)][string]$ResolvedRegionFieldSemanticSha256,
  [string]$SourceProfileId = '',
  [string]$FieldOverlayId = '',
  [ValidateSet('continuous_frontend','pre_pulse_restart')][string]$SourceReleaseMode = 'continuous_frontend',
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
  [string]$MotherParticleSourceReceipt = '',
  [string]$MotherParticleSourceReceiptSha256 = '',
  [int]$PopulationDenominatorCount = 0,
  [int]$EligiblePopulationCount = 0,
  [int]$BootstrapResamples = 0,
  [int]$BootstrapSeed = 20260812,
  [switch]$ResolutionQualification,
  [switch]$PulseResolutionN100Screening,
  [string]$PulseResolutionCampaign = '',
  [string]$PulseResolutionCampaignSha256 = '',
  [string]$PulseResolutionExperimentRowSha256 = '',
  [string]$PulseResolutionArmId = '',
  [string]$PulseResolutionExecutionMode = '',
  [string]$PulseResolutionPrefixPlanRoot = '',
  [string]$PulseResolutionRegistrationAuthority = '',
  [string]$PulseResolutionRegistrationAuthoritySha256 = '',
  [string]$PulseResolutionBaselineCheckpoints = '',
  [string]$PulseResolutionBaselineCheckpointsSha256 = '',
  [ValidateSet('governed_upstream_source','steady_candidate_pool','continuous_injection_full_population','pulse_eligible_conditional')][string]$SamplingMode = 'governed_upstream_source',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
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
  param([Parameter(Mandatory)][object[]]$Arguments,[Parameter(Mandatory)][string]$Failure)
  $saved = Save-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE')
  try {
    $env:PYTHONPATH = $repoRoot; $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $repoRoot
    try { & $python @Arguments; if ($LASTEXITCODE -ne 0) { throw $Failure } } finally { Pop-Location }
  } finally { Restore-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE') -Snapshot $saved }
}

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) { throw "SIMION is missing: $SimionExe" }
$cacheProjectId = 'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
$simionSolverCacheIdentity = Get-RfSimionSolverCacheIdentity -SimionExe $SimionExe
if ($ResolutionQualification -and $BootstrapResamples -ne 5000) {
  throw 'Resolution qualification requires exactly 5000 bootstrap resamples.'
}
if ($BootstrapResamples -lt 0) { throw 'Bootstrap resamples must be nonnegative.' }
if ($PulseResolutionN100Screening) {
  $planRoot = [IO.Path]::GetFullPath($PulseResolutionPrefixPlanRoot)
  $expectedPrefix = Join-Path $planRoot `
    'inputs\pulse_resolution_arm1_all_real_screening_prefix_n100.csv'
  $isBaseline = $PulseResolutionArmId -eq 'real_beam_all_real' -and
    $PulseResolutionExecutionMode -eq 'screening_prefix_n100_baseline_registration'
  $isPairedStage1 = $PulseResolutionArmId -eq 'real_beam_ideal_stage1' -and
    $PulseResolutionExecutionMode -eq 'screening_prefix_n100_paired_candidate'
  $isPairedStage12 = $PulseResolutionArmId -eq 'real_beam_ideal_stage1_stage2' -and
    $PulseResolutionExecutionMode -eq 'screening_prefix_n100_paired_candidate'
  $isPairedAllIdeal = $PulseResolutionArmId -eq 'real_beam_all_ideal' -and
    $PulseResolutionExecutionMode -eq 'screening_prefix_n100_paired_candidate'
  if (-not ($isBaseline -or $isPairedStage1 -or $isPairedStage12 -or $isPairedAllIdeal) -or
      $MotherParticleCount -ne 100 -or
      $SamplingMode -ne 'continuous_injection_full_population' -or
      $BootstrapResamples -ne 0 -or $ResolutionQualification -or
      [string]::IsNullOrWhiteSpace($PulseResolutionCampaign) -or
      [string]::IsNullOrWhiteSpace($PulseResolutionCampaignSha256) -or
      [string]::IsNullOrWhiteSpace($PulseResolutionExperimentRowSha256) -or
      -not ([IO.Path]::GetFullPath($MotherParticleSource)).Equals(
        [IO.Path]::GetFullPath($expectedPrefix),
        [StringComparison]::OrdinalIgnoreCase
      )) {
    throw 'Real multipole beam + real accelerator field + real reflectron field deterministic N=100 baseline result contract differs.'
  }
}
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$($runtime.upstream_project_id)"
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $runtime.upstream_project_id -Mode 'rf_to_oatof_simion_single_flight' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion')
$resourceBudgetExceeded = $false
$snapshotReady = $false
$summaryRole = 'rf_oatof_simion_single_flight_summary'
$resourceUsage = Join-Path $package.log_dir 'resource_usage.json'

try {
  $budget = Initialize-RfIntegrationStageBudget -ResolvedBudget $ResolvedEngineeringBudget `
    -InputDir $package.input_dir -ExpectedIntegrationId `
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $ConnectionProfileId -StageId 'single_flight_transport' -Solver simion
  $configurationSource = Join-Path $integrationRoot 'config\simion_single_flight.json'
  $configuration = Join-Path $package.input_dir 'simion_single_flight.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $configurationSource -Destination $configuration -Role 'single-flight configuration' | Out-Null
  $settings = Get-Content -LiteralPath $configuration -Raw -Encoding UTF8 | ConvertFrom-Json
  $selectedGridProfileId = if ([string]::IsNullOrWhiteSpace($FrontendGridProfileId)) {
    [string]$settings.default_frontend_grid_profile_id
  } else { $FrontendGridProfileId }
  $gridProfiles = @($settings.frontend_grid_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedGridProfileId
  })
  if ($settings.role -ne 'rf_oatof_simion_single_flight_configuration' -or
      $gridProfiles.Count -ne 1 -or
      @($gridProfiles[0].cell_mm_xyz.PSObject.Properties.Name).Count -ne 3 -or
      @($gridProfiles[0].cell_mm_xyz.PSObject.Properties.Name | Where-Object {
        $_ -notin @('x','y','z')
      }).Count -ne 0 -or
      [double]$gridProfiles[0].cell_mm_xyz.x -le 0 -or
      [double]$gridProfiles[0].cell_mm_xyz.y -le 0 -or
      [double]$gridProfiles[0].cell_mm_xyz.z -le 0 -or
      [int]$gridProfiles[0].max_parallel_batches -lt 1 -or
      [int]$gridProfiles[0].max_parallel_batches -gt 5 -or
    [string]$settings.clock_basis -ne 'canonical_instrument_time_us') {
    throw 'Single-flight numerical configuration is invalid.'
  }
  $frontendCellMmX = [double]$gridProfiles[0].cell_mm_xyz.x
  $frontendCellMmY = [double]$gridProfiles[0].cell_mm_xyz.y
  $frontendCellMmZ = [double]$gridProfiles[0].cell_mm_xyz.z
  $maxParallelBatches = [int]$gridProfiles[0].max_parallel_batches
  $overlayEnabled = $null -ne $gridProfiles[0].PSObject.Properties['accelerator_overlay'] -and
    [bool]$gridProfiles[0].accelerator_overlay.enabled
  $resolvedFieldOverlayId = [string]$gridProfiles[0].field_overlay_id
  if ($FieldOverlayId -and $FieldOverlayId -ne $resolvedFieldOverlayId) {
    throw 'Single-flight field-overlay identity differs from the selected grid profile.'
  }
  $overlayCellMmX = $null
  $overlayCellMmY = $null
  $overlayCellMmZ = $null
  if ($overlayEnabled) {
    $overlayProfile = $gridProfiles[0].accelerator_overlay
    if (@($overlayProfile.PSObject.Properties.Name | Where-Object {
          $_ -notin @('enabled','cell_mm_xyz','boundary_mode','transient_disk_estimate')
        }).Count -ne 0 -or
        [string]$overlayProfile.boundary_mode -ne 'coarse_electrode_basis_dirichlet_v1' -or
        $frontendCellMmX -ne $frontendCellMmY -or $frontendCellMmY -ne $frontendCellMmZ) {
      throw 'Accelerator overlay requires an isotropic coarse grid and the governed boundary mode.'
    }
    $overlayCellMmX = [double]$overlayProfile.cell_mm_xyz.x
    $overlayCellMmY = [double]$overlayProfile.cell_mm_xyz.y
    $overlayCellMmZ = [double]$overlayProfile.cell_mm_xyz.z
    if ($overlayCellMmX -ne $frontendCellMmX -or
        $overlayCellMmY -ne $frontendCellMmY -or
        $overlayCellMmZ -le 0 -or $overlayCellMmZ -gt $frontendCellMmZ) {
      throw 'Accelerator overlay may only refine z while preserving the coarse x-y grid.'
    }
  }
  $selectedOatofNumericalProfileId = if ([string]::IsNullOrWhiteSpace($OatofNumericalProfileId)) {
    [string]$settings.default_oatof_numerical_profile_id
  } else { $OatofNumericalProfileId }
  $oatofNumericalProfiles = @($settings.oatof_numerical_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedOatofNumericalProfileId
  })
  if ($oatofNumericalProfiles.Count -ne 1 -or
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.axial -le 0 -or
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.radial -le 0) {
    throw 'Single-flight oaTOF numerical profile is invalid.'
  }
  $selectedTrajectoryQualityProfileId = if ([string]::IsNullOrWhiteSpace($TrajectoryQualityProfileId)) {
    'tqual_8'
  } else { $TrajectoryQualityProfileId }
  $trajectoryQualityProfiles = @($settings.trajectory_quality_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedTrajectoryQualityProfileId
  })
  if ($trajectoryQualityProfiles.Count -ne 1 -or
      [int]$trajectoryQualityProfiles[0].trajectory_quality -notin @(8,108)) {
    throw 'Single-flight trajectory-quality profile is invalid.'
  }
  $trajectoryQuality = [int]$trajectoryQualityProfiles[0].trajectory_quality
  $selectedTimeIntegrationProfileId = if (
    [string]::IsNullOrWhiteSpace($TimeIntegrationProfileId)
  ) {
    [string]$settings.default_time_integration_profile_id
  } else { $TimeIntegrationProfileId }
  $timeIntegrationProfiles = @($settings.time_integration_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedTimeIntegrationProfileId
  })
  if ($timeIntegrationProfiles.Count -ne 1 -or
      [int]$timeIntegrationProfiles[0].rf_steps_per_period -notin @(160,320)) {
    throw 'Single-flight time-integration profile is invalid.'
  }
  $rfStepsPerPeriod = [int]$timeIntegrationProfiles[0].rf_steps_per_period
  $spatialWindowProfiles = @(if ([string]::IsNullOrWhiteSpace($SpatialWindowProfileId)) {
  } else {
    $settings.spatial_window_profiles | Where-Object {
      [string]$_.profile_id -eq $SpatialWindowProfileId
    }
  })
  if (-not [string]::IsNullOrWhiteSpace($SpatialWindowProfileId) -and
      $spatialWindowProfiles.Count -ne 1) {
    throw 'Single-flight spatial-window profile is invalid.'
  }
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
  $hasGovernedLayout = -not [string]::IsNullOrWhiteSpace($LayoutProfileId)
  if ($hasGovernedLayout -ne (
      -not [string]::IsNullOrWhiteSpace($OatofResolvedGeometry) -and
      -not [string]::IsNullOrWhiteSpace($PulseSchedule))) {
    throw 'Single-flight layout profile, resolved geometry and pulse schedule must be supplied together.'
  }
  $resolvedFrozen = Join-Path $package.input_dir 'resolved_connection.json'
  $upstreamFrozen = Join-Path $package.input_dir 'upstream_resolved_design.json'
  $sourceContractFrozen = Join-Path $package.input_dir 'resolved_source_contract.json'
  $runtimeBindingFrozen = Join-Path $package.input_dir 'runtime_binding.json'
  $oatofGeometry = Join-Path $package.input_dir 'oatof_resolved_geometry.json'
  Copy-Item -LiteralPath $runtime.resolved_connection_path -Destination $resolvedFrozen
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design -Destination $upstreamFrozen
  Copy-Item -LiteralPath $runtime.contracts.resolved_source_contract -Destination $sourceContractFrozen
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
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.axial -or
      [double]$oatofGeometryDocument.simion_geometry_build.reflectron.cell_radial_mm -ne
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.radial) {
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
    $SamplingMode -ne 'steady_candidate_pool' -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.reflectron_pa
  )
  $hasFlightTubeRebuild = (
    $SamplingMode -ne 'steady_candidate_pool' -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.flight_tube_pa
  )
  $pulseScheduleFrozen = $null
  $pulseTimeUs = [double]$settings.pulse_time_us
  $pulseWidthUs = [double]$settings.pulse_width_us
  if ($hasGovernedLayout) {
    $pulseScheduleFrozen = Join-Path $package.input_dir 'resolved_single_flight_pulse_schedule.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $PulseSchedule `
      -Destination $pulseScheduleFrozen -Role 'single-flight pulse schedule' | Out-Null
    $pulseScheduleDocument = Get-Content -LiteralPath $pulseScheduleFrozen -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ($pulseScheduleDocument.role -ne 'rf_oatof_single_flight_multipole_handoff_pulse_schedule' -or
        $pulseScheduleDocument.layout_profile_id -ne $LayoutProfileId -or
        [double]$pulseScheduleDocument.derived_pulse_time_us -le 0 -or
        [double]$pulseScheduleDocument.pulse_width_us -le 0) {
      throw 'Governed single-flight pulse schedule identity differs.'
    }
    $pulseTimeUs = [double]$pulseScheduleDocument.derived_pulse_time_us
    $pulseWidthUs = [double]$pulseScheduleDocument.pulse_width_us
  }

  $isPrePulseRestart = $SourceReleaseMode -eq 'pre_pulse_restart'
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
  $sourceToCopy = if ($isPrePulseRestart) { [IO.Path]::GetFullPath($PrePulseSourceState) } elseif ($hasMotherOverride) { [IO.Path]::GetFullPath($MotherParticleSource) } else { $runtime.source_particle_source }
  $motherSourceRoot = if ($PulseResolutionN100Screening) {
    [IO.Path]::GetFullPath($PulseResolutionPrefixPlanRoot)
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
  $launched = if ($isPrePulseRestart) { $PrePulseSourceStateCount } elseif ($hasMotherOverride) { $MotherParticleCount } else { [int]$runtime.source_record.launched_particle_count }
  if ($SamplingMode -eq 'pulse_eligible_conditional' -and
      ($PopulationDenominatorCount -lt $EligiblePopulationCount -or
       $EligiblePopulationCount -lt $launched)) {
    throw 'Conditional-source population counts are inconsistent.'
  }
  if (@(Import-Csv -LiteralPath $motherSource).Count -ne $launched) {
    throw 'Single-flight mother sample count differs from source authority.'
  }
  $campaignFrozen = $null
  $sourceIdentity = $null
  $registrationAuthorityFrozen = $null
  if ($PulseResolutionN100Screening) {
    $campaignFrozen = Join-Path $package.input_dir 'pulse_resolution_optimization_campaign.json'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $PulseResolutionCampaign `
      -Destination $campaignFrozen -Role 'pulse-resolution campaign' | Out-Null
    if ((Get-FileHash -LiteralPath $campaignFrozen -Algorithm SHA256).Hash -ne
        $PulseResolutionCampaignSha256) { throw 'Pulse-resolution campaign SHA differs.' }
    $registrationAuthorityFrozen = Join-Path $package.input_dir `
      'pulse_resolution_baseline_registration_authority.json'
    Copy-RfStableFile -SourceRunRoot ([IO.Path]::GetFullPath($PulseResolutionPrefixPlanRoot)) `
      -SourcePath $PulseResolutionRegistrationAuthority `
      -Destination $registrationAuthorityFrozen `
      -Role 'pulse-resolution baseline registration authority' | Out-Null
    if ((Get-FileHash -LiteralPath $registrationAuthorityFrozen -Algorithm SHA256).Hash -ne
        $PulseResolutionRegistrationAuthoritySha256) {
      throw 'Pulse-resolution baseline registration authority SHA differs.'
    }
    $sourceIdentity = Join-Path $package.input_dir 'pulse_resolution_source_identity.json'
    $registrationSourceIdentity = [ordered]@{}
    foreach ($property in $runtime.source_identity.PSObject.Properties) {
      $registrationSourceIdentity[$property.Name] = $property.Value
    }
    $registrationSourceIdentity.mother_sample_count = 1000
    $registrationSourceIdentity.mother_particle_source_sha256 =
      [string]$runtime.source_identity.particle_source_sha256
    Write-RfJson -Path $sourceIdentity -Depth 10 -Value $registrationSourceIdentity
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
    project_id=$cacheProjectId; solver=$simionSolverCacheIdentity
    inputs=[ordered]@{frontend_gem_sha256=$frontendHash}
    critical_options=[ordered]@{
      gem2pa=@('--nogui','--noprompt','gem2pa','frontend.gem','frontend.pa#')
      refine=@('--nogui','--noprompt','refine','frontend.pa#')
    }
  }
  $frontendCacheKey = Get-RfContentIdentitySha256 -Identity $frontendCacheIdentity
  $cacheRoot = Join-Path $workspaceRoot "artifacts\projects\$cacheProjectId\cache\simion_single_flight_frontend"
  $cacheDir = Join-Path $cacheRoot $frontendCacheKey
  $frontendRefineRequired = -not (Test-RfReusableCacheEntry -Python $python `
    -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $cacheProjectId `
    -CacheRoot $cacheRoot -CacheKey $frontendCacheKey -Role $frontendCacheRole)
  if ($frontendRefineRequired) {
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
      -WorkspaceRoot $workspaceRoot -ProjectId $cacheProjectId -CacheRoot $cacheRoot `
      -CacheKey $frontendCacheKey -Role $frontendCacheRole -Identity $frontendCacheIdentity `
      -StagingDirectory $frontendBuildDir -ProviderRunId $RunId
    } catch {
      if (Test-Path -LiteralPath $frontendBuildDir) {
        Remove-Item -LiteralPath $frontendBuildDir -Recurse -Force
      }
      throw
    }
  }
  $cacheGem = Join-Path $cacheDir 'frontend.gem'; $cachePaSharp = Join-Path $cacheDir 'frontend.pa#'; $cachePa0 = Join-Path $cacheDir 'frontend.pa0'

  $overlayGeometry = $null
  $overlayCacheDir = $null
  $overlayCachePa0 = $null
  $overlayBasisBuilderFrozen = $null
  $overlayRefinerFrozen = $null
  $overlayBasisReport = $null
  $overlayInterfaceVerifierFrozen = $null
  $overlayInterfaceReport = $null
  if ($overlayEnabled) {
    $overlayGeometry = Get-Content -LiteralPath $overlayContract -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($overlayGeometry.role -ne 'rf_oatof_simion_accelerator_overlay_contract' -or
        [string]$overlayGeometry.boundary_condition.mode -ne 'coarse_electrode_basis_dirichlet_v1') {
      throw 'Compiled accelerator overlay contract is invalid.'
    }
    $overlayBasisBuilderSource = Join-Path $PSScriptRoot 'build_accelerator_overlay_basis.lua'
    $overlayRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
    $overlayInterfaceVerifierSource = Join-Path $PSScriptRoot 'verify_accelerator_overlay_interface.lua'
    $overlayCacheRole = 'simion_accelerator_overlay_pa_cache'
    $overlayIdentity = [ordered]@{
      schema_version=2; role=$overlayCacheRole
      project_id=$cacheProjectId; solver=$simionSolverCacheIdentity
      inputs=[ordered]@{
        overlay_gem_sha256=(Get-FileHash -LiteralPath $overlayGem -Algorithm SHA256).Hash
        frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash
        basis_builder_sha256=(Get-FileHash -LiteralPath $overlayBasisBuilderSource -Algorithm SHA256).Hash
        refiner_sha256=(Get-FileHash -LiteralPath $overlayRefinerSource -Algorithm SHA256).Hash
        interface_verifier_sha256=(Get-FileHash -LiteralPath $overlayInterfaceVerifierSource -Algorithm SHA256).Hash
      }
      critical_options=[ordered]@{
        boundary_mode='coarse_electrode_basis_dirichlet_v1'; basis_count=20
        gem2pa=@('--nogui','--noprompt','gem2pa','accelerator_overlay.gem','accelerator_overlay.pa#')
        refinement_convergence='5e-7'; maximum_electrode_id=19
      }
    }
    $overlayKey = Get-RfContentIdentitySha256 -Identity $overlayIdentity
    $overlayCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$cacheProjectId\cache\simion_accelerator_overlay"
    $overlayCacheDir = Join-Path $overlayCacheRoot $overlayKey
    $overlayCachePaSharp = Join-Path $overlayCacheDir 'accelerator_overlay.pa#'
    $overlayCachePa0 = Join-Path $overlayCacheDir 'accelerator_overlay.pa0'
    $overlayCacheManifest = Join-Path $overlayCacheDir 'cache_manifest.json'
    $overlayCacheBasisReport = Join-Path $overlayCacheDir 'basis_build.json'
    $overlayFamilyComplete = Test-RfReusableCacheEntry -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $cacheProjectId `
      -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayCacheRole
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
          -ArgumentList @('--nogui','--noprompt','lua',$overlayBasisBuilderFrozen,$cachePa0,$overlayBuildPaSharp,
            ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
            ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),'19',$overlayBuildBasisReport)
        if ($overlayBuild.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay basis transfer exceeded its resource budget.' }
        if ($overlayBuild.exit_code -ne 0) { throw 'Overlay basis transfer failed.' }
        foreach ($electrode in 0..19) {
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
          -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $cacheProjectId `
          -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayCacheRole `
          -Identity $overlayIdentity -StagingDirectory $overlayBuildDir -ProviderRunId $RunId
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
    Copy-Item -LiteralPath $overlayCacheBasisReport -Destination $overlayBasisReport
    $overlayInterfaceReport = Join-Path $package.result_dir 'accelerator_overlay_interface_verification.json'
    $overlayVerify = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
      -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_interface_verify_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $overlayCacheDir `
      -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_interface_verify.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'overlay_interface_verify.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','lua',$overlayInterfaceVerifierFrozen,$cachePa0,$overlayCachePa0,
        ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
        ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),'19',$overlayInterfaceReport)
    if ($overlayVerify.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay interface verification exceeded its resource budget.' }
    if ($overlayVerify.exit_code -ne 0) { throw 'Overlay interface verification failed.' }
  }

  $topologyResult = Invoke-SimionCompiledApertureTopologyCheck `
    -PaPath $cachePa0 -ReportPath $apertureTopologyReport -VerifierPath $apertureVerifier `
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
        -WorkingDirectory $cacheDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_aperture_topology.stdout.log') `
        -RedirectStandardError (Join-Path $package.log_dir 'frontend_aperture_topology.stderr.log') `
        -ArgumentList @('--nogui','--noprompt','lua',$verifierPath)
    }
  $apertureTopology = $topologyResult.audit

  $particleInput = Join-Path $package.input_dir $(if ($isPrePulseRestart) {
      'single_flight_mother_sample.fly2'
    } else {
      'single_flight_mother_sample.ion'
    })
  $globalSource = Join-Path $package.input_dir 'single_flight_initial_global_state.csv'
  $sourceArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source',
    '--source',$motherSource,'--connection',$resolvedFrozen,'--particle-input',$particleInput,'--global-state',$globalSource,
    '--source-release-mode',$SourceReleaseMode)
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
  $downstreamCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$cacheProjectId\cache\simion_oatof_downstream_pa"
  $geometryHash = (Get-FileHash -LiteralPath $oatofGeometry -Algorithm SHA256).Hash
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
      [string]$Additional=''
    )
    $additionalHash = if ([string]::IsNullOrWhiteSpace($Additional)) { '' } else { (Get-FileHash -LiteralPath $Additional -Algorithm SHA256).Hash }
    $identity = [ordered]@{
      schema_version=2; role=$Role
      project_id=$cacheProjectId; solver=$simionSolverCacheIdentity
      inputs=[ordered]@{
        oatof_geometry_sha256=$geometryHash
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
  $flightTubeCachePlan = Get-DownstreamCachePlan -Kind 'flight_tube_ground' `
    -Role 'simion_oatof_flight_tube_pa_cache' -Builder $flightTubeBuilderSource `
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
  function Use-ReadOnlyPaCacheFamily {
    param([Parameter(Mandatory)][string]$CacheDirectory,[Parameter(Mandatory)][string]$Pattern)
    foreach ($source in Get-ChildItem -LiteralPath $CacheDirectory -Filter $Pattern -File) {
      $target = Join-Path $runtimeDir $source.Name
      if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
      try {
        New-Item -ItemType HardLink -Path $target -Target $source.FullName -ErrorAction Stop | Out-Null
      } catch {
        Copy-Item -LiteralPath $source.FullName -Destination $target -Force
      }
    }
  }
  function Publish-DownstreamPaCacheFamily {
    param([Parameter(Mandatory)]$Plan,[Parameter(Mandatory)][string]$Pattern)
    $staging = New-RfCacheStagingDirectory -CacheRoot $downstreamCacheRoot
    try {
      foreach ($source in Get-ChildItem -LiteralPath $runtimeDir -Filter $Pattern -File) {
        $destination = Join-Path $staging $source.Name
        try {
          New-Item -ItemType HardLink -Path $destination -Target $source.FullName -ErrorAction Stop | Out-Null
        } catch {
          Copy-Item -LiteralPath $source.FullName -Destination $destination
        }
      }
      return Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot `
        -WorkspaceRoot $workspaceRoot -ProjectId $cacheProjectId `
        -CacheRoot $downstreamCacheRoot -CacheKey $Plan.key -Role $Plan.role `
        -Identity $Plan.identity -StagingDirectory $staging -ProviderRunId $RunId
    } catch {
      if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
      throw
    }
  }
  $flightTubeCacheUsed = $false
  $reflectronCacheUsed = $false
  if ($hasFlightTubeRebuild -and (Test-RfReusableCacheEntry -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $cacheProjectId `
      -CacheRoot $downstreamCacheRoot -CacheKey $flightTubeCachePlan.key `
      -Role $flightTubeCachePlan.role)) {
    Use-ReadOnlyPaCacheFamily -CacheDirectory $flightTubeCacheDir -Pattern 'flight_tube_ground.pa*'
    $flightTubeCacheUsed = $true
    $hasFlightTubeRebuild = $false
  }
  if ($hasReflectronRebuild -and (Test-RfReusableCacheEntry -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $cacheProjectId `
      -CacheRoot $downstreamCacheRoot -CacheKey $reflectronCachePlan.key `
      -Role $reflectronCachePlan.role)) {
    Use-ReadOnlyPaCacheFamily -CacheDirectory $reflectronCacheDir -Pattern 'reflectron.pa*'
    $reflectronCacheUsed = $true
    $hasReflectronRebuild = $false
  }
  if ($hasFlightTubeRebuild) {
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
  }
  if ($hasReflectronRebuild) {
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
    $assignments = @('1=0')
    foreach ($ringIndex in 1..([int]$rings.stage1_count)) {
      $assignments += "$(1+$ringIndex)=$($voltage.midgrid*$ringIndex/([int]$rings.stage1_count+1))"
    }
    $midgridElectrode = 2 + [int]$rings.stage1_count
    $assignments += "$midgridElectrode=$($voltage.midgrid)"
    foreach ($ringIndex in 1..([int]$rings.stage2_count)) {
      $electrode = $midgridElectrode + $ringIndex
      $ringVoltage = $voltage.midgrid + ($voltage.backplate-$voltage.midgrid)*$ringIndex/([int]$rings.stage2_count+1)
      $assignments += "$electrode=$ringVoltage"
    }
    $assignments += "$(3+[int]$rings.stage1_count+[int]$rings.stage2_count)=$($voltage.backplate)"
    $assignments += "$maximumReflectronElectrode=0"
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
  }
  $overlayIobBuilderFrozen = $null
  $overlayIobContainerFrozen = $null
  $overlayIobContainerGemFrozen = @()
  if ($overlayEnabled) {
    Use-ReadOnlyPaCacheFamily -CacheDirectory $overlayCacheDir -Pattern 'accelerator_overlay.pa*'
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
    $overlayContainerRuntimeDir = Join-Path $runtimeDir 'simion_five_instance_container'
    New-Item -ItemType Directory -Path $overlayContainerFrozenDir,$overlayContainerRuntimeDir -Force | Out-Null
    $overlayIobContainerFrozen = Join-Path $overlayContainerFrozenDir 'mag_quad_2dp.iob'
    Copy-Item -LiteralPath $overlayIobContainerSource -Destination $overlayIobContainerFrozen
    foreach ($seedName in @('mag_quad_2dp.gem','mag_quad_2dp-Mx.gem','mag_quad_2dp-My.gem','mag_quad_2dp-j.gem','mag_quad_2dp-mu.gem')) {
      $seedFrozen = Join-Path $overlayContainerFrozenDir $seedName
      Copy-Item -LiteralPath (Join-Path $overlayIobContainerSourceDir $seedName) -Destination $seedFrozen
      $overlayIobContainerGemFrozen += $seedFrozen
    }
    Get-ChildItem -LiteralPath $overlayContainerFrozenDir -File | Copy-Item -Destination $overlayContainerRuntimeDir
    $overlayIobContainerRuntime = Join-Path $overlayContainerRuntimeDir 'mag_quad_2dp.iob'
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
  $formalLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\formal\oatof_ideal_grounded.lua'
  $pulseLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_handoff_pulse.lua'
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'single_flight_program_build.json'
  $programArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
    '--formal',$formalLua,'--pulse-extension',$pulseLua,'--upstream',$upstreamFrozen,
    '--frontend-contract',$frontendContract,'--oatof',$oatofGeometry,
    '--initial-global-state',$globalSource,
    '--resolved-region-field-contract',$resolvedRegionFieldContractFrozen,
    '--output',$program,'--metadata',$programMetadata)
  if ($SamplingMode -eq 'steady_candidate_pool') { $programArguments += '--terminate-after-pulse' }
  if ($null -ne $prePulseValidationFrozen) { $programArguments += '--global-segments' }
  if ($overlayEnabled) { $programArguments += @('--accelerator-overlay-contract',$overlayContract) }
  Invoke-SingleFlightPython -Arguments $programArguments `
    -Failure 'Single-flight Program build failed.'

  $runConfiguration = [ordered]@{
    schema_version=2; run_id=$RunId; project=$runtime.upstream_project_id; mode='rf_to_oatof_simion_single_flight'; project_root=$repoRoot
    inputs=[ordered]@{ configuration=$configuration; runtime_binding=$runtimeBindingFrozen; resolved_connection=$resolvedFrozen; resolved_source_contract=$sourceContractFrozen; upstream_resolved_design=$upstreamFrozen; oatof_resolved_geometry=$oatofGeometry; pulse_schedule=$pulseScheduleFrozen; resolved_region_field_contract=$resolvedRegionFieldContractFrozen; resolved_integration_engineering_budget=$budget.frozen_budget; resolved_stage_resource_budget=$budget.stage_budget; mother_particle_source=$motherSource; mother_particle_source_materialization_receipt=$motherSourceReceiptFrozen; initial_global_state=$globalSource; pre_pulse_restart_validation=$prePulseValidationFrozen; particle_input=$particleInput; frontend_gem=$frontendGem; frontend_contract=$frontendContract; frontend_pa_cache_manifest=$frontendCacheManifestInput; accelerator_overlay_gem=$overlayGem; accelerator_overlay_contract=$overlayContract; accelerator_overlay_basis_builder=$overlayBasisBuilderFrozen; accelerator_overlay_refiner=$overlayRefinerFrozen; accelerator_overlay_interface_verifier=$overlayInterfaceVerifierFrozen; accelerator_overlay_pa_cache_manifest=$overlayCacheManifestInput; accelerator_overlay_iob_builder=$overlayIobBuilderFrozen; accelerator_overlay_iob_container=$overlayIobContainerFrozen; accelerator_overlay_iob_container_gems=$overlayIobContainerGemFrozen; accelerator_overlay_basis_report=$overlayBasisReport; accelerator_overlay_interface_report=$overlayInterfaceReport; flight_tube_pa_cache_manifest=$flightTubeCacheManifestInput; reflectron_pa_cache_manifest=$reflectronCacheManifestInput; frontend_aperture_topology_support=$apertureTopologySupport; frontend_aperture_topology_verifier=$apertureVerifier; program_metadata=$programMetadata; candidate_flight_tube_builder=$flightTubeBuilderFrozen; candidate_flight_tube_gem=$flightTubeGemFrozen; candidate_reflectron_builder=$reflectronBuilderFrozen; candidate_reflectron_gem=$reflectronGemFrozen; candidate_reflectron_refiner=$reflectronRefinerFrozen }
    upstream_source_identity=$runtime.source_identity
    parameters=[ordered]@{ connection_profile_id=$ConnectionProfileId; source_branch_id=$SourceBranchId; layout_profile_id=$(if($hasGovernedLayout){$LayoutProfileId}else{$null}); architecture_generation_id=$(if($hasGovernedLayout){$ArchitectureGenerationId}else{$null}); source_profile_id=$(if($SourceProfileId){$SourceProfileId}else{$null}); field_overlay_id=$resolvedFieldOverlayId; source_release_mode=$SourceReleaseMode; bore_radius_mm=[double]$oatofGeometryDocument.geometry_mm.bore_r; ring_outer_radius_mm=[double]$oatofGeometryDocument.geometry_mm.ring_outer_r; shield_inner_radius_mm=[double]$oatofGeometryDocument.geometry_mm.flight_tube_r; frontend_grid_profile_id=$selectedGridProfileId; frontend_cell_mm_xyz=[ordered]@{x=$frontendCellMmX;y=$frontendCellMmY;z=$frontendCellMmZ}; accelerator_overlay_enabled=$overlayEnabled; accelerator_overlay_cell_mm_xyz=$(if($overlayEnabled){[ordered]@{x=$overlayCellMmX;y=$overlayCellMmY;z=$overlayCellMmZ}}else{$null}); accelerator_overlay_boundary_mode=$(if($overlayEnabled){'coarse_electrode_basis_dirichlet_v1'}else{$null}); oatof_numerical_profile_id=$selectedOatofNumericalProfileId; trajectory_quality_profile_id=$selectedTrajectoryQualityProfileId; trajectory_quality=$trajectoryQuality; time_integration_profile_id=$selectedTimeIntegrationProfileId; rf_steps_per_period=$rfStepsPerPeriod; spatial_window_profile_id=$(if($spatialWindowProfiles.Count -eq 1){$SpatialWindowProfileId}else{$null}); accelerator_field_profile_id=$selectedFieldProfileId; resolved_region_field_contract_sha256=$ResolvedRegionFieldContractSha256; resolved_region_field_semantic_sha256=$ResolvedRegionFieldSemanticSha256; max_parallel_batches=$maxParallelBatches; clock_basis=[string]$settings.clock_basis; launched_particle_count=$launched; particle_count=$launched; population_denominator_count=$(if($PopulationDenominatorCount -gt 0){$PopulationDenominatorCount}else{$launched}); eligible_population_count=$(if($EligiblePopulationCount -gt 0){$EligiblePopulationCount}else{$null}); population_basis=$(if($SamplingMode -eq 'continuous_injection_full_population'){'candidate_full_population'}elseif($SamplingMode -eq 'pulse_eligible_conditional'){'pulse_eligible_conditional_population'}else{'source_contract_population'}); execution_batch_count=$(if($launched -ge [int]$settings.batching_policy.enabled_at_particle_count){[int]$settings.batching_policy.default_batch_count}else{1}); execution_batches_parallel=$(if($launched -ge [int]$settings.batching_policy.enabled_at_particle_count){[bool]$settings.batching_policy.parallel_after_cache_warmup}else{$false}); aperture_width_mm=$apertureWidthMm; aperture_height_mm=$apertureHeightMm; aperture_boolean_boundary_policy=[string]$apertureDiscretization.boolean_boundary_policy; aperture_grid_warnings=$apertureGridWarnings; frontend_open_aperture_column_count=[int]$apertureTopology.open_column_count; frontend_aperture_guard_electrode_check_passed=[bool]$apertureTopology.guard_electrode_check_passed; frontend_aperture_topology_report_sha256=(Get-FileHash -LiteralPath $apertureTopologyReport -Algorithm SHA256).Hash; rod_end_to_accelerator_shield_mm=1.0; surrounded_transition=$true; accelerator_axis_x_mm=[double]$oatofGeometryDocument.coordinate_convention.accelerator_axis_x; pulse_time_us=$pulseTimeUs; pulse_width_us=$pulseWidthUs; design_compilation=$(if($null -ne $layoutDerivation){$layoutDerivation.design_compilation}else{$null}); source_release_full_width_mm=[double]$oatofGeometryDocument.particle_source.size_z_mm; reflectron_stage2_length_mm=[double]$oatofGeometryDocument.geometry_mm.L_stage2; reflectron_midgrid_voltage_V=[double]$oatofGeometryDocument.electrodes_V.midgrid; reflectron_backplate_voltage_V=[double]$oatofGeometryDocument.electrodes_V.backplate; reflectron_pa0_sha256=(Get-FileHash -LiteralPath $reflectronPa0 -Algorithm SHA256).Hash; frontend_gem_sha256=$frontendHash; frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash; accelerator_overlay_pa0_sha256=$(if($overlayEnabled){(Get-FileHash -LiteralPath $overlayCachePa0 -Algorithm SHA256).Hash}else{$null}) }
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}; formal_gate_passed=$false
  }
  if ($PulseResolutionN100Screening) {
    $runConfiguration.inputs.pulse_resolution_campaign = $campaignFrozen
    $runConfiguration.inputs.pulse_resolution_source_identity = $sourceIdentity
    $runConfiguration.inputs.pulse_resolution_baseline_registration_authority =
      $registrationAuthorityFrozen
    $runConfiguration.parameters.pulse_resolution_physical_arm = $PulseResolutionArmId
    $runConfiguration.parameters.pulse_resolution_mother_sample_count = 1000
    $runConfiguration.parameters.pulse_resolution_screening_prefix_count = 100
    $runConfiguration.parameters.pulse_resolution_selection_rule =
      'deterministic_first_n_rows'
    $runConfiguration.parameters.pulse_resolution_screening_is_random = $false
  }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{schema_version=1;role=$summaryRole;status='interrupted';reason='Frozen inputs recorded; SIMION flight not complete.'})
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status interrupted -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $batchCount = [int]$runConfiguration.parameters.execution_batch_count
  if ($batchCount -gt 1 -and (
      $batchCount -ne 5 -or
      -not [bool]$runConfiguration.parameters.execution_batches_parallel)) {
    throw 'N=1000 single flight requires five batches with profile-capped wave dispatch.'
  }
  $particleLines = @(Get-Content -LiteralPath $particleInput -Encoding UTF8)
  if ($isPrePulseRestart) {
    $particleLines = @($particleLines | Where-Object { $_ -match '^  standard_beam ' })
  }
  if ($particleLines.Count -ne $launched) {
    throw 'Single-flight particle-input row count differs from the launched mother sample.'
  }
  $batchRecords = @()
  $quotient = [Math]::Floor($launched / $batchCount)
  $remainder = $launched % $batchCount
  $offset = 0
  foreach ($batchIndex in 1..$batchCount) {
    $count = $quotient + $(if ($batchIndex -le $remainder) { 1 } else { 0 })
    $batchParticleInput = Join-Path $package.input_dir (
      'single_flight_mother_sample__batch{0:D2}.{1}' -f $batchIndex,$(if ($isPrePulseRestart) {'fly2'} else {'ion'})
    )
    $batchParticleLines = [string[]]$particleLines[$offset..($offset + $count - 1)]
    if ($isPrePulseRestart) {
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
      usage = Join-Path $package.log_dir (
        'resource_usage__batch{0:D2}.json' -f $batchIndex
      )
    }
    $offset += $count
  }
  $stdoutFiles = @($batchRecords | ForEach-Object { $_.stdout })
  $stderrFiles = @($batchRecords | ForEach-Object { $_.stderr })
  $resourceUsageFiles = @($batchRecords | ForEach-Object { $_.usage })
  $oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  try {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $cachePa0
    for ($waveStart = 0; $waveStart -lt $batchRecords.Count; $waveStart += $maxParallelBatches) {
      $waveEnd = [Math]::Min($waveStart + $maxParallelBatches - 1,$batchRecords.Count - 1)
      $jobs = @()
      foreach ($batch in @($batchRecords[$waveStart..$waveEnd])) {
        $payload = [pscustomobject]@{
        support = Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1'
        budget = $budget.stage_budget
        run_dir = $package.run_dir
        usage = $batch.usage
        executable = $SimionExe
        working_directory = $runtimeDir
        stdout = $batch.stdout
        stderr = $batch.stderr
        accelerator_pa = $cachePa0
        particle_id_offset = [int]$batch.offset
        arguments = [string[]]@(
          '--default-num-particles',([string][Math]::Max(100,[int]$batch.count)),
          '--nogui','--noprompt','fly',
          '--trajectory-quality',([string]$trajectoryQuality),
          '--retain-trajectories','0','--particles',$batch.particle_input,'--programs','1',
          '--adjustable',("trajectory_quality={0}" -f $trajectoryQuality),
          '--adjustable','trajectory_log_enable=1',
          '--adjustable',("diagnostic_max_tof_us={0:R}" -f [double]$settings.maximum_time_of_flight_us),
          '--adjustable','handoff_pulse_mode=1',
          '--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
          '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs),
          '--adjustable',("single_flight_rf_steps={0}" -f $rfStepsPerPeriod),
          (Join-Path $runtimeDir 'oatof_ideal_grounded.iob')
        )
      }
        $jobs += Start-Job -ArgumentList $payload -ScriptBlock {
          param($item)
          . $item.support
          $env:OATOF_ACCELERATOR_PA_OVERRIDE = $item.accelerator_pa
          $env:OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET = [string]$item.particle_id_offset
          Invoke-ResourceBudgetedProcess `
            -ResolvedBudgetPath $item.budget -RunDir $item.run_dir `
            -UsagePath $item.usage -FilePath $item.executable `
            -WorkingDirectory $item.working_directory `
            -RedirectStandardOutput $item.stdout `
            -RedirectStandardError $item.stderr `
            -ArgumentList ([string[]]$item.arguments)
        }
      }
      try {
        foreach ($job in $jobs) {
          $fly = Receive-Job -Job $job -Wait
          if ($job.State -ne 'Completed' -or $null -eq $fly) {
            throw 'Single-flight SIMION batch job failed.'
          }
          if ($fly.resource_budget_exceeded) {
            $resourceBudgetExceeded = $true
            throw 'Single-flight SIMION batch exceeded its resource budget.'
          }
          if ($fly.exit_code -ne 0) {
            throw 'Single-flight SIMION batch failed.'
          }
        }
      } finally {
        $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
      }
    }
  } finally { $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride }

  $checkpoints = Join-Path $package.result_dir 'single_flight_particle_checkpoints.csv'
  $analysisArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight',
    '--launched',([string]$launched),'--mass-amu','100',
    '--geometry',$oatofGeometry,'--pulse-time-us',([string]$pulseTimeUs),
    '--clock-basis',([string]$settings.clock_basis),
    '--bootstrap-resamples',([string]$BootstrapResamples),
    '--bootstrap-seed',([string]$BootstrapSeed),
    '--initial-global-state',$globalSource,
    '--source-release-mode',$SourceReleaseMode,
    '--initial-global-state-sha256',((Get-FileHash -LiteralPath $globalSource -Algorithm SHA256).Hash),
    '--checkpoints',$checkpoints,'--summary',$package.summary)
  if ($SourceReleaseMode -eq 'pre_pulse_restart') {
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
  if ($PopulationDenominatorCount -gt 0) {
    $analysisArguments += @(
      '--population-denominator-count',([string]$PopulationDenominatorCount),
      '--eligible-population-count',([string]$EligiblePopulationCount)
    )
  }
  if ($spatialWindowProfiles.Count -eq 1) {
    $analysisArguments += @(
      '--configuration',$configuration,
      '--spatial-window-profile-id',$SpatialWindowProfileId
    )
  }
  foreach ($batch in $batchRecords) {
    $analysisArguments += @(
      '--log',$batch.stdout,
      '--batch-particle-count',([string]$batch.count)
    )
  }
  Invoke-SingleFlightPython -Arguments $analysisArguments `
    -Failure 'Single-flight log analysis failed.'
  if ($ResolutionQualification) {
    $qualificationSummary = Get-Content -LiteralPath $package.summary -Raw -Encoding UTF8 | ConvertFrom-Json
    $bootstrapRecords = @($qualificationSummary.full_pulse_eligible_bootstrap)
    if ($null -ne $qualificationSummary.spatial_window_peak) {
      $bootstrapRecords += @($qualificationSummary.spatial_window_peak.bootstrap)
    }
    if ($bootstrapRecords.Count -lt 2 -or @($bootstrapRecords | Where-Object {
          [string]$_.status -ne 'computed' -or
          [int]$_.resamples_requested -ne 5000 -or
          [int]$_.resamples_valid -lt 4750 -or
          [double]$_.relative_95pct_interval_width -gt 0.10
        }).Count -ne 0) {
      throw 'Resolution qualification bootstrap acceptance failed.'
    }
  }
  $sixPanel = Join-Path $package.result_dir 'single_flight_spatial_six_panel.png'
  $sixPanelMetadata = Join-Path $package.result_dir 'single_flight_spatial_six_panel_metadata.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel',
    '--initial',$globalSource,'--checkpoints',$checkpoints,'--upstream',$upstreamFrozen,
    '--frontend',$frontendContract,'--oatof',$oatofGeometry,'--output',$sixPanel,
    '--metadata',$sixPanelMetadata) -Failure 'Single-flight six-panel spatial diagnostic failed.'
  $result = Get-Content -LiteralPath $package.summary -Raw -Encoding UTF8 | ConvertFrom-Json
  $baselineReceipt = $null
  $promotionReceipt = $null
  if ($PulseResolutionN100Screening) {
    $resultName = if ($PulseResolutionArmId -eq 'real_beam_all_real') {
      'pulse_resolution_real_beam_all_real_n100_baseline_result.json'
    } elseif ($PulseResolutionArmId -eq 'real_beam_ideal_stage1') {
      'pulse_resolution_real_beam_ideal_stage1_n100_candidate_result.json'
    } elseif ($PulseResolutionArmId -eq 'real_beam_ideal_stage1_stage2') { 'pulse_resolution_real_beam_ideal_stage1_stage2_n100_candidate_result.json' } else { 'pulse_resolution_real_beam_full_domain_piecewise_ideal_n100_candidate_result.json' }
    $baselineReceipt = Join-Path $package.result_dir $resultName
    $receiptArguments = @('-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.register_n100_baseline',
      '--campaign',$campaignFrozen,
      '--campaign-sha256',$PulseResolutionCampaignSha256,
      '--experiment-row-sha256',$PulseResolutionExperimentRowSha256,
      '--experiment-id',$(if($PulseResolutionArmId -eq 'real_beam_all_real'){'pulse_resolution_baseline'}elseif($PulseResolutionArmId -eq 'real_beam_ideal_stage1'){'pulse_resolution_real_beam_ideal_stage1_real_stage2_real_reflectron_n100'}elseif($PulseResolutionArmId -eq 'real_beam_ideal_stage1_stage2'){'pulse_resolution_real_beam_ideal_stage1_stage2_real_reflectron_n100'}else{'pulse_resolution_real_beam_full_domain_piecewise_ideal_n100'}),
      '--arm-id',$PulseResolutionArmId,'--execution-mode',$PulseResolutionExecutionMode,
      '--summary',$package.summary,'--checkpoints',$checkpoints,
      '--source-identity',$sourceIdentity,'--prefix',$motherSource,
      '--prefix-plan-path','inputs/pulse_resolution_arm1_all_real_screening_prefix_n100.csv',
      '--prefix-sha256',$MotherParticleSourceSha256,
      '--registration-authority',$registrationAuthorityFrozen,
      '--registration-authority-sha256',$PulseResolutionRegistrationAuthoritySha256,
      '--output',$baselineReceipt)
    if ($PulseResolutionArmId -ne 'real_beam_all_real') {
      if (-not (Test-Path -LiteralPath $PulseResolutionBaselineCheckpoints -PathType Leaf) -or
          (Get-FileHash -LiteralPath $PulseResolutionBaselineCheckpoints -Algorithm SHA256).Hash -ne
            $PulseResolutionBaselineCheckpointsSha256) {
        throw 'Paired baseline checkpoints SHA differs.'
      }
      $promotionReceipt = Join-Path $package.result_dir (
        $(if($PulseResolutionArmId -eq 'real_beam_all_ideal'){'pulse_resolution_real_beam_full_domain_piecewise_ideal_n100_eligible_only_promotion_receipt.json'}else{'pulse_resolution_' + $PulseResolutionArmId + '_n100_promotion_receipt.json'})
      )
      $receiptArguments += @('--baseline-checkpoints',$PulseResolutionBaselineCheckpoints,
        '--promotion-receipt',$promotionReceipt)
    }
    Invoke-SingleFlightPython -Arguments $receiptArguments `
      -Failure 'N=100 pulse-resolution result receipt failed.'
    $registration = Get-Content -LiteralPath $baselineReceipt -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $expectedStatus = if ($PulseResolutionArmId -eq 'real_beam_all_real') {
      'baseline_registered_not_candidate'
    } else { 'candidate_screening_complete_not_qualified' }
    if ($registration.execution_status -ne $expectedStatus -or
        $registration.formal_gate_passed) {
      throw 'N=100 screening result receipt differs.'
    }
    $result | Add-Member -NotePropertyName pulse_resolution_registration `
      -NotePropertyValue ([ordered]@{
        execution_status=$expectedStatus
        receipt=('results/' + $resultName)
        receipt_sha256=(Get-FileHash -LiteralPath $baselineReceipt -Algorithm SHA256).Hash
      }) -Force
    if ($null -ne $promotionReceipt) {
      $promotion = Get-Content -LiteralPath $promotionReceipt -Raw -Encoding UTF8 |
        ConvertFrom-Json
      $result | Add-Member -NotePropertyName pulse_resolution_promotion `
        -NotePropertyValue ([ordered]@{
          decision=[string]$promotion.decision
          population_count=[int]$promotion.pairing.population_count
          eligible_paired_count=[int]$promotion.pairing.eligible_paired_count
          failure_codes=@($promotion.failure_reasons | ForEach-Object { [string]$_.code })
          receipt=('results/' + [IO.Path]::GetFileName($promotionReceipt))
          receipt_sha256=(Get-FileHash -LiteralPath $promotionReceipt -Algorithm SHA256).Hash
        }) -Force
    }
    Write-RfJson -Path $package.summary -Depth 10 -Value $result
  }
  $runConfiguration.parameters.multipole_handoff_count = [int]$result.census.multipole_handoff
  $runConfiguration.parameters.local_accelerator_exit_count = [int]$result.census.local_accelerator_exit
  $runConfiguration.parameters.detector_crossing_count = [int]$result.census.detector_crossing
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $outputs = @($checkpoints,$sixPanel,$sixPanelMetadata,$baselineReceipt,$promotionReceipt) + $stdoutFiles + $stderrFiles + $resourceUsageFiles + @($flightTubeBuildStdout,$flightTubeBuildStderr,$reflectronBuildStdout,$reflectronBuildStderr,$package.summary,$retentionActions) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
  foreach ($usage in $resourceUsageFiles) {
    if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath $usage)) { $resourceBudgetExceeded=$true; throw 'Single-flight compact retained-byte budget exceeded.' }
  }
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  Write-Output "SIMION_SINGLE_FLIGHT=PASS RUN_ID=$RunId DETECTOR=$($result.census.detector_crossing)/$launched"
} catch {
  if ($snapshotReady) {
    Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole $summaryRole -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status $(if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}) -FailureClass $(if ($resourceBudgetExceeded) {'resource_budget_exceeded'} else {''}) -ResourceUsagePath $(if ($resourceBudgetExceeded) {$resourceUsage} else {''})
  } else {
    Write-RfJson -Path $package.summary -Value ([ordered]@{schema_version=1;role=$summaryRole;status='failed';reason=$_.Exception.Message;manifest_written=$false})
  }
  throw
}
