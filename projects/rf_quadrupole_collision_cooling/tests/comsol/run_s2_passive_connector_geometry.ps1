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
if (-not [bool]$contractDocument.permissions.geometry_builder_implementation_allowed) {
  throw 'The S2 contract does not authorize geometry construction.'
}
$gapMm = [double]$contractDocument.nominal_registration.connector_gap_mm
if (-not [double]::IsFinite($gapMm) -or $gapMm -lt 0) {
  throw 'The S2 geometry-only runner requires a finite non-negative gap.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $gapLabel = ('{0:g}' -f $gapMm).Replace('.','p')
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__build__comsol__rf-oatof-s2-connector__gap$gapLabel"
}
$mode = 'rf_to_oatof_s2_passive_connector_geometry_build'
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package = New-RfRunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'rf_quadrupole_collision_cooling' -Mode $mode -Software $software
$python = $package.python
$runDir = $package.run_dir
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir

try {
$task = Join-Path $inputDir 'build_s2_passive_connector_geometry.m'
$geometryBuilder = Join-Path $inputDir 'build_s2_passive_connector_model.m'
$runner = Join-Path $inputDir 'run_s2_passive_connector_geometry.ps1.txt'
$support = Join-Path $inputDir 'rf_run_artifact_support.ps1.txt'
$contract = Join-Path $inputDir 'rf_to_oatof_s2_passive_connector.json'
$dependencyContract = Join-Path $inputDir 'rf_to_oatof_s2_dependencies.json'
$s1Contract = Join-Path $inputDir 'rf_to_oatof_s1_joint_field.json'
$rfResolved = Join-Path $inputDir 'rf_resolved_geometry.json'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_s2_passive_connector_geometry.m') -Destination $task
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

$metrics = Join-Path $resultDir 's2_passive_connector_geometry_metrics.json'
$report = Join-Path $logDir 'comsol_s2_passive_connector_geometry.txt'
$summary = $package.summary
$runConfig = $package.run_config
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
    geometry_build = $true
    mesh_build = $false
    physics_created = $false
    field_solve = $false
    particle_tracking = $false
    model_saved = $false
  }
  formal_gate_passed = $false
}
Write-RfJson -Path $runConfig -Depth 8 -Value $runConfiguration
Write-RfJson -Path $summary -Value ([ordered]@{
  schema_version = 1
  role = 'rf_to_oatof_s2_passive_connector_geometry_summary'
  status = 'interrupted'
  reason = 'Run package initialized; final status not yet recorded.'
})
Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
  -Status interrupted -Software $software

$environmentNames = @(
  'RF_OATOF_S2_GEOMETRY_METRICS','RF_OATOF_S2_CONTRACT','RF_OATOF_S2_S1_CONTRACT',
  'RF_OATOF_S2_RF_RESOLVED','RF_OATOF_S2_OA_BASELINE','RF_OATOF_S2_OA_COMSOL_DIR'
)
$oldEnvironment = Save-RfEnvironment -Names $environmentNames
try {
    $env:RF_OATOF_S2_GEOMETRY_METRICS = $metrics
    $env:RF_OATOF_S2_CONTRACT = $contract
    $env:RF_OATOF_S2_S1_CONTRACT = $s1Contract
    $env:RF_OATOF_S2_RF_RESOLVED = $rfResolved
    $env:RF_OATOF_S2_OA_BASELINE = $oaBaseline
    $env:RF_OATOF_S2_OA_COMSOL_DIR = $inputDir
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL S2 geometry-only task failed.' }
} finally {
  Restore-RfEnvironment -Names $environmentNames -Snapshot $oldEnvironment
}
$geometryMetrics = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
if ($geometryMetrics.status -ne 'BUILT' -or [bool]$geometryMetrics.field_solved -or
    [bool]$geometryMetrics.particle_runtime_executed) {
  throw 'S2 geometry metrics violate the build-only contract.'
}

Write-RfJson -Path $summary -Value ([ordered]@{
  schema_version = 1
  role = 'rf_to_oatof_s2_passive_connector_geometry_summary'
  status = 'success'
  result = 'results/s2_passive_connector_geometry_metrics.json'
  gap_mm = $gapMm
  geometry_built = $true
  mesh_built = $false
  field_solved = $false
  particle_runtime = $false
  s2_stage_passed = $false
  formal_gate_passed = $false
})
$outputs = @($metrics,$report,$summary)
Write-RfRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
  -Status success -Software $software -Outputs $outputs
Write-Output "STATUS=PASS RUN_ID=$RunId GAP_MM=$gapMm FIELD_SOLVED=false PARTICLES=false"
} catch {
  Complete-RfFailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_to_oatof_s2_passive_connector_geometry_summary' `
    -Reason $_.Exception.Message -Software $software
  throw
}
