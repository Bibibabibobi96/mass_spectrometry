param(
    [int]$RfStepsPerPeriod = 40,
    [int]$TrajectoryQuality = 10,
    [string]$RunLabel = 'baseline',
    [double]$SourceAxialOffsetMm = 0.0,
    [string]$CandidateSubdir = 'quad_transport'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$candidateDir = Join-Path $artifactRoot "models\simion\candidates\$CandidateSubdir\$RunLabel"
$resultDir = Join-Path $artifactRoot 'results\simion'
$runDir = Join-Path $artifactRoot "runs\transport_no_collision\simion_$RunLabel"
$simion = 'C:\Program Files\SIMION-2020\simion.exe'
$officialIob = 'C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'

if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $candidateDir)) {
    throw "Run or candidate directory already exists; choose a new RunLabel: $RunLabel"
}
New-Item -ItemType Directory -Path $candidateDir,$resultDir,$runDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_include.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\programs\quad_transport.lua') -Destination (Join-Path $candidateDir 'quad_monolithic.lua') -Force
Copy-Item -LiteralPath $officialIob -Destination (Join-Path $candidateDir 'quad_monolithic.iob') -Force

$ionPath = Join-Path $projectRoot 'config\particles\official_fixed_25.ion'
$flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
& (Join-Path $repoRoot '.venv\Scripts\python.exe') `
    (Join-Path $projectRoot 'analysis\generate_fixed_fly2.py') $ionPath $flyPath `
    --axial-offset-mm $SourceAxialOffsetMm
if ($LASTEXITCODE -ne 0) { throw 'Fixed FLY2 generation failed.' }

$resolvedPath = Join-Path $projectRoot 'config\resolved_geometry.json'
$resolved = Get-Content -LiteralPath $resolvedPath -Raw -Encoding UTF8 | ConvertFrom-Json
$mode = $resolved.mode
$particleCsv = Join-Path $resultDir "transport_no_collision_particles_$RunLabel.csv"
$trajectoryCsv = Join-Path $resultDir "transport_no_collision_trajectory_samples_$RunLabel.csv"
$summaryJson = Join-Path $resultDir "transport_no_collision_summary_$RunLabel.json"
$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfigLua = Join-Path $runDir 'run_config.lua'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_simion_run_config'; run_id="simion_$RunLabel"
    project='rf_quadrupole_collision_cooling'; mode='transport_no_collision'; project_root=$projectRoot
    inputs=[ordered]@{baseline='config/baseline.json'; resolved_geometry='config/resolved_geometry.json'; mode='config/modes/transport_no_collision.json'; particle_table='config/particles/official_fixed_25.ion'}
    output_dir=$resultDir; rf_steps_per_period=$RfStepsPerPeriod; trajectory_quality=$TrajectoryQuality
    source_axial_offset_mm=$SourceAxialOffsetMm
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$luaConfig = @"
return {
  iob=[[$(Join-Path $candidateDir 'quad_monolithic.iob')]], fly2=[[$flyPath]],
  particle_csv=[[$particleCsv]], trajectory_csv=[[$trajectoryCsv]], summary_json=[[$summaryJson]],
  trajectory_quality=$TrajectoryQuality, rf_steps_per_period=$RfStepsPerPeriod,
  rf_peak_v=$($mode.rf.amplitude_V_peak), frequency_hz=$($mode.rf.frequency_Hz), phase_deg=$($mode.rf.phase_rad*180/[Math]::PI),
  axis_voltage_v=$($mode.rf.axis_offset_V), entrance_voltage_v=$($mode.static_electrodes_V.entrance_plate),
  exit_voltage_v=$($mode.static_electrodes_V.exit_enclosure), detector_voltage_v=$($mode.static_electrodes_V.detector),
  maximum_time_us=$($mode.numerics.maximum_time_us)
}
"@
$luaConfig | Set-Content -LiteralPath $runConfigLua -Encoding UTF8

Push-Location $candidateDir
try {
    & $simion --nogui gem2pa quad_monolithic.gem quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
    & $simion --nogui refine quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }

    $env:RFQUAD_RUN_CONFIG_LUA = $runConfigLua
    & $simion --nogui lua (Join-Path $PSScriptRoot 'run_fly.lua') 2>&1 |
        Tee-Object -FilePath (Join-Path $runDir 'simion_stdout.txt')
    if ($LASTEXITCODE -ne 0) { throw 'SIMION fly failed.' }
}
finally {
    Remove-Item Env:RFQUAD_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
    Pop-Location
}

$summary = Get-Content -LiteralPath $summaryJson -Raw | ConvertFrom-Json
if ($summary.particles -ne 25 -or $summary.collision_model -ne 'none' -or $summary.transmission -lt 0.8) {
    throw "SIMION transport gate failed: $($summary | ConvertTo-Json -Compress)"
}
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'SIMION 2020' --output $particleCsv --output $trajectoryCsv --output $summaryJson `
    --output (Join-Path $candidateDir 'quad_monolithic.iob') --output (Join-Path $candidateDir 'quad_monolithic.pa0') `
    --output $flyPath
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
"STATUS=PASS LABEL=$RunLabel HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
