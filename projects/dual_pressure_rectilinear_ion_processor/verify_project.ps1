[CmdletBinding()]
param([string]$PythonExe='')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/host_execution_lease.ps1')
if(-not $PythonExe){$PythonExe=Join-Path $repoRoot '.venv/Scripts/python.exe'}
$lease=Enter-HostExecutionLease -Role GATE
Push-Location $repoRoot
try {
 & $PythonExe -m common.gate_unittest discover -s (Join-Path $PSScriptRoot 'tests') -p 'test_*.py'
 if($LASTEXITCODE-ne0){throw 'Ion Processor static gate failed'}
 Write-Output 'PROJECT_GATE=PASS PROJECT=dual_pressure_rectilinear_ion_processor LEVEL=Static'
} finally {Pop-Location;Exit-HostExecutionLease -Lease $lease}
