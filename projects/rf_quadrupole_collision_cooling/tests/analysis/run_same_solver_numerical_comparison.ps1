param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('SIMION','COMSOL')]
    [string]$Solver,
    [Parameter(Mandatory = $true)][string]$BaselineRunId,
    [Parameter(Mandatory = $true)][string]$RefinedRunId,
    [string]$RunId = '',
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
} else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') +
        "__analysis__python__rf-$($Solver.ToLower())-time-convergence"
}
foreach ($candidateRunId in @($BaselineRunId,$RefinedRunId,$RunId)) {
    & $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $candidateRunId
    if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $candidateRunId" }
}
$baselineRun = Join-Path $artifactRoot "runs\$BaselineRunId"
$refinedRun = Join-Path $artifactRoot "runs\$RefinedRunId"
$baselineManifest = Join-Path $baselineRun 'run_manifest.json'
$refinedManifest = Join-Path $refinedRun 'run_manifest.json'
foreach ($manifest in @($baselineManifest,$refinedManifest)) {
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
        $manifest --require-status success --require-project rf_quadrupole_collision_cooling
    if ($LASTEXITCODE -ne 0) { throw "Source success manifest verification failed: $manifest" }
}
$baselineManifestDocument = Get-Content -LiteralPath $baselineManifest -Raw -Encoding UTF8 | ConvertFrom-Json
$refinedManifestDocument = Get-Content -LiteralPath $refinedManifest -Raw -Encoding UTF8 | ConvertFrom-Json
$baselineConfig = Get-Content -LiteralPath $baselineManifestDocument.run_config.path -Raw -Encoding UTF8 | ConvertFrom-Json
$refinedConfig = Get-Content -LiteralPath $refinedManifestDocument.run_config.path -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedRole = if ($Solver -eq 'SIMION') {
    'rf_quadrupole_simion_run_config'
} else {
    'rf_quadrupole_comsol_run_config'
}
if ($baselineConfig.role -ne $expectedRole -or $refinedConfig.role -ne $expectedRole) {
    throw "Source run-config roles do not identify two $Solver runs."
}

$runDir = Join-Path $artifactRoot "runs\$RunId"
$resultDir = Join-Path $runDir 'results'
if (Test-Path -LiteralPath $runDir) { throw "Analysis run already exists: $RunId" }
New-Item -ItemType Directory -Path $runDir,$resultDir -Force | Out-Null
$contract = Join-Path $projectRoot 'config\same_solver_numerical_convergence.json'
$analysis = Join-Path $projectRoot 'analysis\compare_same_solver_numerics.py'
$baselineState = Join-Path $baselineRun 'results\particle_state.csv'
$refinedState = Join-Path $refinedRun 'results\particle_state.csv'
$baselineSummary = Join-Path $baselineRun 'results\solver_summary.json'
$refinedSummary = Join-Path $refinedRun 'results\solver_summary.json'
$baselineParticles = [IO.Path]::GetFullPath([string]$baselineConfig.inputs.particle_table)
$refinedParticles = [IO.Path]::GetFullPath([string]$refinedConfig.inputs.particle_table)
$comparison = Join-Path $resultDir 'same_solver_numerical_convergence.json'
$census = Join-Path $resultDir 'particle_event_census.csv'
$summary = Join-Path $runDir 'summary.json'
$runConfigPath = Join-Path $runDir 'run_config.json'
$inputs = [ordered]@{
    analysis=$analysis
    contract=$contract
    baseline_manifest=$baselineManifest
    refined_manifest=$refinedManifest
    baseline_particle_state=$baselineState
    refined_particle_state=$refinedState
    baseline_particle_table=$baselineParticles
    refined_particle_table=$refinedParticles
    baseline_solver_summary=$baselineSummary
    refined_solver_summary=$refinedSummary
}
if ($Solver -eq 'SIMION') {
    $inputs.baseline_pa_inventory = Join-Path $baselineRun 'simion\SHA256SUMS.csv'
    $inputs.refined_pa_inventory = Join-Path $refinedRun 'simion\SHA256SUMS.csv'
    foreach ($side in @(
        [pscustomobject]@{Name='baseline';Run=$baselineRun;Inventory=$inputs.baseline_pa_inventory},
        [pscustomobject]@{Name='refined';Run=$refinedRun;Inventory=$inputs.refined_pa_inventory}
    )) {
        $paIndex = 0
        Import-Csv -LiteralPath $side.Inventory | Where-Object {
            $_.file -like 'quad_monolithic.pa*'
        } | Sort-Object file | ForEach-Object {
            $inputs["$($side.Name)_pa_core_$paIndex"] = Join-Path $side.Run "simion\$($_.file)"
            $paIndex++
        }
        if ($paIndex -eq 0) { throw "$($side.Name) SIMION PA core inventory is empty." }
    }
}
$runConfig = [ordered]@{
    schema_version=1
    role='rf_quadrupole_same_solver_numerical_convergence_run_config'
    run_id=$RunId
    project='rf_quadrupole_collision_cooling'
    mode='same_solver_numerical_convergence'
    project_root=$projectRoot
    inputs=$inputs
    parameters=[ordered]@{
        solver=$Solver
        baseline_run_id=$BaselineRunId
        refined_run_id=$RefinedRunId
    }
    formal_gate_passed=$false
}
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

Push-Location $repoRoot
try {
    & $python -m projects.rf_quadrupole_collision_cooling.analysis.compare_same_solver_numerics `
        --baseline-manifest $baselineManifest --refined-manifest $refinedManifest `
        --contract $contract --output $comparison --census-output $census
}
finally { Pop-Location }
$analysisExit = $LASTEXITCODE
if ($analysisExit -ne 0 -or
    -not (Test-Path -LiteralPath $comparison -PathType Leaf) -or
    -not (Test-Path -LiteralPath $census -PathType Leaf)) {
    [ordered]@{
        schema_version=1
        role='rf_quadrupole_same_solver_numerical_convergence_summary'
        status='failed'
        execution_status='failed'
        decision_status='NOT_EVALUATED'
        reason="Same-solver numerical comparison execution failed with exit code $analysisExit."
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary -Encoding UTF8
    & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
        --run-config $runConfigPath --status failed --software 'Python 3.11' `
        --output $summary
    if ($LASTEXITCODE -ne 0) { throw 'Failed analysis manifest generation failed.' }
    throw 'Same-solver numerical comparison failed before writing complete evidence.'
}

$report = Get-Content -LiteralPath $comparison -Raw -Encoding UTF8 | ConvertFrom-Json
if ($report.execution_status -ne 'success' -or $report.status -notin @('PASS','FAIL')) {
    [ordered]@{
        schema_version=1
        role='rf_quadrupole_same_solver_numerical_convergence_summary'
        status='failed'
        execution_status='failed'
        decision_status='NOT_EVALUATED'
        reason='Same-solver numerical comparison report status is invalid.'
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary -Encoding UTF8
    & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
        --run-config $runConfigPath --status failed --software 'Python 3.11' `
        --output $comparison --output $census --output $summary
    if ($LASTEXITCODE -ne 0) { throw 'Invalid analysis manifest generation failed.' }
    throw 'Same-solver numerical comparison report status is invalid.'
}
[ordered]@{
    schema_version=1
    role='rf_quadrupole_same_solver_numerical_convergence_summary'
    status='success'
    execution_status='success'
    decision_status=$report.status
    solver=$report.solver
    numerical_parameter=$report.numerical_parameter
    asset_identity=$report.asset_identity
    metrics=$report.metrics
    gates=$report.gates
    comparison='results/same_solver_numerical_convergence.json'
    census='results/particle_event_census.csv'
} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summary -Encoding UTF8
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
    --run-config $runConfigPath --status success --software 'Python 3.11' `
    --output $comparison --output $census --output $summary
if ($LASTEXITCODE -ne 0) { throw 'Analysis run-manifest generation failed.' }
if ($report.status -ne 'PASS') {
    throw "Same-solver numerical comparison completed but failed its decision gates: $comparison"
}
"STATUS=PASS RUN_ID=$RunId SOLVER=$Solver"
