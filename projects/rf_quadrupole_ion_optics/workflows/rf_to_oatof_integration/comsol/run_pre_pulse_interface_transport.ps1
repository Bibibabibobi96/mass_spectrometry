param(
  [string]$RunId = '',
  [switch]$Particles,
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$supportSource = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\runtime\run_artifacts.ps1')).Path
. $supportSource
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }

function Copy-PrePulseLocalSnapshotInput {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$SnapshotRoot,
    [Parameter(Mandatory)][string]$SourceRepoPath
  )
  $source = [IO.Path]::GetFullPath((Join-Path $RepoRoot $SourceRepoPath))
  $destination = [IO.Path]::GetFullPath((Join-Path $SnapshotRoot $SourceRepoPath))
  $snapshot = [IO.Path]::GetFullPath($SnapshotRoot).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
  )
  if (-not $destination.StartsWith(
      $snapshot + [IO.Path]::DirectorySeparatorChar,
      [StringComparison]::OrdinalIgnoreCase
  )) { throw "PrePulse local snapshot destination escapes inputs: $SourceRepoPath" }
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "PrePulse local snapshot source is missing: $SourceRepoPath"
  }
  if (Test-Path -LiteralPath $destination) {
    throw "PrePulse local snapshot destination already exists: $destination"
  }
  New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
  Copy-Item -LiteralPath $source -Destination $destination
  $sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  if ($sha256 -ne (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash) {
    throw "PrePulse local snapshot changed while copied: $SourceRepoPath"
  }
  return [pscustomobject]@{
    source_repo_path = $SourceRepoPath.Replace('\','/')
    frozen_path = $destination
    sha256 = $sha256
  }
}

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
  $savedEnvironment = Save-RfEnvironment -Names $environmentNames
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
    Restore-RfEnvironment -Names $environmentNames -Snapshot $savedEnvironment
  }
}

$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_ion_optics'
$contractSource = Join-Path $projectRoot 'config\rf_to_oatof_pre_pulse_passive_connector.json'
$dependencyContractSource = Join-Path $projectRoot 'config\rf_to_oatof_pre_pulse_dependencies.json'
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
if ([double]$resolvedConnectionDocument.spatial_registration.actual_gap_mm -ne $gapMm) {
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
  $suffix = if ($Particles) { "__sim__comsol__rf-oatof-pre_pulse-connector-gap${gapLabel}__n100" } `
    else { "__analysis__comsol__rf-oatof-pre_pulse-no-pulse-field__gap${gapLabel}" }
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + $suffix
}
$mode = if ($Particles) { 'rf_to_oatof_pre_pulse_interface_transport_n100' } `
  else { 'rf_to_oatof_pre_pulse_interface_transport_no_pulse_field' }
$summaryRole = if ($Particles) { 'rf_to_oatof_pre_pulse_interface_transport_n100_summary' } `
  else { 'rf_to_oatof_pre_pulse_no_pulse_field_summary' }
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'rf_quadrupole_ion_optics' -Mode $mode -Software $software `
  -RetentionContractEnabled -RetentionClass compact
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
  $snapshotRfProject = Join-Path $snapshotRoot 'projects\rf_quadrupole_ion_optics'
  $contract = Join-Path $inputDir 'rf_to_oatof_pre_pulse_passive_connector.json'
  $oatofHandoff = Join-Path $snapshotRfProject 'analysis\build_oatof_handoff.py'
  $frozenResolvedConnection = Join-Path $inputDir 'resolved_connection.json'
  $particleInput = $null
  $particleOutput = $null
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'solve_pre_pulse_interface_transport_field.m') -Destination $task
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_pre_pulse_interface_transport_model.m') -Destination $geometryBuilder
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'prepare_pre_pulse_interface_transport_field_model.m') -Destination $fieldBuilder
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  Copy-Item -LiteralPath $contractSource -Destination $contract
  Copy-Item -LiteralPath $ResolvedConnection -Destination $frozenResolvedConnection
  $resolvedConnectionSha256 = (
    Get-FileHash -LiteralPath $ResolvedConnection -Algorithm SHA256
  ).Hash
  if ((Get-FileHash -LiteralPath $frozenResolvedConnection -Algorithm SHA256).Hash -ne
      $resolvedConnectionSha256) {
    throw 'Resolved connection changed while frozen into the PrePulse run.'
  }

  $dependencyContract = Join-Path $snapshotRoot `
    'projects\rf_quadrupole_ion_optics\config\rf_to_oatof_pre_pulse_dependencies.json'
  $dependencyContractIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $dependencyContractSource -Destination $dependencyContract `
    -Role 'PrePulse dependency contract'
  $dependencyDocument = Get-Content -LiteralPath $dependencyContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
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
  $dependencyPaths = @{}
  $dependencySnapshotPaths = @{}
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
      compatibility_path = $identity.compatibility_path
      sha256 = $identity.sha256
    }
    $dependencyPaths[$identity.id] = $identity.frozen_path
    $dependencySnapshotPaths[$identity.id] = $identity.snapshot_path
  }
  $localSnapshotIdentities = [ordered]@{}
  foreach ($sourceRepoPath in @(
    'projects/rf_quadrupole_ion_optics/analysis/build_oatof_handoff.py'
  )) {
    $identity = Copy-PrePulseLocalSnapshotInput -RepoRoot $repoRoot -SnapshotRoot $snapshotRoot `
      -SourceRepoPath $sourceRepoPath
    $localSnapshotIdentities[[IO.Path]::GetFileNameWithoutExtension($sourceRepoPath)] = [ordered]@{
      source_repo_path = $identity.source_repo_path
      frozen_path = $identity.frozen_path
      sha256 = $identity.sha256
    }
  }
  $manifestToolRoot = $snapshotRoot
  if (-not $dependencySnapshotPaths['rf_dependency_contract_snapshot'].Equals(
      $dependencyContract, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'PrePulse dependency contract self identity is inconsistent.'
  }
  $sharedJoint = $dependencySnapshotPaths['rf_shared_joint_geometry']
  $rfResolved = $dependencySnapshotPaths['rf_resolved_design']
  $oaBaseline = $dependencyPaths['oatof_baseline']
  $oaBaselineSnapshot = $dependencySnapshotPaths['oatof_baseline']
  $oaBuilder = $dependencyPaths['oatof_accelerator_geometry_builder']
  $frozenManifestVerifier = $dependencySnapshotPaths['common_verify_run_manifest']
  $frozenComsolRunner = $dependencySnapshotPaths['common_comsol_runner']
  $frozenResourceBudgetSupport =
    $dependencySnapshotPaths['common_resource_budget_support']
  if (-not (Test-Path -LiteralPath $frozenResourceBudgetSupport -PathType Leaf)) {
    throw 'PrePulse frozen resource-budget support is missing.'
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
  if ($Particles) {
    $candidate = $contractDocument.particle_runtime
    $binding = $candidate.source_artifact_binding
    $descriptorDependencyId = [string]$binding.project_descriptor_dependency_id
    if (-not $dependencySnapshotPaths.ContainsKey($descriptorDependencyId)) {
      throw 'PrePulse source artifact binding has no frozen project descriptor.'
    }
    $sourceIdentity = Resolve-RfDeclaredLegacyRunDirectory `
      -WorkspaceRoot $workspaceRoot `
      -ProjectDescriptor $dependencySnapshotPaths[$descriptorDependencyId] `
      -MappingId ([string]$binding.legacy_mapping_id) `
      -RecordedProjectId ([string]$binding.recorded_project_id) `
      -RunId ([string]$candidate.source_run_id)
    $sourceRun = $sourceIdentity.run_dir
    $sourceManifestOriginal = $sourceIdentity.manifest_path
    $sourceEventsOriginal = Join-Path $sourceRun ([string]$candidate.source_event_path)
    $sourceMetadataOriginal = Join-Path $sourceRun ([string]$candidate.source_metadata_path)
    Invoke-PrePulseSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
      $frozenManifestVerifier,$sourceManifestOriginal,'--require-status','success'
    ) -FailureMessage 'The frozen PrePulse particle source manifest is invalid.'
    $sourceManifest = Join-Path $inputDir 'source_run_manifest.json'
    $sourceEvents = Join-Path $inputDir ([System.IO.Path]::GetFileName([string]$candidate.source_event_path))
    $sourceMetadata = Join-Path $inputDir 'particle_source_metadata.json'
    $handoffBuilder = $oatofHandoff
    $handoffProjectRoot = Join-Path $inputDir 'handoff_project_snapshot'
    $handoffConfigDir = Join-Path $handoffProjectRoot 'config'
    $handoffTargetConfigDir = Join-Path $inputDir 'single_reflection_oa_tof_mass_analyzer\config'
    New-Item -ItemType Directory -Path $handoffConfigDir,$handoffTargetConfigDir -Force | Out-Null
    $handoffContract = Join-Path $handoffConfigDir 'rf_to_oatof_handoff.json'
    $energyMatchContract = Join-Path $handoffConfigDir 'rf_to_oatof_energy_match_candidate.json'
    $sourceInterfaceContract = Join-Path $handoffConfigDir 'interface_contract.json'
    $energyMatchContractSource = Join-Path $projectRoot 'config\rf_to_oatof_energy_match_candidate.json'
    $sourceInterfaceContractSource = Join-Path $projectRoot 'config\interface_contract.json'
    $sourceBaseline = Join-Path $handoffConfigDir 'baseline.json'
    $targetBaseline = Join-Path $handoffTargetConfigDir 'baseline.json'
    Copy-Item -LiteralPath $sourceManifestOriginal -Destination $sourceManifest
    Copy-Item -LiteralPath $sourceEventsOriginal -Destination $sourceEvents
    Copy-Item -LiteralPath $sourceMetadataOriginal -Destination $sourceMetadata
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_handoff.json') -Destination $handoffContract
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\baseline.json') -Destination $sourceBaseline
    Copy-Item -LiteralPath $oaBaselineSnapshot -Destination $targetBaseline
    Copy-Item -LiteralPath $energyMatchContractSource -Destination $energyMatchContract
    Copy-Item -LiteralPath $sourceInterfaceContractSource -Destination $sourceInterfaceContract
    $particleInput = Join-Path $inputDir 'canonical_rf_exit_at_pre_pulse_connector.csv'
    $particleIon = Join-Path $inputDir 'rf_exit_at_pre_pulse_connector.ion'
    $particleRowMap = Join-Path $inputDir 'particle_row_map.csv'
    $particleMetadata = Join-Path $inputDir 'pre_pulse_handoff_metadata.json'
    Invoke-PrePulseSnapshotPython -Python $python -SnapshotRoot $snapshotRoot -Arguments @(
      '-m','projects.rf_quadrupole_ion_optics.analysis.build_oatof_handoff',
      '--convert','--contract',$handoffContract,
      '--resolved-connection',$frozenResolvedConnection,
      '--source-csv',$sourceEvents,'--source-manifest',$sourceManifest,
      '--source-manifest-project-id',$sourceIdentity.recorded_project_id,
      '--canonical-output',$particleInput,'--ion-output',$particleIon,
      '--row-map-output',$particleRowMap,'--metadata-output',$particleMetadata,
      '--solver-clock','instrument_time'
    ) -AdditionalEnvironment @{RF_HANDOFF_PROJECT_ROOT=$handoffProjectRoot} `
      -FailureMessage 'PrePulse canonical particle-source conversion failed.'
    $sourceParticleIdentity = [ordered]@{
      run_id = [string]$candidate.source_run_id
      legacy_mapping_id = $sourceIdentity.mapping_id
      recorded_project_id = $sourceIdentity.recorded_project_id
      artifact_root = $sourceIdentity.artifact_root
      manifest_sha256 = (Get-FileHash -LiteralPath $sourceManifestOriginal -Algorithm SHA256).Hash
      event_sha256 = (Get-FileHash -LiteralPath $sourceEventsOriginal -Algorithm SHA256).Hash
      metadata_sha256 = (Get-FileHash -LiteralPath $sourceMetadataOriginal -Algorithm SHA256).Hash
    }
    $particleOutput = Join-Path $resultDir 'pre_pulse_interface_transport_particles.csv'
  }
  $metrics = Join-Path $resultDir 'pre_pulse_no_pulse_field_metrics.json'
  $samples = Join-Path $resultDir 'pre_pulse_no_pulse_field_samples.csv'
  $report = Join-Path $logDir 'comsol_pre_pulse_no_pulse_field.txt'
  $runConfiguration = [ordered]@{
    schema_version = 2
    run_id = $RunId
    project = 'rf_quadrupole_ion_optics'
    mode = $mode
    project_root = $repoRoot
    inputs = [ordered]@{
      task = $task
      geometry_builder = $geometryBuilder
      field_builder = $fieldBuilder
      runner = $runner
      run_artifact_support = $support
      pre_pulse_contract = $contract
      oatof_handoff_library = $oatofHandoff
      dependency_contract = $dependencyContract
      shared_physical_port_joint_geometry = $sharedJoint
      rf_resolved_geometry = $rfResolved
      resolved_connection = $frozenResolvedConnection
      oatof_baseline = $oaBaseline
      oatof_accelerator_builder = $oaBuilder
      particle_source = $particleInput
      resolved_integration_engineering_budget = $budgetBinding.frozen_budget
      resolved_stage_resource_budget = $budgetBinding.stage_budget
    }
    dependency_identities = $dependencyIdentities
    local_snapshot_identities = $localSnapshotIdentities
    source_particle_identity = if ($Particles) { $sourceParticleIdentity } else { $null }
    parameters = [ordered]@{
      connector_gap_mm = $gapMm
      connection_profile_id = $ConnectionProfileId
      resolved_connection_sha256 = $resolvedConnectionSha256
      dependency_consumer_id = $dependencyConsumer
      field_bases = @('oatof_static','rf_unit_100_V')
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
    if (-not [string]::IsNullOrWhiteSpace([string]$identity.compatibility_path)) {
      $runConfiguration.inputs[([string]$identity.frozen_input_name + '_compatibility')] = `
        [string]$identity.compatibility_path
    }
  }
  if ($Particles) {
    $runConfiguration.inputs.source_run_manifest = $sourceManifest
    $runConfiguration.inputs.source_events = $sourceEvents
    $runConfiguration.inputs.source_metadata = $sourceMetadata
    $runConfiguration.inputs.handoff_builder = $handoffBuilder
    $runConfiguration.inputs.handoff_contract = $handoffContract
    $runConfiguration.inputs.handoff_source_baseline = $sourceBaseline
    $runConfiguration.inputs.handoff_target_baseline = $targetBaseline
    $runConfiguration.inputs.energy_match_contract = $energyMatchContract
    $runConfiguration.inputs.source_interface_contract = $sourceInterfaceContract
    $runConfiguration.inputs.particle_ion = $particleIon
    $runConfiguration.inputs.particle_row_map = $particleRowMap
    $runConfiguration.inputs.particle_handoff_metadata = $particleMetadata
  }
  Write-RfJson -Path $package.run_config -Depth 8 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = $summaryRole
    status = 'interrupted'
    reason = 'Run package initialized; final status not yet recorded.'
  })
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status interrupted -Software $software

  $environmentNames = @(
    'RF_OATOF_PrePulse_FIELD_METRICS','RF_OATOF_PrePulse_FIELD_SAMPLES','RF_OATOF_PrePulse_CONTRACT',
    'RF_OATOF_PrePulse_SHARED_JOINT_CONTRACT','RF_OATOF_PrePulse_RF_RESOLVED','RF_OATOF_PrePulse_OA_BASELINE',
    'RF_OATOF_RESOLVED_CONNECTION','RF_OATOF_RESOLVED_CONNECTION_SHA256',
    'RF_OATOF_PrePulse_OA_COMSOL_DIR',
    'RF_OATOF_PrePulse_PARTICLE_INPUT','RF_OATOF_PrePulse_PARTICLE_OUTPUT'
  )
  $oldEnvironment = Save-RfEnvironment -Names $environmentNames
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
    Restore-RfEnvironment -Names $environmentNames -Snapshot $oldEnvironment
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
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = $summaryRole
    status = 'success'
    metrics = 'results/pre_pulse_no_pulse_field_metrics.json'
    samples = 'results/pre_pulse_no_pulse_field_samples.csv'
    gap_mm = $gapMm
    field_bases_solved = 2
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
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  Write-Output "STATUS=PASS RUN_ID=$RunId GAP_MM=$gapMm FIELD_BASES=2 PARTICLES=$Particles OA_PULSE=false"
} catch {
  Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole $summaryRole `
    -Reason $_.Exception.Message -Software $software `
    -Status $(if ($resourceBudgetExceeded) { 'interrupted' } else { 'failed' }) `
    -FailureClass $(if ($resourceBudgetExceeded) {
      'resource_budget_exceeded'
    } else { '' }) `
    -ResourceUsagePath $(if ($resourceBudgetExceeded) { $resourceUsage } else { '' })
  throw
}
