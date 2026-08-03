[CmdletBinding()]
param([string]$PythonExe)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectDir)
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Formal Python environment is missing: $PythonExe. See analysis/README.md."
}
$version = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne '3.11') {
    throw "Formal analysis requires Python 3.11; detected '$version'."
}
& $PythonExe -c "import numpy, scipy, pandas, matplotlib, openpyxl"
if ($LASTEXITCODE -ne 0) { throw 'Formal Python dependencies are incomplete.' }
& $PythonExe (Join-Path $PSScriptRoot 'verify_formal_validation.py')
if ($LASTEXITCODE -ne 0) {
    throw "Formal cross-solver validation gate failed with exit code $LASTEXITCODE."
}
Write-Host 'REFERENCE_ANALYSIS_STATUS=PASS'
