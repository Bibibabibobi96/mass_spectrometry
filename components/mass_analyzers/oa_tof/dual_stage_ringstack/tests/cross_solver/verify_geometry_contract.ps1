param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [switch]$SkipRuntime
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$componentDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $componentDir '..\..\..\..')).Path
$projectRoot = Split-Path -Parent $repoRoot
$contractPath = Join-Path $componentDir 'config\baseline.json'
$comsolSource = Join-Path $componentDir 'comsol\ms_oaTOF_two_stage_ringstack_reflectron.m'
$simionLua = Join-Path $componentDir 'simion\workbench\formal\oatof_ideal_grounded.lua'
$formalDir = Join-Path $projectRoot 'artifacts\components\mass_analyzers\oa_tof\dual_stage_ringstack\models\simion\workspace\04_workbench\formal'
$formalMph = Join-Path $projectRoot 'artifacts\components\mass_analyzers\oa_tof\dual_stage_ringstack\models\comsol\formal\MS_oaTOF_TwoStageRingStackReflectron_Final.mph'

function Assert-Near([double]$Actual, [double]$Expected, [string]$Label, [double]$Tolerance = 1e-9) {
  if ([Math]::Abs($Actual - $Expected) -gt $Tolerance) { throw "$Label mismatch: actual=$Actual expected=$Expected" }
}
function Get-Adjustable([string]$Text, [string]$Name) {
  $m = [regex]::Match($Text, "(?m)^adjustable\s+$([regex]::Escape($Name))=([-+0-9.eE]+)\s*$")
  if (-not $m.Success) { throw "Missing SIMION adjustable: $Name" }
  return [double]::Parse($m.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture)
}
function Assert-Contains([string]$Text, [string]$Needle, [string]$Label) {
  if (-not $Text.Contains($Needle)) { throw "$Label is not linked by the required expression: $Needle" }
}

$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$lua = Get-Content -LiteralPath $simionLua -Raw -Encoding UTF8
$comsol = Get-Content -LiteralPath $comsolSource -Raw -Encoding UTF8
$axisX = Get-Adjustable $lua 'accelerator_axis_x_mm'
$axisY = Get-Adjustable $lua 'accelerator_axis_y_mm'
$detectorOffsetX = Get-Adjustable $lua 'detector_mirror_offset_x_mm'
$detectorOffsetY = Get-Adjustable $lua 'detector_mirror_offset_y_mm'
Assert-Near $axisX $contract.coordinate_convention.accelerator_axis_x 'SIMION accelerator axis x'
Assert-Near (-$axisX + $detectorOffsetX) $contract.coordinate_convention.detector_x 'SIMION linked detector x'
Assert-Near $axisY 0 'SIMION accelerator axis y'
Assert-Near (-$axisY + $detectorOffsetY) 0 'SIMION linked detector y'
Assert-Near (Get-Adjustable $lua 'detector_radius_mm') $contract.geometry_mm.detector_radius 'SIMION detector radius'
Assert-Near (Get-Adjustable $lua 'accelerator_grid2_z_mm') $contract.geometry_mm.L_accel 'SIMION grid2/L_accel'
Assert-Near (Get-Adjustable $lua 'reflectron_entgrid_z_mm') $contract.geometry_mm.L_flight 'SIMION entgrid/L_flight'
Assert-Near (Get-Adjustable $lua 'reflectron_midgrid_z_mm') ($contract.geometry_mm.L_flight + $contract.geometry_mm.L_stage1) 'SIMION midgrid'
Assert-Near (Get-Adjustable $lua 'reflectron_backplate_z_mm') ($contract.geometry_mm.L_flight + $contract.geometry_mm.L_reflectron) 'SIMION backplate'
Assert-Near (Get-Adjustable $lua 'V_repeller') $contract.electrodes_V.repeller 'SIMION repeller voltage'
Assert-Near (Get-Adjustable $lua 'V_grid1') $contract.electrodes_V.grid1 'SIMION grid1 voltage'
Assert-Near (Get-Adjustable $lua 'V_mid') $contract.electrodes_V.midgrid 'SIMION midgrid voltage'
Assert-Near (Get-Adjustable $lua 'V_backplate') $contract.electrodes_V.backplate 'SIMION backplate voltage'

Assert-Contains $lua 'ai.x,ai.y,ai.z=accelerator_axis_x_mm-45,accelerator_axis_y_mm-45,accelerator_instance_z_mm' 'SIMION accelerator transform'
Assert-Contains $lua 'detector_x_mm=-accelerator_axis_x_mm+detector_mirror_offset_x_mm' 'SIMION detector x'
Assert-Contains $lua 'detector_z_mm=accelerator_grid2_z_mm' 'SIMION detector z'
Assert-Contains $comsol "p.set('detector_x', '-x_accel_center'" 'COMSOL detector x parameter'
Assert-Contains $comsol "p.set('detector_radius', '40[mm]'" 'COMSOL detector radius parameter'
Assert-Contains $comsol "geom1.feature('detector').set('r', 'detector_radius')" 'COMSOL detector radius geometry'
Assert-Contains $comsol "geom1.feature('detector').set('pos', {'detector_x' '0' 'detector_z-1[mm]'})" 'COMSOL detector position geometry'

if (-not $SkipRuntime) {
  if (-not (Test-Path -LiteralPath $formalDir)) { throw "Formal SIMION runtime workspace missing: $formalDir" }
  if (-not (Test-Path -LiteralPath $formalMph)) { throw "Formal COMSOL MPH missing: $formalMph" }
  $mphHash = (Get-FileHash -LiteralPath $formalMph -Algorithm SHA256).Hash
  if ($mphHash -ne $contract.runtime_contract.comsol_formal_mph_sha256) { throw 'Formal COMSOL MPH differs from the verified geometry contract.' }
  $runtimeLua = Join-Path $formalDir 'oatof_ideal_grounded.lua'
  if ((Get-FileHash -LiteralPath $simionLua -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $runtimeLua -Algorithm SHA256).Hash) { throw 'Formal SIMION runtime Lua differs from source.' }
  $verifyLua = Join-Path $componentDir 'simion\workbench\formal\verify_comsol_sync.lua'
  $report = Join-Path $env:TEMP 'oatof_geometry_contract_simion.txt'
  $oldReport = $env:OATOF_SIMION_SYNC_REPORT
  try {
    $env:OATOF_SIMION_SYNC_REPORT = $report
    Push-Location $formalDir
    & $SimionExe --nogui lua $verifyLua
    if ($LASTEXITCODE -ne 0) { throw "SIMION runtime geometry verification failed with exit code $LASTEXITCODE" }
    if (-not (Select-String -LiteralPath $report -Pattern '^STATUS=PASS$' -Quiet)) { throw 'SIMION runtime geometry report did not pass.' }
  } finally {
    Pop-Location
    $env:OATOF_SIMION_SYNC_REPORT = $oldReport
  }
}

Write-Output 'GEOMETRY_CONTRACT_STATUS=PASS'
Write-Output ("ACCELERATOR_AXIS_X_MM={0}" -f $axisX)
Write-Output ("DETECTOR_X_MM={0}" -f (-$axisX + $detectorOffsetX))
Write-Output ("DETECTOR_RADIUS_MM={0}" -f $contract.geometry_mm.detector_radius)
if (-not $SkipRuntime) { Write-Output ("COMSOL_FORMAL_MPH_SHA256={0}" -f $mphHash) }
