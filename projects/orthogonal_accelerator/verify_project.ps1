[CmdletBinding()]
param([string]$PythonExe = '', [string]$LuaExe = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $repoRoot 'common\require_powershell7.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$acceleratorGateLease = Enter-HostExecutionLease -Role GATE
$previousPythonPath = $env:PYTHONPATH
try {
    if (-not $PythonExe) { $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe' }
    $env:PYTHONPATH = $repoRoot
    & $PythonExe -c "import sys; assert sys.version_info[:2] == (3, 11), 'Python 3.11 required'"
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python runtime.' }
    & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'tests\analysis') -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw 'Orthogonal accelerator static tests failed.' }
    if ($LuaExe -and -not (Test-Path -LiteralPath $LuaExe -PathType Leaf)) {
        throw "Explicit Lua executable is missing: $LuaExe"
    }
    if (-not $LuaExe -and $env:ProgramFiles) {
        $installedLua = Join-Path $env:ProgramFiles 'SIMION-2020\lua.exe'
        if (Test-Path -LiteralPath $installedLua -PathType Leaf) { $LuaExe = $installedLua }
    }
    if ($LuaExe) {
        & $LuaExe (Join-Path $PSScriptRoot 'tests\simion\test_required_parameters.lua') (Join-Path $PSScriptRoot 'simion')
        if ($LASTEXITCODE -ne 0) { throw 'Accelerator Lua parameter-contract regression failed.' }
    } else {
        Write-Output 'ACCELERATOR_REQUIRED_PARAMETERS=SKIP REASON=Lua_runtime_unavailable'
    }
    Write-Output 'PROJECT_GATE=PASS PROJECT=orthogonal_accelerator LEVEL=Static COMMERCIAL_SOLVER_EXECUTED=false'
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Exit-HostExecutionLease -Lease $acceleratorGateLease
}
