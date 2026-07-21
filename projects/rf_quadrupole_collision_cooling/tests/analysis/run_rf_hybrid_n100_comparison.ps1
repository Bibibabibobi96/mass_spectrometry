param(
  [Parameter(Mandatory=$true)][string]$CoarseRunId,
  [Parameter(Mandatory=$true)][string]$FineRunId,
  [string]$RunId=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$runsRoot=Join-Path (Split-Path -Parent $repoRoot) 'artifacts\projects\rf_quadrupole_collision_cooling\runs'
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
foreach($id in @($CoarseRunId,$FineRunId)){& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $id;if($LASTEXITCODE-ne 0){throw "Invalid source run: $id"}}
$coarseDir=Join-Path $runsRoot $CoarseRunId
$fineDir=Join-Path $runsRoot $FineRunId
$coarseEvents=Join-Path $coarseDir 'results\rf_hybrid_mesh_n100_events.csv'
$fineEvents=Join-Path $fineDir 'results\rf_hybrid_mesh_n100_events.csv'
$sourceManifests=@((Join-Path $coarseDir 'run_manifest.json'),(Join-Path $fineDir 'run_manifest.json'))
foreach($path in @($coarseEvents,$fineEvents)+$sourceManifests){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Source evidence missing: $path"}}
foreach($path in $sourceManifests){$source=Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json;if($source.status-ne'success'-or$source.mode-ne'rf_full_device_hybrid_mesh_n100_functional_arbitration'){throw "Source is not a successful hybrid N=100 run: $path"}}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__rf-hybrid-n100-functional-arbitration'}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if($LASTEXITCODE-ne 0){throw "Invalid run id: $RunId"}
$runDir=Join-Path $runsRoot $RunId
if(Test-Path -LiteralPath $runDir){throw "Run exists: $runDir"}
$inputDir=Join-Path $runDir 'inputs';$resultDir=Join-Path $runDir 'results';New-Item -ItemType Directory -Force -Path $inputDir,$resultDir|Out-Null
$analysis=Join-Path $inputDir 'compare_rf_continuous_shield_n100.py';$runner=Join-Path $inputDir 'run_rf_hybrid_n100_comparison.ps1.txt';Copy-Item (Join-Path $projectRoot 'analysis\compare_rf_continuous_shield_n100.py') $analysis;Copy-Item $PSCommandPath $runner
$summary=Join-Path $runDir 'summary.json';$runConfig=Join-Path $runDir 'run_config.json';$writer=Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_full_device_hybrid_mesh_n100_paired_comparison';project_root=$repoRoot;inputs=[ordered]@{analysis=$analysis;runner=$runner;coarse_events=$coarseEvents;fine_events=$fineEvents;source_manifests=$sourceManifests};parameters=[ordered]@{coarse_run_id=$CoarseRunId;fine_run_id=$FineRunId;particle_count=100};formal_gate_passed=$false}|ConvertTo-Json -Depth 6|Set-Content $runConfig -Encoding UTF8
[ordered]@{schema_version=1;role='rf_hybrid_n100_comparison_summary';status='interrupted'}|ConvertTo-Json|Set-Content $summary -Encoding UTF8
& $python $writer --run-config $runConfig --status interrupted --software 'Python 3.11'
$metrics=Join-Path $resultDir 'rf_continuous_shield_n100_comparison_metrics.json'
try{& $python $analysis --candidate $coarseEvents --reference $fineEvents --output-dir $resultDir;if($LASTEXITCODE-ne 0){throw 'Hybrid N=100 comparison failed.'}}catch{[ordered]@{schema_version=1;role='rf_hybrid_n100_comparison_summary';status='failed';reason=$_.Exception.Message}|ConvertTo-Json|Set-Content $summary -Encoding UTF8;& $python $writer --run-config $runConfig --status failed --software 'Python 3.11';throw}
$report=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
[ordered]@{schema_version=1;role='rf_hybrid_n100_comparison_summary';status='success';decision=$report.acceptance_decision;classification_change_count=$report.classification_change_count}|ConvertTo-Json|Set-Content $summary -Encoding UTF8
$outputs=@((Join-Path $resultDir 'rf_continuous_shield_n100_paired_particles.csv'),$metrics,$summary);$args=@($writer,'--run-config',$runConfig,'--status','success','--software','Python 3.11');foreach($output in $outputs){$args+=@('--output',$output)};& $python @args
if($LASTEXITCODE-ne 0){throw 'Final manifest failed.'}
Write-Output "STATUS=PASS RUN_ID=$RunId DECISION=$($report.acceptance_decision) CLASSIFICATION_CHANGES=$($report.classification_change_count)"
