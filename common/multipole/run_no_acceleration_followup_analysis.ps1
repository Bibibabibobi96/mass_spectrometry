param(
    [Parameter(Mandatory)][ValidateSet(
        'rf_quadrupole_ion_optics',
        'rf_hexapole_ion_optics',
        'rf_octupole_ion_optics'
    )][string]$Project,
    [Parameter(Mandatory)][string]$ArmARunId,
    [Parameter(Mandatory)][string]$ArmRRunId,
    [Parameter(Mandatory)][string]$ArmZRunId,
    [Parameter(Mandatory)][string]$ArmIRunId,
    [Parameter(Mandatory)][string]$ArmTRunId,
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
    -Mode 'simion_no_acceleration_anisotropic_followup_analysis' `
    -Software $software -RetentionContractEnabled
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$runConfigPath = $package.run_config
$summaryPath = $package.summary

try {
    $armRunIds = [ordered]@{
        A = $ArmARunId
        R = $ArmRRunId
        Z = $ArmZRunId
        I = $ArmIRunId
        T = $ArmTRunId
    }
    $inputs = [ordered]@{}
    $frozenManifests = [ordered]@{}
    $frozenStates = [ordered]@{}
    foreach ($arm in $armRunIds.Keys) {
        $sourceRun = Join-Path $artifactRoot "runs\$($armRunIds[$arm])"
        $sourceManifest = Join-Path $sourceRun 'run_manifest.json'
        & $python (Join-Path $repoRoot `
            'common\contracts\verify_run_manifest.py') $sourceManifest `
            --require-status success --require-project $Project
        if ($LASTEXITCODE -ne 0) {
            throw "Source run manifest failed verification for arm $arm."
        }
        $manifestDocument = Get-Content -LiteralPath $sourceManifest -Raw `
            -Encoding UTF8 | ConvertFrom-Json
        $stateMatches = @(
            $manifestDocument.outputs | Where-Object {
                (Split-Path -Leaf ([string]$_.path)) -eq `
                    'particle_states__rf_on.csv'
            }
        )
        if ($stateMatches.Count -ne 1) {
            throw "Arm $arm must contain exactly one RF-on canonical state table."
        }
        $frozenManifest = Join-Path $inputDir "${arm}_run_manifest.json"
        $frozenState = Join-Path $inputDir "${arm}_particle_states__rf_on.csv"
        Copy-VerifiedRunInput -Source $sourceManifest `
            -Destination $frozenManifest | Out-Null
        Copy-VerifiedRunInput -Source ([string]$stateMatches[0].path) `
            -Destination $frozenState | Out-Null
        $frozenManifests[$arm] = $frozenManifest
        $frozenStates[$arm] = $frozenState
        $inputs["arm_${arm}_run_manifest"] = $frozenManifest
        $inputs["arm_${arm}_particle_state"] = $frozenState
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
        mode = 'simion_no_acceleration_anisotropic_followup_analysis'
        project_root = $repoRoot
        inputs = $inputs
        parameters = [ordered]@{
            arm_run_ids = $armRunIds
            factorial_definition = 'I - R - Z + A'
            histogram_bin_count = 24
            diagnostic_dpi = 200
            claim_scope = 'direction_sensitivity_only'
        }
        artifact_retention = [ordered]@{
            policy_version = 1
            class = 'compact'
            reason = $null
        }
        formal_gate_passed = $false
    }
    Write-RunJson -Path $runConfigPath -Depth 12 -Value $runConfiguration

    $analysis = Join-Path $resultDir 'simion_anisotropic_factorial.json'
    $figure = Join-Path $resultDir 'simion_exit_state_factorial.png'
    $figureManifest = Join-Path $resultDir `
        'simion_exit_state_factorial.figure.json'
    $savedPythonPath = $env:PYTHONPATH
    $savedNoUserSite = $env:PYTHONNOUSERSITE
    try {
        $env:PYTHONPATH = $codeRoot
        $env:PYTHONNOUSERSITE = '1'
        Push-Location -LiteralPath $codeRoot
        try {
            & $python -m common.multipole.followup_analysis `
                --resolution $resolution --output $analysis factorial `
                --a $frozenManifests.A --r $frozenManifests.R `
                --z $frozenManifests.Z --i $frozenManifests.I `
                --t $frozenManifests.T
            if ($LASTEXITCODE -ne 0) {
                throw 'Factorial follow-up analysis failed.'
            }
            $plotArguments = @(
                '-m', 'common.multipole.exit_state_plot'
            )
            foreach ($arm in $armRunIds.Keys) {
                $plotArguments += @(
                    '--series',
                    "$arm=$($frozenStates[$arm])=$($armRunIds[$arm])"
                )
            }
            $plotArguments += @(
                '--output', $figure,
                '--manifest', $figureManifest,
                '--title', "$Project SIMION no-acceleration A/R/Z/I/T",
                '--purpose',
                'Shared-scale directional and temporal discretization diagnostic.',
                '--bin-count', '24',
                '--dpi', '200',
                '--repo-root', $repoRoot
            )
            & $python @plotArguments
            if ($LASTEXITCODE -ne 0) {
                throw 'Factorial exit-state plot failed.'
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
        role = 'multipole_simion_no_acceleration_followup_analysis_summary'
        status = 'success'
        decision_status = $analysisDocument.status
        project_id = $Project
        arm_run_ids = $armRunIds
        scientific_claim = $analysisDocument.scientific_claim
        analysis = 'results/simion_anisotropic_factorial.json'
        figure = 'results/simion_exit_state_factorial.png'
        figure_manifest = `
            'results/simion_exit_state_factorial.figure.json'
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
        'multipole_simion_no_acceleration_followup_analysis_summary' `
        -Reason $_.Exception.Message -Software $software
    throw
}
"FOLLOWUP_ANALYSIS=PASS PROJECT=$Project RUN_ID=$RunId"
