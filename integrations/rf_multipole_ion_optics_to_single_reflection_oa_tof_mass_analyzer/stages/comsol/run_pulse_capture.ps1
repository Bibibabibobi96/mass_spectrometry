param(
  [Parameter(Mandatory)][string]$SourceRunId,
  [string]$RunId = '',
  [Parameter(Mandatory)][string]$ExpectedConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [Parameter(Mandatory)][string]$RuntimeBinding,
  [Parameter(Mandatory)][ValidateSet('comsol','simion')]
  [string]$SourceBranchId,
  [Parameter(Mandatory)][string]$ResolvedSourceContract,
  [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256,
  [string]$PythonExe = '',
  [ValidateSet('strict','exploration')][string]$RuntimeImplementationBindingMode = 'strict'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
. (Join-Path $integrationRoot 'runtime\runtime_binding.ps1')
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repoRoot `
  -ResolvedConnection $ResolvedConnection -RuntimeBinding $RuntimeBinding `
  -ExpectedConnectionProfileId $ExpectedConnectionProfileId `
  -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256 `
  -AllowImplementationContentShaMismatch:($RuntimeImplementationBindingMode -eq 'exploration')
$upstreamProjectId = $runtime.upstream_project_id
$projectRoot = Join-Path $repoRoot "projects\$upstreamProjectId"
$supportSource = $runtime.run_artifact_support
. $supportSource
$executionCapacityPaths = Get-RfOatofExecutionCapacityPaths -Runtime $runtime `
  -ConsumerId 'pulse_capture' -AdditionalPaths @(
  'results/pulse_capture_local_accelerator_exit_validation.json',
  'results/pulse_capture_pulse_geometry_snapshot.json',
  'results/pulse_capture_pulse_geometry_snapshot.png',
  'logs/comsol_pulse_capture.txt'
)
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }

function Invoke-PulseCaptureSnapshotPython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SnapshotRoot,
    [Parameter(Mandatory)][string[]]$Arguments,
    [Parameter(Mandatory)][string]$FailureMessage
  )
  $environmentNames = @('PYTHONPATH','PYTHONNOUSERSITE')
  $savedEnvironment = Save-RunEnvironment -Names $environmentNames
  try {
    $env:PYTHONPATH = $SnapshotRoot
    $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $SnapshotRoot
    try { & $Python @Arguments } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
  } finally {
    Restore-RunEnvironment -Names $environmentNames -Snapshot $savedEnvironment
  }
}

$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$upstreamProjectId"
$pulse_captureSource = $runtime.contracts.pulse_capture_contract
$pulsePolicySource = $runtime.contracts.pulse_timing_contract
$pulse_captureDocument = Get-Content -LiteralPath $pulse_captureSource -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$pulse_captureDocument.permissions.nominal_particle_runtime_allowed -or
    [bool]$pulse_captureDocument.permissions.phase_pass_allowed) {
  throw 'The PulseCapture contract does not authorize a qualification-limited particle runtime.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $particleCount = [int]$runtime.source_record.particle_count
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') +
    "__sim__comsol__rf-oatof-pulse-capture__n${particleCount}"
}
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $upstreamProjectId `
  -Mode 'rf_to_oatof_pulse_capture' -Software $software `
  -RetentionContractEnabled -RetentionClass compact -UseShortExecutionPath `
  -ExpectedExecutionRelativePaths $executionCapacityPaths
$manifestToolRoot = $repoRoot
$resourceBudgetExceeded = $false
$python = $package.python
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir

try {
  $task = Join-Path $inputDir 'solve_pulse_capture.m'
  $geometryBuilder = Join-Path $inputDir 'build_pre_pulse_interface_transport_model.m'
  $fieldBuilder = Join-Path $inputDir 'prepare_pre_pulse_interface_transport_field_model.m'
  $runner = Join-Path $inputDir 'run_pulse_capture.ps1.txt'
  $support = Join-Path $inputDir 'run_artifacts.ps1.txt'
  $snapshotRoot = Join-Path $inputDir 'runtime_snapshot'
  $pulse_capture = Join-Path $inputDir 'rf_to_oatof_pulse_capture.json'
  $pre_pulse = Join-Path $inputDir 'rf_to_oatof_pre_pulse_passive_connector.json'
  $resolvedConnection = Join-Path $inputDir 'resolved_connection.json'
  $runtimeBindingFrozen = Join-Path $inputDir 'runtime_binding.json'
  $resolvedSourceContract = Join-Path $inputDir 'resolved_source_contract.json'
  $rf = Join-Path $inputDir 'upstream_resolved_design.json'
  $pulsePolicy = Join-Path $inputDir 'rf_to_oatof_pulse_timing.json'
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'solve_pulse_capture.m') -Destination $task
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_pre_pulse_interface_transport_model.m') -Destination $geometryBuilder
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'prepare_pre_pulse_interface_transport_field_model.m') -Destination $fieldBuilder
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  Copy-Item -LiteralPath $pulse_captureSource -Destination $pulse_capture
  Copy-Item -LiteralPath $pulsePolicySource -Destination $pulsePolicy
  Copy-Item -LiteralPath $runtime.binding_path -Destination $runtimeBindingFrozen
  Copy-Item -LiteralPath $runtime.contracts.resolved_source_contract `
    -Destination $resolvedSourceContract
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design -Destination $rf
  $pulse_captureDocument = Get-Content -LiteralPath $pulse_capture -Raw -Encoding UTF8 | ConvertFrom-Json

  $dependencyPublication = Publish-RfOatofDependencyInventory `
    -Runtime $runtime -RepoRoot $repoRoot -InputDir $inputDir -Role 'PulseCapture'
  $dependencyContract = $dependencyPublication.code_inventory_path
  $dependencyDocument = Get-Content -LiteralPath $dependencyContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $dependencyConsumer = 'pulse_capture'
  if (@($dependencyDocument.consumer_ids) -notcontains $dependencyConsumer) {
    throw "PulseCapture dependency consumer is not declared: $dependencyConsumer"
  }
  $selectedDependencies = @(
    $dependencyDocument.dependencies |
      Where-Object { @($_.consumers) -contains $dependencyConsumer }
  )
  if ($selectedDependencies.Count -eq 0 -or
      @($selectedDependencies.id | Select-Object -Unique).Count -ne $selectedDependencies.Count) {
    throw 'PulseCapture dependency consumer subset is empty or has duplicate identities.'
  }
  $dependencyIdentities = [ordered]@{}
  $dependencySnapshotPaths = @{}
  foreach ($dependency in $selectedDependencies) {
    $identity = Copy-RfFrozenDependency -RepoRoot $repoRoot -InputDir $inputDir `
      -Dependency $dependency
    if ((Get-FileHash -LiteralPath $identity.snapshot_path -Algorithm SHA256).Hash -ne
        $identity.sha256) {
      throw "PulseCapture dependency snapshot identity differs: $($identity.id)"
    }
    $dependencyIdentities[$identity.id] = [ordered]@{
      provider_scope = $identity.provider_scope
      provider_project = $identity.provider_project
      provider_repo_path = $identity.provider_repo_path
      source_repo_path = $identity.source_repo_path
      frozen_input_name = $identity.frozen_input_name
      consumers = @($identity.consumers)
      snapshot_path = $identity.snapshot_path
      sha256 = $identity.sha256
    }
    $dependencySnapshotPaths[$identity.id] = $identity.snapshot_path
  }
  $manifestToolRoot = $snapshotRoot
  $interfaceStagePlan = $dependencySnapshotPaths['rf_interface_stage_plan']
  $sharedJoint = $dependencySnapshotPaths['rf_shared_joint_geometry']
  $scheduler = $dependencySnapshotPaths['rf_pulse_capture_pulse_scheduler']
  $snapshotAnalysis = $dependencySnapshotPaths['rf_pulse_capture_geometry_snapshot_plotter']
  $auditAnalysis = $dependencySnapshotPaths['rf_pulse_capture_pulse_chain_auditor']
  $localExitAdapter = $dependencySnapshotPaths['rf_pulse_capture_local_exit_adapter']
  $multipoleRodBuilder =
    $dependencySnapshotPaths['common_create_multipole_round_rods']
  $oaBaselineSnapshot = $dependencySnapshotPaths['oatof_baseline']
  $oaBuilderSnapshot = $dependencySnapshotPaths['oatof_accelerator_geometry_builder']
  $oaBaselineMatlab = $dependencySnapshotPaths['oatof_baseline']
  $oaBuilderMatlab = $dependencySnapshotPaths['oatof_accelerator_geometry_builder']
  if ([string]::IsNullOrWhiteSpace($oaBaselineMatlab) -or
      [string]::IsNullOrWhiteSpace($oaBuilderMatlab)) {
    throw 'PulseCapture MATLAB inputs are not declared by the dependency contract.'
  }
  $frozenManifestVerifier = $dependencySnapshotPaths['common_verify_run_manifest']
  $frozenComsolRunner = $dependencySnapshotPaths['common_comsol_runner']

  $requiredSnapshotIds = @(
    'rf_interface_stage_plan',
    'rf_shared_joint_geometry',
    'rf_pulse_capture_pulse_scheduler','rf_pulse_capture_geometry_snapshot_plotter',
    'rf_pulse_capture_pulse_chain_auditor','rf_pulse_capture_local_exit_adapter',
    'common_component_particle_state','common_particle_physics',
    'common_artifact_retention','common_artifact_retention_policy',
    'common_resource_budget_support',
    'common_verify_run_manifest','common_write_run_manifest',
    'common_run_artifact_support','common_comsol_runner',
    'common_create_multipole_round_rods'
  )
  foreach ($requiredId in $requiredSnapshotIds) {
    if ([string]::IsNullOrWhiteSpace([string]$dependencySnapshotPaths[$requiredId])) {
      throw "PulseCapture dependency consumer is missing required identity: $requiredId"
    }
  }
  . $dependencySnapshotPaths['common_resource_budget_support']

  $timingRun = Resolve-RfDirectChildDirectory `
    -ParentRoot (Join-Path $artifactRoot 'runs') -ChildName $SourceRunId `
    -Role 'SourceRunId'
  $sourceManifestOriginal = Join-Path $timingRun 'run_manifest.json'
  $sourceManifest = Join-Path $inputDir 'pre_pulse_source_run_manifest.json'
  $sourceManifestIdentity = Copy-RfStableFile -SourceRunRoot $timingRun `
    -SourcePath $sourceManifestOriginal -Destination $sourceManifest `
    -Role 'source run manifest'
  Invoke-PulseCaptureSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $frozenManifestVerifier,$sourceManifest,
    '--require-status','success','--require-run-id',$SourceRunId,
    '--require-project',$upstreamProjectId,
      '--require-mode','rf_to_oatof_pre_pulse_interface_transport'
  ) -FailureMessage 'The frozen PrePulse timing/source run manifest is invalid.'
  $sourceManifestDocument = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($sourceManifestDocument.role -ne 'simulation_run_manifest' -or
      $sourceManifestDocument.status -ne 'success' -or
      $sourceManifestDocument.project -ne $upstreamProjectId -or
      $sourceManifestDocument.mode -ne 'rf_to_oatof_pre_pulse_interface_transport' -or
      $sourceManifestDocument.run_id -ne $SourceRunId) {
    throw 'PulseCapture source manifest identity or role is invalid.'
  }

  $sourceRunConfig = Join-Path $inputDir 'pre_pulse_source_run_config.json'
  $sourceRunConfigIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath ([string]$sourceManifestDocument.run_config.path) `
    -Destination $sourceRunConfig -ManifestRecord $sourceManifestDocument.run_config `
    -Role 'run_config'
  $sourceRunConfiguration = Get-Content -LiteralPath $sourceRunConfig -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($sourceRunConfiguration.run_id -ne $SourceRunId -or
      $sourceRunConfiguration.project -ne $upstreamProjectId -or
      $sourceRunConfiguration.mode -ne 'rf_to_oatof_pre_pulse_interface_transport' -or
      -not [bool]$sourceRunConfiguration.parameters.particle_tracking) {
    throw 'PulseCapture requires one successful PrePulse particle source run.'
  }
  Assert-RfOatofSourceIdentityMatches `
    -Actual $sourceRunConfiguration.source_particle_identity `
    -Expected $runtime.source_identity `
    -Role 'PulseCapture upstream particle source'

  $sourcePrePulseContract = [string]$sourceRunConfiguration.inputs.pre_pulse_contract
  $sourceResolvedConnection = [string]$sourceRunConfiguration.inputs.resolved_connection
  $particleOriginal = [string]$sourceRunConfiguration.inputs.particle_source
  $timingStateOriginal = Join-Path $timingRun 'results\pre_pulse_interface_transport_particles.csv'
  $particleInput = Join-Path $inputDir 'canonical_rf_exit_at_pre_pulse_connector.csv'
  $timingState = Join-Path $inputDir 'pre_pulse_interface_transport_particles.csv'
  $sourcePrePulseIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $sourcePrePulseContract -Destination $pre_pulse `
    -ManifestRecord (Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 'pre_pulse_contract') `
    -Role 'pre_pulse_contract'
  $sourceResolvedIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $sourceResolvedConnection -Destination $resolvedConnection `
    -ManifestRecord (Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 'resolved_connection') `
    -Role 'resolved_connection'
  $sourceParticleIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $particleOriginal -Destination $particleInput `
    -ManifestRecord (Get-RfManifestInputRecord -Manifest $sourceManifestDocument -Role 'particle_source') `
    -Role 'particle_source'
  $timingOutputRecord = Get-RfManifestOutputRecord -Manifest $sourceManifestDocument `
    -ExpectedPath $timingStateOriginal -Role 'timing_state'
  $sourceTimingIdentity = Copy-RfManifestBoundFile -SourceRunRoot $timingRun `
    -SourcePath $timingStateOriginal -Destination $timingState `
    -ManifestRecord $timingOutputRecord -Role 'timing_state'
  $resolvedPrePulseDocument = Get-Content -LiteralPath $pre_pulse -Raw -Encoding UTF8 | ConvertFrom-Json
  $resolvedConnectionDocument = Get-Content -LiteralPath $resolvedConnection -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($resolvedConnectionDocument.role -ne 'resolved_connection_do_not_edit' -or
      $resolvedConnectionDocument.compatibility.status -ne 'pass' -or
      $resolvedConnectionDocument.clock_alignment.mode -ne 'same_origin') {
    throw 'PulseCapture requires the compatible resolved connection frozen by PrePulse.'
  }
  $connectionProfileId =
    [string]$sourceRunConfiguration.parameters.connection_profile_id
  if ($resolvedConnectionDocument.selection.connection_profile_id -ne
      $connectionProfileId -or
      $connectionProfileId -ne $ExpectedConnectionProfileId) {
    throw 'PulseCapture source profile differs from its resolved connection.'
  }
  $budgetBinding = Initialize-RfIntegrationStageBudget `
    -ResolvedBudget $ResolvedEngineeringBudget -InputDir $inputDir `
    -ExpectedIntegrationId `
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $connectionProfileId `
    -StageId 'pulse_capture' -Solver comsol
  $resourceUsage = Join-Path $logDir 'resource_usage.json'

  $particleValidation = Join-Path $inputDir 'canonical_rf_exit_component_state_validation.json'
  Invoke-PulseCaptureSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    '-m','common.contracts.component_particle_state',
    '--state',$particleInput,'--output',$particleValidation
  ) -FailureMessage 'PulseCapture canonical particle input failed the common component-state contract.'
  if (-not (Test-Path -LiteralPath $particleValidation -PathType Leaf)) {
    throw 'PulseCapture canonical particle input failed the common component-state contract.'
  }
  $particleValidationDocument = Get-Content -LiteralPath $particleValidation `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($particleValidationDocument.status -ne 'PASS' -or
      [int]$particleValidationDocument.particles -ne
        [int]$resolvedPrePulseDocument.particle_runtime.source_particles) {
    throw 'PulseCapture canonical particle validation report is incomplete or inconsistent.'
  }
  $pulseSchedule = Join-Path $inputDir 'pulse_capture_centroid_pulse_schedule.json'
  Invoke-PulseCaptureSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $scheduler,'--particle-state',$timingState,
    '--oatof-baseline',$oaBaselineSnapshot,
    '--pre-pulse-contract',$pre_pulse,'--resolved-connection',$resolvedConnection,
    '--policy',$pulsePolicy,
    '--output',$pulseSchedule
  ) -FailureMessage 'PulseCapture centroid pulse schedule derivation failed.'
  $scheduleDocument = Get-Content -LiteralPath $pulseSchedule -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($scheduleDocument.role -ne 'rf_to_oatof_pulse_capture_centroid_pulse_schedule' -or
      $scheduleDocument.status -ne 'PASS' -or
      [string]$scheduleDocument.source_particle_table_sha256 -ne
        (Get-FileHash -LiteralPath $timingState -Algorithm SHA256).Hash) {
    throw 'PulseCapture derived pulse schedule identity is invalid.'
  }

  $terminal = Join-Path $resultDir 'pulse_capture_particle_terminal_census.csv'
  $capture = Join-Path $resultDir 'pulse_capture_pulse_left_limit_state.csv'
  $localExit = Join-Path $resultDir 'pulse_capture_local_accelerator_exit.csv'
  $metrics = Join-Path $resultDir 'pulse_capture_metrics.json'
  $audit = Join-Path $resultDir 'pulse_capture_particle_chain_audit.json'
  $localExitValidation = Join-Path $resultDir 'pulse_capture_local_accelerator_exit_validation.json'
  $snapshotFigure = Join-Path $resultDir 'pulse_capture_pulse_geometry_snapshot.png'
  $snapshotMetadata = Join-Path $resultDir 'pulse_capture_pulse_geometry_snapshot.json'
  $report = Join-Path $logDir 'comsol_pulse_capture.txt'
  $sourceIdentity = [ordered]@{
    run_id = $SourceRunId
    manifest_sha256 = $sourceManifestIdentity.sha256
    run_config_sha256 = $sourceRunConfigIdentity.sha256
    pre_pulse_contract_sha256 = $sourcePrePulseIdentity.sha256
    resolved_connection_sha256 = $sourceResolvedIdentity.sha256
    particle_sha256 = $sourceParticleIdentity.sha256
    particle_validation_sha256 = (Get-FileHash -LiteralPath $particleValidation -Algorithm SHA256).Hash
    timing_state_sha256 = $sourceTimingIdentity.sha256
  }
  $runConfiguration = [ordered]@{
    schema_version = 2
    run_id = $RunId
    project = $upstreamProjectId
    mode = 'rf_to_oatof_pulse_capture'
    project_root = $repoRoot
    inputs = [ordered]@{
      task = $task; geometry_builder = $geometryBuilder; field_builder = $fieldBuilder
      runner = $runner; run_artifact_support = $support; pulse_capture_contract = $pulse_capture
      pre_pulse_contract = $pre_pulse; shared_physical_port_joint_geometry = $sharedJoint
      resolved_source_contract = $resolvedSourceContract
      upstream_resolved_design = $rf
      interface_stage_plan = $interfaceStagePlan
      resolved_connection = $resolvedConnection
      runtime_binding = $runtimeBindingFrozen
      pulse_timing_policy = $pulsePolicy; pulse_scheduler = $scheduler
      snapshot_analysis = $snapshotAnalysis; audit_analysis = $auditAnalysis
      local_exit_adapter = $localExitAdapter
      code_inventory = $dependencyContract
      dependency_contract = $dependencyPublication.dependency_contract_path
      oatof_baseline = $oaBaselineSnapshot
      oatof_baseline_matlab = $oaBaselineMatlab
      oatof_accelerator_builder = $oaBuilderSnapshot
      oatof_accelerator_builder_matlab = $oaBuilderMatlab
      source_run_manifest = $sourceManifest
      source_run_config = $sourceRunConfig
      resolved_integration_engineering_budget = $budgetBinding.frozen_budget
      resolved_stage_resource_budget = $budgetBinding.stage_budget
      particle_source = $particleInput; particle_state_validation = $particleValidation
      timing_state = $timingState; pulse_schedule = $pulseSchedule
    }
    dependency_identities = $dependencyIdentities
    resource_budget_identity = [ordered]@{
      resolved_budget_sha256 = $budgetBinding.resolved_budget_sha256
      stage_budget_sha256 = $budgetBinding.stage_budget_sha256
    }
    source_particle_identity = $sourceIdentity
    upstream_source_identity = $runtime.source_identity
    parameters = [ordered]@{
      source_particles = [int]$runtime.source_record.particle_count
      connector_gap_mm = [double]$resolvedConnectionDocument.connector.length_mm
      connection_profile_id = [string]$sourceRunConfiguration.parameters.connection_profile_id
      source_branch_id = $runtime.source_branch_id
      pulse_time_us = [double]$scheduleDocument.derived_pulse_time_us
      pulse_width_us = [double]$scheduleDocument.pulse_width_us
      rise_fall_model = [string]$pulse_captureDocument.waveform.rise_fall_model
      pre_pulse_oatof_field_scale = 0.0; pulse_oatof_field_scale = 1.0
      post_pulse_oatof_field_scale = 0.0; solver_rerun = $true
      dense_trajectories_saved = $false; pulse_capture_stage_passed = $false
    }
    artifact_retention = [ordered]@{
      policy_version = 1
      class = 'compact'
      reason = $null
    }
    formal_gate_passed = $false
  }
  Write-RunJson -Path $package.run_config -Depth 9 -Value $runConfiguration
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1; role = 'rf_to_oatof_pulse_capture_summary'
    status = 'interrupted'; reason = 'Run package initialized; final status not yet recorded.'
  })
  Write-RunManifest -Python $python -RepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status interrupted -Software $software

  $environmentNames = @(
    'RF_OATOF_PulseCapture_METRICS','RF_OATOF_PulseCapture_TERMINAL_OUTPUT','RF_OATOF_PulseCapture_CAPTURE_OUTPUT',
    'RF_OATOF_PulseCapture_CONTRACT','RF_OATOF_PulseCapture_PrePulse_CONTRACT',
    'RF_OATOF_PulseCapture_SHARED_JOINT_CONTRACT','RF_OATOF_PulseCapture_RF_RESOLVED','RF_OATOF_PulseCapture_OA_BASELINE',
    'RF_OATOF_RESOLVED_CONNECTION','RF_OATOF_PulseCapture_PULSE_SCHEDULE',
    'RF_OATOF_PulseCapture_PARTICLE_INPUT','RF_OATOF_PulseCapture_OA_COMSOL_DIR',
    'RF_OATOF_MULTIPOLE_COMSOL_DIR'
  )
  $oldEnvironment = Save-RunEnvironment -Names $environmentNames
  $comsolWrapperStdout = Join-Path $logDir 'comsol_wrapper.stdout.log'
  $comsolWrapperStderr = Join-Path $logDir 'comsol_wrapper.stderr.log'
  try {
    $env:RF_OATOF_PulseCapture_METRICS=$metrics; $env:RF_OATOF_PulseCapture_TERMINAL_OUTPUT=$terminal
    $env:RF_OATOF_PulseCapture_CAPTURE_OUTPUT=$capture
    $env:RF_OATOF_PulseCapture_CONTRACT=$pulse_capture; $env:RF_OATOF_PulseCapture_PrePulse_CONTRACT=$pre_pulse
    $env:RF_OATOF_PulseCapture_SHARED_JOINT_CONTRACT=$sharedJoint; $env:RF_OATOF_PulseCapture_RF_RESOLVED=$rf
    $env:RF_OATOF_RESOLVED_CONNECTION=$resolvedConnection
    $env:RF_OATOF_PulseCapture_OA_BASELINE=$oaBaselineMatlab
    $env:RF_OATOF_PulseCapture_PULSE_SCHEDULE=$pulseSchedule
    $env:RF_OATOF_PulseCapture_PARTICLE_INPUT=$particleInput; $env:RF_OATOF_PulseCapture_OA_COMSOL_DIR=$inputDir
    $env:RF_OATOF_MULTIPOLE_COMSOL_DIR =
      Split-Path -Parent $multipoleRodBuilder
    $powerShellExe = (Get-Process -Id $PID).Path
    $processResult = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budgetBinding.stage_budget `
      -RunDir $package.run_dir -UsagePath $resourceUsage `
      -FilePath $powerShellExe -WorkingDirectory $snapshotRoot `
      -RedirectStandardOutput $comsolWrapperStdout `
      -RedirectStandardError $comsolWrapperStderr `
      -ArgumentList @(
        '-NoLogo','-NoProfile','-NonInteractive','-File',$frozenComsolRunner,
        '-TaskScript',$task,'-ReportPath',$report,'-StartupAttempts','1'
      )
    if ($processResult.resource_budget_exceeded) {
      $resourceBudgetExceeded = $true
      throw "COMSOL PulseCapture resource budget exceeded: $($processResult.limit_name)"
    }
    if ($processResult.exit_code -ne 0) {
      throw 'COMSOL PulseCapture pulse-capture task failed.'
    }
  } finally {
    Restore-RunEnvironment -Names $environmentNames -Snapshot $oldEnvironment
  }
  Invoke-PulseCaptureSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $localExitAdapter,'--source',$particleInput,'--terminal',$terminal,
    '--pulse-capture-contract',$pulse_capture,
    '--pre-pulse-contract',$pre_pulse,
    '--resolved-connection',$resolvedConnection,
    '--output',$localExit,'--validation',$localExitValidation
  ) -FailureMessage 'PulseCapture local-exit canonical adapter failed.'
  if (-not (Test-Path -LiteralPath $localExit -PathType Leaf) -or
      -not (Test-Path -LiteralPath $localExitValidation -PathType Leaf)) {
    throw 'PulseCapture local-exit canonical adapter failed.'
  }
  Invoke-PulseCaptureSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $auditAnalysis,'--source',$particleInput,'--terminal',$terminal,
    '--capture',$capture,'--local-exit',$localExit,'--schedule',$pulseSchedule,
    '--pulse-capture-contract',$pulse_capture,
    '--pre-pulse-contract',$pre_pulse,
    '--resolved-connection',$resolvedConnection,
    '--output',$audit
  ) -FailureMessage 'PulseCapture particle-chain audit failed.'
  Invoke-PulseCaptureSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
    $snapshotAnalysis,'--capture',$capture,'--events',$terminal,
    '--oatof-baseline',$oaBaselineSnapshot,
    '--resolved-connection',$resolvedConnection,
    '--figure',$snapshotFigure,'--metadata',$snapshotMetadata
  ) -FailureMessage 'PulseCapture pulse snapshot generation failed.'
  $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  $auditResult = Get-Content -LiteralPath $audit -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($result.status -ne 'PASS' -or $auditResult.status -ne 'PASS' -or
      [int]$result.source_particles -ne
        [int]$resolvedPrePulseDocument.particle_runtime.source_particles -or
      [int]$result.active_at_pulse -lt [int]$pulse_captureDocument.runtime.minimum_active_at_pulse -or
      [int]$result.local_accelerator_exit -lt [int]$pulse_captureDocument.runtime.minimum_local_accelerator_exit -or
      [int]$result.local_accelerator_exit -ne [int]$auditResult.local_accelerator_exit -or
      [bool]$result.pulse_capture_stage_passed -or [bool]$result.formal_gate_passed) {
    throw 'PulseCapture result violates the qualification-limited functional contract.'
  }
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1; role = 'rf_to_oatof_pulse_capture_summary'; status = 'success'
    source_particles = [int]$result.source_particles
    oatof_entry_crossings = [int]$result.oatof_entry_crossings
    active_at_pulse = [int]$result.active_at_pulse
    inside_ideal_reference_volume_at_pulse = [int]$result.inside_ideal_reference_volume_at_pulse
    local_accelerator_exit = [int]$result.local_accelerator_exit
    pulse_time_us = [double]$result.pulse_time_us; pulse_width_us = [double]$result.pulse_width_us
    pulse_snapshot_figure = 'results/pulse_capture_pulse_geometry_snapshot.png'
    dense_trajectories_saved = $false; pulse_capture_stage_passed = $false; formal_gate_passed = $false
  })
  $outputs = @(
    $terminal,$capture,$localExit,$localExitValidation,$metrics,$audit,
    $snapshotFigure,$snapshotMetadata,$report,$comsolWrapperStdout,
    $comsolWrapperStderr,$resourceUsage,$package.summary
  )
  $retentionActions = Apply-RunArtifactRetention -Python $python `
    -RepoRoot $manifestToolRoot -RunConfig $package.run_config
  $outputs = @($outputs | Where-Object {
    Test-Path -LiteralPath $_ -PathType Leaf
  })
  $outputs += $retentionActions
  if (-not (Complete-ResourceUsage `
      -ResolvedBudgetPath $budgetBinding.stage_budget `
      -RunDir $package.run_dir -UsagePath $resourceUsage)) {
    $resourceBudgetExceeded = $true
    throw 'COMSOL PulseCapture compact final retained-byte budget exceeded.'
  }
  Write-RunManifest -Python $python -RepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  Write-Output "STATUS=PASS RUN_ID=$RunId SOURCE=$($result.source_particles) ACTIVE=$($result.active_at_pulse) LOCAL_EXIT=$($result.local_accelerator_exit) PulseCapture_STAGE_PASS=false"
} catch {
  Complete-FailedRun -Python $python -RepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_to_oatof_pulse_capture_summary' `
    -Reason $_.Exception.Message -Software $software `
    -Status $(if ($resourceBudgetExceeded) { 'interrupted' } else { 'failed' }) `
    -FailureClass $(if ($resourceBudgetExceeded) {
      'resource_budget_exceeded'
    } else { '' }) `
    -ResourceUsagePath $(if ($resourceBudgetExceeded) { $resourceUsage } else { '' })
  throw
} finally {
  Remove-RunPackageExecutionAlias -Package $package
}
