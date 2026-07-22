param([string]$RunId = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$contractSource = Join-Path $projectRoot 'config\rf_to_oatof_s2_passive_connector.json'
$contractDocument = Get-Content -LiteralPath $contractSource -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$contractDocument.permissions.geometry_builder_implementation_allowed) {
  throw 'The S2 contract does not authorize geometry construction.'
}
if ([bool]$contractDocument.permissions.field_solve_allowed -or
    [bool]$contractDocument.permissions.particle_runtime_allowed) {
  throw 'The S2 geometry-only runner requires field and particle runtime to remain disabled.'
}
$gapMm = [double]$contractDocument.nominal_registration.connector_gap_mm
if ([math]::Abs($gapMm-1.0) -gt 1e-12) {
  throw 'The S2 geometry-only runner requires the approved 1 mm gap.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__build__comsol__rf-oatof-s2-passive-connector__gap1'
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }

$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir | Out-Null

$task = Join-Path $inputDir 'build_s2_passive_connector_geometry.m'
$runner = Join-Path $inputDir 'run_s2_passive_connector_geometry.ps1.txt'
$contract = Join-Path $inputDir 'rf_to_oatof_s2_passive_connector.json'
$s1Contract = Join-Path $inputDir 'rf_to_oatof_s1_joint_field.json'
$rfResolved = Join-Path $inputDir 'rf_resolved_geometry.json'
$oaBaseline = Join-Path $inputDir 'oatof_baseline.json'
$oaBuilder = Join-Path $inputDir 'oatof_build_accelerator_geometry.m'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'build_s2_passive_connector_geometry.m') -Destination $task
Copy-Item -LiteralPath $PSCommandPath -Destination $runner
Copy-Item -LiteralPath $contractSource -Destination $contract
Copy-Item -LiteralPath (Join-Path $projectRoot 'config\rf_to_oatof_s1_joint_field.json') -Destination $s1Contract
Copy-Item -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Destination $rfResolved
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\config\baseline.json') -Destination $oaBaseline
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\comsol\oatof_build_accelerator_geometry.m') -Destination $oaBuilder

$metrics = Join-Path $resultDir 's2_passive_connector_geometry_metrics.json'
$report = Join-Path $logDir 'comsol_s2_passive_connector_geometry.txt'
$summary = Join-Path $runDir 'summary.json'
$runConfig = Join-Path $runDir 'run_config.json'
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
[ordered]@{
  schema_version = 1
  run_id = $RunId
  project = 'rf_quadrupole_collision_cooling'
  mode = 'rf_to_oatof_s2_passive_connector_geometry_build'
  project_root = $repoRoot
  inputs = [ordered]@{
    task = $task
    runner = $runner
    s2_contract = $contract
    s1_joint_field_contract = $s1Contract
    rf_resolved_geometry = $rfResolved
    oatof_baseline = $oaBaseline
    oatof_accelerator_builder = $oaBuilder
  }
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
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{
  schema_version = 1
  role = 'rf_to_oatof_s2_passive_connector_geometry_summary'
  status = 'interrupted'
  reason = 'Run package initialized; final status not yet recorded.'
} | ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted `
  --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
if ($LASTEXITCODE -ne 0) { throw 'Initial S2 geometry manifest failed.' }

$environmentNames = @(
  'RF_OATOF_S2_GEOMETRY_METRICS','RF_OATOF_S2_CONTRACT','RF_OATOF_S2_S1_CONTRACT',
  'RF_OATOF_S2_RF_RESOLVED','RF_OATOF_S2_OA_BASELINE','RF_OATOF_S2_OA_COMSOL_DIR'
)
$oldEnvironment = @{}
foreach ($name in $environmentNames) {
  $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
}
try {
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
    foreach ($name in $environmentNames) {
      [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name])
    }
  }
  $geometryMetrics = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($geometryMetrics.status -ne 'BUILT' -or [bool]$geometryMetrics.field_solved -or
      [bool]$geometryMetrics.particle_runtime_executed) {
    throw 'S2 geometry metrics violate the build-only contract.'
  }
} catch {
  [ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_s2_passive_connector_geometry_summary'
    status = 'failed'
    reason = $_.Exception.Message
  } | ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
  & $python $manifestWriter --run-config $runConfig --status failed `
    --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
  throw
}

[ordered]@{
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
} | ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
$outputs = @($metrics,$report,$summary)
$manifestArguments = @($manifestWriter,'--run-config',$runConfig,'--status','success',
  '--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
foreach ($output in $outputs) { $manifestArguments += @('--output',$output) }
& $python @manifestArguments
if ($LASTEXITCODE -ne 0) { throw 'Final S2 geometry manifest failed.' }
Write-Output "STATUS=PASS RUN_ID=$RunId GAP_MM=1 FIELD_SOLVED=false PARTICLES=false"
