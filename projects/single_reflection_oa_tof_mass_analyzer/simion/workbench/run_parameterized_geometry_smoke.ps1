# Candidate gate runner for parameterized accelerator and reflectron builds.
param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$OutputDir = '',
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__gate__simion__native-ideal-grid__smoke'
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
  $OutputDir = Join-Path $artifactRoot "runs\$RunId\simion"
}
$contract = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$numerics = Get-Content -LiteralPath (Join-Path $projectRoot 'config\formal_solver_numerics.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$geometry = $contract.geometry_mm
$accelerator = $contract.geometry_derivation.accelerator
$voltage = $contract.electrodes_V
$acceleratorBuild = $numerics.simion.geometry_build.accelerator
$reflectronBuild = $numerics.simion.geometry_build.reflectron
$numericsPath = Join-Path $projectRoot 'config\formal_solver_numerics.json'
$numericsSha256 = (Get-FileHash -LiteralPath $numericsPath -Algorithm SHA256).Hash
$acceleratorXySpan = 2 * ([double]$geometry.accelerator_bore_half + [double]$geometry.accelerator_ring_width + [double]$geometry.accelerator_insulation_gap + [double]$geometry.accelerator_shield_wall)
$acceleratorZMinForBudget = -[double]$geometry.accelerator_repeller_thickness - [double]$geometry.accelerator_rear_clearance - [double]$geometry.accelerator_shield_wall
$acceleratorZSpan = [double]$accelerator.d1_mm + [double]$accelerator.d2_mm + [double]$geometry.accelerator_front_vacuum_margin - $acceleratorZMinForBudget
$acceleratorNx = [Math]::Floor($acceleratorXySpan / [double]$acceleratorBuild.cell_xy_mm + 0.5) + 1
$acceleratorNz = [Math]::Floor($acceleratorZSpan / [double]$acceleratorBuild.cell_z_mm + 0.5) + 1
$acceleratorEstimatedGib = $acceleratorNx * $acceleratorNx * $acceleratorNz * 8 * 11.25 / [Math]::Pow(1024,3)
$reflectronAxialSpan = [double]$geometry.L_reflectron + [double]$geometry.ring_thickness + [double]$geometry.shield_axial_gap + [double]$geometry.shield_endcap_thickness
$reflectronRadialSpan = [double]$geometry.flight_tube_r + [double]$geometry.flight_tube_wall
$reflectronNx = [Math]::Ceiling($reflectronAxialSpan / [double]$reflectronBuild.cell_axial_mm) + 1
$reflectronNy = [Math]::Ceiling($reflectronRadialSpan / [double]$reflectronBuild.cell_radial_mm) + 1
$reflectronArrayFactor = [int]$contract.rings.stage1_count + [int]$contract.rings.stage2_count + 6.25
$reflectronEstimatedGib = $reflectronNx * $reflectronNy * 8 * $reflectronArrayFactor / [Math]::Pow(1024,3)
if ($acceleratorEstimatedGib -gt [double]$acceleratorBuild.max_gib) { throw 'Formal accelerator PA estimate exceeds its solver-numerics authority.' }
if ($reflectronEstimatedGib -gt [double]$reflectronBuild.max_gib) { throw 'Formal reflectron PA estimate exceeds its solver-numerics authority.' }
$artifactOutputFull = [IO.Path]::GetFullPath($OutputDir)
$runDir = Split-Path -Parent $artifactOutputFull
if (Test-Path -LiteralPath $artifactOutputFull) { throw "Smoke output already exists: $artifactOutputFull" }
New-Item -ItemType Directory -Path $artifactOutputFull | Out-Null
$executionAlias = New-RunExecutionAlias -TargetDirectory $artifactOutputFull `
  -ExpectedExecutionRelativePaths @('native_ideal_grid_crossing.stderr.log')
$outputFull = [string]$executionAlias.execution_alias
$runConfigPath = Join-Path $runDir 'run_config.json'
$summaryPath = Join-Path $runDir 'summary.json'
$manifestPath = Join-Path $runDir 'run_manifest.json'
try {
$runConfig = [ordered]@{
  schema_version=2; role='oa_tof_native_ideal_grid_smoke_run_config'
  run_id=$RunId; project='single_reflection_oa_tof_mass_analyzer'; mode='native_ideal_grid_smoke'
  project_root=$projectRoot; formal_gate_passed=$false
  inputs=[ordered]@{baseline='config/baseline.json';resolved_geometry='config/resolved_geometry.json';solver_numerics='config/formal_solver_numerics.json';mode='config/modes/formal.json'}
  output_dir=$artifactOutputFull
  actual_cells_mm=[ordered]@{
    accelerator=[ordered]@{x=[double]$acceleratorBuild.cell_xy_mm;y=[double]$acceleratorBuild.cell_xy_mm;z=[double]$acceleratorBuild.cell_z_mm}
    reflectron=[ordered]@{axial=[double]$reflectronBuild.cell_axial_mm;radial=[double]$reflectronBuild.cell_radial_mm}
  }
  pa_resource_budget=[ordered]@{
    authority_path='config/formal_solver_numerics.json';authority_sha256=$numericsSha256
    accelerator=[ordered]@{max_gib=[double]$acceleratorBuild.max_gib;estimated_gib=$acceleratorEstimatedGib;dimensions=@($acceleratorNx,$acceleratorNx,$acceleratorNz)}
    reflectron=[ordered]@{max_gib=[double]$reflectronBuild.max_gib;estimated_gib=$reflectronEstimatedGib;dimensions=@($reflectronNx,$reflectronNy,1)}
  }
  artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
}
Write-RunJson -Value $runConfig -Path $runConfigPath
Write-RunJson -Value ([ordered]@{schema_version=2;role='oa_tof_native_ideal_grid_smoke_summary';status='interrupted';reason='Run package initialized.';threshold_result_eligible=$false}) -Path $summaryPath
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath `
  -Manifest $manifestPath -Status interrupted -Software @('SIMION 2020') -Outputs @($summaryPath)
} catch {
  Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias -TargetDirectory $artifactOutputFull
  throw
}
$terminalized = $false
$failureStage = 'run_initialization'
$stageWallSeconds = [ordered]@{}

function Invoke-Builder([string]$Script, [object[]]$Arguments, [string]$LogStem) {
  $timer = [Diagnostics.Stopwatch]::StartNew()
  & $SimionExe --nogui lua $Script @Arguments `
    1> (Join-Path $outputFull ($LogStem + '.log')) `
    2> (Join-Path $outputFull ($LogStem + '.stderr.log'))
  $timer.Stop()
  $stageWallSeconds[$LogStem] = [Math]::Round($timer.Elapsed.TotalSeconds,3)
  if ($LASTEXITCODE -ne 0) { throw "SIMION builder failed: $Script" }
}

try {
$failureStage = 'accelerator_build'
Invoke-Builder (Join-Path $projectRoot 'simion\accelerator\build_accelerator_variant.lua') @(
  (Join-Path $projectRoot 'simion\accelerator\oatof_accelerator_3d.gem'),
  (Join-Path $outputFull 'accelerator.pa#'),
  $acceleratorBuild.cell_xy_mm, $acceleratorBuild.cell_z_mm, $geometry.accelerator_bore_half, $geometry.accelerator_ring_width,
  $geometry.accelerator_insulation_gap, $geometry.accelerator_rear_clearance,
  $geometry.accelerator_shield_wall, 0, $acceleratorBuild.max_gib, 0, 0, 0,
  $accelerator.d1_mm, $accelerator.d2_mm, $contract.rings.accelerator_count,
  $geometry.accelerator_repeller_thickness, $geometry.accelerator_ring_thickness,
  $geometry.accelerator_front_vacuum_margin, $voltage.repeller, $voltage.grid1
) 'accelerator_builder'

$failureStage = 'reflectron_build'
Invoke-Builder (Join-Path $projectRoot 'simion\reflectron\build_reflectron_variant.lua') @(
  (Join-Path $projectRoot 'simion\reflectron\oatof_reflectron_ideal_10_5.gem'),
  (Join-Path $outputFull 'reflectron.pa#'),
  $reflectronBuild.cell_axial_mm, $reflectronBuild.cell_radial_mm, $reflectronBuild.max_gib, $geometry.flight_tube_r, $geometry.flight_tube_wall,
  $geometry.L_reflectron, $geometry.ring_thickness, $geometry.shield_axial_gap,
  $geometry.shield_endcap_thickness, $geometry.L_stage1, $geometry.L_stage2,
  $geometry.bore_r, $geometry.ring_outer_r, $contract.rings.stage1_count,
  $contract.rings.stage2_count, $voltage.midgrid, $voltage.backplate
) 'reflectron_builder'

$expectedAcceleratorElectrodes = 4 + [int]$contract.rings.accelerator_count
$expectedReflectronElectrodes = 4 + [int]$contract.rings.stage1_count + [int]$contract.rings.stage2_count
$failureStage = 'post_build_family_validation'
$paFamilyValidator = Join-Path $projectRoot 'analysis\validate_simion_pa_family.py'
foreach ($family in @(
  [pscustomobject]@{Stem='accelerator';Highest=$expectedAcceleratorElectrodes},
  [pscustomobject]@{Stem='reflectron';Highest=$expectedReflectronElectrodes}
)) {
  & $python $paFamilyValidator $outputFull $family.Stem $family.Highest
  if ($LASTEXITCODE -ne 0) { throw "$($family.Stem) surface=none PA family validation failed." }
}

$rawPaReceipt = Join-Path $outputFull 'native_ideal_grid_raw_pa_receipt.json'
$rowInspector = Join-Path $projectRoot 'simion\workbench\formal\inspect_native_ideal_grid_rows.lua'
$acceleratorZMin = -[double]$geometry.accelerator_repeller_thickness - [double]$geometry.accelerator_rear_clearance - [double]$geometry.accelerator_shield_wall
$grid1RawRow = [Math]::Round((-$acceleratorZMin + [double]$accelerator.d1_mm) / [double]$acceleratorBuild.cell_z_mm)
$grid2RawRow = [Math]::Round((-$acceleratorZMin + [double]$accelerator.d1_mm + [double]$accelerator.d2_mm) / [double]$acceleratorBuild.cell_z_mm)
$entgridRawRow = 0
$midgridRawRow = [Math]::Round([double]$geometry.L_stage1 / [double]$reflectronBuild.cell_axial_mm)
$rawAuditTimer = [Diagnostics.Stopwatch]::StartNew()
& $SimionExe --nogui lua $rowInspector (Join-Path $outputFull 'accelerator.pa#') `
  (Join-Path $outputFull 'reflectron.pa#') $rawPaReceipt `
  (3 + [int]$contract.rings.accelerator_count) (2 + [int]$contract.rings.stage1_count) `
  $grid1RawRow $grid2RawRow $entgridRawRow $midgridRawRow
if ($LASTEXITCODE -ne 0) { throw 'Native ideal-grid raw PA row receipt failed.' }
$rawAuditTimer.Stop()
$stageWallSeconds['combined_raw_pa_receipt'] = [Math]::Round($rawAuditTimer.Elapsed.TotalSeconds,3)
$timingReceipt = Join-Path $outputFull 'native_ideal_grid_stage_timing_receipt.json'
$builderStages = [ordered]@{}
$geometryAlignment = [ordered]@{}
foreach ($stem in @('accelerator_builder','reflectron_builder')) {
  $builderLog = Join-Path $outputFull ($stem + '.log')
  $builderStages[$stem] = @(
    Select-String -LiteralPath $builderLog -Pattern '^BUILD_TIMING: stage=(\w+) event=complete utc=(\S+) wall_seconds=(\d+)$' |
      ForEach-Object {[ordered]@{stage=$_.Matches[0].Groups[1].Value;utc=$_.Matches[0].Groups[2].Value;wall_seconds=[int]$_.Matches[0].Groups[3].Value}}
  )
  $warnings = @(Select-String -LiteralPath $builderLog -Pattern '^WARNING: (accelerator|reflectron)_geometry_edge_not_on_grid_node .*axis=(\w+) label=(\S+) value_mm=(\S+) cell_mm=(\S+) grid_coordinate=(\S+) nearest_node_mm=(\S+) offset_mm=([+-]?\S+) .*action=continue$' |
    ForEach-Object {[ordered]@{component=$_.Matches[0].Groups[1].Value;axis=$_.Matches[0].Groups[2].Value;label=$_.Matches[0].Groups[3].Value;value_mm=[double]$_.Matches[0].Groups[4].Value;cell_mm=[double]$_.Matches[0].Groups[5].Value;grid_coordinate=[double]$_.Matches[0].Groups[6].Value;nearest_node_mm=[double]$_.Matches[0].Groups[7].Value;offset_mm=[double]$_.Matches[0].Groups[8].Value}})
  $geometryAlignment[$stem] = [ordered]@{warnings=$warnings;max_abs_offset_mm=$(if($warnings.Count){($warnings | ForEach-Object {[Math]::Abs($_.offset_mm)} | Measure-Object -Maximum).Maximum}else{0.0})}
}
$alignmentReceipt = Join-Path $outputFull 'native_ideal_grid_geometry_alignment_receipt.json'
Write-RunJson -Value ([ordered]@{schema_version=2;role='oa_tof_native_ideal_grid_geometry_alignment_receipt';policy='zero_width_grids_hard_fail_ordinary_edges_warn_and_continue';components=$geometryAlignment}) -Path $alignmentReceipt
Write-RunJson -Value ([ordered]@{schema_version=2;role='oa_tof_native_ideal_grid_stage_timing_receipt';actual_cells_mm=$runConfig.actual_cells_mm;runner_wall_seconds=$stageWallSeconds;builder_stages=$builderStages}) -Path $timingReceipt

$formalDir = Join-Path $artifactRoot 'formal\simion'
$formalIob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
$formalFly2 = Join-Path $formalDir 'oatof_ideal_grounded.fly2'
$formalN100 = Join-Path $formalDir 'oatof_comsol_524amu_gaussian_N100.ion'
$program = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
$resolvedLua = Join-Path $projectRoot 'simion\workbench\formal\oatof_resolved.lua'
$iobBuilder = Join-Path $projectRoot 'simion\workbench\build_formal_iob.lua'
foreach ($required in @($formalIob,$formalFly2,$formalN100,$program,$resolvedLua,$iobBuilder)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "Native crossing smoke input is missing: $required"
  }
}
foreach ($pattern in @('flight_tube_ground.pa*','detector_ground.pa*')) {
  Copy-Item -Path (Join-Path $formalDir $pattern) -Destination $outputFull
}
$smokeIob = Join-Path $outputFull 'native_ideal_grid_smoke.iob'
& $SimionExe --nogui lua $iobBuilder $resolvedLua $smokeIob $formalIob $program $formalFly2
if ($LASTEXITCODE -ne 0) { throw 'Native ideal-grid smoke IOB build failed.' }
$singleIon = Join-Path $outputFull 'fixed_single_particle.ion'
Get-Content -LiteralPath $formalN100 -TotalCount 1 | Set-Content -LiteralPath $singleIon -Encoding ascii
$crossingLog = Join-Path $outputFull 'native_ideal_grid_crossing.log'
$crossingError = Join-Path $outputFull 'native_ideal_grid_crossing.stderr.log'
$flyTimer = [Diagnostics.Stopwatch]::StartNew()
$process = Start-Process -FilePath $SimionExe -ArgumentList @(
  '--nogui','fly','--trajectory-quality','8','--retain-trajectories','0',
  '--particles',$singleIon,'--adjustable','trajectory_quality=8',
  '--adjustable','trajectory_log_enable=1',$smokeIob
) -WorkingDirectory $outputFull -WindowStyle Hidden -Wait -PassThru `
  -RedirectStandardOutput $crossingLog -RedirectStandardError $crossingError
$flyTimer.Stop()
$stageWallSeconds['single_particle_fly'] = [Math]::Round($flyTimer.Elapsed.TotalSeconds,3)
if ($process.ExitCode -ne 0) { throw "Native ideal-grid crossing smoke failed: $crossingError" }
$crossings = @(Select-String -LiteralPath $crossingLog -Pattern '^TRACE: native_grid_crossing ')
$expectedCrossings = [ordered]@{
  'grid1:forward'=1; 'grid2:forward'=1
  'entgrid:forward'=1; 'entgrid:return'=1
  'midgrid:forward'=1; 'midgrid:return'=1
}
$actualCrossings = @{}
foreach ($line in $crossings.Line) {
  if ($line -notmatch 'grid=(\w+) direction=(\w+)') { continue }
  $key = "$($Matches[1]):$($Matches[2])"
  if (-not $expectedCrossings.Contains($key)) {
    throw "Unexpected native grid crossing key: $key"
  }
  $actualCrossings[$key] = 1 + [int]($actualCrossings[$key])
}
foreach ($entry in $expectedCrossings.GetEnumerator()) {
  if ([int]$actualCrossings[$entry.Key] -ne [int]$entry.Value) {
    throw "Native grid crossing count mismatch for $($entry.Key): $([int]$actualCrossings[$entry.Key])"
  }
}
if (-not (Select-String -LiteralPath $crossingLog -Quiet -Pattern '^TRACE: detector_hit_entity ion=1 instance=4$')) {
  throw 'Native ideal-grid smoke particle did not reach the detector entity.'
}
if (Select-String -LiteralPath $crossingLog,$crossingError -Quiet -Pattern 'non_detector_splat|TRACE: timeout|Lua error|ERROR:') {
  throw 'Native ideal-grid smoke reported a splat, timeout, or Lua error.'
}
$crossingReceipt = Join-Path $outputFull 'native_ideal_grid_crossing_receipt.json'
[ordered]@{
  schema_version=2; role='oa_tof_native_ideal_grid_crossing_receipt'
  ideal_grid_model='simion_one_row_zero_width_native_transmission'
  particle_count=1; detector_hit_count=1; crossings=$expectedCrossings
} | ConvertTo-Json -Depth 4 -Compress | Set-Content -LiteralPath $crossingReceipt -Encoding UTF8
Write-RunJson -Value ([ordered]@{schema_version=2;role='oa_tof_native_ideal_grid_stage_timing_receipt';actual_cells_mm=$runConfig.actual_cells_mm;runner_wall_seconds=$stageWallSeconds;builder_stages=$builderStages}) -Path $timingReceipt
$failureStage = 'terminal_publication'
Write-RunJson -Value ([ordered]@{schema_version=2;role='oa_tof_native_ideal_grid_smoke_summary';status='success';threshold_result_eligible=$true;ideal_grid_model='simion_one_row_zero_width_native_transmission';accelerator_electrodes=$expectedAcceleratorElectrodes;reflectron_electrodes=$expectedReflectronElectrodes;raw_pa_row_receipt='native_ideal_grid_raw_pa_receipt.json';native_crossing_receipt='native_ideal_grid_crossing_receipt.json';stage_timing_receipt='native_ideal_grid_stage_timing_receipt.json';geometry_alignment_receipt='native_ideal_grid_geometry_alignment_receipt.json'}) -Path $summaryPath
$retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath
$terminalOutputs = @($summaryPath,$rawPaReceipt,$crossingReceipt,$timingReceipt,$alignmentReceipt,$crossingLog,$crossingError,$retentionActions) +
  @(Get-ChildItem -LiteralPath $outputFull -File -Filter '*.log' | Select-Object -ExpandProperty FullName)
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath `
  -Manifest $manifestPath -Status success -Software @('SIMION 2020') -Outputs @($terminalOutputs | Select-Object -Unique)
$terminalized = $true
"PARAMETERIZED_GEOMETRY_BUILD_STATUS=PASS"
"NATIVE_IDEAL_GRID_RAW_PA_STATUS=PASS"
"NATIVE_IDEAL_GRID_CROSSING_STATUS=PASS"
"OUTPUT_DIR=$artifactOutputFull"
"ACCELERATOR_ELECTRODES=$expectedAcceleratorElectrodes"
"REFLECTRON_ELECTRODES=$expectedReflectronElectrodes"
} catch {
  $message = $_.Exception.Message
  Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath `
    -Summary $summaryPath -SummaryRole 'oa_tof_native_ideal_grid_smoke_summary' `
    -SummarySchemaVersion 2 -Status failed -Reason $message -FailureClass 'native_ideal_grid_smoke_failed' `
    -FailureStage $failureStage -ThresholdResultEligible $false -Software @('SIMION 2020')
  $terminalized = $true
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfigPath -PathType Leaf)) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath `
      -Summary $summaryPath -SummaryRole 'oa_tof_native_ideal_grid_smoke_summary' `
      -SummarySchemaVersion 2 -Status interrupted -Reason 'Runner exited without a terminal status.' `
      -FailureClass 'runner_interrupted' -FailureStage $failureStage `
      -ThresholdResultEligible $false -Software @('SIMION 2020')
  }
  if ($null -ne $executionAlias) {
    try {
      Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias `
        -TargetDirectory $artifactOutputFull
    } catch {
      Write-Warning "Could not remove short execution alias after native-grid smoke: $($_.Exception.Message)"
    }
  }
}
