[CmdletBinding()]
param(
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        $PythonExe = $venvPython
    }
    else {
        $PythonExe = (Get-Command python -ErrorAction Stop).Source
    }
}
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Python runtime missing: $PythonExe"
}
$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') {
    throw "Lightweight gate requires Python 3.11, found $pythonVersion at $PythonExe"
}

& (Join-Path $PSScriptRoot 'verify_documentation.ps1')
& (Join-Path $repoRoot 'projects\oa_tof\verify_project.ps1') -Level Static -PythonExe $PythonExe
& (Join-Path $repoRoot 'projects\rf_quadrupole_collision_cooling\verify_project.ps1') -Level Static -PythonExe $PythonExe

Write-Output "LIGHTWEIGHT_GATE=PASS PYTHON=$pythonVersion"
