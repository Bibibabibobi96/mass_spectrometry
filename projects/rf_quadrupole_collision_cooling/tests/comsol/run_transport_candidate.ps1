param(
    [string]$RunLabel = ('phase_space_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
    [int]$RfStepsPerPeriod = 80,
    [int]$MeshAutoLevel = 1,
    [double]$MeshHmaxMm = [double]::NaN,
    [double]$SourceAxialOffsetMm = 0.0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$runDir = Join-Path $artifactRoot "runs\transport_no_collision\comsol_$RunLabel"
$resultDir = Join-Path $artifactRoot 'results\comsol'
$candidateDir = Join-Path $artifactRoot 'models\comsol\candidates'
if (Test-Path -LiteralPath $runDir) { throw "Run directory already exists; choose a new RunLabel: $RunLabel" }
New-Item -ItemType Directory -Path $runDir,$resultDir,$candidateDir -Force | Out-Null

$runConfigPath = Join-Path $runDir 'run_config.json'
$bootstrapReport = Join-Path $runDir 'comsol_bootstrap_report.txt'
$guiVerifyReport = Join-Path $runDir 'comsol_gui_compute_report.txt'
$stateContractReport = Join-Path $runDir 'particle_state_contract.json'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_comsol_run_config'; run_id=$RunLabel
    project='rf_quadrupole_collision_cooling'; mode='transport_no_collision'; project_root=$projectRoot
    inputs=[ordered]@{
        baseline='config/baseline.json'; resolved_geometry='config/resolved_geometry.json'
        mode='config/modes/transport_no_collision.json'; particle_table='config/particles/official_fixed_25.ion'
        interface_contract='config/interface_contract.json'
    }
    output_dir=$resultDir; candidate_dir=$candidateDir; run_dir=$runDir
    comsol_rf_steps_per_period=$RfStepsPerPeriod; comsol_mesh_auto_level=$MeshAutoLevel
    comsol_hmax_mm=$MeshHmaxMm; source_axial_offset_mm=$SourceAxialOffsetMm
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

$suffix = "_$RunLabel"
$modelPath = Join-Path $candidateDir "rf_quadrupole_transport_no_collision_simion_reference_$RunLabel.mph"
$summaryPath = Join-Path $resultDir "transport_no_collision_summary$suffix.json"
$trajectoryPath = Join-Path $resultDir "transport_no_collision_trajectory_samples$suffix.csv"
$particleStatePath = Join-Path $resultDir "transport_no_collision_particle_state$suffix.csv"
$rawPhaseSpacePath = Join-Path $resultDir "transport_no_collision_particle_raw$suffix.csv"
$env:RFQUAD_COMSOL_MODEL_PATH = $modelPath
try {
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $PSScriptRoot 'verify_nocollision_comsol.m') `
        -ReportPath $guiVerifyReport -StartupAttempts 1
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL GUI Compute verification failed.' }
}
finally {
    Remove-Item Env:RFQUAD_COMSOL_MODEL_PATH -ErrorAction SilentlyContinue
}

$expected = @($modelPath,$summaryPath,$trajectoryPath,$particleStatePath,$rawPhaseSpacePath,$bootstrapReport,$guiVerifyReport)
$missing = @($expected | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missing.Count -gt 0) { throw "COMSOL candidate outputs are missing: $($missing -join ', ')" }

$resolved = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $projectRoot 'analysis\verify_particle_state_contract.py') `
    --state $particleStatePath --particles (Join-Path $projectRoot 'config\particles\official_fixed_25.ion') `
    --interface (Join-Path $projectRoot 'config\interface_contract.json') --axial-offset-mm $SourceAxialOffsetMm `
    --frequency-hz $resolved.mode.rf.frequency_Hz --phase-rad $resolved.mode.rf.phase_rad `
    --solver COMSOL --output $stateContractReport
if ($LASTEXITCODE -ne 0) { throw 'Particle-state contract gate failed.' }

& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'COMSOL 6.4' --software 'MATLAB R2025b' `
    --output $modelPath --output $summaryPath --output $trajectoryPath `
    --output $particleStatePath --output $rawPhaseSpacePath --output $bootstrapReport --output $guiVerifyReport --output $stateContractReport
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
$summary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
"STATUS=PASS LABEL=$RunLabel HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
