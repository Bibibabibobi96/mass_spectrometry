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
if (-not $PythonExe) {
  $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path

Push-Location $repoRoot
try {
  & $PythonExe -m projects.apertured_tube_electron_impact_ion_source.analysis.resolve_contract `
    --baseline projects/apertured_tube_electron_impact_ion_source/config/baseline.json `
    --modes projects/apertured_tube_electron_impact_ion_source/config/numerical_modes.json `
    --mode build_only_smoke `
    --evidence-particle-count 1 `
    --check projects/apertured_tube_electron_impact_ion_source/config/resolved_model.json
  if ($LASTEXITCODE -ne 0) {
    throw 'EI-source resolved contract is invalid or stale.'
  }

  & $PythonExe -m unittest discover `
    -s projects/apertured_tube_electron_impact_ion_source/tests/analysis -p 'test_*.py'
  if ($LASTEXITCODE -ne 0) {
    throw 'EI-source static tests failed.'
  }

  & $PythonExe -m ruff check `
    projects/apertured_tube_electron_impact_ion_source/analysis `
    projects/apertured_tube_electron_impact_ion_source/tests/analysis
  if ($LASTEXITCODE -ne 0) {
    throw 'EI-source Ruff checks failed.'
  }
} finally {
  Pop-Location
}

Write-Output (
  'PROJECT_GATE=PASS PROJECT=apertured_tube_electron_impact_ion_source LEVEL=Static'
)
} finally {
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease
  }
}
