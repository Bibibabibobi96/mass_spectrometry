param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [switch]$SkipRuntime
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$componentDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $componentDir '..\..')).Path
$projectRoot = Split-Path -Parent $repoRoot
$baselinePath = Join-Path $componentDir 'config\baseline.json'
$contractPath = Join-Path $componentDir 'config\resolved_geometry.json'
$resolvedLuaPath = Join-Path $componentDir 'simion\workbench\formal\oatof_resolved.lua'
$comsolSourceDir = Join-Path $componentDir 'comsol'
$comsolSources = @(
  (Join-Path $comsolSourceDir 'ms_oaTOF_two_stage_ringstack_reflectron.m')
) + @(Get-ChildItem -LiteralPath $comsolSourceDir -Filter 'oatof_*.m' -File |
  Select-Object -ExpandProperty FullName)
$simionLua = Join-Path $componentDir 'simion\workbench\formal\oatof_ideal_grounded.lua'
$simionFly2 = Join-Path $componentDir 'simion\workbench\formal\oatof_ideal_grounded.fly2'
$ionGeneratorPath = Join-Path $componentDir 'simion\workbench\generate_comsol_consistent_ions.ps1'
$detectorGem = Join-Path $componentDir 'simion\workbench\oatof_detector_ground.gem'
$acceleratorGemPath = Join-Path $componentDir 'simion\accelerator\oatof_accelerator_3d.gem'
$flightTubeGemPath = Join-Path $componentDir 'simion\workbench\oatof_flight_tube_ground.gem'
$flightTubeBuilderPath = Join-Path $componentDir 'simion\workbench\build_flight_tube_variant.lua'
$reflectronGemPath = Join-Path $componentDir 'simion\reflectron\oatof_reflectron_ideal_10_5.gem'
$reflectronBuilderPath = Join-Path $componentDir 'simion\reflectron\build_reflectron_variant.lua'
$formalDir = Join-Path $projectRoot 'artifacts\projects\oa_tof\models\simion\formal\oatof_524amu'
$formalMph = Join-Path $projectRoot 'artifacts\projects\oa_tof\models\comsol\formal\MS_oaTOF_TwoStageRingStackReflectron_Final.mph'
$formalCadAssembly = Join-Path $projectRoot 'artifacts\projects\oa_tof\cad\formal\MS_oaTOF_TwoStageRingStackReflectron_Final_physical_components.sldasm'
$formalCadReport = Join-Path $projectRoot 'artifacts\projects\oa_tof\cad\formal\oaTOF_solidworks_export_report.json'

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
function Assert-NotContains([string]$Text, [string]$Needle, [string]$Label) {
  if ($Text.Contains($Needle)) { throw "$Label contains forbidden legacy logic: $Needle" }
}

$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$formalAssets = Get-Content -LiteralPath (Join-Path $componentDir 'config\formal_assets.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$derivationGate = Join-Path $PSScriptRoot 'verify_geometry_derivation.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 project runtime missing: $python" }
$derivationOutput = & $python $derivationGate $baselinePath
if ($LASTEXITCODE -ne 0 -or $derivationOutput -notcontains 'GEOMETRY_DERIVATION_STATUS=PASS') {
  throw 'Physics-input to engineering-geometry derivation gate failed.'
}
$syncScript = Join-Path $componentDir 'analysis\sync_geometry_contract.py'
$syncOutput = & $python $syncScript --check
if ($LASTEXITCODE -ne 0 -or $syncOutput -notcontains 'GEOMETRY_TEXT_SYNC=PASS') {
  throw 'Resolved geometry or generated SIMION inputs are stale.'
}
if (-not [bool]$contract.simion_runtime.program_required) { throw 'SIMION formal runtime must require Program.' }
$lua = Get-Content -LiteralPath $simionLua -Raw -Encoding UTF8
$fly2 = Get-Content -LiteralPath $simionFly2 -Raw -Encoding UTF8
$ionGenerator = Get-Content -LiteralPath $ionGeneratorPath -Raw -Encoding UTF8
$detector = Get-Content -LiteralPath $detectorGem -Raw -Encoding UTF8
$acceleratorGem = Get-Content -LiteralPath $acceleratorGemPath -Raw -Encoding UTF8
$flightTubeGem = Get-Content -LiteralPath $flightTubeGemPath -Raw -Encoding UTF8
$flightTubeBuilder = Get-Content -LiteralPath $flightTubeBuilderPath -Raw -Encoding UTF8
$reflectronGem = Get-Content -LiteralPath $reflectronGemPath -Raw -Encoding UTF8
$reflectronBuilder = Get-Content -LiteralPath $reflectronBuilderPath -Raw -Encoding UTF8
$comsol = ($comsolSources | ForEach-Object {
  Get-Content -LiteralPath $_ -Raw -Encoding UTF8
}) -join "`n"
$axisX = Get-Adjustable $lua 'accelerator_axis_x_mm'
$axisY = Get-Adjustable $lua 'accelerator_axis_y_mm'
$detectorOffsetX = Get-Adjustable $lua 'detector_mirror_offset_x_mm'
$detectorOffsetY = Get-Adjustable $lua 'detector_mirror_offset_y_mm'
Assert-Near $axisX $contract.coordinate_convention.accelerator_axis_x 'SIMION accelerator axis x'
Assert-Near (-$axisX + $detectorOffsetX) $contract.coordinate_convention.detector_x 'SIMION linked detector x'
Assert-Near $axisY 0 'SIMION accelerator axis y'
Assert-Near (-$axisY + $detectorOffsetY) 0 'SIMION linked detector y'
Assert-Near (Get-Adjustable $lua 'detector_radius_mm') $contract.geometry_mm.detector_radius 'SIMION detector radius'
Assert-Near (Get-Adjustable $lua 'detector_active_plane_z_mm') $contract.simion_detector_marker.active_plane_z_mm 'SIMION detector active plane'
Assert-Near (Get-Adjustable $lua 'detector_marker_absorber_thickness_mm') $contract.simion_detector_marker.absorber_thickness_mm 'SIMION detector marker thickness'
Assert-Near (Get-Adjustable $lua 'detector_marker_front_margin_z_mm') $contract.simion_detector_marker.front_margin_z_mm 'SIMION detector marker front margin'
Assert-Near (Get-Adjustable $lua 'detector_marker_back_margin_z_mm') $contract.simion_detector_marker.back_margin_z_mm 'SIMION detector marker back margin'
Assert-Near (Get-Adjustable $lua 'detector_tstep_enable') 1 'SIMION detector crossing-step control'
Assert-Near (Get-Adjustable $lua 'trajectory_quality') $contract.simion_runtime.trajectory_quality 'SIMION trajectory quality'
Assert-Near (Get-Adjustable $lua 'trajectory_log_enable') ([int]$contract.simion_runtime.trajectory_log_default_enabled) 'SIMION trajectory log default'
Assert-Near (Get-Adjustable $lua 'detector_capture_depth_mm') $contract.simion_detector_marker.capture_depth_mm 'SIMION detector capture depth'
Assert-Near (Get-Adjustable $lua 'detector_capture_arm_distance_mm') $contract.simion_detector_marker.capture_arm_distance_mm 'SIMION detector capture arm distance'
Assert-Near (Get-Adjustable $lua 'accelerator_repeller_front_z_mm') $contract.geometry_mm.accelerator_repeller_z 'SIMION repeller global z'
Assert-Near (Get-Adjustable $lua 'accelerator_grid1_z_mm') $contract.geometry_mm.accelerator_grid1_z 'SIMION grid1 global z'
Assert-Near (Get-Adjustable $lua 'accelerator_grid2_z_mm') $contract.geometry_mm.accelerator_grid2_z 'SIMION grid2 global z'
Assert-Near (Get-Adjustable $lua 'accelerator_assembly_translation_z_mm') $contract.geometry_mm.accelerator_repeller_z 'SIMION formal accelerator translation'
Assert-Near (Get-Adjustable $lua 'accelerator_stage1_length_mm') $contract.geometry_derivation.accelerator.d1_mm 'SIMION formal accelerator stage1 length'
Assert-Near (Get-Adjustable $lua 'accelerator_stage2_length_mm') $contract.geometry_derivation.accelerator.d2_mm 'SIMION formal accelerator stage2 length'
Assert-Near (Get-Adjustable $lua 'accelerator_ring_count') $contract.rings.accelerator_count 'SIMION accelerator ring count'
Assert-Near (Get-Adjustable $lua 'reflectron_stage1_ring_count') $contract.rings.stage1_count 'SIMION reflectron stage1 ring count'
Assert-Near (Get-Adjustable $lua 'reflectron_stage2_ring_count') $contract.rings.stage2_count 'SIMION reflectron stage2 ring count'
Assert-Near (Get-Adjustable $lua 'accelerator_grid_epsilon_mm') $contract.simion_runtime.accelerator_grid_epsilon_mm 'SIMION accelerator grid jump default'
Assert-Near (Get-Adjustable $lua 'reflectron_grid_epsilon_mm') $contract.simion_runtime.reflectron_grid_epsilon_mm 'SIMION reflectron grid jump default'
Assert-Near ((Get-Adjustable $lua 'accelerator_grid2_z_mm') + (Get-Adjustable $lua 'accelerator_focus_drift_mm')) $contract.simion_detector_marker.active_plane_z_mm 'SIMION detector/focus plane linkage'
Assert-Near (Get-Adjustable $lua 'reflectron_entgrid_z_mm') $contract.geometry_mm.L_flight 'SIMION entgrid/L_flight'
Assert-Near (Get-Adjustable $lua 'reflectron_midgrid_z_mm') ($contract.geometry_mm.L_flight + $contract.geometry_mm.L_stage1) 'SIMION midgrid'
Assert-Near (Get-Adjustable $lua 'reflectron_backplate_z_mm') ($contract.geometry_mm.L_flight + $contract.geometry_mm.L_reflectron) 'SIMION backplate'
Assert-Near (Get-Adjustable $lua 'accelerator_repeller_thickness_mm') $contract.geometry_mm.accelerator_repeller_thickness 'SIMION repeller thickness'
Assert-Near (Get-Adjustable $lua 'accelerator_bore_half_mm') $contract.geometry_mm.accelerator_bore_half 'SIMION accelerator bore half-width'
Assert-Near (Get-Adjustable $lua 'accelerator_ring_width_mm') $contract.geometry_mm.accelerator_ring_width 'SIMION accelerator ring width'
Assert-Near (Get-Adjustable $lua 'accelerator_insulation_gap_mm') $contract.geometry_mm.accelerator_insulation_gap 'SIMION accelerator insulation gap'
Assert-Near (Get-Adjustable $lua 'accelerator_shield_wall_mm') $contract.geometry_mm.accelerator_shield_wall 'SIMION accelerator shield wall'
Assert-Near (Get-Adjustable $lua 'accelerator_rear_insulation_gap_mm') $contract.geometry_mm.accelerator_rear_clearance 'SIMION accelerator rear clearance'
Assert-Near (Get-Adjustable $lua 'flight_tube_inner_radius_mm') $contract.geometry_mm.flight_tube_r 'SIMION shield inner radius'
Assert-Near (Get-Adjustable $lua 'flight_tube_shield_wall_mm') $contract.geometry_mm.flight_tube_wall 'SIMION shield wall'
Assert-Near (Get-Adjustable $lua 'flight_tube_near_endcap_gap_mm') $contract.geometry_mm.shield_near_endcap_gap 'SIMION near-end clearance'
Assert-Near (Get-Adjustable $lua 'flight_tube_far_endcap_gap_mm') $contract.geometry_mm.shield_axial_gap 'SIMION far-end clearance'
Assert-Near (Get-Adjustable $lua 'flight_tube_endcap_thickness_mm') $contract.geometry_mm.shield_endcap_thickness 'SIMION end-cap thickness'
Assert-Near (Get-Adjustable $lua 'reflectron_backplate_thickness_mm') $contract.geometry_mm.ring_thickness 'SIMION backplate thickness'
$exitGridHalf = (Get-Adjustable $lua 'accelerator_bore_half_mm') +
  (Get-Adjustable $lua 'accelerator_ring_width_mm') +
  (Get-Adjustable $lua 'accelerator_insulation_gap_mm')
Assert-Near $exitGridHalf $contract.geometry_mm.accelerator_exit_grid_half_width 'SIMION accelerator exit-grid half-width'
$shieldNearBore = (Get-Adjustable $lua 'accelerator_repeller_front_z_mm') -
  (Get-Adjustable $lua 'accelerator_repeller_thickness_mm') -
  (Get-Adjustable $lua 'accelerator_rear_insulation_gap_mm') -
  (Get-Adjustable $lua 'accelerator_shield_wall_mm') -
  (Get-Adjustable $lua 'flight_tube_near_endcap_gap_mm')
$shieldNearOuter = $shieldNearBore - (Get-Adjustable $lua 'flight_tube_endcap_thickness_mm')
$shieldFarBore = (Get-Adjustable $lua 'reflectron_backplate_z_mm') +
  (Get-Adjustable $lua 'reflectron_backplate_thickness_mm') +
  (Get-Adjustable $lua 'flight_tube_far_endcap_gap_mm')
$shieldFarOuter = $shieldFarBore + (Get-Adjustable $lua 'flight_tube_endcap_thickness_mm')
Assert-Near $shieldNearBore $contract.geometry_mm.shield_bore_z_min 'SIMION near bore face'
Assert-Near $shieldNearOuter $contract.geometry_mm.shield_outer_z_min 'SIMION near outer face'
Assert-Near $shieldFarBore $contract.geometry_mm.shield_bore_z_max 'SIMION far bore face'
Assert-Near $shieldFarOuter $contract.geometry_mm.shield_outer_z_max 'SIMION far outer face'
Assert-Near (Get-Adjustable $lua 'V_repeller') $contract.electrodes_V.repeller 'SIMION repeller voltage'
Assert-Near (Get-Adjustable $lua 'V_grid1') $contract.electrodes_V.grid1 'SIMION grid1 voltage'
Assert-Near (Get-Adjustable $lua 'V_mid') $contract.electrodes_V.midgrid 'SIMION midgrid voltage'
Assert-Near (Get-Adjustable $lua 'V_backplate') $contract.electrodes_V.backplate 'SIMION backplate voltage'

Assert-Contains $lua 'local half_x=(ai.pa.nx-1)*ai.pa.dx_mm*ai.scale/2' 'SIMION accelerator x half-span linkage'
Assert-Contains $lua 'local half_y=(ai.pa.ny-1)*ai.pa.dy_mm*ai.scale/2' 'SIMION accelerator y half-span linkage'
Assert-Contains $lua 'ai.x,ai.y,ai.z=accelerator_axis_x_mm-half_x,accelerator_axis_y_mm-half_y,' 'SIMION accelerator lateral transform'
Assert-Contains $lua 'accelerator_instance_z_mm-accelerator_pa_back_margin_mm-' 'SIMION accelerator axial transform'
Assert-Contains $lua 'detector_x_mm=-accelerator_axis_x_mm+detector_mirror_offset_x_mm' 'SIMION detector x'
Assert-Contains $lua 'detector_z_mm=detector_active_plane_z_mm' 'SIMION detector z'
Assert-Contains $lua 'di.x=detector_x_mm-detector_half_x' 'SIMION detector PA x transform'
Assert-Contains $lua 'di.z=detector_z_mm-detector_marker_back_margin_z_mm-' 'SIMION detector PA z transform'
Assert-Contains $lua "if ion_instance~=INSTANCE_DETECTOR then" 'SIMION physical detector termination'
Assert-Contains $lua 'function segment.tstep_adjust()' 'SIMION detector time-step control'
Assert-Contains $lua 'local dt_to_capture=(dz+detector_capture_depth_mm)/speed_z' 'SIMION detector event-aligned capture step'
Assert-Contains $lua 'dz>detector_capture_arm_distance_mm' 'SIMION detector bounded event prediction'
Assert-Contains $lua 'if ion_time_step>dt_to_capture then ion_time_step=dt_to_capture end' 'SIMION detector single-step cap'
Assert-NotContains $lua 'detector_tstep_max_dz_mm' 'SIMION detector blanket fine stepping'
Assert-Contains $lua 'TRACE: detector_splat_raw' 'SIMION native splat audit'
Assert-Contains $lua 'function segment.load()' 'SIMION load-time settings'
Assert-Contains $lua 'sim_trajectory_quality=trajectory_quality' 'SIMION persisted trajectory quality'
Assert-Contains $lua 'inside_grid(g,ion_px_mm,ion_py_mm)' 'SIMION finite grid footprint gate'
Assert-Contains $lua 'local eps=override>0 and override or ideal_grid_epsilon_mm' 'SIMION grouped grid jump fallback'
Assert-Contains $lua 'local INSTANCE_FLIGHT_TUBE=1' 'SIMION lowest-priority shield slot'
Assert-Contains $lua 'local INSTANCE_REFLECTRON=2' 'SIMION reflectron-above-shield slot'
Assert-Contains $lua 'local INSTANCE_ACCELERATOR=3' 'SIMION accelerator slot'
Assert-Contains $lua 'local INSTANCE_DETECTOR=4' 'SIMION highest-priority detector slot'
Assert-NotContains $lua 'function segment.instance_adjust' 'SIMION runtime PA-priority override'
Assert-NotContains $lua 'detector_plane' 'SIMION detector implementation'
Assert-NotContains $lua 'detector_hit_interpolated' 'SIMION detector implementation'
Assert-Contains $detector 'GUI-visible detector-position marker and numerical absorber' 'SIMION detector marker role'
Assert-Contains $detector '# local radius = var.radius or 40' 'SIMION detector GEM radius'
Assert-Contains $detector '# local mmgu_xy = var.mmgu_xy or 0.5' 'SIMION detector GEM xy cell'
Assert-Contains $detector '# local mmgu_z = var.mmgu_z or 0.01' 'SIMION detector GEM z cell'
Assert-Contains $detector '# local absorber_thickness = var.absorber_thickness or 0.1' 'SIMION detector GEM marker thickness'
Assert-Contains $acceleratorGem '# local shield_inner_width = electrode_width+2*insulation_gap' 'SIMION linked shield opening'
Assert-Contains $acceleratorGem '# local ring_pitch = stage2_length/(ring_count+1)' 'SIMION equal accelerator ring pitch'
Assert-Contains $acceleratorGem '# for ring_index=1,ring_count do' 'SIMION parameterized accelerator ring loop'
Assert-Contains $acceleratorGem 'e($(3+ring_count)) { fill { within { centered_box3D(0,0,$(stage1_length+stage2_length)' 'SIMION parameterized accelerator exit grid entity'
Assert-Contains $acceleratorGem 'e($(4+ring_count)) { fill {' 'SIMION parameterized accelerator shield electrode'
Assert-Contains $flightTubeGem '# local wall = var.wall or 10' 'SIMION field-free shield wall'
Assert-Contains $flightTubeGem '# local near_cap_thickness = var.near_cap_thickness or 10' 'SIMION near end-cap thickness'
Assert-Contains $flightTubeGem '# local near_outer_z = var.near_outer_z or ' 'SIMION shield near outer-face parameter interface'
Assert-Contains $flightTubeGem 'box(0,0,$(near_cap_thickness),$(outer_radius))' 'SIMION full near end cap'
Assert-Contains $flightTubeGem 'box($(side_start),$(inner_radius),$(side_end),$(outer_radius))' 'SIMION continuous field-free side wall'
Assert-Contains $flightTubeBuilder "local wall = tonumber(arg[7] or '10')" 'SIMION field-free builder wall default'
Assert-Contains $reflectronGem '# local wall = var.wall or 10' 'SIMION reflectron shield wall'
Assert-Contains $reflectronGem '# local far_clearance = var.far_clearance or 50' 'SIMION far clearance'
Assert-Contains $reflectronGem '# local far_cap_thickness = var.far_cap_thickness or 10' 'SIMION far end-cap thickness'
Assert-Contains $reflectronGem 'box($(bore_end),0,$(outer_end),$(outer_radius))' 'SIMION full far end cap'
Assert-Contains $reflectronGem '# for ring_index=1,stage1_ring_count do' 'SIMION parameterized stage1 ring loop'
Assert-Contains $reflectronGem '# for ring_index=1,stage2_ring_count do' 'SIMION parameterized stage2 ring loop'
Assert-Contains $reflectronGem 'e($(3+stage1_ring_count+stage2_ring_count))' 'SIMION parameterized backplate electrode'
Assert-Contains $reflectronBuilder "local wall = tonumber(arg[7] or '10')" 'SIMION reflectron builder wall default'
Assert-Contains $reflectronBuilder "local far_clearance = tonumber(arg[10] or '50')" 'SIMION reflectron builder clearance default'
Assert-Contains $fly2 'Generated by analysis/sync_geometry_contract.py' 'SIMION GUI particle generator identity'
Assert-Contains $fly2 'standard_beam {' 'SIMION GUI particle definition'
Assert-Contains $fly2 'charge = 1' 'SIMION GUI particle charge'
Assert-Contains $comsol "p.set('detector_x', '-x_accel_center'" 'COMSOL detector x parameter'
Assert-Contains $comsol 'contract = load_oatof_contract();' 'COMSOL resolved-contract loader'
Assert-Contains $comsol "p.set('detector_radius', sprintf('%.12g[mm]', geometryMm.detector_radius)" 'COMSOL detector radius parameter'
Assert-Contains $comsol "p.set('E_mean_eV', sprintf('%.12g[V]', contract.validation_target.initial_energy_mean_ev)" 'COMSOL mean initial energy'
Assert-Contains $comsol "p.set('flight_tube_wall', sprintf('%.12g[mm]', geometryMm.flight_tube_wall)" 'COMSOL shield wall thickness'
Assert-Contains $comsol 'd2_raw_mm = reflectron_stage2_min_mm*(1+d2_margin_fraction);' 'COMSOL unrounded physical stage2 derivation'
Assert-Contains $comsol 'reflectron_backplate_voltage_v = reflectron_midgrid_voltage_v + reflectron_stage2_field_vpm*(d2_raw_mm/1000);' 'COMSOL voltage derivation before engineering rounding'
Assert-Contains $comsol 'd2_mm = round(d2_raw_mm, reflectronDesign.engineering_length_decimals_mm);' 'COMSOL baseline engineering-length precision'
Assert-Contains $comsol "p.set('L_refl', sprintf('%.12g[mm]', d1_mm+d2_mm)" 'COMSOL reflectron serialization precision'
Assert-Contains $comsol "if nargin < 9 || isempty(ring_thickness_mm)" 'COMSOL backplate-thickness default branch'
Assert-Contains $comsol "ring_thickness_mm = geometryMm.ring_thickness;" 'COMSOL backplate-thickness default'
Assert-Contains $comsol "if nargin < 12 || isempty(accel_bore_half_mm)" 'COMSOL accelerator-bore default branch'
Assert-Contains $comsol "accel_bore_half_mm = geometryMm.accelerator_bore_half;" 'COMSOL accelerator-bore default'
Assert-Contains $comsol "z0_bore = 'z_accel_origin-accel_repeller_thickness-accel_shield_back_extra-accel_shield_wall-endcap_gap';" 'COMSOL linked near bore face'
Assert-Contains $comsol "z1_bore = 'L_flight+L_refl+ring_thickness+shield_axial_gap';" 'COMSOL linked far bore face'
Assert-Contains $comsol "geom1.feature('flighttubewallO').set('h', [z1_bore '-(' z0_bore ')+2*flight_tube_wall']);" 'COMSOL two end-cap thicknesses'
Assert-Contains $comsol "Flight tube shield (grounded, one-piece shell with both ends closed -- encloses field-free tube + reflectron)" 'COMSOL authoritative closed shield'
Assert-Contains $comsol "'wp_grid2',     'z_accel_grid2' 'square'  '2*accel_shield_half'" 'COMSOL accelerator exit grid geometry'
Assert-Contains $ionGenerator '[double]$CenterXmm' 'SIMION ION parameterized source x center'
Assert-Contains $ionGenerator '[double]$CenterYmm' 'SIMION ION parameterized source y center'
Assert-Contains $ionGenerator '[double]$CenterZmm' 'SIMION ION parameterized source z center'
Assert-Contains $comsol 'if nargin<1, mass_amu = contract.validation_target.mass_amu; end' 'COMSOL standard mass'
Assert-Contains $comsol "geom1.feature('detector').set('r', 'detector_radius')" 'COMSOL detector radius geometry'
Assert-Contains $comsol "geometryMm.detector_thickness" 'COMSOL detector thickness/position linkage'

if (-not $SkipRuntime) {
  if ($formalAssets.comsol.geometry_status -ne 'synchronized') {
    throw "Formal COMSOL geometry is not synchronized: $($formalAssets.comsol.geometry_status). Use -SkipRuntime only for candidate/source validation."
  }
  if ($formalAssets.solidworks.geometry_status -ne 'synchronized') {
    throw "Formal SolidWorks geometry is not synchronized: $($formalAssets.solidworks.geometry_status)."
  }
  if (-not (Test-Path -LiteralPath $formalDir)) { throw "Formal SIMION runtime workspace missing: $formalDir" }
  if (-not (Test-Path -LiteralPath $formalMph)) { throw "Formal COMSOL MPH missing: $formalMph" }
  if (-not (Test-Path -LiteralPath $formalCadAssembly)) { throw "Formal SolidWorks assembly missing: $formalCadAssembly" }
  if (-not (Test-Path -LiteralPath $formalCadReport)) { throw "Formal SolidWorks export report missing: $formalCadReport" }
  $mphHash = (Get-FileHash -LiteralPath $formalMph -Algorithm SHA256).Hash
  if ($mphHash -ne $formalAssets.comsol.sha256) { throw 'Formal COMSOL MPH differs from the verified asset manifest.' }
  $cadHash = (Get-FileHash -LiteralPath $formalCadAssembly -Algorithm SHA256).Hash
  if ($cadHash -ne $formalAssets.solidworks.assembly_sha256) { throw 'Formal SolidWorks assembly differs from the verified asset manifest.' }
  $cadReport = Get-Content -LiteralPath $formalCadReport -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($cadReport.solidWorks.solidWorksRevision -ne $formalAssets.solidworks.revision) { throw 'Formal SolidWorks revision differs from the verified asset manifest.' }
  if ($cadReport.solidWorks.partCount -ne $formalAssets.solidworks.component_count) { throw 'Formal SolidWorks part count differs from the verified asset manifest.' }
  if ($cadReport.solidWorks.assembly.componentCount -ne $formalAssets.solidworks.component_count) { throw 'Formal SolidWorks assembly component count differs from the verified asset manifest.' }
  if ($cadReport.solidWorks.assembly.saveErrors -ne 0 -or $cadReport.solidWorks.assembly.saveWarnings -ne 0) { throw 'Formal SolidWorks assembly report contains save errors or warnings.' }
  if (($cadReport.solidWorks.parts | Measure-Object -Property saveErrors -Maximum).Maximum -ne 0 -or ($cadReport.solidWorks.parts | Measure-Object -Property saveWarnings -Maximum).Maximum -ne 0) { throw 'Formal SolidWorks part report contains save errors or warnings.' }
  $runtimeLua = Join-Path $formalDir 'oatof_ideal_grounded.lua'
  if ((Get-FileHash -LiteralPath $simionLua -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $runtimeLua -Algorithm SHA256).Hash) { throw 'Formal SIMION runtime Lua differs from source.' }
  $runtimeFly2 = Join-Path $formalDir 'oatof_ideal_grounded.fly2'
  if ((Get-FileHash -LiteralPath $simionFly2 -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $runtimeFly2 -Algorithm SHA256).Hash) { throw 'Formal SIMION runtime Fly2 differs from source.' }
  $verifyLua = Join-Path $componentDir 'tests\simion\verify_formal_runtime.lua'
  $report = Join-Path $env:TEMP 'oatof_geometry_contract_simion.txt'
  try {
    Push-Location $formalDir
    & $SimionExe --nogui lua $verifyLua $report (Join-Path $formalDir 'oatof_ideal_grounded.iob') $resolvedLuaPath
    if ($LASTEXITCODE -ne 0) { throw "SIMION runtime geometry verification failed with exit code $LASTEXITCODE" }
    if (-not (Select-String -LiteralPath $report -Pattern '^STATUS=PASS$' -Quiet)) { throw 'SIMION runtime geometry report did not pass.' }
  } finally {
    Pop-Location
  }
}

Write-Output 'GEOMETRY_CONTRACT_STATUS=PASS'
Write-Output ("ACCELERATOR_AXIS_X_MM={0}" -f $axisX)
Write-Output ("DETECTOR_X_MM={0}" -f (-$axisX + $detectorOffsetX))
Write-Output ("DETECTOR_RADIUS_MM={0}" -f $contract.geometry_mm.detector_radius)
$derivationOutput | Write-Output
if (-not $SkipRuntime) {
  Write-Output ("COMSOL_FORMAL_MPH_SHA256={0}" -f $mphHash)
  Write-Output ("SOLIDWORKS_FORMAL_ASSEMBLY_SHA256={0}" -f $cadHash)
  Write-Output ("SOLIDWORKS_FORMAL_COMPONENT_COUNT={0}" -f $cadReport.solidWorks.assembly.componentCount)
}
