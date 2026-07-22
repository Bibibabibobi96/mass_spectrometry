[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectRoot,
  [Parameter(Mandatory = $true)]
  [string]$FieldScreenRunId,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRootPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$project = Get-Content -LiteralPath (Join-Path $projectRootPath 'config\project.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$projectId = [string]$project.project_id
& $python (Join-Path $repoRoot 'common\contracts\artifact_project.py') `
  --artifact-projects-root (Join-Path $workspaceRoot 'artifacts\projects') --project-id $projectId
if ($LASTEXITCODE -ne 0) { throw 'Multipole artifact project initialization failed.' }
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $FieldScreenRunId
if ($LASTEXITCODE -ne 0) { throw "Invalid field-screen run_id: $FieldScreenRunId" }
$sourceDir = Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$FieldScreenRunId"
$sourceManifest = Join-Path $sourceDir 'run_manifest.json'
$sourceDocument = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sourceDocument.status -ne 'success' -or $sourceDocument.project -ne $projectId) {
  throw 'The finite 3D field-screen source is not a successful run for this project.'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $taskLabel = $projectId.Replace('_','-') + '-finite-3d-interfaces'
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__sim__comsol__${taskLabel}__l3-n25"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }

$runDir = Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
$runtimeDir = Join-Path $logDir 'runtime'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir,$runtimeDir | Out-Null
$baseline = Join-Path $inputDir 'baseline.json'
$familyOperating = Join-Path $inputDir 'family_operating_contract.json'
$contract = Join-Path $inputDir 'finite_3d_transport.json'
$resolvedContract = Join-Path $inputDir 'finite_3d_transport_resolved.json'
$mode = Join-Path $inputDir 'finite_3d_no_collision.json'
$fieldMetrics = Join-Path $inputDir 'round_rod_field_screen_metrics.json'
$roundRodGeometry = Join-Path $inputDir 'round_rod_geometry.json'
$particleSource = Join-Path $inputDir 'particle_source.csv'
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\baseline.json') -Destination $baseline
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\finite_3d_transport.json') -Destination $contract
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\modes\finite_3d_no_collision.json') -Destination $mode
Push-Location $repoRoot
try {
  & $python -m common.multipole.resolve_family_operating_contract `
    --adapter high-order --baseline $baseline --output $familyOperating
  if ($LASTEXITCODE -ne 0) { throw 'Shared multipole operating-contract resolution failed.' }
} finally { Pop-Location }
$sourceSamples = Join-Path $sourceDir 'results\round_rod_potential_samples.csv'
$sourceContract = Join-Path $sourceDir 'inputs\round_rod_field_screen.json'
$screenAnalysis = Join-Path $repoRoot 'common\multipole\analyze_round_rod_screen.py'
'{}' | Set-Content -LiteralPath $fieldMetrics -Encoding UTF8
'{}' | Set-Content -LiteralPath $resolvedContract -Encoding UTF8
'{}' | Set-Content -LiteralPath $roundRodGeometry -Encoding UTF8
'particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s' |
  Set-Content -LiteralPath $particleSource -Encoding UTF8

$events = Join-Path $resultDir 'particle_events.csv'
$trajectories = Join-Path $resultDir 'trajectory_samples.csv'
$metrics = Join-Path $resultDir 'finite_3d_transport_metrics.json'
$plot = Join-Path $resultDir 'finite_3d_transport.png'
$model = Join-Path $resultDir 'finite_3d_transport.mph'
$report = Join-Path $logDir 'comsol_finite_3d_transport.txt'
$summary = Join-Path $runDir 'summary.json'
$runConfig = Join-Path $runDir 'run_config.json'
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
$task = Join-Path $repoRoot 'common\multipole\solve_finite_3d_transport.m'
[ordered]@{
  schema_version = 1
  role = 'multipole_finite_3d_transport_run_config'
  run_id = $RunId
  project = $projectId
  mode = 'finite_3d_no_collision'
  project_root = $projectRootPath
  inputs = [ordered]@{
    baseline = $baseline
    family_operating_contract = $familyOperating
    mode = $mode
    finite_3d_contract = $contract
    finite_3d_resolved_contract = $resolvedContract
    particle_source = $particleSource
    field_screen_metrics = $fieldMetrics
    round_rod_geometry = $roundRodGeometry
    field_screen_manifest = $sourceManifest
    field_screen_contract = $sourceContract
    field_screen_samples = $sourceSamples
    comsol_task = $task
  }
  parameters = [ordered]@{ model_level='L3'; direct_comsol_particle_tracking=$true; mesh_convergence=$false }
  formal_gate_passed = $false
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{ schema_version=1; role='multipole_finite_3d_transport_summary'; status='interrupted' } |
  ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $summary
if ($LASTEXITCODE -ne 0) { throw 'Initial finite 3D run manifest failed.' }

$environmentNames = @(
  'MULTIPOLE_L3_BASELINE','MULTIPOLE_L3_FAMILY_OPERATING','MULTIPOLE_L3_CONTRACT','MULTIPOLE_L3_FIELD_METRICS','MULTIPOLE_L3_ROUND_ROD_GEOMETRY',
  'MULTIPOLE_L3_PARTICLE_SOURCE','MULTIPOLE_L3_RUNTIME_DIR','MULTIPOLE_L3_EVENTS',
  'MULTIPOLE_L3_TRAJECTORIES','MULTIPOLE_L3_METRICS','MULTIPOLE_L3_PLOT','MULTIPOLE_L3_MODEL'
)
$oldEnvironment = @{}
foreach ($name in $environmentNames) { $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
  try {
    & $python $screenAnalysis --samples $sourceSamples --contract $sourceContract --output $fieldMetrics
    if ($LASTEXITCODE -ne 0) { throw 'Could not freeze the selected L2 field-screen geometry.' }
    Push-Location $repoRoot
    try {
      & $python -m common.multipole.resolve_finite_3d_contract `
        --baseline $baseline --contract $contract --output $resolvedContract
      if ($LASTEXITCODE -ne 0) { throw 'Finite 3D interface contract validation failed.' }
    } finally { Pop-Location }
    Push-Location $repoRoot
    try {
      & $python -m common.multipole.round_rod_geometry `
        --baseline $baseline --finite-3d $resolvedContract --field-metrics $fieldMetrics --output $roundRodGeometry
      if ($LASTEXITCODE -ne 0) { throw 'Could not freeze the shared round-rod geometry.' }
    } finally { Pop-Location }
    $l3Document = Get-Content -LiteralPath $resolvedContract -Raw -Encoding UTF8 | ConvertFrom-Json
    Push-Location $repoRoot
    try {
      & $python -m common.multipole.generate_particle_source `
        --baseline $baseline --release-z-mm ([double]$l3Document.derived_geometry_mm.source_z) --output $particleSource
      if ($LASTEXITCODE -ne 0) { throw 'Could not freeze the finite 3D particle source.' }
    } finally { Pop-Location }
    $env:MULTIPOLE_L3_BASELINE = $baseline
    $env:MULTIPOLE_L3_FAMILY_OPERATING = $familyOperating
    $env:MULTIPOLE_L3_CONTRACT = $resolvedContract
    $env:MULTIPOLE_L3_FIELD_METRICS = $fieldMetrics
    $env:MULTIPOLE_L3_ROUND_ROD_GEOMETRY = $roundRodGeometry
    $env:MULTIPOLE_L3_PARTICLE_SOURCE = $particleSource
    $env:MULTIPOLE_L3_RUNTIME_DIR = $runtimeDir
    $env:MULTIPOLE_L3_EVENTS = $events
    $env:MULTIPOLE_L3_TRAJECTORIES = $trajectories
    $env:MULTIPOLE_L3_METRICS = $metrics
    $env:MULTIPOLE_L3_PLOT = $plot
    $env:MULTIPOLE_L3_MODEL = $model
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL finite 3D multipole transport failed.' }
    $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
    [ordered]@{
      schema_version = 1
      role = 'multipole_finite_3d_transport_summary'
      status = 'success'
      project_id = $projectId
      source_field_screen_run_id = $FieldScreenRunId
      selected_rod_radius_ratio = $result.selected_geometry.rod_radius_ratio
      rf_transmission = $result.cases.finite_3d_rf_on.transmission_fraction
      zero_rf_transmission = $result.cases.zero_rf_control.transmission_fraction
      model_level = 'L3'
      formal_gate_passed = $false
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summary -Encoding UTF8
    $outputs = @($events,$trajectories,$metrics,$plot,$model,$report,$summary)
    $manifestArguments = @($manifestWriter,'--run-config',$runConfig,'--status','success',
      '--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
    foreach ($output in $outputs) { $manifestArguments += @('--output',$output) }
    & $python @manifestArguments
    if ($LASTEXITCODE -ne 0) { throw 'Final finite 3D run manifest failed.' }
    Write-Output "FINITE_3D_L3=PASS PROJECT=$projectId RUN_ID=$RunId RF=$($result.cases.finite_3d_rf_on.transmission_fraction) ZERO=$($result.cases.zero_rf_control.transmission_fraction)"
  } catch {
    [ordered]@{ schema_version=1; role='multipole_finite_3d_transport_summary'; status='failed'; reason=$_.Exception.Message } |
      ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
    $failureOutputs = @($summary)
    foreach ($path in @($report,$events,$trajectories,$metrics,$plot,$model)) {
      if (Test-Path -LiteralPath $path -PathType Leaf) { $failureOutputs += $path }
    }
    $failureArguments = @($manifestWriter,'--run-config',$runConfig,'--status','failed',
      '--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
    foreach ($output in $failureOutputs) { $failureArguments += @('--output',$output) }
    & $python @failureArguments
    throw
  }
} finally {
  foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name]) }
}
