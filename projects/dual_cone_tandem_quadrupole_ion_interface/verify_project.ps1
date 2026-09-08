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
      throw "PROJECT_GATE=BLOCKED PROJECT=dual_cone_tandem_quadrupole_ion_interface LEVEL=$Level REASON=no_candidate_or_formal_solver_evidence"
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
