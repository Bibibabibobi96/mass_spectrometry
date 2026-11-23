[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string[]]$ChangedTestModules = @(),
    [string[]]$SelectedTestModules = @(),
    [switch]$PreflightOnly,
    [switch]$PreflightValidated
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
. (Join-Path $executionResources 'require_powershell7.ps1')
$lease = $null
try {
    if (($PreflightOnly -and $SelectedTestModules.Count) -or
        (($PreflightOnly -or $SelectedTestModules.Count) -and $ChangedTestModules.Count) -or
        ($PreflightValidated -and -not $SelectedTestModules.Count)) {
        throw 'Integration preflight and selected test modules are mutually exclusive with changed-test selection.'
    }
    if (-not $PythonExe) { $PythonExe = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' } }
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Python 3.11 executable not found: $PythonExe"
    }
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
    $version = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or $version -ne '3.11') {
        throw "Integration gate requires Python 3.11, found $version at $PythonExe"
    }
    $hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Join-Path (Split-Path -Parent $repoRoot) 'artifacts/common/host_resources.sqlite3' }
    $hostContext = @{workspace=(Split-Path -Parent $repoRoot);python_executable=$PythonExe;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
    . (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
    $lease = Enter-HostExecutionLease -Role GATE
    Push-Location $repoRoot
    try {
        if (-not $PreflightValidated) {
            & $PythonExe -m ruff check src/msplatform tests/integration
            if ($LASTEXITCODE -ne 0) { throw 'Instrument assembly Ruff gate failed.' }
        }
        if ($PreflightOnly) {
            Write-Output 'INTEGRATION_PREFLIGHT=PASS PYTHON_TESTS=DEFERRED'
            return
        }
        $discovered = @(
            Get-ChildItem -LiteralPath (Join-Path $repoRoot 'tests/integration') -Filter 'test_*.py' -File -Recurse |
                ForEach-Object {
                    $_.FullName.Substring($repoRoot.Length + 1, $_.FullName.Length - $repoRoot.Length - 4).Replace('\', '.')
                }
        )
        if ($SelectedTestModules.Count) {
            $testModules = @($SelectedTestModules | Sort-Object -Unique)
            if ($testModules.Count -ne $SelectedTestModules.Count -or
                @($testModules | Where-Object { $_ -notin $discovered }).Count) {
                throw 'Integration test partition has duplicate, missing or foreign modules.'
            }
        } else {
            $testModules = @($discovered + $ChangedTestModules | Sort-Object -Unique)
        }
        & $PythonExe -m tools.repository.gate_unittest @testModules -v
        if ($LASTEXITCODE -ne 0) { throw 'Instrument assembly tests failed.' }
        if ($SelectedTestModules.Count) {
            Write-Output "INTEGRATION_TEST_PARTITION=PASS PREFLIGHT_PREVALIDATED=$([bool]$PreflightValidated) FULL_INTEGRATION_GATE=False"
            return
        }
    } finally {
        Pop-Location
    }
    Write-Output 'INTEGRATION_GATE=PASS OWNER=instrument_assembly'
} finally {
    if ($null -ne $lease) { Exit-HostExecutionLease -Lease $lease }
}
