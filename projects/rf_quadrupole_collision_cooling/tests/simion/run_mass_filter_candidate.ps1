param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceIonPath,
    [int]$RfStepsPerPeriod = 40,
    [int]$TrajectoryQuality = 10,
    [string]$RunId = '',
    [string]$ArtifactRootPath = '',
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$modeName = 'mass_filter_reference'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = if ($ArtifactRootPath) {
    [IO.Path]::GetFullPath($ArtifactRootPath)
} else {
    Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
}
$python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
} else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__rf-mass-filter__reference'
}
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_quadrupole_collision_cooling' -Mode $modeName -Software @('SIMION 2020','Python 3.11') `
    -AdditionalDirectories @('simion')
$runDir = $package.run_dir
$candidateDir = Join-Path $runDir 'simion'
$resultDir = $package.result_dir
$logDir = $package.log_dir
$inputDir = $package.input_dir
$runConfigPath = $package.run_config
$runSummary = $package.summary
$simion = 'C:\Program Files\SIMION-2020\simion.exe'
$officialIob = 'C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'

try {
    $sourceIon = [IO.Path]::GetFullPath($SourceIonPath)
    if (-not (Test-Path -LiteralPath $sourceIon -PathType Leaf)) {
        throw "Mass-filter source ION11 table is missing: $sourceIon"
    }

    $frozenSourceIon = Join-Path $inputDir 'source_particles.ion'
    $frozenBaseline = Join-Path $inputDir 'baseline.json'
    $frozenMode = Join-Path $inputDir 'mode.json'
    $frozenResolved = Join-Path $inputDir 'resolved_design.json'
    $frozenInterface = Join-Path $inputDir 'interface_contract.json'
    $particlePath = Join-Path $inputDir 'mass_scan_particles.ion'
    $massScanMetadata = Join-Path $inputDir 'mass_scan_particles.json'
    Copy-Item -LiteralPath $sourceIon -Destination $frozenSourceIon
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\baseline.json') -Destination $frozenBaseline
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\modes\mass_filter_reference.json') -Destination $frozenMode
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\resolved_design_mass_filter.json') -Destination $frozenResolved
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\interface_contract.json') -Destination $frozenInterface

    Push-Location $repoRoot
    try {
        & $python -m projects.rf_quadrupole_collision_cooling.analysis.generate_mass_scan_particle_table `
            --source $frozenSourceIon --mode $frozenMode --output $particlePath --metadata $massScanMetadata
        if ($LASTEXITCODE -ne 0) {
            throw 'Paired mass-scan particle generation failed.'
        }
    } finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $particlePath -PathType Leaf)) {
        throw "Generated mass-scan particle table is missing: $particlePath"
    }
    $expectedParticles = @(
        Get-Content -LiteralPath $particlePath -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count

    Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_include.gem') `
        -Destination $candidateDir -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') `
        -Destination $candidateDir -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot 'common\multipole\simion_transport.lua') `
        -Destination (Join-Path $candidateDir 'quad_monolithic.lua') -Force
    $flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
    $sourceStatesLua = Join-Path $inputDir 'source_states.lua'
    Push-Location $repoRoot
    try {
        & $python -m projects.rf_quadrupole_collision_cooling.analysis.render_ion11_simion_source `
            --ion-table $particlePath --fly2 $flyPath --source-states-lua $sourceStatesLua
        if ($LASTEXITCODE -ne 0) {
            throw 'Mass-scan ION11 projection failed.'
        }
    } finally {
        Pop-Location
    }
    Copy-Item -LiteralPath $officialIob -Destination (Join-Path $candidateDir 'quad_monolithic.iob') -Force

    $resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 | ConvertFrom-Json
    $numericalMode = Get-Content -LiteralPath $frozenMode -Raw -Encoding UTF8 | ConvertFrom-Json
    $geometry = $resolved.geometry_mm
    $enclosure = $geometry.enclosure
    $interface = Get-Content -LiteralPath $frozenInterface -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $PSBoundParameters.ContainsKey('RfStepsPerPeriod')) {
        $RfStepsPerPeriod = [int]$numericalMode.numerics.simion_rf_steps_per_period
    }
    if (-not $PSBoundParameters.ContainsKey('TrajectoryQuality')) {
        $TrajectoryQuality = [int]$numericalMode.numerics.simion_trajectory_quality
    }
    $rfPeakV = [double]$resolved.drive.rf_amplitude_V_zero_to_peak_per_group
    $frequencyHz = [double]$resolved.drive.frequency_Hz
    $phaseDeg = [double]$resolved.drive.phase_rad * 180 / [Math]::PI
    $dcAmplitudeV = [double]$resolved.drive.dc_amplitude_V_per_group
    $axisVoltageV = [double]$resolved.drive.common_mode_offset_V
    $staticElectrodes = $resolved.static_electrodes_V
    $simionCellMm = 0.2
    $particleStateCsv = Join-Path $resultDir 'particle_state.csv'
    $trajectoryCsv = Join-Path $resultDir 'trajectory_samples.csv'
    $summaryJson = Join-Path $resultDir 'solver_summary.json'
    $runConfigLua = Join-Path $runDir 'run_config.lua'
    $iobReport = Join-Path $logDir 'simion_iob_contract.txt'
    $stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
    $massResponseCsv = Join-Path $resultDir 'mass-response__simion.csv'
    $massMetricsJson = Join-Path $resultDir 'mass-filter__simion-functional-metrics.json'
    $massResponseFigure = Join-Path $resultDir 'mass-response__simion-passband.png'

    $runConfig = [ordered]@{
        schema_version = 1
        role = 'rf_quadrupole_simion_mass_filter_run_config'
        run_id = $RunId
        project = 'rf_quadrupole_collision_cooling'
        mode = $modeName
        project_root = $projectRoot
        inputs = [ordered]@{
            baseline = $frozenBaseline
            resolved_design = $frozenResolved
            interface_contract = $frozenInterface
            mode = $frozenMode
            source_ion11 = $frozenSourceIon
            particle_table = $particlePath
            mass_scan_ion11 = $particlePath
            mass_scan_metadata = $massScanMetadata
            source_states = $sourceStatesLua
        }
        provenance = [ordered]@{
            source_ion11_sha256 = (Get-FileHash -LiteralPath $frozenSourceIon -Algorithm SHA256).Hash
            mass_scan_ion11_sha256 = (Get-FileHash -LiteralPath $particlePath -Algorithm SHA256).Hash
            representation = 'ion11'
        }
        output_dir = $resultDir
        candidate_dir = $candidateDir
        run_dir = $runDir
        rf_steps_per_period = $RfStepsPerPeriod
        trajectory_quality = $TrajectoryQuality
        rf_peak_v = $rfPeakV
        dc_amplitude_v = $dcAmplitudeV
        frequency_hz = $frequencyHz
        particles = $expectedParticles
    }
    $runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

    $luaConfig = @"
return {
  mode=[[$modeName]], operating_point=[[mass_filter_reference]],
  iob=[[$(Join-Path $candidateDir 'quad_monolithic.iob')]], fly2=[[$flyPath]],
  source_states=dofile([[$sourceStatesLua]]),
  particle_state_csv=[[$particleStateCsv]], trajectory_csv=[[$trajectoryCsv]], summary_json=[[$summaryJson]],
  trajectory_quality=$TrajectoryQuality, rf_steps_per_period=$RfStepsPerPeriod,
  rf_peak_v=$rfPeakV, rf_scale=1, axial_scale=0, dc_amplitude_v=$dcAmplitudeV,
  frequency_hz=$frequencyHz, phase_deg=$phaseDeg, axis_voltage_v=$axisVoltageV,
  entrance_voltage_v=$($staticElectrodes.entrance_plate_and_connector),
  exit_voltage_v=$($staticElectrodes.exit_enclosure_and_connector),
  detector_voltage_v=$($staticElectrodes.detector),
  ground_electrode_id=0, output_electrode_id=0, output_reference_v=0,
  maximum_time_us=$($numericalMode.numerics.maximum_time_us),
  trajectory_plane_step_mm=$simionCellMm,
  rod_z_min_mm=$($geometry.rod_z_min), rod_z_max_mm=$($geometry.rod_z_max),
  rod_exit_plane_mm=$($interface.planes.rod_exit.z_mm),
  handoff_plane_mm=$($interface.planes.handoff.z_mm),
  detector_crossing_threshold_mm=$(
      $resolved.interfaces_mm.exit.particle_plane_z_mm -
      $interface.solver_numerics.simion_terminal_surface_backoff_cells * $simionCellMm
  ),
  detector_radius_mm=$($enclosure.detector_radius_mm),
  radial_escape_radius_mm=$($enclosure.outer_half_width_mm),
  expected_pa_nx=$([int][Math]::Round($enclosure.outer_half_width_mm / $simionCellMm) + 1),
  expected_pa_ny=$([int][Math]::Round($enclosure.outer_half_width_mm / $simionCellMm) + 1),
  expected_pa_nz=$(
      [int][Math]::Round(
          ($enclosure.vacuum_z_max_mm - $enclosure.vacuum_z_min_mm) / $simionCellMm
      ) + 1
  ),
  expected_pa_cell_mm=$simionCellMm
}
"@
    # Windows PowerShell 5.1 writes a BOM for UTF8; SIMION Lua 5.1 treats it as source text.
    $luaConfig | Set-Content -LiteralPath $runConfigLua -Encoding ASCII

    Push-Location $candidateDir
    try {
        & $simion --nogui --noprompt gem2pa quad_monolithic.gem quad_monolithic.pa#
        if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
        & $simion --nogui --noprompt refine quad_monolithic.pa#
        if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }
        Start-Sleep -Milliseconds 500

        $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA = $runConfigLua
        $env:RFQUAD_SIMION_REFERENCE_REPORT = $iobReport
        $env:RFQUAD_SIMION_REFERENCE_IOB = Join-Path $candidateDir 'quad_monolithic.iob'
        & $simion --nogui --noprompt lua (Join-Path $PSScriptRoot 'inspect_builtin_quad_reference.lua')
        if ($LASTEXITCODE -ne 0) { throw 'SIMION IOB runtime contract failed.' }
        Start-Sleep -Milliseconds 500

        $stdoutPath = Join-Path $logDir 'simion_stdout.txt'
        $stderrPath = Join-Path $logDir 'simion_stderr.txt'
        $flyArguments = @(
            '--nogui','--noprompt','fly','--trajectory-quality',[string]$TrajectoryQuality,
            '--particles',$flyPath,'--programs','1','--retain-trajectories','0',
            '--adjustable',"transport_rf_steps_per_period=$RfStepsPerPeriod",
            (Join-Path $candidateDir 'quad_monolithic.iob')
        )
        $flyProcess = Start-Process -FilePath $simion -ArgumentList $flyArguments `
            -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath
        Get-Content -LiteralPath $stdoutPath -Encoding UTF8
        if ((Get-Item -LiteralPath $stderrPath).Length -gt 0) {
            Get-Content -LiteralPath $stderrPath -Encoding UTF8
        }
        if ($flyProcess.ExitCode -ne 0) {
            throw "SIMION fly failed with exit code $($flyProcess.ExitCode)."
        }
    } finally {
        Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
        Remove-Item Env:RFQUAD_SIMION_REFERENCE_REPORT -ErrorAction SilentlyContinue
        Remove-Item Env:RFQUAD_SIMION_REFERENCE_IOB -ErrorAction SilentlyContinue
        Pop-Location
    }

    $summary = Get-Content -LiteralPath $summaryJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($summary.particles -ne $expectedParticles -or $summary.collision_model -ne 'none') {
        throw "SIMION mass-filter execution integrity failed: $($summary | ConvertTo-Json -Compress)"
    }
    Push-Location $repoRoot
    try {
        & $python -m common.contracts.particle_state `
            --state $particleStateCsv --particles $particlePath --source-format ion11 `
            --contract $frozenInterface --axial-offset-mm 0 --frequency-hz $frequencyHz `
            --phase-rad ($phaseDeg * [Math]::PI / 180) --solver SIMION --output $stateContractReport
        if ($LASTEXITCODE -ne 0) {
            throw 'Particle-state contract gate failed.'
        }

        & $python -m projects.rf_quadrupole_collision_cooling.analysis.analyze_simion_mass_scan `
            --state $particleStateCsv --particles $particlePath `
            --baseline $frozenBaseline --mode $frozenMode `
            --response $massResponseCsv --metrics $massMetricsJson --figure $massResponseFigure
        $analysisExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    foreach ($analysisOutput in @($massResponseCsv,$massMetricsJson,$massResponseFigure)) {
        if (-not (Test-Path -LiteralPath $analysisOutput -PathType Leaf)) {
            throw "SIMION mass-filter analysis did not produce required output: $analysisOutput"
        }
    }
    $massMetrics = Get-Content -LiteralPath $massMetricsJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($massMetrics.status -notin @('PASS','FAIL')) {
        throw "SIMION mass-filter analysis returned invalid physical status: $($massMetrics.status)"
    }
    if (($analysisExitCode -eq 0) -ne ($massMetrics.status -eq 'PASS')) {
        throw "SIMION mass-filter analyzer exit/status mismatch: exit=$analysisExitCode status=$($massMetrics.status)"
    }
    $physicalDecision = [string]$massMetrics.status

    $shaPath = Join-Path $candidateDir 'SHA256SUMS.csv'
    $hashes = Get-ChildItem -LiteralPath $candidateDir -File | Where-Object {
        $_.Name -ne 'SHA256SUMS.csv' -and $_.Name -notlike 'trj*.tmp'
    } | Sort-Object Name | ForEach-Object {
        [pscustomobject]@{
            file = $_.Name
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    }
    $hashes | Export-Csv -LiteralPath $shaPath -NoTypeInformation -Encoding UTF8

    $rootSummary = [ordered]@{
        schema_version = 1
        role = 'rf_quadrupole_mass_filter_summary'
        status = 'success'
        mode = $modeName
        physical_decision = $physicalDecision
        functional_gate = [string]$massMetrics.status
        particles = $expectedParticles
        hits = $summary.hits
        transmission = $summary.transmission
        mass_response = 'results/mass-response__simion.csv'
        metrics = 'results/mass-filter__simion-functional-metrics.json'
        figure = 'results/mass-response__simion-passband.png'
    }
    $rootSummary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runSummary -Encoding UTF8
    $manifestOutputs = @(
        $trajectoryCsv,$summaryJson,$particleStateCsv,$stateContractReport,
        (Join-Path $logDir 'simion_stdout.txt'),(Join-Path $logDir 'simion_stderr.txt'),
        (Join-Path $candidateDir 'quad_monolithic.iob'),(Join-Path $candidateDir 'quad_monolithic.pa0'),
        $flyPath,$iobReport,$shaPath,$massResponseCsv,$massMetricsJson,$massResponseFigure,$runSummary
    )
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath -Status success `
        -Software @('SIMION 2020','Python 3.11') -Outputs $manifestOutputs
    "EXECUTION=PASS DECISION=$physicalDecision RUN_ID=$RunId HITS=$($summary.hits) " +
        "TRANSMISSION=$($summary.transmission)"
}
catch {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath -Summary $runSummary `
        -SummaryRole 'rf_quadrupole_mass_filter_summary' -Reason $_.Exception.Message `
        -Software @('SIMION 2020','Python 3.11')
    throw
}
