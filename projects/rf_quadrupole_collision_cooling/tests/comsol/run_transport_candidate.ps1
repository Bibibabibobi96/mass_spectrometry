param(
    [string]$RunId = '',
    [int]$RfStepsPerPeriod = 80,
    [int]$MeshAutoLevel = 1,
    [double]$MeshHmaxMm = [double]::NaN,
    [double]$SourceAxialOffsetMm = 0.0,
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
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $detail = $Mode.Replace('_','-')
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__sim__comsol__rf-transport__$detail"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$resultDir = Join-Path $runDir 'results'
$inputDir = Join-Path $runDir 'inputs'
$candidateDir = Join-Path $runDir 'comsol'
$logDir = Join-Path $runDir 'logs'
$runtimeDir = Join-Path $runDir 'runtime'
if (Test-Path -LiteralPath $runDir) { throw "Run directory already exists: $RunId" }

$particleTable = if ([string]::IsNullOrWhiteSpace($ParticleTablePath)) {
    Join-Path $projectRoot 'config\particles\official_fixed_25.ion'
} else { [IO.Path]::GetFullPath($ParticleTablePath) }
if (-not (Test-Path -LiteralPath $particleTable -PathType Leaf)) { throw "Particle table is missing: $particleTable" }
$expectedParticles = @(Get-Content -LiteralPath $particleTable -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
$resolved = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
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
if ([double]::IsNaN($RfPeakV) -or [double]::IsInfinity($RfPeakV)) { $RfPeakV = $resolved.mode.rf.amplitude_V_peak }
if ([double]::IsNaN($FrequencyHz) -or [double]::IsInfinity($FrequencyHz)) { $FrequencyHz = $resolved.mode.rf.frequency_Hz }
$modeInput = if ($Mode -eq 'transport_no_collision') { 'config/modes/transport_no_collision.json' } else { 'config/modes/transport_interface_readiness.json' }

New-Item -ItemType Directory -Path $runDir,$inputDir,$resultDir,$candidateDir,$logDir,$runtimeDir -Force | Out-Null

$familyOperatingPath = Join-Path $inputDir 'family_operating_contract.json'
Push-Location $repoRoot
try {
    & $python -m common.multipole.resolve_family_operating_contract --adapter quadrupole `
        --baseline (Join-Path $projectRoot 'config\baseline.json') --mode (Join-Path $projectRoot $modeInput) `
        --rf-amplitude-v-per-group $RfPeakV --frequency-hz $FrequencyHz --output $familyOperatingPath
    if ($LASTEXITCODE -ne 0) { throw 'Shared multipole operating-contract resolution failed.' }
}
finally { Pop-Location }
$familyOperating = Get-Content -LiteralPath $familyOperatingPath -Raw -Encoding UTF8 | ConvertFrom-Json

$runConfigPath = Join-Path $runDir 'run_config.json'
$bootstrapReport = Join-Path $logDir 'comsol_bootstrap_report.txt'
$guiVerifyReport = Join-Path $logDir 'comsol_gui_compute_report.txt'
$stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_comsol_run_config'; run_id=$RunId
    project='rf_quadrupole_collision_cooling'; mode=$Mode; project_root=$projectRoot
    inputs=[ordered]@{
        baseline='config/baseline.json'; resolved_geometry='config/resolved_geometry.json'; resolved_contract=$resolvedContractInput
        mode=$modeInput; particle_table=$particleTable
        family_operating_contract=$familyOperatingPath
        interface_contract='config/interface_contract.json'
    }
    results_dir=$resultDir; comsol_dir=$candidateDir; logs_dir=$logDir; runtime_dir=$runtimeDir; run_dir=$runDir
    comsol_rf_steps_per_period=$RfStepsPerPeriod; comsol_mesh_auto_level=$MeshAutoLevel
    comsol_hmax_mm=$MeshHmaxMm; source_axial_offset_mm=$SourceAxialOffsetMm
    particle_table_path=$particleTable; operating_point=$OperatingPoint
    rf_peak_v=$RfPeakV; frequency_hz=$FrequencyHz; particles=$expectedParticles
    formal_gate_passed=$false
}
# The run config is ASCII-only.  Avoid the Windows PowerShell 5.1 UTF-8 BOM,
# which MATLAB jsondecode treats as an invalid first JSON character.
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding ASCII

$env:RFQUAD_RUN_CONFIG = $runConfigPath
try {
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $PSScriptRoot 'run_nocollision_candidate.m') `
        -ReportPath $bootstrapReport -StartupAttempts 1
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL candidate launcher failed.' }
}
finally {
    Remove-Item Env:RFQUAD_RUN_CONFIG -ErrorAction SilentlyContinue
}

$modelPath = Join-Path $candidateDir 'rf_quadrupole_collision_cooling__model.mph'
$summaryPath = Join-Path $resultDir 'solver_summary.json'
$trajectoryPath = Join-Path $resultDir 'trajectory_samples.csv'
$particleStatePath = Join-Path $resultDir 'particle_state.csv'
$rawPhaseSpacePath = Join-Path $resultDir 'particle_raw.csv'
$summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$env:RFQUAD_COMSOL_MODEL_PATH = $modelPath
$env:RFQUAD_EXPECTED_PARTICLES = [string]$expectedParticles
$env:RFQUAD_EXPECTED_HITS = [string]$summary.hits
$env:RFQUAD_EXPECTED_RF_PEAK_V = [string]$RfPeakV
$env:RFQUAD_EXPECTED_FREQUENCY_HZ = [string]$FrequencyHz
try {
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $PSScriptRoot 'verify_nocollision_comsol.m') `
        -ReportPath $guiVerifyReport -StartupAttempts 1
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL GUI Compute verification failed.' }
}
finally {
    Remove-Item Env:RFQUAD_COMSOL_MODEL_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_PARTICLES -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_HITS -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_RF_PEAK_V -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_EXPECTED_FREQUENCY_HZ -ErrorAction SilentlyContinue
}

$expected = @($modelPath,$summaryPath,$trajectoryPath,$particleStatePath,$rawPhaseSpacePath,$bootstrapReport,$guiVerifyReport)
$missing = @($expected | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missing.Count -gt 0) { throw "COMSOL candidate outputs are missing: $($missing -join ', ')" }

Push-Location $repoRoot
try {
& $python -m projects.rf_quadrupole_collision_cooling.analysis.verify_particle_state_contract `
    --state $particleStatePath --particles $particleTable --source-format ion11 `
    --contract (Join-Path $projectRoot 'config\interface_contract.json') --axial-offset-mm $SourceAxialOffsetMm `
    --frequency-hz $FrequencyHz --phase-rad $familyOperating.voltage.phase_rad `
    --solver COMSOL --output $stateContractReport
    if ($LASTEXITCODE -ne 0) { throw 'Particle-state contract gate failed.' }
}
finally { Pop-Location }

$runSummary = Join-Path $runDir 'summary.json'
[ordered]@{
    schema_version=1; role='rf_quadrupole_transport_summary'; status='success'; mode=$Mode
    particles=$expectedParticles; hits=$summary.hits; transmission=$summary.transmission
    solver_summary='results/solver_summary.json'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runSummary -Encoding UTF8

& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'COMSOL 6.4' --software 'MATLAB R2025b' `
    --output $modelPath --output $summaryPath --output $trajectoryPath `
    --output $particleStatePath --output $rawPhaseSpacePath --output $bootstrapReport --output $guiVerifyReport --output $stateContractReport --output $runSummary
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
"STATUS=PASS RUN_ID=$RunId HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
