[CmdletBinding(DefaultParameterSetName='Execute')]
param(
    [Nullable[int]]$RfStepsPerPeriod = $null,
    [Nullable[int]]$TrajectoryQuality = $null,
    [string]$RunId = '',
    [Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$ParticleTablePath,
    [Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$ParticleBundleMetadataPath,
    [Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$SourceFamilyPath,
    [Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$ParticleDistributionPath,
    [Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$SolverNumericsContractPath,
    [Parameter(Mandatory=$true,ParameterSetName='Execute')][string]$OperatingPoint,
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
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = if ($ArtifactRootPath) {
    [IO.Path]::GetFullPath($ArtifactRootPath)
} else {
    Join-Path $workspaceRoot 'artifacts\projects\rf_multipole_ion_optics'
}
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$mode = 'transport_interface_readiness'
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
. (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\runtime\simion_layout_template_support.ps1')
. (Join-Path $projectRoot 'runtime\simion_run_config.ps1')
. (Join-Path $projectRoot 'runtime\simion_execution.ps1')
. (Join-Path $projectRoot 'runtime\simion_field_checkpoint_support.ps1')
. (Join-Path $projectRoot 'runtime\frozen_python_package.ps1')
$frozenPythonRelativePaths = @(
    'projects\rf_multipole_ion_optics\workflows\__init__.py',
    'projects\rf_multipole_ion_optics\workflows\interface_readiness\__init__.py',
    'projects\rf_multipole_ion_optics\workflows\interface_readiness\generate_particle_table.py',
    'projects\rf_multipole_ion_optics\workflows\interface_readiness\particle_source_policy.py',
    'projects\rf_multipole_ion_optics\analysis\paired_particle_source_bundle.py',
    'common\contracts\particle_physics.py',
    'common\contracts\particle_count_policy.py',
    'common\contracts\particle_count_policy.json',
    'common\contracts\file_identity.py',
    'common\ion_release\__init__.py',
    'common\ion_release\cylinder.py',
    'common\ion_release\mt19937_disk_cone_rf_phase.py',
    'common\ion_release\numpy_box_cone.py',
    'common\ion_release\numpy_ion11_box.py',
    'projects\rf_multipole_ion_optics\core\__init__.py',
    'projects\rf_multipole_ion_optics\core\interface_geometry.py',
    'projects\rf_multipole_ion_optics\runtime\particle_source_preflight.py',
    'projects\rf_multipole_ion_optics\runtime\simion_particle_source.py',
    'common\simion\__init__.py','common\simion\particle_source.py'
)
$executionCapacityPaths = @('inputs/frozen_python_package.ps1') +
    (Get-FrozenPythonPackageExecutionPaths -RelativePaths $frozenPythonRelativePaths)
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__rf-transport__interface-readiness'
}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_multipole_ion_optics' -Mode $mode -Software @('SIMION 2020','Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review `
    -RetentionReason 'Producer-owned fractional SIMION field and IOB retained for explicit continuation; no scientific qualification.' `
    -CapacityLedgerLifecycleEnabled `
    -AdditionalDirectories @('simion') -UseShortExecutionPath `
    -ExpectedExecutionRelativePaths $executionCapacityPaths
$runDir=$package.run_dir
$candidateDir=Join-Path $runDir 'simion'
$resultDir=$package.result_dir
$logDir=$package.log_dir
$inputDir=$package.input_dir
$runConfigPath=$package.run_config
$runSummary=$package.summary
$simion = if ($SimionExe) {
    [IO.Path]::GetFullPath($SimionExe)
} else {
    'C:\Program Files\SIMION-2020\simion.exe'
}

$hostExecutionLease = $null
$hostExecutionOutcome = 'failed'
$writerCompletionUnknown = $false
$interfaceFailure = $null
$continuation=$null
$ownerContext=$null;$ownerCapacity=$null;$hostReleaseState=@{released=$false;completion=$null};$deferFinalization=$false
$fieldContext=$null;$nativePreparation=[Collections.Generic.List[object]]::new()
$completedBatchOutputs=[Collections.Generic.List[string]]::new()
try {
$sourceParticlePath = [IO.Path]::GetFullPath($ParticleTablePath)
if (-not (Test-Path -LiteralPath $sourceParticlePath -PathType Leaf)) {
    throw "Particle table is missing: $sourceParticlePath"
}
$bundleMetadataInput = [IO.Path]::GetFullPath($ParticleBundleMetadataPath)
$sourceFamilyInput = [IO.Path]::GetFullPath($SourceFamilyPath)
$distributionInput = [IO.Path]::GetFullPath($ParticleDistributionPath)
if (-not (Test-Path -LiteralPath $bundleMetadataInput -PathType Leaf)) {
    throw "Paired particle bundle metadata is missing: $bundleMetadataInput"
}
if (-not (Test-Path -LiteralPath $sourceFamilyInput -PathType Leaf)) {
    throw "Particle source family is missing: $sourceFamilyInput"
}
if (-not (Test-Path -LiteralPath $distributionInput -PathType Leaf)) {
    throw "Particle source distribution is missing: $distributionInput"
}
$modeInput = 'config/modes/quadrupole_transport_interface_readiness.json'
$expectedParticles = 0

$frozenMode = Join-Path $inputDir 'mode.json'
$frozenInterface = Join-Path $inputDir 'interface_contract.json'
$frozenSourceFamily = Join-Path $inputDir 'particle_source_family.json'
$frozenDistribution = Join-Path $inputDir 'particle_source_distribution.json'
$sourceBinding = Join-Path $inputDir 'particle_source_binding.json'
$frozenNumericalContract = Join-Path $inputDir 'simion_solver_numerics.json'
$templateDir = Join-Path $inputDir 'simion_layout_template'
$template = Resolve-MultipoleSimionLayoutTemplate -Python $python `
    -RepositoryRoot $repoRoot -TemplateDirectory $templateDir
$templateResolution = $template.resolution
$templateProfile = $template.profile
$templateRegistry = $template.registry
$templateManifest = $template.registration_manifest
$templateIob = $template.iob
$templateCon = $template.con
Copy-VerifiedRunInput -Source (Join-Path $projectRoot ($modeInput -replace '/', '\')) `
    -Destination $frozenMode | Out-Null
    $frozenPythonSupport = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'runtime\frozen_python_package.ps1') `
        -Destination (Join-Path $inputDir 'frozen_python_package.ps1')
    . $frozenPythonSupport
    $publishedDesignFreshness = New-RfPublishedDesignFreshnessPackage `
        -Python $python -SourceRoot $repoRoot `
        -SnapshotRoot (Join-Path $inputDir 'published_design_snapshot') -Profile interface
    $frozenResolved = $publishedDesignFreshness.resolved_path
    $publishedDesignFreshnessPath = Join-Path $inputDir 'published_design_freshness.json'
    Write-RunJson -Path $publishedDesignFreshnessPath -Value $publishedDesignFreshness -Depth 16
Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'variants\quadrupole\config\interface_contract.json') `
    -Destination $frozenInterface | Out-Null
Copy-VerifiedRunInput -Source ([IO.Path]::GetFullPath($SolverNumericsContractPath)) `
    -Destination $frozenNumericalContract | Out-Null
$numericalMode = Get-Content -LiteralPath $frozenMode -Raw -Encoding UTF8 | ConvertFrom-Json
$modeNumerics = Get-RfSimionRequiredProperty -Object $numericalMode `
    -Property 'numerics' -Name 'frozen interface mode numerics'
$minimumParticles = [int](Get-RfSimionRequiredFiniteNumber -Object $modeNumerics `
    -Property 'minimum_diagnostic_particles' `
    -Name 'frozen interface minimum_diagnostic_particles' -Positive)
$acceptanceTargets = Get-RfSimionRequiredProperty -Object $numericalMode `
    -Property 'candidate_acceptance_targets' -Name 'frozen interface acceptance targets'
$minimumTransmission = Get-RfSimionRequiredFiniteNumber -Object $acceptanceTargets `
    -Property 'minimum_transmission' -Name 'frozen interface minimum_transmission' -Positive
if ($minimumTransmission -gt 1) {
    throw 'Frozen interface minimum_transmission must not exceed 1.'
}
Push-Location $repoRoot
try {
    & $python -m projects.rf_multipole_ion_optics.analysis.verify_resolved_design $frozenResolved
    if ($LASTEXITCODE -ne 0) { throw 'Frozen resolved-design identity verification failed.' }
} finally {
    Pop-Location
}
Copy-VerifiedRunInput -Source $sourceFamilyInput -Destination $frozenSourceFamily | Out-Null
Copy-VerifiedRunInput -Source $distributionInput -Destination $frozenDistribution | Out-Null
$frozenCodeRoot = Join-Path $inputDir 'code'
$frozenPythonPackage = New-FrozenPythonPackage `
    -SourceRoot $repoRoot -CodeRoot $frozenCodeRoot -RelativePaths $frozenPythonRelativePaths
$bundleDocument = Get-Content -LiteralPath $bundleMetadataInput -Raw -Encoding UTF8 |
    ConvertFrom-Json
$liveBundleRoot = [IO.Path]::GetFullPath((Split-Path -Parent $bundleMetadataInput))
$frozenBundleRoot = Join-Path $inputDir 'paired_bundle'
New-Item -ItemType Directory -Path $frozenBundleRoot -Force | Out-Null
foreach ($entry in $bundleDocument.artifacts) {
    $relativePath = [string]$entry.relative_path
    $sourceArtifact = [IO.Path]::GetFullPath((Join-Path $liveBundleRoot $relativePath))
    if (-not $sourceArtifact.StartsWith(
        $liveBundleRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
        throw "Paired particle artifact escapes its bundle root: $relativePath"
    }
    $frozenArtifact = Join-Path $frozenBundleRoot $relativePath
    Copy-VerifiedRunInput -Source $sourceArtifact -Destination $frozenArtifact |
        Out-Null
}
$frozenBundleMetadata = Join-Path $frozenBundleRoot 'paired_particle_bundle.json'
Copy-VerifiedRunInput -Source $bundleMetadataInput -Destination $frozenBundleMetadata |
    Out-Null
$frozenPythonExecution = Invoke-IsolatedFrozenPythonModule `
    -Python $python -Package $frozenPythonPackage `
    -Module `
    'projects.rf_multipole_ion_optics.workflows.interface_readiness.generate_particle_table' `
    -Arguments @(
        '--source-family',$frozenSourceFamily,
        '--distribution',$frozenDistribution,
        '--resolved-design',$frozenResolved,
        '--validate-bundle',$frozenBundleMetadata
    ) -DistributionNames @('numpy') -RequiredModuleNames @(
        'projects.rf_multipole_ion_optics.workflows',
        'projects.rf_multipole_ion_optics.workflows.interface_readiness',
        'projects.rf_multipole_ion_optics.workflows.interface_readiness.generate_particle_table',
        'projects.rf_multipole_ion_optics.workflows.interface_readiness.particle_source_policy',
        'projects.rf_multipole_ion_optics.analysis.paired_particle_source_bundle',
        'common.contracts.particle_physics',
        'common.contracts.particle_count_policy',
        'common.contracts.file_identity',
        'common.ion_release',
        'common.ion_release.numpy_ion11_box',
        'projects.rf_multipole_ion_optics.core',
        'projects.rf_multipole_ion_optics.core.interface_geometry',
        'projects.rf_multipole_ion_optics.runtime.particle_source_preflight'
    ) -ForbiddenRoots @($repoRoot,$projectRoot)
$frozenParticlePolicy = Get-FrozenPythonPackageFile `
    -Package $frozenPythonPackage -RelativePath `
    'projects/rf_multipole_ion_optics/workflows/interface_readiness/particle_source_policy.py'
$frozenParticleGenerator = Get-FrozenPythonPackageFile `
    -Package $frozenPythonPackage -RelativePath `
    'projects/rf_multipole_ion_optics/workflows/interface_readiness/generate_particle_table.py'
$frozenBundleMechanism = Get-FrozenPythonPackageFile `
    -Package $frozenPythonPackage -RelativePath `
    'projects/rf_multipole_ion_optics/analysis/paired_particle_source_bundle.py'
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
$sourceMetadata = Join-Path $inputDir 'particle_source_metadata.json'
Push-Location $repoRoot
try {
    $sourceFamilySha = Get-RunFileSha256 -Path $frozenSourceFamily
    $requestedParticles = @(Import-Csv -LiteralPath $sourceParticlePath).Count
    $bindingArguments = @(
        '-m','projects.rf_multipole_ion_optics.analysis.validate_paired_particle_source_binding',
        '--bundle-metadata',$bundleMetadataInput,
        '--source-family',$frozenSourceFamily,
        '--distribution',$frozenDistribution,
        '--resolved-design',$frozenResolved,
        '--operating-point',$OperatingPoint,
        '--particle-count',$requestedParticles,
        '--consumed-representation','canonical10',
        '--expected-consumed',$sourceParticlePath,
        '--output',$sourceBinding
    )
    & $python @bindingArguments
    if ($LASTEXITCODE -ne 0) { throw 'Paired particle source bundle binding failed.' }
    $bindingDocument = Get-Content -LiteralPath $sourceBinding -Raw -Encoding UTF8 | ConvertFrom-Json
    $canonicalEntry = @($bundleDocument.artifacts | Where-Object {
        $_.operating_point_id -eq $OperatingPoint -and
        [int]$_.particle_count -eq $requestedParticles -and
        $_.representation -eq 'canonical10'
    })
    $ionEntry = @($bundleDocument.artifacts | Where-Object {
        $_.operating_point_id -eq $OperatingPoint -and
        [int]$_.particle_count -eq $requestedParticles -and
        $_.representation -eq 'ion11'
    })
    if ($canonicalEntry.Count -ne 1 -or $ionEntry.Count -ne 1) {
        throw 'Frozen paired bundle selection is not unique.'
    }
    $particlePath = Join-Path $frozenBundleRoot ([string]$canonicalEntry[0].relative_path)
    $frozenIonPath = Join-Path $frozenBundleRoot ([string]$ionEntry[0].relative_path)
    $frozenBindingArguments = @(
        '-m','projects.rf_multipole_ion_optics.analysis.validate_paired_particle_source_binding',
        '--bundle-metadata',$frozenBundleMetadata,
        '--source-family',$frozenSourceFamily,
        '--distribution',$frozenDistribution,
        '--resolved-design',$frozenResolved,
        '--operating-point',$OperatingPoint,
        '--particle-count',$requestedParticles,
        '--consumed-representation','canonical10',
        '--expected-consumed',$particlePath,
        '--output',$sourceBinding
    )
    & $python @frozenBindingArguments
    if ($LASTEXITCODE -ne 0) { throw 'Frozen paired particle source bundle binding failed.' }
    $bindingDocument = Get-Content -LiteralPath $sourceBinding -Raw -Encoding UTF8 | ConvertFrom-Json
    $preflightArguments = @(
        '-m','projects.rf_multipole_ion_optics.runtime.particle_source_preflight',
        '--source',$particlePath,
        '--resolved-design',$frozenResolved,
        '--source-family',$frozenSourceFamily,
        '--operating-point',$OperatingPoint,
        '--expected-source-family-sha256',$sourceFamilySha,
        '--output',$sourceMetadata
    )
    & $python @preflightArguments
    if ($LASTEXITCODE -ne 0) { throw 'Canonical particle source preflight failed.' }
    $sourceMetadataDocument = Get-Content -LiteralPath $sourceMetadata -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedParticles = [int]$sourceMetadataDocument.particle_count
    if (-not $Exploration -and $expectedParticles -lt $minimumParticles) {
        throw "Formal interface readiness requires at least $minimumParticles particles."
    }
    $sourceProjectionArguments = @(
        '-m','projects.rf_multipole_ion_optics.runtime.simion_particle_source',
        '--particles',$particlePath,
        '--resolved-design',$frozenResolved,
        '--source-family',$frozenSourceFamily,
        '--operating-point',$OperatingPoint,
        '--expected-source-family-sha256',$sourceFamilySha,
        '--fly2',$flyPath,
        '--source-states-lua',$sourceStatesLua
    )
    Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenPythonPackage `
        -Module 'projects.rf_multipole_ion_optics.runtime.simion_particle_source' `
        -Arguments @($sourceProjectionArguments|Select-Object -Skip 2) -ForbiddenRoots @($repoRoot,$projectRoot)|Out-Null
} finally { Pop-Location }


$resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 | ConvertFrom-Json
$interface = Get-Content -LiteralPath $frozenInterface -Raw -Encoding UTF8 | ConvertFrom-Json
$numericalContract = Get-Content -LiteralPath $frozenNumericalContract -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PSBoundParameters.ContainsKey('RfStepsPerPeriod')) {
    $RfStepsPerPeriod = [int]$numericalContract.baseline_rf_steps_per_period
}
if (-not $PSBoundParameters.ContainsKey('TrajectoryQuality')) {
    $TrajectoryQuality = [int]$numericalContract.trajectory_quality
}
if ($RfStepsPerPeriod -lt 1 -or $TrajectoryQuality -lt 1) {
    throw 'SIMION interface numerics must be positive.'
}
$particleStateCsv = Join-Path $resultDir 'particle_state.csv'
$trajectoryCsv = Join-Path $resultDir 'trajectory_samples.csv'
$summaryJson = Join-Path $resultDir 'solver_summary.json'
$runConfigLua = Join-Path $runDir 'run_config.lua'
$iobReport = Join-Path $logDir 'simion_iob_contract.txt'
$stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
$coreConfig = New-RfSimionCoreRunConfig `
    -ResolvedDesign $resolved -InterfaceContract $interface -SolverNumerics $numericalContract `
    -RfStepsPerPeriod $RfStepsPerPeriod -TrajectoryQuality $TrajectoryQuality `
    -ModeName $mode -OperatingPoint $OperatingPoint `
    -IobPath (Join-Path $candidateDir 'quad_monolithic.iob') -Fly2Path $flyPath `
    -SourceStatesLua $sourceStatesLua -ParticleStateCsv $particleStateCsv `
    -TrajectoryCsv $trajectoryCsv -SummaryJson $summaryJson
$dispatchRequest = Join-Path $inputDir 'simion_dispatch_request.json'
$dispatchPlan = Join-Path $inputDir 'simion_repository_dispatch_plan.json'
$resourceProfiles = Join-Path $inputDir 'simion_resource_profiles.json'
$batchPlan = Join-Path $inputDir 'simion_execution_batch_plan.json'
[ordered]@{
    solver = 'SIMION'; field_kind = 'rf'; particle_count = $expectedParticles
    independent_particles = $true
    frontend_cell_mm_xyz = @([double]$numericalContract.simion_cell_mm,[double]$numericalContract.simion_cell_mm,[double]$numericalContract.simion_cell_mm)
    trajectory_quality = [int]$coreConfig.trajectory_quality
    rf_steps_per_period = [int]$coreConfig.rf_steps_per_period
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $dispatchRequest -Encoding UTF8
Push-Location $repoRoot
try {
    & $python -m common.simion.resource_profile discover --runs-root (Join-Path $artifactRoot 'runs') --output $resourceProfiles
    if ($LASTEXITCODE -ne 0) { throw 'SIMION resource profile discovery failed.' }
    & $python -m common.simion.resource_scheduler --request $dispatchRequest --profiles $resourceProfiles --output $dispatchPlan
    if ($LASTEXITCODE -ne 0) { throw 'SIMION repository dispatch planning failed.' }
} finally { Pop-Location }
$dispatchPlanDocument = Get-Content -LiteralPath $dispatchPlan -Raw -Encoding UTF8 | ConvertFrom-Json
if ($dispatchPlanDocument.role -ne 'simion_repository_dispatch_plan' -or
    [int]$dispatchPlanDocument.particle_count -ne $expectedParticles -or
    @($dispatchPlanDocument.waves).Count -ne 1 -or [int]$dispatchPlanDocument.waves[0].batch_count -lt 1) {
    throw 'SIMION repository dispatch plan differs from the canonical source population.'
}
& $python -m common.simion.particle_batching --from-dispatch-plan $dispatchPlan `
    --output $batchPlan
if ($LASTEXITCODE -ne 0) { throw 'SIMION shared particle batch planning failed.' }
$batchPlanDocument = Get-Content -LiteralPath $batchPlan -Raw -Encoding UTF8 | ConvertFrom-Json
if ([int]$batchPlanDocument.particle_count -ne $expectedParticles) {
    throw 'SIMION particle batch plan differs from the canonical source population.'
}
$RfPeakV = [double]$coreConfig.rf_peak_v
$FrequencyHz = [double]$coreConfig.frequency_hz
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_simion_run_config'; run_id=$RunId
    project='rf_multipole_ion_optics'; mode=$mode; project_root=$projectRoot
    inputs=[ordered]@{published_design_freshness=$publishedDesignFreshnessPath;resolved_design=$frozenResolved; interface_contract=$frozenInterface; mode=$frozenMode; numerical_contract=$frozenNumericalContract; particle_table=$particlePath; source_states=$sourceStatesLua;
        simion_layout_template_resolution=$templateResolution;simion_layout_template_registry=$templateRegistry;
        simion_layout_registration_manifest=$templateManifest;simion_layout_template_iob=$templateIob;
        simion_layout_template_con=$templateCon;simion_layout_template_placeholder_pa0=$template.placeholder_pa0}
    output_dir=$resultDir; candidate_dir=$candidateDir; run_dir=$runDir
    rf_steps_per_period=$coreConfig.rf_steps_per_period
    trajectory_quality=$coreConfig.trajectory_quality
    source_axial_offset_mm=0.0; operating_point=$OperatingPoint
    rf_peak_v=$coreConfig.rf_peak_v; dc_amplitude_v=$coreConfig.dc_amplitude_v
    frequency_hz=$coreConfig.frequency_hz; waveform=$coreConfig.waveform
    parent_resolved_design_sha256=$coreConfig.parent_resolved_design_sha256; particles=$expectedParticles
}
$runConfig.inputs.source_ion11 = $frozenIonPath
$runConfig.inputs.source_canonical10 = $particlePath
$runConfig.inputs.consumed_particle_table = $particlePath
$runConfig.inputs.particle_bundle_metadata = $frozenBundleMetadata
$runConfig.inputs.particle_source_binding = $sourceBinding
$runConfig.inputs.particle_source_family = $frozenSourceFamily
$runConfig.inputs.particle_source_distribution = $frozenDistribution
$runConfig.inputs.particle_source_policy = $frozenParticlePolicy
$runConfig.inputs.particle_source_generator = $frozenParticleGenerator
$runConfig.inputs.paired_particle_source_mechanism = $frozenBundleMechanism
$runConfig.inputs.frozen_python_package_support = $frozenPythonSupport
$runConfig.inputs.particle_source_metadata = $sourceMetadata
$runConfig.inputs.simion_iob_builder = $iobBuilder
$runConfig.inputs.simion_program_source = $programSource
$runConfig.inputs.simion_rf_drive_kernel=$rfDriveKernel
$runConfig.inputs.simion_gem=Join-Path $candidateDir 'quad_monolithic.gem'
$runConfig.inputs.simion_gem_include=Join-Path $candidateDir 'quad_include.gem'
$runConfig.inputs.simion_fly2=$flyPath
$runConfig.inputs.simion_dispatch_request = $dispatchRequest
$runConfig.inputs.simion_resource_profiles = $resourceProfiles
$runConfig.inputs.simion_repository_dispatch_plan = $dispatchPlan
$runConfig.inputs.simion_execution_batch_plan = $batchPlan
$runConfig.execution_batch_count = [int]$batchPlanDocument.batch_count
$frozenCodeIndex = 0
foreach ($entry in $frozenPythonPackage.files) {
    $frozenCodeIndex += 1
    $runConfig.inputs[("frozen_python_code_{0:D3}" -f $frozenCodeIndex)] = `
        [string]$entry.path
}
$bundleArtifactIndex = 0
foreach ($entry in $bundleDocument.artifacts) {
    $bundleArtifactIndex += 1
    $runConfig.inputs[("bundle_artifact_{0:D3}" -f $bundleArtifactIndex)] = Join-Path `
        $frozenBundleRoot ([string]$entry.relative_path)
}
$runConfig.provenance = [ordered]@{
    source_sample_family_sha256 = [string]$bindingDocument.source_sample_family_sha256
    source_family_sha256 = [string]$bindingDocument.source_family_sha256
    distribution_sha256 = [string]$bindingDocument.distribution_sha256
    latent_sha256 = [string]$bindingDocument.latent_sha256
    coordinate_mapping_version = [string]$bindingDocument.coordinate_mapping_version
    representation_equivalence = [string]$bindingDocument.representation_equivalence
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
    minimum_diagnostic_particles = $minimumParticles
    minimum_transmission = $minimumTransmission
    operating_point_id = $OperatingPoint
    particle_count = $expectedParticles
    representation = 'canonical10'
    consumed_sha256 = [string]$bindingDocument.consumed_sha256
    particle_source_sha256 = [string]$bindingDocument.consumed_sha256
    ion11_sha256 = [string]$bindingDocument.ion11_sha256
    canonical10_sha256 = [string]$bindingDocument.canonical10_sha256
    n1000_parent = $bindingDocument.n1000_parent
    ion11_n1000_parent = $bindingDocument.ion11_n1000_parent
    canonical10_n1000_parent = $bindingDocument.canonical10_n1000_parent
    simion_layout_template = [ordered]@{
        template_id = [string]$templateProfile.template_id
        registration_run_id = [string]$templateProfile.registration_run_id
        registry_sha256 = [string]$templateProfile.registry_sha256
        registration_manifest_sha256 = [string]$templateProfile.run_manifest.sha256
        iob_sha256 = [string]$templateProfile.bundle.iob.sha256
        con_sha256 = [string]$templateProfile.bundle.con.sha256
    }
}
$runConfig.frozen_python = [ordered]@{
    package = $frozenPythonPackage
    execution = $frozenPythonExecution
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
Write-RfSimionPreparedFlyIdentity -CoreConfig $coreConfig -CaseName 'interface_readiness' `
    -Path $runConfig.inputs.simion_fly_physics -SourcePackage $frozenPythonPackage -ProgramSourcePath $programSource `
    -NativeFlyArguments @(Get-RfSimionFlyArgumentIdentity -CoreConfig $coreConfig) `
    -SourceRelativePaths @('projects/rf_multipole_ion_optics/runtime/simion_particle_source.py',
        'projects/rf_multipole_ion_optics/runtime/particle_source_preflight.py',
        'projects/rf_multipole_ion_optics/core/interface_geometry.py',
        'common/simion/particle_source.py','common/contracts/particle_physics.py',
        'common/contracts/particle_count_policy.py','common/contracts/particle_count_policy.json')
$lifecycle=Get-Content -LiteralPath $runConfigPath -Raw|ConvertFrom-Json -AsHashtable
foreach($key in @('artifact_retention','capacity_ledger_lifecycle')){if($lifecycle.ContainsKey($key)){$runConfig[$key]=$lifecycle[$key]}}
$runConfig.schema_version=$lifecycle.schema_version
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
if($ContinuationPredecessorManifestPath){
    $continuation=Initialize-RfSimionPreparedContinuation -ManifestPath $ContinuationPredecessorManifestPath `
        -RunDir $package.artifact_run_dir -ArtifactRoot (Split-Path (Split-Path $artifactRoot -Parent) -Parent) `
        -PythonExe $python -RepositoryRoot $repoRoot -RunConfig $runConfig -RunConfigPath $runConfigPath `
        -CapacityOwner ("run-artifact-workflow:rf_multipole_ion_optics:{0}"-f$RunId) -CaseName 'interface_readiness' -BatchPlanPath $batchPlan -DispatchPlanPath $dispatchPlan `
        -InputNames @('resolved_design','particle_table','simion_field_identity',
            'simion_program_source','simion_rf_drive_kernel','simion_iob_builder','simion_gem','simion_gem_include','simion_fly2','source_states',
            'simion_layout_template_iob','simion_layout_template_con')
    $batchPlanDocument=Get-Content -LiteralPath $batchPlan -Raw|ConvertFrom-Json
    $dispatchPlanDocument=Get-Content -LiteralPath $dispatchPlan -Raw|ConvertFrom-Json
}
$luaConfig = ConvertTo-RfSimionLuaConfig -CoreConfig $coreConfig `
    -SharedProgramPath $programSource
# Windows PowerShell 5.1 writes a BOM for -Encoding UTF8; SIMION's Lua 5.1
# parser treats that BOM as source text.  This generated table is ASCII-only.
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

function New-InterfaceBatchRuns {
  param([Parameter(Mandatory)]$PlanDocument,[bool]$ReuseFirst=$false)
  $runs=@();$singleComplete=([int]$PlanDocument.batch_count-eq1-and
    [string]$PlanDocument.coverage-eq'complete_population')
  foreach ($batch in @($PlanDocument.batches)) {
    $batchIndex = [int]$batch.index
    $batchSuffix = 'batch_{0:D2}' -f $batchIndex
    $batchFly = if ($singleComplete) { $flyPath } else { Join-Path $candidateDir ("quad_monolithic__$batchSuffix.fly2") }
    $batchStates = if ($singleComplete) { $sourceStatesLua } else { Join-Path $inputDir ("source_states__$batchSuffix.lua") }
    $batchState = if ($singleComplete) { $particleStateCsv } else { Join-Path $resultDir ("particle_state__$batchSuffix.csv") }
    $batchTrajectory = if ($singleComplete) { $trajectoryCsv } else { Join-Path $resultDir ("trajectory_samples__$batchSuffix.csv") }
    $batchSummary = if ($singleComplete) { $summaryJson } else { Join-Path $resultDir ("solver_summary__$batchSuffix.json") }
    $batchLua = if ($singleComplete) { $runConfigLua } else { Join-Path $inputDir ("simion_run_config__$batchSuffix.lua") }
    $batchLogDir = if ($singleComplete) { $logDir } else { Join-Path $logDir $batchSuffix }
    if (-not $singleComplete -and -not ($ReuseFirst -and $batchIndex -eq 1)) {
        New-Item -ItemType Directory -Path $batchLogDir -Force | Out-Null
        $batchArguments = @($sourceProjectionArguments) + @(
            '--particle-id-min',([string]$batch.particle_id_min),
            '--particle-id-max',([string]$batch.particle_id_max),
            '--simion-particle-id-offset',([string]$batch.simion_particle_id_offset)
        )
        $flyArgumentIndex = [array]::IndexOf($batchArguments, '--fly2')
        $statesArgumentIndex = [array]::IndexOf($batchArguments, '--source-states-lua')
        $batchArguments[$flyArgumentIndex + 1] = $batchFly
        $batchArguments[$statesArgumentIndex + 1] = $batchStates
        Push-Location $repoRoot
        try {
            Invoke-IsolatedFrozenPythonModule -Python $python -Package $frozenPythonPackage `
                -Module 'projects.rf_multipole_ion_optics.runtime.simion_particle_source' `
                -Arguments @($batchArguments|Select-Object -Skip 2) -ForbiddenRoots @($repoRoot,$projectRoot)|Out-Null
        } finally { Pop-Location }
    }
    $batchConfig = New-RfSimionCoreRunConfig `
        -ResolvedDesign $resolved -InterfaceContract $interface -SolverNumerics $numericalContract `
        -RfStepsPerPeriod $RfStepsPerPeriod -TrajectoryQuality $TrajectoryQuality `
        -ModeName $mode -OperatingPoint $OperatingPoint -IobPath ([string]$coreConfig.iob) `
        -Fly2Path $batchFly -SourceStatesLua $batchStates -ParticleStateCsv $batchState `
        -TrajectoryCsv $batchTrajectory -SummaryJson $batchSummary
    if (-not $singleComplete -and -not ($ReuseFirst -and $batchIndex -eq 1)) {
        (ConvertTo-RfSimionLuaConfig -CoreConfig $batchConfig `
            -SharedProgramPath $programSource) |
            Set-Content -LiteralPath $batchLua -Encoding ASCII
    }
    $runs += [pscustomobject]@{
        batch = $batch; config = $batchConfig; fly = $batchFly; states = $batchStates
        state = $batchState; trajectory = $batchTrajectory; summary = $batchSummary; lua = $batchLua
        log_dir = $batchLogDir; name = ('interface_readiness_' + $batchIndex)
        merged_state = $particleStateCsv; merged_trajectory = $trajectoryCsv; merged_summary = $summaryJson
    }
  }
  return @($runs)
}
Set-RfSimionExecutionPhase -Context $execution -Name flight
$batchRuns=@(New-InterfaceBatchRuns -PlanDocument $batchPlanDocument)
$resourceUsage = Join-Path $resultDir 'simion_resource_usage.json'

$waveArguments = @{
    HostLease=$hostExecutionLease; SimionExe=$simion; CandidateDir=$candidateDir
    IobPath=[string]$coreConfig.iob; RootFly2Path=[string]$coreConfig.fly2
    IobBuilderScript=$iobBuilder; ProgramSourcePath=$programSource; RootRunConfigLua=$runConfigLua
    InspectScript=$inspectScript; IobReport=$iobReport; LogDir=$logDir
    TrajectoryQuality=[int]$coreConfig.trajectory_quality; RfStepsPerPeriod=[int]$coreConfig.rf_steps_per_period
    BatchRuns=$batchRuns; BatchPlanPath=$batchPlan; DispatchPlanPath=$dispatchPlan
    RunDir=$runDir; UsagePath=$resourceUsage; PythonExe=$python; RepositoryRoot=$repoRoot
    CaseName='interface_readiness';CompletionOutputs=$completedBatchOutputs
    Prepared=$true;NativeOperations=$nativePreparation
    RfDriveKernelPath=$rfDriveKernel
}
if($null-ne$continuation){$waveArguments.ContinuationUnits=$continuation.units;$waveArguments.ContinuationRequested=$true}
$wave = Invoke-RfSimionAdaptiveBatchWave -WaveArguments $waveArguments -BatchRuns ([ref]$batchRuns) `
    -DispatchPlan $dispatchPlanDocument `
    -DispatchRequestPath $dispatchRequest -ResourceProfilesPath $resourceProfiles `
    -RunConfig $runConfig -RunConfigPath $runConfigPath `
    -PrepareReplannedBatches { param($plan) New-InterfaceBatchRuns -PlanDocument $plan -ReuseFirst $true }
$hostExecutionLease=$wave.lease; $batchRuns=@($wave.batches)
$waveReceipt=$wave.receipt; $resourceProfile=$wave.resource_profile
Set-RfSimionExecutionPhase -Context $execution -Name analysis

$summary = Get-Content -LiteralPath $summaryJson -Raw | ConvertFrom-Json
if ($summary.particles -ne $expectedParticles -or $summary.collision_model -ne 'none' -or
    $summary.parent_resolved_design_sha256 -cne $coreConfig.parent_resolved_design_sha256) {
    throw "SIMION transport execution integrity failed: $($summary | ConvertTo-Json -Compress)"
}
$dataValidity='valid_raw_outputs'
$physicalDecision = if ($summary.transmission -ge $minimumTransmission) { 'PASS' } else { 'FAIL' }
Push-Location $repoRoot
try { & $python -m common.contracts.particle_state `
    --state $particleStateCsv --particles $particlePath `
    --source-format canonical --contract $frozenInterface `
    --axial-offset-mm 0.0 --frequency-hz $FrequencyHz `
    --phase-rad ([double]$coreConfig.phase_rad) `
    --solver SIMION --output $stateContractReport } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Particle-state contract gate failed.' }
$shaPath = Join-Path $candidateDir 'SHA256SUMS.csv'
Write-RunDirectoryChecksumInventory -Directory $candidateDir -OutputPath $shaPath `
    -ExcludedPatterns @('trj*.tmp')
Set-RfSimionExecutionPhase -Context $execution -Name finalize
$executionStatus='completed';$dataValidity='valid';$scienceStatus=if($physicalDecision-eq'PASS'){'functional_pass'}else{'functional_fail'}
$rootSummary = [ordered]@{
    execution_status=$executionStatus;data_validity=$dataValidity;science_status=$scienceStatus
    failure_stage=$null;reason=$null;recovery_action=$null;result_path=$ResultPath
    phase_seconds=$execution.phase_seconds;elapsed_seconds=$execution.elapsed_seconds;timing_scope='through_terminal_publication_preparation'
    schema_version=1;role='rf_quadrupole_transport_summary';status='success';mode=$mode
    physical_decision=$physicalDecision
    numerics_qualification = Get-RfSimionNumericsQualification `
        -SolverNumerics $numericalContract `
        -RfStepsPerPeriod ([int]$coreConfig.rf_steps_per_period) `
        -TrajectoryQuality ([int]$coreConfig.trajectory_quality) `
        -Exploration ([bool]$Exploration)
    particles=$expectedParticles;hits=$summary.hits;transmission=$summary.transmission
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
    $flyPath,$iobReport,$shaPath,$runSummary
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
    -ResourceUsagePaths @(@($resourceUsage)|Where-Object{$_-and(Test-Path -LiteralPath $_)}|ForEach-Object{@{case_name='interface_readiness';path=$_}})
$deferFinalization=$false;$ownerCapacity=$null
$hostExecutionOutcome = 'success'
"EXECUTION=PASS DECISION=$physicalDecision RUN_ID=$RunId HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
}
catch {
    $interfaceFailure = $_
    if($null-eq$fieldContext-and$interfaceFailure.Exception.Data.Contains('rf_field_context')){$fieldContext=$interfaceFailure.Exception.Data['rf_field_context']}
    if($null-ne$ownerContext-and$ownerContext.completion_written){$executionStatus='finalization_failed';$failureStage='finalization';throw $interfaceFailure}
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
        }catch{$interfaceFailure.Exception.Data['field_binding_closeout_error']=[string]$_}
    }

    $executionStatus='failed';$failureStage=$execution.phase
    Set-RfSimionExecutionPhase -Context $execution
    $recovery="Use this CLI with a new -RunId and -ContinuationPredecessorManifestPath '$(Join-Path $package.artifact_run_dir 'run_manifest.json')'."
    $data = $interfaceFailure.Exception.Data
    $writerCompletionUnknown = [bool]$data['simion_first_batch_writer_unknown'] -or
        $data.Contains('rf_host_release_unconfirmed') -or $data.Contains('simion_first_batch_drain_error') -or $data.Contains('simion_wave_drain_error') -or
        ($data.Contains('simion_wave_writer_completion_confirmed') -and -not [bool]$data['simion_wave_writer_completion_confirmed'])
    if ($writerCompletionUnknown) {
        $executionStatus='writer_completion_unknown'
        $recovery='Confirm writer exit and host release, then finish owner publication before creating a continuation run.'
        try { Write-RunJson -Path $runSummary -Value @{schema_version=1;role='rf_quadrupole_transport_summary';status='writer_completion_unknown';execution_status=$executionStatus;data_validity=$dataValidity;science_status=$scienceStatus;failure_stage=$failureStage;recovery_action=$recovery;result_path=$ResultPath;phase_seconds=$execution.phase_seconds;elapsed_seconds=$execution.elapsed_seconds;timing_scope='through_failure_capture';reason=$interfaceFailure.Exception.Message;drain_error=[string]($data['simion_wave_drain_error'] ?? $data['simion_first_batch_drain_error'])} }
        catch { $interfaceFailure.Exception.Data['writer_unknown_result_error'] = [string]$_ }
        if($null-ne$ownerContext){
            try{
                $null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status failed -Summary @{} `
                    -WriterCompletion @{operations=@();resource_releases=@()} -WritersStopped $false -OriginalFailure $interfaceFailure
            }catch{if($_.Exception.Message-notmatch'native writer completion is unknown'){$interfaceFailure.Exception.Data['writer_unknown_transport_error']=[string]$_}}
        }
    } else {
        try {
            if($null-ne$ownerContext){
                $failedSummary=@{schema_version=1;role='rf_quadrupole_transport_summary';run_id=$RunId;status='failed';execution_status=$executionStatus;
                    data_validity=$dataValidity;scientific_result=$scienceStatus;failure_stage=$failureStage;failure_reason=$interfaceFailure.Exception.Message;
                    recovery_action=$recovery;result_path=$ResultPath;phase_timings_seconds=$execution.phase_seconds;elapsed_before_finalization_seconds=$execution.elapsed_seconds}
                $writers=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativePreparation -State $hostReleaseState
                $failureOutputs=@(foreach($folder in @($resultDir,$logDir,$candidateDir)){Get-ChildItem $folder -Recurse -File|Select-Object -ExpandProperty FullName})
                $deferFinalization=$true
                $null=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status failed -Summary $failedSummary -OutputPaths $failureOutputs `
                    -WriterCompletion $writers -WritersStopped $true -OriginalFailure $interfaceFailure
                $deferFinalization=$false;$ownerCapacity=$null
            }else{
                Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath -Summary $runSummary `
                    -SummaryRole 'rf_quadrupole_transport_summary' -Reason $interfaceFailure.Exception.Message -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage
            }
        }catch{if($_.Exception.Data['rf_host_release_unconfirmed']){$writerCompletionUnknown=$true};$interfaceFailure.Exception.Data['failure_closure_error']=[string]$_}

    }
    throw $interfaceFailure
} finally {
    if(-not$writerCompletionUnknown){
        try{
            if(-not$hostReleaseState.released){$null=Get-RfSimionStoppedWriterCompletion -HostLease $hostExecutionLease -NativeOperations $nativePreparation -State $hostReleaseState}
        }catch{if($null-eq$interfaceFailure){throw};$interfaceFailure.Exception.Data['host_release_error']=[string]$_}
        if($hostReleaseState.released){
            if($null-ne$fieldContext-and$null-ne$fieldContext.guard){Close-RfSimionFieldCheckpointGuard -Context $fieldContext.guard}
            if($null-ne$continuation){foreach($guard in $continuation.guards){$guard.Dispose()}}
            if($null-ne$ownerCapacity-and-not$deferFinalization){
                try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $ownerCapacity|Out-Null}
                catch{if($null-eq$interfaceFailure){throw};$interfaceFailure.Exception.Data['capacity_release_error']=[string]$_}
            }
            try{Remove-RunPackageExecutionAlias -Package $package}catch{Write-Warning "Could not remove short execution alias: $_"}
        }
    }
    Set-RfSimionExecutionPhase -Context $execution
    Write-Host "RF_EXECUTION_STATUS=$executionStatus DATA_VALIDITY=$dataValidity SCIENCE_STATUS=$scienceStatus FAILURE_STAGE=$failureStage RESULT=$ResultPath ELAPSED_SECONDS=$($execution.elapsed_seconds)"
}
