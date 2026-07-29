param(
    [Nullable[int]]$RfStepsPerPeriod = $null,
    [Nullable[int]]$TrajectoryQuality = $null,
    [string]$RunId = '',
    [Parameter(Mandatory=$true)][string]$ParticleTablePath,
    [Parameter(Mandatory=$true)][string]$ParticleBundleMetadataPath,
    [Parameter(Mandatory=$true)][string]$SourceFamilyPath,
    [Parameter(Mandatory=$true)][string]$ParticleDistributionPath,
    [Parameter(Mandatory=$true)][string]$SolverNumericsContractPath,
    [Parameter(Mandatory=$true)][string]$OperatingPoint,
    [string]$ArtifactRootPath = '',
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = if ($ArtifactRootPath) {
    [IO.Path]::GetFullPath($ArtifactRootPath)
} else {
    Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_ion_optics'
}
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$mode = 'transport_interface_readiness'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $projectRoot 'runtime\simion_run_config.ps1')
. (Join-Path $projectRoot 'runtime\simion_execution.ps1')
. (Join-Path $projectRoot 'runtime\frozen_python_package.ps1')
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__rf-transport__interface-readiness'
}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
    -Project 'rf_quadrupole_ion_optics' -Mode $mode -Software @('SIMION 2020','Python 3.11') `
    -AdditionalDirectories @('simion')
$runDir=$package.run_dir
$candidateDir=Join-Path $runDir 'simion'
$resultDir=$package.result_dir
$logDir=$package.log_dir
$inputDir=$package.input_dir
$runConfigPath=$package.run_config
$runSummary=$package.summary
$simion = 'C:\Program Files\SIMION-2020\simion.exe'

try {
$sourceParticlePath = [IO.Path]::GetFullPath($ParticleTablePath)
if (-not (Test-Path -LiteralPath $sourceParticlePath -PathType Leaf)) {
    throw "Particle table is missing: $sourceParticlePath"
}
$resolvedContractInput = 'config/resolved_design_official.json'
$modeInput = 'config/modes/transport_interface_readiness.json'
$expectedParticles = 0

$frozenMode = Join-Path $inputDir 'mode.json'
$frozenResolved = Join-Path $inputDir 'resolved_design.json'
$frozenInterface = Join-Path $inputDir 'interface_contract.json'
$frozenSourceFamily = Join-Path $inputDir 'particle_source_family.json'
$frozenDistribution = Join-Path $inputDir 'particle_source_distribution.json'
$sourceBinding = Join-Path $inputDir 'particle_source_binding.json'
$frozenNumericalContract = Join-Path $inputDir 'simion_solver_numerics.json'
$templateDir = Join-Path $inputDir 'simion_layout_template'
$templateResolution = Join-Path $templateDir 'resolution.json'
New-Item -ItemType Directory -Path $templateDir | Out-Null
Push-Location $repoRoot
try {
    & $python -m common.multipole.simion_layout_template --repo-root $repoRoot `
        --output $templateResolution | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Shared SIMION layout template resolution failed.' }
} finally { Pop-Location }
$templateProfile = Get-Content -LiteralPath $templateResolution -Raw -Encoding UTF8 |
    ConvertFrom-Json
$templateRegistry = Copy-VerifiedRunInput -Source $templateProfile.registry_path `
    -Destination (Join-Path $templateDir 'simion_layout_template.json')
$templateManifest = Copy-VerifiedRunInput -Source $templateProfile.run_manifest.path `
    -Destination (Join-Path $templateDir 'registration_run_manifest.json')
$templateIob = Copy-VerifiedRunInput -Source $templateProfile.bundle.iob.path `
    -Destination (Join-Path $templateDir 'quad_monolithic.iob')
$templateCon = Copy-VerifiedRunInput -Source $templateProfile.bundle.con.path `
    -Destination (Join-Path $templateDir 'quad_monolithic.con')
Copy-VerifiedRunInput -Source (Join-Path $projectRoot ($modeInput -replace '/', '\')) `
    -Destination $frozenMode | Out-Null
Copy-VerifiedRunInput -Source (Join-Path $projectRoot ($resolvedContractInput -replace '/', '\')) `
    -Destination $frozenResolved | Out-Null
Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'config\interface_contract.json') `
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
    & $python -m common.multipole.verify_resolved_design $frozenResolved
    if ($LASTEXITCODE -ne 0) { throw 'Frozen resolved-design identity verification failed.' }
} finally {
    Pop-Location
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
Copy-VerifiedRunInput -Source $sourceFamilyInput -Destination $frozenSourceFamily | Out-Null
Copy-VerifiedRunInput -Source $distributionInput -Destination $frozenDistribution | Out-Null
$frozenPythonSupport = Copy-VerifiedRunInput `
    -Source (Join-Path $projectRoot 'runtime\frozen_python_package.ps1') `
    -Destination (Join-Path $inputDir 'frozen_python_package.ps1')
$frozenCodeRoot = Join-Path $inputDir 'code'
$frozenPythonPackage = New-FrozenPythonPackage `
    -SourceRoot $repoRoot -CodeRoot $frozenCodeRoot -RelativePaths @(
        'projects\rf_quadrupole_ion_optics\workflows\__init__.py',
        'projects\rf_quadrupole_ion_optics\workflows\interface_readiness\__init__.py',
        'projects\rf_quadrupole_ion_optics\workflows\interface_readiness\generate_particle_table.py',
        'projects\rf_quadrupole_ion_optics\workflows\interface_readiness\particle_source_policy.py',
        'projects\rf_quadrupole_ion_optics\analysis\paired_particle_source_bundle.py',
        'common\contracts\particle_physics.py',
        'common\contracts\particle_count_policy.py',
        'common\contracts\particle_count_policy.json',
        'common\multipole\__init__.py',
        'common\multipole\particle_source_preflight.py'
    )
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
        'common.multipole',
        'common.multipole.particle_source_preflight'
    ) -ForbiddenRoots @($repoRoot,$projectRoot)
$frozenParticlePolicy = Get-FrozenPythonPackageFile `
    -Package $frozenPythonPackage -RelativePath `
    'projects/rf_quadrupole_ion_optics/workflows/interface_readiness/particle_source_policy.py'
$frozenParticleGenerator = Get-FrozenPythonPackageFile `
    -Package $frozenPythonPackage -RelativePath `
    'projects/rf_quadrupole_ion_optics/workflows/interface_readiness/generate_particle_table.py'
$frozenBundleMechanism = Get-FrozenPythonPackageFile `
    -Package $frozenPythonPackage -RelativePath `
    'projects/rf_quadrupole_ion_optics/analysis/paired_particle_source_bundle.py'
Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'simion\geometry\quad_include.gem') `
    -Destination (Join-Path $candidateDir 'quad_include.gem') | Out-Null
Copy-VerifiedRunInput -Source (Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem') `
    -Destination (Join-Path $candidateDir 'quad_monolithic.gem') | Out-Null
$programSource = Copy-VerifiedRunInput `
    -Source (Join-Path $repoRoot 'common\multipole\simion_transport.lua') `
    -Destination (Join-Path $candidateDir 'multipole_runtime_program.lua')
$iobBuilder = Copy-VerifiedRunInput `
    -Source (Join-Path $repoRoot 'common\multipole\build_simion_runtime_iob.lua') `
    -Destination (Join-Path $candidateDir 'build_simion_runtime_iob.lua')
$flyPath = Join-Path $candidateDir 'quad_monolithic.fly2'
$sourceStatesLua = Join-Path $inputDir 'source_states.lua'
$sourceMetadata = Join-Path $inputDir 'particle_source_metadata.json'
Push-Location $repoRoot
try {
    $sourceFamilySha = Get-RunFileSha256 -Path $frozenSourceFamily
    $requestedParticles = @(Import-Csv -LiteralPath $sourceParticlePath).Count
    $bindingArguments = @(
        '-m','projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding',
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
        '-m','projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding',
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
        '-m','common.multipole.particle_source_preflight',
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
    if ($expectedParticles -lt $minimumParticles) {
        throw "Interface-readiness mode requires at least $minimumParticles particles."
    }
    $sourceProjectionArguments = @(
        '-m','common.multipole.simion_particle_source',
        '--particles',$particlePath,
        '--resolved-design',$frozenResolved,
        '--source-family',$frozenSourceFamily,
        '--operating-point',$OperatingPoint,
        '--expected-source-family-sha256',$sourceFamilySha,
        '--fly2',$flyPath,
        '--source-states-lua',$sourceStatesLua
    )
    & $python @sourceProjectionArguments
    if ($LASTEXITCODE -ne 0) { throw 'Canonical SIMION particle projection failed.' }
} finally { Pop-Location }
Copy-VerifiedRunInput -Source $templateIob `
    -Destination (Join-Path $candidateDir 'quad_monolithic.iob') | Out-Null
Copy-VerifiedRunInput -Source $templateCon `
    -Destination (Join-Path $candidateDir 'quad_monolithic.con') | Out-Null

$resolved = Get-Content -LiteralPath $frozenResolved -Raw -Encoding UTF8 | ConvertFrom-Json
$interface = Get-Content -LiteralPath $frozenInterface -Raw -Encoding UTF8 | ConvertFrom-Json
$numericalContract = Get-Content -LiteralPath $frozenNumericalContract -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $PSBoundParameters.ContainsKey('RfStepsPerPeriod')) {
    $RfStepsPerPeriod = [int]$numericalContract.baseline_rf_steps_per_period
}
if (-not $PSBoundParameters.ContainsKey('TrajectoryQuality')) {
    $TrajectoryQuality = [int]$numericalContract.trajectory_quality
}
if ($RfStepsPerPeriod -notin @($numericalContract.allowed_rf_steps_per_period | ForEach-Object { [int]$_ })) {
    throw 'SIMION interface RF steps must be a preregistered baseline or refined value.'
}
if ($TrajectoryQuality -ne [int]$numericalContract.trajectory_quality) {
    throw 'SIMION interface trajectory quality differs from its frozen numerical contract.'
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
$RfPeakV = [double]$coreConfig.rf_peak_v
$FrequencyHz = [double]$coreConfig.frequency_hz
$runConfig = [ordered]@{
    schema_version=1; role='rf_quadrupole_simion_run_config'; run_id=$RunId
    project='rf_quadrupole_ion_optics'; mode=$mode; project_root=$projectRoot
    inputs=[ordered]@{resolved_design=$frozenResolved; interface_contract=$frozenInterface; mode=$frozenMode; numerical_contract=$frozenNumericalContract; particle_table=$particlePath; source_states=$sourceStatesLua;
        simion_layout_template_resolution=$templateResolution;simion_layout_template_registry=$templateRegistry;
        simion_layout_registration_manifest=$templateManifest;simion_layout_template_iob=$templateIob;
        simion_layout_template_con=$templateCon}
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
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$luaConfig = ConvertTo-RfSimionLuaConfig -CoreConfig $coreConfig `
    -SharedProgramPath (Join-Path $candidateDir 'quad_monolithic.lua')
# Windows PowerShell 5.1 writes a BOM for -Encoding UTF8; SIMION's Lua 5.1
# parser treats that BOM as source text.  This generated table is ASCII-only.
$luaConfig | Set-Content -LiteralPath $runConfigLua -Encoding ASCII

Invoke-RfSimionCoreRun -SimionExe $simion -CandidateDir $candidateDir `
    -IobPath ([string]$coreConfig.iob) -Fly2Path ([string]$coreConfig.fly2) `
    -IobBuilderScript $iobBuilder -ProgramSourcePath $programSource `
    -RunConfigLua $runConfigLua `
    -InspectScript (Join-Path $projectRoot 'simion\workbench\inspect_builtin_quad_reference.lua') `
    -IobReport $iobReport -LogDir $logDir `
    -TrajectoryQuality ([int]$coreConfig.trajectory_quality) `
    -RfStepsPerPeriod ([int]$coreConfig.rf_steps_per_period)

$summary = Get-Content -LiteralPath $summaryJson -Raw | ConvertFrom-Json
if ($summary.particles -ne $expectedParticles -or $summary.collision_model -ne 'none' -or
    $summary.parent_resolved_design_sha256 -cne $coreConfig.parent_resolved_design_sha256) {
    throw "SIMION transport execution integrity failed: $($summary | ConvertTo-Json -Compress)"
}
$physicalDecision = if ($summary.transmission -ge $minimumTransmission) { 'PASS' } else { 'FAIL' }
Push-Location $repoRoot
try { & $python -m common.contracts.particle_state `
    --state $particleStateCsv --particles $particlePath `
    --source-format canonical --contract $frozenInterface `
    --axial-offset-mm 0.0 --frequency-hz $FrequencyHz `
    --phase-rad ([double]$coreConfig.phase_deg*[Math]::PI/180) `
    --solver SIMION --output $stateContractReport } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Particle-state contract gate failed.' }
$shaPath = Join-Path $candidateDir 'SHA256SUMS.csv'
Write-RunDirectoryChecksumInventory -Directory $candidateDir -OutputPath $shaPath `
    -ExcludedPatterns @('trj*.tmp')
$rootSummary = [ordered]@{
    schema_version=1;role='rf_quadrupole_transport_summary';status='success';mode=$mode
    physical_decision=$physicalDecision
    particles=$expectedParticles;hits=$summary.hits;transmission=$summary.transmission
}
$rootSummary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $runSummary -Encoding UTF8
$manifestOutputs = @(
    $trajectoryCsv,$summaryJson,$particleStateCsv,$stateContractReport,
    (Join-Path $logDir 'simion_iob_stdout.txt'),(Join-Path $logDir 'simion_iob_stderr.txt'),
    (Join-Path $logDir 'simion_iob_exit_code.txt'),
    (Join-Path $logDir 'simion_stdout.txt'),(Join-Path $logDir 'simion_stderr.txt'),
    (Join-Path $candidateDir 'quad_monolithic.iob'),(Join-Path $candidateDir 'quad_monolithic.con'),
    (Join-Path $candidateDir 'quad_monolithic.pa0'),
    $flyPath,$iobReport,$shaPath,$runSummary
)
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $manifestOutputs
"EXECUTION=PASS DECISION=$physicalDecision RUN_ID=$RunId HITS=$($summary.hits) TRANSMISSION=$($summary.transmission)"
}
catch {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfigPath -Summary $runSummary `
        -SummaryRole 'rf_quadrupole_transport_summary' -Reason $_.Exception.Message `
        -Software @('SIMION 2020','Python 3.11')
    throw
}
