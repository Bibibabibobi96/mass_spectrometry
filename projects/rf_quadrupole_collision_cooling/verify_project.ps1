param(
  [ValidateSet('Static','Candidate','Formal')][string]$Level = 'Static',
  [string]$PythonExe = '',
  [string]$ComsolRunLabel = '',
  [string]$SimionRunLabel = '',
  [string]$ComparisonLabel = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 runtime missing: $python" }

& $python (Join-Path $projectRoot 'analysis\resolve_contract.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Resolved-contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\resolve_contract.py') --profile interface --check
if ($LASTEXITCODE -ne 0) { throw 'Interface-readiness contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\sync_simion_geometry.py') --check
if ($LASTEXITCODE -ne 0) { throw 'SIMION geometry publication gate failed.' }
& $python (Join-Path $projectRoot 'analysis\generate_official_particle_table.py') --check `
  (Join-Path $projectRoot 'config\particles\official_fixed_25.ion')
if ($LASTEXITCODE -ne 0) { throw 'Paired-particle identity gate failed.' }
& $python -m unittest discover -s (Join-Path $projectRoot 'tests\analysis') -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Python analysis tests failed.' }

if ($Level -eq 'Candidate') {
  if ([string]::IsNullOrWhiteSpace($ComsolRunLabel) -or [string]::IsNullOrWhiteSpace($SimionRunLabel) -or
      [string]::IsNullOrWhiteSpace($ComparisonLabel)) {
    throw 'Candidate gate requires explicit ComsolRunLabel, SimionRunLabel, and ComparisonLabel.'
  }
  & (Join-Path $projectRoot 'tests\cross_solver\verify_transport_candidate.ps1') `
    -ComsolRunLabel $ComsolRunLabel -SimionRunLabel $SimionRunLabel -ComparisonLabel $ComparisonLabel
  if ($LASTEXITCODE -ne 0) { throw 'Cross-solver transport candidate gate failed.' }
}
elseif ($Level -eq 'Formal') {
  throw 'Formal gate is intentionally unavailable until the component geometry and SolidWorks assembly are selected and synchronized.'
}

"PROJECT_GATE=PASS PROJECT=rf_quadrupole_collision_cooling LEVEL=$Level"
