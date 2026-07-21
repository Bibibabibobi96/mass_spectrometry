param([string]$RunId = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__comsol__accelerator-transverse-field__grid'
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir | Out-Null

$task = Join-Path $inputDir 'export_accelerator_transverse_field_uniformity.m'
$analysis = Join-Path $inputDir 'analyze_accelerator_transverse_field_uniformity.py'
$baseline = Join-Path $inputDir 'baseline.json'
$runner = Join-Path $inputDir 'run_accelerator_transverse_field_uniformity.ps1.txt'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'export_accelerator_transverse_field_uniformity.m') -Destination $task
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\analyze_accelerator_transverse_field_uniformity.py') -Destination $analysis
Copy-Item -LiteralPath (Join-Path $projectRoot 'config\baseline.json') -Destination $baseline
Copy-Item -LiteralPath $PSCommandPath -Destination $runner
$formalModel = Join-Path $artifactRoot 'formal\comsol\oa_tof__model.mph'
$fieldCsv = Join-Path $resultDir 'accelerator_transverse_field_samples.csv'
$report = Join-Path $logDir 'comsol_export.txt'
$runConfig = Join-Path $runDir 'run_config.json'
$summary = Join-Path $runDir 'summary.json'
[ordered]@{
  schema_version=1; run_id=$RunId; project='oa_tof'
  mode='accelerator_transverse_field_uniformity_reference'; project_root=$repoRoot
  inputs=[ordered]@{task=$task;analysis=$analysis;baseline=$baseline;runner=$runner;formal_model=$formalModel}
  parameters=[ordered]@{solver_rerun=$false;particle_tracking=$false;formal_source_half_width_y_mm=0.5}
  formal_gate_passed=$false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{
  schema_version=1;role='oatof_accelerator_transverse_field_uniformity_run_summary'
  status='interrupted';reason='Run package initialized; final status was not yet recorded.'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
& $python $manifestWriter --run-config $runConfig --status interrupted `
  --software 'COMSOL 6.4 saved field' --software 'MATLAB R2025b' --software 'Python 3.11'
if ($LASTEXITCODE -ne 0) { throw 'Initial run manifest generation failed.' }

$oldProject = $env:OATOF_PROJECT_ROOT
$oldModel = $env:OATOF_COMSOL_MODEL_PATH
$oldOutput = $env:OATOF_TRANSVERSE_FIELD_CSV
try {
  try {
    $env:OATOF_PROJECT_ROOT = $projectRoot
    $env:OATOF_COMSOL_MODEL_PATH = $formalModel
    $env:OATOF_TRANSVERSE_FIELD_CSV = $fieldCsv
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL field export failed.' }
  } finally {
    $env:OATOF_PROJECT_ROOT = $oldProject
    $env:OATOF_COMSOL_MODEL_PATH = $oldModel
    $env:OATOF_TRANSVERSE_FIELD_CSV = $oldOutput
  }
  & $python $analysis --input $fieldCsv --baseline $baseline --output-dir $resultDir
  if ($LASTEXITCODE -ne 0) { throw 'Transverse field analysis failed.' }
} catch {
  [ordered]@{
    schema_version=1;role='oatof_accelerator_transverse_field_uniformity_run_summary'
    status='failed';reason=$_.Exception.Message
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
  & $python $manifestWriter --run-config $runConfig --status failed `
    --software 'COMSOL 6.4 saved field' --software 'MATLAB R2025b' --software 'Python 3.11'
  throw
}
[ordered]@{
  schema_version=1;role='oatof_accelerator_transverse_field_uniformity_run_summary'
  status='success';physical_interface=$false;field_source='saved formal electrostatic solution'
  result='results/transverse_field_uniformity_metrics.json'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
$outputs = @(
  $fieldCsv,
  (Join-Path $resultDir 'transverse_field_uniformity_curve.csv'),
  (Join-Path $resultDir 'transverse_field_uniformity_metrics.json'),
  (Join-Path $resultDir 'transverse_field_uniformity.png'),
  $report,$summary
)
$manifestArgs = @(
  $manifestWriter,
  '--run-config',$runConfig,'--status','success',
  '--software','COMSOL 6.4 saved field','--software','MATLAB R2025b','--software','Python 3.11'
)
foreach ($output in $outputs) { $manifestArgs += @('--output',$output) }
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Run manifest generation failed.' }
Write-Output "STATUS=PASS RUN_ID=$RunId"
