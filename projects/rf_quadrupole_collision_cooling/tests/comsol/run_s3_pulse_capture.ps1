param(
  [Parameter(Mandatory)][string]$SourceRunId,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$supportSource = (Resolve-Path (Join-Path $PSScriptRoot '..\support\rf_run_artifact_support.ps1')).Path
. $supportSource
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
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
$package = New-RfRunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'rf_quadrupole_collision_cooling' `
  -Mode 'rf_to_oatof_s3_shared_clock_pulse_capture_n100' -Software $software
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
  $s3 = Join-Path $inputDir 'rf_to_oatof_s3_pulse_capture.json'
  $s2 = Join-Path $inputDir 'rf_to_oatof_s2_passive_connector.json'
  $spatialRegistration = Join-Path $inputDir 'resolved_rf_to_oatof_s2_spatial_registration.json'
  $sharedJoint = Join-Path $inputDir 'rf_to_oatof_shared_physical_port_joint_geometry.json'
  $rf = Join-Path $inputDir 'rf_resolved_design.json'
  $pulsePolicy = Join-Path $inputDir 'rf_to_oatof_pulse_timing.json'
  $scheduler = Join-Path $inputDir 'derive_shared_centroid_pulse_time.py'
  $snapshotAnalysis = Join-Path $inputDir 'plot_shared_pulse_geometry_snapshot.py'
  $auditAnalysis = Join-Path $inputDir 'audit_s3_pulse_chain.py'
  $dependencyContractSource = Join-Path $projectRoot 'config\rf_to_oatof_s2_dependencies.json'
  $dependencyContract = Join-Path $inputDir 'rf_to_oatof_s2_dependencies.json'
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'solve_s3_pulse_capture.m') -Destination $task
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_s2_passive_connector_model.m') -Destination $geometryBuilder
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'prepare_s2_joint_field_model.m') -Destination $fieldBuilder
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  Copy-Item -LiteralPath $s3Source -Destination $s3
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_shared_physical_port_joint_geometry.json') -Destination $sharedJoint
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\resolved_design_official.json') -Destination $rf
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_pulse_timing.json') -Destination $pulsePolicy
  Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\derive_shared_centroid_pulse_time.py') -Destination $scheduler
  Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\plot_shared_pulse_geometry_snapshot.py') -Destination $snapshotAnalysis
  Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\audit_s3_pulse_chain.py') -Destination $auditAnalysis
  Copy-Item -LiteralPath $dependencyContractSource -Destination $dependencyContract

  $dependencyDocument = Get-Content -LiteralPath $dependencyContractSource -Raw -Encoding UTF8 | ConvertFrom-Json
  $dependencyIdentities = [ordered]@{}
  $dependencyPaths = @{}
  foreach ($dependency in $dependencyDocument.dependencies) {
    $identity = Copy-RfFrozenDependency -RepoRoot $repoRoot -InputDir $inputDir -Dependency $dependency
    $dependencyIdentities[$identity.id] = [ordered]@{
      provider_project = $identity.provider_project
      source_repo_path = $identity.source_repo_path
      frozen_input_name = $identity.frozen_input_name
      sha256 = $identity.sha256
    }
    $dependencyPaths[$identity.id] = $identity.frozen_path
  }
  $oaBaseline = $dependencyPaths['oatof_baseline']
  $oaBuilder = $dependencyPaths['oatof_accelerator_geometry_builder']

  $timingRun = Join-Path (Join-Path $artifactRoot 'runs') $SourceRunId
  $sourceManifestOriginal = Join-Path $timingRun 'run_manifest.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    $sourceManifestOriginal --require-status success
  if ($LASTEXITCODE -ne 0) { throw 'The frozen S2 timing/source run manifest is invalid.' }
  $sourceRunConfiguration = Get-Content -LiteralPath (Join-Path $timingRun 'run_config.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceRunConfiguration.mode -ne 'rf_to_oatof_s2_passive_connector_n100' -or
      -not [bool]$sourceRunConfiguration.parameters.particle_tracking) {
    throw 'S3 requires a successful S2 N=100 particle source run.'
  }
  $sourceS2Contract = [string]$sourceRunConfiguration.inputs.s2_contract
  $sourceSpatialRegistration = [string]$sourceRunConfiguration.inputs.spatial_registration
  $particleOriginal = [string]$sourceRunConfiguration.inputs.particle_source
  $timingStateOriginal = Join-Path $timingRun 'results\s2_passive_connector_particles.csv'
  foreach ($path in @($particleOriginal,$timingStateOriginal)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "S3 source input is missing: $path" }
  }
  if (-not (Test-Path -LiteralPath $sourceS2Contract -PathType Leaf)) {
    throw 'S3 source run has no frozen S2 connector contract.'
  }
  if (-not (Test-Path -LiteralPath $sourceSpatialRegistration -PathType Leaf)) {
    throw 'S3 source run has no frozen spatial-registration release.'
  }
  Copy-Item -LiteralPath $sourceS2Contract -Destination $s2
  Copy-Item -LiteralPath $sourceSpatialRegistration -Destination $spatialRegistration
  $resolvedS2Document = Get-Content -LiteralPath $s2 -Raw -Encoding UTF8 | ConvertFrom-Json
  $sourceManifest = Join-Path $inputDir 's2_source_run_manifest.json'
  $particleInput = Join-Path $inputDir 'canonical_rf_exit_at_s2_connector.csv'
  $timingState = Join-Path $inputDir 's2_passive_connector_particles.csv'
  Copy-Item -LiteralPath $sourceManifestOriginal -Destination $sourceManifest
  Copy-Item -LiteralPath $particleOriginal -Destination $particleInput
  Copy-Item -LiteralPath $timingStateOriginal -Destination $timingState
  $particleValidation = Join-Path $inputDir 'canonical_rf_exit_component_state_validation.json'
  Push-Location -LiteralPath $repoRoot
  try {
    & $python -m common.contracts.component_particle_state --state $particleInput `
      --output $particleValidation
  } finally {
    Pop-Location
  }
  if ($LASTEXITCODE -ne 0 -or
      -not (Test-Path -LiteralPath $particleValidation -PathType Leaf)) {
    throw 'S3 canonical particle input failed the common component-state contract.'
  }
  $particleValidationDocument = Get-Content -LiteralPath $particleValidation `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($particleValidationDocument.status -ne 'PASS' -or
      [int]$particleValidationDocument.particles -ne [int]$s3Document.source.source_particles) {
    throw 'S3 canonical particle validation report is incomplete or inconsistent.'
  }
  $pulseSchedule = Join-Path $inputDir 's3_centroid_pulse_schedule.json'
  & $python $scheduler --particle-state $timingState --oatof-baseline $oaBaseline `
    --joint-contract $sharedJoint --s2-contract $s2 --policy $pulsePolicy `
    --target-mass-amu ([double]$s3Document.source.target_mass_amu) `
    --target-charge-state ([int]$s3Document.source.target_charge_state) --output $pulseSchedule
  if ($LASTEXITCODE -ne 0) { throw 'S3 centroid pulse schedule derivation failed.' }
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
  $snapshotFigure = Join-Path $resultDir 's3_pulse_geometry_snapshot.png'
  $snapshotMetadata = Join-Path $resultDir 's3_pulse_geometry_snapshot.json'
  $report = Join-Path $logDir 'comsol_s3_pulse_capture.txt'
  $sourceIdentity = [ordered]@{
    run_id = $SourceRunId
    manifest_sha256 = (Get-FileHash -LiteralPath $sourceManifestOriginal -Algorithm SHA256).Hash
    particle_sha256 = (Get-FileHash -LiteralPath $particleOriginal -Algorithm SHA256).Hash
    particle_validation_sha256 = (Get-FileHash -LiteralPath $particleValidation -Algorithm SHA256).Hash
    timing_state_sha256 = (Get-FileHash -LiteralPath $timingStateOriginal -Algorithm SHA256).Hash
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
      spatial_registration = $spatialRegistration
      pulse_timing_policy = $pulsePolicy; pulse_scheduler = $scheduler
      snapshot_analysis = $snapshotAnalysis; audit_analysis = $auditAnalysis
      dependency_contract = $dependencyContract; oatof_baseline = $oaBaseline
      oatof_accelerator_builder = $oaBuilder; source_run_manifest = $sourceManifest
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
  Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status interrupted -Software $software

  $environmentNames = @(
    'RF_OATOF_S3_METRICS','RF_OATOF_S3_TERMINAL_OUTPUT','RF_OATOF_S3_CAPTURE_OUTPUT',
    'RF_OATOF_S3_LOCAL_EXIT_OUTPUT','RF_OATOF_S3_CONTRACT','RF_OATOF_S3_S2_CONTRACT',
    'RF_OATOF_S3_SHARED_JOINT_CONTRACT','RF_OATOF_S3_RF_RESOLVED','RF_OATOF_S3_OA_BASELINE',
    'RF_OATOF_SPATIAL_REGISTRATION','RF_OATOF_S3_PULSE_SCHEDULE',
    'RF_OATOF_S3_PARTICLE_INPUT','RF_OATOF_S3_OA_COMSOL_DIR'
  )
  $oldEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:RF_OATOF_S3_METRICS=$metrics; $env:RF_OATOF_S3_TERMINAL_OUTPUT=$terminal
    $env:RF_OATOF_S3_CAPTURE_OUTPUT=$capture; $env:RF_OATOF_S3_LOCAL_EXIT_OUTPUT=$localExit
    $env:RF_OATOF_S3_CONTRACT=$s3; $env:RF_OATOF_S3_S2_CONTRACT=$s2
    $env:RF_OATOF_S3_SHARED_JOINT_CONTRACT=$sharedJoint; $env:RF_OATOF_S3_RF_RESOLVED=$rf
    $env:RF_OATOF_SPATIAL_REGISTRATION=$spatialRegistration
    $env:RF_OATOF_S3_OA_BASELINE=$oaBaseline; $env:RF_OATOF_S3_PULSE_SCHEDULE=$pulseSchedule
    $env:RF_OATOF_S3_PARTICLE_INPUT=$particleInput; $env:RF_OATOF_S3_OA_COMSOL_DIR=$inputDir
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL S3 pulse-capture task failed.' }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $oldEnvironment
  }
  & $python $auditAnalysis --source $particleInput --terminal $terminal --capture $capture `
    --local-exit $localExit --schedule $pulseSchedule --contract $s3 --output $audit
  if ($LASTEXITCODE -ne 0) { throw 'S3 particle-chain audit failed.' }
  & $python $snapshotAnalysis --capture $capture --events $terminal `
    --oatof-baseline $oaBaseline --joint-contract $sharedJoint `
    --figure $snapshotFigure --metadata $snapshotMetadata
  if ($LASTEXITCODE -ne 0) { throw 'S3 pulse snapshot generation failed.' }
  $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  $auditResult = Get-Content -LiteralPath $audit -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($result.status -ne 'PASS' -or $auditResult.status -ne 'PASS' -or
      [int]$result.source_particles -ne [int]$s3Document.source.source_particles -or
      [int]$result.active_at_pulse -lt [int]$s3Document.runtime.minimum_active_at_pulse -or
      [int]$result.local_accelerator_exit -lt [int]$s3Document.runtime.minimum_local_accelerator_exit -or
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
  $outputs = @($terminal,$capture,$localExit,$metrics,$audit,$snapshotFigure,$snapshotMetadata,$report,$package.summary)
  Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  Write-Output "STATUS=PASS RUN_ID=$RunId SOURCE=$($result.source_particles) ACTIVE=$($result.active_at_pulse) LOCAL_EXIT=$($result.local_accelerator_exit) S3_STAGE_PASS=false"
} catch {
  Complete-RfFailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_to_oatof_s3_pulse_capture_summary' `
    -Reason $_.Exception.Message -Software $software
  throw
}
