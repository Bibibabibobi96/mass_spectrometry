[CmdletBinding()]
param([string]$PythonExe = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
if (-not $PythonExe) { $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe' }
$oldPythonPath = $env:PYTHONPATH
try {
  $env:PYTHONPATH = $repoRoot
  & $PythonExe -m unittest discover -s (Join-Path $projectRoot 'tests') -p 'test_*.py'
  if ($LASTEXITCODE -ne 0) { throw 'RF octupole static tests failed.' }
} finally { $env:PYTHONPATH = $oldPythonPath }
Write-Output 'PROJECT_GATE=PASS PROJECT=rf_octupole_ion_guide LEVEL=Static'
