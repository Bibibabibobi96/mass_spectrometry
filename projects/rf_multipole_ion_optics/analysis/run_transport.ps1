[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$DesignProfileId, [string]$RunId = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$arguments = @('-m', 'projects.rf_multipole_ion_optics.runtime.run_ideal_transport', '--design-profile-id', $DesignProfileId, '--project-root', $projectRoot)
if (-not [string]::IsNullOrWhiteSpace($RunId)) { $arguments += @('--run-id', $RunId) }
Push-Location $repoRoot
try {
  & $python @arguments
  if ($LASTEXITCODE -ne 0) { throw 'RF multipole ideal L1 transport failed.' }
} finally {
  Pop-Location
}
