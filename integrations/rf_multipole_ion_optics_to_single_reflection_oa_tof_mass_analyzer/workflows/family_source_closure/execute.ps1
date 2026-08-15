[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Campaign,
  [Parameter(Mandatory)][string]$ExperimentId,
  [string]$OutputDirectory = '',
  [string]$PythonExe = '',
  [switch]$ValidateOnly,
  [switch]$PrepareOnly,
  [switch]$SolverAuthorized
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$selectedModeCount = (
  [int][bool]$ValidateOnly +
  [int][bool]$PrepareOnly +
  [int][bool]$SolverAuthorized
)
if ($selectedModeCount -ne 1) {
  throw 'Select exactly one of ValidateOnly, PrepareOnly or SolverAuthorized.'
}
if ($PrepareOnly -and [string]::IsNullOrWhiteSpace($OutputDirectory)) {
  throw 'PrepareOnly requires an explicit OutputDirectory for review.'
}
if (-not $PrepareOnly -and
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
$legacyDispositionPath = Join-Path $integrationRoot `
  'config\family_source_closure_legacy_attribution_migration.json'
$legacyDisposition = Get-Content -LiteralPath $legacyDispositionPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$expectedActiveWorkflow = 'workflows/family_source_closure/execute.ps1'
if ([string]$legacyDisposition.active_workflow -ne $expectedActiveWorkflow) {
  throw 'Legacy attribution disposition does not name this active workflow.'
}
$campaignRepoRelative = [IO.Path]::GetRelativePath($repoRoot, $campaignPath).Replace('\', '/')
$registeredCampaigns = @(
  @($legacyDisposition.historical_campaigns) +
  @($legacyDisposition.current_evidence_campaigns)
)
$registeredCampaigns = @($registeredCampaigns | Where-Object {
  [string]$_.path -eq $campaignRepoRelative
})
if ($registeredCampaigns.Count -gt 1) {
  throw 'Terminal campaign disposition must resolve at most once.'
}
if ($registeredCampaigns.Count -eq 1) {
  $registeredCampaign = $registeredCampaigns[0]
  $registeredCampaignSha256 = (
    Get-FileHash -LiteralPath $campaignPath -Algorithm SHA256
  ).Hash.ToLowerInvariant()
  if (-not ([string]$registeredCampaign.disposition).StartsWith('non_executable_') -or
      $registeredCampaignSha256 -ne
      ([string]$registeredCampaign.content_sha256).ToLowerInvariant()) {
    throw 'Terminal campaign disposition identity differs; execution remains forbidden.'
  }
  throw 'Campaign is registered non-executable evidence in ValidateOnly, PrepareOnly and SolverAuthorized modes.'
}
$campaignDocument = Get-Content -LiteralPath $campaignPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
if ($SolverAuthorized -and [string]$campaignDocument.status -ne 'authorized') {
  throw 'SolverAuthorized execution requires campaign.status=authorized.'
}
$experimentRows = @($campaignDocument.experiments | Where-Object {
  $_.experiment_id -eq $ExperimentId
})
if ($experimentRows.Count -ne 1) {
  throw 'Campaign experiment must resolve exactly once.'
}
$selectedExperiment = $experimentRows[0]
$isStagedGrid2 =
  [string]$selectedExperiment.source_release_mode -eq 'staged_grid2_restart'
if ($SolverAuthorized -and $isStagedGrid2 -and (
    [int]$campaignDocument.schema_version -ne 5 -or
    $null -eq $selectedExperiment.staged_grid2_source_state -or
    -not ($selectedExperiment.staged_grid2_source_state.PSObject.Properties.Name `
      -contains 'loader_authorization_budget'))) {
  throw 'SolverAuthorized staged grid2 execution requires campaign v5 with an explicit loader authorization budget.'
}
& $PythonExe -m (
  'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
  'workflows.family_source_closure.refresh_campaign_source_bindings'
) --repo-root $repoRoot --campaign $campaignPath --check
if ($LASTEXITCODE -ne 0) {
  throw 'Campaign source bindings must be refreshed before execution.'
}
$campaignRunId = [string]$experimentRows[0].run_id
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
} else {
  & $PythonExe -m common.contracts.artifact_naming run $campaignRunId
  if ($LASTEXITCODE -ne 0) {
    throw 'Campaign row run_id fails the repository artifact naming contract.'
  }
  $runsRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' +
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs'
  )
  $outputRoot = [IO.Path]::GetFullPath((Join-Path $runsRoot $campaignRunId))
}
$outputRoot = [IO.Path]::GetFullPath($outputRoot)

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

  Push-Location $repoRoot
  try {
    & $PythonExe -m $prepareModule `
      --repo-root $repoRoot `
      --profile-registry $profileRegistry `
      --adapter-registry $adapterRegistry `
      --campaign $campaignPath `
      --experiment-id $ExperimentId `
      --resolved-output $resolvedPath `
      --plan-output $planPath
    if ($LASTEXITCODE -ne 0) {
      throw 'Family source-closure preparation failed.'
    }
  } finally {
    Pop-Location
  }

  $commonExecute = Join-Path $repoRoot 'common\integration\execute_connection.ps1'
  $arguments = @{
    CompositionPlan = $planPath
    ResolvedConnection = $resolvedPath
    PythonExe = $PythonExe
    RepoRoot = $repoRoot
  }
  if ($ValidateOnly) {
    $arguments.ValidateOnly = $true
  } else {
    $arguments.AdapterEntrypoint = Join-Path $workflowRoot 'adapter.ps1'
    $arguments.RunId = $(if ($SolverAuthorized) { $campaignRunId } else { '' })
    if ($PrepareOnly) { $arguments.PrepareOnly = $true }
    if ($SolverAuthorized) { $arguments.SolverAuthorized = $true }
  }
  try {
    & $commonExecute @arguments
    if ($LASTEXITCODE -ne 0) {
      throw 'Family source-closure execution boundary failed.'
    }
  } catch {
    $executionError = $_
    $terminalManifest = Join-Path $outputRoot 'run_manifest.json'
    $budgetPath = Join-Path $outputRoot 'resolved_engineering_budget.json'
    if ($SolverAuthorized -and
        -not (Test-Path -LiteralPath $terminalManifest -PathType Leaf) -and
        (Test-Path -LiteralPath $resolvedPath -PathType Leaf) -and
        (Test-Path -LiteralPath $planPath -PathType Leaf) -and
        (Test-Path -LiteralPath $budgetPath -PathType Leaf)) {
      & $PythonExe -m (
        'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
        'workflows.family_source_closure.publish_run'
      ) --repo-root $repoRoot `
        --integration-run-dir $outputRoot `
        --resolved-connection $resolvedPath `
        --composition-plan $planPath `
        --resolved-engineering-budget $budgetPath `
        --terminal-status failed `
        --failure-reason $executionError.Exception.Message
      if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Failed to terminalize the parent integration run after child failure.'
      }
    }
    throw $executionError
  }
} finally {
  if ($cleanupOutput -and (Test-Path -LiteralPath $outputRoot)) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
  }
  if ($cleanupOutput -and (Test-Path -LiteralPath $validationRoot) -and
      @(Get-ChildItem -LiteralPath $validationRoot -Force).Count -eq 0) {
    Remove-Item -LiteralPath $validationRoot -Force -ErrorAction SilentlyContinue
  }
}
