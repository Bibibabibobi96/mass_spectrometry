[CmdletBinding()]
param(
  [ValidateSet('Core', 'Static')][string]$Level = 'Static',
  [string]$PythonExe = '',
  [string]$LuaExe = '',
  [string[]]$ChangedTestModules = @(),
  [string[]]$SelectedTestModules = @(),
  [switch]$PreflightOnly,
  [switch]$PreflightValidated,
  [switch]$RegistryPrevalidated
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
  if (($PreflightOnly -and $SelectedTestModules.Count) -or
      (($PreflightOnly -or $SelectedTestModules.Count) -and $Level -ne 'Static') -or
      (($PreflightOnly -or $SelectedTestModules.Count) -and $ChangedTestModules.Count) -or
      ($PreflightValidated -and -not $SelectedTestModules.Count)) {
    throw 'Static preflight and selected test modules are mutually exclusive with other modes.'
  }
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
    if (-not ($PreflightValidated -or $RegistryPrevalidated)) {
      & $python common/contracts/build_project_registry.py --check
      if ($LASTEXITCODE -ne 0) { throw 'MR-TOF project registration is stale or invalid.' }
    } elseif ($RegistryPrevalidated) {
      'PROJECT_REGISTRY=PREVALIDATED'
    }

    if ($PreflightOnly) {
      Write-Output 'MRTOF_PYTHON_TESTS=DEFERRED REASON=repository_integration_partition'
    } elseif ($SelectedTestModules.Count) {
      $testModules = @($SelectedTestModules | Sort-Object -Unique)
      if ($testModules.Count -ne $SelectedTestModules.Count -or @($testModules | Where-Object {
        $_ -notmatch '^projects\.parallel_mirror_dual_stripe_mr_tof\.tests\.[A-Za-z0-9_.]+$'
      }).Count) { throw 'MR-TOF test partition has duplicate or foreign modules.' }
      & $python -m common.gate_unittest @testModules
      if ($LASTEXITCODE -ne 0) { throw 'MR-TOF test partition failed.' }
      Write-Output "MRTOF_TEST_PARTITION=PASS PREFLIGHT_PREVALIDATED=$([bool]$PreflightValidated) FULL_PROJECT_GATE=False"
      return
    } elseif ($Level -eq 'Core') {
      $coreTests = @(
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_drift_phase_contract',
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_prism_analytic',
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_native_corridor_plan',
        'projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_native_corridor_freeze'
      )
      $coreTests = @($coreTests + $ChangedTestModules | Sort-Object -Unique)
      Write-Output "PROJECT_TEST_MODULES=$($coreTests -join ',')"
      & $python -m common.gate_unittest @coreTests
      if ($LASTEXITCODE -ne 0) { throw 'MR-TOF core contract tests failed.' }
    } else {
      $testModules = @(@(
        Get-ChildItem -LiteralPath (Join-Path $projectRoot 'tests') -Filter 'test_*.py' -File -Recurse |
          ForEach-Object {
            $_.FullName.Substring($repoRoot.Length + 1, $_.FullName.Length - $repoRoot.Length - 4).Replace('\', '.')
          }
      ) + $ChangedTestModules | Sort-Object -Unique)
      & $python -m common.gate_unittest @testModules
      if ($LASTEXITCODE -ne 0) { throw 'MR-TOF solver-free Python tests failed.' }
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

  if ($PreflightOnly) { 'MRTOF_STATIC_PREFLIGHT=PASS PYTHON_TESTS=DEFERRED' }
  else { "PROJECT_GATE=PASS PROJECT=parallel_mirror_dual_stripe_mr_tof LEVEL=$Level COMMERCIAL_SOLVER_EXECUTED=false" }
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
