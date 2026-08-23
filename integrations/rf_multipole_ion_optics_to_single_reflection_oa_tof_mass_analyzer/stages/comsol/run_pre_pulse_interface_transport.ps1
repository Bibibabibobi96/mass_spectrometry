param(
  [string]$RunId = '',
  [switch]$Particles,
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [Parameter(Mandatory)][string]$RuntimeBinding,
  [Parameter(Mandatory)][ValidateSet('comsol','simion')]
  [string]$SourceBranchId,
  [Parameter(Mandatory)][string]$ResolvedSourceContract,
  [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256,
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
. (Join-Path $integrationRoot 'runtime\runtime_binding.ps1')
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repoRoot `
  -ResolvedConnection $ResolvedConnection -RuntimeBinding $RuntimeBinding `
  -ExpectedConnectionProfileId $ConnectionProfileId `
  -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256
$upstreamProjectId = $runtime.upstream_project_id
$projectRoot = Join-Path $repoRoot "projects\$upstreamProjectId"
$supportSource = $runtime.run_artifact_support
. $supportSource
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }

function Invoke-PrePulseSnapshotPython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SnapshotRoot,
    [Parameter(Mandatory)][string[]]$Arguments,
    [Parameter(Mandatory)][string]$FailureMessage,
    [hashtable]$AdditionalEnvironment = @{}
  )
  $environmentNames = @('PYTHONPATH','PYTHONNOUSERSITE') + @($AdditionalEnvironment.Keys)
  $savedEnvironment = Save-RunEnvironment -Names $environmentNames
  try {
    $env:PYTHONPATH = $SnapshotRoot
    $env:PYTHONNOUSERSITE = '1'
    foreach ($name in $AdditionalEnvironment.Keys) {
      [Environment]::SetEnvironmentVariable($name, [string]$AdditionalEnvironment[$name])
    }
    Push-Location -LiteralPath $SnapshotRoot
    try { & $Python @Arguments } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
  } finally {
    Restore-RunEnvironment -Names $environmentNames -Snapshot $savedEnvironment
  }
}

$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$upstreamProjectId"
$contractSource = $runtime.contracts.pre_pulse_contract
$sourceContractSource = $runtime.contracts.resolved_source_contract
$baseContractDocument = Get-Content -LiteralPath $contractSource -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$baseContractDocument.permissions.field_solve_allowed) {
  throw 'The PrePulse contract does not authorize a field solve.'
}
if ($Particles -and -not [bool]$baseContractDocument.permissions.particle_runtime_allowed) {
  throw 'The PrePulse contract does not authorize particle runtime.'
}
$resolvedConnectionDocument = Get-Content -LiteralPath $ResolvedConnection -Raw -Encoding UTF8 | ConvertFrom-Json
if ($resolvedConnectionDocument.selection.connection_profile_id -ne $ConnectionProfileId) {
  throw 'Resolved connection identity differs from ConnectionProfileId.'
}
if ($resolvedConnectionDocument.role -ne 'resolved_connection_do_not_edit' -or
    $resolvedConnectionDocument.compatibility.status -ne 'pass' -or
    $resolvedConnectionDocument.coupling_mode -ne 'monolithic_joint_solve') {
  throw 'PrePulse requires one compatible monolithic resolved connection.'
}
$gapMm = [double]$resolvedConnectionDocument.connector.length_mm
if (-not [double]::IsFinite($gapMm) -or $gapMm -lt 0) {
  throw 'The PrePulse connector gap must be finite and non-negative.'
}
$positionToleranceMm = [double](
  $resolvedConnectionDocument.spatial_registration.position_tolerance_mm
)
if (-not [double]::IsFinite($positionToleranceMm) -or
    $positionToleranceMm -le 0 -or
    [Math]::Abs(
      [double]$resolvedConnectionDocument.spatial_registration.actual_gap_mm -
      $gapMm
    ) -gt $positionToleranceMm) {
  throw 'Resolved connector length differs from the resolved spatial gap.'
}
if ($resolvedConnectionDocument.potential_alignment.mode -ne 'continuous' -or
    [Math]::Abs([double]$resolvedConnectionDocument.potential_alignment.actual_step_V) -gt
      [double]$resolvedConnectionDocument.potential_alignment.tolerance_V -or
    $resolvedConnectionDocument.clock_alignment.mode -ne 'same_origin' -or
    [Math]::Abs([double]$resolvedConnectionDocument.clock_alignment.offset_s) -gt 1e-15) {
  throw 'PrePulse requires continuous potential and one unchanged instrument clock.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $gapLabel = ('{0:g}' -f $gapMm).Replace('.','p')
  $sourceParticleCount = [int]$runtime.source_record.particle_count
  $suffix = if ($Particles) { "__sim__comsol__rf-oatof-pre_pulse-connector-gap${gapLabel}__n${sourceParticleCount}" } `
    else { "__analysis__comsol__rf-oatof-pre_pulse-no-pulse-field__gap${gapLabel}" }
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + $suffix
}
$mode = if ($Particles) { 'rf_to_oatof_pre_pulse_interface_transport' } `
  else { 'rf_to_oatof_pre_pulse_interface_transport_no_pulse_field' }
$summaryRole = if ($Particles) { 'rf_to_oatof_pre_pulse_interface_transport_summary' } `
  else { 'rf_to_oatof_pre_pulse_no_pulse_field_summary' }
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $upstreamProjectId -Mode $mode -Software $software `
  -RetentionContractEnabled -RetentionClass compact -UseShortExecutionPath
$manifestToolRoot = $repoRoot
$resourceBudgetExceeded = $false
$python = $package.python
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir

try {
  $task = Join-Path $inputDir 'solve_pre_pulse_interface_transport_field.m'
  $geometryBuilder = Join-Path $inputDir 'build_pre_pulse_interface_transport_model.m'
  $fieldBuilder = Join-Path $inputDir 'prepare_pre_pulse_interface_transport_field_model.m'
  $runner = Join-Path $inputDir 'run_pre_pulse_interface_transport_field.ps1.txt'
  $support = Join-Path $inputDir 'run_artifacts.ps1.txt'
  $snapshotRoot = Join-Path $inputDir 'runtime_snapshot'
  $contract = Join-Path $inputDir 'rf_to_oatof_pre_pulse_passive_connector.json'
  $sourceContract = Join-Path $inputDir 'resolved_source_contract.json'
  $runtimeBindingFrozen = Join-Path $inputDir 'runtime_binding.json'
  $rfResolved = Join-Path $inputDir 'upstream_resolved_design.json'
  $frozenResolvedConnection = Join-Path $inputDir 'resolved_connection.json'
  $particleInput = $null
  $particleOutput = $null
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'solve_pre_pulse_interface_transport_field.m') -Destination $task
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_pre_pulse_interface_transport_model.m') -Destination $geometryBuilder
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'prepare_pre_pulse_interface_transport_field_model.m') -Destination $fieldBuilder
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  Copy-Item -LiteralPath $contractSource -Destination $contract
  Copy-Item -LiteralPath $sourceContractSource -Destination $sourceContract
  Copy-Item -LiteralPath $runtime.binding_path -Destination $runtimeBindingFrozen
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design `
    -Destination $rfResolved
  Copy-Item -LiteralPath $ResolvedConnection -Destination $frozenResolvedConnection
  $resolvedConnectionSha256 = (
    Get-FileHash -LiteralPath $ResolvedConnection -Algorithm SHA256
  ).Hash
  if ((Get-FileHash -LiteralPath $frozenResolvedConnection -Algorithm SHA256).Hash -ne
      $resolvedConnectionSha256) {
    throw 'Resolved connection changed while frozen into the PrePulse run.'
  }

  $dependencyPublication = Publish-RfOatofDependencyInventory `
    -Runtime $runtime -RepoRoot $repoRoot -InputDir $inputDir -Role 'PrePulse'
  $dependencyContract = $dependencyPublication.code_inventory_path
  $dependencyDocument = Get-Content -LiteralPath $dependencyContract `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $dependencyConsumer = 'pre_pulse_interface_transport'
  if (@($dependencyDocument.consumer_ids) -notcontains $dependencyConsumer) {
    throw "PrePulse dependency consumer is not declared: $dependencyConsumer"
  }
  $selectedDependencies = @(
    $dependencyDocument.dependencies |
      Where-Object { @($_.consumers) -contains $dependencyConsumer }
  )
  if ($selectedDependencies.Count -eq 0 -or
      @($selectedDependencies.id | Select-Object -Unique).Count -ne $selectedDependencies.Count) {
    throw 'PrePulse dependency consumer subset is empty or has duplicate identities.'
  }
  $dependencyIdentities = [ordered]@{}
  $dependencySnapshotPaths = @{}
  foreach ($dependency in $selectedDependencies) {
    $identity = Copy-RfFrozenDependency -RepoRoot $repoRoot -InputDir $inputDir `
      -Dependency $dependency
    if ((Get-FileHash -LiteralPath $identity.snapshot_path -Algorithm SHA256).Hash -ne $identity.sha256) {
      throw "PrePulse dependency snapshot identity differs: $($identity.id)"
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
  $sharedJoint = $dependencySnapshotPaths['rf_shared_joint_geometry']
  $oaBaseline = $dependencySnapshotPaths['oatof_baseline']
  $oaBaselineSnapshot = $dependencySnapshotPaths['oatof_baseline']
  $oaBuilder = $dependencySnapshotPaths['oatof_accelerator_geometry_builder']
  $oatofHandoff = Join-Path $inputDir 'source_adapter.py'
  $null = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $runtime.source_adapter -Destination $oatofHandoff `
    -Role 'resolved source adapter'
  $multipoleRodBuilder =
    $dependencySnapshotPaths['common_create_multipole_round_rods']
  $frozenManifestVerifier = $dependencySnapshotPaths['common_verify_run_manifest']
  $frozenComsolRunner = $dependencySnapshotPaths['common_comsol_runner']
  $handoffBuilder = $oatofHandoff
  $frozenResourceBudgetSupport =
    $dependencySnapshotPaths['common_resource_budget_support']
  if (-not (Test-Path -LiteralPath $frozenResourceBudgetSupport -PathType Leaf)) {
    throw 'PrePulse frozen resource-budget support is missing.'
  }
  if (-not (Test-Path -LiteralPath $oatofHandoff -PathType Leaf) -or
      -not (Test-Path -LiteralPath $multipoleRodBuilder -PathType Leaf)) {
    throw 'PrePulse handoff adapter or common multipole rod builder is missing.'
  }
  . $frozenResourceBudgetSupport
  $budgetBinding = Initialize-RfIntegrationStageBudget `
    -ResolvedBudget $ResolvedEngineeringBudget -InputDir $inputDir `
    -ExpectedIntegrationId `
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $ConnectionProfileId `
    -StageId 'pre_pulse_interface_transport' -Solver comsol
  $resourceUsage = Join-Path $logDir 'resource_usage.json'

  $contractDocument = Get-Content -LiteralPath $contract -Raw -Encoding UTF8 | ConvertFrom-Json
  # Publish the runtime-selected canonical source for both solver modes.  The
  # Particles switch controls COMSOL particle tracking, not whether the frozen
  # field run can serve as an audited source for the SIMION interface stage.
  $sourceContractDocument = $runtime.resolved_source_contract
    $sourceRecord = $runtime.source_record
    $recordedProjectId = $runtime.recorded_project_id
    if ($contractDocument.particle_runtime.source_particle_count_policy -ne
        'runtime_selected_handoff_rows') {
      throw 'PrePulse source-particle count policy differs.'
    }
    $contractDocument.particle_runtime.source_particles =
      [int]$sourceRecord.particle_count
    $contractDocument | ConvertTo-Json -Depth 20 |
      Set-Content -LiteralPath $contract -Encoding UTF8
    $candidate = $contractDocument.particle_runtime
    $sourceManifestOriginal = $runtime.source_manifest
    $sourceEventsOriginal = $runtime.source_state
    $sourceMetadataOriginal = $runtime.source_metadata
    Invoke-PrePulseSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
      $frozenManifestVerifier,$sourceManifestOriginal,
      '--require-status','success',
      '--require-run-id',([string]$sourceRecord.run_id),
      '--require-project',$recordedProjectId
    ) -FailureMessage 'The frozen PrePulse particle source manifest is invalid.'
    $sourceManifest = Join-Path $inputDir 'source_run_manifest.json'
    $sourceEvents = Join-Path $inputDir (
      [System.IO.Path]::GetFileName($sourceEventsOriginal)
    )
    $sourceMetadata = Join-Path $inputDir 'particle_source_metadata.json'
    $handoffBuilder = $oatofHandoff
    $sourceManifestIdentity = Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $sourceManifestOriginal -Destination $sourceManifest `
      -Role 'runtime-bound source manifest'
    $sourceEventsIdentity = Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $sourceEventsOriginal -Destination $sourceEvents `
      -Role 'runtime-bound source state'
    $sourceMetadataIdentity = Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $sourceMetadataOriginal -Destination $sourceMetadata `
      -Role 'runtime-bound source metadata'
    $particleInput = Join-Path $inputDir 'canonical_rf_exit_at_pre_pulse_connector.csv'
    $particleIon = Join-Path $inputDir 'rf_exit_at_pre_pulse_connector.ion'
    $particleRowMap = Join-Path $inputDir 'particle_row_map.csv'
    $particleMetadata = Join-Path $inputDir 'pre_pulse_handoff_metadata.json'
    if ($sourceContractDocument.adapter.callable -eq
        'publish_family_source_bundle') {
      $handoffBuilder = $oatofHandoff
      $handoffContract = Join-Path $inputDir 'handoff_publication_contract.json'
      $sourceParticleSource = Join-Path $inputDir 'particle_source.csv'
      Copy-Item -LiteralPath `
        $runtime.source_adapter_dependencies.handoff_publication_contract `
        -Destination $handoffContract
      $sourceParticleSourceIdentity = Copy-RfStableFile `
        -SourceRunRoot $workspaceRoot `
        -SourcePath $runtime.source_particle_source `
        -Destination $sourceParticleSource `
        -Role 'runtime-bound canonical mother source'
      Invoke-PrePulseSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
        -Arguments @(
          $handoffBuilder,
          '--handoff-contract',$handoffContract,
          '--resolved-connection',$frozenResolvedConnection,
          '--state',$sourceEvents,'--source',$sourceParticleSource,
          '--canonical-output',$particleInput,'--ion-output',$particleIon,
          '--row-map-output',$particleRowMap,'--metadata-output',$particleMetadata
        ) -FailureMessage 'PrePulse family particle-source publication failed.'
    } else {
      throw 'Runtime source adapter callable is unsupported by PrePulse.'
    }
    $sourceParticleIdentity = [ordered]@{
      run_id = [string]$sourceRecord.run_id
      project_id = $recordedProjectId
      particle_count = [int]$sourceRecord.particle_count
      manifest_sha256 = $sourceManifestIdentity.sha256
      event_sha256 = $sourceEventsIdentity.sha256
      metadata_sha256 = $sourceMetadataIdentity.sha256
      adapter_sha256 = (
        Get-FileHash -LiteralPath $handoffBuilder -Algorithm SHA256
      ).Hash
    }
    if (-not [string]::IsNullOrWhiteSpace($runtime.source_branch_id)) {
      $sourceParticleIdentity.source_branch_id = $runtime.source_branch_id
      $sourceParticleIdentity.solver_id = $runtime.source_solver_id
      $sourceParticleIdentity.particle_source_sha256 = (
        Get-FileHash -LiteralPath $runtime.source_particle_source `
          -Algorithm SHA256
      ).Hash
    }
    $particleOutput = if ($Particles) {
      Join-Path $resultDir 'pre_pulse_interface_transport_particles.csv'
    } else { $null }
  $metrics = Join-Path $resultDir 'pre_pulse_no_pulse_field_metrics.json'
  $samples = Join-Path $resultDir 'pre_pulse_no_pulse_field_samples.csv'
  $report = Join-Path $logDir 'comsol_pre_pulse_no_pulse_field.txt'
  $runConfiguration = [ordered]@{
    schema_version = 2
    run_id = $RunId
    project = $upstreamProjectId
    mode = $mode
    project_root = $repoRoot
    inputs = [ordered]@{
      task = $task
      geometry_builder = $geometryBuilder
      field_builder = $fieldBuilder
      runner = $runner
      run_artifact_support = $support
      runtime_binding = $runtimeBindingFrozen
      resolved_source_contract = $sourceContract
      pre_pulse_contract = $contract
      oatof_handoff_library = $handoffBuilder
      code_inventory = $dependencyContract
      dependency_contract = $dependencyPublication.dependency_contract_path
      shared_physical_port_joint_geometry = $sharedJoint
      upstream_resolved_design = $rfResolved
      resolved_connection = $frozenResolvedConnection
      oatof_baseline = $oaBaseline
      oatof_accelerator_builder = $oaBuilder
      particle_source = $particleInput
      resolved_integration_engineering_budget = $budgetBinding.frozen_budget
      resolved_stage_resource_budget = $budgetBinding.stage_budget
    }
    dependency_identities = $dependencyIdentities
    resource_budget_identity = [ordered]@{
      resolved_budget_sha256 = $budgetBinding.resolved_budget_sha256
      stage_budget_sha256 = $budgetBinding.stage_budget_sha256
    }
    source_particle_identity = $sourceParticleIdentity
    parameters = [ordered]@{
      connector_gap_mm = $gapMm
      connection_profile_id = $ConnectionProfileId
      source_branch_id = $runtime.source_branch_id
      resolved_connection_sha256 = $resolvedConnectionSha256
      dependency_consumer_id = $dependencyConsumer
      field_bases = @('axial_dc','rf_unit_100_V','oatof_pulse')
      oa_extraction_pulse = $false
      particle_tracking = [bool]$Particles
      model_saved = $false
      mesh_convergence_claimed = $false
    }
    artifact_retention = [ordered]@{
      policy_version = 1
      class = 'compact'
      reason = $null
    }
    formal_gate_passed = $false
  }
  foreach ($identity in $dependencyIdentities.Values) {
    $runConfiguration.inputs[[string]$identity.frozen_input_name] = [string]$identity.snapshot_path
  }
  if ($Particles) {
    $runConfiguration.inputs.source_run_manifest = $sourceManifest
    $runConfiguration.inputs.source_events = $sourceEvents
    $runConfiguration.inputs.source_metadata = $sourceMetadata
    $runConfiguration.inputs.handoff_builder = $handoffBuilder
    $runConfiguration.inputs.handoff_contract = $handoffContract
    $runConfiguration.inputs.canonical_mother_source = $sourceParticleSource
    $runConfiguration.inputs.particle_ion = $particleIon
    $runConfiguration.inputs.particle_row_map = $particleRowMap
    $runConfiguration.inputs.particle_handoff_metadata = $particleMetadata
  }
  Write-RunJson -Path $package.run_config -Depth 8 -Value $runConfiguration
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = $summaryRole
    status = 'interrupted'
    reason = 'Run package initialized; final status not yet recorded.'
  })
  Write-RunManifest -Python $python -RepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status interrupted -Software $software

  $environmentNames = @(
    'RF_OATOF_PrePulse_FIELD_METRICS','RF_OATOF_PrePulse_FIELD_SAMPLES','RF_OATOF_PrePulse_CONTRACT',
    'RF_OATOF_PrePulse_SHARED_JOINT_CONTRACT','RF_OATOF_PrePulse_RF_RESOLVED','RF_OATOF_PrePulse_OA_BASELINE',
    'RF_OATOF_RESOLVED_CONNECTION','RF_OATOF_RESOLVED_CONNECTION_SHA256',
    'RF_OATOF_PrePulse_OA_COMSOL_DIR','RF_OATOF_MULTIPOLE_COMSOL_DIR',
    'RF_OATOF_PrePulse_PARTICLE_INPUT','RF_OATOF_PrePulse_PARTICLE_OUTPUT'
  )
  $oldEnvironment = Save-RunEnvironment -Names $environmentNames
  $comsolWrapperStdout = Join-Path $logDir 'comsol_wrapper.stdout.log'
  $comsolWrapperStderr = Join-Path $logDir 'comsol_wrapper.stderr.log'
  try {
    $env:RF_OATOF_PrePulse_FIELD_METRICS = $metrics
    $env:RF_OATOF_PrePulse_FIELD_SAMPLES = $samples
    $env:RF_OATOF_PrePulse_CONTRACT = $contract
    $env:RF_OATOF_PrePulse_SHARED_JOINT_CONTRACT = $sharedJoint
    $env:RF_OATOF_PrePulse_RF_RESOLVED = $rfResolved
    $env:RF_OATOF_RESOLVED_CONNECTION = $frozenResolvedConnection
    $env:RF_OATOF_RESOLVED_CONNECTION_SHA256 = $resolvedConnectionSha256
    $env:RF_OATOF_PrePulse_OA_BASELINE = $oaBaseline
    $env:RF_OATOF_PrePulse_OA_COMSOL_DIR = $inputDir
    $env:RF_OATOF_MULTIPOLE_COMSOL_DIR =
      Split-Path -Parent $multipoleRodBuilder
    if ($Particles) {
      $env:RF_OATOF_PrePulse_PARTICLE_INPUT = $particleInput
      $env:RF_OATOF_PrePulse_PARTICLE_OUTPUT = $particleOutput
    }
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
      throw "COMSOL PrePulse resource budget exceeded: $($processResult.limit_name)"
    }
    if ($processResult.exit_code -ne 0) {
      throw 'COMSOL PrePulse no-pulse field task failed.'
    }
  } finally {
    Restore-RunEnvironment -Names $environmentNames -Snapshot $oldEnvironment
  }

  $fieldMetrics = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  $expectedResolvedSha256 = (
    Get-FileHash -LiteralPath $frozenResolvedConnection -Algorithm SHA256
  ).Hash
  if ($fieldMetrics.status -ne 'SOLVED' -or -not [bool]$fieldMetrics.all_probe_values_finite -or
      [string]$fieldMetrics.frame_id -ne
        [string]$resolvedConnectionDocument.port_geometry.downstream.coordinate_frame.frame_id -or
      [string]$fieldMetrics.position_unit -ne 'mm' -or
      [string]$fieldMetrics.resolved_connection_sha256 -ne $expectedResolvedSha256 -or
      [double]$fieldMetrics.rf_off_axis_field_norm_V_per_m -le 0 -or
      [bool]$fieldMetrics.particle_runtime_executed -ne [bool]$Particles -or
      [bool]$fieldMetrics.oa_extraction_pulse_included -or
      [bool]$fieldMetrics.mesh_convergence_claimed -or [bool]$fieldMetrics.pre_pulse_stage_passed) {
    throw 'PrePulse field metrics violate the no-pulse functional contract.'
  }
  if ($Particles -and
      ([int]$fieldMetrics.particle_input_count -ne
        [int]$contractDocument.particle_runtime.source_particles -or
       [int]$fieldMetrics.oatof_entry_crossings -lt
        [int]$contractDocument.particle_runtime.minimum_oatof_entry_crossings)) {
    throw 'PrePulse particle metrics violate the nominal functional contract.'
  }
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = $summaryRole
    status = 'success'
    metrics = 'results/pre_pulse_no_pulse_field_metrics.json'
    samples = 'results/pre_pulse_no_pulse_field_samples.csv'
    gap_mm = $gapMm
    field_bases_solved = 3
    finite_probe_rows = [int]$fieldMetrics.probe_count
    particle_runtime = [bool]$Particles
    particle_input_count = [int]$fieldMetrics.particle_input_count
    oatof_entry_crossings = [int]$fieldMetrics.oatof_entry_crossings
    connector_losses = [int]$fieldMetrics.connector_losses
    oa_extraction_pulse = $false
    mesh_convergence_claimed = $false
    pre_pulse_stage_passed = $false
    formal_gate_passed = $false
  })
  $outputs = @(
    $metrics,$samples,$report,$comsolWrapperStdout,$comsolWrapperStderr,
    $resourceUsage,$package.summary
  )
  if ($Particles) { $outputs += $particleOutput }
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
    throw 'COMSOL PrePulse compact final retained-byte budget exceeded.'
  }
  Write-RunManifest -Python $python -RepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  Write-Output "STATUS=PASS RUN_ID=$RunId GAP_MM=$gapMm FIELD_BASES=2 PARTICLES=$Particles OA_PULSE=false"
} catch {
  Complete-FailedRun -Python $python -RepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole $summaryRole `
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
