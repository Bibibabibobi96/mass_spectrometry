param(
    [Parameter(Mandatory = $true)][string]$ComsolRunId,
    [Parameter(Mandatory = $true)][string]$SimionRunId,
    [string]$RunId = '',
    [ValidateSet('transport_interface_readiness')]
    [string]$Mode = 'transport_interface_readiness',
    [string]$PythonExe = '',
    [string]$ParticleTablePath = '',
    [double]$FrequencyHz = [double]::NaN,
    [double]$PhaseRad = 0.0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'particle_table_identity.ps1')
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__analysis__cross__rf-transport__$($Mode.Replace('_','-'))"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$resultDir = Join-Path $runDir 'results'
$inputDir = Join-Path $runDir 'inputs'
if (Test-Path -LiteralPath $runDir) { throw "Cross-solver run already exists: $RunId" }

$comsolRun = Join-Path $artifactRoot "runs\$ComsolRunId"
$simionRun = Join-Path $artifactRoot "runs\$SimionRunId"
$comsolManifest = Join-Path $comsolRun 'run_manifest.json'
$simionManifest = Join-Path $simionRun 'run_manifest.json'
$comsolState = Join-Path $comsolRun 'results\particle_state.csv'
$simionState = Join-Path $simionRun 'results\particle_state.csv'
$comparison = Join-Path $resultDir 'comparison.json'
$paired = Join-Path $resultDir 'paired_particle_state.csv'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python runtime missing: $python" }

& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $comsolManifest
if ($LASTEXITCODE -ne 0) { throw 'COMSOL run-manifest verification failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $simionManifest
if ($LASTEXITCODE -ne 0) { throw 'SIMION run-manifest verification failed.' }

$comsolManifestData = Get-Content -LiteralPath $comsolManifest -Raw -Encoding UTF8 | ConvertFrom-Json
$simionManifestData = Get-Content -LiteralPath $simionManifest -Raw -Encoding UTF8 | ConvertFrom-Json
$comsolConfig = Get-Content -LiteralPath $comsolManifestData.run_config.path -Raw -Encoding UTF8 | ConvertFrom-Json
$simionConfig = Get-Content -LiteralPath $simionManifestData.run_config.path -Raw -Encoding UTF8 | ConvertFrom-Json
if ($comsolConfig.role -ne 'rf_quadrupole_comsol_run_config' -or
    $simionConfig.role -ne 'rf_quadrupole_simion_run_config') {
    throw 'Cross-solver comparison accepts only interface transport run-config roles.'
}
if ($comsolConfig.mode -ne $Mode -or $simionConfig.mode -ne $Mode) {
    throw "Run-config mode does not match requested candidate mode: $Mode"
}
if ($comsolConfig.operating_point -ne $simionConfig.operating_point -or
    [double]$comsolConfig.rf_peak_v -ne [double]$simionConfig.rf_peak_v -or
    [double]$comsolConfig.frequency_hz -ne [double]$simionConfig.frequency_hz) {
    throw 'COMSOL and SIMION operating point, RF peak, or frequency differ.'
}
$resolvedPath = Join-Path $projectRoot 'config\resolved_design_official.json'
$resolved = Get-Content -LiteralPath $resolvedPath -Raw -Encoding UTF8 | ConvertFrom-Json
$comsolBindingValidation = Join-Path $inputDir 'comsol_particle_source_binding.json'
$simionBindingValidation = Join-Path $inputDir 'simion_particle_source_binding.json'
New-Item -ItemType Directory -Path $runDir,$resultDir,$inputDir -Force | Out-Null
$particleIdentity = Assert-RfTransportParticleTableIdentity `
    -Python $python -RepoRoot $repoRoot `
    -ComsolRunConfig $comsolConfig -SimionRunConfig $simionConfig `
    -ComsolBindingOutput $comsolBindingValidation `
    -SimionBindingOutput $simionBindingValidation `
    -ExplicitIon11Path $ParticleTablePath
$particlePath = $particleIdentity.ion11_path
if ([double]::IsNaN($FrequencyHz) -or [double]::IsInfinity($FrequencyHz)) {
    $FrequencyHz = [double]$comsolConfig.frequency_hz
} elseif ($FrequencyHz -ne [double]$comsolConfig.frequency_hz) {
    throw 'Explicit frequency differs from the solver run configs.'
}
$interfacePath = Join-Path $projectRoot 'config\interface_contract.json'
$regressionModePath = Join-Path $projectRoot 'config\modes\transport_no_collision.json'
$interfaceModePath = Join-Path $projectRoot 'config\modes\transport_interface_readiness.json'
$entries = @(
    [pscustomobject]@{
        Solver='COMSOL'; Path=$comsolState
        Particles=$particleIdentity.comsol_consumed_path; Format='ion11'
    },
    [pscustomobject]@{
        Solver='SIMION'; Path=$simionState
        Particles=$particleIdentity.simion_consumed_path; Format='canonical'
    }
)
foreach ($entry in $entries) {
    Push-Location $repoRoot
    try {
        & $python -m common.contracts.particle_state `
            --state $entry.Path --particles $entry.Particles --source-format $entry.Format --contract $interfacePath `
            --frequency-hz $FrequencyHz --phase-rad $PhaseRad --solver $entry.Solver
        if ($LASTEXITCODE -ne 0) { throw "$($entry.Solver) particle-state contract failed." }
    }
    finally { Pop-Location }
}

$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_cross_solver_run_config'; run_id=$RunId
    project='rf_quadrupole_collision_cooling'; mode="${Mode}_phase_space_comparison"
    project_root=$projectRoot; formal_gate_passed=$false
    source_sample_family_sha256=$particleIdentity.source_sample_family_sha256
    latent_sha256=$particleIdentity.latent_sha256
    coordinate_mapping_version=$particleIdentity.coordinate_mapping_version
    ion11_sha256=$particleIdentity.ion11_sha256
    canonical10_sha256=$particleIdentity.canonical10_sha256
    inputs=[ordered]@{
        comsol_manifest=$comsolManifest; simion_manifest=$simionManifest
        comsol_particle_state=$comsolState; simion_particle_state=$simionState
        comsol_particle_table=$particleIdentity.comsol_consumed_path
        simion_particle_table=$particleIdentity.simion_consumed_path
        particle_table=$particlePath
        comsol_particle_source_binding=$comsolBindingValidation
        simion_particle_source_binding=$simionBindingValidation
        resolved_design='config/resolved_design_official.json'
        regression_mode='config/modes/transport_no_collision.json'
        interface_mode='config/modes/transport_interface_readiness.json'
        interface_contract='config/interface_contract.json'
        mode='config/modes/transport_interface_readiness.json'
    }
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding ASCII
$summaryPath = Join-Path $runDir 'summary.json'

& $python (Join-Path $projectRoot 'analysis\compare_particle_state.py') `
    --comsol $comsolState --simion $simionState --resolved $resolvedPath `
    --regression-mode $regressionModePath --interface-mode $interfaceModePath `
    --particles $particlePath --output $comparison --paired-output $paired
$comparisonExit = $LASTEXITCODE
if ($comparisonExit -ne 0 -or
    -not (Test-Path -LiteralPath $comparison -PathType Leaf) -or
    -not (Test-Path -LiteralPath $paired -PathType Leaf)) {
    [ordered]@{
        schema_version=1; role='rf_quadrupole_cross_solver_summary'
        status='failed'; execution_status='failed'; decision_status='NOT_EVALUATED'
        reason="Particle-state comparison execution failed with exit code $comparisonExit."
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
        --run-config $runConfigPath --status failed `
        --software 'COMSOL 6.4' --software 'SIMION 2020' --output $summaryPath
    if ($LASTEXITCODE -ne 0) { throw 'Failed comparison manifest generation failed.' }
    throw 'Cross-solver particle-state comparison failed before writing complete evidence.'
}

$comparisonDocument = Get-Content -LiteralPath $comparison -Raw -Encoding UTF8 | ConvertFrom-Json
if ($comparisonDocument.execution_status -ne 'success' -or
    $comparisonDocument.status -notin @('PASS','FAIL')) {
    [ordered]@{
        schema_version=1; role='rf_quadrupole_cross_solver_summary'
        status='failed'; execution_status='failed'; decision_status='NOT_EVALUATED'
        reason='Cross-solver comparison report has an invalid execution or decision status.'
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
        --run-config $runConfigPath --status failed `
        --software 'COMSOL 6.4' --software 'SIMION 2020' `
        --output $comparison --output $paired --output $summaryPath
    if ($LASTEXITCODE -ne 0) { throw 'Invalid comparison manifest generation failed.' }
    throw 'Cross-solver comparison report has an invalid execution or decision status.'
}
[ordered]@{
    schema_version=1; role='rf_quadrupole_cross_solver_summary'
    status='success'; execution_status='success'
    decision_status=$comparisonDocument.status
    comparison='results/comparison.json'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'COMSOL 6.4' --software 'SIMION 2020' `
    --output $comparison --output $paired --output $summaryPath
if ($LASTEXITCODE -ne 0) { throw 'Cross-solver manifest generation failed.' }
if ($comparisonDocument.status -ne 'PASS') {
    throw "Cross-solver comparison completed but did not meet acceptance targets: $comparison"
}
"STATUS=PASS RUN_ID=$RunId"
