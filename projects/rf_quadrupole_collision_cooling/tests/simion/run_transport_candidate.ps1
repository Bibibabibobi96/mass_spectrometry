param(
    [int]$RfStepsPerPeriod = 40,
    [int]$TrajectoryQuality = 10,
    [string]$RunId = '',
    [double]$SourceAxialOffsetMm = 0.0,
    [string]$ParticleTablePath = '',
    [ValidateSet('transport_no_collision','transport_interface_readiness','mass_filter_reference')][string]$Mode = 'transport_no_collision',
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
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__sim__simion__rf-transport__$($Mode.Replace('_','-'))"
}
$package=New-RunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_quadrupole_collision_cooling' -Mode $Mode -Software @('SIMION 2020','Python 3.11') `
    -AdditionalDirectories @('simion')
$runDir=$package.run_dir
$candidateDir=Join-Path $runDir 'simion'
$resultDir=$package.result_dir
$logDir=$package.log_dir
$inputDir=$package.input_dir
$simion = 'C:\Program Files\SIMION-2020\simion.exe'
$officialIob = 'C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'

$isMassFilter = $Mode -eq 'mass_filter_reference'
if ($isMassFilter -and -not [string]::IsNullOrWhiteSpace($ParticleTablePath)) {
    throw 'Mass-filter mode generates its paired multi-mass particle table; ParticleTablePath must be omitted.'
}
$sourceIonPath = if ([string]::IsNullOrWhiteSpace($ParticleTablePath)) {
    Join-Path $projectRoot 'config\particles\official_fixed_25.ion'
} else { [IO.Path]::GetFullPath($ParticleTablePath) }
$ionPath = Join-Path $inputDir $(if ($isMassFilter) { 'mass_scan_particles.ion' } else { 'particles.ion' })
$resolvedContractInput = switch ($Mode) {
    'transport_no_collision' { 'config/resolved_geometry.json' }
    'transport_interface_readiness' { 'config/resolved_interface_readiness.json' }
    'mass_filter_reference' { 'config/resolved_mass_filter.json' }
}
$modeInput = switch ($Mode) {
    'transport_no_collision' { 'config/modes/transport_no_collision.json' }
    'transport_interface_readiness' { 'config/modes/transport_interface_readiness.json' }
    'mass_filter_reference' { 'config/modes/mass_filter_reference.json' }
}
$expectedParticles = if ($isMassFilter) {
    0
} else {
    @(Get-Content -LiteralPath $sourceIonPath -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
}
if ($Mode -eq 'transport_interface_readiness') {
    $minimumParticles = (Get-Content -LiteralPath (Join-Path $projectRoot 'config\modes\transport_interface_readiness.json') -Raw -Encoding UTF8 | ConvertFrom-Json).numerics.minimum_diagnostic_particles
    if ([string]::IsNullOrWhiteSpace($ParticleTablePath) -or $expectedParticles -lt $minimumParticles) {
        throw "Interface-readiness mode requires an explicit particle table with at least $minimumParticles particles."
    }
    if ([double]::IsNaN($RfPeakV) -or [double]::IsInfinity($RfPeakV)) {
        throw 'Interface-readiness mode requires an explicit RfPeakV.'
    }
}

$frozenBaseline = Join-Path $inputDir 'baseline.json'
$frozenMode = Join-Path $inputDir 'mode.json'
$frozenResolved = Join-Path $inputDir 'resolved_contract.json'
$frozenInterface = Join-Path $inputDir 'interface_contract.json'
$frozenBaseTransportMode = Join-Path $inputDir 'base_transport_mode.json'
Copy-Item -LiteralPath (Join-Path $projectRoot 'config\baseline.json') -Destination $frozenBaseline
Copy-Item -LiteralPath (Join-Path $projectRoot ($modeInput -replace '/', '\')) -Destination $frozenMode
Copy-Item -LiteralPath (Join-Path $projectRoot ($resolvedContractInput -replace '/', '\')) -Destination $frozenResolved
Copy-Item -LiteralPath (Join-Path $projectRoot 'config\interface_contract.json') -Destination $frozenInterface
Copy-Item -LiteralPath (Join-Path $projectRoot 'config\modes\transport_no_collision.json') -Destination $frozenBaseTransportMode
$baseTransportMode = Get-Content -LiteralPath $frozenBaseTransportMode -Raw -Encoding UTF8 | ConvertFrom-Json
if ($isMassFilter) {
    $massScanMetadata = Join-Path $inputDir 'mass_scan_particles.json'
    & $python -m projects.rf_quadrupole_collision_cooling.analysis.generate_mass_scan_particle_table `
        --source $sourceIonPath --mode $frozenMode --output $ionPath --metadata $massScanMetadata
    if ($LASTEXITCODE -ne 0) { throw 'Paired mass-scan particle generation failed.' }
} else {
    Copy-Item -LiteralPath $sourceIonPath -Destination $ionPath
}
$familyOperatingContract = Join-Path $inputDir 'family_operating_contract.json'
$familyResolverArguments = @(
    '-m','common.multipole.resolve_family_operating_contract',
    '--adapter','quadrupole','--baseline',$frozenBaseline,
    '--mode',$frozenMode,'--output',$familyOperatingContract
)
if (-not [double]::IsNaN($RfPeakV) -and -not [double]::IsInfinity($RfPeakV)) {
    $familyResolverArguments += @('--rf-amplitude-v-per-group', [string]$RfPeakV)
}
if (-not [double]::IsNaN($FrequencyHz) -and -not [double]::IsInfinity($FrequencyHz)) {
    $familyResolverArguments += @('--frequency-hz', [string]$FrequencyHz)
}
& $python @familyResolverArguments
if ($LASTEXITCODE -ne 0) { throw 'Shared multipole operating-contract resolution failed.' }
$operating = Get-Content -LiteralPath $familyOperatingContract -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $ionPath -PathType Leaf)) { throw "Particle table is missing: $ionPath" }
if ($isMassFilter) {
    $expectedParticles = @(Get-Content -LiteralPath $ionPath -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_include.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'common\multipole\simion_transport.lua') -Destination (Join-Path $candidateDir 'quad_monolithic.lua') -Force
Copy-Item -LiteralPath $officialIob -Destination (Join-Path $candidateDir 'quad_monolithic.iob') -Force
$flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
$sourceStatesLua = Join-Path $inputDir 'source_states.lua'
Push-Location $repoRoot
try {
    & $python -m common.multipole.simion_particle_source --ion-table $ionPath --fly2 $flyPath `
        --axial-offset-mm $SourceAxialOffsetMm --source-states-lua $sourceStatesLua
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Fixed FLY2 generation failed.' }

$resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 | ConvertFrom-Json
$physicalMode = $resolved.mode
$geometry = $resolved.geometry_mm
$interface = Get-Content -LiteralPath $frozenInterface -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PSBoundParameters.ContainsKey('RfStepsPerPeriod')) {
    $RfStepsPerPeriod = if ($physicalMode.numerics.PSObject.Properties.Name -contains 'simion_rf_steps_per_period') {
        $physicalMode.numerics.simion_rf_steps_per_period
    } else { $baseTransportMode.numerics.simion_rf_steps_per_period }
}
if (-not $PSBoundParameters.ContainsKey('TrajectoryQuality')) {
    $TrajectoryQuality = if ($physicalMode.numerics.PSObject.Properties.Name -contains 'simion_trajectory_quality') {
        $physicalMode.numerics.simion_trajectory_quality
    } else { $baseTransportMode.numerics.simion_trajectory_quality }
}
if ([double]::IsNaN($RfPeakV) -or [double]::IsInfinity($RfPeakV)) { $RfPeakV = $operating.voltage.rf_amplitude_V_zero_to_peak_per_group }
if ([double]::IsNaN($FrequencyHz) -or [double]::IsInfinity($FrequencyHz)) { $FrequencyHz = $operating.voltage.frequency_Hz }
$particleStateCsv = Join-Path $resultDir 'particle_state.csv'
$trajectoryCsv = Join-Path $resultDir 'trajectory_samples.csv'
$summaryJson = Join-Path $resultDir 'solver_summary.json'
$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfigLua = Join-Path $runDir 'run_config.lua'
$iobReport = Join-Path $logDir 'simion_iob_contract.txt'
$stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
$phaseDeg = $operating.voltage.phase_rad*180/[Math]::PI
$dcAmplitudeV = $operating.voltage.dc_amplitude_V_per_group
$axisVoltageV = $operating.voltage.common_mode_offset_V
$staticElectrodes = if ($physicalMode.PSObject.Properties.Name -contains 'static_electrodes_V') {
    $physicalMode.static_electrodes_V
} else { $baseTransportMode.static_electrodes_V }
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_simion_run_config'; run_id=$RunId
    project='rf_quadrupole_collision_cooling'; mode=$Mode; project_root=$projectRoot
    inputs=[ordered]@{baseline=$frozenBaseline; base_transport_mode=$frozenBaseTransportMode; family_operating_contract=$familyOperatingContract; resolved_contract=$frozenResolved; interface_contract=$frozenInterface; mode=$frozenMode; particle_table=$ionPath; source_states=$sourceStatesLua}
    output_dir=$resultDir; candidate_dir=$candidateDir; run_dir=$runDir
    rf_steps_per_period=$RfStepsPerPeriod; trajectory_quality=$TrajectoryQuality
    source_axial_offset_mm=$SourceAxialOffsetMm; operating_point=$OperatingPoint
    rf_peak_v=$RfPeakV; dc_amplitude_v=$dcAmplitudeV; frequency_hz=$FrequencyHz; particles=$expectedParticles
}
if ($isMassFilter) { $runConfig.inputs.mass_scan_metadata = $massScanMetadata }
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$luaConfig = @"
return {
  mode=[[$Mode]], operating_point=[[$OperatingPoint]],
  iob=[[$(Join-Path $candidateDir 'quad_monolithic.iob')]], fly2=[[$flyPath]],
  source_states=dofile([[$sourceStatesLua]]),
  particle_state_csv=[[$particleStateCsv]], trajectory_csv=[[$trajectoryCsv]], summary_json=[[$summaryJson]],
  trajectory_quality=$TrajectoryQuality, rf_steps_per_period=$RfStepsPerPeriod,
  rf_peak_v=$RfPeakV, dc_amplitude_v=$dcAmplitudeV, frequency_hz=$FrequencyHz, phase_deg=$phaseDeg,
  axis_voltage_v=$axisVoltageV, entrance_voltage_v=$($staticElectrodes.entrance_plate),
  exit_voltage_v=$($staticElectrodes.exit_enclosure), detector_voltage_v=$($staticElectrodes.detector),
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
    $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA = $runConfigLua
    $env:RFQUAD_SIMION_REFERENCE_REPORT = $iobReport
    $env:RFQUAD_SIMION_REFERENCE_IOB = Join-Path $candidateDir 'quad_monolithic.iob'
    & $simion --nogui --noprompt lua (Join-Path $PSScriptRoot 'inspect_builtin_quad_reference.lua')
    if ($LASTEXITCODE -ne 0) { throw 'SIMION IOB runtime contract failed.' }

    $stdoutPath = Join-Path $logDir 'simion_stdout.txt'
    $stderrPath = Join-Path $logDir 'simion_stderr.txt'
    $flyProcess = Start-Process -FilePath $simion -ArgumentList @(
        '--nogui','--noprompt','lua',(Join-Path $repoRoot 'common\multipole\simion_run_fly.lua')
    ) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    Get-Content -LiteralPath $stdoutPath -Encoding UTF8
    if ((Get-Item -LiteralPath $stderrPath).Length -gt 0) { Get-Content -LiteralPath $stderrPath -Encoding UTF8 }
    if ($flyProcess.ExitCode -ne 0) { throw "SIMION fly failed with exit code $($flyProcess.ExitCode)." }
}
finally {
    Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_REFERENCE_REPORT -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_REFERENCE_IOB -ErrorAction SilentlyContinue
    Pop-Location
}

$summary = Get-Content -LiteralPath $summaryJson -Raw | ConvertFrom-Json
if ($summary.particles -ne $expectedParticles -or $summary.collision_model -ne 'none' -or
    (-not $isMassFilter -and $summary.transmission -lt 0.8)) {
    throw "SIMION transport gate failed: $($summary | ConvertTo-Json -Compress)"
}
Push-Location $repoRoot
try { & $python -m common.contracts.particle_state `
    --state $particleStateCsv --particles $ionPath --source-format ion11 --contract $frozenInterface `
    --axial-offset-mm $SourceAxialOffsetMm --frequency-hz $FrequencyHz --phase-rad ($phaseDeg*[Math]::PI/180) `
    --solver SIMION --output $stateContractReport } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Particle-state contract gate failed.' }
$massResponseCsv = Join-Path $resultDir 'mass-response__simion.csv'
$massMetricsJson = Join-Path $resultDir 'mass-filter__simion-functional-metrics.json'
$massResponseFigure = Join-Path $resultDir 'mass-response__simion-passband.png'
$massMetrics = $null
if ($isMassFilter) {
    & $python -m projects.rf_quadrupole_collision_cooling.analysis.analyze_simion_mass_scan `
        --state $particleStateCsv --particles $ionPath `
        --baseline $frozenBaseline --mode $frozenMode `
        --response $massResponseCsv --metrics $massMetricsJson --figure $massResponseFigure
    if ($LASTEXITCODE -ne 0) { throw 'SIMION mass-filter functional analysis failed.' }
    $massMetrics = Get-Content -LiteralPath $massMetricsJson -Raw -Encoding UTF8 | ConvertFrom-Json
}
$shaPath = Join-Path $candidateDir 'SHA256SUMS.csv'
$hashes = Get-ChildItem -LiteralPath $candidateDir -File | Where-Object {
    $_.Name -ne 'SHA256SUMS.csv' -and $_.Name -notlike 'trj*.tmp'
} | Sort-Object Name | ForEach-Object {
    [pscustomobject]@{file=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
}
$hashes | Export-Csv -LiteralPath $shaPath -NoTypeInformation -Encoding UTF8
$runSummary = Join-Path $runDir 'summary.json'
$summaryRole = if ($isMassFilter) { 'rf_quadrupole_mass_filter_summary' } else { 'rf_quadrupole_transport_summary' }
$rootSummary = [ordered]@{schema_version=1;role=$summaryRole;status='success';mode=$Mode;particles=$expectedParticles;hits=$summary.hits;transmission=$summary.transmission}
if ($isMassFilter) {
    $rootSummary.functional_gate = $massMetrics.status
    $rootSummary.mass_response = 'results/mass-response__simion.csv'
    $rootSummary.metrics = 'results/mass-filter__simion-functional-metrics.json'
    $rootSummary.figure = 'results/mass-response__simion-passband.png'
}
$rootSummary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runSummary -Encoding UTF8
$manifestOutputs = @(
    $trajectoryCsv,$summaryJson,$particleStateCsv,$stateContractReport,
    (Join-Path $logDir 'simion_stdout.txt'),(Join-Path $logDir 'simion_stderr.txt'),
    (Join-Path $candidateDir 'quad_monolithic.iob'),(Join-Path $candidateDir 'quad_monolithic.pa0'),
    $flyPath,$iobReport,$shaPath,$runSummary
)
if ($isMassFilter) {
    $manifestOutputs += @($massResponseCsv,$massMetricsJson,$massResponseFigure)
}
Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $manifestOutputs
"STATUS=PASS RUN_ID=$RunId HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
