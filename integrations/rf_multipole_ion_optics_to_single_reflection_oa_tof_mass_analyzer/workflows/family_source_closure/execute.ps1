[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Campaign,
  [Parameter(Mandatory)][string]$ExperimentId,
  [string]$OutputDirectory = '',
  [string]$PythonExe = '',
  [switch]$ValidateOnly,
  [switch]$PrepareOnly,
  [switch]$SolverAuthorized,
  [switch]$FinalizeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$selectedModeCount = (
  [int][bool]$ValidateOnly +
  [int][bool]$PrepareOnly +
  [int][bool]$SolverAuthorized +
  [int][bool]$FinalizeOnly
)
if ($selectedModeCount -ne 1) {
  throw 'Select exactly one of ValidateOnly, PrepareOnly, SolverAuthorized or FinalizeOnly.'
}
if ($PrepareOnly -and [string]::IsNullOrWhiteSpace($OutputDirectory)) {
  throw 'PrepareOnly requires an explicit OutputDirectory for review.'
}
if (-not $PrepareOnly -and
    -not $FinalizeOnly -and
    -not [string]::IsNullOrWhiteSpace($OutputDirectory)) {
  throw 'OutputDirectory is accepted only for PrepareOnly.'
}

$workflowRoot = $PSScriptRoot
$integrationRoot = (Resolve-Path (Join-Path $workflowRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
  $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
  throw "Python 3.11 executable not found: $PythonExe"
}

$campaignCandidate = if ([IO.Path]::IsPathRooted($Campaign)) {
  $Campaign
} else {
  Join-Path $repoRoot $Campaign
}
$campaignPath = [IO.Path]::GetFullPath($campaignCandidate)
if (-not $campaignPath.StartsWith(
      $repoRoot + [IO.Path]::DirectorySeparatorChar,
      [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not (Test-Path -LiteralPath $campaignPath -PathType Leaf)) {
  throw 'Campaign must be one repository-managed file.'
}
$expectedActiveWorkflow = 'workflows/family_source_closure/execute.ps1'
$campaignRepoRelative = [IO.Path]::GetRelativePath($repoRoot, $campaignPath).Replace('\', '/')
$campaignDocument = Get-Content -LiteralPath $campaignPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$lifecycleRegistryPath = Join-Path $integrationRoot `
  'config\diagnostics\lifecycle_registry.json'
$lifecycleRegistry = Get-Content -LiteralPath $lifecycleRegistryPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
if ($lifecycleRegistry.role -ne 'rf_oatof_diagnostics_lifecycle_registry' -or
    $lifecycleRegistry.integration_id -ne
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' -or
    $lifecycleRegistry.discovery_policy -ne 'default_deny') {
  throw 'Diagnostics lifecycle registry identity or policy is invalid.'
}
$campaignRole = [string]$lifecycleRegistry.campaign_selector.role
if ([string]$campaignDocument.role -ne $campaignRole) {
  throw 'Only registered experiment campaigns may enter the family workflow.'
}
$registeredCampaigns = @($lifecycleRegistry.active_campaigns | Where-Object {
  [string]$_.path -eq $campaignRepoRelative
})
if ($registeredCampaigns.Count -ne 1) {
  throw 'Campaign is not an active lifecycle authority; execution is forbidden.'
}
$campaignSha256 = (Get-FileHash -LiteralPath $campaignPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($campaignSha256 -ne ([string]$registeredCampaigns[0].content_sha256).ToLowerInvariant()) {
  throw 'Active lifecycle campaign identity differs; execution is forbidden.'
}
if ([string]$campaignDocument.status -in @('retired', 'archived_invalid')) {
  throw 'Retired or invalid campaigns are not executable in any mode.'
}
if (($SolverAuthorized -or $FinalizeOnly) -and [string]$campaignDocument.status -ne 'authorized') {
  throw 'SolverAuthorized or FinalizeOnly execution requires campaign.status=authorized.'
}
$executionRegistryPath = Join-Path $integrationRoot `
  'config\family_source_closure_execution_registry.json'
$executionRegistry = Get-Content -LiteralPath $executionRegistryPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
if ($executionRegistry.role -ne
      'rf_oatof_family_source_closure_execution_registry' -or
    $executionRegistry.integration_id -ne
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' -or
    $executionRegistry.active_workflow -ne $expectedActiveWorkflow) {
  throw 'Family execution registry identity is invalid.'
}
$currentCampaigns = @($executionRegistry.current_campaigns | Where-Object {
  [string]$_.path -eq $campaignRepoRelative
})
if ($currentCampaigns.Count -gt 1) {
  throw 'Family execution registry resolves the campaign more than once.'
}
if ($SolverAuthorized -or $FinalizeOnly) {
  if ($currentCampaigns.Count -ne 1) {
    throw 'Campaign is not a current registered execution authority; execution is forbidden.'
  }
  $currentCampaignSha256 = (
    Get-FileHash -LiteralPath $campaignPath -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  if ($currentCampaignSha256 -ne
      ([string]$currentCampaigns[0].content_sha256).ToLowerInvariant()) {
    throw 'Current execution authority campaign identity differs; execution is forbidden.'
  }
}
$experimentRows = @($campaignDocument.experiments | Where-Object {
  $_.experiment_id -eq $ExperimentId
})
if ($experimentRows.Count -ne 1) {
  throw 'Campaign experiment must resolve exactly once.'
}
$selectedExperiment = $experimentRows[0]
$activePostPulseWorkingPointPolicy =
  [string]$executionRegistry.active_post_pulse_restart_working_point_policy
if ($activePostPulseWorkingPointPolicy -ne
    'source_zvz_three_zone_theory_working_point_required_v1') {
  throw 'Family execution registry post-pulse working-point policy is invalid.'
}
$isManifestBoundPostPulseRestart =
  [string]$selectedExperiment.source_release_mode -eq 'pre_pulse_restart' -and
  ($selectedExperiment.PSObject.Properties.Name -contains
    'post_pulse_restart_reuse_authority')
if ($SolverAuthorized -and $isManifestBoundPostPulseRestart) {
  $theoryWorkingPoint = $selectedExperiment.single_flight_source_zvz_theory_working_point
  if ([string]$selectedExperiment.single_flight_source_zvz_affine_policy -ne
        'source_zvz_affine_identify_and_bind_v1' -or
      $null -eq $theoryWorkingPoint -or
      [string]$theoryWorkingPoint.policy_id -ne
        'source_zvz_three_zone_theory_working_point_v1' -or
      [string]$selectedExperiment.post_pulse_restart_reuse_authority.post_pulse_variation_axis -ne
        'accelerator_field_profile_id_and_source_zvz_theory_working_point') {
    throw 'Active manifest-bound post-pulse restart requires the source z--vz theory working point.'
  }
}
$isStagedGrid2 =
  [string]$selectedExperiment.source_release_mode -eq 'staged_grid2_restart'
if ($SolverAuthorized -and $isStagedGrid2 -and (
    [int]$campaignDocument.schema_version -ne 5 -or
    $null -eq $selectedExperiment.staged_grid2_source_state -or
    -not ($selectedExperiment.staged_grid2_source_state.PSObject.Properties.Name `
      -contains 'loader_authorization_budget'))) {
  throw 'SolverAuthorized staged grid2 execution requires campaign v5 with an explicit loader authorization budget.'
}
if (-not $FinalizeOnly) {
  & $PythonExe -m (
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
    'workflows.family_source_closure.refresh_campaign_source_bindings'
  ) --repo-root $repoRoot --campaign $campaignPath --check
  if ($LASTEXITCODE -ne 0) {
    throw 'Campaign source bindings must be refreshed before execution.'
  }
}
$campaignRunId = [string]$experimentRows[0].run_id
& $PythonExe -m common.contracts.artifact_naming run $campaignRunId
if ($LASTEXITCODE -ne 0) {
  throw 'Campaign row run_id fails the repository artifact naming contract.'
}
$legacySingleFlightCachePolicy =
  [string]$selectedExperiment.execution_strategy -eq 'simion_single_flight' -and
  -not ($selectedExperiment.PSObject.Properties.Name -contains
    'single_flight_pa_cache_policy')
if ($legacySingleFlightCachePolicy -and -not $ValidateOnly) {
  throw 'Legacy single-flight cache policy is compatible with ValidateOnly only.'
}

$workspaceRoot = Split-Path -Parent $repoRoot
$cleanupOutput = $ValidateOnly
if ($ValidateOnly) {
  $validationRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' +
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\' +
    'scratch'
  )
  $outputRoot = Join-Path $validationRoot (
    (Get-Date -Format 'yyyyMMdd_HHmmss') +
    '__repo__family-source-validation-' +
    [guid]::NewGuid().ToString('N').Substring(0, 8)
  )
} elseif ($PrepareOnly) {
  $outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
} elseif ($FinalizeOnly) {
  $runsRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' +
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs'
  )
  $sourceParentRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $campaignRunId))
  if (-not (Test-Path -LiteralPath (Join-Path $sourceParentRoot 'run_manifest.json') -PathType Leaf)) {
    throw 'FinalizeOnly requires the exact failed campaign parent run.'
  }
  $outputRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot ($campaignRunId + '__r01')))
  if (Test-Path -LiteralPath $outputRoot) {
    throw 'FinalizeOnly recovery target already exists; never overwrite a recovery run.'
  }
} else {
  $runsRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' +
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs'
  )
  $outputRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $campaignRunId))
}
$outputRoot = [IO.Path]::GetFullPath($outputRoot)
$removeUnpublishedTargetOnExit = [bool]($SolverAuthorized -or $FinalizeOnly)
if ($SolverAuthorized -and (Test-Path -LiteralPath $outputRoot)) {
  throw 'SolverAuthorized target run directory already exists.'
}
$unpublishedDiscoveryRoot = ''
if ($SolverAuthorized -and $campaignRunId -match
    '^(?<stamp>[0-9]{8}_[0-9]{6})__.+__(?<detail>n[0-9]+)(?<retry>__r[0-9]{2})?$') {
  $derivedDiscoveryRunId = (
    $Matches.stamp + '__sim__cross__pulse-timing-discovery__' +
    $Matches.detail + [string]$Matches['retry']
  )
  $candidateDiscoveryRoot = [IO.Path]::GetFullPath((Join-Path `
    $runsRoot $derivedDiscoveryRunId))
  if (-not (Test-Path -LiteralPath $candidateDiscoveryRoot)) {
    $unpublishedDiscoveryRoot = $candidateDiscoveryRoot
  }
}

function Invoke-FamilyPreparation {
  param(
    [Parameter(Mandatory)][string]$ResolvedPath,
    [Parameter(Mandatory)][string]$PlanPath,
    [string]$PulseTimingTransition = '',
    [switch]$MaterializePulseTimingStage
  )

  $prepareArguments = @(
    '-m', $prepareModule,
    '--repo-root', $repoRoot,
    '--profile-registry', $profileRegistry,
    '--adapter-registry', $adapterRegistry,
    '--campaign', $campaignPath,
    '--experiment-id', $ExperimentId,
    '--resolved-output', $ResolvedPath,
    '--plan-output', $PlanPath
  )
  if (-not [string]::IsNullOrWhiteSpace($PulseTimingTransition)) {
    $prepareArguments += @('--pulse-timing-transition', $PulseTimingTransition)
  }
  if ($MaterializePulseTimingStage) {
    $prepareArguments += '--materialize-pulse-timing-stage'
  }
  Push-Location $repoRoot
  try {
    & $PythonExe @prepareArguments
    if ($LASTEXITCODE -ne 0) {
      throw 'Family source-closure preparation failed.'
    }
  } finally {
    Pop-Location
  }
}

function Get-CompositionPlanArgumentMap {
  param([Parameter(Mandatory)][string]$PlanPath)

  $plan = Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $steps = @($plan.execution_steps)
  if ($steps.Count -ne 1) {
    throw 'Family source-closure composition plan must contain exactly one step.'
  }
  $arguments = @{}
  foreach ($argument in @($steps[0].arguments)) {
    $parts = ([string]$argument).Split('=', 2)
    if ($parts.Count -ne 2 -or $arguments.ContainsKey($parts[0])) {
      throw 'Family source-closure composition-plan argument is malformed or duplicated.'
    }
    $arguments[$parts[0]] = $parts[1]
  }
  return $arguments
}

function Get-PulseTimingOrchestration {
  param(
    [Parameter(Mandatory)][string]$PlanPath,
    [Parameter(Mandatory)][string]$PreparedRoot
  )

  $arguments = Get-CompositionPlanArgumentMap -PlanPath $PlanPath
  $required = @(
    'pulse_timing_orchestration_filename',
    'pulse_timing_orchestration_sha256',
    'pulse_timing_orchestration_state'
  )
  $presentCount = @($required | Where-Object { $arguments.ContainsKey($_) }).Count
  if ($presentCount -eq 0) {
    return $null
  }
  foreach ($name in $required) {
    if (-not $arguments.ContainsKey($name) -or
        [string]::IsNullOrWhiteSpace([string]$arguments[$name])) {
      throw "Prepared pulse-timing orchestration argument is missing: $name"
    }
  }
  $orchestrationPath = [IO.Path]::GetFullPath((Join-Path `
    $PreparedRoot ([string]$arguments['pulse_timing_orchestration_filename'])))
  if (-not $orchestrationPath.StartsWith(
        ([IO.Path]::GetFullPath($PreparedRoot) + [IO.Path]::DirectorySeparatorChar),
        [StringComparison]::OrdinalIgnoreCase
      ) -or -not (Test-Path -LiteralPath $orchestrationPath -PathType Leaf)) {
    throw 'Prepared pulse-timing orchestration file is missing or escapes its run.'
  }
  $actualSha256 = (Get-FileHash -LiteralPath $orchestrationPath -Algorithm SHA256).Hash
  if ($actualSha256 -ne [string]$arguments['pulse_timing_orchestration_sha256']) {
    throw 'Prepared pulse-timing orchestration SHA-256 differs.'
  }
  $orchestration = Get-Content -LiteralPath $orchestrationPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ([string]$orchestration.role -ne 'rf_oatof_resolved_pulse_timing_orchestration' -or
      [string]$orchestration.state -ne
      [string]$arguments['pulse_timing_orchestration_state'] -or
      [string]$orchestration.campaign_id -ne [string]$campaignDocument.campaign_id -or
      [string]$orchestration.experiment_id -ne $ExperimentId -or
      [string]$orchestration.original_run_id -ne $campaignRunId) {
    throw 'Prepared pulse-timing orchestration identity differs.'
  }
  return $orchestration
}

function Resolve-WorkspaceStagePath {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Label
  )

  $candidate = if ([IO.Path]::IsPathRooted($Path)) {
    $Path
  } else {
    Join-Path $workspaceRoot $Path
  }
  $resolved = [IO.Path]::GetFullPath($candidate)
  if (-not $resolved.StartsWith(
        ([IO.Path]::GetFullPath($workspaceRoot) + [IO.Path]::DirectorySeparatorChar),
        [StringComparison]::OrdinalIgnoreCase
      )) {
    throw "$Label escapes the managed workspace."
  }
  return $resolved
}

function Get-PulseTimingStage {
  param(
    [Parameter(Mandatory)]$Orchestration,
    [Parameter(Mandatory)][string]$ExpectedStageId
  )

  $stage = $Orchestration.stage
  if ($null -eq $stage -or [string]$stage.stage_id -ne $ExpectedStageId) {
    throw "Pulse-timing orchestration does not provide $ExpectedStageId."
  }
  $output = Resolve-WorkspaceStagePath `
    -Path ([string]$stage.output_directory) -Label 'Pulse-timing stage output'
  $resolved = Resolve-WorkspaceStagePath `
    -Path ([string]$stage.resolved_connection.path) `
    -Label 'Pulse-timing stage resolved connection'
  $plan = Resolve-WorkspaceStagePath `
    -Path ([string]$stage.composition_plan.path) `
    -Label 'Pulse-timing stage composition plan'
  foreach ($record in @(
      @{ Label = 'resolved connection'; Path = $resolved; Record = $stage.resolved_connection },
      @{ Label = 'composition plan'; Path = $plan; Record = $stage.composition_plan }
    )) {
    if (-not (Test-Path -LiteralPath $record.Path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $record.Path -Algorithm SHA256).Hash -ne
        [string]$record.Record.sha256) {
      throw "Pulse-timing stage $($record.Label) identity differs."
    }
  }
  return [pscustomobject]@{
    RunId = [string]$stage.run_id
    OutputRoot = $output
    ResolvedPath = $resolved
    PlanPath = $plan
  }
}

function Assert-PulseTimingTarget {
  param([Parameter(Mandatory)]$Orchestration)

  $declaredTarget = Resolve-WorkspaceStagePath `
    -Path ([string]$Orchestration.target_output_directory) `
    -Label 'Pulse-timing target output'
  if ($declaredTarget -ne $outputRoot) {
    throw 'Pulse-timing orchestration target output differs from the requested run.'
  }
}

function Invoke-FamilyExecutionBoundary {
  param(
    [Parameter(Mandatory)][AllowEmptyString()][string]$RunId,
    [Parameter(Mandatory)][string]$ExecutionRoot,
    [Parameter(Mandatory)][string]$ResolvedPath,
    [Parameter(Mandatory)][string]$PlanPath,
    [Parameter(Mandatory)][ValidateSet('ValidateOnly', 'PrepareOnly', 'SolverAuthorized', 'FinalizeOnly')]
      [string]$Mode
  )

  if ($Mode -in @('SolverAuthorized','FinalizeOnly') -and [string]::IsNullOrWhiteSpace($RunId)) {
    throw 'Physical or finalize execution requires a nonempty run ID.'
  }

  $arguments = @{
    CompositionPlan = $PlanPath
    ResolvedConnection = $ResolvedPath
    PythonExe = $PythonExe
    RepoRoot = $repoRoot
  }
  if ($Mode -eq 'ValidateOnly') {
    $arguments.ValidateOnly = $true
  } else {
    $arguments.AdapterEntrypoint = Join-Path $workflowRoot 'adapter.ps1'
    $arguments.RunId = $(if ($Mode -in @('SolverAuthorized','FinalizeOnly')) { $RunId } else { '' })
    if ($Mode -eq 'PrepareOnly') { $arguments.PrepareOnly = $true }
    if ($Mode -eq 'SolverAuthorized') { $arguments.SolverAuthorized = $true }
    if ($Mode -eq 'FinalizeOnly') { $arguments.FinalizeOnly = $true }
  }
  try {
    & $commonExecute @arguments
    if ($LASTEXITCODE -ne 0) {
      throw 'Family source-closure execution boundary failed.'
    }
  } catch {
    $executionError = $_
    $terminalManifest = Join-Path $ExecutionRoot 'run_manifest.json'
    $budgetPath = Join-Path $ExecutionRoot 'resolved_engineering_budget.json'
    if ($Mode -eq 'SolverAuthorized' -and
        -not (Test-Path -LiteralPath $terminalManifest -PathType Leaf) -and
        (Test-Path -LiteralPath $ResolvedPath -PathType Leaf) -and
        (Test-Path -LiteralPath $PlanPath -PathType Leaf) -and
        (Test-Path -LiteralPath $budgetPath -PathType Leaf)) {
      & $PythonExe -m (
        'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
        'workflows.family_source_closure.publish_run'
      ) --repo-root $repoRoot `
        --integration-run-dir $ExecutionRoot `
        --resolved-connection $ResolvedPath `
        --composition-plan $PlanPath `
        --resolved-engineering-budget $budgetPath `
        --terminal-status failed `
        --failure-reason $executionError.Exception.Message
      if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Failed to terminalize the parent integration run after child failure.'
      }
    }
    throw $executionError
  }
}

try {
  $resolvedPath = Join-Path $outputRoot 'resolved_connection.json'
  $planPath = Join-Path $outputRoot 'composition_plan.json'
  $profileRegistry = Join-Path $integrationRoot 'config\connection_profiles.json'
  $adapterRegistry =
    Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
  $prepareModule = (
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
    'workflows.family_source_closure.prepare'
  )

  if ($FinalizeOnly) {
    $sourceParentRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $campaignRunId))
    $resolvedPath = Join-Path $sourceParentRoot 'resolved_connection.json'
    $planPath = Join-Path $sourceParentRoot 'composition_plan.json'
  } else {
    Invoke-FamilyPreparation -ResolvedPath $resolvedPath -PlanPath $planPath `
      -MaterializePulseTimingStage:$SolverAuthorized
  }

  $commonExecute = Join-Path $repoRoot 'common\integration\execute_connection.ps1'
  if ($ValidateOnly) {
    Invoke-FamilyExecutionBoundary -RunId '' -ExecutionRoot $outputRoot `
      -ResolvedPath $resolvedPath -PlanPath $planPath -Mode ValidateOnly
  } elseif ($PrepareOnly) {
    Invoke-FamilyExecutionBoundary -RunId '' -ExecutionRoot $outputRoot `
      -ResolvedPath $resolvedPath -PlanPath $planPath -Mode PrepareOnly
  } elseif ($FinalizeOnly) {
    Invoke-FamilyExecutionBoundary -RunId ($campaignRunId + '__r01') `
      -ExecutionRoot $outputRoot -ResolvedPath $resolvedPath `
      -PlanPath $planPath -Mode FinalizeOnly
    $removeUnpublishedTargetOnExit = $false
  } else {
    $orchestration = Get-PulseTimingOrchestration `
      -PlanPath $planPath -PreparedRoot $outputRoot
    if ($null -eq $orchestration) {
      Invoke-FamilyExecutionBoundary -RunId $campaignRunId `
        -ExecutionRoot $outputRoot -ResolvedPath $resolvedPath `
        -PlanPath $planPath -Mode SolverAuthorized
      $removeUnpublishedTargetOnExit = $false
    } else {
      Assert-PulseTimingTarget -Orchestration $orchestration
      switch ([string]$orchestration.state) {
        'ready_verified' {
          Invoke-FamilyExecutionBoundary -RunId $campaignRunId `
            -ExecutionRoot $outputRoot -ResolvedPath $resolvedPath `
            -PlanPath $planPath -Mode SolverAuthorized
          $removeUnpublishedTargetOnExit = $false
        }
        'confirmation_required' {
          $confirmation = Get-PulseTimingStage `
            -Orchestration $orchestration `
            -ExpectedStageId 'pulse_timing_confirmation'
          if ($confirmation.RunId -ne $campaignRunId -or
              $confirmation.OutputRoot -ne $outputRoot) {
            throw 'Pulse-timing confirmation is not the originally requested run.'
          }
          Invoke-FamilyExecutionBoundary -RunId $confirmation.RunId `
            -ExecutionRoot $confirmation.OutputRoot `
            -ResolvedPath $confirmation.ResolvedPath `
            -PlanPath $confirmation.PlanPath -Mode SolverAuthorized
          $removeUnpublishedTargetOnExit = $false
        }
        'discovery_required' {
          $discovery = Get-PulseTimingStage `
            -Orchestration $orchestration -ExpectedStageId 'pulse_timing_discovery'
          Invoke-FamilyExecutionBoundary -RunId $discovery.RunId `
            -ExecutionRoot $discovery.OutputRoot `
            -ResolvedPath $discovery.ResolvedPath `
            -PlanPath $discovery.PlanPath -Mode SolverAuthorized
          $transitionPath = [IO.Path]::GetFullPath((Join-Path `
            $discovery.OutputRoot `
            ([string]$orchestration.transition_relative_path)))
          if (-not $transitionPath.StartsWith(
                ($discovery.OutputRoot + [IO.Path]::DirectorySeparatorChar),
                [StringComparison]::OrdinalIgnoreCase
              ) -or -not (Test-Path -LiteralPath $transitionPath -PathType Leaf)) {
            throw 'Pulse-timing discovery did not publish its declared transition.'
          }
          Invoke-FamilyPreparation -ResolvedPath $resolvedPath -PlanPath $planPath `
            -PulseTimingTransition $transitionPath
          $confirmationOrchestration = Get-PulseTimingOrchestration `
            -PlanPath $planPath -PreparedRoot $outputRoot
          if ([string]$confirmationOrchestration.state -ne 'confirmation_required') {
            throw 'Pulse-timing discovery did not advance to confirmation_required.'
          }
          Assert-PulseTimingTarget -Orchestration $confirmationOrchestration
          $confirmation = Get-PulseTimingStage `
            -Orchestration $confirmationOrchestration `
            -ExpectedStageId 'pulse_timing_confirmation'
          if ($confirmation.RunId -ne $campaignRunId -or
              $confirmation.OutputRoot -ne $outputRoot) {
            throw 'Pulse-timing confirmation is not the originally requested run.'
          }
          Invoke-FamilyExecutionBoundary -RunId $confirmation.RunId `
            -ExecutionRoot $confirmation.OutputRoot `
            -ResolvedPath $confirmation.ResolvedPath `
            -PlanPath $confirmation.PlanPath -Mode SolverAuthorized
          $removeUnpublishedTargetOnExit = $false
        }
        default {
          throw 'Prepared pulse-timing orchestration state is unsupported.'
        }
      }
    }
  }
} finally {
  if (-not [string]::IsNullOrWhiteSpace($unpublishedDiscoveryRoot) -and
      (Test-Path -LiteralPath $unpublishedDiscoveryRoot) -and
      -not (Test-Path -LiteralPath (
        Join-Path $unpublishedDiscoveryRoot 'run_manifest.json'
      ))) {
    $managedRunsRoot = [IO.Path]::GetFullPath($runsRoot)
    if (-not $unpublishedDiscoveryRoot.StartsWith(
          ($managedRunsRoot + [IO.Path]::DirectorySeparatorChar),
          [StringComparison]::OrdinalIgnoreCase
        )) {
      throw 'Unpublished discovery cleanup escaped the managed runs root.'
    }
    Remove-Item -LiteralPath $unpublishedDiscoveryRoot -Recurse -Force
  }
  if ($removeUnpublishedTargetOnExit -and
      (Test-Path -LiteralPath $outputRoot) -and
      -not (Test-Path -LiteralPath (Join-Path $outputRoot 'run_manifest.json'))) {
    $managedRunsRoot = [IO.Path]::GetFullPath($runsRoot)
    if (-not $outputRoot.StartsWith(
          ($managedRunsRoot + [IO.Path]::DirectorySeparatorChar),
          [StringComparison]::OrdinalIgnoreCase
        )) {
      throw 'Unpublished target cleanup escaped the managed runs root.'
    }
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
  }
  if ($cleanupOutput -and (Test-Path -LiteralPath $outputRoot)) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
  }
  if ($cleanupOutput -and (Test-Path -LiteralPath $validationRoot) -and
      @(Get-ChildItem -LiteralPath $validationRoot -Force).Count -eq 0) {
    Remove-Item -LiteralPath $validationRoot -Force -ErrorAction SilentlyContinue
  }
}
