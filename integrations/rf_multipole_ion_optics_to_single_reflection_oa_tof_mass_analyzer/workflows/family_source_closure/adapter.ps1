[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CompositionPlan,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$PythonExe,
  [Parameter(Mandatory)][string]$RepoRoot,
  [string]$RunId = '',
  [switch]$PrepareOnly,
  [switch]$SolverAuthorized,
  [switch]$FinalizeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$workflowRoot = $PSScriptRoot
$integrationRoot = (Resolve-Path (Join-Path $workflowRoot '..\..')).Path
$registryPath = Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
. (Join-Path $integrationRoot 'runtime\runtime_binding.ps1')
. (Join-Path $integrationRoot 'runtime\run_artifacts.ps1')

function Resolve-RfObservedPrePulseSourceIdentity {
  param(
    [Parameter(Mandatory)]$Experiment,
    [Parameter(Mandatory)]$BudgetSourceIdentity
  )
  $experimentHasProjection = $Experiment.PSObject.Properties.Name -contains
    'observed_pre_pulse_projection'
  $budgetHasProjection = $BudgetSourceIdentity.PSObject.Properties.Name -contains
    'observed_pre_pulse_projection'
  if ($experimentHasProjection) {
    if (-not $budgetHasProjection -or
        ($Experiment.observed_pre_pulse_projection |
          ConvertTo-Json -Depth 100 -Compress) -cne
        ($BudgetSourceIdentity.observed_pre_pulse_projection |
          ConvertTo-Json -Depth 100 -Compress)) {
      throw 'Observed pre-pulse projection source identity differs from the campaign row.'
    }
  } elseif ($budgetHasProjection) {
    throw 'Non-observed campaign row prohibits an observed pre-pulse projection identity.'
  }
  return $BudgetSourceIdentity
}

function Resolve-RfPulseTimingOrchestrationArguments {
  param(
    [Parameter(Mandatory)][hashtable]$FrozenArguments,
    [string]$PreparedRoot = ''
  )

  $names = @(
    'pulse_timing_orchestration_filename',
    'pulse_timing_orchestration_sha256',
    'pulse_timing_orchestration_state'
  )
  $presentCount = @($names | Where-Object {
    $FrozenArguments.ContainsKey($_)
  }).Count
  if ($presentCount -eq 0) {
    return
  }
  if ($presentCount -ne $names.Count) {
    throw 'Prepared pulse-timing orchestration arguments must be all-or-none.'
  }
  if ([string]$FrozenArguments.pulse_timing_orchestration_filename -ne
        'resolved_pulse_timing_orchestration.json' -or
      [string]$FrozenArguments.pulse_timing_orchestration_state -notin @(
        'discovery_required','confirmation_required','ready_verified'
      )) {
    throw 'Prepared pulse-timing orchestration filename or state is invalid.'
  }
  if (-not [string]::IsNullOrWhiteSpace($PreparedRoot)) {
    $root = [IO.Path]::GetFullPath($PreparedRoot)
    $path = [IO.Path]::GetFullPath((Join-Path $root `
      $FrozenArguments.pulse_timing_orchestration_filename))
    if (-not (Split-Path -Parent $path).Equals(
          $root,[StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne
          [string]$FrozenArguments.pulse_timing_orchestration_sha256) {
      throw 'Prepared pulse-timing orchestration file is missing, misplaced or stale.'
    }
  }
  return $names
}

$plan = Get-Content -LiteralPath $CompositionPlan -Raw -Encoding UTF8 |
  ConvertFrom-Json
$resolved = Get-Content -LiteralPath $ResolvedConnection -Raw -Encoding UTF8 |
  ConvertFrom-Json
$steps = @($plan.execution_steps)
if ($steps.Count -ne 1 -or $steps[0].step_id -ne 'rf_to_oatof_transfer') {
  throw 'Prepared family plan does not contain one transfer step.'
}
if ($plan.selection.connection_profile_id -ne
    $resolved.selection.connection_profile_id) {
  throw 'Prepared family plan and resolved connection identities differ.'
}

if ($FinalizeOnly) {
  if ($PrepareOnly -or $SolverAuthorized -or [string]::IsNullOrWhiteSpace($RunId)) {
    throw 'FinalizeOnly is mutually exclusive with preparation and solver execution and requires a recovery run ID.'
  }
  $sourceParentRoot = (Split-Path -Parent ([IO.Path]::GetFullPath($CompositionPlan)))
  $expectedRecoveryRunId = (Split-Path -Leaf $sourceParentRoot) + '__r01'
  if ($RunId -ne $expectedRecoveryRunId) {
    throw 'FinalizeOnly recovery run ID must be the exact failed parent run ID plus __r01.'
  }
  $workspaceRoot = Split-Path -Parent $RepoRoot
  $recoveryParentRoot = Join-Path $workspaceRoot (
    'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs\' + $RunId
  )
  if (Test-Path -LiteralPath $recoveryParentRoot) {
    throw 'FinalizeOnly recovery parent directory already exists.'
  }
  $campaignArgument = @($plan.execution_steps[0].arguments | Where-Object {
    [string]$_ -like 'campaign_path=*'
  })
  if ($campaignArgument.Count -ne 1) {
    throw 'FinalizeOnly source plan does not bind exactly one campaign path.'
  }
  $campaignPath = Join-Path $RepoRoot (([string]$campaignArgument[0]).Substring('campaign_path='.Length))
  Push-Location -LiteralPath $RepoRoot
  try {
    & $PythonExe -m (
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
      'workflows.family_source_closure.recover_completed_single_flight'
    ) --repo-root $RepoRoot --campaign $campaignPath --failed-parent-run-dir $sourceParentRoot `
      --recovery-parent-run-dir $recoveryParentRoot
    if ($LASTEXITCODE -ne 0) {
      throw 'FinalizeOnly completed-single-flight recovery failed.'
    }
  } finally {
    Pop-Location
  }
  Write-Output "FAMILY_SOURCE_CLOSURE_ADAPTER=FINALIZED RUN_ID=$RunId"
  exit 0
}

$frozenArguments = @{}
foreach ($argument in @($steps[0].arguments)) {
  $separator = $argument.IndexOf('=')
  if ($separator -le 0) {
    throw "Prepared family adapter argument is invalid: $argument"
  }
  $name = $argument.Substring(0, $separator)
  if ($frozenArguments.ContainsKey($name)) {
    throw "Prepared family adapter argument is duplicated: $name"
  }
  $frozenArguments[$name] = $argument.Substring($separator + 1)
}
$expectedArguments = @(
  'adapter_registry_sha256',
  'campaign_path',
  'campaign_sha256',
  'campaign_id',
  'experiment_id',
  'experiment_row_sha256',
  'execution_strategy',
  'runtime_binding_path',
  'runtime_binding_sha256',
  'source_branch_id',
  'resolved_budget_filename',
  'resolved_budget_sha256',
  'resolved_source_contract_filename',
  'resolved_source_contract_sha256',
  'upstream_resolved_design_filename',
  'upstream_resolved_design_sha256'
)
if ([string]$frozenArguments.execution_strategy -eq 'simion_single_flight') {
  $expectedArguments += @(
    'single_flight_pa_cache_policy',
    'single_flight_pa_cache_policy_provenance',
    'single_flight_batch_count'
  )
  if ($frozenArguments.ContainsKey('single_flight_pa_cache_generation_binding_filename')) {
    $expectedArguments += @(
      'single_flight_pa_cache_generation_binding_filename',
      'single_flight_pa_cache_generation_binding_sha256'
    )
  }
}
$layoutArgumentNames = @(
  'layout_profile_id',
  'architecture_generation_id',
  'resolved_oatof_geometry_filename',
  'resolved_oatof_geometry_sha256',
  'resolved_oatof_bore_radius_mm',
  'resolved_oatof_ring_outer_radius_mm',
  'resolved_oatof_shield_inner_radius_mm',
  'resolved_population_contract_filename',
  'resolved_population_contract_sha256',
  'single_flight_layout_registry_sha256'
)
if ($frozenArguments.ContainsKey('layout_profile_id')) {
  $expectedArguments += $layoutArgumentNames
  if ($frozenArguments.ContainsKey('resolved_single_flight_pulse_schedule_filename')) {
    $expectedArguments += @(
      'resolved_single_flight_pulse_schedule_filename',
      'resolved_single_flight_pulse_schedule_sha256'
    )
  }
}
$threeZoneCandidateArgumentNames = @(
  'single_flight_three_zone_candidate_path',
  'single_flight_three_zone_candidate_sha256'
)
if ($frozenArguments.ContainsKey('single_flight_three_zone_candidate_path')) {
  $expectedArguments += $threeZoneCandidateArgumentNames
}
$sourceOverrideArgumentNames = @(
  'single_flight_particle_source_path',
  'single_flight_particle_source_sha256',
  'single_flight_particle_source_count'
)
if ($frozenArguments.ContainsKey('single_flight_particle_source_path')) {
  $expectedArguments += $sourceOverrideArgumentNames
}
$materializedSourceArgumentNames = @(
  'single_flight_source_materialization_profile_id',
  'single_flight_materialized_source_filename',
  'single_flight_materialized_source_sha256',
  'single_flight_materialized_source_count',
  'single_flight_materialization_receipt_filename',
  'single_flight_materialization_receipt_sha256'
)
if ($frozenArguments.ContainsKey('single_flight_source_materialization_profile_id')) {
  $expectedArguments += 'single_flight_source_materialization_profile_id'
  if ($frozenArguments.ContainsKey('single_flight_materialized_source_filename')) {
    $expectedArguments += $materializedSourceArgumentNames[1..5]
  }
}
if ($frozenArguments.ContainsKey('single_flight_frontend_grid_profile_id')) {
  $expectedArguments += 'single_flight_frontend_grid_profile_id'
}
if ($frozenArguments.ContainsKey('single_flight_oatof_numerical_profile_id')) {
  $expectedArguments += 'single_flight_oatof_numerical_profile_id'
}
if ($frozenArguments.ContainsKey('single_flight_trajectory_quality_profile_id')) {
  $expectedArguments += 'single_flight_trajectory_quality_profile_id'
}
if ($frozenArguments.ContainsKey('single_flight_time_integration_profile_id')) {
  $expectedArguments += 'single_flight_time_integration_profile_id'
}
if ($frozenArguments.ContainsKey('single_flight_maximum_time_of_flight_us')) {
  $expectedArguments += 'single_flight_maximum_time_of_flight_us'
}
if ($frozenArguments.ContainsKey('single_flight_spatial_window_profile_id')) {
  $expectedArguments += 'single_flight_spatial_window_profile_id'
}
if ($frozenArguments.ContainsKey('resolved_region_field_contract_filename')) {
  $expectedArguments += @(
    'resolved_region_field_contract_filename',
    'resolved_region_field_contract_sha256',
    'resolved_region_field_semantic_sha256',
    'resolved_region_field_profile_id'
  )
}
if ($frozenArguments.ContainsKey('source_zvz_affine_receipt_filename')) {
  $expectedArguments += @(
    'source_zvz_affine_receipt_filename',
    'source_zvz_affine_receipt_sha256'
  )
}
if ($frozenArguments.ContainsKey('source_zvz_theory_working_point_filename')) {
  $expectedArguments += @(
    'source_zvz_theory_working_point_filename',
    'source_zvz_theory_working_point_sha256',
    'source_zvz_theory_geometry_input_sha256'
  )
}
if ($frozenArguments.ContainsKey('source_release_mode')) {
  $expectedArguments += 'source_release_mode'
  if ($frozenArguments.ContainsKey('source_profile_id')) {
    $expectedArguments += @('source_profile_id','field_overlay_id')
  }
}
if ($frozenArguments.ContainsKey('pre_pulse_source_state_path')) {
  $expectedArguments += @(
    'pre_pulse_source_state_path','pre_pulse_source_state_sha256',
    'pre_pulse_source_state_count'
  )
  if ($frozenArguments.ContainsKey('pre_pulse_restart_validation_filename')) {
    $expectedArguments += @(
      'pre_pulse_restart_position_tolerance_mm',
      'pre_pulse_restart_velocity_tolerance_m_per_s',
      'pre_pulse_restart_clock_tolerance_us',
      'pre_pulse_restart_energy_tolerance_eV',
      'pre_pulse_restart_validation_filename',
      'pre_pulse_restart_validation_sha256'
    )
  }
}
$hasPrePulseTimeSeriesArguments = $frozenArguments.ContainsKey(
  'pre_pulse_time_series_contract_filename'
)
if ($hasPrePulseTimeSeriesArguments) {
  $expectedArguments += @(
    'pre_pulse_time_series_prefix_filename',
    'pre_pulse_time_series_prefix_sha256',
    'pre_pulse_time_series_prefix_count',
    'pre_pulse_time_series_contract_filename',
    'pre_pulse_time_series_contract_sha256',
    'pre_pulse_time_series_time_integration_profile_id'
  )
}
$hasPulseCandidateConfirmationArguments = $frozenArguments.ContainsKey(
  'pulse_candidate_confirmation_prefix_filename'
)
if ($hasPulseCandidateConfirmationArguments) {
  $expectedArguments += @(
    'pulse_candidate_confirmation_prefix_filename',
    'pulse_candidate_confirmation_prefix_sha256',
    'pulse_candidate_confirmation_prefix_count'
  )
}
$pulseTimingInternalStage = if (
  $frozenArguments.ContainsKey('pulse_timing_internal_stage')
) { [string]$frozenArguments.pulse_timing_internal_stage } else { '' }
if ($pulseTimingInternalStage -ne '') {
  if ($pulseTimingInternalStage -notin @(
      'pulse_timing_discovery','pulse_timing_confirmation'
    )) {
    throw 'Prepared pulse-timing internal stage is unsupported.'
  }
  $expectedArguments += 'pulse_timing_internal_stage'
}
$pulseTimingOrchestrationArgumentNames = @(
  Resolve-RfPulseTimingOrchestrationArguments -FrozenArguments $frozenArguments
)
$expectedArguments += $pulseTimingOrchestrationArgumentNames
if (@($frozenArguments.Keys | Where-Object {
      $_ -notin $expectedArguments
    }).Count -ne 0 -or
    @($expectedArguments | Where-Object {
      -not $frozenArguments.ContainsKey($_)
    }).Count -ne 0) {
  throw 'Prepared family adapter arguments differ from the campaign-only contract.'
}

$sourceBranchId = [string]$frozenArguments.source_branch_id
if ($sourceBranchId -notin @('comsol','simion')) {
  throw 'Prepared family source branch is invalid.'
}
$executionStrategy = [string]$frozenArguments.execution_strategy
if ($executionStrategy -notin @('staged_three_stage','simion_single_flight')) {
  throw 'Prepared family execution strategy is invalid.'
}
if ((Get-FileHash -LiteralPath $registryPath -Algorithm SHA256).Hash -ne
    $frozenArguments.adapter_registry_sha256) {
  throw 'Family adapter registry changed after preparation.'
}

$repo = [IO.Path]::GetFullPath($RepoRoot)
$workspaceRoot = Split-Path -Parent $repo
$campaignPath = [IO.Path]::GetFullPath(
  (Join-Path $repo $frozenArguments.campaign_path)
)
if (-not $campaignPath.StartsWith(
      $repo + [IO.Path]::DirectorySeparatorChar,
      [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not (Test-Path -LiteralPath $campaignPath -PathType Leaf) -or
    (Get-RfOatofRepositoryTextSha256 -Path $campaignPath) -ne
      $frozenArguments.campaign_sha256) {
  throw 'Campaign path is outside the repository, missing or stale.'
}
$campaign = Get-Content -LiteralPath $campaignPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$prepareModule = (
  'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
  'workflows.family_source_closure.prepare'
)
$profileRegistry = Join-Path $integrationRoot 'config\connection_profiles.json'
$adapterRegistry = Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
$selectedExperimentJson = & $PythonExe -m $prepareModule --repo-root $repo `
  --profile-registry $profileRegistry --adapter-registry $adapterRegistry `
  --campaign $campaignPath --print-experiment-json $frozenArguments.experiment_id
if ($LASTEXITCODE -ne 0) {
  throw 'Campaign experiment identity no longer resolves uniquely.'
}
$experiments = @($selectedExperimentJson | ConvertFrom-Json)
if ($campaign.role -ne 'rf_multipole_oatof_experiment_campaign' -or
    $campaign.integration_id -ne $plan.integration_id -or
    $campaign.campaign_id -ne $frozenArguments.campaign_id -or
    $experiments.Count -ne 1) {
  throw 'Campaign or experiment identity no longer resolves uniquely.'
}
if ($SolverAuthorized) {
  $lifecycleRegistryPath = Join-Path $integrationRoot `
    'config\diagnostics\lifecycle_registry.json'
  $lifecycleRegistry = Get-Content -LiteralPath $lifecycleRegistryPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $campaignRepoRelative = [IO.Path]::GetRelativePath($repo, $campaignPath).Replace('\', '/')
  $currentCampaigns = @($lifecycleRegistry.active_campaigns | Where-Object {
    [string]$_.path -eq $campaignRepoRelative
  })
  if ($currentCampaigns.Count -ne 1 -or
      (Get-RfOatofRepositoryTextSha256 -Path $campaignPath) -ne
        ([string]$currentCampaigns[0].content_sha256).ToUpperInvariant()) {
    throw 'Campaign is not a current registered execution authority; SolverAuthorized is forbidden.'
  }
}
$experiment = $experiments[0]
$campaignHasThreeZoneCandidate = (
  $experiment.PSObject.Properties.Name -contains
  'single_flight_three_zone_candidate'
)
$argumentsHaveThreeZoneCandidate = (
  $frozenArguments.ContainsKey('single_flight_three_zone_candidate_path') -and
  $frozenArguments.ContainsKey('single_flight_three_zone_candidate_sha256')
)
if ($campaignHasThreeZoneCandidate -ne $argumentsHaveThreeZoneCandidate) {
  throw 'Three-zone Candidate binding and layout identity differ.'
}
$threeZoneCandidatePath = $null
if ($campaignHasThreeZoneCandidate) {
  if ([string]$experiment.single_flight_three_zone_candidate.path -ne
      [string]$frozenArguments.single_flight_three_zone_candidate_path -or
      [string]$experiment.single_flight_three_zone_candidate.sha256 -ne
      [string]$frozenArguments.single_flight_three_zone_candidate_sha256) {
    throw 'Three-zone Candidate campaign and plan bindings differ.'
  }
  $threeZoneCandidatePath = [IO.Path]::GetFullPath(
    (Join-Path $workspaceRoot $frozenArguments.single_flight_three_zone_candidate_path)
  )
  $workspaceArtifactRoot = [IO.Path]::GetFullPath(
    (Join-Path $workspaceRoot 'artifacts')
  )
  if (-not $threeZoneCandidatePath.StartsWith(
        $workspaceArtifactRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      ) -or
      -not (Test-Path -LiteralPath $threeZoneCandidatePath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $threeZoneCandidatePath -Algorithm SHA256).Hash -ne
      $frozenArguments.single_flight_three_zone_candidate_sha256) {
    throw 'Three-zone Candidate is outside workspace artifacts, missing or stale.'
  }
}
$experimentHasPaCachePolicy =
  $experiment.PSObject.Properties.Name -contains 'single_flight_pa_cache_policy'
if ([string]$experiment.execution_strategy -eq 'simion_single_flight') {
  if (-not $experimentHasPaCachePolicy) {
    throw 'Single-flight execution requires an explicit PA cache policy.'
  }
  $expectedPaCachePolicy = [string]$experiment.single_flight_pa_cache_policy
  $expectedPaCachePolicyProvenance = 'explicit_campaign_row'
  if ([string]$frozenArguments.single_flight_pa_cache_policy -ne
        $expectedPaCachePolicy -or
      [string]$frozenArguments.single_flight_pa_cache_policy_provenance -ne
        $expectedPaCachePolicyProvenance) {
    throw 'Frozen PA cache policy differs from the exact campaign row.'
  }
}
if ($SolverAuthorized -and
    [string]$experiment.execution_strategy -eq 'simion_single_flight' -and (
      $expectedPaCachePolicy -notin @(
        'require_existing','build_and_publish_if_missing'
      ))) {
  throw 'SolverAuthorized single-flight execution requires an explicit schema-v4 PA cache policy.'
}
$campaignHasPrePulseTimeSeries = (
  $campaign.PSObject.Properties.Name -contains
  'pre_pulse_time_series_screening'
) -and $null -ne $campaign.pre_pulse_time_series_screening
$pulseSchedulePolicyProperty =
  $experiment.PSObject.Properties['single_flight_pulse_schedule_policy']
$pulseSchedulePolicy = if ($null -ne $pulseSchedulePolicyProperty) {
  $pulseSchedulePolicyProperty.Value
} else { $null }
$cacheMissPolicyProperty = if ($null -ne $pulseSchedulePolicy) {
  $pulseSchedulePolicy.PSObject.Properties['cache_miss_policy']
} else { $null }
$automaticPulseTiming = (
  $null -ne $cacheMissPolicyProperty -and
  $null -ne $cacheMissPolicyProperty.Value -and
  [string]$cacheMissPolicyProperty.Value.mode -eq
    'auto_detector_blind_discovery_and_confirmation_v1'
)
$pulseTimingDiscovery = $pulseTimingInternalStage -eq 'pulse_timing_discovery'
$pulseTimingConfirmation = $pulseTimingInternalStage -eq 'pulse_timing_confirmation'
$pulseTimingDiscoveryRequired = $automaticPulseTiming -and
  $frozenArguments.ContainsKey('pulse_timing_orchestration_state') -and
  [string]$frozenArguments.pulse_timing_orchestration_state -eq
    'discovery_required'
if (($pulseTimingDiscovery -or $pulseTimingConfirmation) -and
    -not $automaticPulseTiming) {
  throw 'Internal pulse-timing stage requires the automatic campaign policy.'
}
if (($campaignHasPrePulseTimeSeries -or $pulseTimingDiscovery -or
    $pulseTimingDiscoveryRequired) -ne
    $hasPrePulseTimeSeriesArguments) {
  throw 'Pre-pulse time-series campaign and prepared authority differ.'
}
$prePulseTimeSeriesScreening = $campaignHasPrePulseTimeSeries -or
  $pulseTimingDiscovery -or $pulseTimingDiscoveryRequired
$pulseCandidateConfirmation = $pulseTimingConfirmation
if ($pulseCandidateConfirmation -ne $hasPulseCandidateConfirmationArguments) {
  throw 'Pulse candidate confirmation and prepared prefix authority differ.'
}
if ($pulseCandidateConfirmation -and $prePulseTimeSeriesScreening) {
  throw 'Pulse candidate confirmation and screening authorities are mutually exclusive.'
}
$singleFlightParticleSourcePath = $null
if ($frozenArguments.ContainsKey('single_flight_particle_source_path')) {
  $singleFlightParticleSourcePath = [IO.Path]::GetFullPath(
    (Join-Path $repo $frozenArguments.single_flight_particle_source_path)
  )
  $declaredSource = $experiment.single_flight_particle_source
  if ($null -eq $declaredSource -or
      [string]$declaredSource.path -ne $frozenArguments.single_flight_particle_source_path -or
      [string]$declaredSource.sha256 -ne $frozenArguments.single_flight_particle_source_sha256 -or
      [int]$declaredSource.particle_count -ne [int]$frozenArguments.single_flight_particle_source_count -or
      -not $singleFlightParticleSourcePath.StartsWith($repo + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
      -not (Test-Path -LiteralPath $singleFlightParticleSourcePath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $singleFlightParticleSourcePath -Algorithm SHA256).Hash -ne $frozenArguments.single_flight_particle_source_sha256) {
    throw 'Single-flight particle-source override is missing or stale.'
  }
}
if ($frozenArguments.ContainsKey('single_flight_materialized_source_filename')) {
  if ($null -ne $singleFlightParticleSourcePath -or
      [string]$experiment.single_flight_source_materialization_profile_id -ne
        $frozenArguments.single_flight_source_materialization_profile_id) {
    throw 'Materialized and static single-flight source authorities conflict.'
  }
  $materializedRunDirectory = [IO.Path]::GetFullPath(
    (Split-Path -Parent $CompositionPlan)
  )
  $singleFlightParticleSourcePath = [IO.Path]::GetFullPath(
    (Join-Path $materializedRunDirectory $frozenArguments.single_flight_materialized_source_filename)
  )
  $materializationReceiptPath = [IO.Path]::GetFullPath(
    (Join-Path $materializedRunDirectory $frozenArguments.single_flight_materialization_receipt_filename)
  )
  $inputsRoot = [IO.Path]::GetFullPath((Join-Path $materializedRunDirectory 'inputs'))
  if (-not $singleFlightParticleSourcePath.StartsWith(
        $inputsRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase) -or
      -not $materializationReceiptPath.StartsWith(
        $inputsRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase) -or
      -not (Test-Path -LiteralPath $singleFlightParticleSourcePath -PathType Leaf) -or
      -not (Test-Path -LiteralPath $materializationReceiptPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $singleFlightParticleSourcePath -Algorithm SHA256).Hash -ne
        $frozenArguments.single_flight_materialized_source_sha256 -or
      (Get-FileHash -LiteralPath $materializationReceiptPath -Algorithm SHA256).Hash -ne
        $frozenArguments.single_flight_materialization_receipt_sha256) {
    throw 'Plan-bound source materialization inputs are missing or stale.'
  }
  $materializationReceipt = Get-Content -LiteralPath $materializationReceiptPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($materializationReceipt.role -ne 'rf_oatof_single_flight_source_materialization_receipt' -or
      $materializationReceipt.profile_id -ne
        $frozenArguments.single_flight_source_materialization_profile_id -or
      [int]$materializationReceipt.particle_count -ne
        [int]$frozenArguments.single_flight_materialized_source_count -or
      $materializationReceipt.particle_source.sha256 -ne
        $frozenArguments.single_flight_materialized_source_sha256 -or
      $materializationReceipt.particle_source.sampling_mode -ne
        'continuous_injection_full_population') {
    throw 'Plan-bound source materialization receipt differs.'
  }
  $frozenArguments.single_flight_particle_source_sha256 =
    $frozenArguments.single_flight_materialized_source_sha256
  $frozenArguments.single_flight_particle_source_count =
    $frozenArguments.single_flight_materialized_source_count
}
$prePulseSourceStatePath = $null
$prePulseRestartValidationPath = $null
if ($frozenArguments.ContainsKey('source_release_mode')) {
  if ([string]$experiment.source_release_mode -ne $frozenArguments.source_release_mode) {
    throw 'Campaign source-release identity changed after preparation.'
  }
  if ($frozenArguments.ContainsKey('source_profile_id') -and (
      [string]$experiment.architecture_generation_id -ne
        $frozenArguments.architecture_generation_id -or
      [string]$experiment.source_profile_id -ne $frozenArguments.source_profile_id -or
      [string]$experiment.field_overlay_id -ne $frozenArguments.field_overlay_id)) {
    throw 'Campaign architecture/source/field identity changed after preparation.'
  }
  if ($frozenArguments.source_release_mode -eq 'pre_pulse_restart') {
    $usesGeneratedPrePulseSubset =
      $experiment.PSObject.Properties.Name -contains
        'generated_pre_pulse_ordered_subset'
    $usesManifestBoundPostPulseRestart =
      $experiment.PSObject.Properties.Name -contains
        'post_pulse_restart_reuse_authority'
    $declaredPrePulseSourceState = if (
      $experiment.PSObject.Properties.Name -contains 'pre_pulse_source_state'
    ) { $experiment.pre_pulse_source_state } else { $null }
    $restartAuthorityCount = @(
      $usesGeneratedPrePulseSubset,
      $usesManifestBoundPostPulseRestart,
      ($null -ne $declaredPrePulseSourceState)
    ).Where({ $_ }).Count
    if ($restartAuthorityCount -ne 1) {
      throw 'Pre-pulse restart must select exactly one governed source authority.'
    }
    if (-not $frozenArguments.ContainsKey('pre_pulse_source_state_path')) {
      throw 'Pre-pulse restart lacks a frozen source state.'
    }
    if ($frozenArguments.ContainsKey('pre_pulse_restart_validation_filename')) {
      if ($null -ne $declaredPrePulseSourceState -and (
        [double]$declaredPrePulseSourceState.position_rowwise_abs_tolerance_mm -ne
          [double]$frozenArguments.pre_pulse_restart_position_tolerance_mm -or
        [double]$declaredPrePulseSourceState.velocity_rowwise_abs_tolerance_m_per_s -ne
          [double]$frozenArguments.pre_pulse_restart_velocity_tolerance_m_per_s -or
        [double]$declaredPrePulseSourceState.clock_abs_tolerance_us -ne
          [double]$frozenArguments.pre_pulse_restart_clock_tolerance_us -or
        [double]$declaredPrePulseSourceState.energy_abs_tolerance_eV -ne
          [double]$frozenArguments.pre_pulse_restart_energy_tolerance_eV
      )) {
        throw 'Pre-pulse restart source-release tolerance identity changed after preparation.'
      }
      $prePulseRestartValidationPath = Join-Path (Split-Path -Parent $CompositionPlan) `
        $frozenArguments.pre_pulse_restart_validation_filename
      if (-not (Test-Path -LiteralPath $prePulseRestartValidationPath -PathType Leaf) -or
          (Get-FileHash -LiteralPath $prePulseRestartValidationPath -Algorithm SHA256).Hash -ne
            $frozenArguments.pre_pulse_restart_validation_sha256) {
        throw 'Pre-pulse restart validation identity is missing or stale.'
      }
    }
    $prePulseSourceStatePath = [IO.Path]::GetFullPath(
      (Join-Path $workspaceRoot $frozenArguments.pre_pulse_source_state_path)
    )
    $artifactRoot = [IO.Path]::GetFullPath((Join-Path $workspaceRoot 'artifacts'))
    if (-not $prePulseSourceStatePath.StartsWith(
          $artifactRoot + [IO.Path]::DirectorySeparatorChar,
          [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $prePulseSourceStatePath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $prePulseSourceStatePath -Algorithm SHA256).Hash -ne
          $frozenArguments.pre_pulse_source_state_sha256 -or
        ($null -ne $declaredPrePulseSourceState -and
          [int]$declaredPrePulseSourceState.particle_count -ne
            [int]$frozenArguments.pre_pulse_source_state_count) -or
        (($usesGeneratedPrePulseSubset -or $usesManifestBoundPostPulseRestart) -and
          @(Import-Csv -LiteralPath $prePulseSourceStatePath).Count -ne
            [int]$frozenArguments.pre_pulse_source_state_count)) {
      throw 'Pre-pulse source-state identity is missing, stale or outside artifacts.'
    }
  } elseif ($frozenArguments.source_release_mode -ne 'continuous_frontend' -or
            $frozenArguments.ContainsKey('pre_pulse_source_state_path')) {
    throw 'Source release mode and pre-pulse source-state identity differ.'
  }
}
$campaignExecutionStrategy = if (
  $experiment.PSObject.Properties.Name -contains 'execution_strategy'
) { [string]$experiment.execution_strategy } else { 'staged_three_stage' }
if ($campaignExecutionStrategy -ne $executionStrategy) {
  throw 'Campaign execution strategy changed after preparation.'
}
if ($experiment.connection_profile_id -ne
      $plan.selection.connection_profile_id) {
  throw 'Campaign row differs from the prepared connection.'
}
$rowHashCode = @'
import hashlib, json, pathlib, sys
campaign = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import expand_flat_experiment_authoring
campaign = expand_flat_experiment_authoring(campaign)
rows = [row for row in campaign["experiments"] if row["experiment_id"] == sys.argv[2]]
if len(rows) != 1:
    raise SystemExit("campaign experiment identity is not unique")
payload = json.dumps(rows[0], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
print(hashlib.sha256(payload.encode("utf-8")).hexdigest().upper())
'@
$experimentRowSha256 = (& $PythonExe -c $rowHashCode `
  $campaignPath $frozenArguments.experiment_id).Trim()
if ($LASTEXITCODE -ne 0 -or
    $experimentRowSha256 -ne $frozenArguments.experiment_row_sha256) {
  throw 'Campaign experiment row identity changed after preparation.'
}
$registry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$mappings = @($registry.mappings | Where-Object {
  $_.connection_profile_id -eq $plan.selection.connection_profile_id
})
if ($mappings.Count -ne 1) {
  throw 'Family execution adapter mapping no longer resolves uniquely.'
}
$mapping = $mappings[0]
$adapterPath = [IO.Path]::GetFullPath($PSCommandPath)
$expectedAdapterPath = (
  'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/' +
  'workflows/family_source_closure/adapter.ps1'
)
if ($mapping.adapter_entrypoint -ne $expectedAdapterPath -or
    (Get-FileHash -LiteralPath $adapterPath -Algorithm SHA256).Hash -ne
      $mapping.adapter_sha256) {
  throw 'Family adapter implementation differs from its registry identity.'
}
if ($mapping.runtime_binding_path -ne
      $frozenArguments.runtime_binding_path -or
    $mapping.runtime_binding_sha256 -ne
      $frozenArguments.runtime_binding_sha256) {
  throw 'Prepared family runtime binding differs from the active registry.'
}
$runtimeBinding = [IO.Path]::GetFullPath(
  (Join-Path $repo $frozenArguments.runtime_binding_path)
)
if (-not (Test-Path -LiteralPath $runtimeBinding -PathType Leaf) -or
    (Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256).Hash -ne
      $frozenArguments.runtime_binding_sha256) {
  throw 'Family runtime binding is missing or stale.'
}

$runDirectory = [IO.Path]::GetFullPath((Split-Path -Parent $CompositionPlan))
$paCacheGenerationBindingPath = $null
$campaignHasPaCacheGenerationBinding =
  $experiment.PSObject.Properties.Name -contains
    'single_flight_pa_cache_generation_binding'
$argumentsHavePaCacheGenerationBinding =
  $frozenArguments.ContainsKey('single_flight_pa_cache_generation_binding_filename') -and
  $frozenArguments.ContainsKey('single_flight_pa_cache_generation_binding_sha256')
if ($campaignHasPaCacheGenerationBinding -ne $argumentsHavePaCacheGenerationBinding) {
  throw 'Campaign and prepared PA cache generation binding differ.'
}
if ($campaignHasPaCacheGenerationBinding) {
  $paCacheGenerationBindingPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.single_flight_pa_cache_generation_binding_filename)
  )
  if ($frozenArguments.single_flight_pa_cache_generation_binding_filename -ne
      'inputs/single_flight_pa_cache_generation_binding.json' -or
      -not (Test-Path -LiteralPath $paCacheGenerationBindingPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $paCacheGenerationBindingPath -Algorithm SHA256).Hash -ne
        $frozenArguments.single_flight_pa_cache_generation_binding_sha256) {
    throw 'Frozen PA cache generation binding is missing or stale.'
  }
  $frozenPaCacheGenerationBinding = Get-Content -LiteralPath $paCacheGenerationBindingPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if (($frozenPaCacheGenerationBinding | ConvertTo-Json -Depth 8 -Compress) -ne
      ($experiment.single_flight_pa_cache_generation_binding | ConvertTo-Json -Depth 8 -Compress) -or
      [string]$frozenPaCacheGenerationBinding.binding_mode -ne
        'require_exact_schema_v3_generations_v1' -or
      @($frozenPaCacheGenerationBinding.cache_generations).Count -lt 1) {
    throw 'Frozen PA cache generation binding differs from the campaign.'
  }
}
if ($pulseTimingOrchestrationArgumentNames.Count -ne 0) {
  $null = Resolve-RfPulseTimingOrchestrationArguments `
    -FrozenArguments $frozenArguments -PreparedRoot $runDirectory
}
$resolvedRegionFieldContractPath = $null
if ($frozenArguments.ContainsKey('resolved_region_field_contract_filename')) {
  $resolvedRegionFieldContractPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.resolved_region_field_contract_filename)
  )
  $regionInputsRoot = (Join-Path $runDirectory 'inputs') + [IO.Path]::DirectorySeparatorChar
  if ($frozenArguments.resolved_region_field_contract_filename -ne
      'inputs/resolved_region_field_contract.json' -or
      -not $resolvedRegionFieldContractPath.StartsWith(
        $regionInputsRoot,[StringComparison]::OrdinalIgnoreCase
      ) -or
      -not (Test-Path -LiteralPath $resolvedRegionFieldContractPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $resolvedRegionFieldContractPath -Algorithm SHA256).Hash -ne
      $frozenArguments.resolved_region_field_contract_sha256) {
    throw 'Plan-bound resolved region field contract is missing or stale.'
  }
  $resolvedRegionFieldContract = Get-Content -LiteralPath `
    $resolvedRegionFieldContractPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($resolvedRegionFieldContract.role -ne
      'rf_oatof_resolved_region_field_contract' -or
      [bool]$resolvedRegionFieldContract.semantic.real_pa_field_blending_allowed -or
      [string]$resolvedRegionFieldContract.semantic_sha256 -ne
      [string]$frozenArguments.resolved_region_field_semantic_sha256 -or
      [string]$resolvedRegionFieldContract.semantic.canonical_profile_id -ne
      [string]$frozenArguments.resolved_region_field_profile_id -or
      $resolvedRegionFieldContract.layout_geometry.sha256 -ne
      $frozenArguments.resolved_oatof_geometry_sha256) {
    throw 'Plan-bound resolved region field contract identity differs.'
  }
}
$sourceZvzAffineReceiptPath = $null
if ($frozenArguments.ContainsKey('source_zvz_affine_receipt_filename')) {
  $sourceZvzAffineReceiptPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.source_zvz_affine_receipt_filename)
  )
  if ($frozenArguments.source_zvz_affine_receipt_filename -ne
      'inputs/source_zvz_affine_receipt.json' -or
      -not (Test-Path -LiteralPath $sourceZvzAffineReceiptPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $sourceZvzAffineReceiptPath -Algorithm SHA256).Hash -ne
      $frozenArguments.source_zvz_affine_receipt_sha256) {
    throw 'Plan-bound source z--vz affine receipt is missing or stale.'
  }
  $sourceZvzAffineReceipt = Get-Content -LiteralPath `
    $sourceZvzAffineReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceZvzAffineReceipt.role -ne 'rf_oatof_source_zvz_affine_receipt' -or
      $sourceZvzAffineReceipt.policy_id -ne 'source_zvz_affine_identify_and_bind_v1') {
    throw 'Plan-bound source z--vz affine receipt has an unsupported identity.'
  }
}
$sourceZvzTheoryWorkingPointPath = $null
if ($frozenArguments.ContainsKey('source_zvz_theory_working_point_filename')) {
  $sourceZvzTheoryWorkingPointPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.source_zvz_theory_working_point_filename)
  )
  if ($frozenArguments.source_zvz_theory_working_point_filename -ne
      'inputs/source_zvz_theory_working_point.json' -or
      -not (Test-Path -LiteralPath $sourceZvzTheoryWorkingPointPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $sourceZvzTheoryWorkingPointPath -Algorithm SHA256).Hash -ne
      $frozenArguments.source_zvz_theory_working_point_sha256) {
    throw 'Plan-bound source theory working point is missing or stale.'
  }
  $sourceZvzTheoryWorkingPoint = Get-Content -LiteralPath `
    $sourceZvzTheoryWorkingPointPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceZvzTheoryWorkingPoint.role -ne 'rf_oatof_theory_working_point' -or
      $sourceZvzTheoryWorkingPoint.policy_id -ne
      'source_zvz_three_zone_theory_working_point_v1' -or
      $sourceZvzTheoryWorkingPoint.source_state_sha256 -ne
      $sourceZvzAffineReceipt.source_state.sha256 -or
      $sourceZvzTheoryWorkingPoint.resolved_geometry_input_sha256 -ne
      $frozenArguments.source_zvz_theory_geometry_input_sha256) {
    throw 'Plan-bound source theory working point identity differs.'
  }
}
$prePulseTimeSeriesPrefixPath = $null
$prePulseTimeSeriesContractPath = $null
if ($prePulseTimeSeriesScreening) {
  $prePulseTimeSeriesPrefixBinding = [string]$frozenArguments.pre_pulse_time_series_prefix_filename
  $prePulseTimeSeriesPrefixPath = [IO.Path]::GetFullPath((Join-Path `
    $(if ($prePulseTimeSeriesPrefixBinding.StartsWith('artifacts/')) {
      $workspaceRoot
    } else { $runDirectory }) $prePulseTimeSeriesPrefixBinding))
  $prePulseTimeSeriesContractPath = [IO.Path]::GetFullPath((Join-Path $runDirectory `
    $frozenArguments.pre_pulse_time_series_contract_filename))
  $inputsRoot = (Join-Path $runDirectory 'inputs') +
    [IO.Path]::DirectorySeparatorChar
  $artifactsRoot = (Join-Path $workspaceRoot 'artifacts') +
    [IO.Path]::DirectorySeparatorChar
  $pulseTimingDiscoveryAuthority = $pulseTimingDiscovery -or
    $pulseTimingDiscoveryRequired
  $expectedTimeSeriesPrefix = if ($pulseTimingDiscoveryAuthority) {
    $prePulseTimeSeriesPrefixBinding
  } else { 'inputs/pre_pulse_time_series_screening_prefix_n100.csv' }
  if ([IO.Path]::IsPathRooted($prePulseTimeSeriesPrefixBinding) -or
      $prePulseTimeSeriesPrefixBinding -ne
        $expectedTimeSeriesPrefix -or
      $frozenArguments.pre_pulse_time_series_contract_filename -ne
        'inputs/pre_pulse_time_series_screening_contract.json' -or
      (-not $prePulseTimeSeriesPrefixPath.StartsWith(
        $inputsRoot,[StringComparison]::OrdinalIgnoreCase) -and
       -not ($pulseTimingDiscoveryAuthority -and
         $prePulseTimeSeriesPrefixPath.StartsWith(
           $artifactsRoot,[StringComparison]::OrdinalIgnoreCase))) -or
      -not $prePulseTimeSeriesContractPath.StartsWith(
        $inputsRoot,[StringComparison]::OrdinalIgnoreCase) -or
      -not (Test-Path -LiteralPath $prePulseTimeSeriesPrefixPath -PathType Leaf) -or
      -not (Test-Path -LiteralPath $prePulseTimeSeriesContractPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $prePulseTimeSeriesPrefixPath -Algorithm SHA256).Hash -ne
        $frozenArguments.pre_pulse_time_series_prefix_sha256 -or
      (Get-FileHash -LiteralPath $prePulseTimeSeriesContractPath -Algorithm SHA256).Hash -ne
        $frozenArguments.pre_pulse_time_series_contract_sha256 -or
      [int]$frozenArguments.pre_pulse_time_series_prefix_count -ne
        [int]$experiment.single_flight_population.execution_population.particle_count -or
      @(Import-Csv -LiteralPath $prePulseTimeSeriesPrefixPath).Count -ne
        [int]$frozenArguments.pre_pulse_time_series_prefix_count) {
    throw 'Plan-bound pre-pulse time-series inputs are missing or stale.'
  }
}
$pulseCandidateConfirmationPrefixPath = $null
if ($pulseCandidateConfirmation) {
  $pulseCandidateConfirmationPrefixBinding = [string]$frozenArguments.pulse_candidate_confirmation_prefix_filename
  $pulseCandidateConfirmationPrefixPath = [IO.Path]::GetFullPath((Join-Path `
    $(if ($pulseCandidateConfirmationPrefixBinding.StartsWith('artifacts/')) {
      $workspaceRoot
    } else { $runDirectory }) $pulseCandidateConfirmationPrefixBinding))
  $inputsRoot = (Join-Path $runDirectory 'inputs') +
    [IO.Path]::DirectorySeparatorChar
  $artifactsRoot = (Join-Path $workspaceRoot 'artifacts') +
    [IO.Path]::DirectorySeparatorChar
  $expectedConfirmationPrefix = if ($pulseTimingConfirmation) {
    $pulseCandidateConfirmationPrefixBinding
  } else { 'inputs/pulse_candidate_confirmation_prefix_n100.csv' }
  if ([IO.Path]::IsPathRooted($pulseCandidateConfirmationPrefixBinding) -or
      $pulseCandidateConfirmationPrefixBinding -ne
        $expectedConfirmationPrefix -or
      (-not $pulseCandidateConfirmationPrefixPath.StartsWith(
        $inputsRoot,[StringComparison]::OrdinalIgnoreCase) -and
       -not ($pulseTimingConfirmation -and
         $pulseCandidateConfirmationPrefixPath.StartsWith(
           $artifactsRoot,[StringComparison]::OrdinalIgnoreCase))) -or
      -not (Test-Path -LiteralPath $pulseCandidateConfirmationPrefixPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $pulseCandidateConfirmationPrefixPath -Algorithm SHA256).Hash -ne
        $frozenArguments.pulse_candidate_confirmation_prefix_sha256 -or
      [int]$frozenArguments.pulse_candidate_confirmation_prefix_count -ne
        [int]$experiment.single_flight_population.execution_population.particle_count -or
      @(Import-Csv -LiteralPath $pulseCandidateConfirmationPrefixPath).Count -ne
        [int]$frozenArguments.pulse_candidate_confirmation_prefix_count) {
    throw 'Plan-bound pulse candidate confirmation prefix is missing or stale.'
  }
}
$resolvedSourceContractPath = [IO.Path]::GetFullPath(
  (Join-Path $runDirectory $frozenArguments.resolved_source_contract_filename)
)
$resolvedBudgetPath = [IO.Path]::GetFullPath(
  (Join-Path $runDirectory $frozenArguments.resolved_budget_filename)
)
$upstreamResolvedDesignPath = [IO.Path]::GetFullPath(
  (Join-Path $runDirectory $frozenArguments.upstream_resolved_design_filename)
)
$resolvedOatofGeometryPath = $null
$resolvedPulseSchedulePath = $null
$resolvedPopulationContractPath = $null
if ([int]$campaign.schema_version -ge 3) {
  $resolvedOatofGeometryPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.resolved_oatof_geometry_filename)
  )
  $hasPulseSchedule = $frozenArguments.ContainsKey(
    'resolved_single_flight_pulse_schedule_filename'
  )
  if ($hasPulseSchedule) {
    $resolvedPulseSchedulePath = [IO.Path]::GetFullPath(
      (Join-Path $runDirectory $frozenArguments.resolved_single_flight_pulse_schedule_filename)
    )
  }
  $resolvedPopulationContractPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.resolved_population_contract_filename)
  )
  $layoutRegistryPath = Join-Path $integrationRoot 'config\single_flight_layout_profiles.json'
  $declaredArchitectureGeneration = if (
    $experiment.PSObject.Properties.Name -contains 'architecture_generation_id'
  ) { [string]$experiment.architecture_generation_id } else {
    [string]$frozenArguments.architecture_generation_id
  }
  if ([string]$experiment.single_flight_layout_profile_id -ne
      [string]$frozenArguments.layout_profile_id -or
      $declaredArchitectureGeneration -ne
        [string]$frozenArguments.architecture_generation_id -or
      $frozenArguments.resolved_oatof_geometry_filename -ne 'resolved_oatof_geometry.json' -or
      -not (Test-Path -LiteralPath $resolvedOatofGeometryPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $resolvedOatofGeometryPath -Algorithm SHA256).Hash -ne
        $frozenArguments.resolved_oatof_geometry_sha256 -or
      ($hasPulseSchedule -and (
        $frozenArguments.resolved_single_flight_pulse_schedule_filename -ne
          'resolved_single_flight_pulse_schedule.json' -or
        -not (Test-Path -LiteralPath $resolvedPulseSchedulePath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $resolvedPulseSchedulePath -Algorithm SHA256).Hash -ne
          $frozenArguments.resolved_single_flight_pulse_schedule_sha256)) -or
      $frozenArguments.resolved_population_contract_filename -ne
        'resolved_population_contract.json' -or
      -not (Test-Path -LiteralPath $resolvedPopulationContractPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $resolvedPopulationContractPath -Algorithm SHA256).Hash -ne
        $frozenArguments.resolved_population_contract_sha256 -or
      (Get-FileHash -LiteralPath $layoutRegistryPath -Algorithm SHA256).Hash -ne
        $frozenArguments.single_flight_layout_registry_sha256) {
    throw 'Prepared single-flight layout or pulse schedule is missing or stale.'
  }
  if (-not $hasPulseSchedule) {
    throw 'Single-flight source release requires a pulse schedule.'
  }
  $geometryDocument = Get-Content -LiteralPath $resolvedOatofGeometryPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ([string]$geometryDocument.single_flight_layout_derivation.layout_profile_id -ne
        [string]$frozenArguments.layout_profile_id -or
      [string]$geometryDocument.single_flight_layout_derivation.architecture_generation_id -ne
        [string]$frozenArguments.architecture_generation_id -or
      [double]$geometryDocument.geometry_mm.bore_r -ne
        [double]$frozenArguments.resolved_oatof_bore_radius_mm -or
      [double]$geometryDocument.geometry_mm.ring_outer_r -ne
        [double]$frozenArguments.resolved_oatof_ring_outer_radius_mm -or
      [double]$geometryDocument.geometry_mm.flight_tube_r -ne
        [double]$frozenArguments.resolved_oatof_shield_inner_radius_mm) {
    throw 'Prepared oaTOF geometry identity differs.'
  }
  $resolvedPopulation = Get-Content -LiteralPath $resolvedPopulationContractPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($resolvedPopulation.role -ne 'rf_oatof_resolved_population_contract' -or
      $resolvedPopulation.campaign_id -ne $campaign.campaign_id -or
      $resolvedPopulation.experiment_id -ne $experiment.experiment_id -or
      $resolvedPopulation.experiment_row_sha256 -ne
        $frozenArguments.experiment_row_sha256 -or
      [string]$resolvedPopulation.execution_strategy -ne $executionStrategy -or
      [string]$resolvedPopulation.source_release_mode -ne
        [string]$frozenArguments.source_release_mode) {
    throw 'Prepared resolved population contract identity differs.'
  }
}
if ($frozenArguments.resolved_source_contract_filename -ne
      'resolved_source_contract.json' -or
    -not (Test-Path -LiteralPath $resolvedSourceContractPath -PathType Leaf) -or
    (Get-FileHash -LiteralPath $resolvedSourceContractPath -Algorithm SHA256).Hash -ne
      $frozenArguments.resolved_source_contract_sha256) {
  throw 'Prepared resolved source contract is missing or stale.'
}
if ($frozenArguments.resolved_budget_filename -ne
      'resolved_engineering_budget.json' -or
    -not (Test-Path -LiteralPath $resolvedBudgetPath -PathType Leaf) -or
    (Get-FileHash -LiteralPath $resolvedBudgetPath -Algorithm SHA256).Hash -ne
      $frozenArguments.resolved_budget_sha256) {
  throw 'Prepared family engineering budget is missing or stale.'
}
if ($frozenArguments.upstream_resolved_design_filename -ne
      'upstream_resolved_design.json' -or
    -not $upstreamResolvedDesignPath.StartsWith(
      $runDirectory + [IO.Path]::DirectorySeparatorChar,
      [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not (Test-Path -LiteralPath $upstreamResolvedDesignPath -PathType Leaf) -or
    (Get-FileHash -LiteralPath $upstreamResolvedDesignPath -Algorithm SHA256).Hash -ne
      $frozenArguments.upstream_resolved_design_sha256) {
  throw 'Upstream resolved design is outside the workspace, missing or stale.'
}

$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repo `
  -ResolvedConnection $ResolvedConnection `
  -RuntimeBinding $runtimeBinding `
  -ExpectedConnectionProfileId $plan.selection.connection_profile_id `
  -SourceBranchId $sourceBranchId `
  -ResolvedSourceContract $resolvedSourceContractPath `
  -ResolvedSourceContractSha256 $frozenArguments.resolved_source_contract_sha256 `
  -UpstreamResolvedDesign $upstreamResolvedDesignPath `
  -UpstreamResolvedDesignSha256 $frozenArguments.upstream_resolved_design_sha256
$budget = Get-Content -LiteralPath $resolvedBudgetPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$executionPolicy = Get-Content `
  -LiteralPath $runtime.contracts.execution_policy_contract `
  -Raw -Encoding UTF8 | ConvertFrom-Json
$runtimeLaunchedCount = if (
  $runtime.source_record.PSObject.Properties.Name -contains
    'launched_particle_count'
) { [int]$runtime.source_record.launched_particle_count } else {
  [int]$runtime.source_record.particle_count
}
$expectedExecutionParticleCount = if ($executionStrategy -eq 'simion_single_flight') {
  [int]$resolvedPopulation.execution_population.particle_count
} else { [int]$runtime.source_record.particle_count }
$sourceBudgetIdentityDiffers =
  $budget.source_identity.solver_id -ne $runtime.source_identity.solver_id -or
  $budget.source_identity.run_id -ne $runtime.source_identity.run_id -or
  $budget.source_identity.project_id -ne $runtime.source_identity.project_id -or
  $budget.source_identity.manifest_sha256 -ne
    $runtime.source_identity.manifest_sha256 -or
  $budget.source_identity.event_sha256 -ne
    $runtime.source_identity.event_sha256 -or
  $budget.source_identity.particle_source_sha256 -ne
    $runtime.source_identity.particle_source_sha256 -or
  $budget.source_identity.metadata_sha256 -ne
    $runtime.source_identity.metadata_sha256
if ($budget.role -ne 'integration_resolved_engineering_budget' -or
    $budget.integration_id -ne $plan.integration_id -or
    $budget.connection_profile_id -ne
      $plan.selection.connection_profile_id -or
    $budget.campaign_id -ne $frozenArguments.campaign_id -or
    $budget.experiment_id -ne $frozenArguments.experiment_id -or
    $budget.experiment_row_sha256 -ne
      $frozenArguments.experiment_row_sha256 -or
    $budget.policy_id -ne $executionPolicy.policy_id -or
    $budget.source_identity.source_branch_id -ne $sourceBranchId -or
    $budget.source_identity.project_id -ne
      $resolved.selection.upstream_project_id -or
    $sourceBudgetIdentityDiffers -or
    [int]$budget.launched_particle_count -ne $expectedExecutionParticleCount -or
    [int]$budget.particle_count -ne $expectedExecutionParticleCount -or
    $budget.execution_strategy -ne $executionStrategy -or
    ($executionStrategy -eq 'simion_single_flight' -and (
      [string]$budget.single_flight_pa_cache_policy -ne
        [string]$frozenArguments.single_flight_pa_cache_policy -or
      [string]$budget.single_flight_pa_cache_policy_provenance -ne
        [string]$frozenArguments.single_flight_pa_cache_policy_provenance)) -or
    $budget.retention_class -ne 'compact') {
  throw 'Campaign budget and runtime source identities differ before stage 1.'
}
$runtime.source_identity = Resolve-RfObservedPrePulseSourceIdentity `
  -Experiment $experiment -BudgetSourceIdentity $budget.source_identity

if ($PrepareOnly) {
  Write-Output (
    'FAMILY_SOURCE_CLOSURE_ADAPTER=PREPARED ' +
    "CAMPAIGN=$($campaign.campaign_id) EXPERIMENT=$($experiment.experiment_id)"
  )
  exit 0
}
if ([string]$campaign.status -ne 'authorized') {
  throw 'Campaign status permits validation only and cannot execute a solver.'
}
if (-not $SolverAuthorized) {
  throw 'Family source-closure execution requires explicit solver authorization.'
}
$expectedRunId = [string]$experiment.run_id
if ($pulseTimingDiscovery) {
  if ($expectedRunId -notmatch
      '^(?<stamp>[0-9]{8}_[0-9]{6})__.+__(?<detail>n[0-9]+)(?<retry>__r[0-9]{2})?$') {
    throw 'Automatic pulse-timing target RunId cannot derive a discovery RunId.'
  }
  $expectedRunId = (
    $Matches.stamp + '__sim__cross__pulse-timing-discovery__' +
    $Matches.detail + [string]$Matches['retry']
  )
}
if ($expectedRunId -ne $RunId) {
  $recoveryMatch = [regex]::Match($RunId, ('^' +
    [regex]::Escape($expectedRunId) + '__r(?<index>[0-9]{2})$'))
  $recoveryParentRunId = ''
  if ($recoveryMatch.Success -and [int]$recoveryMatch.Groups['index'].Value -ge 1) {
    $recoveryIndex = [int]$recoveryMatch.Groups['index'].Value
    $recoveryParentRunId = if ($recoveryIndex -eq 1) {
      $expectedRunId
    } else {
      $expectedRunId + ('__r{0:D2}' -f ($recoveryIndex - 1))
    }
  }
  $recoveryParentDirectory = [IO.Path]::GetFullPath((Join-Path (
    Join-Path $workspaceRoot ('artifacts\projects\' + $plan.integration_id + '\runs')
  ) $recoveryParentRunId))
  $recoveryParentManifest = Join-Path $recoveryParentDirectory 'run_manifest.json'
  $recoveryParentStatus = ''
  if (Test-Path -LiteralPath $recoveryParentManifest -PathType Leaf) {
    $recoveryParentStatus = [string]((Get-Content `
      -LiteralPath $recoveryParentManifest -Raw | ConvertFrom-Json).status)
  }
  $isFailedRecovery = $recoveryMatch.Success -and
    $recoveryParentStatus -eq 'failed'
  if (-not $isFailedRecovery) {
    throw 'Solver-authorized RunId differs from the campaign row.'
  }
}
$runsRoot = Join-Path $workspaceRoot (
  'artifacts\projects\' + $plan.integration_id + '\runs'
)
$expectedRunDirectory = [IO.Path]::GetFullPath((Join-Path $runsRoot $RunId))
if (-not $runDirectory.Equals(
    $expectedRunDirectory,
    [StringComparison]::OrdinalIgnoreCase
  )) {
  throw 'Family execution directory must be the canonical parent run.'
}

$runnerArguments = @{
  ConnectionProfileId = $plan.selection.connection_profile_id
  ResolvedConnection = $ResolvedConnection
  ResolvedEngineeringBudget = $resolvedBudgetPath
  RuntimeBinding = $runtimeBinding
  SourceBranchId = $sourceBranchId
  ResolvedSourceContract = $resolvedSourceContractPath
  ResolvedSourceContractSha256 = $frozenArguments.resolved_source_contract_sha256
  UpstreamResolvedDesign = $upstreamResolvedDesignPath
  UpstreamResolvedDesignSha256 = $frozenArguments.upstream_resolved_design_sha256
  PythonExe = $PythonExe
}
$retrySuffix = if ($RunId -match '(__r\d{2})$') { $Matches[1] } else { '' }
if ($executionStrategy -eq 'simion_single_flight') {
  if ($null -eq $resolved.connector -or
      $null -eq $resolved.connector.length_mm) {
    throw 'Resolved connector length is missing for single-flight run identity.'
  }
  $connectorGapMm = [double]$resolved.connector.length_mm
  if ([double]::IsNaN($connectorGapMm) -or
      [double]::IsInfinity($connectorGapMm) -or
      $connectorGapMm -lt 0.0) {
    throw 'Resolved connector length is invalid for single-flight run identity.'
  }
  $connectorGapLabel = $connectorGapMm.ToString(
    '0.###############',
    [Globalization.CultureInfo]::InvariantCulture
  ).Replace('.', 'p')
  $singleFlightRole = if ($pulseTimingDiscovery) {
    'rf-oatof-pulse-screen'
  } else {
    'rf-oatof-single-flight'
  }
  $singleFlightRunId = "$($RunId.Substring(0, 15))__sim__simion__$singleFlightRole-gap$connectorGapLabel`__n$expectedExecutionParticleCount$retrySuffix"
  $runnerArguments.RunId = $singleFlightRunId
  $runnerArguments.PaCachePolicy =
    [string]$frozenArguments.single_flight_pa_cache_policy
  $runnerArguments.PaCachePolicyProvenance =
    [string]$frozenArguments.single_flight_pa_cache_policy_provenance
  if ($null -ne $paCacheGenerationBindingPath) {
    $runnerArguments.RequiredPaCacheGenerationBinding = $paCacheGenerationBindingPath
    $runnerArguments.RequiredPaCacheGenerationBindingSha256 =
      [string]$frozenArguments.single_flight_pa_cache_generation_binding_sha256
  }
  # Preparation resolves the effective count, including automatic memory
  # selection.  The frozen plan argument is the sole execution authority;
  # comparing it with the optional static campaign hint would reject a valid
  # memory-bound decision.
  $resolvedBatchCount = [int]$frozenArguments.single_flight_batch_count
  $dispatchPlan = $budget.single_flight_dispatch_plan
  if ($null -eq $dispatchPlan -or
      $null -eq $dispatchPlan.waves -or
      @($dispatchPlan.waves).Count -ne 1 -or
      [int]$dispatchPlan.waves[0].batch_count -ne $resolvedBatchCount) {
    throw 'Resolved dispatch plan and prepared single-flight batch count differ.'
  }
  if ($resolvedBatchCount -lt 1 -or
      $resolvedBatchCount -gt $expectedExecutionParticleCount) {
    throw 'Prepared single-flight batch count is invalid or exceeds the resolved population.'
  }
  $runnerArguments.ExecutionBatchCount = $resolvedBatchCount
  if ([int]$campaign.schema_version -ge 3) {
    $runnerArguments.OatofResolvedGeometry = $resolvedOatofGeometryPath
    if ($null -ne $resolvedPulseSchedulePath) {
      $runnerArguments.PulseSchedule = $resolvedPulseSchedulePath
    }
    $runnerArguments.ResolvedPopulationContract = $resolvedPopulationContractPath
    $runnerArguments.ResolvedPopulationContractSha256 =
      $frozenArguments.resolved_population_contract_sha256
    $runnerArguments.LayoutProfileId = [string]$frozenArguments.layout_profile_id
    $runnerArguments.ArchitectureGenerationId =
      [string]$frozenArguments.architecture_generation_id
    $runnerArguments.ExpectedBoreRadiusMm =
      [double]$frozenArguments.resolved_oatof_bore_radius_mm
    $runnerArguments.ExpectedRingOuterRadiusMm =
      [double]$frozenArguments.resolved_oatof_ring_outer_radius_mm
    $runnerArguments.ExpectedShieldInnerRadiusMm =
      [double]$frozenArguments.resolved_oatof_shield_inner_radius_mm
    if ($campaignHasThreeZoneCandidate) {
      $runnerArguments.ThreeZoneCandidate = $threeZoneCandidatePath
      $runnerArguments.ThreeZoneCandidateSha256 =
        [string]$frozenArguments.single_flight_three_zone_candidate_sha256
      if ($null -ne $sourceZvzTheoryWorkingPointPath) {
        $runnerArguments.TheoryWorkingPoint = $sourceZvzTheoryWorkingPointPath
        $runnerArguments.TheoryWorkingPointSha256 =
          [string]$frozenArguments.source_zvz_theory_working_point_sha256
      }
    }
  }
  if ($frozenArguments.ContainsKey('single_flight_frontend_grid_profile_id')) {
    if ([string]$experiment.single_flight_frontend_grid_profile_id -ne
        [string]$frozenArguments.single_flight_frontend_grid_profile_id) {
      throw 'Single-flight frontend grid profile changed after preparation.'
    }
    $runnerArguments.FrontendGridProfileId =
      [string]$frozenArguments.single_flight_frontend_grid_profile_id
  }
  if ($frozenArguments.ContainsKey('single_flight_oatof_numerical_profile_id')) {
    if ([string]$experiment.single_flight_oatof_numerical_profile_id -ne
        [string]$frozenArguments.single_flight_oatof_numerical_profile_id) {
      throw 'Single-flight oaTOF numerical profile changed after preparation.'
    }
    $runnerArguments.OatofNumericalProfileId =
      [string]$frozenArguments.single_flight_oatof_numerical_profile_id
  }
  if ($frozenArguments.ContainsKey('single_flight_trajectory_quality_profile_id')) {
    if ([string]$experiment.single_flight_trajectory_quality_profile_id -ne
        [string]$frozenArguments.single_flight_trajectory_quality_profile_id) {
      throw 'Single-flight trajectory-quality profile changed after preparation.'
    }
    $runnerArguments.TrajectoryQualityProfileId =
      [string]$frozenArguments.single_flight_trajectory_quality_profile_id
  }
  if ($frozenArguments.ContainsKey('single_flight_time_integration_profile_id')) {
    if ([string]$experiment.single_flight_time_integration_profile_id -ne
        [string]$frozenArguments.single_flight_time_integration_profile_id) {
      throw 'Single-flight time-integration profile changed after preparation.'
    }
    $runnerArguments.TimeIntegrationProfileId =
      [string]$frozenArguments.single_flight_time_integration_profile_id
  }
  if ($frozenArguments.ContainsKey('single_flight_maximum_time_of_flight_us')) {
    $declaredMaximumTofUs = [double]$experiment.single_flight_maximum_time_of_flight_us
    $frozenMaximumTofUs = [double]$frozenArguments.single_flight_maximum_time_of_flight_us
    if ([double]::IsNaN($declaredMaximumTofUs) -or
        [double]::IsInfinity($declaredMaximumTofUs) -or
        $declaredMaximumTofUs -le 0 -or
        $declaredMaximumTofUs -ne $frozenMaximumTofUs) {
      throw 'Single-flight maximum time of flight changed after preparation or is invalid.'
    }
    $runnerArguments.MaximumTimeOfFlightUs = $declaredMaximumTofUs
  }
  if ($frozenArguments.ContainsKey('single_flight_spatial_window_profile_id')) {
    if ([string]$experiment.single_flight_spatial_window_profile_id -ne
        [string]$frozenArguments.single_flight_spatial_window_profile_id) {
      throw 'Single-flight spatial-window profile changed after preparation.'
    }
    $runnerArguments.SpatialWindowProfileId =
      [string]$frozenArguments.single_flight_spatial_window_profile_id
  }
  if ($frozenArguments.ContainsKey('source_release_mode')) {
    if ($frozenArguments.ContainsKey('source_profile_id')) {
      $runnerArguments.SourceProfileId = [string]$frozenArguments.source_profile_id
      $runnerArguments.FieldOverlayId = [string]$frozenArguments.field_overlay_id
    }
    if ($null -ne $prePulseSourceStatePath) {
      $runnerArguments.PrePulseSourceState = $prePulseSourceStatePath
      $runnerArguments.PrePulseSourceStateSha256 =
        [string]$frozenArguments.pre_pulse_source_state_sha256
      $runnerArguments.PrePulseSourceStateCount =
        [int]$frozenArguments.pre_pulse_source_state_count
      if ($null -ne $prePulseRestartValidationPath) {
        $runnerArguments.PrePulseRestartPositionToleranceMm =
          [double]$frozenArguments.pre_pulse_restart_position_tolerance_mm
        $runnerArguments.PrePulseRestartVelocityToleranceMPerS =
          [double]$frozenArguments.pre_pulse_restart_velocity_tolerance_m_per_s
        $runnerArguments.PrePulseRestartClockToleranceUs =
          [double]$frozenArguments.pre_pulse_restart_clock_tolerance_us
        $runnerArguments.PrePulseRestartEnergyToleranceEv =
          [double]$frozenArguments.pre_pulse_restart_energy_tolerance_eV
        $runnerArguments.PrePulseRestartValidation = $prePulseRestartValidationPath
        $runnerArguments.PrePulseRestartValidationSha256 =
          [string]$frozenArguments.pre_pulse_restart_validation_sha256
      }
    }
  }
  if ($null -ne $singleFlightParticleSourcePath -and
      $frozenArguments.source_release_mode -eq 'continuous_frontend') {
    $runnerArguments.MotherParticleSource = $singleFlightParticleSourcePath
    $runnerArguments.MotherParticleSourceSha256 = $frozenArguments.single_flight_particle_source_sha256
    $runnerArguments.MotherParticleCount = [int]$frozenArguments.single_flight_particle_source_count
    if ($frozenArguments.ContainsKey('single_flight_materialization_receipt_filename')) {
      $runnerArguments.MotherParticleSourceReceipt = $materializationReceiptPath
      $runnerArguments.MotherParticleSourceReceiptSha256 =
        $frozenArguments.single_flight_materialization_receipt_sha256
    }
  }
  if ($null -eq $resolvedRegionFieldContractPath) {
    throw 'SIMION single flight requires one resolved region field contract.'
  }
  $runnerArguments.ResolvedRegionFieldContract = $resolvedRegionFieldContractPath
  $runnerArguments.ResolvedRegionFieldContractSha256 =
    $frozenArguments.resolved_region_field_contract_sha256
  $runnerArguments.ResolvedRegionFieldSemanticSha256 =
    $frozenArguments.resolved_region_field_semantic_sha256
  $preparedPrefixPath = if ($pulseTimingDiscovery) {
    $prePulseTimeSeriesPrefixPath
  } elseif ($pulseTimingConfirmation) {
    $pulseCandidateConfirmationPrefixPath
  } elseif ($prePulseTimeSeriesScreening) {
    $prePulseTimeSeriesPrefixPath
  } else { $null }
  if ($null -ne $preparedPrefixPath) {
    $runnerArguments.MotherParticleSource = $preparedPrefixPath
    $runnerArguments.MotherParticleSourceRunRoot = $runDirectory
    if ($preparedPrefixPath.StartsWith(
        (Join-Path $workspaceRoot 'artifacts') +
          [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      )) {
      $runnerArguments.MotherParticleSourceRunRoot = $workspaceRoot
    }
    $runnerArguments.MotherParticleSourceSha256 = if ($pulseCandidateConfirmation) {
      $frozenArguments.pulse_candidate_confirmation_prefix_sha256
    } else {
      $frozenArguments.pre_pulse_time_series_prefix_sha256
    }
    $runnerArguments.MotherParticleCount = @(
      Import-Csv -LiteralPath $preparedPrefixPath
    ).Count
  }
  if ($prePulseTimeSeriesScreening) {
    $screeningTimeIntegrationProfileId =
      [string]$frozenArguments.pre_pulse_time_series_time_integration_profile_id
    $screeningContract = Get-Content -LiteralPath $prePulseTimeSeriesContractPath `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$screeningContract.identities.time_integration_profile_id -ne
        $screeningTimeIntegrationProfileId) {
      throw 'Pre-pulse time-series solver time-integration identity differs.'
    }
    $runnerArguments.TimeIntegrationProfileId = $screeningTimeIntegrationProfileId
    $runnerArguments.PrePulseTimeSeriesContract =
      $prePulseTimeSeriesContractPath
    $runnerArguments.PrePulseTimeSeriesContractSha256 =
      $frozenArguments.pre_pulse_time_series_contract_sha256
  }
  & $runtime.implementation.single_flight_runner @runnerArguments
} else {
  $runnerArguments.Stamp = $RunId.Substring(0, 15)
  & $runtime.implementation.transfer_runner @runnerArguments
}
if ($LASTEXITCODE -ne 0) {
  throw "Family mapped RF-to-oaTOF $executionStrategy execution failed."
}
if ($executionStrategy -eq 'simion_single_flight') {
  $singleFlightRunsRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' + $plan.integration_id + '\runs'
  )
  $singleFlightManifestPath = Join-Path (
    Join-Path $singleFlightRunsRoot $singleFlightRunId
  ) 'run_manifest.json'
  if (-not (Test-Path -LiteralPath $singleFlightManifestPath -PathType Leaf)) {
    throw 'New single-flight output must publish under the integration project.'
  }
  $singleFlightManifest = Get-Content -LiteralPath $singleFlightManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($singleFlightManifest.role -ne 'simulation_run_manifest' -or
      $singleFlightManifest.run_id -ne $singleFlightRunId -or
      $singleFlightManifest.project -ne $plan.integration_id -or
      $singleFlightManifest.mode -ne 'rf_to_oatof_simion_single_flight') {
    throw 'New single-flight output ownership identity differs.'
  }
}

$stageParticleCount = [int]$budget.particle_count
$runtimeBindingSha256 = (
  Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256
).Hash
$receipt = [ordered]@{
  schema_version = 1
  role = 'integration_family_source_closure_execution_receipt'
  integration_run_id = $RunId
  campaign_path = $frozenArguments.campaign_path
  campaign_sha256 = $frozenArguments.campaign_sha256
  campaign_id = $frozenArguments.campaign_id
  experiment_id = $frozenArguments.experiment_id
  experiment_row_sha256 = $frozenArguments.experiment_row_sha256
  execution_strategy = $executionStrategy
  single_flight_pa_cache_policy = if (
    $executionStrategy -eq 'simion_single_flight'
  ) { [string]$frozenArguments.single_flight_pa_cache_policy } else { $null }
  single_flight_pa_cache_policy_provenance = if (
    $executionStrategy -eq 'simion_single_flight'
  ) { [string]$frozenArguments.single_flight_pa_cache_policy_provenance } else { $null }
  connection_profile_id = $plan.selection.connection_profile_id
  source_branch_id = $sourceBranchId
  source_identity = $budget.source_identity
  launched_particle_count = [int]$budget.launched_particle_count
  particle_count = [int]$budget.particle_count
  policy_id = $budget.policy_id
  retention_class = $budget.retention_class
  composition_plan_sha256 =
    (Get-FileHash -LiteralPath $CompositionPlan -Algorithm SHA256).Hash
  resolved_connection_sha256 =
    (Get-FileHash -LiteralPath $ResolvedConnection -Algorithm SHA256).Hash
  resolved_engineering_budget_sha256 =
    (Get-FileHash -LiteralPath $resolvedBudgetPath -Algorithm SHA256).Hash
  resolved_source_contract_filename =
    $frozenArguments.resolved_source_contract_filename
  resolved_source_contract_sha256 =
    $frozenArguments.resolved_source_contract_sha256
  resolved_population_contract_filename = if ($executionStrategy -eq 'simion_single_flight') {
    $frozenArguments.resolved_population_contract_filename
  } else { $null }
  resolved_population_contract_sha256 = if ($executionStrategy -eq 'simion_single_flight') {
    $frozenArguments.resolved_population_contract_sha256
  } else { $null }
  upstream_resolved_design_filename =
    $frozenArguments.upstream_resolved_design_filename
  upstream_resolved_design_sha256 =
    $frozenArguments.upstream_resolved_design_sha256
  runtime_binding_sha256 = $runtimeBindingSha256
  stage_run_ids = if ($executionStrategy -eq 'simion_single_flight') { [ordered]@{
    single_flight_transport = $singleFlightRunId
  } } else { [ordered]@{
    pre_pulse_interface_transport =
      "$($RunId.Substring(0, 15))__sim__comsol__rf-oatof-pre-pulse-interface-gap0__n$stageParticleCount$retrySuffix"
    pulse_capture =
      "$($RunId.Substring(0, 15))__sim__comsol__rf-oatof-pulse-capture-gap0__n$stageParticleCount$retrySuffix"
    analyzer_transport =
      "$($RunId.Substring(0, 15))__sim__cross__rf-oatof-analyzer-transport-gap0__n$stageParticleCount$retrySuffix"
  } }
  stage_runtime_binding_sha256s = if ($executionStrategy -eq 'simion_single_flight') { [ordered]@{
    single_flight_transport = $runtimeBindingSha256
  } } else { [ordered]@{
    pre_pulse_interface_transport = $runtimeBindingSha256
    pulse_capture = $runtimeBindingSha256
    analyzer_transport = $runtimeBindingSha256
  } }
  execution_status = 'completed_pending_paired_analysis'
  claim_status = 'FUNCTIONAL_SCREEN_ONLY'
}
$receiptPath = Join-Path $runDirectory 'execution_receipt.json'
$receipt | ConvertTo-Json -Depth 6 |
  Set-Content -LiteralPath $receiptPath -Encoding UTF8

$publisherModule = (
  'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
  'workflows.family_source_closure.publish_run'
)
Push-Location -LiteralPath $repo
try {
  & $PythonExe -m $publisherModule `
    --repo-root $repo `
    --integration-run-dir $runDirectory `
    --receipt $receiptPath `
    --resolved-connection $ResolvedConnection `
    --composition-plan $CompositionPlan `
    --resolved-engineering-budget $resolvedBudgetPath
  if ($LASTEXITCODE -ne 0) {
    throw 'Family source-closure parent run publication failed.'
  }
} finally {
  Pop-Location
}
Write-Output (
  'FAMILY_SOURCE_CLOSURE_ADAPTER=EXECUTED ' +
  "RUN_ID=$RunId CAMPAIGN=$($campaign.campaign_id) " +
  "EXPERIMENT=$($experiment.experiment_id)"
)
