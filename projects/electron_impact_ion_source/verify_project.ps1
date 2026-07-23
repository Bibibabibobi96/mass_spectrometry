[CmdletBinding()]
param([string]$PythonExe = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
if (-not $PythonExe) {
  $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}

Push-Location $projectRoot
try {
  & $PythonExe -m analysis.resolve_contract `
    --baseline config/baseline.json `
    --modes config/numerical_modes.json `
    --mode build_only_smoke `
    --evidence-particle-count 1 `
    --check config/resolved_model.json
  if ($LASTEXITCODE -ne 0) {
    throw 'EI-source resolved contract is invalid or stale.'
  }

  & $PythonExe -m unittest discover -s tests/analysis -p 'test_*.py'
  if ($LASTEXITCODE -ne 0) {
    throw 'EI-source static tests failed.'
  }

  & $PythonExe -m ruff check analysis tests/analysis
  if ($LASTEXITCODE -ne 0) {
    throw 'EI-source Ruff checks failed.'
  }
} finally {
  Pop-Location
}

Write-Output (
  'PROJECT_GATE=PASS PROJECT=electron_impact_ion_source LEVEL=Static'
)
