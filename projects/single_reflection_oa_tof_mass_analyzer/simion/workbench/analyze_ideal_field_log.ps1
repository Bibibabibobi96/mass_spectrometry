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
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$arguments = @(
  (Join-Path $projectRoot 'analysis\solver_diagnostics.py')
  'analyze-simion-log'
  '--log'; $Log
  '--ion-file'; $IonFile
  '--mode'; $Mode
  '--distribution'; $Distribution
  '--detector-radius-mm'; [string]$DetectorRadiusMm
)
if ($ParticleCsv) { $arguments += @('--particle-csv', $ParticleCsv) }
if ($AllowIncompleteCensus) { $arguments += '--allow-incomplete-census' }
$summaryJson = & $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Python SIMION log analysis failed.' }
$summaryJson | ConvertFrom-Json
