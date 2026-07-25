param(
    [Parameter(Mandatory = $true)][string]$ComsolRunId,
    [Parameter(Mandatory = $true)][string]$SimionRunId,
    [string]$RunId = '',
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
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $projectRoot 'runtime\particle_table_identity.ps1')
. (Join-Path $projectRoot `
    'runtime\cross_solver_analysis_lifecycle.ps1')
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') +
        '__analysis__cross__rf-transport__interface-readiness'
}
$software = @('COMSOL 6.4','SIMION 2020','Python 3.11')
$package = New-CrossSolverAnalysisPackage -Python $python `
    -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
    -PackageMode 'transport_interface_readiness_cross_solver_comparison' `
    -Software $software
$runDir,$inputDir,$resultDir=$package.run_dir,$package.input_dir,$package.result_dir
$runConfigPath,$summaryPath=$package.run_config,$package.summary
$decisionStatus = 'NOT_EVALUATED'

try {
    $source = Get-CrossSolverSourcePair -Python $python `
        -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
        -ComsolRunId $ComsolRunId -SimionRunId $SimionRunId
    $comsolRun,$simionRun = $source.comsol.run,$source.simion.run
    $comsolManifest,$simionManifest = `
        $source.comsol.manifest,$source.simion.manifest
    $comsolConfigPath,$simionConfigPath = `
        $source.comsol.config_path,$source.simion.config_path
    $comsolConfig,$simionConfig = `
        $source.comsol.config,$source.simion.config
    if ($comsolConfig.role -ne 'rf_quadrupole_comsol_run_config' -or
        $simionConfig.role -ne 'rf_quadrupole_simion_run_config' -or
        $comsolConfig.mode -ne 'transport_interface_readiness' -or
        $simionConfig.mode -ne 'transport_interface_readiness') {
        throw 'Interface comparison accepts only interface transport run configs.'
    }
    if ($comsolConfig.operating_point -ne $simionConfig.operating_point -or
        [double]$comsolConfig.rf_peak_v -ne [double]$simionConfig.rf_peak_v -or
        [double]$comsolConfig.frequency_hz -ne [double]$simionConfig.frequency_hz) {
        throw 'COMSOL and SIMION operating point, RF peak, or frequency differ.'
    }

    $comsolBinding = Join-Path $inputDir 'comsol_particle_source_binding.json'
    $simionBinding = Join-Path $inputDir 'simion_particle_source_binding.json'
    $particleIdentity = Assert-RfTransportParticleTableIdentity `
        -Python $python -RepoRoot $repoRoot `
        -ComsolRunConfig $comsolConfig -SimionRunConfig $simionConfig `
        -ComsolBindingOutput $comsolBinding `
        -SimionBindingOutput $simionBinding `
        -ExplicitIon11Path $ParticleTablePath
    if ([double]::IsNaN($FrequencyHz) -or [double]::IsInfinity($FrequencyHz)) {
        $FrequencyHz = [double]$comsolConfig.frequency_hz
    } elseif ($FrequencyHz -ne [double]$comsolConfig.frequency_hz) {
        throw 'Explicit frequency differs from the solver run configs.'
    }

    $frozen = New-CrossSolverFrozenPathSet -InputDir $inputDir `
        -AnalyzerRelativePath `
        'projects\rf_quadrupole_collision_cooling\workflows\interface_readiness\evaluate.py' `
        -ModeFilename 'interface_mode.json'
    $frozenAnalyzer,$frozenCore,$frozenMode=$frozen.analyzer,$frozen.core,$frozen.mode
    $frozenComsolManifest,$frozenSimionManifest=$frozen.comsol_manifest,$frozen.simion_manifest
    $frozenComsolConfig,$frozenSimionConfig=$frozen.comsol_config,$frozen.simion_config
    $frozenComsolState,$frozenSimionState=$frozen.comsol_state,$frozen.simion_state
    $frozenLifecycleSupport = $frozen.support
    $frozenWorkflowInit = Join-Path $frozen.module_root `
        'projects\rf_quadrupole_collision_cooling\workflows\__init__.py'
    $frozenPackageInit = Join-Path $frozen.module_root `
        'projects\rf_quadrupole_collision_cooling\workflows\interface_readiness\__init__.py'
    $frozenInterface = Join-Path $inputDir 'interface_contract.json'
    $frozenIon11 = Join-Path $inputDir 'particles.ion'
    $frozenCanonical = Join-Path $inputDir 'particles.csv'
    $freezePairs = @(
        @((Join-Path $PSScriptRoot 'evaluate.py'),$frozenAnalyzer),
        @((Join-Path $projectRoot 'analysis\particle_state_comparison_core.py'),$frozenCore),
        @((Join-Path $projectRoot 'workflows\__init__.py'),$frozenWorkflowInit),
        @((Join-Path $PSScriptRoot '__init__.py'),$frozenPackageInit),
        @((Join-Path $projectRoot 'config\modes\transport_interface_readiness.json'),$frozenMode),
        @((Join-Path $projectRoot 'config\interface_contract.json'),$frozenInterface),
        @($comsolManifest,$frozenComsolManifest),
        @($simionManifest,$frozenSimionManifest),
        @($comsolConfigPath,$frozenComsolConfig),
        @($simionConfigPath,$frozenSimionConfig),
        @((Join-Path $comsolRun 'results\particle_state.csv'),$frozenComsolState),
        @((Join-Path $simionRun 'results\particle_state.csv'),$frozenSimionState),
        @($particleIdentity.ion11_path,$frozenIon11),
        @($particleIdentity.canonical10_path,$frozenCanonical),
        @((Join-Path $projectRoot 'runtime\cross_solver_analysis_lifecycle.ps1'),$frozenLifecycleSupport)
    )
    Copy-CrossSolverAnalysisInputs -Pairs $freezePairs
    foreach($entry in @([pscustomobject]@{Solver='COMSOL';State=$frozenComsolState;Particles=$frozenIon11;Format='ion11'},
        [pscustomobject]@{Solver='SIMION';State=$frozenSimionState;Particles=$frozenCanonical;Format='canonical'})){
        Push-Location $repoRoot
        try {
            & $python -m common.contracts.particle_state `
                --state $entry.State --particles $entry.Particles `
                --source-format $entry.Format --contract $frozenInterface `
                --frequency-hz $FrequencyHz --phase-rad $PhaseRad `
                --solver $entry.Solver
            if($LASTEXITCODE-ne 0){throw "$($entry.Solver) particle-state contract failed."}
        } finally {
            Pop-Location
        }
    }

    $comparison = Join-Path $resultDir 'interface_readiness_cross_solver.json'
    $census = Join-Path $resultDir 'interface_particle_event_census.csv'
    $inputs=[ordered]@{analyzer=$frozenAnalyzer;comparison_core=$frozenCore;mode_contract=$frozenMode
        interface_contract=$frozenInterface;comsol_manifest=$frozenComsolManifest
        simion_manifest=$frozenSimionManifest;comsol_run_config=$frozenComsolConfig
        simion_run_config=$frozenSimionConfig;comsol_particle_state=$frozenComsolState
        simion_particle_state=$frozenSimionState;particle_table_ion11=$frozenIon11
        particle_table_canonical10=$frozenCanonical;comsol_particle_source_binding=$comsolBinding
        simion_particle_source_binding=$simionBinding;analysis_lifecycle_support=$frozenLifecycleSupport}
    Write-RunJson -Path $runConfigPath -Depth 8 -Value ([ordered]@{
        schema_version=2
        role='rf_quadrupole_interface_readiness_cross_solver_run_config'
        run_id=$RunId
        project='rf_quadrupole_collision_cooling'
        mode='transport_interface_readiness_cross_solver_comparison'
        project_root=$projectRoot
        inputs=$inputs
        parameters=[ordered]@{comsol_source_run_id=$ComsolRunId;simion_source_run_id=$SimionRunId
            operating_point=$comsolConfig.operating_point;particle_count=$particleIdentity.particle_count}
        provenance=[ordered]@{source_sample_family_sha256=$particleIdentity.source_sample_family_sha256
            latent_sha256=$particleIdentity.latent_sha256;coordinate_mapping_version=$particleIdentity.coordinate_mapping_version
            ion11_sha256=$particleIdentity.ion11_sha256;canonical10_sha256=$particleIdentity.canonical10_sha256}
        formal_gate_passed=$false
    })

    $stdout = Join-Path $package.log_dir 'analysis_stdout.txt'
    $stderr = Join-Path $package.log_dir 'analysis_stderr.txt'
    $arguments=@('--comsol',$frozenComsolState,'--simion',$frozenSimionState,
        '--mode-contract',$frozenMode,'--particles',$frozenIon11,
        '--particle-count',[string]$particleIdentity.particle_count,
        '--output',$comparison,'--census-output',$census)
    Invoke-CrossSolverAnalyzer -Python $python `
        -AnalyzerModule `
        'projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.evaluate' `
        -ModuleRoot $frozen.module_root `
        -Arguments $arguments -Stdout $stdout -Stderr $stderr `
        -RequiredOutputs @($comparison,$census)
    $report = Get-Content -LiteralPath $comparison -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($report.execution_status -ne 'success' -or
        $report.role -ne `
        'rf_quadrupole_interface_readiness_cross_solver_result' -or
        $report.status -notin @('PASS','FAIL','NOT_EVALUATED')) {
        throw 'Interface comparison result identity or status is invalid.'
    }
    $decisionStatus = [string]$report.status
    $summary=[ordered]@{schema_version=2;role='rf_quadrupole_interface_readiness_cross_solver_summary'
        status='success';execution_status='success';decision_status=$decisionStatus
        comparison='results/interface_readiness_cross_solver.json';census='results/interface_particle_event_census.csv'}
    Complete-CrossSolverAnalysis `
        -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath `
        -Summary $summaryPath -SummaryValue $summary `
        -Outputs @($comparison,$census) `
        -Software $software -Logs @($stdout,$stderr)
} catch {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Summary $summaryPath `
        -SummaryRole 'rf_quadrupole_interface_readiness_cross_solver_summary' `
        -Reason $_.Exception.Message `
        -Software $software
    throw
}
if($decisionStatus-ne'PASS'){throw "Interface comparison completed with decision $decisionStatus."}
"STATUS=PASS RUN_ID=$RunId"
