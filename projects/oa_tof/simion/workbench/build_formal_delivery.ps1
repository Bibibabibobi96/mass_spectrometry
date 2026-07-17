param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$OutputDir = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$baselinePath = Join-Path $projectRoot 'config\baseline.json'
$modePath = Join-Path $projectRoot 'config\modes\formal.json'
$contractPath = Join-Path $projectRoot 'config\resolved_geometry.json'

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $OutputDir = Join-Path $artifactRoot "models\simion\candidates\oatof_524amu_$stamp"
}
$outputFull = [IO.Path]::GetFullPath($OutputDir)
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $artifactRoot 'models\simion'))
if (-not $outputFull.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputDir must remain under $allowedRoot"
}
if (Test-Path -LiteralPath $outputFull) {
  throw "Output directory already exists; no automatic overwrite is allowed: $outputFull"
}
New-Item -ItemType Directory -Path $outputFull | Out-Null

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $projectRoot 'analysis\sync_geometry_contract.py') --write
if ($LASTEXITCODE -ne 0) { throw 'SIMION text synchronization failed.' }
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$geometry = $contract.geometry_mm
$accelerator = $contract.geometry_derivation.accelerator
$build = $contract.simion_geometry_build
$detector = $contract.simion_detector_marker
$source = $contract.particle_source
$voltage = $contract.electrodes_V

function Invoke-SimionLua([string]$Script, [object[]]$Arguments) {
  & $SimionExe --nogui lua $Script @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "SIMION Lua failed with exit code ${LASTEXITCODE}: $Script"
  }
}

$acceleratorStem = Join-Path $outputFull 'accelerator.pa#'
Invoke-SimionLua (Join-Path $projectRoot 'simion\accelerator\build_accelerator_variant.lua') @(
  (Join-Path $projectRoot 'simion\accelerator\oatof_accelerator_3d.gem'), $acceleratorStem,
  $build.accelerator.cell_xy_mm, $build.accelerator.cell_z_mm,
  $geometry.accelerator_bore_half, $geometry.accelerator_ring_width,
  $geometry.accelerator_insulation_gap, $geometry.accelerator_rear_clearance,
  $geometry.accelerator_shield_wall, $build.accelerator.vacuum_margin_mm,
  $build.accelerator.max_gib, $build.accelerator.back_domain_margin_mm,
  $build.accelerator.front_domain_margin_mm, $build.accelerator.grid_phase_z_mm,
  $accelerator.d1_mm, $accelerator.d2_mm, $contract.rings.accelerator_count,
  $geometry.accelerator_repeller_thickness, $geometry.accelerator_ring_thickness,
  $geometry.accelerator_front_vacuum_margin, $voltage.repeller, $voltage.grid1
)

$reflectronStem = Join-Path $outputFull 'reflectron.pa#'
Invoke-SimionLua (Join-Path $projectRoot 'simion\reflectron\build_reflectron_variant.lua') @(
  (Join-Path $projectRoot 'simion\reflectron\oatof_reflectron_ideal_10_5.gem'), $reflectronStem,
  $build.reflectron.cell_axial_mm, $build.reflectron.cell_radial_mm,
  $build.reflectron.max_gib, $geometry.flight_tube_r, $geometry.flight_tube_wall,
  $geometry.L_reflectron, $geometry.ring_thickness, $geometry.shield_axial_gap,
  $geometry.shield_endcap_thickness, $geometry.L_stage1, $geometry.L_stage2,
  $geometry.bore_r, $geometry.ring_outer_r, $contract.rings.stage1_count,
  $contract.rings.stage2_count, $voltage.midgrid, $voltage.backplate
)

$flightTubeStem = Join-Path $outputFull 'flight_tube_ground.pa#'
Invoke-SimionLua (Join-Path $projectRoot 'simion\workbench\build_flight_tube_variant.lua') @(
  (Join-Path $projectRoot 'simion\workbench\oatof_flight_tube_ground.gem'), $flightTubeStem,
  $build.flight_tube.cell_axial_mm, $build.flight_tube.cell_radial_mm,
  $build.flight_tube.max_gib, $geometry.flight_tube_r, $geometry.flight_tube_wall,
  $geometry.shield_endcap_thickness, $geometry.shield_outer_z_min, $geometry.L_flight
)

$detectorStem = Join-Path $outputFull 'detector_ground.pa#'
Invoke-SimionLua (Join-Path $projectRoot 'simion\workbench\build_detector_variant.lua') @(
  (Join-Path $projectRoot 'simion\workbench\oatof_detector_ground.gem'), $detectorStem,
  $detector.cell_xy_mm, $detector.cell_z_mm, $detector.active_radius_mm,
  $detector.absorber_thickness_mm, $detector.front_margin_z_mm,
  $detector.back_margin_z_mm, $build.detector.margin_xy_mm, $build.detector.max_mib
)

$ionGenerator = Join-Path $PSScriptRoot 'generate_comsol_consistent_ions.ps1'
foreach ($particleCount in @(100, 1000)) {
  $ionPath = Join-Path $outputFull "oatof_comsol_524amu_gaussian_N$particleCount.ion"
  & $ionGenerator -N $particleCount -MassAmu $contract.validation_target.mass_amu -Charge 1 `
    -EnergyMeanEv $contract.validation_target.initial_energy_mean_ev `
    -EnergyStdEv $contract.validation_target.initial_energy_sigma_ev `
    -HalfWidthXmm ($source.size_x_mm/2) -HalfWidthYmm ($source.size_y_mm/2) `
    -HalfWidthZmm ($source.size_z_mm/2) -CenterXmm $source.center_x_mm `
    -CenterYmm $source.center_y_mm -CenterZmm $source.center_z_mm `
    -Seed $source.seed -Output $ionPath | Out-Null
}

Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\SIMION_REPRODUCTION_PARAMETERS.md') `
  -Destination (Join-Path $outputFull 'SIMION_REPRODUCTION_PARAMETERS.md')
Copy-Item -LiteralPath $baselinePath -Destination (Join-Path $outputFull 'baseline.json')
Copy-Item -LiteralPath $modePath -Destination (Join-Path $outputFull 'formal_mode.json')
Copy-Item -LiteralPath $contractPath -Destination (Join-Path $outputFull 'resolved_geometry.json')
$resolvedLua = Join-Path $projectRoot 'simion\workbench\formal\oatof_resolved.lua'
Copy-Item -LiteralPath $resolvedLua -Destination (Join-Path $outputFull 'oatof_resolved.lua')

$runId = Split-Path -Leaf $outputFull
$runConfigPath = Join-Path $outputFull 'run_config.json'
$runConfig = [ordered]@{
  schema_version = 1; role = 'oa_tof_simion_delivery_run_config'
  run_id = $runId; project = 'oa_tof'; mode = 'formal_delivery_candidate'
  project_root = $projectRoot
  inputs = [ordered]@{baseline='config/baseline.json'; resolved_geometry='config/resolved_geometry.json'; mode='config/modes/formal.json'}
  output_dir = $outputFull; overwrite = $false
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

$template = Join-Path $artifactRoot 'models\simion\formal\oatof_524amu\oatof_ideal_grounded.iob'
if (-not (Test-Path -LiteralPath $template -PathType Leaf)) {
  throw "Four-instance template IOB is unavailable: $template"
}
$iobOutput = Join-Path $outputFull 'oatof_ideal_grounded.iob'
Invoke-SimionLua (Join-Path $PSScriptRoot 'build_formal_iob.lua') @(
  (Join-Path $outputFull 'oatof_resolved.lua'), $iobOutput, $template,
  (Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'),
  (Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.fly2')
)

foreach ($required in @('oatof_ideal_grounded.iob','oatof_ideal_grounded.con','oatof_ideal_grounded.lua','oatof_ideal_grounded.fly2')) {
  if (-not (Test-Path -LiteralPath (Join-Path $outputFull $required) -PathType Leaf)) {
    throw "Delivery is missing $required"
  }
}
$hashes = Get-ChildItem -LiteralPath $outputFull -File | Where-Object {
  $_.Name -ne 'SHA256SUMS.csv' -and $_.Name -notlike 'trj*.tmp'
} | Sort-Object Name | ForEach-Object {
  [pscustomobject]@{file=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
}
$hashes | Export-Csv -LiteralPath (Join-Path $outputFull 'SHA256SUMS.csv') -NoTypeInformation -Encoding UTF8
$manifestScript = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
& $python $manifestScript --run-config $runConfigPath --status success --software 'SIMION 2020' `
  --output $iobOutput --output (Join-Path $outputFull 'oatof_ideal_grounded.lua') `
  --output (Join-Path $outputFull 'oatof_ideal_grounded.fly2') `
  --output (Join-Path $outputFull 'SHA256SUMS.csv')
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
"STATUS=PASS OUTPUT_DIR=$outputFull FILES=$($hashes.Count)"
