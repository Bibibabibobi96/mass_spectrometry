[CmdletBinding()]
param([string]$PythonExe = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
. (Join-Path $repoRoot 'common\require_powershell7.ps1')
if (-not $PythonExe) {
  $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
  throw "Python runtime missing: $PythonExe"
}
$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') {
  throw "Wehnelt Static gate requires Python 3.11, found $pythonVersion at $PythonExe"
}

Push-Location $repoRoot
try {
  & $PythonExe -m projects.wehnelt_electron_gun.analysis.resolve_contract `
    --baseline projects/wehnelt_electron_gun/config/baseline.json `
    --modes projects/wehnelt_electron_gun/config/numerical_modes.json `
    --mode build_only_smoke `
    --evidence-particle-count 1 `
    --check projects/wehnelt_electron_gun/config/resolved_model.json
  if ($LASTEXITCODE -ne 0) {
    throw 'Wehnelt resolved contract is invalid or stale.'
  }

  & $PythonExe -m unittest discover `
    -s projects/wehnelt_electron_gun/tests/analysis -p 'test_*.py'
  if ($LASTEXITCODE -ne 0) {
    throw 'Wehnelt static tests failed.'
  }

  & $PythonExe -m ruff check projects/wehnelt_electron_gun/analysis `
    projects/wehnelt_electron_gun/tests/analysis
  if ($LASTEXITCODE -ne 0) {
    throw 'Wehnelt Ruff checks failed.'
  }
} finally {
  Pop-Location
}

Write-Output (
  'PROJECT_GATE=PASS PROJECT=wehnelt_electron_gun LEVEL=Static'
)
