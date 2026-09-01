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

function Resolve-RfRecoveryFailureAncestor {
  param(
    [Parameter(Mandatory)][string]$RequestedRunId,
    [Parameter(Mandatory)][string]$ExpectedRunId,
    [Parameter(Mandatory)][string]$RunsRoot,
    [Parameter(Mandatory)][string]$CampaignId,
    [Parameter(Mandatory)][string]$ExperimentId
  )

  $recoveryMatch = [regex]::Match($RequestedRunId, ('^' +
    [regex]::Escape($ExpectedRunId) + '__r(?<index>[0-9]{2})$'))
  if (-not $recoveryMatch.Success -or
      [int]$recoveryMatch.Groups['index'].Value -lt 1) {
    return $null
  }
  $fallbackFailure = $null
  $fallbackUnpublished = $null
  for ($index = [int]$recoveryMatch.Groups['index'].Value - 1;
       $index -ge 0;
       $index--) {
    $candidateRunId = if ($index -eq 0) {
      $ExpectedRunId
    } else {
      $ExpectedRunId + ('__r{0:D2}' -f $index)
    }
    $candidateDirectory = Join-Path $RunsRoot $candidateRunId
    $candidateManifestPath = Join-Path $candidateDirectory 'run_manifest.json'
    if (-not (Test-Path -LiteralPath $candidateManifestPath -PathType Leaf)) {
      # An externally stopped execution can leave a prepared suffix without a
      # manifest.  It may authorize exactly the next recovery identity only
      # when its frozen campaign row proves that it is this same experiment.
      # A bare directory is never enough: it could belong to another campaign
      # or be an abandoned manual path.
      $frozenExperimentPath = Join-Path $candidateDirectory `
        'inputs\frozen_campaign_experiment.json'
      if (Test-Path -LiteralPath $frozenExperimentPath -PathType Leaf) {
        try {
          $frozenExperiment = Get-Content -LiteralPath $frozenExperimentPath -Raw |
            ConvertFrom-Json
          if ([string]$frozenExperiment.campaign.campaign_id -eq $CampaignId -and
              [string]$frozenExperiment.experiment.experiment_id -eq $ExperimentId -and
              [string]$frozenExperiment.experiment.run_id -eq $ExpectedRunId) {
            # An unpublished recovery has no trustworthy child-run identity.
            # Keep it only as the last fallback, then continue looking for an
            # earlier published batch checkpoint that can be resumed exactly.
            if ($null -eq $fallbackUnpublished) {
              $fallbackUnpublished = [pscustomobject]@{
                run_id = $candidateRunId; status = 'unpublished'
              }
            }
          }
        } catch {
          return $null
        }
      }
      continue
    }
    $candidateConfigPath = Join-Path $candidateDirectory 'run_config.json'
    if (-not (Test-Path -LiteralPath $candidateConfigPath -PathType Leaf)) {
      return $null
    }
    try {
      $candidateManifest = Get-Content -LiteralPath $candidateManifestPath -Raw |
        ConvertFrom-Json
      $candidateConfig = Get-Content -LiteralPath $candidateConfigPath -Raw |
        ConvertFrom-Json
    } catch {
      return $null
    }
    if ([string]$candidateManifest.run_id -ne $candidateRunId -or
        [string]$candidateConfig.campaign_id -ne $CampaignId -or
        [string]$candidateConfig.experiment_id -ne $ExperimentId) {
      return $null
    }
    $candidateStatus = [string]$candidateManifest.status
    if ($candidateStatus -in @('failed','interrupted')) {
      $candidate = [pscustomobject]@{
        run_id = $candidateRunId
        status = $candidateStatus
      }
      # Prefer the oldest predecessor that already contains a naturally
      # completed SIMION batch.  A later retry can fail before launching any
      # batch (for example in continuation planning); resuming from it would
      # discard the earlier checkpoint and force needless replay.
      $completedBatchLog = @(Get-ChildItem -LiteralPath (Join-Path $candidateDirectory 'logs') `
        -Filter 'simion__batch*.stdout.log' -File -ErrorAction SilentlyContinue |
        Where-Object { Select-String -LiteralPath $_.FullName -SimpleMatch `
          -Quiet -Pattern 'status,Fly completed.' })
      # The governed integration parent does not own the SIMION stdout.  A
      # single-flight child does, so recover its completion evidence only when
      # the child's frozen screening contract proves that it belongs to this
      # exact campaign/experiment and retry suffix.
      if ($completedBatchLog.Count -eq 0 -and $candidateRunId.Length -ge 15) {
        $candidateRetrySuffix = if ($candidateRunId -match '(__r\d{2})$') {
          $Matches[1]
        } else { '' }
        $childNamePattern = '^' + [regex]::Escape($candidateRunId.Substring(0, 15)) +
          '__sim__simion__.+__n\d+' + [regex]::Escape($candidateRetrySuffix) + '$'
        $completedBatchLog = @(
          Get-ChildItem -LiteralPath $RunsRoot -Directory -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match $childNamePattern } |
          ForEach-Object {
            $screeningPath = Join-Path $_.FullName `
              'inputs\pre_pulse_time_series_screening_contract.json'
            if (-not (Test-Path -LiteralPath $screeningPath -PathType Leaf)) { return }
            try {
              $screening = Get-Content -LiteralPath $screeningPath -Raw -Encoding UTF8 |
                ConvertFrom-Json
              if ([string]$screening.identities.campaign_id -ne $CampaignId -or
                  [string]$screening.identities.experiment_id -ne $ExperimentId) { return }
              Get-ChildItem -LiteralPath (Join-Path $_.FullName 'logs') `
                -Filter 'simion__batch*.stdout.log' -File -ErrorAction SilentlyContinue |
                Where-Object { Select-String -LiteralPath $_.FullName -SimpleMatch `
                  -Quiet -Pattern 'status,Fly completed.' }
            } catch { return }
          }
        )
      }
      if ($completedBatchLog.Count -gt 0) {
        $childRunDirectory = @($completedBatchLog | ForEach-Object {
          $_.Directory.Parent.FullName
        } | Where-Object {
          -not $_.Equals($candidateDirectory,[StringComparison]::OrdinalIgnoreCase)
        } | Select-Object -First 1)
        return [pscustomobject]@{
          run_id=$candidateRunId; status=$candidateStatus
          pre_pulse_child_run_directory=$(if ($childRunDirectory.Count -eq 1) {
            [string]$childRunDirectory[0]
          } else { $null })
        }
      }
      if ($null -eq $fallbackFailure) { $fallbackFailure = $candidate }
      continue
    }
    # A successful predecessor is an authority boundary.  A bare ``created``
    # parent predating a same-experiment prepared retry carries no result
    # evidence, so it must not hide that newer durable retry input.
    if ($candidateStatus -eq 'created' -and $null -ne $fallbackUnpublished) {
      continue
    }
    return $null
  }
  # A same-experiment prepared retry is newer than an earlier failed ancestor
  # and retains its frozen inputs.  Prefer it so recovery can continue from the
  # latest durable boundary without replaying preparation unnecessarily.
  if ($null -ne $fallbackUnpublished) { return $fallbackUnpublished }
  return $fallbackFailure
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
$flattenedArguments = $frozenArguments
$executionPlanReferenceNames = @(
  'resolved_execution_plan_filename',
  'resolved_execution_plan_sha256'
)
$executionPlanReferenceCount = @($executionPlanReferenceNames | Where-Object {
  $flattenedArguments.ContainsKey($_)
}).Count
if ($executionPlanReferenceCount -ne 0) {
  if ($executionPlanReferenceCount -ne $executionPlanReferenceNames.Count) {
    throw 'Prepared resolved execution plan reference must be all-or-none.'
  }
  $compositionPlanRoot = Split-Path -Parent ([IO.Path]::GetFullPath($CompositionPlan))
  $executionPlanFilename = [string]$flattenedArguments.resolved_execution_plan_filename
  $executionPlanPath = [IO.Path]::GetFullPath((Join-Path $compositionPlanRoot $executionPlanFilename))
  if ([IO.Path]::GetFileName($executionPlanFilename) -ne $executionPlanFilename -or
      -not (Split-Path -Parent $executionPlanPath).Equals(
        $compositionPlanRoot,[StringComparison]::OrdinalIgnoreCase
      ) -or
      -not (Test-Path -LiteralPath $executionPlanPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $executionPlanPath -Algorithm SHA256).Hash -cne
        [string]$flattenedArguments.resolved_execution_plan_sha256) {
    throw 'Prepared resolved execution plan is missing, misplaced or stale.'
  }
  $resolvedExecutionPlan = Get-Content -LiteralPath $executionPlanPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($resolvedExecutionPlan.schema_version -ne 1 -or
      $resolvedExecutionPlan.role -ne 'rf_oatof_resolved_execution_plan' -or
      $resolvedExecutionPlan.campaign_id -ne $flattenedArguments.campaign_id -or
      $resolvedExecutionPlan.experiment_id -ne $flattenedArguments.experiment_id -or
      $resolvedExecutionPlan.experiment_row_sha256 -ne $flattenedArguments.experiment_row_sha256 -or
      $resolvedExecutionPlan.execution_strategy -ne $flattenedArguments.execution_strategy -or
      $null -eq $resolvedExecutionPlan.arguments) {
    throw 'Prepared resolved execution plan identity is invalid.'
  }
  $resolvedArguments = @{}
  foreach ($property in @($resolvedExecutionPlan.arguments.PSObject.Properties)) {
    if ($property.Name -in $executionPlanReferenceNames -or
        $property.Value -isnot [string] -or
        $resolvedArguments.ContainsKey($property.Name)) {
      throw 'Prepared resolved execution plan arguments are invalid.'
    }
    $resolvedArguments[$property.Name] = [string]$property.Value
  }
  $flattenedExecutionArguments = @{}
  foreach ($name in $flattenedArguments.Keys) {
    if ($name -notin $executionPlanReferenceNames) {
      $flattenedExecutionArguments[$name] = [string]$flattenedArguments[$name]
    }
  }
  if ($resolvedArguments.Count -ne $flattenedExecutionArguments.Count -or
      @($resolvedArguments.Keys | Where-Object {
        -not $flattenedExecutionArguments.ContainsKey($_) -or
        $resolvedArguments[$_] -cne $flattenedExecutionArguments[$_]
      }).Count -ne 0) {
    throw 'Prepared resolved execution plan differs from flattened adapter arguments.'
  }
  $frozenArguments = $resolvedArguments
}
$expectedArguments = @(
  'adapter_sha256',
  'campaign_path',
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
$frozenAuthoringArgumentNames = @(
  'frozen_campaign_experiment_filename',
  'frozen_campaign_experiment_sha256'
)
$frozenAuthoringArgumentCount = @($frozenAuthoringArgumentNames | Where-Object {
  $frozenArguments.ContainsKey($_)
}).Count
if ($frozenAuthoringArgumentCount -ne $frozenAuthoringArgumentNames.Count) {
  throw 'Prepared execution requires exactly one frozen campaign experiment.'
}
$expectedArguments += $frozenAuthoringArgumentNames
if ([string]$frozenArguments.execution_strategy -eq 'simion_single_flight') {
  if ($frozenArguments.ContainsKey('single_flight_execution_mode')) {
    $expectedArguments += 'single_flight_execution_mode'
  }
  $expectedArguments += @(
    'single_flight_pa_cache_policy',
    'single_flight_pa_cache_policy_provenance',
    'resolved_single_flight_execution_profile_filename',
    'resolved_single_flight_execution_profile_sha256'
  )
  $hasPreparedLocalApertureWidth = $frozenArguments.ContainsKey(
    'accelerator_entrance_local_aperture_width_mm'
  )
  $hasPreparedLocalApertureHeight = $frozenArguments.ContainsKey(
    'accelerator_entrance_local_aperture_height_mm'
  )
  if ($hasPreparedLocalApertureWidth -ne $hasPreparedLocalApertureHeight) {
    throw 'Prepared local accelerator aperture arguments are incomplete.'
  }
  if ($hasPreparedLocalApertureWidth) {
    $expectedArguments += @(
      'accelerator_entrance_local_aperture_width_mm',
      'accelerator_entrance_local_aperture_height_mm'
    )
  }
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
  if ($frozenArguments.ContainsKey('terminal_handoff_state_path')) {
    $expectedArguments += @(
      'terminal_handoff_state_path','terminal_handoff_state_sha256',
      'terminal_handoff_mother_particle_count',
      'terminal_handoff_continued_particle_count',
      'terminal_handoff_mass_amu','terminal_handoff_charge_state',
      'terminal_handoff_upstream_loss_count',
      'terminal_handoff_receipt_filename','terminal_handoff_receipt_sha256'
    )
    if ($frozenArguments.ContainsKey('terminal_handoff_smoke_source_particle_id')) {
      $expectedArguments += 'terminal_handoff_smoke_source_particle_id'
    }
    if ($frozenArguments.ContainsKey('terminal_handoff_execution_particle_count')) {
      $expectedArguments += 'terminal_handoff_execution_particle_count'
    }
  }
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
if (@($expectedArguments | Where-Object {
      -not $frozenArguments.ContainsKey($_)
    }).Count -ne 0) {
  throw 'Prepared family adapter is missing a required contract argument.'
}

$sourceBranchId = [string]$frozenArguments.source_branch_id
if ($sourceBranchId -notin @('comsol','simion')) {
  throw 'Prepared family source branch is invalid.'
}
$executionStrategy = [string]$frozenArguments.execution_strategy
if ($executionStrategy -notin @('staged_three_stage','simion_single_flight')) {
  throw 'Prepared family execution strategy is invalid.'
}
$singleFlightExecutionMode = if (
  $frozenArguments.ContainsKey('single_flight_execution_mode')
) { [string]$frozenArguments.single_flight_execution_mode } else { 'particle_flight' }
if ($executionStrategy -ne 'simion_single_flight' -and
    $singleFlightExecutionMode -ne 'particle_flight') {
  throw 'Non-single-flight execution cannot select a single-flight execution mode.'
}
if ($executionStrategy -eq 'simion_single_flight' -and
    $singleFlightExecutionMode -notin @('particle_flight','program_axis_field_export')) {
  throw 'Prepared single-flight execution mode is unsupported.'
}
$repo = [IO.Path]::GetFullPath($RepoRoot)
$workspaceRoot = Split-Path -Parent $repo
$compositionPlanRoot = Split-Path -Parent ([IO.Path]::GetFullPath($CompositionPlan))
$frozenAuthoringPath = [IO.Path]::GetFullPath((Join-Path $compositionPlanRoot `
    $frozenArguments.frozen_campaign_experiment_filename))
  if (-not $frozenAuthoringPath.StartsWith(
        $compositionPlanRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase) -or
      -not (Test-Path -LiteralPath $frozenAuthoringPath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $frozenAuthoringPath -Algorithm SHA256).Hash -cne
        [string]$frozenArguments.frozen_campaign_experiment_sha256) {
    throw 'Frozen campaign experiment is missing, outside the plan, or stale.'
  }
  $frozenAuthoring = Get-Content -LiteralPath $frozenAuthoringPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($frozenAuthoring.schema_version -ne 1 -or
      $frozenAuthoring.role -ne 'rf_oatof_frozen_campaign_experiment' -or
      $frozenAuthoring.campaign.role -ne 'rf_multipole_oatof_experiment_campaign' -or
      $frozenAuthoring.campaign.integration_id -ne $plan.integration_id -or
      $frozenAuthoring.campaign.campaign_id -ne $frozenArguments.campaign_id -or
      $frozenAuthoring.experiment.experiment_id -ne $frozenArguments.experiment_id -or
      $frozenAuthoring.experiment_row_sha256 -ne $frozenArguments.experiment_row_sha256) {
    throw 'Frozen campaign experiment identity is invalid.'
  }
$campaign = $frozenAuthoring.campaign
$experiment = $frozenAuthoring.experiment
$hasLocalApertureArguments = $frozenArguments.ContainsKey(
  'accelerator_entrance_local_aperture_width_mm'
)
if ($hasLocalApertureArguments -ne $frozenArguments.ContainsKey(
    'accelerator_entrance_local_aperture_height_mm')) {
  throw 'Prepared local accelerator aperture arguments are incomplete.'
}
$experimentLocalAperture = if (
  $experiment.PSObject.Properties.Name -contains
  'accelerator_entrance_local_aperture_mm'
) {
  $experiment.accelerator_entrance_local_aperture_mm
} else { $null }
if ($hasLocalApertureArguments) {
  if ($null -eq $experimentLocalAperture -or
      [double]$frozenArguments.accelerator_entrance_local_aperture_width_mm -le 0.0 -or
      [double]$frozenArguments.accelerator_entrance_local_aperture_height_mm -le 0.0 -or
      [double]$experimentLocalAperture.width -ne
        [double]$frozenArguments.accelerator_entrance_local_aperture_width_mm -or
      [double]$experimentLocalAperture.height -ne
        [double]$frozenArguments.accelerator_entrance_local_aperture_height_mm) {
    throw 'Prepared local accelerator aperture arguments differ from the frozen experiment.'
  }
} elseif ($null -ne $experimentLocalAperture) {
  throw 'Frozen experiment local accelerator aperture is missing from execution arguments.'
}
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
  $isIdealMaterialization = $materializationReceipt.role -eq
    'rf_oatof_single_flight_source_materialization_receipt'
  $isIndependentIonSourceVolume = (
    $materializationReceipt.role -eq 'continuous_axial_volume_ion_beam_source' -and
    $materializationReceipt.method -eq
      'independent_spatial_velocity_ion_source_snapshot_v1' -and
    $materializationReceipt.materialization_mode -eq
      'independent_spatial_velocity_ion_source_snapshot'
  )
  if ((-not $isIdealMaterialization -and -not $isIndependentIonSourceVolume) -or
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
  } elseif ($frozenArguments.source_release_mode -notin @('continuous_frontend','continuous_frontend_handoff') -or
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
$registry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$mappings = @($registry.mappings | Where-Object {
  $_.connection_profile_id -eq $plan.selection.connection_profile_id
})
if ($mappings.Count -ne 1) {
  throw 'Family execution adapter mapping no longer resolves uniquely.'
}
$mapping = $mappings[0]
$adapterImplementations = $registry.adapter_implementations
$adapterImplementation = $adapterImplementations.PSObject.Properties[
  [string]$mapping.adapter_id
].Value
if ($null -eq $adapterImplementation) {
  throw 'Family execution adapter implementation no longer resolves uniquely.'
}
$adapterPath = [IO.Path]::GetFullPath($PSCommandPath)
$expectedAdapterPath = (
  'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/' +
  'workflows/family_source_closure/adapter.ps1'
)
if ($adapterImplementation.adapter_entrypoint -ne $expectedAdapterPath -or
    $adapterImplementation.adapter_sha256 -ne $frozenArguments.adapter_sha256 -or
    (Get-FileHash -LiteralPath $adapterPath -Algorithm SHA256).Hash -ne
      $frozenArguments.adapter_sha256) {
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
$expectedRunId = [string]$experiment.run_id
$recoveryAncestor = $null
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
if (-not $PrepareOnly -and $expectedRunId -ne $RunId) {
  $recoveryRunsRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' + $plan.integration_id + '\runs'
  )
  $recoveryAncestor = Resolve-RfRecoveryFailureAncestor `
    -RequestedRunId $RunId -ExpectedRunId $expectedRunId `
    -RunsRoot $recoveryRunsRoot -CampaignId $campaign.campaign_id `
    -ExperimentId $experiment.experiment_id
  if ($null -eq $recoveryAncestor) {
    throw 'Solver-authorized RunId differs from the campaign row.'
  }
}
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
  $declaredPrePulsePopulationCount = [int]`
    $experiment.single_flight_population.execution_population.particle_count
  $expectedTimeSeriesPrefix = if ($frozenArguments.source_release_mode -eq
      'continuous_frontend_handoff') {
    'inputs/terminal_handoff_continuation_global_state.csv'
  } elseif ($pulseTimingDiscoveryAuthority) {
    $prePulseTimeSeriesPrefixBinding
  } else {
    'inputs/pre_pulse_time_series_screening_prefix_n' +
      $declaredPrePulsePopulationCount + '.csv'
  }
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
if ($null -ne $recoveryAncestor) {
  $recoveryChildRunDirectory = [string]$recoveryAncestor.pre_pulse_child_run_directory
  if ([string]::IsNullOrWhiteSpace($recoveryChildRunDirectory)) {
    $ancestorRetrySuffix = if ([string]$recoveryAncestor.run_id -match '(__r\d{2})$') {
      $Matches[1]
    } else { '' }
    $childPattern = '^' + [regex]::Escape(
      ([string]$recoveryAncestor.run_id).Substring(0, 15)
    ) + '__sim__simion__.+__n\d+' + [regex]::Escape($ancestorRetrySuffix) + '$'
    $recoveryChildren = @(
      Get-ChildItem -LiteralPath $recoveryRunsRoot -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match $childPattern } |
      Where-Object {
        $screeningPath = Join-Path $_.FullName 'inputs\pre_pulse_time_series_screening_contract.json'
        if (-not (Test-Path -LiteralPath $screeningPath -PathType Leaf)) { return $false }
        try {
          $screening = Get-Content -LiteralPath $screeningPath -Raw -Encoding UTF8 | ConvertFrom-Json
          [string]$screening.identities.campaign_id -eq [string]$campaign.campaign_id -and
            [string]$screening.identities.experiment_id -eq [string]$experiment.experiment_id -and
            @(Get-ChildItem -LiteralPath (Join-Path $_.FullName 'logs') `
              -Filter 'simion__batch*.stdout.log' -File -ErrorAction SilentlyContinue |
              Where-Object { Select-String -LiteralPath $_.FullName -SimpleMatch `
                -Quiet -Pattern 'status,Fly completed.' }).Count -gt 0
        } catch { return $false }
      }
    )
    if ($recoveryChildren.Count -ne 1) {
      throw 'Pre-pulse continuation cannot resolve exactly one completed child run.'
    }
    $recoveryChildRunDirectory = $recoveryChildren[0].FullName
  }
  $predecessorSourceContract = Join-Path `
    $recoveryChildRunDirectory `
    'inputs\resolved_source_contract.json'
  $predecessorScreeningContract = Join-Path `
    $recoveryChildRunDirectory `
    'inputs\pre_pulse_time_series_screening_contract.json'
  if (-not (Test-Path -LiteralPath $predecessorSourceContract -PathType Leaf) -or
      -not (Test-Path -LiteralPath $predecessorScreeningContract -PathType Leaf)) {
    throw 'Pre-pulse continuation child lacks frozen source identity inputs.'
  }
  $predecessorScreening = Get-Content -LiteralPath $predecessorScreeningContract `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $predecessorSourceSha256 = (Get-FileHash -LiteralPath $predecessorSourceContract `
    -Algorithm SHA256).Hash
  if ($predecessorSourceSha256 -ne
      [string]$predecessorScreening.identities.resolved_source_contract_sha256) {
    throw 'Pre-pulse continuation child source contract identity differs.'
  }
  $preparedSourceSha256 = (Get-FileHash -LiteralPath $resolvedSourceContractPath `
    -Algorithm SHA256).Hash
  Copy-Item -LiteralPath $predecessorSourceContract -Destination $resolvedSourceContractPath -Force
  $frozenArguments.resolved_source_contract_sha256 = $predecessorSourceSha256
  [ordered]@{
    schema_version=1;role='rf_oatof_pre_pulse_continuation_source_authority'
    predecessor_run_id=[string]$recoveryAncestor.run_id
    predecessor_single_flight_run=$recoveryChildRunDirectory
    predecessor_source_contract_sha256=$predecessorSourceSha256
    superseded_prepared_source_contract_sha256=$preparedSourceSha256
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (
    Join-Path $runDirectory 'pre_pulse_continuation_source_authority.json'
  ) -Encoding UTF8
}
$resolvedBudgetPath = [IO.Path]::GetFullPath(
  (Join-Path $runDirectory $frozenArguments.resolved_budget_filename)
)
$upstreamResolvedDesignPath = [IO.Path]::GetFullPath(
  (Join-Path $runDirectory $frozenArguments.upstream_resolved_design_filename)
)
$resolvedOatofGeometryPath = $null
$resolvedPulseSchedulePath = $null
$resolvedPopulationContractPath = $null
$resolvedExecutionProfilePath = $null
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
if ($executionStrategy -eq 'simion_single_flight') {
  $resolvedExecutionProfilePath = [IO.Path]::GetFullPath((Join-Path $runDirectory `
    $frozenArguments.resolved_single_flight_execution_profile_filename))
  $inputsRoot = (Join-Path $runDirectory 'inputs') + [IO.Path]::DirectorySeparatorChar
  if ($frozenArguments.resolved_single_flight_execution_profile_filename -ne
        'inputs/resolved_single_flight_execution_profile.json' -or
      -not $resolvedExecutionProfilePath.StartsWith(
        $inputsRoot,[StringComparison]::OrdinalIgnoreCase) -or
      -not (Test-Path -LiteralPath $resolvedExecutionProfilePath -PathType Leaf) -or
      (Get-FileHash -LiteralPath $resolvedExecutionProfilePath -Algorithm SHA256).Hash -ne
        $frozenArguments.resolved_single_flight_execution_profile_sha256) {
    throw 'Prepared single-flight execution profile is missing or stale.'
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
  -UpstreamResolvedDesignSha256 $frozenArguments.upstream_resolved_design_sha256 `
  -AllowImplementationContentShaMismatch:([string]$campaign.status -eq 'exploration')
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
if ([string]$campaign.status -notin @('authorized','exploration')) {
  throw 'Campaign status does not permit solver execution.'
}
if (-not $SolverAuthorized) {
  throw 'Family source-closure execution requires explicit solver authorization.'
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
  RuntimeImplementationBindingMode = if ([string]$campaign.status -eq 'exploration') {
    'exploration'
  } else { 'strict' }
}
if ($hasLocalApertureArguments) {
  $runnerArguments.AcceleratorEntranceLocalApertureWidthMm =
    [double]$frozenArguments.accelerator_entrance_local_aperture_width_mm
  $runnerArguments.AcceleratorEntranceLocalApertureHeightMm =
    [double]$frozenArguments.accelerator_entrance_local_aperture_height_mm
}
if ($singleFlightExecutionMode -eq 'program_axis_field_export') {
  # The export remains a run-local SIMION build, but must be configured only
  # after the common runner request exists under StrictMode.
  if (-not $campaignHasThreeZoneCandidate) {
    throw 'Program axis-field export requires a frozen three-zone Candidate.'
  }
  $runnerArguments.BuildOnly = $true
  $runnerArguments.ProgramAxisFieldExport = $true
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
  if ($null -ne $paCacheGenerationBindingPath) {
    $runnerArguments.RequiredPaCacheGenerationBinding = $paCacheGenerationBindingPath
    $runnerArguments.RequiredPaCacheGenerationBindingSha256 =
      [string]$frozenArguments.single_flight_pa_cache_generation_binding_sha256
  }
  $runnerArguments.ResolvedExecutionProfile = $resolvedExecutionProfilePath
  $runnerArguments.ResolvedExecutionProfileSha256 =
    [string]$frozenArguments.resolved_single_flight_execution_profile_sha256
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
  if ($frozenArguments.ContainsKey('source_release_mode')) {
    if ($frozenArguments.ContainsKey('source_profile_id')) {
      $runnerArguments.SourceProfileId = [string]$frozenArguments.source_profile_id
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
  if ($frozenArguments.source_release_mode -eq 'continuous_frontend_handoff') {
    $terminalHandoffStatePath = [IO.Path]::GetFullPath(
      (Join-Path $workspaceRoot $frozenArguments.terminal_handoff_state_path)
    )
    $terminalHandoffReceiptPath = Join-Path (Split-Path -Parent $CompositionPlan) `
      $frozenArguments.terminal_handoff_receipt_filename
    if (-not (Test-Path -LiteralPath $terminalHandoffStatePath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $terminalHandoffStatePath -Algorithm SHA256).Hash -ne
          $frozenArguments.terminal_handoff_state_sha256 -or
        -not (Test-Path -LiteralPath $terminalHandoffReceiptPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $terminalHandoffReceiptPath -Algorithm SHA256).Hash -ne
          $frozenArguments.terminal_handoff_receipt_sha256) {
      throw 'Terminal-handoff continuation input is missing or stale.'
    }
    $runnerArguments.TerminalHandoffState = $terminalHandoffStatePath
    $runnerArguments.TerminalHandoffStateSha256 =
      [string]$frozenArguments.terminal_handoff_state_sha256
    $runnerArguments.TerminalHandoffMotherParticleCount =
      [int]$frozenArguments.terminal_handoff_mother_particle_count
    $runnerArguments.TerminalHandoffContinuedParticleCount =
      [int]$frozenArguments.terminal_handoff_continued_particle_count
    $runnerArguments.TerminalHandoffMassAmu = [double]$frozenArguments.terminal_handoff_mass_amu
    $runnerArguments.TerminalHandoffChargeState = [int]$frozenArguments.terminal_handoff_charge_state
    $runnerArguments.TerminalHandoffUpstreamLossCount = [int]$frozenArguments.terminal_handoff_upstream_loss_count
    if ($frozenArguments.ContainsKey('terminal_handoff_smoke_source_particle_id')) {
      $runnerArguments.TerminalHandoffSmokeSourceParticleId =
        [int]$frozenArguments.terminal_handoff_smoke_source_particle_id
    }
    if ($frozenArguments.ContainsKey('terminal_handoff_execution_particle_count')) {
      $runnerArguments.TerminalHandoffExecutionParticleCount =
        [int]$frozenArguments.terminal_handoff_execution_particle_count
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
  if ($null -ne $preparedPrefixPath -and
      $frozenArguments.source_release_mode -ne 'continuous_frontend_handoff') {
    # The pre-pulse prefix is an explicit frozen subset, not the complete
    # materialized source described by its receipt.  Passing that receipt
    # alongside the subset creates contradictory source identities in the
    # runner.  The prefix's own byte identity and screening contract remain
    # the authority for this detector-blind execution.
    $runnerArguments.Remove('MotherParticleSourceReceipt')
    $runnerArguments.Remove('MotherParticleSourceReceiptSha256')
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
    if ($null -ne $recoveryAncestor) {
      $ancestorRunId = [string]$recoveryAncestor.run_id
      $ancestorRetrySuffix = if ($ancestorRunId -match '(__r\d{2})$') {
        $Matches[1]
      } else { '' }
      $ancestorSingleFlightRunId = "$($ancestorRunId.Substring(0, 15))__sim__simion__$singleFlightRole-gap$connectorGapLabel`__n$expectedExecutionParticleCount$ancestorRetrySuffix"
      $expectedAncestorSingleFlightRun = Join-Path $runsRoot `
        $ancestorSingleFlightRunId
      if (-not $recoveryChildRunDirectory.Equals(
        $expectedAncestorSingleFlightRun,[StringComparison]::OrdinalIgnoreCase
      )) {
        throw 'Pre-pulse continuation source authority and completed-batch child differ.'
      }
      $runnerArguments.ResumePrePulseFromRun = $recoveryChildRunDirectory
      # A resumed batch must retain the predecessor's exact screening
      # contract, not a newly materialized byte-different copy from the
      # recovery composition plan.  The shared continuation protocol verifies
      # this frozen input against the predecessor manifest before it imports
      # any completed TRACE records.
      $predecessorScreeningContract = Join-Path `
        $runnerArguments.ResumePrePulseFromRun `
        'inputs\pre_pulse_time_series_screening_contract.json'
      if (-not (Test-Path -LiteralPath $predecessorScreeningContract -PathType Leaf)) {
        throw 'Pre-pulse continuation predecessor lacks its frozen screening contract.'
      }
      $predecessorScreeningDocument = Get-Content -LiteralPath $predecessorScreeningContract `
        -Raw -Encoding UTF8 | ConvertFrom-Json
      # Completed trace batches are only valid under the predecessor's exact
      # source contract: it contributes to both the time-series identity and
      # the static PA cache keys.  The recovery composition can legitimately
      # have a new run-local source receipt, but it must not rebuild a field
      # and then combine it with predecessor trajectories.
      $predecessorResolvedSourceContract = Join-Path `
        $runnerArguments.ResumePrePulseFromRun 'inputs\resolved_source_contract.json'
      if (-not (Test-Path -LiteralPath $predecessorResolvedSourceContract -PathType Leaf)) {
        throw 'Pre-pulse continuation predecessor lacks its frozen resolved source contract.'
      }
      $predecessorResolvedSourceContractSha256 = (
        Get-FileHash -LiteralPath $predecessorResolvedSourceContract -Algorithm SHA256
      ).Hash
      if ($predecessorResolvedSourceContractSha256 -ne
          [string]$predecessorScreeningDocument.identities.resolved_source_contract_sha256) {
        throw 'Pre-pulse continuation predecessor resolved source contract identity differs.'
      }
      $runnerArguments.TimeIntegrationProfileId =
        [string]$predecessorScreeningDocument.identities.time_integration_profile_id
      $runnerArguments.PrePulseTimeSeriesContract = $predecessorScreeningContract
      $runnerArguments.PrePulseTimeSeriesContractSha256 =
        (Get-FileHash -LiteralPath $predecessorScreeningContract -Algorithm SHA256).Hash
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
  frozen_campaign_experiment_sha256 = $frozenArguments.frozen_campaign_experiment_sha256
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
  runtime_implementation_binding_mode = $runnerArguments.RuntimeImplementationBindingMode
  runtime_implementation_identity = $runtime.implementation_identity
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
