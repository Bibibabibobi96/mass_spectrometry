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
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/host_execution_lease.ps1')
$lease = Enter-HostExecutionLease -Role GATE
try {
    if (($PreflightOnly -and $SelectedTestModules.Count) -or
        (($PreflightOnly -or $SelectedTestModules.Count) -and $ChangedTestModules.Count) -or
        ($PreflightValidated -and -not $SelectedTestModules.Count)) {
        throw 'Integration preflight and selected test modules are mutually exclusive with changed-test selection.'
    }
    if (-not $PythonExe) { $PythonExe = Join-Path $repoRoot '.venv/Scripts/python.exe' }
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Python 3.11 executable not found: $PythonExe"
    }
    $version = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0 -or $version -ne '3.11') {
        throw "Integration gate requires Python 3.11, found $version at $PythonExe"
    }
    Push-Location $repoRoot
    try {
        if (-not $PreflightValidated) {
            & $PythonExe -m ruff check integrations/runtime integrations/analysis integrations/workflows integrations/tests
            if ($LASTEXITCODE -ne 0) { throw 'Instrument assembly Ruff gate failed.' }
        }
        if ($PreflightOnly) {
            Write-Output 'INTEGRATION_PREFLIGHT=PASS PYTHON_TESTS=DEFERRED'
            return
        }
        $discovered = @(
            Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'tests') -Filter 'test_*.py' -File -Recurse |
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
        & $PythonExe -m common.gate_unittest @testModules -v
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
    Exit-HostExecutionLease -Lease $lease
}
