[CmdletBinding()]
param(
  [ValidateSet('Static', 'Candidate', 'Formal')]
  [string]$Level = 'Static',
  [string]$PythonExe = '',
  [switch]$RuffHandledByParent
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

    & $PythonExe -m msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry `
      --baseline (Join-Path $projectRoot 'config\baseline.json') `
      --check (Join-Path $projectRoot 'config\resolved_geometry.json')
    if ($LASTEXITCODE -ne 0) {
      throw 'Dual-cone resolved geometry is invalid or stale.'
    }

    $requiredProjectFiles = @(
      'config\gas_flow_science.json',
      'config\comsol_solver_numerics.json',
      'config\gas_field_interface.json',
      'config\uniform_rear_gas_field.json',
      'config\ion_transport_science.json',
      'config\simion_solver_numerics.json',
      'workflows\gas_assisted_transport\prepare.ps1'
    )
    $requiredCoreFiles = @(
      'src/msplatform/backends/comsol/matlab/build_and_solve_axisymmetric_gas_flow.m',
      'src/msplatform/backends/comsol/matlab/run_axisymmetric_gas_flow.m',
      'src/msplatform/backends/comsol/gas_flow.py',
      'src/msplatform/backends/comsol/native_execution.py',
      'src/msplatform/results/gas_field.py',
      'src\msplatform\components\dual_cone_tandem_quadrupole_ion_interface\geometry.py',
      'src\msplatform\contracts\gas_field.py',
      'src\msplatform\components\dual_cone_tandem_quadrupole_ion_interface\gas_runtime.py',
      'src\msplatform\components\dual_cone_tandem_quadrupole_ion_interface\uniform_gas_runtime.py',
      'src\msplatform\backends\simion\dual_cone_geometry.py'
    )
    foreach ($relativePath in $requiredCoreFiles) {
      $requiredPath = Join-Path $repoRoot $relativePath
      if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Dual-cone core authority file is missing: $relativePath"
      }
    }
    foreach ($relativePath in $requiredProjectFiles) {
      $requiredPath = Join-Path $projectRoot $relativePath
      if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Dual-cone authority file is missing: $relativePath"
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

    & $PythonExe -m common.gate_unittest discover `
      -s projects/dual_cone_tandem_quadrupole_ion_interface/tests -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) {
      throw 'Dual-cone interface static tests failed.'
    }

    if ($RuffHandledByParent) {
      'RUFF=HANDLED_BY_PARENT PROJECT=dual_cone_tandem_quadrupole_ion_interface'
    } else {
      & $PythonExe -m ruff check `
        src/msplatform/components/dual_cone_tandem_quadrupole_ion_interface `
        src/msplatform/backends/simion/dual_cone_geometry.py `
        projects/dual_cone_tandem_quadrupole_ion_interface/analysis `
        projects/dual_cone_tandem_quadrupole_ion_interface/simion `
        projects/dual_cone_tandem_quadrupole_ion_interface/tests
      if ($LASTEXITCODE -ne 0) {
        throw 'Dual-cone interface Ruff checks failed.'
      }
    }

    if ($Level -ne 'Static') {
      throw "PROJECT_GATE=BLOCKED PROJECT=dual_cone_tandem_quadrupole_ion_interface LEVEL=$Level REASON=single_ion_uniform_gas_prototype_not_candidate_qualified"
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
