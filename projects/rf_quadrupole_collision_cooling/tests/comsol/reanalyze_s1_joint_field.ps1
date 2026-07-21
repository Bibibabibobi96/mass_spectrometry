[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [string]$SourceRunId,
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__rf-oatof-s1-joint-field-reanalysis')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$sourceRun = Join-Path $artifactRoot "runs\$SourceRunId"
$sourceManifest = Join-Path $sourceRun 'run_manifest.json'
$sourceConfigPath = Join-Path $sourceRun 'run_config.json'
$sourceMetricsPath = Join-Path $sourceRun 'results\s1_joint_field_metrics.json'
foreach ($path in @($sourceManifest,$sourceConfigPath,$sourceMetricsPath)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "S1 source run is incomplete: $path" }
}
$sourceConfig = Get-Content -LiteralPath $sourceConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceMetrics = Get-Content -LiteralPath $sourceMetricsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sourceConfig.mode -ne 'rf_to_oatof_s1_local_joint_field' -or $sourceMetrics.status -ne 'CHARACTERIZED') {
  throw 'SourceRunId is not a characterized S1 joint-field run.'
}
$candidate = Join-Path $sourceRun 'results\s1_joint_field_samples.csv'
$closedReference = [string]$sourceConfig.inputs.closed_reference
$joint = [string]$sourceConfig.inputs.joint_contract
$interface = [string]$sourceConfig.inputs.interface_contract
$rfResolved = [string]$sourceConfig.inputs.rf_resolved
$referenceRole = [string]$sourceMetrics.axis_change_reference_role

$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'
New-Item -ItemType Directory -Path $inputDir,$resultDir | Out-Null
$analysis = Join-Path $inputDir 'analyze_s1_joint_field.py'
Copy-Item (Join-Path $projectRoot 'analysis\analyze_s1_joint_field.py') $analysis
$uniformity = Join-Path $inputDir 'analyze_accelerator_transverse_field_uniformity.py'
Copy-Item (Join-Path $repoRoot 'projects\oa_tof\analysis\analyze_accelerator_transverse_field_uniformity.py') $uniformity
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python $analysis --candidate $candidate --closed-reference $closedReference `
  --joint-contract $joint --interface-contract $interface --rf-resolved $rfResolved `
  --reference-role $referenceRole --output-dir $resultDir
if ($LASTEXITCODE -ne 0) { throw 'S1 joint-field reanalysis failed.' }

$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{
  schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_to_oatof_s1_joint_field_reanalysis';project_root=$repoRoot
  inputs=[ordered]@{analysis=$analysis;uniformity_analysis=$uniformity;source_manifest=$sourceManifest;candidate_field=$candidate;closed_reference=$closedReference;joint_contract=$joint;interface_contract=$interface;rf_resolved=$rfResolved}
  parameters=[ordered]@{source_run_id=$SourceRunId;solver_rerun=$false;reference_role=$referenceRole}
  formal_gate_passed=$false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_to_oatof_s1_joint_field_reanalysis_summary';status='success';source_run_id=$SourceRunId;result='results/s1_joint_field_metrics.json'} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
$manifest = Join-Path $runDir 'run_manifest.json'
$outputs = @((Join-Path $resultDir 's1_joint_field_uniformity_curve.csv'),(Join-Path $resultDir 's1_joint_field_metrics.json'),$summary)
$figure = Join-Path $resultDir 's1_injection_axis_field.png'; if (Test-Path -LiteralPath $figure) { $outputs += $figure }
$args = @((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$runConfig,'--manifest',$manifest,'--status','success','--software','Python 3.11')
foreach ($output in $outputs) { $args += @('--output',$output) }
& $python @args
if ($LASTEXITCODE -ne 0) { throw 'S1 reanalysis manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest
if ($LASTEXITCODE -ne 0) { throw 'S1 reanalysis manifest verification failed.' }
Write-Output "S1_JOINT_FIELD_REANALYSIS=PASS RUN_ID=$RunId SOURCE_RUN_ID=$SourceRunId"
