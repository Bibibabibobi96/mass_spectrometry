param(
    [Parameter(Mandatory)][ValidateSet(
        'rf_quadrupole_ion_optics',
        'rf_hexapole_ion_optics',
        'rf_octupole_ion_optics'
    )][string]$Project,
    [Parameter(Mandatory)][string]$LeftRunId,
    [Parameter(Mandatory)][string]$RightRunId,
    [Parameter(Mandatory)][string]$ComparisonId,
    [Parameter(Mandatory)][string]$RunId,
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$Project"
$python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
} else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$software = @('Python 3.11')
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -RunId $RunId -Project $Project `
    -Mode 'comsol_no_acceleration_temporal_pair_analysis' `
    -Software $software -RetentionContractEnabled
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$runConfigPath = $package.run_config
$summaryPath = $package.summary

try {
    $runIds = [ordered]@{
        left = $LeftRunId
        right = $RightRunId
    }
    $inputs = [ordered]@{}
    $frozenManifests = [ordered]@{}
    $frozenStates = [ordered]@{}
    foreach ($side in $runIds.Keys) {
        $sourceRun = Join-Path $artifactRoot "runs\$($runIds[$side])"
        $sourceManifest = Join-Path $sourceRun 'run_manifest.json'
        & $python (Join-Path $repoRoot `
            'common\contracts\verify_run_manifest.py') $sourceManifest `
            --require-status success --require-project $Project
        if ($LASTEXITCODE -ne 0) {
            throw "Source run manifest failed verification for $side."
        }
        $manifestDocument = Get-Content -LiteralPath $sourceManifest -Raw `
            -Encoding UTF8 | ConvertFrom-Json
        $stateMatches = @(
            $manifestDocument.outputs | Where-Object {
                (Split-Path -Leaf ([string]$_.path)) -eq `
                    'particle_state__primary.csv'
            }
        )
        if ($stateMatches.Count -ne 1) {
            throw "$side must contain exactly one COMSOL primary state table."
        }
        $frozenManifest = Join-Path $inputDir "${side}_run_manifest.json"
        $frozenState = Join-Path $inputDir "${side}_particle_state__primary.csv"
        Copy-VerifiedRunInput -Source $sourceManifest `
            -Destination $frozenManifest | Out-Null
        Copy-VerifiedRunInput -Source ([string]$stateMatches[0].path) `
            -Destination $frozenState | Out-Null
        $frozenManifests[$side] = $frozenManifest
        $frozenStates[$side] = $frozenState
        $inputs["${side}_run_manifest"] = $frozenManifest
        $inputs["${side}_particle_state"] = $frozenState
    }

    $resolution = Copy-VerifiedRunInput `
        -Source (Join-Path $PSScriptRoot `
            'no_acceleration_followup_resolution.json') `
        -Destination (Join-Path $inputDir `
            'no_acceleration_followup_resolution.json')
    $inputs.effect_resolution = $resolution
    $codeRoot = Join-Path $inputDir 'code'
    $codeFiles = @(
        'common\multipole\__init__.py',
        'common\multipole\followup_analysis.py',
        'common\multipole\exit_state_plot.py',
        'common\multipole\numerical_qualification.py',
        'common\contracts\particle_physics.py'
    )
    foreach ($relative in $codeFiles) {
        $source = Join-Path $repoRoot $relative
        $target = Join-Path $codeRoot $relative
        Copy-VerifiedRunInput -Source $source -Destination $target | Out-Null
        $role = 'frozen_code_' +
            (($relative -replace '[^A-Za-z0-9]+', '_').Trim('_'))
        $inputs[$role] = $target
    }

    $runConfiguration = [ordered]@{
        schema_version = 2
        run_id = $RunId
        project = $Project
        mode = 'comsol_no_acceleration_temporal_pair_analysis'
        project_root = $repoRoot
        inputs = $inputs
        parameters = [ordered]@{
            run_ids = $runIds
            comparison_id = $ComparisonId
            histogram_bin_count = 24
            diagnostic_dpi = 200
            claim_scope = 'fixed_bin_engineering_sensitivity_only'
        }
        artifact_retention = [ordered]@{
            policy_version = 1
            class = 'compact'
            reason = $null
        }
        formal_gate_passed = $false
    }
    Write-RunJson -Path $runConfigPath -Depth 12 -Value $runConfiguration

    $analysis = Join-Path $resultDir 'comsol_temporal_pair.json'
    $figure = Join-Path $resultDir 'comsol_exit_state_pair.png'
    $figureManifest = Join-Path $resultDir 'comsol_exit_state_pair.figure.json'
    $savedPythonPath = $env:PYTHONPATH
    $savedNoUserSite = $env:PYTHONNOUSERSITE
    try {
        $env:PYTHONPATH = $codeRoot
        $env:PYTHONNOUSERSITE = '1'
        Push-Location -LiteralPath $codeRoot
        try {
            & $python -m common.multipole.followup_analysis `
                --resolution $resolution --output $analysis pair `
                --left $frozenManifests.left `
                --right $frozenManifests.right `
                --comparison-id $ComparisonId
            if ($LASTEXITCODE -ne 0) {
                throw 'COMSOL temporal pair analysis failed.'
            }
            & $python -m common.multipole.exit_state_plot `
                --series `
                "left=$($frozenStates.left)=$($runIds.left)" `
                --series `
                "right=$($frozenStates.right)=$($runIds.right)" `
                --output $figure --manifest $figureManifest `
                --title "$Project COMSOL no-acceleration temporal pair" `
                --purpose `
                'Shared-scale fixed-bin temporal discretization diagnostic.' `
                --bin-count 24 --dpi 200 --repo-root $repoRoot
            if ($LASTEXITCODE -ne 0) {
                throw 'COMSOL temporal pair plot failed.'
            }
        } finally {
            Pop-Location
        }
    } finally {
        $env:PYTHONPATH = $savedPythonPath
        $env:PYTHONNOUSERSITE = $savedNoUserSite
    }
    foreach ($path in @($analysis, $figure, $figureManifest)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required analysis output is missing: $path"
        }
    }
    $analysisDocument = Get-Content -LiteralPath $analysis -Raw `
        -Encoding UTF8 | ConvertFrom-Json
    Write-RunJson -Path $summaryPath -Depth 12 -Value ([ordered]@{
        schema_version = 2
        role = 'multipole_comsol_no_acceleration_pair_analysis_summary'
        status = 'success'
        decision_status = $analysisDocument.status
        project_id = $Project
        run_ids = $runIds
        comparison_id = $ComparisonId
        scientific_claim = $analysisDocument.scientific_claim
        analysis = 'results/comsol_temporal_pair.json'
        figure = 'results/comsol_exit_state_pair.png'
        figure_manifest = 'results/comsol_exit_state_pair.figure.json'
    })
    $retentionActions = Apply-RunArtifactRetention -Python $python `
        -RepoRoot $repoRoot -RunConfig $runConfigPath
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Status success -Software $software `
        -Outputs @(
            $analysis,
            $figure,
            $figureManifest,
            $summaryPath,
            $retentionActions
        )
} catch {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Summary $summaryPath `
        -SummaryRole `
        'multipole_comsol_no_acceleration_pair_analysis_summary' `
        -Reason $_.Exception.Message -Software $software
    throw
}
"FOLLOWUP_PAIR_ANALYSIS=PASS PROJECT=$Project RUN_ID=$RunId"
