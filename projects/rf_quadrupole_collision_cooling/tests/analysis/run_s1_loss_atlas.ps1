[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$SourceRunId,
  [Parameter(Mandatory = $true)][string]$RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$source = Join-Path $artifactRoot "runs\$SourceRunId"
$sourceManifestPath = Join-Path $source 'run_manifest.json'
$sourceManifest = Get-Content -LiteralPath $sourceManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sourceManifest.status -ne 'success' -or $sourceManifest.mode -ne 'rf_oatof_s1_physical_end_to_end') {
  throw 'Loss atlas requires a successful S1 physical end-to-end source run.'
}
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir | Out-Null
$inputMap = [ordered]@{}
foreach ($item in @(
  @{Key='entry';Source='inputs\canonical_rf_exit_at_oatof_entry.csv';Name='canonical_rf_exit_at_oatof_entry.csv'},
  @{Key='local';Source='inputs\s1_physical_port_particles.csv';Name='s1_physical_port_particles.csv'},
  @{Key='row_map';Source='inputs\row_map.csv';Name='row_map.csv'},
  @{Key='simion_log';Source='logs\simion.stdout.log';Name='simion.stdout.log'}
)) {
  $destination = Join-Path $inputDir $item.Name
  Copy-Item -LiteralPath (Join-Path $source $item.Source) -Destination $destination
  $inputMap[$item.Key] = $destination
}
$plotter = Join-Path $inputDir 'plot_s1_loss_atlas.py'
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\plot_s1_loss_atlas.py') -Destination $plotter
$inputMap.plotter = $plotter; $inputMap.source_run_manifest = $sourceManifestPath
$figure = Join-Path $resultDir 's1_end_to_end_loss_atlas.png'
$atlasSummary = Join-Path $resultDir 's1_loss_atlas_summary.json'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python $plotter --entry $inputMap.entry --local $inputMap.local --row-map $inputMap.row_map `
  --simion-log $inputMap.simion_log --output $figure --summary $atlasSummary
if ($LASTEXITCODE -ne 0) { throw 'S1 loss-atlas generation failed.' }
$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_oatof_s1_loss_atlas';project_root=$repoRoot;inputs=$inputMap;parameters=[ordered]@{source_run_id=$SourceRunId;solver_rerun=$false;dense_trajectories_used=$false};formal_gate_passed=$false} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_oatof_s1_loss_atlas_run_summary';status='success';figure='results/s1_end_to_end_loss_atlas.png';source_run_id=$SourceRunId} | ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
$writer = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
& $python $writer --run-config $runConfig --status success --software 'Python 3.11' --output $figure --output $atlasSummary --output $summary
if ($LASTEXITCODE -ne 0) { throw 'S1 loss-atlas manifest failed.' }
Write-Output "S1_LOSS_ATLAS_RUN=PASS RUN_ID=$RunId"
