[CmdletBinding()]
param(
  [ValidateSet('Static', 'Candidate', 'Formal')]
  [string]$Level = 'Static',
  [string]$PythonExe = '',
  [switch]$RuffHandledByParent
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$componentRoot = 'src/msplatform/components/apertured_tube_electron_impact_ion_source'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
. (Join-Path $executionResources 'require_powershell7.ps1')
if (-not $PythonExe) {
  $PythonExe = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' }
}
$PythonExe = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path
$hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Join-Path (Split-Path -Parent $repoRoot) 'artifacts/common/host_resources.sqlite3' }
$hostContext = @{workspace=(Split-Path -Parent $repoRoot);python_executable=$PythonExe;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
$hostExecutionLease = Enter-HostExecutionLease -Role GATE
try {
  Push-Location $repoRoot
  try {
    & $PythonExe -m msplatform.components.apertured_tube_electron_impact_ion_source.resolve_contract `
      --baseline "$componentRoot/config/baseline.json" `
      --modes "$componentRoot/config/numerical_modes.json" `
      --mode build_only_smoke `
      --evidence-particle-count 1 `
      --check "$componentRoot/config/resolved_model.json"
    if ($LASTEXITCODE -ne 0) {
      throw 'EI-source resolved contract is invalid or stale.'
    }

    $legacyProjectRoot = Join-Path $repoRoot 'projects/apertured_tube_electron_impact_ion_source'
    if (Test-Path -LiteralPath $legacyProjectRoot) {
      throw "Retired EI-source project tree remains active: $legacyProjectRoot"
    }

    & $PythonExe -m tools.repository.gate_unittest discover `
      -s tests/components/apertured_tube_electron_impact_ion_source -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) {
      throw 'EI-source static tests failed.'
    }

    if ($RuffHandledByParent) {
      'RUFF=HANDLED_BY_PARENT PROJECT=apertured_tube_electron_impact_ion_source'
    } else {
      & $PythonExe -m ruff check `
        $componentRoot `
        src/msplatform/backends/comsol/ei_model.py `
        tests/components/apertured_tube_electron_impact_ion_source
      if ($LASTEXITCODE -ne 0) {
        throw 'EI-source Ruff checks failed.'
      }
    }

    if ($Level -ne 'Static') {
      throw "PROJECT_GATE=BLOCKED PROJECT=apertured_tube_electron_impact_ion_source LEVEL=$Level REASON=functional_gui_compute_and_particle_count_not_closed"
    }
  } finally {
    Pop-Location
  }

  Write-Output 'PROJECT_GATE=PASS PROJECT=apertured_tube_electron_impact_ion_source LEVEL=Static'
} finally {
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease
  }
}
