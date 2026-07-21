param(
  [Parameter(Mandatory=$true)][string]$Reference2DRunId,
  [Parameter(Mandatory=$true)][string]$Layers20RunId,
  [Parameter(Mandatory=$true)][string]$Layers40RunId,
  [Parameter(Mandatory=$true)][string]$LocalizedRunId,
  [string]$RunId=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactRoot=Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$runsRoot=Join-Path $artifactRoot 'runs'
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
$sourceIds=@($Reference2DRunId,$Layers20RunId,$Layers40RunId,$LocalizedRunId)
foreach($sourceId in $sourceIds){& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $sourceId;if($LASTEXITCODE -ne 0){throw "Invalid source run_id: $sourceId"}}
$sourceDirs=@($sourceIds|ForEach-Object{Join-Path $runsRoot $_})
$manifests=@($sourceDirs|ForEach-Object{Join-Path $_ 'run_manifest.json'})
foreach($manifestPath in $manifests){if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){throw "Source manifest missing: $manifestPath"};$manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json;if($manifest.status -ne 'success'){throw "Source run is not successful: $manifestPath"}}
$reference2D=Join-Path $sourceDirs[0] 'results\rf_continuous_shield_2d_samples.csv'
$layers20=Join-Path $sourceDirs[1] 'results\rf_rod_region_swept_field_samples.csv'
$layers40=Join-Path $sourceDirs[2] 'results\rf_rod_region_swept_field_samples.csv'
$localized=Join-Path $sourceDirs[3] 'results\rf_rod_region_swept_field_samples.csv'
$referenceLog=Join-Path $sourceDirs[2] 'logs\comsol_rf_rod_region_swept_mesh.txt'
$localizedLog=Join-Path $sourceDirs[3] 'logs\comsol_rf_rod_region_swept_mesh.txt'
foreach($path in @($reference2D,$layers20,$layers40,$localized,$referenceLog,$localizedLog)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Source evidence missing: $path"}}
function Read-ElementCount([string]$Path){$line=Get-Content -LiteralPath $Path -Encoding UTF8|Where-Object{$_ -match '^MESH_TOTAL_ELEMENTS='}|Select-Object -Last 1;if(-not $line){throw "Element count missing: $Path"};return [int]($line-split '=',2)[1]}
$referenceElements=Read-ElementCount $referenceLog;$localizedElements=Read-ElementCount $localizedLog
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__rf-swept-mesh-convergence'}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId;if($LASTEXITCODE -ne 0){throw "Invalid run_id: $RunId"}
$runDir=Join-Path $runsRoot $RunId;if(Test-Path -LiteralPath $runDir){throw "Run already exists: $runDir"}
$inputDir=Join-Path $runDir 'inputs';$resultDir=Join-Path $runDir 'results';New-Item -ItemType Directory -Force -Path $inputDir,$resultDir|Out-Null
$analysis=Join-Path $inputDir 'compare_rf_rod_region_swept_mesh.py';$contract=Join-Path $inputDir 'rf_rod_region_swept_mesh_candidate.json';$runner=Join-Path $inputDir 'run_rf_rod_region_swept_mesh_comparison.ps1.txt'
Copy-Item (Join-Path $projectRoot 'analysis\compare_rf_rod_region_swept_mesh.py') $analysis;Copy-Item (Join-Path $projectRoot 'config\rf_rod_region_swept_mesh_candidate.json') $contract;Copy-Item $PSCommandPath $runner
$metrics=Join-Path $resultDir 'rf_rod_region_swept_mesh_convergence.json';$summary=Join-Path $runDir 'summary.json';$runConfig=Join-Path $runDir 'run_config.json';$manifestWriter=Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_uniform_rod_region_swept_mesh_convergence';project_root=$repoRoot;inputs=[ordered]@{analysis=$analysis;contract=$contract;runner=$runner;source_manifests=$manifests;reference_2d=$reference2D;layers_20=$layers20;layers_40=$layers40;localized_candidate=$localized};parameters=[ordered]@{localized_core_radius_mm=8.0;localized_outer_hmax_mm=1.0;reference_elements=$referenceElements;localized_elements=$localizedElements;particle_tracking=$false};formal_gate_passed=$false}|ConvertTo-Json -Depth 7|Set-Content $runConfig -Encoding UTF8
[ordered]@{schema_version=1;role='rf_rod_region_swept_mesh_convergence_summary';status='interrupted'}|ConvertTo-Json|Set-Content $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'Python 3.11';if($LASTEXITCODE -ne 0){throw 'Initial manifest failed.'}
try{& $python $analysis --reference-2d $reference2D --layers-20 $layers20 --layers-40 $layers40 --localized $localized --localized-core-radius-mm 8 --localized-outer-hmax-mm 1 --reference-elements $referenceElements --localized-elements $localizedElements --contract $contract --output $metrics;if($LASTEXITCODE -ne 0){throw 'Swept mesh comparison failed.'}}catch{[ordered]@{schema_version=1;role='rf_rod_region_swept_mesh_convergence_summary';status='failed';reason=$_.Exception.Message}|ConvertTo-Json|Set-Content $summary -Encoding UTF8;& $python $manifestWriter --run-config $runConfig --status failed --software 'Python 3.11';throw}
$report=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
[ordered]@{schema_version=1;role='rf_rod_region_swept_mesh_convergence_summary';status='success';decision=$report.status;selected_uniform_region_mesh=$report.selected_uniform_region_mesh;hybrid_integration_allowed=($report.status -eq 'PASS')}|ConvertTo-Json -Depth 5|Set-Content $summary -Encoding UTF8
$args=@($manifestWriter,'--run-config',$runConfig,'--status','success','--software','Python 3.11','--output',$metrics,'--output',$summary);& $python @args;if($LASTEXITCODE -ne 0){throw 'Final manifest failed.'}
Write-Output "STATUS=PASS RUN_ID=$RunId DECISION=$($report.status)"
