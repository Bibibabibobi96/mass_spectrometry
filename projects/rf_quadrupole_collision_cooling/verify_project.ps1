param(
  [ValidateSet('Static','Candidate','Formal')][string]$Level = 'Static',
  [string]$RunLabel = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

& $python (Join-Path $projectRoot 'analysis\resolve_contract.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Resolved-contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\resolve_contract.py') --profile interface --check
if ($LASTEXITCODE -ne 0) { throw 'Interface-readiness contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\generate_official_particle_table.py') --check `
  (Join-Path $projectRoot 'config\particles\official_fixed_25.ion')
if ($LASTEXITCODE -ne 0) { throw 'Paired-particle identity gate failed.' }

if ($Level -eq 'Candidate') {
  if ([string]::IsNullOrWhiteSpace($RunLabel)) { $RunLabel = 'gate_' + (Get-Date -Format 'yyyyMMdd_HHmmss') }
  & (Join-Path $projectRoot 'tests\simion\run_transport_candidate.ps1') -RunLabel $RunLabel
  if ($LASTEXITCODE -ne 0) { throw 'SIMION transport candidate gate failed.' }
}
elseif ($Level -eq 'Formal') {
  & (Join-Path $repoRoot 'common\verify_toolchain.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Toolchain gate failed.' }
  & $python (Join-Path $projectRoot 'analysis\verify_cross_solver_transport.py') `
    --workspace $workspaceRoot --project $projectRoot
  if ($LASTEXITCODE -ne 0) { throw 'Formal cross-solver transport gate failed.' }
}

"PROJECT_GATE=PASS PROJECT=rf_quadrupole_collision_cooling LEVEL=$Level"
