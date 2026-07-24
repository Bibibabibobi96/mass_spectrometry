param(
  [Parameter(Mandatory)][string]$SourceRunId,
  [string]$RunId = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$supportSource = (Resolve-Path (Join-Path $PSScriptRoot '..\support\rf_run_artifact_support.ps1')).Path
. $supportSource
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }

function Invoke-S3SnapshotPython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SnapshotRoot,
    [Parameter(Mandatory)][string[]]$Arguments,
    [Parameter(Mandatory)][string]$FailureMessage
  )
  $environmentNames = @('PYTHONPATH','PYTHONNOUSERSITE')
  $savedEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:PYTHONPATH = $SnapshotRoot
    $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $SnapshotRoot
    try { & $Python @Arguments } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $savedEnvironment
  }
}

$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$s3Source = Join-Path $projectRoot 'config\rf_to_oatof_s3_pulse_capture.json'
$s3Document = Get-Content -LiteralPath $s3Source -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$s3Document.permissions.nominal_particle_runtime_allowed -or
    [bool]$s3Document.permissions.s3_stage_pass_allowed) {
  throw 'The S3 contract does not authorize a qualification-limited particle runtime.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__comsol__rf-oatof-s3-pulse-capture__n100'
}
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'rf_quadrupole_collision_cooling' `
  -Mode 'rf_to_oatof_s3_shared_clock_pulse_capture_n100' -Software $software
$manifestToolRoot = $repoRoot
$python = $package.python
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir

try {
  $task = Join-Path $inputDir 'solve_s3_pulse_capture.m'
  $geometryBuilder = Join-Path $inputDir 'build_s2_passive_connector_model.m'
  $fieldBuilder = Join-Path $inputDir 'prepare_s2_joint_field_model.m'
  $runner = Join-Path $inputDir 'run_s3_pulse_capture.ps1.txt'
  $support = Join-Path $inputDir 'rf_run_artifact_support.ps1.txt'
  $snapshotRoot = Join-Path $inputDir 'runtime_snapshot'
  $s3 = Join-Path $inputDir 'rf_to_oatof_s3_pulse_capture.json'
  $s2 = Join-Path $inputDir 'rf_to_oatof_s2_passive_connector.json'
  $spatialRegistration = Join-Path $inputDir 'resolved_rf_to_oatof_s2_spatial_registration.json'
  $pulsePolicy = Join-Path $inputDir 'rf_to_oatof_pulse_timing.json'
  $dependencyContractSource = Join-Path $projectRoot 'config\rf_to_oatof_s2_dependencies.json'
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'solve_s3_pulse_capture.m') -Destination $task
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_s2_passive_connector_model.m') -Destination $geometryBuilder
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'prepare_s2_joint_field_model.m') -Destination $fieldBuilder
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  Copy-Item -LiteralPath $s3Source -Destination $s3
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_pulse_timing.json') -Destination $pulsePolicy
  $s3Document = Get-Content -LiteralPath $s3 -Raw -Encoding UTF8 | ConvertFrom-Json

  $dependencyContract = Join-Path $snapshotRoot `
    'projects\rf_quadrupole_collision_cooling\config\rf_to_oatof_s2_dependencies.json'
  $dependencyContractIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $dependencyContractSource -Destination $dependencyContract `
    -Role 'S3 dependency contract'
  $dependencyDocument = Get-Content -LiteralPath $dependencyContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $dependencyConsumer = 's3_pulse_capture'
  if (@($dependencyDocument.consumer_ids) -notcontains $dependencyConsumer) {
    throw "S3 dependency consumer is not declared: $dependencyConsumer"
  }
  $selectedDependencies = @(
    $dependencyDocument.dependencies |
      Where-Object { @($_.consumers) -contains $dependencyConsumer }
  )
  if ($selectedDependencies.Count -eq 0 -or
      @($selectedDependencies.id | Select-Object -Unique).Count -ne $selectedDependencies.Count) {
    throw 'S3 dependency consumer subset is empty or has duplicate identities.'
  }
  $dependencyIdentities = [ordered]@{}
  $dependencySnapshotPaths = @{}
  $dependencyCompatibilityPaths = @{}
  foreach ($dependency in $selectedDependencies) {
    if ([string]$dependency.id -eq 'rf_dependency_contract_snapshot') {
      $identity = Confirm-RfFrozenDependencyIdentity -RepoRoot $repoRoot `
        -InputDir $inputDir -Dependency $dependency `
        -ExpectedSourcePath $dependencyContractSource `
        -ExistingSnapshotPath $dependencyContract `
        -ExpectedSha256 $dependencyContractIdentity.sha256
    } else {
      $identity = Copy-RfFrozenDependency -RepoRoot $repoRoot -InputDir $inputDir `
        -Dependency $dependency
    }
    if ((Get-FileHash -LiteralPath $identity.snapshot_path -Algorithm SHA256).Hash -ne
        $identity.sha256) {
      throw "S3 dependency snapshot identity differs: $($identity.id)"
    }
    $dependencyIdentities[$identity.id] = [ordered]@{
      provider_scope = $identity.provider_scope
      provider_project = $identity.provider_project
      provider_repo_path = $identity.provider_repo_path
      source_repo_path = $identity.source_repo_path
      frozen_input_name = $identity.frozen_input_name
      consumers = @($identity.consumers)
      snapshot_path = $identity.snapshot_path
      compatibility_path = $identity.compatibility_path
      sha256 = $identity.sha256
    }
    $dependencySnapshotPaths[$identity.id] = $identity.snapshot_path
    $dependencyCompatibilityPaths[$identity.id] = $identity.compatibility_path
  }
  $manifestToolRoot = $snapshotRoot
  if (-not $dependencySnapshotPaths['rf_dependency_contract_snapshot'].Equals(
      $dependencyContract, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'S3 dependency contract self identity is inconsistent.'
  }
  $interfaceStagePlan = $dependencySnapshotPaths['rf_interface_stage_plan']
  $sharedJoint = $dependencySnapshotPaths['rf_shared_joint_geometry']
  $rf = $dependencySnapshotPaths['rf_resolved_design']
  $scheduler = $dependencySnapshotPaths['rf_s3_pulse_scheduler']
  $snapshotAnalysis = $dependencySnapshotPaths['rf_s3_geometry_snapshot_plotter']
  $auditAnalysis = $dependencySnapshotPaths['rf_s3_pulse_chain_auditor']
  $localExitAdapter = $dependencySnapshotPaths['rf_s3_local_exit_adapter']
  $oaBaselineSnapshot = $dependencySnapshotPaths['oatof_baseline']
  $oaBuilderSnapshot = $dependencySnapshotPaths['oatof_accelerator_geometry_builder']
  $oaBaselineMatlab = $dependencyCompatibilityPaths['oatof_baseline']
  $oaBuilderMatlab = $dependencyCompatibilityPaths['oatof_accelerator_geometry_builder']
  if ([string]::IsNullOrWhiteSpace($oaBaselineMatlab) -or
      [string]::IsNullOrWhiteSpace($oaBuilderMatlab)) {
    throw 'S3 MATLAB compatibility inputs are not declared by the dependency contract.'
  }
  $frozenManifestVerifier = $dependencySnapshotPaths['common_verify_run_manifest']
  $frozenComsolRunner = $dependencySnapshotPaths['common_comsol_runner']

  $requiredSnapshotIds = @(
    'rf_dependency_contract_snapshot','rf_interface_stage_plan',
    'rf_shared_joint_geometry','rf_resolved_design',
    'rf_s3_pulse_scheduler','rf_s3_geometry_snapshot_plotter',
    'rf_s3_pulse_chain_auditor','rf_s3_local_exit_adapter',
    'common_component_particle_state','common_particle_physics',
    'common_verify_run_manifest','common_write_run_manifest',
    'common_run_artifact_support','common_comsol_runner'
  )
  foreach ($requiredId in $requiredSnapshotIds) {
    if ([string]::IsNullOrWhiteSpace([string]$dependencySnapshotPaths[$requiredId])) {
      throw "S3 dependency consumer is missing required identity: $requiredId"
    }
  }

  $timingRun = Resolve-RfDirectChildDirectory `
    -ParentRoot (Join-Path $artifactRoot 'runs') -ChildName $SourceRunId `
    -Role 'SourceRunId'
  $sourceManifestOriginal = Join-Path $timingRun 'run_manifest.json'
  $sourceManifest = Join-Path $inputDir 's2_source_run_manifest.json'
  $sourceManifestIdentity = Copy-RfStableFile -SourceRunRoot $timingRun `
    -SourcePath $sourceManifestOriginal -Destination $sourceManifest `
    -Role 'source run manifest'
  Invoke-S3SnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $frozenManifestVerifier,$sourceManifest,
    '--require-status','success','--require-run-id',$SourceRunId,
    '--require-project','rf_quadrupole_collision_cooling',
    '--require-mode','rf_to_oatof_s2_passive_connector_n100'
  ) -FailureMessage 'The frozen S2 timing/source run manifest is invalid.'
  $sourceManifestDocument = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($sourceManifestDocument.role -ne 'simulation_run_manifest' -or
      $sourceManifestDocument.status -ne 'success' -or
      $sourceManifestDocument.project -ne 'rf_quadrupole_collision_cooling' -or
      $sourceManifestDocument.mode -ne 'rf_to_oatof_s2_passive_connector_n100' -or
      $sourceManifestDocument.run_id -ne $SourceRunId) {
    throw 'S3 source manifest identity or role is invalid.'
  }

  $sourceRunConfig = Join-Path $inputDir 's2_source_run_config.json'
  $sourceRunConfigIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath ([string]$sourceManifestDocument.run_config.path) `
    -Destination $sourceRunConfig -ManifestRecord $sourceManifestDocument.run_config `
    -Role 'run_config'
  $sourceRunConfiguration = Get-Content -LiteralPath $sourceRunConfig -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($sourceRunConfiguration.run_id -ne $SourceRunId -or
      $sourceRunConfiguration.project -ne 'rf_quadrupole_collision_cooling' -or
      $sourceRunConfiguration.mode -ne 'rf_to_oatof_s2_passive_connector_n100' -or
      -not [bool]$sourceRunConfiguration.parameters.particle_tracking) {
    throw 'S3 requires a successful S2 N=100 particle source run.'
  }

  $sourceS2Contract = [string]$sourceRunConfiguration.inputs.s2_contract
  $sourceSpatialRegistration = [string]$sourceRunConfiguration.inputs.spatial_registration
  $particleOriginal = [string]$sourceRunConfiguration.inputs.particle_source
  $timingStateOriginal = Join-Path $timingRun 'results\s2_passive_connector_particles.csv'
  $particleInput = Join-Path $inputDir 'canonical_rf_exit_at_s2_connector.csv'
  $timingState = Join-Path $inputDir 's2_passive_connector_particles.csv'
  $sourceS2Identity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $sourceS2Contract -Destination $s2 `
    -ManifestRecord (Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 's2_contract') `
    -Role 's2_contract'
  $sourceSpatialIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $sourceSpatialRegistration -Destination $spatialRegistration `
    -ManifestRecord (Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 'spatial_registration') `
    -Role 'spatial_registration'
  $sourceParticleIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $particleOriginal -Destination $particleInput `
    -ManifestRecord (Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 'particle_source') `
    -Role 'particle_source'
  $timingOutputRecord = Get-RfManifestOutputRecord -Manifest $sourceManifestDocument `
    -ExpectedPath $timingStateOriginal -Role 'timing_state'
  $sourceTimingIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $timingStateOriginal -Destination $timingState `
    -ManifestRecord $timingOutputRecord -Role 'timing_state'
  $resolvedS2Document = Get-Content -LiteralPath $s2 -Raw -Encoding UTF8 | ConvertFrom-Json

  $particleValidation = Join-Path $inputDir 'canonical_rf_exit_component_state_validation.json'
  Invoke-S3SnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    '-m','common.contracts.component_particle_state',
    '--state',$particleInput,'--output',$particleValidation
  ) -FailureMessage 'S3 canonical particle input failed the common component-state contract.'
  if (-not (Test-Path -LiteralPath $particleValidation -PathType Leaf)) {
    throw 'S3 canonical particle input failed the common component-state contract.'
  }
  $particleValidationDocument = Get-Content -LiteralPath $particleValidation `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($particleValidationDocument.status -ne 'PASS' -or
      [int]$particleValidationDocument.particles -ne [int]$s3Document.source.source_particles) {
    throw 'S3 canonical particle validation report is incomplete or inconsistent.'
  }
  $pulseSchedule = Join-Path $inputDir 's3_centroid_pulse_schedule.json'
  Invoke-S3SnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $scheduler,'--particle-state',$timingState,
    '--oatof-baseline',$oaBaselineSnapshot,
    '--joint-contract',$sharedJoint,'--s2-contract',$s2,
    '--policy',$pulsePolicy,'--resolved-registration',$spatialRegistration,
    '--target-mass-amu',([string][double]$s3Document.source.target_mass_amu),
    '--target-charge-state',([string][int]$s3Document.source.target_charge_state),
    '--output',$pulseSchedule
  ) -FailureMessage 'S3 centroid pulse schedule derivation failed.'
  $scheduleDocument = Get-Content -LiteralPath $pulseSchedule -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($scheduleDocument.role -ne 'rf_to_oatof_s3_centroid_pulse_schedule' -or
      $scheduleDocument.status -ne 'PASS' -or
      [string]$scheduleDocument.source_particle_table_sha256 -ne
        (Get-FileHash -LiteralPath $timingState -Algorithm SHA256).Hash) {
    throw 'S3 derived pulse schedule identity is invalid.'
  }

  $terminal = Join-Path $resultDir 's3_particle_terminal_census.csv'
  $capture = Join-Path $resultDir 's3_pulse_left_limit_state.csv'
  $localExit = Join-Path $resultDir 's3_local_accelerator_exit.csv'
  $metrics = Join-Path $resultDir 's3_pulse_capture_metrics.json'
  $audit = Join-Path $resultDir 's3_particle_chain_audit.json'
  $localExitValidation = Join-Path $resultDir 's3_local_accelerator_exit_validation.json'
  $snapshotFigure = Join-Path $resultDir 's3_pulse_geometry_snapshot.png'
  $snapshotMetadata = Join-Path $resultDir 's3_pulse_geometry_snapshot.json'
  $report = Join-Path $logDir 'comsol_s3_pulse_capture.txt'
  $sourceIdentity = [ordered]@{
    run_id = $SourceRunId
    manifest_sha256 = $sourceManifestIdentity.sha256
    run_config_sha256 = $sourceRunConfigIdentity.sha256
    s2_contract_sha256 = $sourceS2Identity.sha256
    spatial_registration_sha256 = $sourceSpatialIdentity.sha256
    particle_sha256 = $sourceParticleIdentity.sha256
    particle_validation_sha256 = (Get-FileHash -LiteralPath $particleValidation -Algorithm SHA256).Hash
    timing_state_sha256 = $sourceTimingIdentity.sha256
  }
  $runConfiguration = [ordered]@{
    schema_version = 1
    run_id = $RunId
    project = 'rf_quadrupole_collision_cooling'
    mode = 'rf_to_oatof_s3_shared_clock_pulse_capture_n100'
    project_root = $repoRoot
    inputs = [ordered]@{
      task = $task; geometry_builder = $geometryBuilder; field_builder = $fieldBuilder
      runner = $runner; run_artifact_support = $support; s3_contract = $s3
      s2_contract = $s2; shared_physical_port_joint_geometry = $sharedJoint
      rf_resolved_geometry = $rf
      interface_stage_plan = $interfaceStagePlan
      spatial_registration = $spatialRegistration
      pulse_timing_policy = $pulsePolicy; pulse_scheduler = $scheduler
      snapshot_analysis = $snapshotAnalysis; audit_analysis = $auditAnalysis
      local_exit_adapter = $localExitAdapter
      dependency_contract = $dependencyContract
      oatof_baseline = $oaBaselineSnapshot
      oatof_baseline_matlab_compatibility = $oaBaselineMatlab
      oatof_accelerator_builder = $oaBuilderSnapshot
      oatof_accelerator_builder_matlab_compatibility = $oaBuilderMatlab
      source_run_manifest = $sourceManifest
      source_run_config = $sourceRunConfig
      particle_source = $particleInput; particle_state_validation = $particleValidation
      timing_state = $timingState; pulse_schedule = $pulseSchedule
    }
    dependency_identities = $dependencyIdentities
    source_particle_identity = $sourceIdentity
    parameters = [ordered]@{
      source_particles = [int]$s3Document.source.source_particles
      connector_gap_mm = [double]$resolvedS2Document.nominal_registration.connector_gap_mm
      connector_case_id = [string]$resolvedS2Document.runtime_case.case_id
      pulse_time_us = [double]$scheduleDocument.derived_pulse_time_us
      pulse_width_us = [double]$scheduleDocument.pulse_width_us
      rise_fall_model = [string]$s3Document.waveform.rise_fall_model
      pre_pulse_oatof_field_scale = 0.0; pulse_oatof_field_scale = 1.0
      post_pulse_oatof_field_scale = 0.0; solver_rerun = $true
      dense_trajectories_saved = $false; s3_stage_passed = $false
    }
    formal_gate_passed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 9 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1; role = 'rf_to_oatof_s3_pulse_capture_summary'
    status = 'interrupted'; reason = 'Run package initialized; final status not yet recorded.'
  })
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status interrupted -Software $software

  $environmentNames = @(
    'RF_OATOF_S3_METRICS','RF_OATOF_S3_TERMINAL_OUTPUT','RF_OATOF_S3_CAPTURE_OUTPUT',
    'RF_OATOF_S3_CONTRACT','RF_OATOF_S3_S2_CONTRACT',
    'RF_OATOF_S3_SHARED_JOINT_CONTRACT','RF_OATOF_S3_RF_RESOLVED','RF_OATOF_S3_OA_BASELINE',
    'RF_OATOF_SPATIAL_REGISTRATION','RF_OATOF_S3_PULSE_SCHEDULE',
    'RF_OATOF_S3_PARTICLE_INPUT','RF_OATOF_S3_OA_COMSOL_DIR'
  )
  $oldEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:RF_OATOF_S3_METRICS=$metrics; $env:RF_OATOF_S3_TERMINAL_OUTPUT=$terminal
    $env:RF_OATOF_S3_CAPTURE_OUTPUT=$capture
    $env:RF_OATOF_S3_CONTRACT=$s3; $env:RF_OATOF_S3_S2_CONTRACT=$s2
    $env:RF_OATOF_S3_SHARED_JOINT_CONTRACT=$sharedJoint; $env:RF_OATOF_S3_RF_RESOLVED=$rf
    $env:RF_OATOF_SPATIAL_REGISTRATION=$spatialRegistration
    $env:RF_OATOF_S3_OA_BASELINE=$oaBaselineMatlab
    $env:RF_OATOF_S3_PULSE_SCHEDULE=$pulseSchedule
    $env:RF_OATOF_S3_PARTICLE_INPUT=$particleInput; $env:RF_OATOF_S3_OA_COMSOL_DIR=$inputDir
    & $frozenComsolRunner `
      -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL S3 pulse-capture task failed.' }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $oldEnvironment
  }
  Invoke-S3SnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $localExitAdapter,'--source',$particleInput,'--terminal',$terminal,
    '--contract',$s3,'--output',$localExit,'--validation',$localExitValidation
  ) -FailureMessage 'S3 local-exit canonical adapter failed.'
  if (-not (Test-Path -LiteralPath $localExit -PathType Leaf) -or
      -not (Test-Path -LiteralPath $localExitValidation -PathType Leaf)) {
    throw 'S3 local-exit canonical adapter failed.'
  }
  Invoke-S3SnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $auditAnalysis,'--source',$particleInput,'--terminal',$terminal,
    '--capture',$capture,'--local-exit',$localExit,'--schedule',$pulseSchedule,
    '--contract',$s3,'--output',$audit
  ) -FailureMessage 'S3 particle-chain audit failed.'
  Invoke-S3SnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $snapshotAnalysis,'--capture',$capture,'--events',$terminal,
    '--oatof-baseline',$oaBaselineSnapshot,'--joint-contract',$sharedJoint,
    '--resolved-registration',$spatialRegistration,
    '--figure',$snapshotFigure,'--metadata',$snapshotMetadata
  ) -FailureMessage 'S3 pulse snapshot generation failed.'
  $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  $auditResult = Get-Content -LiteralPath $audit -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($result.status -ne 'PASS' -or $auditResult.status -ne 'PASS' -or
      [int]$result.source_particles -ne [int]$s3Document.source.source_particles -or
      [int]$result.active_at_pulse -lt [int]$s3Document.runtime.minimum_active_at_pulse -or
      [int]$result.local_accelerator_exit -lt [int]$s3Document.runtime.minimum_local_accelerator_exit -or
      [int]$result.local_accelerator_exit -ne [int]$auditResult.local_accelerator_exit -or
      [bool]$result.s3_stage_passed -or [bool]$result.formal_gate_passed) {
    throw 'S3 result violates the qualification-limited functional contract.'
  }
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1; role = 'rf_to_oatof_s3_pulse_capture_summary'; status = 'success'
    source_particles = [int]$result.source_particles
    oatof_entry_crossings = [int]$result.oatof_entry_crossings
    active_at_pulse = [int]$result.active_at_pulse
    inside_ideal_reference_volume_at_pulse = [int]$result.inside_ideal_reference_volume_at_pulse
    local_accelerator_exit = [int]$result.local_accelerator_exit
    pulse_time_us = [double]$result.pulse_time_us; pulse_width_us = [double]$result.pulse_width_us
    pulse_snapshot_figure = 'results/s3_pulse_geometry_snapshot.png'
    dense_trajectories_saved = $false; s3_stage_passed = $false; formal_gate_passed = $false
  })
  $outputs = @($terminal,$capture,$localExit,$localExitValidation,$metrics,$audit, $snapshotFigure,$snapshotMetadata,$report,$package.summary)
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  Write-Output "STATUS=PASS RUN_ID=$RunId SOURCE=$($result.source_particles) ACTIVE=$($result.active_at_pulse) LOCAL_EXIT=$($result.local_accelerator_exit) S3_STAGE_PASS=false"
} catch {
  Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_to_oatof_s3_pulse_capture_summary' `
    -Reason $_.Exception.Message -Software $software
  throw
}
