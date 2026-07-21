param(
  [Parameter(Mandatory=$true)][string]$CandidateRunId,
  [Parameter(Mandatory=$true)][string]$ReferenceRunId,
  [Parameter(Mandatory=$true)][ValidateSet('mesh_convergence','radius_sensitivity')][string]$ComparisonKind,
  [string]$RunId=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactRoot=Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
$sourceRoot=Join-Path $artifactRoot 'runs'
foreach($sourceId in @($CandidateRunId,$ReferenceRunId)) {
  & $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $sourceId
  if($LASTEXITCODE -ne 0){throw "Invalid source run_id: $sourceId"}
}
$candidateDir=Join-Path $sourceRoot $CandidateRunId; $referenceDir=Join-Path $sourceRoot $ReferenceRunId
$candidateManifest=Join-Path $candidateDir 'run_manifest.json'; $referenceManifest=Join-Path $referenceDir 'run_manifest.json'
$candidateCsv=Join-Path $candidateDir 'results\rf_continuous_shield_3d_samples.csv'; $referenceCsv=Join-Path $referenceDir 'results\rf_continuous_shield_3d_samples.csv'
foreach($path in @($candidateManifest,$referenceManifest,$candidateCsv,$referenceCsv)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required source evidence is missing: $path"}}
foreach($manifestPath in @($candidateManifest,$referenceManifest)){
  $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if($manifest.status -ne 'success' -or $manifest.mode -ne 'rf_continuous_grounded_shield_3d_fringe_field_screen'){throw "Source manifest is not a successful 3D shield field run: $manifestPath"}
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__analysis__python__rf-continuous-shield-3d-$ComparisonKind"}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if($LASTEXITCODE -ne 0){throw "Invalid run_id: $RunId"}
$runDir=Join-Path $sourceRoot $RunId; if(Test-Path -LiteralPath $runDir){throw "Run already exists: $runDir"}
$inputDir=Join-Path $runDir 'inputs'; $resultDir=Join-Path $runDir 'results'; New-Item -ItemType Directory -Force -Path $inputDir,$resultDir | Out-Null
$analysis=Join-Path $inputDir 'compare_rf_continuous_shield_3d.py'; $runner=Join-Path $inputDir 'run_rf_continuous_shield_3d_comparison.ps1.txt'
Copy-Item (Join-Path $projectRoot 'analysis\compare_rf_continuous_shield_3d.py') $analysis; Copy-Item $PSCommandPath $runner
$summary=Join-Path $runDir 'summary.json'; $runConfig=Join-Path $runDir 'run_config.json'; $manifestWriter=Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
[ordered]@{
  schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_continuous_grounded_shield_3d_paired_field_comparison';project_root=$repoRoot
  inputs=[ordered]@{analysis=$analysis;runner=$runner;candidate_samples=$candidateCsv;candidate_manifest=$candidateManifest;reference_samples=$referenceCsv;reference_manifest=$referenceManifest}
  parameters=[ordered]@{comparison_kind=$ComparisonKind;candidate_run_id=$CandidateRunId;reference_run_id=$ReferenceRunId;particle_tracking=$false}
  formal_gate_passed=$false
}|ConvertTo-Json -Depth 6|Set-Content $runConfig -Encoding UTF8
[ordered]@{schema_version=1;role='rf_continuous_shield_3d_paired_field_summary';status='interrupted'}|ConvertTo-Json|Set-Content $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'Python 3.11'
if($LASTEXITCODE -ne 0){throw 'Initial manifest failed.'}
try{
  & $python $analysis --candidate $candidateCsv --reference $referenceCsv --comparison-kind $ComparisonKind --output-dir $resultDir
  if($LASTEXITCODE -ne 0){throw 'Paired 3D shield field analysis failed.'}
}catch{
  [ordered]@{schema_version=1;role='rf_continuous_shield_3d_paired_field_summary';status='failed';reason=$_.Exception.Message}|ConvertTo-Json|Set-Content $summary -Encoding UTF8
  & $python $manifestWriter --run-config $runConfig --status failed --software 'Python 3.11'
  throw
}
$metrics=Get-Content -LiteralPath (Join-Path $resultDir 'rf_continuous_shield_3d_paired_field_metrics.json') -Raw -Encoding UTF8|ConvertFrom-Json
[ordered]@{schema_version=1;role='rf_continuous_shield_3d_paired_field_summary';status='success';comparison_kind=$ComparisonKind;acceptance_decision=$metrics.acceptance_decision}|ConvertTo-Json|Set-Content $summary -Encoding UTF8
$outputs=@((Join-Path $resultDir 'rf_continuous_shield_3d_paired_field_comparison.csv'),(Join-Path $resultDir 'rf_continuous_shield_3d_paired_field_metrics.json'),$summary)
$args=@($manifestWriter,'--run-config',$runConfig,'--status','success','--software','Python 3.11');foreach($output in $outputs){$args+=@('--output',$output)};& $python @args
if($LASTEXITCODE -ne 0){throw 'Final manifest failed.'}
Write-Output "STATUS=PASS RUN_ID=$RunId ACCEPTANCE_DECISION=$($metrics.acceptance_decision)"
