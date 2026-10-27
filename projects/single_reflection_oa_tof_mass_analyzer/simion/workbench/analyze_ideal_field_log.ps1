param(
  [Parameter(Mandatory = $true)][string]$Log,
  [Parameter(Mandatory = $true)][string]$IonFile,
  [Parameter(Mandatory = $true)][string]$Mode,
  [Parameter(Mandatory = $true)][string]$Distribution,
  [double]$DetectorRadiusMm = 40,
  [string]$ParticleCsv = '',
  [switch]$AllowIncompleteCensus
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else {
  Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$pythonVersion = (& $python -c 'import sys; print(str(sys.version_info.major) + "." + str(sys.version_info.minor))').Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') { throw 'SIMION log analysis requires Python 3.11.' }
$arguments = @(
  '-m'
  'projects.single_reflection_oa_tof_mass_analyzer.analysis.solver_diagnostics'
  'analyze-simion-log'
  '--log'; (Resolve-Path -LiteralPath $Log).Path
  '--ion-file'; (Resolve-Path -LiteralPath $IonFile).Path
  '--mode'; $Mode
  '--distribution'; $Distribution
  '--detector-radius-mm'; [string]$DetectorRadiusMm
)
if ($ParticleCsv) {
  $arguments += @('--particle-csv', $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ParticleCsv))
}
if ($AllowIncompleteCensus) { $arguments += '--allow-incomplete-census' }
Push-Location -LiteralPath $repoRoot
try {
  $summaryJson = & $python @arguments
  if ($LASTEXITCODE -ne 0) { throw 'Python SIMION log analysis failed.' }
} finally {
  Pop-Location
}
$summaryJson | ConvertFrom-Json
