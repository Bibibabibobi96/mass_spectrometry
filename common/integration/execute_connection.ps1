param(
    [Parameter(Mandatory = $true)]
    [string]$CompositionPlan,
    [Parameter(Mandatory = $true)]
    [string]$ResolvedConnection,
    [string]$PythonExe,
    [string]$RepoRoot,
    [switch]$ValidateOnly,
    [switch]$PrepareOnly,
    [string]$AdapterEntrypoint = '',
    [string]$RunId = '',
    [switch]$SolverAuthorized
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'execute_connection.ps1 requires PowerShell Core 7.'
}

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $RepoRoot) {
    $RepoRoot = $workspaceRoot
}
if (-not $PythonExe) {
    $PythonExe = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python 3.11 executable not found: $PythonExe"
}

& $PythonExe -m common.integration.resolve_connection `
    --verify-plan $CompositionPlan `
    --resolved $ResolvedConnection `
    --verify-repo-root $RepoRoot
if ($LASTEXITCODE -ne 0) {
    throw 'Composition plan validation failed.'
}

if ($ValidateOnly) {
    Write-Output 'INTEGRATION_EXECUTION=VALIDATED'
    exit 0
}

if ([string]::IsNullOrWhiteSpace($AdapterEntrypoint)) {
    throw ('INTEGRATION_EXECUTION_ADAPTER_REQUIRED: the public contract layer validates and ' +
        'freezes composition; an integration-owned adapter is required for preparation or execution.')
}
$AdapterEntrypoint = [IO.Path]::GetFullPath($AdapterEntrypoint)
if (-not (Test-Path -LiteralPath $AdapterEntrypoint -PathType Leaf)) {
    throw "Integration-owned adapter is missing: $AdapterEntrypoint"
}
$integrationRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot 'integrations'))
$integrationPrefix = $integrationRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) +
    [IO.Path]::DirectorySeparatorChar
if (-not $AdapterEntrypoint.StartsWith(
        $integrationPrefix,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "Integration adapter must be owned by the repository integrations tree: $AdapterEntrypoint"
}
$planDocument = Get-Content -LiteralPath $CompositionPlan -Raw | ConvertFrom-Json
if ($planDocument.execution_steps.Count -ne 1) {
    throw 'Executable composition plan must contain exactly one integration-owned step.'
}
$plannedEntrypoint = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot ([string]$planDocument.execution_steps[0].entrypoint))
)
if (-not [string]::Equals(
        $AdapterEntrypoint,
        $plannedEntrypoint,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'AdapterEntrypoint differs from the frozen composition plan.'
}
if (-not $PrepareOnly) {
    if ([string]::IsNullOrWhiteSpace($RunId)) {
        throw 'Physical integration execution requires an explicit RunId.'
    }
    if (-not $SolverAuthorized) {
        throw 'Physical integration execution requires explicit solver authorization.'
    }
}
$adapterArguments = @{
    CompositionPlan = [IO.Path]::GetFullPath($CompositionPlan)
    ResolvedConnection = [IO.Path]::GetFullPath($ResolvedConnection)
    PythonExe = $PythonExe
    RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
    RunId = $RunId
}
if ($PrepareOnly) { $adapterArguments.PrepareOnly = $true }
if ($SolverAuthorized) { $adapterArguments.SolverAuthorized = $true }
& $AdapterEntrypoint @adapterArguments
if ($LASTEXITCODE -ne 0) {
    throw 'Integration-owned adapter failed.'
}
