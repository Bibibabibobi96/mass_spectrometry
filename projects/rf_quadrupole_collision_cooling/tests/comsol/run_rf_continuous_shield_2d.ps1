param(
  [double]$ShieldInnerRadiusMm = 19.776,
  [ValidateSet(0.1,0.2)]
  [double]$MeshHmaxMm = 0.2,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$contractSource = Join-Path $projectRoot 'config\rf_continuous_grounded_shield_candidate.json'
& $python (Join-Path $projectRoot 'analysis\validate_rf_continuous_shield.py')
if ($LASTEXITCODE -ne 0) { throw 'RF continuous shield contract failed.' }
$contractDocument = Get-Content -LiteralPath $contractSource -Raw -Encoding UTF8 | ConvertFrom-Json
$allowedRadii = @($contractDocument.candidate_geometry_mm.inner_radius_mm_sweep | ForEach-Object { [double]$_ })
if (-not ($allowedRadii | Where-Object { [math]::Abs($_-$ShieldInnerRadiusMm) -le 1e-12 })) {
  throw "ShieldInnerRadiusMm must match a frozen diagnostic value: $($allowedRadii -join ', ')"
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $radiusLabel = ([string]$ShieldInnerRadiusMm).Replace('.','p')
  $meshLabel = ([string]$MeshHmaxMm).Replace('.','p')
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__analysis__comsol__rf-continuous-shield-2d__r${radiusLabel}-h${meshLabel}"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'; $logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir | Out-Null
$task = Join-Path $inputDir 'build_rf_continuous_shield_2d.m'
$analysis = Join-Path $inputDir 'analyze_rf_continuous_shield_2d.py'
$contract = Join-Path $inputDir 'rf_continuous_grounded_shield_candidate.json'
$resolved = Join-Path $inputDir 'rf_resolved_geometry.json'
$runner = Join-Path $inputDir 'run_rf_continuous_shield_2d.ps1.txt'
Copy-Item $PSCommandPath $runner
Copy-Item (Join-Path $PSScriptRoot 'build_rf_continuous_shield_2d.m') $task
Copy-Item (Join-Path $projectRoot 'analysis\analyze_rf_continuous_shield_2d.py') $analysis
Copy-Item $contractSource $contract
Copy-Item (Join-Path $projectRoot 'config\resolved_geometry.json') $resolved
$fieldCsv = Join-Path $resultDir 'rf_continuous_shield_2d_samples.csv'
$report = Join-Path $logDir 'comsol_rf_continuous_shield_2d.txt'
$summary = Join-Path $runDir 'summary.json'; $runConfig = Join-Path $runDir 'run_config.json'
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
[ordered]@{
  schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_continuous_grounded_shield_2d_field_screen';project_root=$repoRoot
  inputs=[ordered]@{task=$task;analysis=$analysis;shield_contract=$contract;rf_resolved=$resolved;runner=$runner}
  parameters=[ordered]@{shield_inner_radius_mm=$ShieldInnerRadiusMm;mesh_hmax_mm=$MeshHmaxMm;rod_potential_pattern_V=@(100,-100,100,-100);particle_tracking=$false;model_saved=$false}
  formal_gate_passed=$false
} | ConvertTo-Json -Depth 6 | Set-Content $runConfig -Encoding UTF8
[ordered]@{schema_version=1;role='rf_continuous_shield_2d_summary';status='interrupted';reason='Run package initialized; final status not yet recorded.'} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
if ($LASTEXITCODE -ne 0) { throw 'Initial manifest failed.' }
$names=@('RF_SHIELD_2D_FIELD_CSV','RF_SHIELD_CONTRACT','RF_SHIELD_RF_RESOLVED','RF_SHIELD_INNER_RADIUS_MM','RF_SHIELD_MESH_HMAX_MM')
$old=@{}; foreach($name in $names){$old[$name]=[Environment]::GetEnvironmentVariable($name)}
try {
  try {
    $env:RF_SHIELD_2D_FIELD_CSV=$fieldCsv; $env:RF_SHIELD_CONTRACT=$contract; $env:RF_SHIELD_RF_RESOLVED=$resolved
    $env:RF_SHIELD_INNER_RADIUS_MM=[string]$ShieldInnerRadiusMm; $env:RF_SHIELD_MESH_HMAX_MM=[string]$MeshHmaxMm
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL RF shield 2D task failed.' }
  } finally {
    foreach($name in $names){[Environment]::SetEnvironmentVariable($name,$old[$name])}
  }
  & $python $analysis --input $fieldCsv --output-dir $resultDir
  if ($LASTEXITCODE -ne 0) { throw 'RF shield 2D analysis failed.' }
} catch {
  [ordered]@{schema_version=1;role='rf_continuous_shield_2d_summary';status='failed';reason=$_.Exception.Message} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
  & $python $manifestWriter --run-config $runConfig --status failed --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
  throw
}
[ordered]@{schema_version=1;role='rf_continuous_shield_2d_summary';status='success';result='results/rf_continuous_shield_2d_metrics.json';physical_shield_selected=$false;particle_tracking=$false} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
$outputs=@($fieldCsv,(Join-Path $resultDir 'rf_continuous_shield_harmonics.csv'),(Join-Path $resultDir 'rf_continuous_shield_2d_metrics.json'),$report,$summary)
$args=@($manifestWriter,'--run-config',$runConfig,'--status','success','--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
foreach($output in $outputs){$args+=@('--output',$output)}
& $python @args
if ($LASTEXITCODE -ne 0) { throw 'Final manifest failed.' }
Write-Output "STATUS=PASS RUN_ID=$RunId SHIELD_SELECTED=false"
