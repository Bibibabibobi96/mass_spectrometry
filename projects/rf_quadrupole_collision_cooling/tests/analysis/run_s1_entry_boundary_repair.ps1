[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$SourceRunId,
  [Parameter(Mandatory = $true)][string]$LegacyRunId,
  [Parameter(Mandatory = $true)][string]$RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$source = Join-Path $artifactRoot "runs\$SourceRunId"
$legacy = Join-Path $artifactRoot "runs\$LegacyRunId"
$sourceManifest = Join-Path $source 'run_manifest.json'
$legacyManifest = Join-Path $legacy 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $sourceManifest --require-status success
if ($LASTEXITCODE -ne 0) { throw 'RF source manifest verification failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $legacyManifest --require-status success
if ($LASTEXITCODE -ne 0) { throw 'Legacy S1 manifest verification failed.' }

$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run directory already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir | Out-Null
$builder = Join-Path $inputDir 'rebuild_s1_entry_boundary.py'
$handoffBuilder = Join-Path $inputDir 'build_oatof_handoff.py'
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\rebuild_s1_entry_boundary.py') -Destination $builder
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\build_oatof_handoff.py') -Destination $handoffBuilder
$canonical = Join-Path $resultDir 'canonical_rf_exit_at_physical_oatof_entry.csv'
$ion = Join-Path $resultDir 'rf_exit_at_physical_oatof_entry.ion'
$rowMap = Join-Path $resultDir 'row_map.csv'
$metadata = Join-Path $resultDir 'handoff_metadata.json'
$repair = Join-Path $resultDir 'entry_boundary_repair.json'
& $python $builder `
  --source-csv (Join-Path $source 'results\rf_hybrid_mesh_n100_events.csv') `
  --source-manifest $sourceManifest `
  --project-root $projectRoot `
  --handoff-contract (Join-Path $projectRoot 'config\rf_to_oatof_handoff.json') `
  --joint-contract (Join-Path $projectRoot 'config\rf_to_oatof_s1_joint_field.json') `
  --canonical-output $canonical --ion-output $ion --row-map-output $rowMap `
  --metadata-output $metadata --summary-output $repair `
  --legacy-canonical (Join-Path $legacy 'inputs\canonical_rf_exit_at_oatof_entry.csv')
if ($LASTEXITCODE -ne 0) { throw 'S1 physical entry boundary repair failed.' }
$repairResult = Get-Content -LiteralPath $repair -Raw -Encoding UTF8 | ConvertFrom-Json

$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_oatof_s1_entry_boundary_repair';project_root=$repoRoot;inputs=[ordered]@{source_run_manifest=$sourceManifest;legacy_run_manifest=$legacyManifest;handoff_contract=(Join-Path $projectRoot 'config\rf_to_oatof_handoff.json');joint_contract=(Join-Path $projectRoot 'config\rf_to_oatof_s1_joint_field.json');builder=$builder;handoff_builder=$handoffBuilder};parameters=[ordered]@{solver_rerun=$false;particles=$repairResult.particles;physical_entry_surface_x_mm=$repairResult.physical_entry_surface_x_mm;numerical_release_offset_inside_surface_mm=$repairResult.numerical_release_offset_inside_surface_mm};formal_gate_passed=$false} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_oatof_s1_entry_boundary_repair_summary';status='success';candidate_decision=$repairResult.status;particles=$repairResult.particles;frame_id=$repairResult.frame_id;physical_entry_surface_x_mm=$repairResult.physical_entry_surface_x_mm;maximum_entry_surface_residual_mm=$repairResult.maximum_entry_surface_residual_mm;numerical_release_offset_inside_surface_mm=$repairResult.numerical_release_offset_inside_surface_mm;comparison_to_legacy_projection=$repairResult.comparison_to_legacy_projection;solver_rerun=$false;historical_physical_trajectory_invalidated=$false;formal_gate_passed=$false} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $summary -Encoding UTF8
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
  --run-config $runConfig --status success --software 'Python 3.11' `
  --output $canonical --output $ion --output $rowMap --output $metadata --output $repair --output $summary
if ($LASTEXITCODE -ne 0) { throw 'S1 entry repair manifest failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') (Join-Path $runDir 'run_manifest.json') --require-status success
if ($LASTEXITCODE -ne 0) { throw 'S1 entry repair manifest verification failed.' }
Write-Output "S1_ENTRY_BOUNDARY_REPAIR_RUN=PASS RUN_ID=$RunId PARTICLES=$($repairResult.particles)"
