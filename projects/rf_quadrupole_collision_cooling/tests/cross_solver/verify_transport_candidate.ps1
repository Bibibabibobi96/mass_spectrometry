param(
    [Parameter(Mandatory = $true)][string]$ComsolRunLabel,
    [Parameter(Mandatory = $true)][string]$SimionRunLabel,
    [Parameter(Mandatory = $true)][string]$ComparisonLabel
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$runDir = Join-Path $artifactRoot "runs\cross_solver\$ComparisonLabel"
$resultDir = Join-Path $artifactRoot 'results\cross_solver'
if (Test-Path -LiteralPath $runDir) { throw "Cross-solver run already exists: $ComparisonLabel" }
New-Item -ItemType Directory -Path $runDir,$resultDir -Force | Out-Null

$comsolManifest = Join-Path $artifactRoot "runs\transport_no_collision\comsol_$ComsolRunLabel\run_manifest.json"
$simionManifest = Join-Path $artifactRoot "runs\transport_no_collision\simion_$SimionRunLabel\run_manifest.json"
$comsolState = Join-Path $artifactRoot "results\comsol\transport_no_collision_particle_state_$ComsolRunLabel.csv"
$simionState = Join-Path $artifactRoot "results\simion\transport_no_collision_particle_state_$SimionRunLabel.csv"
$comparison = Join-Path $resultDir "transport_no_collision_phase_space_$ComparisonLabel.json"
$paired = Join-Path $resultDir "transport_no_collision_phase_space_paired_$ComparisonLabel.csv"
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $comsolManifest
if ($LASTEXITCODE -ne 0) { throw 'COMSOL run-manifest verification failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $simionManifest
if ($LASTEXITCODE -ne 0) { throw 'SIMION run-manifest verification failed.' }

$resolvedPath = Join-Path $projectRoot 'config\resolved_geometry.json'
$resolved = Get-Content -LiteralPath $resolvedPath -Raw -Encoding UTF8 | ConvertFrom-Json
$particlePath = Join-Path $projectRoot 'config\particles\official_fixed_25.ion'
$interfacePath = Join-Path $projectRoot 'config\interface_contract.json'
$entries = @(
    [pscustomobject]@{Solver='COMSOL'; Path=$comsolState},
    [pscustomobject]@{Solver='SIMION'; Path=$simionState}
)
foreach ($entry in $entries) {
    & $python (Join-Path $projectRoot 'analysis\verify_particle_state_contract.py') `
        --state $entry.Path --particles $particlePath --interface $interfacePath `
        --frequency-hz $resolved.mode.rf.frequency_Hz --phase-rad $resolved.mode.rf.phase_rad --solver $entry.Solver
    if ($LASTEXITCODE -ne 0) { throw "$($entry.Solver) particle-state contract failed." }
}

& $python (Join-Path $projectRoot 'analysis\compare_particle_state.py') `
    --comsol $comsolState --simion $simionState --resolved $resolvedPath `
    --interface-mode (Join-Path $projectRoot 'config\modes\transport_interface_readiness.json') `
    --output $comparison --paired-output $paired
if ($LASTEXITCODE -ne 0) { throw 'Cross-solver particle-state comparison failed.' }

$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_cross_solver_run_config'; run_id=$ComparisonLabel
    project='rf_quadrupole_collision_cooling'; mode='transport_no_collision_phase_space_comparison'
    project_root=$projectRoot; formal_gate_passed=$false
    inputs=[ordered]@{
        comsol_manifest=$comsolManifest; simion_manifest=$simionManifest
        comsol_particle_state=$comsolState; simion_particle_state=$simionState
        resolved_geometry='config/resolved_geometry.json'; interface_contract='config/interface_contract.json'
    }
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding ASCII
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath `
    --status success --software 'COMSOL 6.4' --software 'SIMION 2020' --output $comparison --output $paired
if ($LASTEXITCODE -ne 0) { throw 'Cross-solver manifest generation failed.' }
"STATUS=PASS COMPARISON=$ComparisonLabel"
