[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][ValidateSet('comsol','simion')]
  [string]$SourceBranchId,
  [string]$SourceRevisionId = 'baseline',
  [Parameter(Mandatory)][string]$OutputDirectory,
  [string]$RunId = '',
  [string]$PythonExe = '',
  [switch]$ValidateOnly,
  [switch]$PrepareOnly,
  [switch]$SolverAuthorized
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($ValidateOnly -and $PrepareOnly) {
  throw 'ValidateOnly and PrepareOnly are mutually exclusive.'
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

$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
if ($SolverAuthorized) {
  & $PythonExe -m common.contracts.artifact_naming run $RunId
  if ($LASTEXITCODE -ne 0) {
    throw 'Solver-authorized execution requires one valid explicit RunId.'
  }
  $workspaceRoot = Split-Path -Parent $repoRoot
  $runsRoot = Join-Path $workspaceRoot (
    'artifacts\projects\' +
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs'
  )
  $canonicalOutput = [IO.Path]::GetFullPath((Join-Path $runsRoot $RunId))
  if (-not $outputRoot.Equals(
      $canonicalOutput,
      [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'Solver execution OutputDirectory must be the canonical RunId directory.'
  }
}
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null

$resolvedPath = Join-Path $outputRoot 'resolved_connection.json'
$planPath = Join-Path $outputRoot 'composition_plan.json'
$profileRegistry = Join-Path $integrationRoot 'config\connection_profiles.json'
$adapterRegistry =
  Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
$preregistration = Join-Path $integrationRoot (
  'config\family_source_closure_preregistration.json'
)
$revisionRegistry = Join-Path $integrationRoot (
  'config\family_source_revision_registry.json'
)
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
    --preregistration $preregistration `
    --revision-registry $revisionRegistry `
    --profile-id $ConnectionProfileId `
    --source-branch-id $SourceBranchId `
    --source-revision-id $SourceRevisionId `
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
  $arguments.RunId = $RunId
  if ($PrepareOnly) { $arguments.PrepareOnly = $true }
  if ($SolverAuthorized) { $arguments.SolverAuthorized = $true }
}
& $commonExecute @arguments
if ($LASTEXITCODE -ne 0) {
  throw 'Family source-closure execution boundary failed.'
}
