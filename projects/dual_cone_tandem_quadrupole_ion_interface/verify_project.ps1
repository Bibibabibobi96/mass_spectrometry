[CmdletBinding()]
param(
  [ValidateSet('Static', 'Candidate', 'Formal')]
  [string]$Level = 'Static',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$powerShellPreflight = Join-Path $repoRoot 'common\require_powershell7.ps1'
if (-not (Test-Path -LiteralPath $powerShellPreflight -PathType Leaf)) {
  throw "Missing PowerShell 7 preflight: $powerShellPreflight"
}
. $powerShellPreflight
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
    & $PythonExe -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) {
      throw 'Dual-cone interface requires Python 3.11.'
    }

    & $PythonExe -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.resolve_geometry --check
    if ($LASTEXITCODE -ne 0) {
      throw 'Dual-cone resolved geometry is invalid or stale.'
    }

    $requiredProjectFiles = @(
      'config\gas_flow_science.json',
      'config\comsol_solver_numerics.json',
      'config\gas_field_interface.json',
      'config\ion_transport_science.json',
      'config\simion_solver_numerics.json',
      'comsol\build_and_solve_axisymmetric_gas_flow.m',
      'analysis\validate_gas_field.py',
      'analysis\export_simion_gas_runtime.py',
      'simion\geometry.py'
    )
    foreach ($relativePath in $requiredProjectFiles) {
      $requiredPath = Join-Path $projectRoot $relativePath
      if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "COMSOL gas-flow authority file is missing: $relativePath"
      }
    }

    $retiredPaths = @(
      'analysis\reduced_order_transport.py',
      'analysis\run_reduced_order_transport.py',
      'config\modes\pressure_drag_screening.json'
    )
    foreach ($relativePath in $retiredPaths) {
      if (Test-Path -LiteralPath (Join-Path $projectRoot $relativePath)) {
        throw "Retired Python trajectory entry remains active: $relativePath"
      }
    }

    & $PythonExe -m unittest discover `
      -s projects/dual_cone_tandem_quadrupole_ion_interface/tests -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) {
      throw 'Dual-cone interface static tests failed.'
    }

    & $PythonExe -m ruff check `
      projects/dual_cone_tandem_quadrupole_ion_interface/analysis `
      projects/dual_cone_tandem_quadrupole_ion_interface/tests
    if ($LASTEXITCODE -ne 0) {
      throw 'Dual-cone interface Ruff checks failed.'
    }

    if ($Level -ne 'Static') {
      throw "PROJECT_GATE=BLOCKED PROJECT=dual_cone_tandem_quadrupole_ion_interface LEVEL=$Level REASON=comsol_gas_field_to_simion_trajectory_chain_not_qualified"
    }
  } finally {
    Pop-Location
  }

  Write-Output 'PROJECT_GATE=PASS PROJECT=dual_cone_tandem_quadrupole_ion_interface LEVEL=Static'
} finally {
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease
  }
}
