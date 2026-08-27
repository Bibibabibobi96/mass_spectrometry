[CmdletBinding()]
param([string]$PythonExe = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$hostExecutionLease = $null
$hostExecutionLeaseSupport = Join-Path $repoRoot 'common\host_execution_lease.ps1'
if (Test-Path -LiteralPath $hostExecutionLeaseSupport -PathType Leaf) {
  . $hostExecutionLeaseSupport
  $hostExecutionLease = Enter-HostExecutionLease -Role GATE
}
try {
if (-not $PythonExe) { $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe' }
$oldPythonPath = $env:PYTHONPATH
try {
  $env:PYTHONPATH = $repoRoot
  & $PythonExe -m unittest discover -s (Join-Path $projectRoot 'tests') -p 'test_*.py'
  if ($LASTEXITCODE -ne 0) { throw 'RF hexapole static tests failed.' }
} finally { $env:PYTHONPATH = $oldPythonPath }
Write-Output 'PROJECT_GATE=PASS PROJECT=rf_hexapole_ion_optics LEVEL=Static'
} finally {
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease
  }
}
