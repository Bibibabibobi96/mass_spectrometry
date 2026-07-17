param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [Parameter(Mandatory=$true)][string]$OutputDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$contract = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$geometry = $contract.geometry_mm
$accelerator = $contract.geometry_derivation.accelerator
$voltage = $contract.electrodes_V
$outputFull = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $outputFull) { throw "Smoke output already exists: $outputFull" }
New-Item -ItemType Directory -Path $outputFull | Out-Null

function Invoke-Builder([string]$Script, [object[]]$Arguments) {
  & $SimionExe --nogui lua $Script @Arguments
  if ($LASTEXITCODE -ne 0) { throw "SIMION builder failed: $Script" }
}

Invoke-Builder (Join-Path $projectRoot 'simion\accelerator\build_accelerator_variant.lua') @(
  (Join-Path $projectRoot 'simion\accelerator\oatof_accelerator_3d.gem'),
  (Join-Path $outputFull 'accelerator_smoke.pa#'),
  2.0, 1.0, $geometry.accelerator_bore_half, $geometry.accelerator_ring_width,
  $geometry.accelerator_insulation_gap, $geometry.accelerator_rear_clearance,
  $geometry.accelerator_shield_wall, 0, 0.1, 0, 0, 0,
  $accelerator.d1_mm, $accelerator.d2_mm, $contract.rings.accelerator_count,
  $geometry.accelerator_repeller_thickness, $geometry.accelerator_ring_thickness,
  $geometry.accelerator_front_vacuum_margin, $voltage.repeller, $voltage.grid1
)

Invoke-Builder (Join-Path $projectRoot 'simion\reflectron\build_reflectron_variant.lua') @(
  (Join-Path $projectRoot 'simion\reflectron\oatof_reflectron_ideal_10_5.gem'),
  (Join-Path $outputFull 'reflectron_smoke.pa#'),
  5.0, 5.0, 0.1, $geometry.flight_tube_r, $geometry.flight_tube_wall,
  $geometry.L_reflectron, $geometry.ring_thickness, $geometry.shield_axial_gap,
  $geometry.shield_endcap_thickness, $geometry.L_stage1, $geometry.L_stage2,
  $geometry.bore_r, $geometry.ring_outer_r, $contract.rings.stage1_count,
  $contract.rings.stage2_count, $voltage.midgrid, $voltage.backplate
)

$expectedAcceleratorElectrodes = 4 + [int]$contract.rings.accelerator_count
$expectedReflectronElectrodes = 4 + [int]$contract.rings.stage1_count + [int]$contract.rings.stage2_count
$acceleratorFiles = @(Get-ChildItem -LiteralPath $outputFull -File -Filter 'accelerator_smoke.pa*')
$reflectronFiles = @(Get-ChildItem -LiteralPath $outputFull -File -Filter 'reflectron_smoke.pa*')
if ($acceleratorFiles.Count -ne $expectedAcceleratorElectrodes + 3) {
  throw "Accelerator PA family mismatch: $($acceleratorFiles.Count)"
}
if ($reflectronFiles.Count -ne $expectedReflectronElectrodes + 3) {
  throw "Reflectron PA family mismatch: $($reflectronFiles.Count)"
}
$runConfigPath = Join-Path $outputFull 'run_config.json'
$runConfig = [ordered]@{
  schema_version=1; role='oa_tof_parameterized_geometry_smoke_run_config'
  run_id=(Split-Path -Leaf $outputFull); project='oa_tof'; mode='parameterized_geometry_smoke'
  project_root=$projectRoot
  inputs=[ordered]@{baseline='config/baseline.json'; resolved_geometry='config/resolved_geometry.json'; mode='config/modes/formal.json'}
  output_dir=$outputFull
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
  --status success --software 'SIMION 2020' --output (Join-Path $outputFull 'accelerator_smoke.pa0') `
  --output (Join-Path $outputFull 'reflectron_smoke.pa0')
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
"PARAMETERIZED_GEOMETRY_BUILD_STATUS=PASS"
"OUTPUT_DIR=$outputFull"
"ACCELERATOR_ELECTRODES=$expectedAcceleratorElectrodes"
"REFLECTRON_ELECTRODES=$expectedReflectronElectrodes"
