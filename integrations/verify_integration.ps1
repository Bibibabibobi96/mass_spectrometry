[CmdletBinding()]
param([string]$PythonExe = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/host_execution_lease.ps1')
$lease = Enter-HostExecutionLease -Role GATE
try {
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
        & $PythonExe -m ruff check integrations/runtime integrations/analysis integrations/workflows integrations/tests
        if ($LASTEXITCODE -ne 0) { throw 'Instrument assembly Ruff gate failed.' }
        & $PythonExe -m unittest discover -s integrations/tests -p 'test_*.py' -v
        if ($LASTEXITCODE -ne 0) { throw 'Instrument assembly tests failed.' }
    } finally {
        Pop-Location
    }
    Write-Output 'INTEGRATION_GATE=PASS OWNER=instrument_assembly'
} finally {
    Exit-HostExecutionLease -Lease $lease
}
