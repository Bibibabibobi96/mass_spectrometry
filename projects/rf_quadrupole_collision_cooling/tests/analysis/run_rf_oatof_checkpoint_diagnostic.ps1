[CmdletBinding(DefaultParameterSetName = 'SourceRun')]
param(
  [Parameter(Mandatory, ParameterSetName = 'SourceRun')]
  [string]$SourceRunId,
  [Parameter(Mandatory, ParameterSetName = 'SourceManifest')]
  [string]$SourceManifest,
  [Parameter(Mandatory)]
  [string]$DownstreamRunId,
  [string]$RunId = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Copy-CheckpointInput {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination
  )
  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Checkpoint source input is missing: $Source"
  }
  Copy-Item -LiteralPath $Source -Destination $Destination
  $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
  $destinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
  if ($sourceHash -ne $destinationHash) {
    throw "Checkpoint source changed while frozen: $Source"
  }
  return $sourceHash
}

function Get-ManifestRecordPaths {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][object]$Records,
    [Parameter(Mandatory)][ValidateSet('Inputs', 'Outputs')][string]$Kind
  )
  if ($Kind -eq 'Inputs') {
    return @($Records.PSObject.Properties | ForEach-Object {
      [IO.Path]::GetFullPath([string]$_.Value.path)
    })
  }
  return @($Records | ForEach-Object {
    [IO.Path]::GetFullPath([string]$_.path)
  })
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$runsRoot = Join-Path $artifactRoot 'runs'
$supportSource = (
  Resolve-Path (Join-Path $projectRoot 'tests\support\rf_run_artifact_support.ps1')
).Path
. $supportSource

if ($PSCmdlet.ParameterSetName -eq 'SourceRun') {
  $sourceManifestPath = Join-Path (Join-Path $runsRoot $SourceRunId) 'run_manifest.json'
} else {
  $sourceManifestPath = (Resolve-Path -LiteralPath $SourceManifest).Path
}
$sourceManifestPath = [IO.Path]::GetFullPath($sourceManifestPath)
$sourceRun = Split-Path -Parent $sourceManifestPath
$expectedRunsPrefix = [IO.Path]::GetFullPath($runsRoot) + [IO.Path]::DirectorySeparatorChar
if (-not $sourceRun.StartsWith($expectedRunsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'The source manifest must belong to the RF project artifact runs directory.'
}

if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') +
    '__analysis__python__rf-oatof-checkpoint-diagnostic__n100'
}
$software = @('Python 3.11')
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'rf_quadrupole_collision_cooling' `
  -Mode 'rf_to_oatof_checkpoint_diagnostic_n100' -Software $software

try {
  & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    $sourceManifestPath --require-status success
  if ($LASTEXITCODE -ne 0) {
    throw 'The source S3 run manifest is invalid.'
  }
  $sourceManifestDocument = Get-Content -LiteralPath $sourceManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceManifestDocument.project -ne 'rf_quadrupole_collision_cooling' -or
      $sourceManifestDocument.mode -ne 'rf_to_oatof_s3_shared_clock_pulse_capture_n100') {
    throw 'Checkpoint diagnostics require a successful RF S3 pulse-capture N=100 manifest.'
  }
  if ([string]$sourceManifestDocument.run_id -ne (Split-Path -Leaf $sourceRun)) {
    throw 'The source S3 run directory and manifest run_id differ.'
  }

  $sourceRunConfigurationPath = [IO.Path]::GetFullPath(
    [string]$sourceManifestDocument.run_config.path)
  $sourceRunConfiguration = Get-Content -LiteralPath $sourceRunConfigurationPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceRunConfiguration.run_id -ne $sourceManifestDocument.run_id -or
      $sourceRunConfiguration.mode -ne 'rf_to_oatof_s3_shared_clock_pulse_capture_n100' -or
      [bool]$sourceRunConfiguration.parameters.s3_stage_passed -or
      [bool]$sourceRunConfiguration.formal_gate_passed) {
    throw 'The source S3 run configuration identity or qualification boundary is invalid.'
  }

  $downstreamRun = [IO.Path]::GetFullPath((Join-Path $runsRoot $DownstreamRunId))
  if (-not $downstreamRun.StartsWith(
      $expectedRunsPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The downstream run must belong to the RF project artifact runs directory.'
  }
  $downstreamManifestPath = Join-Path $downstreamRun 'run_manifest.json'
  & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    $downstreamManifestPath --require-status success
  if ($LASTEXITCODE -ne 0) {
    throw 'The downstream end-to-end run manifest is invalid.'
  }
  $downstreamManifestDocument = Get-Content -LiteralPath $downstreamManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $downstreamRunConfigurationPath = [IO.Path]::GetFullPath(
    [string]$downstreamManifestDocument.run_config.path)
  $downstreamRunConfiguration = Get-Content -LiteralPath $downstreamRunConfigurationPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($downstreamManifestDocument.project -ne 'rf_quadrupole_collision_cooling' -or
      $downstreamManifestDocument.mode -ne 'rf_to_oatof_s3_cumulative_end_to_end' -or
      [string]$downstreamManifestDocument.run_id -ne $DownstreamRunId -or
      [string]$downstreamRunConfiguration.run_id -ne $DownstreamRunId -or
      [string]$downstreamRunConfiguration.parameters.source_run_id -ne
        [string]$sourceManifestDocument.run_id -or
      [bool]$downstreamRunConfiguration.parameters.s3_stage_passed -or
      [bool]$downstreamRunConfiguration.formal_gate_passed) {
    throw 'The downstream run is not explicitly linked to the selected S3 source.'
  }

  $sourceExitOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.particle_source)
  $pulseScheduleOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.pulse_schedule)
  $s2ContractOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.s2_contract)
  $spatialRegistrationOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.spatial_registration)
  $jointContractOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.shared_physical_port_joint_geometry)
  $oatofBaselineOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.oatof_baseline)
  $rfResolvedGeometryOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.rf_resolved_geometry)
  $captureOriginal = Join-Path $sourceRun 'results\s3_pulse_left_limit_state.csv'
  $terminalOriginal = Join-Path $sourceRun 'results\s3_particle_terminal_census.csv'
  $s2EntryOriginal = [IO.Path]::GetFullPath(
    [string]$sourceRunConfiguration.inputs.timing_state)
  $localExitOriginal = Join-Path $sourceRun 'results\s3_local_accelerator_exit.csv'
  $downstreamRowMapOriginal = Join-Path $downstreamRun 'inputs\row_map.csv'
  $downstreamStateOriginal = Join-Path $downstreamRun 'results\simion_downstream_particles.csv'
  $manifestInputPaths = Get-ManifestRecordPaths `
    -Records $sourceManifestDocument.inputs -Kind Inputs
  $manifestOutputPaths = Get-ManifestRecordPaths `
    -Records $sourceManifestDocument.outputs -Kind Outputs
  foreach ($path in @(
      $sourceExitOriginal, $s2EntryOriginal, $pulseScheduleOriginal, $s2ContractOriginal,
      $spatialRegistrationOriginal, $jointContractOriginal, $oatofBaselineOriginal,
      $rfResolvedGeometryOriginal
    )) {
    if ($manifestInputPaths -notcontains [IO.Path]::GetFullPath($path)) {
      throw "Required checkpoint input is not covered by the source manifest: $path"
    }
  }
  foreach ($path in @($captureOriginal, $terminalOriginal, $localExitOriginal)) {
    if ($manifestOutputPaths -notcontains [IO.Path]::GetFullPath($path)) {
      throw "Required checkpoint state is not covered by the source manifest: $path"
    }
  }
  $downstreamManifestOutputPaths = Get-ManifestRecordPaths `
    -Records $downstreamManifestDocument.outputs -Kind Outputs
  foreach ($path in @($downstreamRowMapOriginal, $downstreamStateOriginal)) {
    if ($downstreamManifestOutputPaths -notcontains [IO.Path]::GetFullPath($path)) {
      throw "Required downstream state is not covered by its manifest: $path"
    }
  }

  $analysis = Join-Path $package.input_dir 'analyze_rf_oatof_checkpoints.py'
  $snapshotAnalysis = Join-Path $package.input_dir 'plot_shared_pulse_geometry_snapshot.py'
  $contract = Join-Path $package.input_dir 'rf_to_oatof_checkpoint_diagnostic.json'
  $runner = Join-Path $package.input_dir 'run_rf_oatof_checkpoint_diagnostic.ps1.txt'
  $support = Join-Path $package.input_dir 'rf_run_artifact_support.ps1.txt'
  $sourceManifestFrozen = Join-Path $package.input_dir 'source_s3_run_manifest.json'
  $sourceRunConfigurationFrozen = Join-Path $package.input_dir 'source_s3_run_config.json'
  $downstreamManifestFrozen = Join-Path $package.input_dir 'downstream_run_manifest.json'
  $downstreamRunConfigurationFrozen = Join-Path $package.input_dir 'downstream_run_config.json'
  $sourceExit = Join-Path $package.input_dir 'rf_exit_particle_state.csv'
  $capture = Join-Path $package.input_dir 's3_pulse_left_limit_state.csv'
  $terminal = Join-Path $package.input_dir 's3_particle_terminal_census.csv'
  $s2Entry = Join-Path $package.input_dir 's2_oatof_entry_state.csv'
  $localExit = Join-Path $package.input_dir 's3_local_accelerator_exit.csv'
  $downstreamRowMap = Join-Path $package.input_dir 'simion_row_map.csv'
  $downstreamState = Join-Path $package.input_dir 'simion_downstream_particles.csv'
  $pulseSchedule = Join-Path $package.input_dir 's3_centroid_pulse_schedule.json'
  $s2Contract = Join-Path $package.input_dir 'rf_to_oatof_s2_passive_connector.json'
  $spatialRegistration = Join-Path $package.input_dir 'resolved_rf_to_oatof_s2_spatial_registration.json'
  $jointContract = Join-Path $package.input_dir 'rf_to_oatof_shared_physical_port_joint_geometry.json'
  $oatofBaseline = Join-Path $package.input_dir 'oatof_baseline.json'
  $rfResolvedGeometry = Join-Path $package.input_dir 'resolved_design_official.json'

  $sourceIdentities = [ordered]@{
    source_manifest_sha256 = Copy-CheckpointInput `
      -Source $sourceManifestPath -Destination $sourceManifestFrozen
    source_run_config_sha256 = Copy-CheckpointInput `
      -Source $sourceRunConfigurationPath -Destination $sourceRunConfigurationFrozen
    downstream_manifest_sha256 = Copy-CheckpointInput `
      -Source $downstreamManifestPath -Destination $downstreamManifestFrozen
    downstream_run_config_sha256 = Copy-CheckpointInput `
      -Source $downstreamRunConfigurationPath -Destination $downstreamRunConfigurationFrozen
    source_exit_sha256 = Copy-CheckpointInput `
      -Source $sourceExitOriginal -Destination $sourceExit
    pulse_left_limit_sha256 = Copy-CheckpointInput `
      -Source $captureOriginal -Destination $capture
    terminal_census_sha256 = Copy-CheckpointInput `
      -Source $terminalOriginal -Destination $terminal
    s2_oatof_entry_state_sha256 = Copy-CheckpointInput `
      -Source $s2EntryOriginal -Destination $s2Entry
    local_accelerator_exit_sha256 = Copy-CheckpointInput `
      -Source $localExitOriginal -Destination $localExit
    simion_row_map_sha256 = Copy-CheckpointInput `
      -Source $downstreamRowMapOriginal -Destination $downstreamRowMap
    simion_downstream_state_sha256 = Copy-CheckpointInput `
      -Source $downstreamStateOriginal -Destination $downstreamState
    pulse_schedule_sha256 = Copy-CheckpointInput `
      -Source $pulseScheduleOriginal -Destination $pulseSchedule
    s2_contract_sha256 = Copy-CheckpointInput `
      -Source $s2ContractOriginal -Destination $s2Contract
    spatial_registration_sha256 = Copy-CheckpointInput `
      -Source $spatialRegistrationOriginal -Destination $spatialRegistration
    shared_physical_port_joint_geometry_sha256 = Copy-CheckpointInput `
      -Source $jointContractOriginal -Destination $jointContract
    oatof_baseline_sha256 = Copy-CheckpointInput `
      -Source $oatofBaselineOriginal -Destination $oatofBaseline
    rf_resolved_geometry_sha256 = Copy-CheckpointInput `
      -Source $rfResolvedGeometryOriginal -Destination $rfResolvedGeometry
  }
  Copy-CheckpointInput `
    -Source (Join-Path $projectRoot 'analysis\analyze_rf_oatof_checkpoints.py') `
    -Destination $analysis | Out-Null
  Copy-CheckpointInput `
    -Source (Join-Path $projectRoot 'analysis\plot_shared_pulse_geometry_snapshot.py') `
    -Destination $snapshotAnalysis | Out-Null
  Copy-CheckpointInput `
    -Source (Join-Path $projectRoot 'config\rf_to_oatof_checkpoint_diagnostic.json') `
    -Destination $contract | Out-Null
  Copy-CheckpointInput -Source $PSCommandPath -Destination $runner | Out-Null
  Copy-CheckpointInput -Source $supportSource -Destination $support | Out-Null
  & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    $sourceManifestPath --require-status success
  if ($LASTEXITCODE -ne 0) {
    throw 'The source S3 manifest changed while checkpoint inputs were frozen.'
  }

  $metrics = Join-Path $package.result_dir 'rf-oatof-checkpoints__metrics.json'
  $particles = Join-Path $package.result_dir 'rf-oatof-checkpoints__particles.csv'
  $figure = Join-Path $package.result_dir 'rf-oatof-checkpoints__state-comparison.png'
  $analysisLog = Join-Path $package.log_dir 'checkpoint_analysis.txt'
  $runConfiguration = [ordered]@{
    schema_version = 1
    run_id = $RunId
    project = 'rf_quadrupole_collision_cooling'
    mode = 'rf_to_oatof_checkpoint_diagnostic_n100'
    project_root = $repoRoot
    inputs = [ordered]@{
      analysis = $analysis
      snapshot_analysis = $snapshotAnalysis
      diagnostic_contract = $contract
      runner = $runner
      run_artifact_support = $support
      source_s3_run_manifest = $sourceManifestFrozen
      source_s3_run_config = $sourceRunConfigurationFrozen
      downstream_run_manifest = $downstreamManifestFrozen
      downstream_run_config = $downstreamRunConfigurationFrozen
      source_exit_state = $sourceExit
      pulse_left_limit_state = $capture
      terminal_census = $terminal
      s2_oatof_entry_state = $s2Entry
      local_accelerator_exit_state = $localExit
      simion_row_map = $downstreamRowMap
      simion_downstream_state = $downstreamState
      pulse_schedule = $pulseSchedule
      s2_contract = $s2Contract
      spatial_registration = $spatialRegistration
      shared_physical_port_joint_geometry = $jointContract
      oatof_baseline = $oatofBaseline
      rf_resolved_geometry = $rfResolvedGeometry
    }
    source_identity = [ordered]@{
      run_id = [string]$sourceManifestDocument.run_id
      downstream_run_id = [string]$downstreamManifestDocument.run_id
      original_manifest_path = $sourceManifestPath
      original_downstream_manifest_path = $downstreamManifestPath
      files = $sourceIdentities
    }
    parameters = [ordered]@{
      solver_rerun = $false
      particle_count = 100
      diagnostic_only = $true
      s3_stage_passed = $false
    }
    formal_gate_passed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 9 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_checkpoint_diagnostic_summary'
    status = 'interrupted'
    reason = 'Inputs frozen; checkpoint analysis has not reached a terminal status.'
  })
  Write-VerifiedRunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status interrupted -Software $software

  $analysisEnvironment = Save-RfEnvironment -Names @('PYTHONPATH')
  try {
    $env:PYTHONPATH = $repoRoot
    & $package.python $analysis `
      --exit-state $sourceExit `
      --capture-state $capture `
      --terminal-census $terminal `
      --s2-entry-state $s2Entry `
      --local-exit-state $localExit `
      --downstream-row-map $downstreamRowMap `
      --downstream-state $downstreamState `
      --pulse-schedule $pulseSchedule `
      --oatof-baseline $oatofBaseline `
      --s2-contract $s2Contract `
      --resolved-registration $spatialRegistration `
      --rf-resolved-geometry $rfResolvedGeometry `
      --joint-contract $jointContract `
      --contract $contract `
      --metrics $metrics `
      --particles $particles `
      --figure $figure 2>&1 | Tee-Object -FilePath $analysisLog
    if ($LASTEXITCODE -ne 0) {
      throw 'RF-to-oaTOF checkpoint analysis failed.'
    }
  } finally {
    Restore-RfEnvironment -Names @('PYTHONPATH') -Snapshot $analysisEnvironment
  }
  $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($result.role -ne 'rf_to_oatof_same_id_checkpoint_diagnostic' -or
      $result.status -ne 'PASS' -or
      [int]$result.population_counts.source_exit_all -ne 100 -or
      [int]$result.population_counts.capture_all_active -lt 1 -or
      [int]$result.exclusive_particle_outcomes.denominator -ne 100 -or
      -not [bool]$result.exclusive_particle_outcomes.classes_are_mutually_exclusive_and_exhaustive -or
      [int]$result.stage_membership.detector_hit -lt 1 -or
      [int]$result.scientific_scope.particles_removed_from_metrics -ne 0 -or
      [bool]$result.scientific_scope.stage_passed -or
      [bool]$result.scientific_scope.formal_gate_passed) {
    throw 'Checkpoint output violates the diagnostic-only N=100 contract.'
  }

  Write-RfJson -Path $package.summary -Depth 6 -Value ([ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_checkpoint_diagnostic_summary'
    status = 'success'
    source_run_id = [string]$sourceManifestDocument.run_id
    downstream_run_id = [string]$downstreamManifestDocument.run_id
    source_exit_particles = [int]$result.population_counts.source_exit_all
    scheduler_cohort_particles = [int]$result.population_counts.scheduler_cohort
    active_at_pulse_particles = [int]$result.population_counts.capture_all_active
    lost_before_pulse_particles = [int]$result.population_counts.all_exit_lost_before_pulse
    s2_oatof_entry_particles = [int]$result.population_counts.s2_oatof_entry
    local_accelerator_exit_particles = [int]$result.population_counts.local_accelerator_exit
    detector_hit_particles = [int]$result.population_counts.detector_hit
    pulse_instrument_time_us = [double]$result.pulse_instrument_time_us
    metrics = 'results/rf-oatof-checkpoints__metrics.json'
    particles = 'results/rf-oatof-checkpoints__particles.csv'
    figure = 'results/rf-oatof-checkpoints__state-comparison.png'
    solver_rerun = $false
    diagnostic_only = $true
    s3_stage_passed = $false
    formal_gate_passed = $false
  })
  $outputs = @($metrics, $particles, $figure, $analysisLog, $package.summary)
  Write-VerifiedRunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success -Software $software -Outputs $outputs
  Write-Output (
    'STATUS=PASS RUN_ID={0} SOURCE_RUN_ID={1} EXIT={2} ACTIVE={3} LOSS={4} S3_STAGE_PASS=false FORMAL=false' -f
    $RunId, $sourceManifestDocument.run_id,
    $result.population_counts.source_exit_all,
    $result.population_counts.capture_all_active,
    $result.population_counts.all_exit_lost_before_pulse
  )
} catch {
  $failureReason = $_.Exception.Message
  try {
    Complete-RfFailedRun -Python $package.python -RepoRoot $repoRoot `
      -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole 'rf_to_oatof_checkpoint_diagnostic_summary' `
      -Reason $failureReason -Software $software
    & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
      (Join-Path $package.run_dir 'run_manifest.json') --require-status failed
    if ($LASTEXITCODE -ne 0) {
      throw 'The failed checkpoint run manifest could not be verified.'
    }
  } catch {
    throw "Checkpoint diagnostic failed: $failureReason; failure record error: $($_.Exception.Message)"
  }
  throw "Checkpoint diagnostic failed: $failureReason"
}
