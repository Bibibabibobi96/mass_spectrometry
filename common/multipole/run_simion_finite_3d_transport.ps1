[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [Parameter(Mandatory=$true)][string]$FieldScreenRunId,
  [string]$RunId='',
  [string]$ReferenceComsolRunId='',
  [double]$CellMm=0.4
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRootPath=(Resolve-Path -LiteralPath $ProjectRoot).Path
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
$simion='C:\Program Files\SIMION-2020\simion.exe'
$templateIob='C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'
$project=Get-Content -LiteralPath (Join-Path $projectRootPath 'config\project.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$projectId=[string]$project.project_id
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__simion__$($projectId.Replace('_','-'))-finite-3d__l3-n25"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE-ne 0){throw "Invalid run_id: $RunId"}
$sourceDir=Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$FieldScreenRunId"
$sourceManifest=Join-Path $sourceDir 'run_manifest.json'
$sourceSamples=Join-Path $sourceDir 'results\round_rod_potential_samples.csv'
$sourceContract=Join-Path $sourceDir 'inputs\round_rod_field_screen.json'
if (!(Test-Path -LiteralPath $sourceManifest)){throw "Field-screen run is missing: $FieldScreenRunId"}
$runDir=Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$RunId"
if(Test-Path -LiteralPath $runDir){throw "Run already exists: $runDir"}
$inputDir=Join-Path $runDir 'inputs'; $resultDir=Join-Path $runDir 'results'; $logDir=Join-Path $runDir 'logs'; $solverDir=Join-Path $runDir 'simion'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir,$solverDir|Out-Null
$runConfig=Join-Path $runDir 'run_config.json'; $summary=Join-Path $runDir 'summary.json'; $manifestWriter=Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
[ordered]@{schema_version=1;role='multipole_simion_finite_3d_run_config';run_id=$RunId;project=$projectId;mode='finite_3d_no_collision';inputs=[ordered]@{};parameters=[ordered]@{simion_cell_mm=$CellMm};formal_gate_passed=$false}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status='interrupted';reason='Run has not completed.'}|ConvertTo-Json|Set-Content -LiteralPath $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'SIMION 2020' --software 'Python 3.11' --output $summary
if($LASTEXITCODE-ne 0){throw 'Initial run-manifest generation failed.'}
$baseline=Join-Path $inputDir 'baseline.json'; $finite=Join-Path $inputDir 'finite_3d_transport.json'; $resolved=Join-Path $inputDir 'finite_3d_transport_resolved.json'
$operating=Join-Path $inputDir 'family_operating_contract.json'; $fieldMetrics=Join-Path $inputDir 'round_rod_field_screen_metrics.json'; $geometry=Join-Path $inputDir 'round_rod_geometry.json'; $particles=Join-Path $inputDir 'particle_source.csv'
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\baseline.json') -Destination $baseline
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\finite_3d_transport.json') -Destination $finite
& $python (Join-Path $repoRoot 'common\multipole\analyze_round_rod_screen.py') --samples $sourceSamples --contract $sourceContract --output $fieldMetrics
if($LASTEXITCODE-ne 0){throw 'Could not freeze selected round-rod geometry.'}
Push-Location $repoRoot
try{
  & $python -m common.multipole.resolve_family_operating_contract --adapter high-order --baseline $baseline --output $operating
  if($LASTEXITCODE-ne 0){throw 'Operating-contract resolution failed.'}
  & $python -m common.multipole.resolve_finite_3d_contract --baseline $baseline --contract $finite --output $resolved
  if($LASTEXITCODE-ne 0){throw 'Finite-3D contract resolution failed.'}
  & $python -m common.multipole.round_rod_geometry --baseline $baseline --finite-3d $resolved --field-metrics $fieldMetrics --output $geometry
  if($LASTEXITCODE-ne 0){throw 'Round-rod geometry resolution failed.'}
}finally{Pop-Location}
$resolvedDoc=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
& $python -m common.multipole.generate_particle_source --baseline $baseline --release-z-mm ([double]$resolvedDoc.derived_geometry_mm.source_z) --output $particles
if($LASTEXITCODE-ne 0){throw 'Particle-source generation failed.'}
$gem=Join-Path $solverDir 'quad_monolithic.gem'; $fly2=Join-Path $solverDir 'quad_monolithic.fly2'; $states=Join-Path $inputDir 'source_states.lua'
& $python -m common.multipole.simion_geometry --geometry $geometry --cell-mm $CellMm --output $gem
if($LASTEXITCODE-ne 0){throw 'SIMION GEM export failed.'}
& $python -m common.multipole.simion_particle_source --particles $particles --baseline $baseline --geometry $geometry --fly2 $fly2 --source-states-lua $states
if($LASTEXITCODE-ne 0){throw 'SIMION particle export failed.'}
Copy-Item -LiteralPath $templateIob -Destination (Join-Path $solverDir 'quad_monolithic.iob')
Copy-Item -LiteralPath (Join-Path $repoRoot 'common\multipole\simion_transport.lua') -Destination (Join-Path $solverDir 'quad_monolithic.lua')
$geometryDoc=Get-Content -LiteralPath $geometry -Raw -Encoding UTF8|ConvertFrom-Json
$operatingDoc=Get-Content -LiteralPath $operating -Raw -Encoding UTF8|ConvertFrom-Json
$baselineDoc=Get-Content -LiteralPath $baseline -Raw -Encoding UTF8|ConvertFrom-Json
[ordered]@{schema_version=1;role='multipole_simion_finite_3d_run_config';run_id=$RunId;project=$projectId;mode='finite_3d_no_collision';inputs=[ordered]@{baseline=$baseline;finite_3d_resolved=$resolved;family_operating_contract=$operating;round_rod_geometry=$geometry;particle_source=$particles;field_screen_manifest=$sourceManifest};parameters=[ordered]@{simion_cell_mm=$CellMm;paired_rf_zero_control=$true;reference_comsol_run_id=$ReferenceComsolRunId};formal_gate_passed=$false}|ConvertTo-Json -Depth 7|Set-Content -LiteralPath $runConfig -Encoding UTF8
Push-Location $solverDir
try{
  & $simion --nogui --noprompt gem2pa quad_monolithic.gem quad_monolithic.pa#
  if($LASTEXITCODE-ne 0){throw 'SIMION gem2pa failed.'}
  & $simion --nogui --noprompt refine quad_monolithic.pa#
  if($LASTEXITCODE-ne 0){throw 'SIMION refine failed.'}
}finally{Pop-Location}

function Invoke-TransportCase([string]$name,[int]$rfScale){
  $caseState=Join-Path $resultDir "particle_states__$name.csv"; $caseTrajectory=Join-Path $resultDir "trajectory_samples__$name.csv"; $caseSummary=Join-Path $resultDir "simion_summary__$name.json"; $luaConfig=Join-Path $inputDir "simion_config__$name.lua"
  $outer=[double]$geometryDoc.grounded_enclosure_mm.shield_outer_radius; $zShift=-[double]$geometryDoc.grounded_enclosure_mm.vacuum_z_min
  $text=@"
return {iob=[[$(Join-Path $solverDir 'quad_monolithic.iob')]], fly2=[[$fly2]], source_states=dofile([[$states]]),
trajectory_csv=[[$caseTrajectory]], particle_state_csv=[[$caseState]], summary_json=[[$caseSummary]],
mode="finite_3d_no_collision", operating_point="$name", trajectory_quality=10, rf_steps_per_period=$($resolvedDoc.trajectory.rf_steps_per_period),
rf_peak_v=$($operatingDoc.voltage.rf_amplitude_V_zero_to_peak_per_group), rf_scale=$rfScale, dc_amplitude_v=$($operatingDoc.voltage.dc_amplitude_V_per_group), frequency_hz=$($operatingDoc.voltage.frequency_Hz), phase_deg=$([double]$operatingDoc.voltage.phase_rad*180/[Math]::PI),
axis_voltage_v=$($operatingDoc.voltage.common_mode_offset_V), entrance_voltage_v=0, exit_voltage_v=0, detector_voltage_v=0, has_electrode_4=false, has_electrode_5=false,
maximum_time_us=$($resolvedDoc.trajectory.maximum_global_time_us), trajectory_plane_step_mm=$CellMm,
rod_z_min_mm=$($geometryDoc.array_mm.rods[0].z_min_mm), rod_z_max_mm=$($geometryDoc.array_mm.rods[0].z_max_mm),
rod_exit_plane_mm=$($geometryDoc.array_mm.rods[0].z_max_mm), handoff_plane_mm=$($geometryDoc.interfaces_mm.detector_z),
detector_crossing_threshold_mm=$([double]$geometryDoc.interfaces_mm.detector_z-$CellMm), detector_radius_mm=$($geometryDoc.interfaces_mm.exit_aperture_radius), radial_escape_radius_mm=$($geometryDoc.grounded_enclosure_mm.shield_inner_radius),
detector_is_handoff=true,
axial_axis="x", origin_x_mm=$zShift, origin_y_mm=$(-$outer), origin_z_mm=$outer, backward_escape_plane_mm=$($geometryDoc.grounded_enclosure_mm.vacuum_z_min)}
"@
  $text|Set-Content -LiteralPath $luaConfig -Encoding ASCII
  $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA=$luaConfig
  $stdout=Join-Path $logDir "simion_stdout__$name.txt"; $stderr=Join-Path $logDir "simion_stderr__$name.txt"
  try{
    $process=Start-Process -FilePath $simion -ArgumentList @('--nogui','--noprompt','lua',(Join-Path $repoRoot 'common\multipole\simion_run_fly.lua')) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if($process.ExitCode-ne 0){Get-Content -LiteralPath $stderr -Encoding UTF8; throw "SIMION $name fly failed."}
  }finally{Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue}
  return Get-Content -LiteralPath $caseSummary -Raw -Encoding UTF8|ConvertFrom-Json
}
$rf=Invoke-TransportCase 'rf_on' 1; $zero=Invoke-TransportCase 'zero_rf_control' 0
$minimum=[double]$resolvedDoc.functional_acceptance.minimum_rf_transmission; $improvement=[double]$resolvedDoc.functional_acceptance.minimum_improvement_over_zero_rf
$status=if($rf.transmission-ge $minimum -and ($rf.transmission-$zero.transmission)-ge $improvement){'PASS'}else{'FAIL'}
$metrics=Join-Path $resultDir 'finite_3d_transport_metrics.json'
[ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_metrics';status=$status;project_id=$projectId;model_level='L3';simion_cell_mm=$CellMm;cases=[ordered]@{finite_3d_rf_on=$rf;zero_rf_control=$zero};rf_minus_zero_transmission=($rf.transmission-$zero.transmission);claim_limit='Functional SIMION cross-solver regression only; no mesh convergence or Candidate claim.'}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $metrics -Encoding UTF8
[ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status=if($status-eq'PASS'){'success'}else{'failed'};project_id=$projectId;rf_transmission=$rf.transmission;zero_rf_transmission=$zero.transmission;model_level='L3';formal_gate_passed=$false}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
$comparison=$null
if(-not [string]::IsNullOrWhiteSpace($ReferenceComsolRunId)){
  $referenceMetrics=Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$ReferenceComsolRunId\results\finite_3d_transport_metrics.json"
  $comparison=Join-Path $resultDir 'cross_solver_functional_comparison.json'
  & $python -m common.multipole.compare_simion_comsol_l3 --rf-state (Join-Path $resultDir 'particle_states__rf_on.csv') --zero-state (Join-Path $resultDir 'particle_states__zero_rf_control.csv') --comsol-metrics $referenceMetrics --output $comparison
  if($LASTEXITCODE-ne 0){throw 'SIMION/COMSOL functional comparison failed.'}
}
$manifest=Join-Path $repoRoot 'common\contracts\write_run_manifest.py'; $outputs=@($summary,$metrics,(Join-Path $solverDir 'quad_monolithic.pa0'),(Join-Path $solverDir 'quad_monolithic.iob'),$gem,$fly2)
if($comparison){$outputs+=$comparison}
$args=@($manifest,'--run-config',$runConfig,'--status',$(if($status-eq'PASS'){'success'}else{'failed'}),'--software','SIMION 2020','--software','Python 3.11'); foreach($output in $outputs){$args+=@('--output',$output)}
& $python @args
if($LASTEXITCODE-ne 0){throw 'Run-manifest generation failed.'}
if($status-ne'PASS'){throw "SIMION functional gate failed: RF=$($rf.transmission) ZERO=$($zero.transmission)"}
Write-Output "MULTIPOLE_SIMION_L3=PASS PROJECT=$projectId RUN_ID=$RunId RF=$($rf.transmission) ZERO=$($zero.transmission)"
