param(
  [ValidateSet('Static','Candidate','Formal')][string]$Level = 'Static',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

& $python (Join-Path $projectRoot 'analysis\resolve_geometry.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Resolved-geometry gate failed.' }
& $python (Join-Path $projectRoot 'analysis\sync_geometry_contract.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Generated-input freshness gate failed.' }
& (Join-Path $projectRoot 'tests\cross_solver\verify_geometry_contract.ps1') -SkipRuntime -SimionExe $SimionExe
if ($LASTEXITCODE -ne 0) { throw 'Static cross-solver geometry gate failed.' }
& $python -m unittest discover -s (Join-Path $projectRoot 'tests\analysis') -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Python analysis tests failed.' }

if ($Level -eq 'Candidate') {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $output = Join-Path $workspaceRoot "artifacts\projects\oa_tof\scratch\simion\parameterized_geometry_gate_$stamp"
  & (Join-Path $projectRoot 'tests\simion\test_parameterized_geometry_build.ps1') -SimionExe $SimionExe -OutputDir $output
  if ($LASTEXITCODE -ne 0) { throw 'Candidate SIMION geometry build failed.' }
}
elseif ($Level -eq 'Formal') {
  & (Join-Path $repoRoot 'common\verify_toolchain.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Toolchain gate failed.' }
  & (Join-Path $projectRoot 'tests\cross_solver\verify_geometry_contract.ps1') -SimionExe $SimionExe
  if ($LASTEXITCODE -ne 0) { throw 'Formal runtime/CAD/COMSOL gate failed.' }
}

"PROJECT_GATE=PASS PROJECT=oa_tof LEVEL=$Level"
