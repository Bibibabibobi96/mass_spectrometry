param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceIonPath,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$SolverNumericsContractPath,
    [Nullable[int]]$RfStepsPerPeriod = $null,
    [Nullable[int]]$TrajectoryQuality = $null,
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
. (Join-Path $projectRoot 'runtime\simion_run_config.ps1')
. (Join-Path $projectRoot 'runtime\simion_execution.ps1')
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
    $frozenNumericalContract = Join-Path $inputDir 'simion_solver_numerics.json'
    $particlePath = Join-Path $inputDir 'mass_scan_particles.ion'
    $massScanMetadata = Join-Path $inputDir 'mass_scan_particles.json'
    $templateDir = Join-Path $inputDir 'simion_layout_template'
    $templateResolution = Join-Path $templateDir 'resolution.json'
    New-Item -ItemType Directory -Path $templateDir | Out-Null
    Push-Location $repoRoot
    try {
        & $python -m common.multipole.simion_layout_template --repo-root $repoRoot `
            --output $templateResolution | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Shared SIMION layout template resolution failed.' }
    } finally { Pop-Location }
    $templateProfile = Get-Content -LiteralPath $templateResolution -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $templateRegistry = Copy-VerifiedRunInput -Source $templateProfile.registry_path `
        -Destination (Join-Path $templateDir 'simion_layout_template.json')
    $templateManifest = Copy-VerifiedRunInput -Source $templateProfile.run_manifest.path `
        -Destination (Join-Path $templateDir 'registration_run_manifest.json')
    $templateIob = Copy-VerifiedRunInput -Source $templateProfile.bundle.iob.path `
        -Destination (Join-Path $templateDir 'quad_monolithic.iob')
    $templateCon = Copy-VerifiedRunInput -Source $templateProfile.bundle.con.path `
        -Destination (Join-Path $templateDir 'quad_monolithic.con')
    Copy-VerifiedRunInput -Source $sourceIon -Destination $frozenSourceIon | Out-Null
    $sourceParticleCount = @(
        Get-Content -LiteralPath $frozenSourceIon -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count
    & $python (Join-Path $repoRoot `
        'common\contracts\particle_count_policy.py') --count $sourceParticleCount
    if ($LASTEXITCODE -ne 0) {
        throw 'Mass-filter source violates the repository N=100/N=1000 policy.'
    }
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'config\baseline.json') `
        -Destination $frozenBaseline | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'config\modes\mass_filter_reference.json') `
        -Destination $frozenMode | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'config\resolved_design_mass_filter.json') `
        -Destination $frozenResolved | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'config\interface_contract.json') `
        -Destination $frozenInterface | Out-Null
    Copy-VerifiedRunInput -Source ([IO.Path]::GetFullPath($SolverNumericsContractPath)) `
        -Destination $frozenNumericalContract | Out-Null
    Push-Location $repoRoot
    try {
        & $python -m common.multipole.verify_resolved_design $frozenResolved
        if ($LASTEXITCODE -ne 0) { throw 'Frozen resolved-design identity verification failed.' }
    } finally {
        Pop-Location
    }

    Push-Location $repoRoot
    try {
        & $python -m `
            projects.rf_quadrupole_collision_cooling.workflows.mass_filter_reference.prepare_simion_scan `
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

    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'simion\geometry\quad_include.gem') `
        -Destination (Join-Path $candidateDir 'quad_include.gem') | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') `
        -Destination (Join-Path $candidateDir 'quad_monolithic.gem') | Out-Null
    $programSource = Copy-VerifiedRunInput `
        -Source (Join-Path $repoRoot 'common\multipole\simion_transport.lua') `
        -Destination (Join-Path $candidateDir 'multipole_runtime_program.lua')
    $iobBuilder = Copy-VerifiedRunInput `
        -Source (Join-Path $repoRoot 'common\multipole\build_simion_runtime_iob.lua') `
        -Destination (Join-Path $candidateDir 'build_simion_runtime_iob.lua')
    $flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
    $sourceStatesLua = Join-Path $inputDir 'source_states.lua'
    Push-Location $repoRoot
    try {
        & $python -m `
            projects.rf_quadrupole_collision_cooling.workflows.mass_filter_reference.render_simion_source `
            --ion-table $particlePath --fly2 $flyPath --source-states-lua $sourceStatesLua
        if ($LASTEXITCODE -ne 0) {
            throw 'Mass-scan ION11 projection failed.'
        }
    } finally {
        Pop-Location
    }
    Copy-VerifiedRunInput -Source $templateIob `
        -Destination (Join-Path $candidateDir 'quad_monolithic.iob') | Out-Null
    Copy-VerifiedRunInput -Source $templateCon `
        -Destination (Join-Path $candidateDir 'quad_monolithic.con') | Out-Null

    $resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 | ConvertFrom-Json
    $numericalMode = Get-Content -LiteralPath $frozenMode -Raw -Encoding UTF8 | ConvertFrom-Json
    $interface = Get-Content -LiteralPath $frozenInterface -Raw -Encoding UTF8 | ConvertFrom-Json
    $numericalContract = Get-Content -LiteralPath $frozenNumericalContract -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $PSBoundParameters.ContainsKey('RfStepsPerPeriod')) {
        $RfStepsPerPeriod = [int]$numericalContract.baseline_rf_steps_per_period
    }
    if (-not $PSBoundParameters.ContainsKey('TrajectoryQuality')) {
        $TrajectoryQuality = [int]$numericalContract.trajectory_quality
    }
    if ($RfStepsPerPeriod -ne [int]$numericalContract.baseline_rf_steps_per_period -or
        $TrajectoryQuality -ne [int]$numericalContract.trajectory_quality) {
        throw 'SIMION mass-filter numerics differ from the frozen baseline contract.'
    }
    $particleStateCsv = Join-Path $resultDir 'particle_state.csv'
    $trajectoryCsv = Join-Path $resultDir 'trajectory_samples.csv'
    $summaryJson = Join-Path $resultDir 'solver_summary.json'
    $runConfigLua = Join-Path $runDir 'run_config.lua'
    $iobReport = Join-Path $logDir 'simion_iob_contract.txt'
    $stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
    $massResponseCsv = Join-Path $resultDir 'mass-response__simion.csv'
    $massMetricsJson = Join-Path $resultDir 'mass-filter__simion-functional-metrics.json'
    $massResponseFigure = Join-Path $resultDir 'mass-response__simion-passband.png'
    $coreConfig = New-RfSimionCoreRunConfig `
        -ResolvedDesign $resolved -InterfaceContract $interface -SolverNumerics $numericalContract `
        -RfStepsPerPeriod $RfStepsPerPeriod -TrajectoryQuality $TrajectoryQuality `
        -ModeName $modeName -OperatingPoint 'mass_filter_reference' `
        -IobPath (Join-Path $candidateDir 'quad_monolithic.iob') -Fly2Path $flyPath `
        -SourceStatesLua $sourceStatesLua -ParticleStateCsv $particleStateCsv `
        -TrajectoryCsv $trajectoryCsv -SummaryJson $summaryJson

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
            numerical_contract = $frozenNumericalContract
            source_ion11 = $frozenSourceIon
            particle_table = $particlePath
            mass_scan_ion11 = $particlePath
            mass_scan_metadata = $massScanMetadata
            source_states = $sourceStatesLua
            simion_layout_template_resolution = $templateResolution
            simion_layout_template_registry = $templateRegistry
            simion_layout_registration_manifest = $templateManifest
            simion_layout_template_iob = $templateIob
            simion_layout_template_con = $templateCon
            simion_iob_builder = $iobBuilder
            simion_program_source = $programSource
        }
        provenance = [ordered]@{
            source_ion11_sha256 = Get-RunFileSha256 -Path $frozenSourceIon
            mass_scan_ion11_sha256 = Get-RunFileSha256 -Path $particlePath
            representation = 'ion11'
            waveform = $coreConfig.waveform
            parent_resolved_design_sha256 = $coreConfig.parent_resolved_design_sha256
            solver_numerics_contract_sha256 = Get-RunFileSha256 -Path $frozenNumericalContract
            rf_steps_per_period = [int]$coreConfig.rf_steps_per_period
            trajectory_quality = [int]$coreConfig.trajectory_quality
            rf_steps_override = $false
            simion_layout_template = [ordered]@{
                template_id = [string]$templateProfile.template_id
                registration_run_id = [string]$templateProfile.registration_run_id
                registry_sha256 = [string]$templateProfile.registry_sha256
                registration_manifest_sha256 = [string]$templateProfile.run_manifest.sha256
                iob_sha256 = [string]$templateProfile.bundle.iob.sha256
                con_sha256 = [string]$templateProfile.bundle.con.sha256
            }
        }
        output_dir = $resultDir
        candidate_dir = $candidateDir
        run_dir = $runDir
        rf_steps_per_period = $coreConfig.rf_steps_per_period
        trajectory_quality = $coreConfig.trajectory_quality
        rf_peak_v = $coreConfig.rf_peak_v
        dc_amplitude_v = $coreConfig.dc_amplitude_v
        frequency_hz = $coreConfig.frequency_hz
        waveform = $coreConfig.waveform
        parent_resolved_design_sha256 = $coreConfig.parent_resolved_design_sha256
        particles = $expectedParticles
    }
    $runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

    $luaConfig = ConvertTo-RfSimionLuaConfig -CoreConfig $coreConfig `
        -SharedProgramPath (Join-Path $candidateDir 'quad_monolithic.lua')
    # Windows PowerShell 5.1 writes a BOM for UTF8; SIMION Lua 5.1 treats it as source text.
    $luaConfig | Set-Content -LiteralPath $runConfigLua -Encoding ASCII

    Invoke-RfSimionCoreRun -SimionExe $simion -CandidateDir $candidateDir `
        -IobPath ([string]$coreConfig.iob) -Fly2Path ([string]$coreConfig.fly2) `
        -IobBuilderScript $iobBuilder -ProgramSourcePath $programSource `
        -RunConfigLua $runConfigLua `
        -InspectScript (Join-Path $projectRoot `
            'tests\simion\inspect_builtin_quad_reference.lua') `
        -IobReport $iobReport -LogDir $logDir `
        -TrajectoryQuality ([int]$coreConfig.trajectory_quality) `
        -RfStepsPerPeriod ([int]$coreConfig.rf_steps_per_period)

    $summary = Get-Content -LiteralPath $summaryJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($summary.particles -ne $expectedParticles -or $summary.collision_model -ne 'none' -or
        $summary.parent_resolved_design_sha256 -cne $coreConfig.parent_resolved_design_sha256) {
        throw "SIMION mass-filter execution integrity failed: $($summary | ConvertTo-Json -Compress)"
    }
    Push-Location $repoRoot
    try {
        & $python -m common.contracts.particle_state `
            --state $particleStateCsv --particles $particlePath --source-format ion11 `
            --contract $frozenInterface --axial-offset-mm 0 `
            --frequency-hz ([double]$coreConfig.frequency_hz) `
            --phase-rad ([double]$coreConfig.phase_deg * [Math]::PI / 180) `
            --solver SIMION --output $stateContractReport
        if ($LASTEXITCODE -ne 0) {
            throw 'Particle-state contract gate failed.'
        }

        & $python -m `
            projects.rf_quadrupole_collision_cooling.workflows.mass_filter_reference.evaluate_simion `
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
    Write-RunDirectoryChecksumInventory -Directory $candidateDir -OutputPath $shaPath `
        -ExcludedPatterns @('trj*.tmp')

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
        (Join-Path $logDir 'simion_iob_stdout.txt'),(Join-Path $logDir 'simion_iob_stderr.txt'),
        (Join-Path $logDir 'simion_iob_exit_code.txt'),
        (Join-Path $logDir 'simion_stdout.txt'),(Join-Path $logDir 'simion_stderr.txt'),
        (Join-Path $candidateDir 'quad_monolithic.iob'),(Join-Path $candidateDir 'quad_monolithic.con'),
        (Join-Path $candidateDir 'quad_monolithic.pa0'),
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
