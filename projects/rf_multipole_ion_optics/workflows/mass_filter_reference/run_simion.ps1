[CmdletBinding(DefaultParameterSetName='Execute')]
param(
    [Parameter(Mandatory = $true,ParameterSetName='Execute')]
    [ValidateNotNullOrEmpty()]
    [string]$SourceIonPath,
    [Parameter(Mandatory = $true,ParameterSetName='Execute')]
    [ValidateNotNullOrEmpty()]
    [string]$SolverNumericsContractPath,
    [Nullable[int]]$RfStepsPerPeriod = $null,
    [Nullable[int]]$TrajectoryQuality = $null,
    [string]$RunId = '',
    [string]$ArtifactRootPath = '',
    [string]$PythonExe = '',
    [string]$SimionExe = '',
    [string]$ContinuationPredecessorManifestPath = '',
    [string]$NativeFieldRunPath = '',
    [string]$ResultPath = '',
    [Parameter(Mandatory=$true,ParameterSetName='Resume')][switch]$ResumeFinalization,
    [switch]$Exploration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$execution=@{clock=[Diagnostics.Stopwatch]::StartNew();phase='prepare';phase_started=0.0;phase_seconds=[ordered]@{};elapsed_seconds=0.0}
$executionStatus='failed';$dataValidity='unavailable';$scienceStatus='not_evaluated';$failureStage=$null
$modeName = 'mass_filter_reference'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = if ($ArtifactRootPath) {
    [IO.Path]::GetFullPath($ArtifactRootPath)
} else {
    Join-Path $workspaceRoot 'artifacts\projects\rf_multipole_ion_optics'
}
$python = if ($PythonExe) {
    [IO.Path]::GetFullPath($PythonExe)
} else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if($ResumeFinalization){
    if(-not$RunId){throw 'Finalization recovery requires the original RunId.'}
    Push-Location $repoRoot
    try{& $python -m common.contracts.artifact_naming run $RunId|Out-Null;if($LASTEXITCODE-ne0){throw 'Recovery requires a valid original RunId.'}}finally{Pop-Location}
    if(-not$ResultPath){$ResultPath=Join-Path $artifactRoot "scratch/workflow_results/$RunId/result.json"}
    . (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization
    $outcome=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $artifactRoot "runs/$RunId/inputs/execution_request.json") -ResultPath $ResultPath -ResumeFinalization
    Write-Output "RF_FINALIZATION=$($outcome.status) RUN_ID=$RunId RESULT=$ResultPath"
    if($outcome.status-ne'success'){exit 1};return
}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$entryScriptHash=Get-RunFileSha256 -Path $PSCommandPath
. (Join-Path $projectRoot 'runtime\frozen_python_package.ps1')
. (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\runtime\simion_layout_template_support.ps1')
. (Join-Path $projectRoot 'runtime\simion_run_config.ps1')
. (Join-Path $projectRoot 'runtime\simion_execution.ps1')
. (Join-Path $projectRoot 'runtime\simion_field_checkpoint_support.ps1')
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__rf-mass-filter__reference'
}
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_multipole_ion_optics' -Mode $modeName -Software @('SIMION 2020','Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review `
    -RetentionReason 'Producer-owned fractional SIMION field and IOB retained for explicit continuation; no scientific qualification.' `
    -CapacityLedgerLifecycleEnabled `
    -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir = $package.run_dir
$candidateDir = Join-Path $runDir 'simion'
$resultDir = $package.result_dir
$logDir = $package.log_dir
$inputDir = $package.input_dir
$runConfigPath = $package.run_config
$runSummary = $package.summary
$simion = if ($SimionExe) {
    [IO.Path]::GetFullPath($SimionExe)
} else {
    'C:\Program Files\SIMION-2020\simion.exe'
}

$hostExecutionLease = $null
$hostExecutionOutcome = 'failed'
$writerCompletionUnknown = $false
$massFilterFailure = $null
$continuation=$null
$ownerContext=$null;$ownerCapacity=$null;$hostReleaseState=@{released=$false;completion=$null};$deferFinalization=$false
$fieldContext=$null;$nativePreparation=[Collections.Generic.List[object]]::new()
$completedBatchOutputs=[Collections.Generic.List[string]]::new()
try {
    $sourceIon = [IO.Path]::GetFullPath($SourceIonPath)
    if (-not (Test-Path -LiteralPath $sourceIon -PathType Leaf)) {
        throw "Mass-filter source ION11 table is missing: $sourceIon"
    }

    $frozenSourceIon = Join-Path $inputDir 'source_particles.ion'
    $frozenBaseline = Join-Path $inputDir 'baseline.json'
    $frozenMode = Join-Path $inputDir 'mode.json'
    $frozenResolved = Join-Path $inputDir 'resolved_design.json'
    $frozenInterface = Join-Path $inputDir 'interface_contract.json'
    $frozenNumericalContract = Join-Path $inputDir 'simion_solver_numerics.json'
    $particlePath = Join-Path $inputDir 'mass_scan_particles.ion'
    $massScanMetadata = Join-Path $inputDir 'mass_scan_particles.json'
    $templateDir = Join-Path $inputDir 'simion_layout_template'
    $template = Resolve-MultipoleSimionLayoutTemplate -Python $python `
        -RepositoryRoot $repoRoot -TemplateDirectory $templateDir
    $templateResolution = $template.resolution
    $templateProfile = $template.profile
    $templateRegistry = $template.registry
    $templateManifest = $template.registration_manifest
    $templateIob = $template.iob
    $templateCon = $template.con
    Copy-VerifiedRunInput -Source $sourceIon -Destination $frozenSourceIon | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'variants\quadrupole\config\baseline.json') `
        -Destination $frozenBaseline | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'config\modes\quadrupole_mass_filter_reference.json') `
        -Destination $frozenMode | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'variants\quadrupole\config\resolved_design_mass_filter.json') `
        -Destination $frozenResolved | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'variants\quadrupole\config\interface_contract.json') `
        -Destination $frozenInterface | Out-Null
    Copy-VerifiedRunInput -Source ([IO.Path]::GetFullPath($SolverNumericsContractPath)) `
        -Destination $frozenNumericalContract | Out-Null

    $frozenPythonSupport = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'runtime\frozen_python_package.ps1') `
        -Destination (Join-Path $inputDir 'frozen_python_package.ps1')
    . $frozenPythonSupport
    $analysisModule = 'projects.rf_multipole_ion_optics.workflows.mass_filter_reference.evaluate_simion'
    $analysisFiles = @(
        'projects\rf_multipole_ion_optics\workflows\__init__.py',
        'projects\rf_multipole_ion_optics\workflows\mass_filter_reference\__init__.py',
        'projects\rf_multipole_ion_optics\workflows\mass_filter_reference\evaluate_simion.py',
        'projects\rf_multipole_ion_optics\core\__init__.py',
        'projects\rf_multipole_ion_optics\core\mass_response.py',
        'projects\rf_multipole_ion_optics\core\paired_mass_scan.py',
        'common\contracts\file_identity.py',
        'common\analysis\peak_metrics.py',
        'projects\rf_multipole_ion_optics\workflows\mass_filter_reference\theory.py',
        'projects\rf_multipole_ion_optics\core\family_contract.py',
        'projects\rf_multipole_ion_optics\config\contracts\family_contract.json',
        'projects\rf_multipole_ion_optics\workflows\mass_filter_reference\render_simion_source.py',
        'projects\rf_multipole_ion_optics\runtime\simion_particle_source.py',
        'projects\rf_multipole_ion_optics\runtime\particle_source_preflight.py',
        'projects\rf_multipole_ion_optics\core\interface_geometry.py',
        'common\contracts\particle_physics.py','common\contracts\particle_count_policy.py',
        'common\contracts\particle_count_policy.json','common\simion\__init__.py','common\simion\particle_source.py'
    )
    $frozenAnalysisPackage = New-FrozenPythonPackage `
        -SourceRoot $repoRoot -CodeRoot (Join-Path $inputDir 'analysis_runtime') `
        -RelativePaths $analysisFiles
    $analysisRequiredModules = @($analysisFiles | Where-Object { $_.EndsWith('.py') } |
        ForEach-Object { $_ -replace '[/\\]__init__\.py$', '' -replace '\.py$', '' -replace '[/\\]', '.' })
    $analysisDistributions = @('matplotlib','numpy','scipy')
    $frozenAnalysisEnvironment = Invoke-IsolatedFrozenPythonModule `
        -Python $python -Package $frozenAnalysisPackage -Module $analysisModule `
        -Arguments @('--help') -DistributionNames $analysisDistributions `
        -RequiredModuleNames $analysisRequiredModules `
        -ForbiddenRoots @($repoRoot,$projectRoot) -ProbeOnly
    Push-Location $repoRoot
    try {
        & $python -m projects.rf_multipole_ion_optics.analysis.verify_resolved_design $frozenResolved
        if ($LASTEXITCODE -ne 0) { throw 'Frozen resolved-design identity verification failed.' }
    } finally {
        Pop-Location
    }

    Push-Location $repoRoot
    try {
        & $python -m `
            projects.rf_multipole_ion_optics.workflows.mass_filter_reference.prepare_simion_scan `
            --source $frozenSourceIon --mode $frozenMode --output $particlePath --metadata $massScanMetadata
        if ($LASTEXITCODE -ne 0) {
            throw 'Paired mass-scan particle generation failed.'
        }
    } finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $particlePath -PathType Leaf)) {
        throw "Generated mass-scan particle table is missing: $particlePath"
    }
    $expectedParticles = @(
        Get-Content -LiteralPath $particlePath -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count

    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'simion\geometry\quad_include.gem') `
        -Destination (Join-Path $candidateDir 'quad_include.gem') | Out-Null
    Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') `
        -Destination (Join-Path $candidateDir 'quad_monolithic.gem') | Out-Null
    $programSource = Copy-VerifiedRunInput `
        -Source (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\simion\simion_transport.lua') `
        -Destination (Join-Path $candidateDir 'multipole_runtime_program.lua')
    $rfDriveKernel=Copy-VerifiedRunInput -Source (Join-Path $repoRoot 'common/simion/rf_drive.lua') `
        -Destination (Join-Path $inputDir 'multipole_rf_drive_kernel.lua')
    $iobBuilder = Copy-VerifiedRunInput `
        -Source (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\simion\build_simion_runtime_iob.lua') `
        -Destination (Join-Path $candidateDir 'build_simion_runtime_iob.lua')
    $flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
    $sourceStatesLua = Join-Path $inputDir 'source_states.lua'
    Push-Location $repoRoot
    try {
        Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenAnalysisPackage `
            -Module 'projects.rf_multipole_ion_optics.workflows.mass_filter_reference.render_simion_source' `
            -Arguments @('--ion-table',$particlePath,'--fly2',$flyPath,'--source-states-lua',$sourceStatesLua) `
            -ForbiddenRoots @($repoRoot,$projectRoot)|Out-Null
    } finally {
        Pop-Location
    }


    $resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 | ConvertFrom-Json
    $numericalMode = Get-Content -LiteralPath $frozenMode -Raw -Encoding UTF8 | ConvertFrom-Json
    $interface = Get-Content -LiteralPath $frozenInterface -Raw -Encoding UTF8 | ConvertFrom-Json
    $numericalContract = Get-Content -LiteralPath $frozenNumericalContract -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $PSBoundParameters.ContainsKey('RfStepsPerPeriod')) {
        $RfStepsPerPeriod = [int]$numericalContract.baseline_rf_steps_per_period
    }
    if (-not $PSBoundParameters.ContainsKey('TrajectoryQuality')) {
        $TrajectoryQuality = [int]$numericalContract.trajectory_quality
    }
    if ($RfStepsPerPeriod -lt 1 -or $TrajectoryQuality -lt 1) {
        throw 'SIMION mass-filter numerics must be positive.'
    }
    $particleStateCsv = Join-Path $resultDir 'particle_state.csv'
    $trajectoryCsv = Join-Path $resultDir 'trajectory_samples.csv'
    $summaryJson = Join-Path $resultDir 'solver_summary.json'
    $runConfigLua = Join-Path $runDir 'run_config.lua'
    $iobReport = Join-Path $logDir 'simion_iob_contract.txt'
    $stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
    $massResponseCsv = Join-Path $resultDir 'mass-response__simion.csv'
    $massMetricsJson = Join-Path $resultDir 'mass-filter__simion-functional-metrics.json'
    $massResponseFigure = Join-Path $resultDir 'mass-response__simion-passband.png'
    $coreConfig = New-RfSimionCoreRunConfig `
        -ResolvedDesign $resolved -InterfaceContract $interface -SolverNumerics $numericalContract `
        -RfStepsPerPeriod $RfStepsPerPeriod -TrajectoryQuality $TrajectoryQuality `
        -ModeName $modeName -OperatingPoint 'mass_filter_reference' `
        -IobPath (Join-Path $candidateDir 'quad_monolithic.iob') -Fly2Path $flyPath `
        -SourceStatesLua $sourceStatesLua -ParticleStateCsv $particleStateCsv `
        -TrajectoryCsv $trajectoryCsv -SummaryJson $summaryJson

    # The repository scheduler owns process parallelism.  The scientific
    # workflow keeps ownership of its resolved numerics and particle table.
    $dispatchRequest = Join-Path $inputDir 'simion_dispatch_request.json'
    $dispatchPlan = Join-Path $inputDir 'simion_repository_dispatch_plan.json'
    $resourceProfiles = Join-Path $inputDir 'simion_resource_profiles.json'
    $batchPlan = Join-Path $inputDir 'simion_execution_batch_plan.json'
    $dispatchRequestDocument = [ordered]@{
        solver = 'SIMION'
        field_kind = 'rf'
        particle_count = $expectedParticles
        independent_particles = $true
        frontend_cell_mm_xyz = @(
            [double]$numericalContract.simion_cell_mm,
            [double]$numericalContract.simion_cell_mm,
            [double]$numericalContract.simion_cell_mm
        )
        trajectory_quality = [int]$coreConfig.trajectory_quality
        rf_steps_per_period = [int]$coreConfig.rf_steps_per_period
    }
    $dispatchRequestDocument | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $dispatchRequest -Encoding UTF8
    Push-Location $repoRoot
    try {
        & $python -m common.simion.resource_profile discover `
            --runs-root (Join-Path $artifactRoot 'runs') --output $resourceProfiles
        if ($LASTEXITCODE -ne 0) { throw 'SIMION resource profile discovery failed.' }
        & $python -m common.simion.resource_scheduler --request $dispatchRequest `
            --profiles $resourceProfiles --output $dispatchPlan
        if ($LASTEXITCODE -ne 0) { throw 'SIMION repository dispatch planning failed.' }
    } finally {
        Pop-Location
    }
    $dispatchPlanDocument = Get-Content -LiteralPath $dispatchPlan -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($dispatchPlanDocument.role -ne 'simion_repository_dispatch_plan' -or
        [int]$dispatchPlanDocument.particle_count -ne $expectedParticles -or
        @($dispatchPlanDocument.waves).Count -ne 1 -or
        [int]$dispatchPlanDocument.waves[0].batch_count -lt 1) {
        throw 'SIMION repository dispatch plan differs from the mass-scan population.'
    }
    & $python -m common.simion.particle_batching --from-dispatch-plan $dispatchPlan `
        --output $batchPlan
    if ($LASTEXITCODE -ne 0) { throw 'SIMION shared particle batch planning failed.' }
    $batchPlanDocument = Get-Content -LiteralPath $batchPlan -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$batchPlanDocument.particle_count -ne $expectedParticles) {
        throw 'SIMION particle batch plan differs from the mass-scan population.'
    }

    $runConfig = [ordered]@{
        schema_version = 1
        role = 'rf_quadrupole_simion_mass_filter_run_config'
        run_id = $RunId
        project = 'rf_multipole_ion_optics'
        mode = $modeName
        project_root = $projectRoot
        inputs = [ordered]@{
            frozen_python_package_support = $frozenPythonSupport
            baseline = $frozenBaseline
            resolved_design = $frozenResolved
            interface_contract = $frozenInterface
            mode = $frozenMode
            numerical_contract = $frozenNumericalContract
            source_ion11 = $frozenSourceIon
            particle_table = $particlePath
            mass_scan_ion11 = $particlePath
            mass_scan_metadata = $massScanMetadata
            source_states = $sourceStatesLua
            simion_layout_template_resolution = $templateResolution
            simion_layout_template_registry = $templateRegistry
            simion_layout_registration_manifest = $templateManifest
            simion_layout_template_iob = $templateIob
            simion_layout_template_con = $templateCon
            simion_layout_template_placeholder_pa0 = $template.placeholder_pa0
            simion_iob_builder = $iobBuilder
            simion_program_source = $programSource
            simion_rf_drive_kernel = $rfDriveKernel
            simion_gem = Join-Path $candidateDir 'quad_monolithic.gem'
            simion_gem_include = Join-Path $candidateDir 'quad_include.gem'
            simion_fly2 = $flyPath
            simion_dispatch_request = $dispatchRequest
            simion_resource_profiles = $resourceProfiles
            simion_repository_dispatch_plan = $dispatchPlan
            simion_execution_batch_plan = $batchPlan
        }
        frozen_python = [ordered]@{
            package = $frozenAnalysisPackage
            environment = $frozenAnalysisEnvironment
        }
        provenance = [ordered]@{
            source_ion11_sha256 = Get-RunFileSha256 -Path $frozenSourceIon
            mass_scan_ion11_sha256 = Get-RunFileSha256 -Path $particlePath
            representation = 'ion11'
            waveform = $coreConfig.waveform
            parent_resolved_design_sha256 = $coreConfig.parent_resolved_design_sha256
            solver_numerics_contract_sha256 = Get-RunFileSha256 -Path $frozenNumericalContract
            rf_steps_per_period = [int]$coreConfig.rf_steps_per_period
            trajectory_quality = [int]$coreConfig.trajectory_quality
            numerics_qualification = Get-RfSimionNumericsQualification `
                -SolverNumerics $numericalContract `
                -RfStepsPerPeriod ([int]$coreConfig.rf_steps_per_period) `
                -TrajectoryQuality ([int]$coreConfig.trajectory_quality) `
                -Exploration ([bool]$Exploration)
            rf_steps_override = (
                [int]$coreConfig.rf_steps_per_period -ne
                [int]$numericalContract.baseline_rf_steps_per_period
            )
            simion_layout_template = [ordered]@{
                template_id = [string]$templateProfile.template_id
                registration_run_id = [string]$templateProfile.registration_run_id
                registry_sha256 = [string]$templateProfile.registry_sha256
                registration_manifest_sha256 = [string]$templateProfile.run_manifest.sha256
                iob_sha256 = [string]$templateProfile.bundle.iob.sha256
                con_sha256 = [string]$templateProfile.bundle.con.sha256
            }
        }
        output_dir = $resultDir
        candidate_dir = $candidateDir
        run_dir = $runDir
        rf_steps_per_period = $coreConfig.rf_steps_per_period
        trajectory_quality = $coreConfig.trajectory_quality
        rf_peak_v = $coreConfig.rf_peak_v
        dc_amplitude_v = $coreConfig.dc_amplitude_v
        frequency_hz = $coreConfig.frequency_hz
        waveform = $coreConfig.waveform
        parent_resolved_design_sha256 = $coreConfig.parent_resolved_design_sha256
        particles = $expectedParticles
        execution_batch_count = [int]$batchPlanDocument.batch_count
    }
    foreach ($entry in $frozenAnalysisPackage.files) {
        $name = 'analysis_runtime_' +
            ([string]$entry.relative_path -replace '[^A-Za-z0-9]+','_').Trim('_')
        $runConfig.inputs[$name] = [string]$entry.path
    }
    $runConfig.inputs.simion_field_identity=Join-Path $inputDir 'simion_field_identity.json'
$fieldArguments=Get-RfSimionPaBasisArguments
$fieldIdentity=New-RfSimionFieldIdentity -GemPath $runConfig.inputs.simion_gem -GemIncludePaths @($runConfig.inputs.simion_gem_include) `
    -SimionExe $simion -Grid @([int]$coreConfig.expected_pa_nx,[int]$coreConfig.expected_pa_ny,[int]$coreConfig.expected_pa_nz) `
    -CellMm @([double]$coreConfig.expected_pa_cell_mm,[double]$coreConfig.expected_pa_cell_mm,[double]$coreConfig.expected_pa_cell_mm) `
    -ResponseIds @(@($coreConfig.rod_electrodes)+@($coreConfig.static_electrodes)|ForEach-Object{[int]$_.electrode_id}) `
    -Gem2PaArguments $fieldArguments.gem2pa -RefineArguments $fieldArguments.refine
Write-RunJson -Path $runConfig.inputs.simion_field_identity -Value $fieldIdentity -Depth 12
$runConfig.inputs.simion_fly_physics=Join-Path $inputDir 'simion_fly_physics.json'
    Write-RfSimionPreparedFlyIdentity -CoreConfig $coreConfig -CaseName 'mass_filter_reference' `
        -Path $runConfig.inputs.simion_fly_physics -SourcePackage $frozenAnalysisPackage -ProgramSourcePath $programSource `
        -NativeFlyArguments @(Get-RfSimionFlyArgumentIdentity -CoreConfig $coreConfig) `
        -SourceRelativePaths @('projects/rf_multipole_ion_optics/workflows/mass_filter_reference/render_simion_source.py',
            'projects/rf_multipole_ion_optics/runtime/simion_particle_source.py',
            'projects/rf_multipole_ion_optics/runtime/particle_source_preflight.py',
            'projects/rf_multipole_ion_optics/core/interface_geometry.py','common/simion/particle_source.py',
            'common/contracts/particle_physics.py','common/contracts/particle_count_policy.py','common/contracts/particle_count_policy.json')
    $lifecycle=Get-Content -LiteralPath $runConfigPath -Raw|ConvertFrom-Json -AsHashtable
    foreach($key in @('artifact_retention','capacity_ledger_lifecycle')){if($lifecycle.ContainsKey($key)){$runConfig[$key]=$lifecycle[$key]}}
    $runConfig.schema_version=$lifecycle.schema_version
    $runConfig | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
    if($ContinuationPredecessorManifestPath){
        $continuation=Initialize-RfSimionPreparedContinuation -ManifestPath $ContinuationPredecessorManifestPath `
            -RunDir $package.artifact_run_dir -ArtifactRoot (Split-Path (Split-Path $artifactRoot -Parent) -Parent) `
            -PythonExe $python -RepositoryRoot $repoRoot -RunConfig $runConfig -RunConfigPath $runConfigPath `
            -CapacityOwner ("run-artifact-workflow:rf_multipole_ion_optics:{0}"-f$RunId) -CaseName 'mass_filter_reference' -BatchPlanPath $batchPlan -DispatchPlanPath $dispatchPlan `
            -InputNames @('resolved_design','particle_table','simion_field_identity',
                'simion_program_source','simion_rf_drive_kernel','simion_iob_builder','simion_gem','simion_gem_include','simion_fly2','source_states',
                'simion_layout_template_iob','simion_layout_template_con')
        $batchPlanDocument=Get-Content -LiteralPath $batchPlan -Raw|ConvertFrom-Json
        $dispatchPlanDocument=Get-Content -LiteralPath $dispatchPlan -Raw|ConvertFrom-Json
    }

    $luaConfig = ConvertTo-RfSimionLuaConfig -CoreConfig $coreConfig `
        -SharedProgramPath $programSource
    # Windows PowerShell 5.1 writes a BOM for UTF8; SIMION Lua 5.1 treats it as source text.
    $luaConfig | Set-Content -LiteralPath $runConfigLua -Encoding ASCII

    $inspectScript = Join-Path $projectRoot 'simion\workbench\inspect_builtin_quad_reference.lua'

$ownerCapacity=if($null-ne$continuation){$continuation.capacity}else{
    Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot (Split-Path (Split-Path $artifactRoot -Parent) -Parent) `
        -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -Owner ("run-artifact-workflow:rf_multipole_ion_optics:{0}"-f$RunId)
}
$ownerSource=Copy-VerifiedRunInput -Source $PSCommandPath -Destination (Join-Path $package.artifact_run_dir 'inputs/powershell_owner.ps1')
if((Get-RunFileSha256 -Path $ownerSource)-cne$entryScriptHash){throw 'Frozen PowerShell owner differs from launched source.'}
$runConfig.inputs.powershell_owner=$ownerSource
$runConfig.inputs.simion_execution_owner=Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'runtime/simion_execution.ps1') -Destination (Join-Path $inputDir 'simion_execution_owner.ps1')
Write-RunJson -Path $runConfigPath -Value $runConfig -Depth 20
. (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization
$ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $ownerCapacity `
    -ResultPath $ResultPath -EntrypointPath $ownerSource -CommitmentInputPaths @($frozenNumericalContract) -Software @('SIMION 2020','Python 3.11')
$ResultPath=$ownerContext.result_path
$runConfig.inputs.execution_request=$ownerContext.request_path
if($null-eq$continuation-or-not$continuation.all_reused){$hostExecutionLease = Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId}
else{$hostExecutionLease=Enter-HostExecutionLease -Role GATE -Stage postprocess -RunId $RunId}
if($null-eq$continuation-or-not$continuation.all_reused){
    Set-RfSimionExecutionPhase -Context $execution -Name field_and_layout
    $fieldSource=if($NativeFieldRunPath){$NativeFieldRunPath}elseif($null-ne$continuation){$continuation.predecessor}else{''}
    $existingRuns=if($null-ne$continuation){@($continuation.chain)}else{@()}
    $capacity=$ownerCapacity
    $preparation=@{SimionExe=$simion;CandidateDir=$candidateDir;IobPath=[string]$coreConfig.iob;Fly2Path=$flyPath;
        IobBuilderScript=$iobBuilder;ProgramSourcePath=$programSource;RunConfigLua=$runConfigLua;InspectScript=$inspectScript;
        IobReport=$iobReport;LogDir=$logDir;RfDriveKernelPath=$rfDriveKernel}
    $fieldContext=Initialize-RfSimionPreparedField -Package $package -IdentityPath $runConfig.inputs.simion_field_identity `
        -Preparation $preparation -HostLease $hostExecutionLease -TemplateIobPath $templateIob -TemplateConPath $templateCon `
        -PythonExe $python -RepositoryRoot $repoRoot -ArtifactRoot (Split-Path (Split-Path $artifactRoot -Parent) -Parent) `
        -Owner $runConfig.project -NativeOperations $nativePreparation -SourceRunPath $fieldSource `
        -ExistingProtectedRuns $existingRuns -CapacitySession $capacity -TemplateSeedPaPath $template.placeholder_pa0
    $ownerCapacity=$fieldContext.capacity;$ownerContext.session=$ownerCapacity
    $request=Get-Content $ownerContext.request_path -Raw|ConvertFrom-Json -AsHashtable
    $request.capacity.protected_paths=@($ownerCapacity.protected_paths)
    Write-RunJson -Atomic -Path $ownerContext.request_path -Value $request -Depth 64
    if($null-ne$continuation){$continuation.capacity=$ownerCapacity}
    $coreConfig.iob=[string]$fieldContext.iob_path
    (ConvertTo-RfSimionLuaConfig -CoreConfig $coreConfig -SharedProgramPath $programSource) |
        Set-Content -LiteralPath $runConfigLua -Encoding ASCII
    if($fieldContext.source_reused){
        $runConfig.inputs.simion_field_checkpoint=[string]$fieldContext.checkpoint_path
        $runConfig.inputs.simion_field_producer_manifest=[string]$fieldContext.producer_manifest
    }
    Write-RunJson -Path $runConfigPath -Value $runConfig -Depth 20
}

    function New-MassFilterBatchRuns {
      param([Parameter(Mandatory)]$PlanDocument,[bool]$ReuseFirst=$false)
      $runs=@();$singleComplete=([int]$PlanDocument.batch_count-eq1-and
        [string]$PlanDocument.coverage-eq'complete_population')
      foreach ($batch in @($PlanDocument.batches)) {
        $batchIndex = [int]$batch.index
        $batchSuffix = 'batch_{0:D2}' -f $batchIndex
        $batchFly = if ($singleComplete) { $flyPath } else {
            Join-Path $candidateDir ("quad_monolithic__$batchSuffix.fly2")
        }
        $batchStates = if ($singleComplete) { $sourceStatesLua } else {
            Join-Path $inputDir ("source_states__$batchSuffix.lua")
        }
        $batchState = if ($singleComplete) { $particleStateCsv } else {
            Join-Path $resultDir ("particle_state__$batchSuffix.csv")
        }
        $batchTrajectory = if ($singleComplete) { $trajectoryCsv } else {
            Join-Path $resultDir ("trajectory_samples__$batchSuffix.csv")
        }
        $batchSummary = if ($singleComplete) { $summaryJson } else {
            Join-Path $resultDir ("solver_summary__$batchSuffix.json")
        }
        $batchLua = if ($singleComplete) { $runConfigLua } else {
            Join-Path $inputDir ("simion_run_config__$batchSuffix.lua")
        }
        $batchLogDir = if ($singleComplete) { $logDir } else {
            Join-Path $logDir $batchSuffix
        }
        if (-not $singleComplete -and -not ($ReuseFirst -and $batchIndex -eq 1)) {
            New-Item -ItemType Directory -Path $batchLogDir -Force | Out-Null
            Push-Location $repoRoot
            try {
                Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenAnalysisPackage `
                    -Module 'projects.rf_multipole_ion_optics.workflows.mass_filter_reference.render_simion_source' `
                    -Arguments @('--ion-table',$particlePath,'--particle-id-min',[string][int]$batch.particle_id_min,
                        '--particle-id-max',[string][int]$batch.particle_id_max,'--fly2',$batchFly,'--source-states-lua',$batchStates) `
                    -ForbiddenRoots @($repoRoot,$projectRoot)|Out-Null
            } finally {
                Pop-Location
            }
        }
        $batchConfig = New-RfSimionCoreRunConfig `
            -ResolvedDesign $resolved -InterfaceContract $interface -SolverNumerics $numericalContract `
            -RfStepsPerPeriod $RfStepsPerPeriod -TrajectoryQuality $TrajectoryQuality `
            -ModeName $modeName -OperatingPoint 'mass_filter_reference' `
            -IobPath ([string]$coreConfig.iob) -Fly2Path $batchFly -SourceStatesLua $batchStates `
            -ParticleStateCsv $batchState -TrajectoryCsv $batchTrajectory -SummaryJson $batchSummary
        if (-not $singleComplete -and -not ($ReuseFirst -and $batchIndex -eq 1)) {
            (ConvertTo-RfSimionLuaConfig -CoreConfig $batchConfig `
                -SharedProgramPath $programSource) |
                Set-Content -LiteralPath $batchLua -Encoding ASCII
        }
        $runs += [pscustomobject]@{
            batch = $batch; config = $batchConfig; fly = $batchFly; states = $batchStates
            state = $batchState; trajectory = $batchTrajectory; summary = $batchSummary
            lua = $batchLua; log_dir = $batchLogDir; name = ('mass_filter_' + $batchIndex)
            merged_state = $particleStateCsv; merged_trajectory = $trajectoryCsv; merged_summary = $summaryJson
        }
      }
      return @($runs)
    }
    Set-RfSimionExecutionPhase -Context $execution -Name flight
$batchRuns=@(New-MassFilterBatchRuns -PlanDocument $batchPlanDocument)
    $resourceUsage = Join-Path $resultDir 'simion_resource_usage.json'

    $waveArguments = @{
        HostLease=$hostExecutionLease; SimionExe=$simion; CandidateDir=$candidateDir
        IobPath=[string]$coreConfig.iob; RootFly2Path=[string]$coreConfig.fly2
        IobBuilderScript=$iobBuilder; ProgramSourcePath=$programSource; RootRunConfigLua=$runConfigLua
        InspectScript=$inspectScript; IobReport=$iobReport; LogDir=$logDir
        TrajectoryQuality=[int]$coreConfig.trajectory_quality; RfStepsPerPeriod=[int]$coreConfig.rf_steps_per_period
        BatchRuns=$batchRuns; BatchPlanPath=$batchPlan; DispatchPlanPath=$dispatchPlan
        RunDir=$runDir; UsagePath=$resourceUsage; PythonExe=$python; RepositoryRoot=$repoRoot
        CaseName='mass_filter_reference';CompletionOutputs=$completedBatchOutputs
    Prepared=$true;NativeOperations=$nativePreparation
        RfDriveKernelPath=$rfDriveKernel
    }
    if($null-ne$continuation){$waveArguments.ContinuationUnits=$continuation.units;$waveArguments.ContinuationRequested=$true}
    $wave = Invoke-RfSimionAdaptiveBatchWave -WaveArguments $waveArguments -BatchRuns ([ref]$batchRuns) `
        -DispatchPlan $dispatchPlanDocument `
        -DispatchRequestPath $dispatchRequest -ResourceProfilesPath $resourceProfiles `
        -RunConfig $runConfig -RunConfigPath $runConfigPath `
        -PrepareReplannedBatches { param($plan) New-MassFilterBatchRuns -PlanDocument $plan -ReuseFirst $true }
    $hostExecutionLease=$wave.lease; $batchRuns=@($wave.batches)
    $waveReceipt=$wave.receipt; $resourceProfile=$wave.resource_profile
Set-RfSimionExecutionPhase -Context $execution -Name analysis

    $summary = Get-Content -LiteralPath $summaryJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($summary.particles -ne $expectedParticles -or $summary.collision_model -ne 'none' -or
        $summary.parent_resolved_design_sha256 -cne $coreConfig.parent_resolved_design_sha256) {
        throw "SIMION mass-filter execution integrity failed: $($summary | ConvertTo-Json -Compress)"
    }
    $dataValidity='valid_raw_outputs'
    Push-Location $repoRoot
    try {
        & $python -m common.contracts.particle_state `
            --state $particleStateCsv --particles $particlePath --source-format ion11 `
            --contract $frozenInterface --axial-offset-mm 0 `
            --frequency-hz ([double]$coreConfig.frequency_hz) `
            --phase-rad ([double]$coreConfig.phase_rad) `
            --solver SIMION --output $stateContractReport
        if ($LASTEXITCODE -ne 0) {
            throw 'Particle-state contract gate failed.'
        }

    } finally {
        Pop-Location
    }
    $analysisExitCode = 0
    try {
        Invoke-IsolatedFrozenPythonModule `
            -Python $python -Package $frozenAnalysisPackage -Module $analysisModule `
            -Arguments @(
                '--state',$particleStateCsv,'--particles',$particlePath,
                '--baseline',$frozenBaseline,'--mode',$frozenMode,
                '--response',$massResponseCsv,'--metrics',$massMetricsJson,
                '--figure',$massResponseFigure
            ) -DistributionNames $analysisDistributions `
            -RequiredModuleNames $analysisRequiredModules `
            -ForbiddenRoots @($repoRoot,$projectRoot) | Out-Null
    } catch {
        # A completed analyzer may exit nonzero for a physical FAIL. All other
        # isolation failures propagate; the existing output/status checks follow.
        if (-not $_.Exception.Data.Contains('exit_code')) {
            throw
        }
        $analysisExitCode = [int]$_.Exception.Data['exit_code']
        if ($analysisExitCode -eq 0) { throw }
        Assert-FrozenPythonPackage -Package $frozenAnalysisPackage
    }
    foreach ($analysisOutput in @($massResponseCsv,$massMetricsJson,$massResponseFigure)) {
        if (-not (Test-Path -LiteralPath $analysisOutput -PathType Leaf)) {
            throw "SIMION mass-filter analysis did not produce required output: $analysisOutput"
        }
    }
    $massMetrics = Get-Content -LiteralPath $massMetricsJson -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($massMetrics.status -notin @('PASS','FAIL')) {
        throw "SIMION mass-filter analysis returned invalid physical status: $($massMetrics.status)"
    }
    if (($analysisExitCode -eq 0) -ne ($massMetrics.status -eq 'PASS')) {
        throw "SIMION mass-filter analyzer exit/status mismatch: exit=$analysisExitCode status=$($massMetrics.status)"
    }
    $physicalDecision = [string]$massMetrics.status

    $shaPath = Join-Path $candidateDir 'SHA256SUMS.csv'
    Write-RunDirectoryChecksumInventory -Directory $candidateDir -OutputPath $shaPath `
        -ExcludedPatterns @('trj*.tmp')

    Set-RfSimionExecutionPhase -Context $execution -Name finalize
$executionStatus='completed';$dataValidity='valid';$scienceStatus=if($physicalDecision-eq'PASS'){'functional_pass'}else{'functional_fail'}
$rootSummary = [ordered]@{
    execution_status=$executionStatus;data_validity=$dataValidity;science_status=$scienceStatus
    failure_stage=$null;reason=$null;recovery_action=$null;result_path=$ResultPath
    phase_seconds=$execution.phase_seconds;elapsed_seconds=$execution.elapsed_seconds;timing_scope='through_terminal_publication_preparation'
        schema_version = 1
        role = 'rf_quadrupole_mass_filter_summary'
        status = 'success'
        mode = $modeName
        physical_decision = $physicalDecision
        numerics_qualification = Get-RfSimionNumericsQualification `
            -SolverNumerics $numericalContract `
            -RfStepsPerPeriod ([int]$coreConfig.rf_steps_per_period) `
            -TrajectoryQuality ([int]$coreConfig.trajectory_quality) `
            -Exploration ([bool]$Exploration)
        functional_gate = [string]$massMetrics.status
        particles = $expectedParticles
        hits = $summary.hits
        transmission = $summary.transmission
        mass_response = 'results/mass-response__simion.csv'
        metrics = 'results/mass-filter__simion-functional-metrics.json'
        figure = 'results/mass-response__simion-passband.png'
        continuation_predecessor=$(if($null-ne$continuation){$continuation.predecessor}else{$null})
        reused_fly_batches=$(if($null-ne$continuation){$continuation.units.Count}else{0})
    field_producer_manifest=$(if($null-ne$fieldContext-and$fieldContext.source_reused){$fieldContext.producer_manifest}elseif($null-ne$fieldContext){Join-Path $package.artifact_run_dir 'run_manifest.json'}else{$null})
    field_reused=$(if($null-ne$fieldContext){[bool]$fieldContext.source_reused}else{$null})
    field_grid=$fieldIdentity.grid;field_cell_mm=$fieldIdentity.cell_mm;particle_source=$particlePath
    flight_scope='explicit frozen particle-table source; finite fractional monolithic field; reused batches retain original provenance'
    }
    $rootSummary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runSummary -Encoding UTF8
    $manifestOutputs = @(
        $trajectoryCsv,$summaryJson,$particleStateCsv,$stateContractReport,
        (Join-Path $logDir 'simion_iob_stdout.txt'),(Join-Path $logDir 'simion_iob_stderr.txt'),
        (Join-Path $logDir 'simion_iob_exit_code.txt'),
        (Join-Path $candidateDir 'quad_monolithic.iob'),(Join-Path $candidateDir 'quad_monolithic.con'),
        (Join-Path $candidateDir 'quad_monolithic.pa0'),
        $flyPath,$iobReport,$shaPath,$massResponseCsv,$massMetricsJson,$massResponseFigure,$runSummary
    )
    foreach ($batchRun in $batchRuns) {
        $manifestOutputs += @(
            $batchRun.fly,$batchRun.states,$batchRun.state,$batchRun.trajectory,$batchRun.summary,
            (Join-Path $batchRun.log_dir 'simion_stdout.txt'),
            (Join-Path $batchRun.log_dir 'simion_stderr.txt')
        )
    }
    $manifestOutputs += $resourceUsage
    $manifestOutputs += @($completedBatchOutputs)
if($null-ne$fieldContext){$manifestOutputs+=@($fieldContext.output_paths)}
    if ($resourceProfile) { $manifestOutputs += $resourceProfile }
    $ownerPrefixes=@([IO.Path]::GetFullPath($runDir).TrimEnd('\')+'\',[IO.Path]::GetFullPath($package.artifact_run_dir).TrimEnd('\')+'\')
$manifestOutputs = @($manifestOutputs | Where-Object {
    $output=[IO.Path]::GetFullPath($_)
    (Test-Path -LiteralPath $output -PathType Leaf)-and@($ownerPrefixes|Where-Object{$output.StartsWith($_,[StringComparison]::OrdinalIgnoreCase)}).Count
} | Select-Object -Unique)
    $rootSummary.scientific_result=$scienceStatus;$rootSummary.data_validity=$dataValidity
$rootSummary.phase_timings_seconds=$execution.phase_seconds;$rootSummary.elapsed_before_finalization_seconds=$execution.elapsed_seconds
$writers=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativePreparation -State $hostReleaseState
$deferFinalization=$true
$null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status success -Summary $rootSummary -OutputPaths $manifestOutputs `
    -WriterCompletion $writers -WritersStopped $true `
    -ResourceUsagePaths @(@($resourceUsage)|Where-Object{$_-and(Test-Path -LiteralPath $_)}|ForEach-Object{@{case_name='mass_filter_reference';path=$_}})
$deferFinalization=$false;$ownerCapacity=$null
$hostExecutionOutcome = 'success'
    "EXECUTION=PASS DECISION=$physicalDecision RUN_ID=$RunId HITS=$($summary.hits) " +
        "TRANSMISSION=$($summary.transmission)"
}
catch {
    $massFilterFailure = $_
    if($null-eq$fieldContext-and$massFilterFailure.Exception.Data.Contains('rf_field_context')){$fieldContext=$massFilterFailure.Exception.Data['rf_field_context']}
    if($null-ne$ownerContext-and$ownerContext.completion_written){$executionStatus='finalization_failed';$failureStage='finalization';throw $massFilterFailure}
    if($null-ne$ownerContext-and$null-ne$fieldContext-and$null-ne$fieldContext.capacity){
        $ownerCapacity=$fieldContext.capacity;$ownerContext.session=$ownerCapacity
        try{
            $request=Get-Content $ownerContext.request_path -Raw|ConvertFrom-Json -AsHashtable
            $request.capacity.protected_paths=@($ownerCapacity.protected_paths)
            Write-RunJson -Atomic -Path $ownerContext.request_path -Value $request -Depth 64
            if($fieldContext.source_reused){
                $runConfig.inputs.simion_field_checkpoint=[string]$fieldContext.checkpoint_path
                $runConfig.inputs.simion_field_producer_manifest=[string]$fieldContext.producer_manifest
                Write-RunJson -Path $runConfigPath -Value $runConfig -Depth 20
            }
        }catch{$massFilterFailure.Exception.Data['field_binding_closeout_error']=[string]$_}
    }

    $executionStatus='failed';$failureStage=$execution.phase
    Set-RfSimionExecutionPhase -Context $execution
    $recovery="Use this CLI with a new -RunId and -ContinuationPredecessorManifestPath '$(Join-Path $package.artifact_run_dir 'run_manifest.json')'."
    $data = $massFilterFailure.Exception.Data
    $writerCompletionUnknown = [bool]$data['simion_first_batch_writer_unknown'] -or
        $data.Contains('rf_host_release_unconfirmed') -or $data.Contains('simion_first_batch_drain_error') -or $data.Contains('simion_wave_drain_error') -or
        ($data.Contains('simion_wave_writer_completion_confirmed') -and -not [bool]$data['simion_wave_writer_completion_confirmed'])
    if ($writerCompletionUnknown) {
        $executionStatus='writer_completion_unknown'
        $recovery='Confirm writer exit and host release, then finish owner publication before creating a continuation run.'
        try { Write-RunJson -Path $runSummary -Value @{schema_version=1;role='rf_quadrupole_mass_filter_summary';status='writer_completion_unknown';execution_status=$executionStatus;data_validity=$dataValidity;science_status=$scienceStatus;failure_stage=$failureStage;recovery_action=$recovery;result_path=$ResultPath;phase_seconds=$execution.phase_seconds;elapsed_seconds=$execution.elapsed_seconds;timing_scope='through_failure_capture';reason=$massFilterFailure.Exception.Message;drain_error=[string]($data['simion_wave_drain_error'] ?? $data['simion_first_batch_drain_error'])} }
        catch { $massFilterFailure.Exception.Data['writer_unknown_result_error'] = [string]$_ }
        if($null-ne$ownerContext){
            try{
                $null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status failed -Summary @{} `
                    -WriterCompletion @{operations=@();resource_releases=@()} -WritersStopped $false -OriginalFailure $massFilterFailure
            }catch{if($_.Exception.Message-notmatch'native writer completion is unknown'){$massFilterFailure.Exception.Data['writer_unknown_transport_error']=[string]$_}}
        }
    } else {
        try {
            if($null-ne$ownerContext){
                $failedSummary=@{schema_version=1;role='rf_quadrupole_mass_filter_summary';run_id=$RunId;status='failed';execution_status=$executionStatus;
                    data_validity=$dataValidity;scientific_result=$scienceStatus;failure_stage=$failureStage;failure_reason=$massFilterFailure.Exception.Message;
                    recovery_action=$recovery;result_path=$ResultPath;phase_timings_seconds=$execution.phase_seconds;elapsed_before_finalization_seconds=$execution.elapsed_seconds}
                $writers=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativePreparation -State $hostReleaseState
                $failureOutputs=@(foreach($folder in @($resultDir,$logDir,$candidateDir)){Get-ChildItem $folder -Recurse -File|Select-Object -ExpandProperty FullName})
                $deferFinalization=$true
                $null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status failed -Summary $failedSummary -OutputPaths $failureOutputs `
                    -WriterCompletion $writers -WritersStopped $true -OriginalFailure $massFilterFailure
                $deferFinalization=$false;$ownerCapacity=$null
            }else{
                Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath -Summary $runSummary `
                    -SummaryRole 'rf_quadrupole_mass_filter_summary' -Reason $massFilterFailure.Exception.Message -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage
            }
        }catch{if($_.Exception.Data['rf_host_release_unconfirmed']){$writerCompletionUnknown=$true};$massFilterFailure.Exception.Data['failure_closure_error']=[string]$_}

    }
    throw $massFilterFailure
} finally {
    if(-not$writerCompletionUnknown){
        try{
            if(-not$hostReleaseState.released){$null=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativePreparation -State $hostReleaseState}
        }catch{if($null-eq$massFilterFailure){throw};$massFilterFailure.Exception.Data['host_release_error']=[string]$_}
        if($hostReleaseState.released){
            if($null-ne$fieldContext-and$null-ne$fieldContext.guard){Close-RfSimionFieldCheckpointGuard -Context $fieldContext.guard}
            if($null-ne$continuation){foreach($guard in $continuation.guards){$guard.Dispose()}}
            if($null-ne$ownerCapacity-and-not$deferFinalization){
                try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $ownerCapacity|Out-Null}
                catch{if($null-eq$massFilterFailure){throw};$massFilterFailure.Exception.Data['capacity_release_error']=[string]$_}
            }
            try{Remove-RunPackageExecutionAlias -Package $package}catch{Write-Warning "Could not remove short execution alias: $_"}
        }
    }
    Set-RfSimionExecutionPhase -Context $execution
    Write-Host "RF_EXECUTION_STATUS=$executionStatus DATA_VALIDITY=$dataValidity SCIENCE_STATUS=$scienceStatus FAILURE_STAGE=$failureStage RESULT=$ResultPath ELAPSED_SECONDS=$($execution.elapsed_seconds)"
}
