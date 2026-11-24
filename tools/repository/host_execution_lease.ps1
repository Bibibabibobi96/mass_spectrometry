[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
$explicitArgs = Get-Variable args -ErrorAction SilentlyContinue
$callerPython = Get-Variable PythonExe -ErrorAction SilentlyContinue
$existingPython = Get-Variable python -ErrorAction SilentlyContinue
$python = if ($null-ne$explicitArgs-and$explicitArgs.Value.Count -gt 0 -and $explicitArgs.Value[0]) { [IO.Path]::GetFullPath([string]$explicitArgs.Value[0]) } elseif ($null-ne$callerPython-and$callerPython.Value) { [IO.Path]::GetFullPath([string]$callerPython.Value) } elseif ($null-ne$existingPython-and$existingPython.Value) { [IO.Path]::GetFullPath([string]$existingPython.Value) } elseif ($env:SIMULATION_PYTHON_EXE) { [IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE) } else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python runtime missing: $python" }
$hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Join-Path (Split-Path -Parent $repoRoot) 'artifacts/platform/host_resources.sqlite3' }
$hostContext = @{workspace=(Split-Path -Parent $repoRoot);python_executable=$python;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
$hostResource = Join-Path $executionResources 'host_execution_lease.ps1'
if (-not (Test-Path -LiteralPath $hostResource -PathType Leaf)) { throw "Frozen execution host resource is unavailable: $hostResource" }
. $hostResource -HostContext $hostContext
