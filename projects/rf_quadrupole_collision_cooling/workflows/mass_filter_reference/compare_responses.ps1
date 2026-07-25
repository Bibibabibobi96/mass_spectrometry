param(
    [Parameter(Mandatory = $true)][string]$ComsolRunId,
    [Parameter(Mandatory = $true)][string]$SimionRunId,
    [Parameter(Mandatory = $true)][string]$L1RunId,
    [string]$RunId = '',
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot `
    'artifacts\projects\rf_quadrupole_collision_cooling'
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
        '__analysis__python__rf-mass-filter-response-comparison'
}
$software = @('Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_quadrupole_collision_cooling' `
    -Mode 'mass_filter_reference' -Software $software
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$runConfigPath = $package.run_config
$summaryPath = $package.summary

try {
    $sourceManifests = [ordered]@{
        COMSOL = Join-Path $artifactRoot "runs\$ComsolRunId\run_manifest.json"
        SIMION = Join-Path $artifactRoot "runs\$SimionRunId\run_manifest.json"
        L1 = Join-Path $artifactRoot "runs\$L1RunId\run_manifest.json"
    }
    $comsolClosure = Copy-PortableRunManifestClosure `
        -SourceManifest $sourceManifests.COMSOL `
        -Destination (Join-Path $inputDir 'comsol_source') `
        -RequiredInputRoles @(
            'baseline',
            'mode',
            'resolved_design',
            'interface_contract',
            'comsol_solver_numerics',
            'source_ion11',
            'particle_cases',
            'scan_execution'
        ) `
        -RequiredOutputRoles ([ordered]@{
            response = 'mass-response__comsol.csv'
            metrics = 'mass-filter__comsol-functional-metrics.json'
            summary = 'summary.json'
        })
    $simionClosure = Copy-PortableRunManifestClosure `
        -SourceManifest $sourceManifests.SIMION `
        -Destination (Join-Path $inputDir 'simion_source') `
        -RequiredInputRoles @(
            'baseline',
            'resolved_design',
            'interface_contract',
            'mode',
            'numerical_contract',
            'source_ion11',
            'mass_scan_ion11',
            'mass_scan_metadata'
        ) `
        -RequiredOutputRoles ([ordered]@{
            response = 'mass-response__simion.csv'
            metrics = 'mass-filter__simion-functional-metrics.json'
            summary = 'summary.json'
        })
    $l1Closure = Copy-PortableRunManifestClosure `
        -SourceManifest $sourceManifests.L1 `
        -Destination (Join-Path $inputDir 'l1_source') `
        -RequiredInputRoles @(
            'baseline',
            'resolved_design',
            'mode',
            'source',
            'runner',
            'l0_reference'
        ) `
        -RequiredOutputRoles ([ordered]@{
            response = 'mass-response__finite-length.csv'
            metrics = 'mass-filter__functional-metrics.json'
            summary = 'summary.json'
        })
    $closures = [ordered]@{
        COMSOL = $comsolClosure
        SIMION = $simionClosure
        L1 = $l1Closure
    }
    foreach ($closure in $closures.Values) {
        & $python (Join-Path $repoRoot `
            'common\contracts\verify_run_manifest.py') `
            $closure.manifest --require-status success `
            --require-project rf_quadrupole_collision_cooling
        if ($LASTEXITCODE -ne 0) {
            throw "Portable mass-response source closure failed: $($closure.manifest)"
        }
    }
    $sourceConfigs = [ordered]@{}
    foreach ($entry in $closures.GetEnumerator()) {
        $sourceConfigs[$entry.Key] = Get-Content `
            -LiteralPath $entry.Value.config -Raw -Encoding UTF8 |
            ConvertFrom-Json
    }
    if (
        $sourceConfigs.COMSOL.role -ne
        'rf_quadrupole_comsol_mass_filter_run_config' -or
        $sourceConfigs.SIMION.role -ne
        'rf_quadrupole_simion_mass_filter_run_config' -or
        $sourceConfigs.L1.role -ne
        'rf_quadrupole_mass_filter_l1_run_config' -or
        $sourceConfigs.COMSOL.mode -ne 'mass_filter_reference' -or
        $sourceConfigs.SIMION.mode -ne 'mass_filter_reference' -or
        $sourceConfigs.L1.mode -ne 'mass_filter_reference'
    ) {
        throw 'Mass-response source run identities differ.'
    }
    $l1Summary = Get-Content -LiteralPath `
        $l1Closure.output_roles.summary -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if (
        $l1Summary.role -ne 'quadrupole_mass_filter_l1_run_summary' -or
        $l1Summary.status -ne 'success'
    ) {
        throw 'L1 source summary identity or status differs.'
    }
    foreach ($identity in @(
        [ordered]@{
            name = 'baseline'
            paths = @(
                $sourceConfigs.COMSOL.inputs.baseline,
                $sourceConfigs.SIMION.inputs.baseline,
                $sourceConfigs.L1.inputs.baseline
            )
        },
        [ordered]@{
            name = 'mode'
            paths = @(
                $sourceConfigs.COMSOL.inputs.mode,
                $sourceConfigs.SIMION.inputs.mode,
                $sourceConfigs.L1.inputs.mode
            )
        },
        [ordered]@{
            name = 'resolved design'
            paths = @(
                $sourceConfigs.COMSOL.inputs.resolved_design,
                $sourceConfigs.SIMION.inputs.resolved_design,
                $sourceConfigs.L1.inputs.resolved_design
            )
        },
        [ordered]@{
            name = 'solver source ION11'
            paths = @(
                $sourceConfigs.COMSOL.inputs.source_ion11,
                $sourceConfigs.SIMION.inputs.source_ion11
            )
        }
    )) {
        $hashes = @(
            $identity.paths |
                ForEach-Object { Get-RunFileSha256 -Path $_ } |
                Sort-Object -Unique
        )
        if ($hashes.Count -ne 1) {
            throw "Mass-response source $($identity.name) identities differ."
        }
    }
    $comsolSourceParticles = @(
        Get-Content -LiteralPath `
            $sourceConfigs.COMSOL.inputs.source_ion11 -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count
    $simionSourceParticles = @(
        Get-Content -LiteralPath `
            $sourceConfigs.SIMION.inputs.source_ion11 -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count
    if (
        $comsolSourceParticles -le 0 -or
        $simionSourceParticles -le 0 -or
        $comsolSourceParticles -ne $simionSourceParticles
    ) {
        throw 'COMSOL and SIMION portable source ION11 row counts differ.'
    }

    $frozenAnalysisSupport = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot `
            'runtime\analysis_run_lifecycle.ps1') `
        -Destination (Join-Path $inputDir 'analysis_run_lifecycle.ps1')
    $frozenPythonSupport = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'runtime\frozen_python_package.ps1') `
        -Destination (Join-Path $inputDir 'frozen_python_package.ps1')
    $runtimeRoot = Join-Path $inputDir 'runtime'
    $runtimeFiles = @(
        'projects\rf_quadrupole_collision_cooling\workflows\__init__.py',
        'projects\rf_quadrupole_collision_cooling\workflows\mass_filter_reference\__init__.py',
        'projects\rf_quadrupole_collision_cooling\workflows\mass_filter_reference\evaluate_comparison.py',
        'projects\rf_quadrupole_collision_cooling\workflows\mass_filter_reference\theory.py',
        'common\multipole\__init__.py',
        'common\multipole\family_contract.py',
        'common\multipole\family_contract.json'
    )
    $frozenPythonPackage = New-FrozenPythonPackage `
        -SourceRoot $repoRoot -CodeRoot $runtimeRoot `
        -RelativePaths $runtimeFiles
    $inputs = [ordered]@{
        analysis_run_support = $frozenAnalysisSupport
        frozen_python_package_support = $frozenPythonSupport
        comsol_manifest = $comsolClosure.manifest
        simion_manifest = $simionClosure.manifest
        l1_manifest = $l1Closure.manifest
    }
    foreach ($entry in $frozenPythonPackage.files) {
        $name = 'runtime_' +
            ([string]$entry.relative_path -replace '[^A-Za-z0-9]+','_').Trim('_')
        $inputs[$name] = [string]$entry.path
    }
    foreach ($entry in $closures.GetEnumerator()) {
        Add-RunInputClosure -Inputs $inputs `
            -Prefix "$($entry.Key.ToLower())_source" `
            -Files $entry.Value.files
    }
    $module = 'projects.rf_quadrupole_collision_cooling.workflows.' +
        'mass_filter_reference.evaluate_comparison'
    $requiredModules = @(
        'projects.rf_quadrupole_collision_cooling.workflows',
        'projects.rf_quadrupole_collision_cooling.workflows.mass_filter_reference',
        $module,
        'projects.rf_quadrupole_collision_cooling.workflows.mass_filter_reference.theory',
        'common.multipole',
        'common.multipole.family_contract'
    )
    $distributions = @('matplotlib','numpy','scipy')
    $frozenPythonEnvironment = Invoke-IsolatedFrozenPythonModule `
        -Python $python -Package $frozenPythonPackage -Module $module `
        -Arguments @() -DistributionNames $distributions `
        -RequiredModuleNames $requiredModules `
        -ForbiddenRoots @($repoRoot,$projectRoot) -ProbeOnly
    $runConfiguration = [ordered]@{
        schema_version = 1
        role = 'rf_quadrupole_mass_filter_response_comparison_run_config'
        run_id = $RunId
        project = 'rf_quadrupole_collision_cooling'
        mode = 'mass_filter_reference'
        project_root = $projectRoot
        inputs = $inputs
        frozen_python = [ordered]@{
            package = $frozenPythonPackage
            environment = $frozenPythonEnvironment
        }
        parameters = [ordered]@{
            comsol_run_id = $ComsolRunId
            simion_run_id = $SimionRunId
            l1_run_id = $L1RunId
            comsol_source_particles = $comsolSourceParticles
            simion_source_particles = $simionSourceParticles
        }
        formal_gate_passed = $false
    }
    Write-RunJson -Path $runConfigPath -Depth 12 -Value $runConfiguration

    $comparison = Join-Path $resultDir `
        'mass-response__l0-l1-simion-comsol.csv'
    $metrics = Join-Path $resultDir `
        'mass-response__comparison-metrics.json'
    $figure = Join-Path $resultDir `
        'mass-response__l0-l1-simion-comsol.png'
    Invoke-IsolatedFrozenPythonModule `
        -Python $python -Package $frozenPythonPackage -Module $module `
        -Arguments @(
            '--comsol-response',$comsolClosure.output_roles.response,
            '--simion-response',$simionClosure.output_roles.response,
            '--l1-response',$l1Closure.output_roles.response,
            '--comsol-metrics',$comsolClosure.output_roles.metrics,
            '--simion-metrics',$simionClosure.output_roles.metrics,
            '--l1-metrics',$l1Closure.output_roles.metrics,
            '--comsol-source-particles',$comsolSourceParticles,
            '--simion-source-particles',$simionSourceParticles,
            '--baseline',$sourceConfigs.COMSOL.inputs.baseline,
            '--mode',$sourceConfigs.COMSOL.inputs.mode,
            '--output',$comparison,
            '--metrics',$metrics,
            '--figure',$figure
        ) -DistributionNames $distributions `
        -RequiredModuleNames $requiredModules `
        -ForbiddenRoots @($repoRoot,$projectRoot) | Out-Null
    foreach ($path in @($comparison,$metrics,$figure)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Mass-response comparison output is missing: $path"
        }
    }
    $report = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if (
        $report.role -ne
        'rf_quadrupole_mass_filter_response_comparison' -or
        $report.status -ne 'success' -or
        $report.decision_status -notin @('PASS','FAIL','NOT_EVALUATED')
    ) {
        throw 'Mass-response comparison report identity or status differs.'
    }
    Write-RunJson -Path $summaryPath -Depth 8 -Value ([ordered]@{
        schema_version = 1
        role = 'rf_quadrupole_mass_filter_response_comparison_summary'
        status = 'success'
        decision_status = [string]$report.decision_status
        mode = 'mass_filter_reference'
        comparison = 'results/mass-response__l0-l1-simion-comsol.csv'
        metrics = 'results/mass-response__comparison-metrics.json'
        figure = 'results/mass-response__l0-l1-simion-comsol.png'
        claim_limit = [string]$report.claim_limit
    })
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Status success -Software $software `
        -Outputs @($comparison,$metrics,$figure,$summaryPath)
    "STATUS=PASS RUN_ID=$RunId DECISION=$($report.decision_status)"
} catch {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Summary $summaryPath `
        -SummaryRole `
        'rf_quadrupole_mass_filter_response_comparison_summary' `
        -Reason $_.Exception.Message -Software $software
    throw
}
