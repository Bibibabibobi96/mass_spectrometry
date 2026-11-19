[CmdletBinding()]
param([string]$PythonExe = '')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } elseif ($env:SIMULATION_PYTHON_EXE) { [IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE) } else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python runtime missing: $python" }
$hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Join-Path (Split-Path -Parent $repoRoot) 'artifacts/common/host_resources.sqlite3' }
$hostContext = @{workspace=(Split-Path -Parent $repoRoot);python_executable=$python;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
