[CmdletBinding()]
param(
    [string]$PythonExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$integrationRoot = $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $integrationRoot)
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python 3.11 executable not found: $PythonExe"
}

$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') {
    throw "Integration gate requires Python 3.11, found $pythonVersion at $PythonExe"
}

Push-Location $repoRoot
try {
    & $PythonExe -m ruff check `
        (Join-Path $repoRoot 'common\integration') `
        $integrationRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'RF multipole to single-reflection oaTOF integration Ruff gate failed.'
    }
    & $PythonExe -m unittest discover `
        -s (Join-Path $integrationRoot 'tests') `
        -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) {
        throw 'RF multipole to single-reflection oaTOF integration tests failed.'
    }
}
finally {
    Pop-Location
}

Write-Output "INTEGRATION_GATE=PASS FAMILY=rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
