[CmdletBinding()]
param([string]$PythonExe='')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
. (Join-Path $executionResources 'require_powershell7.ps1')
if(-not $PythonExe){$PythonExe=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required'}}
$PythonExe=[IO.Path]::GetFullPath($PythonExe)
if(-not(Test-Path -LiteralPath $PythonExe -PathType Leaf)){throw "Python runtime missing: $PythonExe"}
. (Join-Path $executionResources 'workspace_paths.ps1')
$hostState=if($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH){$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH}else{Resolve-PlatformArtifactPath -ArtifactRoot (Join-Path (Split-Path -Parent $repoRoot) 'artifacts') -RelativePath host_resources.sqlite3 -Python $PythonExe}
$hostContext=@{workspace=(Split-Path -Parent $repoRoot);python_executable=$PythonExe;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
$lease=Enter-HostExecutionLease -Role GATE
Push-Location $repoRoot
try {
 & $PythonExe -m tools.repository.gate_unittest discover -s 'tests/components/dual_pressure_rectilinear_ion_processor' -p 'test_*.py'
 if($LASTEXITCODE-ne0){throw 'Ion Processor static gate failed'}
 Write-Output 'PROJECT_GATE=PASS PROJECT=dual_pressure_rectilinear_ion_processor LEVEL=Static'
} finally {Pop-Location;Exit-HostExecutionLease -Lease $lease}
