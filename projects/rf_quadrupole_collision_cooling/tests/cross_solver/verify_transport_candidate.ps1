param(
    [Parameter(Mandatory = $true)][string]$ComsolRunLabel,
    [Parameter(Mandatory = $true)][string]$SimionRunLabel,
    [Parameter(Mandatory = $true)][string]$ComparisonLabel,
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
$runDir = Join-Path $artifactRoot "runs\cross_solver\$Mode\$ComparisonLabel"
$resultDir = Join-Path $artifactRoot 'results\cross_solver'
if (Test-Path -LiteralPath $runDir) { throw "Cross-solver run already exists: $ComparisonLabel" }

$comsolManifest = Join-Path $artifactRoot "runs\$Mode\comsol_$ComsolRunLabel\run_manifest.json"
$simionManifest = Join-Path $artifactRoot "runs\$Mode\simion_$SimionRunLabel\run_manifest.json"
$comsolState = Join-Path $artifactRoot "results\comsol\${Mode}_particle_state_$ComsolRunLabel.csv"
$simionState = Join-Path $artifactRoot "results\simion\${Mode}_particle_state_$SimionRunLabel.csv"
$newInputs = @($comsolManifest,$simionManifest,$comsolState,$simionState)
if ($Mode -eq 'transport_interface_readiness' -and @($newInputs | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -gt 0) {
    # Compatibility is read-only: interface runs created before mode isolation
    # retain transport_no_collision paths, but their run-config mode must still
    # pass the explicit identity checks below.  New runs never write here.
    $legacyComsolManifest = Join-Path $artifactRoot "runs\transport_no_collision\comsol_$ComsolRunLabel\run_manifest.json"
    $legacySimionManifest = Join-Path $artifactRoot "runs\transport_no_collision\simion_$SimionRunLabel\run_manifest.json"
    $legacyComsolState = Join-Path $artifactRoot "results\comsol\transport_no_collision_particle_state_$ComsolRunLabel.csv"
    $legacySimionState = Join-Path $artifactRoot "results\simion\transport_no_collision_particle_state_$SimionRunLabel.csv"
    $legacyInputs = @($legacyComsolManifest,$legacySimionManifest,$legacyComsolState,$legacySimionState)
    if (@($legacyInputs | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -eq 0) {
        $comsolManifest,$simionManifest = $legacyComsolManifest,$legacySimionManifest
        $comsolState,$simionState = $legacyComsolState,$legacySimionState
    }
}
$comparison = Join-Path $resultDir "${Mode}_phase_space_$ComparisonLabel.json"
$paired = Join-Path $resultDir "${Mode}_phase_space_paired_$ComparisonLabel.csv"
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
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
    & $python (Join-Path $projectRoot 'analysis\verify_particle_state_contract.py') `
        --state $entry.Path --particles $particlePath --interface $interfacePath `
        --frequency-hz $FrequencyHz --phase-rad $PhaseRad --solver $entry.Solver
    if ($LASTEXITCODE -ne 0) { throw "$($entry.Solver) particle-state contract failed." }
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
    schema_version=1; role='rf_quadrupole_cross_solver_run_config'; run_id=$ComparisonLabel
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
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'COMSOL 6.4' --software 'SIMION 2020' --output $comparison --output $paired
if ($LASTEXITCODE -ne 0) { throw 'Cross-solver manifest generation failed.' }
if ($comparisonExit -ne 0) { throw "Cross-solver comparison completed but did not meet acceptance targets: $comparison" }
"STATUS=PASS COMPARISON=$ComparisonLabel"
