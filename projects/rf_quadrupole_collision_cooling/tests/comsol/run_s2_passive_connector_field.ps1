param([string]$RunId = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$supportSource = (Resolve-Path (Join-Path $PSScriptRoot '..\support\rf_run_artifact_support.ps1')).Path
. $supportSource
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$contractSource = Join-Path $projectRoot 'config\rf_to_oatof_s2_passive_connector.json'
$dependencyContractSource = Join-Path $projectRoot 'config\rf_to_oatof_s2_dependencies.json'
$contractDocument = Get-Content -LiteralPath $contractSource -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$contractDocument.permissions.field_solve_allowed) {
  throw 'The S2 contract does not authorize a field solve.'
}
if ([bool]$contractDocument.permissions.particle_runtime_allowed) {
  throw 'The S2 no-pulse field runner requires particle runtime to remain disabled.'
}
$gapMm = [double]$contractDocument.nominal_registration.connector_gap_mm
if ([math]::Abs($gapMm-1.0) -gt 1e-12) {
  throw 'The S2 no-pulse field runner requires the approved 1 mm gap.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__comsol__rf-oatof-s2-no-pulse-field__gap1'
}
$mode = 'rf_to_oatof_s2_passive_connector_no_pulse_field'
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
  $runner = Join-Path $inputDir 'run_s2_passive_connector_field.ps1.txt'
  $support = Join-Path $inputDir 'rf_run_artifact_support.ps1.txt'
  $contract = Join-Path $inputDir 'rf_to_oatof_s2_passive_connector.json'
  $dependencyContract = Join-Path $inputDir 'rf_to_oatof_s2_dependencies.json'
  $s1Contract = Join-Path $inputDir 'rf_to_oatof_s1_joint_field.json'
  $rfResolved = Join-Path $inputDir 'rf_resolved_geometry.json'
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'solve_s2_passive_connector_field.m') -Destination $task
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_s2_passive_connector_model.m') -Destination $geometryBuilder
  Copy-Item -LiteralPath $PSCommandPath -Destination $runner
  Copy-Item -LiteralPath $supportSource -Destination $support
  Copy-Item -LiteralPath $contractSource -Destination $contract
  Copy-Item -LiteralPath $dependencyContractSource -Destination $dependencyContract
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_s1_joint_field.json') -Destination $s1Contract
  Copy-Item -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Destination $rfResolved

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
      runner = $runner
      run_artifact_support = $support
      s2_contract = $contract
      dependency_contract = $dependencyContract
      s1_joint_field_contract = $s1Contract
      rf_resolved_geometry = $rfResolved
      oatof_baseline = $oaBaseline
      oatof_accelerator_builder = $oaBuilder
    }
    dependency_identities = $dependencyIdentities
    parameters = [ordered]@{
      connector_gap_mm = $gapMm
      field_bases = @('oatof_static','rf_unit_100_V')
      oa_extraction_pulse = $false
      particle_tracking = $false
      model_saved = $false
      mesh_convergence_claimed = $false
    }
    formal_gate_passed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 8 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_s2_no_pulse_field_summary'
    status = 'interrupted'
    reason = 'Run package initialized; final status not yet recorded.'
  })
  Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status interrupted -Software $software

  $environmentNames = @(
    'RF_OATOF_S2_FIELD_METRICS','RF_OATOF_S2_FIELD_SAMPLES','RF_OATOF_S2_CONTRACT',
    'RF_OATOF_S2_S1_CONTRACT','RF_OATOF_S2_RF_RESOLVED','RF_OATOF_S2_OA_BASELINE',
    'RF_OATOF_S2_OA_COMSOL_DIR'
  )
  $oldEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:RF_OATOF_S2_FIELD_METRICS = $metrics
    $env:RF_OATOF_S2_FIELD_SAMPLES = $samples
    $env:RF_OATOF_S2_CONTRACT = $contract
    $env:RF_OATOF_S2_S1_CONTRACT = $s1Contract
    $env:RF_OATOF_S2_RF_RESOLVED = $rfResolved
    $env:RF_OATOF_S2_OA_BASELINE = $oaBaseline
    $env:RF_OATOF_S2_OA_COMSOL_DIR = $inputDir
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL S2 no-pulse field task failed.' }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $oldEnvironment
  }

  $fieldMetrics = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($fieldMetrics.status -ne 'SOLVED' -or -not [bool]$fieldMetrics.all_probe_values_finite -or
      [double]$fieldMetrics.rf_off_axis_field_norm_V_per_m -le 0 -or
      [bool]$fieldMetrics.particle_runtime_executed -or [bool]$fieldMetrics.oa_extraction_pulse_included -or
      [bool]$fieldMetrics.mesh_convergence_claimed -or [bool]$fieldMetrics.s2_stage_passed) {
    throw 'S2 field metrics violate the no-pulse functional contract.'
  }
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_s2_no_pulse_field_summary'
    status = 'success'
    metrics = 'results/s2_no_pulse_field_metrics.json'
    samples = 'results/s2_no_pulse_field_samples.csv'
    gap_mm = $gapMm
    field_bases_solved = 2
    finite_probe_rows = [int]$fieldMetrics.probe_count
    particle_runtime = $false
    oa_extraction_pulse = $false
    mesh_convergence_claimed = $false
    s2_stage_passed = $false
    formal_gate_passed = $false
  })
  $outputs = @($metrics,$samples,$report,$package.summary)
  Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  Write-Output "STATUS=PASS RUN_ID=$RunId GAP_MM=1 FIELD_BASES=2 PARTICLES=false OA_PULSE=false"
} catch {
  Complete-RfFailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_to_oatof_s2_no_pulse_field_summary' `
    -Reason $_.Exception.Message -Software $software
  throw
}
