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
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$sourceManifest = Get-Content -LiteralPath (Join-Path $source 'run_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceReport = Join-Path $source 'logs\comsol_joint_field.txt'
if ($sourceManifest.status -ne 'failed' -or -not ((Get-Content -LiteralPath $sourceReport -Raw -Encoding UTF8) -match '(?m)^STATUS=PASS$')) {
  throw 'Reanalysis requires a solver-success run that failed only after COMSOL returned.'
}
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir | Out-Null
$events = Join-Path $inputDir 's1_physical_port_particles.csv'
$canonical = Join-Path $inputDir 'canonical_rf_exit_at_oatof_entry.csv'
$analyzer = Join-Path $inputDir 'analyze_s1_physical_port_particles.py'
Copy-Item -LiteralPath (Join-Path $source 'results\s1_physical_port_particles.csv') -Destination $events
Copy-Item -LiteralPath (Join-Path $source 'inputs\canonical_rf_exit_at_oatof_entry.csv') -Destination $canonical
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\analyze_s1_physical_port_particles.py') -Destination $analyzer
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$metrics = Join-Path $resultDir 's1_physical_port_metrics.json'
$figure = Join-Path $resultDir 's1_physical_port_entry.png'
& $python $analyzer --events $events --canonical $canonical --center-z-mm -18.42918680341103 --output $metrics --figure $figure
if ($LASTEXITCODE -ne 0) { throw 'S1 physical-port reanalysis failed.' }
$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='s1_physical_port_analysis_only';project_root=$repoRoot;inputs=[ordered]@{source_run_manifest=(Join-Path $source 'run_manifest.json');source_solver_report=$sourceReport;events=$events;canonical=$canonical;analyzer=$analyzer};parameters=[ordered]@{solver_rerun=$false;source_run_id=$SourceRunId;boolean_csv_fix='accept MATLAB 0/1'};formal_gate_passed=$false} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
$result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
[ordered]@{schema_version=1;role='s1_physical_port_analysis_only_summary';status='success';candidate_decision=$result.status;source_solver_status='PASS';geometric_port_accepted=$result.geometric_port_accepted;local_joint_exit=$result.local_joint_exit;physical_link_claim_allowed=$false;resolution_claim_allowed=$false} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary -Encoding UTF8
$writer = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
& $python $writer --run-config $runConfig --status success --software 'Python 3.11' --output $metrics --output $figure --output $summary
if ($LASTEXITCODE -ne 0) { throw 'S1 reanalysis manifest failed.' }
Write-Output "S1_PHYSICAL_PORT_REANALYSIS=PASS RUN_ID=$RunId LOCAL_EXIT=$($result.local_joint_exit)/100"
