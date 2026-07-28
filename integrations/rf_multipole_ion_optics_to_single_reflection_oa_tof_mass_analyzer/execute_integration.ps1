[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConnectionProfileId,
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

$integrationRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python 3.11 executable not found: $PythonExe"
}
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$resolvedPath = Join-Path $outputRoot 'resolved_connection.json'
$planPath = Join-Path $outputRoot 'composition_plan.json'
$profileRegistry = Join-Path $integrationRoot 'config\connection_profiles.json'
$adapterRegistry = Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
$preregistration = Join-Path $integrationRoot 'config\migration_equivalence_preregistration.json'
$prepareModule = (
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
    'prepare_migration'
)

Push-Location $repoRoot
try {
    & $PythonExe -m $prepareModule `
        --repo-root $repoRoot `
        --profile-registry $profileRegistry `
        --adapter-registry $adapterRegistry `
        --preregistration $preregistration `
        --profile-id $ConnectionProfileId `
        --resolved-output $resolvedPath `
        --plan-output $planPath
    if ($LASTEXITCODE -ne 0) { throw 'Integration migration preparation failed.' }
}
finally {
    Pop-Location
}

$commonExecute = Join-Path $repoRoot 'common\integration\execute_connection.ps1'
$commonArguments = @{
    CompositionPlan = $planPath
    ResolvedConnection = $resolvedPath
    PythonExe = $PythonExe
    RepoRoot = $repoRoot
}
if ($ValidateOnly) {
    $commonArguments.ValidateOnly = $true
}
else {
    $commonArguments.AdapterEntrypoint = Join-Path $integrationRoot 'adapter.ps1'
    $commonArguments.RunId = $RunId
    if ($PrepareOnly) { $commonArguments.PrepareOnly = $true }
    if ($SolverAuthorized) { $commonArguments.SolverAuthorized = $true }
}
& $commonExecute @commonArguments
if ($LASTEXITCODE -ne 0) {
    throw 'Public integration execution boundary failed.'
}
