[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CompositionPlan,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$PythonExe,
  [Parameter(Mandatory)][string]$RepoRoot,
  [string]$RunId = '',
  [switch]$PrepareOnly,
  [switch]$SolverAuthorized
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$workflowRoot = $PSScriptRoot
$integrationRoot = (Resolve-Path (Join-Path $workflowRoot '..\..')).Path
$registryPath = Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
. (Join-Path $integrationRoot 'runtime\runtime_binding.ps1')
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
$layoutArgumentNames = @(
  'layout_profile_id',
  'architecture_generation_id',
  'resolved_oatof_geometry_filename',
  'resolved_oatof_geometry_sha256',
  'resolved_oatof_bore_radius_mm',
  'resolved_oatof_ring_outer_radius_mm',
  'resolved_oatof_shield_inner_radius_mm',
  'resolved_single_flight_pulse_schedule_filename',
  'resolved_single_flight_pulse_schedule_sha256',
  'resolved_population_contract_filename',
  'resolved_population_contract_sha256',
  'single_flight_layout_registry_sha256'
)
if ($frozenArguments.ContainsKey('layout_profile_id')) {
  $expectedArguments += $layoutArgumentNames
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
if ($frozenArguments.ContainsKey('pulse_resolution_attribution_arm_id')) {
  $expectedArguments += @(
    'pulse_resolution_attribution_arm_id',
    'pulse_resolution_execution_mode',
    'pulse_resolution_prefix_filename',
    'pulse_resolution_prefix_sha256',
    'pulse_resolution_registration_filename',
    'pulse_resolution_registration_sha256'
  )
  if ($frozenArguments.ContainsKey('pulse_resolution_baseline_checkpoints_path')) {
    $expectedArguments += @(
      'pulse_resolution_baseline_checkpoints_path',
      'pulse_resolution_baseline_checkpoints_sha256'
    )
  }
}
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
$experiments = @($campaign.experiments | Where-Object {
  $_.experiment_id -eq $frozenArguments.experiment_id
})
if ($campaign.role -ne 'rf_multipole_oatof_experiment_campaign' -or
    $campaign.integration_id -ne $plan.integration_id -or
    $campaign.campaign_id -ne $frozenArguments.campaign_id -or
    $experiments.Count -ne 1) {
  throw 'Campaign or experiment identity no longer resolves uniquely.'
}
$experiment = $experiments[0]
if ($SolverAuthorized -and
    [string]$experiment.execution_strategy -eq 'simion_single_flight' -and
    [int]$campaign.schema_version -lt 3) {
  throw 'SolverAuthorized single-flight execution requires a schema-v3 successor campaign.'
}
$pulseN100Screening = $frozenArguments.ContainsKey(
  'pulse_resolution_attribution_arm_id'
)
if ($pulseN100Screening) {
  $pulseContract = $campaign.pulse_resolution_optimization
  $arm = @($pulseContract.attribution_arms | Where-Object {
    $_.arm_id -eq $frozenArguments.pulse_resolution_attribution_arm_id
  })
  $baselineRow = [int]$arm[0].sequence -eq 1 -and
    $arm[0].implementation_status -eq 'executable_registration' -and
    $arm[0].accelerator_field -eq 'all_real' -and
    $experiment.pulse_resolution_execution_mode -eq 'screening_prefix_n100_baseline_registration' -and
    $experiment.single_flight_accelerator_field_profile_id -eq 'accelerator_real_pa'
  $pairedRow = [int]$arm[0].sequence -eq 2 -and
    $arm[0].implementation_status -eq 'executable_paired_screening' -and
    $arm[0].accelerator_field -eq 'ideal_stage1' -and
    $experiment.pulse_resolution_execution_mode -eq 'screening_prefix_n100_paired_candidate' -and
    $experiment.single_flight_accelerator_field_profile_id -eq 'accelerator_ideal_stage1_real_stage2'
  $pairedStage12Row = [int]$arm[0].sequence -eq 3 -and
    $arm[0].implementation_status -eq 'executable_paired_screening' -and
    $arm[0].accelerator_field -eq 'ideal_stage1_stage2' -and
    $experiment.pulse_resolution_execution_mode -eq 'screening_prefix_n100_paired_candidate' -and
    $experiment.single_flight_accelerator_field_profile_id -eq 'accelerator_ideal_stage1_stage2_real_reflectron'
  $pairedAllIdealRow = [int]$arm[0].sequence -eq 4 -and
    $arm[0].implementation_status -eq 'executable_paired_screening_with_full_domain_contract' -and
    $arm[0].accelerator_field -eq 'ideal_accelerator' -and
    $arm[0].reflectron_field -eq 'ideal' -and
    $experiment.pulse_resolution_execution_mode -eq 'screening_prefix_n100_paired_candidate' -and
    $experiment.single_flight_accelerator_field_profile_id -eq 'full_domain_piecewise_ideal_field'
  if ($pulseContract.execution_state -ne 'n100_full_domain_piecewise_ideal_field_screening' -or
      $arm.Count -ne 1 -or -not ($baselineRow -or $pairedRow -or $pairedStage12Row -or $pairedAllIdealRow) -or
      $arm[0].source_model -ne 'real_beam' -or
      $arm[0].reflectron_field -notin @('real','ideal')) {
    throw 'Only real multipole beam + real accelerator field + real reflectron field, deterministic N=100 prefix baseline registration is executable.'
  }
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
    if (-not $frozenArguments.ContainsKey('pre_pulse_source_state_path')) {
      throw 'Pre-pulse restart lacks a frozen source state.'
    }
    if ($frozenArguments.ContainsKey('pre_pulse_restart_validation_filename')) {
      if (
        [double]$experiment.pre_pulse_source_state.position_rowwise_abs_tolerance_mm -ne
          [double]$frozenArguments.pre_pulse_restart_position_tolerance_mm -or
        [double]$experiment.pre_pulse_source_state.velocity_rowwise_abs_tolerance_m_per_s -ne
          [double]$frozenArguments.pre_pulse_restart_velocity_tolerance_m_per_s -or
        [double]$experiment.pre_pulse_source_state.clock_abs_tolerance_us -ne
          [double]$frozenArguments.pre_pulse_restart_clock_tolerance_us -or
        [double]$experiment.pre_pulse_source_state.energy_abs_tolerance_eV -ne
          [double]$frozenArguments.pre_pulse_restart_energy_tolerance_eV
      ) {
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
        [int]$experiment.pre_pulse_source_state.particle_count -ne
          [int]$frozenArguments.pre_pulse_source_state_count) {
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
$pulsePrefixPath = $null
$pulseRegistrationPath = $null
if ($pulseN100Screening) {
  $expectedPulsePrefix = 'inputs/pulse_resolution_arm1_all_real_screening_prefix_n100.csv'
  $pulsePrefixPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.pulse_resolution_prefix_filename)
  )
  if ($frozenArguments.pulse_resolution_prefix_filename -ne $expectedPulsePrefix -or
      -not $pulsePrefixPath.StartsWith(
        (Join-Path $runDirectory 'inputs') + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      ) -or
      -not (Test-Path -LiteralPath $pulsePrefixPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $pulsePrefixPath -Algorithm SHA256).Hash -ne
        $frozenArguments.pulse_resolution_prefix_sha256) {
    throw 'Plan-bound arm 1 screening prefix is outside inputs, missing or stale.'
  }
  $candidateMode = [string]$frozenArguments.pulse_resolution_execution_mode -eq
    'screening_prefix_n100_paired_candidate'
  $expectedRegistration = if ($candidateMode) {
    'inputs/pulse_resolution_baseline_result_reference.json'
  } else {
    'inputs/pulse_resolution_real_beam_real_accelerator_real_reflectron_n100_baseline_registration_authority.json'
  }
  $pulseRegistrationPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.pulse_resolution_registration_filename)
  )
  if ($frozenArguments.pulse_resolution_registration_filename -ne $expectedRegistration -or
      -not $pulseRegistrationPath.StartsWith(
        (Join-Path $runDirectory 'inputs') + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      ) -or -not (Test-Path -LiteralPath $pulseRegistrationPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $pulseRegistrationPath -Algorithm SHA256).Hash -ne
        $frozenArguments.pulse_resolution_registration_sha256) {
    throw 'Plan-bound baseline registration authority is outside inputs, missing or stale.'
  }
  if ($candidateMode) {
    $baselineResultRecord = $experiment.pulse_resolution_baseline_result
    $publishedBaselineResult = [IO.Path]::GetFullPath(
      (Join-Path $workspaceRoot $baselineResultRecord.path)
    )
    $baselineSimionRoot = Split-Path -Parent (Split-Path -Parent $publishedBaselineResult)
    $baselineSimionManifestPath = Join-Path $baselineSimionRoot 'run_manifest.json'
    $baselineCrossManifestPath = Join-Path $workspaceRoot `
      'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs\20260812_210000__sim__cross__pulse-resolution-baseline__n100\run_manifest.json'
    $baselineSimionManifest = Get-Content $baselineSimionManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $baselineCrossManifest = Get-Content $baselineCrossManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $resultOutput = @($baselineSimionManifest.outputs | Where-Object {
      [IO.Path]::GetFullPath([string]$_.path).Equals($publishedBaselineResult,[StringComparison]::OrdinalIgnoreCase)
    })
    if ($baselineSimionManifest.status -ne 'success' -or
        $baselineCrossManifest.status -ne 'success' -or
        $resultOutput.Count -ne 1 -or
        [string]$resultOutput[0].sha256 -ne [string]$baselineResultRecord.sha256 -or
        (Get-FileHash $publishedBaselineResult -Algorithm SHA256).Hash -ne
          [string]$baselineResultRecord.sha256) {
      throw 'Published baseline cross/SIMION result evidence is missing or stale.'
    }
    $baselineReceipt = Get-Content $publishedBaselineResult -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($baselineReceipt.campaign_id -ne $campaign.campaign_id -or
        $baselineReceipt.arm.arm_id -ne 'real_beam_all_real' -or
        $baselineReceipt.source_identity.particle_source_sha256 -ne
          $experiment.source.particle_source.sha256 -or
        $baselineReceipt.prefix.sha256 -ne
          $frozenArguments.pulse_resolution_prefix_sha256 -or
        @($baselineReceipt.prefix.ordered_particle_ids).Count -ne 100) {
      throw 'Published baseline campaign/source/prefix identity differs.'
    }
  }
}
$pulseBaselineCheckpointsPath = $null
if ($frozenArguments.ContainsKey('pulse_resolution_baseline_checkpoints_path')) {
  $pulseBaselineCheckpointsPath = [IO.Path]::GetFullPath(
    (Join-Path $workspaceRoot $frozenArguments.pulse_resolution_baseline_checkpoints_path)
  )
  if (-not $pulseBaselineCheckpointsPath.StartsWith(
        (Join-Path $workspaceRoot 'artifacts') + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      ) -or -not (Test-Path -LiteralPath $pulseBaselineCheckpointsPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $pulseBaselineCheckpointsPath -Algorithm SHA256).Hash -ne
        $frozenArguments.pulse_resolution_baseline_checkpoints_sha256) {
    throw 'Paired baseline checkpoints are outside artifacts, missing or stale.'
  }
  $baselineManifestPath = Join-Path `
    (Split-Path -Parent (Split-Path -Parent $pulseBaselineCheckpointsPath)) `
    'run_manifest.json'
  $baselineManifest = Get-Content $baselineManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $checkpointOutput = @($baselineManifest.outputs | Where-Object {
    [IO.Path]::GetFullPath([string]$_.path).Equals($pulseBaselineCheckpointsPath,[StringComparison]::OrdinalIgnoreCase)
  })
  if ($baselineManifest.status -ne 'success' -or $checkpointOutput.Count -ne 1 -or
      [string]$checkpointOutput[0].sha256 -ne
        $frozenArguments.pulse_resolution_baseline_checkpoints_sha256) {
    throw 'Published baseline checkpoints are not frozen by a successful SIMION manifest.'
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
if ([int]$campaign.schema_version -eq 3) {
  $resolvedOatofGeometryPath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.resolved_oatof_geometry_filename)
  )
  $resolvedPulseSchedulePath = [IO.Path]::GetFullPath(
    (Join-Path $runDirectory $frozenArguments.resolved_single_flight_pulse_schedule_filename)
  )
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
      $frozenArguments.resolved_single_flight_pulse_schedule_filename -ne
        'resolved_single_flight_pulse_schedule.json' -or
      -not (Test-Path -LiteralPath $resolvedPulseSchedulePath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $resolvedPulseSchedulePath -Algorithm SHA256).Hash -ne
        $frozenArguments.resolved_single_flight_pulse_schedule_sha256 -or
      $frozenArguments.resolved_population_contract_filename -ne
        'resolved_population_contract.json' -or
      -not (Test-Path -LiteralPath $resolvedPopulationContractPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $resolvedPopulationContractPath -Algorithm SHA256).Hash -ne
        $frozenArguments.resolved_population_contract_sha256 -or
      (Get-FileHash -LiteralPath $layoutRegistryPath -Algorithm SHA256).Hash -ne
        $frozenArguments.single_flight_layout_registry_sha256) {
    throw 'Prepared single-flight layout or pulse schedule is missing or stale.'
  }
  $geometryDocument = Get-Content -LiteralPath $resolvedOatofGeometryPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ([string]$geometryDocument.single_flight_layout_derivation.architecture_generation_id -ne
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
      $runtime.source_identity.metadata_sha256 -or
    [int]$budget.launched_particle_count -ne $expectedExecutionParticleCount -or
    [int]$budget.particle_count -ne $expectedExecutionParticleCount -or
    $budget.execution_strategy -ne $executionStrategy -or
    [int]$budget.launched_particle_count -ne $expectedExecutionParticleCount -or
    [int]$budget.particle_count -ne $expectedExecutionParticleCount -or
    $budget.retention_class -ne 'compact') {
  throw 'Campaign budget and runtime source identities differ before stage 1.'
}

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
if ($experiment.run_id -ne $RunId) {
  throw 'Solver-authorized RunId differs from the campaign row.'
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
  $singleFlightRunId = "$($RunId.Substring(0, 15))__sim__simion__rf-oatof-single-flight-gap0__n$expectedExecutionParticleCount$retrySuffix"
  $runnerArguments.RunId = $singleFlightRunId
  if ([int]$campaign.schema_version -eq 3) {
    $runnerArguments.OatofResolvedGeometry = $resolvedOatofGeometryPath
    $runnerArguments.PulseSchedule = $resolvedPulseSchedulePath
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
  if ($null -ne $singleFlightParticleSourcePath) {
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
  if ($pulseN100Screening) {
    $runnerArguments.MotherParticleSource = $pulsePrefixPath
    $runnerArguments.MotherParticleSourceSha256 =
      $frozenArguments.pulse_resolution_prefix_sha256
    $runnerArguments.MotherParticleCount = 100
    $runnerArguments.PulseResolutionN100Screening = $true
    $runnerArguments.PulseResolutionCampaign = $campaignPath
    $runnerArguments.PulseResolutionCampaignSha256 =
      $frozenArguments.campaign_sha256
    $runnerArguments.PulseResolutionExperimentRowSha256 =
      $frozenArguments.experiment_row_sha256
    $runnerArguments.PulseResolutionArmId =
      [string]$frozenArguments.pulse_resolution_attribution_arm_id
    $runnerArguments.PulseResolutionExecutionMode =
      [string]$frozenArguments.pulse_resolution_execution_mode
    $runnerArguments.PulseResolutionPrefixPlanRoot = $runDirectory
    $runnerArguments.PulseResolutionRegistrationAuthority = $pulseRegistrationPath
    $runnerArguments.PulseResolutionRegistrationAuthoritySha256 =
      $frozenArguments.pulse_resolution_registration_sha256
    if ($null -ne $pulseBaselineCheckpointsPath) {
      $runnerArguments.PulseResolutionBaselineCheckpoints = $pulseBaselineCheckpointsPath
      $runnerArguments.PulseResolutionBaselineCheckpointsSha256 =
        $frozenArguments.pulse_resolution_baseline_checkpoints_sha256
    }
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
