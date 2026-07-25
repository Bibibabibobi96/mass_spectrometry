param(
    [Parameter(Mandatory = $true)][string]$ComsolRunId,
    [Parameter(Mandatory = $true)][string]$SimionRunId,
    [string]$RunId = '',
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $projectRoot `
    'runtime\cross_solver_analysis_lifecycle.ps1')

function Resolve-RunConfigInput {
    param([Parameter(Mandatory)]$RunConfig,[Parameter(Mandatory)][string]$Name)
    $member = $RunConfig.inputs.PSObject.Properties[$Name]
    if($null-eq$member){throw "Source run config lacks input $Name."}
    $value = [string]$member.Value
    if([IO.Path]::IsPathRooted($value)){return [IO.Path]::GetFullPath($value)}
    [IO.Path]::GetFullPath((Join-Path ([string]$RunConfig.project_root) $value))
}

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') +
        '__analysis__cross__rf-transport__no-collision'
}
$software = @('COMSOL 6.4','SIMION 2020','Python 3.11')
$package = New-CrossSolverAnalysisPackage -Python $python `
    -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
    -PackageMode 'transport_no_collision_cross_solver_comparison' `
    -Software $software
$inputDir,$resultDir=$package.input_dir,$package.result_dir
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
    if ($comsolConfig.role -ne 'multipole_resolved_comsol_run_config' -or
        $simionConfig.role -ne 'multipole_resolved_simion_run_config' -or
        $comsolConfig.mode -ne 'resolved_design_transport' -or
        $simionConfig.mode -ne 'resolved_design_transport') {
        throw 'No-collision comparison accepts only resolved multipole transport runs.'
    }
    foreach ($config in @($comsolConfig,$simionConfig)) {
        if ($config.parameters.design_profile_id -ne 'official_transport') {
            throw 'No-collision source run design profile is not official_transport.'
        }
    }
    foreach ($field in @(
        'parent_resolved_design_sha256',
        'particle_source_sha256',
        'source_family_sha256',
        'operating_point_id'
    )) {
        if ([string]$comsolConfig.provenance.$field -ne
            [string]$simionConfig.provenance.$field) {
            throw "No-collision source provenance differs at $field."
        }
    }
    $comsolResolved = Resolve-RunConfigInput $comsolConfig `
        'multipole_resolved_design'
    $simionResolved = Resolve-RunConfigInput $simionConfig `
        'multipole_resolved_design'
    $comsolParticles = Resolve-RunConfigInput $comsolConfig 'particle_source'
    $simionParticles = Resolve-RunConfigInput $simionConfig 'particle_source'
    if ((Get-RunFileSha256 $comsolResolved) -ne
        (Get-RunFileSha256 $simionResolved)) {
        throw 'No-collision source resolved designs differ.'
    }
    if ((Get-RunFileSha256 $comsolParticles) -ne
        (Get-RunFileSha256 $simionParticles)) {
        throw 'No-collision source particle files differ.'
    }
    $sourceMetadata = Resolve-RunConfigInput $comsolConfig `
        'particle_source_metadata'
    $sourceMetadataDocument = Get-Content -LiteralPath $sourceMetadata -Raw `
        -Encoding UTF8 | ConvertFrom-Json
    $particleCount = [int]$sourceMetadataDocument.particle_count
    if ($particleCount -le 0) {
        throw 'No-collision particle source count is missing or empty.'
    }

    $frozen = New-CrossSolverFrozenPathSet -InputDir $inputDir `
        -AnalyzerRelativePath `
        'projects\rf_quadrupole_collision_cooling\workflows\no_collision_transport\evaluate.py' `
        -ModeFilename 'no_collision_mode.json'
    $frozenAnalyzer,$frozenCore,$frozenMode=$frozen.analyzer,$frozen.core,$frozen.mode
    $frozenComsolManifest,$frozenSimionManifest=$frozen.comsol_manifest,$frozen.simion_manifest
    $frozenComsolConfig,$frozenSimionConfig=$frozen.comsol_config,$frozen.simion_config
    $frozenComsolState,$frozenSimionState=$frozen.comsol_state,$frozen.simion_state
    $frozenLifecycleSupport = $frozen.support
    $frozenWorkflowInit = Join-Path $frozen.module_root `
        'projects\rf_quadrupole_collision_cooling\workflows\__init__.py'
    $frozenPackageInit = Join-Path $frozen.module_root `
        'projects\rf_quadrupole_collision_cooling\workflows\no_collision_transport\__init__.py'
    $frozenParticleCountPolicy = Join-Path $inputDir `
        'particle_count_policy.json'
    $frozenResolved = Join-Path $inputDir 'resolved_design.json'
    $frozenParticles = Join-Path $inputDir 'particles.dat'
    $frozenSourceMetadata = Join-Path $inputDir 'particle_source_metadata.json'
    $freezePairs = @(
        @((Join-Path $PSScriptRoot 'evaluate.py'),$frozenAnalyzer),
        @((Join-Path $projectRoot 'analysis\particle_state_comparison_core.py'),$frozenCore),
        @((Join-Path $projectRoot 'workflows\__init__.py'),$frozenWorkflowInit),
        @((Join-Path $PSScriptRoot '__init__.py'),$frozenPackageInit),
        @((Join-Path $projectRoot 'config\modes\transport_no_collision.json'),$frozenMode),
        @((Join-Path $repoRoot 'common\contracts\particle_count_policy.json'),$frozenParticleCountPolicy),
        @($comsolResolved,$frozenResolved),
        @($comsolParticles,$frozenParticles),
        @($sourceMetadata,$frozenSourceMetadata),
        @($comsolManifest,$frozenComsolManifest),
        @($simionManifest,$frozenSimionManifest),
        @($comsolConfigPath,$frozenComsolConfig),
        @($simionConfigPath,$frozenSimionConfig),
        @((Join-Path $comsolRun 'results\particle_state.csv'),$frozenComsolState),
        @((Join-Path $simionRun 'results\particle_state.csv'),$frozenSimionState),
        @((Join-Path $projectRoot 'runtime\cross_solver_analysis_lifecycle.ps1'),$frozenLifecycleSupport)
    )
    Copy-CrossSolverAnalysisInputs -Pairs $freezePairs
    $comparison = Join-Path $resultDir 'no_collision_cross_solver.json'
    $census = Join-Path $resultDir 'no_collision_particle_event_census.csv'
    Write-RunJson -Path $runConfigPath -Depth 8 -Value ([ordered]@{
        schema_version=2
        role='rf_quadrupole_no_collision_cross_solver_run_config'
        run_id=$RunId
        project='rf_quadrupole_collision_cooling'
        mode='transport_no_collision_cross_solver_comparison'
        project_root=$projectRoot
        inputs=[ordered]@{analyzer=$frozenAnalyzer;comparison_core=$frozenCore;mode_contract=$frozenMode
            particle_count_policy=$frozenParticleCountPolicy;resolved_design=$frozenResolved
            particle_table=$frozenParticles;particle_source_metadata=$frozenSourceMetadata
            comsol_manifest=$frozenComsolManifest;simion_manifest=$frozenSimionManifest
            comsol_run_config=$frozenComsolConfig;simion_run_config=$frozenSimionConfig
            comsol_particle_state=$frozenComsolState;simion_particle_state=$frozenSimionState
            analysis_lifecycle_support=$frozenLifecycleSupport}
        parameters=[ordered]@{comsol_source_run_id=$ComsolRunId;simion_source_run_id=$SimionRunId
            particle_count=$particleCount}
        provenance=[ordered]@{parent_resolved_design_sha256=[string]$comsolConfig.provenance.parent_resolved_design_sha256
            particle_source_sha256=[string]$comsolConfig.provenance.particle_source_sha256}
        formal_gate_passed=$false
    })
    $stdout = Join-Path $package.log_dir 'analysis_stdout.txt'
    $stderr = Join-Path $package.log_dir 'analysis_stderr.txt'
    $arguments=@('--comsol',$frozenComsolState,'--simion',$frozenSimionState,
        '--resolved',$frozenResolved,'--mode-contract',$frozenMode,
        '--particle-count-policy',$frozenParticleCountPolicy,'--particles',$frozenParticles,
        '--particle-count',[string]$particleCount,'--output',$comparison,'--census-output',$census)
    Invoke-CrossSolverAnalyzer -Python $python `
        -AnalyzerModule `
        'projects.rf_quadrupole_collision_cooling.workflows.no_collision_transport.evaluate' `
        -ModuleRoot $frozen.module_root `
        -Arguments $arguments -Stdout $stdout -Stderr $stderr `
        -RequiredOutputs @($comparison,$census)
    $report = Get-Content -LiteralPath $comparison -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ($report.execution_status -ne 'success' -or
        $report.role -ne `
        'rf_quadrupole_no_collision_cross_solver_result' -or
        $report.status -notin @('PASS','FAIL','NOT_EVALUATED')) {
        throw 'No-collision comparison result identity or status is invalid.'
    }
    $decisionStatus = [string]$report.status
    $summary=[ordered]@{schema_version=2;role='rf_quadrupole_no_collision_cross_solver_summary'
        status='success';execution_status='success';decision_status=$decisionStatus
        comparison='results/no_collision_cross_solver.json';census='results/no_collision_particle_event_census.csv'}
    Complete-CrossSolverAnalysis `
        -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath `
        -Summary $summaryPath -SummaryValue $summary `
        -Outputs @($comparison,$census) `
        -Software $software -Logs @($stdout,$stderr)
} catch {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot `
        -RunConfig $runConfigPath -Summary $summaryPath `
        -SummaryRole 'rf_quadrupole_no_collision_cross_solver_summary' `
        -Reason $_.Exception.Message `
        -Software $software
    throw
}
if($decisionStatus-ne'PASS'){throw "No-collision comparison completed with decision $decisionStatus."}
"STATUS=PASS RUN_ID=$RunId"
