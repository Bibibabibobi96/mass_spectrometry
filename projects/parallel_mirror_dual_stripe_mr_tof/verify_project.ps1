[CmdletBinding()]
param(
  [ValidateSet('Core', 'Static')][string]$Level = 'Static',
  [string]$PythonExe = '',
  [string]$LuaExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
. (Join-Path $repoRoot 'common\require_powershell7.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$lease = Enter-HostExecutionLease -Role GATE
$savedPythonPath = $env:PYTHONPATH
$savedNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$savedSimionExe = $env:SIMION_EXE
try {
  $python = if ($PythonExe) {
    (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path
  } else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
  }
  if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python 3.11 runtime missing: $python"
  }
  $env:PYTHONPATH = $repoRoot
  $env:PYTHONDONTWRITEBYTECODE = '1'
  Remove-Item Env:SIMION_EXE -ErrorAction SilentlyContinue

  Push-Location $repoRoot
  try {
    & $python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'MR-TOF requires Python 3.11.' }
    & $python common/contracts/build_project_registry.py --check
    if ($LASTEXITCODE -ne 0) { throw 'MR-TOF project registration is stale or invalid.' }

    if ($Level -eq 'Core') {
      $coreTests = @(
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_accelerator_dependency',
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_drift_phase_contract',
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_prism_analytic',
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_native_corridor_plan',
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_native_corridor_freeze'
      )
      & $python -m unittest @coreTests
      if ($LASTEXITCODE -ne 0) { throw 'MR-TOF core contract tests failed.' }
    } else {
      & $python -m unittest discover -s (Join-Path $projectRoot 'tests\analysis') -p 'test_*.py'
      if ($LASTEXITCODE -ne 0) { throw 'MR-TOF Python analysis tests failed.' }
      & $python -m unittest discover -s (Join-Path $projectRoot 'tests\simion') -p 'test_*.py'
      if ($LASTEXITCODE -ne 0) { throw 'MR-TOF solver-free SIMION adapter tests failed.' }
    }
  } finally {
    Pop-Location
  }

  $parseErrors = @()
  Get-ChildItem -LiteralPath $projectRoot -Recurse -Filter '*.ps1' | ForEach-Object {
    $tokens = $null
    $fileErrors = $null
    [Management.Automation.Language.Parser]::ParseFile(
      $_.FullName, [ref]$tokens, [ref]$fileErrors
    ) | Out-Null
    if ($fileErrors) { $parseErrors += $fileErrors }
  }
  if ($parseErrors.Count -gt 0) {
    throw "MR-TOF PowerShell syntax gate failed: $($parseErrors -join '; ')"
  }

  if ($LuaExe -and -not (Test-Path -LiteralPath $LuaExe -PathType Leaf)) {
    throw "Explicit Lua executable is missing: $LuaExe"
  }
  if (-not $LuaExe -and $env:ProgramFiles) {
    $installedLua = Join-Path $env:ProgramFiles 'SIMION-2020\lua.exe'
    if (Test-Path -LiteralPath $installedLua -PathType Leaf) { $LuaExe = $installedLua }
  }
  if ($LuaExe) {
    Push-Location $repoRoot
    try {
      foreach ($name in @(
        'test_candidate_plane_events.lua',
        'test_candidate_voltage_map.lua',
        'test_mirror_cycle_counter.lua'
      )) {
        & $LuaExe (Join-Path $projectRoot "tests\simion\$name") $repoRoot
        if ($LASTEXITCODE -ne 0) { throw "MR-TOF plain-Lua regression failed: $name" }
      }
    } finally {
      Pop-Location
    }
  } else {
    Write-Output 'MRTOF_PLAIN_LUA=SKIP REASON=Lua_runtime_unavailable'
  }

  "PROJECT_GATE=PASS PROJECT=parallel_mirror_dual_stripe_mr_tof LEVEL=$Level COMMERCIAL_SOLVER_EXECUTED=false"
} finally {
  $env:PYTHONPATH = $savedPythonPath
  $env:PYTHONDONTWRITEBYTECODE = $savedNoBytecode
  if ($null -eq $savedSimionExe) {
    Remove-Item Env:SIMION_EXE -ErrorAction SilentlyContinue
  } else {
    $env:SIMION_EXE = $savedSimionExe
  }
  Exit-HostExecutionLease -Lease $lease
}
