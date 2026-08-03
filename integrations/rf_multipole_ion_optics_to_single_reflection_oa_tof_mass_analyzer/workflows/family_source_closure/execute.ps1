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
$campaignDocument = Get-Content -LiteralPath $campaignPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$experimentRows = @($campaignDocument.experiments | Where-Object {
  $_.experiment_id -eq $ExperimentId
})
if ($experimentRows.Count -ne 1) {
  throw 'Campaign experiment must resolve exactly once.'
}
$campaignRunId = [string]$experimentRows[0].run_id

$workspaceRoot = Split-Path -Parent $repoRoot
$cleanupOutput = $ValidateOnly
if ($ValidateOnly) {
  $validationRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' +
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\' +
    'validation_tmp'
  )
  $outputRoot = Join-Path $validationRoot (
    'validate-' + [guid]::NewGuid().ToString('N')
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
  New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
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
  & $commonExecute @arguments
  if ($LASTEXITCODE -ne 0) {
    throw 'Family source-closure execution boundary failed.'
  }
} finally {
  if ($cleanupOutput -and (Test-Path -LiteralPath $outputRoot)) {
    Remove-Item -LiteralPath $outputRoot -Recurse -Force
  }
  if ($cleanupOutput -and (Test-Path -LiteralPath $validationRoot) -and
      @(Get-ChildItem -LiteralPath $validationRoot -Force).Count -eq 0) {
    Remove-Item -LiteralPath $validationRoot -Force
  }
}
