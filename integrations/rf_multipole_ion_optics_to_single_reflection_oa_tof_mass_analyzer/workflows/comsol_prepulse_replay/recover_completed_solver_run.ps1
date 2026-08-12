[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$SourceRunId,
  [ValidateSet('prepulse_replay','voltage_ab')][string]$RecoveryKind='prepulse_replay'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workflowRoot = $PSScriptRoot
$integrationRoot = (Resolve-Path (Join-Path $workflowRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$artifactRoot = Join-Path $workspaceRoot `
  'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
$sourceRoot = Join-Path $artifactRoot "runs\$SourceRunId"
$sourceManifest = Join-Path $sourceRoot 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  $sourceManifest --require-status failed --require-local-run-config `
  --require-run-id $SourceRunId --require-project single_reflection_oa_tof_mass_analyzer
if ($LASTEXITCODE -ne 0) { throw 'Recovery source run is not a verified failed run.' }
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw 'Recovery RunId is invalid.' }

$sourceLayout = switch ($RecoveryKind) {
  'prepulse_replay' { @{ report='logs\comsol_replay.txt'; model='models\rf_prepulse_complete_oatof.mph' } }
  'voltage_ab' { @{ report='logs\comsol_voltage_ab.txt'; model='models\rf_prepulse_voltage_ab.mph' } }
}
$sourceReport = Join-Path $sourceRoot $sourceLayout.report
$sourceModel = Join-Path $sourceRoot $sourceLayout.model
$sourceParticles = Join-Path $sourceRoot 'results\comsol_particles.csv'
$sourceCensus = Join-Path $sourceRoot 'results\comsol_particle_census.csv'
$sourceConfig = Join-Path $sourceRoot 'run_config.json'
foreach ($path in @($sourceReport,$sourceModel,$sourceParticles,$sourceCensus,$sourceConfig)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Completed solver recovery input is absent: $path"
  }
}
if (-not (Select-String -LiteralPath $sourceReport -Pattern '^STATUS=PASS$' -Quiet)) {
  throw 'Recovery source does not prove that the COMSOL solver stage passed.'
}

$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Recovery run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$analysisDir = Join-Path $resultDir 'resolution'
New-Item -ItemType Directory -Path $inputDir,$analysisDir | Out-Null
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$manifestCopy = Copy-VerifiedRunInput -Source $sourceManifest `
  -Destination (Join-Path $inputDir 'source_run_manifest.json')
$configCopy = Copy-VerifiedRunInput -Source $sourceConfig `
  -Destination (Join-Path $inputDir 'source_run_config.json')
$modelCopy = Copy-VerifiedRunInput -Source $sourceModel `
  -Destination (Join-Path $inputDir 'completed_solver_model.mph')
$particlesCopy = Copy-VerifiedRunInput -Source $sourceParticles `
  -Destination (Join-Path $inputDir 'completed_solver_particles.csv')
$censusCopy = Copy-VerifiedRunInput -Source $sourceCensus `
  -Destination (Join-Path $inputDir 'completed_solver_census.csv')
$reportCopy = Copy-VerifiedRunInput -Source $sourceReport `
  -Destination (Join-Path $inputDir 'completed_solver_report.txt')
$runConfig = Join-Path $runDir 'run_config.json'
$summary = Join-Path $runDir 'summary.json'
[ordered]@{
  schema_version=1; run_id=$RunId; project='single_reflection_oa_tof_mass_analyzer'
  mode='rf_oatof_comsol_prepulse_completed_solver_recovery'; project_root=$repoRoot
  inputs=[ordered]@{
    source_run_manifest=$manifestCopy; source_run_config=$configCopy
    completed_solver_model=$modelCopy; completed_solver_particles=$particlesCopy
    completed_solver_census=$censusCopy; completed_solver_report=$reportCopy
  }
  parameters=[ordered]@{
    source_run_id=$SourceRunId; recovery_kind=$RecoveryKind
    recovery_scope='postprocess_completed_solver_outputs'
    solver_reexecuted=$false; mass_amu=100.0
  }
  formal_gate_passed=$false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8

try {
  & $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.reference_analysis `
    single $particlesCopy --mass 100 --output $analysisDir `
    --label COMSOL-pre-pulse-replay-frame-fixed
  if ($LASTEXITCODE -ne 0) { throw 'Recovered unified resolution analysis failed.' }
  $metrics = Get-Content -LiteralPath (Join-Path $analysisDir 'metrics.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $censusRows = Import-Csv -LiteralPath $censusCopy
  $detected = @($censusRows | Where-Object { $_.hit -eq '1' }).Count
  [ordered]@{
    schema_version=1; role='rf_oatof_comsol_completed_solver_recovery_summary'
    status='success'; source_run_id=$SourceRunId; recovery_kind=$RecoveryKind
    particles=$censusRows.Count
    detected=$detected; mass_resolution=[double]$metrics.metrics.mass_resolution
    direct_fwhm_tof_ns=[double]$metrics.metrics.direct_fwhm_tof_ns
    std_tof_ns=[double]$metrics.metrics.std_tof_ns
    mean_tof_us=[double]$metrics.metrics.mean_tof_us
    solver_reexecuted=$false
    claim_class='CONTROLLED_CROSS_SOLVER_DIAGNOSTIC_ONLY'; formal_gate_passed=$false
  } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary -Encoding UTF8
  $outputs = @($summary) + @(
    Get-ChildItem -LiteralPath $analysisDir -File | Select-Object -ExpandProperty FullName
  )
  $arguments = @(
    (Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),
    '--run-config',$runConfig,'--status','success','--software','Python 3.11'
  )
  foreach ($output in $outputs) { $arguments += @('--output',$output) }
  & $python @arguments
  if ($LASTEXITCODE -ne 0) { throw 'Recovered run manifest creation failed.' }
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    (Join-Path $runDir 'run_manifest.json') --require-status success `
    --require-local-run-config
  if ($LASTEXITCODE -ne 0) { throw 'Recovered run manifest verification failed.' }
  Write-Output "COMSOL_PREPULSE_RECOVERY=PASS RUN_ID=$RunId R=$($metrics.metrics.mass_resolution)"
} catch {
  [ordered]@{
    schema_version=1; role='rf_oatof_comsol_completed_solver_recovery_summary'
    status='failed'; reason=$_.Exception.Message
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $summary -Encoding UTF8
  & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') `
    --run-config $runConfig --status failed --software 'Python 3.11' --output $summary
  throw
}
