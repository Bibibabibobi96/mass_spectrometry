param(
    [Parameter(Mandatory = $true)][string]$ComsolRunId,
    [Parameter(Mandatory = $true)][string]$SimionRunId,
    [string]$RunId = '',
    [ValidateSet('transport_no_collision','transport_interface_readiness')]
    [string]$Mode = 'transport_no_collision',
    [string]$PythonExe = '',
    [string]$ParticleTablePath = '',
    [double]$FrequencyHz = [double]::NaN,
    [double]$PhaseRad = 0.0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
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
if ($comsolConfig.mode -ne $Mode -or $simionConfig.mode -ne $Mode) {
    throw "Run-config mode does not match requested candidate mode: $Mode"
}
if ($comsolConfig.operating_point -ne $simionConfig.operating_point -or
    [double]$comsolConfig.rf_peak_v -ne [double]$simionConfig.rf_peak_v -or
    [double]$comsolConfig.frequency_hz -ne [double]$simionConfig.frequency_hz) {
    throw 'COMSOL and SIMION operating point, RF peak, or frequency differ.'
}
$comsolParticlePath = [IO.Path]::GetFullPath([string]$comsolConfig.inputs.particle_table)
$simionParticlePath = [IO.Path]::GetFullPath([string]$simionConfig.inputs.particle_table)
if ($comsolParticlePath -ne $simionParticlePath) { throw 'COMSOL and SIMION particle tables differ.' }

$resolvedPath = Join-Path $projectRoot 'config\resolved_geometry.json'
$resolved = Get-Content -LiteralPath $resolvedPath -Raw -Encoding UTF8 | ConvertFrom-Json
$particlePath = if ([string]::IsNullOrWhiteSpace($ParticleTablePath)) {
    $comsolParticlePath
} else { [IO.Path]::GetFullPath($ParticleTablePath) }
if ($particlePath -ne $comsolParticlePath) { throw 'Explicit particle table differs from the solver run configs.' }
if ([double]::IsNaN($FrequencyHz) -or [double]::IsInfinity($FrequencyHz)) {
    $FrequencyHz = [double]$comsolConfig.frequency_hz
} elseif ($FrequencyHz -ne [double]$comsolConfig.frequency_hz) {
    throw 'Explicit frequency differs from the solver run configs.'
}
$interfacePath = Join-Path $projectRoot 'config\interface_contract.json'
$entries = @(
    [pscustomobject]@{Solver='COMSOL'; Path=$comsolState},
    [pscustomobject]@{Solver='SIMION'; Path=$simionState}
)
foreach ($entry in $entries) {
    Push-Location $repoRoot
    try {
        & $python -m common.contracts.particle_state `
            --state $entry.Path --particles $particlePath --source-format ion11 --contract $interfacePath `
            --frequency-hz $FrequencyHz --phase-rad $PhaseRad --solver $entry.Solver
        if ($LASTEXITCODE -ne 0) { throw "$($entry.Solver) particle-state contract failed." }
    }
    finally { Pop-Location }
}

New-Item -ItemType Directory -Path $runDir,$resultDir -Force | Out-Null

& $python (Join-Path $projectRoot 'analysis\compare_particle_state.py') `
    --comsol $comsolState --simion $simionState --resolved $resolvedPath `
    --interface-mode (Join-Path $projectRoot 'config\modes\transport_interface_readiness.json') `
    --output $comparison --paired-output $paired
$comparisonExit = $LASTEXITCODE
if ($comparisonExit -ne 0 -and -not (Test-Path -LiteralPath $comparison -PathType Leaf)) {
    throw 'Cross-solver particle-state comparison failed before writing a report.'
}

$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_cross_solver_run_config'; run_id=$RunId
    project='rf_quadrupole_collision_cooling'; mode="${Mode}_phase_space_comparison"
    project_root=$projectRoot; formal_gate_passed=$false
    inputs=[ordered]@{
        comsol_manifest=$comsolManifest; simion_manifest=$simionManifest
        comsol_particle_state=$comsolState; simion_particle_state=$simionState
        particle_table=$particlePath
        resolved_geometry='config/resolved_geometry.json'; interface_contract='config/interface_contract.json'
        mode=$(if ($Mode -eq 'transport_no_collision') { 'config/modes/transport_no_collision.json' } else { 'config/modes/transport_interface_readiness.json' })
    }
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding ASCII
$summaryPath = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_quadrupole_cross_solver_summary';status=$(if ($comparisonExit -eq 0) {'success'} else {'failed'});comparison='results/comparison.json'} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$manifestStatus = if ($comparisonExit -eq 0) { 'success' } else { 'failed' }
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status $manifestStatus --software 'COMSOL 6.4' --software 'SIMION 2020' --output $comparison --output $paired --output $summaryPath
if ($LASTEXITCODE -ne 0) { throw 'Cross-solver manifest generation failed.' }
if ($comparisonExit -ne 0) { throw "Cross-solver comparison completed but did not meet acceptance targets: $comparison" }
"STATUS=PASS RUN_ID=$RunId"
