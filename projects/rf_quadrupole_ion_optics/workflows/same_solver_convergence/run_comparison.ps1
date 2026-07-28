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
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_ion_optics'
$python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
} else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $projectRoot 'runtime\analysis_run_lifecycle.ps1')
. (Join-Path $projectRoot 'runtime\frozen_python_package.ps1')

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') +
        "__analysis__python__rf-$($Solver.ToLower())-time-convergence"
}
$software = @('Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_quadrupole_ion_optics' `
    -Mode 'same_solver_numerical_convergence' -Software $software
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$runConfigPath = $package.run_config
$summaryPath = $package.summary
$decisionStatus = 'NOT_EVALUATED'

try {
    $baselineRun = Join-Path $artifactRoot "runs\$BaselineRunId"
    $refinedRun = Join-Path $artifactRoot "runs\$RefinedRunId"
    $baselineManifest = Join-Path $baselineRun 'run_manifest.json'
    $refinedManifest = Join-Path $refinedRun 'run_manifest.json'

    $runtimeRoot = Join-Path $inputDir 'runtime'
    $runtimeFiles = @(
        'projects\rf_quadrupole_ion_optics\workflows\__init__.py',
        'projects\rf_quadrupole_ion_optics\workflows\same_solver_convergence\__init__.py',
        'projects\rf_quadrupole_ion_optics\workflows\same_solver_convergence\evaluate.py',
        'projects\rf_quadrupole_ion_optics\analysis\particle_state_comparison_core.py',
        'projects\rf_quadrupole_ion_optics\analysis\validate_paired_particle_source_binding.py',
        'projects\rf_quadrupole_ion_optics\analysis\paired_particle_source_bundle.py',
        'common\contracts\particle_state.py',
        'common\contracts\particle_physics.py',
        'common\contracts\particle_count_policy.py',
        'common\contracts\particle_count_policy.json',
        'common\multipole\__init__.py',
        'common\multipole\particle_source_preflight.py'
    )
    $frozenPythonSupport = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'runtime\frozen_python_package.ps1') `
        -Destination (Join-Path $inputDir 'frozen_python_package.ps1')
    $frozenPythonPackage = New-FrozenPythonPackage `
        -SourceRoot $repoRoot -CodeRoot $runtimeRoot `
        -RelativePaths $runtimeFiles
    $runtimeInputs = [ordered]@{}
    foreach ($entry in $frozenPythonPackage.files) {
        $name = 'runtime_' +
            ([string]$entry.relative_path -replace '[^A-Za-z0-9]+','_').Trim('_')
        $runtimeInputs[$name] = [string]$entry.path
    }
    $frozenContract = Join-Path $inputDir `
        'same_solver_numerical_convergence.json'
    $frozenSimionNumerics = Join-Path $inputDir `
        'simion_solver_numerics.json'
    $frozenComsolNumerics = Join-Path $inputDir `
        'comsol_solver_numerics.json'
    $frozenParticleCountPolicy = Join-Path $inputDir `
        'particle_count_policy.json'
    $frozenAnalysisSupport = Join-Path $inputDir `
        'analysis_run_lifecycle.ps1'
    foreach ($pair in @(
        @(
            (Join-Path $projectRoot `
                'config\same_solver_numerical_convergence.json'),
            $frozenContract
        ),
        @(
            (Join-Path $projectRoot 'config\simion_solver_numerics.json'),
            $frozenSimionNumerics
        ),
        @(
            (Join-Path $projectRoot 'config\comsol_solver_numerics.json'),
            $frozenComsolNumerics
        ),
        @(
            (Join-Path $repoRoot 'common\contracts\particle_count_policy.json'),
            $frozenParticleCountPolicy
        ),
        @(
            (Join-Path $projectRoot `
                'runtime\analysis_run_lifecycle.ps1'),
            $frozenAnalysisSupport
        )
    )) {
        Copy-VerifiedRunInput -Source $pair[0] -Destination $pair[1] |
            Out-Null
    }
    $requiredInputRoles = @(
        'particle_table',
        'consumed_particle_table',
        'source_ion11',
        'source_canonical10',
        'particle_bundle_metadata',
        'particle_source_family',
        'particle_source_distribution',
        'resolved_design',
        'interface_contract'
    )
    if ($Solver -eq 'SIMION') {
        $requiredInputRoles += @('mode','numerical_contract')
    } else {
        $requiredInputRoles += @(
            'scientific_mode',
            'comsol_solver_numerics'
        )
    }
    $baselineSourceManifest = Get-Content -LiteralPath $baselineManifest -Raw `
        -Encoding UTF8 | ConvertFrom-Json
    $refinedSourceManifest = Get-Content -LiteralPath $refinedManifest -Raw `
        -Encoding UTF8 | ConvertFrom-Json
    $baselineRuntimeRoles = @(
        $baselineSourceManifest.inputs.PSObject.Properties.Name |
            Where-Object {
                $_ -match '^frozen_python_code_[0-9]+$' -or
                $_ -eq 'frozen_python_package_support'
            } | Sort-Object
    )
    $refinedRuntimeRoles = @(
        $refinedSourceManifest.inputs.PSObject.Properties.Name |
            Where-Object {
                $_ -match '^frozen_python_code_[0-9]+$' -or
                $_ -eq 'frozen_python_package_support'
            } | Sort-Object
    )
    if (($baselineRuntimeRoles -join "`n") -cne
        ($refinedRuntimeRoles -join "`n")) {
        throw 'Source frozen-Python input role inventories differ.'
    }
    $requiredInputRoles += $baselineRuntimeRoles
    $requiredOutputRoles = [ordered]@{
        particle_state = 'particle_state.csv'
        solver_summary = 'solver_summary.json'
    }
    if ($Solver -eq 'SIMION') {
        $requiredOutputRoles.pa_core_inventory = 'SHA256SUMS.csv'
    }
    $baselineClosure = Copy-PortableRunManifestClosure `
        -SourceManifest $baselineManifest `
        -Destination (Join-Path $inputDir 'baseline_source') `
        -RequiredInputRoles $requiredInputRoles `
        -RequiredOutputRoles $requiredOutputRoles `
        -BundleMetadataInputRole 'particle_bundle_metadata'
    $refinedClosure = Copy-PortableRunManifestClosure `
        -SourceManifest $refinedManifest `
        -Destination (Join-Path $inputDir 'refined_source') `
        -RequiredInputRoles $requiredInputRoles `
        -RequiredOutputRoles $requiredOutputRoles `
        -BundleMetadataInputRole 'particle_bundle_metadata'
    $frozenBaselineManifest = $baselineClosure.manifest
    $frozenRefinedManifest = $refinedClosure.manifest
    foreach ($manifest in @(
        $frozenBaselineManifest,
        $frozenRefinedManifest
    )) {
        & $python (Join-Path $repoRoot `
            'common\contracts\verify_run_manifest.py') `
            $manifest --require-status success `
            --require-project rf_quadrupole_ion_optics
        if ($LASTEXITCODE -ne 0) {
            throw "Portable source closure verification failed: $manifest"
        }
    }
    $baselineConfig = Get-Content -LiteralPath $baselineClosure.config -Raw `
        -Encoding UTF8 | ConvertFrom-Json
    $refinedConfig = Get-Content -LiteralPath $refinedClosure.config -Raw `
        -Encoding UTF8 | ConvertFrom-Json
    $expectedRole = if ($Solver -eq 'SIMION') {
        'rf_quadrupole_simion_run_config'
    } else {
        'rf_quadrupole_comsol_run_config'
    }
    if ($baselineConfig.role -ne $expectedRole -or
        $refinedConfig.role -ne $expectedRole) {
        throw "Source run-config roles do not identify two $Solver runs."
    }
    $inputs = [ordered]@{
        convergence_contract=$frozenContract
        simion_solver_numerics_contract=$frozenSimionNumerics
        comsol_solver_numerics_contract=$frozenComsolNumerics
        particle_count_policy=$frozenParticleCountPolicy
        baseline_manifest=$frozenBaselineManifest
        refined_manifest=$frozenRefinedManifest
        analysis_run_support=$frozenAnalysisSupport
        frozen_python_package_support=$frozenPythonSupport
    }
    foreach ($entry in $runtimeInputs.GetEnumerator()) {
        $inputs[$entry.Key] = $entry.Value
    }
    Add-RunInputClosure -Inputs $inputs -Prefix 'baseline_source' `
        -Files $baselineClosure.files
    Add-RunInputClosure -Inputs $inputs -Prefix 'refined_source' `
        -Files $refinedClosure.files
    $comparison = Join-Path $resultDir `
        'same_solver_numerical_convergence.json'
    $census = Join-Path $resultDir 'particle_event_census.csv'
    $frozenPythonEnvironment = Invoke-IsolatedFrozenPythonModule `
        -Python $python -Package $frozenPythonPackage `
        -Module `
        'projects.rf_quadrupole_ion_optics.workflows.same_solver_convergence.evaluate' `
        -Arguments @() -DistributionNames @('numpy') -RequiredModuleNames @(
            'projects.rf_quadrupole_ion_optics.workflows',
            'projects.rf_quadrupole_ion_optics.workflows.same_solver_convergence',
            'projects.rf_quadrupole_ion_optics.workflows.same_solver_convergence.evaluate',
            'projects.rf_quadrupole_ion_optics.analysis.particle_state_comparison_core',
            'projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding',
            'projects.rf_quadrupole_ion_optics.analysis.paired_particle_source_bundle',
            'common.contracts.particle_state',
            'common.contracts.particle_physics',
            'common.contracts.particle_count_policy',
            'common.multipole',
            'common.multipole.particle_source_preflight'
        ) -ForbiddenRoots @($repoRoot,$projectRoot) -ProbeOnly
    $runConfiguration = [ordered]@{
        schema_version=2
        role='rf_quadrupole_same_solver_numerical_convergence_run_config'
        run_id=$RunId
        project='rf_quadrupole_ion_optics'
        mode='same_solver_numerical_convergence'
        project_root=$projectRoot
        inputs=$inputs
        frozen_python=[ordered]@{
            package=$frozenPythonPackage
            environment=$frozenPythonEnvironment
        }
        parameters=[ordered]@{
            solver=$Solver
            baseline_run_id=$BaselineRunId
            refined_run_id=$RefinedRunId
        }
        formal_gate_passed=$false
    }
    Write-RunJson -Path $runConfigPath -Depth 12 -Value $runConfiguration

    Invoke-IsolatedFrozenPythonModule `
        -Python $python -Package $frozenPythonPackage `
        -Module `
        'projects.rf_quadrupole_ion_optics.workflows.same_solver_convergence.evaluate' `
        -Arguments @(
            '--baseline-manifest',$frozenBaselineManifest,
            '--refined-manifest',$frozenRefinedManifest,
            '--contract',$frozenContract,
            '--comsol-numerics',$frozenComsolNumerics,
            '--simion-numerics',$frozenSimionNumerics,
            '--particle-count-policy',$frozenParticleCountPolicy,
            '--output',$comparison,
            '--census-output',$census
        ) -DistributionNames @('numpy') -RequiredModuleNames @(
            'projects.rf_quadrupole_ion_optics.workflows',
            'projects.rf_quadrupole_ion_optics.workflows.same_solver_convergence',
            'projects.rf_quadrupole_ion_optics.workflows.same_solver_convergence.evaluate',
            'projects.rf_quadrupole_ion_optics.analysis.particle_state_comparison_core',
            'projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding',
            'projects.rf_quadrupole_ion_optics.analysis.paired_particle_source_bundle',
            'common.contracts.particle_state',
            'common.contracts.particle_physics',
            'common.contracts.particle_count_policy',
            'common.multipole',
            'common.multipole.particle_source_preflight'
        ) -ForbiddenRoots @($repoRoot,$projectRoot) | Out-Null
    if (-not (Test-Path -LiteralPath $comparison -PathType Leaf) -or
        -not (Test-Path -LiteralPath $census -PathType Leaf)) {
        throw 'Same-solver comparison execution did not produce required outputs.'
    }
    $report = Get-Content -LiteralPath $comparison -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($report.execution_status -ne 'success' -or
        $report.role -ne `
        'rf_quadrupole_same_solver_numerical_convergence_result' -or
        $report.status -notin @('PASS','FAIL','NOT_EVALUATED')) {
        throw 'Same-solver numerical comparison report identity or status is invalid.'
    }
    $decisionStatus = [string]$report.status
    Write-RunJson -Path $summaryPath -Depth 12 -Value ([ordered]@{
        schema_version=2
        role='rf_quadrupole_same_solver_numerical_convergence_summary'
        status='success'
        execution_status='success'
        decision_status=$decisionStatus
        solver=$report.solver
        numerical_parameter=$report.numerical_parameter
        asset_identity=$report.asset_identity
        metrics=$report.metrics
        gates=$report.gates
        comparison='results/same_solver_numerical_convergence.json'
        census='results/particle_event_census.csv'
    })
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Status success -Software $software `
        -Outputs @($comparison,$census,$summaryPath)
} catch {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Summary $summaryPath `
        -SummaryRole `
        'rf_quadrupole_same_solver_numerical_convergence_summary' `
        -Reason $_.Exception.Message -Software $software
    throw
}
if ($decisionStatus -ne 'PASS') {
    throw "Same-solver numerical comparison completed with decision $decisionStatus."
}
"STATUS=PASS RUN_ID=$RunId SOLVER=$Solver"
