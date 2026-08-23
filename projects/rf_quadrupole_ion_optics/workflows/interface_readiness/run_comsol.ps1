param(
    [string]$RunId = '',
    [Parameter(Mandatory = $true)][string]$ParticleTablePath,
    [Parameter(Mandatory = $true)][string]$ParticleBundleMetadataPath,
    [Parameter(Mandatory = $true)][string]$SourceFamilyPath,
    [Parameter(Mandatory = $true)][string]$ParticleDistributionPath,
    [Parameter(Mandatory = $true)][string]$SolverNumericsContractPath,
    [Parameter(Mandatory = $true)][string]$SolverNumericsProfileId,
    [string]$NumericalExperimentId = '',
    [Parameter(Mandatory = $true)][string]$OperatingPoint,
    [string]$PythonExe = '',
    [switch]$ReleaseConstructionGate
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
. (Join-Path $projectRoot 'runtime\comsol_solver_numerics.ps1')
. (Join-Path $projectRoot 'runtime\frozen_python_package.ps1')
$frozenPythonRelativePaths = @(
    'projects\rf_quadrupole_ion_optics\workflows\__init__.py',
    'projects\rf_quadrupole_ion_optics\workflows\interface_readiness\__init__.py',
    'projects\rf_quadrupole_ion_optics\workflows\interface_readiness\generate_particle_table.py',
    'projects\rf_quadrupole_ion_optics\workflows\interface_readiness\particle_source_policy.py',
    'projects\rf_quadrupole_ion_optics\analysis\paired_particle_source_bundle.py',
    'projects\rf_quadrupole_ion_optics\analysis\validate_release_construction_gate.py',
    'common\contracts\particle_physics.py',
    'common\contracts\particle_count_policy.py',
    'common\contracts\particle_count_policy.json',
    'common\contracts\file_identity.py',
    'common\multipole\__init__.py',
    'common\multipole\particle_source_preflight.py'
)
$executionCapacityPaths = @('inputs/frozen_python_package.ps1') +
    (Get-FrozenPythonPackageExecutionPaths -RelativePaths $frozenPythonRelativePaths)

$workflowId = 'transport_interface_readiness'
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = if($ReleaseConstructionGate){
        (Get-Date -Format 'yyyyMMdd_HHmmss') +
            '__test__comsol__rf-release-construction__n100'
    }else{
        (Get-Date -Format 'yyyyMMdd_HHmmss') +
            '__sim__comsol__rf-transport__interface-readiness'
    }
}
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_quadrupole_ion_optics' -Mode $workflowId `
    -Software $software -AdditionalDirectories @('comsol','runtime') -UseShortExecutionPath `
    -ExpectedExecutionRelativePaths $executionCapacityPaths
$runDir,$inputDir,$resultDir,$logDir = $package.run_dir,$package.input_dir,
    $package.result_dir,$package.log_dir
$candidateDir,$runtimeDir = (Join-Path $runDir 'comsol'),(Join-Path $runDir 'runtime')
$bootstrapReport = Join-Path $logDir 'comsol_bootstrap_report.txt'
$guiVerifyReport = Join-Path $logDir 'comsol_gui_compute_report.txt'
$stateContractReport = Join-Path $resultDir 'particle_state_contract.json'
$releaseGateBreadcrumbs = Join-Path $logDir 'release_construction_breadcrumbs.jsonl'
$releaseGateResult = Join-Path $resultDir 'release_construction_gate.json'
$releaseGateValidation = Join-Path $resultDir `
    'release_construction_gate_validation.json'
$releaseGateModel = Join-Path $candidateDir `
    'rf_quadrupole_ion_optics__release-construction-gate.mph'
$summaryRole = if ($ReleaseConstructionGate) {
    'rf_release_construction_gate_summary'
} else {
    'rf_quadrupole_transport_summary'
}
$environmentNames = @('RFQUAD_RUN_CONFIG','RFQUAD_COMSOL_MODEL_PATH',
    'RFQUAD_EXPECTED_PARTICLES','RFQUAD_EXPECTED_HITS',
    'RFQUAD_EXPECTED_RF_PEAK_V','RFQUAD_EXPECTED_FREQUENCY_HZ')
$environmentSnapshot = Save-RunEnvironment -Names $environmentNames
$failureStage = 'freeze_inputs'

try {
    $officialNumerics = Join-Path $projectRoot 'config\comsol_solver_numerics.json'
    $liveParticleTable = [IO.Path]::GetFullPath($ParticleTablePath)
    $liveBundleMetadata = [IO.Path]::GetFullPath($ParticleBundleMetadataPath)
    $liveSourceFamily = [IO.Path]::GetFullPath($SourceFamilyPath)
    $liveDistribution = [IO.Path]::GetFullPath($ParticleDistributionPath)
    $liveNumerics = if ([IO.Path]::IsPathRooted($SolverNumericsContractPath)) {
        [IO.Path]::GetFullPath($SolverNumericsContractPath)
    } else {
        [IO.Path]::GetFullPath((Join-Path $repoRoot $SolverNumericsContractPath))
    }
    $frozenNumerics = Copy-VerifiedRunInput -Source $officialNumerics `
        -Destination (Join-Path $inputDir 'comsol_solver_numerics.json')
    $numericsCompilation = Compile-RfComsolSolverNumerics `
        -OfficialContractPath $frozenNumerics `
        -RequestedContractPath $liveNumerics `
        -ProfileId $SolverNumericsProfileId `
        -ExperimentAuthorizationId $NumericalExperimentId
    $compiledNumerics = $numericsCompilation.compiled
    foreach ($source in @($liveParticleTable,$liveBundleMetadata,
        $liveSourceFamily,$liveDistribution)) {
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required interface input is missing: $source"
        }
    }

    $frozenResolved = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'config\resolved_design_official.json') `
        -Destination (Join-Path $inputDir 'resolved_design_official.json')
    $frozenScientificMode = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'config\modes\transport_interface_readiness.json') `
        -Destination (Join-Path $inputDir 'transport_interface_readiness.json')
    $frozenInterface = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'config\interface_contract.json') `
        -Destination (Join-Path $inputDir 'interface_contract.json')
    $frozenSourceFamily = Copy-VerifiedRunInput -Source $liveSourceFamily `
        -Destination (Join-Path $inputDir 'particle_source_family.json')
    $frozenDistribution = Copy-VerifiedRunInput -Source $liveDistribution `
        -Destination (Join-Path $inputDir 'particle_source_distribution.json')
    $frozenPythonSupport = Copy-VerifiedRunInput `
        -Source (Join-Path $projectRoot 'runtime\frozen_python_package.ps1') `
        -Destination (Join-Path $inputDir 'frozen_python_package.ps1')
    $frozenCodeRoot = Join-Path $inputDir 'code'
    $frozenPythonPackage = New-FrozenPythonPackage `
        -SourceRoot $repoRoot -CodeRoot $frozenCodeRoot -RelativePaths $frozenPythonRelativePaths
    $frozenParticlePolicy = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_quadrupole_ion_optics/workflows/interface_readiness/particle_source_policy.py'
    $frozenParticleGenerator = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_quadrupole_ion_optics/workflows/interface_readiness/generate_particle_table.py'
    $frozenBundleMechanism = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_quadrupole_ion_optics/analysis/paired_particle_source_bundle.py'
    $frozenReleaseGateValidator = Get-FrozenPythonPackageFile `
        -Package $frozenPythonPackage -RelativePath `
        'projects/rf_quadrupole_ion_optics/analysis/validate_release_construction_gate.py'

    $bundleDocument = Get-Content -LiteralPath $liveBundleMetadata -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $bundleArtifacts = Get-RfComsolRequiredProperty -Object $bundleDocument `
        -Property 'artifacts' -Name 'paired particle bundle artifacts'
    if ($bundleArtifacts.Count -eq 0) {throw 'Paired particle bundle artifacts must not be empty.'}
    $liveBundleRoot = [IO.Path]::GetFullPath((Split-Path -Parent $liveBundleMetadata))
    $frozenBundleRoot = Join-Path $inputDir 'paired_bundle'
    New-Item -ItemType Directory -Path $frozenBundleRoot -Force | Out-Null
    $frozenBundleMetadata = Copy-VerifiedRunInput -Source $liveBundleMetadata `
        -Destination (Join-Path $frozenBundleRoot 'paired_particle_bundle.json')
    $bundleInputPaths = [ordered]@{}
    $bundleIndex = 0
    foreach ($entry in $bundleArtifacts) {
        $relativePath=[string](Get-RfComsolRequiredProperty -Object $entry `
            -Property 'relative_path' -Name 'paired particle artifact relative_path')
        $sourceArtifact = [IO.Path]::GetFullPath((Join-Path $liveBundleRoot $relativePath))
        if (-not $sourceArtifact.StartsWith($liveBundleRoot+
            [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
            throw "Paired particle artifact escapes its bundle root: $relativePath"
        }
        $frozenArtifact = Copy-VerifiedRunInput -Source $sourceArtifact `
            -Destination (Join-Path $frozenBundleRoot $relativePath)
        $bundleIndex += 1
        $bundleInputPaths[("bundle_artifact_{0:D3}" -f $bundleIndex)] = $frozenArtifact
    }
    $frozenPythonExecution = Invoke-IsolatedFrozenPythonModule `
        -Python $python -Package $frozenPythonPackage `
        -Module `
        'projects.rf_quadrupole_ion_optics.workflows.interface_readiness.generate_particle_table' `
        -Arguments @(
            '--source-family',$frozenSourceFamily,
            '--distribution',$frozenDistribution,
            '--resolved-design',$frozenResolved,
            '--validate-bundle',$frozenBundleMetadata
        ) -DistributionNames @('numpy') -RequiredModuleNames @(
            'projects.rf_quadrupole_ion_optics.workflows',
            'projects.rf_quadrupole_ion_optics.workflows.interface_readiness',
            'projects.rf_quadrupole_ion_optics.workflows.interface_readiness.generate_particle_table',
            'projects.rf_quadrupole_ion_optics.workflows.interface_readiness.particle_source_policy',
            'projects.rf_quadrupole_ion_optics.analysis.paired_particle_source_bundle',
            'common.contracts.particle_physics',
        'common.contracts.particle_count_policy',
        'common.contracts.file_identity',
        'common.multipole',
            'common.multipole.particle_source_preflight'
        ) -ForbiddenRoots @($repoRoot,$projectRoot)

    $ionEntry = @($bundleArtifacts | Where-Object {
        $_.operating_point_id -eq $OperatingPoint -and
        [IO.Path]::GetFullPath((Join-Path $liveBundleRoot ([string]$_.relative_path))) -eq
            $liveParticleTable -and
        $_.representation -eq 'ion11'
    })
    if ($ionEntry.Count-ne 1){throw 'Explicit particle table is not one unique ION11 bundle artifact.'}
    $expectedParticles = [int]$ionEntry[0].particle_count
    $canonicalEntry = @($bundleArtifacts | Where-Object {
        $_.operating_point_id -eq $OperatingPoint -and
        [int]$_.particle_count -eq $expectedParticles -and
        $_.representation -eq 'canonical10'
    })
    if ($canonicalEntry.Count-ne 1){throw 'The paired canonical10 bundle artifact is not unique.'}
    $particleTable = Join-Path $frozenBundleRoot ([string]$ionEntry[0].relative_path)
    $frozenCanonicalPath = Join-Path $frozenBundleRoot `
        ([string]$canonicalEntry[0].relative_path)
    $actualParticleCount = @(
        Get-Content -LiteralPath $particleTable -Encoding UTF8 |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    ).Count
    if ($actualParticleCount-ne$expectedParticles){throw 'Frozen ION11 row count differs from metadata.'}
    & $python -m common.contracts.particle_count_policy --count $expectedParticles
    if($LASTEXITCODE-ne 0){throw 'Particle table violates the repository N=100/N=1000 policy.'}
    if($ReleaseConstructionGate -and $expectedParticles-ne 100){
        throw 'Release-construction gate requires exactly N=100.'}

    $mode = Get-Content -LiteralPath $frozenScientificMode -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if([string]$mode.mode-cne$workflowId -or
       [string]$mode.physics.collision_model-cne'none' -or
       [bool]$mode.physics.mass_filter_dc -or [bool]$mode.physics.space_charge){
        throw 'Frozen interface scientific mode is not RF-only no-collision transport.'
    }
    if ($mode.numerics.PSObject.Properties['maximum_time_us'] -or
        $mode.numerics.PSObject.Properties['comsol_rf_steps_per_period'] -or
        $mode.numerics.PSObject.Properties['comsol_mesh_auto_level']) {
        throw 'Scientific mode must not contain COMSOL solver numerics.'
    }
    $minimumParticles = [int](Get-RfComsolRequiredFiniteNumber `
        -Object $mode.numerics -Property 'minimum_diagnostic_particles' `
        -Name 'interface minimum_diagnostic_particles' -Positive -Integer)
    if($expectedParticles-lt$minimumParticles){
        throw "Interface workflow requires at least $minimumParticles particles."}
    $minimumTransmission = Get-RfComsolRequiredFiniteNumber `
        -Object $mode.candidate_acceptance_targets -Property 'minimum_transmission' `
        -Name 'interface minimum_transmission'
    $maximumRadiusFraction = Get-RfComsolRequiredFiniteNumber `
        -Object $mode.candidate_acceptance_targets `
        -Property 'maximum_allowed_radius_fraction_r0' `
        -Name 'interface maximum_allowed_radius_fraction_r0' -Positive
    if($minimumTransmission-lt 0 -or $minimumTransmission-gt 1){
        throw 'Interface minimum_transmission must be in [0, 1].'}
    $resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 |
        ConvertFrom-Json
    if ([double]$resolved.drive.dc_amplitude_V_per_group -ne 0 -or
        [double]$resolved.drive.common_mode_offset_V -ne 0 -or
        [double]$resolved.static_electrodes_V.entrance_aperture_plate_and_connector_V -ne 0 -or
        [double]$resolved.static_electrodes_V.exit_outer_enclosure_and_connector_V -ne 0 -or
        [double]$resolved.static_electrodes_V.physical_detector_V -ne 0) {
        throw 'Interface resolved design is not RF-only.'
    }

    $sourceBinding = Join-Path $inputDir 'particle_source_binding.json'
    $bindingArguments = @(
        '-m','projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding',
        '--bundle-metadata',$frozenBundleMetadata,
        '--source-family',$frozenSourceFamily,
        '--distribution',$frozenDistribution,
        '--resolved-design',$frozenResolved,
        '--operating-point',$OperatingPoint,
        '--particle-count',$expectedParticles,
        '--consumed-representation','ion11',
        '--expected-consumed',$particleTable,
        '--output',$sourceBinding
    )
    Push-Location $repoRoot
    try {
        & $python @bindingArguments
        if($LASTEXITCODE-ne 0){throw 'Frozen paired particle source bundle binding failed.'}
    } finally {
        Pop-Location
    }
    $bindingDocument = Get-Content -LiteralPath $sourceBinding -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $compiledScientificSpec = [ordered]@{
        role='rf_quadrupole_comsol_interface_scientific_spec';workflow_id=$workflowId
        claim = 'RF-only no-collision interface transport and canonical state export'
        collision_model='none';mass_filter_dc=$false;space_charge=$false
        source_axial_offset_mm=0.0;minimum_transmission=[double]$minimumTransmission
        maximum_allowed_radius_fraction_r0=[double]$maximumRadiusFraction
        resolved_design_sha256=Get-RunFileSha256 -Path $frozenResolved
        interface_contract_sha256=Get-RunFileSha256 -Path $frozenInterface
        scientific_mode_sha256=Get-RunFileSha256 -Path $frozenScientificMode
    }
    $runConfig = [ordered]@{
        schema_version=1;role='rf_quadrupole_comsol_run_config';run_id=$RunId
        project='rf_quadrupole_ion_optics';workflow_id=$workflowId
        mode=$workflowId;project_root=$repoRoot
        inputs = [ordered]@{
            resolved_design=$frozenResolved;scientific_mode=$frozenScientificMode
            interface_contract=$frozenInterface;comsol_solver_numerics=$frozenNumerics
            particle_table=$particleTable
            consumed_particle_table=$particleTable
            source_ion11=$particleTable
            source_canonical10=$frozenCanonicalPath
            particle_bundle_metadata=$frozenBundleMetadata;particle_source_binding=$sourceBinding
            particle_source_family=$frozenSourceFamily
            particle_source_distribution=$frozenDistribution
            particle_source_policy=$frozenParticlePolicy
            particle_source_generator=$frozenParticleGenerator
            paired_particle_source_mechanism=$frozenBundleMechanism
            release_construction_gate_validator=$frozenReleaseGateValidator
            frozen_python_package_support=$frozenPythonSupport
        }
        frozen_python=[ordered]@{
            package=$frozenPythonPackage
            execution=$frozenPythonExecution
        }
        compiled_scientific_spec=$compiledScientificSpec
        compiled_solver_numerics=$compiledNumerics
        solver_numerics_contract_id=$compiledNumerics.authority.contract_id
        solver_numerics_contract_logical_sha256=$compiledNumerics.authority.logical_sha256
        solver_numerics_profile_id=$compiledNumerics.selection.profile_id
        numerical_experiment_id=$compiledNumerics.selection.numerical_experiment_id
        operating_point=$OperatingPoint;particles=$expectedParticles
        comsol_rf_steps_per_period=$compiledNumerics.trajectory.rf_steps_per_period
        comsol_mesh_auto_level=$compiledNumerics.mesh.global_auto_level
        maximum_time_us=$compiledNumerics.trajectory.maximum_time_us
        output_policy=[ordered]@{save_model=$true;write_detailed_outputs=$true}
        results_dir=$resultDir;comsol_dir=$candidateDir;logs_dir=$logDir
        runtime_dir=$runtimeDir;run_dir=$runDir;formal_gate_passed=$false
        parameters=[ordered]@{
            lifecycle_stage='inputs_frozen_and_validated'
            execution_stage=if($ReleaseConstructionGate){
                'release_construction_gate'
            }else{
                'full_particle_transport'
            }
        }
        provenance = [ordered]@{
            solver_numerics_sha256=Get-RunFileSha256 -Path $frozenNumerics
            source_sample_family_sha256=[string]$bindingDocument.source_sample_family_sha256
            source_family_sha256=[string]$bindingDocument.source_family_sha256
            distribution_sha256=[string]$bindingDocument.distribution_sha256
            latent_sha256=[string]$bindingDocument.latent_sha256
            coordinate_mapping_version=[string]$bindingDocument.coordinate_mapping_version
            representation_equivalence=[string]$bindingDocument.representation_equivalence
            operating_point_id=$OperatingPoint;particle_count=$expectedParticles
            representation='ion11';consumed_sha256=[string]$bindingDocument.consumed_sha256
            particle_source_sha256=[string]$bindingDocument.consumed_sha256
            ion11_sha256=[string]$bindingDocument.ion11_sha256
            canonical10_sha256=[string]$bindingDocument.canonical10_sha256
            n1000_parent=$bindingDocument.n1000_parent
            ion11_n1000_parent=$bindingDocument.ion11_n1000_parent
            canonical10_n1000_parent=$bindingDocument.canonical10_n1000_parent
        }
    }
    foreach ($key in $bundleInputPaths.Keys) {
        $runConfig.inputs[$key] = $bundleInputPaths[$key]
    }
    $frozenCodeIndex = 0
    foreach ($entry in $frozenPythonPackage.files) {
        $frozenCodeIndex += 1
        $runConfig.inputs[("frozen_python_code_{0:D3}" -f $frozenCodeIndex)] = `
            [string]$entry.path
    }
    Write-RunJson -Value $runConfig -Path $package.run_config
    Write-RunJson -Path $package.summary -Value ([ordered]@{
        schema_version=1;role=$summaryRole;status='interrupted'
        failure_stage='commercial_execution_not_started';threshold_result_eligible=$false
        reason='Frozen inputs and COMSOL numerics passed preflight.'
    })
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
        -RunConfig $package.run_config -Status interrupted -Software $software `
        -Outputs @($package.summary)

    $failureStage = if($ReleaseConstructionGate){
        'comsol_release_construction_gate'
    }else{
        'comsol_model_build'
    }
    $env:RFQUAD_RUN_CONFIG = $package.run_config
    $taskScript = if($ReleaseConstructionGate){
        Join-Path $projectRoot `
            'comsol\interface_readiness\run_release_construction_gate.m'
    }else{
        Join-Path $projectRoot 'workflows\interface_readiness\comsol\run_nocollision_candidate.m'
    }
    $startupAttempts = if($ReleaseConstructionGate){2}else{1}
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript $taskScript `
        -ReportPath $bootstrapReport -StartupAttempts $startupAttempts `
        -StartupReportTimeoutSeconds 120
    if($LASTEXITCODE-ne 0){
        throw 'COMSOL interface LiveLink task launcher failed.'}
    [Environment]::SetEnvironmentVariable('RFQUAD_RUN_CONFIG',$null)

    if($ReleaseConstructionGate){
        $failureStage = 'release_construction_gate_contract'
        foreach($expected in @(
            $releaseGateBreadcrumbs,
            $releaseGateResult,
            $releaseGateModel,
            $bootstrapReport
        )){
            if(-not(Test-Path -LiteralPath $expected -PathType Leaf)){
                throw "Release-construction gate output is missing: $expected"}
        }
        $gateResult=Get-Content -LiteralPath $releaseGateResult -Raw -Encoding UTF8 |
            ConvertFrom-Json
        $breadcrumbLines=@(
            Get-Content -LiteralPath $releaseGateBreadcrumbs -Encoding UTF8 |
                Where-Object{-not[string]::IsNullOrWhiteSpace($_)}
        )
        $releaseFiles=@(
            Get-ChildItem -LiteralPath $runtimeDir -File -Filter 'particle_*.txt' |
                Sort-Object Name
        )
        $expectedReleaseNames=@(
            1..100|ForEach-Object{'particle_{0:D3}.txt'-f$_}
        )
        $releaseNameDifference=@(
            Compare-Object -ReferenceObject $expectedReleaseNames `
                -DifferenceObject ([string[]]$releaseFiles.Name) -CaseSensitive
        )
        if([string]$gateResult.status-cne'success' -or
           [string]$gateResult.role-cne'rf_release_construction_gate_result' -or
           [int]$gateResult.particles-ne 100 -or
           [int]$gateResult.release_tag_count-ne 100 -or
           [int]$gateResult.release_file_count-ne 100 -or
           [int]$gateResult.birth_time_count-ne 100 -or
           [int]$gateResult.unique_birth_time_count-ne 100 -or
           [int]$gateResult.unique_release_time_expression_count-ne 100 -or
           [int]$gateResult.breadcrumb_count-ne 1000 -or
           [string]$gateResult.first_release_tag-cne'rel001' -or
           [string]$gateResult.last_release_tag-cne'rel100' -or
           -not [bool]$gateResult.stationary_study_present -or
           -not [bool]$gateResult.stationary_solver_present -or
           [bool]$gateResult.electric_force_present -or
           [bool]$gateResult.particle_study_present -or
           [bool]$gateResult.particle_solver_present){
            throw 'Release-construction gate result violates the fixed N=100 contract.'}
        if(-not [string]::Equals(
            [string]$gateResult.particle_table_sha256,
            [string]$runConfig.provenance.particle_source_sha256,
            [StringComparison]::OrdinalIgnoreCase)){
            throw 'Release-construction gate particle-table SHA-256 differs from the frozen binding.'}
        if($releaseFiles.Count-ne 100 -or $releaseNameDifference.Count-ne 0){
            throw 'Release-construction gate did not preserve particle_001..particle_100.'}
        if($breadcrumbLines.Count-ne 1000){
            throw 'Release-construction gate did not preserve all 1000 durable breadcrumbs.'}
        $gateValidationExecution=Invoke-IsolatedFrozenPythonModule `
            -Python $python -Package $frozenPythonPackage `
            -Module `
            'projects.rf_quadrupole_ion_optics.analysis.validate_release_construction_gate' `
            -Arguments @(
                '--run-config',$package.run_config,
                '--particle-table',$particleTable,
                '--breadcrumbs',$releaseGateBreadcrumbs,
                '--result',$releaseGateResult,
                '--runtime-dir',$runtimeDir,
                '--output',$releaseGateValidation
            ) -DistributionNames @() -RequiredModuleNames @(
                'projects.rf_quadrupole_ion_optics.analysis.validate_release_construction_gate'
            ) -ForbiddenRoots @($repoRoot,$projectRoot)
        if(-not(Test-Path -LiteralPath $releaseGateValidation -PathType Leaf)){
            throw 'Frozen release-construction validator did not create its report.'}
        $gateValidation=Get-Content -LiteralPath $releaseGateValidation `
            -Raw -Encoding UTF8|ConvertFrom-Json
        if([string]$gateValidation.status-cne'success' -or
           [int]$gateValidation.particles-ne 100 -or
           [int]$gateValidation.release_files-ne 100 -or
           [int]$gateValidation.release_time_expressions-ne 100 -or
           [int]$gateValidation.breadcrumbs-ne 1000){
            throw 'Frozen release-construction validator did not close Gate A artifacts.'}
        Write-RunJson -Path $package.summary -Value ([ordered]@{
            schema_version=1;role=$summaryRole;status='success'
            workflow_id=$workflowId;execution_stage='release_construction_gate'
            particles=100;release_tags=100;release_files=100
            unique_birth_times=100;unique_release_time_expressions=100
            particle_study_present=$false;particle_solver_present=$false
            threshold_result_eligible=$false
            result='results/release_construction_gate.json'
        })
        $runConfig.parameters.lifecycle_stage='complete'
        $runConfig.frozen_python.release_construction_gate_validation=`
            $gateValidationExecution
        Write-RunJson -Value $runConfig -Path $package.run_config
        $outputs=@($releaseGateModel,$releaseGateResult,$releaseGateBreadcrumbs,
            $releaseGateValidation,$bootstrapReport,$package.summary)
        $outputs+=@($releaseFiles|Select-Object -ExpandProperty FullName)
        Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
            -RunConfig $package.run_config -Status success -Software $software `
            -Outputs $outputs
        "STATUS=PASS RUN_ID=$RunId EXECUTION_STAGE=release_construction_gate RELEASE_TAGS=100"
        return
    }

    $modelPath=Join-Path $candidateDir 'rf_quadrupole_ion_optics__model.mph'
    $summaryPath=Join-Path $resultDir 'solver_summary.json'
    $trajectoryPath,$particleStatePath,$rawPhaseSpacePath =
        (Join-Path $resultDir 'trajectory_samples.csv'),
        (Join-Path $resultDir 'particle_state.csv'),(Join-Path $resultDir 'particle_raw.csv')
    foreach ($expected in @(
        $modelPath,
        $summaryPath,
        $trajectoryPath,
        $particleStatePath,
        $rawPhaseSpacePath,
        $bootstrapReport
    )) {
        if(-not(Test-Path -LiteralPath $expected -PathType Leaf)){
            throw "COMSOL interface output is missing: $expected"}
    }
    $solverSummary = Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8 |
        ConvertFrom-Json

    $failureStage = 'comsol_gui_compute_verification'
    $env:RFQUAD_COMSOL_MODEL_PATH = $modelPath
    $env:RFQUAD_EXPECTED_PARTICLES = [string]$expectedParticles
    $env:RFQUAD_EXPECTED_HITS = [string]$solverSummary.hits
    $env:RFQUAD_EXPECTED_RF_PEAK_V = [string]$resolved.drive.rf_amplitude_V_zero_to_peak_per_group
    $env:RFQUAD_EXPECTED_FREQUENCY_HZ = [string]$resolved.drive.frequency_Hz
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $projectRoot 'workflows\interface_readiness\comsol\verify_nocollision_comsol.m') `
        -ReportPath $guiVerifyReport -StartupAttempts 1
    if($LASTEXITCODE-ne 0){throw 'COMSOL GUI Compute verification failed.'}
    foreach ($name in $environmentNames | Where-Object {
        $_ -ne 'RFQUAD_RUN_CONFIG'
    }) {
        [Environment]::SetEnvironmentVariable($name,$null)
    }

    $failureStage = 'particle_state_contract'
    Push-Location $repoRoot
    try {
        & $python -m common.contracts.particle_state `
            --state $particleStatePath `
            --particles $particleTable `
            --source-format ion11 `
            --contract $frozenInterface `
            --axial-offset-mm 0 `
            --frequency-hz ([double]$resolved.drive.frequency_Hz) `
            --phase-rad ([double]$resolved.drive.phase_rad) `
            --solver COMSOL `
            --output $stateContractReport
        if($LASTEXITCODE-ne 0){throw 'Particle-state contract gate failed.'}
    } finally {
        Pop-Location
    }

    $failureStage = 'success_manifest'
    Write-RunJson -Path $package.summary -Value ([ordered]@{
        schema_version=1;role='rf_quadrupole_transport_summary';status='success'
        workflow_id=$workflowId;particles=$expectedParticles;hits=$solverSummary.hits
        transmission=$solverSummary.transmission
        mean_output_energy_eV=$solverSummary.mean_output_energy_eV
        solver_summary='results/solver_summary.json'
    })
    $runConfig.parameters.lifecycle_stage = 'complete'
    Write-RunJson -Value $runConfig -Path $package.run_config
    $outputs = @($modelPath,$summaryPath,$trajectoryPath,$particleStatePath,
        $rawPhaseSpacePath,$bootstrapReport,$guiVerifyReport,$stateContractReport,
        $package.summary)
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
        -RunConfig $package.run_config -Status success -Software $software `
        -Outputs $outputs
    "STATUS=PASS RUN_ID=$RunId HITS=$($solverSummary.hits) TRANSMISSION=$($solverSummary.transmission)"
} catch {
    $failureReason = "$failureStage`: $($_.Exception.Message)"
    try {
        Complete-FailedRun -Python $python -RepoRoot $repoRoot `
            -RunConfig $package.run_config -Summary $package.summary `
            -SummaryRole $summaryRole `
            -Reason $failureReason -Software $software
        if($ReleaseConstructionGate -and
           (Test-Path -LiteralPath $releaseGateModel -PathType Leaf)){
            $failedManifestPath=Join-Path $runDir 'run_manifest.json'
            $failedManifest=Get-Content -LiteralPath $failedManifestPath `
                -Raw -Encoding UTF8|ConvertFrom-Json
            $failedOutputs=@(
                @($failedManifest.outputs)|ForEach-Object{[string]$_.path}
            )+$releaseGateModel
            Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot `
                -RunConfig $package.run_config -Status failed `
                -Software $software -Outputs @($failedOutputs|Select-Object -Unique)
        }
    } catch {
        throw "COMSOL interface failure closure also failed: $($_.Exception.Message)"
    }
    throw
} finally {
    Restore-RunEnvironment -Names $environmentNames -Snapshot $environmentSnapshot
    try { Remove-RunPackageExecutionAlias -Package $package } catch {
        Write-Warning "Could not remove short execution alias after interface COMSOL run: $($_.Exception.Message)"
    }
}
