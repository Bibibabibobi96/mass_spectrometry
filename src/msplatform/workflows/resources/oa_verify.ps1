[CmdletBinding()]
param([string]$PythonExe = '', [string]$LuaExe = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
. (Join-Path $executionResources 'require_powershell7.ps1')
if (-not $PythonExe) { $PythonExe = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' } }
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Python runtime missing: $PythonExe" }
. (Join-Path $executionResources 'workspace_paths.ps1')
$hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Resolve-PlatformArtifactPath -ArtifactRoot (Join-Path (Split-Path -Parent $repoRoot) 'artifacts') -RelativePath @('host_resources.sqlite3') -Python $PythonExe }
$hostContext = @{workspace=(Split-Path -Parent $repoRoot);python_executable=$PythonExe;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
$acceleratorGateLease = Enter-HostExecutionLease -Role GATE
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $repoRoot + [IO.Path]::PathSeparator + (Join-Path $repoRoot 'src')
    & $PythonExe -c "import sys; assert sys.version_info[:2] == (3, 11), 'Python 3.11 required'"
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python runtime.' }
    & $PythonExe -m tools.repository.gate_unittest discover -s (Join-Path $repoRoot 'tests\components\orthogonal_accelerator\analysis') -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw 'Orthogonal accelerator static tests failed.' }
    if ($LuaExe -and -not (Test-Path -LiteralPath $LuaExe -PathType Leaf)) {
        throw "Explicit Lua executable is missing: $LuaExe"
    }
    if (-not $LuaExe) {
      foreach ($commandName in @('lua', 'lua5.1')) {
        $candidate = Get-Command -Name $commandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($candidate) { $LuaExe = $candidate.Source; break }
      }
    }
    if (-not $LuaExe -and $env:ProgramFiles) {
        $installedLua = Join-Path $env:ProgramFiles 'SIMION-2020\lua.exe'
        if (Test-Path -LiteralPath $installedLua -PathType Leaf) { $LuaExe = $installedLua }
    }
    if ($LuaExe) {
        & $LuaExe (Join-Path $repoRoot 'tests\components\orthogonal_accelerator\simion\test_required_parameters.lua') (Join-Path $repoRoot 'src\msplatform\backends\simion\resources')
        if ($LASTEXITCODE -ne 0) { throw 'Accelerator Lua parameter-contract regression failed.' }
        & $LuaExe (Join-Path $repoRoot 'tests\components\orthogonal_accelerator\simion\test_component_focus_iob_arguments.lua') (Join-Path $repoRoot 'src\msplatform\backends\simion\resources')
        if ($LASTEXITCODE -ne 0) { throw 'Accelerator IOB argument regression failed.' }
        $testPlaneLibrary = Join-Path (Split-Path -Parent $LuaExe) 'examples\test_plane\testplanelib.lua'
        if (Test-Path -LiteralPath $testPlaneLibrary -PathType Leaf) {
            & $LuaExe (Join-Path $repoRoot 'tests\components\orthogonal_accelerator\simion\test_component_focus_callbacks.lua') (Join-Path $repoRoot 'src\msplatform\backends\simion\resources\component_focus.lua') $testPlaneLibrary
            if ($LASTEXITCODE -ne 0) { throw 'Accelerator focus callback regression failed.' }
        } else {
            Write-Output 'ACCELERATOR_COMPONENT_FOCUS_CALLBACKS=SKIP REASON=official_test_plane_library_unavailable'
        }
    } else {
        Write-Output 'ACCELERATOR_REQUIRED_PARAMETERS=SKIP REASON=Lua_runtime_unavailable'
    }
    Write-Output 'PROJECT_GATE=PASS PROJECT=orthogonal_accelerator LEVEL=Static COMMERCIAL_SOLVER_EXECUTED=false'
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Exit-HostExecutionLease -Lease $acceleratorGateLease
}
