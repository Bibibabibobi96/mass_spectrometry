[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Campaign,
  [string]$ExperimentId = '',
  [switch]$AllExperiments,
  [string]$OutputDirectory = '',
  [string]$PythonExe = '',
  [string]$SemanticDiffAgainst = '',
  [switch]$ValidateOnly,
  [switch]$PrepareOnly,
  [switch]$Exploration,
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
if ([string]::IsNullOrWhiteSpace($SemanticDiffAgainst) -and $selectedModeCount -ne 1) {
  throw 'Select exactly one of ValidateOnly, PrepareOnly, SolverAuthorized or FinalizeOnly.'
}
if (-not [string]::IsNullOrWhiteSpace($SemanticDiffAgainst) -and $selectedModeCount -ne 0) {
  throw 'SemanticDiffAgainst cannot be combined with an execution mode.'
}
if ($AllExperiments -and -not [string]::IsNullOrWhiteSpace($ExperimentId)) {
  throw 'AllExperiments and ExperimentId are mutually exclusive.'
}
if ($AllExperiments -and -not [string]::IsNullOrWhiteSpace($SemanticDiffAgainst)) {
  throw 'AllExperiments and SemanticDiffAgainst are mutually exclusive.'
}
if (-not $AllExperiments -and [string]::IsNullOrWhiteSpace($ExperimentId)) {
  throw 'ExperimentId is required unless AllExperiments is selected.'
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
  $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
  if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $PythonExe = $venvPython
  }
  else {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
  }
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
  throw "Python 3.11 executable not found: $PythonExe"
}
$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') {
  throw "Family source closure requires Python 3.11, found $pythonVersion at $PythonExe"
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
$campaignRepoRelative = [IO.Path]::GetRelativePath($repoRoot, $campaignPath).Replace('\', '/')
$campaignDocument = Get-Content -LiteralPath $campaignPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
if ($Exploration) {
  if ([string]$campaignDocument.status -in @('retired', 'archived_invalid')) {
    throw 'Retired or invalid campaigns are not executable in any mode.'
  }
  if ([string]$campaignDocument.role -ne 'rf_multipole_oatof_experiment_campaign' -or
      [string]$campaignDocument.status -ne 'exploration') {
    throw 'Exploration requires an experiment campaign with campaign.status=exploration.'
  }
} else {
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
}
if ($FinalizeOnly -and [string]$campaignDocument.status -ne 'authorized') {
  throw 'FinalizeOnly execution requires campaign.status=authorized.'
}
if ($SolverAuthorized -and [string]$campaignDocument.status -ne 'authorized' -and
    -not ($Exploration -and [string]$campaignDocument.status -eq 'exploration')) {
  throw 'SolverAuthorized execution requires an authorized campaign or explicit exploration status.'
}
if ($AllExperiments) {
  $prepareModule = (
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
    'workflows.family_source_closure.prepare'
  )
  $profileRegistry = Join-Path $integrationRoot 'config\connection_profiles.json'
  $adapterRegistry = Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
  $experimentIds = @(& $PythonExe -m $prepareModule --repo-root $repoRoot `
    --profile-registry $profileRegistry --adapter-registry $adapterRegistry `
    --campaign $campaignPath --list-experiment-ids)
  if ($LASTEXITCODE -ne 0 -or $experimentIds.Count -lt 1) {
    throw 'Could not resolve ordered experiment IDs from the campaign.'
  }
  foreach ($nextExperimentId in $experimentIds) {
    $childParameters = @{
      Campaign = $Campaign; ExperimentId = [string]$nextExperimentId; PythonExe = $PythonExe
    }
    if ($ValidateOnly) { $childParameters.ValidateOnly = $true }
    elseif ($SolverAuthorized) { $childParameters.SolverAuthorized = $true }
    elseif ($FinalizeOnly) { $childParameters.FinalizeOnly = $true }
    else { throw 'AllExperiments does not support PrepareOnly because each row requires its own review directory.' }
    & $PSCommandPath @childParameters
    if ($LASTEXITCODE -ne 0) { throw "Campaign sequence stopped at experiment: $nextExperimentId" }
  }
  return
}
$prepareModule = (
  'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
  'workflows.family_source_closure.prepare'
)
$profileRegistry = Join-Path $integrationRoot 'config\connection_profiles.json'
$adapterRegistry = Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
if (-not [string]::IsNullOrWhiteSpace($SemanticDiffAgainst)) {
  & $PythonExe -m $prepareModule --repo-root $repoRoot `
    --profile-registry $profileRegistry --adapter-registry $adapterRegistry `
    --campaign $campaignPath --semantic-diff-experiment-json $ExperimentId $SemanticDiffAgainst
  if ($LASTEXITCODE -ne 0) {
    throw 'Campaign semantic diff must resolve exactly two experiments.'
  }
  return
}
$selectedExperimentJson = & $PythonExe -m $prepareModule --repo-root $repoRoot `
  --profile-registry $profileRegistry --adapter-registry $adapterRegistry `
  --campaign $campaignPath --print-experiment-json $ExperimentId
if ($LASTEXITCODE -ne 0) {
  throw 'Campaign experiment must resolve exactly once.'
}
$experimentRows = @($selectedExperimentJson | ConvertFrom-Json)
if ($experimentRows.Count -ne 1) {
  throw 'Campaign experiment must resolve exactly once.'
}
$selectedExperiment = $experimentRows[0]
if (-not $FinalizeOnly -and -not $Exploration) {
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
$workspaceRoot = Split-Path -Parent $repoRoot
$executionRunId = $campaignRunId
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
  $publishedManifestPath = Join-Path $outputRoot 'run_manifest.json'
  if (Test-Path -LiteralPath $publishedManifestPath -PathType Leaf) {
    $publishedManifest = Get-Content -LiteralPath $publishedManifestPath -Raw |
      ConvertFrom-Json
    # Parent manifests intentionally list only materialized run inputs.  The
    # campaign identity is frozen in the composition-plan step arguments.
    $publishedCampaignSha256 = ''
    $publishedPlanPath = Join-Path $outputRoot 'composition_plan.json'
    if (Test-Path -LiteralPath $publishedPlanPath -PathType Leaf) {
      $publishedPlan = Get-Content -LiteralPath $publishedPlanPath -Raw |
        ConvertFrom-Json
      $publishedCampaignArgument = @($publishedPlan.execution_steps |
        ForEach-Object { @($_.arguments | Where-Object {
          [string]$_ -like 'campaign_sha256=*'
        }) } | Select-Object -First 1)
      if ($publishedCampaignArgument.Count -eq 1) {
        $publishedCampaignSha256 = ([string]$publishedCampaignArgument[0]).Substring(
          'campaign_sha256='.Length
        )
      }
    }
    if ($publishedManifest.role -eq 'simulation_run_manifest' -and
        $publishedManifest.status -eq 'success' -and
        $publishedManifest.run_id -eq $campaignRunId -and
        $publishedCampaignSha256.ToUpperInvariant() -eq $campaignSha256.ToUpperInvariant()) {
      Write-Output 'INTEGRATION_EXECUTION=ALREADY_SUCCESS'
      return
    }
  }
  # Preserve the failed run as evidence, then make exactly one explicitly
  # named recovery attempt.  A failed recovery itself is evidence too, so the
  # next unused suffix may be attempted only when its immediate predecessor is
  # a failed manifest.  This keeps an --AllExperiments campaign continuous
  # without ever overwriting a solver result.
  if ($publishedManifest.role -eq 'simulation_run_manifest' -and
      $publishedManifest.status -eq 'failed') {
    $publishedRecovery = @(Get-ChildItem -LiteralPath $runsRoot -Directory `
      -Filter ($campaignRunId + '__r??') | ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'run_manifest.json'
        if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
          Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        }
      } | Where-Object {
        $_.role -eq 'simulation_run_manifest' -and $_.status -eq 'success' -and
        $_.mode -eq 'multipole_family_source_closure'
      })
    if ($publishedRecovery.Count -gt 0) {
      Write-Output 'INTEGRATION_EXECUTION=ALREADY_RECOVERED_SUCCESS'
      return
    }
    $retryIndex = 1
    do {
      $executionRunId = $campaignRunId + ('__r{0:D2}' -f $retryIndex)
      $outputRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $executionRunId))
      $retryIndex += 1
    } while (Test-Path -LiteralPath $outputRoot)
    $outputRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $executionRunId))
    Write-Output "INTEGRATION_EXECUTION=RECOVER_FAILED_RUN PARENT=$campaignRunId RETRY=$executionRunId"
  } else {
    throw 'SolverAuthorized target run directory already exists.'
  }
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
    [switch]$MaterializePulseTimingStage,
    [switch]$Exploration
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
  if ($Exploration) {
    $prepareArguments += '--exploration'
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
      -MaterializePulseTimingStage:$SolverAuthorized -Exploration:$Exploration
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
      Invoke-FamilyExecutionBoundary -RunId $executionRunId `
        -ExecutionRoot $outputRoot -ResolvedPath $resolvedPath `
        -PlanPath $planPath -Mode SolverAuthorized
      $removeUnpublishedTargetOnExit = $false
    } else {
      Assert-PulseTimingTarget -Orchestration $orchestration
      switch ([string]$orchestration.state) {
        'ready_verified' {
          Invoke-FamilyExecutionBoundary -RunId $executionRunId `
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
