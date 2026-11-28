param(
  [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
  [Parameter(Mandatory = $true)][string]$ArtifactRootPath,
  [Parameter(Mandatory = $true)][string]$ScienceRoot,
  [string]$PythonExe = '',
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$repoRoot = $workspaceRoot
$artifactRootPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRootPath)
$artifactRoot = $artifactRootPath
$projectRoot = (Resolve-Path -LiteralPath $ScienceRoot).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) }
  elseif ($env:SIMULATION_PYTHON_EXE) { [IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE) }
  else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' }
$packageRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $packageRoot 'execution/resources/workspace_paths.ps1')
$artifactRoot = Resolve-RunArtifactRoot -ArtifactRoot $artifactRootPath -OwnerKind component -OwnerId single_reflection_oa_tof_mass_analyzer -Python $python
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__comsol__accelerator-transverse-field__grid'
}
& $python -I -B -m msplatform.execution.artifact_naming run $RunId
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
Copy-Item -LiteralPath (Join-Path $packageRoot 'backends/comsol/matlab/export_accelerator_transverse_field_uniformity.m') -Destination $task
Copy-Item -LiteralPath (Join-Path $packageRoot 'workflows/oa_tof_design/analyze_accelerator_transverse_field_uniformity.py') -Destination $analysis
Copy-Item -LiteralPath (Join-Path $projectRoot 'config\baseline.json') -Destination $baseline
Copy-Item -LiteralPath $PSCommandPath -Destination $runner
$formalModel = Join-Path $artifactRoot 'formal\comsol\single_reflection_oa_tof_mass_analyzer__model.mph'
$fieldCsv = Join-Path $resultDir 'accelerator_transverse_field_samples.csv'
$report = Join-Path $logDir 'comsol_export.txt'
$runConfig = Join-Path $runDir 'run_config.json'
$summary = Join-Path $runDir 'summary.json'
[ordered]@{
  schema_version=1; run_id=$RunId; project='single_reflection_oa_tof_mass_analyzer'
  mode='accelerator_transverse_field_uniformity_reference'; project_root=$repoRoot
  inputs=[ordered]@{task=$task;analysis=$analysis;baseline=$baseline;runner=$runner;formal_model=$formalModel}
  parameters=[ordered]@{solver_rerun=$false;particle_tracking=$false;formal_source_half_width_y_mm=0.5}
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{
  schema_version=1;role='oatof_accelerator_transverse_field_uniformity_run_summary'
  status='interrupted';reason='Run package initialized; final status was not yet recorded.'
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
$manifestWriter = 'from msplatform.execution.manifest_publication import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)'
& $python -I -B -c $manifestWriter --run-config $runConfig --status interrupted `
  --software 'COMSOL 6.4 saved field' --software 'MATLAB R2025b' --software 'Python 3.11'
if ($LASTEXITCODE -ne 0) { throw 'Initial run manifest generation failed.' }
& $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' `
  (Join-Path $runDir 'run_manifest.json') --require-status interrupted
if ($LASTEXITCODE -ne 0) { throw 'Initial run manifest verification failed.' }

$oldProject = $env:OATOF_PROJECT_ROOT
$oldModel = $env:OATOF_COMSOL_MODEL_PATH
$oldOutput = $env:OATOF_TRANSVERSE_FIELD_CSV
try {
  try {
    $env:OATOF_PROJECT_ROOT = $projectRoot
    $env:OATOF_COMSOL_MODEL_PATH = $formalModel
    $env:OATOF_TRANSVERSE_FIELD_CSV = $fieldCsv
    . (Join-Path (Split-Path -Parent ((Join-Path $packageRoot 'backends\comsol\launcher\run_comsol_r2025b.ps1'))) 'resolve_comsol_64.ps1')
    $comsolLauncherParameters=Get-ComsolLauncherParameters -HostContext $script:HostResourceExecutionContext -WorkingDirectory $script:HostResourceExecutionContext.workspace
    & (Join-Path $packageRoot 'backends\comsol\launcher\run_comsol_r2025b.ps1') @comsolLauncherParameters -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL field export failed.' }
  } finally {
    $env:OATOF_PROJECT_ROOT = $oldProject
    $env:OATOF_COMSOL_MODEL_PATH = $oldModel
    $env:OATOF_TRANSVERSE_FIELD_CSV = $oldOutput
  }
  & $python -I -B $analysis --input $fieldCsv --baseline $baseline --output-dir $resultDir
  if ($LASTEXITCODE -ne 0) { throw 'Transverse field analysis failed.' }
} catch {
  [ordered]@{
    schema_version=1;role='oatof_accelerator_transverse_field_uniformity_run_summary'
    status='failed';reason=$_.Exception.Message
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
  & $python -I -B -c $manifestWriter --run-config $runConfig --status failed `
    --software 'COMSOL 6.4 saved field' --software 'MATLAB R2025b' --software 'Python 3.11'
  & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' `
    (Join-Path $runDir 'run_manifest.json') --require-status failed
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
& $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' `
  (Join-Path $runDir 'run_manifest.json') --require-status success
if ($LASTEXITCODE -ne 0) { throw 'Run manifest verification failed.' }
Write-Output "STATUS=PASS RUN_ID=$RunId"
