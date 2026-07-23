param(
  [string]$RunId = '',
  [switch]$Particles,
  [string]$ConnectorCaseId = 'nominal_gap_1mm'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$supportSource = (Resolve-Path (Join-Path $PSScriptRoot '..\support\rf_run_artifact_support.ps1')).Path
. $supportSource
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$contractSource = Join-Path $projectRoot 'config\rf_to_oatof_s2_passive_connector.json'
$connectorCasesSource = Join-Path $projectRoot 'config\rf_to_oatof_connector_cases.json'
$connectorResolverSource = Join-Path $projectRoot 'analysis\resolve_s2_connector_case.py'
$connectorValidatorSource = Join-Path $projectRoot 'analysis\validate_s2_passive_connector.py'
$oatofHandoffSource = Join-Path $projectRoot 'analysis\build_oatof_handoff.py'
$dependencyContractSource = Join-Path $projectRoot 'config\rf_to_oatof_s2_dependencies.json'
$spatialResolverSource = Join-Path $projectRoot 'analysis\resolve_spatial_registration.py'
$baseContractDocument = Get-Content -LiteralPath $contractSource -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$baseContractDocument.permissions.field_solve_allowed) {
  throw 'The S2 contract does not authorize a field solve.'
}
if ($Particles -and -not [bool]$baseContractDocument.permissions.particle_runtime_allowed) {
  throw 'The S2 contract does not authorize particle runtime.'
}
$connectorCasesDocument = Get-Content -LiteralPath $connectorCasesSource -Raw -Encoding UTF8 | ConvertFrom-Json
$selectedCases = @($connectorCasesDocument.cases | Where-Object { $_.case_id -eq $ConnectorCaseId })
if ($selectedCases.Count -ne 1) { throw "Connector case must resolve uniquely: $ConnectorCaseId" }
$gapMm = [double]$selectedCases[0].connector_gap_mm
if (-not [double]::IsFinite($gapMm) -or $gapMm -lt 0) {
  throw 'The S2 connector gap must be finite and non-negative.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $gapLabel = ('{0:g}' -f $gapMm).Replace('.','p')
  $suffix = if ($Particles) { "__sim__comsol__rf-oatof-s2-connector-gap$gapLabel__n100" } `
    else { "__analysis__comsol__rf-oatof-s2-no-pulse-field__gap$gapLabel" }
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + $suffix
}
$mode = if ($Particles) { 'rf_to_oatof_s2_passive_connector_n100' } `
  else { 'rf_to_oatof_s2_passive_connector_no_pulse_field' }
$summaryRole = if ($Particles) { 'rf_to_oatof_s2_passive_connector_n100_summary' } `
  else { 'rf_to_oatof_s2_no_pulse_field_summary' }
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package = New-RfRunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'rf_quadrupole_collision_cooling' -Mode $mode -Software $software
$python = $package.python
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir

try {
  $task = Join-Path $inputDir 'solve_s2_passive_connector_field.m'
  $geometryBuilder = Join-Path $inputDir 'build_s2_passive_connector_model.m'
  $fieldBuilder = Join-Path $inputDir 'prepare_s2_joint_field_model.m'
  $runner = Join-Path $inputDir 'run_s2_passive_connector_field.ps1.txt'
  $support = Join-Path $inputDir 'rf_run_artifact_support.ps1.txt'
  $contract = Join-Path $inputDir 'rf_to_oatof_s2_passive_connector.json'
  $baseContract = Join-Path $inputDir 'rf_to_oatof_s2_passive_connector_base.json'
  $connectorCases = Join-Path $inputDir 'rf_to_oatof_connector_cases.json'
  $connectorResolver = Join-Path $inputDir 'resolve_s2_connector_case.py'
  $connectorValidator = Join-Path $inputDir 'validate_s2_passive_connector.py'
  $oatofHandoff = Join-Path $inputDir 'build_oatof_handoff.py'
  $dependencyContract = Join-Path $inputDir 'rf_to_oatof_s2_dependencies.json'
  $sharedJoint = Join-Path $inputDir 'rf_to_oatof_shared_physical_port_joint_geometry.json'
  $rfResolved = Join-Path $inputDir 'rf_resolved_design.json'
  $spatialRegistration = Join-Path $inputDir 'resolved_rf_to_oatof_s2_spatial_registration.json'
  $spatialResolver = Join-Path $inputDir 'resolve_spatial_registration.py'
  $particleInput = $null
  $particleOutput = $null
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'solve_s2_passive_connector_field.m') -Destination $task
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_s2_passive_connector_model.m') -Destination $geometryBuilder
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'prepare_s2_joint_field_model.m') -Destination $fieldBuilder
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  Copy-Item -LiteralPath $contractSource -Destination $baseContract
  Copy-Item -LiteralPath $connectorCasesSource -Destination $connectorCases
  Copy-Item -LiteralPath $connectorResolverSource -Destination $connectorResolver
  Copy-Item -LiteralPath $connectorValidatorSource -Destination $connectorValidator
  Copy-Item -LiteralPath $oatofHandoffSource -Destination $oatofHandoff
  Copy-Item -LiteralPath $spatialResolverSource -Destination $spatialResolver
  Push-Location $repoRoot
  try {
    & $python -m projects.rf_quadrupole_collision_cooling.analysis.resolve_s2_connector_case `
      --base $baseContract --cases $connectorCases `
      --case-id $ConnectorCaseId --output $contract
  } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'S2 connector-case resolution failed.' }
  $contractDocument = Get-Content -LiteralPath $contract -Raw -Encoding UTF8 | ConvertFrom-Json
  Copy-Item -LiteralPath $dependencyContractSource -Destination $dependencyContract
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_shared_physical_port_joint_geometry.json') -Destination $sharedJoint
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\resolved_design_official.json') -Destination $rfResolved

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
  Push-Location $repoRoot
  try {
    & $python -m projects.rf_quadrupole_collision_cooling.analysis.resolve_spatial_registration `
      --stage s2 --stage-contract $contract --shared-joint $sharedJoint `
      --rf-resolved $rfResolved --oatof-baseline $oaBaseline `
      --source-root $inputDir --output $spatialRegistration --write
  } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { throw 'S2 spatial-registration resolution failed.' }
  $spatialDocument = Get-Content -LiteralPath $spatialRegistration -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $validatorEnvironment = Save-RfEnvironment -Names @('PYTHONPATH')
  try {
    $env:PYTHONPATH = $repoRoot
    & $python $connectorValidator --contract $contract --reference-root $projectRoot `
      --resolved-registration $spatialRegistration
    if ($LASTEXITCODE -ne 0) { throw 'Resolved S2 connector-case contract is invalid.' }
  } finally {
    Restore-RfEnvironment -Names @('PYTHONPATH') -Snapshot $validatorEnvironment
  }
  if ($Particles) {
    $candidate = $contractDocument.functional_candidate
    $sourceRun = Join-Path (Join-Path $artifactRoot 'runs') ([string]$candidate.source_run_id)
    $sourceManifestOriginal = Join-Path $sourceRun 'run_manifest.json'
    $sourceEventsOriginal = Join-Path $sourceRun ([string]$candidate.source_event_path)
    $sourceMetadataOriginal = Join-Path $sourceRun ([string]$candidate.source_metadata_path)
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
      $sourceManifestOriginal --require-status success
    if ($LASTEXITCODE -ne 0) { throw 'The frozen S2 particle source manifest is invalid.' }
    $sourceManifest = Join-Path $inputDir 'source_run_manifest.json'
    $sourceEvents = Join-Path $inputDir ([System.IO.Path]::GetFileName([string]$candidate.source_event_path))
    $sourceMetadata = Join-Path $inputDir 'particle_source_metadata.json'
    $handoffBuilder = Join-Path $inputDir 'build_oatof_handoff.py'
    $handoffProjectRoot = Join-Path $inputDir 'handoff_project_snapshot'
    $handoffConfigDir = Join-Path $handoffProjectRoot 'config'
    $handoffTargetConfigDir = Join-Path $inputDir 'oa_tof\config'
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
    Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\build_oatof_handoff.py') -Destination $handoffBuilder
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_handoff.json') -Destination $handoffContract
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config\baseline.json') -Destination $sourceBaseline
    Copy-Item -LiteralPath $oaBaseline -Destination $targetBaseline
    Copy-Item -LiteralPath $energyMatchContractSource -Destination $energyMatchContract
    Copy-Item -LiteralPath $sourceInterfaceContractSource -Destination $sourceInterfaceContract
    $particleInput = Join-Path $inputDir 'canonical_rf_exit_at_s2_connector.csv'
    $particleIon = Join-Path $inputDir 'rf_exit_at_s2_connector.ion'
    $particleRowMap = Join-Path $inputDir 'particle_row_map.csv'
    $particleMetadata = Join-Path $inputDir 's2_handoff_metadata.json'
    $sourceCenter = @($contractDocument.nominal_registration.source_exit_center_instrument_mm)
    $handoffEnvironment = Save-RfEnvironment -Names @(
      'RF_HANDOFF_PROJECT_ROOT','PYTHONPATH'
    )
    try {
      $env:RF_HANDOFF_PROJECT_ROOT = $handoffProjectRoot
      $env:PYTHONPATH = $repoRoot
      & $python $handoffBuilder --convert --contract $handoffContract `
        --resolved-registration $spatialRegistration `
        --source-csv $sourceEvents --source-manifest $sourceManifest `
        --canonical-output $particleInput --ion-output $particleIon `
        --row-map-output $particleRowMap --metadata-output $particleMetadata `
        --solver-clock instrument_time --target-origin-mm $sourceCenter[0] $sourceCenter[1] $sourceCenter[2]
      if ($LASTEXITCODE -ne 0) { throw 'S2 canonical particle-source conversion failed.' }
    } finally {
      Restore-RfEnvironment -Names @(
        'RF_HANDOFF_PROJECT_ROOT','PYTHONPATH'
      ) -Snapshot $handoffEnvironment
    }
    $sourceIdentity = [ordered]@{
      run_id = [string]$candidate.source_run_id
      manifest_sha256 = (Get-FileHash -LiteralPath $sourceManifestOriginal -Algorithm SHA256).Hash
      event_sha256 = (Get-FileHash -LiteralPath $sourceEventsOriginal -Algorithm SHA256).Hash
      metadata_sha256 = (Get-FileHash -LiteralPath $sourceMetadataOriginal -Algorithm SHA256).Hash
    }
    $particleOutput = Join-Path $resultDir 's2_passive_connector_particles.csv'
  }
  $metrics = Join-Path $resultDir 's2_no_pulse_field_metrics.json'
  $samples = Join-Path $resultDir 's2_no_pulse_field_samples.csv'
  $report = Join-Path $logDir 'comsol_s2_no_pulse_field.txt'
  $runConfiguration = [ordered]@{
    schema_version = 1
    run_id = $RunId
    project = 'rf_quadrupole_collision_cooling'
    mode = $mode
    project_root = $repoRoot
    inputs = [ordered]@{
      task = $task
      geometry_builder = $geometryBuilder
      field_builder = $fieldBuilder
      runner = $runner
      run_artifact_support = $support
      s2_contract = $contract
      s2_base_contract = $baseContract
      connector_cases = $connectorCases
      connector_case_resolver = $connectorResolver
      connector_case_validator = $connectorValidator
      oatof_handoff_library = $oatofHandoff
      dependency_contract = $dependencyContract
      shared_physical_port_joint_geometry = $sharedJoint
      rf_resolved_geometry = $rfResolved
      spatial_registration = $spatialRegistration
      spatial_registration_resolver = $spatialResolver
      oatof_baseline = $oaBaseline
      oatof_accelerator_builder = $oaBuilder
      particle_source = $particleInput
    }
    dependency_identities = $dependencyIdentities
    source_particle_identity = if ($Particles) { $sourceIdentity } else { $null }
    parameters = [ordered]@{
      connector_gap_mm = $gapMm
      connector_case_id = $ConnectorCaseId
      field_bases = @('oatof_static','rf_unit_100_V')
      oa_extraction_pulse = $false
      particle_tracking = [bool]$Particles
      model_saved = $false
      mesh_convergence_claimed = $false
    }
    formal_gate_passed = $false
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
  Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status interrupted -Software $software

  $environmentNames = @(
    'RF_OATOF_S2_FIELD_METRICS','RF_OATOF_S2_FIELD_SAMPLES','RF_OATOF_S2_CONTRACT',
    'RF_OATOF_S2_SHARED_JOINT_CONTRACT','RF_OATOF_S2_RF_RESOLVED','RF_OATOF_S2_OA_BASELINE',
    'RF_OATOF_SPATIAL_REGISTRATION','RF_OATOF_SPATIAL_REGISTRATION_SHA256',
    'RF_OATOF_S2_OA_COMSOL_DIR',
    'RF_OATOF_S2_PARTICLE_INPUT','RF_OATOF_S2_PARTICLE_OUTPUT'
  )
  $oldEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:RF_OATOF_S2_FIELD_METRICS = $metrics
    $env:RF_OATOF_S2_FIELD_SAMPLES = $samples
    $env:RF_OATOF_S2_CONTRACT = $contract
    $env:RF_OATOF_S2_SHARED_JOINT_CONTRACT = $sharedJoint
    $env:RF_OATOF_S2_RF_RESOLVED = $rfResolved
    $env:RF_OATOF_SPATIAL_REGISTRATION = $spatialRegistration
    $env:RF_OATOF_SPATIAL_REGISTRATION_SHA256 = (
      Get-FileHash -LiteralPath $spatialRegistration -Algorithm SHA256
    ).Hash
    $env:RF_OATOF_S2_OA_BASELINE = $oaBaseline
    $env:RF_OATOF_S2_OA_COMSOL_DIR = $inputDir
    if ($Particles) {
      $env:RF_OATOF_S2_PARTICLE_INPUT = $particleInput
      $env:RF_OATOF_S2_PARTICLE_OUTPUT = $particleOutput
    }
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL S2 no-pulse field task failed.' }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $oldEnvironment
  }

  $fieldMetrics = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  $expectedSpatialSha256 = (Get-FileHash -LiteralPath $spatialRegistration -Algorithm SHA256).Hash
  if ($fieldMetrics.status -ne 'SOLVED' -or -not [bool]$fieldMetrics.all_probe_values_finite -or
      [string]$fieldMetrics.frame_id -ne [string]$spatialDocument.instrument_frame_id -or
      [string]$fieldMetrics.position_unit -ne 'mm' -or
      [string]$fieldMetrics.spatial_registration_sha256 -ne $expectedSpatialSha256 -or
      [double]$fieldMetrics.rf_off_axis_field_norm_V_per_m -le 0 -or
      [bool]$fieldMetrics.particle_runtime_executed -ne [bool]$Particles -or
      [bool]$fieldMetrics.oa_extraction_pulse_included -or
      [bool]$fieldMetrics.mesh_convergence_claimed -or [bool]$fieldMetrics.s2_stage_passed) {
    throw 'S2 field metrics violate the no-pulse functional contract.'
  }
  if ($Particles -and
      ([int]$fieldMetrics.particle_input_count -ne [int]$contractDocument.functional_candidate.source_particles -or
       [int]$fieldMetrics.oatof_entry_crossings -lt [int]$contractDocument.functional_candidate.minimum_oatof_entry_crossings)) {
    throw 'S2 particle metrics violate the nominal functional contract.'
  }
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = $summaryRole
    status = 'success'
    metrics = 'results/s2_no_pulse_field_metrics.json'
    samples = 'results/s2_no_pulse_field_samples.csv'
    gap_mm = $gapMm
    field_bases_solved = 2
    finite_probe_rows = [int]$fieldMetrics.probe_count
    particle_runtime = [bool]$Particles
    particle_input_count = [int]$fieldMetrics.particle_input_count
    oatof_entry_crossings = [int]$fieldMetrics.oatof_entry_crossings
    connector_losses = [int]$fieldMetrics.connector_losses
    oa_extraction_pulse = $false
    mesh_convergence_claimed = $false
    s2_stage_passed = $false
    formal_gate_passed = $false
  })
  $outputs = @($metrics,$samples,$report,$package.summary)
  if ($Particles) { $outputs += $particleOutput }
  Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  Write-Output "STATUS=PASS RUN_ID=$RunId GAP_MM=$gapMm FIELD_BASES=2 PARTICLES=$Particles OA_PULSE=false"
} catch {
  Complete-RfFailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole $summaryRole `
    -Reason $_.Exception.Message -Software $software
  throw
}
