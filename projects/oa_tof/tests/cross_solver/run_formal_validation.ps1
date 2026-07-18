param(
  [string]$RunId = ('current_assets_n1000_' + (Get-Date -Format 'yyyyMMdd')),
  [int]$BootstrapResamples = 5000,
  [int]$BootstrapSeed = 20260718,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$artifactRoot = Join-Path (Split-Path -Parent $repoRoot) 'artifacts\projects\oa_tof'
$runDir = Join-Path $artifactRoot "runs\formal_validation\$RunId"
$resultDir = Join-Path $artifactRoot "results\cross_solver\formal_validation\$RunId"
if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $resultDir)) {
  throw "Formal validation run already exists: $RunId"
}
New-Item -ItemType Directory -Path $runDir,$resultDir | Out-Null

$formalMph = Join-Path $artifactRoot 'models\comsol\formal\MS_oaTOF_TwoStageRingStackReflectron_Final.mph'
$formalSimion = Join-Path $artifactRoot 'models\simion\formal\oatof_524amu'
$ion = Join-Path $formalSimion 'oatof_comsol_524amu_gaussian_N1000.ion'
$iob = Join-Path $formalSimion 'oatof_ideal_grounded.iob'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$comsolCsv = Join-Path $runDir 'comsol_particles.csv'
$comsolReport = Join-Path $runDir 'comsol_report.txt'
$simionLog = Join-Path $runDir 'simion.log'
$simionStderr = Join-Path $runDir 'simion.stderr.log'
$simionCsv = Join-Path $runDir 'simion_particles.csv'
$simionSummary = Join-Path $runDir 'simion_summary.json'
foreach ($path in @($formalMph,$ion,$iob,$python,$SimionExe)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}

$old = @{}
$variables = @{
  OATOF_SOURCE_MODEL_PATH=$formalMph; OATOF_ION_TABLE=$ion; OATOF_COMSOL_OUTPUT_CSV=$comsolCsv
  OATOF_ACCELERATOR_HMAX_MM='1'; OATOF_REUSE_EXISTING_FIELD='1'; OATOF_FINE_TSTEP_NS='0.2'
  OATOF_DRIFT_TSTEP_NS='50'; OATOF_SEGMENTED_OUTPUT='1'; OATOF_USE_PARTICLE_STOP_TIME='0'
}
try {
  foreach ($entry in $variables.GetEnumerator()) {
    $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
    [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
  }
  & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
    -TaskScript (Join-Path $projectRoot 'tests\comsol\test_accelerator_mesh_particle_candidate.m') `
    -ReportPath $comsolReport
} finally {
  foreach ($entry in $variables.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key,$old[$entry.Key],'Process')
  }
}
if (-not (Select-String -LiteralPath $comsolReport -Pattern '^DETECTED=1000/1000$' -Quiet)) {
  throw 'Current formal COMSOL did not detect 1000/1000 particles.'
}

$process = Start-Process -FilePath $SimionExe -WorkingDirectory $formalSimion -WindowStyle Hidden -Wait -PassThru `
  -RedirectStandardOutput $simionLog -RedirectStandardError $simionStderr -ArgumentList @(
    '--default-num-particles','1000','--nogui','fly','--trajectory-quality','8',
    '--retain-trajectories','0','--particles',$ion,'--programs','1',
    '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',$iob)
if ($process.ExitCode -ne 0) { throw "SIMION formal fly failed: $simionStderr" }
$summary = & (Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1') `
  -Log $simionLog -IonFile $ion -Mode 'formal_current_assets' -Distribution 'fixedN1000' -ParticleCsv $simionCsv
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $simionSummary -Encoding UTF8
if ([int]$summary.Hit -ne 1000) { throw "Current formal SIMION hit count is $($summary.Hit)/1000" }

& $python (Join-Path $projectRoot 'analysis\reference_analysis.py') compare $comsolCsv $simionCsv `
  --mass 524 --output $resultDir --left-label COMSOL --right-label SIMION `
  --require-paired-particle-ids --bootstrap-resamples $BootstrapResamples --bootstrap-seed $BootstrapSeed
if ($LASTEXITCODE -ne 0) { throw 'Formal cross-solver analysis failed.' }
$comparison = Join-Path $resultDir 'comparison_metrics.json'
& $python (Join-Path $projectRoot 'analysis\publish_formal_validation.py') --run-id $RunId `
  --comsol-csv $comsolCsv --comsol-report $comsolReport --simion-csv $simionCsv `
  --simion-summary $simionSummary --comparison $comparison
if ($LASTEXITCODE -ne 0) { throw 'Formal validation publication failed.' }
& $python (Join-Path $projectRoot 'analysis\verify_formal_validation.py')
if ($LASTEXITCODE -ne 0) { throw 'Published formal validation did not verify.' }
Write-Output "FORMAL_VALIDATION_RUN=PASS RUN_ID=$RunId"
