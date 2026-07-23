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
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$source = Join-Path $artifactRoot "runs\$SourceRunId"
$sourceManifestPath = Join-Path $source 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  $sourceManifestPath --require-status success
if ($LASTEXITCODE -ne 0) { throw 'S1 source manifest verification failed.' }
$sourceConfigPath = Join-Path $source 'run_config.json'
$sourceConfig = Get-Content -LiteralPath $sourceConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sourceConfig.mode -ne 'rf_oatof_s1_physical_end_to_end') {
  throw 'State-chain audit requires an S1 physical end-to-end source run.'
}
$upstreamManifestPath = [string]$sourceConfig.inputs.source_run_manifest
$upstreamConfigPath = Join-Path (Split-Path -Parent $upstreamManifestPath) 'run_config.json'

$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run directory already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir | Out-Null
$auditor = Join-Path $inputDir 'audit_s1_state_chain.py'
$handoffAdapter = Join-Path $inputDir 'rf_handoff_adapter.py'
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\audit_s1_state_chain.py') -Destination $auditor
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\analysis\rf_handoff_adapter.py') -Destination $handoffAdapter
$audit = Join-Path $resultDir 's1_state_chain_audit.json'
& $python $auditor `
  --entry (Join-Path $source 'inputs\canonical_rf_exit_at_oatof_entry.csv') `
  --local-events (Join-Path $source 'inputs\s1_physical_port_particles.csv') `
  --canonical (Join-Path $source 'inputs\canonical_local_joint_exit.csv') `
  --ion (Join-Path $source 'inputs\local_joint_exit_instrument_clock.ion') `
  --row-map (Join-Path $source 'inputs\row_map.csv') `
  --downstream (Join-Path $source 'results\simion_downstream_particles.csv') `
  --handoff-metadata (Join-Path $source 'inputs\handoff_metadata.json') `
  --run-config $sourceConfigPath --source-run-config $upstreamConfigPath `
  --simion-stdout (Join-Path $source 'logs\simion.stdout.log') --output $audit
if ($LASTEXITCODE -ne 0) { throw 'S1 state-chain physics audit failed.' }
$auditResult = Get-Content -LiteralPath $audit -Raw -Encoding UTF8 | ConvertFrom-Json

$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_oatof_s1_state_chain_audit';project_root=$repoRoot;inputs=[ordered]@{source_run_manifest=$sourceManifestPath;auditor=$auditor;oa_shared_handoff_adapter=$handoffAdapter};parameters=[ordered]@{solver_rerun=$false;particles=$auditResult.particles;authoritative_frame_id=$auditResult.coordinate_chain.authoritative_frame_id;dense_trajectories_saved=$false};formal_gate_passed=$false} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_oatof_s1_state_chain_audit_summary';status='success';candidate_decision=$auditResult.status;particles=$auditResult.particles;coordinate_chain=$auditResult.coordinate_chain;identity_and_time=$auditResult.identity_and_time;pulse_continuation=$auditResult.pulse_continuation;physical_link_claim_allowed=$false;numerical_convergence_claim_allowed=$false;resolution_claim_allowed=$false} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $summary -Encoding UTF8
$writer = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
& $python $writer --run-config $runConfig --status success --software 'Python 3.11' `
  --output $audit --output $summary
if ($LASTEXITCODE -ne 0) { throw 'S1 state-chain audit manifest failed.' }
Write-Output "S1_STATE_CHAIN_AUDIT_RUN=PASS RUN_ID=$RunId PARTICLES=$($auditResult.particles)"
