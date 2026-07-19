param(
    [int]$RfStepsPerPeriod = 40,
    [int]$TrajectoryQuality = 10,
    [string]$RunLabel = 'baseline',
    [double]$SourceAxialOffsetMm = 0.0,
    [string]$CandidateSubdir = 'quad_transport',
    [string]$ParticleTablePath = '',
    [ValidateSet('transport_no_collision','transport_interface_readiness')][string]$Mode = 'transport_no_collision',
    [string]$OperatingPoint = 'official_100amu_2eV',
    [double]$RfPeakV = [double]::NaN,
    [double]$FrequencyHz = [double]::NaN
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$candidateDir = Join-Path $artifactRoot "models\simion\candidates\$CandidateSubdir\$Mode\$RunLabel"
$resultDir = Join-Path $artifactRoot 'results\simion'
$runDir = Join-Path $artifactRoot "runs\$Mode\simion_$RunLabel"
$simion = 'C:\Program Files\SIMION-2020\simion.exe'
$officialIob = 'C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'

if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $candidateDir)) {
    throw "Run or candidate directory already exists; choose a new RunLabel: $RunLabel"
}

$ionPath = if ([string]::IsNullOrWhiteSpace($ParticleTablePath)) {
    Join-Path $projectRoot 'config\particles\official_fixed_25.ion'
} else { [IO.Path]::GetFullPath($ParticleTablePath) }
if (-not (Test-Path -LiteralPath $ionPath -PathType Leaf)) { throw "Particle table is missing: $ionPath" }
$expectedParticles = @(Get-Content -LiteralPath $ionPath -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
$resolvedContractInput = if ($Mode -eq 'transport_no_collision') { 'config/resolved_geometry.json' } else { 'config/resolved_interface_readiness.json' }
if ($Mode -eq 'transport_interface_readiness') {
    $minimumParticles = (Get-Content -LiteralPath (Join-Path $projectRoot 'config\modes\transport_interface_readiness.json') -Raw -Encoding UTF8 | ConvertFrom-Json).numerics.minimum_diagnostic_particles
    if ([string]::IsNullOrWhiteSpace($ParticleTablePath) -or $expectedParticles -lt $minimumParticles) {
        throw "Interface-readiness mode requires an explicit particle table with at least $minimumParticles particles."
    }
    if ([double]::IsNaN($RfPeakV) -or [double]::IsInfinity($RfPeakV)) {
        throw 'Interface-readiness mode requires an explicit RfPeakV.'
    }
}

New-Item -ItemType Directory -Path $candidateDir,$resultDir,$runDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_include.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\programs\quad_transport.lua') -Destination (Join-Path $candidateDir 'quad_monolithic.lua') -Force
Copy-Item -LiteralPath $officialIob -Destination (Join-Path $candidateDir 'quad_monolithic.iob') -Force
$flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
$sourceStatesLua = Join-Path $runDir 'source_states.lua'
& (Join-Path $repoRoot '.venv\Scripts\python.exe') `
    (Join-Path $projectRoot 'analysis\generate_fixed_fly2.py') $ionPath $flyPath `
    --axial-offset-mm $SourceAxialOffsetMm --source-states-lua $sourceStatesLua
if ($LASTEXITCODE -ne 0) { throw 'Fixed FLY2 generation failed.' }

$resolvedPath = Join-Path $projectRoot 'config\resolved_geometry.json'
$resolved = Get-Content -LiteralPath $resolvedPath -Raw -Encoding UTF8 | ConvertFrom-Json
$physicalMode = $resolved.mode
$geometry = $resolved.geometry_mm
$interface = Get-Content -LiteralPath (Join-Path $projectRoot 'config\interface_contract.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ([double]::IsNaN($RfPeakV) -or [double]::IsInfinity($RfPeakV)) { $RfPeakV = $physicalMode.rf.amplitude_V_peak }
if ([double]::IsNaN($FrequencyHz) -or [double]::IsInfinity($FrequencyHz)) { $FrequencyHz = $physicalMode.rf.frequency_Hz }
$modeInput = if ($Mode -eq 'transport_no_collision') { 'config/modes/transport_no_collision.json' } else { 'config/modes/transport_interface_readiness.json' }
$particleStateCsv = Join-Path $resultDir "${Mode}_particle_state_$RunLabel.csv"
$trajectoryCsv = Join-Path $resultDir "${Mode}_trajectory_samples_$RunLabel.csv"
$summaryJson = Join-Path $resultDir "${Mode}_summary_$RunLabel.json"
$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfigLua = Join-Path $runDir 'run_config.lua'
$iobReport = Join-Path $runDir 'simion_iob_contract.txt'
$stateContractReport = Join-Path $runDir 'particle_state_contract.json'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_simion_run_config'; run_id="simion_$RunLabel"
    project='rf_quadrupole_collision_cooling'; mode=$Mode; project_root=$projectRoot
    inputs=[ordered]@{baseline='config/baseline.json'; resolved_geometry='config/resolved_geometry.json'; resolved_contract=$resolvedContractInput; mode=$modeInput; particle_table=$ionPath; source_states=$sourceStatesLua}
    output_dir=$resultDir; candidate_dir=$candidateDir; run_dir=$runDir
    rf_steps_per_period=$RfStepsPerPeriod; trajectory_quality=$TrajectoryQuality
    source_axial_offset_mm=$SourceAxialOffsetMm; operating_point=$OperatingPoint
    rf_peak_v=$RfPeakV; frequency_hz=$FrequencyHz; particles=$expectedParticles
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$luaConfig = @"
return {
  mode=[[$Mode]], operating_point=[[$OperatingPoint]],
  iob=[[$(Join-Path $candidateDir 'quad_monolithic.iob')]], fly2=[[$flyPath]],
  source_states=dofile([[$sourceStatesLua]]),
  particle_state_csv=[[$particleStateCsv]], trajectory_csv=[[$trajectoryCsv]], summary_json=[[$summaryJson]],
  trajectory_quality=$TrajectoryQuality, rf_steps_per_period=$RfStepsPerPeriod,
  rf_peak_v=$RfPeakV, frequency_hz=$FrequencyHz, phase_deg=$($physicalMode.rf.phase_rad*180/[Math]::PI),
  axis_voltage_v=$($physicalMode.rf.axis_offset_V), entrance_voltage_v=$($physicalMode.static_electrodes_V.entrance_plate),
  exit_voltage_v=$($physicalMode.static_electrodes_V.exit_enclosure), detector_voltage_v=$($physicalMode.static_electrodes_V.detector),
  maximum_time_us=$($physicalMode.numerics.maximum_time_us),
  trajectory_plane_step_mm=$($geometry.simion_cell_mm), rod_z_min_mm=$($geometry.rod_z_min), rod_z_max_mm=$($geometry.rod_z_max),
  rod_exit_plane_mm=$($interface.planes.rod_exit.z_mm), handoff_plane_mm=$($interface.planes.handoff.z_mm),
  detector_crossing_threshold_mm=$($resolved.coordinate_convention.detector_plane_z_mm-$interface.solver_numerics.simion_terminal_surface_backoff_cells*$geometry.simion_cell_mm),
  detector_radius_mm=$($geometry.detector_radius), radial_escape_radius_mm=$($geometry.exit_enclosure_outer_half_width),
  expected_pa_nx=$([int][Math]::Round($geometry.exit_enclosure_outer_half_width/$geometry.simion_cell_mm)+1),
  expected_pa_ny=$([int][Math]::Round($geometry.exit_enclosure_outer_half_width/$geometry.simion_cell_mm)+1),
  expected_pa_nz=$([int][Math]::Round($geometry.model_z_span/$geometry.simion_cell_mm)+1), expected_pa_cell_mm=$($geometry.simion_cell_mm)
}
"@
# Windows PowerShell 5.1 writes a BOM for -Encoding UTF8; SIMION's Lua 5.1
# parser treats that BOM as source text.  This generated table is ASCII-only.
$luaConfig | Set-Content -LiteralPath $runConfigLua -Encoding ASCII

Push-Location $candidateDir
try {
    & $simion --nogui --noprompt gem2pa quad_monolithic.gem quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
    & $simion --nogui --noprompt refine quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }

    # Loading the IOB immediately loads its same-basename Program, which
    # validates this run configuration before the structural report runs.
    $env:RFQUAD_RUN_CONFIG_LUA = $runConfigLua
    $env:RFQUAD_SIMION_REFERENCE_REPORT = $iobReport
    $env:RFQUAD_SIMION_REFERENCE_IOB = Join-Path $candidateDir 'quad_monolithic.iob'
    & $simion --nogui --noprompt lua (Join-Path $PSScriptRoot 'inspect_builtin_quad_reference.lua')
    if ($LASTEXITCODE -ne 0) { throw 'SIMION IOB runtime contract failed.' }

    $stdoutPath = Join-Path $runDir 'simion_stdout.txt'
    $stderrPath = Join-Path $runDir 'simion_stderr.txt'
    $flyProcess = Start-Process -FilePath $simion -ArgumentList @(
        '--nogui','--noprompt','lua',(Join-Path $PSScriptRoot 'run_fly.lua')
    ) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    Get-Content -LiteralPath $stdoutPath -Encoding UTF8
    if ((Get-Item -LiteralPath $stderrPath).Length -gt 0) { Get-Content -LiteralPath $stderrPath -Encoding UTF8 }
    if ($flyProcess.ExitCode -ne 0) { throw "SIMION fly failed with exit code $($flyProcess.ExitCode)." }
}
finally {
    Remove-Item Env:RFQUAD_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_REFERENCE_REPORT -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_REFERENCE_IOB -ErrorAction SilentlyContinue
    Pop-Location
}

$summary = Get-Content -LiteralPath $summaryJson -Raw | ConvertFrom-Json
if ($summary.particles -ne $expectedParticles -or $summary.collision_model -ne 'none' -or $summary.transmission -lt 0.8) {
    throw "SIMION transport gate failed: $($summary | ConvertTo-Json -Compress)"
}
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $projectRoot 'analysis\verify_particle_state_contract.py') `
    --state $particleStateCsv --particles $ionPath --interface (Join-Path $projectRoot 'config\interface_contract.json') `
    --axial-offset-mm $SourceAxialOffsetMm --frequency-hz $FrequencyHz --phase-rad $physicalMode.rf.phase_rad `
    --solver SIMION --output $stateContractReport
if ($LASTEXITCODE -ne 0) { throw 'Particle-state contract gate failed.' }
$shaPath = Join-Path $candidateDir 'SHA256SUMS.csv'
$hashes = Get-ChildItem -LiteralPath $candidateDir -File | Where-Object {
    $_.Name -ne 'SHA256SUMS.csv' -and $_.Name -notlike 'trj*.tmp'
} | Sort-Object Name | ForEach-Object {
    [pscustomobject]@{file=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
}
$hashes | Export-Csv -LiteralPath $shaPath -NoTypeInformation -Encoding UTF8
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'SIMION 2020' --output $trajectoryCsv --output $summaryJson `
    --output $particleStateCsv `
    --output $stateContractReport `
    --output (Join-Path $runDir 'simion_stdout.txt') --output (Join-Path $runDir 'simion_stderr.txt') `
    --output (Join-Path $candidateDir 'quad_monolithic.iob') --output (Join-Path $candidateDir 'quad_monolithic.pa0') `
    --output $flyPath --output $iobReport --output $shaPath
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
"STATUS=PASS LABEL=$RunLabel HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
