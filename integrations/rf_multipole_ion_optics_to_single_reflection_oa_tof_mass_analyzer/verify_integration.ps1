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

function Invoke-CheckedPythonCommand {
    param(
        [Parameter(Mandatory)][string[]]$CommandArguments,
        [Parameter(Mandatory)][string]$FailureMessage
    )
    & $PythonExe @CommandArguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$FailureMessage Exit code: $exitCode."
    }
}

Push-Location $repoRoot
try {
    Invoke-CheckedPythonCommand -CommandArguments @(
        '-m', 'ruff', 'check',
        (Join-Path $repoRoot 'common\integration'),
        $integrationRoot
    ) -FailureMessage (
        'RF multipole to single-reflection oaTOF integration Ruff gate failed.'
    )
    Invoke-CheckedPythonCommand -CommandArguments @(
        '-m', 'unittest', 'discover',
        '-s', (Join-Path $integrationRoot 'tests'),
        '-p', 'test_*.py'
    ) -FailureMessage (
        'RF multipole to single-reflection oaTOF integration tests failed.'
    )
}
finally {
    Pop-Location
}

Write-Output "INTEGRATION_GATE=PASS FAMILY=rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
