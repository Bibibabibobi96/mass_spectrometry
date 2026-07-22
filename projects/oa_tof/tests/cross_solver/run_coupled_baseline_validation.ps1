param(
  [Parameter(Mandatory = $true)][string]$CandidateRunRoot,
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__cross__coupled-baseline-validation__n1000'),
  [int]$BootstrapResamples = 5000,
  [int]$BootstrapSeed = 20260720,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$candidateRoot = (Resolve-Path -LiteralPath $CandidateRunRoot).Path
$candidateSummary = Get-Content (Join-Path $candidateRoot 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($candidateSummary.status -ne 'success' -or $candidateSummary.candidate_decision -ne 'candidate_accepted_not_promoted') {
  throw 'Candidate source run has not passed the isolated N=100 workflow.'
}

$runDir = Join-Path $artifactRoot "runs\$RunId"
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
if (Test-Path -LiteralPath $runDir) { throw "Validation run already exists: $RunId" }
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
New-Item -ItemType Directory -Path $runDir,$resultDir,$logDir | Out-Null

$candidateBaseline = Join-Path $candidateRoot 'inputs\candidate_baseline.json'
$candidateMph = Join-Path $candidateRoot 'comsol\oa_tof__candidate.mph'
$candidateSimion = Join-Path $candidateRoot 'simion'
$candidateIon = Join-Path $candidateSimion 'oatof_comsol_524amu_gaussian_N1000.ion'
$candidateIob = Join-Path $candidateSimion 'oatof_ideal_grounded.iob'
$formalValidationPath = Join-Path $projectRoot 'config\formal_validation.json'
$formalValidation = Get-Content $formalValidationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$formalComsolCsv = Join-Path $artifactRoot $formalValidation.comsol.particle_csv_artifact_relative_path
$formalSimionCsv = Join-Path $artifactRoot $formalValidation.simion.particle_csv_artifact_relative_path
foreach ($path in @($candidateBaseline,$candidateMph,$candidateIon,$candidateIob,$formalComsolCsv,$formalSimionCsv,$python,$SimionExe)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}

$newComsolCsv = Join-Path $resultDir 'new_baseline_comsol_particles.csv'
$newComsolReport = Join-Path $logDir 'new_baseline_comsol_report.txt'
$newSimionLog = Join-Path $logDir 'new_baseline_simion_stdout.log'
$newSimionStderr = Join-Path $logDir 'new_baseline_simion_stderr.log'
$newSimionCsv = Join-Path $resultDir 'new_baseline_simion_particles.csv'
$newSimionSummary = Join-Path $resultDir 'new_baseline_simion_summary.json'

$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{
  schema_version=1; run_id=$RunId; project='oa_tof'; mode='coupled_baseline_validation'
  project_root=$projectRoot; formal_gate_passed=$false; promotion_authorized=$false
  inputs=[ordered]@{
    candidate_baseline=$candidateBaseline
    candidate_mph=$candidateMph; candidate_ion_table=$candidateIon; candidate_simion_iob=$candidateIob
    old_baseline_comsol_particles=$formalComsolCsv; old_baseline_simion_particles=$formalSimionCsv
  }
  parameters=[ordered]@{
    mass_to_charge_Th=524; particles=1000
    bootstrap_resamples=$BootstrapResamples; bootstrap_seed=$BootstrapSeed
  }
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8

$oldEnvironment = @{}
$environment = @{
  OATOF_SOURCE_MODEL_PATH=$candidateMph; OATOF_ION_TABLE=$candidateIon
  OATOF_COMSOL_OUTPUT_CSV=$newComsolCsv; OATOF_RUNTIME_DIR=$resultDir; OATOF_RESULTS_DIR=$resultDir
  OATOF_ACCELERATOR_HMAX_MM='1'; OATOF_REUSE_EXISTING_FIELD='1'; OATOF_FINE_TSTEP_NS='0.2'
  OATOF_DRIFT_TSTEP_NS='50'; OATOF_SEGMENTED_OUTPUT='1'; OATOF_USE_PARTICLE_STOP_TIME='0'
}
try {
  foreach ($entry in $environment.GetEnumerator()) {
    $oldEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
  }
  & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
    -TaskScript (Join-Path $projectRoot 'tests\comsol\test_accelerator_mesh_particle_candidate.m') `
    -ReportPath $newComsolReport
} finally {
  foreach ($entry in $environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $oldEnvironment[$entry.Key], 'Process')
  }
}
if (-not (Select-String -LiteralPath $newComsolReport -Pattern '^DETECTED=1000/1000$' -Quiet)) {
  throw 'New-baseline COMSOL did not detect 1000/1000 particles.'
}

$process = Start-Process -FilePath $SimionExe -WorkingDirectory $candidateSimion -WindowStyle Hidden -Wait -PassThru `
  -RedirectStandardOutput $newSimionLog -RedirectStandardError $newSimionStderr -ArgumentList @(
    '--default-num-particles','1000','--nogui','fly','--trajectory-quality','8',
    '--retain-trajectories','0','--particles',$candidateIon,'--programs','1',
    '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',$candidateIob)
if ($process.ExitCode -ne 0) { throw "New-baseline SIMION fly failed: $newSimionStderr" }
$simionSummary = & (Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1') `
  -Log $newSimionLog -IonFile $candidateIon -Mode 'coupled_baseline_candidate' `
  -Distribution 'fixedN1000' -ParticleCsv $newSimionCsv
$simionSummary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $newSimionSummary -Encoding UTF8
if ([int]$simionSummary.Hit -ne 1000) { throw "New-baseline SIMION hit count is $($simionSummary.Hit)/1000" }

function Invoke-PairedComparison([string]$Left, [string]$Right, [string]$Output, [string]$LeftLabel, [string]$RightLabel) {
  & $python -m projects.oa_tof.analysis.reference_analysis compare $Left $Right --mass 524 --output $Output `
    --left-label $LeftLabel --right-label $RightLabel --require-paired-particle-ids `
    --bootstrap-resamples $BootstrapResamples --bootstrap-seed $BootstrapSeed
  if ($LASTEXITCODE -ne 0) { throw "Paired comparison failed: $LeftLabel versus $RightLabel" }
}
Invoke-PairedComparison $newComsolCsv $newSimionCsv (Join-Path $resultDir 'new_baseline_cross_solver') 'COMSOL_NEW' 'SIMION_NEW'
Invoke-PairedComparison $formalComsolCsv $newComsolCsv (Join-Path $resultDir 'old_vs_new_comsol') 'COMSOL_OLD' 'COMSOL_NEW'
Invoke-PairedComparison $formalSimionCsv $newSimionCsv (Join-Path $resultDir 'old_vs_new_simion') 'SIMION_OLD' 'SIMION_NEW'

$theoryValidator = Join-Path $projectRoot 'analysis\validate_longitudinal_prediction.py'
& $python $theoryValidator --baseline (Join-Path $projectRoot 'config\baseline.json') `
  --comsol-csv $formalComsolCsv --simion-csv $formalSimionCsv `
  --output (Join-Path $resultDir 'old_theory_vs_old_baseline.json') | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Old-theory/old-baseline validation failed.' }
& $python $theoryValidator --baseline $candidateBaseline `
  --comsol-csv $newComsolCsv --simion-csv $newSimionCsv `
  --output (Join-Path $resultDir 'new_theory_vs_new_baseline.json') | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'New-theory/new-baseline validation failed.' }

$summaryPath = Join-Path $runDir 'summary.json'
[ordered]@{
  schema_version=1; role='oa_tof_coupled_baseline_validation_summary'; status='success'
  particles=1000; formal_modified=$false; promotion_authorized=$false
  comparisons=[ordered]@{
    old_theory_vs_old_baseline='results/old_theory_vs_old_baseline.json'
    new_theory_vs_new_baseline='results/new_theory_vs_new_baseline.json'
    old_vs_new_comsol='results/old_vs_new_comsol/comparison_metrics.json'
    old_vs_new_simion='results/old_vs_new_simion/comparison_metrics.json'
    new_baseline_cross_solver='results/new_baseline_cross_solver/comparison_metrics.json'
  }
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

$manifestArgs = @(
  (Join-Path $repoRoot 'common\contracts\write_run_manifest.py'), '--run-config', $runConfig,
  '--manifest', (Join-Path $runDir 'run_manifest.json'), '--status', 'success',
  '--software', 'COMSOL R2025b', '--software', 'SIMION 2020',
  '--output', $newComsolCsv, '--output', $newComsolReport, '--output', $newSimionCsv,
  '--output', $newSimionSummary, '--output', (Join-Path $resultDir 'old_theory_vs_old_baseline.json'),
  '--output', (Join-Path $resultDir 'new_theory_vs_new_baseline.json'),
  '--output', (Join-Path $resultDir 'old_vs_new_comsol\comparison_metrics.json'),
  '--output', (Join-Path $resultDir 'old_vs_new_simion\comparison_metrics.json'),
  '--output', (Join-Path $resultDir 'new_baseline_cross_solver\comparison_metrics.json'),
  '--output', $summaryPath
)
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Candidate validation manifest creation failed.' }
Write-Output "COUPLED_BASELINE_VALIDATION=PASS RUN_ID=$RunId"
