[CmdletBinding()]
param([string]$PythonExe = '', [switch]$RuffHandledByParent)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
. (Join-Path $executionResources 'require_powershell7.ps1')
if (-not $PythonExe) {
  $PythonExe = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' }
}
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
  throw "Python runtime missing: $PythonExe"
}
$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') {
  throw "Wehnelt Static gate requires Python 3.11, found $pythonVersion at $PythonExe"
}
$hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Join-Path (Split-Path -Parent $repoRoot) 'artifacts/common/host_resources.sqlite3' }
$hostContext = @{workspace=(Split-Path -Parent $repoRoot);python_executable=$PythonExe;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
$hostExecutionLease = Enter-HostExecutionLease -Role GATE
try {

Push-Location $repoRoot
try {
  & $PythonExe -m msplatform.components.transverse_helical_filament_wehnelt_electron_gun.resolve_contract `
    --baseline projects/transverse_helical_filament_wehnelt_electron_gun/config/baseline.json `
    --modes projects/transverse_helical_filament_wehnelt_electron_gun/config/numerical_modes.json `
    --mode build_only_smoke `
    --evidence-particle-count 1 `
    --check projects/transverse_helical_filament_wehnelt_electron_gun/config/resolved_model.json
  if ($LASTEXITCODE -ne 0) {
    throw 'Wehnelt resolved contract is invalid or stale.'
  }

  & $PythonExe -m common.gate_unittest discover `
    -s projects/transverse_helical_filament_wehnelt_electron_gun/tests/analysis -p 'test_*.py'
  if ($LASTEXITCODE -ne 0) {
    throw 'Wehnelt static tests failed.'
  }

  if ($RuffHandledByParent) {
    'RUFF=HANDLED_BY_PARENT PROJECT=transverse_helical_filament_wehnelt_electron_gun'
  } else {
    & $PythonExe -m ruff check `
      src/msplatform/components/transverse_helical_filament_wehnelt_electron_gun `
      projects/transverse_helical_filament_wehnelt_electron_gun/tests/analysis
    if ($LASTEXITCODE -ne 0) {
      throw 'Wehnelt Ruff checks failed.'
    }
  }
} finally {
  Pop-Location
}

Write-Output (
  'PROJECT_GATE=PASS PROJECT=transverse_helical_filament_wehnelt_electron_gun LEVEL=Static'
)
} finally {
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease
  }
}
